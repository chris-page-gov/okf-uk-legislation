from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import seal_refresh_attempt as refresh  # noqa: E402


def observation_bytes(
    *,
    result: str = "no-drift-observed",
    violations: list[str] | None = None,
    new_works: int = 0,
) -> bytes:
    report = {
        "access_policy": {
            "authentication": "none",
            "body_limit_bytes": 1_048_576,
            "hosts": ["chris-page-gov.github.io", "legislation.gov.uk"],
            "redirects": "https allowlist only; maximum 5",
            "repository_writes": False,
        },
        "generated_at": "2026-07-26T08:15:30Z",
        "local": {
            "access_evidence": {
                "access_methods": 108,
                "source_records": 72,
            },
            "checksums_valid": True,
            "snapshot": {
                "generated_at": "2026-07-25T20:00:00Z",
                "id": "legislation-20260725",
            },
            "works": 365786,
        },
        "new_work_feed": {
            "bytes_read": 1024,
            "sha256": "1" * 64,
            "status": 200,
            "url": "https://www.legislation.gov.uk/all/data.feed",
        },
        "new_works": {
            "new_works": [],
            "new_works_count": new_works,
            "observed_entries": 20,
            "records": [],
        },
        "public_links": [
            {
                "sha256": "2" * 64,
                "status": 200,
                "url": (
                    "https://chris-page-gov.github.io/"
                    "okf-uk-legislation/okf-explorer.json"
                ),
            }
        ],
        "result": result,
        "schema": "okf-release-drift-observation.v1",
        "violations": violations or [],
    }
    return refresh.render(report)


