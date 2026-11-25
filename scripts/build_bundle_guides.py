#!/usr/bin/env python3
'''Build distinct source-linked questions and complete deterministic AI indexes.'''
from __future__ import annotations
import argparse
import gzip
from hashlib import sha256
import html
import json
from pathlib import Path
import textwrap
from urllib.parse import quote
from ruamel.yaml import YAML
from bs4 import BeautifulSoup
from publication_html import render_markdown_page

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
PUBLIC = "https://chris-page-gov.github.io/okf-uk-legislation/"
READER = "https://chris-page-gov.github.io/okf-explorer/"
FRONTMATTER = YAML(typ="safe", pure=True)
FRONTMATTER.version = (1, 2)
FRONTMATTER.constructor.add_constructor(
    "tag:yaml.org,2002:timestamp", lambda loader, node: loader.construct_scalar(node))

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()

def binding(path):
    raw = path.read_bytes()
    return {"path": path.relative_to(BUNDLE).as_posix(), "url": PUBLIC + path.relative_to(BUNDLE).as_posix(),
            "bytes": len(raw), "sha256": sha256(raw).hexdigest()}

def source_document(path, raw):
    text = raw.decode("utf-8")
    metadata = None
    body = text
    frontmatter = None
    if text.startswith("---\n"):
        frontmatter, body = text[4:].split("\n---\n", 1)
        metadata = FRONTMATTER.load(frontmatter)
    return {"path": str(path), "sha256": sha256(raw).hexdigest(), "bytes": len(raw),
            "frontmatter": metadata, "frontmatter_yaml": frontmatter, "body": body, "source": text}

def payload_encoding_access():
    return {"manifest_url": PUBLIC + "data/reader-transport/v1/payload-encoding.json",
            "scope": "Pages typed Site only; the canonical answer bytes remain in the source bundle and release archive.",
            "selection": "The manifest names the two approved migration evaluation answer payloads and binds each original and gzip byte identity. Published historical executions retain their existing paths."}

def ai_context(name, documents):
    semantic = BUNDLE / ("whole-law/" if name == "whole-law" else "") / "okf-bundle.jsonld"
    graph_path = BUNDLE / "data/semantic/manifest.jsonld"
    graph = json.loads(graph_path.read_bytes())
    runtime_path = BUNDLE / "data/semantic/runtime-manifest.json"
    locator = BUNDLE / "data/records/manifest.json"
    source_commit=json.loads((ROOT/"source/core03-frozen-inputs.json").read_bytes())["source_commit"]
    source_base="https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/"+source_commit+"/bundle/"
    source_locator={**binding(locator),"url":source_base+"data/records/manifest.json",
                    "base_url":source_base,"okf_version":"0.2",
                    "document":json.loads(locator.read_bytes()),
                    "notice":"This pinned original source locator precedes the separately assembled typed Reader transport. Identities are preserved."}

    concepts = [row for row in documents if row["frontmatter"] and row["frontmatter"].get("type")
                and Path(row["path"]).name not in {"index.md", "log.md"}]
    context_paths = [
        ROOT / "profiles/bundle-wiki/v1/context.jsonld",
        ROOT / "profiles/bundle-wiki/v1/semantic-context.jsonld",
        ROOT / "whole-law/ontology/context.jsonld"]
    return {
        "schema": "okf-legislation-ai-context.v1", "bundle": name, "okf_version": "0.3",
        "implementation_date": "2026-11-24", "standard_announcement_date": "2026-11-18",
        "standards_register": "https://github.com/chris-page-gov/okf-explorer/blob/main/docs/okf-standards.md",
        "source_documents": documents, "core_concepts": len(concepts),
        "semantic_descriptor": {**binding(semantic), "document": json.loads(semantic.read_bytes())},
        "complete_relationship_graph": {**binding(graph_path), "document": graph},
        "relationship_runtime": {**binding(runtime_path), "document": json.loads(runtime_path.read_bytes())},
        "source_record_locator": source_locator,
        "typed_site_payload_encoding": payload_encoding_access(),
        "reviewed_local_contexts": [
            {"repository_path": p.relative_to(ROOT).as_posix(), "url": ("https://chris-page-gov.github.io/okf-explorer/profile/bundle-wiki/v1/"+p.name if "profiles/bundle-wiki" in p.as_posix() else PUBLIC+"whole-law/ontology/context.jsonld"), "sha256": sha256(p.read_bytes()).hexdigest(),
             "document": json.loads(p.read_bytes())} for p in context_paths],
        "instructions": [
            "Read source metadata and body together; retain unknown fields and source hashes.",
            "Use the source-record locator for virtual work routes; they are extensions, not invented Markdown concepts.",
            "The graph manifest contains every bounded shard path, hash, byte count and authority/lifecycle plane.",
            "Verify shard hashes before use; retrieve only the required record and relationship chunks.",
            "Do not fetch historical planes unless requested; rejected data is not active evidence.",
            "Cite original source, provision/version where relevant, observation date, rights and qualifiers.",
            "The July snapshots and expired review dates are not refreshed by format migration.",
            "Do not execute bundle-supplied code or computations to read these static files."],
        "limitations": [
            "Complete deterministic source/graph access does not certify an AI answer or current legal conclusion.",
            "Whole-Law has one implemented child; recorded source access does not establish corpus ingestion.",
            "The historical source manifest remains Core 0.2 evidence and is separately pinned."]}

