import uvicorn
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from dependencies import get_ns_user, get_ns_client, verify_origin
from models import NSUser, Subscription
from ns_client import NSClient
from database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from schemas import SubscriptionCreate, SubscriptionResponse, SubscriptionUpdate
import crud
import logging
from typing import List, Union, Optional, Dict, Any
from datetime import datetime

log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
if settings.DEBUG:
    log_level = logging.DEBUG

logging.basicConfig(level=log_level, format=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)

app = FastAPI(title="Netsapiens Subscription Registry")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS Configuration - Dynamic regex for wildcard origin matching
raw_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]

if any("*" in o for o in raw_origins):
    import re

    regex_parts = []
    for o in raw_origins:
        p = re.escape(o).replace(r"\*", r"[^/]+")
        if not p.startswith("http"):
            p = r"https?://" + p
        regex_parts.append(p)

    origin_regex = "^(" + "|".join(regex_parts) + ")$"
    logger.info(f"CORS initialized with wildcard regex: {origin_regex}")

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=raw_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/info")
async def get_app_info():
    return {
        "name": "Netsapiens Subscription Registry",
        "version": "1.0.0",
        "status": "operational",
    }


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.get("/portal-script.js")
async def get_portal_script(request: Request):
    # Dynamically generated JS for portal injection
    base = settings.PUBLIC_API_URL.rstrip("/")
    redirect_uri = f"{base}/receive-ns-redirect/"

    return templates.TemplateResponse(
        "portal_injection.js",
        {
            "request": request,
            "api_endpoint": f"{base}/subscriptions",
            "client_id": settings.NS_CLIENT_ID,
            "redirect_uri": redirect_uri,
        },
        media_type="application/javascript",
    )


@app.get("/subscriptions", dependencies=[Depends(verify_origin)])
async def get_subscriptions_ui(request: Request, user: NSUser = Depends(get_ns_user)):
    # HTML UI skeleton for Subscription Registry management tab
    return templates.TemplateResponse(
        "index.html", {"request": request, "user": user, "version": "1.0.0"}
    )


@app.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    dependencies=[Depends(verify_origin)],
)
async def create_subscription(
    sub_in: SubscriptionCreate,
    user: NSUser = Depends(get_ns_user),
    client: NSClient = Depends(get_ns_client),
    db: AsyncSession = Depends(get_db),
):
    # Create subscription on PBX and local registry
    api_url = normalize_api_url(settings.NS_API_URL)

    try:
        expires_seconds = settings.SUBSCRIPTION_DURATION_DAYS * 24 * 60 * 60
        await client.create_subscription(
            domain=user.domain,
            user=sub_in.user,
            model=sub_in.subscription_model.lower(),
            url=sub_in.post_url,
            expires=expires_seconds,
        )
    except Exception as e:
        logger.error(f"Failed to create subscription on PBX: {e}")
        raise HTTPException(
            status_code=502, detail=f"Failed to create on PBX: {str(e)}"
        )

    return await crud.create_subscription(
        db, sub_in, api_server=api_url, domain=user.domain
    )


@app.post(
    "/subscriptions/adopt",
    response_model=SubscriptionResponse,
    status_code=201,
    dependencies=[Depends(verify_origin)],
)
async def adopt_subscription(
    sub_in: SubscriptionCreate,
    user: NSUser = Depends(get_ns_user),
    db: AsyncSession = Depends(get_db),
):
    # Adopt existing PBX subscription into managed database
    api_url = normalize_api_url(settings.NS_API_URL)

    db_sub = await crud.create_subscription(
        db, sub_in, api_server=api_url, domain=user.domain
    )

    await crud.create_audit_log(
        db,
        api_server=api_url,
        domain=user.domain,
        user=user.user,
        action="adopt",
        resource_type="subscription",
        resource_id=db_sub.id,
        description=f"Adopted existing PBX subscription for {sub_in.user}",
    )

    return db_sub


