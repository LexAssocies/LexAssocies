"""LEX ASSOCIÉS local platform. Run python server.py; binds to loopback only."""
import base64, hashlib, hmac, json, mimetypes, os, re, secrets, sqlite3, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('LEX_DATA_DIR',ROOT/'data'))
DATA.mkdir(parents=True,exist_ok=True)
(DATA/'files').mkdir(exist_ok=True)
PORT=int(os.environ.get('LEX_PORT','4180'))
from security import STAFF, initialize_security, suspended, audit, get_security, account_action, recover
from admin_support import initialize_admin, admin_get, admin_post, track_visit, validate_content
import seo
def db():
 c=sqlite3.connect(DATA/'lex.sqlite',timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def initialize():
 with db() as c:
  c.executescript('''
  PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'member',created REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id) ON DELETE CASCADE,expires REAL);
  CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,category TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'draft',payload TEXT NOT NULL,updated REAL NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_items_kind_status ON items(kind,status);
  CREATE TABLE IF NOT EXISTS favorites(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,item_id TEXT REFERENCES items(id) ON DELETE CASCADE,PRIMARY KEY(user_id,item_id));
  CREATE TABLE IF NOT EXISTS enrollments(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,item_id TEXT REFERENCES items(id) ON DELETE CASCADE,created REAL,PRIMARY KEY(user_id,item_id));
  CREATE TABLE IF NOT EXISTS progress(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,item_id TEXT REFERENCES items(id) ON DELETE CASCADE,module_id TEXT,completed REAL,PRIMARY KEY(user_id,item_id,module_id));
  CREATE TABLE IF NOT EXISTS cart(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,item_id TEXT REFERENCES items(id) ON DELETE CASCADE,quantity INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(user_id,item_id));
  CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),status TEXT NOT NULL,total INTEGER NOT NULL,lines TEXT NOT NULL,created REAL NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id,created);
  CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,email TEXT,phone TEXT,subject TEXT,body TEXT,created REAL,status TEXT DEFAULT 'new');
  CREATE TABLE IF NOT EXISTS newsletter(email TEXT PRIMARY KEY,name TEXT,interests TEXT,created REAL);
  CREATE TABLE IF NOT EXISTS event_registrations(user_id TEXT REFERENCES users(id),item_id TEXT REFERENCES items(id) ON DELETE CASCADE,created REAL,PRIMARY KEY(user_id,item_id));
  CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),message TEXT,url TEXT,seen INTEGER DEFAULT 0,created REAL);
  CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,item_id TEXT REFERENCES items(id) ON DELETE CASCADE,name TEXT,mime TEXT,size INTEGER,path TEXT);
  CREATE TABLE IF NOT EXISTS downloads(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),upload_id TEXT,name TEXT,created REAL);
  CREATE TABLE IF NOT EXISTS attempts(ip TEXT,action TEXT,created REAL);
  CREATE TABLE IF NOT EXISTS certificates(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),item_id TEXT REFERENCES items(id),title TEXT,name TEXT,created REAL,UNIQUE(user_id,item_id));
  CREATE INDEX IF NOT EXISTS idx_attempts ON attempts(ip,action,created);
  ''')
  initialize_admin(c,DATA)
  initialize_security(c)
  if not c.execute('SELECT 1 FROM items LIMIT 1').fetchone():
   for item in json.loads((ROOT/'seed.json').read_text(encoding='utf-8')):
    c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',(item['id'],item['kind'],item['title'],item.get('category',''),item.get('status','published'),json.dumps(item,ensure_ascii=False),time.time()))

def pack(row,full=False):
 p=json.loads(row['payload']);p.update(id=row['id'],kind=row['kind'],title=row['title'],category=row['category'],status=row['status'],updated=row['updated'])
 if not full:
  for m in p.get('modules',[]):
   m.pop('body',None);m.pop('video',None);m.pop('quiz',None);m.pop('exercise',None);m.pop('correction',None)
 return p
def password(value,salt=None):
 salt=salt or secrets.token_hex(16)
 return salt+':'+hashlib.pbkdf2_hmac('sha256',value.encode(),bytes.fromhex(salt),600000).hex()
def clean(value,n=5000):return str(value or '').strip()[:n]
def email(value):
 value=clean(value,254).lower()
 if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):raise ValueError('Adresse e-mail invalide.')
 return value
