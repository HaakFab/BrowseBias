"""
Bias Engine — TH Köln KI Connect Model Discovery & Caching
===========================================================
Periodically checks for available models on TH Köln KI Connect (chat.kiconnect.nrw).
Ensures models are checked on startup if the last check is older than 14 days (2 weeks),
or whenever manually triggered by researchers.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_THKI_MODELS = [
    {
        "id": "openai-gpt5.4-mini",
        "name": "OpenAI GPT-5.4 Mini",
        "recommended": True,
        "note": "Fast, high reasoning accuracy, recommended for research runs"
    },
    {
        "id": "mistralai-mistral-small-4-119b-2603",
        "name": "Mistral Small 4 119B",
        "recommended": True,
        "note": "High throughput open-weights model"
    },
    {
        "id": "qwen3-omni-30b-a3b-instruct",
        "name": "Qwen 3 Omni 30B Instruct",
        "recommended": True,
        "note": "Compact instruct model"
    },
    {
        "id": "openai-gpt5.5",
        "name": "OpenAI GPT-5.5",
        "recommended": False,
        "note": "Advanced frontier model"
    },
    {
        "id": "openai-gpt-oss-120b",
        "name": "OpenAI GPT OSS 120B",
        "recommended": False,
        "note": "120B parameter dense model"
    },
    {
        "id": "glm-4.7",
        "name": "GLM 4.7",
        "recommended": False,
        "note": "Multilingual general-purpose"
    },
    {
        "id": "qwen3.5-397b-a17b",
        "name": "Qwen 3.5 397B",
        "recommended": False,
        "note": "MoE frontier model"
    }
]


def find_env_path() -> Path:
    """Locate the .env file in the project root."""
    cur = Path(__file__).resolve().parent.parent
    for candidate in [cur / ".env", cur.parent / ".env", Path.cwd() / ".env"]:
        if candidate.exists():
            return candidate
    return cur / ".env"


def update_env_variable(key: str, value: str) -> None:
    """Update or append an environment variable in the .env file and in os.environ."""
    os.environ[key] = value
    env_path = find_env_path()
    lines = []
    found = False

    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    if k.strip() == key:
                        new_lines.append(f"{key}={value}\n")
                        found = True
                        continue
                new_lines.append(line)
            lines = new_lines
        except Exception as e:
            logger.warning("Could not read .env to update %s: %s", key, e)

    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{key}={value}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        logger.warning("Could not write to .env to update %s: %s", key, e)


def fetch_remote_thki_models(api_key: str, base_url: str = "https://chat.kiconnect.nrw/api/v1") -> List[Dict[str, Any]]:
    """Fetch live available models from THKI API endpoint."""
    url = f"{base_url.rstrip('/')}/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key.strip()}",
        "User-Agent": "BrowseBias-Engine/1.1.0"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    raw_list = data.get("data", [])
    models: List[Dict[str, Any]] = []

    for item in raw_list:
        model_id = item.get("id", "")
        if not model_id:
            continue
        # Filter out purely embedding models
        if "embedding" in model_id.lower():
            continue

        # Format human-friendly name
        clean_name = model_id.replace("-", " ").title()
        is_rec = model_id in ["openai-gpt5.4-mini", "mistralai-mistral-small-4-119b-2603", "qwen3-omni-30b-a3b-instruct"]

        models.append({
            "id": model_id,
            "name": clean_name,
            "recommended": is_rec,
            "created": item.get("created"),
            "owned_by": item.get("owned_by", "th-koeln.de")
        })

    # Sort recommended first, then by id
    models.sort(key=lambda m: (not m["recommended"], m["id"]))
    return models


def check_and_update_thki_models(
    data_dir: Optional[Path] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Check if THKI models need refreshing (> 14 days or force=True).
    If so, queries THKI, caches to thki_models.json, and updates THKI_MODELS_LAST_CHECKED in .env.
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "server" / "data"

    data_dir.mkdir(parents=True, exist_ok=True)
    cache_file = data_dir / "thki_models.json"

    api_key = os.environ.get("THKI_KEY", "").strip()
    last_checked_str = os.environ.get("THKI_MODELS_LAST_CHECKED", "").strip()

    days_old = 999
    if last_checked_str:
        try:
            last_date = datetime.strptime(last_checked_str, "%Y-%m-%d").date()
            days_old = (date.today() - last_date).days
        except Exception:
            days_old = 999

    needs_refresh = force or (days_old > 14) or (not cache_file.exists())

    if not api_key:
        # No key: return cached or defaults
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    return cached_data
            except Exception:
                pass
        return {
            "last_checked": last_checked_str or "never",
            "days_old": days_old,
            "models": DEFAULT_THKI_MODELS,
            "source": "defaults_no_key"
        }

    if not needs_refresh and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                cached_data["days_old"] = days_old
                return cached_data
        except Exception as e:
            logger.warning("Could not read thki_models.json cache: %s", e)

    # Fetch fresh models
    today_str = date.today().isoformat()
    try:
        live_models = fetch_remote_thki_models(api_key)
        if not live_models:
            live_models = DEFAULT_THKI_MODELS
        
        result_payload = {
            "last_checked": today_str,
            "days_old": 0,
            "models": live_models,
            "source": "live_api"
        }

        # Save cache
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result_payload, f, indent=2, ensure_ascii=False)

        # Update .env
        update_env_variable("THKI_MODELS_LAST_CHECKED", today_str)
        logger.info("Successfully refreshed THKI models list (%d models found, updated %s).", len(live_models), today_str)
        return result_payload

    except Exception as err:
        logger.warning("Failed to refresh THKI models from API: %s. Using fallback cache.", err)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "last_checked": last_checked_str or "fallback",
            "days_old": days_old,
            "models": DEFAULT_THKI_MODELS,
            "source": "fallback_on_error",
            "error": str(err)
        }
