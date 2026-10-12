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
| `--extension` | `-e` | `../plugin` | Path to the unpacked Chrome extension directory. |
| `--typos` | `-t` | `0` | Number of intentional typo permutations per keyword. |
| `--pause` | | `1.5` | Pause in seconds between queries to prevent rate limits. |
| `--no-alphabet` | | `False` | Skip trailing `' a'..' z'` alphabet expansion cycle. |
| `--profile` | | `browser_profile` | Browser profile directory to preserve session cookies. |

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
- `keywords.txt`: General German politics and current events topics.
- `keywords_bundestag.txt`: Complete list of 736+ German Bundestag MPs generated from official parliamentary records.

---

## 💡 Best Practices to Prevent Google Rate Limits (CAPTCHA)

1. **Typing Speed:** Keep typing delay between 45ms and 110ms (the collector simulates human finger typing cadence).
2. **Query Pause:** Set `--pause` to at least 1.5s (or 2.5s for long runs).
3. **Alphabet Cycle:** If scanning large lists (e.g. 700+ MPs), consider running batches of 50-100 keywords with breaks.
4. **Headful Mode:** Chrome extensions *cannot* run in headless mode in Chromium; the window will open visibly so Google autocomplete renders legitimately.
