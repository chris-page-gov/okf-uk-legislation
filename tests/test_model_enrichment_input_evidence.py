from __future__ import annotations

import ast
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_model_enrichment_input_evidence as evidence  # noqa: E402


RECEIPT_PATH = (
    ROOT
    / "whole-law"
    / "assurance"
    / "model-assisted-input-eligibility-20260726.json"
)
CALIBRATION_PATH = (
    ROOT / "enrichment" / "model-assisted-calibration-manifest-v1.json"
)
EXPECTED_ROOTS = {
    "ordered_identity_chunk_root_sha256": (
        "5d9ff660de3c658a6bf0f63518166988442d092b9194aa746d9b94706e9d45ff"
    ),
    "ordered_identity_sha256": (
        "8c8d65057485e9e0ebf5426964ae7ee0d72a7acaff93da4de2d660ccfd289332"
    ),
    "ordered_input_projection_chunk_root_sha256": (
        "011c4bc4aac1031aa2606b63060f7a191f75a32a52f8cbc6ad3b1b27d420f19a"
    ),
    "ordered_input_projection_sha256": (
        "f68c2130d2019f0958e705afc43a4f358e5da353c6d4e23baf9f9429ed6ef5cf"
    ),
    "source_chunk_root_sha256": (
        "0faf9585e6dc0333107dbe30101c3b710ecc26251e406cb589a5df030bd892fa"
    ),
    "source_input_semantic_sha256": (
        "88774344579e6d18572f981a1fc240a6452311e642fcf42fed95eafdfa5bc341"
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_test_chunk(
    directory: Path,
    decompressed: bytes,
    *,
    relative: str = "data/works-test.json.gz",
    records: int = 1,
) -> tuple[Path, dict[str, object]]:
    path = directory / "works-test.json.gz"
    path.write_bytes(gzip.compress(decompressed, mtime=0))
    body = path.read_bytes()
    return path, {
        "compressed_bytes": len(body),
        "compression": "gzip",
        "path": relative,
        "records": records,
        "sha256": hashlib.sha256(body).hexdigest(),
    }


class ModelEnrichmentInputEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifacts = evidence.build_artifacts()
        cls.receipt = json.loads(
            cls.artifacts[
                Path(
                    "whole-law/assurance/"
                    "model-assisted-input-eligibility-20260726.json"
                )
            ]
        )
        cls.calibration = json.loads(
            cls.artifacts[
                Path(
                    "enrichment/"
                    "model-assisted-calibration-manifest-v1.json"
                )
            ]
        )

    def test_generated_artifacts_are_current(self) -> None:
        self.assertEqual([], evidence.artifact_mismatches(self.artifacts))
        self.assertEqual(
            sha256(evidence.BUILDER_PATH),
            self.receipt["bindings"]["builder"]["sha256"],
        )
        self.assertNotIn("data_manifest", self.receipt["bindings"])
        self.assertNotIn("descriptor", self.receipt["bindings"])
        self.assertEqual(
            "bundle/data/records/manifest.json",
            self.receipt["bindings"]["record_locator_manifest"]["path"],
        )
        self.assertEqual(
            self.artifacts[
                Path(
                    "whole-law/assurance/"
                    "model-assisted-input-eligibility-20260726.json"
                )
            ],
            RECEIPT_PATH.read_bytes(),
        )

    def test_full_denominator_chunks_and_stable_roots(self) -> None:
        scope = self.receipt["scope"]
        self.assertEqual(365_786, scope["works"])
        self.assertEqual(366, scope["source_chunks"])
        self.assertEqual(
            "legislation-work-index-2026-07-11T18:00:00Z",
            scope["source_snapshot"],
        )
        self.assertEqual(EXPECTED_ROOTS, {
            key: self.receipt["roots"][key]
            for key in EXPECTED_ROOTS
        })
        self.assertEqual(366, len(self.receipt["chunks"]))
        self.assertEqual(
            365_786,
            sum(chunk["records"] for chunk in self.receipt["chunks"]),
        )
        self.assertTrue(
            all(check["status"] == "passed" for check in self.receipt["checks"])
        )

    def test_field_coverage_is_exact_and_does_not_inflate_clml(self) -> None:
        coverage = self.receipt["field_coverage"]
        self.assertEqual(
            {
                "missing-or-non-substantive": 0,
                "substantive": 359_107,
                "uri-fallback": 6_679,
            },
            coverage["title"]["counts"],
        )
        self.assertEqual(
            {
                "empty": 244_990,
                "generated-boilerplate": 35_156,
                "non-prose-source-value": 2,
                "substantive-source-note": 85_638,
            },
            coverage["long_title_equivalent"]["counts"],
        )
        self.assertEqual(
            85_640,
            coverage["long_title_equivalent"][
                "non_boilerplate_nonempty"
            ],
        )
        clml = coverage["clml_manifestation"]
        self.assertEqual(137_119, clml[
            "source_advertised_manifestation_total"
        ])
        self.assertEqual(228_667, clml["derived_structure_route_total"])
        self.assertEqual(365_786, clml["recorded_or_derived_route_total"])
        self.assertEqual(0, clml["frozen_body_bound"])
        self.assertIn("Neither is evidence", clml["claim_boundary"])

    def test_priority_and_input_outcomes_partition_every_work(self) -> None:
        eligibility = self.receipt["eligibility"]
        self.assertEqual(
            {
                "candidate-local-semantic-evidence": 359_140,
                "deferred-frozen-clml-required": 6_646,
                "terminal-insufficient-input-evidence": 0,
                "terminal-invalid-input-record": 0,
            },
            eligibility["outcome_counts"],
        )
        strata = {
            row["id"]: row["count"]
            for row in self.receipt["priority_strata"]
        }
        self.assertEqual(
            {
                "P1-fallback-resolve-derived-structure-route": 2_091,
                "P2-fallback-resolve-advertised-clml-route": 4_555,
                "P3-fallback-with-substantive-notes": 33,
                "P4-substantive-title-and-notes": 85_605,
                "P5-substantive-title-without-notes": 273_502,
                "P6-no-semantic-text-and-no-recorded-route": 0,
                "P7-invalid-input-record": 0,
            },
            strata,
        )
        self.assertEqual(365_786, sum(strata.values()))
        self.assertEqual(
            365_786,
            sum(eligibility["outcome_counts"].values()),
        )

    def test_insufficient_evidence_is_explicit_and_fail_closed(self) -> None:
        decision = self.receipt["decision"]
        policy = self.receipt["eligibility"]["insufficiency_policy"]
        self.assertFalse(decision["api_calls_authorized"])
        self.assertFalse(decision["paid_run_authorized"])
        self.assertFalse(decision["secret_access_authorized"])
        self.assertFalse(policy["model_call_permitted"])
        self.assertFalse(policy["assertions_permitted"])
        self.assertFalse(policy["default_classification_permitted"])
        self.assertEqual(
            "terminal-insufficient-input-evidence",
            policy["required_terminal_outcome"],
        )
        vocabulary = {
            row["value"]: row
            for row in self.receipt["eligibility"][
                "input_eligibility_outcome_vocabulary"
            ]
        }
        self.assertTrue(
            vocabulary["terminal-insufficient-input-evidence"]["terminal"]
        )
        self.assertFalse(
            vocabulary["terminal-insufficient-input-evidence"][
                "model_call_permitted_by_this_receipt"
            ]
        )

    def test_generated_notes_boilerplate_is_not_semantic_evidence(self) -> None:
        boilerplate = {
            "id": "https://www.legislation.gov.uk/id/uksi/2026/1",
            "title": "The Example Regulations 2026",
            "notes": (
                "Official United Kingdom Statutory Instrument record for "
                "2026 number 1."
            ),
        }
        self.assertEqual(
            (None, "generated-boilerplate"),
            evidence.notes_evidence(boilerplate),
        )

        real_explanation = {
            **boilerplate,
            "notes": (
                "These Regulations amend the official register and prescribe "
                "new filing duties."
            ),
        }
        self.assertEqual(
            (
                real_explanation["notes"],
                "substantive-source-note",
            ),
            evidence.notes_evidence(real_explanation),
        )

        near_miss = {
            **boilerplate,
            "notes": (
                "Official record-keeping requirements for 2026 number 1 are "
                "amended."
            ),
        }
        self.assertEqual(
            (near_miss["notes"], "substantive-source-note"),
            evidence.notes_evidence(near_miss),
        )
        self.assertEqual(
            (None, "non-prose-source-value"),
            evidence.notes_evidence({**boilerplate, "notes": ". . ."}),
        )

    def test_clml_advertisement_and_derived_route_are_distinct(self) -> None:
        advertised_url = (
            "https://www.legislation.gov.uk/uksi/2026/1/made/data.xml"
        )
        advertised = evidence.clml_route({
            "manifestations": {"clml": advertised_url},
            "structure_url": advertised_url,
        })
        self.assertEqual(
            "source-advertised-official-https-route-unfrozen",
            advertised["state"],
        )
        self.assertEqual(
            "source-advertised-manifestation",
            advertised["route_origin"],
        )

        derived = evidence.clml_route({
            "manifestations": {},
            "structure_url": advertised_url,
        })
        self.assertEqual(
            "derived-structure-route-unverified-unfrozen",
            derived["state"],
        )
        self.assertEqual(
            "deterministically-derived-structure-route",
            derived["route_origin"],
        )
        self.assertIsNone(derived["advertised_route"])

    def test_title_and_terminal_classification_adversarial_cases(self) -> None:
        uri_record = {
            "id": "https://www.legislation.gov.uk/id/uksi/2026/1",
            "title": "https://www.legislation.gov.uk/id/uksi/2026/1",
            "notes": "",
            "manifestations": {},
            "structure_url": (
                "https://www.legislation.gov.uk/uksi/2026/1/made/data.xml"
            ),
        }
        self.assertEqual("uri-fallback", evidence.title_kind(uri_record))
        self.assertEqual(
            (
                "deferred-frozen-clml-required",
                "P1-fallback-resolve-derived-structure-route",
            ),
            evidence.classify_input(uri_record, identity_valid=True),
        )

        insufficient = {
            **uri_record,
            "manifestations": {},
            "structure_url": "",
        }
        self.assertEqual(
            (
                "terminal-insufficient-input-evidence",
                "P6-no-semantic-text-and-no-recorded-route",
            ),
            evidence.classify_input(insufficient, identity_valid=True),
        )
        self.assertEqual(
            (
                "terminal-invalid-input-record",
                "P7-invalid-input-record",
            ),
            evidence.classify_input(uri_record, identity_valid=False),
        )

    def test_calibration_manifest_is_fixed_and_content_addressed(self) -> None:
        calibration = self.calibration
        self.assertEqual(58, calibration["counts"]["cases"])
        self.assertEqual(55, calibration["counts"]["rule_tests"])
        self.assertEqual(
            evidence.EXPECTED_HISTORICAL_CALIBRATION_SHA256,
            calibration["source"]["sha256"],
        )
        self.assertEqual(
            evidence.EXPECTED_HISTORICAL_CALIBRATION_SHA256,
            sha256(evidence.HISTORICAL_CALIBRATION_PATH),
        )
        case_ids = [row["case_id"] for row in calibration["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for row in calibration["cases"]:
            payload = {
                "audit_family": row["audit_family"],
                "case_kind": row["case_kind"],
                "expected_topics": row["expected_topics"],
                "title": row["title"],
            }
            semantic_hash = evidence.sha256_bytes(
                evidence.canonical_json_bytes(payload)
            )
            self.assertEqual(semantic_hash, row["canonical_sha256"])
            self.assertEqual(
                f"urn:okf:calibration:sha256:{semantic_hash}",
                row["case_id"],
            )
        self.assertEqual(
            "faba4ac858464f4bb1d86caa4ab7fc74015c1236493ba25e43f9f9858774f315",
            calibration["suite_roots"]["case_set_sha256"],
        )
        self.assertEqual(
            "d34a63f21267aeefef6bd6ddc19c57239e494e5205819ee17f89f8273f39849a",
            sha256(CALIBRATION_PATH),
        )

    def test_builder_has_no_network_process_or_secret_surface(self) -> None:
        source = evidence.BUILDER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: set[str] = set()
        attribute_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Attribute):
                attribute_names.add(node.attr)
        self.assertTrue(
            {
                "openai",
                "requests",
                "httpx",
                "urllib.request",
                "socket",
                "subprocess",
                "keyring",
                "dotenv",
            }.isdisjoint(imports)
        )
        self.assertTrue(
            {"environ", "getenv", "popen", "run", "Popen"}.isdisjoint(
                attribute_names
            )
        )
        self.assertNotIn("OPENAI_API_KEY", source)
        self.assertNotIn("enrich_legislation_semantics", source)

    def test_work_chunk_locator_is_verified_before_decompression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json.gz"
            path.write_bytes(b"not a gzip stream")
            relative = "data/invalid.json.gz"
            locator = {
                "compressed_bytes": path.stat().st_size,
                "compression": "gzip",
                "path": relative,
                "records": 1,
                "sha256": "0" * 64,
            }
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "sha256 mismatch",
            ):
                evidence.load_verified_work_chunk(
                    path,
                    relative,
                    locator,
                )
            locator["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "invalid gzip",
            ):
                evidence.load_verified_work_chunk(
                    path,
                    relative,
                    locator,
                )

    def test_work_chunk_reader_rejects_size_bombs_records_and_trailing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)

            path, locator = write_test_chunk(
                directory,
                b'[{"id":"one"}]\n',
            )
            rows, observed_sha, observed_size = (
                evidence.load_verified_work_chunk(
                    path,
                    str(locator["path"]),
                    locator,
                )
            )
            self.assertEqual([{"id": "one"}], rows)
            self.assertEqual(locator["sha256"], observed_sha)
            self.assertEqual(locator["compressed_bytes"], observed_size)

            wrong_size = dict(locator)
            wrong_size["compressed_bytes"] = int(
                wrong_size["compressed_bytes"]
            ) + 1
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "compressed_bytes mismatch",
            ):
                evidence.load_verified_work_chunk(
                    path,
                    str(locator["path"]),
                    wrong_size,
                )

            mismatch_locator = dict(locator)
            mismatch_locator["records"] = 2
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "records mismatch",
            ):
                evidence.load_verified_work_chunk(
                    path,
                    str(locator["path"]),
                    mismatch_locator,
                    max_records=2,
                )

            bomb_path, bomb_locator = write_test_chunk(
                directory,
                b"[" + (b" " * 256) + b"]\n",
            )
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "decompressed bound",
            ):
                evidence.load_verified_work_chunk(
                    bomb_path,
                    str(bomb_locator["path"]),
                    bomb_locator,
                    max_decompressed_bytes=32,
                )

            excess_path, excess_locator = write_test_chunk(
                directory,
                b'[{"id":"one"},{"id":"two"}]\n',
                records=1,
            )
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "record bound",
            ):
                evidence.load_verified_work_chunk(
                    excess_path,
                    str(excess_locator["path"]),
                    excess_locator,
                    max_records=1,
                )

            trailing_path, trailing_locator = write_test_chunk(
                directory,
                b'[{"id":"one"}]\ntrailing',
            )
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "trailing JSON",
            ):
                evidence.load_verified_work_chunk(
                    trailing_path,
                    str(trailing_locator["path"]),
                    trailing_locator,
                )

            member_path, member_locator = write_test_chunk(
                directory,
                b'[{"id":"one"}]\n',
            )
            member_path.write_bytes(
                member_path.read_bytes() + gzip.compress(b"", mtime=0)
            )
            member_body = member_path.read_bytes()
            member_locator["compressed_bytes"] = len(member_body)
            member_locator["sha256"] = hashlib.sha256(member_body).hexdigest()
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "trailing gzip member|trailing compressed bytes",
            ):
                evidence.load_verified_work_chunk(
                    member_path,
                    str(member_locator["path"]),
                    member_locator,
                )

    def test_checker_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, body in self.artifacts.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            self.assertEqual(
                [],
                evidence.artifact_mismatches(self.artifacts, root),
            )
            tampered = (
                root
                / "whole-law"
                / "assurance"
                / "model-assisted-input-eligibility-20260726.md"
            )
            tampered.write_text("tampered\n", encoding="utf-8")
            self.assertEqual(
                [
                    "out of date: whole-law/assurance/"
                    "model-assisted-input-eligibility-20260726.md"
                ],
                evidence.artifact_mismatches(self.artifacts, root),
            )


if __name__ == "__main__":
    unittest.main()
