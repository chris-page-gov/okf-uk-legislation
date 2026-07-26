#!/usr/bin/env python3
"""Capture bounded, immutable access evidence for the Whole-Law source register.

The research source register contains dated access claims.  This tool does not
rewrite them.  It makes one conservative public probe per declared access
method, stores an immutable request/response envelope, and publishes a compact
projection that compares the observation with the research claim.

No credentials, cookies, authentication challenges, form submissions, search
queries, pagination, crawling, or authentication bypasses are attempted.
Restricted routes receive a HEAD metadata probe only.  All other routes receive
a bounded GET with a Range request and an explicit identity encoding request.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import html.parser
import json
import mimetypes
import os
import re
import shutil
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from source_access_evidence_archive import (
    RECEIPT_ROOT,
    create_archive,
    default_paths as archive_paths,
    directory_snapshot,
    validate_archive,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "research" / "whole-law-okf-research" / "source-register.json"
EVIDENCE_ROOT = (
    ROOT / "evidence" / "source-acquisitions" / "whole-law-access"
)
AUTHORING = ROOT / "whole-law" / "acquisition"
BUNDLE = ROOT / "bundle" / "whole-law" / "acquisition"

TOOL_NAME = "capture_whole_law_source_access"
TOOL_VERSION = "1.0.0"
EVIDENCE_SCHEMA = "okf-source-access-envelope.v1"
RUN_SCHEMA = "okf-source-access-run.v1"
OBSERVATION_SCHEMA = "okf-source-access-observations.v1"
COMPARISON_SCHEMA = "okf-source-access-comparison.v1"
CONSTRAINT_SCHEMA = "okf-source-constraint-ledger.v1"
PROJECTION_SCHEMA = "okf-source-access-publication-projection.v1"
REDACTION_SCHEMA = "okf-source-access-publication-redactions.v2"
PUBLIC_REPOSITORY = "https://github.com/chris-page-gov/okf-uk-legislation"
DEFAULT_USER_AGENT = (
    "UK-Whole-Law-OKF-source-access-evidence/"
    f"{TOOL_VERSION} (+{PUBLIC_REPOSITORY})"
)
SAFE_RESPONSE_HEADERS = {
    "accept-ranges",
    "age",
    "allow",
    "cache-control",
    "content-encoding",
    "content-language",
    "content-length",
    "content-location",
    "content-range",
    "content-type",
    "date",
    "etag",
    "expires",
    "last-modified",
    "link",
    "location",
    "retry-after",
    "server",
    "vary",
    "via",
    "x-cache",
    "x-cache-hits",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-request-id",
}
SENSITIVE_RESPONSE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "set-cookie",
    "cookie",
}
CONSTRAINT_KINDS = {
    "fair-use",
    "licence",
    "authentication",
    "rate-limit",
    "robots",
    "privacy",
    "availability",
    "hosting",
}
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")


class _HTMLStructureParser(html.parser.HTMLParser):
    """Collect a bounded structural signature without retaining page text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: Counter[str] = Counter()
        self.first_tags: list[str] = []
        self.metadata_names: set[str] = set()
        self.link_relations: set[str] = set()
        self.title_present = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        self.tags[tag] += 1
        if len(self.first_tags) < 64:
            self.first_tags.append(tag)
        attributes = {key.lower(): value for key, value in attrs}
        if tag == "title":
            self.title_present = True
        if tag == "meta":
            name = attributes.get("name") or attributes.get("property")
            if name:
                self.metadata_names.add(name.lower())
        if tag == "link" and attributes.get("rel"):
            self.link_relations.update(
                token.lower() for token in attributes["rel"].split()
            )


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def isoformat(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(value)


def write_new_json(path: Path, value: Any) -> None:
    write_new_bytes(path, render_json(value).encode("utf-8"))


def write_projection_json(path: Path, value: Any) -> None:
    """Atomically update a generated current-state projection."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(render_json(value), encoding="utf-8")
    os.replace(temporary, path)


def write_projection_text(path: Path, value: str) -> None:
    """Atomically update a generated human-readable projection."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def make_run_id(now: dt.datetime | None = None) -> str:
    value = now or utc_now()
    stamp = value.strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def enumerate_access_methods(
    source_register: dict[str, Any],
) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    for source in source_register["records"]:
        for position, access_method in enumerate(
            source.get("access_methods", []),
            start=1,
        ):
            status = str(access_method.get("status", "")).strip()
            url = str(access_method.get("url", "")).strip()
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    f"{source['id']} access method {position} has unsafe URL: {url}"
                )
            restricted = status == "authenticated or restricted"
            methods.append(
                {
                    "method_id": f"{source['id']}-A{position:02d}",
                    "source_id": source["id"],
                    "source_title": source["title"],
                    "owning_institution": source["owning_institution"],
                    "authority_classes": source.get("authority_classes", []),
                    "source_classes": source.get("source_classes", []),
                    "kind": access_method.get("kind", ""),
                    "url": url,
                    "research_claim": {
                        "status": status,
                        "tested_at": access_method.get("tested_at") or None,
                        "test_method": access_method.get("test_method") or None,
                        "notes": access_method.get("notes") or None,
                        "source_register_access_test_date": source_register.get(
                            "access_test_date"
                        ),
                    },
                    "request_method": "HEAD" if restricted else "GET",
                    "probe_scope": (
                        "public-metadata-only-no-authentication"
                        if restricted
                        else "bounded-public-response"
                    ),
                    "licence_and_reuse": source.get("licence_and_reuse", ""),
                    "fair_use_rate_limit_robots": source.get(
                        "fair_use_rate_limit_robots",
                        "",
                    ),
                }
            )
    method_ids = [method["method_id"] for method in methods]
    if len(method_ids) != len(set(method_ids)):
        raise ValueError("Source register generated duplicate access method IDs")
    return methods


def request_headers(
    method: dict[str, Any],
    max_body_bytes: int,
    user_agent: str,
) -> dict[str, str]:
    headers = {
        "Accept": (
            "application/ld+json, application/json, application/xml, "
            "text/xml, text/html, text/plain, */*;q=0.1"
        ),
        "Accept-Encoding": "identity",
        "User-Agent": user_agent,
    }
    if method["request_method"] == "GET":
        headers["Range"] = f"bytes=0-{max_body_bytes - 1}"
    return headers


def safe_response_headers(
    headers: Any,
) -> tuple[dict[str, str], list[str], list[str]]:
    captured: dict[str, str] = {}
    received: set[str] = set()
    omitted: set[str] = set()
    for key, value in headers.items():
        normalized = key.lower()
        received.add(normalized)
        if normalized in SAFE_RESPONSE_HEADERS:
            captured[normalized] = str(value)
        else:
            omitted.add(normalized)
    sensitive_present = sorted(
        name for name in received if name in SENSITIVE_RESPONSE_HEADERS
    )
    return captured, sorted(received), sensitive_present


def maybe_decoded_body(
    body: bytes,
    headers: dict[str, str],
    max_body_bytes: int,
) -> tuple[bytes, str]:
    encoding = headers.get("content-encoding", "").lower()
    if encoding != "gzip" or not body.startswith(b"\x1f\x8b"):
        return body, "wire"
    try:
        decompressed = gzip.decompress(body)
    except (EOFError, OSError):
        return body, "wire-gzip-partial"
    return decompressed[:max_body_bytes], "decoded-gzip"


def json_structure(
    value: Any,
    *,
    prefix: str = "$",
    depth: int = 0,
    limit: int = 160,
) -> list[str]:
    if depth > 4 or limit <= 0:
        return []
    if isinstance(value, dict):
        result = [f"{prefix}:object"]
        for key in sorted(value)[:40]:
            result.extend(
                json_structure(
                    value[key],
                    prefix=f"{prefix}.{key}",
                    depth=depth + 1,
                    limit=limit - len(result),
                )
            )
            if len(result) >= limit:
                break
        return result[:limit]
    if isinstance(value, list):
        result = [f"{prefix}:array"]
        for position, item in enumerate(value[:3]):
            result.extend(
                json_structure(
                    item,
                    prefix=f"{prefix}[]",
                    depth=depth + 1,
                    limit=limit - len(result),
                )
            )
            if len(result) >= limit:
                break
        return result[:limit]
    if value is None:
        kind = "null"
    elif isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (int, float)):
        kind = "number"
    else:
        kind = "string"
    return [f"{prefix}:{kind}"]


