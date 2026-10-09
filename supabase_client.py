"""Client REST Supabase minimal, sans dépendance externe."""
import json, os, urllib.request, urllib.error

def _load_env():
    path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_KEY = os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')

def configured():
    return bool(SUPABASE_URL and SUPABASE_KEY)

def request(path, method='GET', payload=None, token=None):
    if not configured():
        raise RuntimeError('Supabase non configuré')
    headers = {'apikey': SUPABASE_KEY, 'Authorization': 'Bearer ' + (token or SUPABASE_KEY)}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(SUPABASE_URL + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=12) as response:
        raw = response.read()
        return json.loads(raw) if raw else None

def health():
    return request('/rest/v1/contents?select=id&limit=1')
