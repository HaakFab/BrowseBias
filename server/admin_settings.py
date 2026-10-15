"""
BrowseBias — Admin Settings, Taxonomy & Cohort Versioning
=========================================================
Handles:
- Dynamic Earth Epoch version switching and dataset archival
- Framework bias categories editor & persistence (framework.yaml)
- Prompt customization and interactive LLM prompt evaluation
- Pairwise & matchmaking parameters persistence (engine_config.json)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from bias_engine.epochs import EARTH_EPOCHS, get_next_epoch
from bias_engine.framework import BiasCategory, BiasFramework, get_default_framework

logger = logging.getLogger(__name__)

DEFAULT_IDENTIFICATION_PROMPT = (
    "You are an expert annotator for search autocomplete bias.\n"
    "Classify each numbered suggestion template across the following categories:\n\n"
    "{categories_def}\n\n"
    "You MUST return a pure JSON object with a 'results' array where each element has 'i' (integer index) "
    "and 0/1 indicators for each category: {keys_schema}.\n"
    "Example format:\n"
    "{\"results\": [{\"i\": 0, {example_format}}]}\n"
    "Do NOT include explanations or markdown prose. Return pure JSON."
)

DEFAULT_QUANTIFICATION_PROMPT = (
    "You are an expert in analyzing {category_name} in search autocomplete suggestions.\n"
    "Definition of {category_name}:\n"
    "\"{category_definition}\"\n\n"
    "You will receive K suggestion texts, each with a numeric id 0..K-1.\n"
    "Rank them from MOST exhibiting {category_name} to LEAST.\n"
    "Return ONLY a strict JSON object with an 'order' array containing the numeric ids:\n"
    "{\"order\": [id0, id1, ...]}\n"
    "- The list MUST contain each id exactly once (a permutation of 0..K-1).\n"
    "- If two items are equally exhibiting this bias, break ties by smaller id.\n"
    "Do NOT include any text content, notes, or explanations in your output."
)


# ─── Earth Epochs & Cohort Archiving ─────────────────────────────────────────

def get_server_config_path(data_dir: str) -> str:
    return os.path.join(data_dir, "server_config.json")


def get_active_version_tag(data_dir: str) -> str:
    cfg_file = get_server_config_path(data_dir)
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("active_version_tag", "Silurian")
        except Exception:
            pass
    return "Silurian"


def get_version_status(data_dir: str) -> Dict[str, Any]:
    active_tag = get_active_version_tag(data_dir)
    next_tag = get_next_epoch(active_tag)
    archives = list_archives(data_dir)

    # Count current items
    uploads_file = os.path.join(data_dir, "uploads.jsonl")
    suggs_file = os.path.join(data_dir, "suggestions.jsonl")
    reports_file = os.path.join(data_dir, "reports.jsonl")

    current_uploads = 0
    if os.path.exists(uploads_file):
        try:
            with open(uploads_file, "r", encoding="utf-8") as f:
                current_uploads = sum(1 for line in f if line.strip())
        except Exception:
            pass

    current_suggestions = 0
    if os.path.exists(suggs_file):
        try:
            with open(suggs_file, "r", encoding="utf-8") as f:
                current_suggestions = sum(1 for line in f if line.strip())
        except Exception:
            pass

    return {
        "active_version_tag": active_tag,
        "next_suggested_epoch": next_tag,
        "current_uploads_count": current_uploads,
        "current_suggestions_count": current_suggestions,
        "all_epochs": EARTH_EPOCHS,
        "archives": archives,
    }


def switch_version_tag(data_dir: str, new_tag: str) -> Dict[str, Any]:
    """Archive current dataset cohort and start clean state with new_tag strictly on command."""
    if not new_tag or not new_tag.strip():
        raise ValueError("New version tag cannot be empty.")
    new_tag = new_tag.strip()

    old_tag = get_active_version_tag(data_dir)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archive_dir = os.path.join(data_dir, "archives")
    os.makedirs(archive_dir, exist_ok=True)

    archive_filename = f"browsebias_{old_tag}_{ts}.zip"
    archive_path = os.path.join(archive_dir, archive_filename)

    uploads_file = os.path.join(data_dir, "uploads.jsonl")
    suggs_file = os.path.join(data_dir, "suggestions.jsonl")
    reports_file = os.path.join(data_dir, "reports.jsonl")
    lexicon_file = os.path.join(data_dir, "lexicon.json")

    # 1. Package into ZIP archive
    archived_files_count = 0
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath, arcname in [
            (uploads_file, f"uploads_{old_tag}.jsonl"),
            (suggs_file, f"suggestions_{old_tag}.jsonl"),
            (reports_file, f"reports_{old_tag}.jsonl"),
            (lexicon_file, f"lexicon_{old_tag}.json"),
        ]:
            if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                zf.write(fpath, arcname=arcname)
                archived_files_count += 1

        readme = (
            f"BrowseBias Archived Cohort: {old_tag}\n"
            f"Archived at: {datetime.utcnow().isoformat()}Z\n"
            f"Next Cohort Tag: {new_tag}\n"
        )
        zf.writestr("ARCHIVE_INFO.txt", readme)

    # 2. Reset active dataset files to fresh empty files for clean new run
    for fpath in [uploads_file, suggs_file, reports_file]:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("")

    # 3. Save new tag and register archive
    cfg_file = get_server_config_path(data_dir)
    cfg = {}
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    cfg["active_version_tag"] = new_tag
    cfg["last_archived_tag"] = old_tag
    cfg["last_archived_at"] = datetime.utcnow().isoformat() + "Z"

    archives_list = cfg.get("archives", [])
    archives_list.append({
        "epoch": old_tag,
        "filename": archive_filename,
        "archived_at": cfg["last_archived_at"],
        "size_bytes": os.path.getsize(archive_path) if os.path.exists(archive_path) else 0,
    })
    cfg["archives"] = archives_list

    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    archive_size = os.path.getsize(archive_path) if os.path.exists(archive_path) else 0

    return {
        "status": "ok",
        "previous_version_tag": old_tag,
        "active_version_tag": new_tag,
        "next_suggested_epoch": get_next_epoch(new_tag),
        "archive_file": archive_filename,
        "archive_filename": archive_filename,
        "archive_path": archive_path,
        "archive_size_bytes": archive_size,
        "archive_url": f"/api/download/archive/{archive_filename}",
        "message": f"Successfully archived cohort '{old_tag}' and initialized clean dataset for '{new_tag}'.",
    }


def list_archives(data_dir: str) -> List[Dict[str, Any]]:
    archive_dir = os.path.join(data_dir, "archives")
    if not os.path.exists(archive_dir):
        return []

    items = []
    for fname in os.listdir(archive_dir):
        if fname.endswith(".zip"):
            fpath = os.path.join(archive_dir, fname)
            stat = os.stat(fpath)
            # Parse epoch from browsebias_{epoch}_{ts}.zip
            epoch_tag = "Archive"
            if fname.startswith("browsebias_"):
                parts = fname[:-4].split("_")
                if len(parts) >= 2:
                    epoch_tag = parts[1]

            items.append({
                "filename": fname,
                "epoch_tag": epoch_tag,
                "size_bytes": stat.st_size,
                "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                "download_url": f"/api/download/archive/{fname}",
            })

    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


# ─── Bias Categories & Framework (YAML) ──────────────────────────────────────

def get_framework_file(data_dir: str) -> str:
    return os.path.join(data_dir, "framework.yaml")


def load_categories(data_dir: str) -> Dict[str, Any]:
    fw_path = get_framework_file(data_dir)
    if os.path.exists(fw_path):
        try:
            fw = load_framework(fw_path)
            cats = []
            for c in fw.categories:
                cats.append({
                    "key": c.key,
                    "short_code": getattr(c, "short_key", c.key[:3]).upper(),
                    "short_key": getattr(c, "short_key", c.key[:3]),
                    "name": c.name,
                    "definition": c.definition,
                    "enabled": True,
                    "mouseover_template": getattr(c, "mouseover_template", "This suggestion shows {name} (score: {score:.2f})."),
                })
            return {"name": fw.name, "categories": cats}
        except Exception as e:
            logger.warning("Failed to load custom framework.yaml, falling back to default: %s", e)

    default_fw = get_default_framework()
    cats = []
    for c in default_fw.categories:
        cats.append({
            "key": c.key,
            "short_code": c.short_key.upper(),
            "short_key": c.short_key,
            "name": c.name,
            "definition": c.definition,
            "enabled": True,
            "mouseover_template": c.mouseover_template,
        })
    return {"name": default_fw.name, "categories": cats}


def save_categories(data_dir: str, categories_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    fw_path = get_framework_file(data_dir)
    os.makedirs(os.path.dirname(fw_path), exist_ok=True)

    formatted_cats = []
    for c in categories_data:
        sk = c.get("short_key") or c.get("short_code") or c["key"][:3]
        formatted_cats.append({
            "key": c["key"],
            "short_key": str(sk).lower(),
            "name": c["name"],
            "definition": c["definition"],
            "mouseover_template": c.get("mouseover_template", "This suggestion shows {name} (score: {score:.2f})."),
            "enabled": c.get("enabled", True),
        })

    yaml_data = {
        "name": "autocomplete_bias_custom",
        "description": "Customized multi-category bias framework for search autocomplete.",
        "categories": formatted_cats,
    }

    with open(fw_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, sort_keys=False, allow_unicode=True)

    return {
        "status": "ok",
        "categories_count": len(formatted_cats),
        "path": fw_path,
        "message": f"Saved {len(formatted_cats)} categories to framework.yaml.",
    }


# ─── Prompt Customization & Interactive Playground ────────────────────────────

def get_prompts_file(data_dir: str) -> str:
    return os.path.join(data_dir, "prompts.json")


def load_prompts(data_dir: str) -> Dict[str, str]:
    ident = DEFAULT_IDENTIFICATION_PROMPT
    quant = DEFAULT_QUANTIFICATION_PROMPT
    p_file = get_prompts_file(data_dir)
    if os.path.exists(p_file):
        try:
            with open(p_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                ident = data.get("identification_prompt") or data.get("identification_system_prompt") or ident
                quant = data.get("quantification_prompt") or data.get("quantification_system_prompt") or quant
        except Exception:
            pass

    return {
        "identification_prompt": ident,
        "identification_system_prompt": ident,
        "quantification_prompt": quant,
        "quantification_system_prompt": quant,
    }


def save_prompts(data_dir: str, *args, **kwargs) -> Dict[str, Any]:
    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], str):
        ident, quant = args[0], args[1]
    elif len(args) == 1 and isinstance(args[0], dict):
        ident = args[0].get("identification_prompt") or args[0].get("identification_system_prompt")
        quant = args[0].get("quantification_prompt") or args[0].get("quantification_system_prompt")
    else:
        ident = kwargs.get("identification_prompt") or kwargs.get("identification_system_prompt", DEFAULT_IDENTIFICATION_PROMPT)
        quant = kwargs.get("quantification_prompt") or kwargs.get("quantification_system_prompt", DEFAULT_QUANTIFICATION_PROMPT)

    p_file = get_prompts_file(data_dir)
    os.makedirs(os.path.dirname(p_file), exist_ok=True)
    payload = {
        "identification_prompt": ident,
        "identification_system_prompt": ident,
        "quantification_prompt": quant,
        "quantification_system_prompt": quant,
    }
    with open(p_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return payload


def reset_prompts(data_dir: str) -> Dict[str, str]:
    p_file = get_prompts_file(data_dir)
    if os.path.exists(p_file):
        try:
            os.remove(p_file)
        except Exception:
            pass
    return {
        "identification_prompt": DEFAULT_IDENTIFICATION_PROMPT,
        "identification_system_prompt": DEFAULT_IDENTIFICATION_PROMPT,
        "quantification_prompt": DEFAULT_QUANTIFICATION_PROMPT,
        "quantification_system_prompt": DEFAULT_QUANTIFICATION_PROMPT,
    }


def test_prompt_evaluation(
    data_dir: str,
    suggestion_text: str = "",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    custom_system_prompt: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Test the identification prompt on a single suggestion using the specified LLM."""
    from bias_engine.llm_providers import create_provider_for_model
    import re

    p_name = provider or provider_name or ("thki" if os.environ.get("THKI_KEY") else "gemini")
    m_name = model or model_name or ("openai-gpt5.4-mini" if os.environ.get("THKI_KEY") else "gemini-3.5-flash-lite")
    text = suggestion_text or kwargs.get("text", "")

    cats_res = load_categories(data_dir)
    cats = cats_res.get("categories", []) if isinstance(cats_res, dict) else cats_res
    cat_defs = [f"- '{c.get('short_key', c.get('key', '')[:1])}' ({c.get('name')}): {c.get('definition', '')}" for c in cats]
    short_keys = [f'"{c.get("short_key", c.get("key", "")[:1])}": 0 or 1' for c in cats]
    example_fmt = ", ".join([f'"{c.get("short_key", c.get("key", "")[:1])}": 0' for c in cats])

    sys_template = custom_system_prompt or load_prompts(data_dir)["identification_system_prompt"]
    system_prompt = (
        sys_template
        .replace("{categories_def}", "\n".join(cat_defs))
        .replace("{keys_schema}", ", ".join(short_keys))
        .replace("{example_format}", example_fmt)
    )

    user_prompt = f"Suggestions:\n0: {repr(text)}"

    prov = create_provider_for_model(p_name, m_name)
    start_time = time.time()
    raw_response = prov.complete(system_prompt, user_prompt)
    elapsed_ms = round((time.time() - start_time) * 1000)

    # Clean code fences if any
    cleaned_resp = raw_response.strip()
    if "```" in cleaned_resp:
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned_resp, re.DOTALL | re.IGNORECASE)
        if m:
            cleaned_resp = m.group(1).strip()
        else:
            cleaned_resp = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned_resp)
            cleaned_resp = re.sub(r"\n?```$", "", cleaned_resp).strip()

    parsed = None
    parse_error = None
    try:
        parsed = json.loads(cleaned_resp)
    except Exception as e:
        parse_error = str(e)

    return {
        "status": "ok",
        "provider": provider_name,
        "model": model_name,
        "suggestion": suggestion_text,
        "elapsed_ms": elapsed_ms,
        "system_prompt": system_prompt,
        "raw_response": raw_response,
        "parsed": parsed,
        "parse_error": parse_error,
    }


# ─── Matchmaking & Engine Parameters Overrides ───────────────────────────────

def get_engine_config_overrides(data_dir: str) -> Dict[str, Any]:
    override_file = os.path.join(data_dir, "engine_config.json")
    defaults = {
        "listwise_group_size": 10,
        "new_item_groups": 3,
        "matchmaking_strategy": "stratified",
        "similar_score_jitter": 0.05,
        "bt_regularization": 0.01,
    }
    if os.path.exists(override_file):
        try:
            with open(override_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    defaults.update(data)
        except Exception:
            pass
    return defaults


def save_engine_config_overrides(data_dir: str, config_data: Dict[str, Any]) -> Dict[str, Any]:
    override_file = os.path.join(data_dir, "engine_config.json")
    current = get_engine_config_overrides(data_dir)
    for k, v in config_data.items():
        if k in current:
            current[k] = v

    with open(override_file, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)

    return {"status": "ok", "config": current, "message": "Updated pairwise comparison and matchmaking parameters."}
