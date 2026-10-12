#!/usr/bin/env python3
"""
Fetch German Bundestag MPs from Abgeordnetenwatch API v2
=========================================================
1. Fetches all current Bundestag MPs (Abgeordnete) from Abgeordnetenwatch API v2.
2. Generates a clean keywords list of politician names for the scraper.
3. Fetches comprehensive politician metadata from the politician entity endpoint
   and saves it as a structured CSV file.

API Reference:
  - Parliament: https://www.abgeordnetenwatch.de/api/v2/parliaments/5
  - Mandates: https://www.abgeordnetenwatch.de/api/v2/candidacies-mandates
  - Politicians: https://www.abgeordnetenwatch.de/api/v2/politicians/{id}
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

API_BASE = "https://www.abgeordnetenwatch.de/api/v2"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def api_get(url: str, params: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Dict[str, Any]:
    """Perform a GET request to the Abgeordnetenwatch API with retries and backoff."""
    if params:
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"
    else:
        full_url = url

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json"
    }

    req = urllib.request.Request(full_url, headers=headers)

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.0 * attempt)
            elif attempt == max_retries:
                return {}
            else:
                time.sleep(0.5 * attempt)
        except Exception:
            if attempt == max_retries:
                return {}
            time.sleep(0.5 * attempt)

    return {}


def get_current_bundestag_period() -> Tuple[int, str]:
    """Retrieve the current Bundestag parliament period ID and label."""
    url = f"{API_BASE}/parliaments/5"
    data = api_get(url)
    parliament = data.get("data", {})
    current_project = parliament.get("current_project", {})

    period_id = current_project.get("id")
    period_label = current_project.get("label", "Bundestag")

    if not period_id:
        period_id = 161
        period_label = "Bundestag 2025 - 2029"

    return period_id, period_label


def get_all_mandates(period_id: int) -> List[Dict[str, Any]]:
    """Fetch all mandates for the given parliament period."""
    mandates = []
    range_start = 0
    batch_size = 500

    print(f"📡 Fetching mandate list for parliament period {period_id}...", flush=True)

    while True:
        url = f"{API_BASE}/candidacies-mandates"
        params = {
            "parliament_period": period_id,
            "type": "mandate",
            "range_start": range_start,
            "range_end": range_start + batch_size
        }
        data = api_get(url, params)
        items = data.get("data", [])
        if not items:
            break

        mandates.extend(items)
        meta_result = data.get("meta", {}).get("result", {})
        total = meta_result.get("total", 0)

        print(f"   Fetched {len(mandates)} / {total if total else '?'} mandates...", flush=True)

        if len(items) < batch_size or (total and len(mandates) >= total):
            break

        range_start += batch_size

    return mandates


def fetch_politician_details(politician_id: int) -> Optional[Dict[str, Any]]:
    """Fetch single politician entity details from /api/v2/politicians/{id}."""
    url = f"{API_BASE}/politicians/{politician_id}"
    try:
        data = api_get(url)
        return data.get("data")
    except Exception:
        return None


def fetch_all_politicians_concurrently(
    politician_ids: List[int],
    max_workers: int = 12,
    cache_file: Optional[Path] = None
) -> Dict[int, Dict[str, Any]]:
    """Fetch profile details for all politicians with disk cache support."""
    cached: Dict[int, Dict[str, Any]] = {}
    if cache_file and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                raw_cache = json.load(f)
                cached = {int(k): v for k, v in raw_cache.items()}
            print(f"📦 Loaded {len(cached)} cached politician profiles from {cache_file.name}", flush=True)
        except Exception:
            cached = {}

    to_fetch = [pid for pid in politician_ids if pid not in cached]
    total = len(politician_ids)

    if to_fetch:
        print(f"📡 Fetching remaining {len(to_fetch)} profiles from API ({max_workers} threads)...", flush=True)
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {
                executor.submit(fetch_politician_details, pid): pid
                for pid in to_fetch
            }

            for future in as_completed(future_to_id):
                pid = future_to_id[future]
                completed += 1
                if completed % 50 == 0 or completed == len(to_fetch):
                    print(f"   Progress: {completed} / {len(to_fetch)} ({completed/len(to_fetch)*100:.1f}%)", flush=True)

                try:
                    data = future.result()
                    if data:
                        cached[pid] = data
                except Exception:
                    pass

        # Save cache
        if cache_file:
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cached, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    return cached


def save_keywords_file(names: List[str], output_path: Path, append_to_existing: bool = False):
    """Save cleaned politician names as a keywords text file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing_names = set()
    if append_to_existing and output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    existing_names.add(line)

    combined_names = sorted(existing_names.union(set(names)))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Seed keywords: German Bundestag MPs (Abgeordnetenwatch API)\n")
        f.write(f"# Total: {len(combined_names)} names\n\n")
        for name in combined_names:
            f.write(f"{name}\n")

    print(f"✅ Saved {len(combined_names)} keywords to: {output_path}", flush=True)


