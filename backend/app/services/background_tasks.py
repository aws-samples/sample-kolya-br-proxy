"""Background task utilities for async operations."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

TaskResult = TypeVar("TaskResult")

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """Manager for background tasks that don't block requests."""

    @staticmethod
    def create_task(
        coro: Coroutine[Any, Any, TaskResult],
        task_name: str = "background_task",
    ) -> asyncio.Task[TaskResult]:
        """
        Create a background task without waiting for it.

        Args:
            coro: Coroutine to run
            task_name: Name for logging
        """
        task = asyncio.get_running_loop().create_task(coro)
        task.add_done_callback(
            lambda t: BackgroundTaskManager._task_done_callback(t, task_name)
        )
        return task

    @staticmethod
    def _task_done_callback(task: asyncio.Task[Any], task_name: str) -> None:
        """Callback when background task completes."""
        try:
            task.result()
            logger.debug(f"Background task '{task_name}' completed successfully")
        except Exception as e:
            logger.error(
                f"Background task '{task_name}' failed: {e}",
                exc_info=True,
            )
