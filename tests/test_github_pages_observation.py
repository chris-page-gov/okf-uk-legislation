from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import stat
import struct
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capture_github_pages_observation as capture  # noqa: E402


OBSERVED_AT = "2026-07-27T10:00:00Z"
HEAD = "a" * 40
TREE = "b" * 40
PUBLIC_ADDRESS = [{"address": "93.184.216.34", "family": "IPv4"}]
SIGNED_URL = (
    "https://productionresultssa1.blob.core.windows.net/"
    "actions-results/unit/pages.zip?sig=must-not-be-persisted&se=tomorrow"
)


def json_body(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def canonical_manifest(
    materials: list[dict[str, Any]],
    tree_sha256: str,
) -> bytes:
    value = {
        "schema": capture.BUILD_MANIFEST_SCHEMA,
        "algorithm": capture.CANONICAL_MATERIALS_ALGORITHM,
        "file_count": len(materials),
        "tree_sha256": tree_sha256,
        "materials": materials,
    }
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def archive_row(path: str, body: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def tar_bytes(
    entries: list[tuple[tarfile.TarInfo, bytes | None]],
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for info, body in entries:
            tar.addfile(info, io.BytesIO(body) if body is not None else None)
    return output.getvalue()


def directory(name: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.size = 0
    return info, None


def regular(name: str, body: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.REGTYPE
    info.mode = 0o644
    info.size = len(body)
    return info, body


def zip_bytes(
    entries: list[tuple[str, bytes, int | None]],
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for name, body, mode in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (
                ((stat.S_IFREG | 0o600) if mode is None else mode) << 16
            )
            archive.writestr(info, body)
    return output.getvalue()


def fixture_archive(
    *,
    actual_files: dict[str, bytes] | None = None,
    declared_files: dict[str, bytes] | None = None,
    manifest_renderer: Callable[
        [list[dict[str, Any]], str], bytes
    ] = canonical_manifest,
    extra_tar_entries: list[
        tuple[tarfile.TarInfo, bytes | None]
    ] | None = None,
    tar_transform: Callable[[bytes], bytes] | None = None,
    zip_entry_names: list[str] | None = None,
    zip_mode: int | None = None,
) -> tuple[capture.TargetProfile, bytes]:
    actual = actual_files or {
        "assets/app.js": b"console.log('fixture');\n",
        "index.html": b"<!doctype html><title>fixture</title>\n",
    }
    declared = declared_files if declared_files is not None else actual
    declared_rows = sorted(
        (archive_row(path, body) for path, body in declared.items()),
        key=lambda row: row["path"],
    )
    tree_digest = hashlib.sha256(
        capture.canonical_materials_bytes(declared_rows)
    ).hexdigest()
    manifest = manifest_renderer(declared_rows, tree_digest)
    entries: list[tuple[tarfile.TarInfo, bytes | None]] = [
        directory("./"),
        directory("./assets/"),
    ]
    for path, body in actual.items():
        entries.append(regular(f"./{path}", body))
    entries.append(
        regular("./okf-explorer-build-manifest.json", manifest)
    )
    entries.extend(extra_tar_entries or [])
    tar = tar_bytes(entries)
    if tar_transform is not None:
        tar = tar_transform(tar)
    names = zip_entry_names or ["artifact.tar"]
    zipped = zip_bytes(
        [(name, tar, zip_mode) for name in names]
    )
    index = declared_rows[
        [row["path"] for row in declared_rows].index("index.html")
    ]
    gnu_longnames = sum(
        1
        for info, _body in entries
        if len(info.name.encode("utf-8")) > 100
    )
    inventory_rows = sorted(
        (
            archive_row(info.name[2:], body or b"")
            for info, body in entries
            if info.isreg()
        ),
        key=lambda row: row["path"],
    )
    inventory_digest = hashlib.sha256(
        capture.canonical_materials_bytes(inventory_rows)
    ).hexdigest()
    profile = replace(
        capture.DEFAULT_PROFILE,
        run_id=101,
        run_attempt=1,
        head_sha=HEAD,
        git_tree=TREE,
        artifact_id=202,
        artifact_api_bytes=len(zipped),
        zip_bytes=len(zipped),
        zip_sha256=hashlib.sha256(zipped).hexdigest(),
        tar_bytes=len(tar),
        tar_sha256=hashlib.sha256(tar).hexdigest(),
        tar_member_count=len(entries),
        tar_file_count=sum(
            1 for info, _body in entries if info.isreg()
        ),
        tar_directory_count=sum(
            1 for info, _body in entries if info.isdir()
        ),
        tar_total_file_bytes=sum(
            info.size for info, _body in entries if info.isreg()
        ),
        tar_inventory_sha256=inventory_digest,
        tar_raw_header_count=len(entries) + gnu_longnames,
        tar_gnu_longname_count=gnu_longnames,
        build_manifest_bytes=len(manifest),
        build_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        build_file_count=len(declared_rows),
        build_tree_sha256=tree_digest,
        build_index_bytes=index["bytes"],
        build_index_sha256=index["sha256"],
    )
    return profile, zipped


def run_document(profile: capture.TargetProfile) -> dict[str, Any]:
    return {
        "conclusion": "success",
        "head_commit": {
            "id": profile.head_sha,
            "tree_id": profile.git_tree,
        },
        "head_sha": profile.head_sha,
        "html_url": f"{profile.repository}/actions/runs/{profile.run_id}",
        "id": profile.run_id,
        "path": profile.workflow_path,
        "repository": {
            "full_name": profile.slug,
            "html_url": profile.repository,
        },
        "run_attempt": profile.run_attempt,
        "status": "completed",
        "url": capture.run_resource_url(profile),
    }


def artifact_document(profile: capture.TargetProfile) -> dict[str, Any]:
    return {
        "archive_download_url": capture.artifact_download_url(profile),
        "expired": False,
        "id": profile.artifact_id,
        "name": profile.artifact_name,
        "size_in_bytes": profile.artifact_api_bytes,
        "url": capture.artifact_api_url(profile),
        "workflow_run": {
            "head_sha": profile.head_sha,
            "id": profile.run_id,
        },
    }


def response(
    body: bytes = b"",
    *,
    status: int = 200,
    headers: list[dict[str, str]] | None = None,
) -> capture.ResponseHandle:
    return capture.ResponseHandle(
        status=status,
        reason="OK" if status == 200 else "Found",
        headers=headers
        or [
            {"name": "Content-Type", "value": "application/json"},
            {"name": "X-GitHub-Request-Id", "value": "fixture-request"},
        ],
        stream=io.BytesIO(body),
    )


class FakeTransport:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def open_once(
        self,
        url: str,
        addresses: list[dict[str, str]],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> capture.ResponseHandle:
        self.calls.append(
            {
                "addresses": copy.deepcopy(addresses),
                "headers": dict(headers),
                "timeout_seconds": timeout_seconds,
                "url": url,
            }
        )
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            value = value()
        return copy.deepcopy(value)


def responses(
    profile: capture.TargetProfile,
    zipped: bytes,
    *,
    run: dict[str, Any] | None = None,
    artifact: dict[str, Any] | None = None,
    redirect: str = SIGNED_URL,
    zip_body: bytes | None = None,
    zip_content_length: int | None = None,
) -> dict[str, Any]:
    body = zipped if zip_body is None else zip_body
    length = len(body) if zip_content_length is None else zip_content_length
    return {
        capture.run_api_url(profile): response(
            json_body(run or run_document(profile))
        ),
        capture.artifact_api_url(profile): response(
            json_body(artifact or artifact_document(profile))
        ),
        capture.artifact_download_url(profile): response(
            status=302,
            headers=[
                {"name": "Location", "value": redirect},
                {
                    "name": "Set-Cookie",
                    "value": "download-secret=must-not-persist",
                },
            ],
        ),
        redirect: response(
            body,
            headers=[
                {
                    "name": "Content-Type",
                    "value": "application/zip",
                },
                {"name": "Content-Length", "value": str(length)},
                {
                    "name": "Set-Cookie",
                    "value": "storage-secret=must-not-persist",
                },
            ],
        ),
    }


def resolver(_host: str, _port: int) -> list[dict[str, str]]:
    return copy.deepcopy(PUBLIC_ADDRESS)


class GithubPagesObservationTests(unittest.TestCase):
    def destination(self, temporary: str) -> Path:
        return Path(temporary).resolve() / "pages-observation"

    def capture_fixture(
        self,
        temporary: str,
        *,
        profile: capture.TargetProfile,
        zipped: bytes,
        transport: FakeTransport | None = None,
        token: str | None = None,
    ) -> tuple[Path, FakeTransport]:
        network = transport or FakeTransport(responses(profile, zipped))
        path = capture.capture_observation(
            output_dir=self.destination(temporary),
            token=token,
            transport=network,
            resolver=resolver,
            clock=lambda: OBSERVED_AT,
            observed_at=OBSERVED_AT,
            profile=profile,
        )
        return path, network

    def test_fixed_production_target_records_all_authoritative_facts(self) -> None:
        profile = capture.DEFAULT_PROFILE
        self.assertEqual(30228627196, profile.run_id)
        self.assertEqual(1, profile.run_attempt)
        self.assertEqual(8639352412, profile.artifact_id)
        self.assertEqual(185023908, profile.zip_bytes)
        self.assertEqual(
            "357c2fcfbdb4fda34a830d933feb290dd8980cc61b0a82f51cd5e0e5a226c1c0",
            profile.zip_sha256,
        )
        self.assertEqual(817694720, profile.tar_bytes)
        self.assertEqual(9980, profile.tar_member_count)
        self.assertEqual(807618104, profile.tar_total_file_bytes)
        self.assertEqual(
            "13928e64e515171336f8c8523c515706693a1c13d8c46abc83728e779a913c61",
            profile.tar_inventory_sha256,
        )
        self.assertEqual(
            "a23dfdea56fea0184b6d53f3163b292dd1a312ed",
            profile.head_sha,
        )
        self.assertEqual(
            "981d5c967b7017c78f37aab379edd95f44917cf5",
            profile.git_tree,
        )
        self.assertEqual(490852327, profile.alternate_asset_id)

    def test_capture_validates_schema_and_closes_raw_evidence(self) -> None:
        profile, zipped = fixture_archive()
        token = "token-that-must-never-be-persisted"
        with tempfile.TemporaryDirectory() as temporary:
            observation_path, network = self.capture_fixture(
                temporary,
                profile=profile,
                zipped=zipped,
                token=token,
            )
            root = observation_path.parent
            document = json.loads(observation_path.read_text())
            schema = json.loads(capture.SCHEMA_PATH.read_text())
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).validate(document)
            self.assertEqual("verified", document["status"])
            self.assertEqual(TREE, document["run"]["git_tree"])
            self.assertEqual(
                profile.zip_sha256,
                document["archive"]["zip"]["material"]["sha256"],
            )
            self.assertEqual(
                profile.build_tree_sha256,
                document["archive"]["build"]["tree"]["computed_sha256"],
            )
            self.assertFalse(
                document["archive"]["tar"]["retained_separately"]
            )
            self.assertFalse((root / "artifact.tar").exists())
            attempt = json.loads((root / capture.ATTEMPT_MANIFEST_PATH).read_text())
            declared = {row["path"] for row in attempt["materials"]}
            self.assertEqual(
                {
                    capture.RUN_HEADERS_PATH,
                    capture.RUN_BODY_PATH,
                    capture.ARTIFACT_HEADERS_PATH,
                    capture.ARTIFACT_BODY_PATH,
                    capture.DOWNLOAD_HEADERS_PATH,
                    capture.ZIP_PATH,
                    capture.INVENTORY_PATH,
                },
                declared,
            )
            all_output = b"".join(
                path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(token.encode(), all_output)
            self.assertNotIn(b"must-not-be-persisted", all_output)
            self.assertNotIn(b"download-secret", all_output)
            self.assertNotIn(b"storage-secret", all_output)
            download_headers = json.loads(
                (root / capture.DOWNLOAD_HEADERS_PATH).read_text()
            )
            self.assertTrue(
                download_headers["hops"][0]["location_query_redacted"]
            )
            self.assertIn(
                "set-cookie",
                download_headers["hops"][0]["omitted_response_headers"],
            )
        api_calls = [
            call
            for call in network.calls
            if call["url"].startswith("https://api.github.com/")
        ]
        storage_calls = [
            call
            for call in network.calls
            if not call["url"].startswith("https://api.github.com/")
        ]
        self.assertEqual(3, len(api_calls))
        self.assertEqual(1, len(storage_calls))
        self.assertTrue(
            all(
                call["headers"].get("Authorization") == f"Bearer {token}"
                for call in api_calls
            )
        )
        self.assertTrue(
            all("Authorization" not in call["headers"] for call in storage_calls)
        )

    def test_api_target_mismatches_fail_closed_before_download(self) -> None:
        profile, zipped = fixture_archive()
        cases: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
            (
                "wrong run",
                lambda body: body.__setitem__("id", 999),
                "workflow run API",
            ),
            (
                "wrong attempt",
                lambda body: body.__setitem__("run_attempt", 2),
                "workflow run API",
            ),
            (
                "wrong commit",
                lambda body: body.__setitem__("head_sha", "c" * 40),
                "workflow run API",
            ),
            (
                "wrong tree",
                lambda body: body["head_commit"].__setitem__(
                    "tree_id", "c" * 40
                ),
                "head-commit tree",
            ),
            (
                "running",
                lambda body: body.__setitem__("status", "in_progress"),
                "workflow run API",
            ),
            (
                "failed",
                lambda body: body.__setitem__("conclusion", "failure"),
                "workflow run API",
            ),
            (
                "wrong workflow",
                lambda body: body.__setitem__(
                    "path", ".github/workflows/other.yml"
                ),
                "workflow run API",
            ),
        ]
        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                run = run_document(profile)
                mutate(run)
                network = FakeTransport(
                    responses(profile, zipped, run=run)
                )
                with self.assertRaisesRegex(capture.CaptureError, message):
                    self.capture_fixture(
                        temporary,
                        profile=profile,
                        zipped=zipped,
                        transport=network,
                    )
                self.assertFalse(os.path.lexists(self.destination(temporary)))
                self.assertEqual(1, len(network.calls))

    def test_artifact_identity_mismatches_fail_before_download(self) -> None:
        profile, zipped = fixture_archive()
        cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
            ("id", lambda body: body.__setitem__("id", 999)),
            ("name", lambda body: body.__setitem__("name", "other")),
            ("size", lambda body: body.__setitem__("size_in_bytes", 1)),
            ("expired", lambda body: body.__setitem__("expired", True)),
            (
                "run",
                lambda body: body["workflow_run"].__setitem__("id", 999),
            ),
            (
                "commit",
                lambda body: body["workflow_run"].__setitem__(
                    "head_sha", "c" * 40
                ),
            ),
        ]
        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                artifact = artifact_document(profile)
                mutate(artifact)
                network = FakeTransport(
                    responses(profile, zipped, artifact=artifact)
                )
                with self.assertRaisesRegex(
                    capture.CaptureError,
                    "artifact",
                ):
                    self.capture_fixture(
                        temporary,
                        profile=profile,
                        zipped=zipped,
                        transport=network,
                    )
                self.assertFalse(os.path.lexists(self.destination(temporary)))
                self.assertEqual(2, len(network.calls))

    def test_non_allowlisted_redirect_is_rejected_before_request(self) -> None:
        profile, zipped = fixture_archive()
        malicious = "https://attacker.example/steal?token=signed"
        network = FakeTransport(
            responses(profile, zipped, redirect=malicious)
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(capture.UnsafeRouteError):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                    transport=network,
                )
            self.assertFalse(os.path.lexists(self.destination(temporary)))
        self.assertEqual(3, len(network.calls))

    def test_private_dns_answer_is_rejected_before_transport(self) -> None:
        profile, zipped = fixture_archive()
        network = FakeTransport(responses(profile, zipped))

        def private(_host: str, _port: int) -> list[dict[str, str]]:
            return [{"address": "127.0.0.1", "family": "IPv4"}]

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(capture.UnsafeRouteError):
                capture.capture_observation(
                    output_dir=self.destination(temporary),
                    transport=network,
                    resolver=private,
                    clock=lambda: OBSERVED_AT,
                    observed_at=OBSERVED_AT,
                    profile=profile,
                )
            self.assertFalse(os.path.lexists(self.destination(temporary)))
        self.assertEqual([], network.calls)

    def test_private_or_mixed_azure_dns_is_rejected_before_storage(self) -> None:
        profile, zipped = fixture_archive()
        for label, azure_rows in (
            (
                "private",
                [{"address": "10.0.0.8", "family": "IPv4"}],
            ),
            (
                "mixed",
                [
                    {"address": "93.184.216.34", "family": "IPv4"},
                    {"address": "127.0.0.1", "family": "IPv4"},
                ],
            ),
        ):
            network = FakeTransport(responses(profile, zipped))

            def conditional(
                host: str,
                _port: int,
                rows: list[dict[str, str]] = azure_rows,
            ) -> list[dict[str, str]]:
                if host.endswith(capture.AZURE_BLOB_SUFFIX):
                    return copy.deepcopy(rows)
                return copy.deepcopy(PUBLIC_ADDRESS)

            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(capture.UnsafeRouteError):
                    capture.capture_observation(
                        output_dir=self.destination(temporary),
                        transport=network,
                        resolver=conditional,
                        clock=lambda: OBSERVED_AT,
                        observed_at=OBSERVED_AT,
                        profile=profile,
                    )
                self.assertFalse(os.path.lexists(self.destination(temporary)))
                self.assertEqual(3, len(network.calls))
                self.assertTrue(
                    all(
                        call["url"].startswith("https://api.github.com/")
                        for call in network.calls
                    )
                )

    def test_transport_receives_only_resolver_reviewed_addresses(self) -> None:
        profile, zipped = fixture_archive()
        network = FakeTransport(responses(profile, zipped))
        reviewed = [
            {
                "address": "2606:2800:220:1:248:1893:25c8:1946",
                "family": "IPv6",
            },
            {"address": "93.184.216.34", "family": "IPv4"},
            {"address": "93.184.216.34", "family": "IPv4"},
        ]
        expected = [
            {"address": "93.184.216.34", "family": "IPv4"},
            {
                "address": "2606:2800:220:1:248:1893:25c8:1946",
                "family": "IPv6",
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            capture.capture_observation(
                output_dir=self.destination(temporary),
                transport=network,
                resolver=lambda _host, _port: copy.deepcopy(reviewed),
                clock=lambda: OBSERVED_AT,
                observed_at=OBSERVED_AT,
                profile=profile,
            )
        self.assertTrue(network.calls)
        self.assertTrue(
            all(call["addresses"] == expected for call in network.calls)
        )

    def test_oversize_or_inconsistent_download_fails_atomically(self) -> None:
        profile, zipped = fixture_archive()
        cases = [
            (
                "body",
                responses(
                    profile,
                    zipped,
                    zip_body=zipped + b"x",
                    zip_content_length=len(zipped) + 1,
                ),
            ),
            (
                "length",
                responses(
                    profile,
                    zipped,
                    zip_content_length=len(zipped) + 1,
                ),
            ),
        ]
        for label, configured in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(capture.CaptureError):
                    self.capture_fixture(
                        temporary,
                        profile=profile,
                        zipped=zipped,
                        transport=FakeTransport(configured),
                    )
                self.assertFalse(os.path.lexists(self.destination(temporary)))

    def test_no_content_length_oversize_download_is_stream_bounded(self) -> None:
        profile, zipped = fixture_archive()
        configured = responses(profile, zipped)
        configured[SIGNED_URL] = response(
            zipped + b"x",
            headers=[
                {"name": "Content-Type", "value": "application/zip"},
            ],
        )
        network = FakeTransport(configured)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                capture.CaptureError,
                "fixed body limit",
            ):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                    transport=network,
                )
            self.assertFalse(os.path.lexists(self.destination(temporary)))

    def test_duplicate_or_wrong_zip_entries_are_rejected(self) -> None:
        cases = [
            {"zip_entry_names": ["artifact.tar", "artifact.tar"]},
            {"zip_entry_names": ["../artifact.tar"]},
            {
                "zip_mode": stat.S_IFLNK | 0o777,
            },
        ]
        for options in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    profile, zipped = fixture_archive(**options)
                with self.assertRaises(capture.CaptureError):
                    self.capture_fixture(
                        temporary,
                        profile=profile,
                        zipped=zipped,
                    )
                self.assertFalse(os.path.lexists(self.destination(temporary)))

    def test_eocd_and_zip64_bounds_fail_before_zipfile(self) -> None:
        profile, zipped = fixture_archive()
        eocd = zipped.rfind(b"PK\x05\x06")
        self.assertGreaterEqual(eocd, 0)
        cases: list[tuple[str, bytes]] = []
        wrong_count = bytearray(zipped)
        struct.pack_into("<H", wrong_count, eocd + 10, 2)
        cases.append(("entry count", bytes(wrong_count)))
        wrong_offset = bytearray(zipped)
        struct.pack_into("<L", wrong_offset, eocd + 16, len(zipped))
        cases.append(("bounds", bytes(wrong_offset)))
        missing_zip64 = bytearray(zipped)
        struct.pack_into("<H", missing_zip64, eocd + 10, 0xFFFF)
        cases.append(("ZIP64", bytes(missing_zip64)))
        for label, unsafe in cases:
            candidate = replace(
                profile,
                zip_sha256=hashlib.sha256(unsafe).hexdigest(),
            )
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "unsafe.zip"
                path.write_bytes(unsafe)
                with mock.patch.object(
                    capture.zipfile,
                    "ZipFile",
                    side_effect=AssertionError("zipfile must not run"),
                ) as zip_parser:
                    with self.assertRaises(capture.CaptureError):
                        capture.scan_pages_zip(path, candidate)
                zip_parser.assert_not_called()

    def test_encrypted_zip_entry_is_rejected_by_entry_validator(self) -> None:
        profile, _zipped = fixture_archive()
        info = zipfile.ZipInfo("artifact.tar")
        info.file_size = profile.tar_bytes
        info.compress_size = max(1, profile.tar_bytes // 2)
        info.flag_bits = 0x1
        info.external_attr = (stat.S_IFREG | 0o600) << 16
        with self.assertRaisesRegex(capture.CaptureError, "encrypted"):
            capture._validate_zip_entry(info, profile, 1)
        info.flag_bits = 0
        info.file_size = 1000
        info.compress_size = 1
        with self.assertRaisesRegex(capture.CaptureError, "bomb-like"):
            capture._validate_zip_entry(info, profile, 1)

    def test_valid_gnu_longname_is_proven_by_raw_header_pass(self) -> None:
        long_path = "assets/" + ("long-segment-" * 10) + "app.js"
        actual = {
            long_path: b"long-name fixture",
            "index.html": b"index",
        }
        profile, zipped = fixture_archive(actual_files=actual)
        self.assertEqual(1, profile.tar_gnu_longname_count)
        with tempfile.TemporaryDirectory() as temporary:
            path, _network = self.capture_fixture(
                temporary,
                profile=profile,
                zipped=zipped,
            )
            document = json.loads(path.read_text())
            census = document["archive"]["tar"]["raw_header_census"]
            self.assertEqual(1, census["gnu_longname_headers"])
            self.assertEqual(
                profile.tar_raw_header_count,
                census["raw_headers"],
            )

    def test_raw_directory_without_trailing_slash_is_rejected(self) -> None:
        info = tarfile.TarInfo("./bad-directory")
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.size = 0

        def remove_trailing_slash(body: bytes) -> bytes:
            changed = bytearray(body)
            position = body.index(b"./bad-directory/")
            offset = (position // 512) * 512
            raw_name = b"./bad-directory"
            changed[offset : offset + 100] = raw_name.ljust(100, b"\0")
            changed[offset + 148 : offset + 156] = b" " * 8
            checksum = sum(changed[offset : offset + 512])
            changed[offset + 148 : offset + 156] = (
                f"{checksum:06o}\0 ".encode("ascii")
            )
            return bytes(changed)

        profile, zipped = fixture_archive(
            extra_tar_entries=[(info, None)],
            tar_transform=remove_trailing_slash,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                capture.CaptureError,
                "trailing slash",
            ):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                )

    def test_tar_links_devices_fifo_and_duplicates_are_rejected(self) -> None:
        specials = []
        for kind in (
            tarfile.SYMTYPE,
            tarfile.LNKTYPE,
            tarfile.FIFOTYPE,
            tarfile.CHRTYPE,
        ):
            info = tarfile.TarInfo("./unsafe")
            info.type = kind
            info.size = 0
            if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                info.linkname = "./index.html"
            specials.append((kind, [(info, None)]))
        specials.append(
            (
                "duplicate",
                [regular("./index.html", b"duplicate")],
            )
        )
        for label, extra in specials:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                profile, zipped = fixture_archive(extra_tar_entries=extra)
                with self.assertRaises(capture.CaptureError):
                    self.capture_fixture(
                        temporary,
                        profile=profile,
                        zipped=zipped,
                    )
                self.assertFalse(os.path.lexists(self.destination(temporary)))

    def test_archive_path_rejects_traversal_control_del_long_and_surrogate(
        self,
    ) -> None:
        unsafe = [
            "./../evil",
            "./bad\nname",
            "./bad\x7fname",
            "./" + ("x" * 4097),
            "./bad\ud800name",
            "index.html",
            "./dir/",
        ]
        for raw in unsafe:
            with self.subTest(raw=repr(raw)), self.assertRaises(
                capture.CaptureError
            ):
                capture.canonical_tar_path(raw, directory=False)
        self.assertEqual(
            "😀" * 2048,
            capture.validate_archive_path("😀" * 2048),
        )
        with self.assertRaises(capture.CaptureError):
            capture.validate_archive_path("😀" * 2049)

    def test_transport_crash_and_malformed_headers_do_not_retry_or_write(
        self,
    ) -> None:
        profile, zipped = fixture_archive()
        configured = responses(profile, zipped)
        configured[capture.artifact_api_url(profile)] = RuntimeError(
            "secret transport detail"
        )
        network = FakeTransport(configured)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(capture.CaptureError, "RuntimeError"):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                    transport=network,
                )
            self.assertFalse(os.path.lexists(self.destination(temporary)))
        self.assertEqual(2, len(network.calls))

        malformed = responses(profile, zipped)
        malformed[capture.run_api_url(profile)] = response(
            json_body(run_document(profile)),
            headers=[{"name": "X-Test", "value": "bad\nvalue"}],
        )
        network = FakeTransport(malformed)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(capture.CaptureError, "malformed"):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                    transport=network,
                )
            self.assertFalse(os.path.lexists(self.destination(temporary)))
        self.assertEqual(1, len(network.calls))

    def test_reflected_token_in_arbitrary_header_is_never_persisted(self) -> None:
        profile, zipped = fixture_archive()
        token = "reflected-token-value"
        configured = responses(profile, zipped)
        configured[capture.run_api_url(profile)] = response(
            json_body(run_document(profile)),
            headers=[
                {"name": "Content-Type", "value": "application/json"},
                {"name": "X-Reflection", "value": token},
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                capture.CaptureError,
                "credential would be persisted",
            ):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                    transport=FakeTransport(configured),
                    token=token,
                )
            self.assertFalse(os.path.lexists(self.destination(temporary)))

    def test_second_storage_host_and_output_symlink_fail_closed(self) -> None:
        profile, zipped = fixture_archive()
        second = (
            "https://productionresultssa2.blob.core.windows.net/"
            "actions-results/other.zip?sig=other"
        )
        configured = responses(profile, zipped)
        configured[SIGNED_URL] = response(
            status=302,
            headers=[{"name": "Location", "value": second}],
        )
        configured[second] = response(zipped)
        network = FakeTransport(configured)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                capture.UnsafeRouteError,
                "changed Azure",
            ):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                    transport=network,
                )
            self.assertEqual(4, len(network.calls))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            network = FakeTransport(responses(profile, zipped))
            with self.assertRaisesRegex(capture.CaptureError, "symlink"):
                capture.capture_observation(
                    output_dir=linked,
                    transport=network,
                    resolver=resolver,
                    clock=lambda: OBSERVED_AT,
                    observed_at=OBSERVED_AT,
                    profile=profile,
                )
            self.assertEqual([], network.calls)

    def test_profile_hard_caps_fail_before_network(self) -> None:
        profile, _zipped = fixture_archive()
        invalid = [
            replace(
                profile,
                zip_bytes=capture.MAXIMUM_ZIP_BYTES + 1,
                artifact_api_bytes=capture.MAXIMUM_ZIP_BYTES + 1,
            ),
            replace(
                profile,
                tar_bytes=capture.MAXIMUM_TAR_BYTES + 1,
            ),
            replace(
                profile,
                tar_raw_header_count=profile.tar_raw_header_count + 1,
            ),
        ]
        for value in invalid:
            with self.subTest(profile=value), tempfile.TemporaryDirectory() as temporary:
                network = FakeTransport({})
                with self.assertRaises(capture.CaptureError):
                    capture.capture_observation(
                        output_dir=self.destination(temporary),
                        transport=network,
                        resolver=resolver,
                        clock=lambda: OBSERVED_AT,
                        observed_at=OBSERVED_AT,
                        profile=value,
                    )
                self.assertEqual([], network.calls)

    def test_noncanonical_manifest_is_rejected(self) -> None:
        def compact(
            rows: list[dict[str, Any]],
            digest: str,
        ) -> bytes:
            return json_body(
                {
                    "algorithm": capture.CANONICAL_MATERIALS_ALGORITHM,
                    "file_count": len(rows),
                    "materials": rows,
                    "schema": capture.BUILD_MANIFEST_SCHEMA,
                    "tree_sha256": digest,
                }
            )

        profile, zipped = fixture_archive(manifest_renderer=compact)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(capture.CaptureError, "canonical"):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                )

    def test_missing_or_tampered_non_index_build_file_is_rejected(self) -> None:
        declared = {
            "assets/app.js": b"declared app",
            "index.html": b"index",
        }
        cases = [
            {"actual_files": {"index.html": b"index"}},
            {
                "actual_files": {
                    "assets/app.js": b"tampered app",
                    "index.html": b"index",
                }
            },
        ]
        for options in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                profile, zipped = fixture_archive(
                    declared_files=declared,
                    **options,
                )
                with self.assertRaisesRegex(
                    capture.CaptureError,
                    "TAR inventory",
                ):
                    self.capture_fixture(
                        temporary,
                        profile=profile,
                        zipped=zipped,
                    )

    def test_v053_post_manifest_pages_404_overwrite_is_rejected(self) -> None:
        """Regress the exact fail-closed condition in Actions run 30226282632."""

        observed_mismatch = {
            "declared": {
                "bytes": 1122,
                "sha256": (
                    "0db86b431ae7017268be6ff89f955719"
                    "bfdc9de2810f8c811439a9b9ce22060b"
                ),
            },
            "actual": {
                "bytes": 159,
                "sha256": (
                    "d07a3c1c6f485ef19cc52285fbedba5"
                    "318a704b44a4a2cafc096c8ce33b8e28c"
                ),
            },
        }
        declared = {
            "404.html": b"x" * 1122,
            "index.html": b"index",
        }
        overwritten_404 = (
            b"<!doctype html><meta charset=\"utf-8\"><title>OKF Explorer</title>"
            b"<meta http-equiv=\"refresh\" content=\"0; url=./\">"
            b"<p>Return to <a href=\"./\">OKF Explorer</a>.</p>\n"
        )
        self.assertEqual(observed_mismatch["actual"]["bytes"], len(overwritten_404))
        self.assertEqual(
            observed_mismatch["actual"]["sha256"],
            hashlib.sha256(overwritten_404).hexdigest(),
        )
        self.assertEqual(1122, observed_mismatch["declared"]["bytes"])
        actual = {
            "404.html": overwritten_404,
            "index.html": b"index",
        }
        profile, zipped = fixture_archive(
            actual_files=actual,
            declared_files=declared,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                capture.CaptureError,
                "TAR inventory: 404.html",
            ):
                self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                )

    def test_write_once_rerun_is_idempotent_without_network(self) -> None:
        profile, zipped = fixture_archive()
        with tempfile.TemporaryDirectory() as temporary:
            first_path, _network = self.capture_fixture(
                temporary,
                profile=profile,
                zipped=zipped,
            )
            before = {
                path.relative_to(first_path.parent).as_posix(): path.read_bytes()
                for path in first_path.parent.rglob("*")
                if path.is_file()
            }
            second = FakeTransport({})
            second_path = capture.capture_observation(
                output_dir=self.destination(temporary),
                transport=second,
                resolver=resolver,
                clock=lambda: OBSERVED_AT,
                observed_at=OBSERVED_AT,
                profile=profile,
            )
            after = {
                path.relative_to(first_path.parent).as_posix(): path.read_bytes()
                for path in first_path.parent.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_path, second_path)
            self.assertEqual(before, after)
            self.assertEqual([], second.calls)

    def test_schema_valid_semantic_mutations_are_rejected_on_rerun(self) -> None:
        profile, zipped = fixture_archive()
        for mutation in ("observation", "attempt"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                observation_path, _network = self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                )
                root = observation_path.parent
                observation = json.loads(observation_path.read_text())
                if mutation == "observation":
                    observation["observed_at"] = "2026-07-27T10:00:01Z"
                else:
                    attempt_path = root / capture.ATTEMPT_MANIFEST_PATH
                    attempt = json.loads(attempt_path.read_text())
                    attempt["limits"]["retries"] = 1
                    attempt_body = capture.render_json(attempt)
                    attempt_path.write_bytes(attempt_body)
                    observation["integrity"]["attempt_manifest"] = (
                        capture.material(
                            capture.ATTEMPT_MANIFEST_PATH,
                            attempt_body,
                        )
                    )
                observation_path.write_bytes(
                    capture.render_json(observation)
                )
                schema = json.loads(capture.SCHEMA_PATH.read_text())
                Draft202012Validator(
                    schema,
                    format_checker=FormatChecker(),
                ).validate(json.loads(observation_path.read_text()))
                with self.assertRaisesRegex(
                    capture.CaptureError,
                    "diverges from raw evidence",
                ):
                    capture.capture_observation(
                        output_dir=self.destination(temporary),
                        transport=FakeTransport({}),
                        resolver=resolver,
                        clock=lambda: OBSERVED_AT,
                        observed_at=OBSERVED_AT,
                        profile=profile,
                    )

    def test_competing_writer_wins_without_being_replaced(self) -> None:
        profile, zipped = fixture_archive()
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.destination(temporary)

            def competing_writer() -> None:
                destination.mkdir()
                (destination / "owner.txt").write_text(
                    "competing writer\n",
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(
                capture.CaptureError,
                "competing writer",
            ):
                capture.capture_observation(
                    output_dir=destination,
                    transport=FakeTransport(responses(profile, zipped)),
                    resolver=resolver,
                    clock=lambda: OBSERVED_AT,
                    observed_at=OBSERVED_AT,
                    profile=profile,
                    publication_barrier=competing_writer,
                )
            self.assertEqual(
                "competing writer\n",
                (destination / "owner.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                [],
                list(destination.parent.glob(f".{destination.name}.partial-*")),
            )

    def test_cleanup_failure_is_observable_and_private_without_secrets(
        self,
    ) -> None:
        profile, zipped = fixture_archive()
        token = "cleanup-secret-token"
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.destination(temporary)

            def stop_before_publish() -> None:
                raise capture.CaptureError(
                    f"halt {token} at {SIGNED_URL}"
                )

            with mock.patch.object(
                capture.shutil,
                "rmtree",
                side_effect=OSError("simulated cleanup failure"),
            ):
                with self.assertRaisesRegex(
                    capture.CaptureError,
                    "partial evidence cleanup failed",
                ):
                    capture.capture_observation(
                        output_dir=destination,
                        token=token,
                        transport=FakeTransport(responses(profile, zipped)),
                        resolver=resolver,
                        clock=lambda: OBSERVED_AT,
                        observed_at=OBSERVED_AT,
                        profile=profile,
                        publication_barrier=stop_before_publish,
                    )
            partials = list(
                destination.parent.glob(f".{destination.name}.partial-*")
            )
            self.assertEqual(1, len(partials))
            partial = partials[0]
            self.assertEqual(
                0o700,
                stat.S_IMODE(partial.stat(follow_symlinks=False).st_mode),
            )
            persisted = b"".join(
                path.read_bytes()
                for path in partial.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(token.encode(), persisted)
            self.assertNotIn(b"must-not-be-persisted", persisted)
            shutil.rmtree(partial)

    def test_write_once_divergence_and_extra_files_are_rejected(self) -> None:
        profile, zipped = fixture_archive()
        for mutation in ("body", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                observation_path, _network = self.capture_fixture(
                    temporary,
                    profile=profile,
                    zipped=zipped,
                )
                if mutation == "body":
                    path = observation_path.parent / capture.RUN_BODY_PATH
                    path.write_bytes(path.read_bytes() + b"x")
                else:
                    (observation_path.parent / "unexpected").write_text("x")
                with self.assertRaisesRegex(capture.CaptureError, "diverge"):
                    capture.capture_observation(
                        output_dir=self.destination(temporary),
                        transport=FakeTransport({}),
                        resolver=resolver,
                        clock=lambda: OBSERVED_AT,
                        observed_at=OBSERVED_AT,
                        profile=profile,
                    )

    def test_existing_hardlinked_material_is_rejected(self) -> None:
        profile, zipped = fixture_archive()
        with tempfile.TemporaryDirectory() as temporary:
            observation_path, _network = self.capture_fixture(
                temporary,
                profile=profile,
                zipped=zipped,
            )
            source = observation_path.parent / capture.RUN_BODY_PATH
            linked = Path(temporary) / "second-link"
            os.link(source, linked)
            try:
                with self.assertRaisesRegex(
                    capture.CaptureError,
                    "single-link",
                ):
                    capture.capture_observation(
                        output_dir=self.destination(temporary),
                        transport=FakeTransport({}),
                        resolver=resolver,
                        clock=lambda: OBSERVED_AT,
                        observed_at=OBSERVED_AT,
                        profile=profile,
                    )
            finally:
                linked.unlink()

    def test_schema_rejects_unexpected_property(self) -> None:
        schema = json.loads(capture.SCHEMA_PATH.read_text())
        Draft202012Validator.check_schema(schema)
        profile, zipped = fixture_archive()
        with tempfile.TemporaryDirectory() as temporary:
            path, _network = self.capture_fixture(
                temporary,
                profile=profile,
                zipped=zipped,
            )
            document = json.loads(path.read_text())
            document["unexpected"] = True
            errors = list(
                Draft202012Validator(
                    schema,
                    format_checker=FormatChecker(),
                ).iter_errors(document)
            )
            self.assertTrue(errors)

    def test_schema_rejects_unsafe_paths_and_request_urls(self) -> None:
        schema = json.loads(capture.SCHEMA_PATH.read_text())
        profile, zipped = fixture_archive()
        with tempfile.TemporaryDirectory() as temporary:
            path, _network = self.capture_fixture(
                temporary,
                profile=profile,
                zipped=zipped,
            )
            baseline = json.loads(path.read_text())
        cases: list[Callable[[dict[str, Any]], None]] = [
            lambda value: value["integrity"]["attempt_manifest"].__setitem__(
                "path", "raw//attempt.json"
            ),
            lambda value: value["integrity"]["attempt_manifest"].__setitem__(
                "path", "raw/../attempt.json"
            ),
            lambda value: value["requests"][0].__setitem__(
                "final_url", "https://user@api.github.com/unsafe"
            ),
            lambda value: value["requests"][2].__setitem__(
                "final_url", "https://example.com/archive.zip"
            ),
        ]
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )
        for mutate in cases:
            candidate = copy.deepcopy(baseline)
            mutate(candidate)
            self.assertTrue(list(validator.iter_errors(candidate)))

    def test_error_text_and_cli_stderr_redact_token_and_signed_query(
        self,
    ) -> None:
        token = "stderr-secret-token"
        error = capture.CaptureError(
            f"failed with {token} at {SIGNED_URL}"
        )
        rendered = capture._error_text(error, token)
        self.assertNotIn(token, rendered)
        self.assertNotIn("must-not-be-persisted", rendered)
        self.assertNotIn("tomorrow", rendered)

        stderr = io.StringIO()
        output = Path(tempfile.gettempdir()).resolve() / "unused-pages-output"
        with mock.patch.dict(
            os.environ,
            {"GITHUB_TOKEN": token},
            clear=False,
        ), mock.patch.object(
            capture,
            "capture_observation",
            side_effect=error,
        ), redirect_stderr(stderr):
            status = capture.main(
                ["--output-dir", str(output), "--allow-network"]
            )
        self.assertEqual(2, status)
        self.assertNotIn(token, stderr.getvalue())
        self.assertNotIn("must-not-be-persisted", stderr.getvalue())
        self.assertNotIn("tomorrow", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
