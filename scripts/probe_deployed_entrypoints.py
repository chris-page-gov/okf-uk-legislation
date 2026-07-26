#!/usr/bin/env python3
"""Capture a bounded, unauthenticated GATE-09 public-entrypoint attempt.

The command is deliberately inert unless both an exact, locked release
candidate manifest and ``--allow-network`` are supplied.  Requests use a
fixed header set without credentials or cookies.  Every initial URL is
literal in the manifest; redirects are followed manually and only to the
route's explicit HTTPS host allowlist.  DNS answers must all be globally
routable and the selected address is pinned for the TLS connection.

Raw response headers and bounded response bodies are retained in a write-once
attempt directory.  ``projection.json`` is the safe publication surface: it
contains selected non-sensitive headers, hashes and validation results, never
response bodies or Set-Cookie values.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import multiprocessing
import os
import re
import shutil
import socket
import ssl
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - the release venv pins jsonschema
    Draft202012Validator = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT / "release-assurance" / "deployed-entrypoints-manifest.json"
)
DEFAULT_OUTPUT_ROOT = (
    ROOT / "release-assurance" / "deployed-entrypoint-attempts"
)
MANIFEST_SCHEMA = (
    ROOT
    / "release-assurance"
    / "schemas"
    / "deployed-entrypoints-manifest.schema.json"
)
PROJECTION_SCHEMA = (
    ROOT
    / "release-assurance"
    / "schemas"
    / "deployed-entrypoint-projection.schema.json"
)
ATTEMPT_SCHEMA = (
    ROOT
    / "release-assurance"
    / "schemas"
    / "deployed-entrypoint-attempt.schema.json"
)

MANIFEST_SCHEMA_ID = "okf-deployed-entrypoint-manifest.v1"
PROJECTION_SCHEMA_ID = "okf-deployed-entrypoint-projection.v1"
ATTEMPT_SCHEMA_ID = "okf-deployed-entrypoint-attempt.v1"
INTEGRITY_SCHEMA_ID = "okf-deployed-entrypoint-integrity.v1"
TOOL_VERSION = "1.0.0"
RELEASE_ASSET_NAME = "okf-uk-legislation-v0.3.0.tar.zst"

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
PLACEHOLDER = re.compile(r"__[A-Z0-9_]+__")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SAFE_HEADERS = {
    "accept-ranges",
    "access-control-allow-origin",
    "cache-control",
    "content-encoding",
    "content-language",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
    "location",
    "x-content-type-options",
}
FORBIDDEN_REQUEST_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
}
REQUIRED_COVERAGE = {
    "pages-descriptor",
    "pages-documentation",
    "raw-declared-subpath",
    "github-archive-fallback",
    "github-release-fallback",
    "explorer-loading",
    "compatibility-documentation",
    "compatibility-moved-descriptor",
    "ckan-documentation",
    "ckan-example",
    "yaml-ld",
    "json-ld-fallback",
}
REQUEST_HEADERS = {
    "Accept": (
        "application/ld+json, application/json, application/ld+yaml, "
        "application/yaml, text/yaml, text/html, text/markdown, "
        "application/octet-stream;q=0.8, */*;q=0.1"
    ),
    "Accept-Encoding": "identity",
    "Connection": "close",
    "User-Agent": (
        "okf-uk-legislation-gate09-probe/1.0 "
        "(unauthenticated bounded release-candidate assurance)"
    ),
}


class ProbeError(RuntimeError):
    """A fail-closed manifest, transport or validation failure."""


class UnsafeRouteError(ProbeError):
    """A URL, redirect or DNS answer violates the SSRF policy."""


class Transport(Protocol):
    def request_once(
        self,
        url: str,
        addresses: list[dict[str, Any]],
        headers: dict[str, str],
        timeout_seconds: float,
        maximum_body_bytes: int,
    ) -> dict[str, Any]:
        """Return one response without following redirects."""


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def validate_executed_at(value: str) -> None:
    if not isinstance(value, str) or len(value) > 40:
        raise ProbeError("executed_at must be a bounded RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProbeError("executed_at is not valid RFC 3339") from error
    if parsed.tzinfo is None:
        raise ProbeError("executed_at must include a timezone")


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def media_type(headers: list[dict[str, str]]) -> str | None:
    values = [
        row["value"].split(";", 1)[0].strip().lower()
        for row in headers
        if row["name"].lower() == "content-type"
    ]
    return values[-1] if values else None


def header_values(
    headers: list[dict[str, str]],
    name: str,
) -> list[str]:
    target = name.lower()
    return [
        row["value"]
        for row in headers
        if row["name"].lower() == target
    ]


def url_without_query(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )


def canonical_https_url(url: str, allowed_hosts: set[str]) -> str:
    if not isinstance(url, str) or not url:
        raise UnsafeRouteError("route URL must be a non-empty string")
    if any(ord(character) < 32 for character in url):
        raise UnsafeRouteError("route URL contains a control character")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or host not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise UnsafeRouteError(
            "refusing non-allowlisted HTTPS URL "
            f"(host={host or 'missing'}, scheme={parsed.scheme or 'missing'})"
        )
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeRouteError("IP-literal URLs are forbidden")
    decoded_path = unquote(parsed.path)
    if "\\" in decoded_path or any(
        segment in {".", ".."} for segment in decoded_path.split("/")
    ):
        raise UnsafeRouteError("ambiguous or traversing URL path is forbidden")
    canonical = urlunsplit(
        ("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )
    if canonical != url:
        raise UnsafeRouteError(
            f"route URL is not in canonical literal form: {url}"
        )
    return canonical


def _public_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(value.split("%", 1)[0])
    if not address.is_global:
        raise UnsafeRouteError(f"non-global DNS answer rejected: {address}")
    return address


def _resolver_worker(
    connection: Any,
    host: str,
    port: int,
    kwargs: dict[str, Any],
) -> None:
    try:
        connection.send(
            {
                "result": socket.getaddrinfo(host, port, **kwargs),
                "status": "ok",
            }
        )
    except BaseException as error:  # child must always return a bounded receipt
        connection.send(
            {
                "error": f"{type(error).__name__}: {error}",
                "status": "error",
            }
        )
    finally:
        connection.close()


def bounded_system_resolver(
    host: str,
    port: int,
    *,
    _timeout_seconds: float,
    **kwargs: Any,
) -> list[Any]:
    """Resolve in a disposable process so DNS has a hard wall-clock bound."""

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_resolver_worker,
        args=(sender, host, port, kwargs),
        daemon=True,
    )
    process.start()
    sender.close()
    try:
        if not receiver.poll(_timeout_seconds):
            process.terminate()
            process.join(timeout=1)
            raise ProbeError(f"DNS resolution timed out for {host}")
        try:
            message = receiver.recv()
        except EOFError as error:
            raise ProbeError(
                f"DNS resolver exited without a receipt for {host}"
            ) from error
    finally:
        receiver.close()
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
    if message.get("status") != "ok":
        raise ProbeError(
            f"DNS resolution failed for {host}: {message.get('error')}"
        )
    return message["result"]


def resolve_public_addresses(
    host: str,
    port: int = 443,
    *,
    resolver: Callable[..., list[Any]] = bounded_system_resolver,
    timeout_seconds: float = 5,
) -> list[dict[str, Any]]:
    try:
        answers = resolver(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
            _timeout_seconds=timeout_seconds,
        )
    except OSError as error:
        raise ProbeError(f"DNS resolution failed for {host}: {error}") from error
    resolved: dict[tuple[int, str], dict[str, Any]] = {}
    for family, _socktype, _proto, _canonname, sockaddr in answers:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        address = str(_public_address(str(sockaddr[0])))
        resolved[(family, address)] = {
            "address": address,
            "family": "IPv4" if family == socket.AF_INET else "IPv6",
        }
    if not resolved:
        raise ProbeError(f"DNS resolution returned no usable address for {host}")
    if len(resolved) > 16:
        raise UnsafeRouteError(
            f"DNS answer set exceeds hard limit 16 for {host}"
        )
    return [
        resolved[key]
        for key in sorted(
            resolved,
            key=lambda item: (0 if item[0] == socket.AF_INET else 1, item[1]),
        )
    ]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection whose TCP destination is an already-reviewed address."""

    def __init__(
        self,
        host: str,
        *,
        pinned_address: str,
        port: int,
        timeout: float,
    ) -> None:
        super().__init__(
            host,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._pinned_address = pinned_address

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw,
                server_hostname=self.host,
            )
        except Exception:
            raw.close()
            raise


