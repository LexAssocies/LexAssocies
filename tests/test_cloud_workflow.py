"""Regression: every request may execute in a fresh Vercel instance."""
import copy
import base64
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
        orders = {}
        storage = {}
        profile = {'id': 'ca7faab4-12b9-4c83-96e1-7d0a0b967def', 'name': 'Admin', 'role': 'owner', 'suspended': False}
        failed = False
        def remote(path, method='GET', payload=None, token=None):
            if 'profiles?' in path:
                return [profile]
            collection = orders if '/orders?' in path else catalogue
            if method == 'GET':
                return list(copy.deepcopy(collection).values())
            if failed:
                raise RuntimeError('Simulated remote outage')
            collection[payload['id']] = copy.deepcopy(payload)
            if collection is orders:collection[payload['id']]['created_at']='2026-10-09T00:00:00Z'
        def upload(bucket, path, raw, mime):
            storage[path] = raw
        with patch.dict(os.environ, {'VERCEL': '1', 'LEX_SESSION_SECRET': 'regression-secret'}), \
             patch.object(supabase_client, 'SUPABASE_SERVICE_KEY', 'test-server-key'), \
             patch.object(supabase_client, 'request', remote), \
             patch.object(server, 'supabase_request', remote), \
             patch.object(server, 'supabase_upload', upload), \
             patch.object(supabase_client, 'download_file', side_effect=lambda bucket,path:storage[path]), \
             patch.object(server, 'supabase_auth_login', return_value={'access_token': 'test-jwt', 'user': {'id': profile['id']}}):
            http = server.ThreadingHTTPServer(('127.0.0.1', 4187), server.App)
            threading.Thread(target=http.serve_forever, daemon=True).start()
            cookie = ''
            def request(route, body=None, expected=200):
                nonlocal cookie
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
                    raw = response.read()
                    result = json.loads(raw) if response.headers.get('Content-Type','').startswith('application/json') else raw
                    self.assertEqual(response.code, expected, result)
                    cart_headers=[h for h in response.headers.get_all('Set-Cookie',[]) if h.startswith('lex_cart=')]
                    if cart_headers:
                        parts=[p for p in cookie.split('; ') if p and not p.startswith('lex_cart=')]
                        cookie='; '.join(parts+[cart_headers[-1].split(';')[0]])
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
                # Uploads remain downloadable after cold start, then detach reliably.
                fid=request('admin/upload',{'item_id':item['id'],'name':'support.txt','content':base64.b64encode(b'private support').decode()})[0]['id']
                self.assertEqual(len(request('item/'+item['id'])[0]['files']),1)
                self.assertEqual(request('file/'+fid)[0],b'private support')
                # A stale edit must not discard newly attached files.
                item['purchasable']=True
                request('admin/item',{'item':item})
                self.assertEqual(len(request('item/'+item['id'])[0]['files']),1)
                request('admin/upload-remove',{'item_id':item['id'],'id':fid})
                self.assertEqual(request('item/'+item['id'])[0]['files'],[])
                request('file/'+fid,expected=404)
                # Signed cart survives fresh instances and checkout validates every field.
                profile['role']='member'
                request('admin/upload-remove',{'item_id':item['id'],'id':fid},403)
                request('cart',{'id':item['id'],'quantity':2})
                self.assertEqual(request('account')[0]['cart'][0]['quantity'],2)
                checkout={'last_name':'Client','first_name':'Test','phone':'+225 0700000000','address':'Abidjan, quartier test','request_id':'cloud-order-request-123'}
                for field in ['last_name','first_name','phone','address']:
                    request('order',{**checkout,field:' '},400)
                failed=True
                request('order',checkout,500)
                self.assertEqual(len(orders),0)
                self.assertEqual(len(request('account')[0]['cart']),1)
                failed=False
                oid=request('order',checkout)[0]['id']
                self.assertEqual(request('account')[0]['cart'],[])
                self.assertEqual(request('order',checkout)[0]['id'],oid)
                self.assertEqual(len(orders),1)
                self.assertEqual(request('account')[0]['orders'][0]['total'],150000)
                profile['role']='owner'
                overview=request('admin/overview')[0]['orders'][0]
                self.assertEqual(overview['delivery']['address'],checkout['address'])
                request('admin/order',{'id':oid,'status':'processing','note':'Préparation'})
                self.assertEqual(request('account')[0]['orders'][0]['status'],'processing')
                self.assertEqual(len(request('admin/overview')[0]['orders'][0]['history']),1)
                failed = True
                request('admin/archive', {'id': item['id']}, 500)
                self.assertEqual(request('bootstrap')[0]['items'][0]['status'], 'published')
                cookie=cookie.split('; ')[0]
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
