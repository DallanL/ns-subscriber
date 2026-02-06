import httpx
import json
import asyncio
from typing import Optional, Any, List, Type, TypeVar, Dict
from fastapi import HTTPException
from models import NSUser, NSSubscription
import logging
from pydantic import BaseModel
from config import settings

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    # Simple token bucket rate limiter for asyncio
    def __init__(self, max_rate: float):
        self.max_rate = max_rate
        self.interval = 1.0 / max_rate if max_rate > 0 else 0
        self.last_check = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self):
        if self.max_rate <= 0:
            return

        async with self.lock:
            now = asyncio.get_event_loop().time()
            target_time = max(now, self.last_check + self.interval)
            wait_time = target_time - now
            self.last_check = target_time

        if wait_time > 0:
            await asyncio.sleep(wait_time)


class NSClient:
    _limiter: Optional[AsyncRateLimiter] = None

    def __init__(
        self,
        token: str,
        client: Optional[httpx.AsyncClient] = None,
    ):
        if NSClient._limiter is None:
            NSClient._limiter = AsyncRateLimiter(
                max_rate=settings.NS_API_MAX_REQUESTS_PER_SECOND
            )

        self.token = token
        self.client = client
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.candidate_urls = []

        if not settings.NS_API_URL:
            raise ValueError("NS_API_URL is not configured.")

        clean_url = settings.NS_API_URL.strip().rstrip("/")
        if not clean_url.startswith("http"):
            clean_url = f"https://{clean_url}"
        if not clean_url.endswith("/ns-api/v2"):
            clean_url += "/ns-api/v2"
        self.candidate_urls.append(clean_url)

        self.call_stats: Dict[str, int] = {}
        self.total_calls = 0

    def _sanitize_log(self, data: Any) -> Any:
        # Mask sensitive fields in logs
        if isinstance(data, dict):
            return {
                k: (
                    "***MASKED***"
                    if k.lower()
                    in (
                        "token",
                        "access_token",
                        "refresh_token",
                        "client_secret",
                        "password",
                    )
                    else self._sanitize_log(v)
                )
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._sanitize_log(item) for item in data]
        return data

    @staticmethod
    async def refresh_oauth_token(refresh_token: str) -> Dict[str, Any]:
        # OAuth2 token refresh
        if NSClient._limiter:
            await NSClient._limiter.acquire()

        if not settings.NS_API_URL:
            raise ValueError("NS_API_URL is not configured.")

        api_url = settings.NS_API_URL
        base_url = api_url.split("/ns-api/")[0]
        token_url = f"{base_url}/ns-api/v2/tokens"

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.NS_CLIENT_ID,
            "client_secret": settings.NS_CLIENT_SECRET,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(token_url, json=payload)
            if response.status_code != 200:
                logger.error(f"Token refresh failed with status {response.status_code}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Token refresh failed",
                )
            return response.json()

    @staticmethod
    async def exchange_auth_code(
        code: str, redirect_uri: str, username: Optional[str] = None
    ) -> Dict[str, Any]:
        # Exchange auth code for tokens
        if NSClient._limiter:
            await NSClient._limiter.acquire()

        if not settings.NS_API_URL:
            raise ValueError("NS_API_URL is not configured.")

        api_url = settings.NS_API_URL
        base_url = api_url.split("/ns-api/")[0]
        token_url = f"{base_url}/ns-api/v2/tokens"

        payload = {
            "grant_type": "authorization_code",
            "client_id": settings.NS_CLIENT_ID,
            "client_secret": settings.NS_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if username:
            payload["username"] = username

        headers = {"Accept": "application/json", "Content-Type": "application/json"}

        # Log redacted payload
        redacted_payload = payload.copy()
        if "client_secret" in redacted_payload:
            redacted_payload["client_secret"] = "***MASKED***"
        if "code" in redacted_payload:
            redacted_payload["code"] = "***MASKED***"
        logger.debug(
            f"Exchange Payload (JSON) to {token_url}: {json.dumps(redacted_payload)}"
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(token_url, json=payload, headers=headers)

            if response.status_code != 200:
                logger.error(f"Token exchange failed. Status: {response.status_code}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Token exchange failed",
                )

            token_data = response.json()

            access_token = token_data.get("access_token")
            if access_token:
                user_url = f"{base_url}/ns-api/v2/domains/~/users/~"
                user_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                }
                user_resp = await client.get(user_url, headers=user_headers)
                if user_resp.status_code == 200:
                    token_data.update(user_resp.json())
                else:
                    logger.warning(
                        f"Failed to fetch user info: {user_resp.status_code} {user_resp.text}"
                    )

            return token_data

    async def _request(
        self, method: str, path: str, model: Optional[Type[T]] = None, **kwargs
    ) -> Any:
        # Core request handler with rate limiting and failover
        import re

        if self._limiter:
            await self._limiter.acquire()

        stat_path = re.sub(r"/[0-9]+", "/{id}", path)
        self.call_stats[stat_path] = self.call_stats.get(stat_path, 0) + 1
        self.total_calls += 1
        exceptions = []

        for base_url in self.candidate_urls:
            url = f"{base_url}{path}"
            logger.debug(f"Attempting API call: {method} {url}")

            try:
                if self.client:
                    response = await self.client.request(
                        method, url, headers=self.headers, **kwargs
                    )
                else:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.request(
                            method, url, headers=self.headers, **kwargs
                        )

                if logger.isEnabledFor(logging.DEBUG):
                    try:
                        resp_json = response.json()
                        sanitized = self._sanitize_log(resp_json)
                        logger.debug(
                            f"Response from {url}:\n{json.dumps(sanitized, indent=2)}"
                        )
                    except Exception:
                        logger.debug(
                            f"Response (Text) from {url}: {response.text[:200]}..."
                        )

                if response.status_code < 500:
                    if response.status_code == 404:
                        logger.info(f"Resource not found (404) at {url}")
                        return None

                if response.status_code >= 400:
                    logger.error(f"API Error {response.status_code} from {url}")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail="API Error",
                    )

                try:
                    data = response.json()
                    if model and isinstance(data, list):
                        return [model.model_validate(item) for item in data]
                    elif model and isinstance(data, dict):
                        return model.model_validate(data)
                    return data
                except Exception as e:
                    logger.error(f"Failed to parse response from {url}: {e}")
                    return None
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as e:
                logger.warning(f"API failover triggered. {base_url} unreachable: {e}")
                exceptions.append(e)
                continue

        logger.error(f"All API endpoints failed. Exceptions: {exceptions}")
        raise HTTPException(status_code=503, detail="Upstream PBX Unreachable")

    async def _get_paginated(
        self,
        path: str,
        model: Type[T],
        limit: int = 1000,
        max_items: int = 10000,
        **kwargs,
    ) -> List[T]:
        # Generic paginated GET handler
        items: List[T] = []
        start = 0
        while True:
            params = {"limit": limit, "start": start}
            params.update(kwargs)

            batch = await self._request("GET", path, model=model, params=params)

            if not batch:
                break

            items.extend(batch)

            if len(items) > max_items:
                raise HTTPException(
                    status_code=413,
                    detail=f"Resource limit exceeded: >{max_items} items found at {path}",
                )

            if len(batch) < limit:
                break

            start += limit

        return items

    async def get_me(self) -> Dict[str, Any]:
        return await self._request("GET", "/domains/~/users/~")

    async def get_current_user(self) -> NSUser:
        data = await self.get_me()
        return NSUser.model_validate(data)

    async def get_users(self, domain: str, **kwargs) -> List[NSUser]:
        return await self._get_paginated(
            f"/domains/{domain}/users", model=NSUser, **kwargs
        )

    async def get_user(self, domain: str, user: str) -> Optional[NSUser]:
        return await self._request(
            "GET", f"/domains/{domain}/users/{user}", model=NSUser
        )

    async def get_subscriptions(self, domain: str, **kwargs) -> List[NSSubscription]:
        kwargs["domain"] = domain
        return await self._get_paginated(
            "/subscriptions", model=NSSubscription, **kwargs
        )

    async def create_subscription(
        self,
        domain: str,
        user: str,
        model: str,
        url: str,
        expires: Optional[int] = None,
        **kwargs,
    ) -> Any:
        payload: Dict[str, Any] = {
            "subscription-geo-support": "yes",
            "user": user,
            "domain": domain,
            "model": model,
            "post-url": url,
        }
        if expires is not None:
            payload["expires"] = expires
        payload.update(kwargs)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Creating Subscription Payload: {json.dumps(payload)}")
        return await self._request("POST", "/subscriptions", json=payload)

    async def delete_subscription(
        self, subscription_id: str, domain: Optional[str] = None
    ) -> Any:
        kwargs = {}
        if domain:
            kwargs["json"] = {"domain": domain}

        return await self._request(
            "DELETE", f"/subscriptions/{subscription_id}", model=None, **kwargs
        )

    async def update_subscription(
        self, subscription_id: str, domain: str, **kwargs
    ) -> Any:
        payload = {"domain": domain}
        payload.update(kwargs)
        return await self._request(
            "PUT", f"/subscriptions/{subscription_id}", json=payload
        )
