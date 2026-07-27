#!/usr/bin/env python3
"""Capture one immutable, independently verified GitHub Pages artifact.

The public command supports exactly the OKF Explorer v0.5.4 Pages workflow
attempt pinned below.  It validates the GitHub Actions run and artifact API
objects, streams the Actions ZIP through a bounded manual redirect chain,
fully scans the ZIP/TAR closure without extracting the TAR, and independently
reconstructs the Explorer application-build manifest.

``GITHUB_TOKEN`` is optional.  It is sent only to ``api.github.com`` and is
never persisted.  Signed redirect query strings, cookies, request headers, and
sensitive response headers are likewise never written.  Tests inject a
transport, resolver, clock, and smaller immutable target profile; the CLI
cannot select an alternate production target.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import http.client
import io
import ipaddress
import json
import multiprocessing
import os
import re
import shutil
import socket
import ssl
import stat
import struct
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Protocol
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "release-assurance"
    / "schemas"
    / "github-pages-observation.schema.json"
)

OBSERVATION_SCHEMA = "okf-github-pages-observation.v1"
ATTEMPT_SCHEMA = "okf-github-pages-observation-attempt.v1"
INVENTORY_SCHEMA = "okf-github-pages-tar-file-inventory.v1"
BUILD_MANIFEST_SCHEMA = "okf-explorer-app-build-manifest.v1"
CANONICAL_MATERIALS_ALGORITHM = "sha256-canonical-json-materials-v1"
TOOL_VERSION = "1.0.0"

API_HOST = "api.github.com"
AZURE_BLOB_SUFFIX = ".blob.core.windows.net"
AZURE_BLOB_HOST = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"\.blob\.core\.windows\.net$"
)
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

REQUEST_TIMEOUT_SECONDS = 60.0
DNS_TIMEOUT_SECONDS = 10.0
MAXIMUM_REDIRECTS = 3
MAXIMUM_API_BODY_BYTES = 4 * 1024 * 1024
MAXIMUM_REDIRECT_BODY_BYTES = 64 * 1024
MAXIMUM_HEADER_BYTES = 256 * 1024
MAXIMUM_URL_UTF16_UNITS = 8192
MAXIMUM_ARCHIVE_PATH_UTF16_UNITS = 4096
MAXIMUM_ZIP_BYTES = 256 * 1024 * 1024
MAXIMUM_TAR_BYTES = 1024 * 1024 * 1024
MAXIMUM_TAR_MEMBERS = 12_000
MAXIMUM_TAR_FILE_BYTES = 512 * 1024 * 1024
MAXIMUM_MANIFEST_BYTES = 4 * 1024 * 1024
MAXIMUM_COMPRESSION_RATIO = 100
STREAM_CHUNK_BYTES = 1024 * 1024

RUN_HEADERS_PATH = "raw/run-attempt-response.headers.json"
RUN_BODY_PATH = "raw/run-attempt-response.body.json"
ARTIFACT_HEADERS_PATH = "raw/artifact-response.headers.json"
ARTIFACT_BODY_PATH = "raw/artifact-response.body.json"
DOWNLOAD_HEADERS_PATH = "raw/artifact-download-response.headers.json"
ZIP_PATH = "raw/github-pages-artifact.zip"
INVENTORY_PATH = "inventory/tar-files.json"
ATTEMPT_MANIFEST_PATH = "attempt-manifest.json"
OBSERVATION_FILENAME = "github-pages-observation.json"

SENSITIVE_RESPONSE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authenticate",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
}
SENSITIVE_VALUE_MARKERS = (
    "authorization=",
    "credential=",
    "signature=",
    "sig=",
    "token=",
)


@dataclass(frozen=True)
class TargetProfile:
    repository: str
    slug: str
    run_id: int
    run_attempt: int
    head_sha: str
    git_tree: str
    workflow_path: str
    artifact_id: int
    artifact_name: str
    artifact_api_bytes: int
    zip_bytes: int
    zip_sha256: str
    tar_name: str
    tar_bytes: int
    tar_sha256: str
    tar_member_count: int
    tar_file_count: int
    tar_directory_count: int
    tar_total_file_bytes: int
    tar_inventory_sha256: str
    tar_raw_header_count: int
    tar_gnu_longname_count: int
    build_manifest_path: str
    build_manifest_bytes: int
    build_manifest_sha256: str
    build_file_count: int
    build_tree_sha256: str
    build_index_path: str
    build_index_bytes: int
    build_index_sha256: str
    alternate_asset_id: int
    alternate_asset_name: str
    alternate_asset_url: str


DEFAULT_PROFILE = TargetProfile(
    repository="https://github.com/chris-page-gov/okf-explorer",
    slug="chris-page-gov/okf-explorer",
    run_id=30228627196,
    run_attempt=1,
    head_sha="a23dfdea56fea0184b6d53f3163b292dd1a312ed",
    git_tree="981d5c967b7017c78f37aab379edd95f44917cf5",
    workflow_path=".github/workflows/pages.yml",
    artifact_id=8639352412,
    artifact_name="github-pages",
    artifact_api_bytes=185023908,
    zip_bytes=185023908,
    zip_sha256=(
        "357c2fcfbdb4fda34a830d933feb290dd8980cc61b0a82f51cd5e0e5a226c1c0"
    ),
    tar_name="artifact.tar",
    tar_bytes=817694720,
    tar_sha256=(
        "10565ce278f5386d736ac7396909d0213431f0c15c4086139302aba5702a01bc"
    ),
    tar_member_count=9980,
    tar_file_count=9911,
    tar_directory_count=69,
    tar_total_file_bytes=807618104,
    tar_inventory_sha256=(
        "13928e64e515171336f8c8523c515706693a1c13d8c46abc83728e779a913c61"
    ),
    tar_raw_header_count=12375,
    tar_gnu_longname_count=2395,
    build_manifest_path="okf-explorer-build-manifest.json",
    build_manifest_bytes=2849,
    build_manifest_sha256=(
        "62dd2b96fba2c832a61fcbccbc01fbe83dda83ffeab61dfb8544a60fa37310be"
    ),
    build_file_count=16,
    build_tree_sha256=(
        "b246c88f4bbcc3eae47f79b4dd6eaad76ea758272e427823a895604f71ba40c7"
    ),
    build_index_path="index.html",
    build_index_bytes=1318,
    build_index_sha256=(
        "b40439d2c8f67447d80f583595197493a1c2a2fe12e61e6e632b74cb4d9b6cc9"
    ),
    alternate_asset_id=490852327,
    alternate_asset_name="okf-explorer-v0.5.4-pages-artifact.zip",
    alternate_asset_url=(
        "https://github.com/chris-page-gov/okf-explorer/releases/download/"
        "v0.5.4/okf-explorer-v0.5.4-pages-artifact.zip"
    ),
)


class CaptureError(RuntimeError):
    """The observation is unsafe, incomplete, or inconsistent."""


class UnsafeRouteError(CaptureError):
    """A URL, redirect, or DNS result escaped the fixed network policy."""


@dataclass
class ResponseHandle:
    status: int
    reason: str
    headers: list[dict[str, str]]
    stream: BinaryIO
    close_callback: Callable[[], None] | None = None

    def close(self) -> None:
        try:
            self.stream.close()
        finally:
            if self.close_callback is not None:
                self.close_callback()


class Transport(Protocol):
    def open_once(
        self,
        url: str,
        addresses: list[dict[str, str]],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> ResponseHandle:
        """Open one response without following redirects."""


AddressResolver = Callable[[str, int], list[dict[str, str]]]
Clock = Callable[[], str]


@dataclass(frozen=True)
class FetchResult:
    body: bytes | None
    body_bytes: int
    body_sha256: str | None
    final_url_redacted: str
    hops: list[dict[str, Any]]
    status: int


@dataclass(frozen=True)
class ArchiveScan:
    zip_entry: dict[str, Any]
    tar: dict[str, Any]
    inventory: dict[str, Any]
    inventory_body: bytes
    build: dict[str, Any]


def render_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def canonical_materials_bytes(materials: list[dict[str, Any]]) -> bytes:
    return (
        json.dumps(
            materials,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utf16_units(value: str) -> int:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CaptureError("text contains an unpaired Unicode surrogate")
    return len(value.encode("utf-16-le")) // 2


def validate_timestamp(value: str, label: str = "timestamp") -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 40
    ):
        raise CaptureError(f"{label} must be a bounded RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CaptureError(f"{label} is not valid RFC 3339") from error
    if parsed.tzinfo is None:
        raise CaptureError(f"{label} must include a timezone")
    return value


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CaptureError(f"{label} must be a positive integer")
    return value


def validate_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise CaptureError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def validate_commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or not COMMIT.fullmatch(value):
        raise CaptureError(f"{label} must be a full lowercase commit SHA")
    return value


def validate_evidence_path(value: str) -> str:
    return validate_archive_path(value, allow_root=False)


def validate_archive_path(value: str, *, allow_root: bool = False) -> str:
    if not isinstance(value, str):
        raise CaptureError("archive path is not a string")
    if allow_root and value == ".":
        return value
    if (
        not value
        or "\\" in value
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        )
        or utf16_units(value) > MAXIMUM_ARCHIVE_PATH_UTF16_UNITS
    ):
        raise CaptureError(f"archive path is unsafe: {value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.as_posix() != value
        or "/".join(path.parts) != value
    ):
        raise CaptureError(f"archive path is not canonical: {value!r}")
    return value


def canonical_tar_path(raw_name: str, *, directory: bool) -> str:
    if not isinstance(raw_name, str):
        raise CaptureError("TAR member name is not text")
    if directory and raw_name == "./":
        return "."
    if not raw_name.startswith("./"):
        raise CaptureError("TAR member must use the canonical leading './'")
    if directory:
        if not raw_name.endswith("/"):
            raise CaptureError("TAR directory must use one trailing slash")
        relative = raw_name[2:-1]
    else:
        if raw_name.endswith("/"):
            raise CaptureError("TAR regular file cannot end with a slash")
        relative = raw_name[2:]
    canonical = validate_archive_path(relative)
    expected = f"./{canonical}/" if directory else f"./{canonical}"
    if raw_name != expected:
        raise CaptureError(f"TAR member spelling is not canonical: {raw_name!r}")
    return canonical


def material(path: str, body: bytes, *, allow_empty: bool = False) -> dict[str, Any]:
    validate_evidence_path(path)
    if not isinstance(body, bytes) or (not body and not allow_empty):
        raise CaptureError(f"evidence material is empty or invalid: {path}")
    return {
        "path": path,
        "bytes": len(body),
        "sha256": sha256_bytes(body),
    }


def file_material(path: str, size: int, digest: str) -> dict[str, Any]:
    validate_archive_path(path)
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise CaptureError(f"archive material byte count is invalid: {path}")
    validate_digest(digest, f"archive material {path} SHA-256")
    return {"path": path, "bytes": size, "sha256": digest}


def json_object(body: bytes, label: str) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CaptureError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    def nonfinite(value: str) -> Any:
        raise CaptureError(f"{label} contains non-finite number {value}")

    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=nonfinite,
        )
    except UnicodeDecodeError as error:
        raise CaptureError(f"{label} is not UTF-8") from error
    except json.JSONDecodeError as error:
        raise CaptureError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise CaptureError(f"{label} must be a JSON object")
    return value


def _validate_profile(profile: TargetProfile) -> None:
    if profile.repository != f"https://github.com/{profile.slug}":
        raise CaptureError("target repository and slug disagree")
    if profile.slug.count("/") != 1:
        raise CaptureError("target repository slug is invalid")
    positive_integer(profile.run_id, "target run ID")
    positive_integer(profile.run_attempt, "target run attempt")
    validate_commit(profile.head_sha, "target head SHA")
    validate_commit(profile.git_tree, "target git tree")
    validate_evidence_path(profile.workflow_path)
    positive_integer(profile.artifact_id, "target artifact ID")
    if not profile.artifact_name or "/" in profile.artifact_name:
        raise CaptureError("target artifact name is invalid")
    if (
        profile.artifact_api_bytes != profile.zip_bytes
        or profile.zip_bytes > MAXIMUM_ZIP_BYTES
    ):
        raise CaptureError("target ZIP size is inconsistent or over hard cap")
    validate_digest(profile.zip_sha256, "target ZIP SHA-256")
    if profile.tar_name != "artifact.tar":
        raise CaptureError("target TAR entry must be artifact.tar")
    if profile.tar_bytes > MAXIMUM_TAR_BYTES:
        raise CaptureError("target TAR exceeds hard cap")
    validate_digest(profile.tar_sha256, "target TAR SHA-256")
    if not 1 <= profile.tar_member_count <= MAXIMUM_TAR_MEMBERS:
        raise CaptureError("target TAR member count is invalid")
    if (
        profile.tar_file_count < 1
        or profile.tar_directory_count < 1
        or profile.tar_file_count + profile.tar_directory_count
        != profile.tar_member_count
        or profile.tar_raw_header_count
        != profile.tar_member_count + profile.tar_gnu_longname_count
        or profile.tar_raw_header_count > MAXIMUM_TAR_MEMBERS * 2
        or not 0 <= profile.tar_gnu_longname_count <= MAXIMUM_TAR_MEMBERS
        or not 1 <= profile.tar_total_file_bytes <= profile.tar_bytes
    ):
        raise CaptureError("target TAR raw/logical member counts are invalid")
    validate_digest(
        profile.tar_inventory_sha256,
        "target TAR inventory SHA-256",
    )
    validate_archive_path(profile.build_manifest_path)
    validate_digest(profile.build_manifest_sha256, "target manifest SHA-256")
    if profile.build_manifest_bytes > MAXIMUM_MANIFEST_BYTES:
        raise CaptureError("target manifest exceeds hard cap")
    if not 1 <= profile.build_file_count <= MAXIMUM_TAR_MEMBERS:
        raise CaptureError("target build file count is invalid")
    validate_digest(profile.build_tree_sha256, "target tree SHA-256")
    validate_archive_path(profile.build_index_path)
    validate_digest(profile.build_index_sha256, "target index SHA-256")
    positive_integer(profile.alternate_asset_id, "alternate release asset ID")
    if not profile.alternate_asset_name:
        raise CaptureError("alternate release asset name is invalid")
    expected_alternate = (
        f"{profile.repository}/releases/download/v0.5.4/"
        f"{profile.alternate_asset_name}"
    )
    if profile.alternate_asset_url != expected_alternate:
        raise CaptureError("alternate release asset URL is invalid")


def run_api_url(profile: TargetProfile) -> str:
    return (
        f"https://{API_HOST}/repos/{profile.slug}/actions/runs/"
        f"{profile.run_id}/attempts/{profile.run_attempt}"
    )


def run_resource_url(profile: TargetProfile) -> str:
    return (
        f"https://{API_HOST}/repos/{profile.slug}/actions/runs/"
        f"{profile.run_id}"
    )


def artifact_api_url(profile: TargetProfile) -> str:
    return (
        f"https://{API_HOST}/repos/{profile.slug}/actions/artifacts/"
        f"{profile.artifact_id}"
    )


def artifact_download_url(profile: TargetProfile) -> str:
    return f"{artifact_api_url(profile)}/zip"


def _redacted_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path or "/", "", "")
    )


def _canonical_api_url(url: str, expected: str) -> str:
    parsed = _validate_https_url(url)
    if (
        parsed.hostname != API_HOST
        or parsed.query
        or url != expected
    ):
        raise UnsafeRouteError("API request URL differs from its fixed endpoint")
    return url


def _canonical_storage_url(url: str) -> str:
    parsed = _validate_https_url(url)
    host = (parsed.hostname or "").lower()
    if not AZURE_BLOB_HOST.fullmatch(host):
        raise UnsafeRouteError("redirect host is not an approved Azure blob host")
    return url


def _validate_https_url(url: str) -> Any:
    if (
        not isinstance(url, str)
        or not url
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in url
        )
        or utf16_units(url) > MAXIMUM_URL_UTF16_UNITS
    ):
        raise UnsafeRouteError("URL is empty, overlong, or contains unsafe text")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
        or parsed.netloc.lower() not in {host, f"{host}:443"}
    ):
        raise UnsafeRouteError("URL is not canonical credential-free HTTPS")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeRouteError("IP-literal URLs are forbidden")
    decoded = unquote(parsed.path)
    if "\\" in url or "\\" in decoded or any(
        part in {".", ".."} for part in decoded.split("/")
    ):
        raise UnsafeRouteError("URL path is ambiguous or traversing")
    canonical = urlunsplit(
        ("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )
    if canonical != url:
        raise UnsafeRouteError("URL is not in canonical literal form")
    return parsed


def _public_addresses(rows: Any, host: str) -> list[dict[str, str]]:
    if not isinstance(rows, list) or not rows or len(rows) > 16:
        raise UnsafeRouteError(f"DNS answer set is invalid for {host}")
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"address", "family"}
            or row.get("family") not in {"IPv4", "IPv6"}
            or not isinstance(row.get("address"), str)
        ):
            raise UnsafeRouteError(f"DNS answer shape is invalid for {host}")
        try:
            address = ipaddress.ip_address(row["address"].split("%", 1)[0])
        except ValueError as error:
            raise UnsafeRouteError(f"DNS answer is invalid for {host}") from error
        if not address.is_global:
            raise UnsafeRouteError(f"non-global DNS answer rejected for {host}")
        family = "IPv4" if address.version == 4 else "IPv6"
        if family != row["family"]:
            raise UnsafeRouteError(f"DNS family disagrees for {host}")
        result[(family, str(address))] = {
            "address": str(address),
            "family": family,
        }
    return [
        result[key]
        for key in sorted(
            result,
            key=lambda item: (0 if item[0] == "IPv4" else 1, item[1]),
        )
    ]


def _resolver_worker(
    connection: Any,
    host: str,
    port: int,
) -> None:
    try:
        answers = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        rows = []
        for family, _socktype, _proto, _canonname, sockaddr in answers:
            if family in {socket.AF_INET, socket.AF_INET6}:
                rows.append(
                    {
                        "address": str(sockaddr[0]),
                        "family": "IPv4" if family == socket.AF_INET else "IPv6",
                    }
                )
        connection.send({"status": "ok", "rows": rows})
    except BaseException as error:
        connection.send(
            {"status": "error", "error_type": type(error).__name__}
        )
    finally:
        connection.close()


def resolve_public_addresses(host: str, port: int = 443) -> list[dict[str, str]]:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_resolver_worker,
        args=(sender, host, port),
        daemon=True,
    )
    process.start()
    sender.close()
    try:
        if not receiver.poll(DNS_TIMEOUT_SECONDS):
            process.terminate()
            process.join(timeout=1)
            raise CaptureError(f"DNS resolution timed out for {host}")
        try:
            message = receiver.recv()
        except EOFError as error:
            raise CaptureError(
                f"DNS resolver exited without a receipt for {host}"
            ) from error
    finally:
        receiver.close()
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
    if message.get("status") != "ok":
        raise CaptureError(
            f"DNS resolution failed for {host} "
            f"({message.get('error_type', 'unknown')})"
        )
    return _public_addresses(message.get("rows"), host)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        *,
        address: str,
        port: int,
        timeout: float,
    ) -> None:
        super().__init__(
            host,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._address = address

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._address, self.port),
            self.timeout,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw,
                server_hostname=self.host,
            )
        except BaseException:
            raw.close()
            raise


class PinnedHTTPSNetworkTransport:
    """Direct TLS transport pinned to a reviewed public DNS result."""

    def open_once(
        self,
        url: str,
        addresses: list[dict[str, str]],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> ResponseHandle:
        parsed = urlsplit(url)
        target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        deadline = time.monotonic() + timeout_seconds
        failures: list[str] = []
        for row in addresses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            connection = _PinnedHTTPSConnection(
                parsed.hostname or "",
                address=row["address"],
                port=parsed.port or 443,
                timeout=remaining,
            )
            try:
                connection.request("GET", target, headers=headers)
                response = connection.getresponse()
                return ResponseHandle(
                    status=int(response.status),
                    reason=str(response.reason),
                    headers=[
                        {"name": name, "value": value}
                        for name, value in response.getheaders()
                    ],
                    stream=response,
                    close_callback=connection.close,
                )
            except BaseException as error:
                connection.close()
                failures.append(type(error).__name__)
        suffix = ",".join(sorted(set(failures))) or "timeout"
        raise CaptureError(f"HTTPS request failed ({suffix})")


def api_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": f"okf-github-pages-observer/{TOOL_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        if (
            len(token) > 1024
            or any(character in token for character in "\r\n\0")
        ):
            raise CaptureError("GITHUB_TOKEN has an invalid header shape")
        headers["Authorization"] = f"Bearer {token}"
    return headers


def storage_headers() -> dict[str, str]:
    return {
        "Accept": "application/octet-stream",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": f"okf-github-pages-observer/{TOOL_VERSION}",
    }


def _normalize_response(handle: Any) -> ResponseHandle:
    if not isinstance(handle, ResponseHandle):
        raise CaptureError("transport returned an invalid response handle")
    if (
        isinstance(handle.status, bool)
        or not isinstance(handle.status, int)
        or not 100 <= handle.status <= 599
        or not isinstance(handle.reason, str)
        or len(handle.reason) > 256
        or not hasattr(handle.stream, "read")
    ):
        raise CaptureError("transport returned invalid response metadata")
    if not isinstance(handle.headers, list) or len(handle.headers) > 256:
        raise CaptureError("transport returned invalid response headers")
    total = 0
    normalized: list[dict[str, str]] = []
    for row in handle.headers:
        if (
            not isinstance(row, dict)
            or set(row) != {"name", "value"}
            or not isinstance(row["name"], str)
            or not isinstance(row["value"], str)
            or not HEADER_NAME.fullmatch(row["name"])
            or any(character in row["value"] for character in "\r\n\0")
        ):
            raise CaptureError("transport returned a malformed response header")
        total += len(row["name"].encode("utf-8"))
        total += len(row["value"].encode("utf-8"))
        normalized.append({"name": row["name"], "value": row["value"]})
    if total > MAXIMUM_HEADER_BYTES:
        raise CaptureError("response headers exceed their fixed limit")
    handle.headers = normalized
    return handle


def _header_values(headers: list[dict[str, str]], name: str) -> list[str]:
    lowered = name.lower()
    return [
        row["value"]
        for row in headers
        if row["name"].lower() == lowered
    ]


def _content_length(headers: list[dict[str, str]]) -> int | None:
    values = _header_values(headers, "content-length")
    if not values:
        return None
    if len(set(values)) != 1 or not values[0].isdigit():
        raise CaptureError("response has an ambiguous Content-Length")
    return int(values[0])


def _safe_response_headers(
    headers: list[dict[str, str]],
    *,
    response_url: str,
) -> tuple[list[dict[str, str]], list[str], bool]:
    selected: list[dict[str, str]] = []
    omitted: set[str] = set()
    location_query_redacted = False
    for row in headers:
        name = row["name"].lower()
        if name in SENSITIVE_RESPONSE_HEADERS:
            omitted.add(name)
            continue
        value = row["value"]
        if name == "location":
            target = urljoin(response_url, value)
            location_query_redacted = (
                location_query_redacted or bool(urlsplit(target).query)
            )
            value = _redacted_url(target)
        elif any(
            marker in value.lower()
            for marker in SENSITIVE_VALUE_MARKERS
        ):
            omitted.add(name)
            continue
        selected.append({"name": row["name"], "value": value})
    return selected, sorted(omitted), location_query_redacted


def _hop_receipt(
    *,
    url: str,
    handle: ResponseHandle,
    requested_at: str,
    completed_at: str,
) -> dict[str, Any]:
    headers, omitted, location_redacted = _safe_response_headers(
        handle.headers,
        response_url=url,
    )
    return {
        "completed_at": validate_timestamp(completed_at, "request completion"),
        "location_query_redacted": location_redacted,
        "omitted_response_headers": omitted,
        "reason": handle.reason,
        "requested_at": validate_timestamp(requested_at, "request start"),
        "response_headers": headers,
        "status": handle.status,
        "url": _redacted_url(url),
        "url_query_redacted": bool(urlsplit(url).query),
    }


def _open_response(
    *,
    transport: Transport,
    resolver: AddressResolver,
    url: str,
    headers: dict[str, str],
    clock: Clock,
) -> tuple[ResponseHandle, str]:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    addresses = _public_addresses(
        resolver(host, parsed.port or 443),
        host,
    )
    requested_at = validate_timestamp(clock(), "request start")
    try:
        handle = _normalize_response(
            transport.open_once(
                url,
                addresses,
                headers,
                REQUEST_TIMEOUT_SECONDS,
            )
        )
    except BaseException as error:
        if isinstance(error, CaptureError):
            raise
        raise CaptureError(
            f"HTTPS transport failed ({type(error).__name__})"
        ) from error
    return handle, requested_at


class _SecretScanner:
    def __init__(self, secret: str | None) -> None:
        self._needle = secret.encode("utf-8") if secret else b""
        self._tail = b""

    def feed(self, body: bytes) -> None:
        if not self._needle:
            return
        candidate = self._tail + body
        if self._needle in candidate:
            raise CaptureError(
                "a response reflected the authentication credential"
            )
        keep = max(0, len(self._needle) - 1)
        self._tail = candidate[-keep:] if keep else b""


def _read_bounded(
    stream: BinaryIO,
    maximum_bytes: int,
    *,
    secret: str | None,
) -> bytes:
    result = bytearray()
    scanner = _SecretScanner(secret)
    while True:
        chunk = stream.read(min(STREAM_CHUNK_BYTES, maximum_bytes + 1))
        if not isinstance(chunk, bytes):
            raise CaptureError("transport stream returned non-bytes data")
        if not chunk:
            break
        scanner.feed(chunk)
        result.extend(chunk)
        if len(result) > maximum_bytes:
            raise CaptureError("response body exceeds its fixed limit")
    return bytes(result)


def _write_stream(
    stream: BinaryIO,
    path: Path,
    maximum_bytes: int,
    *,
    secret: str | None,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    scanner = _SecretScanner(secret)
    size = 0
    with path.open("xb") as output:
        while True:
            chunk = stream.read(STREAM_CHUNK_BYTES)
            if not isinstance(chunk, bytes):
                raise CaptureError("transport stream returned non-bytes data")
            if not chunk:
                break
            scanner.feed(chunk)
            size += len(chunk)
            if size > maximum_bytes:
                raise CaptureError("download exceeds its fixed body limit")
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    os.chmod(path, 0o600)
    return size, digest.hexdigest()


def _ensure_secret_absent(secret: str | None, bodies: list[bytes]) -> None:
    if not secret:
        return
    needle = secret.encode("utf-8")
    if any(needle in body for body in bodies):
        raise CaptureError(
            "authentication credential would be persisted in evidence"
        )


def _fetch_api(
    *,
    transport: Transport,
    resolver: AddressResolver,
    url: str,
    expected_url: str,
    token: str | None,
    purpose: str,
    clock: Clock,
) -> FetchResult:
    current = _canonical_api_url(url, expected_url)
    handle, started = _open_response(
        transport=transport,
        resolver=resolver,
        url=current,
        headers=api_headers(token),
        clock=clock,
    )
    try:
        if handle.status in REDIRECT_STATUSES:
            raise UnsafeRouteError(f"{purpose} API unexpectedly redirected")
        body = _read_bounded(
            handle.stream,
            MAXIMUM_API_BODY_BYTES,
            secret=token,
        )
        content_length = _content_length(handle.headers)
        if content_length is not None and content_length != len(body):
            raise CaptureError(f"{purpose} Content-Length is inconsistent")
        completed = validate_timestamp(clock(), "request completion")
        hop = _hop_receipt(
            url=current,
            handle=handle,
            requested_at=started,
            completed_at=completed,
        )
        return FetchResult(
            body=body,
            body_bytes=len(body),
            body_sha256=sha256_bytes(body),
            final_url_redacted=_redacted_url(current),
            hops=[hop],
            status=handle.status,
        )
    finally:
        handle.close()


def _fetch_zip(
    *,
    transport: Transport,
    resolver: AddressResolver,
    profile: TargetProfile,
    token: str | None,
    destination: Path,
    clock: Clock,
) -> FetchResult:
    current = _canonical_api_url(
        artifact_download_url(profile),
        artifact_download_url(profile),
    )
    hops: list[dict[str, Any]] = []
    left_api = False
    storage_host: str | None = None
    for redirect_number in range(MAXIMUM_REDIRECTS + 1):
        host = urlsplit(current).hostname or ""
        if host == API_HOST:
            if left_api:
                raise UnsafeRouteError("download redirect returned to GitHub API")
            request_headers = api_headers(token)
        else:
            _canonical_storage_url(current)
            left_api = True
            if storage_host is None:
                storage_host = host
            elif host != storage_host:
                raise UnsafeRouteError("download changed Azure storage host")
            request_headers = storage_headers()
        handle, started = _open_response(
            transport=transport,
            resolver=resolver,
            url=current,
            headers=request_headers,
            clock=clock,
        )
        try:
            if handle.status in REDIRECT_STATUSES:
                _read_bounded(
                    handle.stream,
                    MAXIMUM_REDIRECT_BODY_BYTES,
                    secret=token,
                )
                completed = validate_timestamp(clock(), "request completion")
                hops.append(
                    _hop_receipt(
                        url=current,
                        handle=handle,
                        requested_at=started,
                        completed_at=completed,
                    )
                )
                if redirect_number >= MAXIMUM_REDIRECTS:
                    raise UnsafeRouteError("artifact download exceeded redirect limit")
                locations = _header_values(handle.headers, "location")
                if len(locations) != 1 or not locations[0]:
                    raise UnsafeRouteError(
                        "artifact redirect lacks one Location header"
                    )
                redirected = urljoin(current, locations[0])
                if host == API_HOST:
                    current = _canonical_storage_url(redirected)
                else:
                    current = _canonical_storage_url(redirected)
                continue
            if not left_api:
                raise UnsafeRouteError(
                    "artifact body was not served by approved Azure storage"
                )
            if handle.status != 200:
                raise CaptureError(
                    f"artifact download returned HTTP {handle.status}"
                )
            content_length = _content_length(handle.headers)
            if (
                content_length is not None
                and content_length != profile.zip_bytes
            ):
                raise CaptureError(
                    "artifact download Content-Length differs from target"
                )
            size, digest = _write_stream(
                handle.stream,
                destination,
                profile.zip_bytes,
                secret=token,
            )
            completed = validate_timestamp(clock(), "request completion")
            hops.append(
                _hop_receipt(
                    url=current,
                    handle=handle,
                    requested_at=started,
                    completed_at=completed,
                )
            )
            if size != profile.zip_bytes or digest != profile.zip_sha256:
                raise CaptureError(
                    "downloaded Pages ZIP bytes or SHA-256 differ from target"
                )
            return FetchResult(
                body=None,
                body_bytes=size,
                body_sha256=digest,
                final_url_redacted=_redacted_url(current),
                hops=hops,
                status=handle.status,
            )
        finally:
            handle.close()
    raise AssertionError("redirect loop is statically bounded")


def _headers_document(purpose: str, result: FetchResult) -> bytes:
    return render_json(
        {
            "hops": result.hops,
            "purpose": purpose,
            "schema": "okf-github-pages-response-headers.v1",
        }
    )


def _validate_run(body: dict[str, Any], profile: TargetProfile) -> dict[str, Any]:
    expected_api = run_api_url(profile)
    if (
        body.get("id") != profile.run_id
        or body.get("run_attempt") != profile.run_attempt
        or body.get("head_sha") != profile.head_sha
        or body.get("status") != "completed"
        or body.get("conclusion") != "success"
        or body.get("path") != profile.workflow_path
        or body.get("url") != run_resource_url(profile)
        or body.get("html_url")
        != f"{profile.repository}/actions/runs/{profile.run_id}"
    ):
        raise CaptureError(
            "workflow run API response differs from the successful fixed target"
        )
    head_commit = body.get("head_commit")
    if (
        not isinstance(head_commit, dict)
        or head_commit.get("id") != profile.head_sha
        or head_commit.get("tree_id") != profile.git_tree
    ):
        raise CaptureError("workflow run head-commit tree identity is invalid")
    repository = body.get("repository")
    if (
        not isinstance(repository, dict)
        or repository.get("full_name") != profile.slug
        or repository.get("html_url") != profile.repository
    ):
        raise CaptureError("workflow run repository identity is invalid")
    return {
        "api_url": expected_api,
        "attempt": profile.run_attempt,
        "conclusion": "success",
        "git_tree": profile.git_tree,
        "head_sha": profile.head_sha,
        "html_url": f"{profile.repository}/actions/runs/{profile.run_id}",
        "id": profile.run_id,
        "status": "completed",
        "workflow_path": profile.workflow_path,
    }


def _validate_artifact(
    body: dict[str, Any],
    profile: TargetProfile,
) -> dict[str, Any]:
    expected_api = artifact_api_url(profile)
    if (
        body.get("id") != profile.artifact_id
        or body.get("name") != profile.artifact_name
        or body.get("size_in_bytes") != profile.artifact_api_bytes
        or body.get("expired") is not False
        or body.get("archive_download_url") != artifact_download_url(profile)
        or body.get("url") != expected_api
    ):
        raise CaptureError("artifact API response differs from the fixed target")
    workflow = body.get("workflow_run")
    if (
        not isinstance(workflow, dict)
        or workflow.get("id") != profile.run_id
        or workflow.get("head_sha") != profile.head_sha
    ):
        raise CaptureError("artifact workflow-run identity is invalid")
    return {
        "api_url": expected_api,
        "archive_download_url": artifact_download_url(profile),
        "expired": False,
        "id": profile.artifact_id,
        "name": profile.artifact_name,
        "size_in_bytes": profile.artifact_api_bytes,
        "workflow_run": {
            "head_sha": profile.head_sha,
            "id": profile.run_id,
        },
    }


class _HashingBoundedReader(io.RawIOBase):
    def __init__(self, source: BinaryIO, maximum_bytes: int) -> None:
        super().__init__()
        self.source = source
        self.maximum_bytes = maximum_bytes
        self.bytes_read = 0
        self.digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = STREAM_CHUNK_BYTES
        remaining = self.maximum_bytes + 1 - self.bytes_read
        if remaining <= 0:
            raise CaptureError("TAR stream exceeds its fixed limit")
        body = self.source.read(min(size, remaining))
        if not isinstance(body, bytes):
            raise CaptureError("ZIP entry returned non-bytes data")
        self.bytes_read += len(body)
        if self.bytes_read > self.maximum_bytes:
            raise CaptureError("TAR stream exceeds its fixed limit")
        self.digest.update(body)
        return body


def _stable_open(path: Path, label: str) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CaptureError(f"cannot safely open {label}") from error
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        os.close(descriptor)
        raise CaptureError(f"{label} must be a single-link regular file")
    return descriptor, details


def stable_read(path: Path, label: str, maximum_bytes: int) -> bytes:
    descriptor, before = _stable_open(path, label)
    try:
        if before.st_size > maximum_bytes:
            raise CaptureError(f"{label} exceeds its fixed limit")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(STREAM_CHUNK_BYTES, maximum_bytes + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum_bytes:
                raise CaptureError(f"{label} exceeds its fixed limit")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    declared = os.stat(path, follow_symlinks=False)
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_nlink,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_nlink,
    ) or (
        declared.st_dev,
        declared.st_ino,
        declared.st_size,
        declared.st_mtime_ns,
        declared.st_ctime_ns,
        declared.st_nlink,
    ) != identity:
        raise CaptureError(f"{label} changed while it was read")
    return b"".join(chunks)


def stable_file_material(
    path: Path,
    relative: str,
    label: str,
    maximum_bytes: int,
) -> dict[str, Any]:
    """Hash one immutable single-link file without buffering it in memory."""

    validate_evidence_path(relative)
    descriptor, before = _stable_open(path, label)
    digest = hashlib.sha256()
    size = 0
    try:
        if before.st_size > maximum_bytes:
            raise CaptureError(f"{label} exceeds its fixed limit")
        while True:
            chunk = os.read(descriptor, STREAM_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum_bytes:
                raise CaptureError(f"{label} exceeds its fixed limit")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    declared = os.stat(path, follow_symlinks=False)
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_nlink,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_nlink,
    ) or (
        declared.st_dev,
        declared.st_ino,
        declared.st_size,
        declared.st_mtime_ns,
        declared.st_ctime_ns,
        declared.st_nlink,
    ) != identity:
        raise CaptureError(f"{label} changed while it was hashed")
    return {
        "path": relative,
        "bytes": size,
        "sha256": digest.hexdigest(),
    }


def _read_tar_file(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    retain: bool,
) -> tuple[dict[str, Any], bytes | None]:
    if member.size > MAXIMUM_TAR_FILE_BYTES:
        raise CaptureError("TAR regular file exceeds per-file hard cap")
    stream = tar.extractfile(member)
    if stream is None:
        raise CaptureError("TAR regular file cannot be read")
    digest = hashlib.sha256()
    size = 0
    retained = bytearray() if retain else None
    try:
        while True:
            chunk = stream.read(STREAM_CHUNK_BYTES)
            if not isinstance(chunk, bytes):
                raise CaptureError("TAR member returned non-bytes data")
            if not chunk:
                break
            size += len(chunk)
            if size > member.size:
                raise CaptureError("TAR member exceeded its declared size")
            digest.update(chunk)
            if retained is not None:
                if size > MAXIMUM_MANIFEST_BYTES:
                    raise CaptureError("build manifest exceeds its hard cap")
                retained.extend(chunk)
    finally:
        stream.close()
    if size != member.size:
        raise CaptureError("TAR member is shorter than its declared size")
    return (
        {
            "bytes": size,
            "sha256": digest.hexdigest(),
        },
        bytes(retained) if retained is not None else None,
    )


def _canonical_manifest_bytes(document: dict[str, Any]) -> bytes:
    ordered = {
        "schema": document["schema"],
        "algorithm": document["algorithm"],
        "file_count": document["file_count"],
        "tree_sha256": document["tree_sha256"],
        "materials": [
            {
                "path": row["path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in document["materials"]
        ],
    }
    return (
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _parse_build_manifest(
    body: bytes,
    *,
    profile: TargetProfile,
    inventory_by_path: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    document = json_object(body, "Explorer build manifest")
    if set(document) != {
        "schema",
        "algorithm",
        "file_count",
        "tree_sha256",
        "materials",
    }:
        raise CaptureError("Explorer build manifest keys are not exact")
    if (
        document.get("schema") != BUILD_MANIFEST_SCHEMA
        or document.get("algorithm") != CANONICAL_MATERIALS_ALGORITHM
        or document.get("file_count") != profile.build_file_count
        or document.get("tree_sha256") != profile.build_tree_sha256
    ):
        raise CaptureError("Explorer build manifest header differs from target")
    values = document.get("materials")
    if not isinstance(values, list) or len(values) != profile.build_file_count:
        raise CaptureError("Explorer build manifest material count is invalid")
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict) or set(value) != {
            "path",
            "bytes",
            "sha256",
        }:
            raise CaptureError(
                f"Explorer build manifest material {index} shape is invalid"
            )
        path = validate_archive_path(value.get("path"))
        size = value.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise CaptureError("Explorer build material byte count is invalid")
        digest = validate_digest(
            value.get("sha256"),
            "Explorer build material SHA-256",
        )
        rows.append({"path": path, "bytes": size, "sha256": digest})
    paths = [row["path"] for row in rows]
    if (
        paths != sorted(paths)
        or len(paths) != len(set(paths))
        or profile.build_manifest_path in paths
    ):
        raise CaptureError(
            "Explorer build materials are unsorted, duplicated, or recursive"
        )
    if body != _canonical_manifest_bytes(document):
        raise CaptureError("Explorer build manifest bytes are not canonical")
    actual_rows: list[dict[str, Any]] = []
    for declared in rows:
        actual = inventory_by_path.get(declared["path"])
        if actual != declared:
            raise CaptureError(
                "Explorer build material differs from the TAR inventory: "
                f"{declared['path']}"
            )
        actual_rows.append(actual)
    tree_digest = sha256_bytes(canonical_materials_bytes(actual_rows))
    if tree_digest != profile.build_tree_sha256:
        raise CaptureError("Explorer build tree digest is inconsistent")
    index_rows = [
        row for row in actual_rows if row["path"] == profile.build_index_path
    ]
    if len(index_rows) != 1:
        raise CaptureError("Explorer build manifest lacks one unique root index")
    index = index_rows[0]
    if (
        index["bytes"] != profile.build_index_bytes
        or index["sha256"] != profile.build_index_sha256
    ):
        raise CaptureError("Explorer build index differs from target")
    return {
        "algorithm": CANONICAL_MATERIALS_ALGORITHM,
        "index": index,
        "manifest": file_material(
            profile.build_manifest_path,
            len(body),
            sha256_bytes(body),
        ),
        "materials": actual_rows,
        "schema": BUILD_MANIFEST_SCHEMA,
        "tree": {
            "algorithm": CANONICAL_MATERIALS_ALGORITHM,
            "computed_sha256": tree_digest,
            "files": len(actual_rows),
            "sha256": profile.build_tree_sha256,
        },
    }


def _validate_zip_entry(
    info: zipfile.ZipInfo,
    profile: TargetProfile,
    entry_count: int,
) -> dict[str, Any]:
    if entry_count != 1 or info.filename != profile.tar_name:
        raise CaptureError("Pages ZIP must contain exactly artifact.tar")
    if (
        info.is_dir()
        or info.flag_bits & 0x1
        or info.file_size != profile.tar_bytes
        or info.file_size > MAXIMUM_TAR_BYTES
        or info.compress_size < 1
        or info.file_size > info.compress_size * MAXIMUM_COMPRESSION_RATIO
    ):
        raise CaptureError(
            "Pages ZIP entry is encrypted, non-regular, oversized, or bomb-like"
        )
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode and not stat.S_ISREG(mode):
        raise CaptureError("Pages ZIP entry is not a regular file")
    if info.external_attr & 0x10:
        raise CaptureError("Pages ZIP entry has a directory attribute")
    return {
        "compressed_bytes": info.compress_size,
        "crc32": f"{info.CRC:08x}",
        "encrypted": False,
        "name": profile.tar_name,
        "regular_file": True,
        "uncompressed_bytes": info.file_size,
    }


def _read_exact(reader: _HashingBoundedReader, size: int, label: str) -> bytes:
    body = bytearray()
    while len(body) < size:
        chunk = reader.read(size - len(body))
        if not chunk:
            raise CaptureError(f"TAR ended while reading {label}")
        body.extend(chunk)
    return bytes(body)


def _tar_octal(field: bytes, label: str) -> int:
    if field and field[0] & 0x80:
        raise CaptureError(f"TAR {label} uses forbidden base-256 encoding")
    stripped = field.rstrip(b"\0 ").lstrip(b" ")
    if not stripped:
        return 0
    if any(value not in b"01234567" for value in stripped):
        raise CaptureError(f"TAR {label} is not canonical octal")
    try:
        return int(stripped, 8)
    except ValueError as error:
        raise CaptureError(f"TAR {label} is invalid") from error


def _tar_text(field: bytes, label: str) -> str:
    raw = field.split(b"\0", 1)[0]
    try:
        value = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise CaptureError(f"TAR {label} is not strict UTF-8") from error
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CaptureError(f"TAR {label} contains a Unicode surrogate")
    return value


def _raw_header_path(header: bytes) -> str:
    name = _tar_text(header[0:100], "header name")
    prefix = _tar_text(header[345:500], "header prefix")
    return f"{prefix}/{name}" if prefix else name


def _validate_tar_checksum(header: bytes) -> None:
    declared = _tar_octal(header[148:156], "header checksum")
    computed = sum(header[:148]) + (8 * ord(" ")) + sum(header[156:])
    if declared != computed:
        raise CaptureError("TAR raw header checksum is invalid")


def _scan_raw_tar_headers(
    source: BinaryIO,
    *,
    profile: TargetProfile,
    logical_members: list[tuple[str, str]],
) -> dict[str, int]:
    """Prove raw GNU TAR spelling and reconcile every logical member."""

    reader = _HashingBoundedReader(source, profile.tar_bytes)
    raw_headers = 0
    gnu_longnames = 0
    logical_index = 0
    regular_headers = 0
    directory_headers = 0
    pending_longname: str | None = None
    while True:
        header = _read_exact(reader, 512, "raw header")
        if header == b"\0" * 512:
            second = _read_exact(reader, 512, "second TAR end marker")
            if second != b"\0" * 512:
                raise CaptureError("TAR has only one canonical end marker")
            if pending_longname is not None:
                raise CaptureError("GNU long-name header lacks a target member")
            while True:
                trailing = reader.read(STREAM_CHUNK_BYTES)
                if not trailing:
                    break
                if trailing.strip(b"\0"):
                    raise CaptureError("TAR has non-zero data after end markers")
            break
        raw_headers += 1
        if raw_headers > profile.tar_raw_header_count:
            raise CaptureError("TAR raw-header count exceeds fixed target")
        _validate_tar_checksum(header)
        typeflag = header[156:157]
        size = _tar_octal(header[124:136], "member size")
        if size > MAXIMUM_TAR_FILE_BYTES and typeflag != b"L":
            raise CaptureError("TAR raw member size exceeds hard cap")
        padded_size = ((size + 511) // 512) * 512
        if typeflag == b"L":
            if pending_longname is not None:
                raise CaptureError("consecutive GNU long-name headers are forbidden")
            if size < 2 or size > (MAXIMUM_ARCHIVE_PATH_UTF16_UNITS * 4) + 1:
                raise CaptureError("GNU long-name payload size is invalid")
            payload = _read_exact(reader, padded_size, "GNU long-name payload")
            value = payload[:size]
            if not value.endswith(b"\0") or b"\0" in value[:-1]:
                raise CaptureError("GNU long-name payload is not NUL canonical")
            if payload[size:].strip(b"\0"):
                raise CaptureError("GNU long-name padding is non-zero")
            try:
                pending_longname = value[:-1].decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise CaptureError("GNU long-name is not strict UTF-8") from error
            gnu_longnames += 1
            continue
        if typeflag not in {b"0", b"5"}:
            raise CaptureError(
                "TAR raw header has a forbidden non-file type flag"
            )
        if logical_index >= len(logical_members):
            raise CaptureError("TAR raw headers exceed logical member closure")
        directory = typeflag == b"5"
        raw_name = pending_longname or _raw_header_path(header)
        pending_longname = None
        canonical = canonical_tar_path(raw_name, directory=directory)
        expected_path, expected_kind = logical_members[logical_index]
        actual_kind = "directory" if directory else "file"
        if (canonical, actual_kind) != (expected_path, expected_kind):
            raise CaptureError(
                "TAR raw header disagrees with logical member scan"
            )
        logical_index += 1
        if directory:
            directory_headers += 1
            if size != 0:
                raise CaptureError("TAR raw directory size is non-zero")
        else:
            regular_headers += 1
            remaining = size
            while remaining:
                chunk = _read_exact(
                    reader,
                    min(STREAM_CHUNK_BYTES, remaining),
                    "regular-file body",
                )
                remaining -= len(chunk)
            padding_size = padded_size - size
            if padding_size:
                padding = _read_exact(
                    reader,
                    padding_size,
                    "regular-file padding",
                )
                if padding.strip(b"\0"):
                    raise CaptureError("TAR regular-file padding is non-zero")
    if (
        reader.bytes_read != profile.tar_bytes
        or logical_index != len(logical_members)
        or raw_headers != profile.tar_raw_header_count
        or gnu_longnames != profile.tar_gnu_longname_count
        or regular_headers != profile.tar_file_count
        or directory_headers != profile.tar_directory_count
    ):
        raise CaptureError("TAR raw-header census differs from fixed target")
    return {
        "directory_headers": directory_headers,
        "gnu_longname_headers": gnu_longnames,
        "logical_members": logical_index,
        "raw_headers": raw_headers,
        "regular_headers": regular_headers,
    }


def _read_zip_region(
    source: BinaryIO,
    offset: int,
    length: int,
    label: str,
) -> bytes:
    if offset < 0 or length < 0:
        raise CaptureError(f"ZIP {label} has invalid bounds")
    source.seek(offset)
    body = source.read(length)
    if not isinstance(body, bytes) or len(body) != length:
        raise CaptureError(f"ZIP {label} is truncated")
    return body


def _preflight_zip_central_directory(
    source: BinaryIO,
    archive_bytes: int,
) -> None:
    """Validate EOCD/ZIP64 and one-entry central-directory bounds first."""

    if archive_bytes < 22:
        raise CaptureError("Pages ZIP is too short for an EOCD record")
    tail_bytes = min(archive_bytes, 22 + 65_535)
    tail_offset = archive_bytes - tail_bytes
    tail = _read_zip_region(source, tail_offset, tail_bytes, "EOCD search")
    signature = b"PK\x05\x06"
    position = len(tail)
    eocd_offset: int | None = None
    eocd: tuple[Any, ...] | None = None
    while True:
        position = tail.rfind(signature, 0, position)
        if position < 0:
            break
        if position + 22 <= len(tail):
            candidate = struct.unpack_from("<4s4H2LH", tail, position)
            if position + 22 + candidate[7] == len(tail):
                eocd_offset = tail_offset + position
                eocd = candidate
                break
        if position == 0:
            break
    if eocd_offset is None or eocd is None:
        raise CaptureError("Pages ZIP lacks one terminal EOCD record")
    (
        _eocd_signature,
        disk_number,
        directory_disk,
        disk_entries,
        total_entries,
        directory_bytes,
        directory_offset,
        comment_bytes,
    ) = eocd
    if comment_bytes != 0:
        raise CaptureError("Pages ZIP archive comments are forbidden")
    if disk_number != 0 or directory_disk != 0:
        raise CaptureError("multi-disk ZIP archives are forbidden")

    zip64 = any(
        value == sentinel
        for value, sentinel in (
            (disk_entries, 0xFFFF),
            (total_entries, 0xFFFF),
            (directory_bytes, 0xFFFFFFFF),
            (directory_offset, 0xFFFFFFFF),
        )
    )
    directory_boundary = eocd_offset
    if zip64:
        locator_offset = eocd_offset - 20
        locator = _read_zip_region(
            source,
            locator_offset,
            20,
            "ZIP64 EOCD locator",
        )
        (
            locator_signature,
            locator_disk,
            zip64_offset,
            total_disks,
        ) = struct.unpack("<4sLQL", locator)
        if (
            locator_signature != b"PK\x06\x07"
            or locator_disk != 0
            or total_disks != 1
        ):
            raise CaptureError("ZIP64 EOCD locator is invalid")
        fixed = _read_zip_region(
            source,
            zip64_offset,
            56,
            "ZIP64 EOCD record",
        )
        values = struct.unpack("<4sQ2H2L4Q", fixed)
        if (
            values[0] != b"PK\x06\x06"
            or values[1] != 44
            or values[4] != 0
            or values[5] != 0
            or zip64_offset + 56 != locator_offset
        ):
            raise CaptureError("ZIP64 EOCD record is invalid")
        zip64_disk_entries = values[6]
        zip64_total_entries = values[7]
        zip64_directory_bytes = values[8]
        zip64_directory_offset = values[9]
        for classic, sentinel, expanded, label in (
            (disk_entries, 0xFFFF, zip64_disk_entries, "disk entry count"),
            (total_entries, 0xFFFF, zip64_total_entries, "entry count"),
            (
                directory_bytes,
                0xFFFFFFFF,
                zip64_directory_bytes,
                "central-directory size",
            ),
            (
                directory_offset,
                0xFFFFFFFF,
                zip64_directory_offset,
                "central-directory offset",
            ),
        ):
            if classic != sentinel and classic != expanded:
                raise CaptureError(f"ZIP64 {label} disagrees with EOCD")
        disk_entries = zip64_disk_entries
        total_entries = zip64_total_entries
        directory_bytes = zip64_directory_bytes
        directory_offset = zip64_directory_offset
        directory_boundary = zip64_offset

    if disk_entries != 1 or total_entries != 1:
        raise CaptureError("Pages ZIP central directory must contain one entry")
    if (
        directory_bytes < 46
        or directory_offset >= directory_boundary
        or directory_offset + directory_bytes != directory_boundary
    ):
        raise CaptureError("Pages ZIP central-directory bounds are invalid")
    central = _read_zip_region(
        source,
        directory_offset,
        directory_bytes,
        "central directory",
    )
    if central[:4] != b"PK\x01\x02":
        raise CaptureError("Pages ZIP central-directory signature is invalid")
    fixed = struct.unpack_from("<4s6H3L5H2L", central, 0)
    name_bytes, extra_bytes, entry_comment_bytes = fixed[10:13]
    if (
        46 + name_bytes + extra_bytes + entry_comment_bytes
        != directory_bytes
    ):
        raise CaptureError(
            "Pages ZIP central directory contains hidden or extra entries"
        )
    if fixed[13] not in {0, 0xFFFF}:
        raise CaptureError("Pages ZIP entry starts on another disk")
    local_offset = fixed[16]
    if local_offset != 0:
        raise CaptureError(
            "Pages ZIP has a ZIP64 or prepended local-header offset"
        )
    if (
        _read_zip_region(source, local_offset, 4, "local-file header")
        != b"PK\x03\x04"
    ):
        raise CaptureError("Pages ZIP local-file signature is invalid")
    source.seek(0)


def scan_pages_zip(path: Path, profile: TargetProfile) -> ArchiveScan:
    _validate_profile(profile)
    descriptor, before = _stable_open(path, "Pages ZIP")
    try:
        if before.st_size != profile.zip_bytes:
            raise CaptureError("Pages ZIP byte count differs from target")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            _preflight_zip_central_directory(source, before.st_size)
            try:
                archive = zipfile.ZipFile(source)
            except (zipfile.BadZipFile, OSError) as error:
                raise CaptureError("Pages artifact is not a valid ZIP") from error
            with archive:
                entries = archive.infolist()
                if len(entries) != 1:
                    raise CaptureError(
                        "Pages ZIP must contain exactly one archive member"
                    )
                info = entries[0]
                zip_entry = _validate_zip_entry(info, profile, len(entries))
                try:
                    zipped_tar = archive.open(info, "r")
                except (RuntimeError, zipfile.BadZipFile, OSError) as error:
                    raise CaptureError("cannot open Pages TAR ZIP entry") from error
                with zipped_tar:
                    reader = _HashingBoundedReader(
                        zipped_tar,
                        profile.tar_bytes,
                    )
                    try:
                        tar = tarfile.open(
                            fileobj=reader,
                            mode="r|",
                            encoding="utf-8",
                            errors="surrogateescape",
                        )
                    except (tarfile.TarError, OSError) as error:
                        raise CaptureError("ZIP entry is not a valid TAR") from error
                    file_rows: list[dict[str, Any]] = []
                    kinds: dict[str, str] = {}
                    manifest_body: bytes | None = None
                    logical_members: list[tuple[str, str]] = []
                    member_count = 0
                    directory_count = 0
                    total_file_bytes = 0
                    try:
                        for member in tar:
                            member_count += 1
                            if (
                                member_count > profile.tar_member_count
                                or member_count > MAXIMUM_TAR_MEMBERS
                            ):
                                raise CaptureError(
                                    "TAR member count exceeds its fixed limit"
                                )
                            logical_name = member.get_info().get("name")
                            if not isinstance(logical_name, str):
                                raise CaptureError(
                                    "TAR member lacks a stable logical name"
                                )
                            if member.isdir():
                                canonical = canonical_tar_path(
                                    logical_name,
                                    directory=True,
                                )
                                kind = "directory"
                                directory_count += 1
                                if member.size != 0:
                                    raise CaptureError(
                                        "TAR directory has a non-zero size"
                                    )
                            elif member.isreg():
                                canonical = canonical_tar_path(
                                    logical_name,
                                    directory=False,
                                )
                                kind = "file"
                                if getattr(member, "sparse", None):
                                    raise CaptureError(
                                        "sparse TAR files are forbidden"
                                    )
                                total_file_bytes += member.size
                                if total_file_bytes > profile.tar_bytes:
                                    raise CaptureError(
                                        "TAR file total exceeds archive bound"
                                    )
                                row, retained = _read_tar_file(
                                    tar,
                                    member,
                                    retain=(
                                        canonical
                                        == profile.build_manifest_path
                                    ),
                                )
                                row = {
                                    "path": canonical,
                                    **row,
                                }
                                file_rows.append(row)
                                if retained is not None:
                                    if manifest_body is not None:
                                        raise CaptureError(
                                            "build manifest is duplicated"
                                        )
                                    manifest_body = retained
                            else:
                                raise CaptureError(
                                    "TAR contains a link, device, FIFO, "
                                    "or other non-file member"
                                )
                            if canonical in kinds:
                                raise CaptureError(
                                    f"TAR member path is duplicated: {canonical}"
                                )
                            kinds[canonical] = kind
                            logical_members.append((canonical, kind))
                    except (tarfile.TarError, OSError) as error:
                        raise CaptureError("TAR scan failed closed") from error
                    finally:
                        tar.close()
                    while reader.read(STREAM_CHUNK_BYTES):
                        pass
                    if (
                        reader.bytes_read != profile.tar_bytes
                        or reader.digest.hexdigest() != profile.tar_sha256
                    ):
                        raise CaptureError(
                            "TAR bytes or SHA-256 differ from target"
                        )
                try:
                    raw_tar = archive.open(info, "r")
                except (RuntimeError, zipfile.BadZipFile, OSError) as error:
                    raise CaptureError(
                        "cannot reopen Pages TAR for raw-header proof"
                    ) from error
                with raw_tar:
                    raw_header_census = _scan_raw_tar_headers(
                        raw_tar,
                        profile=profile,
                        logical_members=logical_members,
                    )
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    declared = os.stat(path, follow_symlinks=False)
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_nlink,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_nlink,
    ) or (
        declared.st_dev,
        declared.st_ino,
        declared.st_size,
        declared.st_mtime_ns,
        declared.st_ctime_ns,
        declared.st_nlink,
    ) != identity:
        raise CaptureError("Pages ZIP changed during archive scan")
    if member_count != profile.tar_member_count:
        raise CaptureError("TAR member count differs from target")
    if kinds.get(".") != "directory":
        raise CaptureError("TAR lacks one canonical root directory")
    for path_value, kind in kinds.items():
        if path_value == ".":
            continue
        parts = path_value.split("/")
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index])
            if kinds.get(ancestor) == "file":
                raise CaptureError(
                    "TAR regular file is an ancestor of another member"
                )
        if kind == "directory" and path_value in {
            row["path"] for row in file_rows
        }:
            raise CaptureError("TAR path is both file and directory")
    if manifest_body is None:
        raise CaptureError("TAR lacks the root Explorer build manifest")
    if (
        len(manifest_body) != profile.build_manifest_bytes
        or sha256_bytes(manifest_body) != profile.build_manifest_sha256
    ):
        raise CaptureError("Explorer build manifest differs from target")
    file_rows.sort(key=lambda row: row["path"])
    inventory_digest = sha256_bytes(canonical_materials_bytes(file_rows))
    if (
        total_file_bytes != profile.tar_total_file_bytes
        or inventory_digest != profile.tar_inventory_sha256
    ):
        raise CaptureError(
            "TAR total bytes or inventory SHA-256 differs from target"
        )
    inventory = {
        "algorithm": CANONICAL_MATERIALS_ALGORITHM,
        "file_count": len(file_rows),
        "materials": file_rows,
        "materials_sha256": inventory_digest,
        "schema": INVENTORY_SCHEMA,
        "total_file_bytes": total_file_bytes,
    }
    inventory_body = render_json(inventory)
    inventory_by_path = {row["path"]: row for row in file_rows}
    build = _parse_build_manifest(
        manifest_body,
        profile=profile,
        inventory_by_path=inventory_by_path,
    )
    return ArchiveScan(
        zip_entry=zip_entry,
        tar={
            "bytes": profile.tar_bytes,
            "directory_count": directory_count,
            "file_count": len(file_rows),
            "member_count": member_count,
            "name": profile.tar_name,
            "retained_separately": False,
            "sha256": profile.tar_sha256,
            "total_file_bytes": total_file_bytes,
            "raw_header_census": raw_header_census,
        },
        inventory=inventory,
        inventory_body=inventory_body,
        build=build,
    )


def _validate_schema(document: dict[str, Any]) -> None:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureError("Pages observation schema is unavailable") from error
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(document),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        location = "/".join(
            str(part) for part in errors[0].absolute_path
        )
        raise CaptureError(
            "generated Pages observation failed schema validation"
            + (f" at {location}" if location else "")
        )


def _external_destination(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise CaptureError(
            "output directory must be absolute and contain no traversal"
        )
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise CaptureError(
            "output parent must be an existing non-symlink directory"
        )
    resolved_parent = parent.resolve(strict=True)
    resolved_root = ROOT.resolve()
    destination = resolved_parent / path.name
    if destination == resolved_root or destination.is_relative_to(resolved_root):
        raise CaptureError("output directory must be outside the repository")
    if path.is_symlink():
        raise CaptureError("output directory cannot be a symlink")
    return destination


def _write_new_file(path: Path, body: bytes, *, private: bool = False) -> None:
    if not isinstance(body, bytes) or not body:
        raise CaptureError(f"refusing empty output file: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    if private:
        os.chmod(path, 0o600)


def _fsync_directories(root: Path) -> None:
    directories = [
        path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()
    ]
    for path in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        _fsync_directory_path(path)
    _fsync_directory_path(root)


def _fsync_directory_path(path: Path) -> None:
    """Durably flush one directory or fail closed on the active platform."""

    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(path),
            0x80000000,
            0x00000001 | 0x00000002 | 0x00000004,
            None,
            3,
            0x02000000,
            None,
        )
        invalid = ctypes.c_void_p(-1).value
        if handle == invalid:
            raise CaptureError("cannot open publication parent for durability")
        try:
            if not kernel32.FlushFileBuffers(handle):
                raise CaptureError("cannot flush publication parent directory")
        finally:
            kernel32.CloseHandle(handle)
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename a directory while refusing an existing destination."""

    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel32.MoveFileExW
        move.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
        ]
        move.restype = wintypes.BOOL
        if not move(str(source), str(destination), 0x00000008):
            code = ctypes.get_last_error()
            if code in {80, 183}:
                raise CaptureError(
                    "competing writer created the evidence destination"
                )
            raise CaptureError(
                f"atomic no-replace publication failed (Windows error {code})"
            )
    elif sys.platform == "darwin":
        library = ctypes.CDLL(None, use_errno=True)
        renamex = getattr(library, "renamex_np", None)
        if renamex is None:
            raise CaptureError(
                "platform lacks atomic no-replace directory publication"
            )
        renamex.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renamex.restype = ctypes.c_int
        if renamex(
            os.fsencode(source),
            os.fsencode(destination),
            0x00000004,
        ) != 0:
            code = ctypes.get_errno()
            if code in {errno.EEXIST, errno.ENOTEMPTY}:
                raise CaptureError(
                    "competing writer created the evidence destination"
                )
            raise CaptureError(
                "atomic no-replace publication failed"
            ) from OSError(code, os.strerror(code))
    elif sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(library, "renameat2", None)
        if renameat2 is None:
            raise CaptureError(
                "platform lacks atomic no-replace directory publication"
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            0x00000001,
        ) != 0:
            code = ctypes.get_errno()
            if code in {errno.EEXIST, errno.ENOTEMPTY}:
                raise CaptureError(
                    "competing writer created the evidence destination"
                )
            raise CaptureError(
                "atomic no-replace publication failed"
            ) from OSError(code, os.strerror(code))
    else:
        raise CaptureError(
            "platform lacks atomic no-replace directory publication"
        )
    try:
        _fsync_directory_path(destination.parent)
    except (OSError, CaptureError) as error:
        raise CaptureError(
            "evidence directory was published but parent durability failed"
        ) from error


