"""Shared catalogue and authenticated sessions for stateless hosting."""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
import supabase_client as remote

def enabled():
    return bool(os.environ.get('VERCEL'))

def session_key():
    key = os.environ.get('LEX_SESSION_SECRET') or remote.SUPABASE_SERVICE_KEY
    if not key:
        raise RuntimeError('Clé serveur de session manquante.')
    return key.encode()

def sign_user(user):
    claims = {k: user[k] for k in ('id', 'name', 'email', 'role')}
    claims['expires'] = int(time.time()) + 86400 * 7
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return body + '.' + hmac.new(session_key(), body.encode(), hashlib.sha256).hexdigest()

def verify_user(token):
    try:
        body, signature = token.split('.')
        expected = hmac.new(session_key(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        claims = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        if claims['expires'] <= time.time() or claims['role'] not in ('member', 'editor', 'admin', 'owner'):
            return None
        return claims
    except (ValueError, KeyError, TypeError):
        return None

def sync_catalogue(c):
    # Fetch all statuses with the server key. Never replace a failed read by seeds.
    if not remote.SUPABASE_SERVICE_KEY:
        raise RuntimeError('SUPABASE_SECRET_KEY est requis sur Vercel.')
    rows = []
    offset = 0
    while True:
        batch = remote.request('/rest/v1/contents?select=*&order=id&limit=1000&offset=' + str(offset)) or []
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += len(batch)
    ids = set()
    for row in rows:
        payload = dict(row.get('payload') or {})
        local_id = str(payload.get('_local_id') or row['id'])
        if local_id in ids:
            raise RuntimeError('Identifiant de contenu dupliqué dans Supabase.')
        ids.add(local_id)
        payload['_supabase_id'] = row['id']
        updated = datetime.fromisoformat(row['updated_at'].replace('Z', '+00:00')).timestamp()
        c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,title=excluded.title,category=excluded.category,status=excluded.status,payload=excluded.payload,updated=excluded.updated',
                  (local_id, row['kind'], row['title'], row.get('category') or '', row['status'], json.dumps(payload), updated))
    # Old seed rows cannot reappear in either catalogue or trash.
    for row in c.execute('SELECT id FROM items').fetchall():
        if row['id'] not in ids:
            c.execute('UPDATE items SET status=? WHERE id=?', ('unavailable', row['id']))

def save_content(item_id, kind, title, category, status, payload, remote_id=None):
    rid = remote_id or payload.get('_supabase_id') or str(uuid.uuid5(uuid.NAMESPACE_URL, 'lex-associes:' + item_id))
    body = dict(payload)
    body.pop('_supabase_id', None)
    body['_local_id'] = item_id
    remote.request('/rest/v1/contents?on_conflict=id', 'POST', {
        'id': rid, 'kind': kind, 'title': title, 'category': category,
        'status': status, 'payload': body, 'updated_at': datetime.now(timezone.utc).isoformat()
    })
