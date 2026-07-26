#!/usr/bin/env python3
"""Capture a bounded, SSRF-guarded replacement-route evidence delta.

The immutable research source register and the original sealed access run are
never rewritten. This tool validates a versioned overlay against both, permits
only reviewed HTTPS candidates and redirect hosts, rejects non-public network
destinations, captures bounded response prefixes, and seals each completed
delta as immutable evidence before publishing a body-free projection.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

import capture_whole_law_source_access as base
import source_access_evidence_archive as archive_tools


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = (
    ROOT / "whole-law" / "acquisition" / "source-route-replacements.v1.json"
)
COPFS_SUPPLEMENT = (
    ROOT
    / "whole-law"
    / "acquisition"
    / "source-route-replacements-copfs-r02.v1.json"
)
COPFS_SYSTEM_TRUST_SUPPLEMENT = (
    ROOT
    / "whole-law"
    / "acquisition"
    / "source-route-replacements-copfs-r03.v1.json"
)
OVERLAY_SCHEMA = (
    ROOT
    / "whole-law"
    / "acquisition"
    / "source-route-replacement-overlay.schema.json"
)
REGISTER = (
    ROOT / "research" / "whole-law-okf-research" / "source-register.json"
)
BASE_OBSERVATIONS = (
    ROOT / "whole-law" / "acquisition" / "current" / "access-methods.json"
)
BASE_CONSTRAINTS = (
    ROOT
    / "whole-law"
    / "acquisition"
    / "current"
    / "source-constraint-ledger.json"
)
EVIDENCE_ROOT = (
    ROOT
    / "evidence"
    / "source-acquisitions"
    / "whole-law-route-replacements"
)
ARCHIVE_ROOT = EVIDENCE_ROOT / "archives"
RECEIPT_ROOT = EVIDENCE_ROOT / "archive-receipts"
AUTHORING = ROOT / "whole-law" / "acquisition" / "replacements"
BUNDLE = ROOT / "bundle" / "whole-law" / "acquisition" / "replacements"

TOOL_VERSION = "1.1.0"
RUN_SCHEMA = "okf-source-route-replacement-run.v1"
OBSERVATION_SCHEMA = "okf-source-route-replacement-observations.v1"
PROJECTION_SCHEMA = "okf-source-route-replacement-projection.v1"
REFERENCE_SCHEMA = "okf-source-route-replacement-evidence-reference.v1"
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")
UNSAFE_XML = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)

# This is intentionally code-controlled as well as data-controlled. A modified
# overlay cannot silently turn an arbitrary host into an approved source.
APPROVED_CANDIDATES: dict[str, dict[str, Any]] = {
    "SRC018-A02": {
        "url":
            "https://www.justice.gov.uk/courts/procedure-rules/civil/"
            "rules/raprnotes",
        "hosts": {"justice.gov.uk", "www.justice.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC021-A01": {
        "url":
            "https://www.gov.uk/government/organisations/"
            "tribunal-procedure-committee/about",
        "hosts": {"www.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC027-A01": {
        "url": "https://sentencingcouncil.org.uk/",
        "hosts": {
            "sentencingcouncil.org.uk",
            "www.sentencingcouncil.org.uk",
        },
        "classification": "official-public-body",
    },
    "SRC028-A01": {
        "url":
            "https://www.cps.gov.uk/prosecution-guidance/"
            "prosecution-guidance-search",
        "hosts": {"cps.gov.uk", "www.cps.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC029-A02": {
        "url":
            "https://www.copfs.gov.uk/publications/"
            "code-of-practice-disclosure-of-evidence-in-criminal-proceedings/",
        "hosts": {"copfs.gov.uk", "www.copfs.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC030-A01": {
        "url":
            "https://www.ppsni.gov.uk/publications/code-prosecutors",
        "hosts": {"ppsni.gov.uk", "www.ppsni.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC031-A02": {
        "url":
            "https://www.fca.org.uk/about/how-we-regulate/handbook",
        "hosts": {"fca.org.uk", "www.fca.org.uk"},
        "classification": "official-public-body",
    },
    "SRC033-A02": {
        "url":
            "https://www.bankofengland.co.uk/prudential-regulation/"
            "pra-rulebook-website",
        "hosts": {"bankofengland.co.uk", "www.bankofengland.co.uk"},
        "classification": "official-public-body",
    },
    "SRC039-A01": {
        "url":
            "https://www.gov.uk/government/publications/"
            "enforcement-undertakings-accepted-by-the-environment-agency",
        "hosts": {"www.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC040-A02": {
        "url": "https://www.lgo.org.uk/decisions",
        "hosts": {"lgo.org.uk", "www.lgo.org.uk"},
        "classification": "official-public-body",
    },
    "SRC042-A02": {
        "url": "https://swf.spso.org.uk/case-summaries",
        "hosts": {"spso.org.uk", "swf.spso.org.uk", "www.spso.org.uk"},
        "classification": "official-public-body",
    },
    "SRC043-A01": {
        "url":
            "https://www.nipso.org.uk/our-findings/search-our-findings",
        "hosts": {"nipso.org.uk", "www.nipso.org.uk"},
        "classification": "official-public-body",
    },
    "SRC053-A01": {
        "url":
            "https://www.gov.uk/government/collections/"
            "public-inquiries-recommendations-and-the-government-response",
        "hosts": {"www.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC053-A02": {
        "url":
            "https://www.gov.uk/government/collections/"
            "public-inquiries-recommendations-and-the-government-response",
        "hosts": {"www.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC055-A02": {
        "url":
            "https://www.data.gov.uk/dataset/"
            "d2c13ffc-78ee-4ba8-9ee5-c87be9b7f24d/"
            "uk-treaties-database",
        "hosts": {"data.gov.uk", "www.data.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC057-A01": {
        "url": "https://op.europa.eu/en/web/cellar/documentation",
        "hosts": {"op.europa.eu"},
        "classification": "official-public-body",
    },
    "SRC064-A02": {
        "url": "https://www.mygov.scot/browse/crime-justice-law",
        "hosts": {"mygov.scot", "www.mygov.scot"},
        "classification": "official-public-body",
    },
    "SRC064-A03": {
        "url": "https://www.gov.wales/justice-and-law",
        "hosts": {"gov.wales", "www.gov.wales"},
        "classification": "official-public-body",
    },
    "SRC064-A04": {
        "url":
            "https://www.nidirect.gov.uk/information-and-services/"
            "crime-justice-and-law",
        "hosts": {"nidirect.gov.uk", "www.nidirect.gov.uk"},
        "classification": "official-public-body",
    },
    "SRC069-A02": {
        "url":
            "https://www.lexisnexis.co.uk/products/legal-industry",
        "hosts": {"lexisnexis.co.uk", "www.lexisnexis.co.uk"},
        "classification": "primary-source-operator",
    },
}
APPROVED_SUPPLEMENTS: dict[str, dict[str, Any]] = {
    "SRC029-A02-R02": {
        "method_id": "SRC029-A02",
        "url":
            "https://www.copfs.gov.uk/media/03znmxlq/"
            "code-of-practice-disclosure-of-evidence-in-criminal-proceedings.pdf",
        "previous_url":
            "https://www.copfs.gov.uk/publications/"
            "code-of-practice-disclosure-of-evidence-in-criminal-proceedings/",
        "hosts": {"copfs.gov.uk", "www.copfs.gov.uk"},
        "classification": "official-public-body",
        "supplements_replacement_id": "SRC029-A02-R01",
        "transport": "python-urllib-strict",
    },
    "SRC029-A02-R03": {
        "method_id": "SRC029-A02",
        "url":
            "https://www.copfs.gov.uk/media/03znmxlq/"
            "code-of-practice-disclosure-of-evidence-in-criminal-proceedings.pdf",
        "previous_url":
            "https://www.copfs.gov.uk/media/03znmxlq/"
            "code-of-practice-disclosure-of-evidence-in-criminal-proceedings.pdf",
        "hosts": {"copfs.gov.uk", "www.copfs.gov.uk"},
        "classification": "official-public-body",
        "supplements_replacement_id": "SRC029-A02-R02",
        "transport": "system-curl-secure",
    },
}


class UnsafeRouteError(ValueError):
    """Raised before an unsafe route or redirect can be requested."""


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def isoformat(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    return f"{utc_now():%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def normalize_hostname(value: str) -> str:
    try:
        return value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise UnsafeRouteError(f"invalid internationalized hostname: {value}") from error


def validate_public_url(
    url: str,
    allowed_hosts: set[str],
    *,
    resolve: bool,
) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    hostname = normalize_hostname(parsed.hostname or "")
    if parsed.scheme != "https":
        raise UnsafeRouteError(f"non-HTTPS route rejected: {url}")
    if not hostname or hostname not in allowed_hosts:
        raise UnsafeRouteError(f"non-allowlisted host rejected: {url}")
    if parsed.username or parsed.password:
        raise UnsafeRouteError(f"credential-bearing route rejected: {url}")
    if parsed.fragment:
        raise UnsafeRouteError(f"fragment-bearing route rejected: {url}")
    if parsed.port not in {None, 443}:
        raise UnsafeRouteError(f"non-default HTTPS port rejected: {url}")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise UnsafeRouteError(f"IP-literal route rejected: {url}")

    addresses: list[str] = []
    if resolve:
        try:
            answers = socket.getaddrinfo(
                hostname,
                443,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            raise UnsafeRouteError(
                f"DNS resolution failed for {hostname}: {error}"
            ) from error
        addresses = sorted({answer[4][0] for answer in answers})
        if not addresses:
            raise UnsafeRouteError(f"DNS returned no addresses for {hostname}")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise UnsafeRouteError(
                    f"non-public DNS address rejected for {hostname}: {address}"
                )
    return {
        "url": url,
        "scheme": parsed.scheme,
        "hostname": hostname,
        "port": parsed.port or 443,
        "resolved_addresses": addresses,
        "all_addresses_public": bool(addresses) if resolve else None,
    }


class GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(
        self,
        *,
        allowed_hosts: set[str],
        maximum_redirects: int,
    ) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.maximum_redirects = maximum_redirects
        self.redirect_chain: list[dict[str, Any]] = []

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        if len(self.redirect_chain) >= self.maximum_redirects:
            raise UnsafeRouteError(
                f"redirect limit exceeded at {request.full_url}"
            )
        resolution = validate_public_url(
            new_url,
            self.allowed_hosts,
            resolve=True,
        )
        self.redirect_chain.append(
            {
                "from_url": request.full_url,
                "http_status": int(code),
                "to_url": new_url,
                "target_resolution": resolution,
            }
        )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def validate_overlay(
    overlay_path: Path = OVERLAY,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    schema = base.load_json(OVERLAY_SCHEMA)
    overlay = base.load_json(overlay_path)
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(overlay),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path))}: {error.message}"
            for error in errors
        )
        raise ValueError(f"replacement overlay schema failed: {details}")

    if overlay["source_register"]["sha256"] != sha256_file(REGISTER):
        raise ValueError("replacement overlay source-register digest mismatch")
    if (
        overlay["superseded_observation"]["access_methods_sha256"]
        != sha256_file(BASE_OBSERVATIONS)
    ):
        raise ValueError("replacement overlay base-observation digest mismatch")
    base_observations = base.load_json(BASE_OBSERVATIONS)
    if (
        overlay["superseded_observation"]["evidence_run_id"]
        != base_observations["evidence_run_id"]
    ):
        raise ValueError("replacement overlay base run binding mismatch")

    register = base.load_json(REGISTER)
    registered = {
        row["method_id"]: row
        for row in base.enumerate_access_methods(register)
    }
    observed = {
        row["method_id"]: row for row in base_observations["records"]
    }
    stale_ids = {
        method_id
        for method_id, row in observed.items()
        if row["request_method"] == "GET"
        and row["observed_access_state"] in {"unavailable", "network-error"}
    }
    route_ids = {row["replaces_method_id"] for row in overlay["routes"]}
    supplement = overlay.get("supplements")
    if supplement is None:
        if route_ids != stale_ids or route_ids != set(APPROVED_CANDIDATES):
            raise ValueError(
                "replacement overlay does not exactly cover the reviewed "
                "stale set"
            )
    else:
        approved_parent_overlays = {
            COPFS_SUPPLEMENT.resolve(): OVERLAY,
            COPFS_SYSTEM_TRUST_SUPPLEMENT.resolve(): COPFS_SUPPLEMENT,
        }
        approved_parent = approved_parent_overlays.get(
            overlay_path.resolve()
        )
        if approved_parent is None:
            raise ValueError("supplement overlay path is not approved")
        parent_path = ROOT / supplement["overlay_path"]
        if parent_path.resolve() != approved_parent.resolve():
            raise ValueError("supplement parent overlay path is not approved")
        if supplement["overlay_sha256"] != sha256_file(approved_parent):
            raise ValueError("supplement parent overlay digest mismatch")
        parent_archive, parent_receipt = archive_paths(
            supplement["evidence_run_id"]
        )
        if not parent_archive.is_file() or not parent_receipt.is_file():
            raise ValueError("supplement parent evidence is not sealed")
        parent_validation, parent_files = archive_tools.validate_archive(
            parent_archive,
            parent_receipt,
        )
        if (
            parent_validation["archive_sha256"]
            != supplement["archive_sha256"]
        ):
            raise ValueError("supplement parent archive digest mismatch")
        parent_manifest = json.loads(parent_files["manifest.json"])
        if (
            parent_manifest["bindings"]["overlay_sha256"]
            != supplement["overlay_sha256"]
        ):
            raise ValueError("supplement parent run overlay binding mismatch")
        if len(overlay["routes"]) != 1:
            raise ValueError("reviewed COPFS supplement must contain one route")
        approved_route = APPROVED_SUPPLEMENTS.get(
            overlay["routes"][0]["replacement_id"]
        )
        if approved_route is None:
            raise ValueError("supplement replacement ID is not reviewed")
        if route_ids != {approved_route["method_id"]}:
            raise ValueError("supplement method binding is not reviewed")
    if supplement is None and len(overlay["routes"]) != len(route_ids):
        raise ValueError("replacement overlay has duplicate method bindings")
    replacement_ids = [row["replacement_id"] for row in overlay["routes"]]
    if len(replacement_ids) != len(set(replacement_ids)):
        raise ValueError("replacement overlay has duplicate replacement IDs")

    routes: dict[str, dict[str, Any]] = {}
    for route in overlay["routes"]:
        method_id = route["replaces_method_id"]
        expected = registered[method_id]
        approved = (
            APPROVED_CANDIDATES[method_id]
            if supplement is None
            else APPROVED_SUPPLEMENTS[route["replacement_id"]]
        )
        if route["source_id"] != expected["source_id"]:
            raise ValueError(f"{method_id} source binding changed")
        expected_previous = (
            expected["url"]
            if supplement is None
            else approved["previous_url"]
        )
        if route["previous_url"] != expected_previous:
            raise ValueError(f"{method_id} replacement lineage changed")
        if supplement is not None and (
            route.get("supplements_replacement_id")
            != approved["supplements_replacement_id"]
        ):
            raise ValueError(f"{method_id} supplement lineage changed")
        if route["url"] != approved["url"]:
            raise ValueError(f"{method_id} replacement is not reviewed")
        if set(route["allowed_redirect_hosts"]) != approved["hosts"]:
            raise ValueError(f"{method_id} redirect allowlist changed")
        if (
            route["officiality"]["classification"]
            != approved["classification"]
        ):
            raise ValueError(f"{method_id} officiality changed")
        expected_transport = approved.get(
            "transport",
            "python-urllib-strict",
        )
        if route.get("transport", "python-urllib-strict") != expected_transport:
            raise ValueError(f"{method_id} transport changed")
        validate_public_url(
            route["url"],
            set(route["allowed_redirect_hosts"]),
            resolve=False,
        )
        routes[method_id] = route
    return overlay, routes


def safe_schema_fingerprint(
    body: bytes,
    headers: dict[str, str],
    final_url: str,
    max_body_bytes: int,
) -> dict[str, Any]:
    content_encoding = headers.get("content-encoding", "").lower()
    if content_encoding or body.startswith(b"\x1f\x8b"):
        signature = {
            "kind": "compressed-unparsed",
            "signals": {
                "content_encoding": content_encoding or "gzip-signature",
                "media_type": headers.get("content-type"),
            },
        }
        return {
            **signature,
            "fingerprint_sha256": base.sha256_bytes(
                base.canonical_json_bytes(signature)
            ),
        }
    if UNSAFE_XML.search(body[:4096]):
        signature = {
            "kind": "xml-declaration-rejected",
            "signals": {
                "unsafe_declaration_present": True,
                "parser_invoked": False,
            },
        }
        return {
            **signature,
            "fingerprint_sha256": base.sha256_bytes(
                base.canonical_json_bytes(signature)
            ),
        }
    return base.schema_fingerprint(
        body,
        headers,
        final_url,
        max_body_bytes,
    )


def curl_version_record() -> dict[str, Any]:
    executable = Path("/usr/bin/curl")
    if not executable.is_file() or executable.is_symlink():
        raise UnsafeRouteError("fixed system curl executable is unavailable")
    result = subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    lines = result.stdout.splitlines()
    if not lines or not lines[0].startswith("curl "):
        raise UnsafeRouteError("cannot identify fixed system curl")
    return {
        "path": str(executable),
        "sha256": sha256_file(executable),
        "version_line": lines[0],
        "feature_line": lines[1] if len(lines) > 1 else None,
        "peer_verification_disabled": False,
        "hostname_verification_disabled": False,
        "curlrc_loaded": False,
    }


def select_pinned_address(resolution: dict[str, Any]) -> str:
    addresses = [
        ipaddress.ip_address(value)
        for value in resolution["resolved_addresses"]
    ]
    public = [address for address in addresses if address.is_global]
    if len(public) != len(addresses) or not public:
        raise UnsafeRouteError("cannot pin curl to a public DNS address")
    return str(
        sorted(
            public,
            key=lambda address: (
                0 if address.version == 4 else 1,
                int(address),
            ),
        )[0]
    )


def build_curl_command(
    *,
    url: str,
    resolution: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
    max_body_bytes: int,
) -> tuple[list[str], str]:
    hostname = resolution["hostname"]
    pinned_address = select_pinned_address(resolution)
    resolve_address = (
        f"[{pinned_address}]"
        if ipaddress.ip_address(pinned_address).version == 6
        else pinned_address
    )
    command = [
        "/usr/bin/curl",
        "--disable",
        "--silent",
        "--show-error",
        "--request",
        "GET",
        "--proto",
        "=https",
        "--proto-redir",
        "=https",
        "--max-redirs",
        "0",
        "--connect-timeout",
        str(timeout_seconds),
        "--max-time",
        str(timeout_seconds),
        "--range",
        f"0-{max_body_bytes - 1}",
        "--max-filesize",
        str(max_body_bytes),
        "--resolve",
        f"{hostname}:443:{resolve_address}",
        "--dump-header",
        "/dev/stderr",
        "--write-out",
        (
            "%{stderr}\\n__OKF_META__%{http_code}\\t%{content_type}\\t"
            "%{url_effective}\\t%{num_redirects}\\t%{remote_ip}\\t"
            "%{ssl_verify_result}\\t%{size_download}\\n"
        ),
        "--output",
        "-",
    ]
    for name, value in sorted(headers.items()):
        command.extend(["--header", f"{name}: {value}"])
    command.append(url)
    return command, pinned_address


def parse_curl_stderr(
    stderr: bytes,
) -> tuple[int | None, dict[str, str], dict[str, Any]]:
    text = stderr.decode("iso-8859-1", errors="replace")
    marker = "__OKF_META__"
    marker_lines = [
        line[len(marker) :]
        for line in text.splitlines()
        if line.startswith(marker)
    ]
    if not marker_lines:
        metadata = {
            "http_code": None,
            "content_type": None,
            "url_effective": None,
            "num_redirects": 0,
            "remote_ip": None,
            "ssl_verify_result": None,
            "size_download": 0,
        }
    else:
        fields = marker_lines[-1].split("\t")
        if len(fields) != 7:
            raise ValueError("unexpected curl metadata field count")
        metadata = {
            "http_code": int(fields[0]) if fields[0].isdigit() else None,
            "content_type": fields[1] or None,
            "url_effective": fields[2] or None,
            "num_redirects": int(fields[3]),
            "remote_ip": fields[4] or None,
            "ssl_verify_result": (
                int(fields[5]) if fields[5].lstrip("-").isdigit() else None
            ),
            "size_download": (
                int(float(fields[6])) if fields[6] else 0
            ),
        }

    lines = text.splitlines()
    status_positions = [
        index
        for index, line in enumerate(lines)
        if line.startswith("HTTP/")
    ]
    headers: dict[str, str] = {}
    status: int | None = metadata["http_code"]
    if status_positions:
        position = status_positions[-1]
        status_fields = lines[position].split()
        if len(status_fields) >= 2 and status_fields[1].isdigit():
            status = int(status_fields[1])
        for line in lines[position + 1 :]:
            if not line:
                break
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            normalized = name.strip().lower()
            if normalized not in headers:
                headers[normalized] = value.strip()
    safe_headers, received, sensitive = base.safe_response_headers(headers)
    metadata["received_header_names"] = received
    metadata["sensitive_header_names_present_but_not_stored"] = sensitive
    return status, safe_headers, metadata


def curl_hop(
    *,
    url: str,
    allowed_hosts: set[str],
    headers: dict[str, str],
    timeout_seconds: float,
    max_body_bytes: int,
) -> dict[str, Any]:
    resolution = validate_public_url(
        url,
        allowed_hosts,
        resolve=True,
    )
    command, pinned_address = build_curl_command(
        url=url,
        resolution=resolution,
        headers=headers,
        timeout_seconds=timeout_seconds,
        max_body_bytes=max_body_bytes,
    )
    forbidden = {"--insecure", "-k", "--location", "-L"}
    if forbidden & set(command):
        raise UnsafeRouteError("unsafe curl option generated")
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout_seconds + 5,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "url": url,
            "resolution": resolution,
            "pinned_address": pinned_address,
            "status": None,
            "headers": {},
            "body": b"",
            "truncated": False,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "transport": {
                **curl_version_record(),
                "exit_code": None,
                "ssl_verify_result": None,
                "remote_ip": None,
                "timed_out": True,
            },
            "error": {
                "type": "TimeoutExpired",
                "message": (
                    "Strict system-trust curl exceeded the bounded timeout."
                ),
            },
        }
    status, response_headers, metadata = parse_curl_stderr(result.stderr)
    body = result.stdout
    if len(body) > max_body_bytes:
        raise UnsafeRouteError("system curl exceeded the response-body bound")
    ssl_result = metadata["ssl_verify_result"]
    remote_ip = metadata["remote_ip"]
    if status is not None and status > 0:
        if ssl_result != 0:
            raise UnsafeRouteError(
                "system curl did not report successful TLS verification"
            )
        if remote_ip is None:
            raise UnsafeRouteError("system curl omitted the connected address")
        if (
            ipaddress.ip_address(remote_ip)
            != ipaddress.ip_address(pinned_address)
        ):
            raise UnsafeRouteError(
                "system curl connected to an address other than the DNS pin"
            )
    size_limited = result.returncode == 63
    error = None
    if result.returncode != 0:
        error = {
            "type": "CurlExit",
            "code": result.returncode,
            "message": (
                "The strict system-trust transport enforced its body-size "
                "limit."
                if size_limited
                else "The strict system-trust transport did not complete."
            ),
        }
    return {
        "url": url,
        "resolution": resolution,
        "pinned_address": pinned_address,
        "status": status if status and status > 0 else None,
        "headers": response_headers,
        "body": body,
        "truncated": size_limited or len(body) == max_body_bytes,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "transport": {
            **curl_version_record(),
            "exit_code": result.returncode,
            "ssl_verify_result": ssl_result,
            "remote_ip": remote_ip,
            "timed_out": False,
            "https_protocol_only": True,
            "automatic_redirects_followed": False,
            "dns_pin_used": True,
            "cookie_engine_enabled": False,
            "body_size_limit_bytes": max_body_bytes,
        },
        "metadata": metadata,
        "error": error,
    }


def capture_route_system_curl(
    method: dict[str, Any],
    route: dict[str, Any],
    *,
    timeout_seconds: float,
    max_body_bytes: int,
    user_agent: str,
    maximum_redirects: int,
) -> dict[str, Any]:
    allowed_hosts = set(route["allowed_redirect_hosts"])
    headers = base.request_headers(method, max_body_bytes, user_agent)
    started = utc_now()
    current_url = route["url"]
    hops: list[dict[str, Any]] = []
    redirect_chain: list[dict[str, Any]] = []
    while True:
        hop = curl_hop(
            url=current_url,
            allowed_hosts=allowed_hosts,
            headers=headers,
            timeout_seconds=timeout_seconds,
            max_body_bytes=max_body_bytes,
        )
        hops.append(hop)
        status = hop["status"]
        location = hop["headers"].get("location")
        if status is None or not 300 <= status < 400:
            break
        if len(redirect_chain) >= maximum_redirects:
            raise UnsafeRouteError("manual curl redirect limit exceeded")
        if not location:
            break
        new_url = urllib.parse.urljoin(current_url, location)
        target_resolution = validate_public_url(
            new_url,
            allowed_hosts,
            resolve=True,
        )
        redirect_chain.append(
            {
                "from_url": current_url,
                "http_status": status,
                "to_url": new_url,
                "target_resolution": target_resolution,
                "followed_by": "manual-allowlist-validated-system-curl-hop",
            }
        )
        current_url = new_url

    final = hops[-1]
    status = final["status"]
    error = final["error"]
    observed_state = base.classify_http_observation(
        status,
        error["type"] if error and status is None else None,
    )
    comparison = base.compare_with_research_claim(method, observed_state)
    request_record = {
        "method": "GET",
        "url": route["url"],
        "headers": {key.lower(): value for key, value in headers.items()},
        "body": None,
        "scope": "bounded-public-response",
        "network_security": {
            "transport": "system-curl-secure",
            "allowed_redirect_hosts": sorted(allowed_hosts),
            "maximum_redirects": maximum_redirects,
            "credentials_used": False,
            "authentication_bypass_attempted": False,
            "private_network_destinations_allowed": False,
            "curlrc_loaded": False,
            "peer_verification_disabled": False,
            "hostname_verification_disabled": False,
            "automatic_redirects_followed": False,
            "manual_hops": [
                {
                    "url": hop["url"],
                    "resolution": hop["resolution"],
                    "pinned_address": hop["pinned_address"],
                    "transport": hop["transport"],
                }
                for hop in hops
            ],
        },
    }
    body = final["body"]
    response_record = {
        "observed_at": isoformat(started),
        "status": status,
        "reason": None,
        "final_url": current_url,
        "duration_ms": sum(hop["duration_ms"] for hop in hops),
        "headers": final["headers"],
        "received_header_names": final.get("metadata", {}).get(
            "received_header_names",
            [],
        ),
        "sensitive_header_names_present_but_not_stored": final.get(
            "metadata",
            {},
        ).get("sensitive_header_names_present_but_not_stored", []),
        "media_type": final["headers"].get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
        or None,
        "body": {
            "captured_bytes": len(body),
            "capture_limit_bytes": max_body_bytes,
            "truncated": final["truncated"],
            "sha256": base.sha256_bytes(body),
            "stored_path": "body.bin" if body else None,
            "hash_scope": "captured-prefix-only",
            "content_treatment": "untrusted-bounded-bytes-no-execution",
        },
        "schema_fingerprint": safe_schema_fingerprint(
            body,
            final["headers"],
            current_url,
            max_body_bytes,
        )
        if body
        else None,
        "redirect_chain": redirect_chain,
        "transport_receipts": [
            {
                "url": hop["url"],
                "status": hop["status"],
                "resolution": hop["resolution"],
                "pinned_address": hop["pinned_address"],
                "transport": hop["transport"],
            }
            for hop in hops
        ],
        "error": error,
    }
    return {
        "method": method,
        "route": route,
        "body": body,
        "request": request_record,
        "request_sha256": base.sha256_bytes(
            base.canonical_json_bytes(request_record)
        ),
        "response": response_record,
        "observed_access_state": observed_state,
        "comparison": comparison,
    }


def capture_route(
    method: dict[str, Any],
    route: dict[str, Any],
    *,
    timeout_seconds: float,
    max_body_bytes: int,
    user_agent: str,
    maximum_redirects: int,
) -> dict[str, Any]:
    if route.get("transport") == "system-curl-secure":
        return capture_route_system_curl(
            method,
            route,
            timeout_seconds=timeout_seconds,
            max_body_bytes=max_body_bytes,
            user_agent=user_agent,
            maximum_redirects=maximum_redirects,
        )
    allowed_hosts = set(route["allowed_redirect_hosts"])
    initial_resolution = validate_public_url(
        route["url"],
        allowed_hosts,
        resolve=True,
    )
    headers = base.request_headers(method, max_body_bytes, user_agent)
    request = urllib.request.Request(
        route["url"],
        headers=headers,
        method="GET",
    )
    redirect_handler = GuardedRedirectHandler(
        allowed_hosts=allowed_hosts,
        maximum_redirects=maximum_redirects,
    )
    opener = urllib.request.build_opener(redirect_handler)
    started = utc_now()
    monotonic_start = time.monotonic()
    status: int | None = None
    reason: str | None = None
    final_url = route["url"]
    response_headers: dict[str, str] = {}
    received_header_names: list[str] = []
    sensitive_header_names: list[str] = []
    body = b""
    truncated = False
    error: dict[str, str] | None = None
    try:
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                status = int(response.status)
                reason = str(response.reason) if response.reason else None
                final_url = response.geturl()
                validate_public_url(final_url, allowed_hosts, resolve=True)
                (
                    response_headers,
                    received_header_names,
                    sensitive_header_names,
                ) = base.safe_response_headers(response.headers)
                fetched = response.read(max_body_bytes + 1)
                truncated = len(fetched) > max_body_bytes
                body = fetched[:max_body_bytes]
        except urllib.error.HTTPError as http_error:
            status = int(http_error.code)
            reason = str(http_error.reason) if http_error.reason else None
            final_url = http_error.geturl()
            validate_public_url(final_url, allowed_hosts, resolve=True)
            (
                response_headers,
                received_header_names,
                sensitive_header_names,
            ) = base.safe_response_headers(http_error.headers)
            fetched = http_error.read(max_body_bytes + 1)
            truncated = len(fetched) > max_body_bytes
            body = fetched[:max_body_bytes]
    except UnsafeRouteError:
        raise
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
    duration_ms = round((time.monotonic() - monotonic_start) * 1000)
    observed_state = base.classify_http_observation(
        status,
        error["type"] if error else None,
    )
    comparison = base.compare_with_research_claim(method, observed_state)
    request_record = {
        "method": "GET",
        "url": route["url"],
        "headers": {key.lower(): value for key, value in headers.items()},
        "body": None,
        "scope": "bounded-public-response",
        "network_security": {
            "initial_resolution": initial_resolution,
            "allowed_redirect_hosts": sorted(allowed_hosts),
            "maximum_redirects": maximum_redirects,
            "credentials_used": False,
            "authentication_bypass_attempted": False,
            "private_network_destinations_allowed": False,
        },
    }
    response_record = {
        "observed_at": isoformat(started),
        "status": status,
        "reason": reason,
        "final_url": final_url,
        "duration_ms": duration_ms,
        "headers": response_headers,
        "received_header_names": received_header_names,
        "sensitive_header_names_present_but_not_stored":
            sensitive_header_names,
        "media_type": response_headers.get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
        or None,
        "body": {
            "captured_bytes": len(body),
            "capture_limit_bytes": max_body_bytes,
            "truncated": truncated,
            "sha256": base.sha256_bytes(body),
            "stored_path": "body.bin" if body else None,
            "hash_scope": "captured-prefix-only",
            "content_treatment": "untrusted-bounded-bytes-no-execution",
        },
        "schema_fingerprint": safe_schema_fingerprint(
            body,
            response_headers,
            final_url,
            max_body_bytes,
        )
        if body
        else None,
        "redirect_chain": redirect_handler.redirect_chain,
        "error": error,
    }
    return {
        "method": method,
        "route": route,
        "body": body,
        "request": request_record,
        "request_sha256": base.sha256_bytes(
            base.canonical_json_bytes(request_record)
        ),
        "response": response_record,
        "observed_access_state": observed_state,
        "comparison": comparison,
    }


def replacement_methods(
    overlay: dict[str, Any],
    routes: dict[str, dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    register = base.load_json(REGISTER)
    registered = {
        method["method_id"]: method
        for method in base.enumerate_access_methods(register)
    }
    result = []
    for route_record in overlay["routes"]:
        method = json.loads(
            json.dumps(registered[route_record["replaces_method_id"]])
        )
        method["url"] = route_record["url"]
        method["request_method"] = "GET"
        method["probe_scope"] = "bounded-public-response"
        result.append((method, routes[method["method_id"]]))
    return sorted(result, key=lambda pair: pair[1]["replacement_id"])


def build_constraint_ledger(
    captures: list[dict[str, Any]],
    *,
    run_id: str,
    generated_at: str,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    base_ledger = base.load_json(BASE_CONSTRAINTS)
    base_constraints = json.loads(json.dumps(base_ledger["constraints"]))
    additions = []
    for capture in captures:
        route = capture["route"]
        state = capture["observed_access_state"]
        additions.append(
            {
                "id": (
                    f"CON-{route['replacement_id']}-"
                    "REPLACEMENT-AVAILABILITY"
                ),
                "source_id": route["source_id"],
                "kind": "availability",
                "trigger": (
                    f"Replacement route {route['replacement_id']} observed "
                    f"as {state} in delta run {run_id}."
                ),
                "effect": (
                    "This dated result supplements but never rewrites the "
                    "original stale-route observation."
                ),
                "mitigation": (
                    "Use the frozen replacement envelope and redirect chain; "
                    "retain the original run and repeat only as a new attempt."
                ),
                "owner": "UK Whole-Law OKF source monitoring owner",
                "escalation_state": (
                    "resolved" if state == "reachable" else "escalated"
                ),
                "triggered_during_capture": state != "reachable",
                "evidence_run_id": run_id,
                "replacement_id": route["replacement_id"],
                "replaces_method_id": route["replaces_method_id"],
            }
        )
    constraints = base_constraints + additions
    refs: dict[str, list[str]] = defaultdict(list)
    for row in constraints:
        refs[row["source_id"]].append(row["id"])
    ledger = {
        "schema": base.CONSTRAINT_SCHEMA,
        "generated_at": generated_at,
        "evidence_run_id": run_id,
        "base_ledger": {
            "path": str(BASE_CONSTRAINTS.relative_to(ROOT)),
            "sha256": sha256_file(BASE_CONSTRAINTS),
            "constraints_preserved_verbatim": len(base_constraints),
            "base_evidence_run_id": base_ledger["evidence_run_id"],
        },
        "policy": (
            "All published base constraints are preserved verbatim. Delta "
            "availability records supplement them; no licence, fair-use, "
            "authentication, privacy, rate, robots or hosting constraint is "
            "removed or treated as permission."
        ),
        "constraints": constraints,
        "counts": {
            **base.constraint_counts(constraints),
            "base_preserved": len(base_constraints),
            "delta_added": len(additions),
        },
    }
    return ledger, refs


def observation_projection(
    capture: dict[str, Any],
    run_id: str,
    envelope_path: str,
) -> dict[str, Any]:
    method = capture["method"]
    route = capture["route"]
    response = capture["response"]
    return {
        "replacement_id": route["replacement_id"],
        "replaces_method_id": route["replaces_method_id"],
        "method_id": method["method_id"],
        "source_id": method["source_id"],
        "source_title": method["source_title"],
        "owning_institution": method["owning_institution"],
        "kind": method["kind"],
        "previous_url": route["previous_url"],
        "url": route["url"],
        "officiality": route["officiality"],
        "denominator": route["denominator"],
        "research_claim": method["research_claim"],
        "request_method": "GET",
        "probe_scope": "bounded-public-response",
        "observed_at": response["observed_at"],
        "http_status": response["status"],
        "final_url": response["final_url"],
        "redirect_chain": response["redirect_chain"],
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
        "evidence_envelope": envelope_path,
    }


def run_integrity(run_dir: Path) -> dict[str, Any]:
    return base.run_integrity(run_dir)


def write_run(
    captures: list[dict[str, Any]],
    *,
    run_id: str,
    started_at: str,
    completed_at: str,
    args: argparse.Namespace,
    overlay: dict[str, Any],
    overlay_path: Path,
    partial_dir: Path,
) -> None:
    ledger, refs = build_constraint_ledger(
        captures,
        run_id=run_id,
        generated_at=completed_at,
    )
    rows = []
    overlay_sha256 = sha256_file(overlay_path)
    for capture in captures:
        method = capture["method"]
        route = capture["route"]
        method_dir = partial_dir / "methods" / route["replacement_id"]
        envelope_relpath = (
            Path("methods") / route["replacement_id"] / "envelope.json"
        ).as_posix()
        envelope = {
            "schema": base.EVIDENCE_SCHEMA,
            "attempt_id": f"{run_id}/{route['replacement_id']}",
            "run_id": run_id,
            "method_id": method["method_id"],
            "replacement": {
                **route,
                "overlay_id": overlay["overlay_id"],
                "overlay_sha256": overlay_sha256,
            },
            "source": {
                "id": method["source_id"],
                "title": method["source_title"],
                "owning_institution": method["owning_institution"],
                "authority_classes": method["authority_classes"],
                "source_classes": method["source_classes"],
            },
            "access_method": {
                "kind": method["kind"],
                "url": route["url"],
                "previous_url": route["previous_url"],
            },
            "research_claim": method["research_claim"],
            "request": capture["request"],
            "request_sha256": capture["request_sha256"],
            "response": capture["response"],
            "access_assessment": {
                "observed_access_state": capture["observed_access_state"],
                **capture["comparison"],
            },
            "constraint_refs": refs[method["source_id"]],
            "tool": {
                "name": base.TOOL_NAME,
                "version": TOOL_VERSION,
                "capability": "replacement-route-overlay.v1",
                "python": sys.version.split()[0],
                "policy": (
                    "one bounded reviewed HTTPS replacement route; public DNS "
                    "and redirect allowlist enforced; no credentials, cookies, "
                    "forms, crawling or authentication bypass"
                ),
            },
        }
        if capture["body"]:
            base.write_new_bytes(method_dir / "body.bin", capture["body"])
        base.write_new_json(method_dir / "envelope.json", envelope)
        rows.append(
            observation_projection(capture, run_id, envelope_relpath)
        )
    observations = {
        "schema": OBSERVATION_SCHEMA,
        "generated_at": completed_at,
        "evidence_run_id": run_id,
        "source_register": str(REGISTER.relative_to(ROOT)),
        "source_register_sha256": sha256_file(REGISTER),
        "overlay": {
            "path": str(overlay_path.relative_to(ROOT)),
            "id": overlay["overlay_id"],
            "sha256": overlay_sha256,
        },
        "records": rows,
    }
    result_counts = dict(
        sorted(Counter(row["observed_access_state"] for row in rows).items())
    )
    comparison = {
        "schema": "okf-source-route-replacement-comparison.v1",
        "generated_at": completed_at,
        "evidence_run_id": run_id,
        "counts": {
            "replacement_routes": len(rows),
            "observed_access_state": result_counts,
            "redirects": sum(len(row["redirect_chain"]) for row in rows),
        },
        "records": [
            {
                "replacement_id": row["replacement_id"],
                "replaces_method_id": row["replaces_method_id"],
                "previous_url": row["previous_url"],
                "url": row["url"],
                "final_url": row["final_url"],
                "http_status": row["http_status"],
                "observed_access_state": row["observed_access_state"],
                "redirect_chain": row["redirect_chain"],
            }
            for row in rows
        ],
    }
    manifest = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "tool": {
            "name": base.TOOL_NAME,
            "version": TOOL_VERSION,
            "capability": "replacement-route-overlay.v1",
            "python": sys.version.split()[0],
        },
        "bindings": {
            "overlay_path": str(overlay_path.relative_to(ROOT)),
            "overlay_sha256": overlay_sha256,
            "source_register_path": str(REGISTER.relative_to(ROOT)),
            "source_register_sha256": sha256_file(REGISTER),
            "base_observations_path": str(BASE_OBSERVATIONS.relative_to(ROOT)),
            "base_observations_sha256": sha256_file(BASE_OBSERVATIONS),
            "base_constraint_ledger_path": str(
                BASE_CONSTRAINTS.relative_to(ROOT)
            ),
            "base_constraint_ledger_sha256": sha256_file(BASE_CONSTRAINTS),
            "superseded_evidence_run_id":
                overlay["superseded_observation"]["evidence_run_id"],
        },
        "policy": {
            "requests_made": len(rows),
            "request_method": "GET",
            "transports": dict(
                sorted(
                    Counter(
                        capture["route"].get(
                            "transport",
                            "python-urllib-strict",
                        )
                        for capture in captures
                    ).items()
                )
            ),
            "timeout_seconds": args.timeout,
            "max_body_bytes": args.max_body_bytes,
            "maximum_redirects": overlay["policy"]["maximum_redirects"],
            "https_allowlist_only": True,
            "public_dns_addresses_only": True,
            "credentials_used": False,
            "authentication_bypass_attempted": False,
            "cookies_sent": False,
            "form_submissions": False,
            "pagination_or_crawling": False,
            "downloaded_content_executed": False,
            "unsafe_xml_parsed": False,
            "compressed_content_decompressed": False,
        },
        "coverage": {
            "replacement_routes_in_overlay": len(overlay["routes"]),
            "replacement_routes_attempted": len(rows),
            "complete_overlay_attempt": len(rows) == len(overlay["routes"]),
            "source_records_attempted": len({row["source_id"] for row in rows}),
            "exact_route_denominators": sum(
                row["denominator"]["replacement_route_count"] == 1
                for row in rows
            ),
            "exact_corpus_enumerations": sum(
                row["denominator"]["corpus_enumeration_exact"]
                for row in rows
            ),
        },
        "result_counts": result_counts,
        "files": {
            "observations": "observations.json",
            "comparison": "comparison.json",
            "constraint_ledger": "source-constraint-ledger.json",
            "integrity": "integrity.json",
        },
    }
    base.write_new_json(partial_dir / "observations.json", observations)
    base.write_new_json(partial_dir / "comparison.json", comparison)
    base.write_new_json(
        partial_dir / "source-constraint-ledger.json",
        ledger,
    )
    base.write_new_json(partial_dir / "manifest.json", manifest)
    base.write_new_json(
        partial_dir / "complete.json",
        {"complete": True, "completed_at": completed_at, "run_id": run_id},
    )
    base.write_new_json(partial_dir / "integrity.json", run_integrity(partial_dir))


def validate_delta_files(
    files: dict[str, bytes],
    *,
    expected_run_id: str,
) -> dict[str, Any]:
    manifest = json.loads(files["manifest.json"])
    approved_overlay_paths = {
        str(OVERLAY.relative_to(ROOT)): OVERLAY,
        str(COPFS_SUPPLEMENT.relative_to(ROOT)): COPFS_SUPPLEMENT,
        str(COPFS_SYSTEM_TRUST_SUPPLEMENT.relative_to(ROOT)):
            COPFS_SYSTEM_TRUST_SUPPLEMENT,
    }
    overlay_relative = manifest.get("bindings", {}).get("overlay_path")
    overlay_path = approved_overlay_paths.get(overlay_relative)
    if overlay_path is None:
        raise ValueError("replacement-run overlay path is not approved")
    overlay, routes = validate_overlay(overlay_path)
    observations = json.loads(files["observations.json"])
    constraints = json.loads(files["source-constraint-ledger.json"])
    if manifest.get("schema") != RUN_SCHEMA:
        raise ValueError("unexpected replacement-run schema")
    if manifest.get("run_id") != expected_run_id:
        raise ValueError("replacement-run ID mismatch")
    if manifest["bindings"]["overlay_sha256"] != sha256_file(overlay_path):
        raise ValueError("replacement-run overlay digest mismatch")
    if manifest["bindings"]["source_register_sha256"] != sha256_file(REGISTER):
        raise ValueError("replacement-run register digest mismatch")
    if (
        manifest["bindings"]["base_observations_sha256"]
        != sha256_file(BASE_OBSERVATIONS)
    ):
        raise ValueError("replacement-run base observation digest mismatch")
    if (
        manifest["bindings"]["base_constraint_ledger_sha256"]
        != sha256_file(BASE_CONSTRAINTS)
    ):
        raise ValueError("replacement-run base constraint digest mismatch")
    rows = observations.get("records", [])
    if len(rows) != len(overlay["routes"]):
        raise ValueError("replacement-run does not cover its complete overlay")
    if {row["replaces_method_id"] for row in rows} != set(routes):
        raise ValueError("replacement-run method coverage mismatch")
    if len({row["replacement_id"] for row in rows}) != len(rows):
        raise ValueError("replacement-run has duplicate replacement IDs")

    base_ledger = base.load_json(BASE_CONSTRAINTS)
    base_rows = base_ledger["constraints"]
    if (
        constraints["constraints"][: len(base_rows)] != base_rows
        or constraints["counts"]["base_preserved"] != len(base_rows)
    ):
        raise ValueError("base constraint ledger was not preserved verbatim")
    source_ids = {
        row["id"] for row in base.load_json(REGISTER)["records"]
    }
    base.validate_constraint_ledger(constraints, source_ids)

    envelope_schema = base.load_json(
        ROOT / "whole-law" / "acquisition" / "source-access-envelope.schema.json"
    )
    envelope_validator = Draft202012Validator(
        envelope_schema,
        format_checker=FormatChecker(),
    )
    for row in rows:
        route = routes[row["replaces_method_id"]]
        if row["replacement_id"] != route["replacement_id"]:
            raise ValueError("replacement ID binding mismatch")
        if row["url"] != route["url"] or row["previous_url"] != route["previous_url"]:
            raise ValueError("replacement URL lineage mismatch")
        envelope_path = row["evidence_envelope"]
        envelope = json.loads(files[envelope_path])
        envelope_validator.validate(envelope)
        if (
            envelope["replacement"]["overlay_sha256"]
            != sha256_file(overlay_path)
        ):
            raise ValueError("envelope overlay digest mismatch")
        if envelope["request"]["url"] != route["url"]:
            raise ValueError("envelope requested an unbound URL")
        if {"authorization", "cookie"} & set(envelope["request"]["headers"]):
            raise ValueError("credential-bearing request header found")
        for redirect in envelope["response"]["redirect_chain"]:
            validate_public_url(
                redirect["to_url"],
                set(route["allowed_redirect_hosts"]),
                resolve=False,
            )
            resolution = redirect["target_resolution"]
            for address in resolution["resolved_addresses"]:
                if not ipaddress.ip_address(address).is_global:
                    raise ValueError("non-public redirect address in evidence")
        if route.get("transport") == "system-curl-secure":
            security = envelope["request"]["network_security"]
            if (
                security.get("transport") != "system-curl-secure"
                or security.get("curlrc_loaded") is not False
                or security.get("peer_verification_disabled") is not False
                or security.get("hostname_verification_disabled") is not False
                or security.get("automatic_redirects_followed") is not False
            ):
                raise ValueError("system-trust transport policy is incomplete")
            receipts = envelope["response"].get("transport_receipts", [])
            if not receipts:
                raise ValueError("system-trust transport receipt is absent")
            for receipt in receipts:
                transport = receipt["transport"]
                if (
                    transport["path"] != "/usr/bin/curl"
                    or transport["sha256"]
                    != sha256_file(Path("/usr/bin/curl"))
                    or transport["ssl_verify_result"] != 0
                    or transport["peer_verification_disabled"] is not False
                    or transport["hostname_verification_disabled"] is not False
                    or transport["curlrc_loaded"] is not False
                    or transport["automatic_redirects_followed"] is not False
                    or transport["dns_pin_used"] is not True
                ):
                    raise ValueError(
                        "system-trust transport receipt failed closed"
                    )
                if (
                    ipaddress.ip_address(transport["remote_ip"])
                    != ipaddress.ip_address(receipt["pinned_address"])
                ):
                    raise ValueError("system-trust DNS pin was not honoured")
        else:
            initial = envelope["request"]["network_security"][
                "initial_resolution"
            ]
            for address in initial["resolved_addresses"]:
                if not ipaddress.ip_address(address).is_global:
                    raise ValueError("non-public initial address in evidence")
        body_record = envelope["response"]["body"]
        stored_path = body_record["stored_path"]
        if stored_path:
            body_path = (
                str(Path(envelope_path).parent / stored_path)
            )
            body = files.get(body_path)
            if body is None:
                raise ValueError(f"missing body evidence: {body_path}")
            if len(body) != body_record["captured_bytes"]:
                raise ValueError("body byte count mismatch")
            if base.sha256_bytes(body) != body_record["sha256"]:
                raise ValueError("body digest mismatch")
            if len(body) > manifest["policy"]["max_body_bytes"]:
                raise ValueError("body exceeds capture bound")
    return {
        "run_id": expected_run_id,
        "replacement_routes": len(rows),
        "source_records": len({row["source_id"] for row in rows}),
        "observed_access_state": dict(
            sorted(Counter(row["observed_access_state"] for row in rows).items())
        ),
        "redirects": sum(len(row["redirect_chain"]) for row in rows),
        "base_constraints_preserved":
            constraints["counts"]["base_preserved"],
        "delta_constraints_added": constraints["counts"]["delta_added"],
        "exact_route_denominators":
            manifest["coverage"]["exact_route_denominators"],
        "exact_corpus_enumerations":
            manifest["coverage"]["exact_corpus_enumerations"],
    }


def archive_paths(run_id: str) -> tuple[Path, Path]:
    return (
        ARCHIVE_ROOT / f"{run_id}.tar.xz",
        RECEIPT_ROOT / f"{run_id}.json",
    )


def resolve_archive(run_argument: str) -> tuple[Path, Path]:
    if run_argument != "latest":
        if not RUN_ID_RE.fullmatch(run_argument):
            raise ValueError(f"invalid replacement run ID: {run_argument}")
        paths = archive_paths(run_argument)
        if not paths[0].is_file() or not paths[1].is_file():
            raise FileNotFoundError(
                f"sealed replacement archive not found: {run_argument}"
            )
        return paths
    receipts = sorted(RECEIPT_ROOT.glob("*.json"))
    if not receipts:
        raise FileNotFoundError("no sealed replacement archive found")
    return archive_paths(receipts[-1].stem)


def validate_archive(
    archive_path: Path,
    receipt_path: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    archive_validation, files = archive_tools.validate_archive(
        archive_path,
        receipt_path,
    )
    delta_validation = validate_delta_files(
        files,
        expected_run_id=archive_validation["run_id"],
    )
    return {**archive_validation, **delta_validation}, files


def render_review(
    manifest: dict[str, Any],
    observations: dict[str, Any],
    evidence_reference: dict[str, Any],
) -> str:
    rows = observations["records"]
    states = Counter(row["observed_access_state"] for row in rows)
    lines = [
        "# Whole-Law replacement-route access review",
        "",
        f"Evidence run: `{manifest['run_id']}`.",
        "",
        "This is an immutable delta over the original source-access run. It "
        "does not rewrite the research register or the original observations.",
        "",
        "## Coverage",
        "",
        f"- Replacement routes attempted: {len(rows)} / "
        f"{manifest['coverage']['replacement_routes_in_overlay']}",
        f"- Source records represented: "
        f"{manifest['coverage']['source_records_attempted']}",
        f"- Reachable: {states.get('reachable', 0)}",
        f"- Restricted: {states.get('restricted', 0)}",
        f"- Unavailable: {states.get('unavailable', 0)}",
        f"- Network errors: {states.get('network-error', 0)}",
        f"- Redirects followed: "
        f"{sum(len(row['redirect_chain']) for row in rows)}",
        "",
        "Each route was restricted to its reviewed HTTPS host allowlist. DNS "
        "answers for the initial URL and every redirect were required to be "
        "globally routable. No credentials, cookies, forms, crawling, "
        "authentication bypass, downloaded-code execution, compressed-content "
        "decompression or unsafe XML parsing was performed.",
        "",
        "## Denominators",
        "",
        f"All {len(rows)} replacement-route records have the exact route-level "
        "denominator `1`. This run claims "
        f"{manifest['coverage']['exact_corpus_enumerations']} exact corpus "
        "enumerations. Existing "
        "partial, conditional and unavailable corpus denominators therefore "
        "remain open.",
        "",
        "## Results",
        "",
        "| Replacement | Source | HTTP | State | Redirects | URL |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['replacement_id']} | {row['source_id']} | "
            f"{row['http_status'] if row['http_status'] is not None else '—'} "
            f"| {row['observed_access_state']} | "
            f"{len(row['redirect_chain'])} | {row['url']} |"
        )
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "The response prefixes are untrusted and remain only in the "
            "bounded sealed archive. The public projection contains metadata, "
            "hashes and redirect provenance, not response bodies.",
            "",
            f"- Archive: `{evidence_reference['archive_path']}`",
            f"- Archive SHA-256: `{evidence_reference['archive_sha256']}`",
            f"- Tree SHA-256: `{evidence_reference['archive_tree_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def publish_archive(archive_path: Path, receipt_path: Path) -> None:
    validation, files = validate_archive(archive_path, receipt_path)
    receipt = base.load_json(receipt_path)
    manifest = json.loads(files["manifest.json"])
    observations = json.loads(files["observations.json"])
    comparison = json.loads(files["comparison.json"])
    constraints = json.loads(files["source-constraint-ledger.json"])
    projection_id = (
        f"replacement-pub-{receipt['run_id']}-"
        f"{receipt['archive']['sha256'][:12]}"
    )
    resources = {
        "replacement-observations.json": observations,
        "replacement-comparison.json": comparison,
        "source-constraint-ledger.json": constraints,
    }
    evidence_reference = {
        "schema": REFERENCE_SCHEMA,
        "generated_at": receipt["archived_at"],
        "evidence_run_id": receipt["run_id"],
        "overlay": manifest["bindings"]["overlay_path"],
        "overlay_sha256": manifest["bindings"]["overlay_sha256"],
        "superseded_evidence_run_id":
            manifest["bindings"]["superseded_evidence_run_id"],
        "archive_path": receipt["archive"]["path"],
        "archive_receipt_path": str(receipt_path.relative_to(ROOT)),
        "archive_sha256": receipt["archive"]["sha256"],
        "archive_tree_sha256": receipt["archive"]["tree_sha256"],
        "original_integrity_sha256":
            receipt["original_integrity"]["sha256"],
        "validation": validation,
        "publication_projection_id": projection_id,
    }
    publication = {
        "schema": PROJECTION_SCHEMA,
        "projection_id": projection_id,
        "generated_at": receipt["archived_at"],
        "replaceable": True,
        "immutable_original": False,
        "source_evidence": evidence_reference,
        "transformation": {
            "kind": "metadata-only-publication",
            "downloaded_response_bodies_omitted": True,
            "body_hashes_retained": True,
            "redirect_provenance_retained": True,
            "changes_original_run": False,
        },
        "resources": {
            name: {
                "bytes": len(render_json(value).encode("utf-8")),
                "sha256": base.sha256_bytes(
                    render_json(value).encode("utf-8")
                ),
            }
            for name, value in sorted(resources.items())
        },
    }
    review = render_review(manifest, observations, evidence_reference)
    is_supplement = (
        manifest["bindings"]["overlay_path"]
        != str(OVERLAY.relative_to(ROOT))
    )
    prefix = (
        f"supplements/{receipt['run_id']}"
        if is_supplement
        else "current"
    )
    projections = {
        f"{prefix}/replacement-observations.json": observations,
        f"{prefix}/replacement-comparison.json": comparison,
        f"{prefix}/source-constraint-ledger.json": constraints,
        f"{prefix}/evidence-reference.json": evidence_reference,
        f"{prefix}/publication-projection.json": publication,
    }
    for base_path in (AUTHORING, BUNDLE):
        for relative, value in projections.items():
            base.write_projection_json(base_path / relative, value)
        base.write_projection_text(
            base_path / prefix / "replacement-access-review.md",
            review,
        )
    print(
        f"Published replacement projection {projection_id} from "
        f"{receipt['run_id']}",
        flush=True,
    )


def capture_run(args: argparse.Namespace) -> Path:
    overlay_path = {
        "primary": OVERLAY,
        "copfs-r02": COPFS_SUPPLEMENT,
        "copfs-r03": COPFS_SYSTEM_TRUST_SUPPLEMENT,
    }[args.overlay]
    overlay, routes = validate_overlay(overlay_path)
    run_id = args.run_id or make_run_id()
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid replacement run ID")
    final_dir = EVIDENCE_ROOT / run_id
    partial_dir = EVIDENCE_ROOT / f".partial-{run_id}"
    if final_dir.exists() or partial_dir.exists():
        raise FileExistsError(f"replacement attempt already exists: {run_id}")
    partial_dir.mkdir(parents=True, exist_ok=False)
    started_at = isoformat(utc_now())
    captures = []
    try:
        methods = replacement_methods(overlay, routes)
        for position, (method, route) in enumerate(methods, start=1):
            capture = capture_route(
                method,
                route,
                timeout_seconds=args.timeout,
                max_body_bytes=args.max_body_bytes,
                user_agent=args.user_agent,
                maximum_redirects=overlay["policy"]["maximum_redirects"],
            )
            captures.append(capture)
            print(
                f"[{position:02d}/{len(methods):02d}] "
                f"{route['replacement_id']} "
                f"{capture['observed_access_state']} "
                f"{capture['response']['status'] or '-'}",
                flush=True,
            )
        completed_at = isoformat(utc_now())
        write_run(
            captures,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            args=args,
            overlay=overlay,
            overlay_path=overlay_path,
            partial_dir=partial_dir,
        )
        os.replace(partial_dir, final_dir)
        files = archive_tools.directory_snapshot(final_dir)
        archive_path, receipt_path = archive_paths(run_id)
        archive_tools.create_archive(
            run_id=run_id,
            files=files,
            archive_path=archive_path,
            receipt_path=receipt_path,
            archived_at=isoformat(utc_now()),
            source_snapshot={
                "kind": "completed-replacement-route-delta",
                "tree_path": str(final_dir.relative_to(ROOT)),
                "overlay_path": str(overlay_path.relative_to(ROOT)),
                "overlay_sha256": sha256_file(overlay_path),
                "dependency_after_archiving": False,
            },
        )
        validate_archive(archive_path, receipt_path)
        shutil.rmtree(final_dir)
        publish_archive(archive_path, receipt_path)
        return archive_path
    except Exception:
        print(
            f"Replacement capture stopped; partial attempt retained at "
            f"{partial_dir if partial_dir.exists() else final_dir}",
            file=sys.stderr,
        )
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture a safe Whole-Law replacement-route delta"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate-overlay",
        help="validate schema, source bindings and reviewed candidates offline",
    )
    validate.add_argument(
        "--overlay",
        choices=("primary", "copfs-r02", "copfs-r03"),
        default="primary",
    )
    capture = subparsers.add_parser(
        "capture",
        help="make and seal one bounded request per reviewed replacement route",
    )
    capture.add_argument("--run-id")
    capture.add_argument(
        "--overlay",
        choices=("primary", "copfs-r02", "copfs-r03"),
        default="primary",
    )
    capture.add_argument("--timeout", type=float, default=20.0)
    capture.add_argument("--max-body-bytes", type=int, default=32768)
    capture.add_argument(
        "--user-agent",
        default=(
            "UK-Whole-Law-OKF-source-route-replacement/"
            f"{TOOL_VERSION} (+{base.PUBLIC_REPOSITORY})"
        ),
    )
    capture.add_argument(
        "--acknowledge-public-network-access",
        action="store_true",
        help="required to make the 20 bounded reviewed public requests",
    )
    check = subparsers.add_parser(
        "check",
        help="validate a sealed replacement archive offline",
    )
    check.add_argument("--run", default="latest")
    publish = subparsers.add_parser(
        "publish",
        help="rebuild the body-free projection from sealed evidence",
    )
    publish.add_argument("--run", default="latest")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "validate-overlay":
            overlay_path = {
                "primary": OVERLAY,
                "copfs-r02": COPFS_SUPPLEMENT,
                "copfs-r03": COPFS_SYSTEM_TRUST_SUPPLEMENT,
            }[args.overlay]
            overlay, _ = validate_overlay(overlay_path)
            print(
                render_json(
                    {
                        "overlay_id": overlay["overlay_id"],
                        "routes": len(overlay["routes"]),
                        "schema_valid": True,
                        "source_bindings_valid": True,
                        "reviewed_candidate_allowlist_valid": True,
                    }
                ),
                end="",
            )
        elif args.command == "capture":
            if not args.acknowledge_public_network_access:
                raise ValueError(
                    "capture requires --acknowledge-public-network-access"
                )
            if not 1 <= args.timeout <= 60:
                raise ValueError("--timeout must be between 1 and 60 seconds")
            if not 1024 <= args.max_body_bytes <= 65536:
                raise ValueError(
                    "--max-body-bytes must be between 1024 and 65536"
                )
            path = capture_run(args)
            print(f"Immutable replacement evidence sealed at {path}")
        elif args.command == "check":
            archive_path, receipt_path = resolve_archive(args.run)
            validation, _ = validate_archive(archive_path, receipt_path)
            print(render_json(validation), end="")
        elif args.command == "publish":
            archive_path, receipt_path = resolve_archive(args.run)
            publish_archive(archive_path, receipt_path)
        else:  # pragma: no cover
            raise ValueError(f"unsupported command: {args.command}")
    except (
        FileNotFoundError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
        UnsafeRouteError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
