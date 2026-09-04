"""Celery tasks for AIPS fixture project."""
from celery import shared_task


@shared_task
def send_notification(user_id: int, message: str) -> bool:
    """Send a notification to a user."""
    # Placeholder
    return True


@shared_task
def process_article(article_id: int) -> dict:
    """Process an article asynchronously."""
    return {"status": "processed", "article_id": article_id}
