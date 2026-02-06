import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Subscription, OAuthCredential
from ns_client import NSClient
from crud import create_audit_log
from config import settings
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def check_user_existence(
    db: AsyncSession, sub: Subscription, ns_client: NSClient
) -> bool:
    # Check if user exists on PBX and archive if not
    try:
        user = await ns_client.get_user(sub.domain, sub.user)
        if not user:
            logger.warning(
                f"User {sub.user} @ {sub.domain} not found on PBX. Archiving subscription {sub.id}."
            )
            sub.status = "archived"
            sub.maintenance_status = "archived"
            sub.maintenance_message = "User not found on PBX"
            sub.last_maintenance_attempt = datetime.now(timezone.utc)

            await create_audit_log(
                db,
                sub.api_server,
                sub.domain,
                "archive",
                "subscription",
                resource_id=sub.id,
                description=f"Archived due to missing user {sub.user}",
            )
            await db.commit()
            return False
        return True
    except Exception as e:
        logger.error(
            f"Error checking user existence for {sub.user} @ {sub.domain}: {e}"
        )
        sub.maintenance_status = "failed"
        sub.maintenance_message = f"Existence check failed: {str(e)}"
        sub.last_maintenance_attempt = datetime.now(timezone.utc)
        await db.commit()
        return False


async def refresh_credential(db: AsyncSession, cred: OAuthCredential) -> bool:
    # Refresh OAuth token if expiring soon
    TOKEN_MAINTENANCE_WINDOW = timedelta(hours=2)
    now = datetime.now(timezone.utc)

    expires_at = ensure_utc(cred.expires_at)
    if expires_at and (expires_at - now) > TOKEN_MAINTENANCE_WINDOW:
        return True

    logger.info(f"Refreshing token for {cred.user} @ {cred.domain}")
    try:
        new_token_data = await NSClient.refresh_oauth_token(cred.refresh_token)

        cred.access_token = new_token_data["access_token"]
        if "refresh_token" in new_token_data:
            cred.refresh_token = new_token_data["refresh_token"]

        expires_in = new_token_data.get("expires_in", 3600)
        cred.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        cred.last_refresh_at = datetime.now(timezone.utc)

        cred.maintenance_status = "success"
        cred.maintenance_message = "Token refreshed successfully"
        cred.last_maintenance_attempt = datetime.now(timezone.utc)

        await create_audit_log(
            db,
            cred.api_server,
            cred.domain,
            "refresh",
            "credential",
            resource_id=cred.id,
            description="Token refreshed successfully",
        )
        await db.commit()
        return True
    except HTTPException as e:
        logger.error(
            f"Failed to refresh token for {cred.user} @ {cred.domain}: {e.detail}"
        )

        # Archive associated subscriptions on permanent token failure
        if e.status_code in [400, 401, 403]:
            logger.warning(
                f"Refresh token invalid ({e.status_code}). Archiving credential."
            )
            cred.maintenance_status = "failed_permanent"
            cred.maintenance_message = f"Permanent Failure: {e.detail}"

            from sqlalchemy import update

            stmt_archive = (
                update(Subscription)
                .where(
                    Subscription.api_server == cred.api_server,
                    Subscription.domain == cred.domain,
                    Subscription.user == cred.user,
                    Subscription.status == "active",
                )
                .values(
                    status="archived",
                    maintenance_status="archived",
                    maintenance_message="Archived: Credential failed permanently",
                    last_maintenance_attempt=datetime.now(timezone.utc),
                )
            )
            await db.execute(stmt_archive)
        else:
            cred.maintenance_status = "failed"
            cred.maintenance_message = f"Refresh failed: {e.detail}"

        cred.last_maintenance_attempt = datetime.now(timezone.utc)

        await create_audit_log(
            db,
            cred.api_server,
            cred.domain,
            "failed_refresh",
            "credential",
            resource_id=cred.id,
            description=f"Refresh failed: {e.detail}",
            details=e.detail,
        )
        await db.commit()
        return False
    except Exception as e:
        logger.error(f"Failed to refresh token for {cred.user} @ {cred.domain}: {e}")
        cred.maintenance_status = "failed"
        cred.maintenance_message = f"Refresh failed: {str(e)}"
        cred.last_maintenance_attempt = datetime.now(timezone.utc)

        await create_audit_log(
            db,
            cred.api_server,
            cred.domain,
            "failed_refresh",
            "credential",
            resource_id=cred.id,
            description=f"Refresh failed: {str(e)}",
            details=str(e),
        )
        await db.commit()
        return False


