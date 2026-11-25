from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core03_snapshot as snapshot
import build_legislation_okf as base_builder
import build_relationship_semantics as semantics
from build_reader_transport import typed_work


class FrozenCore03InputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        manifest = self.root / "bundle/data/manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"okf_version":"0.2"}')
        self.rows = [{"path": "bundle/data/manifest.json",
                      "bytes": manifest.stat().st_size,
                      "sha256": sha256(manifest.read_bytes()).hexdigest()}]
        self.write_lock()

    def write_lock(self):
        path = self.root / snapshot.LOCK
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": "okf-legislation-core03-frozen-inputs.v1",
            "source_okf_version": "0.2", "source_commit": "a" * 40,
            "files": self.rows}))

    def test_source_version_remains_historical(self):
        result = snapshot.verify_frozen_inputs(self.root)
        self.assertEqual(result["source_manifest"]["okf_version"], "0.2")

    def test_relabelling_the_source_manifest_is_rejected(self):
        (self.root / "bundle/data/manifest.json").write_text('{"okf_version":"0.3"}')
        with self.assertRaisesRegex(ValueError, "Frozen input changed"):
            snapshot.verify_frozen_inputs(self.root)

    def test_escaping_or_duplicated_input_paths_are_rejected(self):
        self.rows.append(dict(self.rows[0]))
        self.write_lock()
        with self.assertRaisesRegex(ValueError, "Unsafe or duplicate"):
            snapshot.verify_frozen_inputs(self.root)
        self.rows[-1]["path"] = "../outside"
        self.write_lock()
        with self.assertRaisesRegex(ValueError, "Unsafe or duplicate"):
            snapshot.verify_frozen_inputs(self.root)

    def test_virtual_work_record_is_an_extension_without_source_mutation(self):
        record = {"name": "ukpga-2010-15",
                  "document_uri": "https://www.legislation.gov.uk/ukpga/2010/15",
                  "structure_url": "https://www.legislation.gov.uk/ukpga/2010/15/data.xml",
                  "legislation_id_uri": "http://www.legislation.gov.uk/id/ukpga/2010/15"}
        before = dict(record)
        self.assertEqual(typed_work(record)["core_role"], "extension")
        self.assertEqual(record, before)


class Core03GraphRoleTests(unittest.TestCase):
    def test_publication_and_release_assurance_pin_the_same_reader(self):
        root = Path(__file__).resolve().parents[1]
        release = json.loads((root / "publication/release.json").read_bytes())
        contract = json.loads((root / "release-assurance/external-finalization-contract.json").read_bytes())
        self.assertEqual("v" + release["explorer_version"], contract["explorer"]["required_tag"])

    def test_only_actual_typed_documents_are_concepts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "topics").mkdir()
            (root / "topics/education.md").write_text('---\ntype: "Topic"\n---\n')
            (root / "topics/index.md").write_text('---\ntype: "Index"\n---\n')
            semantics.core_concept_routes.cache_clear()
            try:
                with patch.object(semantics, "BUNDLE", root):
                    self.assertEqual(semantics.core_role_for_route("topic/education"), "concept")
                    for route in ("topic/index", "topic/absent", "dataset/work", "entity/model-label"):
                        self.assertEqual(semantics.core_role_for_route(route), "extension")
            finally:
                semantics.core_concept_routes.cache_clear()



class Core03ShapeTests(unittest.TestCase):
    def test_all_original_constraints_are_preserved_under_new_shape_identities(self):
        import rdflib
        from rdflib.compare import isomorphic
        root = Path(__file__).resolve().parents[1]
        original_path = root / "whole-law/ontology/shapes.ttl"
        lock = json.loads((root / snapshot.LOCK).read_bytes())
        original = next(row for row in lock["files"] if row["path"] == "whole-law/ontology/shapes.ttl")
        self.assertEqual(sha256(original_path.read_bytes()).hexdigest(), original["sha256"])
        old = rdflib.Graph().parse(original_path, format="turtle")
        new = rdflib.Graph().parse(root / "whole-law/ontology/shapes-core03.ttl", format="turtle")
        before = "https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#"
        after = "https://chris-page-gov.github.io/okf-uk-legislation/whole-law/ontology/shapes-core03.ttl#"
        normalised = rdflib.Graph()
        for subject, predicate, value in new:
            if isinstance(subject, rdflib.URIRef) and str(subject).startswith(after):
                subject = rdflib.URIRef(before + str(subject)[len(after):])
            if isinstance(value, rdflib.URIRef) and str(value).startswith(after):
                value = rdflib.URIRef(before + str(value)[len(after):])
            if predicate == rdflib.SH.hasValue and value == rdflib.Literal("0.3"):
                value = rdflib.Literal("0.2")
            normalised.add((subject, predicate, value))
        self.assertTrue(isomorphic(old, normalised))

    def test_current_shapes_accept_03_and_reject_02_federation(self):
        import rdflib
        import run_semantic_conformance as conformance
        graph = conformance.graph_from_document(conformance.AUTHORED_YAML)
        shapes = rdflib.Graph().parse(conformance.SHAPES, format="turtle")
        vocabulary = rdflib.Graph().parse(conformance.VOCABULARY, format="turtle")
        result, errors = conformance.validate_shacl_graph(
            graph, graph_name="core03-positive", shapes_graph=shapes, vocabulary_graph=vocabulary)
        self.assertTrue(result["conforms"], errors)
        federation = next(graph.subjects(rdflib.RDF.type, conformance.OKFLAW.Federation))
        graph.set((federation, conformance.OKFLAW.okfVersion, rdflib.Literal("0.2")))
        result, errors = conformance.validate_shacl_graph(
            graph, graph_name="core02-negative", shapes_graph=shapes, vocabulary_graph=vocabulary)
        self.assertFalse(result["conforms"])


class FrozenDefaultOutputTests(unittest.TestCase):
    def test_default_snapshot_refuses_before_loading_or_writing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "source/core03-frozen-inputs.json"
            lock.parent.mkdir()
            lock.write_text("{}")
            output = root / "bundle"
            with patch.object(base_builder, "ROOT", root), patch.object(
                base_builder, "DEFAULT_OUTPUT", output
            ), patch.object(base_builder, "load_live_records") as load:
                with self.assertRaises(SystemExit) as error:
                    base_builder.main([])
                self.assertEqual(error.exception.code, 2)
                load.assert_not_called()
                self.assertFalse(output.exists())