def save_politicians_csv(
    mandates: List[Dict[str, Any]],
    politicians_map: Dict[int, Dict[str, Any]],
    output_path: Path
):
    """Save merged politician profile and mandate details as a CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "politician_id",
        "name",
        "first_name",
        "last_name",
        "birth_name",
        "title",
        "sex",
        "year_of_birth",
        "party",
        "fraction",
        "constituency_id",
        "constituency_name",
        "mandate_won",
        "mandate_start",
        "mandate_end",
        "education",
        "occupation",
        "residence",
        "party_past",
        "statistic_questions",
        "statistic_questions_answered",
        "ext_id_bundestagsverwaltung",
        "qid_wikidata",
        "abgeordnetenwatch_url",
        "api_url"
    ]

    records = []
    seen_politician_ids = set()

    for m in mandates:
        pol_stub = m.get("politician", {})
        pid = pol_stub.get("id")
        if not pid or pid in seen_politician_ids:
            continue
        seen_politician_ids.add(pid)

        pol_detail = politicians_map.get(pid, {})

        # Extract fraction name
        fractions = m.get("fraction_membership", [])
        fraction_label = ""
        if fractions and isinstance(fractions, list):
            fraction_label = fractions[0].get("fraction", {}).get("label", "")
            if "(" in fraction_label:
                fraction_label = fraction_label.split("(")[0].strip()

        # Extract electoral data
        electoral = m.get("electoral_data", {}) or {}
        constituency = electoral.get("constituency", {}) or {}
        constituency_id = constituency.get("id", "")
        constituency_name = constituency.get("label", "")
        mandate_won = electoral.get("mandate_won", "")

        party_obj = pol_detail.get("party") or {}
        party_name = party_obj.get("label", "") if isinstance(party_obj, dict) else str(party_obj or "")
        if not party_name and fraction_label:
            party_name = fraction_label

        full_name = (pol_detail.get("label") or pol_stub.get("label") or "").strip()
        first_name = pol_detail.get("first_name") or ""
        last_name = pol_detail.get("last_name") or ""

        # If first/last name not explicitly set in profile, infer from full name
        if not first_name and not last_name and full_name:
            parts = full_name.split()
            if len(parts) == 1:
                first_name, last_name = "", parts[0]
            else:
                first_name, last_name = " ".join(parts[:-1]), parts[-1]

        record = {
            "politician_id": pid,
            "name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "birth_name": pol_detail.get("birth_name") or "",
            "title": pol_detail.get("field_title") or "",
            "sex": pol_detail.get("sex") or "",
            "year_of_birth": pol_detail.get("year_of_birth") or "",
            "party": party_name,
            "fraction": fraction_label,
            "constituency_id": constituency_id,
            "constituency_name": constituency_name,
            "mandate_won": mandate_won,
            "mandate_start": m.get("start_date") or "",
            "mandate_end": m.get("end_date") or "",
            "education": pol_detail.get("education") or "",
            "occupation": pol_detail.get("occupation") or "",
            "residence": pol_detail.get("residence") or "",
            "party_past": pol_detail.get("party_past") or "",
            "statistic_questions": pol_detail.get("statistic_questions") or 0,
            "statistic_questions_answered": pol_detail.get("statistic_questions_answered") or 0,
            "ext_id_bundestagsverwaltung": pol_detail.get("ext_id_bundestagsverwaltung") or "",
            "qid_wikidata": pol_detail.get("qid_wikidata") or "",
            "abgeordnetenwatch_url": pol_detail.get("abgeordnetenwatch_url") or pol_stub.get("abgeordnetenwatch_url") or "",
            "api_url": pol_detail.get("api_url") or pol_stub.get("api_url") or f"{API_BASE}/politicians/{pid}"
        }
        records.append(record)

    # Sort records by name
    records.sort(key=lambda r: (r["last_name"] or r["name"], r["first_name"]))

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(records)

    print(f"✅ Saved detailed CSV with {len(records)} politicians to: {output_path}", flush=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch German Bundestag MPs from Abgeordnetenwatch API v2 as keywords list & CSV."
    )
    base_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "-k", "--keywords-out",
        default=str(base_dir / "keywords_bundestag.txt"),
        help=f"Output path for keywords list (default: {base_dir / 'keywords_bundestag.txt'})"
    )
    parser.add_argument(
        "-c", "--csv-out",
        default=str(base_dir / "bundestag_politicians.csv"),
        help=f"Output path for detailed CSV (default: {base_dir / 'bundestag_politicians.csv'})"
    )
    parser.add_argument(
        "--append-keywords",
        action="store_true",
        help="Also append the names into the main collector/keywords.txt file"
    )
    parser.add_argument(
        "--period",
        type=int,
        default=None,
        help="Parliament period ID (default: auto-detected current Bundestag period)"
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=12,
        help="Number of concurrent worker threads for detail fetching (default: 12)"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    print("=" * 65, flush=True)
    print("  Abgeordnetenwatch.de — Bundestag MP Fetcher", flush=True)
    print("=" * 65, flush=True)

    # 1. Determine Bundestag parliament period
    if args.period:
        period_id = args.period
        period_label = f"Period ID {period_id}"
    else:
        period_id, period_label = get_current_bundestag_period()

    print(f"🏛️  Target Parliament Period: {period_label} (ID: {period_id})", flush=True)

    # 2. Fetch all mandates
    mandates = get_all_mandates(period_id)
    if not mandates:
        print(f"❌ No mandates found for period {period_id}.", file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"📋 Found {len(mandates)} total mandates.", flush=True)

    # 3. Extract unique politician IDs and names
    politician_names = []
    politician_ids = []
    seen_ids = set()

    for m in mandates:
        pol = m.get("politician", {})
        pid = pol.get("id")
        name = pol.get("label", "").strip()

        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            politician_ids.append(pid)
            if name:
                politician_names.append(name)

    politician_names = sorted(list(set(politician_names)))
    print(f"👥 Extracted {len(politician_names)} unique MP names.", flush=True)

    # 4. IMMEDIATELY save keywords file so it is ready right away
    keywords_path = Path(args.keywords_out).resolve()
    save_keywords_file(politician_names, keywords_path)

    if args.append_keywords:
        main_keywords_path = Path(__file__).resolve().parent / "keywords.txt"
        save_keywords_file(politician_names, main_keywords_path, append_to_existing=True)

    # 5. Fetch full detailed profiles with local caching
    cache_path = Path(__file__).resolve().parent / ".politicians_cache.json"
    politicians_map = fetch_all_politicians_concurrently(
        politician_ids,
        max_workers=args.workers,
        cache_file=cache_path
    )

    # 6. Save detailed CSV file
    csv_path = Path(args.csv_out).resolve()
    save_politicians_csv(mandates, politicians_map, csv_path)

    print("=" * 65, flush=True)
    print(f"🎉 Successfully completed!", flush=True)
    print(f"   Keywords: {keywords_path}", flush=True)
    print(f"   CSV Data: {csv_path}", flush=True)
    print("=" * 65, flush=True)


if __name__ == "__main__":
    main()
