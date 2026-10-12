"""
Bias Engine — Persistence & State Management
==============================================
Atomic file operations, backup rotation, and state persistence for
PCMs, BT scores, and engine metadata.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import EngineConfig
from .framework import BiasFramework
from .pairwise_matrix import PairwiseMatrix
from .score_store import ScoreStore

logger = logging.getLogger(__name__)


def atomic_write_json(filepath: str, data: Any, indent: int = 2) -> None:
    """
    Atomically write JSON data to file via temporary file + atomic rename.
    Prevents file corruption if process is killed mid-write.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as tf:
        json.dump(data, tf, indent=indent, ensure_ascii=False)
        tf.flush()
        os.fsync(tf.fileno())
        temp_name = tf.name

    os.replace(temp_name, filepath)


def backup_rotate(filepath: str, max_backups: int = 3) -> None:
    """
    Rotate existing file backups: file.bak.2 -> file.bak.3, file.bak.1 -> file.bak.2, file -> file.bak.1
    """
    if not os.path.exists(filepath):
        return

    for i in range(max_backups - 1, 0, -1):
        src = f"{filepath}.bak.{i}"
        dst = f"{filepath}.bak.{i+1}"
        if os.path.exists(src):
            shutil.copy2(src, dst)

    dst_1 = f"{filepath}.bak.1"
    shutil.copy2(filepath, dst_1)


class StateManager:
    """
    Manages loading and persisting all engine state (PCMs, BT scores, ScoreStore).
    """

    def __init__(self, config: EngineConfig, framework: BiasFramework):
        self.config = config
        self.framework = framework
        self.config.ensure_dirs()

    # ── PCM Persistence ──────────────────────────────────────────────────

    def pcm_path(self, model: str, category: str) -> str:
        safe_model = model.replace("/", "_").replace(":", "_")
        model_dir = os.path.join(self.config.pcm_dir, safe_model)
        os.makedirs(model_dir, exist_ok=True)
        return os.path.join(model_dir, f"{category}.json")

    def save_pcm(self, pcm: PairwiseMatrix) -> None:
        """Save a single model's PCM for a category atomically."""
        path = self.pcm_path(pcm.model, pcm.category)
        backup_rotate(path)
        atomic_write_json(path, pcm.to_dict())

    def load_pcm(self, model: str, category: str) -> PairwiseMatrix:
        """Load a PCM from disk, or return empty PCM if not found."""
        path = self.pcm_path(model, category)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return PairwiseMatrix.from_dict(data)
            except Exception as e:
                logger.error("Failed to load PCM from '%s': %s", path, e)
        return PairwiseMatrix(category=category, model=model)

    def load_all_pcms_for_category(self, category: str) -> List[PairwiseMatrix]:
        """Discover and load all per-model PCMs for a given category."""
        pcms = []
        pcm_root = Path(self.config.pcm_dir)
        if not pcm_root.exists():
            return pcms

        for model_dir in pcm_root.iterdir():
            if model_dir.is_dir():
                target_file = model_dir / f"{category}.json"
                if target_file.exists():
                    try:
                        with open(target_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        pcms.append(PairwiseMatrix.from_dict(data))
                    except Exception as e:
                        logger.error("Error reading PCM from %s: %s", target_file, e)
        return pcms

    # ── Bradley-Terry Scores Persistence ─────────────────────────────────

    def bt_scores_path(self, category: str) -> str:
        return os.path.join(self.config.bt_scores_dir, f"{category}.json")

    def save_bt_scores(self, category: str, scores: Dict[str, float]) -> None:
        path = self.bt_scores_path(category)
        backup_rotate(path)
        atomic_write_json(path, {"category": category, "scores": scores})

    def load_bt_scores(self, category: str) -> Dict[str, float]:
        path = self.bt_scores_path(category)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {k: float(v) for k, v in data.get("scores", {}).items()}
            except Exception as e:
                logger.error("Failed to load BT scores from '%s': %s", path, e)
        return {}

    # ── ScoreStore & Lexicon Output ──────────────────────────────────────

    def save_lexicon(self, score_store: ScoreStore) -> None:
        """Write out the production lexicon.json used by the plugin."""
        path = self.config.lexicon_file
        backup_rotate(path)
        # Writes the rich format with scores, maxScore, level, mouseover
        atomic_write_json(path, score_store.to_lexicon_dict())

    def load_score_store(self) -> ScoreStore:
        """Construct ScoreStore and populate from persisted category BT scores."""
        store = ScoreStore(self.framework)
        for cat in self.framework.categories:
            scores = self.load_bt_scores(cat.key)
            store.bulk_update_category_scores(cat.key, scores)
        return store
