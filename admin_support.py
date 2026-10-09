"""Private administration, content placement and first-party aggregate statistics."""
import json, secrets, re, time
from pathlib import Path
try:
 from supabase_client import configured as supabase_configured, request as supabase_request
except Exception:
 supabase_configured=lambda: False
 supabase_request=lambda *a,**k: None

TAXONOMY=json.loads((Path(__file__).parent/'taxonomy.json').read_text(encoding='utf-8'))
SECTIONS=('formations','boutique','bibliotheque','blog','etudiants','professionnels','entreprises')
STATUSES=('pending_payment','processing','completed','cancelled')

def initialize_admin(c,data):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS visits(id TEXT PRIMARY KEY,visitor TEXT NOT NULL,session TEXT NOT NULL,page TEXT NOT NULL,event TEXT NOT NULL,target TEXT NOT NULL,seconds INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
 CREATE INDEX IF NOT EXISTS visits_date ON visits(created);
 CREATE TABLE IF NOT EXISTS order_updates(id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id),admin_id TEXT NOT NULL REFERENCES users(id),status TEXT NOT NULL,note TEXT NOT NULL,created REAL NOT NULL);
 ''')
 code=data/'admin-setup-code.txt'
 if not code.exists():code.write_text(secrets.token_urlsafe(24),encoding='utf-8')

def validate_content(p):
 placements=p.get('placements',[])
 if not isinstance(placements,list) or len(placements)>100:raise ValueError('Rubriques invalides.')
 for entry in placements:
  if not isinstance(entry,dict) or entry.get('section') not in SECTIONS or entry.get('category') not in TAXONOMY[entry['section']]:raise ValueError('Choisissez une rubrique existante pour chaque page.')
 modules=p.get('modules',[])
 if not isinstance(modules,list) or len(modules)>200:raise ValueError('Modules invalides.')
 ids=set()
 for m in modules:
  if not isinstance(m,dict) or not str(m.get('title','')).strip():raise ValueError('Chaque module doit avoir un titre.')
  if m.get('id') in ids:raise ValueError('Les modules doivent avoir des identifiants distincts.')
  if m.get('id'):ids.add(m['id'])
  for q in m.get('quiz',[]):
   if not q.get('question') or len(q.get('options',[]))<2 or any(not str(x).strip() for x in q['options']) or not isinstance(q.get('correct'),int) or not 0<=q['correct']<len(q['options']):raise ValueError('Complétez la question, les réponses et la bonne réponse du quiz.')

def admin_post(c,path,data,uid,now):
 if path=='/api/admin/archive':
  status='published' if data.get('restore') else 'archived'
  row=c.execute('SELECT * FROM items WHERE id=?',(str(data.get('id','')),)).fetchone()
  if not row:raise ValueError('Contenu introuvable.')
  if supabase_configured():
   from cloud_state import save_content
   save_content(row['id'],row['kind'],row['title'],row['category'],status,json.loads(row['payload']))
  changed=c.execute('UPDATE items SET status=?,updated=? WHERE id=?',(status,now,str(data.get('id','')))).rowcount
  if not changed:raise ValueError('Contenu introuvable.')
  return {'ok':True}
 if path=='/api/admin/order':
  oid=str(data.get('id',''));status=data.get('status');note=str(data.get('note','')).strip()[:3000]
  if status not in STATUSES:raise ValueError('Statut de commande invalide.')
  order=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
  if not order:raise ValueError('Commande introuvable.')
  c.execute('UPDATE orders SET status=? WHERE id=?',(status,oid))
  c.execute('INSERT INTO order_updates VALUES(?,?,?,?,?,?)',(secrets.token_hex(12),oid,uid,status,note,now))
  return {'ok':True}
 return None

def public_page(value):
 value=str(value or '')[:300].split('?')[0]
 if not re.fullmatch(r'/[a-z0-9/_%.-]*',value,re.I):return None
 if value=='/' or value.split('/')[1] in (*SECTIONS,'evenements','apropos','contact','contenu','domaine','live','veille','formateurs','abonnements','faq','newsletter','recherche'):return value
 return None

def track_visit(c,data,now,user,headers):
 if user and user['role'] in ('owner','admin','editor') or headers.get('DNT')=='1' or headers.get('Sec-GPC')=='1':return {'ok':True}
 if data.get('consent') is not True:return {'ok':True}
 visitor=str(data.get('visitor',''));session=str(data.get('session',''));event=data.get('event');page=public_page(data.get('page'));target=public_page(data.get('target')) if event=='click' else ''
 if not all(re.fullmatch('[a-f0-9-]{36}',v) for v in (visitor,session)) or not page or event not in ('view','click','engagement') or (event=='click' and not target):raise ValueError('Événement invalide.')
 if c.execute('SELECT count(*) FROM visits WHERE session=? AND created>?',(session,now-60)).fetchone()[0]>=60:return {'ok':True}
 seconds=max(0,min(120,int(data.get('seconds',0)))) if event=='engagement' else 0
 c.execute('INSERT INTO visits VALUES(?,?,?,?,?,?,?,?)',(secrets.token_hex(12),visitor,session,page,event,target,seconds,now))
 c.execute('DELETE FROM visits WHERE created<?',(now-90*86400,))
 return {'ok':True}

def admin_get(c,query):
 days=int(query.get('days',['30'])[0]);days=days if days in (7,30,90) else 30;since=time.time()-days*86400
 totals=dict(c.execute("SELECT count(DISTINCT visitor) visitors,count(DISTINCT session) sessions,count(*) views FROM visits WHERE event='view' AND created>=?",(since,)).fetchone())
 totals['seconds']=c.execute("SELECT coalesce(sum(seconds),0) FROM visits WHERE event='engagement' AND created>=?",(since,)).fetchone()[0]
 pages=[dict(r) for r in c.execute("SELECT page,count(*) views,count(DISTINCT visitor) visitors FROM visits WHERE event='view' AND created>=? GROUP BY page ORDER BY views DESC LIMIT 30",(since,))]
 clicks=[dict(r) for r in c.execute("SELECT page,target,count(*) clicks FROM visits WHERE event='click' AND created>=? GROUP BY page,target ORDER BY clicks DESC LIMIT 20",(since,))]
 daily=[dict(r) for r in c.execute("SELECT strftime('%Y-%m-%d',created,'unixepoch') day,count(*) views,count(DISTINCT visitor) visitors FROM visits WHERE event='view' AND created>=? GROUP BY day ORDER BY day",(since,))]
 orders=[]
 for row in c.execute('SELECT orders.*,users.name,users.email FROM orders JOIN users ON users.id=orders.user_id ORDER BY created DESC'):
  o=dict(row);o['lines']=json.loads(o['lines']);o['history']=[dict(r) for r in c.execute('SELECT status,note,created FROM order_updates WHERE order_id=? ORDER BY created DESC',(o['id'],))];orders.append(o)
 return {'days':days,'totals':totals,'pages':pages,'clicks':clicks,'daily':daily,'orders':orders}
