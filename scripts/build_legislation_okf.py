#!/usr/bin/env python3
"""Build a corpus-scale OKF/ELI catalogue of legislation.gov.uk.

The static pack enumerates every legislation item exposed by the public Atom
API. Document subdivisions remain authoritative at source and are resolved by
the Explorer from each record's CLML endpoint on demand.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import heapq
import io
import json
import math
import re
import sys
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import build_uk_government_api_okf as large_corpus

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "bundle"
DEFAULT_CACHE = ROOT / "tmp" / "legislation-okf-source"
USER_AGENT = "OKF-Legislation-Explorer/1.0 (public-interest research; chris-page-gov)"
ATOM = "http://www.w3.org/2005/Atom"
OPEN_SEARCH = "http://a9.com/-/spec/opensearch/1.1/"
LEG = "http://www.legislation.gov.uk/namespaces/legislation"
UKM = "http://www.legislation.gov.uk/namespaces/metadata"
NS = {"atom": ATOM, "open": OPEN_SEARCH, "leg": LEG, "ukm": UKM}
BASE = "https://www.legislation.gov.uk"
OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
DATA_DOCS = "https://legislation.github.io/data-documentation/"
URI_DOCS = f"{DATA_DOCS}model/uris.html"
MODEL_DOCS = f"{DATA_DOCS}model/legislation.html"
API_DOCS = f"{DATA_DOCS}api/overview.html"
SEARCH_DOCS = f"{DATA_DOCS}api/search.html"
FORMATS_DOCS = f"{DATA_DOCS}formats/overview.html"
LINKED_DOCS = f"{DATA_DOCS}api/linked-data.html"
PUBLICATION_DOCS = f"{DATA_DOCS}api/publication-log.html"
COVERAGE_DOCS = f"{DATA_DOCS}what-we-have.html"
LICENCE_DOCS = f"{DATA_DOCS}reuse-licence.html"
FAIR_USE_DOCS = f"{DATA_DOCS}fair-use.html"
CLML_DOCS = "https://legislation.github.io/clml-schema/userguide.html"
SCHEMA_ORG = "https://schema.org/Legislation"
ELI = "https://op.europa.eu/en/web/eu-vocabularies/eli"
ELI_I = "https://interoperable-europe.ec.europa.eu/collection/eli-european-legislation-identifier/solution/eli-i"
AKN = "https://docs.oasis-open.org/legaldocml/akn-core/v1.0/"
MODEL_ENRICHMENT_PATH = ROOT / "enrichment" / "model-assisted-v1.json"
MODEL_ENRICHMENT_AUDIT_PATH = (
    ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
)
MODEL_ENRICHMENT_AUDIT_MARKDOWN_PATH = (
    ROOT / "enrichment" / "model-assisted-v1-independent-audit.md"
)
MODEL_ENRICHMENT_PAID_GOVERNANCE_PATH = (
    ROOT / "enrichment" / "model-assisted-paid-governance-v1.json"
)
MODEL_ENRICHMENT_CALIBRATION_MANIFEST_PATH = (
    ROOT / "enrichment" / "model-assisted-calibration-manifest-v1.json"
)
SEARCH_RESULT_DOC_CHUNK_SIZE = 500
SEARCH_MAX_POSTINGS_PER_TOKEN = 10_000
MISSING_FILTER_VALUE = "__missing__"
SEARCH_FILTER_FIELDS = {
    "category": "category",
    "type_code": "type_code",
    "document_type": "document_type",
    "creation_year": "year",
    "jurisdiction": "jurisdiction",
    "legal_status": "legal_status",
    "publisher": "publisher",
    "topic": "topics",
    "format": "formats",
    "tag": "tags",
    "license": "license_id",
    "host": "host",
    "resource_type": "document_type",
    "update_year": "year",
}
SEARCH_WEIGHTS = {
    "title": 20,
    "citation": 14,
    "document_type": 8,
    "topic": 6,
    "jurisdiction": 4,
}
SEARCH_FIELD_MASKS = {
    "title": 1,
    "citation": 2,
    "document_type": 4,
    "topic": 8,
    "jurisdiction": 16,
}

PRIMARY_CODES = {
    "ukpga", "ukla", "ukppa", "gbla", "apgb", "gbppa", "aep", "aosp",
    "asp", "aip", "apni", "mnia", "nia", "ukcm", "mwa", "anaw", "asc",
}
SECONDARY_CODES = {"uksi", "ssi", "wsi", "nisr", "ukci", "nisi", "ukmo", "nisro", "uksro", "ukmd"}
DRAFT_CODES = {"ukdsi", "sdsi", "nidsr", "nidsi", "wdsi"}
EU_CODES = {"eur", "eudn", "eudr", "eut"}

TYPE_TITLES = {
    "UnitedKingdomPublicGeneralAct": "UK Public General Acts",
    "UnitedKingdomLocalAct": "UK Local Acts",
    "UnitedKingdomPrivateOrPersonalAct": "UK Private and Personal Acts",
    "GreatBritainLocalAct": "Local Acts of the Parliament of Great Britain",
    "GreatBritainAct": "Acts of the Parliament of Great Britain",
    "GreatBritainPrivateOrPersonalAct": "Private and Personal Acts of the Parliament of Great Britain",
    "EnglandAct": "Acts of the English Parliament",
    "ScottishOldAct": "Acts of the Old Scottish Parliament",
    "ScottishAct": "Acts of the Scottish Parliament",
    "IrelandAct": "Acts of the Old Irish Parliament",
    "NorthernIrelandParliamentAct": "Acts of the Parliament of Northern Ireland",
    "NorthernIrelandAssemblyMeasure": "Measures of the Northern Ireland Assembly",
    "NorthernIrelandAct": "Acts of the Northern Ireland Assembly",
    "UnitedKingdomChurchMeasure": "UK Church Measures",
    "WelshAssemblyMeasure": "Measures of the Welsh Assembly",
    "WelshNationalAssemblyAct": "Acts of the National Assembly for Wales",
    "WelshParliamentAct": "Acts of Senedd Cymru",
    "UnitedKingdomStatutoryInstrument": "UK Statutory Instruments",
    "ScottishStatutoryInstrument": "Scottish Statutory Instruments",
    "WelshStatutoryInstrument": "Welsh Statutory Instruments",
    "NorthernIrelandStatutoryRule": "Northern Ireland Statutory Rules",
    "UnitedKingdomChurchInstrument": "UK Church Instruments",
    "NorthernIrelandOrderInCouncil": "Northern Ireland Orders in Council",
    "UnitedKingdomMinisterialOrder": "UK Ministerial Orders",
    "NorthernIrelandStatutoryRuleOrOrder": "Northern Ireland Statutory Rules and Orders",
    "UnitedKingdomStatutoryRuleOrOrder": "UK Statutory Rules and Orders",
    "UnitedKingdomMinisterialDirection": "UK Ministerial Directions",
    "UnitedKingdomDraftStatutoryInstrument": "UK Draft Statutory Instruments",
    "ScottishDraftStatutoryInstrument": "Scottish Draft Statutory Instruments",
    "NorthernIrelandDraftStatutoryRule": "Northern Ireland Draft Statutory Rules",
    "NorthernIrelandDraftOrderInCouncil": "Northern Ireland Draft Orders in Council",
    "WelshDraftStatutoryInstrument": "Welsh Draft Statutory Instruments",
    "EuropeanUnionRegulation": "European Union Regulations",
    "EuropeanUnionDecision": "European Union Decisions",
    "EuropeanUnionDirective": "European Union Directives",
    "EuropeanUnionTreaty": "European Union Treaties",
}

TOPIC_RULES: list[tuple[str, str]] = [
    ("Constitutional and administrative law", r"\b(constitution|parliament|minister|government|public bod|devolution|referendum|crown|royal)\b"),
    ("Civil justice and procedure", r"\b(civil procedure|court|tribunal|judgment|appeal|limitation|evidence|damages|injunction)\b"),
    ("Criminal law and policing", r"\b(criminal|crime|offence|penalt|police|prison|prosecution|sentenc|terrorism|fraud)\b"),
    ("Employment and industrial relations", r"\b(employment|worker|labour|industrial relation|trade union|minimum wage|redundancy|pension)\b"),
    ("Taxation and customs", r"\b(tax|vat|customs|excise|duty|revenue|finance act|stamp duty|tariff)\b"),
    ("Companies, insolvency and financial services", r"\b(compan|insolvenc|bankrupt|financial service|banking|insurance|securities|credit)\b"),
    ("Land, housing and planning", r"\b(land|housing|rent|tenant|landlord|planning|building|property|leasehold|conveyancing)\b"),
    ("Environment, energy and agriculture", r"\b(environment|pollution|climate|energy|electricity|gas|agricultur|food|fisher|water|waste)\b"),
    ("Health and social care", r"\b(health|nhs|hospital|medicine|medical|social care|public health|mental health)\b"),
    ("Education and children", r"\b(education|school|student|university|college|child|adoption|nursery)\b"),
    ("Family and succession", r"\b(family|marriage|divorce|matrimonial|inheritance|succession|probate|domestic abuse)\b"),
    ("Immigration, nationality and asylum", r"\b(immigration|nationality|asylum|border|citizen|passport|deport)\b"),
    ("Social security and welfare", r"\b(social security|benefit|universal credit|welfare|allowance|income support)\b"),
    ("Transport and infrastructure", r"\b(transport|road|traffic|railway|rail|aviation|airport|shipping|harbour|vehicle|highway)\b"),
    ("Communications, data and technology", r"\b(data|digital|online|internet|telecom|communication|privacy|information|computer|cyber)\b"),
    ("Consumer and commercial law", r"\b(consumer|contract|sale of goods|commercial|competition|market|trading|product safety)\b"),
    ("Local government", r"\b(local government|local authorit|council|borough|county council|district council)\b"),
    ("Elections and political parties", r"\b(election|electoral|political part|constituenc|ballot|campaign)\b"),
    ("Defence and national security", r"\b(defence|armed forces|army|navy|air force|national security|official secrets)\b"),
    ("Human rights and equality", r"\b(human rights|equalit|discrimination|disability|freedom|rights act)\b"),
    ("Intellectual property and media", r"\b(copyright|patent|trade mark|intellectual property|broadcast|media)\b"),
    ("Professional regulation", r"\b(profession|solicitor|barrister|accountant|architect|regulator|licensing)\b"),
    ("European Union and retained EU law", r"\b(european union|eu |euratom|community regulation|retained eu|assimilated law)\b"),
]


def load_model_enrichment() -> dict[str, Any]:
    if not MODEL_ENRICHMENT_PATH.is_file():
        return {"rules": {"topic_keywords": [], "entity_suffixes": []}, "review_status": "absent"}
    return json.loads(MODEL_ENRICHMENT_PATH.read_text(encoding="utf-8"))


def load_model_enrichment_audit() -> dict[str, Any]:
    if not MODEL_ENRICHMENT_AUDIT_PATH.is_file():
        return {}
    return json.loads(MODEL_ENRICHMENT_AUDIT_PATH.read_text(encoding="utf-8"))


def model_enrichment_disposition(
    document: dict[str, Any],
    audit: dict[str, Any],
) -> tuple[bool, str]:
    """Return whether the legacy v1 rules may affect governed output.

    A self-labelled status in the rule file is never sufficient.  Application
    requires a hash-bound independent audit that explicitly accepts the rules
    and records passing precision and evidence-support gates.
    """

    if not MODEL_ENRICHMENT_PATH.is_file():
        return False, "absent"
    rule_sha256 = hashlib.sha256(MODEL_ENRICHMENT_PATH.read_bytes()).hexdigest()
    subject = audit.get("subject", {})
    decision = audit.get("decision", {})
    precision = audit.get("precision_assessment", {})
    evidence = audit.get("evidence_validity", {})
    if subject.get("sha256") != rule_sha256:
        return False, "rejected-unbound-independent-audit"
    verdict = str(decision.get("verdict", "rejected-independent-audit-missing"))
    accepted = (
        verdict == "accepted"
        and decision.get("release_gate_passed") is True
        and precision.get("passed") is True
        and evidence.get("passed") is True
    )
    return accepted, verdict


MODEL_ENRICHMENT_SOURCE = load_model_enrichment()
MODEL_ENRICHMENT_AUDIT = load_model_enrichment_audit()
MODEL_ENRICHMENT_APPLIED, MODEL_ENRICHMENT_DISPOSITION = (
    model_enrichment_disposition(
        MODEL_ENRICHMENT_SOURCE,
        MODEL_ENRICHMENT_AUDIT,
    )
)
MODEL_ENRICHMENT = (
    MODEL_ENRICHMENT_SOURCE
    if MODEL_ENRICHMENT_APPLIED
    else {
        "rules": {"topic_keywords": [], "entity_suffixes": []},
        "review_status": MODEL_ENRICHMENT_DISPOSITION,
    }
)


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "item"


def https_url(value: str) -> str:
    return re.sub(r"^http://", "https://", value.strip())


def text(node: ET.Element, path: str) -> str:
    found = node.find(path, NS)
    return re.sub(r"\s+", " ", found.text or "").strip() if found is not None else ""


def attr(node: ET.Element, path: str, name: str) -> str:
    found = node.find(path, NS)
    return found.get(name, "") if found is not None else ""


def category_for(code: str) -> str:
    if code in PRIMARY_CODES:
        return "primary"
    if code in SECONDARY_CODES:
        return "secondary"
    if code in DRAFT_CODES:
        return "draft"
    if code in EU_CODES:
        return "eu-origin"
    return "other"


def jurisdiction_for(code: str) -> list[str]:
    if code in {"asp", "aosp", "ssi", "sdsi"}:
        return ["Scotland"]
    if code in {"mwa", "anaw", "asc", "wsi", "wdsi"}:
        return ["Wales"]
    if code in {"apni", "mnia", "nia", "nisr", "nisro", "nisi", "nidsr", "nidsi"}:
        return ["Northern Ireland"]
    if code in EU_CODES:
        return ["European Union origin", "United Kingdom retained or assimilated context"]
    return ["United Kingdom"]


def topics_with_provenance(title: str, code: str) -> tuple[list[str], list[str]]:
    lowered = title.lower()
    topics = [label for label, pattern in TOPIC_RULES if re.search(pattern, lowered)]
    assisted: list[str] = []
    for rule in MODEL_ENRICHMENT.get("rules", {}).get("topic_keywords", []):
        topic = str(rule.get("topic", ""))
        keyword = str(rule.get("keyword", "")).lower().strip()
        if topic and keyword and keyword in lowered and topic not in topics:
            topics.append(topic)
            assisted.append(topic)
    if code in EU_CODES and "European Union and retained EU law" not in topics:
        topics.append("European Union and retained EU law")
    return topics or ["Unclassified — title-only heuristic"], assisted


def topics_for(title: str, code: str) -> list[str]:
    return topics_with_provenance(title, code)[0]


def entities_for(title: str) -> list[str]:
    suffixes = [re.escape(str(value)) for value in MODEL_ENRICHMENT.get("rules", {}).get("entity_suffixes", []) if value]
    if not suffixes:
        return []
    pattern = rf"\b((?:[A-Z][\w’'&.-]*\s+){{1,6}}(?:{'|'.join(suffixes)}))\b"
    return sorted({match.group(1).strip() for match in re.finditer(pattern, title)})


def semantic_enrichment_metadata(
    model_assisted_topics: list[str],
) -> dict[str, Any]:
    return {
        "method": (
            "deterministic-rules-with-governed-model-assistance"
            if MODEL_ENRICHMENT_APPLIED
            else "deterministic-title-rules"
        ),
        "model_assisted_topics": model_assisted_topics,
        "model_rule_set": "enrichment/model-assisted-v1.json",
        "model_rule_audit": (
            "enrichment/model-assisted-v1-independent-audit.json"
        ),
        "model_rules_applied": MODEL_ENRICHMENT_APPLIED,
        "review_status": MODEL_ENRICHMENT_DISPOSITION,
        "authority": "derived-non-official",
    }


class FeedClient:
    def __init__(self, cache: Path, refresh: bool, pause: float = 0.55):
        self.cache = cache
        self.refresh = refresh
        self.pause = pause
        self.last_request = 0.0
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def record_request(self, item: dict[str, Any]) -> None:
        with self.lock:
            self.requests.append(item)

    def pace_request(self) -> None:
        # A single start-rate limiter is shared by all workers. Requests may be
        # in flight concurrently, but starts remain well below the publisher's
        # documented fair-use ceiling.
        with self.lock:
            elapsed = time.monotonic() - self.last_request
            if elapsed < self.pause:
                time.sleep(self.pause - elapsed)
            self.last_request = time.monotonic()

    def get(self, url: str, name: str) -> bytes:
        path = self.cache / name
        if path.exists() and not self.refresh:
            body = path.read_bytes()
            self.record_request({"url": url, "cache": True, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
            return body
        path.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/xml;q=0.9"})
        error: Exception | None = None
        for attempt in range(6):
            try:
                self.pace_request()
                with urlopen(request, timeout=120) as response:
                    body = response.read()
                    status = response.status
                    content_type = response.headers.get_content_type()
                ET.fromstring(body)
                path.write_bytes(body)
                self.record_request({"url": url, "cache": False, "status": status, "content_type": content_type, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
                return body
            except (HTTPError, URLError, TimeoutError, ET.ParseError) as exc:
                error = exc
                if isinstance(exc, HTTPError) and exc.code in {301, 302, 307, 308}:
                    break
                time.sleep(2 ** attempt)
        raise RuntimeError(f"failed to fetch {url}: {error}")


def parse_facets(body: bytes) -> tuple[dict[str, int], dict[str, tuple[str, int]]]:
    root = ET.fromstring(body)
    years: dict[str, int] = {}
    types: dict[str, tuple[str, int]] = {}
    for row in root.findall(".//leg:facetYear", NS):
        year = row.get("year", "")
        if year:
            years[year] = int(row.get("total", "0"))
    for row in root.findall(".//leg:facetType", NS):
        main_type = row.get("type", "")
        href = row.get("href", "")
        if not main_type or "|" in main_type or not href:
            continue
        code = urlparse(href).path.strip("/").split("/")[0]
        types[code] = (main_type, int(row.get("value", "0")))
    return years, types


def representation_links(entry: ET.Element) -> dict[str, str]:
    formats: dict[str, str] = {}
    for link in entry.findall("atom:link", NS):
        href = https_url(link.get("href", ""))
        media = link.get("type", "")
        rel = link.get("rel", "")
        title = link.get("title", "")
        if not href:
            continue
        if rel == "http://purl.org/dc/terms/tableOfContents":
            formats["table_of_contents"] = href
        elif rel == "alternate" and media:
            key = {
                "application/xml": "clml",
                "application/akn+xml": "akoma_ntoso",
                "application/rdf+xml": "rdf_xml",
                "application/xhtml+xml": "xhtml",
                "application/akn+xhtml": "html5",
                "application/pdf": "pdf",
                "text/csv": "csv",
                "text/html": "website",
            }.get(media, slugify(title or media))
            formats[key] = href
        elif not rel:
            formats.setdefault("document", href)
    return formats


def parse_entry(entry: ET.Element) -> dict[str, Any]:
    id_uri = https_url(text(entry, "atom:id"))
    parts = urlparse(id_uri).path.strip("/").split("/")
    code = parts[1] if len(parts) > 1 and parts[0] == "id" else "unknown"
    year = attr(entry, "ukm:Year", "Value") or (parts[2] if len(parts) > 2 else "")
    number = attr(entry, "ukm:Number", "Value") or (parts[-1] if parts else "")
    main_type = attr(entry, "ukm:DocumentMainType", "Value") or "Legislation"
    title = text(entry, "atom:title") or id_uri
    representations = representation_links(entry)
    document_uri = representations.get("document") or id_uri.replace("/id/", "/")
    structure_url = representations.get("clml") or f"{document_uri.rstrip('/')}/data.xml"
    updated = text(entry, "atom:updated")
    updated_year = int(updated[:4]) if updated[:4].isdigit() else 0
    timestamp_anomaly = updated_year > datetime.now(timezone.utc).year + 1
    category = category_for(code)
    topics, model_assisted_topics = topics_with_provenance(title, code)
    semantic_entities = entities_for(title)
    formats = sorted(key for key in representations if key != "document")
    name = slugify(id_uri.replace("https://www.legislation.gov.uk/id/", ""))
    summary = text(entry, "atom:summary")
    creation_date = attr(entry, "ukm:CreationDate", "Date")
    published = text(entry, "atom:published")
    provenance = {
        "source": "legislation.gov.uk Atom API",
        "source_url": id_uri,
        "source_feed": f"{BASE}/{year}/data.feed",
        "source_adapter": "legislation_gov_uk_atom",
        "confidence": "authoritative-source",
        "retrieved_from_official_publisher": True,
        "timestamp_anomaly": timestamp_anomaly,
    }
    return {
        "id": id_uri,
        "name": name,
        "title": title,
        "notes": summary if summary != title else f"Official {TYPE_TITLES.get(main_type, main_type)} record for {year} number {number}.",
        "publisher": category,
        "publisher_title": category.replace("-", " ").title(),
        "publisher_concept_id": f"publishers/{category}",
        "resource_count": len(formats),
        "resource_ids": [],
        "formats": formats,
        "tags": [code, category, f"year-{year}"],
        "topics": topics,
        "semantic_entities": semantic_entities,
        "semantic_enrichment": semantic_enrichment_metadata(
            model_assisted_topics
        ),
        "timestamp": updated if not timestamp_anomaly else creation_date,
        "metadata_created": published or creation_date,
        "metadata_modified": updated,
        "license_id": "open-government-licence-v3",
        "license_title": "Open Government Licence v3.0 (additional terms may apply)",
        "license_source_id": OGL,
        "license_source_title": "The National Archives licensing guidance",
        "license_confidence": 0.9,
        "license_basis": "official-source-policy",
        "host": "legislation.gov.uk",
        "resource_hosts": ["legislation.gov.uk"],
        "source_api_url": structure_url,
        "concept_id": f"works/{name}",
        "route": f"dataset/{name}",
        "url": document_uri,
        "documentation": MODEL_DOCS,
        "state": "published" if category != "draft" else "draft",
        "type": "Legislation Work",
        "record_type": "Legislation Work",
        "source_tier": "official-publication-api",
        "source_adapter": "legislation_gov_uk_atom",
        "confidence": "authoritative-source",
        "dcat_type": "eli:LegalResource",
        "dcat_export_status": "mapped-not-exported",
        "openapi_type": "HTTP resource with content negotiation",
        "openapi_export_status": "documented-not-exported",
        "openapi_security_scheme": "none",
        "protocol": ["HTTP GET", "Atom", "CLML", "Akoma Ntoso"],
        "access_model": "anonymous",
        "visibility": "public",
        "contract_status": "official-legislation-api",
        "lifecycle_status": "draft" if category == "draft" else "published",
        "area_served": jurisdiction_for(code),
        "isopen": True,
        "private": False,
        "quality": {
            "overall": 0.9 if structure_url else 0.75,
            "metrics": {"identifier": 1.0, "title": 1.0, "type": 1.0, "dates": 1.0 if creation_date else 0.5, "structured_text_link": 1.0 if structure_url else 0.0},
            "notes": ["Quality measures metadata completeness, not legal currency or legal effect."],
        },
        "provenance": provenance,
        "legislation_id_uri": id_uri,
        "document_uri": document_uri,
        "structure_url": structure_url,
        "table_of_contents_url": representations.get("table_of_contents", ""),
        "document_type": main_type,
        "type_code": code,
        "category": category,
        "year": year,
        "number": number,
        "creation_date": creation_date,
        "published_at": published,
        "updated_at": updated,
        "jurisdiction": jurisdiction_for(code),
        "legal_status": "draft" if category == "draft" else "published; consult point-in-time and unapplied-effects metadata",
        "schema_org_type": "schema:Legislation",
        "eli_class": "eli:LegalResource",
        "manifestations": representations,
        "remote_full_text_search": f"{BASE}/all/data.feed?text={{query}}&results-count=20",
        "effects_made_url": f"{BASE}/changes/affecting/{code}/{year}/{number}/data.feed",
        "effects_received_url": f"{BASE}/changes/affected/{code}/{year}/{number}/data.feed",
        "extras": {
            "official_identifier": id_uri,
            "work_expression_manifestation_model": "ELI and legislation.gov.uk FRBR variant",
            "subdivision_model": "CLML structural IDs normalized by the Explorer on demand",
            "topic_assignment": "deterministic title-only heuristic; not an official legal classification",
            "source_timestamp_anomaly": timestamp_anomaly,
        },
    }


def parse_entries(body: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(body)
    return [parse_entry(entry) for entry in root.findall("atom:entry", NS)]


def load_live_records(client: FeedClient, include_drafts: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    discovery_url = f"{BASE}/all/data.feed?results-count=1"
    discovery = client.get(discovery_url, "discovery.xml")
    years, type_facets = parse_facets(discovery)
    records: dict[str, dict[str, Any]] = {}
    total_years = len(years)

    def fetch_year(year: str, expected: int) -> tuple[str, list[dict[str, Any]]]:
        url = f"{BASE}/{year}/data.feed?results-count=10000"
        try:
            rows = parse_entries(client.get(url, f"years/{year}.xml"))
        except RuntimeError:
            # Some large/temporarily unhealthy year routes redirect to the
            # canonical /all/{year} path and can fail at 10,000 rows. Retain
            # exact facet-count validation while falling back to smaller pages.
            rows = []
            for page in range(1, math.ceil(expected / 1000) + 1):
                page_url = f"{BASE}/all/{year}/data.feed?results-count=1000&page={page}"
                rows.extend(parse_entries(client.get(page_url, f"years/{year}-{page}.xml")))
        if len(rows) != expected:
            raise RuntimeError(f"{year}: expected {expected} Atom entries from facets, received {len(rows)}")
        return year, rows

    completed = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_year, year, expected): year for year, expected in years.items()}
        for future in as_completed(futures):
            year, rows = future.result()
            for row in rows:
                records[row["id"]] = row
            completed += 1
            print(f"harvested {completed}/{total_years} years ({year}: {len(rows):,}; {len(records):,} unique works)", flush=True)
    draft_rows: list[dict[str, Any]] = []
    if include_drafts:
        draft_url = f"{BASE}/draft/data.feed?results-count=10000"
        draft_rows = parse_entries(client.get(draft_url, "drafts.xml"))
        for row in draft_rows:
            records[row["id"]] = row
    meta = {
        "discovery_url": discovery_url,
        "year_counts": years,
        "type_facets": {code: {"document_type": value[0], "count": value[1]} for code, value in type_facets.items()},
        "draft_count": len(draft_rows),
        "requests": sorted(client.requests, key=lambda row: str(row.get("url", ""))),
    }
    return sorted(records.values(), key=lambda row: (row.get("year", ""), row.get("type_code", ""), row.get("number", ""), row["id"]), reverse=True), meta


def load_fixture(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    body = path.read_bytes()
    rows = parse_entries(body)
    return rows, {"fixture": path.as_posix(), "requests": [], "year_counts": dict(Counter(row["year"] for row in rows)), "type_facets": {}}


def facet_rows(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for record in records:
        value = record.get(key)
        values = value if isinstance(value, list) else [value]
        counts.update(str(item) for item in values if item not in (None, ""))
    return [{"value": value, "count": count} for value, count in counts.most_common()]


def build_facets(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "category": facet_rows(records, "category"),
        "type_code": facet_rows(records, "type_code"),
        "document_type": facet_rows(records, "document_type"),
        "creation_year": facet_rows(records, "year"),
        "jurisdiction": facet_rows(records, "jurisdiction"),
        "legal_status": facet_rows(records, "legal_status"),
        "publisher": facet_rows(records, "publisher"),
        "topic": facet_rows(records, "topics"),
        "format": facet_rows(records, "formats"),
        "tag": facet_rows(records, "tags"),
        "license": facet_rows(records, "license_id"),
        "host": facet_rows(records, "host"),
        "resource_type": facet_rows(records, "document_type"),
        "update_year": [{"value": row["value"], "count": row["count"]} for row in facet_rows(records, "year")],
    }


def build_publishers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(record["publisher"] for record in records)
    return [
        {
            "id": category,
            "name": category,
            "title": category.replace("-", " ").title(),
            "description": f"Normalized legislation.gov.uk category containing {count:,} indexed legal works.",
            "dataset_count": count,
            "resource_count": 0,
            "concept_id": f"publishers/{category}",
            "route": f"publisher/{category}",
            "state": "active",
            "type": "Legislation Category",
            "provenance": {"source": "legislation.gov.uk Atom facets", "source_url": f"{BASE}/{category}/data.feed"},
        }
        for category, count in counts.most_common()
    ]


def search_result_document(record: dict[str, Any], ordinal: int) -> dict[str, Any]:
    """Return the bounded record projection hydrated by the search worker.

    The complete work remains in the record shard.  This projection contains
    enough legal identity and manifestation metadata for a useful result/detail
    view without forcing a 1.7 GB full-corpus hydration.
    """

    return {
        "ordinal": ordinal,
        "name": record["name"],
        "title": record["title"],
        "publisher": record["publisher"],
        "publisher_title": record["publisher_title"],
        "resource_count": record["resource_count"],
        "formats": record.get("formats", []),
        "tags": record.get("tags", []),
        "topics": record.get("topics", []),
        "quality_score": record.get("quality", {}).get("overall"),
        "timestamp": record.get("timestamp", ""),
        "notes": large_corpus.truncate_text(record.get("notes", ""), 320),
        "access_model": record.get("access_model", ""),
        "contract_status": record.get("contract_status", ""),
        "license_id": record.get("license_id", ""),
        "license_title": record.get("license_title", ""),
        "license_source_id": record.get("license_source_id", ""),
        "license_source_title": record.get("license_source_title", ""),
        "license_confidence": record.get("license_confidence"),
        "license_basis": record.get("license_basis", ""),
        "record_type": record.get("record_type", ""),
        "source_tier": record.get("source_tier", ""),
        "source_adapter": record.get("source_adapter", ""),
        "confidence": record.get("confidence", ""),
        "protocol": record.get("protocol", []),
        "documentation": record.get("documentation", ""),
        "url": record.get("url", ""),
        "open": record["route"],
        "legislation_id_uri": record.get("legislation_id_uri", ""),
        "document_uri": record.get("document_uri", ""),
        "structure_url": record.get("structure_url", ""),
        "table_of_contents_url": record.get("table_of_contents_url", ""),
        "document_type": record.get("document_type", ""),
        "type_code": record.get("type_code", ""),
        "category": record.get("category", ""),
        "year": record.get("year", ""),
        "number": record.get("number", ""),
        "creation_date": record.get("creation_date", ""),
        "published_at": record.get("published_at", ""),
        "updated_at": record.get("updated_at", ""),
        "jurisdiction": record.get("jurisdiction", []),
        "legal_status": record.get("legal_status", ""),
        "schema_org_type": record.get("schema_org_type", ""),
        "eli_class": record.get("eli_class", ""),
        "effects_made_url": record.get("effects_made_url", ""),
        "effects_received_url": record.get("effects_received_url", ""),
    }


def search_filter_values(record: dict[str, Any], key: str) -> list[str]:
    source_key = SEARCH_FILTER_FIELDS[key]
    value = record.get(source_key)
    values = value if isinstance(value, list) else [value]
    return sorted({str(item) for item in values if item not in (None, "")})


def build_legislation_search(
    records: list[dict[str, Any]],
    snapshot: str,
) -> dict[str, Any]:
    """Build a bounded v2 static index with exact, separately loaded facets."""

    docs = [search_result_document(record, ordinal) for ordinal, record in enumerate(records)]
    posting_heaps: dict[str, list[tuple[int, int, int, int]]] = defaultdict(list)
    document_frequency: Counter[str] = Counter()
    for doc in docs:
        citation = " ".join(
            value
            for value in (
                str(doc.get("type_code", "")),
                str(doc.get("year", "")),
                str(doc.get("number", "")),
                f"{doc.get('type_code', '')}/{doc.get('year', '')}/{doc.get('number', '')}",
            )
            if value
        )
        document_type = " ".join(
            value
            for value in (
                str(doc.get("document_type", "")),
                TYPE_TITLES.get(str(doc.get("document_type", "")), ""),
                str(doc.get("category", "")),
            )
            if value
        )
        fields = {
            "title": str(doc["title"]),
            "citation": citation,
            "document_type": document_type,
            "topic": " ".join(str(value) for value in doc.get("topics", [])),
            "jurisdiction": " ".join(str(value) for value in doc.get("jurisdiction", [])),
        }
        token_scores: dict[str, list[int]] = {}
        for field, value in fields.items():
            for token in large_corpus.tokenize(value):
                score, mask = token_scores.get(token, [0, 0])
                token_scores[token] = [
                    score + SEARCH_WEIGHTS[field],
                    mask | SEARCH_FIELD_MASKS[field],
                ]
        for token, (score, mask) in token_scores.items():
            document_frequency[token] += 1
            heap = posting_heaps[token]
            item = (score, -int(doc["ordinal"]), int(doc["ordinal"]), mask)
            if len(heap) < SEARCH_MAX_POSTINGS_PER_TOKEN:
                heapq.heappush(heap, item)
            elif item[:2] > heap[0][:2]:
                heapq.heapreplace(heap, item)

    postings_by_path: dict[str, dict[str, list[list[int]]]] = defaultdict(dict)
    lexicon_rows: list[dict[str, Any]] = []
    for token, heap in sorted(posting_heaps.items()):
        path = f"data/search/postings/{large_corpus.search_shard(token)}.json.gz"
        ranked = sorted(heap, key=lambda item: (-item[0], item[2]))
        postings_by_path[path][token] = [
            [ordinal, score, mask]
            for score, _negative_ordinal, ordinal, mask in ranked
        ]
        lexicon_rows.append(
            {
                "token": token,
                "df": document_frequency[token],
                "postings": path,
            }
        )

    lexicon: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prefixes: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in lexicon_rows:
        token = row["token"]
        shard = large_corpus.search_shard(token)
        lexicon[shard].append(row)
        for length in range(3, min(8, len(token)) + 1):
            prefix = token[:length]
            prefixes[large_corpus.search_shard(prefix)][prefix].append(
                {"token": token, "df": row["df"]}
            )
    for payload in prefixes.values():
        for prefix, rows in payload.items():
            payload[prefix] = sorted(
                rows,
                key=lambda item: (-int(item["df"]), str(item["token"])),
            )[:16]

    filter_payloads: dict[str, dict[str, Any]] = {}
    filter_entrypoints: dict[str, str] = {}
    facets: dict[str, list[dict[str, Any]]] = {}
    for key in SEARCH_FILTER_FIELDS:
        values: dict[str, list[int]] = defaultdict(list)
        for ordinal, record in enumerate(records):
            record_values = search_filter_values(record, key)
            if not record_values:
                record_values = [MISSING_FILTER_VALUE]
            for value in record_values:
                values[value].append(ordinal)
        path = f"data/search/filters/{key}.json.gz"
        filter_entrypoints[key] = path
        filter_payloads[path] = {
            "schema": "okf-static-filter-postings.v1",
            "snapshot": snapshot,
            "key": key,
            "values": dict(sorted(values.items())),
        }
        facets[key] = [
            {"value": value, "count": len(ordinals)}
            for value, ordinals in sorted(
                values.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )
        ]

    result_doc_chunks = [
        (path.with_suffix(".json.gz"), rows)
        for path, rows in large_corpus.chunk_paths(
            "search/results",
            docs,
            SEARCH_RESULT_DOC_CHUNK_SIZE,
        )
    ]
    return {
        "manifest": {
            "schema": "okf-static-search.v2",
            "snapshot": snapshot,
            "token_min_length": 2,
            "prefix_min_length": 3,
            "lexicon_shard_length": 2,
            "result_limit": 200,
            "result_doc_chunk_size": SEARCH_RESULT_DOC_CHUNK_SIZE,
            "weights": SEARCH_WEIGHTS,
            "field_masks": SEARCH_FIELD_MASKS,
            "counts": {
                "documents": len(docs),
                "tokens": len(lexicon_rows),
                "postings": sum(
                    len(rows)
                    for payload in postings_by_path.values()
                    for rows in payload.values()
                ),
                "uncapped_postings": sum(document_frequency.values()),
                "max_postings_per_token": SEARCH_MAX_POSTINGS_PER_TOKEN,
            },
            "entrypoints": {
                "lexicon": {
                    shard: f"data/search/lexicon/{shard}.json.gz"
                    for shard in sorted(lexicon)
                },
                "prefixes": {
                    shard: f"data/search/prefixes/{shard}.json.gz"
                    for shard in sorted(prefixes)
                },
                "postings": sorted(postings_by_path),
                "result_docs": [
                    path.as_posix() for path, _rows in result_doc_chunks
                ],
                "facets": "data/facets.json",
                "doc_map": "data/search/doc-map.json.gz",
                "filter_postings": filter_entrypoints,
                "sort_values": "data/search/sort-values.json.gz",
            },
        },
        "lexicon": dict(sorted(lexicon.items())),
        "prefixes": {
            shard: dict(sorted(payload.items()))
            for shard, payload in sorted(prefixes.items())
        },
        "postings": {
            path: {"tokens": dict(sorted(payload.items()))}
            for path, payload in sorted(postings_by_path.items())
        },
        "result_doc_chunks": result_doc_chunks,
        "doc_map": {str(doc["ordinal"]): doc["open"] for doc in docs},
        "filter_payloads": filter_payloads,
        "facets": facets,
        "sort_values": [
            [
                str(
                    record.get("metadata_modified")
                    or record.get("timestamp")
                    or record.get("updated_at")
                    or record.get("creation_date")
                    or ""
                ),
                str(record.get("title") or ""),
                (
                    record.get("quality", {}).get("overall")
                    if isinstance(record.get("quality"), dict)
                    else record.get("quality_score")
                ),
            ]
            for record in records
        ],
    }


def build_record_locator(
    records: list[dict[str, Any]],
    record_chunks: list[tuple[Path, list[dict[str, Any]] | int]],
    snapshot: str,
) -> dict[str, Any]:
    """Build a 256-way route locator for one-shard record hydration."""

    buckets: dict[str, dict[str, list[int]]] = defaultdict(dict)
    chunk_lengths = [
        len(rows) if isinstance(rows, list) else int(rows)
        for _path, rows in record_chunks
    ]
    if any(length <= 0 for length in chunk_lengths):
        raise ValueError("record locator chunks must be non-empty")
    if sum(chunk_lengths) != len(records):
        raise ValueError("record locator chunks do not cover every record")
    chunk_size = max(chunk_lengths, default=1000)
    if chunk_lengths and any(
        length != chunk_size for length in chunk_lengths[:-1]
    ):
        raise ValueError(
            "record locator requires fixed-size chunks except for the final chunk"
        )
    if chunk_lengths and chunk_lengths[-1] > chunk_size:
        raise ValueError("record locator final chunk exceeds the fixed chunk size")
    for ordinal, record in enumerate(records):
        route = str(record["route"])
        bucket = large_corpus.relationship_bucket(route)
        if route in buckets[bucket]:
            raise ValueError(f"duplicate record route in locator: {route}")
        buckets[bucket][route] = [ordinal // chunk_size, ordinal % chunk_size]
    return {
        "manifest": {
            "schema": "okf-record-locator-sharded.v1",
            "snapshot": snapshot,
            "algorithm": "fnv1a32-prefix-2",
            "records": len(records),
            "chunk_size": chunk_size,
            "record_chunks": [
                path.as_posix() for path, _rows in record_chunks
            ],
            "buckets": {},
        },
        "buckets": dict(sorted(buckets.items())),
    }


def disambiguate_discovery_routes(
    records: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, str],
    list[dict[str, Any]],
]:
    """Give case-folded route collisions stable discovery-only aliases.

    The immutable work record retains its published route. Search and locator
    control planes use an alias for later colliding records and declare the
    alias-to-record-route mapping so the Explorer can verify hydration and
    canonicalize route-scoped relationship requests.
    """

    route_ordinals: dict[str, list[int]] = defaultdict(list)
    for ordinal, record in enumerate(records):
        route_ordinals[str(record["route"])].append(ordinal)
    discovery_records = list(records)
    aliases: dict[str, str] = {}
    collision_rows: list[dict[str, Any]] = []
    used_routes = set(route_ordinals)
    for route, ordinals in sorted(route_ordinals.items()):
        if len(ordinals) < 2:
            continue
        collision_aliases: list[str] = []
        identifiers = [
            str(
                records[ordinal].get("id")
                or records[ordinal].get("legislation_id_uri")
                or f"ordinal:{ordinal}"
            )
            for ordinal in ordinals
        ]
        for ordinal, identity in zip(ordinals[1:], identifiers[1:]):
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            length = 12
            alias = f"{route}--{digest[:length]}"
            while alias in used_routes:
                length += 4
                if length > len(digest):
                    raise ValueError(
                        f"could not create a unique route alias for {identity}"
                    )
                alias = f"{route}--{digest[:length]}"
            used_routes.add(alias)
            copied = dict(records[ordinal])
            copied["route"] = alias
            discovery_records[ordinal] = copied
            aliases[alias] = route
            collision_aliases.append(alias)
        collision_rows.append(
            {
                "route": route,
                "ordinals": ordinals,
                "identifiers": identifiers,
                "aliases": collision_aliases,
            }
        )
    return discovery_records, dict(sorted(aliases.items())), collision_rows


def explorer_presentation(snapshot: str) -> dict[str, Any]:
    return {
        "schema": "okf-explorer-presentation.v1",
        "status": "experimental",
        "snapshot": snapshot,
        "defaults": {
            "facet_mode": "suggested",
            "search_threshold": 30,
            "distribution_segment_limit": 8,
        },
        "panels": {
            "left": {
                "tabs": ["facets", "results", "browse"],
                "default_tab": "facets",
            },
            "right": {
                "tabs": ["overview", "evidence", "data"],
                "default_tab": "overview",
            },
        },
        "facets": [
            {
                "key": "category",
                "label": "Legislation category",
                "description": "Primary, secondary, draft or EU-origin work.",
                "value_type": "nominal",
                "order": 10,
                "default_state": "pinned",
                "open_control": "distribution",
                "value_order": "count-desc",
                "examples": ["primary", "secondary", "eu-origin"],
            },
            {
                "key": "jurisdiction",
                "label": "Jurisdiction",
                "description": "Territorial publication context inferred from the official type code.",
                "value_type": "nominal",
                "order": 20,
                "default_state": "pinned",
                "open_control": "distribution",
                "value_order": "count-desc",
                "examples": ["United Kingdom", "Scotland", "Wales"],
            },
            {
                "key": "creation_year",
                "label": "Creation year",
                "description": "Official legislation year, displayed as a temporal distribution.",
                "value_type": "date",
                "order": 30,
                "default_state": "shown",
                "open_control": "histogram",
                "value_order": "value-desc",
                "examples": ["2026", "2010", "1992"],
            },
            {
                "key": "document_type",
                "label": "Document type",
                "description": "Official legislation.gov.uk document main type.",
                "value_type": "nominal",
                "order": 40,
                "default_state": "shown",
                "open_control": "search",
                "value_order": "count-desc",
            },
            {
                "key": "topic",
                "label": "Discovery topic",
                "description": "Non-official, title-derived topic used only for discovery.",
                "value_type": "nominal",
                "order": 50,
                "default_state": "shown",
                "open_control": "distribution",
                "value_order": "count-desc",
            },
            {
                "key": "legal_status",
                "label": "Publication status",
                "description": "Draft or published; not a statement that every provision is in force.",
                "value_type": "nominal",
                "order": 60,
                "default_state": "shown",
                "open_control": "distribution",
                "value_order": "count-desc",
            },
            {
                "key": "type_code",
                "label": "Official type code",
                "description": "Compact legislation.gov.uk URI type code.",
                "value_type": "nominal",
                "order": 70,
                "default_state": "shown",
                "open_control": "search",
                "value_order": "count-desc",
            },
            {
                "key": "format",
                "label": "Available format",
                "description": "Official manifestation or data format advertised for the work.",
                "value_type": "nominal",
                "order": 80,
                "default_state": "shown",
                "open_control": "distribution",
                "value_order": "count-desc",
            },
            {
                "key": "publisher",
                "label": "Legacy category alias",
                "description": "Compatibility alias for legislation category.",
                "value_type": "nominal",
                "order": 90,
                "default_state": "hidden",
                "open_control": "distribution",
                "value_order": "count-desc",
            },
        ],
    }


def semantic_relationships(records: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    relationships: list[dict[str, Any]] = []
    for record in records:
        route = str(record["route"])
        assisted = set(record.get("semantic_enrichment", {}).get("model_assisted_topics", []))
        for topic in record.get("topics", []):
            relationships.append({
                "source": route,
                "target": f"topic/{slugify(str(topic))}",
                "kind": "classified as",
                "evidence_type": "model-assisted-title-rule" if topic in assisted else "deterministic-title-rule",
                "confidence": "medium" if topic in assisted else "low",
                "authority": "derived-non-official",
                "observed_at": generated_at,
            })
        relationships.append({
            "source": route,
            "target": f"legislation-type/{record['type_code']}",
            "kind": "has document type",
            "evidence_type": "official-atom-metadata",
            "confidence": "high",
            "authority": "official-source",
            "observed_at": generated_at,
        })
        for entity in record.get("semantic_entities", []):
            relationships.append({
                "source": route,
                "target": f"entity/{slugify(str(entity))}",
                "kind": "mentions entity",
                "label": str(entity),
                "evidence_type": "model-assisted-entity-pattern",
                "confidence": "medium",
                "authority": "derived-non-official",
                "observed_at": generated_at,
            })
    return relationships


def normalized_relationship_authority(row: dict[str, Any]) -> str:
    value = row.get("authority", "unclassified")
    if isinstance(value, dict):
        value = value.get("class", "unclassified")
    normalized = str(value).strip().lower().replace("_", "-")
    return {
        "official-source": "official",
        "derived-non-official": "derived",
    }.get(normalized, normalized or "unclassified")


def normalized_relationship_confidence(row: dict[str, Any]) -> str:
    value = row.get("confidence")
    if value in (None, ""):
        return "unknown"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return format(value, ".12g")
    return str(value).strip().lower() or "unknown"


def normalized_relationship_freshness(
    row: dict[str, Any],
    default: str = "unknown",
) -> str:
    value = str(row.get("freshness", "")).strip().lower()
    return value or default


def summarize_relationship_rows(
    rows: Any,
    datapack: str,
    *,
    default_freshness: str = "unknown",
) -> list[dict[str, Any]]:
    """Aggregate relationship rows without losing required authority signals."""

    counts: Counter[tuple[str, str, str, str, str]] = Counter()
    for row in rows:
        predicate = str(row.get("predicate") or row.get("kind") or "relationship")
        counts[
            (
                datapack,
                predicate,
                normalized_relationship_authority(row),
                normalized_relationship_confidence(row),
                normalized_relationship_freshness(
                    row,
                    default=default_freshness,
                ),
            )
        ] += 1
    return [
        {
            "datapack": pack,
            "predicate": predicate,
            "authority": authority,
            "confidence": confidence,
            "freshness": freshness,
            "count": count,
        }
        for (pack, predicate, authority, confidence, freshness), count in sorted(
            counts.items()
        )
    ]


def relationship_composition_document(
    rows: list[dict[str, Any]],
    snapshot: str,
    generated_at: str,
) -> dict[str, Any]:
    dimensions = {
        "by_datapack": Counter(),
        "by_predicate": Counter(),
        "by_authority": Counter(),
        "by_confidence": Counter(),
        "by_freshness": Counter(),
    }
    total = 0
    for row in rows:
        count = int(row.get("count", 0))
        total += count
        for key, field in (
            ("by_datapack", "datapack"),
            ("by_predicate", "predicate"),
            ("by_authority", "authority"),
            ("by_confidence", "confidence"),
            ("by_freshness", "freshness"),
        ):
            dimensions[key][str(row.get(field, "unknown"))] += count
    return {
        "schema": "okf-relationship-composition.v1",
        "snapshot": snapshot,
        "generated_at": generated_at,
        "total": total,
        **{
            key: dict(sorted(counter.items()))
            for key, counter in dimensions.items()
        },
        "breakdown": sorted(
            rows,
            key=lambda row: (
                str(row.get("datapack", "")),
                str(row.get("authority", "")),
                str(row.get("predicate", "")),
                str(row.get("confidence", "")),
                str(row.get("freshness", "")),
            ),
        ),
        "notice": (
            "Counts describe materialized rows in the declared core and provider "
            "datapacks. They do not imply complete legal coverage."
        ),
    }


def analysis_for(
    records: list[dict[str, Any]],
    facets: dict[str, list[dict[str, Any]]],
    generated_at: str,
    *,
    core_relationship_count: int,
    combined_relationship_count: int | None = None,
    relationship_rows: list[dict[str, Any]] | None = None,
    snapshot: str = "",
) -> dict[str, Any]:
    counts = Counter(record["category"] for record in records)
    type_counts = Counter(record["document_type"] for record in records)
    category_types = Counter(
        (str(record["category"]), str(record["document_type"]))
        for record in records
    )
    decade_counts: Counter[str] = Counter()
    for record in records:
        year = int(record["year"]) if str(record["year"]).isdigit() else 0
        if year:
            decade_counts[f"{(year // 10) * 10}s"] += 1
    combined_relationship_count = (
        core_relationship_count
        if combined_relationship_count is None
        else combined_relationship_count
    )
    relationship_rows = relationship_rows or []
    relationship_by_authority: Counter[str] = Counter()
    relationship_by_datapack: Counter[str] = Counter()
    relationship_by_predicate: Counter[str] = Counter()
    relationship_by_confidence: Counter[str] = Counter()
    relationship_by_freshness: Counter[str] = Counter()
    for row in relationship_rows:
        count = int(row.get("count", 0))
        relationship_by_authority[str(row.get("authority", "unclassified"))] += count
        relationship_by_datapack[str(row.get("datapack", "core"))] += count
        relationship_by_predicate[str(row.get("predicate", "relationship"))] += count
        relationship_by_confidence[str(row.get("confidence", "unknown"))] += count
        relationship_by_freshness[str(row.get("freshness", "unknown"))] += count

    facet_analysis = []
    for key, rows in facets.items():
        total_assignments = sum(int(row["count"]) for row in rows)
        probabilities = [
            int(row["count"]) / total_assignments
            for row in rows
            if total_assignments and int(row["count"]) > 0
        ]
        entropy = (
            -sum(value * math.log2(value) for value in probabilities)
            / math.log2(len(probabilities))
            if len(probabilities) > 1
            else 0
        )
        present = sum(
            1
            for record in records
            if search_filter_values(record, key)
        ) if key in SEARCH_FILTER_FIELDS else len(records)
        cardinality = len(rows)
        if key in {"creation_year", "update_year"}:
            control = "histogram"
            value_type = "date"
        elif cardinality <= 12:
            control = "distribution"
            value_type = "nominal"
        elif cardinality <= 30:
            control = "list with distribution"
            value_type = "nominal"
        else:
            control = "search"
            value_type = "nominal"
        recommendation = (
            "primary"
            if key in {"category", "document_type", "creation_year", "jurisdiction", "topic"}
            else "secondary"
            if key in SEARCH_FILTER_FIELDS
            else "advanced"
        )
        facet_analysis.append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "description": {
                    "topic": "Non-official title-derived discovery classification.",
                    "legal_status": "Publication state, not provision-level in-force status.",
                    "jurisdiction": "Territorial publication context inferred from the official type code.",
                }.get(key, "Generated whole-corpus distribution."),
                "coverage": round(present / len(records), 6) if records else 0,
                "cardinality": cardinality,
                "top_share": (
                    round(int(rows[0]["count"]) / len(records), 6)
                    if rows and records
                    else 0
                ),
                "entropy": round(entropy, 6),
                "expected_reduction": (
                    round(1 - (int(rows[0]["count"]) / len(records)), 6)
                    if rows and records
                    else 0
                ),
                "recommended_control": control,
                "recommendation": recommendation,
                "value_type": value_type,
                "value_order": (
                    "value-desc"
                    if value_type == "date"
                    else "count-desc"
                ),
                "values": rows[:18],
            }
        )

    graph_nodes = [{"id": f"facet/category/{key}", "label": key.replace("-", " ").title(), "type": "category", "count": value, "route": f"facet/category/{key}"} for key, value in counts.most_common()]
    graph_nodes.extend({"id": f"facet/document_type/{slugify(key)}", "label": TYPE_TITLES.get(key, key), "type": "document type", "count": value, "route": f"facet/document_type/{key}"} for key, value in type_counts.most_common(20))
    return {
        "schema": "okf-explorer-analysis.v1",
        "generated_at": generated_at,
        **({"snapshot": snapshot} if snapshot else {}),
        "source_bundle": "okf-explorer.json",
        "summary": {
            "title": "The legislation.gov.uk corpus",
            "description": "Every work returned by the official public legislation and draft Atom feeds, normalized to ELI/Schema.org and linked to live provision-level CLML.",
            "record_count": len(records),
            "resource_count": sum(record["resource_count"] for record in records),
            "relationship_count": combined_relationship_count,
            "core_relationship_count": core_relationship_count,
            "external_datapack_relationship_count": (
                combined_relationship_count - core_relationship_count
            ),
            "relationship_breakdown": {
                "by_authority": dict(relationship_by_authority.most_common()),
                "by_datapack": dict(relationship_by_datapack.most_common()),
                "by_confidence": dict(relationship_by_confidence.most_common()),
                "by_freshness": dict(relationship_by_freshness.most_common()),
            },
            "notices": [
                "Titles, identifiers, dates, types and manifestation links come from the official Atom API.",
                "Topic tags are deterministic title-only aids and are not official legal classifications.",
                "Relationship totals distinguish materialized core rows from official-effects and model-assisted datapacks.",
                "Provision trees and passage text are resolved from official CLML only when a work is opened.",
                "The public SPARQL and bulk-download pages are documented but currently return HTTP 401 to anonymous clients; Atom and per-document APIs remain the build source.",
            ],
        },
        "graph_overview": {"nodes": graph_nodes, "edges": [{"source": f"facet/category/{category}", "target": f"facet/document_type/{slugify(kind)}", "label": "contains", "count": count} for kind, count in type_counts.most_common() for category in [next((record["category"] for record in records if record["document_type"] == kind), "other")]]},
        "timeline_overview": {"buckets": [{"id": decade, "label": decade, "count": count, "route": f"facet/creation_year/{decade[:-1]}"} for decade, count in sorted(decade_counts.items(), reverse=True)]},
        "relationship_overview": {
            "total": combined_relationship_count,
            "core_total": core_relationship_count,
            "external_datapack_total": (
                combined_relationship_count - core_relationship_count
            ),
            "types": [
                {"kind": predicate, "count": count}
                for predicate, count in relationship_by_predicate.most_common(18)
            ] or [
                {"kind": "core semantic relationships", "count": core_relationship_count}
            ],
            "by_authority": dict(relationship_by_authority.most_common()),
            "by_datapack": dict(relationship_by_datapack.most_common()),
            "by_confidence": dict(relationship_by_confidence.most_common()),
            "by_freshness": dict(relationship_by_freshness.most_common()),
            "composition": "data/relationship-composition.json",
            "top_connected": [],
        },
        "resource_overview": {"total_resources": sum(record["resource_count"] for record in records), "high_resource_datasets": [], "distributions": {"format": facets["format"][:20]}},
        "facet_analysis": facet_analysis,
        "hierarchies": [{"id": "legal-corpus", "label": "Category → document type", "facet": "document_type", "levels": ["category", "document_type"], "values": [{"id": category, "label": category.replace("-", " ").title(), "count": count, "route": f"facet/category/{category}", "children": [{"id": kind, "label": TYPE_TITLES.get(kind, kind), "count": type_count, "route": f"facet/document_type/{kind}"} for (row_category, kind), type_count in category_types.most_common() if row_category == category]} for category, count in counts.most_common()]}],
        "ontology_candidates": [
            {"id": "eli-1.5", "label": "European Legislation Identifier ontology 1.5", "confidence": 0.96, "coverage": 1.0, "classes": ["eli:LegalResource", "eli:LegalExpression", "eli:Format", "eli:LegalResourceSubdivision"], "properties": ["eli:is_realized_by", "eli:is_embodied_by", "eli:has_part", "eli:changes"], "notes": ["Primary normalization ontology."]},
            {"id": "schema-org-legislation", "label": "Schema.org Legislation", "confidence": 0.92, "coverage": 1.0, "classes": ["schema:Legislation", "schema:LegislationObject"], "properties": ["schema:legislationIdentifier", "schema:legislationType", "schema:legislationDateVersion", "schema:legislationChanges"], "notes": ["Web-facing alignment; official ELI-to-Schema.org mapping available."]},
            {"id": "clml-2.6", "label": "Crown Legislation Markup Language 2.6", "confidence": 1.0, "coverage": 1.0, "classes": ["Part", "Chapter", "P1-P7", "Schedule", "Appendix", "Attachment"], "properties": ["id", "IdURI", "DocumentURI", "RestrictExtent", "Status"], "notes": ["Authoritative UK document structure and passage source."]},
        ],
        "narrative": {"title": "Progressive legal discovery", "body": "Begin with category, type, year, jurisdiction or topic; open a legal work; then load its authoritative CLML tree to traverse Parts, Chapters, Schedules, sections, articles, regulations and nested provisions. Every passage retains an official identifier or document link."},
    }


def markdown_frontmatter(
    type_name: str,
    title: str,
    description: str,
    resource: str,
    generated_at: str,
    tags: list[str],
    sources: list[dict[str, str]] | None = None,
) -> str:
    values = {
        "type": type_name,
        "title": title,
        "description": description,
        "resource": resource,
        "tags": tags,
        "generated": {"by": "process:legislation-okf-builder", "at": generated_at},
        # The publication descriptor remains preview; no review is implied.
        "status": "draft",
        "sources": sources or ([{"id": "official-source", "resource": resource}] if resource else []),
    }
    return "---\n" + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in values.items()) + "\n---\n"


def concept(type_name: str, title: str, description: str, resource: str, generated_at: str, tags: list[str], body: str) -> str:
    sources: list[dict[str, str]] = []
    if resource:
        sources.append({"id": "official-source", "resource": resource})
    for identifier, label, url in re.findall(r"(?m)^\[(\d+)\]\s+\[([^\]]+)\]\(([^)]+)\)\s*$", body):
        if any(source["resource"] == url for source in sources):
            continue
        sources.append({"id": f"reference-{identifier}", "resource": url, "title": label})
    normalized_body = re.sub(r"(?m)^# Citations\s*$", "# Source notes", body)
    return (
        markdown_frontmatter(type_name, title, description, resource, generated_at, tags, sources)
        + "\n"
        + normalized_body.strip()
        + "\n"
    )


def citations(*rows: tuple[str, str]) -> str:
    return "# Citations\n\n" + "\n".join(f"[{index}] [{label}]({url})" for index, (label, url) in enumerate(rows, 1))


def markdown_files(corpus: dict[str, Any], source_meta: dict[str, Any]) -> dict[Path, str]:
    generated_at = corpus["descriptor"]["generated_at"]
    records = corpus["records"]
    facets = corpus["facets"]
    files: dict[Path, str] = {}
    files[Path("index.md")] = concept("Legal Knowledge Bundle", "legislation.gov.uk complete corpus", "Progressive-disclosure OKF catalogue of every work exposed by legislation.gov.uk, with live provision-level traversal.", f"{BASE}/", generated_at, ["legislation", "eli", "clml", "complete-corpus"], f"""# Scope

