from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20260725T203207Z-dd7315c3"
ARCHIVE = (
    ROOT
    / "evidence"
    / "source-acquisitions"
    / "whole-law-access"
    / "archives"
    / f"{RUN_ID}.tar.xz"
)
RECEIPT = (
    ROOT
    / "evidence"
    / "source-acquisitions"
    / "whole-law-access"
    / "archive-receipts"
    / f"{RUN_ID}.json"
)
CURRENT = ROOT / "whole-law" / "acquisition" / "current"


def load_module():
    path = ROOT / "scripts" / "source_access_evidence_archive.py"
    spec = importlib.util.spec_from_file_location(
        "source_access_evidence_archive",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load source-access archive module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARCHIVE_MODULE = load_module()


class SourceAccessEvidenceArchiveTests(unittest.TestCase):
    def test_sealed_archive_recovers_original_run_exactly(self) -> None:
        validation, files = ARCHIVE_MODULE.validate_archive(ARCHIVE, RECEIPT)
        self.assertTrue(validation["byte_recovery_verified"])
        self.assertTrue(validation["compressed_blob_plaintext_check_passed"])
        self.assertEqual(validation["file_count"], 216)
        self.assertEqual(validation["original_integrity_file_count"], 215)
        self.assertEqual(
            validation["original_integrity_total_bytes"],
            3_935_608,
        )
        self.assertEqual(
            validation["flagged_public_payload_sha256"],
            "8c747d807be81240b515dbc0f459f11ff134bee825a024409265342f4fc1488a",
        )
        original_integrity = json.loads(files["integrity.json"])
        body_receipt = next(
            row
            for row in original_integrity["files"]
            if row["path"] == "methods/SRC002-A01/body.bin"
        )
        self.assertEqual(
            body_receipt["sha256"],
            validation["flagged_public_payload_sha256"],
        )

    def test_archive_bytes_are_deterministic(self) -> None:
        validation, files = ARCHIVE_MODULE.validate_archive(ARCHIVE, RECEIPT)
        with tempfile.TemporaryDirectory() as directory:
            rebuilt = Path(directory) / "rebuilt.tar.xz"
            ARCHIVE_MODULE.write_deterministic_archive(
                rebuilt,
                RUN_ID,
                files,
            )
            self.assertEqual(
                ARCHIVE_MODULE.sha256_file(rebuilt),
                validation["archive_sha256"],
            )
            self.assertEqual(rebuilt.read_bytes(), ARCHIVE.read_bytes())

    def test_existing_archive_fails_closed_on_different_bytes(self) -> None:
        _, files = ARCHIVE_MODULE.validate_archive(ARCHIVE, RECEIPT)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sealed.tar.xz"
            target.write_bytes(ARCHIVE.read_bytes())
            changed = dict(files)
            changed["complete.json"] = b"{}\n"
            with self.assertRaises(FileExistsError):
                ARCHIVE_MODULE.write_deterministic_archive(
                    target,
                    RUN_ID,
                    changed,
                )
            self.assertEqual(target.read_bytes(), ARCHIVE.read_bytes())

    def test_explicit_recovery_preserves_every_file_digest(self) -> None:
        _, archived_files = ARCHIVE_MODULE.validate_archive(ARCHIVE, RECEIPT)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            ARCHIVE_MODULE.extract_archive(
                ARCHIVE,
                RECEIPT,
                destination,
            )
            recovered = destination / RUN_ID
            recovered_files = {
                path.relative_to(recovered).as_posix(): path.read_bytes()
                for path in recovered.rglob("*")
                if path.is_file()
            }
            self.assertEqual(set(archived_files), set(recovered_files))
            self.assertEqual(
                {
                    path: ARCHIVE_MODULE.sha256_bytes(body)
                    for path, body in archived_files.items()
                },
                {
                    path: ARCHIVE_MODULE.sha256_bytes(body)
                    for path, body in recovered_files.items()
                },
            )

    def test_publication_projection_has_explicit_lineage(self) -> None:
        reference = json.loads(
            (CURRENT / "evidence-reference.json").read_text()
        )
        projection = json.loads(
            (CURRENT / "publication-projection.json").read_text()
        )
        redactions = json.loads(
            (CURRENT / "publication-redactions.json").read_text()
        )
        receipt = json.loads(RECEIPT.read_text())
        self.assertEqual(
            reference["evidence_archive_sha256"],
            receipt["archive"]["sha256"],
        )
        self.assertEqual(
            reference["original_integrity_sha256"],
            receipt["original_integrity"]["sha256"],
        )
        self.assertEqual(
            projection["source_evidence"]["archive_tree_sha256"],
            receipt["archive"]["tree_sha256"],
        )
        self.assertFalse(projection["immutable_original"])
        self.assertTrue(projection["replaceable"])
        self.assertFalse(
            redactions["assertions"]["immutable_original_mutated"]
        )
        self.assertFalse(
            redactions["assertions"]["projection_is_immutable_original"]
        )
        self.assertTrue(
            redactions["assertions"]["original_recoverable_byte_for_byte"]
        )

    def test_constraint_ledger_records_publication_mitigation(self) -> None:
        ledger = json.loads(
            (CURRENT / "source-constraint-ledger.json").read_text()
        )
        constraint = next(
            row
            for row in ledger["constraints"]
            if row["id"]
            == "CON-SRC002-PUBLICATION-CONTENT-SCANNING"
        )
        self.assertEqual(constraint["escalation_state"], "mitigated")
        self.assertEqual(constraint["kind"], "hosting")
        self.assertEqual(ledger["counts"]["total"], 217)
        self.assertEqual(ledger["counts"]["by_kind"]["hosting"], 1)

    def test_unpacked_run_is_not_the_publication_object(self) -> None:
        unpacked = (
            ROOT
            / "evidence"
            / "source-acquisitions"
            / "whole-law-access"
            / RUN_ID
        )
        self.assertFalse(unpacked.exists())
        self.assertTrue(ARCHIVE.is_file())
        self.assertTrue(RECEIPT.is_file())


if __name__ == "__main__":
    unittest.main()
