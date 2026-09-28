'''Channel providers used by the notification worker.'''

import logging

logger = logging.getLogger(__name__)


class Provider:
    def send(self, *, deduplication_key: str, recipient: str, body: str) -> None:
        raise NotImplementedError


class LocalProvider(Provider):
    '''Logs instead of sending; the local stack and tests use it.'''

    def send(self, *, deduplication_key: str, recipient: str, body: str) -> None:
        logger.info("notification %s to %s", deduplication_key, recipient)


_PROVIDERS: dict[str, Provider] = {"email": LocalProvider(), "push": LocalProvider()}


def for_channel(channel: str) -> Provider:
    if channel not in _PROVIDERS:
        raise ValueError("unknown channel: " + channel)
    return _PROVIDERS[channel]
