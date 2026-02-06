from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime
from models import Subscription, AuditLog, OAuthCredential
from schemas import SubscriptionCreate, SubscriptionUpdate


async def create_audit_log(
    db: AsyncSession,
    api_server: str,
    domain: str,
    action: str,
    resource_type: str,
    user: Optional[str] = "System",
    resource_id: Optional[int] = None,
    description: Optional[str] = None,
    details: Optional[str] = None,
) -> AuditLog:
    # Create audit log entry
    log = AuditLog(
        api_server=api_server,
        domain=domain,
        user=user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        description=description,
        details=details,
    )
    db.add(log)
    await db.commit()
    return log


async def create_subscription(
    db: AsyncSession, sub_in: SubscriptionCreate, api_server: str, domain: str
) -> Subscription:
    # Create or update subscription record
    from config import settings
    from datetime import timedelta

    stmt = select(Subscription).where(
        Subscription.api_server == api_server,
        Subscription.domain == domain,
        Subscription.user == sub_in.user,
        Subscription.subscription_model == sub_in.subscription_model,
        Subscription.post_url == sub_in.post_url,
    )
    result = await db.execute(stmt)
    existing_sub = result.scalar_one_or_none()

    expires_at = sub_in.expires_at
    if expires_at is None:
        expires_at = datetime.now() + timedelta(
            days=settings.SUBSCRIPTION_DURATION_DAYS
        )

    if existing_sub:
        existing_sub.description = sub_in.description
        existing_sub.expires_at = expires_at
        existing_sub.status = "active"
        existing_sub.updated_at = datetime.now()
        existing_sub.maintenance_status = "pending"
        existing_sub.maintenance_message = None

        await db.commit()
        await db.refresh(existing_sub)
        return existing_sub

    db_sub = Subscription(
        api_server=api_server,
        domain=domain,
        user=sub_in.user,
        subscription_model=sub_in.subscription_model,
        post_url=sub_in.post_url,
        description=sub_in.description,
        expires_at=expires_at,
        status="active",
    )
    db.add(db_sub)
    await db.commit()
    await db.refresh(db_sub)
    return db_sub


async def get_subscriptions(
    db: AsyncSession, api_server: str, domain: str, user: Optional[str] = None
) -> List[Subscription]:
    # List active subscriptions for a domain
    query = select(Subscription).where(
        Subscription.api_server == api_server,
        Subscription.domain == domain,
        Subscription.status != "archived",
    )

    if user:
        query = query.where(Subscription.user == user)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_subscription_by_id(
    db: AsyncSession, subscription_id: int
) -> Optional[Subscription]:
    query = select(Subscription).where(Subscription.id == subscription_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_subscription(
    db: AsyncSession, subscription_id: int, sub_update: SubscriptionUpdate
) -> Optional[Subscription]:
    # Update non-identity fields
    query = select(Subscription).where(Subscription.id == subscription_id)
    result = await db.execute(query)
    sub = result.scalar_one_or_none()

    if not sub:
        return None

    update_data = sub_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(sub, key, value)

    await db.commit()
    await db.refresh(sub)
    return sub


async def archive_subscription(
    db: AsyncSession, subscription_id: int
) -> Optional[Subscription]:
    # Soft delete
    query = select(Subscription).where(Subscription.id == subscription_id)
    result = await db.execute(query)
    sub = result.scalar_one_or_none()

    if not sub:
        return None

    sub.status = "archived"
    await db.commit()
    await db.refresh(sub)
    return sub


async def upsert_oauth_credential(
    db: AsyncSession,
    api_server: str,
    domain: str,
    user: str,
    refresh_token: str,
    access_token: Optional[str] = None,
    expires_in: Optional[int] = None,
) -> OAuthCredential:
    # Create or update OAuth credential
    stmt = select(OAuthCredential).where(
        OAuthCredential.api_server == api_server,
        OAuthCredential.domain == domain,
        OAuthCredential.user == user,
    )
    result = await db.execute(stmt)
    cred = result.scalar_one_or_none()

    expires_at = None
    if expires_in:
        from datetime import timedelta

        expires_at = datetime.now() + timedelta(seconds=expires_in)

    if cred:
        cred.refresh_token = refresh_token
        if access_token:
            cred.access_token = access_token
        if expires_at:
            cred.expires_at = expires_at

        cred.maintenance_status = "success"
        cred.last_refresh_at = datetime.now()
    else:
        cred = OAuthCredential(
            api_server=api_server,
            domain=domain,
            user=user,
            refresh_token=refresh_token,
            access_token=access_token,
            expires_at=expires_at,
            last_refresh_at=datetime.now(),
            maintenance_status="success",
        )
        db.add(cred)

    await db.commit()
    await db.refresh(cred)
    return cred
