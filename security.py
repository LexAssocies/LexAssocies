"""Account administration. Tokens are stored only as hashes."""
import hashlib, hmac, json, secrets, sqlite3, time

STAFF=('owner','admin','editor')
def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def initialize_security(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS security_settings(key TEXT PRIMARY KEY,value TEXT);
 CREATE TABLE IF NOT EXISTS user_security(user_id TEXT PRIMARY KEY REFERENCES users(id),suspended INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS account_tokens(token TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),purpose TEXT NOT NULL,expires REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id TEXT,actor_name TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,created REAL NOT NULL);
 ''')
 if not c.execute("SELECT 1 FROM security_settings WHERE key='roles_v1'").fetchone():
  c.execute("UPDATE users SET role='owner' WHERE id=(SELECT id FROM users WHERE role='admin' ORDER BY created LIMIT 1)")
  c.execute("INSERT INTO security_settings VALUES('roles_v1','done')")

def suspended(c,uid):return bool(c.execute('SELECT 1 FROM user_security WHERE user_id=? AND suspended=1',(uid,)).fetchone())
def audit(c,u,action,target=''):
 c.execute('INSERT INTO audit(actor_id,actor_name,action,target,created) VALUES(?,?,?,?,?)',(u['id'],u['name'],action,str(target)[:300],time.time()))

def get_security(c,u):
 result={'sessions':c.execute('SELECT count(*) FROM sessions WHERE user_id=? AND expires>?',(u['id'],time.time())).fetchone()[0], 'recovery_remaining':c.execute("SELECT count(*) FROM account_tokens WHERE user_id=? AND purpose='recovery' AND expires>?",(u['id'],time.time())).fetchone()[0]}
 if u['role']=='owner':result['users']=[dict(r) for r in c.execute('SELECT users.id,name,email,role,created,coalesce(suspended,0) suspended FROM users LEFT JOIN user_security ON user_security.user_id=users.id ORDER BY created')]
 return result

def check_password(u,value,password):
 if not hmac.compare_digest(password(str(value or ''),u['password'].split(':')[0]),u['password']):raise ValueError('Mot de passe actuel incorrect.')

def account_action(c,path,data,u,password,email):
 if path not in ('/api/security/profile','/api/security/logout-all','/api/security/recovery-codes','/api/security/create-user','/api/security/user'):return None
 if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
 # Re-read role/status under the write lock to avoid a concurrent privilege change.
 u=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
 if suspended(c,u['id']):raise PermissionError('Ce compte est suspendu.')
 if path not in ('/api/security/create-user','/api/security/user'):check_password(u,data.get('current_password'),password)
 if path=='/api/security/profile':
  name=str(data.get('name','')).strip()[:160];mail=email(data.get('email'))
  if not name:raise ValueError('Indiquez votre nom.')
  new=str(data.get('new_password',''))
  if new and not 10<=len(new)<=256:raise ValueError('Le nouveau mot de passe doit comporter de 10 à 256 caractères.')
  try:c.execute('UPDATE users SET name=?,email=? WHERE id=?',(name,mail,u['id']))
  except sqlite3.IntegrityError:raise ValueError('Cette adresse e-mail est déjà utilisée.')
  if new:
   c.execute('UPDATE users SET password=? WHERE id=?',(password(new),u['id']))
   c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],))
   c.execute('DELETE FROM account_tokens WHERE user_id=?',(u['id'],))
  audit(c,u,'Profil et mot de passe modifiés' if new else 'Profil modifié',u['id'])
  return {'ok':True,'reconnect':bool(new)}
 if path=='/api/security/logout-all':
  c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],));audit(c,u,'Toutes les sessions déconnectées',u['id']);return {'ok':True,'reconnect':True}
 if path=='/api/security/recovery-codes':
  c.execute("DELETE FROM account_tokens WHERE user_id=? AND purpose='recovery'",(u['id'],));codes=[secrets.token_hex(12) for _ in range(8)]
  for code in codes:c.execute('INSERT INTO account_tokens VALUES(?,?,?,?)',(digest(code),u['id'],'recovery',time.time()+365*86400))
  audit(c,u,'Codes de récupération renouvelés',u['id']);return {'ok':True,'codes':codes}
 if u['role']!='owner':raise PermissionError('Seul un administrateur principal peut gérer les comptes.')
 if path=='/api/security/create-user':
  mail=email(data.get('email'));name=str(data.get('name','')).strip()[:160];role=data.get('role');pw=str(data.get('password',''))
  if not name or role not in STAFF:raise ValueError('Complétez le nom et le rôle.')
  if not 10<=len(pw)<=256:raise ValueError('Le mot de passe doit comporter de 10 à 256 caractères.')
  if c.execute('SELECT 1 FROM users WHERE email=?',(mail,)).fetchone():raise ValueError('Cette adresse e-mail est déjà utilisée.')
  uid=secrets.token_hex(12);c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(uid,name,mail,password(pw),role,time.time()))
  audit(c,u,'Compte créé : '+role,uid);return {'ok':True,'id':uid}
 target=c.execute('SELECT * FROM users WHERE id=?',(str(data.get('id','')),)).fetchone()
 if not target:raise ValueError('Compte introuvable.')
 if target['id']==u['id']:raise ValueError('Gérez votre propre compte depuis Mon profil.')
 role=data.get('role',target['role']);disabled=data.get('suspended',suspended(c,target['id']))
 if role not in (*STAFF,'member') or not isinstance(disabled,bool):raise ValueError('Rôle ou état invalide.')
 if target['role']=='owner' and (role!='owner' or disabled):
  count=c.execute("SELECT count(*) FROM users WHERE role='owner' AND id!=? AND NOT EXISTS(SELECT 1 FROM user_security WHERE user_id=users.id AND suspended=1) AND NOT EXISTS(SELECT 1 FROM account_tokens WHERE user_id=users.id AND purpose='invitation')",(target['id'],)).fetchone()[0]
  if count==0:raise ValueError('Conservez au moins un administrateur principal actif.')
 c.execute('UPDATE users SET role=? WHERE id=?',(role,target['id']))
 c.execute('INSERT INTO user_security VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET suspended=excluded.suspended',(target['id'],int(disabled)))
 c.execute('DELETE FROM sessions WHERE user_id=?',(target['id'],))
 c.execute('DELETE FROM account_tokens WHERE user_id=?',(target['id'],))
 audit(c,u,'Compte modifié : '+role+(' / suspendu' if disabled else ' / actif'),target['id'])
 return {'ok':True,'reconnect':target['id']==u['id']}

def recover(c,data,password,email):
 mail=email(data.get('email'));new=str(data.get('new_password',''));token=str(data.get('token','')).strip()
 if not 10<=len(new)<=256:raise ValueError('Choisissez un mot de passe de 10 à 256 caractères.')
 if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
 row=c.execute('SELECT account_tokens.*,users.email FROM account_tokens JOIN users ON users.id=account_tokens.user_id WHERE token=? AND email=? AND expires>?',(digest(token),mail,time.time())).fetchone()
 if not row or suspended(c,row['user_id']):raise ValueError('Code invalide, expiré ou compte indisponible.')
 uid=row['user_id'];u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
 c.execute('UPDATE users SET password=? WHERE id=?',(password(new),uid));c.execute('DELETE FROM account_tokens WHERE user_id=?',(uid,));c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
 audit(c,u,'Invitation acceptée' if row['purpose']=='invitation' else 'Mot de passe récupéré',uid)
 return {'ok':True}
