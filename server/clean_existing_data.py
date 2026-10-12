#!/usr/bin/env python3
"""
Clean existing uploads.jsonl data by stripping embedded CSS and UI clutter,
and generate clean server/data/suggestions.jsonl and sanitized server/data/uploads.jsonl.
"""

import json
import os
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
UPLOAD_FILE = os.path.join(DATA_DIR, 'uploads.jsonl')
SUGGESTIONS_FILE = os.path.join(DATA_DIR, 'suggestions.jsonl')
CLEANED_UPLOAD_FILE = os.path.join(DATA_DIR, 'uploads_cleaned.jsonl')


def clean_text(raw_text: str) -> str:
    if not raw_text:
        return ""

    text = raw_text

    # 1. Remove embedded CSS rules (e.g. .MagqMc .ZFiwCf{...} or anything matching selector{...})
    # First cut off at first CSS class selector attached to Google autocomplete styles
    text = re.split(r'\.[A-Za-z0-9_-]+\s*[\.\{\#]', text)[0]

    # Also cut off if '{' exists
    if '{' in text:
        text = text.split('{')[0]

    # 2. Remove common trailing UI buttons/badges Google renders in autocomplete
    text = re.sub(r'(\s*AI Mode|\s*See more|\s*Delete|\s*Feedback geben|\s*Löschen|\s*Melden)+$', '', text, flags=re.IGNORECASE)
    # Also handle concatenated "AI Mode" without space
    if text.endswith('AI Mode'):
        text = text[:-7].strip()

    # 3. Clean multiple spaces / newlines
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def main():
    if not os.path.exists(UPLOAD_FILE):
        print(f"File {UPLOAD_FILE} not found.")
        return

    print(f"Reading {UPLOAD_FILE} (Size: {os.path.getsize(UPLOAD_FILE):,} bytes)...")

    cleaned_uploads = []
    all_suggestions = []

    with open(UPLOAD_FILE, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                batch = json.loads(line)
            except Exception as e:
                print(f"Error parsing line {line_num}: {e}")
                continue

            received_at = batch.get('receivedAt', '')
            ext_version = batch.get('version') or batch.get('extensionVersion', '1.0.2')
            v_tag = batch.get('v_tag') or batch.get('versionTag', 'trias')
            cleaned_entries = []

            for entry in batch.get('entries', []):
                query = entry.get('query', '')
                tld = entry.get('googleTld', '')
                lang = entry.get('language', '')
                ts = entry.get('timestamp', received_at)

                cleaned_suggs = []
                for s in entry.get('suggestions', []):
                    raw_s_text = s.get('text', '') if isinstance(s, dict) else str(s)
                    bias_level = s.get('biasLevel') if isinstance(s, dict) else None
                    cleaned_s_text = clean_text(raw_s_text)

                    if cleaned_s_text:
                        cleaned_suggs.append({
                            'text': cleaned_s_text,
                            'biasLevel': bias_level
                        })

                        all_suggestions.append({
                            'timestamp': ts,
                            'query': query,
                            'suggestion': cleaned_s_text,
                            'biasLevel': bias_level,
                            'googleTld': tld,
                            'language': lang,
                            'version': ext_version,
                            'v_tag': v_tag,
                            'receivedAt': received_at
                        })

                if cleaned_suggs:
                    cleaned_entry = dict(entry)
                    cleaned_entry['suggestions'] = cleaned_suggs
                    cleaned_entries.append(cleaned_entry)

            if cleaned_entries:
                cleaned_batch = {
                    'receivedAt': received_at,
                    'extensionVersion': ext_version,
                    'version': ext_version,
                    'versionTag': v_tag,
                    'v_tag': v_tag,
                    'entryCount': len(cleaned_entries),
                    'entries': cleaned_entries
                }
                cleaned_uploads.append(cleaned_batch)

    # Write sanitized uploads.jsonl
    backup_file = UPLOAD_FILE + '.bak'
    os.rename(UPLOAD_FILE, backup_file)
    print(f"Original file backed up to {backup_file}")

    with open(UPLOAD_FILE, 'w', encoding='utf-8') as f:
        for b in cleaned_uploads:
            f.write(json.dumps(b, ensure_ascii=False) + '\n')

    # Write suggestions.jsonl
    with open(SUGGESTIONS_FILE, 'w', encoding='utf-8') as f:
        for s in all_suggestions:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    print(f"✅ Cleaned uploads written to {UPLOAD_FILE} (Size: {os.path.getsize(UPLOAD_FILE):,} bytes)")
    print(f"✅ {len(all_suggestions):,} individual suggestions written to {SUGGESTIONS_FILE} (Size: {os.path.getsize(SUGGESTIONS_FILE):,} bytes)")


if __name__ == '__main__':
    main()