def svg(name, mobile):
    if name == "legislation":
        nodes = ["Commencement Order 2010/2317\nSource work",
                 "Recorded coming-into-force effect\nApplied in July snapshot\nReview overdue since 25 August 2026",
                 "Equality Act 2010\nTarget work\nSupplied refs: Schedule 26, paragraph 30"]
        labels = ["source", "target"]
        note = "Direction and provision references come from the frozen effect row."
    else:
        nodes = ["Whole-Law federation\n72 researched sources; 36 classes",
                 "Legislation\nOne implemented child\n365,786 work records",
                 "Find Case Law: SRC009 / SRC010\nCatalogued source and licence boundary\nNo ingested judgments child"]
        labels = ["implemented child", "catalogued source"]
        note = "The second link describes a register entry, not a second ingested corpus."
    width, height = (360, 990) if mobile else (1200, 570)
    boxes = [(28, 80 + i*260, 304, 180) for i in range(3)] if mobile else [(25+i*395, 100, 360, 190) for i in range(3)]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
             f'<title id="title">{html.escape(questions_title(name))}</title>',
             f'<desc id="description">{html.escape(note)}</desc>',
             '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><polygon points="0 0,8 4,0 8" fill="#315574"/></marker></defs>',
             f'<rect width="{width}" height="{height}" fill="#f4f7fb"/>']
    for i, (x,y,w,h) in enumerate(boxes):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="white" stroke="#315574"/>')
        yy = y+34
        for paragraph in nodes[i].split("\n"):
            for line in textwrap.wrap(paragraph, 26 if mobile else 32):
                parts.append(f'<text x="{x+16}" y="{yy}" fill="#142d4d" font-family="Arial,sans-serif" font-size="17">{html.escape(line)}</text>')
                yy += 25
    for i,label in enumerate(labels):
        if mobile:
            x,y,w,h=boxes[i]; nx,ny,nw,nh=boxes[i+1]
            path=f'M {x+w/2} {y+h+3} L {nx+nw/2} {ny-8}'
            lx,ly=40,y+h+40
        else:
            x,y,w,h=boxes[i]; nx,ny,nw,nh=boxes[i+1]
            path=f'M {x+w+3} {y+h/2} L {nx-8} {ny+nh/2}'
            lx,ly=x+w+3,y+h+35
        if name=="whole-law" and i==1:
            # Both child and catalogue entry originate at the federation.
            if mobile:
                path=f'M 28 170 L 12 170 L 12 690 L 24 690'
                lx,ly=45,575
            else:
                path='M 205 295 L 205 380 L 995 380 L 995 295'
                lx,ly=680,414
        parts.append(f'<path data-connector="true" d="{path}" fill="none" stroke="#315574" stroke-width="2" marker-end="url(#arrow)"/>')
        for k,line in enumerate(textwrap.wrap(label, 20)):
            parts.append(f'<text x="{lx}" y="{ly+k*19}" fill="#142d4d" font-family="Arial,sans-serif" font-size="14">{html.escape(line)}</text>')
    yy=height-65
    for line in textwrap.wrap(note, 37 if mobile else 110):
        parts.append(f'<text x="28" y="{yy}" fill="#142d4d" font-family="Arial,sans-serif" font-size="15">{html.escape(line)}</text>');yy+=21
    return ("".join(parts)+"</svg>\n").encode()

