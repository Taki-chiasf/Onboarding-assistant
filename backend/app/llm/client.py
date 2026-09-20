from functools import lru_cache

from app.core.config import get_settings
from app.llm.provider import MistralProvider


@lru_cache
def get_provider() -> MistralProvider:
    return MistralProvider.from_api_key(get_settings().mistral_api_key)