class PinnedHTTPSNetworkTransport:
    """Direct HTTPS transport with no proxy, cookie jar or redirect support."""

    def request_once(
        self,
        url: str,
        addresses: list[dict[str, Any]],
        headers: dict[str, str],
        timeout_seconds: float,
        maximum_body_bytes: int,
    ) -> dict[str, Any]:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_https_worker,
            args=(
                sender,
                url,
                addresses,
                headers,
                timeout_seconds,
                maximum_body_bytes,
            ),
            daemon=True,
        )
        process.start()
        sender.close()
        try:
            if not receiver.poll(timeout_seconds):
                process.terminate()
                process.join(timeout=1)
                raise ProbeError(
                    f"HTTPS request timed out for {url_without_query(url)}"
                )
            try:
                message = receiver.recv()
            except EOFError as error:
                raise ProbeError(
                    "HTTPS worker exited without a receipt for "
                    f"{url_without_query(url)}"
                ) from error
        finally:
            receiver.close()
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        if message.get("status") != "ok":
            raise ProbeError(
                "HTTPS request failed for "
                f"{url_without_query(url)}: {message.get('error')}"
            )
        return message["result"]


def _pinned_https_request(
    url: str,
    addresses: list[dict[str, Any]],
    headers: dict[str, str],
    timeout_seconds: float,
    maximum_body_bytes: int,
) -> dict[str, Any]:
    if any(name.lower() in FORBIDDEN_REQUEST_HEADERS for name in headers):
        raise UnsafeRouteError("credential-bearing request header rejected")
    parsed = urlsplit(url)
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    failures: list[str] = []
    deadline = time.monotonic() + timeout_seconds
    for resolved in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        connection = _PinnedHTTPSConnection(
            parsed.hostname or "",
            pinned_address=resolved["address"],
            port=parsed.port or 443,
            timeout=remaining,
        )
        started = time.monotonic()
        try:
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
            body = response.read(maximum_body_bytes + 1)
            truncated = len(body) > maximum_body_bytes
            body = body[:maximum_body_bytes]
            return {
                "body": body,
                "elapsed_ms": round(
                    (time.monotonic() - started) * 1000,
                    3,
                ),
                "headers": [
                    {"name": name, "value": value}
                    for name, value in response.getheaders()
                ],
                "peer_ip": resolved["address"],
                "reason": str(response.reason),
                "status": int(response.status),
                "truncated": truncated,
            }
        except (OSError, ssl.SSLError, http.client.HTTPException) as error:
            failures.append(
                f"{resolved['address']}: {type(error).__name__}: {error}"
            )
        finally:
            connection.close()
    raise ProbeError(
        f"all pinned addresses failed for {parsed.hostname}: "
        + " | ".join(failures)
    )


