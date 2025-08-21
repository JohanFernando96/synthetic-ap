from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .settings import settings


class AIConfig(BaseModel):
    enabled: bool = True
    model: str = "gpt-4o-mini"
    temperature: float = 0.15
    top_p: float = 1.0
    max_output_tokens: int = 1200
    system_prompt: str | None = None
    max_vendors: int = 6
    line_item_description_enabled: bool = False
    line_item_description_prompt: str = (
        "Write a short description for invoice line item '{item_name}'."
    )


class GeneratorCfg(BaseModel):
    allow_price_variation: bool = False
    price_variation_pct: float = 0.10
    currency: str = "AUD"
    status: str = "AUTHORISED"
    business_days_only: bool = True


class ArtifactsCfg(BaseModel):
    include_meta_json: bool = True


class RuntimeConfig(BaseModel):
    ai: AIConfig = Field(default_factory=AIConfig)
    generator: GeneratorCfg = Field(default_factory=GeneratorCfg)
    artifacts: ArtifactsCfg = Field(default_factory=ArtifactsCfg)
    force_no_tax: bool = False


def _config_dir(base_dir: str) -> Path:
    p = Path(base_dir) / "config"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _runtime_path(base_dir: str) -> Path:
    return _config_dir(base_dir) / "runtime_config.yaml"


def _defaults_path(base_dir: str) -> Path:
    # optional file; if present, merged under runtime
    return _config_dir(base_dir) / "service_defaults.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_runtime_config(base_dir: str) -> RuntimeConfig:
    defaults = _load_yaml(_defaults_path(base_dir))
    runtime = _load_yaml(_runtime_path(base_dir))
    merged = _deep_merge(defaults, runtime)
    return RuntimeConfig(**merged)


def save_runtime_config(cfg: RuntimeConfig, base_dir: str | None = None) -> None:
    base_dir = base_dir or settings.data_dir
    runtime_path = _runtime_path(base_dir)
    raw = cfg.model_dump()
    runtime_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
