"""
Background tasks for pricing updates.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.database import async_session_maker
from app.services.pricing_updater import PricingUpdater

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: AsyncIOScheduler = None


async def update_pricing_task():
    """Background task to update model pricing."""
    logger.info("Starting pricing update task...")

    async with async_session_maker() as db:
        try:
            updater = PricingUpdater(db)
            stats = await updater.update_all_pricing()
            logger.info(
                f"Pricing update completed: {stats['updated']} models updated "
                f"from {stats['source']}, {stats['failed']} failed"
            )
        except Exception as e:
            logger.error(f"Pricing update task failed: {e}", exc_info=True)


def start_scheduler():
    """Start the background task scheduler."""
    global scheduler

    if scheduler is not None:
        logger.warning("Scheduler already started")
        return

    scheduler = AsyncIOScheduler()

    # Schedule pricing update daily at 2 AM UTC
    scheduler.add_job(
        update_pricing_task,
        trigger=CronTrigger(hour=2, minute=0),
        id="update_pricing",
        name="Update model pricing from AWS",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Pricing update scheduler started (runs daily at 2 AM UTC)")


def stop_scheduler():
    """Stop the background task scheduler."""
    global scheduler

    if scheduler is not None:
        scheduler.shutdown()
        scheduler = None
        logger.info("Pricing update scheduler stopped")