def _https_worker(
    connection: Any,
    url: str,
    addresses: list[dict[str, Any]],
    headers: dict[str, str],
    timeout_seconds: float,
    maximum_body_bytes: int,
) -> None:
    try:
        connection.send(
            {
                "result": _pinned_https_request(
                    url,
                    addresses,
                    headers,
                    timeout_seconds,
                    maximum_body_bytes,
                ),
                "status": "ok",
            }
        )
    except BaseException as error:  # child must always return a bounded receipt
        connection.send(
            {
                "error": f"{type(error).__name__}: {error}",
                "status": "error",
            }
        )
    finally:
        connection.close()


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_errors(document: Any, schema_path: Path) -> list[str]:
    if Draft202012Validator is None:
        return ["jsonschema is unavailable in the release environment"]
    validator = Draft202012Validator(load_schema(schema_path))
    return [
        (
            "/".join(str(part) for part in error.absolute_path)
            + (": " if error.absolute_path else "")
            + error.message
        )
        for error in sorted(
            validator.iter_errors(document),
            key=lambda item: [str(part) for part in item.absolute_path],
        )
    ]


def validate_manifest(
    manifest: dict[str, Any],
    *,
    require_locked: bool,
) -> list[str]:
    errors = schema_errors(manifest, MANIFEST_SCHEMA)
    if errors:
        return errors
    policy = manifest["policy"]
    hosts = set(manifest["allowed_hosts"])
    routes = manifest["routes"]
    if set(REQUEST_HEADERS) != set(policy["request_headers"]):
        errors.append("manifest request_headers differ from fixed tool headers")
    elif policy["request_headers"] != REQUEST_HEADERS:
        errors.append("manifest request header values differ from fixed values")
    if any(
        name.lower() in FORBIDDEN_REQUEST_HEADERS
        for name in policy["request_headers"]
    ):
        errors.append("manifest contains credential-bearing request headers")
    if policy["authentication"] != "none" or policy["cookies"] != "never":
        errors.append("manifest does not prohibit authentication and cookies")
    if policy["maximum_redirects"] > 5:
        errors.append("maximum_redirects exceeds hard tool limit 5")
    if policy["maximum_body_bytes"] > 2_097_152:
        errors.append("maximum_body_bytes exceeds hard tool limit 2 MiB")
    if policy["dns_timeout_seconds"] > 5:
        errors.append("dns_timeout_seconds exceeds hard tool limit 5")
    if policy["timeout_seconds"] > 30:
        errors.append("timeout_seconds exceeds hard tool limit 30")
    route_ids = [row["id"] for row in routes]
    if len(route_ids) != len(set(route_ids)):
        errors.append("route ids are not unique")
    if len(routes) > 64:
        errors.append("route count exceeds hard tool limit 64")
    represented = {
        coverage
        for route in routes
        for coverage in route["coverage"]
    }
    missing_coverage = sorted(REQUIRED_COVERAGE - represented)
    if missing_coverage:
        errors.append(
            "manifest does not cover required route classes: "
            + ", ".join(missing_coverage)
        )
    for host in hosts:
        try:
            canonical_https_url(f"https://{host}/", hosts)
        except UnsafeRouteError as error:
            errors.append(f"unsafe allowed host {host}: {error}")
    by_id = {row["id"]: row for row in routes}
    for route in routes:
        route_hosts = set(route["allowed_redirect_hosts"])
        if not route_hosts <= hosts:
            errors.append(
                f"{route['id']}: redirect hosts escape top-level allowlist"
            )
        try:
            canonical_https_url(route["url"], route_hosts)
        except UnsafeRouteError as error:
            errors.append(f"{route['id']}: {error}")
        if route.get("maximum_body_bytes", 0) > policy["maximum_body_bytes"]:
            errors.append(f"{route['id']}: body limit exceeds policy")
    for assertion in manifest["cross_route_assertions"]:
        referenced = [
            assertion.get(name)
            for name in (
                "left_route",
                "right_route",
                "yaml_route",
                "json_route",
                "explorer_route",
                "bundle_route",
            )
            if assertion.get(name)
        ]
        unknown = sorted(set(referenced) - set(by_id))
        if unknown:
            errors.append(
                f"{assertion['id']}: unknown route ids {', '.join(unknown)}"
            )
    if require_locked:
        candidate = manifest["candidate"]
        if manifest["state"] != "locked":
            errors.append("manifest state is not locked")
        if not COMMIT.fullmatch(candidate["git_commit"]):
            errors.append("candidate git_commit is not an exact 40-hex commit")
        if not DIGEST.fullmatch(candidate["bundle_tree_sha256"]):
            errors.append("candidate bundle_tree_sha256 is not a SHA-256")
        serialized = render(manifest)
        if PLACEHOLDER.search(serialized):
            errors.append("locked manifest still contains placeholders")
        raw_routes = [
            row for row in routes if "raw-declared-subpath" in row["coverage"]
        ]
        for route in raw_routes:
            if candidate["git_commit"] not in route["url"]:
                errors.append(
                    f"{route['id']}: raw URL is not pinned to candidate commit"
                )
        archive_routes = [
            row for row in routes if "github-archive-fallback" in row["coverage"]
        ]
        for route in archive_routes:
            if candidate["git_commit"] not in route["url"]:
                errors.append(
                    f"{route['id']}: archive URL is not pinned to candidate commit"
                )
        release_routes = [
            row for row in routes if "github-release-fallback" in row["coverage"]
        ]
        for route in release_routes:
            if candidate["release_tag"] not in route["url"]:
                errors.append(
                    f"{route['id']}: release URL is not pinned to release tag"
                )
        release_asset = by_id.get("github-candidate-release-asset")
        if (
            release_asset is None
            or not release_asset["url"].endswith("/" + RELEASE_ASSET_NAME)
        ):
            errors.append(
                "release asset route does not use the frozen production filename "
                + RELEASE_ASSET_NAME
            )
    return sorted(set(errors))