@app.put(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionResponse,
    dependencies=[Depends(verify_origin)],
)
async def update_subscription(
    subscription_id: int,
    sub_update: SubscriptionUpdate,
    user: NSUser = Depends(get_ns_user),
    db: AsyncSession = Depends(get_db),
    client: NSClient = Depends(get_ns_client),
):
    # Update managed subscription on PBX and local registry
    from datetime import timezone

    db_sub = await crud.get_subscription_by_id(db, subscription_id)
    if not db_sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    try:
        pbx_subs = await client.get_subscriptions(
            domain=db_sub.domain, user=db_sub.user
        )
        target_pbx_id = None
        for p in pbx_subs:
            if (
                p.model.lower() == db_sub.subscription_model.lower()
                and p.post_url == db_sub.post_url
            ):
                target_pbx_id = p.id
                break

        if target_pbx_id:
            ns_payload: Dict[str, Any] = {
                "model": db_sub.subscription_model,
                "post-url": (
                    sub_update.post_url if sub_update.post_url else db_sub.post_url
                ),
                "subscription-geo-support": "yes",
            }
            if sub_update.expires_at:
                duration = sub_update.expires_at - datetime.now(timezone.utc)
                ns_payload["expires"] = max(60, int(duration.total_seconds()))

            await client.update_subscription(target_pbx_id, db_sub.domain, **ns_payload)
            logger.info(
                f"Updated PBX sub {target_pbx_id} for local sub {subscription_id}"
            )
        else:
            logger.warning(
                f"PBX sub not found for local sub {subscription_id}. Attempting re-creation."
            )
            expires_seconds = settings.SUBSCRIPTION_DURATION_DAYS * 24 * 60 * 60
            await client.create_subscription(
                domain=db_sub.domain,
                user=db_sub.user,
                model=db_sub.subscription_model.lower(),
                url=sub_update.post_url if sub_update.post_url else db_sub.post_url,
                expires=expires_seconds,
            )

    except Exception as e:
        logger.error(f"Failed to update subscription on PBX: {e}")
        raise HTTPException(
            status_code=502, detail=f"Failed to update on PBX: {str(e)}"
        )

    updated_sub = await crud.update_subscription(db, subscription_id, sub_update)

    await crud.create_audit_log(
        db,
        api_server=db_sub.api_server,
        domain=db_sub.domain,
        user=user.user,
        action="update",
        resource_type="subscription",
        resource_id=subscription_id,
        description=f"Updated subscription {subscription_id}",
    )

    return updated_sub


@app.get("/subscriptions/status", dependencies=[Depends(verify_origin)])
async def get_subscriptions_status(
    user: NSUser = Depends(get_ns_user),
    db: AsyncSession = Depends(get_db),
):
    # Health summary for managed subscriptions
    from sqlalchemy import select
    from models import Subscription

    api_url = normalize_api_url(settings.NS_API_URL)

    stmt = select(Subscription).where(
        Subscription.domain == user.domain,
        Subscription.status == "active",
        Subscription.maintenance_status == "failed",
        Subscription.api_server == api_url,
    )
    result = await db.execute(stmt)
    failed_subs = result.scalars().all()

    if failed_subs:
        return {
            "status": "unhealthy",
            "count": len(failed_subs),
            "message": f"Maintenance is failing for {len(failed_subs)} subscriptions.",
        }

    return {"status": "healthy"}


@app.get(
    "/subscriptions/list",
    response_model=List[SubscriptionResponse],
    dependencies=[Depends(verify_origin)],
)
async def list_subscriptions(
    user: NSUser = Depends(get_ns_user),
    db: AsyncSession = Depends(get_db),
    client: NSClient = Depends(get_ns_client),
):
    # Merged list of managed (DB) and unmanaged (PBX) subscriptions
    api_url = normalize_api_url(settings.NS_API_URL)

    db_subs = await crud.get_subscriptions(db, api_server=api_url, domain=user.domain)

    try:
        pbx_subs_raw = await client.get_subscriptions(domain=user.domain)
    except Exception as e:
        logger.warning(f"Failed to fetch PBX subscriptions: {e}")
        pbx_subs_raw = []

    merged_list: List[Union[Subscription, SubscriptionResponse]] = []
    db_index = {f"{s.user}:{s.subscription_model}:{s.post_url}": s for s in db_subs}
    merged_list.extend(db_subs)

    for p in pbx_subs_raw:
        p_user = p.user
        p_model = p.model
        p_url = p.post_url

        if not (p_user and p_model and p_url):
            continue

        key = f"{p_user}:{p_model}:{p_url}"

        if key not in db_index:
            unmanaged = SubscriptionResponse(
                user=p_user,
                subscription_model=p_model,
                post_url=p_url,
                expires_at=None,
                description="Unmanaged (PBX Only)",
                status="active",
                source="pbx",
                api_server=api_url,
                domain=user.domain,
                id=None,
            )
            merged_list.append(unmanaged)

    return merged_list