async def renew_subscription(
    db: AsyncSession, sub: Subscription, ns_client: NSClient
) -> bool:
    # Renew PBX subscription if expiring soon or duration mismatch
    now = datetime.now(timezone.utc)
    standard_duration = timedelta(days=settings.SUBSCRIPTION_DURATION_DAYS)
    renewal_window = timedelta(hours=settings.SUBSCRIPTION_RENEWAL_WINDOW_HOURS)
    expires_at = ensure_utc(sub.expires_at)

    if not expires_at:
        should_renew = True
    else:
        time_left = expires_at - now
        if time_left < renewal_window:
            should_renew = True
        elif time_left < (standard_duration - renewal_window):
            logger.info(
                f"Subscription {sub.id} does not meet standard {settings.SUBSCRIPTION_DURATION_DAYS} day duration. Forcing renewal."
            )
            should_renew = True
        else:
            should_renew = False

    if not should_renew:
        return True

    logger.info(f"Renewing subscription {sub.id} for {sub.user} @ {sub.domain}")
    try:
        if not await check_user_existence(db, sub, ns_client):
            return False

        expires_seconds = int(standard_duration.total_seconds())
        await ns_client.create_subscription(
            domain=sub.domain,
            user=sub.user,
            model=sub.subscription_model,
            url=sub.post_url,
            expires=expires_seconds,
        )

        sub.expires_at = datetime.now(timezone.utc) + standard_duration
        sub.maintenance_status = "success"
        sub.maintenance_message = "Subscription renewed successfully"
        sub.last_maintenance_attempt = datetime.now(timezone.utc)

        await create_audit_log(
            db,
            sub.api_server,
            sub.domain,
            "renew",
            "subscription",
            resource_id=sub.id,
            description="Subscription renewed successfully",
        )
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to renew subscription {sub.id}: {e}")
        sub.maintenance_status = "failed"
        sub.maintenance_message = f"Renewal failed: {str(e)}"
        sub.last_maintenance_attempt = datetime.now(timezone.utc)

        await create_audit_log(
            db,
            sub.api_server,
            sub.domain,
            "failed_renew",
            "subscription",
            resource_id=sub.id,
            description=f"Renewal failed: {str(e)}",
        )
        await db.commit()
        return False


async def run_maintenance(db: AsyncSession) -> None:
    # Main maintenance loop: refresh tokens and renew subscriptions
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        stmt_cred = select(OAuthCredential).where(
            OAuthCredential.maintenance_status != "failed_permanent"
        )
        result_cred = await db.execute(stmt_cred)
        credentials = result_cred.scalars().all()

        logger.info(f"Checking {len(credentials)} credentials for refresh...")
        for cred in credentials:
            await refresh_credential(db, cred)

        stmt_sub = select(Subscription).where(Subscription.status == "active")
        result_sub = await db.execute(stmt_sub)
        subscriptions = result_sub.scalars().all()

        logger.info(
            f"Checking {len(subscriptions)} active subscriptions for renewal..."
        )

        cred_map: Dict[Tuple[str, str, str], OAuthCredential] = {
            (c.api_server, c.domain, c.user): c for c in credentials
        }
        clients: Dict[Tuple[str, str, str], NSClient] = {}

        for sub in subscriptions:
            cred_key = (sub.api_server, sub.domain, sub.user)
            cred_obj = cred_map.get(cred_key)

            if not cred_obj or not cred_obj.access_token:
                logger.warning(
                    f"No valid credential for subscription {sub.id}. Archiving orphaned subscription."
                )
                sub.status = "archived"
                sub.maintenance_status = "archived"
                sub.maintenance_message = "Archived: No matching OAuth credential found"
                sub.last_maintenance_attempt = datetime.now(timezone.utc)

                await create_audit_log(
                    db,
                    sub.api_server,
                    sub.domain,
                    "archive",
                    "subscription",
                    resource_id=sub.id,
                    description="Auto-archived orphaned subscription",
                )
                await db.commit()
                continue

            if cred_obj.maintenance_status == "failed_permanent":
                logger.warning(
                    f"Skipping subscription {sub.id} due to permanently failed credential."
                )
                sub.maintenance_status = "failed"
                sub.maintenance_message = (
                    f"Credential failed: {cred_obj.maintenance_message}"
                )
                sub.last_maintenance_attempt = datetime.now(timezone.utc)
                await db.commit()
                continue

            if cred_key not in clients:
                clients[cred_key] = NSClient(
                    token=cred_obj.access_token, client=http_client
                )
            await renew_subscription(db, sub, clients[cred_key])
