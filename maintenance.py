import asyncio
import logging
import sys
from database import async_session_factory
from maintenance_service import run_maintenance
from config import settings

# Configure logging for CLI
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format=settings.LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("maintenance-cli")


async def main():
    # CLI entrypoint for maintenance run
    db_url = settings.DATABASE_URL
    if "@" in db_url:
        part1, part2 = db_url.split("@")
        masked_url = f"{part1.split(':')[0]}:***@{part2}"
        logger.info(f"Connecting to database: {masked_url}")

    logger.info("Starting maintenance run...")
    async with async_session_factory() as db:
        try:
            await run_maintenance(db)
            logger.info("Maintenance run completed successfully.")
        except Exception as e:
            logger.exception(f"Maintenance run failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Maintenance run interrupted by user.")
        sys.exit(0)
