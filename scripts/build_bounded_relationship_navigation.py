#!/usr/bin/env python3
"""Offer bounded work-level alternatives when a broad graph exceeds Reader limits."""
from __future__ import annotations
import argparse,gzip,hashlib,html,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'bundle'
MAX_CHUNKS=64
MAX_ROWS=100000
MAX_COMPRESSED=64*1024*1024
MAX_EXAMPLES=12

NAVIGATION_JS = r'''export function explorerLink(page, route) {
  const parent = new URL(page);
  const local = ['127.0.0.1', 'localhost', '[::1]'].includes(parent.hostname);
  if (parent.username || parent.password || (parent.protocol !== 'https:' && !(local && parent.protocol === 'http:'))) throw new Error('Unsupported navigation origin');
  if (!/^dataset\/[A-Za-z0-9_./~-]+$/.test(route) || route.split('/').includes('..')) throw new Error('Unsupported work route');
  const descriptor = new URL('../okf-explorer.json', parent);
  const explorer = new URL(local ? '/explore/' : 'https://chris-page-gov.github.io/okf-explorer/explore/', parent);
  explorer.searchParams.set('bundle', descriptor.href);
  explorer.searchParams.set('view', 'graph');
  explorer.hash = route;
  return explorer.href;
}
if (typeof document !== 'undefined') {
  for (const link of document.querySelectorAll('a.work[data-route]')) {
    try { link.href = explorerLink(location.href, link.dataset.route); link.textContent = link.dataset.route; }
    catch { link.removeAttribute('href'); link.textContent += ' — navigation unavailable'; }
  }
}
'''

def digest(raw):return hashlib.sha256(raw).hexdigest()
def load_bound(ref):
    path=(BUNDLE/ref['path']).resolve()
    if not path.is_relative_to(BUNDLE.resolve()):raise ValueError('External material')
    raw=path.read_bytes()
    if (ref.get('bytes') is not None and len(raw)!=ref['bytes']) or digest(raw)!=ref['sha256']:raise ValueError('Material binding differs')
    return json.loads(gzip.decompress(raw) if ref.get('content_encoding')=='gzip' else raw)
def route_limit(row,active,chunks):
    selected=[p for p in row['planes'] if p['name'] in active]
    paths=set(p for plane in selected for p in plane['chunks'])
    counts={'chunks':len(paths),'assertions':sum(p['assertions'] for p in selected),'compressed_bytes':sum(chunks[p]['bytes'] for p in paths)}
    return counts, counts['chunks']>MAX_CHUNKS or counts['assertions']>MAX_ROWS or counts['compressed_bytes']>MAX_COMPRESSED

def build():
    manifest_raw=(BUNDLE/'data/semantic/runtime-manifest.json').read_bytes();m=json.loads(manifest_raw)
    active=set(m['default_planes']);chunks={c['path']:c for p in m['planes'] if p['name'] in active for c in p['chunks']}
    locator=load_bound(m['route_locator']);broad={};safe={}
    for ref in locator['buckets']:
        for row in load_bound(ref)['routes']:
            counts,over=route_limit(row,active,chunks)
            if over:broad[row['route']]={'route':row['route'],'counts':counts,'examples':{}}
            elif row['route'].startswith('dataset/'):safe[row['route']]=counts
    # Walk bound active evidence once. Each offered work has a recorded incident
    # assertion and is itself within the route-count and byte bounds.
    for ref in chunks.values():
        for row in load_bound(ref):
            for parent,child in [(row['source'],row['target']),(row['target'],row['source'])]:
                if parent not in broad or child not in safe:continue
                examples=broad[parent]['examples']
                examples.setdefault(child,{'route':child,'assertion_id':row['id'],'assertion_chunk':ref,'counts':safe[child]})
                if len(examples)>MAX_EXAMPLES:del examples[max(examples)]
    routes=[]
    for route,row in sorted(broad.items()):
        row['examples']=[v for _,v in sorted(row['examples'].items())]
        for example in row['examples']:
            example['descriptor_path']='okf-explorer.json'
            example['transport']='resolve-within-the-displayed-bundle'
        row['complete']=False
        routes.append(row)
    result={'schema':'okf-legislation-bounded-navigation.v1','runtime_manifest_sha256':digest(manifest_raw),
        'limits':{'route_chunks':MAX_CHUNKS,'route_rows':MAX_ROWS,'compressed_bytes':MAX_COMPRESSED,'examples':MAX_EXAMPLES},
        'routes':routes,'limitations':['Each route offers at most 12 lexicographically ordered work-level examples, not all related works.','Count and compressed-byte checks do not certify retained-text or browser performance limits.','Discovery relationships do not establish legal applicability.','For another work, use Explorer Search before opening its graph; broad route limits remain enforced.']}
    sections=[]
    for row in routes:
        links=''.join('<li><a class="work" data-route="'+html.escape(e['route'],quote=True)+'" href="../okf-explorer.json">Inspect matching descriptor: '+html.escape(e['route'])+'</a></li>' for e in row['examples'])
        sections.append('<section><h2>'+html.escape(row['route'])+'</h2><p>'+str(row['counts']['assertions'])+' incident assertions; '+str(row['counts']['chunks'])+' chunks. Open one narrower work:</p><ul>'+links+'</ul><p>Bounded examples only; this is not the full relationship set.</p></section>')
    page='<!doctype html><html lang="en-GB"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Bounded legislation graphs</title><style>body{max-width:65rem;margin:2rem auto;padding:1rem;font:1.1rem system-ui;line-height:1.5}a:focus{outline:3px solid #ffdd00}section{border-top:1px solid #aaa;margin-top:2rem}</style><main><h1>Bounded legislation graphs</h1><p>These broad routes exceed the Reader’s unchanged count or byte limits. Select a work below, or search for a specific legal work in Explorer. The examples are discovery aids, not an exhaustive list or legal advice.</p><p><a href="../data/bounded-relationship-navigation.json">Machine-readable counts and evidence bindings</a></p>'+''.join(sections)+'<noscript>JavaScript is disabled: work links open this bundle’s descriptor. They do not select a different public baseline.</noscript></main><script type="module" src="bounded-relationship-navigation.mjs"></script></html>\n'
    return {'bundle/data/bounded-relationship-navigation.json':json.dumps(result,indent=2,ensure_ascii=False)+'\n','bundle/docs/bounded-relationship-navigation.html':page,'bundle/docs/bounded-relationship-navigation.mjs':NAVIGATION_JS}
def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    for relative,text in build().items():
        path=ROOT/relative
        if a.check:
            if path.read_text()!=text:raise ValueError('Stale bounded navigation: '+relative)
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    print('PASS: bounded alternatives retain graph limits and source bindings')
if __name__=='__main__':main()
