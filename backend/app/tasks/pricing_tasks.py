"""
Background tasks for pricing updates.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.database import async_session_maker
from app.services.pricing_updater import PricingUpdater
from app.services.gemini_pricing_updater import GeminiPricingUpdater

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: AsyncIOScheduler = None


async def update_pricing_task():
    """Background task to update AWS Bedrock model pricing."""
    logger.info("Starting AWS pricing update task...")

    async with async_session_maker() as db:
        try:
            updater = PricingUpdater(db)
            stats = await updater.update_all_pricing()
            logger.info(
                f"AWS pricing update completed: {stats['updated']} models updated "
                f"from {stats['source']}, {stats['failed']} failed"
            )
        except Exception as e:
            logger.error(f"AWS pricing update task failed: {e}", exc_info=True)


async def refresh_profile_cache_task():
    """Background task to refresh the Bedrock inference profile cache."""
    logger.info("Starting profile cache refresh task...")

    try:
        from app.services.bedrock import BedrockClient

        bc = BedrockClient.get_instance()
        await bc.refresh_profile_cache()
        logger.info("Profile cache refresh completed")
    except Exception as e:
        logger.error(f"Profile cache refresh task failed: {e}", exc_info=True)


async def update_gemini_pricing_task():
    """Background task to update Google Gemini model pricing."""
    logger.info("Starting Gemini pricing update task...")

    async with async_session_maker() as db:
        try:
            updater = GeminiPricingUpdater(db)
            stats = await updater.update_all_pricing()
            logger.info(
                f"Gemini pricing update completed: {stats['updated']} models updated, "
                f"{stats['failed']} failed"
            )
        except Exception as e:
            logger.error(f"Gemini pricing update task failed: {e}", exc_info=True)


def start_scheduler():
    """Start the background task scheduler."""
    global scheduler

    if scheduler is not None:
        logger.warning("Scheduler already started")
        return

    scheduler = AsyncIOScheduler()

    # Profile cache MUST refresh BEFORE pricing updates so the filter
    # can correctly identify which cross-region profiles are available.
    scheduler.add_job(
        refresh_profile_cache_task,
        trigger=CronTrigger(hour=1, minute=50),
        id="refresh_profile_cache",
        name="Refresh Bedrock inference profile cache",
        replace_existing=True,
    )

    # Schedule AWS pricing update daily at 2:00 AM UTC
    scheduler.add_job(
        update_pricing_task,
        trigger=CronTrigger(hour=2, minute=0),
        id="update_pricing",
        name="Update model pricing from AWS",
        replace_existing=True,
    )

    # Schedule Gemini pricing update daily at 2:30 AM UTC (offset from AWS job)
    scheduler.add_job(
        update_gemini_pricing_task,
        trigger=CronTrigger(hour=2, minute=30),
        id="update_gemini_pricing",
        name="Update Gemini model pricing from Google",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started (profile cache: 1:50, AWS pricing: 2:00, Gemini: 2:30 UTC)"
    )


def stop_scheduler():
    """Stop the background task scheduler."""
    global scheduler

    if scheduler is not None:
        scheduler.shutdown()
        scheduler = None
        logger.info("Pricing update scheduler stopped")
