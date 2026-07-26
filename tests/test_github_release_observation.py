from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capture_github_release_observation as capture  # noqa: E402


COMMIT = "1" * 40
OTHER_COMMIT = "2" * 40
TAG_OBJECT_SHA = "3" * 40
OBSERVED_AT = "2026-07-26T10:00:00Z"
EXPLORER = "https://github.com/chris-page-gov/okf-explorer"
LEGISLATION = (
    "https://github.com/chris-page-gov/okf-uk-legislation"
)
ASSET_NAME = "okf-uk-legislation-v0.3.0.tar.zst"


def json_body(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def response(
    body: bytes = b"",
    *,
    status: int = 200,
    headers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "body": body,
        "headers": headers
        or [
            {"name": "Content-Type", "value": "application/json"},
            {"name": "X-GitHub-Request-Id", "value": "fixture-request"},
        ],
        "reason": "OK" if status == 200 else "Found",
        "status": status,
        "truncated": False,
    }


class FakeTransport:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request_once(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        maximum_body_bytes: int,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "headers": dict(headers),
                "maximum_body_bytes": maximum_body_bytes,
                "timeout_seconds": timeout_seconds,
                "url": url,
            }
        )
        configured = self.responses[url]
        if isinstance(configured, BaseException):
            raise configured
        result = copy.deepcopy(configured)
        body = result["body"]
        result["truncated"] = len(body) > maximum_body_bytes
        result["body"] = body[:maximum_body_bytes]
        return result


def explorer_responses(commit: str = COMMIT) -> dict[str, Any]:
    release_url = (
        "https://api.github.com/repos/chris-page-gov/okf-explorer/"
        "releases/tags/v0.5.0"
    )
    ref_url = (
        "https://api.github.com/repos/chris-page-gov/okf-explorer/"
        "git/ref/tags/v0.5.0"
    )
    return {
        release_url: response(
            json_body(
                {
                    "assets": [],
                    "draft": False,
                    "html_url": (
                        "https://github.com/chris-page-gov/okf-explorer/"
                        "releases/tag/v0.5.0"
                    ),
                    "id": 501,
                    "tag_name": "v0.5.0",
                }
            )
        ),
        ref_url: response(
            json_body(
                {
                    "object": {
                        "sha": commit,
                        "type": "commit",
                        "url": (
                            "https://api.github.com/repos/chris-page-gov/"
                            f"okf-explorer/git/commits/{commit}"
                        ),
                    },
                    "ref": "refs/tags/v0.5.0",
                }
            )
        ),
    }


def annotated_asset_responses(
    asset_body: bytes,
) -> dict[str, Any]:
    release_url = (
        "https://api.github.com/repos/chris-page-gov/"
        "okf-uk-legislation/releases/tags/v0.3.0"
    )
    ref_url = (
        "https://api.github.com/repos/chris-page-gov/"
        "okf-uk-legislation/git/ref/tags/v0.3.0"
    )
    tag_object_url = (
        "https://api.github.com/repos/chris-page-gov/"
        f"okf-uk-legislation/git/tags/{TAG_OBJECT_SHA}"
    )
    download_url = (
        "https://github.com/chris-page-gov/okf-uk-legislation/"
        f"releases/download/v0.3.0/{ASSET_NAME}"
    )
    redirected_url = (
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/fixture"
        "?sp=r&sig=official-fixture"
    )
    return {
        release_url: response(
            json_body(
                {
                    "assets": [
                        {
                            "browser_download_url": download_url,
                            "id": 9001,
                            "name": ASSET_NAME,
                            "size": len(asset_body),
                        }
                    ],
                    "draft": False,
                    "html_url": (
                        "https://github.com/chris-page-gov/"
                        "okf-uk-legislation/releases/tag/v0.3.0"
                    ),
                    "id": 7001,
                    "tag_name": "v0.3.0",
                }
            )
        ),
        ref_url: response(
            json_body(
                {
                    "object": {
                        "sha": TAG_OBJECT_SHA,
                        "type": "tag",
                        "url": tag_object_url,
                    },
                    "ref": "refs/tags/v0.3.0",
                }
            )
        ),
        tag_object_url: response(
            json_body(
                {
                    "object": {
                        "sha": COMMIT,
                        "type": "commit",
                    },
                    "sha": TAG_OBJECT_SHA,
                }
            )
        ),
        download_url: response(
            status=302,
            headers=[{"name": "Location", "value": redirected_url}],
        ),
        redirected_url: response(
            asset_body,
            headers=[
                {
                    "name": "Content-Type",
                    "value": "application/octet-stream",
                },
                {
                    "name": "Content-Length",
                    "value": str(len(asset_body)),
                },
            ],
        ),
    }


