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
        sync_files(c, local_id, payload)
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

def sync_files(c, item_id, payload):
    c.execute('DELETE FROM uploads WHERE item_id=?', (item_id,))
    for f in payload.get('_attachments', []):
        c.execute('INSERT INTO uploads VALUES(?,?,?,?,?,?)',
                  (f['id'], item_id, f['name'], f['mime'], f['size'], f['path']))

def save_order(order_id, user, total, lines, delivery, status='pending', history=None):
    envelope = {'items': lines, 'delivery': delivery, 'user_id': user['id'],
                'name': user['name'], 'email': user['email'], 'history': history or []}
    remote.request('/rest/v1/orders?on_conflict=id', 'POST', {
        'id': order_id, 'user_id': None, 'status': status, 'total': total, 'lines': envelope})

def sync_orders(c):
    rows = []
    offset = 0
    while True:
        batch = remote.request('/rest/v1/orders?select=*&order=id&limit=1000&offset=' + str(offset)) or []
        rows.extend(batch)
        if len(batch) < 1000:break
        offset += len(batch)
    for row in rows:
        envelope = row['lines'] if isinstance(row['lines'], dict) else {}
        uid = envelope.get('user_id') or row.get('user_id')
        if not uid:continue
        c.execute('INSERT OR IGNORE INTO users VALUES(?,?,?,?,?,?)',
                  (uid, envelope.get('name') or '', envelope.get('email') or uid+'@unknown.invalid', '0'*32+':'+'0'*64, 'member', time.time()))
        created = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')).timestamp()
        c.execute('INSERT INTO orders(id,user_id,status,total,lines,created,delivery) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,total=excluded.total,lines=excluded.lines,delivery=excluded.delivery',
                  (row['id'], uid, row['status'], row['total'], json.dumps(envelope.get('items', row['lines'])), created, json.dumps(envelope.get('delivery', {}))))
        c.execute('DELETE FROM order_updates WHERE order_id=?', (row['id'],))
        for h in envelope.get('history', []):
            c.execute('INSERT OR IGNORE INTO users VALUES(?,?,?,?,?,?)', (h['admin_id'], 'Administrateur', h['admin_id']+'@unknown.invalid', '0'*32+':'+'0'*64, 'member', time.time()))
            c.execute('INSERT INTO order_updates VALUES(?,?,?,?,?,?)', (h['id'],row['id'],h['admin_id'],h['status'],h['note'],h['created']))

def sign_cart(user_id, cart):
    body = base64.urlsafe_b64encode(json.dumps({'user_id': user_id, 'cart': cart}).encode()).decode().rstrip('=')
    return body + '.' + hmac.new(session_key(), ('cart:'+body).encode(), hashlib.sha256).hexdigest()

def verify_cart(token, user_id):
    try:
        body, signature = token.split('.')
        if not hmac.compare_digest(signature, hmac.new(session_key(), ('cart:'+body).encode(), hashlib.sha256).hexdigest()):return []
        value = json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        return value['cart'] if value['user_id']==user_id else []
    except (ValueError,KeyError,TypeError):return []
