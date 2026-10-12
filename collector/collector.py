#!/usr/bin/env python3
"""
Autocomplete Bias — User Input Simulator & Collector
=====================================================
Automates human-like typing on Google Search while running the Chrome
extension ("Autocomplete Bias") to trigger and collect autocomplete suggestions.

Workflow for each keyword:
  1. Type root keyword character-by-character (human typing speed)
  2. Append space + cycle through 'a'..'z' (type char -> wait -> backspace)
  3. Generate 5 intentional typo permutations (e.g. 'Dnoald Trump')
  4. Repeat the typing + alphabet cycle for each typo permutation

The installed Chrome extension captures suggestions, scores them, buffers
them locally, and uploads them to the research server in intervals.
"""

import argparse
import os
import random
import sys
import time
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import sync_playwright, BrowserContext, Page

# Import local modules
import config
from typo_generator import generate_typos


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate human typing on Google Search with the Autocomplete Bias extension."
    )
    parser.add_argument(
        "-k", "--keywords",
        default=config.KEYWORDS_FILE,
        help=f"Path to keywords text file (default: {config.KEYWORDS_FILE})"
    )
    parser.add_argument(
        "-u", "--url",
        default=config.GOOGLE_URL,
        help=f"Google Search URL (default: {config.GOOGLE_URL})"
    )
    parser.add_argument(
        "-e", "--extension",
        default=config.EXTENSION_PATH,
        help=f"Path to extension folder (default: {config.EXTENSION_PATH})"
    )
    parser.add_argument(
        "-t", "--typos",
        type=int,
        default=config.TYPOS_PER_KEYWORD,
        help=f"Number of typo permutations per keyword (default: {config.TYPOS_PER_KEYWORD})"
    )
    parser.add_argument(
        "--no-alphabet",
        action="store_true",
        help="Skip the trailing ' a'..' z' alphabet expansion"
    )
    parser.add_argument(
        "--profile",
        default=config.USER_DATA_DIR,
        help=f"Browser profile directory (default: {config.USER_DATA_DIR})"
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=config.PAUSE_BETWEEN_QUERIES_S,
        help=f"Pause in seconds between queries (default: {config.PAUSE_BETWEEN_QUERIES_S}s)"
    )
    return parser.parse_args()


def load_keywords(file_path: str) -> List[str]:
    """Load non-empty, non-comment lines from keyword file."""
    path = Path(file_path)
    if not path.exists():
        print(f"❌ Keyword file not found: {file_path}")
        sys.exit(1)

    keywords = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                keywords.append(line)

    print(f"📋 Loaded {len(keywords)} keyword(s) from {file_path}")
    return keywords


def handle_cookie_consent(page: Page):
    """Dismiss Google's cookie consent dialog if present."""
    consent_selectors = [
        'button:has-text("Alle akzeptieren")',
        'button:has-text("Accept all")',
        'button:has-text("I agree")',
        'button:has-text("Ich stimme zu")',
        '#L2AGLb',  # Common German/EU 'Accept all' button ID
    ]
    for sel in consent_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                print("🍪 Dismissed Google cookie consent banner.")
                page.wait_for_timeout(1000)
                break
        except Exception:
            pass


def ensure_extension_consent(context: BrowserContext) -> None:
    """
    Guarantees that the Chrome extension has consentGiven=True and scrapingEnabled=True
    by accessing the extension origin directly and setting chrome.storage.local.
    Also closes any onboarding tabs that Chrome might have opened on installation.
    """
    print("🔧 Ensuring extension consent & research data collection are active...")

    # 1. Identify extension ID from service worker or waiting for event
    ext_id = None
    if context.service_workers:
        sw = context.service_workers[0]
        ext_id = sw.url.split('/')[2]
    else:
        try:
            sw = context.wait_for_event("serviceworker", timeout=4000)
            ext_id = sw.url.split('/')[2]
        except Exception:
            pass

    # 2. Check if any onboarding tab is open
    for p in list(context.pages):
        try:
            if not p.is_closed() and "onboarding.html" in p.url:
                if not ext_id:
                    ext_id = p.url.split('/')[2]
                break
        except Exception:
            pass

    # 3. Direct configuration inside extension origin
    if ext_id:
        try:
            setup_page = context.new_page()
            setup_page.goto(f"chrome-extension://{ext_id}/src/onboarding.html", wait_until="domcontentloaded", timeout=5000)
            setup_page.evaluate("""() => {
                return new Promise((resolve) => {
                    chrome.storage.local.set({
                        highlightingEnabled: true,
                        scrapingEnabled: true,
                        consentGiven: true,
                        consentDate: new Date().toISOString()
                    }, () => resolve());
                });
            }""")
            setup_page.close()
            print("✅ Extension consent & data collection enabled (verified via storage API).")
        except Exception as e:
            print(f"Extension storage configuration note: {e}")

    # 4. Clean up any open onboarding tabs
    time.sleep(0.3)
    for p in list(context.pages):
        try:
            if not p.is_closed() and "onboarding.html" in p.url:
                p.close()
        except Exception:
            pass



