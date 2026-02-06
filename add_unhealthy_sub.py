import asyncio
import logging
from datetime import datetime, timedelta, timezone
from database import async_session_factory
from models import Subscription
from sqlalchemy import select

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed-unhealthy")


async def main():
    # Seed unhealthy subscription for testing
    logger.info("Seeding unhealthy subscription...")
    async with async_session_factory() as db:
        seed_data = {
            "api_server": "sandbox.voipco.co",
            "domain": "5622970000.com",
            "user": "101",
            "subscription_model": "message",
            "post_url": "https://example.com/expired-webhook",
        }

        stmt = select(Subscription).where(
            Subscription.api_server == seed_data["api_server"],
            Subscription.domain == seed_data["domain"],
            Subscription.user == seed_data["user"],
            Subscription.subscription_model == seed_data["subscription_model"],
            Subscription.post_url == seed_data["post_url"],
        )
        result = await db.execute(stmt)
        existing_sub = result.scalar_one_or_none()

        if existing_sub:
            logger.info(
                "Updating existing subscription %s to unhealthy state...",
                existing_sub.id,
            )
            existing_sub.status = "active"
            existing_sub.maintenance_status = "failed"
            existing_sub.maintenance_message = (
                "Simulated maintenance failure: API Timeout"
            )
            existing_sub.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            existing_sub.last_maintenance_attempt = datetime.now(timezone.utc)
            await db.commit()
            return

        sub = Subscription(
            **seed_data,
            description="Simulated Unhealthy Subscription",
            status="active",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            maintenance_status="failed",
            maintenance_message="Simulated maintenance failure: API Timeout",
            last_maintenance_attempt=datetime.now(timezone.utc),
        )

        db.add(sub)
        try:
            await db.commit()
            logger.info("Successfully added unhealthy subscription.")
        except Exception as e:
            logger.error(f"Failed to add subscription: {e}")
            await db.rollback()


if __name__ == "__main__":
    asyncio.run(main())
