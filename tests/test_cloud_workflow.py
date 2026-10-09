"""Regression: every request may execute in a fresh Vercel instance."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error

os.environ['LEX_DATA_DIR'] = tempfile.mkdtemp()
os.environ['LEX_PORT'] = '4187'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import cloud_state
import supabase_client

class CloudWorkflow(unittest.TestCase):
    def test_session_and_catalogue_across_cold_instances(self):
        catalogue = {}
        profile = {'id': 'ca7faab4-12b9-4c83-96e1-7d0a0b967def', 'name': 'Admin', 'role': 'owner', 'suspended': False}
        failed = False
        def remote(path, method='GET', payload=None, token=None):
            if 'profiles?' in path:
                return [profile]
            if method == 'GET':
                return list(copy.deepcopy(catalogue).values())
            if failed:
                raise RuntimeError('Simulated remote outage')
            catalogue[payload['id']] = copy.deepcopy(payload)
        with patch.dict(os.environ, {'VERCEL': '1', 'LEX_SESSION_SECRET': 'regression-secret'}), \
             patch.object(supabase_client, 'SUPABASE_SERVICE_KEY', 'test-server-key'), \
             patch.object(supabase_client, 'request', remote), \
             patch.object(server, 'supabase_request', remote), \
             patch.object(server, 'supabase_auth_login', return_value={'access_token': 'test-jwt', 'user': {'id': profile['id']}}):
            http = server.ThreadingHTTPServer(('127.0.0.1', 4187), server.App)
            threading.Thread(target=http.serve_forever, daemon=True).start()
            cookie = ''
            def request(route, body=None, expected=200):
                # Fresh storage on EVERY read/write: no session or content cache survives.
                server.DATA = Path(tempfile.mkdtemp())
                (server.DATA / 'files').mkdir()
                server.initialize()
                req = urllib.request.Request('http://127.0.0.1:4187/api/' + route,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'Cookie': cookie, 'Origin': 'http://127.0.0.1:4187', 'Content-Type': 'application/json'})
                try:
                    response = urllib.request.urlopen(req)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    result = json.loads(response.read())
                    self.assertEqual(response.code, expected, result)
                    return result, response.headers
            try:
                _, headers = request('login', {'email': 'admin@example.test', 'password': 'example-password'})
                cookie = next(x.split(';')[0] for x in headers.get_all('Set-Cookie') if x.startswith('lex_cloud='))
                self.assertEqual(request('bootstrap')[0]['user']['role'], 'owner')
                item = {'id': 'cloud-training', 'kind': 'formation', 'title': 'Formation test', 'category': 'Général', 'status': 'published', 'price': 45000, 'modules': [], 'placements': []}
                request('admin/item', {'item': item})
                self.assertEqual(len(request('admin')[0]['items']), 1)
                self.assertEqual(request('bootstrap')[0]['items'][0]['price'], 45000)
                request('admin/archive', {'id': item['id']})
                self.assertEqual(request('bootstrap')[0]['items'], [])
                self.assertEqual(request('admin')[0]['items'][0]['status'], 'archived')
                request('admin/overview')
                profile['suspended'] = True
                request('admin', expected=403)
                profile['suspended'] = False
                profile['role'] = 'member'
                request('admin', expected=403)
                profile['role'] = 'owner'
                request('admin/archive', {'id': item['id'], 'restore': True})
                self.assertEqual(request('bootstrap')[0]['items'][0]['price'], 45000)
                item['price'] = 75000
                request('admin/item', {'item': item})
                self.assertEqual(len(catalogue), 1)
                self.assertEqual(request('bootstrap')[0]['items'][0]['price'], 75000)
                failed = True
                request('admin/archive', {'id': item['id']}, 500)
                self.assertEqual(request('bootstrap')[0]['items'][0]['status'], 'published')
                forged = cookie[:-1] + ('0' if cookie[-1] != '0' else '1')
                valid = cookie
                cookie = forged
                request('admin', expected=403)
                cookie = valid
                _, headers = request('logout', {})
                self.assertTrue(any('lex_cloud=;' in x and 'Max-Age=0' in x for x in headers.get_all('Set-Cookie')))
                cookie = ''
                request('admin', expected=403)
            finally:
                http.shutdown()
                http.server_close()

    def test_auth_token_is_not_api_key_and_upsert_merges(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        with patch.object(urllib.request, 'urlopen', return_value=response) as opening:
            supabase_client.auth_user('user-jwt')
            req = opening.call_args.args[0]
            self.assertEqual(req.get_header('Apikey'), supabase_client.SUPABASE_KEY)
            self.assertEqual(req.get_header('Authorization'), 'Bearer user-jwt')
            supabase_client.request('/rest/v1/contents?on_conflict=id', 'POST', {})
            self.assertIn('merge-duplicates', opening.call_args.args[0].get_header('Prefer'))

if __name__ == '__main__':
    unittest.main()
