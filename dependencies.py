from fastapi import Depends, HTTPException, Header, Request
from ns_client import NSClient
from models import NSUser
from config import settings
from security import is_origin_allowed
import httpx
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


async def verify_origin(request: Request):
    # Validate Origin or Referer against ALLOWED_ORIGINS
    if settings.ALLOWED_ORIGINS == "*":
        return

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    target = origin or referer

    if not target:
        logger.warning(
            f"Request missing Origin/Referer. Headers: {list(request.headers.keys())}"
        )
        raise HTTPException(status_code=403, detail="Origin not allowed")

    if not is_origin_allowed(target, settings.ALLOWED_ORIGINS):
        logger.warning(f"Origin/Referer '{target}' denied.")
        raise HTTPException(status_code=403, detail="Origin not allowed")


async def get_ns_client(
    authorization: str = Header(..., description="Bearer token from Netsapiens portal"),
) -> AsyncGenerator[NSClient, None]:
    # Returns an authenticated NSClient
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Invalid authorization header format"
        )

    token = authorization.split(" ")[1]

    async with httpx.AsyncClient(timeout=10.0, verify=False) as http_client:
        client = NSClient(token, client=http_client)
        yield client


async def get_ns_user(client: NSClient = Depends(get_ns_client)) -> NSUser:
    # Resolves and returns current NSUser
    try:
        return await client.get_current_user()
    except HTTPException as e:
        logger.warning(f"Identity resolution failed: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected identity resolution error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error during identity resolution"
        )