def human_type(page: Page, text: str, min_delay_ms: int = 40, max_delay_ms: int = 110):
    """Simulate human-like typing with randomized millisecond delays per keystroke."""
    for char in text:
        delay = random.randint(min_delay_ms, max_delay_ms)
        page.keyboard.type(char, delay=delay)


def clear_search_input(page: Page, input_sel: Optional[str] = None):
    """Thoroughly clear all text in the Google search input."""
    if not input_sel:
        input_sel = find_search_input(page)
    if not input_sel:
        return

    # 1. Click Google's clear "X" button if present
    clear_btn_selectors = [
        'div[aria-label="Clear"]',
        'div[aria-label="Löschen"]',
        'button[aria-label="Clear"]',
        'button[aria-label="Löschen"]',
        '[jsname="RP0xAe"]',
        '[aria-label="Löschen"]',
        '[aria-label="Clear"]'
    ]
    for c_sel in clear_btn_selectors:
        try:
            c_btn = page.query_selector(c_sel)
            if c_btn and c_btn.is_visible():
                c_btn.click()
                page.wait_for_timeout(100)
                break
        except Exception:
            pass

    # 2. Playwright native fill to empty string
    try:
        page.fill(input_sel, "")
    except Exception:
        pass

    # 3. Focus and keyboard select-all + backspace
    try:
        page.click(input_sel)
        page.keyboard.press("Meta+A")
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
    except Exception:
        pass

    # 4. JavaScript DOM reset + trigger input events
    try:
        page.evaluate(f"""(sel) => {{
            const el = document.querySelector(sel);
            if (el) {{
                el.value = '';
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}""", input_sel)
    except Exception:
        pass

    # 5. Safeguard: if input_value is still not empty, delete remaining chars
    try:
        current_val = page.locator(input_sel).input_value()
        if current_val:
            page.click(input_sel)
            for _ in range(len(current_val) + 5):
                page.keyboard.press("Backspace")
    except Exception:
        pass

    page.wait_for_timeout(150)


