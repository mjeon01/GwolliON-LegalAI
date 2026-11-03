"""HTTP document navigation must support direct visits and refreshes."""
from pathlib import Path
import tempfile
import unittest
import re
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app


FRONTEND_DIR = Path(__file__).resolve().parents[1] / 'frontend/dist'


@unittest.skipUnless((FRONTEND_DIR / 'index.html').is_file(),
                     'Run npm --prefix frontend run build first')
class WorkspaceRouteTests(unittest.TestCase):
    def test_each_task_and_deep_link_serves_the_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(create_app(Path(folder) / 'workspace.sqlite3')) as client:
                for page in ('', 'upload/', 'samples/', 'review/?id=missing', 'chat/?id=missing',
                             'draft/?id=missing', 'documents/', 'history/', 'original/?id=missing',
                             'sources/?id=missing', 'confirm/?id=missing'):
                    with self.subTest(page=page):
                        response = client.get('/' + page)
                        self.assertEqual(response.status_code, 200)
                        self.assertIn('type="module"', response.text)
                        self.assertIn('/assets/', response.text)
                self.assertEqual(client.get('/api/analyses/missing').status_code, 404)
                for removed in ('/static/runtime.js', '/guide/', '/language/'):
                    self.assertEqual(client.get(removed).status_code, 404)

    def test_built_frontend_assets_and_api_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(create_app(Path(folder) / 'workspace.sqlite3')) as client:
                home = client.get('/')
                assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', home.text)
                self.assertTrue(assets)
                for asset in assets:
                    response = client.get(asset)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn('text/html', response.headers['content-type'])
                    self.assertIn("script-src 'self'", response.headers['content-security-policy'])
                for page in ('upload', 'samples', 'review', 'chat', 'draft', 'history', 'original', 'sources', 'confirm'):
                    self.assertEqual(client.get(f'/{page}/?id=test&finding=R001').text, home.text)
                self.assertEqual(client.get('/api/not-a-real-route').status_code, 404)
                self.assertEqual(client.get('/assets/not-a-real-script.js').status_code, 404)
                self.assertEqual(client.get('/not-a-real-page').status_code, 404)

    def test_sample_pdf_links_still_download_after_relocation(self):
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(create_app(Path(folder) / 'workspace.sqlite3')) as client:
                samples = client.get('/api/samples').json()
                self.assertEqual(len(samples), 6)
                for sample in samples:
                    with self.subTest(sample=sample['id']):
                        response = client.get(f"/api/samples/{sample['id']}/pdf")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.headers['content-type'], 'application/pdf')
                        self.assertTrue(response.content.startswith(b'%PDF-'))


class MissingFrontendTests(unittest.TestCase):
    def test_missing_build_explains_setup_without_serving_legacy_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('backend.app.FRONTEND_DIR', Path(folder) / 'dist'):
                with TestClient(create_app(Path(folder) / 'workspace.sqlite3')) as client:
                    response = client.get('/')
                    self.assertEqual(response.status_code, 503)
                    self.assertIn('./run_app.sh', response.json()['detail'])
                    self.assertEqual(client.get('/api/samples').status_code, 200)
                    self.assertEqual(client.get('/assets/missing.js').status_code, 404)
