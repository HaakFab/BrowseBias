# BrowseBias — Collector Tool & Playwright Simulator Guide

The **BrowseBias Collector** is an automated typing simulator that runs a real Chromium browser with the **Autocomplete Bias** Chrome extension installed to systematically collect and record Google Search autocomplete suggestions.

---

## 🚀 Quickstart: Web GUI Runner

The easiest way to run the collector on any operating system is using the zero-dependency Web GUI:

### Launching:
- **macOS:** Double-click `collector/run_collector_gui.command` or run `python start_collector.py`
- **Windows:** Double-click `collector/run_collector_gui.bat` or run `python start_collector.py`
- **Linux:** Run `./collector/run_collector_gui.sh` or run `python start_collector.py`

This starts a local server on `http://localhost:8766` and opens your browser automatically.

---

## ⚙️ Prerequisites

1. Install Python packages:
   ```bash
   pip install playwright
   playwright install chromium
   ```
2. Verify extension path:
   The collector automatically finds `plugin/manifest.json`.

---

## ⌨️ CLI Mode (Command Line Usage)

If you prefer running the collector directly from a terminal or in automated scripts:

```bash
cd collector
python collector.py -k keywords.txt -u https://www.google.de --pause 1.5
```

### Available Command-Line Arguments:

| Argument | Shorthand | Default | Description |
| :--- | :--- | :--- | :--- |
| `--keywords` | `-k` | `keywords.txt` | Path to text file containing keywords (one per line). |
| `--url` | `-u` | `https://www.google.de` | Google Search URL domain. |
| `--lang` | `-l` | `de-DE` | Browser locale, HTTP Accept-Language, and Google `?hl=` UI language code (e.g. `de-DE`, `en-US`, `en-GB`). |
| `--speed` | | `normal` | Pacing preset: `ultra-fast`, `fast`, `normal`, or `relaxed` for rapid testing vs human cadence. |
| `--pause` | | `1.5` | Pause in seconds between queries (supports down to `0.2`s for rapid testing). |
| `--suggestion-wait` | | `500` (preset) | Milliseconds to wait after typing before capturing suggestions. |
| `--alphabet-wait` | | `450` (preset) | Milliseconds to wait per letter during alphabet cycle. |
| `--pseudonym` | `-p` | `pseudonym.txt` | Auditor pseudonym tag assigned to all collected suggestions (persists across restarts). |
| `--restart-every` | | `10` | Restarts browser session every N keywords to clear Google autocomplete throttling (0 to disable). |
| `--flush-every` | | `5` | Flushes buffered suggestions directly to research server every N keywords (0 for end-only). |
| `--server-url` | | `http://localhost:8765/api/upload` | Upload endpoint URL on the research server. |
| `--extension` | `-e` | `../plugin` | Path to the unpacked Chrome extension directory. |
| `--typos` | `-t` | `0` | Number of intentional typo permutations per keyword. |
| `--no-alphabet` | | `False` | Skip trailing `' a'..' z'` alphabet expansion cycle. |
| `--profile` | | `browser_profile` | Browser profile directory to preserve session cookies. |

---

## 🛡️ Anti-Throttling & Browser Restarts (Preserving Pseudonyms)

When scanning terms with the full alphabet cycle (`a` through `z`), 20 keywords generate **540 rapid queries** on a single Chromium TLS connection. Google's frontend rate limiting detects rapid socket usage and eventually stops returning autocomplete dropdown items.

To solve this:
- The collector automatically **restarts the browser session every 10 keywords** (configurable via `--restart-every` or the GUI dropdown).
- **Persistent Pseudonyms:** Before restarting, your auditor pseudonym is preserved in `collector/pseudonym.txt` and re-injected directly into `chrome.storage.local` upon reopening. All collected suggestions across the entire batch belong to the **exact same pseudonym**, ensuring seamless scientific cohort tracking.
- **Automated Mid-Run Server Flushes:** Every 5 keywords (and immediately before any browser restart or exit), the collector instructs the Chrome extension background script to upload pending suggestions to `http://localhost:8765/api/upload`, preventing data loss even if a run is halted early.

---

## 📝 Keyword File Format

Keyword files are plain UTF-8 text files (`.txt`) with one keyword per line. Empty lines and lines starting with `#` are automatically ignored:

```text
# German Politicians
Olaf Scholz
Friedrich Merz
Robert Habeck
Christian Lindner
Alice Weidel

# Controversy Topics
Klimawandel
Energiekrise
Bürgergeld
```

### Included Presets:
- `50_keywords_topics.txt`: 50 German socio-political topics (migration, energy, pension, inflation, etc.) formatted with 1 keyword per line.
- `keywords.txt`: General German politics and current events topics.
- `keywords_bundestag.txt`: Complete list of 736+ German Bundestag MPs generated from official parliamentary records.

---

## ⚠️ Window Focus & Suggestions: Do I Need to Keep the Window Active?

A common question during long collection runs: **"Do I need to keep the browser window maximized and active in foreground?"**

- **Do NOT minimize the browser to the Dock / Taskbar:**
  When a window is minimized, modern operating systems (macOS, Windows) notify the browser that the window is completely occluded and inactive (`document.hidden = true`). Google's search box has an active blur listener (`blur` / `focusout` event): the moment the window is minimized, Google **destroys the suggestion listbox dropdown** and stops issuing autocomplete queries (`/complete/search`).
- **Does it need to be maximized?**
  **No.** You do not need to maximize the window.
- **Can it run in the background?**
  **Yes!** You can leave the browser unminimized in the background behind your other open windows (e.g., behind VS Code, Word, or another browser). As long as the window is not minimized to the dock/taskbar, Playwright maintains input focus and Google will continuously display suggestions.

---

## 💡 Best Practices to Prevent Google Rate Limits (CAPTCHA)

1. **Typing Speed:** Keep typing delay between 45ms and 110ms (the collector simulates human finger typing cadence).
2. **Query Pause:** Set `--pause` to at least 1.5s (or 2.5s for long runs).
3. **Alphabet Cycle:** If scanning large lists (e.g. 700+ MPs), consider running batches of 50-100 keywords with breaks.
4. **Headful Mode:** Chrome extensions *cannot* run in headless mode in Chromium; the window will open visibly so Google autocomplete renders legitimately.