def schema_fingerprint(
    body: bytes,
    headers: dict[str, str],
    final_url: str,
    max_body_bytes: int,
) -> dict[str, Any]:
    media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not media_type:
        guessed, _ = mimetypes.guess_type(
            urllib.parse.urlsplit(final_url).path
        )
        media_type = guessed or "application/octet-stream"
    decoded, representation = maybe_decoded_body(
        body,
        headers,
        max_body_bytes,
    )
    kind = "binary"
    signals: dict[str, Any] = {
        "media_type": media_type,
        "representation": representation,
    }
    stripped = decoded.lstrip()
    if (
        media_type == "application/json"
        or media_type.endswith("+json")
        or stripped.startswith((b"{", b"["))
    ):
        try:
            value = json.loads(decoded.decode("utf-8"))
            structure = json_structure(value)
            kind = "json"
            signals["structure"] = structure
        except (UnicodeDecodeError, json.JSONDecodeError):
            kind = "json-partial-or-invalid"
    elif (
        media_type in {"application/xml", "text/xml", "application/atom+xml"}
        or media_type.endswith("+xml")
        or stripped.startswith(b"<?xml")
    ):
        try:
            root = ET.fromstring(decoded)
            children = sorted(
                {child.tag for child in list(root)[:100]}
            )
            kind = "xml"
            signals["root"] = root.tag
            signals["direct_child_elements"] = children
        except ET.ParseError:
            kind = "xml-partial-or-invalid"
    elif media_type in {"text/html", "application/xhtml+xml"} or re.match(
        br"(?is)<!doctype\s+html|<html(?:\s|>)",
        stripped[:256],
    ):
        parser = _HTMLStructureParser()
        try:
            parser.feed(decoded.decode("utf-8", errors="replace"))
            kind = "html"
            signals.update(
                {
                    "first_tags": parser.first_tags,
                    "tag_counts": dict(sorted(parser.tags.items())),
                    "metadata_names": sorted(parser.metadata_names),
                    "link_relations": sorted(parser.link_relations),
                    "title_present": parser.title_present,
                }
            )
        except Exception as error:  # HTMLParser can receive malformed markup.
            kind = "html-partial"
            signals["parser_error"] = type(error).__name__
    elif decoded.startswith(b"%PDF-"):
        kind = "pdf"
        signals["pdf_signature"] = decoded[:8].decode(
            "ascii",
            errors="replace",
        )
    elif media_type.startswith("text/"):
        kind = "text"
        text = decoded.decode("utf-8", errors="replace")
        signals["line_count_in_capture"] = text.count("\n") + bool(text)
        signals["first_line_length"] = (
            len(text.splitlines()[0]) if text.splitlines() else 0
        )
    else:
        signals["magic_hex"] = decoded[:16].hex()
    signature = {"kind": kind, "signals": signals}
    return {
        **signature,
        "fingerprint_sha256": sha256_bytes(canonical_json_bytes(signature)),
    }


class HostLimiter:
    def __init__(self, per_host: int) -> None:
        self.per_host = per_host
        self._lock = threading.Lock()
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}

    def for_url(self, url: str) -> threading.BoundedSemaphore:
        hostname = (urllib.parse.urlsplit(url).hostname or "").lower()
        with self._lock:
            if hostname not in self._semaphores:
                self._semaphores[hostname] = threading.BoundedSemaphore(
                    self.per_host
                )
            return self._semaphores[hostname]


def classify_http_observation(
    status: int | None,
    error_type: str | None,
) -> str:
    if status is None:
        return "network-error" if error_type else "no-response"
    if 200 <= status < 400:
        return "reachable"
    if status in {401, 403, 407}:
        return "restricted"
    if status == 429:
        return "rate-limited"
    if status in {404, 410, 451}:
        return "unavailable"
    if 400 <= status < 500:
        return "client-error"
    if status >= 500:
        return "server-error"
    return "unexpected-response"


def compare_with_research_claim(
    method: dict[str, Any],
    observed_state: str,
) -> dict[str, str]:
    claim = method["research_claim"]["status"]
    restricted_claim = claim == "authenticated or restricted"
    if restricted_claim:
        if observed_state == "restricted":
            comparison = "restriction-confirmed"
        elif observed_state == "reachable":
            comparison = "public-surface-reachable-restriction-not-bypassed"
        else:
            comparison = "restriction-not-disproved"
        conclusion = (
            "The probe tested public response metadata only. It did not "
            "authenticate and cannot establish access to the restricted corpus."
        )
        return {"comparison": comparison, "conclusion": conclusion}
    if claim == "verified working":
        if observed_state == "reachable":
            comparison = "claim-confirmed"
        elif observed_state in {"restricted", "rate-limited"}:
            comparison = "public-access-regression-observed"
        else:
            comparison = "claim-not-reproduced"
    elif claim == "documented but not tested":
        comparison = (
            "route-now-observed-reachable"
            if observed_state == "reachable"
            else "route-test-unsuccessful"
        )
    elif claim == "unavailable":
        comparison = (
            "route-now-observed-reachable"
            if observed_state == "reachable"
            else "unavailability-reproduced"
        )
    else:
        comparison = "no-comparison-rule"
    conclusion = (
        "This is a bounded point-in-time access observation. It does not prove "
        "continuing availability, corpus completeness, or permission for bulk use."
    )
    return {"comparison": comparison, "conclusion": conclusion}


def capture_one(
    method: dict[str, Any],
    *,
    timeout_seconds: float,
    max_body_bytes: int,
    user_agent: str,
    host_limiter: HostLimiter,
) -> dict[str, Any]:
    started = utc_now()
    headers = request_headers(method, max_body_bytes, user_agent)
    request = urllib.request.Request(
        method["url"],
        headers=headers,
        method=method["request_method"],
    )
    status: int | None = None
    reason: str | None = None
    final_url = method["url"]
    response_headers: dict[str, str] = {}
    received_header_names: list[str] = []
    sensitive_header_names: list[str] = []
    body = b""
    truncated = False
    error: dict[str, str] | None = None
    limiter = host_limiter.for_url(method["url"])
    monotonic_start = time.monotonic()
    try:
        with limiter:
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=timeout_seconds,
                ) as response:
                    status = response.status
                    reason = str(response.reason) if response.reason else None
                    final_url = response.geturl()
                    (
                        response_headers,
                        received_header_names,
                        sensitive_header_names,
                    ) = safe_response_headers(response.headers)
                    if method["request_method"] == "GET":
                        fetched = response.read(max_body_bytes + 1)
                        truncated = len(fetched) > max_body_bytes
                        body = fetched[:max_body_bytes]
            except urllib.error.HTTPError as http_error:
                status = http_error.code
                reason = str(http_error.reason) if http_error.reason else None
                final_url = http_error.geturl()
                (
                    response_headers,
                    received_header_names,
                    sensitive_header_names,
                ) = safe_response_headers(http_error.headers)
                if method["request_method"] == "GET":
                    fetched = http_error.read(max_body_bytes + 1)
                    truncated = len(fetched) > max_body_bytes
                    body = fetched[:max_body_bytes]
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        ssl.SSLError,
        ConnectionError,
    ) as network_error:
        cause = getattr(network_error, "reason", None)
        error = {
            "type": type(network_error).__name__,
            "message": str(cause if cause is not None else network_error)[:500],
        }
    except Exception as unexpected:
        error = {
            "type": type(unexpected).__name__,
            "message": str(unexpected)[:500],
        }
    duration_ms = round((time.monotonic() - monotonic_start) * 1000)
    observed_at = isoformat(started)
    observed_state = classify_http_observation(
        status,
        error["type"] if error else None,
    )
    comparison = compare_with_research_claim(method, observed_state)
    request_record = {
        "method": method["request_method"],
        "url": method["url"],
        "headers": {key.lower(): value for key, value in headers.items()},
        "body": None,
        "scope": method["probe_scope"],
    }
    response_record: dict[str, Any] = {
        "observed_at": observed_at,
        "status": status,
        "reason": reason,
        "final_url": final_url,
        "duration_ms": duration_ms,
        "headers": response_headers,
        "received_header_names": received_header_names,
        "sensitive_header_names_present_but_not_stored": sensitive_header_names,
        "media_type": response_headers.get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
        or None,
        "body": {
            "captured_bytes": len(body),
            "capture_limit_bytes": max_body_bytes,
            "truncated": truncated,
            "sha256": sha256_bytes(body),
            "stored_path": "body.bin" if body else None,
            "hash_scope": "captured-prefix-only",
        },
        "schema_fingerprint": schema_fingerprint(
            body,
            response_headers,
            final_url,
            max_body_bytes,
        )
        if body
        else None,
        "error": error,
    }
    return {
        "method": method,
        "body": body,
        "request": request_record,
        "request_sha256": sha256_bytes(canonical_json_bytes(request_record)),
        "response": response_record,
        "observed_access_state": observed_state,
        "comparison": comparison,
    }


