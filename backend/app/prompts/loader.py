"""Prompt registry.

Prompts live as versioned YAML files under this package. Each file carries its
own name and version, and the registry discovers them at load time so prompt
versions are explicit and recorded on every answer.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

PROMPTS_DIR = Path(__file__).resolve().parent


class Prompt(BaseModel):
    name: str
    version: str
    system: str
    user: str


@lru_cache
def _registry() -> dict[str, tuple[str, Path]]:
    registry: dict[str, tuple[str, Path]] = {}
    for path in sorted(PROMPTS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        registry[str(data["name"])] = (str(data["version"]), path)
    return registry


@lru_cache
def load_prompt(name: str) -> Prompt:
    version, path = _registry()[name]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Prompt(
        name=str(data["name"]),
        version=version,
        system=str(data["system"]),
        user=str(data["user"]),
    )


def prompt_version(name: str) -> str:
    prompt = load_prompt(name)
    return f"{prompt.name}.v{prompt.version}"
