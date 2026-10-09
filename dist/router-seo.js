/* Clean URLs with compatibility for bookmarks from the original hash router. */
function currentRoute(){return location.pathname+location.search;}
function cleanLegacyRoute(){if(location.hash.startsWith('#/')){const route=location.hash.slice(1);if(route.startsWith('/')&&!route.startsWith('//'))history.replaceState(null,'',route);}}
cleanLegacyRoute();
window.addEventListener('hashchange',cleanLegacyRoute);
window.addEventListener('popstate',()=>window.dispatchEvent(new Event('hashchange')));
document.addEventListener('click',e=>{
 const a=e.target.closest('a');if(!a||e.defaultPrevented||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||a.target||a.hasAttribute('download'))return;
 const url=new URL(a.href,location.href);if(url.origin!==location.origin||url.pathname.startsWith('/api/')||url.pathname.startsWith('/assets/')||url.hash&&!url.hash.startsWith('#/'))return;
 if(url.pathname.includes('.'))return;
 e.preventDefault();history.pushState(null,'',url.hash.startsWith('#/')?url.hash.slice(1):url.pathname+url.search);window.dispatchEvent(new Event('hashchange'));
});
function cleanLinks(root){root.querySelectorAll('a[href^="#/"]').forEach(a=>a.setAttribute('href',a.getAttribute('href').slice(1)));}
new MutationObserver(records=>{for(const r of records)for(const n of r.addedNodes)if(n.nodeType===1){if(n.matches('a[href^="#/"]'))n.setAttribute('href',n.getAttribute('href').slice(1));cleanLinks(n);}}).observe(document.documentElement,{childList:true,subtree:true});
let seoRequest=0;
async function updatePageSEO(){
 const id=++seoRequest,route=currentRoute();try{const r=await fetch('/api/seo?route='+encodeURIComponent(route));if(!r.ok)return;const m=await r.json();if(id!==seoRequest||route!==currentRoute())return;document.title=m.title;
 const meta=(key,value,attr='name')=>{let el=document.head.querySelector(`meta[${attr}="${key}"]`);if(!el){el=document.createElement('meta');el.setAttribute(attr,key);document.head.append(el);}el.content=value;};
 meta('description',m.description);meta('robots',m.robots);
 for(const [k,v] of Object.entries({'og:title':m.title,'og:description':m.description,'og:url':m.canonical,'og:image':m.image}))meta(k,v,'property');
 for(const [k,v] of Object.entries({'twitter:title':m.title,'twitter:description':m.description,'twitter:image':m.image}))meta(k,v);
 let canonical=document.querySelector('link[rel="canonical"]');if(!canonical){canonical=document.createElement('link');canonical.rel='canonical';document.head.append(canonical);}canonical.href=m.canonical;
 document.getElementById('structured-data')?.remove();if(m.structured){const el=document.createElement('script');el.id='structured-data';el.type='application/ld+json';el.textContent=JSON.stringify(m.structured);document.head.append(el);}
 }catch{}
}
