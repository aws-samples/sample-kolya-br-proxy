"""Background task utilities for async operations."""

import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """Manager for background tasks that don't block requests."""

    @staticmethod
    def create_task(coro: Callable, task_name: str = "background_task"):
        """
        Create a background task without waiting for it.

        Args:
            coro: Coroutine to run
            task_name: Name for logging
        """
        task = asyncio.create_task(coro)
        task.add_done_callback(
            lambda t: BackgroundTaskManager._task_done_callback(t, task_name)
        )
        return task

    @staticmethod
    def _task_done_callback(task: asyncio.Task, task_name: str):
        """Callback when background task completes."""
        try:
            task.result()
            logger.debug(f"Background task '{task_name}' completed successfully")
        except Exception as e:
            logger.error(
                f"Background task '{task_name}' failed: {e}",
                exc_info=True,
            )
