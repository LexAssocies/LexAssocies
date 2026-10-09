"""Public metadata and crawlable first render; never includes private course modules."""
import json, re, html
from pathlib import Path
from urllib.parse import urlsplit, quote, unquote
from datetime import datetime, timezone

ROOT=Path(__file__).parent
PAGES={
 '/':('Formations juridiques et ressources OHADA','LEX ASSOCIÉS : formations juridiques, bibliothèque, documents pratiques et analyses du droit en Côte d’Ivoire et dans l’espace OHADA.'),
 '/formations':('Formations juridiques','Découvrez les formations juridiques LEX ASSOCIÉS : droit OHADA, contrats, procédures et pratique professionnelle pour étudiants, professionnels et entreprises.'),
 '/boutique':('Boutique juridique : modèles et documents','Explorez les contrats, actes juridiques, documents d’entreprise et guides pratiques proposés par LEX ASSOCIÉS.'),
 '/bibliotheque':('Bibliothèque juridique','Consultez la bibliothèque LEX ASSOCIÉS : textes juridiques, jurisprudence, ouvrages, fiches de cours et supports pédagogiques.'),
 '/blog':('Blog juridique et analyses du droit','Retrouvez les articles et analyses LEX ASSOCIÉS sur le droit OHADA, les contrats, les procédures, la fiscalité et la pratique juridique.'),
 '/etudiants':('Ressources juridiques pour étudiants','Fiches de cours, méthodologie, cas pratiques et préparation aux examens : découvrez l’espace étudiants de LEX ASSOCIÉS.'),
 '/professionnels':('Formations et ressources pour professionnels du droit','Explorez les formations et ressources destinées aux avocats, juristes, notaires, commissaires de justice et autres professionnels du droit.'),
 '/entreprises':('Formation et ressources juridiques pour entreprises','Formation des équipes, contrats, gouvernance et conformité : découvrez les ressources LEX ASSOCIÉS pour les entreprises.'),
 '/evenements':('Événements et webinaires juridiques','Découvrez les webinaires, conférences, masterclass et classes virtuelles proposés par LEX ASSOCIÉS.'),
 '/apropos':('À propos du cabinet','Découvrez LEX ASSOCIÉS, sa mission, ses valeurs et son expertise en formation, documentation et accompagnement juridique.'),
 '/contact':('Contacter LEX ASSOCIÉS','Contactez LEX ASSOCIÉS pour une formation, une ressource juridique, un projet d’accompagnement ou une demande de rendez-vous.'),
 '/live':('LEX ASSOCIÉS LIVE','Retrouvez les vidéos, conférences, interviews et échanges autour de la pratique du droit avec LEX ASSOCIÉS.'),
 '/veille':('Veille juridique','Découvrez les ressources de veille juridique proposées par LEX ASSOCIÉS pour suivre les évolutions du droit.'),
 '/formateurs':('Nos formateurs','Découvrez les formateurs et les domaines de formation présentés par LEX ASSOCIÉS.'),
 '/abonnements':('Abonnements et accès aux ressources','Découvrez les offres d’accès aux formations et ressources juridiques de LEX ASSOCIÉS.'),
 '/faq':('Questions fréquentes','Retrouvez les réponses aux questions sur les formations, les ressources et le fonctionnement de la plateforme LEX ASSOCIÉS.'),
 '/newsletter':('Newsletter juridique','Choisissez vos sujets et inscrivez-vous à la newsletter de LEX ASSOCIÉS pour suivre les formations et publications du cabinet.')}
PRIVATE={'administration','compte','connexion','inscription','recuperation','panier','paiement','recherche','juridique'}
KINDS={'formations':'formation','boutique':'document','bibliotheque':'resource','blog':'article','evenements':'event','live':'live','veille':'watch','formateurs':'trainer','abonnements':'plan'}
def config():return json.loads((ROOT/'seo-config.json').read_text(encoding='utf-8'))
def enabled(host):
 c=config();return c.get('indexing_enabled') is True and host==urlsplit(c['public_url']).netloc
def public_items(c):
 result=[]
 for r in c.execute("SELECT * FROM items WHERE status='published' ORDER BY updated DESC"):
  p=json.loads(r['payload']);p.update(id=r['id'],title=r['title'],kind=r['kind'],category=r['category'],updated=r['updated']);result.append(p)
 return result