@app.delete(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionResponse,
    dependencies=[Depends(verify_origin)],
)
async def delete_subscription(
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    client: NSClient = Depends(get_ns_client),
):
    # Archives local record and attempts deletion from PBX
    sub = await crud.get_subscription_by_id(db, subscription_id)

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    try:
        pbx_subs = await client.get_subscriptions(domain=sub.domain, user=sub.user)

        target_id = None
        for p in pbx_subs:
            if (
                p.model.lower() == sub.subscription_model.lower()
                and p.post_url == sub.post_url
            ):
                target_id = p.id
                break

        if target_id:
            await client.delete_subscription(target_id, domain=sub.domain)
            logger.info(
                f"Deleted PBX subscription {target_id} for local sub {subscription_id}"
            )
        else:
            logger.warning(
                f"Could not find PBX subscription for local sub {subscription_id} to delete."
            )

    except HTTPException as e:
        if e.status_code == 404:
            logger.info(
                "Subscription not found on PBX (404). Proceeding to archive local record."
            )
        else:
            logger.error(f"Failed to delete subscription from PBX: {e.detail}")
            raise e
    except Exception as e:
        logger.error(f"Unexpected error deleting subscription from PBX: {e}")
        raise HTTPException(
            status_code=502, detail=f"Failed to delete on PBX: {str(e)}"
        )

    return await crud.archive_subscription(db, subscription_id)


@app.get(
    "/users/search", response_model=List[NSUser], dependencies=[Depends(verify_origin)]
)
async def search_users(
    q: str,
    user: NSUser = Depends(get_ns_user),
    client: NSClient = Depends(get_ns_client),
):
    # Searches for Netsapiens users/extensions for UI autocomplete
    all_users = await client.get_users(domain=user.domain)

    if not q:
        return all_users[:20]

    q_lower = q.lower()

    filtered = []
    for u in all_users:
        if (
            q_lower in u.user.lower()
            or (u.name_first_name and q_lower in u.name_first_name.lower())
            or (u.name_last_name and q_lower in u.name_last_name.lower())
        ):
            filtered.append(u)

    return filtered[:50]


def normalize_api_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"
    return url


@app.get("/receive-ns-redirect/")
async def receive_ns_redirect(
    request: Request,
    code: str,
    state: str,
    username: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    # Handle OAuth2 authorization code redirect and save credentials
    import base64
    import json

    try:
        padding = 4 - (len(state) % 4)
        if padding != 4:
            state += "=" * padding

        decoded_state = base64.urlsafe_b64decode(state).decode()
        state_data = json.loads(decoded_state)

        domain = state_data.get("domain")
        user = state_data.get("user")
        redirect_uri = state_data.get("redirect_uri")

        if not (domain and user and redirect_uri):
            raise ValueError("Invalid state payload")

        api_url = normalize_api_url(settings.NS_API_URL)

    except Exception as e:
        logger.error(f"Failed to parse OAuth state: {e}")
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    try:
        token_data = await NSClient.exchange_auth_code(
            code, redirect_uri, username=username
        )
    except HTTPException as e:
        logger.error(f"OAuth exchange failed: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected OAuth error: {e}")
        raise HTTPException(status_code=500, detail="Token exchange failed")

    await crud.upsert_oauth_credential(
        db,
        api_server=api_url,
        domain=domain,
        user=user,
        refresh_token=token_data["refresh_token"],
        access_token=token_data.get("access_token"),
        expires_in=token_data.get("expires_in"),
    )

    return templates.TemplateResponse(
        "auth_success.html", {"request": request, "user": user, "domain": domain}
    )


@app.get("/auth/check", dependencies=[Depends(verify_origin)])
async def check_auth_status(
    user: NSUser = Depends(get_ns_user),
    db: AsyncSession = Depends(get_db),
):
    # Check if valid OAuth credentials exist for the user
    from sqlalchemy import select
    from models import OAuthCredential

    api_url = normalize_api_url(settings.NS_API_URL)

    stmt = select(OAuthCredential).where(
        OAuthCredential.api_server == api_url,
        OAuthCredential.domain == user.domain,
        OAuthCredential.user == user.user,
    )
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    return {"has_auth": cred is not None, "user": user.user, "domain": user.domain}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