class RefreshAttemptTests(unittest.TestCase):
    SOURCE_COMMIT = "a" * 40

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.observation = self.root / "observation.json"
        self.observation.write_bytes(observation_bytes())

    def test_seal_creates_a_schema_valid_content_addressed_datapack(self) -> None:
        package = refresh.seal_attempt(
            self.observation,
            self.root / "attempts",
            self.SOURCE_COMMIT,
        )
        manifest = refresh.verify_attempt(package)
        datapack = json.loads((package / "datapack.json").read_text())

        self.assertRegex(
            package.name,
            r"^20260726T081530Z-[0-9a-f]{16}$",
        )
        self.assertEqual(package.name, manifest["attempt_id"])
        self.assertEqual(
            f"refresh-attempt-{package.name}",
            manifest["persistence"]["release_tag"],
        )
        self.assertTrue(manifest["persistence"]["append_only"])
        self.assertTrue(manifest["immutable"])
        self.assertEqual(
            {
                "source_drift",
                "new_work_delta",
                "link_availability",
                "checksum_integrity",
                "source_access",
            },
            {probe["name"] for probe in manifest["probes"]},
        )
        self.assertEqual(5, datapack["counts"]["probes"])
        self.assertEqual(5, datapack["counts"]["passed"])

        manifest_schema = refresh.load_schema(refresh.MANIFEST_SCHEMA_PATH)
        datapack_schema = refresh.load_schema(refresh.DATAPACK_SCHEMA_PATH)
        Draft202012Validator.check_schema(manifest_schema)
        Draft202012Validator.check_schema(datapack_schema)
        Draft202012Validator(manifest_schema).validate(manifest)
        Draft202012Validator(datapack_schema).validate(datapack)

    def test_resealing_the_same_attempt_is_idempotent_not_a_rewrite(self) -> None:
        package = refresh.seal_attempt(
            self.observation,
            self.root / "attempts",
            self.SOURCE_COMMIT,
        )
        before = {
            path.relative_to(package).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in package.rglob("*")
            if path.is_file()
        }
        repeated = refresh.seal_attempt(
            self.observation,
            self.root / "attempts",
            self.SOURCE_COMMIT,
        )
        after = {
            path.relative_to(package).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in package.rglob("*")
            if path.is_file()
        }
        self.assertEqual(package, repeated)
        self.assertEqual(before, after)

    def test_each_commit_gets_a_distinct_append_only_attempt(self) -> None:
        first = refresh.seal_attempt(
            self.observation,
            self.root / "attempts",
            self.SOURCE_COMMIT,
        )
        second = refresh.seal_attempt(
            self.observation,
            self.root / "attempts",
            "b" * 40,
        )
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())
        refresh.verify_attempt(first)
        refresh.verify_attempt(second)

    def test_tampering_is_detected(self) -> None:
        package = refresh.seal_attempt(
            self.observation,
            self.root / "attempts",
            self.SOURCE_COMMIT,
        )
        (package / "README.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(
            refresh.RefreshAttemptError,
            "checksums.json does not match",
        ):
            refresh.verify_attempt(package)

    def test_drift_and_unavailable_probe_states_are_preserved(self) -> None:
        self.observation.write_bytes(
            observation_bytes(
                result="drift-detected",
                violations=["new works found"],
                new_works=2,
            )
        )
        package = refresh.seal_attempt(
            self.observation,
            self.root / "attempts",
            self.SOURCE_COMMIT,
        )
        manifest = refresh.verify_attempt(package)
        statuses = {
            probe["name"]: probe["status"] for probe in manifest["probes"]
        }
        self.assertEqual("drift", statuses["source_drift"])
        self.assertEqual("drift", statuses["new_work_delta"])
        self.assertEqual("drift-detected", manifest["result"])

    def test_repository_output_is_refused(self) -> None:
        with self.assertRaisesRegex(
            refresh.RefreshAttemptError,
            "outside the repository",
        ):
            refresh.seal_attempt(
                self.observation,
                ROOT / ".forbidden-refresh-attempt",
                self.SOURCE_COMMIT,
            )

    def test_unbounded_or_symbolic_link_observations_are_refused(self) -> None:
        with self.assertRaisesRegex(
            refresh.RefreshAttemptError,
            "observation must be 1-",
        ):
            refresh.build_package_documents(
                b"x" * (refresh.MAX_OBSERVATION_BYTES + 1),
                self.SOURCE_COMMIT,
            )

        link = self.root / "observation-link.json"
        link.symlink_to(self.observation)
        with self.assertRaisesRegex(
            refresh.RefreshAttemptError,
            "non-symlink regular file",
        ):
            refresh.seal_attempt(
                link,
                self.root / "attempts",
                self.SOURCE_COMMIT,
            )

    def test_policy_and_workflow_make_releases_primary_and_append_only(self) -> None:
        policy = json.loads(
            (
                ROOT / "release-assurance" / "refresh-attempt-policy.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            sorted(refresh.EXPECTED_FILES),
            sorted(policy["package"]["files"]),
        )
        self.assertEqual(
            "unique-github-release",
            policy["persistence"]["primary"],
        )
        self.assertTrue(policy["persistence"]["append_only"])
        self.assertTrue(policy["persistence"]["overwrite_prohibited"])
        self.assertEqual(
            refresh.MAX_OBSERVATION_BYTES,
            policy["package"]["maximum_observation_bytes"],
        )
        self.assertTrue(
            policy["untrusted_content"]["raw_observation_is_data_only"]
        )
        self.assertTrue(
            policy["persistence"]["workflow_artifact_is_secondary_only"]
        )

        workflow_path = ROOT / ".github" / "workflows" / "drift.yml"
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        self.assertEqual("write", workflow["permissions"]["contents"])
        steps = workflow["jobs"]["observe"]["steps"]
        observe = next(step for step in steps if step.get("id") == "observe")
        seal = next(step for step in steps if step.get("id") == "seal")
        self.assertTrue(observe["continue-on-error"])
        self.assertIn("seal_refresh_attempt.py seal", seal["run"])
        workflow_text = workflow_path.read_text(encoding="utf-8")
        self.assertIn("gh release create", workflow_text)
        self.assertIn("gh release download", workflow_text)
        self.assertIn("cmp \"${{ steps.seal.outputs.manifest }}\"", workflow_text)
        self.assertNotIn("gh release edit", workflow_text)
        self.assertNotIn("gh release delete", workflow_text)


if __name__ == "__main__":
    unittest.main()