def metadata(c,route,host):
 parsed=urlsplit(route);path=parsed.path.rstrip('/') or '/';base=config()['public_url'].rstrip('/');key=path.split('/')[1];status=200;item=None
 title,description=PAGES.get(path,('Espace privé','Espace personnel de la plateforme LEX ASSOCIÉS.'))
 indexable=path in PAGES and path not in ('/abonnements','/formateurs','/newsletter')
 if key=='contenu':
  item=next((i for i in public_items(c) if i['id']==unquote(path.split('/')[-1])),None)
  if item:title=item['title'];description=str(item.get('description') or title)[:180];indexable=not item.get('demo')
  else:status=404;title='Contenu introuvable';description='Ce contenu n’est pas disponible.'
 elif key=='domaine':
  title=unquote(path.split('/')[-1]);description='Formations et ressources LEX ASSOCIÉS : '+title;indexable=False
 elif path not in PAGES and key not in PRIVATE:status=404;title='Page introuvable';description='La page demandée n’existe pas.'
 canonical=base+path;robots='index, follow, max-image-preview:large' if enabled(host) and indexable and not parsed.query and status==200 else 'noindex, follow'
 if key in PRIVATE or status!=200:robots='noindex, nofollow'
 org={'@type':'Organization','@id':base+'/#organization','name':'LEX ASSOCIÉS','url':base+'/','logo':base+'/assets/logo-lex-associes.png'}
 graph=[org,{'@type':'WebSite','@id':base+'/#website','name':'LEX ASSOCIÉS','url':base+'/','inLanguage':'fr','publisher':{'@id':org['@id']}}, {'@type':'WebPage','@id':canonical+'#webpage','url':canonical,'name':title,'description':description,'inLanguage':'fr','isPartOf':{'@id':base+'/#website'}}]
 if path!='/':graph.append({'@type':'BreadcrumbList','itemListElement':[{'@type':'ListItem','position':1,'name':'Accueil','item':base+'/'},{'@type':'ListItem','position':2,'name':title,'item':canonical}]})
 if item and not item.get('demo') and item['kind']=='formation':graph.append({'@type':'Course','name':title,'description':description,'url':canonical,'provider':{'@id':org['@id']}})
 if item and not item.get('demo') and item['kind']=='article':graph.append({'@type':'Article','headline':title,'description':description,'url':canonical,'publisher':{'@id':org['@id']},'dateModified':datetime.fromtimestamp(item['updated'],timezone.utc).isoformat()})
 return {'title':title+' | LEX ASSOCIÉS','heading':title,'description':description,'canonical':canonical,'robots':robots,'image':base+'/assets/logo-lex-associes.png','status':status,'structured':{'@context':'https://schema.org','@graph':graph} if indexable and status==200 else None}
def tags(m):
 e=html.escape
 tags=[f'<title>{e(m["title"])}</title>',f'<meta name="description" content="{e(m["description"])}">',f'<meta name="robots" content="{m["robots"]}">',f'<link rel="canonical" href="{e(m["canonical"])}">']
 for key,value in {'og:type':'website','og:site_name':'LEX ASSOCIÉS','og:locale':'fr_CI','og:title':m['title'],'og:description':m['description'],'og:url':m['canonical'],'og:image':m['image'],'og:image:alt':'Logo LEX ASSOCIÉS'}.items():tags.append(f'<meta property="{key}" content="{e(value)}">')
 for key,value in {'twitter:card':'summary_large_image','twitter:title':m['title'],'twitter:description':m['description'],'twitter:image':m['image'],'twitter:image:alt':'Logo LEX ASSOCIÉS'}.items():tags.append(f'<meta name="{key}" content="{e(value)}">')
 if m['structured']:tags.append('<script type="application/ld+json" id="structured-data">'+json.dumps(m['structured'],ensure_ascii=False).replace('<','\\u003c')+'</script>')
 return '\n'.join(tags)
def document(c,route,host):
 m=metadata(c,route,host);e=html.escape;path=urlsplit(route).path.rstrip('/') or '/';key=path.split('/')[1]
 template=(ROOT/'dist/index.html').read_text(encoding='utf-8');template=re.sub(r'<title>.*?</title>','',template);template=re.sub(r'<meta name="description"[^>]*>','',template)
 template=template.replace('<!-- SEO_HEAD -->',tags(m))
 content=f'<section class="wrap section"><h1>{e(m["heading"])}</h1><p>{e(m["description"])}</p>'
 if key not in PRIVATE and m['status']==200:
  entries=public_items(c)
  if key=='contenu':
   item=next((i for i in entries if i['id']==unquote(path.split('/')[-1])),None)
   if item:
    content+=f'<p class="prose">{e(str(item.get("body") or ""))}</p>'
    if item.get('demo'):content+='<p>Aperçu : contenu de présentation à valider par le cabinet.</p>'
    for field,label in [('level','Niveau'),('duration','Durée'),('trainer','Formateur')]:
     if item.get(field):content+=f'<p>{label} : {e(str(item[field]))}</p>'
    if item.get('modules'):content+='<h2>Programme de la formation</h2><ul>'+''.join('<li>'+e(str(module.get('title','')) )+'</li>' for module in item['modules'])+'</ul>'
  else:
   if path!='/':entries=[i for i in entries if i['kind']==KINDS.get(key) or any(p.get('section')==key for p in i.get('placements',[]))]
   content+='<div class="grid">'+''.join(f'<article class="card"><div class="body"><h2><a href="/contenu/{quote(i["id"],safe="")}">{e(i["title"])}</a></h2><p>{e(str(i.get("description") or ""))}</p></div></article>' for i in entries)+'</div>'
  content+='<nav aria-label="Pages du site">'+''.join(f'<p><a href="{p}">{e(v[0])}</a></p>' for p,v in PAGES.items())+'</nav>'
 content+='</section>'
 return template.replace('<main id="main" tabindex="-1"></main>','<main id="main" tabindex="-1">'+content+'</main>'),m
def sitemap(c,host):
 urls=[]
 if enabled(host):
  base=config()['public_url'].rstrip('/')
  urls=[base+p for p in PAGES if 'noindex' not in metadata(c,p,host)['robots']]
  urls += [base+'/contenu/'+quote(i['id'],safe='') for i in public_items(c) if not i.get('demo')]
 return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+html.escape(u)+'</loc></url>' for u in urls)+'</urlset>'
def robots(host):
 if not enabled(host):return 'User-agent: *\nDisallow: /\n'
 return 'User-agent: *\nAllow: /\nSitemap: '+config()['public_url'].rstrip('/')+'/sitemap.xml\n'