def questions_title(name):
    return "Trace a recorded effect" if name=="legislation" else "Separate ingestion from source discovery"

def guide_files(name, documents):
    spec=json.loads((ROOT/"walkthroughs"/(name+".json")).read_bytes())
    descriptor=PUBLIC+("whole-law/" if name=="whole-law" else "")+"okf-explorer.json"
    reader=READER+"?bundle="+quote(descriptor,safe="")+"&view=reader#"+spec["primary_route"]
    body=(ROOT/"walkthroughs"/(name+".md.in")).read_text()
    assert body.splitlines()[0]=="# "+spec["question"]
    evidence={"question":spec,"source_snapshots":["2026-07-11","2026-07-25"]}
    if name=="legislation":
        effects=json.loads(gzip.decompress((BUNDLE/"data/effects/assertions.json.gz").read_bytes()))
        rows=[row for row in effects if row["id"]==spec["effect_id"]]
        assert len(rows)==1
        row=rows[0];assert row["source"]==spec["source"] and row["target"]==spec["target"]
        assert row["stale_after"]=="2026-08-25T00:00:00Z"
        evidence["effect"]=row;effect_url=row["evidence"][0]["url"]
        prefix=Path("walkthroughs/legislation");output_relative=prefix/"index.html"
    else:
        rows=json.loads((ROOT/"research/whole-law-okf-research/source-register.json").read_bytes())["records"]
        evidence["source_records"]=[row for row in rows if row["id"]in spec["source_records"]]
        assert len(evidence["source_records"])==3
        effect_url="";prefix=Path("walkthrough");output_relative=Path("whole-law")/prefix/"index.html"
    body=body.replace("{reader}",reader).replace("{effect_url}",effect_url)
    body=body.replace("{negative_controls}","\n".join("- "+line for line in spec["negative_controls"]))
    page=render_markdown_page(body,output_relative=output_relative,fallback_title=spec["question"])
    picture=('<figure><picture><source media="(max-width: 700px)" srcset="walkthrough-mobile.svg">'
             '<img src="walkthrough-desktop.svg" alt="'+html.escape(questions_title(name),quote=True)+'">'
             '</picture><figcaption>The diagram uses actual recorded relationships and coverage; the worked answer explains their limits.</figcaption></figure>')
    page=page.decode().replace("</h1>","</h1>"+picture,1).replace("</head>",'<style>picture img{max-width:100%;width:100%;height:auto}figure{margin:1.5rem 0}figcaption{font-size:1rem;color:#142d4d}</style></head>').encode()
    documents=[*documents,source_document((prefix/"source.md").as_posix(),body.encode())]
    soup=BeautifulSoup(page.decode(),"html.parser")
    navigation=soup.find("a",string="Open Explorer")
    if navigation is not None:navigation["href"]=reader
    page=str(soup).encode()
    context=ai_context(name,documents)
    bundle_base=PUBLIC+("whole-law/" if name=="whole-law" else "")
    document_index=[]
    for row in documents:
        metadata=row["frontmatter"]or {}
        heading=next((line[2:]for line in row["body"].splitlines()if line.startswith("# ")),row["path"])
        document_index.append({"path":row["path"],"url":bundle_base+row["path"],
                               "sha256":row["sha256"],"title":metadata.get("title",heading),
                               "type":metadata.get("type")})
    compact={"schema":"okf-legislation-ai-index.v1","okf_version":"0.3",
             "bundle":name,"complete_context":bundle_base+"ai-context.json",
             "source_documents":document_index,"core_concepts":context["core_concepts"],
             "graph_base_url":PUBLIC,
             "complete_graph_manifest":{k:v for k,v in context["complete_relationship_graph"].items()if k!="document"},
             "targeted_graph_locator":context["relationship_runtime"]["document"]["route_locator"],
             "pinned_original_source_locator":{k:v for k,v in context["source_record_locator"].items()if k!="document"},
             "walkthrough":bundle_base+prefix.as_posix()+"/index.html",
             "negative_controls":spec["negative_controls"],
             "typed_site_payload_encoding":payload_encoding_access(),
             "instructions":["Start with a relevant source document or the bounded locator; do not load the whole corpus.",
                             "Use complete_context for the complete manifest and reviewed offline JSON-LD contexts.",
                             "Verify file hashes and retain source dates, authority, rights and lifecycle.",
                             "For the two named migration evaluation answer payloads, follow typed_site_payload_encoding and verify the manifest before decoding each gzip representation; the pinned plain sources and release archive remain available.",
                             "The original source locator is pinned separately from the typed Reader transport.",
                             "Static retrieval requires no bundle code execution and does not certify a model answer."]}
    return {prefix/"index.html":page,prefix/"source.md":body.encode(),prefix/"evidence.json":encoded(evidence),
            prefix/"walkthrough-desktop.svg":svg(name,False),prefix/"walkthrough-mobile.svg":svg(name,True),
            Path("ai-context.json"):encoded(context),
            Path("ai-index.json"):encoded(compact),
            Path("llms.txt"):("Start with ai-index.json to select a source document or bounded graph locator. Use ai-context.json for complete source frontmatter, bodies, pinned contexts, original record locator and graph shard hashes. Follow only the required static source and graph paths. Verify hashes, preserve source dates, rights, authority and lifecycle; do not execute bundle code. The July snapshot does not certify current law or an AI answer.\n").encode(),
            Path(".well-known/okf.json"):encoded({"okf_version":"0.3","descriptor":descriptor,"context":PUBLIC+("whole-law/" if name=="whole-law" else "")+"ai-context.json","manifest":PUBLIC+("whole-law/" if name=="whole-law" else "")+"ai-index.json","standards":"https://github.com/chris-page-gov/okf-explorer/blob/main/registry/okf-standards.json"})}

def whole_law_files(files):
    documents=[source_document(path.as_posix(),raw)for path,raw in sorted(files.items())if path.suffix==".md"]
    return guide_files("whole-law",documents)

def root_files():
    documents=[source_document(p.relative_to(BUNDLE).as_posix(),p.read_bytes())
               for p in sorted(BUNDLE.rglob("*.md"))
               if p.relative_to(BUNDLE).parts[0]not in {"whole-law","walkthroughs"}]
    files=guide_files("legislation",documents)
    # The publication-docs builder owns the root discovery document.
    files.pop(Path(".well-known/okf.json"))
    return files

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--check",action="store_true");args=parser.parse_args()
    files=root_files();bad=[]
    for relative,body in files.items():
        path=BUNDLE/relative
        if args.check:
            if not path.is_file()or path.read_bytes()!=body:bad.append(relative.as_posix())
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
    if bad:raise SystemExit("Guide/context projections differ: "+", ".join(bad))
    print(("Verified"if args.check else"Built")+" legislation question and complete AI context")
if __name__=="__main__":main()