def json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must be empty or start with /")
    current = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def _decode_text(body: bytes) -> str:
    text = body.decode("utf-8")
    if "\x00" in text:
        raise ValueError("NUL byte in text document")
    return text


def evaluate_document(
    route: dict[str, Any],
    body: bytes,
    response_headers: list[dict[str, str]],
    *,
    truncated: bool,
) -> tuple[list[str], dict[str, Any]]:
    expected = route["expected"]
    errors: list[str] = []
    observed_type = media_type(response_headers)
    allowed_types = set(expected["media_types"])
    mime_exception = (
        expected["document_kind"] == "yaml-ld"
        and observed_type == "application/octet-stream"
        and expected.get("allow_declared_yaml_ld_mime_exception") is True
    )
    if observed_type not in allowed_types and not mime_exception:
        errors.append(
            f"unexpected media type {observed_type!r}; "
            f"expected one of {sorted(allowed_types)}"
        )
    if truncated and not expected.get("allow_truncated", False):
        errors.append("response exceeded the route body limit")

    parsed_json: Any = None
    kind = expected["document_kind"]
    try:
        if kind in {"json", "json-ld", "moved-descriptor"}:
            parsed_json = json.loads(_decode_text(body))
            if kind == "json-ld" and not (
                isinstance(parsed_json, dict) and "@context" in parsed_json
            ):
                errors.append("JSON-LD fallback has no top-level @context")
        elif kind == "yaml-ld":
            text = _decode_text(body)
            prefix = text[:16_384].lstrip()
            if prefix.startswith("{"):
                parsed_json = json.loads(text)
                if not (
                    isinstance(parsed_json, dict) and "@context" in parsed_json
                ):
                    errors.append("JSON-compatible YAML-LD has no @context")
            elif not re.search(
                r'(?m)^[ \t]*(?:"@context"|\'@context\'|@context)[ \t]*:',
                prefix,
            ):
                errors.append("YAML-LD content sniff found no top-level @context")
            if "<html" in prefix[:1024].lower():
                errors.append("YAML-LD route returned HTML")
        elif kind == "html":
            text = _decode_text(body)
            lowered = text[:16_384].lower()
            if "<html" not in lowered and "<!doctype html" not in lowered:
                errors.append("HTML route does not contain an HTML document")
        elif kind in {"text", "markdown"}:
            _decode_text(body)
        elif kind == "gzip-archive":
            if not body.startswith(b"\x1f\x8b"):
                errors.append("archive does not start with gzip magic")
        elif kind == "zstd-archive":
            if not body.startswith(b"\x28\xb5\x2f\xfd"):
                errors.append("archive does not start with zstd magic")
        else:
            errors.append(f"unsupported document kind: {kind}")
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        errors.append(f"{kind} parse failed: {error}")

    if expected.get("required_text"):
        try:
            text = _decode_text(body)
        except (UnicodeDecodeError, ValueError):
            text = ""
        for value in expected["required_text"]:
            if value not in text:
                errors.append(f"required text is absent: {value!r}")
    if expected.get("json_fields"):
        if parsed_json is None:
            errors.append("JSON field assertions require a parsed JSON document")
        else:
            for pointer, value in sorted(expected["json_fields"].items()):
                try:
                    observed = json_pointer(parsed_json, pointer)
                except (KeyError, IndexError, TypeError, ValueError):
                    errors.append(f"JSON pointer is absent: {pointer}")
                    continue
                if observed != value:
                    errors.append(
                        f"JSON pointer {pointer} differs from expected value"
                    )
    return (
        sorted(set(errors)),
        {
            "content_sniff": "passed" if not errors else "failed",
            "declared_yaml_ld_mime_exception_observed": mime_exception,
            "media_type": observed_type,
            "transport_conformant_yaml_ld": (
                kind != "yaml-ld" or observed_type == "application/ld+yaml"
            ),
        },
    )


