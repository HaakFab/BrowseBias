#!/usr/bin/env python3
"""
Unit tests to verify server upload, suggestion extraction, version/v_tag logging,
user feedback/report endpoints, rating engine orchestration, and web dashboard.
"""
import json
import os
import sys
from pathlib import Path
import unittest

# Ensure server module is importable
server_dir = Path(__file__).resolve().parent
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from app import app, clean_suggestion_text, REPORTS_FILE, SUGGESTIONS_FILE, UPLOAD_FILE


class TestServerStorage(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_clean_suggestion_text(self):
        dirty = "angela merkel.MagqMc .ZFiwCf{background-color:#2c2e35;width:100%}See moreDelete"
        self.assertEqual(clean_suggestion_text(dirty), "angela merkel")

        dirty_ai = "abrufschein auto neuwagenAI Mode"
        self.assertEqual(clean_suggestion_text(dirty_ai), "abrufschein auto neuwagen")

        clean = "climate change facts"
        self.assertEqual(clean_suggestion_text(clean), "climate change facts")

    def test_upload_and_suggestions_endpoint_with_version_and_vtag(self):
        payload = {
            "entries": [
                {
                    "timestamp": "2026-08-20T12:00:00Z",
                    "query": "renewable energy",
                    "suggestions": [
                        {"text": "renewable energy sources.ZFiwCf{color:red}", "score": 0.0},
                        {"text": "renewable energy scam", "score": 0.72}
                    ],
                    "googleTld": "www.google.com",
                    "language": "en-US"
                }
            ],
            "uploadedAt": "2026-08-20T12:00:00Z",
            "version": "1.0.3",
            "v_tag": "Ordovician"
        }

        res = self.client.post('/api/upload', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['received'], 1)
        self.assertEqual(data['suggestionsSaved'], 2)
        self.assertEqual(data['version'], '1.0.3')
        self.assertEqual(data['v_tag'], 'Ordovician')

        # Query /api/suggestions
        s_res = self.client.get('/api/suggestions?limit=2')
        self.assertEqual(s_res.status_code, 200)
        s_data = s_res.get_json()
        self.assertGreaterEqual(s_data['total'], 2)
        last_suggs = s_data['suggestions']
        suggestions_texts = [s['suggestion'] for s in last_suggs]
        self.assertIn('renewable energy sources', suggestions_texts)
        self.assertIn('renewable energy scam', suggestions_texts)
        self.assertEqual(last_suggs[0]['version'], '1.0.3')
        self.assertEqual(last_suggs[0]['v_tag'], 'Ordovician')

    def test_report_endpoint(self):
        report_payload = {
            "reportType": "problematic_suggestions",
            "query": "election integrity",
            "suggestions": [
                {"text": "election stolen hoax.ZFiwCf{display:none}", "score": 0.85}
            ],
            "comment": "This suggestion promotes false voter fraud claims.",
            "googleTld": "www.google.com",
            "language": "en-US",
            "version": "1.0.3",
            "v_tag": "Ordovician"
        }

        res = self.client.post('/api/report', json=report_payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['report']['reportType'], 'problematic_suggestions')
        self.assertEqual(data['report']['version'], '1.0.3')
        self.assertEqual(data['report']['v_tag'], 'Ordovician')
        self.assertEqual(data['report']['suggestions'][0]['text'], 'election stolen hoax')

        # Test GET /api/reports
        r_res = self.client.get('/api/reports?limit=5')
        self.assertEqual(r_res.status_code, 200)
        r_data = r_res.get_json()
        self.assertGreaterEqual(r_data['total'], 1)
        self.assertTrue(any(r['query'] == 'election integrity' for r in r_data['reports']))

    def test_update_uploads_endpoint(self):
        res = self.client.post('/api/update-uploads')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('uploadsPath', data)
        self.assertIn('uploadCount', data)
        self.assertIn('totalSuggestions', data)

    def test_download_endpoints(self):
        res = self.client.get('/api/download/uploads.jsonl')
        self.assertEqual(res.status_code, 200)
        self.assertIn('attachment', res.headers.get('Content-Disposition', ''))

        s_res = self.client.get('/api/download/suggestions.jsonl')
        self.assertEqual(s_res.status_code, 200)

        r_res = self.client.get('/api/download/reports.jsonl')
        self.assertEqual(r_res.status_code, 200)

        # Test disallowed file
        bad_res = self.client.get('/api/download/secrets.txt')
        self.assertEqual(bad_res.status_code, 404)

    def test_ratings_api_endpoints(self):
        # 1. Test status endpoint
        st_res = self.client.get('/api/ratings/status')
        self.assertEqual(st_res.status_code, 200)
        st_data = st_res.get_json()
        self.assertIn('is_running', st_data)
        self.assertIn('stage', st_data)
        self.assertIn('progress', st_data)
        self.assertIn('model', st_data)
        self.assertIn('logs', st_data)

        # 2. Test history endpoint
        hist_res = self.client.get('/api/ratings/history')
        self.assertEqual(hist_res.status_code, 200)
        hist_data = hist_res.get_json()
        self.assertIn('total', hist_data)
        self.assertIn('history', hist_data)

    def test_dashboard_page(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('⭐ Bias Rating Engine', html)
        self.assertIn('tab-ratings', html)
        self.assertIn('📊 Bias Scores', html)
        self.assertIn('tab-scores', html)
        self.assertIn('scores-table', html)
        self.assertIn('scores-category-select', html)
        self.assertIn('scores-sort-select', html)
        self.assertIn('cat-filter-card', html)
        self.assertIn('Run Incremental Rating', html)
        self.assertIn('Run Full Initial Rating', html)
        self.assertIn('rating-progress-bar', html)
        self.assertIn('Silurian', html)

    def test_upload_with_pseudonym(self):
        payload = {
            'user_pseudonym': 'Curious-Fox-42',
            'version': '1.1.0',
            'v_tag': 'Silurian',
            'entries': [
                {
                    'query': 'politiker skandal',
                    'suggestions': [{'text': 'politiker skandale aktuell', 'score': 0.45}],
                    'googleTld': 'www.google.de',
                    'language': 'de'
                }
            ]
        }
        res = self.client.post('/api/upload', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('user_pseudonym'), 'Curious-Fox-42')
        self.assertEqual(data.get('v_tag'), 'Silurian')

        # Check suggestions.jsonl contains user_pseudonym
        with open(SUGGESTIONS_FILE, 'r', encoding='utf-8') as f:
            lines = [json.loads(line) for line in f if line.strip()]
        last_sugg = lines[-1]
        self.assertEqual(last_sugg.get('user_pseudonym'), 'Curious-Fox-42')

    def test_download_bundle(self):
        res = self.client.get('/api/download/bundle')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get('Content-Type'), 'application/zip')
        self.assertIn('browsebias_dataset_bundle.zip', res.headers.get('Content-Disposition', ''))

    def test_admin_auth_protection(self):
        import app as app_module
        original_pw = app_module.ADMIN_PASSWORD
        try:
            app_module.ADMIN_PASSWORD = "test-secret-admin-pass"

            # Admin dashboard should return 401 without auth
            res_unauth = self.client.get('/')
            self.assertEqual(res_unauth.status_code, 401)

            # Rating start should return 401 without auth
            res_rating = self.client.post('/api/ratings/start', json={})
            self.assertEqual(res_rating.status_code, 401)

            # Models refresh should return 401 without auth
            res_models = self.client.post('/api/models/refresh')
            self.assertEqual(res_models.status_code, 401)

            # With X-Admin-Key header, admin dashboard returns 200
            res_auth = self.client.get('/', headers={'X-Admin-Key': 'test-secret-admin-pass'})
            self.assertEqual(res_auth.status_code, 200)

            # Public endpoints must remain open without auth
            res_lexicon = self.client.get('/api/lexicon')
            self.assertEqual(res_lexicon.status_code, 200)

            res_viewer = self.client.get('/viewer')
            self.assertEqual(res_viewer.status_code, 200)
        finally:
            app_module.ADMIN_PASSWORD = original_pw


if __name__ == '__main__':
    unittest.main()

