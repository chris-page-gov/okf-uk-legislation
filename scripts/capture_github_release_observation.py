#!/usr/bin/env python3
"""Capture one immutable GitHub release observation in external evidence.

Only the three release/tag pairs fixed by the external-finalization contract
are accepted.  The tool performs one bounded request per required GitHub
endpoint, follows redirects manually through a fixed HTTPS host allowlist, and
does not retry failed requests.  ``GITHUB_TOKEN`` is optional, is sent only to
``api.github.com``, and is never written to the evidence directory.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "release-assurance"
    / "schemas"
    / "github-release-observation.schema.json"
)
OBSERVATION_SCHEMA = "okf-github-release-observation.v1"
ATTEMPT_SCHEMA = "okf-github-release-observation-attempt.v1"
TOOL_VERSION = "1.0.0"

API_HOST = "api.github.com"
ASSET_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
}
MAXIMUM_REDIRECTS = 3
REQUEST_TIMEOUT_SECONDS = 30.0
MAXIMUM_API_BODY_BYTES = 4 * 1024 * 1024
MAXIMUM_ASSET_BODY_BYTES = 512 * 1024 * 1024
MAXIMUM_HEADER_BYTES = 256 * 1024
MAXIMUM_URL_BYTES = 8192
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

RELEASE_HEADERS_PATH = "raw/release-response.headers.json"
RELEASE_BODY_PATH = "raw/release-response.body.json"
TAG_HEADERS_PATH = "raw/tag-resolution-response.headers.json"
TAG_REF_BODY_PATH = "raw/tag-ref-response.body.json"
TAG_OBJECT_BODY_PATH = "raw/annotated-tag-response.body.json"
ASSET_HEADERS_PATH = "raw/asset-response.headers.json"
ASSET_BODY_PATH = "raw/asset-response.body"
ATTEMPT_MANIFEST_PATH = "attempt-manifest.json"


@dataclass(frozen=True)
class Target:
    repository: str
    slug: str
    tag: str
    observation_filename: str


TARGETS = {
    (
        "https://github.com/chris-page-gov/okf-explorer",
        "v0.5.0",
    ): Target(
        repository="https://github.com/chris-page-gov/okf-explorer",
        slug="chris-page-gov/okf-explorer",
        tag="v0.5.0",
        observation_filename="explorer-release-observation.json",
    ),
    (
        "https://github.com/chris-page-gov/okf-uk-legislation",
        "v0.3.0-rc.1",
    ): Target(
        repository="https://github.com/chris-page-gov/okf-uk-legislation",
        slug="chris-page-gov/okf-uk-legislation",
        tag="v0.3.0-rc.1",
        observation_filename=(
            "okf-uk-legislation-v0.3.0-rc.1-release-observation.json"
        ),
    ),
    (
        "https://github.com/chris-page-gov/okf-uk-legislation",
        "v0.3.0",
    ): Target(
        repository="https://github.com/chris-page-gov/okf-uk-legislation",
        slug="chris-page-gov/okf-uk-legislation",
        tag="v0.3.0",
        observation_filename=(
            "okf-uk-legislation-v0.3.0-release-observation.json"
        ),
    ),
}


class CaptureError(RuntimeError):
    """The requested observation is unsafe, incomplete, or inconsistent."""


class UnsafeURLError(CaptureError):
    """A request or redirect escaped the fixed HTTPS policy."""


class Transport(Protocol):
    def request_once(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        maximum_body_bytes: int,
    ) -> dict[str, Any]:
        """Return exactly one response without following redirects."""


def render_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def material(path: str, body: bytes) -> dict[str, Any]:
    validate_relative_path(path)
    if not body:
        raise CaptureError(f"evidence material is empty: {path}")
    return {
        "bytes": len(body),
        "path": path,
        "sha256": sha256_bytes(body),
    }


def positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CaptureError(f"{label} must be a positive integer")
    return value


def json_object(body: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise CaptureError(f"{label} must be a JSON object")
    return value


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_timestamp(value: str) -> None:
    if not isinstance(value, str) or len(value) > 40:
        raise CaptureError("observed_at must be a bounded RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CaptureError("observed_at is not valid RFC 3339") from error
    if parsed.tzinfo is None:
        raise CaptureError("observed_at must include a timezone")


def target_for(repository: str, tag: str) -> Target:
    try:
        return TARGETS[(repository, tag)]
    except KeyError as error:
        raise CaptureError(
            "repository/tag pair is not allowed by the release contract"
        ) from error


def canonical_https_url(url: str, allowed_hosts: set[str]) -> str:
    if (
        not isinstance(url, str)
        or not url
        or len(url.encode("utf-8")) > MAXIMUM_URL_BYTES
        or any(ord(character) < 32 for character in url)
    ):
        raise UnsafeURLError("URL is empty, overlong, or contains controls")
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
        or parsed.netloc.lower() not in {host, f"{host}:443"}
    ):
        raise UnsafeURLError(
            "refusing non-allowlisted HTTPS URL "
            f"(host={host or 'missing'})"
        )
    decoded_path = unquote(parsed.path)
    if "\\" in url or "\\" in decoded_path or any(
        part in {".", ".."} for part in decoded_path.split("/")
    ):
        raise UnsafeURLError("refusing ambiguous or traversing URL path")
    canonical = urlunsplit(
        ("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )
    if canonical != url:
        raise UnsafeURLError("URL is not in canonical HTTPS form")
    return canonical


def url_without_query(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )


def _header_values(
    headers: list[dict[str, str]],
    name: str,
) -> list[str]:
    lowered = name.lower()
    return [
        row["value"]
        for row in headers
        if row["name"].lower() == lowered
    ]


def _normalize_response(
    value: Any,
    maximum_body_bytes: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CaptureError("transport returned a non-object response")
    status = value.get("status")
    if (
        isinstance(status, bool)
        or not isinstance(status, int)
        or not 100 <= status <= 599
    ):
        raise CaptureError("transport returned an invalid HTTP status")
    reason = value.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 256:
        raise CaptureError("transport returned an invalid HTTP reason")
    body = value.get("body")
    if not isinstance(body, bytes):
        raise CaptureError("transport returned a non-bytes response body")
    if value.get("truncated") is True or len(body) > maximum_body_bytes:
        raise CaptureError("HTTP response exceeded its fixed body limit")
    raw_headers = value.get("headers")
    if not isinstance(raw_headers, list) or len(raw_headers) > 256:
        raise CaptureError("transport returned invalid response headers")
    headers: list[dict[str, str]] = []
    header_bytes = 0
    for row in raw_headers:
        if (
            not isinstance(row, dict)
            or set(row) != {"name", "value"}
            or not isinstance(row["name"], str)
            or not isinstance(row["value"], str)
            or not row["name"]
        ):
            raise CaptureError("transport returned an invalid response header")
        header_bytes += len(row["name"].encode("utf-8"))
        header_bytes += len(row["value"].encode("utf-8"))
        headers.append({"name": row["name"], "value": row["value"]})
    if header_bytes > MAXIMUM_HEADER_BYTES:
        raise CaptureError("HTTP response headers exceeded their fixed limit")
    return {
        "body": body,
        "headers": headers,
        "reason": reason,
        "status": status,
    }


class BoundedHTTPSNetworkTransport:
    """Direct TLS transport with no proxy, cookie jar, or redirect support."""

    def request_once(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        maximum_body_bytes: int,
    ) -> dict[str, Any]:
        parsed = urlsplit(url)
        connection = http.client.HTTPSConnection(
            parsed.hostname or "",
            port=parsed.port or 443,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
        target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        try:
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
            body = response.read(maximum_body_bytes + 1)
            return {
                "body": body[:maximum_body_bytes],
                "headers": [
                    {"name": name, "value": value}
                    for name, value in response.getheaders()
                ],
                "reason": str(response.reason),
                "status": int(response.status),
                "truncated": len(body) > maximum_body_bytes,
            }
        finally:
            connection.close()


@dataclass(frozen=True)
class FetchResult:
    body: bytes
    final_url: str
    hops: list[dict[str, Any]]
    status: int


def fetch_bounded(
    *,
    transport: Transport,
    url: str,
    allowed_hosts: set[str],
    headers: dict[str, str],
    maximum_body_bytes: int,
    purpose: str,
) -> FetchResult:
    current = canonical_https_url(url, allowed_hosts)
    hops: list[dict[str, Any]] = []
    for redirect_count in range(MAXIMUM_REDIRECTS + 1):
        request_headers = dict(headers)
        if urlsplit(current).hostname != API_HOST:
            request_headers.pop("Authorization", None)
        try:
            raw_response = transport.request_once(
                current,
                request_headers,
                REQUEST_TIMEOUT_SECONDS,
                maximum_body_bytes,
            )
        except Exception as error:
            if isinstance(error, CaptureError):
                raise
            raise CaptureError(
                f"{purpose} HTTPS request failed ({type(error).__name__})"
            ) from error
        response = _normalize_response(raw_response, maximum_body_bytes)
        hops.append(
            {
                "headers": response["headers"],
                "reason": response["reason"],
                "status": response["status"],
                "url": current,
            }
        )
        if response["status"] not in REDIRECT_STATUSES:
            return FetchResult(
                body=response["body"],
                final_url=current,
                hops=hops,
                status=response["status"],
            )
        if redirect_count == MAXIMUM_REDIRECTS:
            raise UnsafeURLError(f"{purpose} exceeded the redirect limit")
        locations = _header_values(response["headers"], "location")
        if len(locations) != 1 or not locations[0]:
            raise UnsafeURLError(
                f"{purpose} redirect did not have one Location header"
            )
        current = canonical_https_url(
            urljoin(current, locations[0]),
            allowed_hosts,
        )
    raise AssertionError("redirect loop is statically bounded")


def api_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": (
            "okf-uk-legislation-release-observation/"
            f"{TOOL_VERSION}"
        ),
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        if (
            len(token) > 1024
            or "\r" in token
            or "\n" in token
            or "\0" in token
        ):
            raise CaptureError("GITHUB_TOKEN has an invalid header shape")
        headers["Authorization"] = f"Bearer {token}"
    return headers


def asset_headers() -> dict[str, str]:
    return {
        "Accept": "application/octet-stream",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": (
            "okf-uk-legislation-release-observation/"
            f"{TOOL_VERSION}"
        ),
    }


def header_document(
    responses: list[tuple[str, FetchResult]],
) -> bytes:
    return render_json(
        {
            "requests": [
                {
                    "hops": result.hops,
                    "purpose": purpose,
                }
                for purpose, result in responses
            ]
        }
    )


def ensure_token_not_reflected(
    token: str | None,
    bodies: list[bytes],
) -> None:
    if not token:
        return
    needle = token.encode("utf-8")
    if any(needle in body for body in bodies):
        raise CaptureError(
            "a response reflected the authentication credential; "
            "no evidence was written"
        )


def validate_asset_arguments(
    asset_name: str | None,
    expected_asset_bytes: int | None,
    expected_asset_sha256: str | None,
) -> None:
    supplied = (
        asset_name is not None,
        expected_asset_bytes is not None,
        expected_asset_sha256 is not None,
    )
    if any(supplied) and not all(supplied):
        raise CaptureError(
            "asset name, expected bytes, and expected sha256 "
            "must be supplied together"
        )
    if asset_name is None:
        return
    if (
        not asset_name
        or len(asset_name.encode("utf-8")) > 255
        or asset_name in {".", ".."}
        or "/" in asset_name
        or "\\" in asset_name
        or any(ord(character) < 32 for character in asset_name)
    ):
        raise CaptureError("asset name is unsafe")
    positive_integer(expected_asset_bytes, "expected asset bytes")
    if expected_asset_bytes > MAXIMUM_ASSET_BODY_BYTES:
        raise CaptureError("expected asset exceeds the hard body limit")
    if (
        not isinstance(expected_asset_sha256, str)
        or not DIGEST.fullmatch(expected_asset_sha256)
    ):
        raise CaptureError("expected asset sha256 must be 64 lowercase hex")


def validate_release(
    body: dict[str, Any],
    target: Target,
) -> tuple[int, list[Any]]:
    release_id = positive_integer(body.get("id"), "release id")
    expected_html = f"{target.repository}/releases/tag/{target.tag}"
    if body.get("html_url") != expected_html:
        raise CaptureError("release HTML URL does not match the fixed target")
    if body.get("tag_name") != target.tag:
        raise CaptureError("release response tag does not match the fixed target")
    if body.get("draft") is not False:
        raise CaptureError("release is absent or still a draft")
    assets = body.get("assets")
    if not isinstance(assets, list):
        raise CaptureError("release response assets must be an array")
    return release_id, assets


def validate_relative_path(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise CaptureError("evidence path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise CaptureError("evidence path is unsafe")


def validate_schema(document: dict[str, Any]) -> None:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureError("release observation schema is unavailable") from error
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
            "generated release observation failed schema validation"
            + (f" at {location}" if location else "")
        )


def _external_new_destination(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise CaptureError(
            "output directory must be an absolute path without traversal"
        )
    if path.is_symlink() or os.path.lexists(path):
        raise CaptureError("output directory must be new and must not be a symlink")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise CaptureError(
            "output directory parent must be an existing non-symlink directory"
        )
    resolved_parent = parent.resolve(strict=True)
    resolved_root = ROOT.resolve()
    destination = resolved_parent / path.name
    if destination == resolved_root or destination.is_relative_to(resolved_root):
        raise CaptureError("output directory must be outside the repository")
    return destination


def _write_new_directory(
    destination: Path,
    files: dict[str, bytes],
) -> None:
    destination = _external_new_destination(destination)
    for relative, body in files.items():
        validate_relative_path(relative)
        if not isinstance(body, bytes) or not body:
            raise CaptureError(f"refusing empty evidence file: {relative}")
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.partial-",
            dir=destination.parent,
        )
    )
    try:
        for relative, body in sorted(files.items()):
            path = temporary / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            if relative.startswith("raw/"):
                os.chmod(path, 0o600)
        if os.path.lexists(destination):
            raise CaptureError("refusing to overwrite an evidence directory")
        os.rename(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _request_row(purpose: str, result: FetchResult) -> dict[str, Any]:
    return {
        "final_url_without_query": url_without_query(result.final_url),
        "http_status": result.status,
        "purpose": purpose,
        "redirects": len(result.hops) - 1,
    }


def capture_observation(
    *,
    repository: str,
    tag: str,
    expected_commit: str,
    output_dir: Path,
    asset_name: str | None = None,
    expected_asset_bytes: int | None = None,
    expected_asset_sha256: str | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    observed_at: str | None = None,
) -> Path:
    """Capture and atomically publish one verified observation directory."""

    target = target_for(repository, tag)
    if not isinstance(expected_commit, str) or not COMMIT.fullmatch(
        expected_commit
    ):
        raise CaptureError("expected commit must be 40 lowercase hex")
    validate_asset_arguments(
        asset_name,
        expected_asset_bytes,
        expected_asset_sha256,
    )
    destination = _external_new_destination(output_dir)
    timestamp = observed_at or utc_timestamp()
    validate_timestamp(timestamp)
    network = transport or BoundedHTTPSNetworkTransport()
    api_request_headers = api_headers(token)

    release_url = (
        f"https://api.github.com/repos/{target.slug}"
        f"/releases/tags/{target.tag}"
    )
    release_result = fetch_bounded(
        transport=network,
        url=release_url,
        allowed_hosts={API_HOST},
        headers=api_request_headers,
        maximum_body_bytes=MAXIMUM_API_BODY_BYTES,
        purpose="release",
    )
    if release_result.status != 200:
        raise CaptureError(
            f"release API returned HTTP {release_result.status}"
        )
    release_body = json_object(release_result.body, "release response")
    release_id, release_assets = validate_release(release_body, target)
    release_headers_body = header_document(
        [("release", release_result)]
    )
    ensure_token_not_reflected(
        token,
        [release_result.body, release_headers_body],
    )

    ref_url = (
        f"https://api.github.com/repos/{target.slug}"
        f"/git/ref/tags/{target.tag}"
    )
    ref_result = fetch_bounded(
        transport=network,
        url=ref_url,
        allowed_hosts={API_HOST},
        headers=api_request_headers,
        maximum_body_bytes=MAXIMUM_API_BODY_BYTES,
        purpose="tag-ref",
    )
    if ref_result.status != 200:
        raise CaptureError(f"tag ref API returned HTTP {ref_result.status}")
    ref_body = json_object(ref_result.body, "tag ref response")
    if ref_body.get("ref") != f"refs/tags/{target.tag}":
        raise CaptureError("tag ref response does not match the fixed tag")
    ref_object = ref_body.get("object")
    if not isinstance(ref_object, dict):
        raise CaptureError("tag ref object is missing")
    object_type = ref_object.get("type")
    object_sha = ref_object.get("sha")
    if object_type not in {"commit", "tag"}:
        raise CaptureError("tag ref has an unsupported object type")
    if not isinstance(object_sha, str) or not COMMIT.fullmatch(object_sha):
        raise CaptureError("tag ref object sha is not a full commit-like SHA")

    tag_responses: list[tuple[str, FetchResult]] = [("tag-ref", ref_result)]
    tag_body_files: list[tuple[str, bytes]] = [
        (TAG_REF_BODY_PATH, ref_result.body)
    ]
    if object_type == "commit":
        peeled_commit = object_sha
    else:
        tag_object_url = (
            f"https://api.github.com/repos/{target.slug}/git/tags/{object_sha}"
        )
        declared_object_url = ref_object.get("url")
        if declared_object_url != tag_object_url:
            raise CaptureError("annotated tag object URL is not the fixed API URL")
        tag_object_result = fetch_bounded(
            transport=network,
            url=tag_object_url,
            allowed_hosts={API_HOST},
            headers=api_request_headers,
            maximum_body_bytes=MAXIMUM_API_BODY_BYTES,
            purpose="annotated-tag",
        )
        if tag_object_result.status != 200:
            raise CaptureError(
                "annotated tag API returned HTTP "
                f"{tag_object_result.status}"
            )
        tag_object_body = json_object(
            tag_object_result.body,
            "annotated tag response",
        )
        if tag_object_body.get("sha") != object_sha:
            raise CaptureError("annotated tag response sha does not match the ref")
        tag_target = tag_object_body.get("object")
        if (
            not isinstance(tag_target, dict)
            or tag_target.get("type") != "commit"
            or not isinstance(tag_target.get("sha"), str)
            or not COMMIT.fullmatch(tag_target["sha"])
        ):
            raise CaptureError("annotated tag does not peel directly to a commit")
        peeled_commit = tag_target["sha"]
        tag_responses.append(("annotated-tag", tag_object_result))
        tag_body_files.append(
            (TAG_OBJECT_BODY_PATH, tag_object_result.body)
        )
    if peeled_commit != expected_commit:
        raise CaptureError("release tag does not resolve to the expected commit")
    tag_headers_body = header_document(tag_responses)
    ensure_token_not_reflected(
        token,
        [
            tag_headers_body,
            *(body for _path, body in tag_body_files),
        ],
    )

    raw_files: dict[str, bytes] = {
        RELEASE_HEADERS_PATH: release_headers_body,
        RELEASE_BODY_PATH: release_result.body,
        TAG_HEADERS_PATH: tag_headers_body,
        **dict(tag_body_files),
    }
    release_headers_material = material(
        RELEASE_HEADERS_PATH,
        release_headers_body,
    )
    release_body_material = material(
        RELEASE_BODY_PATH,
        release_result.body,
    )
    tag_headers_material = material(TAG_HEADERS_PATH, tag_headers_body)
    tag_body_materials = [
        material(path, body) for path, body in tag_body_files
    ]
    declared_materials = [
        release_headers_material,
        release_body_material,
        tag_headers_material,
        *tag_body_materials,
    ]
    request_rows = [
        _request_row("release", release_result),
        *[
            _request_row(purpose, result)
            for purpose, result in tag_responses
        ],
    ]

    asset_observation: dict[str, Any] | None = None
    if asset_name is not None:
        assert expected_asset_bytes is not None
        assert expected_asset_sha256 is not None
        expected_download_url = (
            f"{target.repository}/releases/download/{target.tag}/{asset_name}"
        )
        matches = [
            row
            for row in release_assets
            if isinstance(row, dict)
            and row.get("name") == asset_name
            and row.get("browser_download_url") == expected_download_url
        ]
        if len(matches) != 1:
            raise CaptureError(
                "release does not contain the required asset exactly once"
            )
        release_asset = matches[0]
        asset_id = positive_integer(release_asset.get("id"), "asset id")
        if release_asset.get("size") != expected_asset_bytes:
            raise CaptureError("release API asset size does not match expectation")
        asset_result = fetch_bounded(
            transport=network,
            url=expected_download_url,
            allowed_hosts=ASSET_HOSTS,
            headers=asset_headers(),
            maximum_body_bytes=expected_asset_bytes,
            purpose="release-asset",
        )
        if asset_result.status != 200:
            raise CaptureError(
                f"release asset returned HTTP {asset_result.status}"
            )
        if (
            len(asset_result.body) != expected_asset_bytes
            or sha256_bytes(asset_result.body) != expected_asset_sha256
        ):
            raise CaptureError(
                "downloaded release asset bytes or sha256 do not match"
            )
        asset_headers_body = header_document(
            [("release-asset", asset_result)]
        )
        ensure_token_not_reflected(
            token,
            [asset_headers_body, asset_result.body],
        )
        raw_files[ASSET_HEADERS_PATH] = asset_headers_body
        raw_files[ASSET_BODY_PATH] = asset_result.body
        asset_headers_material = material(
            ASSET_HEADERS_PATH,
            asset_headers_body,
        )
        asset_body_material = material(ASSET_BODY_PATH, asset_result.body)
        declared_materials.extend(
            [asset_headers_material, asset_body_material]
        )
        request_rows.append(_request_row("release-asset", asset_result))
        asset_observation = {
            "asset_id": asset_id,
            "bytes": len(asset_result.body),
            "download_url": expected_download_url,
            "http_status": asset_result.status,
            "name": asset_name,
            "response_body": asset_body_material,
            "response_headers": asset_headers_material,
            "sha256": sha256_bytes(asset_result.body),
        }

    attempt = {
        "authentication": {
            "credential_persisted": False,
            "github_token_supplied": token is not None,
            "request_host": API_HOST if token is not None else None,
        },
        "expected_commit": expected_commit,
        "materials": declared_materials,
        "network_policy": {
            "allowed_api_hosts": [API_HOST],
            "allowed_asset_hosts": sorted(ASSET_HOSTS),
            "maximum_api_body_bytes": MAXIMUM_API_BODY_BYTES,
            "maximum_asset_body_bytes": (
                expected_asset_bytes if asset_name is not None else None
            ),
            "maximum_redirects": MAXIMUM_REDIRECTS,
            "per_request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "retries": 0,
            "transport": "direct-https-manual-redirects",
        },
        "observed_at": timestamp,
        "repository": target.repository,
        "requests": request_rows,
        "schema": ATTEMPT_SCHEMA,
        "status": "complete",
        "tag": target.tag,
        "tool": {
            "name": Path(__file__).name,
            "sha256": sha256_bytes(Path(__file__).read_bytes()),
            "version": TOOL_VERSION,
        },
        "write_once": True,
    }
    attempt_body = render_json(attempt)
    attempt_material = material(ATTEMPT_MANIFEST_PATH, attempt_body)
    observation: dict[str, Any] = {
        "expected_commit": expected_commit,
        "integrity": {
            "attempt_manifest": attempt_material,
            "write_once": True,
        },
        "observed_at": timestamp,
        "release": {
            "api_url": release_url,
            "html_url": f"{target.repository}/releases/tag/{target.tag}",
            "http_status": release_result.status,
            "release_id": release_id,
            "response_body": release_body_material,
            "response_headers": release_headers_material,
            "tag_name": target.tag,
        },
        "repository": target.repository,
        "schema": OBSERVATION_SCHEMA,
        "status": "verified",
        "tag": target.tag,
        "tag_resolution": {
            "http_status": ref_result.status,
            "object_sha": object_sha,
            "object_type": object_type,
            "peeled_commit": peeled_commit,
            "ref_api_url": ref_url,
            "response_bodies": tag_body_materials,
            "response_headers": tag_headers_material,
        },
    }
    if asset_observation is not None:
        observation["asset"] = asset_observation
    validate_schema(observation)
    observation_body = render_json(observation)
    files = {
        **raw_files,
        ATTEMPT_MANIFEST_PATH: attempt_body,
        target.observation_filename: observation_body,
    }
    _write_new_directory(destination, files)
    return destination / target.observation_filename


def _error_text(error: BaseException, token: str | None) -> str:
    text = str(error)
    if token:
        text = text.replace(token, "[REDACTED]")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        required=True,
        choices=sorted({target.repository for target in TARGETS.values()}),
    )
    parser.add_argument(
        "--tag",
        required=True,
        choices=sorted({target.tag for target in TARGETS.values()}),
    )
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--asset-name")
    parser.add_argument("--expected-asset-bytes", type=int)
    parser.add_argument("--expected-asset-sha256")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="required acknowledgement before making the bounded requests",
    )
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN") or None
    if not args.allow_network:
        parser.error("--allow-network is required")
    try:
        observation = capture_observation(
            repository=args.repository,
            tag=args.tag,
            expected_commit=args.expected_commit,
            output_dir=args.output_dir,
            asset_name=args.asset_name,
            expected_asset_bytes=args.expected_asset_bytes,
            expected_asset_sha256=args.expected_asset_sha256,
            token=token,
        )
    except (CaptureError, OSError) as error:
        print(
            f"capture failed: {_error_text(error, token)}",
            file=sys.stderr,
        )
        return 2
    except BaseException as error:
        print(
            "capture failed: unexpected "
            f"{type(error).__name__}; no retry was attempted",
            file=sys.stderr,
        )
        return 2
    print(str(observation))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
