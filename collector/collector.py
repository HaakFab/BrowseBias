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
from typing import List, Optional, Tuple

from playwright.sync_api import sync_playwright, BrowserContext, Page

# Import local modules
import config
from typo_generator import generate_typos


# Pacing & Speed Presets for Testing vs Realistic Emulation
SPEED_PRESETS = {
    "ultra-fast": {
        "typing_min_ms": 15,
        "typing_max_ms": 30,
        "suggestion_wait_ms": 180,
        "alphabet_wait_ms": 150,
        "space_delay_ms": 20,
        "backspace_wait_ms": 40,
    },
    "fast": {
        "typing_min_ms": 25,
        "typing_max_ms": 50,
        "suggestion_wait_ms": 300,
        "alphabet_wait_ms": 250,
        "space_delay_ms": 30,
        "backspace_wait_ms": 70,
    },
    "normal": {
        "typing_min_ms": 45,
        "typing_max_ms": 110,
        "suggestion_wait_ms": 500,
        "alphabet_wait_ms": 450,
        "space_delay_ms": 50,
        "backspace_wait_ms": 100,
    },
    "relaxed": {
        "typing_min_ms": 70,
        "typing_max_ms": 150,
        "suggestion_wait_ms": 800,
        "alphabet_wait_ms": 650,
        "space_delay_ms": 70,
        "backspace_wait_ms": 150,
    },
}


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
        "-l", "--lang",
        default=config.BROWSER_LANG,
        help=f"Browser interface language/locale (e.g. de-DE, en-US, en-GB; default: {config.BROWSER_LANG})"
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=config.PAUSE_BETWEEN_QUERIES_S,
        help=f"Pause in seconds between queries (default: {config.PAUSE_BETWEEN_QUERIES_S}s, e.g. 0.2 or 0.5 for fast tests)"
    )
    parser.add_argument(
        "--speed",
        choices=["ultra-fast", "fast", "normal", "relaxed"],
        default="normal",
        help="Simulation speed preset: ultra-fast, fast, normal, or relaxed (default: normal)"
    )
    parser.add_argument(
        "--suggestion-wait",
        type=int,
        default=None,
        help="Explicit milliseconds to wait after typing keyword before suggestions (default: preset-based)"
    )
    parser.add_argument(
        "--alphabet-wait",
        type=int,
        default=None,
        help="Explicit milliseconds to wait during alphabet expansion cycle (default: preset-based)"
    )
    parser.add_argument(
        "-p", "--pseudonym",
        default=config.get_or_create_pseudonym(),
        help="Auditor pseudonym / cohort tag to assign to all collected suggestions"
    )
    parser.add_argument(
        "--restart-every",
        type=int,
        default=config.RESTART_EVERY_KEYWORDS,
        help=f"Restart browser every N keywords to clear Google session throttling (default: {config.RESTART_EVERY_KEYWORDS}, 0 to disable)"
    )
    parser.add_argument(
        "--flush-every",
        type=int,
        default=config.FLUSH_EVERY_KEYWORDS,
        help=f"Upload captured suggestions to server every N keywords (default: {config.FLUSH_EVERY_KEYWORDS}, 0 for completion only)"
    )
    parser.add_argument(
        "--server-url",
        default=config.SERVER_URL,
        help=f"Research server upload endpoint URL (default: {config.SERVER_URL})"
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


def ensure_extension_consent(
    context: BrowserContext,
    pseudonym: str = "Collector-Auditor-1",
    server_url: str = config.SERVER_URL
) -> Optional[str]:
    """
    Guarantees that the Chrome extension has consentGiven=True, scrapingEnabled=True,
    the designated pseudonym, and serverUrl set directly in chrome.storage.local.
    Returns the resolved extension ID.
    """
    print(f"🔧 Configuring extension consent & pseudonym '{pseudonym}'...")

    # 1. Identify extension ID from service worker or waiting for event
    ext_id = None
    for _ in range(8):
        if context.service_workers:
            sw = context.service_workers[0]
            ext_id = sw.url.split('/')[2]
            break
        for p in context.pages:
            if "chrome-extension://" in p.url:
                ext_id = p.url.split('/')[2]
                break
        if ext_id:
            break
        time.sleep(0.25)

    if not ext_id:
        try:
            sw = context.wait_for_event("serviceworker", timeout=3000)
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
            setup_page.evaluate("""(configData) => {
                return new Promise((resolve) => {
                    const base = configData.serverUrl.replace(/\/api\/upload\/?$/, '');
                    chrome.storage.local.set({
                        highlightingEnabled: true,
                        scrapingEnabled: true,
                        consentGiven: true,
                        user_pseudonym: configData.pseudonym,
                        serverUrl: configData.serverUrl,
                        serverBaseUrl: base,
                        lexiconUrl: base + '/api/lexicon',
                        reportUrl: base + '/api/report',
                        consentDate: new Date().toISOString()
                    }, () => resolve());
                });
            }""", {"pseudonym": pseudonym, "serverUrl": server_url})
            setup_page.close()
            print(f"✅ Extension configured: pseudonym='{pseudonym}', server='{server_url}'.")
        except Exception as e:
            print(f"⚠️ Extension storage configuration note: {e}")

    # 4. Clean up any open onboarding tabs
    time.sleep(0.2)
    for p in list(context.pages):
        try:
            if not p.is_closed() and "onboarding.html" in p.url:
                p.close()
        except Exception:
            pass

    return ext_id


def trigger_extension_upload(context: BrowserContext, ext_id: Optional[str]) -> bool:
    """Trigger immediate batch upload from the extension to the research server."""
    if not ext_id:
        return False
    try:
        page = context.new_page()
        page.goto(f"chrome-extension://{ext_id}/src/popup.html", wait_until="domcontentloaded", timeout=4000)
        result = page.evaluate("""() => {
            return new Promise((resolve) => {
                chrome.runtime.sendMessage({ type: 'triggerManualUpload' }, (res) => {
                    resolve(res || {});
                });
            });
        }""")
        page.close()
        upload_info = result.get("upload", {}) if isinstance(result, dict) else {}
        count = upload_info.get("count", 0)
        success = upload_info.get("success", False) or result.get("success", False)
        if count > 0:
            print(f"   📤 Transmitted {count} captured query entries to research server.")
        elif success:
            print("   📤 Server sync check: buffer is up-to-date (0 pending).")
        else:
            err = upload_info.get("error", "Server unavailable or offline")
            print(f"   ⚠️ Server upload note: {err}")
        return True
    except Exception as e:
        print(f"   ⚠️ Extension upload trigger note: {e}")
        return False


def create_browser_session(
    p,
    profile_dir: Path,
    ext_path: Path,
    args: argparse.Namespace,
    short_lang: str,
    target_url: str,
    pseudonym: str
) -> Tuple[BrowserContext, Page, Optional[str]]:
    """Launch a clean persistent browser context and initialize Google search page."""
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=False,
        viewport={"width": 1280, "height": 800},
        locale=args.lang,
        extra_http_headers={
            "Accept-Language": f"{args.lang},{short_lang};q=0.9,en;q=0.8"
        },
        args=[
            f"--disable-extensions-except={ext_path}",
            f"--load-extension={ext_path}",
            f"--lang={args.lang}",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--no-first-run",
            "--no-default-browser-check",
        ]
    )

    ext_id = ensure_extension_consent(context, pseudonym=pseudonym, server_url=args.server_url)

    valid_pages = [p for p in context.pages if not p.is_closed() and "onboarding.html" not in p.url]
    page = valid_pages[0] if valid_pages else context.new_page()

    print(f"🌐 Navigating to {target_url}...")
    page.goto(target_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    handle_cookie_consent(page)

    return context, page, ext_id



def human_type(page: Page, text: str, min_delay_ms: int = 40, max_delay_ms: int = 110, input_sel: Optional[str] = None):
    """Simulate human-like typing with randomized millisecond delays per keystroke."""
    if input_sel:
        try:
            page.bring_to_front()
            page.click(input_sel, timeout=1500)
            page.focus(input_sel)
        except Exception:
            pass

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
    pause_between_s: float = 1.5,
    target_url: str = config.GOOGLE_URL,
    suggestion_wait_ms: int = 500,
    alphabet_wait_ms: int = 450,
    typing_min_ms: int = 45,
    typing_max_ms: int = 110,
    space_delay_ms: int = 50,
    backspace_wait_ms: int = 100
):
    """
    Execute full typing sequence for a single term (root or typo):
      1. Focus & thoroughly clear search box
      2. Human-type term
      3. Wait for suggestions
      4. If alphabet_cycle: add space, cycle 'a'..'z' with backspaces
      5. Thoroughly clear search box for next query
    """
    # Bring browser tab to front
    try:
        page.bring_to_front()
    except Exception:
        pass

    # Find input
    input_sel = find_search_input(page)
    if not input_sel:
        print(f"⚠️ Search input not found, reloading Google...")
        page.goto(target_url, wait_until="domcontentloaded")
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
    try:
        page.click(input_sel)
        page.focus(input_sel)
    except Exception:
        pass

    human_type(page, term, typing_min_ms, typing_max_ms, input_sel=input_sel)
    
    # Wait for suggestions to render and extension to intercept
    page.wait_for_timeout(suggestion_wait_ms)
    print(" ✓", flush=True)

    # 2. Alphabet cycle: ' term a', ' term b', ... ' term z'
    if alphabet_cycle:
        # Append space
        try:
            page.focus(input_sel)
        except Exception:
            pass
        page.keyboard.type(" ", delay=space_delay_ms)
        page.wait_for_timeout(max(50, backspace_wait_ms))

        print(f"   🔤 Alphabet expansion: ", end="", flush=True)
        for char in config.ALPHABET_CHARS:
            try:
                page.focus(input_sel)
            except Exception:
                pass
            page.keyboard.type(char, delay=space_delay_ms)
            # Give extension & Google time to display suggestion
            page.wait_for_timeout(alphabet_wait_ms)
            page.keyboard.press("Backspace")
            page.wait_for_timeout(backspace_wait_ms)
            print(char, end="", flush=True)
        print(" ✓", flush=True)

    # Clean up input thoroughly before next query
    clear_search_input(page, input_sel)
    page.wait_for_timeout(max(50, int(pause_between_s * 1000)))


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

    # Determine speed pacing & wait thresholds
    preset = SPEED_PRESETS.get(args.speed, SPEED_PRESETS["normal"])
    suggestion_wait_ms = args.suggestion_wait if args.suggestion_wait is not None else preset["suggestion_wait_ms"]
    alphabet_wait_ms = args.alphabet_wait if args.alphabet_wait is not None else preset["alphabet_wait_ms"]
    typing_min_ms = preset["typing_min_ms"]
    typing_max_ms = preset["typing_max_ms"]
    space_delay_ms = preset["space_delay_ms"]
    backspace_wait_ms = preset["backspace_wait_ms"]

    # Determine language & ensure target_url has explicit hl parameter
    short_lang = args.lang.split("-")[0] if "-" in args.lang else args.lang
    target_url = args.url
    if "hl=" not in target_url:
        sep = "&" if "?" in target_url else "?"
        target_url = f"{target_url}{sep}hl={short_lang}"

    pseudonym = args.pseudonym or config.get_or_create_pseudonym()

    print("=" * 65)
    print("🚀 Autocomplete Bias — Input Simulator & Collector")
    print("=" * 65)
    print(f"  Target Google URL : {target_url}")
    print(f"  Language / Locale : {args.lang}")
    print(f"  Auditor Pseudonym : {pseudonym}")
    print(f"  Restart Every     : {f'{args.restart_every} keywords' if args.restart_every > 0 else 'Never (Disabled)'}")
    print(f"  Submit to Server  : {f'Every {args.flush_every} keywords' if args.flush_every > 0 else 'At completion only'}")
    print(f"  Speed Pacing Mode : {args.speed} (Typing: {typing_min_ms}-{typing_max_ms}ms, Wait: {suggestion_wait_ms}ms, Alphabet: {alphabet_wait_ms}ms)")
    print(f"  Pause Between KWs : {args.pause}s")
    print(f"  Keywords count    : {len(keywords)}")
    print(f"  Typos per root    : {args.typos}")
    print(f"  Alphabet cycle    : {'Yes (a-z)' if not args.no_alphabet else 'No'}")
    print(f"  Extension path    : {ext_path}")
    print(f"  Browser profile   : {args.profile}")
    print("=" * 65)

    profile_dir = Path(args.profile).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context, page, ext_id = create_browser_session(
            p=p,
            profile_dir=profile_dir,
            ext_path=ext_path,
            args=args,
            short_lang=short_lang,
            target_url=target_url,
            pseudonym=pseudonym
        )

        total_roots = len(keywords)
        start_time = time.time()

        for k_idx, root_kw in enumerate(keywords, 1):
            print(f"\n[{k_idx}/{total_roots}] 🎯 Root Keyword: '{root_kw}'")

            # 1. Process root keyword
            run_term_simulation(
                page=page,
                term=root_kw,
                alphabet_cycle=not args.no_alphabet,
                pause_between_s=args.pause,
                target_url=target_url,
                suggestion_wait_ms=suggestion_wait_ms,
                alphabet_wait_ms=alphabet_wait_ms,
                typing_min_ms=typing_min_ms,
                typing_max_ms=typing_max_ms,
                space_delay_ms=space_delay_ms,
                backspace_wait_ms=backspace_wait_ms
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
                        pause_between_s=args.pause,
                        target_url=target_url,
                        suggestion_wait_ms=suggestion_wait_ms,
                        alphabet_wait_ms=alphabet_wait_ms,
                        typing_min_ms=typing_min_ms,
                        typing_max_ms=typing_max_ms,
                        space_delay_ms=space_delay_ms,
                        backspace_wait_ms=backspace_wait_ms
                    )

            # Periodic batch upload flush to research server
            if args.flush_every > 0 and k_idx % args.flush_every == 0:
                trigger_extension_upload(context, ext_id)

            # Periodic browser restart to clear Google socket / session throttling
            if args.restart_every > 0 and k_idx % args.restart_every == 0 and k_idx < total_roots:
                print(f"\n🔄 Keyword restart interval reached ({k_idx}/{total_roots}).")
                print(f"   Flushing data and restarting browser with pseudonym '{pseudonym}' to clear Google session...")
                trigger_extension_upload(context, ext_id)
                try:
                    context.close()
                except Exception:
                    pass
                time.sleep(1.5)
                context, page, ext_id = create_browser_session(
                    p=p,
                    profile_dir=profile_dir,
                    ext_path=ext_path,
                    args=args,
                    short_lang=short_lang,
                    target_url=target_url,
                    pseudonym=pseudonym
                )

        elapsed = time.time() - start_time
        print("\n" + "=" * 65)
        print(f"🎉 Collection complete! Processed {total_roots} root keyword(s) in {elapsed:.1f}s.")
        print("📤 Performing final submission flush to research server...")
        trigger_extension_upload(context, ext_id)
        print("=" * 65)

        # Allow final background worker tasks to complete
        time.sleep(1.5)
        try:
            context.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Execution interrupted by user. Exiting cleanly...")
        sys.exit(0)