def keyword_present(text: str, patterns: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


def source_constraint_specs(
    source: dict[str, Any],
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_id = source["id"]
    fair_use = str(source.get("fair_use_rate_limit_robots", "")).strip()
    licence = str(source.get("licence_and_reuse", "")).strip()
    combined = f"{fair_use} {licence}".lower()
    specs: list[dict[str, Any]] = []

    if fair_use:
        explicit_fair_use = keyword_present(
            fair_use,
            (
                "fair-use",
                "fair use",
                "reasonable",
                "polite",
                "respectful",
                "bulk",
                "crawl",
                "scrape",
                "cache",
                "requests",
            ),
        )
        specs.append(
            {
                "kind": "fair-use",
                "trigger": fair_use,
                "effect": (
                    "The declared source-use conditions govern systematic "
                    "acquisition. They did not suppress this single bounded probe."
                ),
                "mitigation": (
                    "Use identified automation, immutable caching, bounded "
                    "requests, source-aware pacing and documented bulk routes."
                ),
                "owner": "UK Whole-Law OKF acquisition maintainer",
                "escalation_state": (
                    "mitigated" if explicit_fair_use else "recorded"
                ),
                "triggered_during_capture": explicit_fair_use,
            }
        )

    if licence:
        licence_review = keyword_present(
            licence,
            (
                "additional",
                "subject to",
                "third-party",
                "third party",
                "copyright",
                "subscription",
                "commercial",
                "requires",
                "restriction",
                "verify",
                "vary",
                "permission",
                "licence required",
            ),
        )
        specs.append(
            {
                "kind": "licence",
                "trigger": licence,
                "effect": (
                    "A successful public access probe does not establish rights "
                    "to redistribute complete source content."
                ),
                "mitigation": (
                    "Retain item-level rights and attribution; publish metadata, "
                    "hashes and source links when redistribution is not established."
                ),
                "owner": "Government rights and licensing lead",
                "escalation_state": (
                    "escalated" if licence_review else "recorded"
                ),
                "triggered_during_capture": licence_review,
            }
        )

    restricted_methods = [
        observation
        for observation in observations
        if observation["method"]["research_claim"]["status"]
        == "authenticated or restricted"
    ]
    if restricted_methods or keyword_present(
        combined,
        (
            "authenticated",
            "subscription",
            "credentials",
            "approved licensees",
        ),
    ):
        specs.append(
            {
                "kind": "authentication",
                "trigger": (
                    "The research or source terms identify authenticated, "
                    "subscription, licensed or credentialed access."
                ),
                "effect": (
                    "Restricted corpus content was not acquired. A reachable "
                    "public documentation page is not counted as corpus access."
                ),
                "mitigation": (
                    "Preserve adapter and access metadata; obtain explicit source "
                    "authority and credentials through an approved internal process."
                ),
                "owner": "Source relationship owner and government security lead",
                "escalation_state": "escalated",
                "triggered_during_capture": bool(restricted_methods),
            }
        )

    if keyword_present(
        fair_use,
        (
            "rate limit",
            "query caps",
            "requests per",
            "requests",
            "pacing",
            "filtered",
            "bulk",
            "crawl",
            "scrape",
            "reasonable",
            "polite",
            "respectful",
            "daily",
        ),
    ):
        specs.append(
            {
                "kind": "rate-limit",
                "trigger": fair_use,
                "effect": (
                    "Unpaced or repeated collection could exceed an explicit or "
                    "implicit source capacity limit."
                ),
                "mitigation": (
                    "One bounded request per route, one concurrent request per "
                    "host, immutable caching, and Retry-After preservation."
                ),
                "owner": "UK Whole-Law OKF acquisition maintainer",
                "escalation_state": (
                    "escalated"
                    if keyword_present(
                        fair_use,
                        ("requests per", "query caps", "authenticated"),
                    )
                    else "mitigated"
                ),
                "triggered_during_capture": True,
            }
        )

    if "robots" in fair_use.lower():
        specs.append(
            {
                "kind": "robots",
                "trigger": fair_use,
                "effect": (
                    "Robots and indexing conditions may constrain later crawling "
                    "or external indexing."
                ),
                "mitigation": (
                    "This run made only the registered point probe. Review the "
                    "current site robots policy before any crawl or bulk adapter run."
                ),
                "owner": "UK Whole-Law OKF acquisition maintainer",
                "escalation_state": (
                    "escalated"
                    if "no external indexing" in fair_use.lower()
                    else "mitigated"
                ),
                "triggered_during_capture": True,
            }
        )

    if keyword_present(
        combined,
        (
            "personal",
            "privacy",
            "confidential",
            "sensitive",
            "redact",
            "person-level",
        ),
    ):
        specs.append(
            {
                "kind": "privacy",
                "trigger": (
                    f"Source-use note: {fair_use} Rights note: {licence}"
                ).strip(),
                "effect": (
                    "Public availability does not remove data-protection, "
                    "redaction, retention or inference risks."
                ),
                "mitigation": (
                    "This access test stores only a bounded public response; "
                    "exclude personal case inputs from the static OKF and complete "
                    "a data-protection review before record-level ingestion."
                ),
                "owner": "Government data protection lead",
                "escalation_state": "escalated",
                "triggered_during_capture": True,
            }
        )

    failed = [
        observation
        for observation in observations
        if observation["observed_access_state"] != "reachable"
    ]
    if failed:
        failures = ", ".join(
            f"{item['method']['method_id']}={item['observed_access_state']}"
            for item in failed
        )
        previously_verified = any(
            item["method"]["research_claim"]["status"] == "verified working"
            for item in failed
        )
        specs.append(
            {
                "kind": "availability",
                "trigger": f"Bounded access observation: {failures}.",
                "effect": (
                    "The recorded route could not be confirmed as publicly "
                    "reachable in this attempt."
                ),
                "mitigation": (
                    "Keep the immutable failure evidence, use declared alternate "
                    "routes, and schedule a fresh attempt without rewriting history."
                ),
                "owner": "UK Whole-Law OKF source monitoring owner",
                "escalation_state": (
                    "escalated" if previously_verified else "recorded"
                ),
                "triggered_during_capture": True,
            }
        )
    return specs


def build_constraint_ledger(
    source_register: dict[str, Any],
    observations: list[dict[str, Any]],
    generated_at: str,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        by_source[observation["method"]["source_id"]].append(observation)
    constraints: list[dict[str, Any]] = []
    refs: dict[str, list[str]] = defaultdict(list)
    for source in source_register["records"]:
        source_id = source["id"]
        for spec in source_constraint_specs(
            source,
            by_source.get(source_id, []),
        ):
            constraint_id = f"CON-{source_id}-{spec['kind'].upper()}"
            constraint = {
                "id": constraint_id,
                "source_id": source_id,
                "kind": spec["kind"],
                "trigger": spec["trigger"],
                "effect": spec["effect"],
                "mitigation": spec["mitigation"],
                "owner": spec["owner"],
                "escalation_state": spec["escalation_state"],
                "triggered_during_capture": spec["triggered_during_capture"],
                "evidence_run_id": run_id,
            }
            constraints.append(constraint)
            refs[source_id].append(constraint_id)
    constraints.sort(key=lambda row: row["id"])
    return (
        {
            "schema": CONSTRAINT_SCHEMA,
            "generated_at": generated_at,
            "evidence_run_id": run_id,
            "policy": (
                "Constraints remain visible and internally escalatable. The "
                "bounded public evidence probe was not silently omitted because "
                "of fair-use or licensing uncertainty; protected content was not "
                "accessed and no authentication was bypassed."
            ),
            "constraints": constraints,
            "counts": {
                "total": len(constraints),
                "by_kind": dict(
                    sorted(
                        Counter(
                            constraint["kind"] for constraint in constraints
                        ).items()
                    )
                ),
                "by_escalation_state": dict(
                    sorted(
                        Counter(
                            constraint["escalation_state"]
                            for constraint in constraints
                        ).items()
                    )
                ),
                "triggered_during_capture": sum(
                    bool(constraint["triggered_during_capture"])
                    for constraint in constraints
                ),
            },
        },
        refs,
    )


def observation_projection(
    capture: dict[str, Any],
    run_id: str,
    envelope_relpath: str,
) -> dict[str, Any]:
    method = capture["method"]
    response = capture["response"]
    return {
        "method_id": method["method_id"],
        "source_id": method["source_id"],
        "source_title": method["source_title"],
        "owning_institution": method["owning_institution"],
        "kind": method["kind"],
        "url": method["url"],
        "research_claim": method["research_claim"],
        "request_method": method["request_method"],
        "probe_scope": method["probe_scope"],
        "observed_at": response["observed_at"],
        "http_status": response["status"],
        "final_url": response["final_url"],
        "media_type": response["media_type"],
        "observed_access_state": capture["observed_access_state"],
        "comparison": capture["comparison"]["comparison"],
        "conclusion": capture["comparison"]["conclusion"],
        "captured_bytes": response["body"]["captured_bytes"],
        "body_sha256": response["body"]["sha256"],
        "schema_fingerprint_sha256": (
            response["schema_fingerprint"]["fingerprint_sha256"]
            if response["schema_fingerprint"]
            else None
        ),
        "error": response["error"],
        "evidence_run_id": run_id,
        "evidence_envelope": envelope_relpath,
    }


def build_comparison(
    observations: list[dict[str, Any]],
    generated_at: str,
    run_id: str,
) -> dict[str, Any]:
    return {
        "schema": COMPARISON_SCHEMA,
        "generated_at": generated_at,
        "evidence_run_id": run_id,
        "interpretation": (
            "Research claims are retained verbatim. Observations are bounded "
            "point-in-time probes and do not establish continuing availability, "
            "complete corpus access, or bulk-reuse permission."
        ),
        "counts": {
            "access_methods": len(observations),
            "research_claim_status": dict(
                sorted(
                    Counter(
                        row["research_claim"]["status"] for row in observations
                    ).items()
                )
            ),
            "observed_access_state": dict(
                sorted(
                    Counter(
                        row["observed_access_state"] for row in observations
                    ).items()
                )
            ),
            "comparison": dict(
                sorted(
                    Counter(row["comparison"] for row in observations).items()
                )
            ),
        },
        "changes_requiring_review": [
            {
                "method_id": row["method_id"],
                "source_id": row["source_id"],
                "url": row["url"],
                "research_status": row["research_claim"]["status"],
                "observed_access_state": row["observed_access_state"],
                "comparison": row["comparison"],
                "http_status": row["http_status"],
                "error": row["error"],
            }
            for row in observations
            if row["comparison"]
            not in {
                "claim-confirmed",
                "restriction-confirmed",
                "restriction-not-disproved",
                "unavailability-reproduced",
            }
        ],
    }


def run_integrity(run_dir: Path) -> dict[str, Any]:
    entries = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "integrity.json":
            continue
        entries.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema": "okf-source-access-integrity.v1",
        "algorithm": "sha256",
        "files": entries,
        "file_count": len(entries),
        "total_bytes": sum(entry["bytes"] for entry in entries),
    }


def capture_run(args: argparse.Namespace) -> Path:
    source_register = load_json(REGISTER)
    methods = enumerate_access_methods(source_register)
    selected = set(args.only or [])
    if selected:
        unknown = selected - {method["method_id"] for method in methods}
        if unknown:
            raise ValueError(
                f"Unknown --only method IDs: {', '.join(sorted(unknown))}"
            )
        methods = [
            method for method in methods if method["method_id"] in selected
        ]
    if not methods:
        raise ValueError("No access methods selected")
    run_id = args.run_id or make_run_id()
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(
            "run ID must match YYYYMMDDTHHMMSSZ- followed by eight hex digits"
        )
    final_dir = EVIDENCE_ROOT / run_id
    partial_dir = EVIDENCE_ROOT / f".partial-{run_id}"
    if final_dir.exists() or partial_dir.exists():
        raise FileExistsError(
            f"Immutable evidence attempt already exists: {run_id}"
        )
    partial_dir.mkdir(parents=True, exist_ok=False)
    started_at = isoformat(utc_now())
    host_limiter = HostLimiter(args.per_host)
    captures: list[dict[str, Any]] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers
        ) as executor:
            future_to_method = {
                executor.submit(
                    capture_one,
                    method,
                    timeout_seconds=args.timeout,
                    max_body_bytes=args.max_body_bytes,
                    user_agent=args.user_agent,
                    host_limiter=host_limiter,
                ): method
                for method in methods
            }
            completed = 0
            for future in concurrent.futures.as_completed(future_to_method):
                capture = future.result()
                captures.append(capture)
                completed += 1
                response = capture["response"]
                print(
                    f"[{completed:03d}/{len(methods):03d}] "
                    f"{capture['method']['method_id']} "
                    f"{capture['observed_access_state']} "
                    f"{response['status'] or '-'}",
                    flush=True,
                )
        captures.sort(key=lambda item: item["method"]["method_id"])
        completed_at = isoformat(utc_now())
        constraint_ledger, constraint_refs = build_constraint_ledger(
            source_register,
            captures,
            completed_at,
            run_id,
        )
        observation_rows: list[dict[str, Any]] = []
        for capture in captures:
            method = capture["method"]
            method_dir = (
                partial_dir / "methods" / method["method_id"]
            )
            envelope_relpath = (
                Path("methods")
                / method["method_id"]
                / "envelope.json"
            ).as_posix()
            envelope = {
                "schema": EVIDENCE_SCHEMA,
                "attempt_id": (
                    f"{run_id}/{method['method_id']}"
                ),
                "run_id": run_id,
                "method_id": method["method_id"],
                "source": {
                    "id": method["source_id"],
                    "title": method["source_title"],
                    "owning_institution": method["owning_institution"],
                    "authority_classes": method["authority_classes"],
                    "source_classes": method["source_classes"],
                },
                "access_method": {
                    "kind": method["kind"],
                    "url": method["url"],
                },
                "research_claim": method["research_claim"],
                "request": capture["request"],
                "request_sha256": capture["request_sha256"],
                "response": capture["response"],
                "access_assessment": {
                    "observed_access_state": capture[
                        "observed_access_state"
                    ],
                    **capture["comparison"],
                },
                "constraint_refs": constraint_refs[method["source_id"]],
                "tool": {
                    "name": TOOL_NAME,
                    "version": TOOL_VERSION,
                    "python": sys.version.split()[0],
                    "policy": (
                        "single registered route probe; no credentials, cookies, "
                        "form submission, crawling or authentication bypass"
                    ),
                },
            }
            body = capture["body"]
            if body:
                write_new_bytes(method_dir / "body.bin", body)
            write_new_json(method_dir / "envelope.json", envelope)
            observation_rows.append(
                observation_projection(
                    capture,
                    run_id,
                    envelope_relpath,
                )
            )
        observations = {
            "schema": OBSERVATION_SCHEMA,
            "generated_at": completed_at,
            "evidence_run_id": run_id,
            "source_register": str(REGISTER.relative_to(ROOT)),
            "source_register_sha256": sha256_file(REGISTER),
            "records": observation_rows,
        }
        comparison = build_comparison(
            observation_rows,
            completed_at,
            run_id,
        )
        source_count = len(
            {row["source_id"] for row in observation_rows}
        )
        run_manifest = {
            "schema": RUN_SCHEMA,
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "tool": {
                "name": TOOL_NAME,
                "version": TOOL_VERSION,
                "python": sys.version.split()[0],
            },
            "policy": {
                "workers": args.workers,
                "per_host_concurrency": args.per_host,
                "timeout_seconds": args.timeout,
                "max_body_bytes": args.max_body_bytes,
                "user_agent": args.user_agent,
                "restricted_route_method": "HEAD",
                "other_route_method": "GET",
                "credentials_used": False,
                "authentication_bypass_attempted": False,
                "cookies_sent": False,
                "form_submissions": False,
                "pagination_or_crawling": False,
            },
            "coverage": {
                "source_records_in_register": len(
                    source_register["records"]
                ),
                "access_methods_in_register": len(
                    enumerate_access_methods(source_register)
                ),
                "source_records_attempted": source_count,
                "access_methods_attempted": len(observation_rows),
                "complete_register_attempt": (
                    not selected
                    and source_count == len(source_register["records"])
                    and len(observation_rows)
                    == len(enumerate_access_methods(source_register))
                ),
            },
            "result_counts": comparison["counts"],
            "files": {
                "observations": "observations.json",
                "comparison": "comparison.json",
                "constraint_ledger": "source-constraint-ledger.json",
                "integrity": "integrity.json",
            },
        }
        write_new_json(partial_dir / "observations.json", observations)
        write_new_json(partial_dir / "comparison.json", comparison)
        write_new_json(
            partial_dir / "source-constraint-ledger.json",
            constraint_ledger,
        )
        write_new_json(partial_dir / "manifest.json", run_manifest)
        write_new_json(
            partial_dir / "complete.json",
            {
                "complete": True,
                "completed_at": completed_at,
                "run_id": run_id,
            },
        )
        write_new_json(partial_dir / "integrity.json", run_integrity(partial_dir))
        EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
        os.replace(partial_dir, final_dir)
    except Exception:
        print(
            f"Partial evidence retained for diagnosis at {partial_dir}",
            file=sys.stderr,
        )
        raise
    validate_run(final_dir, require_full_register=not selected)
    archive_path, receipt_path = archive_paths(run_id)
    create_archive(
        run_id=run_id,
        files=directory_snapshot(final_dir),
        archive_path=archive_path,
        receipt_path=receipt_path,
        archived_at=isoformat(utc_now()),
        source_snapshot={
            "kind": "completed-run-directory",
            "tree_path": str(final_dir.relative_to(ROOT)),
            "dependency_after_archiving": False,
        },
    )
    if not args.no_publish:
        if selected:
            raise ValueError(
                "A partial capture cannot become the current publication "
                "projection; use --no-publish"
            )
        publish_archive(archive_path, receipt_path)
    # The verified archive is the immutable evidence object.  Retaining the
    # unpacked copy in Git would duplicate untrusted downloaded content and can
    # trigger repository protection.  Partial directories survive failures,
    # while successful raw directories are removed only after sealing.
    shutil.rmtree(final_dir)
    return archive_path


def resolve_archive(run_argument: str) -> tuple[Path, Path]:
    if run_argument != "latest":
        if not RUN_ID_RE.fullmatch(run_argument):
            raise ValueError(f"Invalid run ID: {run_argument}")
        archive_path, receipt_path = archive_paths(run_argument)
        if not archive_path.is_file() or not receipt_path.is_file():
            raise FileNotFoundError(
                f"Sealed evidence archive not found: {run_argument}"
            )
        return archive_path, receipt_path
    receipts = sorted(
        path
        for path in RECEIPT_ROOT.glob("*.json")
        if RUN_ID_RE.fullmatch(path.stem)
    )
    if not receipts:
        raise FileNotFoundError("No sealed source-access archive found")
    run_id = receipts[-1].stem
    return archive_paths(run_id)


def validate_constraint_ledger(
    ledger: dict[str, Any],
    source_ids: set[str],
) -> None:
    if ledger.get("schema") != CONSTRAINT_SCHEMA:
        raise ValueError("Constraint ledger schema is not v1")
    identifiers: set[str] = set()
    for constraint in ledger.get("constraints", []):
        required = {
            "id",
            "source_id",
            "kind",
            "trigger",
            "effect",
            "mitigation",
            "owner",
            "escalation_state",
        }
        missing = required - constraint.keys()
        if missing:
            raise ValueError(
                f"Constraint missing fields {sorted(missing)}: {constraint}"
            )
        if constraint["id"] in identifiers:
            raise ValueError(f"Duplicate constraint ID: {constraint['id']}")
        identifiers.add(constraint["id"])
        if constraint["source_id"] not in source_ids:
            raise ValueError(
                f"Unknown constraint source: {constraint['source_id']}"
            )
        if constraint["kind"] not in CONSTRAINT_KINDS:
            raise ValueError(
                f"Unknown constraint kind: {constraint['kind']}"
            )
        if constraint["escalation_state"] not in {
            "recorded",
            "mitigated",
            "escalated",
            "resolved",
            "accepted-prototype-risk",
        }:
            raise ValueError(
                "Invalid constraint escalation state: "
                f"{constraint['escalation_state']}"
            )


def validate_run(
    run_dir: Path,
    *,
    require_full_register: bool,
) -> dict[str, Any]:
    manifest = load_json(run_dir / "manifest.json")
    observations = load_json(run_dir / "observations.json")
    comparison = load_json(run_dir / "comparison.json")
    constraints = load_json(run_dir / "source-constraint-ledger.json")
    complete = load_json(run_dir / "complete.json")
    integrity = load_json(run_dir / "integrity.json")
    source_register = load_json(REGISTER)
    expected_methods = enumerate_access_methods(source_register)
    expected_by_id = {
        method["method_id"]: method for method in expected_methods
    }
    expected_ids = {method["method_id"] for method in expected_methods}
    source_ids = {source["id"] for source in source_register["records"]}
    if manifest.get("schema") != RUN_SCHEMA:
        raise ValueError("Unexpected source-access run schema")
    if manifest.get("run_id") != run_dir.name:
        raise ValueError("Run manifest ID does not match directory")
    if not complete.get("complete") or complete.get("run_id") != run_dir.name:
        raise ValueError("Evidence run is not marked complete")
    if observations.get("schema") != OBSERVATION_SCHEMA:
        raise ValueError("Unexpected observations schema")
    if observations.get("source_register_sha256") != sha256_file(REGISTER):
        raise ValueError(
            "Evidence run source-register hash does not match immutable research"
        )
    if comparison.get("schema") != COMPARISON_SCHEMA:
        raise ValueError("Unexpected comparison schema")
    rows = observations.get("records", [])
    method_ids = [row.get("method_id") for row in rows]
    if len(method_ids) != len(set(method_ids)):
        raise ValueError("Duplicate observed method IDs")
    if not set(method_ids) <= expected_ids:
        raise ValueError("Observed method IDs are not in source register")
    if require_full_register and set(method_ids) != expected_ids:
        missing = sorted(expected_ids - set(method_ids))
        raise ValueError(
            f"Evidence run does not cover complete register: {missing}"
        )
    if require_full_register:
        if len(rows) != 108 or len({row["source_id"] for row in rows}) != 72:
            raise ValueError(
                "Full Whole-Law access evidence must cover 72 sources/108 methods"
            )
    if manifest["coverage"]["access_methods_attempted"] != len(rows):
        raise ValueError("Run manifest access-method count is inconsistent")
    if manifest["coverage"]["source_records_attempted"] != len(
        {row["source_id"] for row in rows}
    ):
        raise ValueError("Run manifest source-record count is inconsistent")
    constraint_ids_by_source: dict[str, set[str]] = defaultdict(set)
    constraint_kinds_by_source: dict[str, set[str]] = defaultdict(set)
    for constraint in constraints.get("constraints", []):
        constraint_ids_by_source[constraint["source_id"]].add(
            constraint["id"]
        )
        constraint_kinds_by_source[constraint["source_id"]].add(
            constraint["kind"]
        )
    for source_id in source_ids:
        required_source_constraints = {"fair-use", "licence"}
        if not required_source_constraints <= constraint_kinds_by_source[
            source_id
        ]:
            raise ValueError(
                f"{source_id} lacks fair-use/licence constraint evidence"
            )
    for row in rows:
        expected_method = expected_by_id[row["method_id"]]
        if row["url"] != expected_method["url"]:
            raise ValueError(
                f"Observed URL changed from research: {row['method_id']}"
            )
        if row["research_claim"] != expected_method["research_claim"]:
            raise ValueError(
                f"Research claim was not preserved: {row['method_id']}"
            )
        envelope_path = run_dir / row["evidence_envelope"]
        if not envelope_path.is_file():
            raise ValueError(
                f"Missing envelope for {row['method_id']}: {envelope_path}"
            )
        envelope = load_json(envelope_path)
        if envelope.get("schema") != EVIDENCE_SCHEMA:
            raise ValueError(
                f"Unexpected envelope schema: {envelope_path}"
            )
        if envelope.get("method_id") != row["method_id"]:
            raise ValueError(
                f"Envelope method ID mismatch: {envelope_path}"
            )
        if envelope["access_method"]["url"] != expected_method["url"]:
            raise ValueError(
                f"Envelope URL changed from research: {envelope_path}"
            )
        if envelope["research_claim"] != expected_method["research_claim"]:
            raise ValueError(
                f"Envelope research claim was not preserved: {envelope_path}"
            )
        if set(envelope["constraint_refs"]) != constraint_ids_by_source[
            row["source_id"]
        ]:
            raise ValueError(
                f"Envelope constraint references are incomplete: {envelope_path}"
            )
        request_hash = sha256_bytes(
            canonical_json_bytes(envelope["request"])
        )
        if request_hash != envelope["request_sha256"]:
            raise ValueError(
                f"Request hash mismatch: {envelope_path}"
            )
        if {"authorization", "cookie"} & set(envelope["request"]["headers"]):
            raise ValueError(
                f"Credential-bearing request header found: {envelope_path}"
            )
        body_record = envelope["response"]["body"]
        body_path_value = body_record["stored_path"]
        if body_path_value:
            body_path = envelope_path.parent / body_path_value
            if not body_path.is_file():
                raise ValueError(f"Missing body evidence: {body_path}")
            if body_path.stat().st_size != body_record["captured_bytes"]:
                raise ValueError(f"Body byte count mismatch: {body_path}")
            if sha256_file(body_path) != body_record["sha256"]:
                raise ValueError(f"Body hash mismatch: {body_path}")
            expected_fingerprint = schema_fingerprint(
                body_path.read_bytes(),
                envelope["response"]["headers"],
                envelope["response"]["final_url"],
                body_record["capture_limit_bytes"],
            )
            if (
                expected_fingerprint
                != envelope["response"]["schema_fingerprint"]
            ):
                raise ValueError(
                    f"Body schema fingerprint mismatch: {body_path}"
                )
        elif body_record["captured_bytes"] != 0:
            publication_storage = envelope.get("publication_storage", {})
            receipt_value = publication_storage.get("receipt")
            receipt_path = (
                (envelope_path.parent / receipt_value).resolve()
                if isinstance(receipt_value, str)
                else None
            )
            if (
                publication_storage.get("disposition")
                != "body-omitted-from-git"
                or publication_storage.get("source_digest_retained") is not True
                or receipt_path is None
                or not receipt_path.is_relative_to(run_dir.resolve())
                or not receipt_path.is_file()
            ):
                raise ValueError(
                    f"Envelope has bytes without a stored body or governed "
                    f"publication-redaction receipt: {envelope_path}"
                )
        if envelope["request"]["scope"] == (
            "public-metadata-only-no-authentication"
        ):
            if envelope["request"]["method"] != "HEAD":
                raise ValueError(
                    f"Restricted method did not use HEAD: {envelope_path}"
                )
    validate_constraint_ledger(constraints, source_ids)
    listed_integrity = {
        entry["path"]: entry for entry in integrity.get("files", [])
    }
    actual_paths = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path.name != "integrity.json"
    }
    if set(listed_integrity) != actual_paths:
        raise ValueError("Integrity file list does not match evidence files")
    for relative, entry in listed_integrity.items():
        path = run_dir / relative
        if path.stat().st_size != entry["bytes"]:
            raise ValueError(f"Integrity byte count mismatch: {relative}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Integrity hash mismatch: {relative}")
    if integrity["file_count"] != len(actual_paths):
        raise ValueError("Integrity file count is inconsistent")
    if integrity["total_bytes"] != sum(
        (run_dir / relative).stat().st_size for relative in actual_paths
    ):
        raise ValueError("Integrity total byte count is inconsistent")
    return {
        "run_id": run_dir.name,
        "source_records": len({row["source_id"] for row in rows}),
        "access_methods": len(rows),
        "observed_access_state": comparison["counts"][
            "observed_access_state"
        ],
        "comparison": comparison["counts"]["comparison"],
        "constraints": constraints["counts"],
        "integrity_files": integrity["file_count"],
        "integrity_bytes": integrity["total_bytes"],
    }


