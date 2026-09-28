'''Notification worker: consumes delivery jobs from the queue.

Delivery is at-least-once, so the provider call carries the notification id as
its deduplication key. Failed jobs retry with exponential backoff and move to
the dead-letter queue after the final attempt.
'''

import logging
import time

import redis
from rq import Queue, Worker

from .providers import for_channel

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (TimeoutError, ConnectionError)
MAX_ATTEMPTS = 5


def deliver(notification_id: str, channel: str, recipient: str, body: str) -> None:
    '''Send one notification through the channel provider.'''
    provider = for_channel(channel)
    provider.send(deduplication_key=notification_id, recipient=recipient, body=body)
    logger.info("delivered notification %s over %s", notification_id, channel)


def deliver_with_retry(notification_id: str, channel: str, recipient: str, body: str) -> None:
    '''Deliver with exponential backoff, then give up to the dead-letter queue.'''
    delay = 1.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            deliver(notification_id, channel, recipient, body)
            return
        except RETRYABLE_ERRORS as error:
            if attempt == MAX_ATTEMPTS:
                logger.error("dead-lettering notification %s", notification_id)
                raise
            logger.warning("attempt %d failed: %s", attempt, error)
            time.sleep(delay)
            delay = min(delay * 2, 30)


def main() -> None:
    connection = redis.from_url("redis://localhost:6379/0")
    queue = Queue("notifications", connection=connection)
    Worker([queue], connection=connection).work(with_scheduler=False)


if __name__ == "__main__":
    main()