class App(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'dist'),**kwargs)
 def log_message(self,*args):pass
 def headers_security(self):
  self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin');self.send_header('X-Frame-Options','DENY')
 def reply(self,data,status=200,cookie=None):
  if status<400 and getattr(self,'transaction',None):
   if getattr(self,'audit_actor',None):
    audit(self.transaction,self.audit_actor,self.audit_action,self.audit_target)
    self.audit_actor=None
   self.transaction.commit();self.transaction=None
  raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.headers_security()
  if cookie:self.send_header('Set-Cookie',cookie)
  self.end_headers();self.wfile.write(raw)
 def identity(self,c):
  cookie=self.headers.get('Cookie','');match=re.search(r'(?:^|;\s*)lex_session=([a-f0-9]{64})(?:;|$)',cookie)
  if not match:return None
  return c.execute('SELECT users.* FROM users JOIN sessions ON sessions.user_id=users.id WHERE token=? AND expires>? AND NOT EXISTS(SELECT 1 FROM user_security WHERE user_id=users.id AND suspended=1)',(hashlib.sha256(match[1].encode()).hexdigest(),time.time())).fetchone()
 def need(self,c,admin=False):
  u=self.identity(c)
  if not u:raise PermissionError('Connectez-vous pour continuer.')
  if admin and u['role'] not in STAFF:raise PermissionError('Accès réservé à l’administration.')
  return u
 def allowed_host(self):return self.headers.get('Host') in (f'localhost:{PORT}',f'127.0.0.1:{PORT}')
 def do_GET(self):
  if not self.allowed_host():return self.reply({'error':'Hôte non autorisé.'},403)
  path=urlparse(self.path).path
  if path=='/api/seo':
   with db() as c:return self.reply(seo.metadata(c,parse_qs(urlparse(self.path).query).get('route',['/'])[0],self.headers.get('Host','')))
  if path in ('/robots.txt','/sitemap.xml'):
   with db() as c:body=seo.robots(self.headers.get('Host','')) if path=='/robots.txt' else seo.sitemap(c,self.headers.get('Host',''))
   return self.page_response(body,'text/plain' if path=='/robots.txt' else 'application/xml')
  if path=='/index.html':
   self.send_response(301);self.send_header('Location','/');self.end_headers();return
  if not path.startswith('/api/') and (path=='/' or not Path(path).suffix):
   with db() as c:body,meta=seo.document(c,self.path,self.headers.get('Host',''))
   return self.page_response(body,'text/html',meta['status'],meta['robots'])
  if not path.startswith('/api/'):
   if path=='/':self.path='/index.html'
   return super().do_GET()
  try:
   with db() as c:
    u=self.identity(c)
    if path=='/api/bootstrap':
     items=[pack(r) for r in c.execute("SELECT * FROM items WHERE status='published' ORDER BY updated DESC")]
     return self.reply({'items':items,'user':{k:u[k] for k in ('id','name','email','role')} if u else None,'setup':not c.execute("SELECT 1 FROM users WHERE role='owner'").fetchone(),'payments':False})
    if path.startswith('/api/item/'):
     itemid=unquote(path.split('/')[-1]);r=c.execute('SELECT * FROM items WHERE id=?',(itemid,)).fetchone()
     if not r or (r['status']!='published' and (not u or u['role'] not in STAFF)):return self.reply({'error':'Contenu introuvable.'},404)
     access=bool(u and (u['role'] in STAFF or c.execute('SELECT 1 FROM enrollments WHERE user_id=? AND item_id=?',(u['id'],itemid)).fetchone()))
     data=pack(r,access);data['access']=access
     if not u or u['role'] not in STAFF:
      for m in data.get('modules',[]):
       for q in m.get('quiz',[]):q.pop('correct',None)
     data['files']=[dict(x) for x in c.execute('SELECT id,name,mime,size FROM uploads WHERE item_id=?',(itemid,))]
     data['completed']=[x[0] for x in c.execute('SELECT module_id FROM progress WHERE user_id=? AND item_id=?',(u['id'],itemid))] if u else []
     return self.reply(data)
    if path=='/api/account':
     u=self.need(c);uid=u['id'];result={}
     result['favorites']=[x[0] for x in c.execute('SELECT item_id FROM favorites WHERE user_id=?',(uid,))]
     result['enrollments']=[dict(x) for x in c.execute('SELECT item_id,created FROM enrollments WHERE user_id=?',(uid,))]
     result['progress']=[dict(x) for x in c.execute('SELECT item_id,module_id,completed FROM progress WHERE user_id=?',(uid,))]
     result['cart']=[dict(x) for x in c.execute('SELECT item_id,quantity FROM cart WHERE user_id=?',(uid,))]
     result['orders']=[dict(x) for x in c.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created DESC',(uid,))]
     result['events']=[x[0] for x in c.execute('SELECT item_id FROM event_registrations WHERE user_id=?',(uid,))]
     result['notifications']=[dict(x) for x in c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created DESC',(uid,))]
     result['downloads']=[dict(x) for x in c.execute('SELECT name,created FROM downloads WHERE user_id=? ORDER BY created DESC',(uid,))]
     result['certificates']=[dict(x) for x in c.execute('SELECT id,title,created FROM certificates WHERE user_id=? ORDER BY created DESC',(uid,))]
     return self.reply(result)
    if path.startswith('/api/certificate/'):
     u=self.need(c);cert=c.execute('SELECT * FROM certificates WHERE id=? AND user_id=?',(path.split('/')[-1],u['id'])).fetchone()
     if not cert:return self.reply({'error':'Attestation introuvable.'},404)
     def pdf_text(s):return s.replace('\\','\\\\').replace('(','\\(').replace(')','\\)').encode('cp1252','replace')
     texts=[(25,65,730,'LEX ASSOCIÉS'),(22,65,665,'ATTESTATION DE FIN DE PARCOURS'),(13,65,610,'Cette attestation confirme la validation du parcours par'),(19,65,570,cert['name'][:65]),(13,65,525,cert['title'][:82]),(11,65,450,'Date : '+time.strftime('%d/%m/%Y',time.gmtime(cert['created']))),(10,65,425,'Référence : '+cert['id']),(10,65,370,'Validation des modules et des évaluations du parcours.'),(9,65,340,'Cette attestation ne constitue pas un diplôme reconnu par l’État.')]
     stream=b'\n'.join(b'BT /F1 '+str(sz).encode()+b' Tf '+str(x).encode()+b' '+str(y).encode()+b' Td ('+pdf_text(t)+b') Tj ET' for sz,x,y,t in texts)
     objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
     raw=b'%PDF-1.4\n';offsets=[0]
     for n,obj in enumerate(objects,1):offsets.append(len(raw));raw+=str(n).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
     xref=len(raw);raw+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets[1:])+b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF'
     self.send_response(200);self.send_header('Content-Type','application/pdf');self.send_header('Content-Disposition','attachment; filename="attestation-lex-associes.pdf"');self.send_header('Content-Length',str(len(raw)));self.headers_security();self.end_headers();self.wfile.write(raw);return
    if path=='/api/security':
     return self.reply(get_security(c,self.need(c)))
    if path=='/api/admin/audit':
     u=self.need(c,True)
     if u['role']=='editor':raise PermissionError('Accès réservé aux administrateurs.')
     return self.reply({'events':[dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 300')]})
    if path=='/api/admin/overview':
     u=self.need(c,True)
     if u['role']=='editor':raise PermissionError('Accès réservé aux administrateurs.')
     return self.reply(admin_get(c,parse_qs(urlparse(self.path).query)))
    if path=='/api/admin':
     u=self.need(c,True)
     if u['role']=='editor':return self.reply({'items':[pack(r,True) for r in c.execute('SELECT * FROM items ORDER BY updated DESC')],'messages':[],'newsletter':[],'orders':[],'users':[]})
     return self.reply({'items':[pack(r,True) for r in c.execute('SELECT * FROM items ORDER BY updated DESC')],'messages':[dict(r) for r in c.execute('SELECT * FROM messages ORDER BY created DESC')],'newsletter':[dict(r) for r in c.execute('SELECT * FROM newsletter ORDER BY created DESC')],'orders':[dict(r) for r in c.execute('SELECT * FROM orders ORDER BY created DESC')],'users':[dict(r) for r in c.execute('SELECT id,name,email,role,created FROM users')]})
    if path.startswith('/api/file/'):
     u=self.need(c);r=c.execute('SELECT uploads.*,items.payload,items.status FROM uploads JOIN items ON uploads.item_id=items.id WHERE uploads.id=?',(path.split('/')[-1],)).fetchone()
     if not r:return self.reply({'error':'Fichier introuvable.'},404)
     p=json.loads(r['payload'])
     if u['role'] not in STAFF and (r['status']!='published' or (p.get('price')!=0 and not c.execute('SELECT 1 FROM enrollments WHERE user_id=? AND item_id=?',(u['id'],r['item_id'])).fetchone())):raise PermissionError('Ce contenu nécessite un accès autorisé.')
     raw=(DATA/'files'/r['path']).read_bytes();c.execute('INSERT INTO downloads VALUES(?,?,?,?,?)',(secrets.token_hex(12),u['id'],r['id'],r['name'],time.time()));self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+__import__('urllib.parse',fromlist=['quote']).quote(r['name']));self.send_header('Content-Length',str(len(raw)));self.headers_security();self.end_headers();self.wfile.write(raw);return
    return self.reply({'error':'Page introuvable.'},404)
  except PermissionError as e:self.reply({'error':str(e)},403)
  except Exception:self.reply({'error':'Le service est momentanément indisponible.'},500)
 def page_response(self,body,mime,status=200,robots=None):
  raw=body.encode('utf-8');self.send_response(status);self.send_header('Content-Type',mime+'; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.headers_security()
  if robots:self.send_header('X-Robots-Tag',robots)
  self.end_headers();self.wfile.write(raw)
 def do_POST(self):
  if not self.allowed_host() or self.headers.get('Origin') not in (f'http://localhost:{PORT}',f'http://127.0.0.1:{PORT}'):
   return self.reply({'error':'Origine non autorisée.'},403)
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length>15*1024*1024:raise ValueError('Fichier trop volumineux (10 Mo maximum).')
   data=json.loads(self.rfile.read(length));path=urlparse(self.path).path;now=time.time()
   with db() as c:
    self.transaction=c
    if path=='/api/visit':
     visitor=self.identity(c)
     return self.reply(track_visit(c,data,now,visitor,self.headers))
    if path in ('/api/register','/api/login','/api/admin/setup','/api/recover','/api/contact','/api/newsletter'):
     n=c.execute('SELECT COUNT(*) FROM attempts WHERE ip=? AND action=? AND created>?',(self.client_address[0],path,now-600)).fetchone()[0]
     if n>=30:return self.reply({'error':'Trop de tentatives. Réessayez dans quelques minutes.'},429)
     c.execute('INSERT INTO attempts VALUES(?,?,?)',(self.client_address[0],path,now));c.execute('DELETE FROM attempts WHERE created<?',(now-3600,));c.commit()
    if path=='/api/recover':return self.reply(recover(c,data,password,email))
    if path in ('/api/register','/api/login','/api/admin/setup'):
     mail=email(data.get('email'));pw=clean(data.get('password'),256)
     if path in ('/api/register','/api/admin/setup'):
      if len(pw)<10:raise ValueError('Choisissez un mot de passe de 10 caractères minimum.')
      name=clean(data.get('name'),160)
      if not name:raise ValueError('Indiquez votre nom.')
      c.execute('BEGIN IMMEDIATE')
      role='member'
      if path=='/api/admin/setup':
       if c.execute("SELECT 1 FROM users WHERE role='owner'").fetchone():raise ValueError('Un administrateur est déjà configuré.')
       if not hmac.compare_digest(clean(data.get('setup_code'),100),(DATA/'admin-setup-code.txt').read_text().strip()):raise PermissionError('Code de configuration incorrect.')
       role='owner'
      try:c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(secrets.token_hex(12),name,mail,password(pw),role,now))
      except sqlite3.IntegrityError:raise ValueError('Cette adresse est déjà utilisée. Connectez-vous.')
     u=c.execute('SELECT * FROM users WHERE email=?',(mail,)).fetchone()
     if not u or suspended(c,u['id']) or not hmac.compare_digest(password(pw,u['password'].split(':')[0]),u['password']):raise ValueError('E-mail ou mot de passe incorrect.')
     token=secrets.token_hex(32);c.execute('DELETE FROM sessions WHERE expires<?',(now,));c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],now+86400*7));return self.reply({'ok':True},cookie=f'lex_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800')
    if path=='/api/logout':
     u=self.identity(c)
     cookie=self.headers.get('Cookie','');match=re.search(r'lex_session=([a-f0-9]{64})',cookie)
     if match:c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(match[1].encode()).hexdigest(),))
     return self.reply({'ok':True},cookie='lex_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
    if path=='/api/contact':
     name=clean(data.get('name'),160);body=clean(data.get('message'));mail=email(data.get('email'))
     if not name or not body:raise ValueError('Complétez votre nom et votre message.')
     c.execute('INSERT INTO messages(id,name,email,phone,subject,body,created) VALUES(?,?,?,?,?,?,?)',(secrets.token_hex(12),name,mail,clean(data.get('phone'),40),clean(data.get('subject'),160),body,now));return self.reply({'ok':True,'message':'Votre demande est enregistrée et consultable par le cabinet dans son administration.'})
    if path=='/api/newsletter':
     if not data.get('consent'):raise ValueError('Votre accord est nécessaire pour vous inscrire.')
     c.execute('INSERT INTO newsletter VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE SET name=excluded.name,interests=excluded.interests',(email(data.get('email')),clean(data.get('name'),160),json.dumps(data.get('interests',[])),now));return self.reply({'ok':True,'message':'Votre inscription est enregistrée. Vous pourrez demander sa suppression au cabinet.'})
    u=self.need(c);uid=u['id']
    if path.startswith('/api/security/'):
     result=account_action(c,path,data,u,password,email)
     if result is None:return self.reply({'error':'Action inconnue.'},404)
     return self.reply(result)
    if path=='/api/profile':
     name=clean(data.get('name'),160)
     if not name:raise ValueError('Indiquez votre nom.')
     c.execute('UPDATE users SET name=? WHERE id=?',(name,uid))
     if data.get('new_password'):
      old=clean(data.get('current_password'),256);new=clean(data['new_password'],256)
      if not hmac.compare_digest(password(old,u['password'].split(':')[0]),u['password']):raise ValueError('Mot de passe actuel incorrect.')
      if len(new)<10:raise ValueError('10 caractères minimum pour le nouveau mot de passe.')
      c.execute('UPDATE users SET password=? WHERE id=?',(password(new),uid));c.execute('DELETE FROM sessions WHERE user_id=?',(uid,));c.execute('DELETE FROM account_tokens WHERE user_id=?',(uid,))
     audit(c,u,'Profil modifié',uid)
     return self.reply({'ok':True})
    if path=='/api/notifications':c.execute('UPDATE notifications SET seen=1 WHERE user_id=?',(uid,));return self.reply({'ok':True})
    if path.startswith('/api/admin/'):
     c.execute('BEGIN IMMEDIATE')
     u=self.need(c,True)
     if u['role']=='editor' and path not in ('/api/admin/item','/api/admin/upload','/api/admin/archive'):raise PermissionError('Le rôle rédacteur est limité aux contenus.')
     self.audit_actor=u;self.audit_action=path;self.audit_target=clean(data.get('id') or data.get('item_id') or data.get('item',{}).get('title'),250)
     handled=admin_post(c,path,data,uid,now)
     if handled is not None:return self.reply(handled)
     if path=='/api/admin/item':
      p=data.get('item',{});itemid=clean(p.get('id'),120) or secrets.token_hex(10);title=clean(p.get('title'),250);kind=p.get('kind');status=p.get('status','draft')
      if kind not in ('formation','document','resource','article','event','live','trainer','plan','watch'):raise ValueError('Type de contenu invalide.')
      if not title:raise ValueError('Un titre est obligatoire.')
      if status not in ('draft','published','archived'):raise ValueError('Statut invalide.')
      p['price']=None if p.get('price') is None or p.get('price')=='' else int(p['price'])
      if p['price'] is not None and p['price']<0:raise ValueError('Prix invalide.')
      validate_content(p)
      p['modules']=p.get('modules',[])
      for i,m in enumerate(p['modules']):
       m['id']=m.get('id') or f'module-{i+1}'
       if m.get('video') and not str(m['video']).startswith('https://'):raise ValueError('La vidéo doit utiliser une adresse HTTPS.')
      c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,title=excluded.title,category=excluded.category,status=excluded.status,payload=excluded.payload,updated=excluded.updated',(itemid,kind,title,clean(p.get('category'),120),status,json.dumps(p,ensure_ascii=False),now))
      return self.reply({'ok':True,'id':itemid})
     if path=='/api/admin/upload':
      itemid=clean(data.get('item_id'),120)
      if not c.execute('SELECT 1 FROM items WHERE id=?',(itemid,)).fetchone():raise ValueError('Enregistrez le contenu avant de joindre un fichier.')
      name=Path(clean(data.get('name'),180)).name
      if Path(name).suffix.lower() not in ('.pdf','.docx','.xlsx','.pptx','.txt','.png','.jpg','.jpeg','.mp4'):raise ValueError('Format non pris en charge.')
      raw=base64.b64decode(data.get('content',''),validate=True)
      if len(raw)>10*1024*1024:raise ValueError('10 Mo maximum par fichier.')
      fid=secrets.token_hex(20);(DATA/'files'/fid).write_bytes(raw);c.execute('INSERT INTO uploads VALUES(?,?,?,?,?,?)',(fid,itemid,name,mimetypes.guess_type(name)[0] or 'application/octet-stream',len(raw),fid));return self.reply({'ok':True})
     if path=='/api/admin/message':c.execute('UPDATE messages SET status=? WHERE id=?',('processed',clean(data.get('id'),120)));return self.reply({'ok':True})
     if path=='/api/admin/newsletter-delete':c.execute('DELETE FROM newsletter WHERE email=?',(email(data.get('email')),));return self.reply({'ok':True})
    if path=='/api/order':
     rows=list(c.execute("SELECT items.*,cart.quantity FROM cart JOIN items ON items.id=cart.item_id WHERE cart.user_id=? AND items.status='published'",(uid,)))
     if not rows:raise ValueError('Votre panier est vide.')
     lines=[];total=0
     for r in rows:
      p=pack(r);price=p.get('price')
      if not p.get('purchasable') or p.get('demo') or not isinstance(price,int) or price<=0:raise ValueError('Un article ne peut pas être commandé.')
      lines.append({'id':r['id'],'title':r['title'],'price':price,'quantity':r['quantity']});total+=price*r['quantity']
     oid=secrets.token_hex(12);c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?)',(oid,uid,'pending_payment',total,json.dumps(lines,ensure_ascii=False),now));c.execute('DELETE FROM cart WHERE user_id=?',(uid,));return self.reply({'ok':True,'id':oid,'message':'Commande enregistrée en attente de paiement. Aucun débit ni accès payant accordé.'})
    itemid=clean(data.get('id'),120);r=c.execute("SELECT * FROM items WHERE id=? AND status='published'",(itemid,)).fetchone()
    if not r:raise ValueError('Contenu introuvable.')
    p=pack(r,True)
    if path=='/api/favorite':
     if data.get('remove'):c.execute('DELETE FROM favorites WHERE user_id=? AND item_id=?',(uid,itemid))
     else:c.execute('INSERT OR IGNORE INTO favorites VALUES(?,?)',(uid,itemid))
    elif path=='/api/certificate':
     modules=p.get('modules',[])
     if p['kind']!='formation' or p.get('demo') or not p.get('attestation') or not modules or not all(m.get('body') for m in modules):raise ValueError('Ce parcours ne permet pas la délivrance d’une attestation.')
     completed={x[0] for x in c.execute('SELECT module_id FROM progress WHERE user_id=? AND item_id=?',(uid,itemid))}
     if not all(m['id'] in completed for m in modules):raise ValueError('Validez tous les modules et leurs évaluations avant de demander votre attestation.')
     cid=secrets.token_hex(12);c.execute('INSERT OR IGNORE INTO certificates VALUES(?,?,?,?,?,?)',(cid,uid,itemid,p['title'],u['name'],now));cid=c.execute('SELECT id FROM certificates WHERE user_id=? AND item_id=?',(uid,itemid)).fetchone()[0]
     return self.reply({'ok':True,'id':cid})
    elif path=='/api/cart':
     if data.get('remove'):c.execute('DELETE FROM cart WHERE user_id=? AND item_id=?',(uid,itemid))
     else:
      if not p.get('purchasable') or p.get('demo') or not isinstance(p.get('price'),int) or p['price']<=0:raise ValueError('Cet article n’est pas encore disponible à l’achat.')
      q=max(1,min(10,int(data.get('quantity',1))));c.execute('INSERT INTO cart VALUES(?,?,?) ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=excluded.quantity',(uid,itemid,q))
    elif path=='/api/enroll':
     if p['kind']!='formation' or p.get('price')!=0 or not p.get('modules'):raise ValueError('L’inscription gratuite n’est pas disponible pour cette formation.')
     c.execute('INSERT OR IGNORE INTO enrollments VALUES(?,?,?)',(uid,itemid,now))
    elif path=='/api/progress':
     if not c.execute('SELECT 1 FROM enrollments WHERE user_id=? AND item_id=?',(uid,itemid)).fetchone():raise PermissionError('Inscrivez-vous à cette formation.')
     module=next((m for m in p.get('modules',[]) if m['id']==data.get('module')),None)
     if not module or not module.get('body'):raise ValueError('Ce module n’est pas encore disponible.')
     for n,q in enumerate(module.get('quiz',[])):
      if str(data.get('answers',{}).get(str(n)))!=str(q.get('correct')):raise ValueError('Une réponse est incorrecte. Relisez le module et réessayez.')
     c.execute('INSERT OR IGNORE INTO progress VALUES(?,?,?,?)',(uid,itemid,module['id'],now))
    elif path=='/api/event':
     if p['kind']!='event' or not p.get('date') or p.get('demo'):raise ValueError('Les inscriptions ouvriront après confirmation de l’événement.')
     if p.get('price',0)>0:raise ValueError('Le paiement doit être activé pour cet événement.')
     c.execute('BEGIN IMMEDIATE')
     count=c.execute('SELECT count(*) FROM event_registrations WHERE item_id=?',(itemid,)).fetchone()[0]
     if p.get('capacity') and count>=int(p['capacity']):raise ValueError('Cet événement est complet.')
     c.execute('INSERT OR IGNORE INTO event_registrations VALUES(?,?,?)',(uid,itemid,now))
     c.execute('INSERT INTO notifications VALUES(?,?,?,?,?,?)',(secrets.token_hex(12),uid,'Inscription confirmée : '+p['title'],'#/contenu/'+itemid,0,now))
    else:return self.reply({'error':'Action introuvable.'},404)
    return self.reply({'ok':True})
  except (ValueError,KeyError,TypeError) as e:self.reply({'error':str(e)},400)
  except PermissionError as e:self.reply({'error':str(e)},403)
  except Exception:self.reply({'error':'Impossible d’enregistrer. Réessayez.'},500)

if __name__=='__main__':
 initialize();print(f'LEX ASSOCIÉS : http://localhost:{PORT}',flush=True)
 ThreadingHTTPServer(('127.0.0.1',PORT),App).serve_forever()
