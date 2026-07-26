from __future__ import annotations

import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_legislation_okf as legislation  # noqa: E402
import check_legislation_okf as checker  # noqa: E402


class LegislationOkfTests(unittest.TestCase):
    fixture = ROOT / "tests" / "fixtures" / "legislation_okf" / "sample.feed.xml"

    def governed_v3_fixture(self, root: Path) -> tuple[Path, Path]:
        accepted_directory = (
            root
            / "bundle"
            / "enrichment"
            / "codex-assisted-v3"
            / "accepted-assertions"
        )
        accepted_directory.mkdir(parents=True)
        reviewer_path = (
            root
            / "enrichment"
            / "codex-assisted-v3"
            / "reviewer-task-receipt.json"
        )
        reviewer_path.parent.mkdir(parents=True)
        reviewer = {
            "status": "accepted",
            "verdict": "accepted",
            "source_edits_made_by_reviewer": False,
            "review_task_id": "review-task-fixture",
        }
        reviewer_path.write_text(json.dumps(reviewer), encoding="utf-8")
        audit_relative = (
            "whole-law/assurance/"
            "enrichment-v3-independent-audit-20260726.json"
        )
        dimensions = [
            ("topic", "classified as"),
            ("concept", "has discovery concept"),
            ("concept", "has discovery concept"),
            ("entity", "mentions entity"),
        ]
        profiles = [
            ("title-only", ("title",)),
            ("notes-only", ("notes",)),
            ("multi-field", ("title", "notes")),
            ("title-only", ("title",)),
        ]

        def evidence_item(
            *,
            source: str,
            field: str,
            rule_id: str,
            index: int,
        ) -> dict[str, str]:
            if field == "title":
                source_value = f"Fixture Title Match {index} Act"
                value = "Title Match"
                provenance = "official-source-record-work-title"
            else:
                source_value = (
                    f"Substantive Fixture Notes Match {index} provision"
                )
                value = "Notes Match"
                provenance = (
                    "official-source-record-explanatory-note-or-"
                    "long-title-equivalent"
                )
            canonical = json.dumps(
                source_value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            return {
                "url": source,
                "type": f"literal-{field}-match",
                "source_field": field,
                "field_provenance": provenance,
                "source_value": source_value,
                "source_value_sha256": hashlib.sha256(
                    canonical
                ).hexdigest(),
                "source_value_hash_canonicalization": "canonical-json-utf8",
                "normalization": "Unicode-NFC-and-whitespace-collapse",
                "value": value,
                "literal_sha256": hashlib.sha256(
                    value.encode("utf-8")
                ).hexdigest(),
                "rule_id": rule_id,
                "rationale": "Fixture literal evidence.",
            }

        rows = []
        for index, ((dimension, predicate), (profile, fields)) in enumerate(
            zip(dimensions, profiles, strict=True)
        ):
            source = f"https://www.legislation.gov.uk/fixture/{index}"
            rule_id = f"fixture-rule-{index}"
            rows.append({
                "schema": "okf-relationship-assertion.v2",
                "id": (
                    "urn:okf:enrichment:sha256:"
                    f"{hashlib.sha256(f'candidate-{index}'.encode()).hexdigest()}"
                ),
                "acceptance_id": (
                    "urn:okf:model-acceptance:"
                    f"{hashlib.sha256(f'acceptance-{index}'.encode()).hexdigest()}"
                ),
                "source": source,
                "target": f"urn:okf:fixture-target:{index}",
                "dimension": dimension,
                "predicate": predicate,
                "rule_id": rule_id,
                "rule_label": "Fixture rule",
                "derivation": (
                    "codex-authored-deterministic-literal-rule-v3"
                ),
                "confidence": 0.95,
                "evidence": [
                    evidence_item(
                        source=source,
                        field=field,
                        rule_id=rule_id,
                        index=index,
                    )
                    for field in fields
                ],
                "support_profile": profile,
                "generated_at": "2026-07-26T12:00:00Z",
                "observed_at": "2026-07-26T12:00:00Z",
                "stale_after": "2026-10-26T00:00:00Z",
                "freshness": "current",
                "review_status": "accepted-independent-review",
                "official_legal_classification": False,
                "authority": {"class": "model-assisted"},
                "rights": {
                    "source": legislation.OGL,
                    "assertion": "derived discovery metadata",
                },
                "review": {
                    "audit_id": "v3-audit-fixture",
                    "audit_path": audit_relative,
                    "verdict_id": f"fixture-verdict-{index}",
                    "review_task_id": "review-task-fixture",
                },
                "verified": [
                    {"by": "process:fixture-reconstruction"},
                    {"by": "process:fixture-semantic-review"},
                ],
            })
        chunk_path = accepted_directory / "assertions-000.json.gz"
        chunk_body = gzip.compress(
            json.dumps(rows).encode("utf-8"),
            mtime=0,
        )
        chunk_path.write_bytes(chunk_body)
        accepted_path = (
            root
            / "bundle"
            / "enrichment"
            / "codex-assisted-v3"
            / "accepted-manifest.json"
        )
        accepted = {
            "schema": "okf-enrichment-accepted-assertion-manifest.v3",
            "id": "fixture-v3-accepted",
            "audit_id": "v3-audit-fixture",
            "generated_at": "2026-07-26T12:00:00Z",
            "snapshot_id": "fixture-2026-07-26T12:00:00Z",
            "review_materials_sha256": "a" * 64,
            "counts": {
                "assertions": len(rows),
                "by_kind": {"topic": 1, "concept": 2, "entity": 1},
                "by_support": {
                    "title-only": 2,
                    "notes-only": 1,
                    "metadata-only": 0,
                    "multi-field": 1,
                },
            },
            "authority": "derived-model-assisted-discovery-metadata",
            "official_legal_classification": False,
            "chunks": [
                {
                    "path": (
                        "bundle/enrichment/codex-assisted-v3/"
                        "accepted-assertions/assertions-000.json.gz"
                    ),
                    "sha256": hashlib.sha256(chunk_body).hexdigest(),
                    "bytes": len(chunk_body),
                    "records": len(rows),
                    "media_type": "application/json",
                    "compression": "gzip",
                }
            ],
        }
        accepted_path.write_text(json.dumps(accepted), encoding="utf-8")
        run_path = accepted_path.with_name("run.json")
        coverage_path = accepted_path.with_name("coverage.json")
        run_path.write_text(
            json.dumps({"schema": "okf-model-enrichment-run.v3"}),
            encoding="utf-8",
        )
        coverage_path.write_text(
            json.dumps({"schema": "okf-model-enrichment-coverage.v3"}),
            encoding="utf-8",
        )
        for relative in (
            legislation.MODEL_ENRICHMENT_V3_AUDIT_MATERIAL_PATHS.values()
        ):
            path = root / relative
            if path.exists():
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".json":
                path.write_text("{}\n", encoding="utf-8")
            else:
                path.write_text("fixture governed material\n", encoding="utf-8")

        def binding(path: Path) -> dict[str, object]:
            body = path.read_bytes()
            return {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }

        audit_path = root / audit_relative
        audit_path.parent.mkdir(parents=True)
        audit = {
            "schema": "okf-enrichment-independent-audit.v3",
            "audit_id": "v3-audit-fixture",
            "artifact_state": "hash-bound-accepted",
            "materials": {
                name: binding(root / relative)
                for name, relative in (
                    legislation
                    .MODEL_ENRICHMENT_V3_AUDIT_MATERIAL_PATHS
                    .items()
                )
            },
            "counts": {
                "accepted_assertions": len(rows),
                "accepted_by_kind": accepted["counts"]["by_kind"],
                "accepted_by_support": accepted["counts"]["by_support"],
            },
            "checks": [{"id": "fixture", "status": "passed"}],
            "decision": {
                "release_gate_passed": True,
                "independent_review_status": "accepted",
                "accepted_assertions": len(rows),
                "accepted_by_kind": accepted["counts"]["by_kind"],
                "errors": [],
            },
        }
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        return reviewer_path, accepted_path

    def test_from_existing_preserves_timestamp_and_every_base_byte(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            generated_at = "2026-07-10T00:00:00Z"
            self.assertEqual(
                0,
                legislation.main(
                    [
                        "--fixture",
                        str(self.fixture),
                        "--output",
                        str(output),
                        "--generated-at",
                        generated_at,
                    ]
                ),
            )
            before = {
                path.relative_to(output): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(
                0,
                legislation.main(
                    [
                        "--from-existing",
                        "--output",
                        str(output),
                    ]
                ),
            )
            after = {
                path.relative_to(output): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            descriptor = json.loads(
                (output / "okf-explorer.json").read_text(encoding="utf-8")
            )
            self.assertEqual(generated_at, descriptor["generated_at"])

    def test_from_existing_preserves_files_owned_by_other_builders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            self.assertEqual(
                0,
                legislation.main(
                    [
                        "--fixture",
                        str(self.fixture),
                        "--output",
                        str(output),
                        "--generated-at",
                        "2026-07-10T00:00:00Z",
                    ]
                ),
            )
            provider = output / "whole-law" / "provider-owned.json"
            provider.parent.mkdir(parents=True)
            provider.write_text("provider-owned\n", encoding="utf-8")

            self.assertEqual(
                0,
                legislation.main(
                    [
                        "--from-existing",
                        "--output",
                        str(output),
                    ]
                ),
            )

            self.assertEqual(
                "provider-owned\n",
                provider.read_text(encoding="utf-8"),
            )

    def test_fixture_maps_to_eli_and_schema_org(self) -> None:
        rows, _ = legislation.load_fixture(self.fixture)
        self.assertEqual(2, len(rows))
        act = rows[0]
        self.assertEqual("eli:LegalResource", act["eli_class"])
        self.assertEqual("schema:Legislation", act["schema_org_type"])
        self.assertEqual("ukpga", act["type_code"])
        self.assertEqual("primary", act["category"])
        self.assertEqual("https://www.legislation.gov.uk/ukpga/2025/18/data.xml", act["structure_url"])
        self.assertIn("Communications, data and technology", act["topics"])

    def test_fixture_build_has_progressive_discovery_contract(self) -> None:
        rows, meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(rows, meta, "2026-07-10T00:00:00Z")
        extension = corpus["descriptor"]["extensions"]["okf-legislation-corpus.v1"]
        self.assertEqual("complete-work-index-live-subdivision-resolver", extension["mode"])
        self.assertEqual(2, corpus["manifest"]["counts"]["works"])
        self.assertIn("document_type", corpus["facets"])
        self.assertIn("topic", corpus["facets"])
        self.assertGreater(corpus["manifest"]["counts"]["relationships"], 0)
        self.assertEqual("fnv1a32-prefix-2", corpus["relationship_adjacency"]["algorithm"])
        self.assertIn("relationship_adjacency", corpus["descriptor"]["entrypoints"])

    def test_fixture_generator_output_is_self_consistent(self) -> None:
        rows, meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(rows, meta, "2026-07-10T00:00:00Z")
        files = legislation.output_files(corpus, meta)
        self.assertIn(Path("okf-explorer.json"), files)
        self.assertIn(Path("okf-bundle.yamlld"), files)
        self.assertIn(Path("okf-bundle.jsonld"), files)
        self.assertIn(Path("data/adjacency/manifest.json"), files)
        self.assertIn(Path("data/presentation.json"), files)
        self.assertIn(Path("data/records/manifest.json"), files)
        self.assertIn(Path("data/search/shards.json"), files)
        self.assertIn(Path("data/relationship-composition.json"), files)
        self.assertIn(Path("enrichment/model-assisted-v1.json"), files)
        self.assertIn(
            Path("enrichment/model-assisted-paid-governance-v1.json"),
            files,
        )
        self.assertIn(
            Path("enrichment/model-assisted-calibration-manifest-v1.json"),
            files,
        )
        self.assertIn(Path("ontology/normalized-vocabulary.md"), files)
        self.assertIn(Path("access/search-lists-feeds.md"), files)
        descriptor = json.loads(files[Path("okf-explorer.json")])
        self.assertEqual("okf-large-corpus", descriptor["kind"])
        self.assertEqual("0.2", descriptor["okf_version"])
        self.assertEqual("0.2", corpus["manifest"]["okf_version"])
        self.assertTrue(files[Path("index.md")].startswith('---\nokf_version: "0.2"\n---'))
        self.assertFalse(files[Path("ontology/index.md")].startswith("---"))
        self.assertTrue(files[Path("log.md")].startswith("# Legislation OKF generation log\n\n## 2026-07-10"))
        concept = files[Path("ontology/normalized-vocabulary.md")]
        self.assertIn('generated: {"by": "process:legislation-okf-builder", "at": "2026-07-10T00:00:00Z"}', concept)
        self.assertIn('sources: [{"id": "official-source"', concept)
        self.assertIn('status: "draft"', concept)
        self.assertNotIn("\ntimestamp:", concept)
        self.assertNotIn("\nverified:", concept)
        evaluation = files[Path("evaluation/README.md")]
        self.assertIn('type: "Evaluation Reference"', evaluation)
        self.assertIn('"id": "repository-source"', evaluation)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            legislation.large_corpus.write_files(output, files)
            self.assertEqual([], legislation.large_corpus.check_files(output, files))

    def test_v2_search_is_bounded_complete_and_deterministic(self) -> None:
        rows, _ = legislation.load_fixture(self.fixture)
        missing = dict(rows[0])
        missing["jurisdiction"] = []
        records = [missing, rows[1]]
        first = legislation.build_legislation_search(records, "fixture-snapshot")
        second = legislation.build_legislation_search(records, "fixture-snapshot")
        first_files = legislation.search_publication_files(
            first,
            "fixture-snapshot",
        )
        second_files = legislation.search_publication_files(
            second,
            "fixture-snapshot",
        )
        self.assertEqual(first_files, second_files)
        manifest = first["manifest"]
        self.assertEqual("okf-static-search.v2", manifest["schema"])
        self.assertEqual(
            set(legislation.SEARCH_FILTER_FIELDS),
            set(manifest["entrypoints"]["filter_postings"]),
        )
        self.assertEqual(
            "data/search/sort-values.json.gz",
            manifest["entrypoints"]["sort_values"],
        )
        jurisdiction_path = Path(
            manifest["entrypoints"]["filter_postings"]["jurisdiction"]
        )
        jurisdiction = json.loads(gzip.decompress(first_files[jurisdiction_path]))
        self.assertEqual([0], jurisdiction["values"][legislation.MISSING_FILTER_VALUE])
        shard_document = json.loads(first_files[Path("data/search/shards.json")])
        for group in shard_document["shards"].values():
            for row in group:
                body = first_files[Path(row["path"])]
                self.assertEqual(
                    row["sha256"],
                    hashlib.sha256(body).hexdigest(),
                )
                if row["compression"] == "gzip":
                    json.loads(gzip.decompress(body))

    def test_record_locator_resolves_routes_and_binds_work_chunks(self) -> None:
        rows, meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(rows, meta, "2026-07-10T00:00:00Z")
        files = legislation.output_files(corpus, meta)
        locator = json.loads(files[Path("data/records/manifest.json")])
        self.assertEqual("fnv1a32-prefix-2", locator["algorithm"])
        self.assertEqual(len(rows), locator["records"])
        self.assertEqual(len(corpus["record_chunks"]), len(locator["record_chunks"]))
        for row in locator["record_chunks"]:
            body = files[Path(row["path"])]
            self.assertEqual(row["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(row["compressed_bytes"], len(body))
        for ordinal, record in enumerate(rows):
            route = record["route"]
            bucket = legislation.large_corpus.relationship_bucket(route)
            bucket_row = locator["buckets"][bucket]
            bucket_body = files[Path(bucket_row["path"])]
            self.assertEqual(
                bucket_row["sha256"],
                hashlib.sha256(bucket_body).hexdigest(),
            )
            routes = json.loads(gzip.decompress(bucket_body))
            chunk, offset = routes[route]
            self.assertEqual(ordinal, chunk * locator["chunk_size"] + offset)

    def test_discovery_route_collision_uses_a_declared_stable_alias(self) -> None:
        rows, _ = legislation.load_fixture(self.fixture)
        first = dict(rows[0])
        second = dict(rows[0])
        second["id"] = f"{first['id']}?case-distinct-source-id"
        second["legislation_id_uri"] = second["id"]
        original = [first, second]
        discovery, aliases, collisions = (
            legislation.disambiguate_discovery_routes(original)
        )
        self.assertEqual(first["route"], discovery[0]["route"])
        self.assertNotEqual(first["route"], discovery[1]["route"])
        self.assertEqual(
            first["route"],
            aliases[discovery[1]["route"]],
        )
        self.assertEqual([0, 1], collisions[0]["ordinals"])
        again, again_aliases, again_collisions = (
            legislation.disambiguate_discovery_routes(original)
        )
        self.assertEqual(discovery, again)
        self.assertEqual(aliases, again_aliases)
        self.assertEqual(collisions, again_collisions)
        chunks = [(Path("data/works-0.json.gz"), original)]
        locator = legislation.build_record_locator(
            discovery,
            chunks,
            "fixture-snapshot",
        )
        locator["manifest"]["route_aliases"] = aliases
        files = legislation.record_locator_publication_files(locator)
        alias = discovery[1]["route"]
        bucket = legislation.large_corpus.relationship_bucket(alias)
        payload = json.loads(
            gzip.decompress(
                files[Path(locator["manifest"]["buckets"][bucket]["path"])]
            )
        )
        self.assertEqual([0, 1], payload[alias])

    def test_relationship_composition_reconciles_every_dimension(self) -> None:
        self.assertEqual(
            (
                ("effects", "legislation-effects"),
                ("enrichment-v3", "codex-assisted-v3"),
            ),
            checker.ACTIVE_RELATIONSHIP_PROVIDER_MANIFESTS,
        )
        rows, meta = legislation.load_fixture(self.fixture)
        corpus = legislation.build_corpus(rows, meta, "2026-07-10T00:00:00Z")
        composition = corpus["relationship_composition"]
        self.assertGreater(composition["total"], 0)
        for dimension in (
            "by_datapack",
            "by_predicate",
            "by_authority",
            "by_confidence",
            "by_freshness",
        ):
            self.assertEqual(
                composition["total"],
                sum(composition[dimension].values()),
            )
        self.assertEqual(
            composition["total"],
            sum(row["count"] for row in composition["breakdown"]),
        )

    def test_v3_graph_input_is_only_hash_bound_accepted_assertions(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            self.governed_v3_fixture(root)
            governed = legislation.load_governed_model_enrichment_v3(root)
            self.assertEqual(4, governed["counts"]["assertions"])
            self.assertEqual(
                {"topic": 1, "concept": 2, "entity": 1},
                governed["counts"]["by_kind"],
            )
            self.assertEqual(
                {
                    "title-only": 2,
                    "notes-only": 1,
                    "metadata-only": 0,
                    "multi-field": 1,
                },
                governed["counts"]["by_support"],
            )
            self.assertEqual(
                ["title", "notes"],
                [
                    item["source_field"]
                    for item in governed["rows"][2]["evidence"]
                ],
            )
            self.assertEqual(
                "multi-field",
                governed["rows"][2]["support_profile"],
            )
            projection = legislation.model_enrichment_v3_explorer_manifest(
                governed
            )
            self.assertEqual("okf-provider-datapack.v1", projection["schema"])
            self.assertEqual(
                "legislation-work-catalogue",
                projection["source_id"],
            )
            self.assertEqual(
                {
                    "kind": (
                        "governed-codex-task-surface-policy-with-"
                        "deterministic-corpus-application"
                    ),
                    "authority": (
                        "derived-model-assisted-discovery-metadata"
                    ),
                    "assistant_surface": "Codex interactive task surface",
                    "input_manifest": "data/manifest.json",
                    "run": "enrichment/codex-assisted-v3/run.json",
                    "coverage": "enrichment/codex-assisted-v3/coverage.json",
                    "accepted_manifest": (
                        "enrichment/codex-assisted-v3/"
                        "accepted-manifest.json"
                    ),
                    "independent_audit": (
                        "whole-law/assurance/"
                        "enrichment-v3-independent-audit-20260726.json"
                    ),
                    "semantic_reviewer": (
                        "whole-law/assurance/"
                        "enrichment-v3-reviewer-task-receipt.json"
                    ),
                    "api_calls": 0,
                    "official_legal_classification": False,
                },
                projection["acquisition"],
            )
            self.assertEqual(
                (
                    "enrichment/codex-assisted-v3/"
                    "accepted-assertions/assertions-000.json.gz"
                ),
                projection["chunks"][0]["path"],
            )
            self.assertEqual(
                "enrichment/codex-assisted-v3/accepted-manifest.json",
                projection["source_contract"]["path"],
            )
            self.assertEqual(
                (
                    "whole-law/assurance/"
                    "enrichment-v3-reviewer-task-receipt.json"
                ),
                projection["semantic_reviewer"]["path"],
            )
            self.assertEqual(
                {
                    "classified as": 1,
                    "has discovery concept": 2,
                    "mentions entity": 1,
                },
                {
                    row["predicate"]: row["count"]
                    for row in projection["relationship_kinds"]
                },
            )
            self.assertEqual(
                "stable-ordered-list",
                projection["provenance"]["evidence_shape"],
            )
            self.assertEqual(
                ["title", "notes"],
                projection["provenance"]["support_profiles"]["multi-field"],
            )
            self.assertEqual(
                governed["counts"]["by_support"],
                projection["counts"]["by_support"],
            )

    def test_v3_graph_input_rejects_a_stale_reviewer_binding(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            reviewer_path, _ = self.governed_v3_fixture(root)
            reviewer = json.loads(reviewer_path.read_text(encoding="utf-8"))
            reviewer["review_task_id"] = "tampered"
            reviewer_path.write_text(json.dumps(reviewer), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewer"):
                legislation.load_governed_model_enrichment_v3(root)

    def test_v3_graph_input_rejects_non_integer_binding_bytes(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            self.governed_v3_fixture(root)
            audit_path = (
                root
                / "whole-law"
                / "assurance"
                / "enrichment-v3-independent-audit-20260726.json"
            )
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["materials"]["accepted_manifest"]["bytes"] = True
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "binding is malformed"):
                legislation.load_governed_model_enrichment_v3(root)

    def test_v3_graph_input_rejects_extra_audit_material(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            _, accepted_path = self.governed_v3_fixture(root)
            audit_path = (
                root
                / "whole-law"
                / "assurance"
                / "enrichment-v3-independent-audit-20260726.json"
            )
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            body = accepted_path.read_bytes()
            audit["materials"]["unreviewed_extra"] = {
                "path": accepted_path.relative_to(root).as_posix(),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inventory"):
                legislation.load_governed_model_enrichment_v3(root)

    def test_v3_gzip_reader_rejects_concatenated_members(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / "concatenated.json.gz"
            path.write_bytes(
                gzip.compress(b"[]", mtime=0)
                + gzip.compress(b"[]", mtime=0)
            )
            with self.assertRaisesRegex(ValueError, "trailing"):
                legislation.inflate_single_gzip(path)

    def test_v3_repository_path_rejects_symlink_components(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            target = root / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            link = root / "linked.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                legislation.repository_path(root, "linked.json", "fixture")

    def test_v02_actor_and_date_validation(self) -> None:
        self.assertTrue(checker.valid_actor("human:reviewer"))
        self.assertTrue(checker.valid_actor("process:legislation-okf-builder"))
        self.assertTrue(checker.valid_actor("reference_agent/gemini-2.5-pro"))
        self.assertFalse(checker.valid_actor("team:legislation"))
        self.assertFalse(checker.valid_actor("process:"))
        self.assertTrue(checker.valid_datetime("2026-07-11T18:00:00Z"))
        self.assertFalse(checker.valid_datetime("2026-07-11"))
        self.assertTrue(checker.valid_date("2026-07-11"))
        self.assertFalse(checker.valid_date("2026-02-30"))

    def test_v02_source_signals_require_valid_windows(self) -> None:
        errors: list[str] = []
        checker.check_sources(
            errors,
            [
                {
                    "resource": "https://www.legislation.gov.uk/",
                    "author": "process:legislation-feed",
                    "usage_count": 3,
                    "last_modified": "2026-07-11",
                }
            ],
            {"from": "2026-07-01", "to": "2026-07-11"},
            "fixture.md",
        )
        self.assertEqual([], errors)
        checker.check_sources(
            errors,
            [{"resource": "https://www.legislation.gov.uk/", "usage_count": 3}],
            None,
            "fixture.md",
        )
        self.assertIn("source usage_count has no usage_window: fixture.md sources[0]", errors)

    def test_v02_attested_computation_contract(self) -> None:
        errors: list[str] = []
        checker.check_attested_computation(
            errors,
            {
                "runtime": "python",
                "parameters": [
                    {"name": "year", "type": "integer", "required": True}
                ],
                "executor": {
                    "resource": "references/run.md",
                    "receipt": ["run_id", "result"],
                },
                "attester": {"resource": "references/attest.py"},
            },
            "# Computation\n\n```python\nprint(year)\n```\n",
            "fixture.md",
        )
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
