"""
Bias Engine — Configuration
============================
Central configuration for the bias identification & quantification engine.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM provider instance."""
    name: str
    provider_type: str  # "gemini", "openai", "openai_compatible"
    model: str
    api_key_env: str = ""         # env var name for API key
    base_url: Optional[str] = None  # for openai_compatible (local models)
    temperature: float = 0.0
    max_retries: int = 3
    timeout_s: float = 60.0


def _load_env_file():
    """Auto-load key/value pairs from .env in project root if present."""
    env_paths = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip('"').strip("'")
                            if k and k not in os.environ:
                                os.environ[k] = v
                break
            except Exception:
                pass

_load_env_file()


def _default_providers() -> Dict[str, LLMProviderConfig]:
    return {
        "gemini-3.1-flash-lite": LLMProviderConfig(
            name="gemini-3.1-flash-lite",
            provider_type="gemini",
            model="gemini-3.1-flash-lite",
            api_key_env="GOOGLE_API_KEY",
        ),
        "thki-cascade": LLMProviderConfig(
            name="thki-cascade",
            provider_type="thki_cascade",
            model="openai-gpt5.4-mini",
            api_key_env="THKI_KEY",
            base_url="https://chat.kiconnect.nrw/api/v1",
        ),
        "thki-gpt5.4-mini": LLMProviderConfig(
            name="thki-gpt5.4-mini",
            provider_type="thki",
            model="openai-gpt5.4-mini",
            api_key_env="THKI_KEY",
            base_url="https://chat.kiconnect.nrw/api/v1",
        ),
        "thki-mistral-small": LLMProviderConfig(
            name="thki-mistral-small",
            provider_type="thki",
            model="mistralai-mistral-small-4-119b-2603",
            api_key_env="THKI_KEY",
            base_url="https://chat.kiconnect.nrw/api/v1",
        ),
        "thki-qwen-omni": LLMProviderConfig(
            name="thki-qwen-omni",
            provider_type="thki",
            model="qwen3-omni-30b-a3b-instruct",
            api_key_env="THKI_KEY",
            base_url="https://chat.kiconnect.nrw/api/v1",
        ),
        "thki-gpt-oss-120b": LLMProviderConfig(
            name="thki-gpt-oss-120b",
            provider_type="thki",
            model="openai-gpt-oss-120b",
            api_key_env="THKI_KEY",
            base_url="https://chat.kiconnect.nrw/api/v1",
        ),
    }


def _default_primary_provider() -> str:
    if os.environ.get("THKI_KEY"):
        return "thki-cascade"
    if os.environ.get("GOOGLE_API_KEY"):
        return "gemini-3.1-flash-lite"
    return "thki-cascade"


@dataclass
class EngineConfig:
    """Master configuration for the bias engine."""

    # ── LLM providers ──────────────────────────────────────────────────
    primary_provider: str = field(default_factory=_default_primary_provider)
    cross_model_provider: Optional[str] = None  # e.g., "thki-mistral-small"

    providers: Dict[str, LLMProviderConfig] = field(default_factory=_default_providers)

    # ── Identification ─────────────────────────────────────────────────
    identification_batch_size: int = 50

    # ── Listwise ranking ───────────────────────────────────────────────
    listwise_group_size: int = 10
    new_item_groups: int = 3  # how many groups each new item participates in

    # ── Scheduling ─────────────────────────────────────────────────────
    daily_schedule_hour: int = 3
    reranking_day: str = "sunday"
    reranking_hour: int = 4
    cross_model_reranking_enabled: bool = False

    # ── Re-ranking (weekly, lightweight) ───────────────────────────────
    reranking_sample_pct: float = 0.15
    reranking_max_items_per_category: int = 50

    # ── Bradley-Terry model ────────────────────────────────────────────
    bt_regularization: float = 0.01
    bt_alpha: float = 1.5  # logistic mapping spread
    score_ema_beta: float = 0.7

    # ── Framework ──────────────────────────────────────────────────────
    framework_path: Optional[str] = None  # None → use default_framework.yaml

    # ── Data paths ─────────────────────────────────────────────────────
    data_dir: str = ""
    engine_state_dir: str = ""

    # ── spaCy model for normalization ──────────────────────────────────
    spacy_model: str = "en_core_web_sm"

    def __post_init__(self):
        if not self.data_dir:
            self.data_dir = str(
                Path(__file__).resolve().parent.parent / "server" / "data"
            )
        if not self.engine_state_dir:
            self.engine_state_dir = str(
                Path(self.data_dir) / "engine_state"
            )

    @property
    def suggestions_file(self) -> str:
        return os.path.join(self.data_dir, "suggestions.jsonl")

    @property
    def lexicon_file(self) -> str:
        return os.path.join(self.data_dir, "lexicon.json")

    @property
    def pcm_dir(self) -> str:
        return os.path.join(self.engine_state_dir, "pcm")

    @property
    def bt_scores_dir(self) -> str:
        return os.path.join(self.engine_state_dir, "bt_scores")

    @property
    def task_journal_file(self) -> str:
        return os.path.join(self.engine_state_dir, "task_journal.jsonl")

    @property
    def identification_log_file(self) -> str:
        return os.path.join(self.engine_state_dir, "identification_log.jsonl")

    @property
    def engine_meta_file(self) -> str:
        return os.path.join(self.engine_state_dir, "engine_meta.json")

    def ensure_dirs(self):
        """Create all required directories."""
        for d in [self.data_dir, self.engine_state_dir,
                  self.pcm_dir, self.bt_scores_dir]:
            os.makedirs(d, exist_ok=True)

    # ── Serialization ──────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str) -> "EngineConfig":
        """Load config from a YAML file, merging with defaults."""
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}

        providers = {}
        for name, pconf in raw.pop("providers", {}).items():
            providers[name] = LLMProviderConfig(name=name, **pconf)

        cfg = cls(**{k: v for k, v in raw.items()
                     if k in cls.__dataclass_fields__})
        if providers:
            cfg.providers.update(providers)
        return cfg
