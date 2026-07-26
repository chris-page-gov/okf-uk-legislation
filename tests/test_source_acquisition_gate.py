from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "audit_source_acquisition_gate.py"
    spec = importlib.util.spec_from_file_location(
        "audit_source_acquisition_gate",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load source-acquisition gate module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE_MODULE = load_module()


class SourceAcquisitionGateTests(unittest.TestCase):
    def test_gate_receipt_is_current(self) -> None:
        GATE_MODULE.check()

    def test_gate_passes_with_declared_constraints_and_exact_denominators(
        self,
    ) -> None:
        receipt = GATE_MODULE.build_receipt()
        denominators = receipt["exact_denominators"]
        self.assertEqual(
            receipt["gate"]["decision"],
            "passed-with-declared-constraints",
        )
        self.assertEqual(denominators["registered_methods"], 108)
        self.assertEqual(denominators["original_frozen_method_envelopes"], 108)
        self.assertEqual(
            denominators["replacement_frozen_method_envelopes"],
            22,
        )
        self.assertEqual(denominators["total_frozen_method_envelopes"], 130)
        self.assertEqual(denominators["public_intended_get_routes"], 105)
        self.assertEqual(denominators["public_intended_get_reachable"], 101)
        self.assertEqual(
            denominators["public_intended_get_not_reachable"],
            4,
        )
        self.assertEqual(denominators["sources_with_no_reachable_get"], 2)
        self.assertEqual(
            denominators["source_ids_with_no_reachable_get"],
            ["SRC066", "SRC068"],
        )
        self.assertEqual(denominators["source_classes_with_reachable_get"], 36)
        self.assertEqual(
            denominators["source_classes_with_no_reachable_get"],
            [],
        )
        self.assertEqual(
            denominators["effective_replacement_routes_reachable"],
            20,
        )
        self.assertEqual(
            denominators["effective_replacement_routes_not_reachable"],
            0,
        )
        self.assertEqual(
            denominators[
                "source_records_complete_against_official_enumeration"
            ],
            5,
        )
        self.assertEqual(
            denominators[
                "source_records_without_complete_official_enumeration"
            ],
            67,
        )
        self.assertEqual(receipt["blocking_conditions"], [])

    def test_replacements_are_frozen_without_modifying_research_register(
        self,
    ) -> None:
        receipt = GATE_MODULE.build_receipt()
        self.assertTrue(receipt["delta_capture"]["created"])
        self.assertEqual(
            receipt["stale_or_network_routes"]["status"],
            "frozen-20-effective-reachable-with-two-retained-tls-failures",
        )
        self.assertEqual(
            receipt["stale_or_network_routes"]["count"],
            receipt["stale_or_network_routes"]["primary_candidate_count"],
        )
        self.assertEqual(
            receipt["stale_or_network_routes"]["frozen_attempt_count"],
            22,
        )
        self.assertFalse(
            receipt["review_scope"]["immutable_research_register_modified"]
        )

    def test_constraints_are_preserved_and_failures_not_erased(self) -> None:
        receipt = GATE_MODULE.build_receipt()
        self.assertEqual(
            receipt["constraints_preserved"]["base_constraints_preserved_verbatim"],
            217,
        )
        self.assertEqual(receipt["constraints_preserved"]["total"], 239)
        copfs = receipt["stale_or_network_routes"]["copfs_supplement"]
        self.assertEqual(
            copfs["python_strict"]["observed_access_state"],
            "network-error",
        )
        self.assertEqual(
            copfs["system_trust"]["observed_access_state"],
            "reachable",
        )