def constraint_counts(constraints: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(constraints),
        "by_kind": dict(
            sorted(Counter(row["kind"] for row in constraints).items())
        ),
        "by_escalation_state": dict(
            sorted(
                Counter(
                    row["escalation_state"] for row in constraints
                ).items()
            )
        ),
        "triggered_during_capture": sum(
            bool(row.get("triggered_during_capture"))
            for row in constraints
        ),
    }


def build_publication_constraints(
    original: dict[str, Any],
    *,
    archive_receipt: dict[str, Any],
    projection_id: str,
) -> dict[str, Any]:
    """Add a projection constraint without changing the original run ledger."""

    constraints = json.loads(json.dumps(original["constraints"]))
    if archive_receipt.get("publication_trigger") is not None:
        constraints.append(
            {
                "id": "CON-SRC002-PUBLICATION-CONTENT-SCANNING",
                "source_id": "SRC002",
                "kind": "hosting",
                "trigger": (
                    "A bounded official CLML response contains public "
                    "identifier values whose lexical form is misclassified by "
                    "GitHub push protection as a credential."
                ),
                "effect": (
                    "The raw response prefix cannot be committed as plaintext. "
                    "The original attempt remains complete in its sealed "
                    "archive; only a metadata projection is published."
                ),
                "mitigation": (
                    "Publish a deterministic tar.xz archive, retain original "
                    "body and integrity digests, verify bounded extraction, "
                    "and publish a value-free receipt. Do not bypass repository "
                    "protection."
                ),
                "owner": "UK Whole-Law OKF publication maintainer",
                "escalation_state": "mitigated",
                "triggered_during_capture": False,
                "evidence_run_id": archive_receipt["run_id"],
                "projection_id": projection_id,
            }
        )
    return {
        "schema": CONSTRAINT_SCHEMA,
        "generated_at": archive_receipt["archived_at"],
        "evidence_run_id": archive_receipt["run_id"],
        "projection": {
            "id": projection_id,
            "kind": "replaceable-sanitized-publication-projection",
            "source_ledger_sha256": sha256_bytes(
                render_json(original).encode("utf-8")
            ),
            "source_archive_sha256": archive_receipt["archive"]["sha256"],
        },
        "policy": original["policy"],
        "constraints": constraints,
        "counts": constraint_counts(constraints),
    }


