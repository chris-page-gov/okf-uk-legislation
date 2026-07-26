#!/usr/bin/env python3
"""Capture and verify a bounded post-build live effects reconciliation.

The static effects datapack remains immutable.  This script fetches only the
latest Atom entry for each declared seed/direction, stores the exact response
bytes in a deterministic compressed archive, and publishes a value-safe
receipt.  It never rewrites the acquisition snapshot or treats an inaccessible
route as agreement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import legislation_effects_evidence_archive as archive_tools

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "whole-law" / "config" / "effects-seeds.json"
STATIC_ASSERTIONS = ROOT / "bundle" / "data" / "effects" / "assertions.json.gz"
STATIC_ATTEMPTS = ROOT / "bundle" / "data" / "effects" / "attempt-ledger.json"
OUTPUT = (
    ROOT
    / "evidence"
    / "source-acquisitions"
    / "legislation-effects"
    / "live-reconciliation"
)
ASSURANCE = (
    ROOT
    / "whole-law"
    / "assurance"
    / "effects-live-reconciliation-20260726.json"
)
ATOM = "http://www.w3.org/2005/Atom"
OPEN_SEARCH = "http://a9.com/-/spec/opensearch/1.1/"
NS = {"atom": ATOM, "openSearch": OPEN_SEARCH}
USER_AGENT = (
    "okf-uk-legislation-effects-reconciliation/0.3 "
    "(+https://github.com/chris-page-gov/okf-uk-legislation)"
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
UNSAFE_XML = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
ALLOWED_HEADERS = {
    "cache-control",
    "content-length",
    "content-type",
    "etag",
    "last-modified",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_uri(value: str | None) -> str | None:
    if value and value.startswith("http://www.legislation.gov.uk/"):
        return "https://" + value[len("http://") :]
    return value


def bounded_read(stream: Any) -> bytes:
    body = stream.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Live reconciliation response exceeds the 2 MiB bound")
    return body


class OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Permit redirects only within the fixed official HTTPS origin."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        parsed = urllib.parse.urlparse(new_url)
        if parsed.scheme != "https" or parsed.hostname != "www.legislation.gov.uk":
            raise urllib.error.URLError("redirect left the official HTTPS origin")
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def request_route(url: str) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.legislation.gov.uk"
        or not parsed.path.startswith("/changes/")
    ):
        raise ValueError("Live reconciliation URL is outside the fixed allowlist")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/atom+xml, application/xml;q=0.9",
            "User-Agent": USER_AGENT,
        },
    )
    retrieved_at = utc_now()
    opener = urllib.request.build_opener(OfficialRedirectHandler())
    try:
        with opener.open(request, timeout=60) as response:
            body = bounded_read(response)
            status = int(response.status)
            final_url = response.geturl()
            headers = {
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower() in ALLOWED_HEADERS
            }
            error = None
    except urllib.error.HTTPError as exc:
        body = bounded_read(exc)
        status = int(exc.code)
        final_url = exc.geturl()
        headers = {
            key.lower(): value
            for key, value in exc.headers.items()
            if key.lower() in ALLOWED_HEADERS
        }
        error = f"HTTP {status}"
    except urllib.error.URLError as exc:
        body = b""
        status = None
        final_url = url
        headers = {}
        error = f"{type(exc.reason).__name__}: {exc.reason}"
    final = urllib.parse.urlparse(final_url)
    if final.scheme != "https" or final.hostname != "www.legislation.gov.uk":
        raise ValueError("Final reconciliation URL left the official HTTPS origin")
    envelope = {
        "schema": "okf-live-source-response-envelope.v1",
        "request": {
            "method": "GET",
            "url": url,
            "headers": {
                "accept": "application/atom+xml, application/xml;q=0.9",
                "user-agent": USER_AGENT,
            },
        },
        "response": {
            "body_bytes": len(body),
            "body_sha256": sha256_bytes(body),
            "final_url": final_url,
            "headers": headers,
            "status": status,
        },
        "retrieved_at": retrieved_at,
        "success": status is not None and 200 <= status < 300,
        "error": error,
        "tool": {
            "name": "scripts/reconcile_legislation_effects_live.py",
            "version": "1.0.0",
        },
    }
    return body, envelope


def feed_observation(body: bytes) -> dict[str, Any]:
    if UNSAFE_XML.search(body):
        raise ValueError("Live reconciliation response contains DTD or ENTITY")
    root = ET.fromstring(body)
    if root.tag != f"{{{ATOM}}}feed":
        raise ValueError("Successful reconciliation response is not an Atom feed")
    entries = root.findall("atom:entry", NS)
    entry_ids = {
        normalize_uri("".join(node.itertext()).strip())
        for entry in entries
        if (node := entry.find("atom:id", NS)) is not None
    }
    total_node = root.find("openSearch:totalResults", NS)
    total_results = (
        int("".join(total_node.itertext()).strip())
        if total_node is not None
        else None
    )
    return {
        "entry_ids": {value for value in entry_ids if value},
        "entries_returned": len(entries),
        "total_results": total_results,
    }


def static_state() -> tuple[dict[tuple[str, str], set[str]], dict[tuple[str, str], bool]]:
    import gzip

    assertions = json.loads(gzip.decompress(STATIC_ASSERTIONS.read_bytes()))
    source_urls: dict[tuple[str, str], set[str]] = {}
    for assertion in assertions:
        for evidence in assertion.get("evidence", []):
            key = (
                str(evidence.get("seed_work")),
                str(evidence.get("feed_route")),
            )
            source_url = normalize_uri(evidence.get("source_url"))
            if source_url:
                source_urls.setdefault(key, set()).add(source_url)
    attempts = load(STATIC_ATTEMPTS)["attempts"]
    successes = {
        (str(row["seed_work"]), str(row["route"])): bool(row["success"])
        for row in attempts
    }
    return source_urls, successes


def route_specs() -> list[dict[str, str]]:
    config = load(CONFIG)
    rows = []
    for seed in config["works"]:
        for route in ("affected", "affecting"):
            work = str(seed["id"])
            rows.append(
                {
                    "route": route,
                    "seed_title": str(seed["title"]),
                    "seed_work": work,
                    "url": (
                        "https://www.legislation.gov.uk/changes/"
                        f"{route}/{work}/data.feed?results-count=1&sort=modified"
                    ),
                }
            )
    return rows


def classify(
    *,
    body: bytes,
    envelope: dict[str, Any],
    snapshot_urls: set[str],
    snapshot_success: bool,
) -> dict[str, Any]:
    if not envelope["success"]:
        status = envelope["response"]["status"]
        return {
            "entries_returned": 0,
            "live_additions": 0,
            "live_matches": 0,
            "state": (
                "inaccessible-consistent"
                if not snapshot_success
                else "live-access-regression"
            ),
            "total_results": None,
            "status": status,
        }
    observation = feed_observation(body)
    live_ids = observation.pop("entry_ids")
    additions = live_ids - snapshot_urls
    matches = live_ids & snapshot_urls
    if additions:
        state = "live-addition"
    elif live_ids and matches == live_ids:
        state = "agreement"
    elif not live_ids and not snapshot_urls:
        state = "agreement-empty"
    elif not live_ids:
        state = "live-empty"
    else:
        state = "unreconciled"
    return {
        **observation,
        "live_additions": len(additions),
        "live_matches": len(matches),
        "state": state,
        "status": envelope["response"]["status"],
    }


def build_receipt(
    *,
    run_id: str,
    observed_at: str,
    archive_path: Path,
    files: dict[str, bytes],
) -> dict[str, Any]:
    snapshot_urls, snapshot_successes = static_state()
    route_rows = []
    for spec in route_specs():
        slug = spec["seed_work"].replace("/", "-")
        base = f"{slug}/{spec['route']}"
        body = files[f"{base}/response.xml"]
        envelope = json.loads(files[f"{base}/envelope.json"])
        key = (spec["seed_work"], spec["route"])
        result = classify(
            body=body,
            envelope=envelope,
            snapshot_urls=snapshot_urls.get(key, set()),
            snapshot_success=snapshot_successes.get(key, False),
        )
        route_rows.append(
            {
                "body": {
                    "archive_member": f"{run_id}/{base}/response.xml",
                    "bytes": len(body),
                    "sha256": sha256_bytes(body),
                },
                "request_url": spec["url"],
                "retrieved_at": envelope["retrieved_at"],
                "route": spec["route"],
                "seed_work": spec["seed_work"],
                "snapshot_route_success": snapshot_successes.get(key, False),
                **result,
            }
        )
    archive_body = archive_path.read_bytes()
    detector_values = {
        value
        for body in files.values()
        for value in archive_tools.PUSH_PROTECTION_SHAPE.findall(body)
    }
    if any(value in archive_body for value in detector_values):
        raise ValueError(
            "Compressed reconciliation archive exposes detector-shaped source data"
        )
    states = Counter(row["state"] for row in route_rows)
    receipt = {
        "schema": "okf-effects-live-reconciliation.v1",
        "run_id": run_id,
        "observed_at": observed_at,
        "scope": {
            "method": "latest-entry probe",
            "results_per_route": 1,
            "routes": len(route_rows),
            "seed_works": len({row["seed_work"] for row in route_rows}),
            "statement": (
                "This post-build check compares the current official latest "
                "entry with the frozen static snapshot. It is not a full live "
                "recrawl and does not imply complete effects coverage."
            ),
        },
        "snapshot": {
            "assertions": {
                "path": STATIC_ASSERTIONS.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(STATIC_ASSERTIONS),
            },
            "attempt_ledger": {
                "path": STATIC_ATTEMPTS.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(STATIC_ATTEMPTS),
            },
            "config": {
                "path": CONFIG.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(CONFIG),
            },
        },
        "archive": {
            "path": archive_path.relative_to(ROOT).as_posix(),
            "bytes": len(archive_body),
            "file_count": len(files),
            "sha256": sha256_bytes(archive_body),
            "tree_sha256": archive_tools.tree_digest(
                archive_tools.tree_receipts(files)
            ),
            "response_bodies_published_loose": False,
            "compressed_blob_plaintext_check_passed": True,
        },
        "counts": {
            "by_state": dict(sorted(states.items())),
            "live_additions": sum(row["live_additions"] for row in route_rows),
            "live_matches": sum(row["live_matches"] for row in route_rows),
            "routes": len(route_rows),
        },
        "routes": route_rows,
        "tool": {
            "path": "scripts/reconcile_legislation_effects_live.py",
            "sha256": sha256_file(Path(__file__)),
            "version": "1.0.0",
        },
        "release_effect": (
            "passed-with-declared-live-delta"
            if not any(
                row["state"] in {"live-access-regression", "unreconciled"}
                for row in route_rows
            )
            else "blocked-live-regression-or-unreconciled-route"
        ),
    }
    return receipt


def capture(run_id: str, observed_at: str) -> None:
    if not archive_tools.SNAPSHOT_RE.fullmatch(run_id):
        raise ValueError(
            "Run ID must use legislation-effects-YYYY-MM-DD so archive "
            "validation fails before any network request"
        )
    archive_path = OUTPUT / "archives" / f"{run_id}.tar.xz"
    receipt_path = OUTPUT / "receipts" / f"{run_id}.json"
    if archive_path.exists() or receipt_path.exists() or ASSURANCE.exists():
        raise FileExistsError(
            "Live reconciliation output already exists; use a new run ID"
        )
    files: dict[str, bytes] = {}
    for spec in route_specs():
        body, envelope = request_route(spec["url"])
        slug = spec["seed_work"].replace("/", "-")
        base = f"{slug}/{spec['route']}"
        files[f"{base}/response.xml"] = body
        files[f"{base}/envelope.json"] = render(envelope)
    archive_tools.write_deterministic_archive(
        archive_path,
        run_id,
        files,
    )
    receipt = build_receipt(
        run_id=run_id,
        observed_at=observed_at,
        archive_path=archive_path,
        files=files,
    )
    body = render(receipt)
    if archive_tools.PUSH_PROTECTION_SHAPE.search(body):
        raise ValueError("Reconciliation receipt contains detector-shaped data")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    ASSURANCE.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(body)
    ASSURANCE.write_bytes(body)
    print(
        "Live effects reconciliation captured: "
        f"{receipt['counts']['routes']} routes; "
        f"states={receipt['counts']['by_state']}"
    )


def check() -> None:
    receipt = load(ASSURANCE)
    run_id = str(receipt["run_id"])
    archive_path = ROOT / receipt["archive"]["path"]
    receipt_path = OUTPUT / "receipts" / f"{run_id}.json"
    if not archive_path.is_file() or not receipt_path.is_file():
        raise ValueError("Live reconciliation archive or receipt is missing")
    files = archive_tools.read_archive_files(
        archive_path,
        expected_snapshot_id=run_id,
    )
    expected = build_receipt(
        run_id=run_id,
        observed_at=str(receipt["observed_at"]),
        archive_path=archive_path,
        files=files,
    )
    expected_body = render(expected)
    if receipt_path.read_bytes() != expected_body:
        raise ValueError("Live reconciliation evidence receipt is out of date")
    if ASSURANCE.read_bytes() != expected_body:
        raise ValueError("Published live reconciliation receipt is out of date")
    print(
        "Live effects reconciliation verified: "
        f"{expected['counts']['routes']} routes; "
        f"states={expected['counts']['by_state']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--run-id", required=True)
    capture_parser.add_argument("--observed-at", required=True)
    subparsers.add_parser("check")
    args = parser.parse_args()
    if args.command == "capture":
        capture(args.run_id, args.observed_at)
    else:
        check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