def _cleanup_partial(path: Path) -> None:
    """Remove a private partial tree and make any cleanup failure observable."""

    if not os.path.lexists(path):
        return
    try:
        shutil.rmtree(path)
    except OSError as error:
        try:
            os.chmod(path, 0o700, follow_symlinks=False)
        except OSError:
            pass
        raise CaptureError(
            f"partial evidence cleanup failed; quarantined at {path}"
        ) from error
    if os.path.lexists(path):
        raise CaptureError(
            f"partial evidence cleanup was incomplete at {path}"
        )


def _controller_material() -> dict[str, Any]:
    body = Path(__file__).read_bytes()
    return material(
        "scripts/capture_github_pages_observation.py",
        body,
    )


def _request_summary(
    purpose: str,
    result: FetchResult,
    headers_material: dict[str, Any],
) -> dict[str, Any]:
    return {
        "final_url": result.final_url_redacted,
        "http_status": result.status,
        "purpose": purpose,
        "redirects": len(result.hops) - 1,
        "response_headers": headers_material,
    }


def _alternate(profile: TargetProfile) -> dict[str, Any]:
    return {
        "asset_id": profile.alternate_asset_id,
        "bytes": profile.zip_bytes,
        "cross_binding": "required-from-github-release-observation",
        "github_digest": f"sha256:{profile.zip_sha256}",
        "name": profile.alternate_asset_name,
        "sha256": profile.zip_sha256,
        "url": profile.alternate_asset_url,
    }


