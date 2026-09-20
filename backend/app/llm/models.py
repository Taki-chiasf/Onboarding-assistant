from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

MODELS_PATH = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


class ModelConfig(BaseModel):
    provider: str
    models: dict[str, str]


@lru_cache
def load_models() -> ModelConfig:
    data = yaml.safe_load(MODELS_PATH.read_text(encoding="utf-8"))
    config = ModelConfig.model_validate(data)
    for model_id in config.models.values():
        if model_id.endswith("-latest"):
            raise ValueError(f"dated model id required, got: {model_id}")
    return config
