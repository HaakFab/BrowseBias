"""
Configuration settings for Autocomplete Bias Collector
"""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent

# Auto-locate extension directory
def _find_extension_dir() -> Path:
    if "EXTENSION_PATH" in os.environ:
        return Path(os.environ["EXTENSION_PATH"])
    if (BASE_DIR.parent / "plugin" / "manifest.json").exists():
        return BASE_DIR.parent / "plugin"
    if (BASE_DIR.parent / "Bias_Browser_Plugin" / "plugin" / "manifest.json").exists():
        return BASE_DIR.parent / "Bias_Browser_Plugin" / "plugin"
    if (BASE_DIR.parent / "manifest.json").exists():
        return BASE_DIR.parent
    if (BASE_DIR.parent / "Bias_Browser_Plugin" / "manifest.json").exists():
        return BASE_DIR.parent / "Bias_Browser_Plugin"
    return BASE_DIR.parent / "plugin"

EXTENSION_PATH = str(_find_extension_dir().resolve())
KEYWORDS_FILE = os.environ.get("KEYWORDS_FILE", str(BASE_DIR / "keywords.txt"))
USER_DATA_DIR = os.environ.get("USER_DATA_DIR", str(BASE_DIR / "browser_profile"))

# Google Target & Language
GOOGLE_URL = os.environ.get("GOOGLE_URL", "https://www.google.de")
BROWSER_LANG = os.environ.get("BROWSER_LANG", "de-DE")

# Human-like Typing Simulation Parameters
TYPING_DELAY_MIN_MS = int(os.environ.get("TYPING_DELAY_MIN_MS", 45))
TYPING_DELAY_MAX_MS = int(os.environ.get("TYPING_DELAY_MAX_MS", 110))

# Pause after typing root/typo query before alphabet expansion
SUGGESTION_WAIT_MS = int(os.environ.get("SUGGESTION_WAIT_MS", 500))

# Alphabet expansion: 'query a', 'query b', ... 'query z'
ALPHABET_CYCLE = os.environ.get("ALPHABET_CYCLE", "true").lower() in ("true", "1", "yes")
ALPHABET_CHARS = "abcdefghijklmnopqrstuvwxyz"
ALPHABET_WAIT_MS = int(os.environ.get("ALPHABET_WAIT_MS", 450))

# Typo Generation
TYPOS_PER_KEYWORD = int(os.environ.get("TYPOS_PER_KEYWORD", 0))

# Pause between queries (to avoid aggressive rate limiting)
PAUSE_BETWEEN_QUERIES_S = float(os.environ.get("PAUSE_BETWEEN_QUERIES_S", 1.5))

# Simulation Speed Preset ('ultra-fast', 'fast', 'normal', 'relaxed')
SIMULATION_SPEED = os.environ.get("SIMULATION_SPEED", "normal")

# Server Target
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8765/api/upload")

# Pseudonym Management & Persistence
PSEUDONYM_FILE = BASE_DIR / "pseudonym.txt"

ADJECTIVES = [
    'Curious', 'Swift', 'Silent', 'Bright', 'Amber', 'Cosmic', 'Lunar', 'Solar',
    'Silver', 'Alpine', 'Brave', 'Calm', 'Clever', 'Gentle', 'Jovial', 'Keen',
    'Noble', 'Quick', 'Rustic', 'Vibrant', 'Astral', 'Zenith', 'Polar', 'Mossy'
]
ANIMALS = [
    'Fox', 'Otter', 'Falcon', 'Badger', 'Panda', 'Lynx', 'Dolphin', 'Hawk',
    'Koala', 'Raven', 'Beaver', 'Osprey', 'Tiger', 'Robin', 'Wolf', 'Jaguar',
    'Heron', 'Finch', 'Crane', 'Orca', 'Seal', 'Ibex', 'Marten', 'Quokka'
]

import random

def generate_pseudonym() -> str:
    """Generate a randomized anonymous auditor tag matching the browser extension."""
    adj = random.choice(ADJECTIVES)
    animal = random.choice(ANIMALS)
    num = random.randint(10, 99)
    return f"{adj}-{animal}-{num}"

def get_or_create_pseudonym() -> str:
    """Load persisted auditor pseudonym from disk or generate and persist a new one."""
    if PSEUDONYM_FILE.exists():
        try:
            val = PSEUDONYM_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass
    tag = generate_pseudonym()
    try:
        PSEUDONYM_FILE.write_text(tag, encoding="utf-8")
    except Exception:
        pass
    return tag

# Restart & Upload Pacing
RESTART_EVERY_KEYWORDS = int(os.environ.get("RESTART_EVERY_KEYWORDS", 10))
FLUSH_EVERY_KEYWORDS = int(os.environ.get("FLUSH_EVERY_KEYWORDS", 5))

# Browser Options
HEADLESS = False  # Chrome extensions require headful mode