class GithubReleaseObservationTests(unittest.TestCase):
    def new_destination(self, temporary: str, name: str = "attempt") -> Path:
        return Path(temporary).resolve() / name

    def test_lightweight_tag_capture_validates_and_preserves_raw_responses(
        self,
    ) -> None:
        token = "github-token-that-must-never-be-written"
        transport = FakeTransport(explorer_responses())
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.new_destination(temporary)
            observation_path = capture.capture_observation(
                repository=EXPLORER,
                tag="v0.5.0",
                expected_commit=COMMIT,
                output_dir=destination,
                token=token,
                transport=transport,
                observed_at=OBSERVED_AT,
            )
            document = json.loads(observation_path.read_text())
            schema = json.loads(capture.SCHEMA_PATH.read_text())
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).validate(document)
            self.assertEqual(501, document["release"]["release_id"])
            self.assertEqual("commit", document["tag_resolution"]["object_type"])
            self.assertEqual(COMMIT, document["tag_resolution"]["peeled_commit"])
            self.assertNotIn("asset", document)
            self.assertEqual(
                explorer_responses()[
                    document["release"]["api_url"]
                ]["body"],
                (
                    destination
                    / document["release"]["response_body"]["path"]
                ).read_bytes(),
            )
            attempt = json.loads(
                (destination / "attempt-manifest.json").read_text()
            )
            self.assertEqual("complete", attempt["status"])
            self.assertEqual(0, attempt["network_policy"]["retries"])
            self.assertEqual(
                capture.sha256_bytes(
                    capture.Path(capture.__file__).read_bytes()
                ),
                attempt["tool"]["sha256"],
            )
            all_output = b"".join(
                path.read_bytes()
                for path in destination.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(token.encode(), all_output)
        self.assertEqual(2, len(transport.calls))
        self.assertTrue(
            all(
                call["headers"].get("Authorization") == f"Bearer {token}"
                for call in transport.calls
            )
        )

    def test_annotated_tag_is_peeled_and_required_asset_is_hashed(
        self,
    ) -> None:
        asset_body = b"\x28\xb5\x2f\xfdsealed-release-archive"
        digest = hashlib.sha256(asset_body).hexdigest()
        token = "another-token-that-must-not-leak"
        transport = FakeTransport(annotated_asset_responses(asset_body))
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.new_destination(temporary)
            observation_path = capture.capture_observation(
                repository=LEGISLATION,
                tag="v0.3.0",
                expected_commit=COMMIT,
                output_dir=destination,
                asset_name=ASSET_NAME,
                expected_asset_bytes=len(asset_body),
                expected_asset_sha256=digest,
                token=token,
                transport=transport,
                observed_at=OBSERVED_AT,
            )
            observation = json.loads(observation_path.read_text())
            self.assertEqual("tag", observation["tag_resolution"]["object_type"])
            self.assertEqual(2, len(observation["tag_resolution"]["response_bodies"]))
            self.assertEqual(COMMIT, observation["tag_resolution"]["peeled_commit"])
            self.assertEqual(7001, observation["release"]["release_id"])
            self.assertEqual(9001, observation["asset"]["asset_id"])
            self.assertEqual(len(asset_body), observation["asset"]["bytes"])
            self.assertEqual(digest, observation["asset"]["sha256"])
            self.assertEqual(
                asset_body,
                (
                    destination
                    / observation["asset"]["response_body"]["path"]
                ).read_bytes(),
            )
            attempt = json.loads(
                (destination / "attempt-manifest.json").read_text()
            )
            declared = {
                (
                    row["path"],
                    row["bytes"],
                    row["sha256"],
                )
                for row in attempt["materials"]
            }
            referenced = {
                (
                    row["path"],
                    row["bytes"],
                    row["sha256"],
                )
                for row in [
                    observation["release"]["response_headers"],
                    observation["release"]["response_body"],
                    observation["tag_resolution"]["response_headers"],
                    *observation["tag_resolution"]["response_bodies"],
                    observation["asset"]["response_headers"],
                    observation["asset"]["response_body"],
                ]
            }
            self.assertEqual(referenced, declared)
        api_calls = [
            call for call in transport.calls
            if call["url"].startswith("https://api.github.com/")
        ]
        asset_calls = [
            call for call in transport.calls
            if not call["url"].startswith("https://api.github.com/")
        ]
        self.assertEqual(3, len(api_calls))
        self.assertEqual(2, len(asset_calls))
        self.assertTrue(
            all("Authorization" in call["headers"] for call in api_calls)
        )
        self.assertTrue(
            all("Authorization" not in call["headers"] for call in asset_calls)
        )

    def test_malicious_redirect_is_rejected_before_second_request(self) -> None:
        release_url = next(iter(explorer_responses()))
        transport = FakeTransport(
            {
                release_url: response(
                    status=302,
                    headers=[
                        {
                            "name": "Location",
                            "value": "https://attacker.example/steal",
                        }
                    ],
                )
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.new_destination(temporary)
            with self.assertRaises(capture.UnsafeURLError):
                capture.capture_observation(
                    repository=EXPLORER,
                    tag="v0.5.0",
                    expected_commit=COMMIT,
                    output_dir=destination,
                    transport=transport,
                    observed_at=OBSERVED_AT,
                )
            self.assertFalse(os.path.lexists(destination))
        self.assertEqual([release_url], [call["url"] for call in transport.calls])

    def test_tag_mismatch_fails_closed_without_retry_or_partial_output(
        self,
    ) -> None:
        transport = FakeTransport(explorer_responses(OTHER_COMMIT))
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.new_destination(temporary)
            with self.assertRaisesRegex(
                capture.CaptureError,
                "does not resolve",
            ):
                capture.capture_observation(
                    repository=EXPLORER,
                    tag="v0.5.0",
                    expected_commit=COMMIT,
                    output_dir=destination,
                    transport=transport,
                    observed_at=OBSERVED_AT,
                )
            self.assertFalse(os.path.lexists(destination))
        self.assertEqual(2, len(transport.calls))

    def test_existing_output_is_never_overwritten(self) -> None:
        first = FakeTransport(explorer_responses())
        second = FakeTransport(explorer_responses())
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.new_destination(temporary)
            observation_path = capture.capture_observation(
                repository=EXPLORER,
                tag="v0.5.0",
                expected_commit=COMMIT,
                output_dir=destination,
                transport=first,
                observed_at=OBSERVED_AT,
            )
            before = {
                path.relative_to(destination).as_posix(): path.read_bytes()
                for path in destination.rglob("*")
                if path.is_file()
            }
            with self.assertRaisesRegex(capture.CaptureError, "must be new"):
                capture.capture_observation(
                    repository=EXPLORER,
                    tag="v0.5.0",
                    expected_commit=COMMIT,
                    output_dir=destination,
                    transport=second,
                    observed_at=OBSERVED_AT,
                )
            after = {
                path.relative_to(destination).as_posix(): path.read_bytes()
                for path in destination.rglob("*")
                if path.is_file()
            }
            self.assertTrue(observation_path.is_file())
            self.assertEqual(before, after)
        self.assertEqual([], second.calls)

    def test_symlink_and_traversing_destinations_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            transport = FakeTransport(explorer_responses())
            with self.assertRaises(capture.CaptureError):
                capture.capture_observation(
                    repository=EXPLORER,
                    tag="v0.5.0",
                    expected_commit=COMMIT,
                    output_dir=linked,
                    transport=transport,
                    observed_at=OBSERVED_AT,
                )
            with self.assertRaisesRegex(capture.CaptureError, "traversal"):
                capture.capture_observation(
                    repository=EXPLORER,
                    tag="v0.5.0",
                    expected_commit=COMMIT,
                    output_dir=root / "child" / ".." / "attempt",
                    transport=transport,
                    observed_at=OBSERVED_AT,
                )
            self.assertEqual([], transport.calls)

    def test_transport_crash_is_controlled_and_not_retried(self) -> None:
        responses = explorer_responses()
        ref_url = (
            "https://api.github.com/repos/chris-page-gov/okf-explorer/"
            "git/ref/tags/v0.5.0"
        )
        responses[ref_url] = RuntimeError("simulated worker crash")
        transport = FakeTransport(responses)
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.new_destination(temporary)
            with self.assertRaisesRegex(
                capture.CaptureError,
                "RuntimeError",
            ):
                capture.capture_observation(
                    repository=EXPLORER,
                    tag="v0.5.0",
                    expected_commit=COMMIT,
                    output_dir=destination,
                    transport=transport,
                    observed_at=OBSERVED_AT,
                )
            self.assertFalse(os.path.lexists(destination))
        self.assertEqual(2, len(transport.calls))


if __name__ == "__main__":
    unittest.main()
