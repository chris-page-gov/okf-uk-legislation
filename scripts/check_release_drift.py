#!/usr/bin/env python3
"""Run a bounded, read-only drift observation for the published OKF.

The probe never writes below the repository root, follows redirects only
between an explicit HTTPS allowlist, reads bounded response prefixes, and does
not use credentials.  A new work or an unavailable declared public entrypoint
is reported as drift and makes the command fail closed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import build_checksums
import build_legislation_okf as legislation
import capture_whole_law_source_access as source_access

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "bundle"
MAX_BODY_BYTES = 1_048_576
TIMEOUT_SECONDS = 20
USER_AGENT = (
    "okf-uk-legislation-drift-probe/1.0 "
    "(read-only public-source observation; no authentication)"
)
ALLOWED_HOSTS = {
    "chris-page-gov.github.io",
    "legislation.gov.uk",
    "raw.githubusercontent.com",
    "www.legislation.gov.uk",
}
PUBLIC_LINKS = (
    "https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json",
    "https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json",
    "https://chris-page-gov.github.io/okf-uk-legislation/docs/",
    "https://chris-page-gov.github.io/okf-uk-legislation/whole-law/docs/",
    "https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/main/bundle/okf-explorer.json",
    "https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/main/bundle/whole-law/okf-explorer.json",
)
NEW_WORK_FEED = (
    "https://www.legislation.gov.uk/all/data.feed"
    "?results-count=20&sort=published"
)


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"refusing non-allowlisted URL: {url}")


class AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.redirects = 0

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        self.redirects += 1
        if self.redirects > 5:
            raise urllib.error.HTTPError(
                newurl, code, "redirect limit exceeded", headers, fp
            )
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> tuple[dict[str, Any], bytes]:
    validate_url(url)
    opener = urllib.request.build_opener(AllowlistedRedirectHandler())
    request = urllib.request.Request(
        url,
        headers={
            "Accept": (
                "application/json, application/atom+xml, text/html;q=0.9, "
                "*/*;q=0.1"
            ),
            "Range": f"bytes=0-{MAX_BODY_BYTES - 1}",
            "User-Agent": USER_AGENT,
        },
    )
    started = datetime.now(timezone.utc)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            validate_url(final_url)
            body = response.read(MAX_BODY_BYTES + 1)
            truncated = len(body) > MAX_BODY_BYTES
            body = body[:MAX_BODY_BYTES]
            result = {
                "bytes_read": len(body),
                "content_type": response.headers.get_content_type(),
                "elapsed_ms": int(
                    (datetime.now(timezone.utc) - started).total_seconds() * 1000
                ),
                "final_url": final_url,
                "sha256": hashlib.sha256(body).hexdigest(),
                "status": int(response.status),
                "truncated": truncated,
                "url": url,
            }
            return result, body
    except (OSError, ValueError, urllib.error.URLError) as error:
        return (
            {
                "elapsed_ms": int(
                    (datetime.now(timezone.utc) - started).total_seconds() * 1000
                ),
                "error": f"{type(error).__name__}: {error}",
                "status": None,
                "url": url,
            },
            b"",
        )


def local_observation() -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    expected_checksums = build_checksums.build()
    checksum_path = PACK / "checksums.json"
    checksums_valid = (
        checksum_path.is_file()
        and checksum_path.read_text(encoding="utf-8") == expected_checksums
    )
    if not checksums_valid:
        failures.append("publication checksum manifest is not synchronized")

    try:
        archive_path, receipt_path = source_access.resolve_archive("latest")
        access, archived_files = source_access.validate_archive(
            archive_path,
            receipt_path,
        )
        observations = json.loads(
            archived_files["observations.json"].decode("utf-8")
        )
        access["source_records"] = len(
            {row["source_id"] for row in observations["records"]}
        )
        access["access_methods"] = len(observations["records"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        access = {"error": f"{type(error).__name__}: {error}"}
        failures.append("latest immutable source-access evidence is invalid")

    descriptor = json.loads(
        (PACK / "okf-explorer.json").read_text(encoding="utf-8")
    )
    return (
        {
            "access_evidence": access,
            "checksums_valid": checksums_valid,
            "snapshot": descriptor.get("snapshot"),
            "works": descriptor.get("counts", {}).get("works"),
        },
        failures,
    )


def route_exists(route: str, locator: dict[str, Any]) -> bool:
    bucket = legislation.large_corpus.relationship_bucket(route)
    metadata = locator["buckets"].get(bucket)
    if not metadata:
        return False
    path = PACK / metadata["path"]
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != metadata["sha256"]:
        raise ValueError(f"locator hash mismatch: {metadata['path']}")
    rows = json.loads(gzip.decompress(body).decode("utf-8"))
    return route in rows or route in locator.get("route_aliases", {})


def new_work_observation(body: bytes) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    try:
        records = legislation.parse_entries(body)
        locator = json.loads(
            (PACK / "data" / "records" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        observed = []
        for record in records:
            route = str(record["route"])
            represented = route_exists(route, locator)
            observed.append(
                {
                    "id": record["id"],
                    "represented_in_snapshot": represented,
                    "route": route,
                }
            )
        missing = [row for row in observed if not row["represented_in_snapshot"]]
        if missing:
            failures.append(
                f"{len(missing)} recently published works are absent from the snapshot"
            )
        return (
            {
                "observed_entries": len(observed),
                "new_works": missing,
                "new_works_count": len(missing),
                "records": observed,
            },
            failures,
        )
    except (ET.ParseError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        failures.append("official new-work feed could not be reconciled")
        return (
            {"error": f"{type(error).__name__}: {error}"},
            failures,
        )


def build_report() -> tuple[dict[str, Any], list[str]]:
    local, failures = local_observation()
    links = []
    for url in PUBLIC_LINKS:
        observation, _ = fetch(url)
        links.append(observation)
        if observation.get("status") not in {200, 206}:
            failures.append(f"public entrypoint unavailable: {url}")

    feed_observation, feed = fetch(NEW_WORK_FEED)
    if feed_observation.get("status") not in {200, 206}:
        failures.append("official new-work feed unavailable")
        new_works: dict[str, Any] = {"status": "not-observed"}
    else:
        new_works, new_failures = new_work_observation(feed)
        failures.extend(new_failures)

    unique_failures = sorted(set(failures))
    report = {
        "access_policy": {
            "authentication": "none",
            "body_limit_bytes": MAX_BODY_BYTES,
            "hosts": sorted(ALLOWED_HOSTS),
            "redirects": "https allowlist only; maximum 5",
            "repository_writes": False,
        },
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "local": local,
        "new_work_feed": feed_observation,
        "new_works": new_works,
        "public_links": links,
        "result": "drift-detected" if unique_failures else "no-drift-observed",
        "schema": "okf-release-drift-observation.v1",
        "violations": unique_failures,
    }
    return report, unique_failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional report path outside the repository (for a CI artifact).",
    )
    args = parser.parse_args()
    if args.output:
        output = args.output.resolve()
        if output == ROOT or output.is_relative_to(ROOT):
            parser.error("--output must be outside the repository")
    report, failures = build_report()
    text = render(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
