"""
Bias Engine — LLM Provider Abstraction
========================================
Flexible LLM provider layer supporting Gemini, OpenAI, and OpenAI-compatible
local models (vLLM, Ollama, text-generation-inference, etc.).

All providers expose a unified ``generate()`` interface.
"""
from __future__ import annotations

import json
import os
import time
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .config import LLMProviderConfig

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    def __init__(self, config: LLMProviderConfig):
        self.config = config
        self.name = config.name
        self.model = config.model
        self._call_count = 0

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send a prompt to the LLM and return the raw text response.

        Args:
            system_prompt: System-level instructions.
            user_prompt: The user message / content to process.
            json_mode: If True, request JSON-formatted output.
            temperature: Override default temperature if set.

        Returns:
            Raw text response from the LLM.

        Raises:
            LLMError: On unrecoverable API failures after retries.
        """
        ...

    def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """Generate with exponential backoff retries."""
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                result = self.generate(
                    system_prompt, user_prompt,
                    json_mode=json_mode, temperature=temperature,
                )
                self._call_count += 1
                return result
            except Exception as e:
                last_error = e
                wait = min(2 ** attempt * 1.0, 30.0)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, self.config.max_retries, e, wait,
                )
                time.sleep(wait)
        raise LLMError(
            f"All {self.config.max_retries} retries exhausted for "
            f"provider '{self.name}': {last_error}"
        ) from last_error

    @property
    def call_count(self) -> int:
        return self._call_count


class LLMError(Exception):
    """Raised when an LLM call fails after all retries."""
    pass


# ─── Gemini Provider ────────────────────────────────────────────────────────


class GeminiProvider(LLMProvider):
    """Google Gemini / Generative AI provider."""

    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import google.generativeai as genai
            except ImportError:
                raise LLMError(
                    "google-generativeai not installed. "
                    "Run: pip install google-generativeai"
                )
            api_key = os.environ.get(self.config.api_key_env or "GOOGLE_API_KEY")
            if not api_key:
                raise LLMError(
                    f"API key env var '{self.config.api_key_env}' not set."
                )
            genai.configure(api_key=api_key)
            self._client = genai.GenerativeModel(self.model)
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        client = self._get_client()
        temp = temperature if temperature is not None else self.config.temperature

        generation_config: Dict[str, Any] = {"temperature": temp}
        if json_mode:
            generation_config["response_mime_type"] = "application/json"

        resp = client.generate_content(
            [{"text": system_prompt}, {"text": user_prompt}],
            generation_config=generation_config,
        )
        return (resp.text or "").strip()


# ─── OpenAI Provider ────────────────────────────────────────────────────────


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise LLMError(
                    "openai not installed. Run: pip install openai"
                )
            api_key = os.environ.get(self.config.api_key_env or "OPENAI_API_KEY")
            if not api_key:
                raise LLMError(
                    f"API key env var '{self.config.api_key_env}' not set."
                )
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        client = self._get_client()
        temp = temperature if temperature is not None else self.config.temperature

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": temp,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()


# ─── OpenAI-Compatible Provider (local models) ──────────────────────────────


class OpenAICompatibleProvider(LLMProvider):
    """
    Provider for local models exposed via an OpenAI-compatible API.

    Supports vLLM, Ollama, text-generation-inference, LM Studio, etc.
    Configure via ``base_url`` in config (e.g., ``http://spark:8000/v1``).
    """

    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise LLMError(
                    "openai not installed. Run: pip install openai"
                )
            base_url = (
                self.config.base_url
                or os.environ.get("LOCAL_LLM_BASE_URL")
            )
            if not base_url:
                raise LLMError(
                    "base_url not configured and LOCAL_LLM_BASE_URL not set."
                )
            api_key = (
                os.environ.get(self.config.api_key_env)
                or os.environ.get("LOCAL_LLM_API_KEY")
                or "not-needed"  # many local servers don't require a key
            )
            self._client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url,
            )
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        client = self._get_client()
        temp = temperature if temperature is not None else self.config.temperature

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": temp,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()


# ─── TH Köln KI Connect Providers ───────────────────────────────────────────


class THKIProvider(OpenAICompatibleProvider):
    """
    Provider for TH Köln KI Connect models (chat.kiconnect.nrw).
    Automatically handles OpenAI compatibility, custom headers, token limits,
    and parameter quirks (max_completion_tokens vs max_tokens).
    """

    DEFAULT_BASE_URL = "https://chat.kiconnect.nrw/api/v1"

    def __init__(self, config: LLMProviderConfig):
        if not config.base_url:
            config.base_url = os.environ.get("THKI_BASE_URL", self.DEFAULT_BASE_URL)
        if not config.api_key_env:
            config.api_key_env = "THKI_KEY"
        super().__init__(config)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        client = self._get_client()
        temp = temperature if temperature is not None else self.config.temperature

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": temp,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        # Certain models (e.g. openai-gpt5.4-mini) require max_completion_tokens
        if "mini" in self.model.lower() or "gpt5" in self.model.lower():
            kwargs["max_completion_tokens"] = 1500
        else:
            kwargs["max_tokens"] = 1500

        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as err:
            err_str = str(err)
            if "max_completion_tokens" in err_str:
                kwargs.pop("max_tokens", None)
                kwargs["max_completion_tokens"] = 1500
                resp = client.chat.completions.create(**kwargs)
            elif "max_tokens" in err_str and "max_completion_tokens" in kwargs:
                kwargs.pop("max_completion_tokens", None)
                kwargs["max_tokens"] = 1500
                resp = client.chat.completions.create(**kwargs)
            else:
                raise

        choice = resp.choices[0].message
        content = choice.content or getattr(choice, "reasoning", None) or ""
        return content.strip()


class THKICascadeProvider(LLMProvider):
    """
    Smart Cascading Fallback Provider for TH Köln KI Connect.
    Cycles across the top fast models:
      1. openai-gpt5.4-mini (Fastest, highest quality)
      2. mistralai-mistral-small-4-119b-2603 (High throughput open-weights)
      3. qwen3-omni-30b-a3b-instruct (Lightweight compact instruct)
      4. openai-gpt-oss-120b (Backup 120B model)

    If model #1 hits HTTP 429 (rate/usage limit), 503 (service unavailable),
    or timeouts, it triggers a 60-second cooldown and automatically cascades
    to model #2, then model #3.
    """

    DEFAULT_MODELS = [
        "openai-gpt5.4-mini",
        "mistralai-mistral-small-4-119b-2603",
        "qwen3-omni-30b-a3b-instruct",
        "openai-gpt-oss-120b",
    ]

    def __init__(self, config: LLMProviderConfig, model_list: Optional[List[str]] = None):
        super().__init__(config)
        self.model_list = model_list or self.DEFAULT_MODELS
        self._providers: Dict[str, THKIProvider] = {}
        self._cooldowns: Dict[str, float] = {}

        for m in self.model_list:
            sub_cfg = LLMProviderConfig(
                name=f"thki-{m}",
                provider_type="thki",
                model=m,
                api_key_env=config.api_key_env or "THKI_KEY",
                base_url=config.base_url or THKIProvider.DEFAULT_BASE_URL,
                temperature=config.temperature,
                max_retries=1,
                timeout_s=config.timeout_s,
            )
            self._providers[m] = THKIProvider(sub_cfg)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        now = time.time()
        last_error = None

        for model_name in self.model_list:
            cooldown_until = self._cooldowns.get(model_name, 0)
            if now < cooldown_until:
                remaining = int(cooldown_until - now)
                logger.info(
                    "Skipping '%s' (on rate-limit cooldown for another %ds)",
                    model_name, remaining
                )
                continue

            provider = self._providers[model_name]
            try:
                logger.debug("Attempting LLM call via THKI model '%s'", model_name)
                result = provider.generate(
                    system_prompt,
                    user_prompt,
                    json_mode=json_mode,
                    temperature=temperature,
                )
                self.model = model_name
                return result
            except Exception as e:
                last_error = e
                err_text = str(e).lower()
                is_rate_limit = "429" in err_text or "quota" in err_text or "rate limit" in err_text
                is_unavailable = "503" in err_text or "timeout" in err_text or "temporarily unavailable" in err_text

                if is_rate_limit or is_unavailable:
                    self._cooldowns[model_name] = time.time() + 60.0
                    logger.warning(
                        "THKI model '%s' rate-limited/unavailable (%s). Cascading to next model...",
                        model_name, e
                    )
                else:
                    logger.warning("THKI model '%s' failed: %s. Cascading...", model_name, e)

        raise LLMError(f"All models in THKI cascade failed. Last error: {last_error}")


# ─── Registry ────────────────────────────────────────────────────────────────

_PROVIDER_TYPES = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "thki": THKIProvider,
    "thki_cascade": THKICascadeProvider,
}


class LLMRegistry:
    """Registry of named LLM provider instances."""

    def __init__(self):
        self._providers: Dict[str, LLMProvider] = {}

    def register(self, name: str, provider: LLMProvider):
        self._providers[name] = provider

    def get(self, name: str) -> LLMProvider:
        if name not in self._providers:
            raise KeyError(
                f"LLM provider '{name}' not registered. "
                f"Available: {list(self._providers.keys())}"
            )
        return self._providers[name]

    @classmethod
    def from_configs(
        cls, configs: Dict[str, LLMProviderConfig]
    ) -> "LLMRegistry":
        """Build a registry from a dict of provider configs."""
        registry = cls()
        for name, cfg in configs.items():
            provider_cls = _PROVIDER_TYPES.get(cfg.provider_type)
            if provider_cls is None:
                raise ValueError(
                    f"Unknown provider_type '{cfg.provider_type}' for "
                    f"provider '{name}'. "
                    f"Supported: {list(_PROVIDER_TYPES.keys())}"
                )
            registry.register(name, provider_cls(cfg))
        return registry

    @property
    def providers(self) -> Dict[str, LLMProvider]:
        return dict(self._providers)
