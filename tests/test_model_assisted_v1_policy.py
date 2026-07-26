from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_legislation_okf as legislation  # noqa: E402


class LegacyModelAssistedV1PolicyTests(unittest.TestCase):
    fixture = ROOT / "tests" / "fixtures" / "legislation_okf" / "sample.feed.xml"
    rule_path = ROOT / "enrichment" / "model-assisted-v1.json"
    audit_path = (
        ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
    )

    def test_historical_api_prototype_is_quarantined_from_automation(self) -> None:
        script = "scripts/enrich_legislation_semantics.py"
        agreement = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(f"Do not run `{script}`", agreement)
        automated_surfaces = [
            ROOT / ".github" / "workflows" / "ci.yml",
            ROOT / ".github" / "workflows" / "pages.yml",
            ROOT / ".github" / "workflows" / "drift.yml",
            ROOT / "release-assurance" / "reproduction-profile.json",
            ROOT / "scripts" / "validate_publication.sh",
        ]
        for path in automated_surfaces:
            self.assertNotIn(
                script,
                path.read_text(encoding="utf-8"),
                f"historical API prototype escaped quarantine in {path}",
            )

    def test_original_rule_artifact_is_preserved_and_hash_bound(self) -> None:
        audit = json.loads(self.audit_path.read_text(encoding="utf-8"))
        self.assertEqual(
            "819030b842a6eedd88ddec35ac526c718689c7cd1a4577a9c64ef802a879d4dc",
            hashlib.sha256(self.rule_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            hashlib.sha256(self.rule_path.read_bytes()).hexdigest(),
            audit["subject"]["sha256"],
        )
        self.assertEqual("governed-accepted", audit["subject"]["claimed_review_status"])
        self.assertEqual("rejected-fail-closed", audit["decision"]["verdict"])
        self.assertFalse(audit["decision"]["release_gate_passed"])
        self.assertLess(
            audit["precision_assessment"]["precision_ceiling"],
            audit["precision_assessment"]["threshold"],
        )
        self.assertEqual(18_697, audit["affected_outputs"]["total_v1_assertions_rejected"])
        self.assertTrue(audit["affected_outputs"]["audited_v2_unchanged"])

    def test_self_label_or_missing_audit_cannot_activate_rules(self) -> None:
        applied, status = legislation.model_enrichment_disposition(
            {"review_status": "governed-accepted"},
            {},
        )
        self.assertFalse(applied)
        self.assertEqual("rejected-unbound-independent-audit", status)

    def test_rejected_rules_emit_no_entities_or_model_topics(self) -> None:
        self.assertFalse(legislation.MODEL_ENRICHMENT_APPLIED)
        self.assertEqual(
            "rejected-fail-closed",
            legislation.MODEL_ENRICHMENT_DISPOSITION,
        )
        self.assertEqual(
            [],
            legislation.entities_for(
                "The Council Tax and The Public Service Pensions Regulations"
            ),
        )
        topics, assisted = legislation.topics_with_provenance(
            "The Building Society Insolvency Regulations",
            "uksi",
        )
        self.assertEqual([], assisted)
        self.assertNotIn(
            "Companies, insolvency and financial services",
            topics,
        )

    def test_fixture_core_and_publication_exclude_rejected_v1(self) -> None:
        rows, source_meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(
            rows,
            source_meta,
            "2026-07-10T00:00:00Z",
        )
        self.assertFalse(
            any(
                row["kind"] == "mentions entity"
                or row["evidence_type"].startswith("model-assisted")
                for row in corpus["relationships"]
            )
        )
        extension = corpus["descriptor"]["extensions"][
            "okf-model-enrichment.v1-historical"
        ]
        self.assertFalse(extension["applied"])
        self.assertEqual(0, extension["governed_assertions"])
        files = legislation.output_files(corpus, source_meta)
        self.assertIn(
            Path("enrichment/model-assisted-v1-independent-audit.json"),
            files,
        )
        self.assertIn(
            Path("enrichment/model-assisted-v1-independent-audit.md"),
            files,
        )

    def test_offline_rebuild_rederives_and_removes_stale_semantics(self) -> None:
        rows, source_meta = legislation.load_fixture(self.fixture)
        stale = dict(rows[0])
        stale["semantic_entities"] = ["The Public Service"]
        stale["topics"] = [
            *stale["topics"],
            "Companies, insolvency and financial services",
        ]
        stale["semantic_enrichment"] = {
            "model_assisted_topics": [
                "Companies, insolvency and financial services"
            ],
            "model_rules_applied": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "data").mkdir()
            (output / "data" / "manifest.json").write_text(
                json.dumps(
                    {"chunks": {"datasets": ["data/works-0.json.gz"]}}
                ),
                encoding="utf-8",
            )
            (output / "data" / "works-0.json.gz").write_bytes(
                legislation.gzip_json([stale])
            )
            (output / "data" / "source-provenance.json").write_text(
                json.dumps(source_meta),
                encoding="utf-8",
            )
            rebuilt, rebuilt_meta = legislation.load_existing_records(output)
        self.assertEqual(source_meta, rebuilt_meta)
        self.assertEqual([], rebuilt[0]["semantic_entities"])
        self.assertEqual(
            [],
            rebuilt[0]["semantic_enrichment"]["model_assisted_topics"],
        )
        self.assertFalse(
            rebuilt[0]["semantic_enrichment"]["model_rules_applied"]
        )
        self.assertEqual(
            "rejected-fail-closed",
            rebuilt[0]["semantic_enrichment"]["review_status"],
        )


if __name__ == "__main__":
    unittest.main()
