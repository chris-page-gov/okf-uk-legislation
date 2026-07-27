from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

import jsonschema
import rdflib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_semantic_conformance as conformance  # noqa: E402


class SemanticConformanceTests(unittest.TestCase):
    def test_relationship_id_namespaces_preserve_authority_boundaries(
        self,
    ) -> None:
        schema = json.loads(
            (
                ROOT
                / "whole-law"
                / "schemas"
                / "relationship-assertion.schema.json"
            ).read_text(encoding="utf-8")
        )
        validator = jsonschema.Draft202012Validator(schema)
        base = {
            "source": "https://example.test/source",
            "target": "https://example.test/target",
            "predicate": "related to",
            "derivation": "test",
        }
        official = {
            **base,
            "id": f"urn:okf:official-effect:sha256:{'a' * 64}",
            "authority": {"class": "official"},
        }
        historical = {
            **base,
            "id": f"urn:okf:enrichment:sha256:{'b' * 64}",
            "authority": {"class": "model-assisted"},
        }
        paid_model = {
            **base,
            "id": f"urn:okf:model-relationship:{'c' * 64}",
            "acceptance_id": f"urn:okf:model-acceptance:{'d' * 64}",
            "authority": {"class": "model-assisted"},
        }
        validator.validate(official)
        validator.validate(historical)
        validator.validate(paid_model)
        missing_acceptance = dict(paid_model)
        del missing_acceptance["acceptance_id"]
        self.assertTrue(list(validator.iter_errors(missing_acceptance)))
        mismatched_authority = {
            **official,
            "authority": {"class": "derived"},
        }
        self.assertTrue(list(validator.iter_errors(mismatched_authority)))

    def test_receipt_is_explicit_about_rdf_and_json_scope(self) -> None:
        receipt = json.loads(conformance.RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual("passed", receipt["status"])
        self.assertEqual(365_786, receipt["scope"]["catalogued_legal_works"])
        self.assertEqual(0, receipt["scope"]["rdf_materialized_legal_works"])
        self.assertEqual(
            906_754,
            receipt["scope"]["relationship_rows_exhaustively_validated_as_json"],
        )
        self.assertEqual(
            835_563,
            receipt["json_schema"]["totals"]["core_rows"],
        )
        self.assertEqual(
            71_191,
            receipt["json_schema"]["totals"]["provider_rows"],
        )
        self.assertEqual(0, receipt["json_schema"]["totals"]["invalid_rows"])
        self.assertTrue(
            receipt["source_contract"][
                "semantic_values_match_published_register"
            ]
        )
        semantic = receipt["semantic_equivalence"]
        self.assertTrue(semantic["graphs_isomorphic"])
        self.assertTrue(semantic["canonical_serializations_equal"])
        self.assertTrue(semantic["turtle_rdf_round_trip"])
        self.assertEqual(
            [21, 21, 21],
            [
                semantic["yaml_graph_triples"],
                semantic["json_graph_triples"],
                semantic["turtle_graph_triples"],
            ],
        )
        self.assertEqual(
            1,
            len(
                set(
                    semantic[
                        "canonical_digest_by_representation"
                    ].values()
                )
            ),
        )
        self.assertEqual(3, receipt["shacl"]["descriptor_graphs_validated"])
        self.assertEqual(
            {
                "authored_yaml_ld",
                "generated_json_ld",
                "generated_turtle",
            },
            set(receipt["shacl"]["results"]),
        )
        for result in receipt["shacl"]["results"].values():
            self.assertTrue(result["conforms"])
            self.assertEqual(1, result["federation_focus_nodes"])
            self.assertEqual(1, result["source_register_focus_nodes"])
            self.assertEqual([], result["uncovered_explicit_types"])
        for operations in receipt["semantic_equivalence"][
            "json_ld_api_operations"
        ].values():
            self.assertTrue(operations["compaction_non_empty"])
            self.assertTrue(operations["flattening_non_empty"])
            self.assertTrue(operations["framing_non_empty"])
            self.assertTrue(operations["framed_identity_retained"])
        entity_contract = receipt["shacl"]["contract_examples"]
        self.assertTrue(entity_contract["all_named_entity_contracts_non_vacuous"])
        self.assertEqual(
            {
                "case",
                "court",
                "jurisdiction",
                "legal_manifestation",
                "organisation",
                "provision",
                "publication",
                "source_record",
                "temporal_state",
            },
            set(entity_contract["entity_contract_targets"]),
        )
        for target in entity_contract["entity_contract_targets"].values():
            self.assertGreaterEqual(target["example_focus_nodes"], 1)
            self.assertGreaterEqual(target["node_shapes"], 1)
            self.assertGreaterEqual(target["required_property_constraints"], 1)

    def test_active_provider_set_uses_governed_v3_not_historical_v2(
        self,
    ) -> None:
        self.assertEqual(
            {"legislation-effects", "codex-assisted-v3"},
            set(conformance.PROVIDER_MANIFESTS),
        )
        self.assertEqual(
            ROOT / "bundle" / "data" / "enrichment-v3" / "manifest.json",
            conformance.PROVIDER_MANIFESTS["codex-assisted-v3"],
        )
        receipt = json.loads(conformance.RECEIPT.read_text(encoding="utf-8"))
        providers = {
            row["datapack_id"]: row
            for row in receipt["json_schema"]["provider_relationships"]
        }
        self.assertNotIn("codex-assisted-v2", providers)
        self.assertEqual(56_479, providers["codex-assisted-v3"]["rows_validated"])
        self.assertEqual(
            "bundle/data/enrichment-v3/manifest.json",
            providers["codex-assisted-v3"]["manifest"]["path"],
        )

    def test_receipt_material_hashes_are_current(self) -> None:
        receipt = json.loads(conformance.RECEIPT.read_text(encoding="utf-8"))

        def walk(value: object) -> None:
            if isinstance(value, dict):
                if {"path", "bytes", "sha256"} <= set(value):
                    path = ROOT / str(value["path"])
                    body = path.read_bytes()
                    self.assertEqual(value["bytes"], len(body))
                    self.assertEqual(
                        value["sha256"],
                        hashlib.sha256(body).hexdigest(),
                    )
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(receipt["materials"])

    def test_federation_shape_rejects_missing_source_register_link(self) -> None:
        graph = conformance.graph_from_document(conformance.AUTHORED_YAML)
        federation = next(
            graph.subjects(rdflib.RDF.type, conformance.OKFLAW.Federation)
        )
        graph.remove((federation, conformance.OKFLAW.sourceRegister, None))
        shapes = rdflib.Graph()
        shapes.parse(conformance.SHAPES, format="turtle")
        vocabulary = rdflib.Graph()
        vocabulary.parse(conformance.VOCABULARY, format="turtle")
        result, errors = conformance.validate_shacl_graph(
            graph,
            graph_name="missing-source-register-fixture",
            shapes_graph=shapes,
            vocabulary_graph=vocabulary,
        )
        self.assertFalse(result["conforms"])
        self.assertGreater(result["validation_results"], 0)
        self.assertTrue(errors)

    def test_named_entity_contracts_are_non_vacuous_and_fail_closed(self) -> None:
        examples = rdflib.Graph()
        examples.parse(conformance.EXAMPLES, format="json-ld")
        shapes = rdflib.Graph()
        shapes.parse(conformance.SHAPES, format="turtle")
        vocabulary = rdflib.Graph()
        vocabulary.parse(conformance.VOCABULARY, format="turtle")

        required_property = {
            conformance.OKFLAW.LegalManifestation: rdflib.URIRef(
                "http://data.europa.eu/eli/ontology#embodies"
            ),
            conformance.OKFLAW.Provision: rdflib.URIRef(
                "http://purl.org/dc/terms/isPartOf"
            ),
            conformance.OKFLAW.Case: conformance.OKFLAW.decidingCourt,
            conformance.OKFLAW.Court: rdflib.URIRef(
                "https://schema.org/name"
            ),
            conformance.OKFLAW.Organisation: rdflib.URIRef(
                "https://schema.org/name"
            ),
            conformance.OKFLAW.Publication: rdflib.URIRef(
                "http://purl.org/dc/terms/publisher"
            ),
            conformance.OKFLAW.SourceRecord: rdflib.URIRef(
                "http://www.w3.org/ns/dcat#landingPage"
            ),
            conformance.OKFLAW.Jurisdiction: rdflib.URIRef(
                "http://www.w3.org/2004/02/skos/core#prefLabel"
            ),
            conformance.OKFLAW.TemporalState: conformance.OKFLAW.stateType,
        }
        for rdf_type, predicate in required_property.items():
            focus_nodes = set(examples.subjects(rdflib.RDF.type, rdf_type))
            self.assertTrue(focus_nodes, f"no example for {rdf_type}")
            self.assertTrue(
                set(shapes.subjects(conformance.SH.targetClass, rdf_type)),
                f"no shape for {rdf_type}",
            )
            focus = sorted(focus_nodes, key=str)[0]
            fixture = rdflib.Graph()
            for triple in examples:
                fixture.add(triple)
            fixture.remove((focus, predicate, None))
            conforms, report_graph, _ = conformance.shacl_validate(
                fixture,
                shacl_graph=shapes,
                ont_graph=vocabulary,
                inference="rdfs",
                advanced=True,
            )
            self.assertFalse(
                conforms,
                f"{rdf_type} shape accepted missing required {predicate}",
            )
            self.assertTrue(
                set(
                    report_graph.subjects(
                        rdflib.RDF.type, conformance.SH.ValidationResult
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