def publication_redaction_receipt(
    *,
    archive_receipt: dict[str, Any],
    projection_id: str,
) -> dict[str, Any]:
    trigger = archive_receipt.get("publication_trigger")
    entries: list[dict[str, Any]] = []
    if trigger is not None:
        payload = trigger["payload"]
        entries.append(
            {
                "method_id": "SRC002-A01",
                "source_id": "SRC002",
                "original_path": payload["path"],
                "original_bytes": payload["bytes"],
                "original_sha256": payload["sha256"],
                "detector": trigger["detector"],
                "classification": trigger["classification"],
                "credential_shaped_public_identifier_count": payload[
                    "credential_shaped_public_identifier_count"
                ],
                "values_recorded": False,
                "action": "omit-plaintext-body-from-publication-projection",
                "recovery": (
                    "Recover only from the sealed archive using the bounded "
                    "verifier and explicit extraction acknowledgement."
                ),
            }
        )
    return {
        "schema": REDACTION_SCHEMA,
        "generated_at": archive_receipt["archived_at"],
        "projection_id": projection_id,
        "source_evidence": {
            "run_id": archive_receipt["run_id"],
            "archive_path": archive_receipt["archive"]["path"],
            "archive_sha256": archive_receipt["archive"]["sha256"],
            "archive_tree_sha256": archive_receipt["archive"]["tree_sha256"],
            "original_integrity_sha256": archive_receipt[
                "original_integrity"
            ]["sha256"],
        },
        "policy": (
            "Downloaded content remains untrusted even when obtained from an "
            "official public source. Detector-matched values are not repeated "
            "in Git metadata or documentation."
        ),
        "entries": entries,
        "assertions": {
            "immutable_original_mutated": False,
            "projection_is_immutable_original": False,
            "original_recoverable_byte_for_byte": True,
        },
    }