def safe_headers(
    headers: list[dict[str, str]],
    *,
    response_url: str,
) -> tuple[list[dict[str, str]], list[str]]:
    selected = []
    for row in headers:
        name = row["name"].lower()
        if name not in SAFE_HEADERS:
            continue
        value = row["value"]
        if name == "location":
            value = url_without_query(urljoin(response_url, value))
        selected.append({"name": row["name"], "value": value})
    omitted = sorted(
        {
            row["name"].lower()
            for row in headers
            if row["name"].lower() not in SAFE_HEADERS
        }
    )
    return selected, omitted


def probe_route(
    route: dict[str, Any],
    policy: dict[str, Any],
    *,
    transport: Transport,
    resolver: Callable[..., list[Any]],
) -> tuple[dict[str, Any], dict[str, bytes], bytes]:
    route_started = time.monotonic()
    allowed_hosts = set(route["allowed_redirect_hosts"])
    current_url = canonical_https_url(route["url"], allowed_hosts)
    maximum_redirects = min(
        policy["maximum_redirects"],
        route.get("maximum_redirects", policy["maximum_redirects"]),
    )
    maximum_body_bytes = min(
        policy["maximum_body_bytes"],
        route.get("maximum_body_bytes", policy["maximum_body_bytes"]),
    )
    deadline = time.monotonic() + policy["timeout_seconds"]
    raw_files: dict[str, bytes] = {}
    hops: list[dict[str, Any]] = []
    final_body = b""
    route_errors: list[str] = []
    for hop_number in range(maximum_redirects + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeError(f"{route['id']}: total route timeout exceeded")
        parsed = urlsplit(current_url)
        addresses = resolve_public_addresses(
            parsed.hostname or "",
            parsed.port or 443,
            resolver=resolver,
            timeout_seconds=min(
                remaining,
                policy["dns_timeout_seconds"],
            ),
        )
        response = transport.request_once(
            current_url,
            addresses,
            REQUEST_HEADERS.copy(),
            min(remaining, policy["per_request_timeout_seconds"]),
            maximum_body_bytes,
        )
        body = bytes(response["body"])
        truncated = bool(response.get("truncated")) or (
            len(body) > maximum_body_bytes
        )
        body = body[:maximum_body_bytes]
        headers = [
            {"name": str(row["name"]), "value": str(row["value"])}
            for row in response["headers"]
        ]
        body_path = f"raw/{route['id']}/hop-{hop_number:02d}.body"
        raw_files[body_path] = body
        hop = {
            "body_bytes": len(body),
            "body_path": body_path,
            "body_sha256": sha256_bytes(body),
            "elapsed_ms": response["elapsed_ms"],
            "headers": headers,
            "peer_ip": response["peer_ip"],
            "request_headers": REQUEST_HEADERS,
            "resolved_addresses": addresses,
            "response_reason": response.get("reason", ""),
            "status": int(response["status"]),
            "truncated": truncated,
            "url": current_url,
        }
        hops.append(hop)
        status = hop["status"]
        if status not in REDIRECT_STATUSES:
            final_body = body
            break
        locations = header_values(headers, "location")
        if len(locations) != 1:
            route_errors.append("redirect response has no unique Location header")
            final_body = body
            break
        if hop_number >= maximum_redirects:
            route_errors.append("redirect limit exceeded")
            final_body = body
            break
        redirected = urljoin(current_url, locations[0])
        try:
            current_url = canonical_https_url(redirected, allowed_hosts)
        except UnsafeRouteError as error:
            route_errors.append(str(error))
            final_body = body
            break
    final_hop = hops[-1]
    if final_hop["status"] not in set(route["expected"]["statuses"]):
        route_errors.append(
            f"unexpected final status {final_hop['status']}; "
            f"expected {route['expected']['statuses']}"
        )
    document_errors, document_receipt = evaluate_document(
        route,
        final_body,
        final_hop["headers"],
        truncated=final_hop["truncated"],
    )
    route_errors.extend(document_errors)
    selected_headers, omitted_headers = safe_headers(
        final_hop["headers"],
        response_url=final_hop["url"],
    )
    final_url_query_redacted = bool(urlsplit(final_hop["url"]).query)
    projected_final_url = (
        url_without_query(final_hop["url"])
        if final_url_query_redacted
        else final_hop["url"]
    )
    raw_route = {
        "errors": sorted(set(route_errors)),
        "final_url": final_hop["url"],
        "hops": hops,
        "route_id": route["id"],
        "schema": "okf-deployed-entrypoint-raw-route.v1",
        "status": "passed" if not route_errors else "failed",
        "total_elapsed_ms": round(
            (time.monotonic() - route_started) * 1000,
            3,
        ),
        "untrusted_response_evidence": True,
    }
    raw_files[f"raw/{route['id']}/route.json"] = render(raw_route).encode()
    projection = {
        "body_bytes": final_hop["body_bytes"],
        "body_hash_scope": (
            "bounded-prefix" if final_hop["truncated"] else "complete-response"
        ),
        "body_sha256": final_hop["body_sha256"],
        "coverage": route["coverage"],
        "declared_yaml_ld_mime_exception_observed": document_receipt[
            "declared_yaml_ld_mime_exception_observed"
        ],
        "elapsed_ms": raw_route["total_elapsed_ms"],
        "errors": sorted(set(route_errors)),
        "final_url": projected_final_url,
        "final_url_query_redacted": final_url_query_redacted,
        "final_url_sha256": sha256_bytes(final_hop["url"].encode()),
        "headers": selected_headers,
        "hops": len(hops),
        "id": route["id"],
        "media_type": document_receipt["media_type"],
        "omitted_response_header_names": omitted_headers,
        "status": "passed" if not route_errors else "failed",
        "status_code": final_hop["status"],
        "transport_conformant_yaml_ld": document_receipt[
            "transport_conformant_yaml_ld"
        ],
        "truncated": final_hop["truncated"],
        "url": route["url"],
    }
    return projection, raw_files, final_body


def evaluate_cross_route_assertions(
    assertions: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    bodies: dict[str, bytes],
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for assertion in assertions:
        failures: list[str] = []
        kind = assertion["kind"]
        if kind == "body-digest-equal":
            left = assertion["left_route"]
            right = assertion["right_route"]
            if sha256_bytes(bodies[left]) != sha256_bytes(bodies[right]):
                failures.append("body digests differ")
        elif kind == "yaml-json-fallback":
            yaml_route = routes[assertion["yaml_route"]]
            json_route = routes[assertion["json_route"]]
            if yaml_route["status"] != "passed":
                failures.append("YAML-LD route failed")
            if json_route["status"] != "passed":
                failures.append("JSON-LD fallback route failed")
            if (
                yaml_route["declared_yaml_ld_mime_exception_observed"]
                and json_route["media_type"]
                not in {"application/json", "application/ld+json"}
            ):
                failures.append(
                    "YAML-LD MIME exception lacks strict JSON-LD transport fallback"
                )
        elif kind == "explorer-bundle-query":
            explorer = routes[assertion["explorer_route"]]
            bundle = routes[assertion["bundle_route"]]
            query = parse_qs(urlsplit(explorer["url"]).query)
            if query.get("bundle") != [bundle["url"]]:
                failures.append("Explorer bundle query does not equal descriptor URL")
            if explorer["status"] != "passed" or bundle["status"] != "passed":
                failures.append("Explorer shell or bundle descriptor failed")
        else:
            failures.append(f"unsupported cross-route assertion kind: {kind}")
        receipts.append(
            {
                "errors": failures,
                "id": assertion["id"],
                "kind": kind,
                "status": "passed" if not failures else "failed",
            }
        )
    return receipts


def run_probe(
    manifest: dict[str, Any],
    *,
    transport: Transport,
    resolver: Callable[..., list[Any]],
    executed_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    validate_executed_at(executed_at)
    errors = validate_manifest(manifest, require_locked=True)
    if errors:
        raise ProbeError("manifest is not runnable:\n- " + "\n- ".join(errors))
    route_results: list[dict[str, Any]] = []
    raw_files: dict[str, bytes] = {}
    bodies: dict[str, bytes] = {}
    for route in manifest["routes"]:
        try:
            result, files, body = probe_route(
                route,
                manifest["policy"],
                transport=transport,
                resolver=resolver,
            )
        except (ProbeError, OSError, ValueError) as error:
            result = {
                "body_bytes": 0,
                "body_hash_scope": "none",
                "body_sha256": None,
                "coverage": route["coverage"],
                "declared_yaml_ld_mime_exception_observed": False,
                "elapsed_ms": None,
                "errors": [f"{type(error).__name__}: {error}"],
                "final_url": None,
                "final_url_query_redacted": False,
                "final_url_sha256": None,
                "headers": [],
                "hops": 0,
                "id": route["id"],
                "media_type": None,
                "omitted_response_header_names": [],
                "status": "failed",
                "status_code": None,
                "transport_conformant_yaml_ld": False,
                "truncated": False,
                "url": route["url"],
            }
            files = {
                f"raw/{route['id']}/route.json": render(
                    {
                        "errors": result["errors"],
                        "route_id": route["id"],
                        "schema": "okf-deployed-entrypoint-raw-route.v1",
                        "status": "failed",
                        "untrusted_response_evidence": True,
                    }
                ).encode()
            }
            body = b""
        route_results.append(result)
        raw_files.update(files)
        bodies[route["id"]] = body
    by_id = {row["id"]: row for row in route_results}
    cross = evaluate_cross_route_assertions(
        manifest["cross_route_assertions"],
        by_id,
        bodies,
    )
    failed_routes = [row["id"] for row in route_results if row["status"] != "passed"]
    failed_cross = [row["id"] for row in cross if row["status"] != "passed"]
    projection = {
        "assurance_boundary": (
            "Unauthenticated bounded HTTPS evidence for the exact candidate. "
            "This receipt does not replace browser GATE-07 evidence or promote "
            "the candidate."
        ),
        "candidate": manifest["candidate"],
        "cross_route_assertions": cross,
        "executed_at": executed_at,
        "gate": "GATE-09",
        "gate_evidence_status": (
            "passed" if not failed_routes and not failed_cross else "failed"
        ),
        "manifest_sha256": sha256_bytes(render(manifest).encode()),
        "policy": {
            "authentication": "none",
            "cookies": "never",
            "maximum_body_bytes": manifest["policy"]["maximum_body_bytes"],
            "maximum_redirects": manifest["policy"]["maximum_redirects"],
            "dns_timeout_seconds": manifest["policy"]["dns_timeout_seconds"],
            "request_header_names": sorted(REQUEST_HEADERS),
            "ssrf_controls": [
                "literal HTTPS route manifest",
                "per-route redirect host allowlist",
                "global-public DNS answers only",
                "DNS-selected address pinned to TLS connection",
                "no proxy, credentials or cookies",
            ],
            "timeout_seconds": manifest["policy"]["timeout_seconds"],
        },
        "routes": route_results,
        "schema": PROJECTION_SCHEMA_ID,
        "summary": {
            "cross_assertions_failed": len(failed_cross),
            "cross_assertions_passed": len(cross) - len(failed_cross),
            "cross_assertions_total": len(cross),
            "failed_cross_assertion_ids": failed_cross,
            "failed_route_ids": failed_routes,
            "routes_failed": len(failed_routes),
            "routes_passed": len(route_results) - len(failed_routes),
            "routes_total": len(route_results),
        },
    }
    projection_errors = schema_errors(projection, PROJECTION_SCHEMA)
    if projection_errors:
        raise ProbeError(
            "generated projection does not validate:\n- "
            + "\n- ".join(projection_errors)
        )
    attempt = {
        "candidate": manifest["candidate"],
        "executed_at": executed_at,
        "gate": "GATE-09",
        "manifest_sha256": projection["manifest_sha256"],
        "network_policy": "unauthenticated-bounded-pinned-https",
        "projection_sha256": sha256_bytes(render(projection).encode()),
        "raw_evidence": {
            "contains_untrusted_response_bytes": True,
            "publication_status": "not-safe-for-direct-publication",
            "safe_projection": "projection.json",
        },
        "schema": ATTEMPT_SCHEMA_ID,
        "status": projection["gate_evidence_status"],
        "tool": {
            "name": Path(__file__).name,
            "sha256": sha256_bytes(Path(__file__).read_bytes()),
            "version": TOOL_VERSION,
        },
    }
    attempt_errors = schema_errors(attempt, ATTEMPT_SCHEMA)
    if attempt_errors:
        raise ProbeError(
            "generated attempt does not validate:\n- "
            + "\n- ".join(attempt_errors)
        )
    return attempt, projection, raw_files


def attempt_id(
    manifest: dict[str, Any],
    executed_at: str,
) -> str:
    timestamp = re.sub(r"[^0-9A-Za-z]", "", executed_at)
    return (
        f"gate09-{timestamp}-"
        f"{manifest['candidate']['git_commit'][:12]}-"
        f"{sha256_bytes(render(manifest).encode())[:12]}"
    )


def write_attempt(
    output_root: Path,
    manifest_body: bytes,
    manifest: dict[str, Any],
    attempt: dict[str, Any],
    projection: dict[str, Any],
    raw_files: dict[str, bytes],
) -> Path:
    identifier = attempt_id(manifest, attempt["executed_at"])
    destination = output_root / identifier
    if destination.exists():
        raise ProbeError(f"refusing to alter immutable attempt: {destination}")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{identifier}-", dir=output_root)
    )
    try:
        files = {
            "attempt.json": render(attempt).encode(),
            "projection.json": render(projection).encode(),
            "route-manifest.json": manifest_body,
            **raw_files,
        }
        for relative, body in sorted(files.items()):
            path = temporary / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            if relative.startswith("raw/"):
                os.chmod(path, 0o600)
        integrity = {
            "attempt_id": identifier,
            "files": [
                {
                    "bytes": len(body),
                    "path": relative,
                    "sha256": sha256_bytes(body),
                }
                for relative, body in sorted(files.items())
            ],
            "schema": INTEGRITY_SCHEMA_ID,
        }
        (temporary / "integrity.json").write_text(
            render(integrity),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def verify_attempt(path: Path) -> list[str]:
    errors: list[str] = []
    for name in (
        "attempt.json",
        "projection.json",
        "route-manifest.json",
        "integrity.json",
    ):
        if not (path / name).is_file():
            errors.append(f"missing {name}")
    if errors:
        return errors
    try:
        attempt = json.loads((path / "attempt.json").read_text())
        projection = json.loads((path / "projection.json").read_text())
        manifest = json.loads((path / "route-manifest.json").read_text())
        integrity = json.loads((path / "integrity.json").read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"invalid JSON: {error}"]
    errors.extend(
        f"attempt schema: {value}"
        for value in schema_errors(attempt, ATTEMPT_SCHEMA)
    )
    errors.extend(
        f"projection schema: {value}"
        for value in schema_errors(projection, PROJECTION_SCHEMA)
    )
    errors.extend(
        f"manifest: {value}"
        for value in validate_manifest(manifest, require_locked=True)
    )
    declared = {
        row["path"]: row
        for row in integrity.get("files", [])
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    for relative, receipt in sorted(declared.items()):
        candidate = (path / relative).resolve()
        if not candidate.is_relative_to(path.resolve()):
            errors.append(f"integrity path escapes attempt: {relative}")
            continue
        if not candidate.is_file():
            errors.append(f"integrity path missing: {relative}")
            continue
        body = candidate.read_bytes()
        if len(body) != receipt.get("bytes"):
            errors.append(f"byte count differs: {relative}")
        if sha256_bytes(body) != receipt.get("sha256"):
            errors.append(f"digest differs: {relative}")
    actual = {
        file.relative_to(path).as_posix()
        for file in path.rglob("*")
        if file.is_file() and file.name != "integrity.json"
    }
    if actual != set(declared):
        errors.append("integrity file set differs from attempt contents")
    if attempt.get("projection_sha256") != sha256_bytes(
        (path / "projection.json").read_bytes()
    ):
        errors.append("attempt projection digest differs")
    if attempt.get("manifest_sha256") != sha256_bytes(render(manifest).encode()):
        errors.append("attempt manifest semantic digest differs")
    return sorted(set(errors))


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser(
        "validate-manifest",
        help="validate structure and report whether the manifest is RC-locked",
    )
    validate_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)

    run_parser = subparsers.add_parser(
        "run",
        help="perform the explicit network attempt for an already deployed RC",
    )
    run_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    run_parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    run_parser.add_argument("--executed-at")
    run_parser.add_argument(
        "--allow-network",
        action="store_true",
        help="required acknowledgement; no request is made without it",
    )

    verify_parser = subparsers.add_parser(
        "verify-attempt",
        help="verify an existing immutable attempt without network access",
    )
    verify_parser.add_argument("attempt", type=Path)
    args = parser.parse_args()

    if args.command == "verify-attempt":
        failures = verify_attempt(args.attempt.resolve())
        if failures:
            print("Deployed-entrypoint attempt verification failed:")
            for failure in failures:
                print(f"- {failure}")
            return 1
        print(f"Deployed-entrypoint attempt verified: {args.attempt}")
        return 0

    manifest_path = args.manifest.resolve()
    manifest_body = manifest_path.read_bytes()
    manifest = json.loads(manifest_body)
    failures = validate_manifest(
        manifest,
        require_locked=args.command == "run",
    )
    if failures:
        print("Deployed-entrypoint manifest validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    if args.command == "validate-manifest":
        state = manifest["state"]
        print(
            f"Deployed-entrypoint manifest structurally valid: "
            f"{len(manifest['routes'])} routes; state={state}; "
            f"network_not_used=true"
        )
        return 0

    if not args.allow_network:
        parser.error("run requires --allow-network")
    attempt, projection, raw_files = run_probe(
        manifest,
        transport=PinnedHTTPSNetworkTransport(),
        resolver=bounded_system_resolver,
        executed_at=args.executed_at or utc_now(),
    )
    destination = write_attempt(
        args.output_root.resolve(),
        manifest_body,
        manifest,
        attempt,
        projection,
        raw_files,
    )
    print(
        f"Deployed-entrypoint attempt written: {destination}; "
        f"evidence_status={projection['gate_evidence_status']}"
    )
    return 0 if projection["gate_evidence_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
