#!/usr/bin/env python3
"""Acquire and build a bounded official legislation.gov.uk effects datapack.

The acquisition cache is immutable: an existing request envelope or body is
never overwritten. A later refresh must use a new snapshot/configuration. The
published coverage ledger explicitly distinguishes complete routes from routes
truncated by the configured page bound.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import legislation_effects_evidence_archive as effects_evidence

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
DATA = BUNDLE / "data"
OUTPUT = DATA / "effects"
RUN_PATH = BUNDLE / "effects" / "legislation-gov-uk-2026-07-25.json"
CONFIG_PATH = ROOT / "whole-law" / "config" / "effects-seeds.json"
EVIDENCE = ROOT / "evidence" / "source-acquisitions" / "legislation-effects"
GENERATED_AT = "2026-07-25T21:30:00Z"
OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
ATOM = "http://www.w3.org/2005/Atom"
LEG = "http://www.legislation.gov.uk/namespaces/legislation"
UKM = "http://www.legislation.gov.uk/namespaces/metadata"
NS = {"atom": ATOM, "leg": LEG, "ukm": UKM}
USER_AGENT = "okf-uk-legislation/0.3 (+https://github.com/chris-page-gov/okf-uk-legislation)"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def gzip_json(value: Any) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=output,
        compresslevel=6,
        mtime=0,
    ) as stream:
        stream.write(render(value).encode("utf-8"))
    return output.getvalue()


def normalize_uri(value: str | None) -> str | None:
    if value and value.startswith("http://www.legislation.gov.uk/"):
        return "https://" + value[len("http://"):]
    return value


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_capture(
    url: str,
    body_path: Path,
    envelope_path: Path,
    allow_fetch: bool,
    *,
    archived_files: dict[str, bytes] | None = None,
    body_member: str | None = None,
    envelope_member: str | None = None,
) -> tuple[bytes | None, dict[str, Any]]:
    if archived_files is not None:
        if body_member is None or envelope_member is None:
            raise ValueError("Archived capture member paths are required")
        body = archived_files.get(body_member)
        envelope_body = archived_files.get(envelope_member)
        if body is None or envelope_body is None:
            raise ValueError(
                "Sealed effects archive is missing a declared capture pair"
            )
        envelope = json.loads(envelope_body.decode("utf-8"))
        if envelope.get("body_bytes") != len(body):
            raise ValueError("Archived capture byte count differs from envelope")
        if envelope.get("body_sha256") != sha256(body):
            raise ValueError("Archived capture digest differs from envelope")
        return body, envelope
    if envelope_path.is_file():
        envelope = load(envelope_path)
        body = body_path.read_bytes() if body_path.is_file() else None
        return body, envelope
    if not allow_fetch:
        return None, {
            "schema": "okf-source-response-envelope.v1",
            "url": url,
            "status": None,
            "success": False,
            "error": "missing immutable acquisition cache",
        }

    body_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/atom+xml, application/xml;q=0.9",
            "User-Agent": USER_AGENT,
        },
    )
    retrieved_at = timestamp()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            headers = {key.lower(): value for key, value in response.headers.items()}
            status = int(response.status)
            final_url = response.geturl()
            success = 200 <= status < 300
            error = None
    except urllib.error.HTTPError as exc:
        body = exc.read()
        headers = {key.lower(): value for key, value in exc.headers.items()}
        status = int(exc.code)
        final_url = exc.geturl()
        success = False
        error = f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        body = None
        headers = {}
        status = None
        final_url = url
        success = False
        error = str(exc.reason)

    schema_fingerprint = None
    if body and success:
        try:
            root = ET.fromstring(body)
            effect_keys = sorted({
                key
                for effect in root.findall(".//ukm:Effect", NS)
                for key in effect.attrib
            })
            schema_fingerprint = "sha256:" + sha256(
                render({"root": root.tag, "effect_attributes": effect_keys}).encode("utf-8")
            )
        except ET.ParseError:
            success = False
            error = "response was not parseable XML"

    envelope = {
        "schema": "okf-source-response-envelope.v1",
        "request": {
            "method": "GET",
            "url": url,
            "headers": {
                "accept": "application/atom+xml, application/xml;q=0.9",
                "user-agent": USER_AGENT,
            },
        },
        "retrieved_at": retrieved_at,
        "status": status,
        "success": success,
        "final_url": final_url,
        "response_headers": headers,
        "media_type": headers.get("content-type"),
        "body_bytes": len(body) if body is not None else 0,
        "body_sha256": sha256(body) if body is not None else None,
        "schema_fingerprint": schema_fingerprint,
        "tool": "scripts/build_legislation_effects.py",
        "tool_version": "1.0.0",
        "error": error,
        "rights": OGL,
    }
    if body is not None:
        body_path.write_bytes(body)
    envelope_path.write_text(render(envelope), encoding="utf-8")
    return body, envelope


def text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return re.sub(r"\s+", " ", value) if value else None


def provision_rows(effect: ET.Element, container: str) -> list[dict[str, Any]]:
    parent = effect.find(f"ukm:{container}", NS)
    if parent is None:
        return []
    rows = []
    for node in parent.iter():
        uri = normalize_uri(node.attrib.get("URI"))
        if not uri:
            continue
        rows.append({
            "uri": uri,
            "label": text(node),
            "ref": node.attrib.get("Ref"),
            "missing": node.attrib.get("Missing") == "true",
        })
    unique = {row["uri"]: row for row in rows}
    return [unique[key] for key in sorted(unique)]


def assertion_from_entry(
    entry: ET.Element,
    route: str,
    seed: dict[str, str],
    evidence_path: str,
    evidence_member: str | None,
    retrieved_at: str,
) -> dict[str, Any] | None:
    effect = entry.find(".//ukm:Effect", NS)
    if effect is None:
        return None
    source = normalize_uri(effect.attrib.get("AffectingURI"))
    target = normalize_uri(effect.attrib.get("AffectedURI"))
    if not source or not target:
        return None
    effect_type = effect.attrib.get("Type", "unspecified").strip() or "unspecified"
    effect_id = effect.attrib.get("EffectId") or effect.attrib.get("URI")
    entry_id = normalize_uri(text(entry.find("atom:id", NS)))
    identity = "\0".join([
        str(effect_id),
        source,
        target,
        effect_type,
        effect.attrib.get("AffectingProvisions", ""),
        effect.attrib.get("AffectedProvisions", ""),
    ])
    assertion_id = "urn:okf:official-effect:sha256:" + sha256(identity.encode("utf-8"))
    in_force_dates = sorted({
        node.attrib["Date"]
        for node in effect.findall(".//ukm:InForce", NS)
        if node.attrib.get("Date")
    })
    applied_raw = effect.attrib.get("Applied")
    application_status = (
        "applied" if applied_raw == "true"
        else "unapplied" if applied_raw == "false"
        else "not-supplied"
    )
    return {
        "id": assertion_id,
        "source": source,
        "target": target,
        "predicate": f"official effect: {effect_type.lower()}",
        "direction": "source-to-target",
        "authority": {
            "class": "official",
            "label": "legislation.gov.uk editorial effect",
            "source": "https://www.legislation.gov.uk/changes",
        },
        "derivation": "source-native-official-atom-feed",
        "confidence": 1.0,
        "application_status": application_status,
        "valid_from": in_force_dates[0] if in_force_dates else None,
        "valid_to": None,
        "source_native_type": effect_type,
        "source_native_effect_id": effect_id,
        "source_native_uri": normalize_uri(effect.attrib.get("URI")),
        "affected_provisions": provision_rows(effect, "AffectedProvisions"),
        "affecting_provisions": provision_rows(effect, "AffectingProvisions"),
        "evidence": [{
            "url": entry_id or normalize_uri(effect.attrib.get("URI")) or source,
            "type": "official-legislation-effect",
            "source_url": entry_id,
            "feed_route": route,
            "seed_work": seed["id"],
            "capture": evidence_path,
            "capture_member": evidence_member,
            "entry_updated": text(entry.find("atom:updated", NS)),
            "entry_title": text(entry.find("atom:title", NS)),
            "source_native_type": effect_type,
            "affected_provisions": effect.attrib.get("AffectedProvisions"),
            "affecting_provisions": effect.attrib.get("AffectingProvisions"),
        }],
        "generated_at": GENERATED_AT,
        "observed_at": retrieved_at,
        "stale_after": "2026-08-25T00:00:00Z",
        "freshness": "current",
        "verified": [{
            "by": "process:official-effect-feed-parser",
            "at": GENERATED_AT,
            "method": "frozen official Atom feed parse",
            "scope": "source-native relationship and supplied application state",
        }],
        "rights": {
            "source": OGL,
            "attribution": "Contains public sector information licensed under the Open Government Licence v3.0.",
        },
    }


def next_url(root: ET.Element) -> str | None:
    for link in root.findall("atom:link", NS):
        if link.attrib.get("rel") == "next":
            return normalize_uri(link.attrib.get("href"))
    return None


def acquire(
    config: dict[str, Any],
    allow_fetch: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    policy = config["retrieval_policy"]
    page_limit = int(policy["maximum_pages_per_route"])
    page_size = int(policy["results_per_page"])
    assertions: dict[str, dict[str, Any]] = {}
    attempts = []
    snapshot_id = config["snapshot_id"]
    archive_path, receipt_path, projection_path = (
        effects_evidence.archive_paths(snapshot_id)
    )
    sealed_files: dict[str, bytes] | None = None
    if archive_path.is_file() or receipt_path.is_file() or projection_path.is_file():
        if not (
            archive_path.is_file()
            and receipt_path.is_file()
            and projection_path.is_file()
        ):
            raise ValueError(
                "Effects evidence archive, receipt and projection must all exist"
            )
        _, sealed_files, _ = effects_evidence.validate_archive(snapshot_id)
    evidence = {
        "sealed": sealed_files is not None,
        "archive": (
            archive_path.relative_to(ROOT).as_posix()
            if sealed_files is not None
            else None
        ),
        "archive_receipt": (
            receipt_path.relative_to(ROOT).as_posix()
            if sealed_files is not None
            else None
        ),
        "publication_projection": (
            projection_path.relative_to(ROOT).as_posix()
            if sealed_files is not None
            else None
        ),
    }

    for seed in config["works"]:
        slug = seed["id"].replace("/", "-")
        for route in policy["routes"]:
            url = (
                f"https://www.legislation.gov.uk/changes/{route}/{seed['id']}/data.feed"
                f"?results-count={page_size}&sort=modified"
            )
            pages = 0
            entries_seen = 0
            total_results = None
            route_success = True
            route_error = None
            last_next = None
            while url and pages < page_limit:
                pages += 1
                base = EVIDENCE / config["snapshot_id"] / slug / route
                body_path = base / f"page-{pages:03d}.xml"
                envelope_path = base / f"page-{pages:03d}.envelope.json"
                body_member = (
                    f"{slug}/{route}/page-{pages:03d}.xml"
                )
                envelope_member = (
                    f"{slug}/{route}/page-{pages:03d}.envelope.json"
                )
                body, envelope = request_capture(
                    url,
                    body_path,
                    envelope_path,
                    allow_fetch,
                    archived_files=sealed_files,
                    body_member=body_member,
                    envelope_member=envelope_member,
                )
                evidence_path = (
                    evidence["archive"]
                    if sealed_files is not None
                    else str(body_path.relative_to(ROOT))
                )
                evidence_member = (
                    f"{snapshot_id}/{body_member}"
                    if sealed_files is not None
                    else None
                )
                if not envelope.get("success") or body is None:
                    route_success = False
                    route_error = envelope.get("error") or f"HTTP {envelope.get('status')}"
                    break
                if effects_evidence.UNSAFE_XML_DECLARATION.search(body):
                    route_success = False
                    route_error = (
                        "XML safety policy rejected a DTD/entity declaration"
                    )
                    break
                try:
                    root = ET.fromstring(body)
                except ET.ParseError as exc:
                    route_success = False
                    route_error = f"XML parse error: {exc}"
                    break
                total = root.find("atom:totalResults", {"atom": "http://a9.com/-/spec/opensearch/1.1/"})
                if total is None:
                    total = root.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
                if total is not None and text(total):
                    total_results = int(text(total))
                entries = root.findall("atom:entry", NS)
                entries_seen += len(entries)
                for entry in entries:
                    assertion = assertion_from_entry(
                        entry,
                        route,
                        seed,
                        evidence_path,
                        evidence_member,
                        envelope["retrieved_at"],
                    )
                    if assertion:
                        existing = assertions.get(assertion["id"])
                        if existing:
                            existing["evidence"].extend(
                                item for item in assertion["evidence"]
                                if item not in existing["evidence"]
                            )
                        else:
                            assertions[assertion["id"]] = assertion
                last_next = next_url(root)
                url = last_next
            truncated = bool(last_next and pages >= page_limit)
            attempts.append({
                "seed_work": seed["id"],
                "seed_title": seed["title"],
                "route": route,
                "initial_url": (
                    f"https://www.legislation.gov.uk/changes/{route}/{seed['id']}/data.feed"
                    f"?results-count={page_size}&sort=modified"
                ),
                "pages_captured": pages,
                "entries_seen": entries_seen,
                "reported_total_results": total_results,
                "success": route_success,
                "complete_route_snapshot": route_success and not truncated,
                "truncated_by_page_bound": truncated,
                "next_url": last_next if truncated else None,
                "error": route_error,
            })
    return (
        sorted(assertions.values(), key=lambda row: row["id"]),
        attempts,
        evidence,
    )


def build(allow_fetch: bool) -> tuple[dict[Path, bytes], dict[str, Any], dict[str, Any]]:
    config = load(CONFIG_PATH)
    assertions, attempts, acquisition_evidence = acquire(config, allow_fetch)
    if not acquisition_evidence["sealed"]:
        raise SystemExit(
            "Effects capture is not sealed. Create and verify its deterministic "
            "archive with scripts/legislation_effects_evidence_archive.py "
            "before publishing the datapack."
        )
    predicate_counts = Counter(row["predicate"] for row in assertions)
    application_counts = Counter(row["application_status"] for row in assertions)
    source_count = len({row["source"] for row in assertions})
    target_count = len({row["target"] for row in assertions})
    body = gzip_json(assertions)
    chunk = {
        "path": "data/effects/assertions.json.gz",
        "media_type": "application/json",
        "compression": "gzip",
        "bytes": len(body),
        "sha256": sha256(body),
        "records": len(assertions),
    }
    manifest = {
        "schema": "okf-provider-datapack.v1",
        "id": "legislation-gov-uk-official-effects-2026-07-25",
        "source_id": "legislation-gov-uk-changes",
        "snapshot_id": config["snapshot_id"],
        "generated_at": GENERATED_AT,
        "counts": {
            "assertions": len(assertions),
            "source_works": source_count,
            "target_works": target_count,
            "seed_works": len(config["works"]),
            "routes_attempted": len(attempts),
            "routes_complete": sum(row["complete_route_snapshot"] for row in attempts),
            "routes_truncated": sum(row["truncated_by_page_bound"] for row in attempts),
            "routes_failed": sum(not row["success"] for row in attempts),
        },
        "chunks": [chunk],
        "acquisition": {
            "kind": "official-atom-feed-frozen-envelope",
            "source": "https://www.legislation.gov.uk/changes",
            "seed_config": "whole-law/config/effects-seeds.json",
            "attempt_ledger": "data/effects/attempt-ledger.json",
            "coverage": "data/effects/coverage.json",
            "reconciliation": "data/effects/reconciliation.json",
            "evidence_archive": acquisition_evidence["archive"],
            "evidence_archive_receipt": (
                acquisition_evidence["archive_receipt"]
            ),
            "evidence_publication_projection": (
                acquisition_evidence["publication_projection"]
            ),
            "authority": "official-source",
            "coverage_status": "partial",
        },
        "replaces": None,
    }
    coverage = {
        "schema": "okf-official-effects-coverage.v1",
        "generated_at": GENERATED_AT,
        "snapshot_id": config["snapshot_id"],
        "evidence": {
            "archive": acquisition_evidence["archive"],
            "archive_receipt": acquisition_evidence["archive_receipt"],
            "publication_projection": (
                acquisition_evidence["publication_projection"]
            ),
            "original_bytes_recoverable": True,
            "projection_contains_response_bodies": False,
        },
        "population": {
            "legislation_works_in_bundle": load(DATA / "manifest.json")["counts"]["works"],
            "seed_works": len(config["works"]),
            "seed_work_fraction": round(
                len(config["works"]) / load(DATA / "manifest.json")["counts"]["works"], 10
            ),
        },
        "routes": attempts,
        "status": "partial",
        "limitations": [
            "This static graph covers only the declared high-value seed works.",
            "A route subject to the page bound is explicitly marked truncated.",
            "Observed access on 25 July 2026 does not guarantee continuing availability.",
            "The feed reports editorial effects; absence from this snapshot is not evidence that no effect exists.",
            "Official public identifiers that trigger a credential detector are retained only inside compressed, integrity-bound evidence and datapack objects; receipts and projections contain no matched values.",
        ],
    }
    reconciliation = {
        "schema": "okf-official-effects-reconciliation.v1",
        "generated_at": GENERATED_AT,
        "snapshot_id": config["snapshot_id"],
        "method": "The frozen datapack was parsed from the live official route at each envelope's observed retrieval time.",
        "states": {
            "agreement_at_acquisition": sum(row["success"] for row in attempts),
            "inaccessible_at_acquisition": sum(not row["success"] for row in attempts),
            "truncated_static_routes": sum(row["truncated_by_page_bound"] for row in attempts),
        },
        "live_routes": [{
            "seed_work": row["seed_work"],
            "route": row["route"],
            "url": row["initial_url"],
            "snapshot_state": (
                "inaccessible"
                if not row["success"]
                else "truncated"
                if row["truncated_by_page_bound"]
                else "agreement-at-acquisition"
            ),
        } for row in attempts],
        "notice": "A scheduled refresh creates a new immutable attempt; it never rewrites this evidence.",
    }
    relationship_summary = {
        "schema": "okf-official-effects-relationship-summary.v1",
        "generated_at": GENERATED_AT,
        "total": len(assertions),
        "by_predicate": dict(sorted(predicate_counts.items())),
        "by_application_status": dict(sorted(application_counts.items())),
        "authority": {"official-source": len(assertions)},
        "freshness": {"observed_on": "2026-07-25", "snapshot_id": config["snapshot_id"]},
        "coverage_status": "partial",
    }
    files = {
        Path("assertions.json.gz"): body,
        Path("manifest.json"): render(manifest).encode("utf-8"),
        Path("attempt-ledger.json"): render({
            "schema": "okf-source-acquisition-attempt-ledger.v1",
            "generated_at": GENERATED_AT,
            "sealed_evidence": {
                "archive": acquisition_evidence["archive"],
                "archive_receipt": acquisition_evidence["archive_receipt"],
                "publication_projection": (
                    acquisition_evidence["publication_projection"]
                ),
            },
            "attempts": attempts,
        }).encode("utf-8"),
        Path("coverage.json"): render(coverage).encode("utf-8"),
        Path("reconciliation.json"): render(reconciliation).encode("utf-8"),
        Path("relationship-summary.json"): render(relationship_summary).encode("utf-8"),
    }
    run = {
        "schema": "okf-official-effects-run.v1",
        "run_id": "official-effects-2026-07-25",
        "snapshot_id": config["snapshot_id"],
        "generated_at": GENERATED_AT,
        "source": "https://www.legislation.gov.uk/changes",
        "authority": "official-source",
        "coverage_status": "partial",
        "assertions": len(assertions),
        "seed_works": len(config["works"]),
        "routes_attempted": len(attempts),
        "routes_complete": manifest["counts"]["routes_complete"],
        "routes_truncated": manifest["counts"]["routes_truncated"],
        "routes_failed": manifest["counts"]["routes_failed"],
        "datapack": "data/effects/manifest.json",
        "coverage": "data/effects/coverage.json",
        "reconciliation": "data/effects/reconciliation.json",
        "evidence_archive": acquisition_evidence["archive"],
        "evidence_archive_receipt": acquisition_evidence["archive_receipt"],
        "evidence_publication_projection": (
            acquisition_evidence["publication_projection"]
        ),
    }
    return files, manifest, run


def update_json(path: Path, transform) -> None:
    value = load(path)
    transform(value)
    path.write_text(render(value), encoding="utf-8")


def reconcile_relationship_counts(
    counts: dict[str, Any],
    *,
    descriptor: bool,
) -> None:
    """Keep core and provider-datapack relationship counts idempotent."""

    core = int(counts.get("core_relationships", counts["relationships"]))
    effects = int(counts.get("official_effect_relationships", 0))
    model = int(counts.get("model_assisted_relationships_v2", 0))
    external = effects + model
    combined = core + external
    counts["core_relationships"] = core
    counts["external_datapack_relationships"] = external
    counts["relationships_with_external_datapacks"] = combined
    if descriptor:
        counts["relationships"] = combined


def update_publication(manifest: dict[str, Any], run: dict[str, Any]) -> None:
    accepted = int(manifest["counts"]["assertions"])

    def descriptor(value: dict[str, Any]) -> None:
        value["version"] = "0.3.0"
        value["status"] = "candidate"
        value.setdefault("entrypoints", {})["official_effects"] = "data/effects/manifest.json"
        value["entrypoints"]["relationship_summary"] = "data/relationship-summary.json"
        value.setdefault("extensions", {})["okf-official-effects.v1"] = {
            "mode": "external-provider-datapack",
            "entrypoint": "official_effects",
            "authority": "official-source",
            "coverage_status": "partial",
            "snapshot_id": run["snapshot_id"],
            "assertions": accepted,
            "reconciliation": "data/effects/reconciliation.json",
        }
        counts = value.setdefault("counts", {})
        counts["official_effect_relationships"] = accepted
        reconcile_relationship_counts(counts, descriptor=True)

    update_json(BUNDLE / "okf-explorer.json", descriptor)

    def data_manifest(value: dict[str, Any]) -> None:
        value.setdefault("indexes", {})["official_effects"] = "data/effects/manifest.json"
        value["indexes"]["relationship_summary"] = "data/relationship-summary.json"
        counts = value.setdefault("counts", {})
        counts["official_effect_relationships"] = accepted
        reconcile_relationship_counts(counts, descriptor=False)

    update_json(DATA / "manifest.json", data_manifest)

    summary = load(DATA / "relationship-summary.json")
    summary["relationships"] = [
        row for row in summary["relationships"]
        if row.get("datapack") != "legislation-effects"
    ]
    effects_summary = load(OUTPUT / "relationship-summary.json")
    summary["relationships"].extend({
        "predicate": predicate,
        "count": count,
        "authority": "official-source",
        "datapack": "legislation-effects",
    } for predicate, count in effects_summary["by_predicate"].items())
    summary["external_datapack_total"] = sum(
        row["count"] for row in summary["relationships"]
        if row.get("datapack") != "core"
    )
    summary["combined_total"] = summary["core_total"] + summary["external_datapack_total"]
    summary["generated_at"] = GENERATED_AT
    summary["notice"] = (
        "Counts are separated by predicate, authority and datapack. Official effects "
        "cover only the declared partial seed snapshot."
    )
    (DATA / "relationship-summary.json").write_text(render(summary), encoding="utf-8")

    def graph(value: dict[str, Any]) -> None:
        external = [
            row for row in value.get("external_edge_counts", [])
            if row.get("datapack") != "data/effects/manifest.json"
        ]
        external.append({
            "kind": "official legislation effect",
            "authority": "official-source",
            "count": accepted,
            "datapack": "data/effects/manifest.json",
            "coverage_status": "partial",
        })
        value["external_edge_counts"] = external
        value["relationship_summary"] = "data/relationship-summary.json"

    update_json(DATA / "graph.json", graph)


def check_files(files: dict[Path, bytes], output: Path) -> list[str]:
    expected = set(files)
    actual = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    } if output.is_dir() else set()
    errors = []
    for path in sorted(actual | expected):
        if path not in expected:
            errors.append(f"unexpected: {path}")
        elif path not in actual:
            errors.append(f"missing: {path}")
        elif (output / path).read_bytes() != files[path]:
            errors.append(f"out of date: {path}")
    return errors


def write_files(files: dict[Path, bytes], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    expected = set(files)
    actual = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    }
    unexpected = actual - expected
    if unexpected:
        raise SystemExit(
            "Refusing to delete unexpected generated effects files: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    for relative, body in files.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not fetch missing immutable source envelopes.",
    )
    args = parser.parse_args()
    files, manifest, run = build(allow_fetch=not args.check and not args.offline)
    if args.check:
        errors = check_files(files, OUTPUT)
        if errors:
            print("Official effects datapack is not synchronized:")
            for error in errors[:100]:
                print(f"- {error}")
            return 1
        current_run = load(RUN_PATH) if RUN_PATH.is_file() else None
        if current_run != run:
            print("Official effects run manifest is not synchronized")
            return 1
        print(
            "Official effects synchronized: "
            f"{run['assertions']:,} assertions from {run['seed_works']} seed works"
        )
        return 0
    write_files(files, OUTPUT)
    RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_PATH.write_text(render(run), encoding="utf-8")
    update_publication(manifest, run)
    print(
        "Built official effects: "
        f"{run['assertions']:,} assertions; "
        f"{run['routes_complete']} complete routes, "
        f"{run['routes_truncated']} truncated, "
        f"{run['routes_failed']} failed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
