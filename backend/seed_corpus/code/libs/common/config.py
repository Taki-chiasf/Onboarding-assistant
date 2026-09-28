'''Environment-backed settings shared by the services.'''

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class BaseSettings:
    database_url: str
    redis_url: str
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "BaseSettings":
        '''Read settings from the environment, applying local defaults.'''
        return cls(
            database_url=os.environ["PLATFORM_DATABASE_URL"],
            redis_url=os.environ.get("PLATFORM_REDIS_URL", "redis://localhost:6379/0"),
            log_level=os.environ.get("PLATFORM_LOG_LEVEL", "INFO"),
        )


@lru_cache
def settings() -> BaseSettings:
    return BaseSettings.from_env()