This pack indexes **{len(records):,} legal works** returned by the official legislation and draft Atom feeds. It includes {len(facets['document_type'])} live document types, {len(facets['creation_year'])} represented calendar years, all advertised manifestations for each work, every documented data-access surface, and a normalized vocabulary for document subdivisions.

# Progressive discovery

1. Start with [categories and document types](types/).
2. Narrow by year, jurisdiction or [derived topic](topics/).
3. Open a work to inspect identifiers, dates, versions, formats and provenance.
4. Load its official CLML tree to traverse introductions, Parts, Chapters, cross-headings, sections, articles, regulations, rules, paragraphs, Schedules, appendices, attachments, signatures and explanatory notes.
5. Cite the official work or provision URI and the displayed passage; never cite this derived catalogue as the law.

# Knowledge areas

* [Ontology and normalized vocabulary](ontology/)
* [APIs and access methods](access/)
* [Coverage, provenance and limitations](methodology/)
* [Explorer descriptor](okf-explorer.json)

# Canonical access

| Repository | Canonical descriptor | Declared `raw_subpath` | Release/archive fallback |
|---|---|---|---|
| [GitHub](https://github.com/chris-page-gov/okf-uk-legislation) | [published descriptor](https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json) | `bundle` | [immutable releases](https://github.com/chris-page-gov/okf-uk-legislation/releases) |

# Official sources and examples

* [legislation.gov.uk](https://www.legislation.gov.uk/)
* [Official legislation data/API documentation]({DATA_DOCS})
* [Official data.gov.uk API documentation](https://guidance.data.gov.uk/get_data/api_documentation/)
* [GOV.UK CKAN example descriptor](https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json)
* [Preserved OKF Bundle Wiki authoring guide](https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md)

{citations(("Legislation.gov.uk data reuse documentation", DATA_DOCS), ("Legislation document data model", MODEL_DOCS), ("ELI ontology", ELI), ("Schema.org Legislation", SCHEMA_ORG), ("CLML User Guide", CLML_DOCS))}""")
    files[Path("log.md")] = f"# Legislation OKF generation log\n\n## {generated_at[:10]}\n\n* **Generation**: indexed {len(records):,} official works and {sum(row['resource_count'] for row in records):,} advertised manifestations.\n* **Normalization**: mapped works and subdivisions to ELI 1.5, ELI-I, Schema.org Legislation, CLML and Akoma Ntoso.\n* **Access**: retained Atom, CLML, AKN, RDF/XML, HTML, PDF, CSV, effects and publication-log routes where supplied or documented.\n"
    files[Path("ontology/index.md")] = concept("Ontology Index", "Legal ontology and normalized vocabulary", "Crosswalk between legislation.gov.uk, ELI, Schema.org, CLML and Akoma Ntoso.", ELI, generated_at, ["ontology", "eli", "schema-org", "clml"], f"""# Selected model

ELI 1.5 is the primary interoperability ontology because it models legal works, expressions, manifestations and subdivisions. ELI-I describes amendment impacts. Schema.org `Legislation` is the public-web projection. The official legislation.gov.uk FRBR variant, CLML and Akoma Ntoso provide source-native identity, version and structure.

* [Normalized vocabulary](normalized-vocabulary.md)
* [ELI and ELI-I](eli.md)
* [Schema.org Legislation](schema-org.md)
* [CLML structure](clml.md)
* [Akoma Ntoso](akoma-ntoso.md)
* [Crosswalk](crosswalk.md)

{citations(("ELI", ELI), ("ELI-I", ELI_I), ("Schema.org Legislation", SCHEMA_ORG), ("Legislation.gov.uk data model", MODEL_DOCS), ("CLML User Guide", CLML_DOCS), ("Akoma Ntoso", AKN))}""")
    ontology_docs = {
        "eli.md": ("ELI and ELI-I", "ELI provides Work/Expression/Manifestation and subdivision semantics; ELI-I models detailed legal impacts.", ELI, "`eli:LegalResource` is the normalized class for a legislation item; `eli:LegalExpression` represents a version; `eli:Format` represents a serialization; `eli:LegalResourceSubdivision` represents a Part, section, article or other addressable component. ELI-I is used as the relationship target for effects and consolidation metadata."),
        "schema-org.md": ("Schema.org Legislation", "Web-facing legal structured data aligned to the ELI ontology.", SCHEMA_ORG, "Every work maps to `schema:Legislation`. Core mappings include `legislationIdentifier`, `legislationType`, `legislationDate`, `legislationDateVersion`, `legislationJurisdiction`, `legislationChanges`, `legislationCommences`, `legislationRepeals`, `legislationAmends`, `isPartOf`, `hasPart`, `encoding`, `citation` and `license`."),
        "clml.md": ("Crown Legislation Markup Language", "Authoritative structured source for UK legislation content, metadata and subdivisions.", CLML_DOCS, "CLML 2.6 supports primary, secondary and EU-origin legislation. The Explorer normalizes `Group`, `Part`, `Chapter`, `Pblock`, `PsubBlock`, `P1group`–`P3group`, `P1`–`P7`, `Schedule`, `Appendix`, EU divisions and attachments while preserving source element names, IDs, status, extent and passage text."),
        "akoma-ntoso.md": ("Akoma Ntoso", "International OASIS LegalDocML representation advertised by the Legislation API.", AKN, "Akoma Ntoso is retained as an advertised manifestation for cross-jurisdictional exchange. CLML remains the preferred source for the Explorer's UK-specific subdivision resolver because the official service describes it as carrying the most complete semantic information."),
        "crosswalk.md": ("Legal standards crosswalk", "Normalized relationships between the source model and interoperable vocabularies.", MODEL_DOCS, "| Source concept | ELI | Schema.org | Explorer vocabulary |\n|---|---|---|---|\n| Item identifier URI | `eli:LegalResource` | `schema:Legislation` | Legislation Work |\n| Point-in-time document URI | `eli:LegalExpression` | `legislationDateVersion` | Legal Expression |\n| CLML/AKN/HTML/PDF | `eli:Format` | `encoding` / `LegislationObject` | Manifestation |\n| Part/Chapter/P1–P7/Schedule | `eli:LegalResourceSubdivision` | `schema:Legislation` + `isPartOf` | Provision node |\n| Effect | ELI-I `Impact` / ELI change properties | `legislationChanges` specializations | Legal effect |\n| Official URI | `eli:uri_schema` / `eli:id_local` | `legislationIdentifier` | Provenance link |"),
        "normalized-vocabulary.md": ("Normalized legislation vocabulary", "Agent-facing vocabulary covering works, versions, manifestations and every CLML structural level.", MODEL_DOCS, "| Normalized concept | Source signals | Meaning |\n|---|---|---|\n| Legislation Work | identifier URI | Abstract legal item independent of version |\n| Legal Expression | current, enacted/made/adopted, dated, prospective, quashed URI | Text/meaning at a point in time, extent and language |\n| Manifestation | `data.xml`, `data.akn`, `data.html`, `data.xht`, `data.pdf`, `data.csv`, `data.rdf` | File-format embodiment |\n| Introduction | `PrimaryPrelims`, `SecondaryPrelims`, `EUPrelims` | Preliminary matter |\n| Group / Part / Chapter | matching CLML elements | Numbered higher-level divisions |\n| Cross-heading | `Pblock`, `PsubBlock` | Titled unnumbered grouping |\n| Provision | `P1` with ID prefix | Section, article, regulation, rule or paragraph |\n| Nested provision | `P2`–`P7` | Subsection, paragraph, sub-paragraph or deeper level |\n| Schedule / Appendix / Attachment / Annex | matching containers and IDs | Supplemental legal text |\n| Signature / Explanatory note | `SignedSection`, `ExplanatoryNotes` | Closing and explanatory matter |\n| Legal effect | changes/effects feed | Amendment, repeal, substitution, commencement or other impact |"),
    }
    for filename, (title, description, resource, body) in ontology_docs.items():
        files[Path("ontology") / filename] = concept("Legal Ontology", title, description, resource, generated_at, ["ontology", slugify(title)], f"# Model\n\n{body}\n\n{citations((title, resource), ("Legislation.gov.uk data model", MODEL_DOCS))}")
    files[Path("access/index.md")] = concept("Access Index", "Legislation data access", "All documented ways to discover, retrieve, monitor and reuse legislation.gov.uk data.", API_DOCS, generated_at, ["api", "access", "provenance"], "# Access surfaces\n\n* [API overview](api-overview.md)\n* [Search, lists and feeds](search-lists-feeds.md)\n* [Representations and content negotiation](representations.md)\n* [Metadata resources and associated documents](metadata-resources.md)\n* [Changes and effects](changes-effects.md)\n* [Publication Log](publication-log.md)\n* [Linked Data and SPARQL](sparql.md)\n* [Bulk data](bulk-data.md)\n* [Licensing](licensing.md)\n* [Fair use](fair-use.md)\n")
    access_docs = {
        "api-overview.md": ("Legislation API", API_DOCS, "The website is also an HTTP API. `GET` retrieves content, metadata, lists and feeds; SPARQL documents `GET` and `POST`. CORS is documented for `/data.[ext]` representations. Dynamic PDFs can return `202 Accepted` while generated."),
        "search-lists-feeds.md": ("Search, lists and Atom feeds", SEARCH_DOCS, "Use `/search/data.feed` query parameters or path-based lists; filter by type, year, number, title and full text; follow Atom pagination links; set sort explicitly because HTML and feed defaults differ. Identifier search under `/id?...` resolves uncertain citations."),
        "representations.md": ("Representations and content negotiation", FORMATS_DOCS, "Structured legislation can be obtained as CLML (`data.xml`), Akoma Ntoso (`data.akn`), XHTML (`data.xht`/`data.htm`), HTML5 (`data.html`), PDF (`data.pdf`), CSV and RDF/XML where advertised. Lists and searches use Atom (`data.feed`)."),
        "metadata-resources.md": ("Metadata resources and associated documents", API_DOCS, "CLML `ukm:Metadata` and AKN `meta` describe identifiers, dates, types, alternatives, associated documents, enabling powers and unapplied changes where available. `/resources/data.xml` provides metadata without the full text. Static PDF and associated-document URIs must be read from metadata."),
        "changes-effects.md": ("Changes, effects and commencements", SEARCH_DOCS, "Affected and affecting feeds expose amendment metadata including source/target provisions, effect type, dates, extent and application status where held. Absence is not proof that no legal effect exists because historical and editorial coverage is partial."),
        "publication-log.md": ("Publication Log", PUBLICATION_DOCS, "The update feed records publication, republication and withdrawal of legislation, drafts, associated documents, impact assessments and effects. Use filtered date/type/item feeds for synchronization; historical events before the log are incomplete."),
        "sparql.md": ("Linked Data and SPARQL", LINKED_DOCS, "The beta linked-data model covers core works and original/current interpretations from 1235 onward using a legislation ontology and provenance graphs. The public documentation remains useful, but the endpoint returned HTTP 401 `By Invitation Only` during this build and is therefore not the corpus source."),
        "bulk-data.md": ("Bulk statute-book data", "https://research.legislation.gov.uk/data", "Research Legislation documents bulk CLML, AKN, HTML and plaintext collections plus core metadata, interpretations, website inventory, in-force and amendments datasets. During this build its anonymous download URLs returned HTTP 401, so the reproducible generator uses year-partitioned Atom feeds instead."),
        "licensing.md": ("Licensing", LICENCE_DOCS, "Content is generally available under OGL v3.0 with attribution. EU-derived and Westlaw-derived material can carry additional terms; preserve item-level source metadata and consult the official licensing page before redistribution."),
        "fair-use.md": ("Fair use", FAIR_USE_DOCS, "Identify automated requests, remain below 3,000 requests per five minutes, use a conservative crawl rate, cache responses, prefer bulk data for large one-off extraction and filtered publication feeds for updates. This generator makes at most one 10,000-result request per represented year and caches every response."),
    }
    for filename, (title, resource, body) in access_docs.items():
        files[Path("access") / filename] = concept("API Capability", title, body.split(".")[0] + ".", resource, generated_at, ["api", slugify(title)], f"# Guidance\n\n{body}\n\n{citations((title, resource), ("API overview", API_DOCS))}")
    files[Path("types/index.md")] = concept("Legislation Type Index", "Legislation types", "Every live document type returned by the official corpus facets.", URI_DOCS, generated_at, ["types", "legislation"], "# Types\n\n" + "\n".join(f"* [{TYPE_TITLES.get(row['value'], row['value'])}]({next((record['type_code'] for record in records if record['document_type'] == row['value']), slugify(row['value']))}.md) — {row['count']:,} works." for row in facets["document_type"]) + "\n\n" + citations(("URI schema reference", URI_DOCS), ("Live Atom facets", f"{BASE}/all/data.feed?results-count=1")))
    for row in facets["document_type"]:
        kind = row["value"]
        sample = next(record for record in records if record["document_type"] == kind)
        code = sample["type_code"]
        files[Path("types") / f"{code}.md"] = concept("Legislation Type", TYPE_TITLES.get(kind, kind), f"Official `{code}` collection mapped to `{kind}`.", f"{BASE}/{code}", generated_at, ["type", code, sample["category"]], f"# Identity\n\n| Field | Value |\n|---|---|\n| URI code | `{code}` |\n| Document main type | `{kind}` |\n| Normalized category | `{sample['category']}` |\n| Indexed works | {row['count']:,} |\n| Jurisdiction heuristic | {', '.join(sample['jurisdiction'])} |\n\n# Access\n\n* [Browse]({BASE}/{code})\n* [Atom feed]({BASE}/{code}/data.feed)\n* Identifier template: `{BASE}/id/{code}/{{year}}/{{number}}`\n* CLML template: `{BASE}/{code}/{{year}}/{{number}}/data.xml`\n\n{citations(("URI schema reference", URI_DOCS), ("Coverage by type", COVERAGE_DOCS))}")
    files[Path("topics/index.md")] = concept("Topic Index", "Derived legislation topics", "Deterministic title-derived discovery topics with explicit non-authoritative status.", f"{BASE}/all", generated_at, ["topics", "derived-classification"], "# Important status\n\nThese topics are navigation aids inferred only from titles. They are not legal advice, official subject headings, or a substitute for full-text research. Each result retains its official type, identifier and source passage route.\n\n# Topics\n\n" + "\n".join(f"* [{row['value']}]({slugify(row['value'])}.md) — {row['count']:,} works." for row in facets["topic"]) + "\n")
    for row in facets["topic"]:
        topic = row["value"]
        rule = next((pattern for label, pattern in TOPIC_RULES if label == topic), "fallback — no title rule matched")
        files[Path("topics") / f"{slugify(topic)}.md"] = concept("Derived Legal Topic", topic, f"Title-derived discovery grouping containing {row['count']:,} works.", f"{BASE}/all/data.feed?title={slugify(topic)}", generated_at, ["topic", "derived", slugify(topic)], f"# Classification\n\n* Indexed works: **{row['count']:,}**\n* Rule: `{rule}`\n* Evidence basis: legislation title only\n* Authority: derived and non-official\n\nUse the Explorer facet to inspect all included works, then verify relevance against official text and status.\n\n{citations(("Search, lists and feeds", SEARCH_DOCS), ("Coverage limitations", COVERAGE_DOCS))}")
    requests = source_meta.get("requests", [])
    files[Path("methodology/index.md")] = concept("Methodology", "Corpus completeness, provenance and limitations", "How the complete website corpus is enumerated, normalized, validated and refreshed.", f"{BASE}/all/data.feed", generated_at, ["methodology", "provenance", "quality"], f"# Completeness contract\n\n* Every official `facetYear` partition is retrieved with `results-count=10000`.\n* The received count for each year must exactly match its advertised facet total or generation stops.\n* IDs are deduplicated across year and draft feeds.\n* **{len(records):,}** unique works were emitted from **{len(requests)}** source requests or cache reads.\n* Every work retains the official identifier, document, CLML, table-of-contents and manifestation links advertised by its Atom entry.\n* Every addressable subdivision is discoverable from its work's official CLML on demand; subdivision instances are not duplicated in Git.\n\n# Source conflict retained\n\nThe public documentation advertises SPARQL and bulk downloads, but both surfaces returned HTTP 401 to anonymous clients during implementation. The Atom and document APIs remained available and are the build source. Topic labels are explicitly derived because the linked-data documentation says subject-classification data are a future development.\n\n# Legal-use warning\n\nLatest-available text may have unapplied changes and is not guaranteed to be legally current. Historical coverage, effects and format availability vary. Answers must cite work/provision URI, version/extent/language context and retrieved passage.\n\n{citations(("Atom API", API_DOCS), ("Coverage limitations", COVERAGE_DOCS), ("Linked Data limitations", LINKED_DOCS), ("Fair use", FAIR_USE_DOCS))}")
    for path, document in list(files.items()):
        if path.name != "index.md":
            continue
        _frontmatter, body = document.split("\n---\n", 1)
        prefix = '---\nokf_version: "0.2"\n---\n\n' if path == Path("index.md") else ""
        files[path] = prefix + body.lstrip("\n")
    return files


def build_corpus(records: list[dict[str, Any]], source_meta: dict[str, Any], generated_at: str) -> dict[str, Any]:
    snapshot = f"legislation-work-index-{generated_at}"
    facets = build_facets(records)
    publishers = build_publishers(records)
    record_chunks = [(path.with_suffix(".json.gz"), rows) for path, rows in large_corpus.chunk_paths("works", records, chunk_size=1000)]
    discovery_records, route_aliases, route_collisions = (
        disambiguate_discovery_routes(records)
    )
    search = build_legislation_search(discovery_records, snapshot)
    record_locator = build_record_locator(
        discovery_records,
        record_chunks,
        snapshot,
    )
    record_locator["manifest"].update(
        {
            "route_aliases": route_aliases,
            "route_collisions": route_collisions,
            "collision_routes": len(route_collisions),
        }
    )
    presentation = explorer_presentation(snapshot)
    resource_chunks = large_corpus.chunk_paths("manifestations", [], chunk_size=1000)
    publisher_chunks = large_corpus.chunk_paths("categories", publishers, chunk_size=1000)
    relationships = semantic_relationships(records, generated_at)
    relationship_chunks = [(path.with_suffix(".json.gz"), rows) for path, rows in large_corpus.chunk_paths("relationships", relationships, chunk_size=5000)]
    relationship_adjacency, relationship_adjacency_buckets = large_corpus.build_relationship_adjacency(relationships)
    relationship_adjacency["buckets"] = {bucket: path.replace(".json", ".json.gz") for bucket, path in relationship_adjacency["buckets"].items()}
    relationship_adjacency_buckets = [(path.with_suffix(".json.gz"), routes) for path, routes in relationship_adjacency_buckets]
    relationship_composition_rows = summarize_relationship_rows(
        relationships,
        "core",
        default_freshness="current",
    )
    relationship_composition = relationship_composition_document(
        relationship_composition_rows,
        snapshot,
        generated_at,
    )
    analysis = analysis_for(
        records,
        facets,
        generated_at,
        core_relationship_count=len(relationships),
        relationship_rows=relationship_composition_rows,
        snapshot=snapshot,
    )
    counts = {
        "works": len(records),
        "records": len(records),
        "datasets": len(records),
        "manifestations": sum(row["resource_count"] for row in records),
        # Manifestation links are embedded on their work and progressively
        # rendered by the legislation detail panel; no duplicate resource
        # rows are emitted into the generic resource chunks.
        "resources": 0,
        "categories": len(publishers),
        "publishers": len(publishers),
        "document_types": len(facets["document_type"]),
        "represented_years": len(facets["creation_year"]),
        "topics": len(facets["topic"]),
        "relationships": len(relationships),
    }
    overview = {
        "schema": "okf-large-overview.v1",
        "title": "legislation.gov.uk complete corpus",
        "generated_at": generated_at,
        "snapshot": snapshot,
        "counts": counts,
        "top_publishers": [{"name": row["name"], "title": row["title"], "dataset_count": row["dataset_count"], "resource_count": row["resource_count"]} for row in publishers],
        "recent_datasets": [
            search_result_document(discovery_records[ordinal], ordinal)
            for ordinal in sorted(
                range(len(records)),
                key=lambda item: str(records[item].get("creation_date", "")),
                reverse=True,
            )[:12]
        ],
        "format_counts": facets["format"],
        "facet_previews": {key: rows[:18] for key, rows in facets.items()},
        "notices": analysis["summary"]["notices"],
    }
    manifest = {
        "okf_version": "0.2",
        "title": "legislation.gov.uk static work index with live provision resolver",
        "generated_at": generated_at,
        "snapshot": snapshot,
        "counts": counts,
        "indexes": {
            "overview": "data/overview.json",
            "analysis": "data/analysis/overview.json",
            "search": "data/search/manifest.json",
            "facets": "data/facets.json",
            "presentation": "data/presentation.json",
            "record_locator": "data/records/manifest.json",
            "graph": "data/graph.json",
            "relationship_adjacency": "data/adjacency/manifest.json",
            "relationship_composition": "data/relationship-composition.json",
        },
        "chunks": {"datasets": [str(path) for path, _ in record_chunks], "resources": [str(path) for path, _ in resource_chunks], "publishers": [str(path) for path, _ in publisher_chunks], "relationships": [str(path) for path, _ in relationship_chunks]},
        "performance": {
            "startup_mode": "overview-first",
            "full_record_hydration": "single-shard-by-route-or-search-ordinal",
            "full_corpus_hydration": "disabled-in-browser",
            "facet_hydration": "exact-v2-filter-postings",
            "relationship_hydration": "lazy",
            "route_relationship_hydration": "hash-sharded adjacency",
            "search": "bounded static worker shards plus official remote full-text Atom search",
            "provision_hydration": "live CLML per selected work",
        },
        "search": {
            "schema": search["manifest"]["schema"],
            "documents": len(records),
            "tokens": search["manifest"]["counts"]["tokens"],
            "result_limit": search["manifest"]["result_limit"],
            "filter_postings": len(
                search["manifest"]["entrypoints"]["filter_postings"]
            ),
        },
    }
    descriptor = {
        "@context": "https://chris-page-gov.github.io/okf-explorer/profile/bundle-wiki/v1/context.jsonld",
        "@id": "https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json",
        "schema": "okf-explorer-large-corpus.v1",
        "kind": "okf-large-corpus",
        "okf_version": "0.2",
        "core_conformance": "Markdown concept layer",
        "title": "UK Legislation OKF",
        "description": "Complete work-level index of legislation.gov.uk with ELI/Schema.org normalization, corpus facets, official full-text search, and live CLML provision-level progressive discovery.",
        "version": "0.2.0",
        "status": "preview",
        "profile": "https://chris-page-gov.github.io/okf-explorer/profile/bundle-wiki/v1/",
        "publisher": "https://github.com/chris-page-gov",
        "license": OGL,
        "semantic_descriptor": "https://chris-page-gov.github.io/okf-uk-legislation/okf-bundle.yamlld",
        "generated_at": generated_at,
        "snapshot": snapshot,
        "entrypoints": {
            "viewer": "https://chris-page-gov.github.io/okf-explorer/",
            "data_manifest": "data/manifest.json",
            "overview_index": "data/overview.json",
            "analysis_overview": "data/analysis/overview.json",
            "presentation": "data/presentation.json",
            "search_manifest": "data/search/manifest.json",
            "record_locator": "data/records/manifest.json",
            "relationship_adjacency": "data/adjacency/manifest.json",
            "relationship_composition": "data/relationship-composition.json",
            "markdown_index": "index.md",
            "notes": "methodology/index.md",
            "ontology": "ontology/index.md",
            "evaluation": "evaluation/README.md",
            "model_enrichment": "enrichment/model-assisted-v1.json",
            "model_enrichment_v1_audit": (
                "enrichment/model-assisted-v1-independent-audit.json"
            ),
            "model_enrichment_v1_audit_report": (
                "enrichment/model-assisted-v1-independent-audit.md"
            ),
        },
        "counts": counts,
        "performance": manifest["performance"],
        "source": {"title": "legislation.gov.uk public API", "url": BASE, "data_url": f"{BASE}/all/data.feed", "license": "Open Government Licence v3.0 unless additional terms apply", "source_adapter": "legislation_gov_uk_atom", "request_count": len(source_meta.get("requests", [])), "fair_use": FAIR_USE_DOCS},
        "vocabulary": {"record_singular": "legal work", "record_plural": "legal works", "resource_singular": "manifestation", "resource_plural": "manifestations", "publisher_singular": "category", "publisher_plural": "categories", "format_plural": "formats", "resource_stack_label": "Manifestation stack", "search_placeholder": "Search titles locally; official full-text results are added automatically"},
        "extensions": {
            "okf-legislation-corpus.v1": {
                "mode": "complete-work-index-live-subdivision-resolver",
                "ontology": [
                    "ELI 1.5",
                    "ELI-I",
                    "Schema.org Legislation",
                    "CLML 2.6",
                    "Akoma Ntoso",
                ],
                "remote_full_text_search": (
                    f"{BASE}/all/data.feed?text={{query}}&results-count=20"
                ),
                "structure_source": "record.structure_url",
                "provenance_required": True,
                "topic_classification": (
                    "deterministic-title-rules-non-authoritative; "
                    "rejected legacy v1 model rules excluded"
                ),
            },
            "okf-model-enrichment.v1-historical": {
                "entrypoint": "model_enrichment",
                "audit": "model_enrichment_v1_audit",
                "claimed_review_status": MODEL_ENRICHMENT_SOURCE.get(
                    "review_status",
                    "absent",
                ),
                "independent_review_status": MODEL_ENRICHMENT_DISPOSITION,
                "applied": MODEL_ENRICHMENT_APPLIED,
                "governed_assertions": 0,
                "historical_reconstructed_assertions": int(
                    MODEL_ENRICHMENT_AUDIT.get("affected_outputs", {}).get(
                        "total_v1_assertions_rejected",
                        0,
                    )
                ),
                "authority": "derived-non-official",
            },
            "okf-explorer-analysis.v1": {"mode": "external", "entrypoint": "analysis_overview"},
            "okf-large-corpus-publication.v2": {
                "search": "okf-static-search.v2",
                "facets": "exact-filter-postings",
                "records": "fnv1a32-route-locator",
                "compression": "pre-compressed-gzip",
                "full_corpus_browser_hydration": False,
            },
        },
        "discovery": {
            "repository": "https://github.com/chris-page-gov/okf-uk-legislation",
            "documentation": "https://chris-page-gov.github.io/okf-uk-legislation/docs/",
            "raw_subpath": "bundle",
            "release_archive": "https://github.com/chris-page-gov/okf-uk-legislation/releases",
            "semantic_descriptor": "https://chris-page-gov.github.io/okf-uk-legislation/okf-bundle.yamlld",
            "routes": [
                {
                    "kind": "published",
                    "purpose": "descriptor",
                    "priority": 10,
                    "url": "https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json",
                },
                {
                    "kind": "raw",
                    "purpose": "descriptor",
                    "priority": 20,
                    "url": "https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/main/bundle/okf-explorer.json",
                },
            ],
        },
    }
    relationship_counts = Counter(row["kind"] for row in relationships)
    graph = {"node_counts": {"work": len(records), "manifestation": counts["manifestations"], "category": len(publishers)}, "edge_counts": [{"kind": kind, "count": count} for kind, count in relationship_counts.most_common()], "relationship_index": "data/relationships-0.json.gz", "relationship_adjacency": "data/adjacency/manifest.json", "top_publishers": overview["top_publishers"]}
    return {
        "descriptor": descriptor,
        "manifest": manifest,
        "overview": overview,
        "analysis": analysis,
        "presentation": presentation,
        "record_locator": record_locator,
        "records": records,
        "resources": [],
        "publishers": publishers,
        "relationships": relationships,
        "record_chunks": record_chunks,
        "resource_chunks": resource_chunks,
        "publisher_chunks": publisher_chunks,
        "relationship_chunks": relationship_chunks,
        "relationship_adjacency": relationship_adjacency,
        "relationship_adjacency_buckets": relationship_adjacency_buckets,
        "relationship_composition": relationship_composition,
        "facets": facets,
        "graph": graph,
        "search": search,
    }


def gzip_json(value: Any) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=output,
        compresslevel=6,
        mtime=0,
    ) as stream:
        stream.write(large_corpus.render_json(value).encode("utf-8"))
    return output.getvalue()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def search_publication_files(
    search: dict[str, Any],
    snapshot: str,
) -> dict[Path, str | bytes]:
    files: dict[Path, str | bytes] = {
        Path("data/search/doc-map.json.gz"): gzip_json(search["doc_map"]),
        Path("data/search/sort-values.json.gz"): gzip_json(search["sort_values"]),
    }
    for shard, rows in search["lexicon"].items():
        files[Path(f"data/search/lexicon/{shard}.json.gz")] = gzip_json(rows)
    for shard, payload in search["prefixes"].items():
        files[Path(f"data/search/prefixes/{shard}.json.gz")] = gzip_json(payload)
    for path, payload in search["postings"].items():
        files[Path(path)] = gzip_json(payload)
    for path, rows in search["result_doc_chunks"]:
        files[path] = gzip_json(rows)
    for path, payload in search["filter_payloads"].items():
        files[Path(path)] = gzip_json(payload)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path, body in sorted(files.items(), key=lambda item: item[0].as_posix()):
        relative = path.as_posix()
        if "/lexicon/" in relative:
            group = "lexicon"
        elif "/prefixes/" in relative:
            group = "prefixes"
        elif "/postings/" in relative:
            group = "postings"
        elif "/filters/" in relative:
            group = "filter_postings"
        elif "/results-" in relative:
            group = "result_docs"
        elif relative.endswith("/sort-values.json.gz"):
            group = "sort_values"
        else:
            group = "doc_map"
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        groups[group].append(
            {
                "path": relative,
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "compressed_bytes": len(encoded),
                "compression": "gzip" if relative.endswith(".gz") else "identity",
                "snapshot": snapshot,
            }
        )
    shard_document = {
        "schema": "okf-search-shard-integrity.v1",
        "snapshot": snapshot,
        "shards": dict(sorted(groups.items())),
    }
    search["manifest"]["shard_metadata"] = "data/search/shards.json"
    search["manifest"]["shard_manifest_sha256"] = hashlib.sha256(
        (canonical_json(shard_document["shards"]) + "\n").encode("utf-8")
    ).hexdigest()
    search["manifest"]["counts"].update(
        {
            "lexicon_shards": len(search["manifest"]["entrypoints"]["lexicon"]),
            "postings_shards": len(search["manifest"]["entrypoints"]["postings"]),
            "result_doc_shards": len(
                search["manifest"]["entrypoints"]["result_docs"]
            ),
            "filter_posting_shards": len(
                search["manifest"]["entrypoints"]["filter_postings"]
            ),
            "doc_map_shards": 1,
            "sort_value_shards": 1,
        }
    )
    files[Path("data/search/shards.json")] = large_corpus.render_json(
        shard_document
    )
    files[Path("data/search/manifest.json")] = large_corpus.render_json(
        search["manifest"]
    )
    return files


def record_locator_publication_files(
    locator: dict[str, Any],
) -> dict[Path, str | bytes]:
    files: dict[Path, str | bytes] = {}
    for bucket, routes in locator["buckets"].items():
        path = Path(f"data/records/locator/{bucket}.json.gz")
        body = gzip_json(routes)
        files[path] = body
        locator["manifest"]["buckets"][bucket] = {
            "path": path.as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "compressed_bytes": len(body),
            "records": len(routes),
            "compression": "gzip",
        }
    locator["manifest"]["bucket_count"] = len(locator["manifest"]["buckets"])
    files[Path("data/records/manifest.json")] = large_corpus.render_json(
        locator["manifest"]
    )
    return files


def record_chunk_metadata(
    record_chunks: list[tuple[Path, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Integrity-bind the immutable work shards referenced by the locator."""

    rows: list[dict[str, Any]] = []
    for path, records in record_chunks:
        body = gzip_json(records) if path.suffix == ".gz" else (
            large_corpus.render_json(records).encode("utf-8")
        )
        rows.append(
            {
                "path": path.as_posix(),
                "sha256": hashlib.sha256(body).hexdigest(),
                "compressed_bytes": len(body),
                "records": len(records),
                "compression": "gzip" if path.suffix == ".gz" else "identity",
            }
        )
    return rows


def output_files(corpus: dict[str, Any], source_meta: dict[str, Any]) -> dict[Path, str | bytes]:
    semantic_descriptor = {
        "@context": corpus["descriptor"]["@context"],
        "@id": "https://chris-page-gov.github.io/okf-uk-legislation/",
        "@type": "okf:Bundle",
        "okf_version": "0.2",
        "title": corpus["descriptor"]["title"],
        "description": corpus["descriptor"]["description"],
        "version": corpus["descriptor"]["version"],
        "status": corpus["descriptor"]["status"],
        "profile": {"@id": corpus["descriptor"]["profile"]},
        "descriptor": {"@id": corpus["descriptor"]["@id"]},
        "publisher": {"@id": corpus["descriptor"]["publisher"]},
        "license": {"@id": corpus["descriptor"]["license"]},
        "generatedAt": corpus["descriptor"]["generated_at"],
    }
    files: dict[Path, str | bytes] = {
        Path("okf-bundle.yamlld"): json.dumps(semantic_descriptor, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        Path("okf-bundle.jsonld"): large_corpus.render_json(semantic_descriptor),
        Path("okf-explorer.json"): large_corpus.render_json(corpus["descriptor"]),
        Path("data/manifest.json"): large_corpus.render_json(corpus["manifest"]),
        Path("data/overview.json"): large_corpus.render_json(corpus["overview"]),
        Path("data/analysis/overview.json"): large_corpus.render_json(corpus["analysis"]),
        Path("data/presentation.json"): large_corpus.render_json(corpus["presentation"]),
        Path("data/facets.json"): large_corpus.render_json(corpus["facets"]),
        Path("data/graph.json"): large_corpus.render_json(corpus["graph"]),
        Path("data/adjacency/manifest.json"): large_corpus.render_json(corpus["relationship_adjacency"]),
        Path("data/relationship-composition.json"): large_corpus.render_json(
            corpus["relationship_composition"]
        ),
        Path("data/source-provenance.json"): large_corpus.render_json(source_meta),
        Path("enrichment/model-assisted-v1.json"): MODEL_ENRICHMENT_PATH.read_text(encoding="utf-8"),
        Path("enrichment/model-assisted-v1-independent-audit.json"): (
            MODEL_ENRICHMENT_AUDIT_PATH.read_text(encoding="utf-8")
        ),
        Path("enrichment/model-assisted-v1-independent-audit.md"): (
            MODEL_ENRICHMENT_AUDIT_MARKDOWN_PATH.read_text(encoding="utf-8")
        ),
        Path("enrichment/model-assisted-paid-governance-v1.json"): (
            MODEL_ENRICHMENT_PAID_GOVERNANCE_PATH.read_text(encoding="utf-8")
        ),
        Path("enrichment/model-assisted-calibration-manifest-v1.json"): (
            MODEL_ENRICHMENT_CALIBRATION_MANIFEST_PATH.read_text(
                encoding="utf-8"
            )
        ),
    }
    files.update(
        search_publication_files(
            corpus["search"],
            corpus["descriptor"]["snapshot"],
        )
    )
    corpus["record_locator"]["manifest"]["record_chunks"] = (
        record_chunk_metadata(corpus["record_chunks"])
    )
    files.update(record_locator_publication_files(corpus["record_locator"]))
    for key in ("record_chunks", "resource_chunks", "publisher_chunks", "relationship_chunks"):
        for path, rows in corpus[key]:
            files[path] = gzip_json(rows) if path.suffix == ".gz" else large_corpus.render_json(rows)
    for path, routes in corpus["relationship_adjacency_buckets"]:
        files[path] = gzip_json(routes)
    evaluation_root = ROOT / "evaluation" / "legislation"
    for path in evaluation_root.rglob("*"):
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            if path.suffix == ".md":
                relative = path.relative_to(evaluation_root).as_posix()
                repository_url = (
                    "https://github.com/chris-page-gov/okf-uk-legislation/"
                    f"blob/main/evaluation/legislation/{relative}"
                )
                content = (
                    markdown_frontmatter(
                        "Evaluation Reference",
                        path.stem.replace("-", " ").replace("_", " "),
                        "Evaluation contract for the UK Legislation OKF publication.",
                        repository_url,
                        corpus["descriptor"]["generated_at"],
                        ["evaluation", "quality"],
                        [{"id": "repository-source", "resource": repository_url, "title": path.name}],
                    )
                    + "\n"
                    + content.lstrip("\n")
                )
            files[Path("evaluation") / path.relative_to(evaluation_root)] = content
    files.update(markdown_files(corpus, source_meta))
    return files


def existing_generated_at(output: Path) -> str | None:
    descriptor = output / "okf-explorer.json"
    if not descriptor.exists():
        return None
    try:
        return json.loads(descriptor.read_text(encoding="utf-8")).get("generated_at")
    except (OSError, json.JSONDecodeError):
        return None


def load_existing_records(
    output: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the checked-in source-normalized works for an offline rebuild.

    This path is intentionally limited to deterministic republication.  It
    does not claim a fresh upstream acquisition.  Semantic fields are
    re-derived from titles and the current independently reviewed rule policy,
    so a rejected historical rule cannot survive merely because it was present
    in an older generated shard.
    """

    manifest_path = output / "data" / "manifest.json"
    provenance_path = output / "data" / "source-provenance.json"
    if not manifest_path.is_file() or not provenance_path.is_file():
        raise RuntimeError(
            "offline rebuild requires the existing data manifest and source provenance"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for relative in manifest.get("chunks", {}).get("datasets", []):
        path = output / relative
        if not path.is_file():
            raise RuntimeError(f"offline rebuild source shard is missing: {relative}")
        rows = (
            json.loads(gzip.decompress(path.read_bytes()))
            if path.suffix == ".gz"
            else json.loads(path.read_text(encoding="utf-8"))
        )
        for record in rows:
            title = str(record.get("title", ""))
            code = str(record.get("type_code", ""))
            topics, model_assisted_topics = topics_with_provenance(title, code)
            record["topics"] = topics
            record["semantic_entities"] = entities_for(title)
            record["semantic_enrichment"] = semantic_enrichment_metadata(
                model_assisted_topics
            )
            records.append(record)
    source_meta = json.loads(provenance_path.read_text(encoding="utf-8"))
    return records, source_meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument(
        "--from-existing",
        action="store_true",
        help=(
            "rebuild deterministically from the checked-in normalized work "
            "shards without claiming a fresh upstream acquisition"
        ),
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--generated-at")
    parser.add_argument("--no-drafts", action="store_true")
    args = parser.parse_args(argv)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    cache = args.cache if args.cache.is_absolute() else ROOT / args.cache
    if args.fixture and args.from_existing:
        parser.error("--fixture and --from-existing are mutually exclusive")
    if args.from_existing:
        records, source_meta = load_existing_records(output)
    elif args.fixture:
        records, source_meta = load_fixture(args.fixture if args.fixture.is_absolute() else ROOT / args.fixture)
    else:
        records, source_meta = load_live_records(FeedClient(cache, args.refresh), include_drafts=not args.no_drafts)
    if not records:
        print("no legislation records received", file=sys.stderr)
        return 1
    preserve_existing_timestamp = args.check or args.from_existing
    generated_at = (
        args.generated_at
        or (
            existing_generated_at(output)
            if preserve_existing_timestamp
            else None
        )
        or now_utc()
    )
    corpus = build_corpus(records, source_meta, generated_at)
    files = output_files(corpus, source_meta)
    if args.check:
        errors = large_corpus.check_files(output, files)
        if errors:
            print("Legislation OKF check failed:", file=sys.stderr)
            for error in errors[:80]:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(f"Legislation OKF is synchronized with {len(records):,} legal works")
        return 0
    large_corpus.write_files(output, files)
    output_label = output.relative_to(ROOT) if output.is_relative_to(ROOT) else output
    print(f"wrote {len(files):,} files for {len(records):,} legal works to {output_label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
