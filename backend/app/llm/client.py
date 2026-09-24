from functools import lru_cache

from app.core.config import get_settings
from app.llm.local import LocalProvider
from app.llm.provider import ChatProvider, MistralProvider


@lru_cache
def get_provider() -> MistralProvider:
    return MistralProvider.from_api_key(get_settings().mistral_api_key)


@lru_cache
def get_router_provider() -> ChatProvider:
    """Provider for the intent router.

    Development runs the router on local open weights through Ollama; production
    and eval run it on the hosted small model behind the same protocol.
    """
    settings = get_settings()
    if settings.llm_provider == "ollama":
        return LocalProvider(settings.ollama_base_url)
    return get_provider()