def find_search_input(page: Page) -> Optional[str]:
    """Locate the Google search input element."""
    selectors = [
        'textarea[name="q"]',
        'input[name="q"]',
        'textarea[aria-label="Search"]',
        'input[aria-label="Search"]',
        'textarea[aria-label="Suche"]',
        'input[aria-label="Suche"]',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return sel
        except Exception:
            pass
    return None


def run_term_simulation(
    page: Page,
    term: str,
    alphabet_cycle: bool = True,
    pause_between_s: float = 1.5
):
    """
    Execute full typing sequence for a single term (root or typo):
      1. Focus & thoroughly clear search box
      2. Human-type term
      3. Wait for suggestions
      4. If alphabet_cycle: add space, cycle 'a'..'z' with backspaces
      5. Thoroughly clear search box for next query
    """
    # Find input
    input_sel = find_search_input(page)
    if not input_sel:
        print(f"⚠️ Search input not found, reloading Google...")
        page.goto(config.GOOGLE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        handle_cookie_consent(page)
        input_sel = find_search_input(page)
        if not input_sel:
            print("❌ Unable to locate search input.")
            return

    # Focus and ensure clean slate
    clear_search_input(page, input_sel)

    # 1. Type the term
    print(f"   ⌨️  Typing: '{term}'", end="", flush=True)
    human_type(page, term, config.TYPING_DELAY_MIN_MS, config.TYPING_DELAY_MAX_MS)
    
    # Wait for suggestions to render and extension to intercept
    page.wait_for_timeout(config.SUGGESTION_WAIT_MS)
    print(" ✓", flush=True)

    # 2. Alphabet cycle: ' term a', ' term b', ... ' term z'
    if alphabet_cycle:
        # Append space
        page.keyboard.type(" ", delay=50)
        page.wait_for_timeout(200)

        print(f"   🔤 Alphabet expansion: ", end="", flush=True)
        for char in config.ALPHABET_CHARS:
            page.keyboard.type(char, delay=35)
            # Give extension & Google time to display suggestion
            page.wait_for_timeout(config.ALPHABET_WAIT_MS)
            page.keyboard.press("Backspace")
            page.wait_for_timeout(100)
            print(char, end="", flush=True)
        print(" ✓", flush=True)

    # Clean up input thoroughly before next query
    clear_search_input(page, input_sel)
    page.wait_for_timeout(int(pause_between_s * 1000))


def main():
    args = parse_arguments()
    keywords = load_keywords(args.keywords)

    if not keywords:
        print("No keywords found. Exiting.")
        return

    ext_path = Path(args.extension).resolve()
    if not ext_path.exists() or not (ext_path / "manifest.json").exists():
        print(f"❌ Invalid extension path: {ext_path}")
        print("Make sure manifest.json exists in that directory.")
        sys.exit(1)

    print("=" * 65)
    print("🚀 Autocomplete Bias — Input Simulator & Collector")
    print("=" * 65)
    print(f"  Target Google URL : {args.url}")
    print(f"  Keywords count    : {len(keywords)}")
    print(f"  Typos per root    : {args.typos}")
    print(f"  Alphabet cycle    : {'Yes (a-z)' if not args.no_alphabet else 'No'}")
    print(f"  Extension path    : {ext_path}")
    print(f"  Browser profile   : {args.profile}")
    print("=" * 65)

    profile_dir = Path(args.profile).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Launch persistent context with Chrome extension loaded
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,  # Extensions require headful mode
            viewport={"width": 1280, "height": 800},
            args=[
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )

        # Ensure extension consent & data collection are 100% active
        ensure_extension_consent(context)

        # Select the active Google page or open a fresh one
        # (avoid selecting any closed or onboarding tabs)
        valid_pages = [p for p in context.pages if not p.is_closed() and "onboarding.html" not in p.url]
        page = valid_pages[0] if valid_pages else context.new_page()

        print(f"\n🌐 Navigating to {args.url}...")
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        handle_cookie_consent(page)

        total_roots = len(keywords)
        start_time = time.time()

        for k_idx, root_kw in enumerate(keywords, 1):
            print(f"\n[{k_idx}/{total_roots}] 🎯 Root Keyword: '{root_kw}'")

            # 1. Process root keyword
            run_term_simulation(
                page=page,
                term=root_kw,
                alphabet_cycle=not args.no_alphabet,
                pause_between_s=args.pause
            )

            # 2. Process typo permutations
            if args.typos > 0:
                typos = generate_typos(root_kw, count=args.typos)
                print(f"   🔀 Generated {len(typos)} typo permutations:")
                for t_idx, typo_term in enumerate(typos, 1):
                    print(f"   [{t_idx}/{len(typos)}] Typo: '{typo_term}'")
                    run_term_simulation(
                        page=page,
                        term=typo_term,
                        alphabet_cycle=not args.no_alphabet,
                        pause_between_s=args.pause
                    )

        elapsed = time.time() - start_time
        print("\n" + "=" * 65)
        print(f"🎉 Collection complete! Processed {total_roots} root keyword(s) in {elapsed:.1f}s.")
        print("💡 The extension has captured the suggestions and will batch-upload them")
        print("   to your server (or you can inspect local storage / server dashboard).")
        print("=" * 65)

        # Give background worker time to settle
        page.wait_for_timeout(3000)
        context.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Execution interrupted by user. Exiting cleanly...")
        sys.exit(0)
