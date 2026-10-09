"""Transfère les contenus SQLite vers Supabase.
Exécution : SUPABASE_SECRET_KEY=... python scripts/migrate_contents.py
La clé secrète reste uniquement dans l'environnement local.
"""
import json, os, sqlite3, sys, uuid
from pathlib import Path
from urllib.request import Request, urlopen

root=Path(__file__).resolve().parents[1]
url=os.environ.get('SUPABASE_URL','').rstrip('/')
key=os.environ.get('SUPABASE_SECRET_KEY','')
if not url or not key:
 print('SUPABASE_URL et SUPABASE_SECRET_KEY sont requis.', file=sys.stderr); raise SystemExit(2)
db=sqlite3.connect(root/'data'/'lex.sqlite'); db.row_factory=sqlite3.Row
rows=[]
for r in db.execute("select id,kind,title,category,status,payload,updated from items"):
 payload=json.loads(r['payload']); payload['_local_id']=r['id']
 rows.append({'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'lex-associes:'+r['id'])),'kind':r['kind'],'title':r['title'],'category':r['category'] or '',
              'status':r['status'],'payload':payload})
if not rows:
 print('Aucun contenu local à transférer.'); raise SystemExit(0)
req=Request(url+'/rest/v1/contents?on_conflict=id',data=json.dumps(rows,ensure_ascii=False).encode(),method='POST',headers={
 'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json','Prefer':'resolution=merge-duplicates,return=minimal'})
with urlopen(req,timeout=30) as response: response.read()
print(f'{len(rows)} contenus transférés vers Supabase.')
