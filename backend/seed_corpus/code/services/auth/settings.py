'''Auth service settings loaded from the environment.'''

import os
from dataclasses import dataclass

DEFAULT_TOKEN_TTL_SECONDS = 3600


@dataclass(frozen=True)
class Settings:
    database_url: str
    signing_key: str
    token_ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        '''Build settings, failing fast when the signing key is missing.'''
        signing_key = os.environ.get("AUTH_SIGNING_KEY", "")
        if not signing_key:
            raise RuntimeError("AUTH_SIGNING_KEY is required")
        return cls(
            database_url=os.environ["AUTH_DATABASE_URL"],
            signing_key=signing_key,
            token_ttl_seconds=int(
                os.environ.get("AUTH_TOKEN_TTL", DEFAULT_TOKEN_TTL_SECONDS)
            ),
        )