def _archive_projection(
    *,
    scan: ArchiveScan,
    zip_material: dict[str, Any],
    inventory_material: dict[str, Any],
) -> dict[str, Any]:
    return {
        "build": scan.build,
        "inventory": {
            "algorithm": scan.inventory["algorithm"],
            "file_count": scan.inventory["file_count"],
            "material": inventory_material,
            "materials_sha256": scan.inventory["materials_sha256"],
            "total_file_bytes": scan.inventory["total_file_bytes"],
        },
        "tar": scan.tar,
        "zip": {
            "entry": scan.zip_entry,
            "material": zip_material,
        },
    }


def _target_projection(profile: TargetProfile) -> dict[str, Any]:
    return {
        "artifact_id": profile.artifact_id,
        "artifact_name": profile.artifact_name,
        "git_tree": profile.git_tree,
        "head_sha": profile.head_sha,
        "repository": profile.repository,
        "run_attempt": profile.run_attempt,
        "run_id": profile.run_id,
        "workflow_path": profile.workflow_path,
    }


def _persisted_headers_result(
    body: bytes,
    *,
    purpose: str,
    profile: TargetProfile,
    response_body: bytes | None,
    response_body_material: dict[str, Any] | None = None,
) -> FetchResult:
    """Reconstruct one fetch result from its canonical redacted hop document."""

    document = json_object(body, f"{purpose} response-header evidence")
    if (
        set(document) != {"schema", "purpose", "hops"}
        or document.get("schema")
        != "okf-github-pages-response-headers.v1"
        or document.get("purpose") != purpose
        or render_json(document) != body
    ):
        raise CaptureError(f"{purpose} response-header evidence is noncanonical")
    hops = document.get("hops")
    if not isinstance(hops, list) or not hops or len(hops) > MAXIMUM_REDIRECTS + 1:
        raise CaptureError(f"{purpose} persisted hop closure is invalid")
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(hops):
        if not isinstance(value, dict) or set(value) != {
            "completed_at",
            "location_query_redacted",
            "omitted_response_headers",
            "reason",
            "requested_at",
            "response_headers",
            "status",
            "url",
            "url_query_redacted",
        }:
            raise CaptureError(f"{purpose} persisted hop {index} shape is invalid")
        requested = validate_timestamp(
            value.get("requested_at"),
            f"{purpose} hop {index} request start",
        )
        completed = validate_timestamp(
            value.get("completed_at"),
            f"{purpose} hop {index} request completion",
        )
        if datetime.fromisoformat(completed.replace("Z", "+00:00")) < (
            datetime.fromisoformat(requested.replace("Z", "+00:00"))
        ):
            raise CaptureError(f"{purpose} persisted hop time is reversed")
        status = value.get("status")
        if (
            isinstance(status, bool)
            or not isinstance(status, int)
            or not 100 <= status <= 599
        ):
            raise CaptureError(f"{purpose} persisted hop status is invalid")
        reason = value.get("reason")
        if not isinstance(reason, str) or len(reason) > 256:
            raise CaptureError(f"{purpose} persisted hop reason is invalid")
        url = value.get("url")
        if not isinstance(url, str) or urlsplit(url).query:
            raise CaptureError(f"{purpose} persisted URL contains a query")
        _validate_https_url(url)
        if not isinstance(value.get("url_query_redacted"), bool) or not isinstance(
            value.get("location_query_redacted"),
            bool,
        ):
            raise CaptureError(f"{purpose} persisted redaction flags are invalid")
        omitted = value.get("omitted_response_headers")
        if (
            not isinstance(omitted, list)
            or omitted != sorted(set(omitted))
            or any(
                not isinstance(name, str)
                or not name
                or name != name.lower()
                or not HEADER_NAME.fullmatch(name)
                for name in omitted
            )
        ):
            raise CaptureError(f"{purpose} omitted-header receipt is invalid")
        headers = value.get("response_headers")
        if not isinstance(headers, list) or len(headers) > 256:
            raise CaptureError(f"{purpose} persisted response headers are invalid")
        header_bytes = 0
        for row in headers:
            if (
                not isinstance(row, dict)
                or set(row) != {"name", "value"}
                or not isinstance(row.get("name"), str)
                or not HEADER_NAME.fullmatch(row["name"])
                or not isinstance(row.get("value"), str)
                or any(character in row["value"] for character in "\r\n\0")
                or row["name"].lower() in SENSITIVE_RESPONSE_HEADERS
                or any(
                    marker in row["value"].lower()
                    for marker in SENSITIVE_VALUE_MARKERS
                )
            ):
                raise CaptureError(
                    f"{purpose} persisted response header is unsafe"
                )
            if row["name"].lower() == "location":
                location = row["value"]
                if urlsplit(location).query:
                    raise CaptureError(
                        f"{purpose} persisted Location contains a query"
                    )
                _validate_https_url(location)
            header_bytes += len(row["name"].encode("utf-8"))
            header_bytes += len(row["value"].encode("utf-8"))
        if header_bytes > MAXIMUM_HEADER_BYTES:
            raise CaptureError(f"{purpose} persisted headers exceed hard cap")
        normalized.append(
            {
                "completed_at": completed,
                "location_query_redacted": value[
                    "location_query_redacted"
                ],
                "omitted_response_headers": omitted,
                "reason": reason,
                "requested_at": requested,
                "response_headers": headers,
                "status": status,
                "url": url,
                "url_query_redacted": value["url_query_redacted"],
            }
        )
    if purpose == "workflow-run-attempt":
        if (
            len(normalized) != 1
            or normalized[0]["url"] != run_api_url(profile)
            or normalized[0]["status"] != 200
            or normalized[0]["url_query_redacted"]
            or normalized[0]["location_query_redacted"]
        ):
            raise CaptureError("persisted workflow-run route is invalid")
    elif purpose == "workflow-artifact":
        if (
            len(normalized) != 1
            or normalized[0]["url"] != artifact_api_url(profile)
            or normalized[0]["status"] != 200
            or normalized[0]["url_query_redacted"]
            or normalized[0]["location_query_redacted"]
        ):
            raise CaptureError("persisted artifact route is invalid")
    elif purpose == "workflow-artifact-download":
        if not 2 <= len(normalized) <= MAXIMUM_REDIRECTS + 1:
            raise CaptureError("persisted download redirect closure is invalid")
        storage_host: str | None = None
        for index, hop in enumerate(normalized):
            if index == 0:
                if (
                    hop["url"] != artifact_download_url(profile)
                    or hop["status"] not in REDIRECT_STATUSES
                    or hop["url_query_redacted"]
                    or not hop["location_query_redacted"]
                ):
                    raise CaptureError(
                        "persisted download API redirect is invalid"
                    )
            else:
                _canonical_storage_url(hop["url"])
                host = urlsplit(hop["url"]).hostname
                if storage_host is None:
                    storage_host = host
                elif host != storage_host:
                    raise CaptureError(
                        "persisted download changed Azure storage host"
                    )
                if not hop["url_query_redacted"]:
                    raise CaptureError(
                        "persisted Azure URL lacks query-redaction receipt"
                    )
                final_hop = index == len(normalized) - 1
                if (
                    final_hop
                    and (
                        hop["status"] != 200
                        or hop["location_query_redacted"]
                    )
                ) or (
                    not final_hop
                    and (
                        hop["status"] not in REDIRECT_STATUSES
                        or not hop["location_query_redacted"]
                    )
                ):
                    raise CaptureError(
                        "persisted Azure redirect status is invalid"
                    )
            if index < len(normalized) - 1:
                locations = _header_values(
                    hop["response_headers"],
                    "location",
                )
                if (
                    len(locations) != 1
                    or locations[0] != normalized[index + 1]["url"]
                ):
                    raise CaptureError(
                        "persisted redirect chain is discontinuous"
                    )
        if normalized[-1]["status"] != 200:
            raise CaptureError("persisted download final status is invalid")
    else:
        raise CaptureError("persisted response-header purpose is unsupported")
    if response_body is not None:
        body_bytes = len(response_body)
        body_sha256 = sha256_bytes(response_body)
    elif response_body_material is not None:
        if (
            set(response_body_material) != {"path", "bytes", "sha256"}
            or response_body_material.get("path") != ZIP_PATH
            or isinstance(response_body_material.get("bytes"), bool)
            or not isinstance(response_body_material.get("bytes"), int)
            or response_body_material["bytes"] < 1
        ):
            raise CaptureError(
                f"{purpose} persisted body material is invalid"
            )
        validate_digest(
            response_body_material.get("sha256"),
            f"{purpose} persisted body SHA-256",
        )
        body_bytes = response_body_material["bytes"]
        body_sha256 = response_body_material["sha256"]
    else:
        raise CaptureError(f"{purpose} persisted body identity is missing")
    result = FetchResult(
        body=response_body,
        body_bytes=body_bytes,
        body_sha256=body_sha256,
        final_url_redacted=normalized[-1]["url"],
        hops=normalized,
        status=normalized[-1]["status"],
    )
    if _headers_document(purpose, result) != body:
        raise CaptureError(f"{purpose} response-header evidence diverges")
    return result