def publish_material(
    *,
    archive_receipt: dict[str, Any],
    validation: dict[str, Any],
    manifest: dict[str, Any],
    observations: dict[str, Any],
    comparison: dict[str, Any],
    original_constraints: dict[str, Any],
) -> None:
    archive = archive_receipt["archive"]
    projection_id = (
        f"pub-{archive_receipt['run_id']}-{archive['sha256'][:12]}"
    )
    constraints = build_publication_constraints(
        original_constraints,
        archive_receipt=archive_receipt,
        projection_id=projection_id,
    )
    redactions = publication_redaction_receipt(
        archive_receipt=archive_receipt,
        projection_id=projection_id,
    )
    projected_resources = {
        "access-methods.json": observations,
        "observed-access-comparison.json": comparison,
        "source-constraint-ledger.json": constraints,
        "publication-redactions.json": redactions,
    }
    projection_manifest = {
        "schema": PROJECTION_SCHEMA,
        "projection_id": projection_id,
        "generated_at": archive_receipt["archived_at"],
        "status": "sanitized-publication-projection",
        "replaceable": True,
        "immutable_original": False,
        "source_evidence": {
            "run_id": archive_receipt["run_id"],
            "archive_path": archive["path"],
            "archive_receipt_path": (
                "evidence/source-acquisitions/whole-law-access/"
                f"archive-receipts/{archive_receipt['run_id']}.json"
            ),
            "archive_sha256": archive["sha256"],
            "archive_tree_sha256": archive["tree_sha256"],
            "original_integrity_sha256": archive_receipt[
                "original_integrity"
            ]["sha256"],
        },
        "transformation": {
            "kind": "metadata-only-publication",
            "included": [
                "access-method observations",
                "research-to-observation comparison",
                "constraint ledger plus publication constraint",
                "archive and redaction receipts",
            ],
            "omitted": [
                {
                    "kind": "downloaded-response-bodies",
                    "reason": (
                        "Untrusted downloaded content is available only in "
                        "the integrity-bound archive."
                    ),
                }
            ],
            "changes_original_run": False,
        },
        "resources": {
            name: {
                "bytes": len(render_json(value).encode("utf-8")),
                "sha256": sha256_bytes(render_json(value).encode("utf-8")),
            }
            for name, value in sorted(projected_resources.items())
        },
    }
    evidence_reference = {
        "schema": "okf-source-access-evidence-reference.v2",
        "generated_at": archive_receipt["archived_at"],
        "evidence_run_id": archive_receipt["run_id"],
        "evidence_archive_path": archive["path"],
        "evidence_archive_sha256": archive["sha256"],
        "evidence_archive_tree_sha256": archive["tree_sha256"],
        "archive_receipt_path": projection_manifest["source_evidence"][
            "archive_receipt_path"
        ],
        "original_integrity_sha256": archive_receipt[
            "original_integrity"
        ]["sha256"],
        "source_register_sha256": observations["source_register_sha256"],
        "tool": manifest["tool"],
        "coverage": manifest["coverage"],
        "validation": validation,
        "publication_projection": {
            "id": projection_id,
            "kind": "replaceable-sanitized-publication-projection",
            "manifest": "publication-projection.json",
            "redaction_receipt": "publication-redactions.json",
            "is_immutable_original": False,
        },
    }
    summary = {
        "schema": "okf-source-access-summary.v1",
        "generated_at": archive_receipt["archived_at"],
        "evidence_run_id": archive_receipt["run_id"],
        "publication_projection_id": projection_id,
        "coverage": manifest["coverage"],
        "result_counts": manifest["result_counts"],
        "constraints": constraints["counts"],
        "immutable_evidence": evidence_reference,
        "limitations": [
            "A successful probe proves only point-in-time route reachability.",
            "No observation proves corpus completeness or continuing availability.",
            "Restricted routes received HEAD metadata probes only; no authentication was attempted.",
            "Stored body hashes cover the bounded captured prefix, not the complete remote representation when truncated.",
            "Rights and fair-use constraints remain source- and item-specific and are escalated in the constraint ledger.",
            "The current files are a replaceable metadata projection, not the immutable original acquisition attempt.",
            "Original response prefixes require explicit, bounded extraction from the sealed archive.",
        ],
    }
    review_markdown = render_access_review(
        manifest,
        observations,
        comparison,
        constraints,
        evidence_reference,
    )
    projections = {
        "current/access-methods.json": observations,
        "current/observed-access-comparison.json": comparison,
        "current/source-constraint-ledger.json": constraints,
        "current/publication-projection.json": projection_manifest,
        "current/publication-redactions.json": redactions,
        "current/evidence-reference.json": evidence_reference,
        "current/source-access-summary.json": summary,
    }
    for base in (AUTHORING, BUNDLE):
        for relative, value in projections.items():
            write_projection_json(base / relative, value)
        write_projection_text(
            base / "current" / "source-access-review.md",
            review_markdown,
        )
    print(
        f"Published sanitized access projection {projection_id} from sealed "
        f"evidence {archive_receipt['run_id']}",
        flush=True,
    )


