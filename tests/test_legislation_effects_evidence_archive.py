from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SNAPSHOT_ID = "legislation-effects-2026-07-25"

import sys

sys.path.insert(0, str(SCRIPTS))

import legislation_effects_evidence_archive as archive  # noqa: E402
import build_legislation_effects as effects_builder  # noqa: E402


ARCHIVE, RECEIPT, PROJECTION = archive.archive_paths(SNAPSHOT_ID)


class LegislationEffectsEvidenceArchiveTests(unittest.TestCase):
    def test_archive_recovers_every_exact_source_file(self) -> None:
        validation, files, projection = archive.validate_archive(SNAPSHOT_ID)
        self.assertTrue(validation["byte_recovery_verified"])
        self.assertTrue(validation["projection_value_safe"])
        self.assertEqual(626, validation["source_file_count"])
        self.assertEqual(38_028_462, validation["source_total_bytes"])
        self.assertEqual(313, validation["capture_count"])
        self.assertEqual(313, projection["capture_count"])
        self.assertEqual(
            "b730b953f3ecd810f8096544b961e32af"
            "615002da597364ef4e4cc5647734e96",
            validation["source_tree_sha256"],
        )
        self.assertEqual(626, len(files))

    def test_archive_bytes_are_reproducible(self) -> None:
        validation, source_files, _ = archive.validate_archive(SNAPSHOT_ID)
        integrity = archive.original_integrity(SNAPSHOT_ID, source_files)
        files = dict(source_files)
        files["integrity.json"] = archive.render_json(integrity).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            rebuilt = Path(directory) / "rebuilt.tar.xz"
            archive.write_deterministic_archive(
                rebuilt,
                SNAPSHOT_ID,
                files,
            )
            self.assertEqual(ARCHIVE.read_bytes(), rebuilt.read_bytes())
            self.assertEqual(
                "3262cb466cf692278567fcc89acdd0c3f"
                "2138b6c07d2e8cc3bff6fa5b75ee631",
                validation["archive_sha256"],
            )

    def test_projection_and_receipt_are_value_safe(self) -> None:
        archive.validate_archive(SNAPSHOT_ID)
        self.assertIsNone(
            archive.PUSH_PROTECTION_SHAPE.search(RECEIPT.read_bytes())
        )
        self.assertIsNone(
            archive.PUSH_PROTECTION_SHAPE.search(PROJECTION.read_bytes())
        )
        receipt = json.loads(RECEIPT.read_text())
        projection = json.loads(PROJECTION.read_text())
        trigger = receipt["publication_trigger"]
        self.assertFalse(trigger["values_recorded_in_receipt_or_projection"])
        self.assertFalse(trigger["values_are_credentials"])
        self.assertFalse(
            projection["publication_policy"]["contains_response_bodies"]
        )
        self.assertFalse(
            projection["publication_policy"]["contains_response_headers"]
        )

    def test_explicit_recovery_preserves_all_digests(self) -> None:
        _, source_files, _ = archive.validate_archive(SNAPSHOT_ID)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            archive.extract_archive(SNAPSHOT_ID, destination)
            recovered = destination / SNAPSHOT_ID
            recovered_files = {
                path.relative_to(recovered).as_posix(): path.read_bytes()
                for path in recovered.rglob("*")
                if path.is_file()
            }
            self.assertEqual(set(source_files), set(recovered_files))
            self.assertEqual(
                {
                    path: archive.sha256_bytes(body)
                    for path, body in source_files.items()
                },
                {
                    path: archive.sha256_bytes(body)
                    for path, body in recovered_files.items()
                },
            )

    def test_capture_validation_rejects_dtd_or_entity_declarations(self) -> None:
        body_path = "ukpga-2026-1/affected/page-001.xml"
        envelope_path = (
            "ukpga-2026-1/affected/page-001.envelope.json"
        )
        body = b"<!DOCTYPE feed [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>"
        envelope = {
            "schema": "okf-source-response-envelope.v1",
            "request": {
                "method": "GET",
                "url": (
                    "https://www.legislation.gov.uk/changes/affected/"
                    "ukpga/2026/1/data.feed"
                ),
            },
            "final_url": (
                "https://www.legislation.gov.uk/changes/affected/"
                "ukpga/2026/1/data.feed"
            ),
            "success": True,
            "body_bytes": len(body),
            "body_sha256": archive.sha256_bytes(body),
        }
        with self.assertRaisesRegex(ValueError, "prohibited XML"):
            archive.validate_capture_tree(
                SNAPSHOT_ID,
                {
                    body_path: body,
                    envelope_path: archive.render_json(envelope).encode(),
                },
            )

    def test_loose_capture_tree_is_ignored_by_git(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text()
        self.assertIn(
            "evidence/source-acquisitions/legislation-effects/"
            "legislation-effects-*/",
            gitignore,
        )

    def test_effects_builder_uses_only_sealed_member_references(self) -> None:
        files, manifest, run = effects_builder.build(allow_fetch=False)
        acquisition = manifest["acquisition"]
        self.assertEqual(
            ARCHIVE.relative_to(ROOT).as_posix(),
            acquisition["evidence_archive"],
        )
        self.assertNotIn("evidence_root", acquisition)
        self.assertEqual(
            RECEIPT.relative_to(ROOT).as_posix(),
            run["evidence_archive_receipt"],
        )
        assertions = json.loads(
            __import__("gzip").decompress(files[Path("assertions.json.gz")])
        )
        self.assertEqual(14_712, len(assertions))
        for row in assertions:
            for evidence in row["evidence"]:
                self.assertEqual(
                    ARCHIVE.relative_to(ROOT).as_posix(),
                    evidence["capture"],
                )
                self.assertTrue(
                    evidence["capture_member"].startswith(
                        f"{SNAPSHOT_ID}/"
                    )
                )


if __name__ == "__main__":
    unittest.main()
