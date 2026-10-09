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
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')

def configured():
    return bool(SUPABASE_URL and SUPABASE_KEY)

def request(path, method='GET', payload=None, token=None):
    if not configured():
        raise RuntimeError('Supabase non configuré')
    active_key = token or SUPABASE_SERVICE_KEY or SUPABASE_KEY
    headers = {'apikey': active_key, 'Authorization': 'Bearer ' + active_key}
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

def upload_file(bucket, path, raw, mime='application/octet-stream'):
    if not configured():
        raise RuntimeError('Supabase non configuré')
    import urllib.request
    active_key=SUPABASE_SERVICE_KEY or SUPABASE_KEY
    req=urllib.request.Request(SUPABASE_URL+'/storage/v1/object/'+bucket+'/'+path,
      data=raw, method='POST', headers={'apikey':active_key,'Authorization':'Bearer '+active_key,
      'Content-Type':mime,'x-upsert':'true'})
    with urllib.request.urlopen(req,timeout=30) as response:
      return response.read()