def publish_archive(archive_path: Path, receipt_path: Path) -> None:
    archive_validation, files = validate_archive(
        archive_path,
        receipt_path,
    )
    archive_receipt = load_json(receipt_path)
    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    observations = json.loads(files["observations.json"].decode("utf-8"))
    comparison = json.loads(files["comparison.json"].decode("utf-8"))
    constraints = json.loads(
        files["source-constraint-ledger.json"].decode("utf-8")
    )
    source_register = load_json(REGISTER)
    source_ids = {row["id"] for row in source_register["records"]}
    validate_constraint_ledger(constraints, source_ids)
    if manifest["run_id"] != archive_validation["run_id"]:
        raise ValueError("Archived manifest run ID is inconsistent")
    if len(observations.get("records", [])) != 108:
        raise ValueError("Archived observations do not cover 108 methods")
    validation = {
        **archive_validation,
        "source_records": len(
            {row["source_id"] for row in observations["records"]}
        ),
        "access_methods": len(observations["records"]),
        "observed_access_state": comparison["counts"][
            "observed_access_state"
        ],
        "comparison": comparison["counts"]["comparison"],
        "constraints": constraints["counts"],
    }
    publish_material(
        archive_receipt=archive_receipt,
        validation=validation,
        manifest=manifest,
        observations=observations,
        comparison=comparison,
        original_constraints=constraints,
    )


