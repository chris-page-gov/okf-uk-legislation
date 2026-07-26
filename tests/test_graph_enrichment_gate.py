from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDITOR = load_module(
    "audit_graph_enrichment_gate",
    ROOT / "scripts/audit_graph_enrichment_gate.py",
)
BUILDER = load_module(
    "build_legislation_okf",
    ROOT / "scripts/build_legislation_okf.py",
)


def receipt() -> dict:
    return json.loads(
        (
            ROOT
            / "whole-law/assurance/graph-enrichment-gate-20260726.json"
        ).read_text(encoding="utf-8")
    )


def checks_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in receipt()["checks"]}


def test_assurance_receipt_is_current_and_passed() -> None:
    expected = AUDITOR.build_receipt()
    assert receipt() == expected
    assert expected["status"] == "passed", expected["blockers"]
    assert all(item["status"] == "passed" for item in expected["checks"])


def test_official_effects_are_non_empty_source_derived_and_reconciled() -> None:
    result = receipt()
    checks = checks_by_id()
    assert result["metrics"]["official_effects"] == 14_712
    assert checks["G05-EFFECTS"]["status"] == "passed"
    assert checks["G05-EFFECTS-EVIDENCE"]["status"] == "passed"
    assert checks["G05-EFFECTS-LIVE"]["status"] == "passed"
    assert checks["G05-EFFECTS"]["evidence"]["authority"] == "official"
    assert checks["G05-EFFECTS"]["evidence"]["schema_failures"] == 0
    assert (
        checks["G05-EFFECTS"]["evidence"][
            "authority_evidence_contract_failures"
        ]
        == 0
    )


def test_enrichment_covers_every_eligible_work_and_excludes_v1() -> None:
    result = receipt()
    checks = checks_by_id()
    assert result["metrics"]["enrichment_attempts"] == 365_786
    assert result["metrics"]["model_assisted_assertions"] == 22_299
    assert checks["G05-ENRICHMENT-ATTEMPTS"]["status"] == "passed"
    assert checks["G05-ENRICHMENT"]["status"] == "passed"
    assert checks["G05-ENRICHMENT"]["evidence"]["v1_contamination"] == 0
    assert (
        checks["G05-ENRICHMENT"]["evidence"]["candidate_review_status"]
        == "pending-independent-audit"
    )
    assert (
        checks["G05-ENRICHMENT"]["evidence"]["independent_audit_status"]
        == "accepted"
    )


def test_zero_cost_claim_is_limited_to_incremental_api_usage() -> None:
    result = receipt()
    check = checks_by_id()["G05-ENRICHMENT-COST"]
    assert check["status"] == "passed"
    assert check["evidence"]["incremental_openai_api_usd"] == 0
    assert check["evidence"]["incremental_openai_api_gbp"] == 0
    assert check["evidence"]["api_calls"] == 0
    assert "subscription usage" in check["evidence"]["boundary"]
    assert "incremental OpenAI API cost only" in result["cost_claim_boundary"]


def test_relationship_dimensions_reconcile_across_all_publications() -> None:
    result = receipt()
    checks = checks_by_id()
    assert result["metrics"]["combined_relationships"] == 872_574
    assert result["metrics"]["composition"]["by_datapack"] == {
        "codex-assisted-v2": 22_299,
        "core": 835_563,
        "legislation-effects": 14_712,
    }
    assert result["metrics"]["composition"]["by_authority"] == {
        "derived": 469_777,
        "model-assisted": 22_299,
        "official": 380_498,
    }
    assert result["metrics"]["composition"]["by_freshness"] == {
        "current": 872_574
    }
    assert checks["G05-COMPOSITION"]["status"] == "passed"
    assert checks["G05-ROOT-SUMMARY"]["status"] == "passed"
    assert checks["G05-FEDERATION-SUMMARY"]["status"] == "passed"


def test_descriptor_entrypoints_and_explorer_receipt_are_digest_bound() -> None:
    checks = checks_by_id()
    assert checks["G05-DESCRIPTORS"]["status"] == "passed"
    assert checks["G05-GRAPH-INDEX"]["status"] == "passed"
    assert checks["G05-EXPLORER"]["status"] == "passed"
    assert checks["G05-EXPLORER"]["evidence"][
        "legislation_descriptor_current"
    ]
    assert checks["G05-EXPLORER"]["evidence"]["whole_law_descriptor_current"]


def test_compact_core_rows_inherit_datapack_snapshot_freshness() -> None:
    rows = BUILDER.summarize_relationship_rows(
        [
            {
                "source": "work/a",
                "target": "topic/a",
                "kind": "classified as",
                "authority": "derived-non-official",
                "confidence": "low",
            }
        ],
        "core",
        default_freshness="current",
    )
    assert rows == [
        {
            "authority": "derived",
            "confidence": "low",
            "count": 1,
            "datapack": "core",
            "freshness": "current",
            "predicate": "classified as",
        }
    ]


def test_p04_01_remains_honestly_scoped() -> None:
    assessment = json.loads(
        (
            ROOT
            / "whole-law/assurance/entity-model-coverage-assessment-20260726.json"
        ).read_text(encoding="utf-8")
    )
    classes = {item["class"]: item for item in assessment["classes"]}
    assert (
        assessment["decision"]["status"]
        == "verified-at-declared-catalogue/schema-grain"
    )
    assert assessment["decision"]["contract_complete"] is True
    assert assessment["decision"]["population_complete"] is False
    assert classes["legal works"]["count"] == 365_786
    assert classes["manifestations"]["count"] == 1_691_403
    assert classes["source records"]["count"] == 72
    assert classes["cases"]["status"] == "not-materialised"
    assert classes["courts"]["status"] == "not-materialised"
    assert "does not claim complete case" in assessment["decision"]["release_claim"]


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    """Expose the module's fail-closed function tests to unittest discovery."""

    del loader, standard_tests, pattern
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite
