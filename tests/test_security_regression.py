import os,tempfile,sys,threading,json,urllib.request,urllib.error,http.cookiejar,base64
from pathlib import Path
os.environ['LEX_DATA_DIR']=tempfile.mkdtemp(prefix='lex-qa-')
os.environ['LEX_PORT']='4181'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
server.initialize()
srv=server.ThreadingHTTPServer(('127.0.0.1',4181),server.App)
threading.Thread(target=srv.serve_forever,daemon=True).start()
base='http://127.0.0.1:4181'
def client():return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
a,b,anon=client(),client(),client(); checks=0
def req(client,path,data=None,expected=200,origin=base):
 global checks
 body=json.dumps(data).encode() if data is not None else None
 r=urllib.request.Request(base+'/api/'+path,body,headers={'Content-Type':'application/json','Origin':origin})
 try:
  with client.open(r) as out:code=out.status;content=out.read();result=json.loads(content) if out.headers.get('Content-Type','').startswith('application/json') else content
 except urllib.error.HTTPError as e:code=e.code;result=json.loads(e.read())
 assert code==expected,(path,code,expected,result)
 checks+=1
 return result
try:
 assert req(anon,'bootstrap')['setup']
 req(anon,'account',expected=403)
 req(anon,'register',{'name':'X','email':'x@x.test','password':'password123'},403,origin='https://evil.example')
 req(anon,'register',{'name':'Public first','email':'public@example.test','password':'public-secret-123'})
 assert req(anon,'bootstrap')['user']['role']=='member'
 req(anon,'admin/overview',expected=403)
 req(a,'admin/setup',{'name':'Admin QA','email':'admin@example.test','password':'test-secret-123','setup_code':'wrong'},403)
 req(a,'admin/setup',{'name':'Admin QA','email':'admin@example.test','password':'test-secret-123','setup_code':(server.DATA/'admin-setup-code.txt').read_text().strip()})
 assert req(a,'bootstrap')['user']['role']=='owner'
 req(b,'register',{'name':'Member QA','email':'member@example.test','password':'test-secret-456'})
 assert req(b,'bootstrap')['user']['role']=='member'
 req(b,'admin',expected=403)
 req(b,'admin/item',{'item':{'title':'hack','kind':'article'}},403)
 req(anon,'progress',{'id':'decouvrir-plateforme','module':'premiers-pas'},403)
 before=req(b,'item/decouvrir-plateforme');assert not before['access'] and 'body' not in before['modules'][0]
 req(b,'enroll',{'id':'decouvrir-plateforme'})
 lesson=req(b,'item/decouvrir-plateforme');assert lesson['access'] and lesson['modules'][0]['body'] and 'correct' not in lesson['modules'][0]['quiz'][0]
 req(b,'progress',{'id':'decouvrir-plateforme','module':'premiers-pas','answers':{'0':1}},400)
 assert not req(b,'account')['progress']
 req(b,'progress',{'id':'decouvrir-plateforme','module':'premiers-pas','answers':{'0':0}})
 assert len(req(b,'account')['progress'])==1
 assert not req(a,'account')['progress']
 req(b,'favorite',{'id':'voies-execution-ohada'})
 assert 'voies-execution-ohada' in req(b,'account')['favorites']
 req(b,'cart',{'id':'mise-en-demeure'},400)
 p={'id':'paid-qa','title':'QA document','kind':'document','status':'published','price':1000,'purchasable':True}
 req(a,'admin/item',{'item':p})
 req(a,'admin/upload',{'item_id':'paid-qa','name':'test.txt','content':base64.b64encode(b'private-file').decode()})
 fid=req(a,'item/paid-qa')['files'][0]['id']
 req(anon,'file/'+fid,expected=403)
 req(b,'file/'+fid,expected=403)
 assert req(a,'file/'+fid)==b'private-file'
 req(b,'cart',{'id':'paid-qa','quantity':2})
 order=req(b,'order',{'total':1})
 orders=req(b,'account')['orders'];assert orders[0]['total']==2000 and orders[0]['status']=='pending_payment'
 req(b,'file/'+fid,expected=403)
 req(b,'order',{},400)
 req(anon,'contact',{'name':'QA','email':'contact@example.test','subject':'Test','message':'Message local'})
 req(anon,'newsletter',{'name':'QA','email':'newsletter@example.test','consent':True,'interests':['Formations']})
 admin=req(a,'admin');assert len(admin['messages'])==1 and len(admin['newsletter'])==1
 req(a,'admin/item',{'item':{'id':'draft-qa','title':'draft','kind':'article','status':'draft'}})
 req(anon,'item/draft-qa',expected=404)
 req(b,'certificate',{'id':'decouvrir-plateforme'},400)
 certcourse={'id':'cert-qa','title':'Parcours QA','kind':'formation','status':'published','price':0,'attestation':True,'modules':[{'id':'one','title':'Module','body':'Contenu test','quiz':[{'question':'Test','options':['A','B'],'correct':0}]}]}
 req(a,'admin/item',{'item':certcourse})
 req(b,'enroll',{'id':'cert-qa'})
 req(b,'certificate',{'id':'cert-qa'},400)
 req(b,'progress',{'id':'cert-qa','module':'one','answers':{'0':0}})
 cert=req(b,'certificate',{'id':'cert-qa'})
 assert req(b,'certificate/'+cert['id']).startswith(b'%PDF')
 req(a,'certificate/'+cert['id'],expected=404)
 req(a,'admin/item',{'item':{'id':'nullable-qa','title':'Tarif futur','kind':'formation','price':None,'status':'published'}})
 assert req(a,'item/nullable-qa')['price'] is None

 req(b,'admin/archive',{'id':'paid-qa'},403)
 req(b,'admin/order',{'id':order['id'],'status':'completed'},403)
 req(anon,'admin/overview',expected=403)
 for status in ['processing','completed','cancelled','pending_payment']:
  req(a,'admin/order',{'id':order['id'],'status':status,'note':'Note privée '+status})
  assert req(b,'account')['orders'][0]['status']==status
 details=req(a,'admin/overview')
 assert len(details['orders'][0]['history'])==4
 assert details['orders'][0]['lines'][0]['quantity']==2
 req(a,'admin/order',{'id':order['id'],'status':'paid'},400)
 req(b,'file/'+fid,expected=403)
 p['placements']=[{'section':'etudiants','category':'Cas pratiques'},{'section':'entreprises','category':'Contrats'}]
 req(a,'admin/item',{'item':p})
 assert len(req(anon,'item/paid-qa')['placements'])==2
 invalid={**p,'placements':[{'section':'etudiants','category':'Inconnue'}]}
 req(a,'admin/item',{'item':invalid},400)
 req(a,'admin/archive',{'id':'paid-qa'})
 req(anon,'item/paid-qa',expected=404)
 assert all(i['id']!='paid-qa' for i in req(anon,'bootstrap')['items'])
 req(a,'admin/archive',{'id':'paid-qa','restore':True})
 assert req(a,'item/paid-qa')['status']=='published'
 assert req(anon,'item/paid-qa')['status']=='published'
 req(a,'admin/item',{'item':p})
 assert req(anon,'item/paid-qa')['status']=='published'
 import uuid
 event={'visitor':str(uuid.uuid4()),'session':str(uuid.uuid4()),'page':'/formations','event':'view','consent':True}
 req(anon,'visit',{**event,'consent':False})
 req(a,'visit',event)
 assert req(a,'admin/overview')['totals']['views']==0
 req(anon,'visit',event)
 req(anon,'visit',{**event,'event':'click','target':'/boutique'})
 req(anon,'visit',{**event,'event':'engagement','seconds':25})
 req(anon,'visit',{**event,'page':'/administration'},400)
 stats=req(a,'admin/overview')
 assert stats['totals']=={'visitors':1,'sessions':1,'views':1,'seconds':25}
 assert stats['clicks'][0]['target']=='/boutique'
 assert stats['daily'][0]['views']==1
 req(b,'logout',{})
 req(b,'account',expected=403)
 req(b,'login',{'email':'member@example.test','password':'test-secret-456'})
 req(b,'security/create-user',{'name':'No','email':'no@example.test','role':'admin','password':'secret-test-123'},403)
 writer=client()
 new=req(a,'security/create-user',{'name':'Writer','email':'writer@example.test','role':'editor','password':'writer-secret-123'})
 req(writer,'login',{'email':'writer@example.test','password':'writer-secret-123'})
 req(writer,'admin/audit',expected=403)
 req(writer,'admin/item',{'item':{'id':'writer-test','title':'Article','kind':'article','status':'published'}})
 req(writer,'admin/archive',{'id':'writer-test'})
 req(a,'security/user',{'id':new['id'],'role':'editor','suspended':True})
 req(writer,'admin',expected=403)
 req(writer,'login',{'email':'writer@example.test','password':'writer-secret-123'},400)
 assert req(a,'admin/audit')['events']
 print(f'{checks} contrôles réussis : comptes, rôles, sessions, isolation, quiz, favoris, droits de téléchargement, commandes, demandes et newsletter.')
finally:srv.shutdown()
