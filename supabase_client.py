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
    active_key = SUPABASE_KEY if token else (SUPABASE_SERVICE_KEY or SUPABASE_KEY)
    headers = {'apikey': active_key, 'Authorization': 'Bearer ' + (token or active_key)}
    if method == 'POST' and 'on_conflict=' in path:
        headers['Prefer'] = 'resolution=merge-duplicates,return=minimal'
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
    from urllib.parse import quote
    req=urllib.request.Request(SUPABASE_URL+'/storage/v1/object/'+quote(bucket,safe='')+'/'+quote(path,safe='/'),
      data=raw, method='POST', headers={'apikey':active_key,'Authorization':'Bearer '+active_key,
      'Content-Type':mime,'x-upsert':'true'})
    for attempt in range(2):
      try:
        with urllib.request.urlopen(req,timeout=30) as response:
          return response.read()
      except urllib.error.HTTPError as exc:
        try: detail=json.loads(exc.read())
        except (ValueError,UnicodeError): detail={}
        code=str(detail.get('code') or detail.get('error') or '')
        message=str(detail.get('message') or '').lower()
        missing=code in ('NoSuchBucket','BucketNotFound') or 'bucket not found' in message
        if missing and attempt==0 and bucket=='course-files' and SUPABASE_SERVICE_KEY:
          try:
            request('/storage/v1/bucket','POST',{'id':bucket,'name':bucket,'public':False,'file_size_limit':10485760})
          except urllib.error.HTTPError as create_error:
            # Another simultaneous upload may already have created it.
            if create_error.code!=409:
              raise ValueError('Le stockage des supports ne peut pas être initialisé. Vérifiez la configuration Supabase.') from None
          continue
        if missing:raise ValueError('Le stockage des supports est absent dans Supabase.') from None
        if exc.code in (401,403) or code in ('AccessDenied','Unauthorized'):
          raise ValueError('Supabase refuse le dépôt du fichier. Vérifiez la clé serveur et les droits du stockage.') from None
        if code=='InvalidKey':raise ValueError('Le nom de stockage du fichier a été refusé.') from None
        if exc.code==413 or code=='EntityTooLarge':raise ValueError('Le fichier dépasse la taille autorisée par le stockage.') from None
        raise ValueError('Supabase n’a pas accepté le fichier (code '+str(exc.code)+'). Réessayez ou vérifiez les réglages du stockage.') from None
      except (urllib.error.URLError,TimeoutError):
        raise ValueError('Le stockage ne répond pas. Réessayez dans quelques instants.') from None

def auth_login(email, password):
    """Authentifie un utilisateur via Supabase Auth."""
    import urllib.request, json
    active_key=SUPABASE_KEY
    req=urllib.request.Request(SUPABASE_URL+'/auth/v1/token?grant_type=password',
      data=json.dumps({'email':email,'password':password}).encode(), method='POST',
      headers={'apikey':active_key,'Authorization':'Bearer '+active_key,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=12) as response:
      return json.loads(response.read())

def auth_user(token):
    return request('/auth/v1/user', token=token)

def download_file(bucket, path):
    from urllib.parse import quote
    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
    req = urllib.request.Request(SUPABASE_URL+'/storage/v1/object/authenticated/'+quote(bucket,safe='')+'/'+quote(path,safe='/'),
        headers={'apikey':key,'Authorization':'Bearer '+key})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()
