"""Placeholder for future email / push notifications."""
import logging

logger = logging.getLogger("bizsuite.notifications")


def notify_task_assigned(user_email: str, task_title: str) -> None:
    logger.info("Would notify %s about task: %s", user_email, task_title)


def notify_announcement(audience: str, title: str) -> None:
    logger.info("Would broadcast announcement to %s: %s", audience, title)