def markdown_cell(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", r"\|").replace("\n", " ")


def render_access_review(
    manifest: dict[str, Any],
    observations: dict[str, Any],
    comparison: dict[str, Any],
    constraints: dict[str, Any],
    evidence_reference: dict[str, Any],
) -> str:
    rows = observations["records"]
    result_counts = manifest["result_counts"]
    not_reproduced = [
        row
        for row in rows
        if row["research_claim"]["status"] == "verified working"
        and row["observed_access_state"] != "reachable"
    ]
    newly_reachable = [
        row
        for row in rows
        if row["comparison"] == "route-now-observed-reachable"
    ]
    restricted_surfaces = [
        row
        for row in rows
        if row["comparison"]
        == "public-surface-reachable-restriction-not-bypassed"
    ]
    lines = [
        "---",
        'type: "Source Access Review"',
        'title: "Whole-Law source-access review — 25 July 2026"',
        (
            'description: "Dated comparison of 108 researched access routes '
            'with bounded public observations."'
        ),
        (
            "generated: "
            + json.dumps(
                {
                    "at": manifest["completed_at"],
                    "by": "process:whole-law-source-access",
                },
                sort_keys=True,
            )
        ),
        'status: "stable"',
        (
            "sources: "
            + json.dumps(
                [
                    {
                        "id": "immutable-access-evidence",
                        "resource": "evidence-reference.json",
                        "title": f"Access evidence {manifest['run_id']}",
                    }
                ],
                sort_keys=True,
            )
        ),
        'tags: ["access", "constraints", "evidence", "whole-law"]',
        "---",
        "",
        "# Whole-Law source-access review — 25 July 2026",
        "",
        f"Evidence run: `{manifest['run_id']}`.",
        "",
        "This report compares the immutable research claims with a separate "
        "bounded observation made on 25 July 2026. It does not rewrite the "
        "research package.",
        "",
        "## Coverage",
        "",
        "| Measure | Count |",
        "| --- | ---: |",
        (
            "| Source records attempted | "
            f"{manifest['coverage']['source_records_attempted']} / "
            f"{manifest['coverage']['source_records_in_register']} |"
        ),
        (
            "| Access methods attempted | "
            f"{manifest['coverage']['access_methods_attempted']} / "
            f"{manifest['coverage']['access_methods_in_register']} |"
        ),
        f"| Reachable | {result_counts['observed_access_state'].get('reachable', 0)} |",
        f"| Restricted response | {result_counts['observed_access_state'].get('restricted', 0)} |",
        f"| Unavailable response | {result_counts['observed_access_state'].get('unavailable', 0)} |",
        f"| Network error | {result_counts['observed_access_state'].get('network-error', 0)} |",
        "",
        "Each public route received one bounded request. The three routes "
        "described as authenticated or restricted received `HEAD` only. No "
        "credentials, cookies, forms, pagination, crawl or authentication "
        "bypass were used.",
        "",
        "## Previously verified routes not reproduced",
        "",
        (
            f"{len(not_reproduced)} of the 97 routes previously labelled "
            "`verified working` did not return a publicly reachable response "
            "to this tool. A 403 may reflect automated-client policy rather "
            "than general service unavailability; a 404 may indicate a moved "
            "route. Every result therefore remains an observation, not a "
            "universal availability claim."
        ),
        "",
        "| Method | Source | HTTP | Observation | URL |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for row in not_reproduced:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(value)
                for value in (
                    row["method_id"],
                    row["source_id"],
                    row["http_status"],
                    row["observed_access_state"],
                    row["url"],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Newly tested or recovered routes",
            "",
            (
                f"{len(newly_reachable)} routes described as untested or "
                "unavailable in the research package returned a reachable "
                "response in this run."
            ),
            "",
            "| Method | Prior research state | HTTP | URL |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for row in newly_reachable:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(value)
                for value in (
                    row["method_id"],
                    row["research_claim"]["status"],
                    row["http_status"],
                    row["url"],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Restricted public surfaces",
            "",
            (
                f"{len(restricted_surfaces)} restricted access methods pointed "
                "to a publicly reachable information page. That confirms only "
                "the public page; the protected corpus was not accessed."
            ),
            "",
            "## Constraints and escalation",
            "",
            "| Constraint kind | Records |",
            "| --- | ---: |",
        ]
    )
    for kind, count in constraints["counts"]["by_kind"].items():
        lines.append(f"| {markdown_cell(kind)} | {count} |")
    lines.extend(
        [
            "",
            (
                f"{constraints['counts']['by_escalation_state'].get('escalated', 0)} "
                "constraint records require internal review or source-owner "
                "coordination. Licence, fair-use, authentication, rate-limit, "
                "robots, privacy and availability concerns remain explicit; "
                "none was silently converted into a claim that a source class "
                "does not exist."
            ),
            "",
            "## Integrity and limitations",
            "",
            (
                "The immutable original is the sealed archive "
                f"`{evidence_reference['evidence_archive_path']}`. Its "
                "archive SHA-256 is "
                f"`{evidence_reference['evidence_archive_sha256']}` and the "
                "extracted original integrity manifest SHA-256 is "
                f"`{evidence_reference['original_integrity_sha256']}`."
            ),
            "",
            "- Reachability is point-in-time and is not corpus completeness.",
            "- A bounded body hash covers only the captured prefix when a response was truncated.",
            "- Public access is not a grant of copyright, database or computational-analysis rights.",
            "- The current metadata projection may advance; it is not the immutable original.",
            "- Historical evidence is never rewritten. Recovery from the archive requires explicit acknowledgement that downloaded content is untrusted.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture and validate immutable Whole-Law source-access evidence"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser(
        "capture",
        help="make one bounded public access attempt per registered route",
    )
    capture.add_argument("--workers", type=int, default=6)
    capture.add_argument("--per-host", type=int, default=1)
    capture.add_argument("--timeout", type=float, default=20.0)
    capture.add_argument("--max-body-bytes", type=int, default=32768)
    capture.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    capture.add_argument("--run-id")
    capture.add_argument(
        "--only",
        action="append",
        help="capture only a stable method ID; repeat to select several",
    )
    capture.add_argument(
        "--no-publish",
        action="store_true",
        help="seal the attempt without updating current projections",
    )

    check = subparsers.add_parser(
        "check",
        help="offline validation of a sealed immutable evidence archive",
    )
    check.add_argument("--run", default="latest")
    check.add_argument(
        "--allow-partial",
        action="store_true",
        help="validate a deliberately selected subset instead of all 108 routes",
    )

    publish = subparsers.add_parser(
        "publish",
        help="publish current summaries from a sealed full offline run",
    )
    publish.add_argument("--run", default="latest")
    return parser


def validate_capture_args(args: argparse.Namespace) -> None:
    if args.workers < 1 or args.workers > 16:
        raise ValueError("--workers must be between 1 and 16")
    if args.per_host < 1 or args.per_host > 2:
        raise ValueError("--per-host must be 1 or 2")
    if args.timeout < 1 or args.timeout > 60:
        raise ValueError("--timeout must be between 1 and 60 seconds")
    if args.max_body_bytes < 1024 or args.max_body_bytes > 65536:
        raise ValueError(
            "--max-body-bytes must be between 1024 and 65536"
        )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "capture":
            validate_capture_args(args)
            archive_path = capture_run(args)
            print(f"Immutable access evidence sealed at {archive_path}")
        elif args.command == "check":
            archive_path, receipt_path = resolve_archive(args.run)
            result, _ = validate_archive(archive_path, receipt_path)
            print(render_json(result), end="")
        elif args.command == "publish":
            archive_path, receipt_path = resolve_archive(args.run)
            publish_archive(archive_path, receipt_path)
        else:  # pragma: no cover - argparse enforces this.
            parser.error(f"Unknown command: {args.command}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