def _evidence_rows(
    *,
    run_headers_body: bytes,
    run_body: bytes,
    artifact_headers_body: bytes,
    artifact_body: bytes,
    download_headers_body: bytes,
    inventory_body: bytes,
    zip_row: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = [
        {"role": role, **material(relative, body)}
        for role, relative, body in (
            ("run_response_headers", RUN_HEADERS_PATH, run_headers_body),
            ("run_response_body", RUN_BODY_PATH, run_body),
            (
                "artifact_response_headers",
                ARTIFACT_HEADERS_PATH,
                artifact_headers_body,
            ),
            ("artifact_response_body", ARTIFACT_BODY_PATH, artifact_body),
            (
                "download_response_headers",
                DOWNLOAD_HEADERS_PATH,
                download_headers_body,
            ),
            ("tar_file_inventory", INVENTORY_PATH, inventory_body),
        )
    ]
    rows.append({"role": "pages_zip", **zip_row})
    rows.sort(key=lambda row: row["path"])
    return rows


def _assemble_documents(
    *,
    profile: TargetProfile,
    observed_at: str,
    run_result: FetchResult,
    artifact_result: FetchResult,
    download_result: FetchResult,
    run_headers_body: bytes,
    artifact_headers_body: bytes,
    download_headers_body: bytes,
    scan: ArchiveScan,
    zip_row: dict[str, Any],
    controller: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the only accepted attempt and observation projections."""

    timestamp = validate_timestamp(observed_at, "observation timestamp")
    if run_result.body is None or artifact_result.body is None:
        raise CaptureError("API body closure is incomplete")
    run_projection = _validate_run(
        json_object(run_result.body, "workflow run response"),
        profile,
    )
    artifact_projection = _validate_artifact(
        json_object(artifact_result.body, "artifact response"),
        profile,
    )
    inventory_row = material(INVENTORY_PATH, scan.inventory_body)
    evidence_rows = _evidence_rows(
        run_headers_body=run_headers_body,
        run_body=run_result.body,
        artifact_headers_body=artifact_headers_body,
        artifact_body=artifact_result.body,
        download_headers_body=download_headers_body,
        inventory_body=scan.inventory_body,
        zip_row=zip_row,
    )
    request_rows = [
        _request_summary(
            "workflow-run-attempt",
            run_result,
            material(RUN_HEADERS_PATH, run_headers_body),
        ),
        _request_summary(
            "workflow-artifact",
            artifact_result,
            material(ARTIFACT_HEADERS_PATH, artifact_headers_body),
        ),
        _request_summary(
            "workflow-artifact-download",
            download_result,
            material(DOWNLOAD_HEADERS_PATH, download_headers_body),
        ),
    ]
    attempt = {
        "authentication": {
            "authorization_scope": "api.github.com-only-if-supplied",
            "credential_persisted": False,
            "request_headers_persisted": False,
            "token_presence_persisted": False,
        },
        "controller": controller,
        "limits": {
            "maximum_api_body_bytes": MAXIMUM_API_BODY_BYTES,
            "maximum_archive_path_utf16_units": (
                MAXIMUM_ARCHIVE_PATH_UTF16_UNITS
            ),
            "maximum_redirects": MAXIMUM_REDIRECTS,
            "maximum_tar_bytes": MAXIMUM_TAR_BYTES,
            "maximum_tar_file_bytes": MAXIMUM_TAR_FILE_BYTES,
            "maximum_tar_members": MAXIMUM_TAR_MEMBERS,
            "maximum_zip_bytes": MAXIMUM_ZIP_BYTES,
            "per_request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "retries": 0,
        },
        "materials": evidence_rows,
        "observed_at": timestamp,
        "requests": request_rows,
        "schema": ATTEMPT_SCHEMA,
        "status": "complete",
        "target": _target_projection(profile),
        "transport": {
            "api_auth_host": API_HOST,
            "automatic_redirects": False,
            "azure_redirect_host_suffix": AZURE_BLOB_SUFFIX,
            "cookies_persisted": False,
            "dns_public_only": True,
            "signed_queries_persisted": False,
            "tls_peer_pinned_to_reviewed_dns": True,
        },
        "write_once": True,
    }
    attempt_body = render_json(attempt)
    observation = {
        "archive": _archive_projection(
            scan=scan,
            zip_material=zip_row,
            inventory_material=inventory_row,
        ),
        "artifact": {
            **artifact_projection,
            "response_body": material(
                ARTIFACT_BODY_PATH,
                artifact_result.body,
            ),
            "response_headers": material(
                ARTIFACT_HEADERS_PATH,
                artifact_headers_body,
            ),
        },
        "controller": controller,
        "durable_alternate": _alternate(profile),
        "integrity": {
            "attempt_manifest": material(
                ATTEMPT_MANIFEST_PATH,
                attempt_body,
            ),
            "raw_evidence_closed": True,
            "write_once": True,
        },
        "observed_at": timestamp,
        "requests": request_rows,
        "run": {
            **run_projection,
            "response_body": material(RUN_BODY_PATH, run_result.body),
            "response_headers": material(
                RUN_HEADERS_PATH,
                run_headers_body,
            ),
        },
        "schema": OBSERVATION_SCHEMA,
        "status": "verified",
        "target": _target_projection(profile),
    }
    _validate_schema(observation)
    return attempt, observation


def _enumerate_output(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()

    def visit(directory: Path, relative: PurePosixPath) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                candidate = (
                    PurePosixPath(entry.name)
                    if str(relative) == "."
                    else relative / entry.name
                )
                safe = validate_evidence_path(candidate.as_posix())
                if entry.is_symlink():
                    raise CaptureError(f"output contains a symlink: {safe}")
                details = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(details.st_mode):
                    directories.add(safe)
                    visit(Path(entry.path), candidate)
                elif stat.S_ISREG(details.st_mode):
                    if details.st_nlink != 1:
                        raise CaptureError(
                            f"output file is not single-link: {safe}"
                        )
                    files.add(safe)
                else:
                    raise CaptureError(
                        f"output contains a non-regular entry: {safe}"
                    )

    visit(root, PurePosixPath("."))
    return files, directories


def _verify_existing(
    destination: Path,
    profile: TargetProfile,
) -> Path:
    if destination.is_symlink() or not destination.is_dir():
        raise CaptureError("existing output is not a regular evidence directory")
    expected_material_paths = {
        RUN_HEADERS_PATH,
        RUN_BODY_PATH,
        ARTIFACT_HEADERS_PATH,
        ARTIFACT_BODY_PATH,
        DOWNLOAD_HEADERS_PATH,
        ZIP_PATH,
        INVENTORY_PATH,
    }
    files, directories = _enumerate_output(destination)
    if files != expected_material_paths | {
        ATTEMPT_MANIFEST_PATH,
        OBSERVATION_FILENAME,
    } or directories != {"raw", "inventory"}:
        raise CaptureError("existing evidence file closure diverges")

    run_headers_body = stable_read(
        destination / RUN_HEADERS_PATH,
        "existing run response headers",
        MAXIMUM_API_BODY_BYTES,
    )
    artifact_headers_body = stable_read(
        destination / ARTIFACT_HEADERS_PATH,
        "existing artifact response headers",
        MAXIMUM_API_BODY_BYTES,
    )
    download_headers_body = stable_read(
        destination / DOWNLOAD_HEADERS_PATH,
        "existing download response headers",
        MAXIMUM_API_BODY_BYTES,
    )
    run_body = stable_read(
        destination / RUN_BODY_PATH,
        "existing run response",
        MAXIMUM_API_BODY_BYTES,
    )
    artifact_body = stable_read(
        destination / ARTIFACT_BODY_PATH,
        "existing artifact response",
        MAXIMUM_API_BODY_BYTES,
    )
    inventory_body = stable_read(
        destination / INVENTORY_PATH,
        "existing TAR inventory",
        MAXIMUM_API_BODY_BYTES * 4,
    )
    attempt_body = stable_read(
        destination / ATTEMPT_MANIFEST_PATH,
        "existing attempt manifest",
        MAXIMUM_API_BODY_BYTES,
    )
    observation_path = destination / OBSERVATION_FILENAME
    observation_body = stable_read(
        observation_path,
        "existing Pages observation",
        MAXIMUM_API_BODY_BYTES,
    )
    observation = json_object(observation_body, "existing Pages observation")
    _validate_schema(observation)

    zip_row = stable_file_material(
        destination / ZIP_PATH,
        ZIP_PATH,
        "existing Pages ZIP",
        MAXIMUM_ZIP_BYTES,
    )
    if (
        zip_row["bytes"] != profile.zip_bytes
        or zip_row["sha256"] != profile.zip_sha256
    ):
        raise CaptureError("existing Pages ZIP differs from target")
    scan = scan_pages_zip(destination / ZIP_PATH, profile)
    if inventory_body != scan.inventory_body:
        raise CaptureError("existing TAR inventory diverges")

    try:
        run_result = _persisted_headers_result(
            run_headers_body,
            purpose="workflow-run-attempt",
            profile=profile,
            response_body=run_body,
        )
        artifact_result = _persisted_headers_result(
            artifact_headers_body,
            purpose="workflow-artifact",
            profile=profile,
            response_body=artifact_body,
        )
        download_result = _persisted_headers_result(
            download_headers_body,
            purpose="workflow-artifact-download",
            profile=profile,
            response_body=None,
            response_body_material=zip_row,
        )
        timestamp = validate_timestamp(
            run_result.hops[0]["requested_at"],
            "existing observation timestamp",
        )
        expected_attempt, expected_observation = _assemble_documents(
            profile=profile,
            observed_at=timestamp,
            run_result=run_result,
            artifact_result=artifact_result,
            download_result=download_result,
            run_headers_body=run_headers_body,
            artifact_headers_body=artifact_headers_body,
            download_headers_body=download_headers_body,
            scan=scan,
            zip_row=zip_row,
            controller=_controller_material(),
        )
    except CaptureError as error:
        raise CaptureError(
            "existing evidence diverges from its fixed raw semantics"
        ) from error
    if attempt_body != render_json(expected_attempt):
        raise CaptureError(
            "existing attempt manifest diverges from raw evidence"
        )
    if observation_body != render_json(expected_observation):
        raise CaptureError(
            "existing Pages observation diverges from raw evidence"
        )
    return observation_path


def capture_observation(
    *,
    output_dir: Path,
    token: str | None = None,
    transport: Transport | None = None,
    resolver: AddressResolver = resolve_public_addresses,
    clock: Clock = utc_timestamp,
    observed_at: str | None = None,
    profile: TargetProfile = DEFAULT_PROFILE,
    publication_barrier: Callable[[], None] | None = None,
) -> Path:
    """Capture and atomically publish one verified Pages observation."""

    _validate_profile(profile)
    destination = _external_destination(output_dir)
    if os.path.lexists(destination):
        return _verify_existing(destination, profile)
    supplied_timestamp = (
        validate_timestamp(observed_at, "observation timestamp")
        if observed_at is not None
        else None
    )
    network = transport or PinnedHTTPSNetworkTransport()

    run_result = _fetch_api(
        transport=network,
        resolver=resolver,
        url=run_api_url(profile),
        expected_url=run_api_url(profile),
        token=token,
        purpose="workflow-run-attempt",
        clock=clock,
    )
    if run_result.status != 200 or run_result.body is None:
        raise CaptureError(
            f"workflow run API returned HTTP {run_result.status}"
        )
    _validate_run(
        json_object(run_result.body, "workflow run response"),
        profile,
    )
    timestamp = validate_timestamp(
        run_result.hops[0]["requested_at"],
        "observation timestamp",
    )
    if supplied_timestamp is not None and supplied_timestamp != timestamp:
        raise CaptureError(
            "supplied observation timestamp differs from raw request evidence"
        )

    artifact_result = _fetch_api(
        transport=network,
        resolver=resolver,
        url=artifact_api_url(profile),
        expected_url=artifact_api_url(profile),
        token=token,
        purpose="workflow-artifact",
        clock=clock,
    )
    if artifact_result.status != 200 or artifact_result.body is None:
        raise CaptureError(
            f"artifact API returned HTTP {artifact_result.status}"
        )
    _validate_artifact(
        json_object(artifact_result.body, "artifact response"),
        profile,
    )

    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.partial-",
            dir=destination.parent,
        )
    )
    os.chmod(temporary, 0o700)
    try:
        (temporary / "raw").mkdir()
        zip_path = temporary / ZIP_PATH
        download_result = _fetch_zip(
            transport=network,
            resolver=resolver,
            profile=profile,
            token=token,
            destination=zip_path,
            clock=clock,
        )
        scan = scan_pages_zip(zip_path, profile)

        run_headers_body = _headers_document(
            "workflow-run-attempt",
            run_result,
        )
        artifact_headers_body = _headers_document(
            "workflow-artifact",
            artifact_result,
        )
        download_headers_body = _headers_document(
            "workflow-artifact-download",
            download_result,
        )
        source_bodies = {
            RUN_HEADERS_PATH: run_headers_body,
            RUN_BODY_PATH: run_result.body,
            ARTIFACT_HEADERS_PATH: artifact_headers_body,
            ARTIFACT_BODY_PATH: artifact_result.body,
            DOWNLOAD_HEADERS_PATH: download_headers_body,
            INVENTORY_PATH: scan.inventory_body,
        }
        _ensure_secret_absent(token, list(source_bodies.values()))
        for relative, body in source_bodies.items():
            _write_new_file(
                temporary / relative,
                body,
                private=relative.startswith("raw/"),
            )
        zip_row = {
            "path": ZIP_PATH,
            "bytes": download_result.body_bytes,
            "sha256": download_result.body_sha256,
        }
        assert isinstance(zip_row["sha256"], str)
        controller = _controller_material()
        attempt, observation = _assemble_documents(
            profile=profile,
            observed_at=timestamp,
            run_result=run_result,
            artifact_result=artifact_result,
            download_result=download_result,
            run_headers_body=run_headers_body,
            artifact_headers_body=artifact_headers_body,
            download_headers_body=download_headers_body,
            scan=scan,
            zip_row=zip_row,
            controller=controller,
        )
        attempt_body = render_json(attempt)
        _write_new_file(
            temporary / ATTEMPT_MANIFEST_PATH,
            attempt_body,
        )
        _write_new_file(
            temporary / OBSERVATION_FILENAME,
            render_json(observation),
        )
        _fsync_directories(temporary)
        if publication_barrier is not None:
            publication_barrier()
        _atomic_publish_no_replace(temporary, destination)
    except BaseException as error:
        try:
            _cleanup_partial(temporary)
        except CaptureError as cleanup_error:
            raise cleanup_error from error
        raise
    return destination / OBSERVATION_FILENAME


def _error_text(error: BaseException, token: str | None) -> str:
    text = str(error)
    if token:
        text = text.replace(token, "[REDACTED]")

    def redact_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,;:)]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return "[REDACTED-URL]" + trailing
        if parsed.scheme == "https" and parsed.netloc and parsed.query:
            return _redacted_url(raw) + trailing
        return raw + trailing

    text = re.sub(r"https://[^\s<>'\"]+", redact_url, text)
    return re.sub(
        r"([?&][A-Za-z0-9_.~-]+)=([^&\s]*)",
        r"\1=[REDACTED]",
        text,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="required acknowledgement before the bounded GitHub requests",
    )
    args = parser.parse_args(argv)
    if not args.allow_network:
        parser.error("--allow-network is required")
    token = os.environ.get("GITHUB_TOKEN") or None
    try:
        result = capture_observation(
            output_dir=args.output_dir,
            token=token,
        )
    except (CaptureError, OSError) as error:
        print(f"capture failed: {_error_text(error, token)}", file=sys.stderr)
        return 2
    except BaseException as error:
        print(
            "capture failed: unexpected "
            f"{type(error).__name__}; no retry was attempted",
            file=sys.stderr,
        )
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
