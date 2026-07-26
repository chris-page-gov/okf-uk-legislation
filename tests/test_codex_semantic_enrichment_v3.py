from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "bundle" / "enrichment" / "codex-assisted-v3"
AUTHORING = ROOT / "enrichment" / "codex-assisted-v3"
RUN = OUTPUT / "run.json"
CANDIDATES = OUTPUT / "candidate-manifest.json"
OUTCOMES = OUTPUT / "terminal-outcome-manifest.json"
CHECKPOINTS = OUTPUT / "checkpoints.json"
REVIEW_MANIFEST = OUTPUT / "review-verdict-manifest.json"
ACCEPTED_MANIFEST = OUTPUT / "accepted-manifest.json"
AUDIT = (
    ROOT
    / "whole-law"
    / "assurance"
    / "enrichment-v3-independent-audit-20260726.json"
)


def load(path: Path):
    body = path.read_bytes()
    if path.suffix == ".gz":
        body = gzip.decompress(body)
    return json.loads(body)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class CodexSemanticEnrichmentV3Tests(unittest.TestCase):
    def test_generator_is_zero_direct_api_and_truthfully_scoped(self) -> None:
        run = load(RUN)
        self.assertEqual(run["schema"], "okf-model-enrichment-run.v3")
        counts = run["counts"]
        self.assertEqual(counts["records"]["attempted"], 365_786)
        self.assertEqual(
            counts["records"]["terminal_outcomes"],
            counts["records"]["attempted"],
        )
        self.assertEqual(
            counts["records"]["with_candidates"]
            + counts["records"]["without_supported_candidates"],
            counts["records"]["attempted"],
        )
        self.assertEqual(
            counts["candidates"]["total"],
            sum(
                counts["candidates"][kind]
                for kind in ("topic", "concept", "entity")
            ),
        )
        self.assertEqual(
            counts["candidates"]["total"],
            sum(counts["candidate_support"].values()),
        )
        self.assertGreater(counts["candidate_support"]["title-only"], 0)
        self.assertGreater(counts["candidate_support"]["notes-only"], 0)
        self.assertGreater(counts["candidate_support"]["multi-field"], 0)
        self.assertEqual(counts["candidate_support"]["metadata-only"], 0)
        self.assertEqual(run["usage"]["api_calls"], 0)
        self.assertEqual(run["usage"]["api_input_tokens"], 0)
        self.assertEqual(run["usage"]["api_output_tokens"], 0)
        self.assertEqual(run["cost"]["incremental_openai_api_usd"], 0.0)
        self.assertEqual(run["cost"]["incremental_openai_api_gbp"], 0.0)
        self.assertFalse(run["cost"]["cap_triggered"])
        self.assertFalse(run["exact_model_deployment_identity_available"])
        self.assertEqual(
            run["usage"]["codex_subscription_token_usage"],
            "not exposed",
        )
        self.assertEqual(
            run["usage"]["codex_weekly_allowance_usage"],
            "not exposed",
        )
        self.assertFalse(run["official_legal_classification"])
        self.assertIn("without per-work LLM calls", run["model_role"])

    def test_generation_manifests_and_checkpoints_are_hash_bound(self) -> None:
        run = load(RUN)
        candidate_manifest = load(CANDIDATES)
        terminal_manifest = load(OUTCOMES)
        checkpoints = load(CHECKPOINTS)
        self.assertEqual(
            candidate_manifest["materials_sha256"],
            run["materials_sha256"],
        )
        self.assertEqual(
            terminal_manifest["materials_sha256"],
            run["materials_sha256"],
        )
        self.assertEqual(
            checkpoints["materials_sha256"],
            run["materials_sha256"],
        )
        self.assertEqual(
            checkpoints["source_corpus_semantic_sha256"],
            run["source_corpus_semantic_sha256"],
        )
        self.assertEqual(len(candidate_manifest["chunks"]), 366)
        self.assertEqual(len(terminal_manifest["chunks"]), 366)
        self.assertEqual(len(checkpoints["chunks"]), 366)
        self.assertEqual(
            candidate_manifest["counts"]["assertions"],
            run["counts"]["candidates"]["total"],
        )
        self.assertEqual(
            candidate_manifest["counts"]["by_support"],
            run["counts"]["candidate_support"],
        )
        self.assertEqual(
            terminal_manifest["counts"]["terminal_outcomes"],
            365_786,
        )
        for row in checkpoints["chunks"]:
            for key in ("candidate_shard", "terminal_outcome_shard"):
                artifact = row[key]
                path = ROOT / artifact["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(sha256(path), artifact["sha256"])

    def test_executed_calibration_and_generator_are_hash_bound(self) -> None:
        run = load(RUN)
        result_path = OUTPUT / "calibration-result.json"
        result = load(result_path)
        self.assertEqual(
            run["materials"]["generator_executable"]["sha256"],
            sha256(
                ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py"
            ),
        )
        self.assertEqual(
            run["materials"]["v3_calibration"]["sha256"],
            sha256(AUTHORING / "calibration.json"),
        )
        self.assertTrue(result["passed"])
        self.assertFalse(result["population_level_precision_claimed"])
        self.assertRegex(result["case_set_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["schema_validity"], 1.0)
        schema = result["schema_validation"]
        self.assertEqual(
            schema["candidate"]["valid"],
            schema["candidate"]["total"],
        )
        self.assertEqual(
            schema["terminal_outcome"],
            {"valid": 365_786, "total": 365_786},
        )
        self.assertEqual(schema["valid"], schema["total"])
        for dimension in ("topic", "concept", "entity"):
            self.assertTrue(result[dimension]["passed"])
            self.assertGreaterEqual(
                result[dimension]["precision"]["value"],
                result["thresholds"]["precision"],
            )
            self.assertGreaterEqual(
                result[dimension]["evidence_support"]["value"],
                result["thresholds"]["evidence_support"],
            )
        self.assertEqual(
            result["concept"]["near_miss"],
            {"passed": 55, "total": 55},
        )
        self.assertEqual(
            result["entity"]["near_miss"],
            {"passed": 19, "total": 19},
        )
        self.assertEqual(
            result["entity"]["exclusion"],
            {"passed": 7, "total": 7},
        )
        self.assertEqual(
            result["entity"]["jurisdiction_collision"],
            {"passed": 4, "total": 4},
        )
        self.assertEqual(
            result["entity"]["retirement_abstention"],
            {"passed": 1, "total": 1},
        )
        self.assertEqual(
            result["entity"]["retained_context"],
            {"passed": 1, "total": 1},
        )
        self.assertTrue(result["field_policy"]["passed"])
        self.assertEqual(
            result["field_policy"]["semantic_text"]["positive"],
            {"passed": 3, "total": 3},
        )
        self.assertEqual(
            result["field_policy"]["source_metadata"]["abstention"],
            {"passed": 4, "total": 4},
        )
        self.assertEqual(
            set(run["output_bindings"]),
            {
                "candidate_manifest",
                "terminal_outcome_manifest",
                "coverage",
                "checkpoints",
                "calibration_result",
            },
        )
        for artifact in run["output_bindings"].values():
            path = ROOT / artifact["path"]
            self.assertEqual(sha256(path), artifact["sha256"])
            self.assertEqual(path.stat().st_size, artifact["bytes"])

    def test_every_work_has_one_three_dimension_terminal_outcome(self) -> None:
        manifest = load(OUTCOMES)
        seen: set[str] = set()
        eligibility: dict[str, int] = {}
        field_outcomes: dict[str, dict[str, int]] = {
            field: {}
            for field in (
                "title",
                "notes",
                "category",
                "document_type",
                "publisher_title",
                "tags",
            )
        }
        frozen_bodies = 0
        for chunk in manifest["chunks"]:
            rows = load(ROOT / chunk["path"])
            self.assertEqual(len(rows), chunk["records"])
            for row in rows:
                work_id = row["work_id"]
                self.assertNotIn(work_id, seen)
                seen.add(work_id)
                self.assertEqual(
                    set(row["attempts"]),
                    {"topic", "concept", "entity_link"},
                )
                candidate_ids = []
                for dimension in ("topic", "concept", "entity_link"):
                    attempt = row["attempts"][dimension]
                    self.assertIn(
                        attempt["status"],
                        {
                            "candidate-generated",
                            "suppressed-no-new-candidate",
                            "abstained-no-literal-support",
                        },
                    )
                    candidate_ids.extend(attempt["candidate_ids"])
                self.assertEqual(candidate_ids, row["candidate_ids"])
                self.assertEqual(len(candidate_ids), row["candidate_count"])
                evidence = row["input"]
                self.assertTrue(evidence["title"]["considered"])
                self.assertTrue(
                    evidence["long_title_equivalent"]["considered"]
                )
                self.assertTrue(evidence["source_metadata"]["considered"])
                for key, field in (
                    ("title", evidence["title"]),
                    ("notes", evidence["long_title_equivalent"]),
                ):
                    outcome = field["evaluation_outcome"]
                    field_outcomes[key][outcome] = (
                        field_outcomes[key].get(outcome, 0) + 1
                    )
                    self.assertRegex(
                        field["source_value_sha256"],
                        r"^[0-9a-f]{64}$",
                    )
                metadata = evidence["source_metadata"]["fields"]
                self.assertEqual(
                    set(metadata),
                    {
                        "category",
                        "document_type",
                        "publisher_title",
                        "tags",
                    },
                )
                for key, field in metadata.items():
                    self.assertEqual(field["governed_dimensions"], [])
                    self.assertEqual(
                        field["evaluation_outcome"],
                        "considered-no-supported-match",
                    )
                    self.assertEqual(field["supporting_candidate_ids"], [])
                    field_outcomes[key][field["evaluation_outcome"]] = (
                        field_outcomes[key].get(
                            field["evaluation_outcome"],
                            0,
                        )
                        + 1
                    )
                self.assertTrue(evidence["manifestations"]["considered"])
                self.assertFalse(
                    evidence["manifestations"][
                        "frozen_clml_body_available"
                    ]
                )
                frozen_bodies += int(
                    evidence["manifestations"][
                        "frozen_clml_body_available"
                    ]
                )
                outcome = evidence["input_eligibility_outcome"]
                eligibility[outcome] = eligibility.get(outcome, 0) + 1
        self.assertEqual(len(seen), 365_786)
        self.assertEqual(
            eligibility,
            {
                "candidate-local-semantic-evidence": 359_140,
                "deferred-frozen-clml-required": 6_646,
            },
        )
        self.assertEqual(frozen_bodies, 0)
        self.assertGreater(
            field_outcomes["notes"].get("used-candidate-support", 0),
            0,
        )
        for field in (
            "category",
            "document_type",
            "publisher_title",
            "tags",
        ):
            self.assertEqual(
                field_outcomes[field],
                {"considered-no-supported-match": 365_786},
            )

    def test_generator_resume_guard_requires_exact_hashes(self) -> None:
        producer = module(
            ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py",
            "build_codex_semantic_enrichment_v3_test",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer.ROOT = root
            input_path = root / "input"
            candidate_path = root / "candidate"
            outcome_path = root / "outcome"
            input_path.write_bytes(b"input")
            candidate_path.write_bytes(b"candidate")
            outcome_path.write_bytes(b"outcome")
            row = {
                "input": {
                    "path": "input",
                    "sha256": hashlib.sha256(b"input").hexdigest(),
                },
                "materials_sha256": "a" * 64,
                "candidate_shard": {
                    "path": "candidate",
                    "sha256": hashlib.sha256(b"candidate").hexdigest(),
                },
                "terminal_outcome_shard": {
                    "path": "outcome",
                    "sha256": hashlib.sha256(b"outcome").hexdigest(),
                },
            }
            self.assertTrue(
                producer.reusable_checkpoint(
                    row,
                    input_path=input_path,
                    input_sha256=hashlib.sha256(b"input").hexdigest(),
                    materials_sha256="a" * 64,
                    candidate_path=candidate_path,
                    outcome_path=outcome_path,
                )
            )
            candidate_path.write_bytes(b"changed")
            self.assertFalse(
                producer.reusable_checkpoint(
                    row,
                    input_path=input_path,
                    input_sha256=hashlib.sha256(b"input").hexdigest(),
                    materials_sha256="a" * 64,
                    candidate_path=candidate_path,
                    outcome_path=outcome_path,
                )
            )

    def test_multi_field_evidence_and_metadata_abstention_reconstruct(
        self,
    ) -> None:
        producer = module(
            ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py",
            "build_codex_semantic_enrichment_v3_fields_test",
        )
        auditor = module(
            ROOT / "scripts" / "audit_codex_semantic_enrichment_v3.py",
            "audit_codex_semantic_enrichment_v3_fields_test",
        )
        materials = producer.governed_materials()
        records = load(ROOT / "bundle" / "data" / "works-0.json.gz")
        multi = next(
            row
            for row in records
            if row["id"]
            == "https://www.legislation.gov.uk/id/uksi/2026/99"
        )

        def generate(record):
            return producer.record_candidates(
                record,
                "bundle/data/works-0.json.gz",
                materials[2],
                materials[3],
                materials[4],
                materials[5],
                materials[6],
            )

        multi_candidates, multi_terminal = generate(multi)
        self.assertTrue(multi_candidates)
        self.assertTrue(
            all(
                candidate["support_profile"] == "multi-field"
                for candidate in multi_candidates
            )
        )
        self.assertTrue(
            all(
                [row["source_field"] for row in candidate["evidence"]]
                == ["title", "notes"]
                for candidate in multi_candidates
            )
        )
        notes_only = json.loads(json.dumps(records[0]))
        notes_only["id"] = "urn:test:notes-only"
        notes_only["title"] = "https://example.test/id/notes-only"
        notes_only["notes"] = (
            "These Regulations make provision for student support."
        )
        notes_candidates, notes_terminal = generate(notes_only)
        self.assertTrue(notes_candidates)
        self.assertTrue(
            all(
                candidate["support_profile"] == "notes-only"
                for candidate in notes_candidates
            )
        )
        metadata_only = json.loads(json.dumps(records[0]))
        metadata_only["id"] = "urn:test:metadata-only"
        metadata_only["title"] = "https://example.test/id/metadata-only"
        metadata_only["notes"] = ""
        metadata_candidates, metadata_terminal = generate(metadata_only)
        self.assertEqual(metadata_candidates, [])
        for terminal, record in (
            (multi_terminal, multi),
            (notes_terminal, notes_only),
            (metadata_terminal, metadata_only),
        ):
            specs, attempts, receipts = auditor.reconstruct_record(record)
            expected = auditor.terminal_core(
                record,
                "bundle/data/works-0.json.gz",
                specs,
                attempts,
                receipts,
            )
            self.assertEqual(terminal, expected)
            self.assertEqual(
                set(terminal["input"]["source_metadata"]["fields"]),
                {
                    "category",
                    "document_type",
                    "publisher_title",
                    "tags",
                },
            )

    def test_jurisdiction_entity_rules_reconstruct_exactly(self) -> None:
        producer = module(
            ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py",
            "build_codex_semantic_enrichment_v3_entity_scope_test",
        )
        auditor = module(
            ROOT / "scripts" / "audit_codex_semantic_enrichment_v3.py",
            "audit_codex_semantic_enrichment_v3_entity_scope_test",
        )
        materials = producer.governed_materials()
        calibration = producer.execute_calibration(
            materials[2],
            materials[3],
            materials[4],
            materials[6],
        )
        self.assertTrue(calibration["rule_calibration_passed"])
        self.assertEqual(
            calibration["entity"]["exclusion"],
            {"passed": 7, "total": 7},
        )
        self.assertEqual(
            calibration["entity"]["jurisdiction_collision"],
            {"passed": 4, "total": 4},
        )
        self.assertEqual(
            calibration["entity"]["retirement_abstention"],
            {"passed": 1, "total": 1},
        )
        self.assertEqual(
            calibration["entity"]["retained_context"],
            {"passed": 1, "total": 1},
        )

        active_ids = {str(rule.row["id"]) for rule in materials[4]}
        self.assertNotIn("E001", active_ids)
        self.assertEqual(
            {
                identifier
                for identifier in active_ids
                if identifier
                in {
                    "E004",
                    "E010",
                    "E015",
                    "E017",
                    "E018",
                    "E019",
                    "E020",
                }
            },
            {"E004", "E010", "E015", "E017", "E018", "E019", "E020"},
        )
        base = load(ROOT / "bundle" / "data" / "works-0.json.gz")[0]
        cases = [
            (
                "The National Health Service Regulations 2026",
                "",
                set(),
            ),
            (
                "The Environment Agency Regulations 2026",
                "",
                {"E004"},
            ),
            (
                "The Northern Ireland Environment Agency Regulations 2026",
                "",
                {"E017"},
            ),
            (
                "The European Environment Agency Regulations 2026",
                "",
                {"E020"},
            ),
            (
                "The Health and Safety Executive Regulations 2026",
                "",
                {"E010"},
            ),
            (
                "The Health and Safety Executive for Northern Ireland "
                "Regulations 2026",
                "",
                {"E018"},
            ),
            (
                "The Charity Commission Regulations 2026",
                "",
                {"E015"},
            ),
            (
                "The Charity Commission for Northern Ireland Regulations 2026",
                "",
                {"E019"},
            ),
            (
                "The Bank of England Regulations 2026",
                "",
                {"E002"},
            ),
            (
                "The Imperial Bank of England Act 1842",
                "",
                set(),
            ),
            (
                "The Pensions Regulator Regulations 2026",
                "",
                {"E005"},
            ),
            (
                "The Pensions Regulator Tribunal Rules 2005",
                "These Rules regulate the Pensions Regulator Tribunal.",
                set(),
            ),
            (
                "A Constitution Order",
                (
                    "This Order establishes a new Constitution for Montserrat, "
                    "in which an Electoral Commission is established for the "
                    "first time."
                ),
                set(),
            ),
            (
                "A UK founding Act",
                (
                    "An Act to establish an Electoral Commission; and to make "
                    "provision about elections and political parties."
                ),
                {"E011"},
            ),
        ]
        for index, (title, notes, expected_rule_ids) in enumerate(cases):
            with self.subTest(title=title, notes=notes):
                record = json.loads(json.dumps(base))
                record["id"] = f"urn:test:entity-scope:{index}"
                record["title"] = title
                record["notes"] = notes
                generated, _terminal = producer.record_candidates(
                    record,
                    "bundle/data/works-0.json.gz",
                    materials[2],
                    materials[3],
                    materials[4],
                    materials[5],
                    materials[6],
                )
                generated_entities = {
                    row["id"]: row
                    for row in generated
                    if row["dimension"] == "entity"
                }
                specs, _attempts, _receipts = auditor.reconstruct_record(record)
                expected_entities = {
                    row["id"]: row
                    for row in specs
                    if row["dimension"] == "entity"
                }
                self.assertEqual(
                    {
                        row["rule_id"]
                        for row in generated_entities.values()
                    },
                    expected_rule_ids,
                )
                self.assertEqual(
                    set(generated_entities),
                    set(expected_entities),
                )
                errors: list[str] = []
                for identifier, candidate in generated_entities.items():
                    self.assertTrue(
                        auditor.validate_candidate(
                            candidate,
                            expected_entities[identifier],
                            errors,
                        )
                    )
                self.assertEqual(errors, [])

    def test_auditor_does_not_import_or_execute_generator(self) -> None:
        path = ROOT / "scripts" / "audit_codex_semantic_enrichment_v3.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            str(node.module)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertNotIn("build_codex_semantic_enrichment_v3", imports)
        self.assertFalse(
            imports.intersection(
                {
                    "openai",
                    "requests",
                    "httpx",
                    "urllib.request",
                    "subprocess",
                }
            )
        )

    def test_auditor_rejects_trailing_gzip_and_archive_bomb(self) -> None:
        auditor = module(
            ROOT / "scripts" / "audit_codex_semantic_enrichment_v3.py",
            "audit_codex_semantic_enrichment_v3_gzip_test",
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            concatenated = directory / "concatenated.json.gz"
            concatenated.write_bytes(
                gzip.compress(b"[]", mtime=0)
                + gzip.compress(b"[]", mtime=0)
            )
            with self.assertRaises(RuntimeError):
                auditor.load(concatenated)
            bomb = directory / "bomb.json.gz"
            bomb.write_bytes(
                gzip.compress(
                    json.dumps(["x" * 512]).encode("utf-8"),
                    mtime=0,
                )
            )
            auditor.MAX_GZIP_DECOMPRESSED_BYTES = 128
            with self.assertRaises(RuntimeError):
                auditor.load(bomb)

    def test_auditor_rejects_unsafe_and_symlink_component_paths(self) -> None:
        auditor = module(
            ROOT / "scripts" / "audit_codex_semantic_enrichment_v3.py",
            "audit_codex_semantic_enrichment_v3_path_test",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir()
            target = real / "artifact.json"
            target.write_text("{}\n", encoding="utf-8")
            link = root / "link"
            link.symlink_to(real, target_is_directory=True)
            auditor.ROOT = root
            body = target.read_bytes()
            binding = {
                "path": "link/artifact.json",
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
            }
            with self.assertRaises(RuntimeError):
                auditor.safe_bound_path(
                    binding,
                    expected_path=link / "artifact.json",
                )
            binding["path"] = "../artifact.json"
            with self.assertRaises(RuntimeError):
                auditor.safe_bound_path(
                    binding,
                    expected_path=root / "artifact.json",
                )

    def test_verdict_and_accepted_projection_are_exactly_reconstructable(
        self,
    ) -> None:
        auditor = module(
            ROOT / "scripts" / "audit_codex_semantic_enrichment_v3.py",
            "audit_codex_semantic_enrichment_v3_projection_test",
        )
        producer = module(
            ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py",
            "build_codex_semantic_enrichment_v3_projection_test",
        )
        materials = producer.governed_materials()
        records = load(ROOT / "bundle" / "data" / "works-0.json.gz")
        record = next(
            row
            for row in records
            if row["id"]
            == "https://www.legislation.gov.uk/id/uksi/2026/99"
        )
        generated, _terminal = producer.record_candidates(
            record,
            "bundle/data/works-0.json.gz",
            materials[2],
            materials[3],
            materials[4],
            materials[5],
            materials[6],
        )
        candidate = generated[0]
        reviewer = {
            "review_task_id": "independent-test-task",
            "reviewer_visible_model_label": "Codex test label",
        }
        receipt_hash = "a" * 64
        verdict = auditor.make_verdict(
            candidate,
            passed=True,
            reviewer_receipt=reviewer,
            reviewer_receipt_sha256=receipt_hash,
        )
        assertion = auditor.make_accepted_assertion(
            candidate,
            verdict,
            reviewer_receipt=reviewer,
            reviewer_receipt_sha256=receipt_hash,
        )
        self.assertTrue(auditor.verdict_contract_valid(verdict))
        self.assertTrue(auditor.accepted_contract_valid(assertion))
        rejected = auditor.make_verdict(
            candidate,
            passed=False,
            reviewer_receipt=reviewer,
            reviewer_receipt_sha256=receipt_hash,
        )
        self.assertTrue(auditor.verdict_contract_valid(rejected))
        self.assertEqual(rejected["decision"], "rejected")
        tampered_verdict = dict(verdict)
        tampered_verdict["decision"] = "rejected"
        self.assertFalse(auditor.verdict_contract_valid(tampered_verdict))
        tampered_assertion = dict(assertion)
        tampered_assertion["target"] = "topic/tampered"
        self.assertNotEqual(
            tampered_assertion,
            auditor.make_accepted_assertion(
                candidate,
                verdict,
                reviewer_receipt=reviewer,
                reviewer_receipt_sha256=receipt_hash,
            ),
        )
        self.assertFalse(auditor.is_exact_zero_number(False))
        self.assertTrue(auditor.is_exact_zero_number(0))
        self.assertTrue(auditor.is_exact_zero_number(0.0))
        source = (
            ROOT / "scripts" / "audit_codex_semantic_enrichment_v3.py"
        ).read_text(encoding="utf-8")
        self.assertIn("expected_acceptance_by_id", source)
        self.assertNotIn(
            'passed = verdict.get("decision") == "accepted"',
            source,
        )

    def test_auditor_check_fails_closed_on_runtime_error(self) -> None:
        auditor = module(
            ROOT / "scripts" / "audit_codex_semantic_enrichment_v3.py",
            "audit_codex_semantic_enrichment_v3_runtime_test",
        )

        def raise_runtime_error() -> dict[str, object]:
            raise RuntimeError("synthetic corrupt projection")

        auditor._check_impl = raise_runtime_error
        result = auditor.check()
        self.assertEqual(result["status"], "failed")
        self.assertIn("synthetic corrupt projection", result["errors"][0])

    def test_separate_semantic_reviewer_receipt_is_hash_bound(self) -> None:
        receipt = load(AUTHORING / "reviewer-task-receipt.json")
        run = load(RUN)
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(receipt["verdict"], "accepted")
        self.assertFalse(receipt["source_edits_made_by_reviewer"])
        self.assertTrue(receipt["review_task_id"])
        self.assertTrue(receipt["reviewer_visible_model_label"])
        self.assertEqual(
            receipt["reviewed_materials"],
            {
                "generator_prompt_sha256": sha256(
                    AUTHORING / "generator-prompt.md"
                ),
                "generator_executable_sha256": sha256(
                    ROOT / "scripts" / "build_codex_semantic_enrichment_v3.py"
                ),
                "reviewer_prompt_sha256": sha256(
                    AUTHORING / "reviewer-prompt.md"
                ),
                "rules_sha256": sha256(AUTHORING / "rules.json"),
                "review_policy_sha256": sha256(
                    AUTHORING / "review-policy.json"
                ),
                "calibration_sha256": sha256(
                    AUTHORING / "calibration.json"
                ),
                "calibration_result_sha256": sha256(
                    OUTPUT / "calibration-result.json"
                ),
                "source_corpus_semantic_sha256": run[
                    "source_corpus_semantic_sha256"
                ],
                "candidate_manifest_sha256": sha256(CANDIDATES),
                "terminal_outcome_manifest_sha256": sha256(OUTCOMES),
                "coverage_sha256": sha256(OUTPUT / "coverage.json"),
                "checkpoints_sha256": sha256(CHECKPOINTS),
            },
        )

    def test_independent_audit_and_accepted_projection_complete(self) -> None:
        audit = load(AUDIT)
        review_manifest = load(REVIEW_MANIFEST)
        accepted = load(ACCEPTED_MANIFEST)
        self.assertTrue(audit["decision"]["release_gate_passed"])
        self.assertEqual(
            audit["decision"]["independent_review_status"],
            "accepted",
        )
        self.assertEqual(audit["decision"]["errors"], [])
        counts = audit["counts"]
        self.assertEqual(counts["records_attempted"], 365_786)
        self.assertEqual(counts["terminal_outcomes"], 365_786)
        self.assertEqual(counts["candidates"], counts["review_verdicts"])
        self.assertEqual(
            counts["candidates"],
            counts["accepted_assertions"],
        )
        self.assertEqual(counts["rejected_candidates"], 0)
        self.assertEqual(counts["accepted_by_support"]["metadata-only"], 0)
        self.assertGreater(counts["accepted_by_support"]["notes-only"], 0)
        self.assertGreater(counts["accepted_by_support"]["multi-field"], 0)
        self.assertEqual(
            review_manifest["counts"],
            {
                "review_verdicts": counts["candidates"],
                "accepted": counts["candidates"],
                "rejected": 0,
            },
        )
        self.assertEqual(
            accepted["counts"],
            {
                "assertions": counts["candidates"],
                "by_kind": counts["accepted_by_kind"],
                "by_support": counts["accepted_by_support"],
            },
        )
        self.assertEqual(
            audit["metrics"]["cost"]["openai_api_calls"],
            0,
        )
        self.assertEqual(
            audit["metrics"]["cost"]["incremental_openai_api_usd"],
            0.0,
        )
        self.assertEqual(
            audit["metrics"]["cost"]["incremental_openai_api_gbp"],
            0.0,
        )
        self.assertEqual(
            audit["metrics"]["cost"]["codex_weekly_allowance_usage"],
            "not exposed",
        )
        for material in audit["materials"].values():
            path = ROOT / material["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(sha256(path), material["sha256"])

    def test_every_candidate_has_one_verdict_and_projection(self) -> None:
        candidate_manifest = load(CANDIDATES)
        review_manifest = load(REVIEW_MANIFEST)
        accepted_manifest = load(ACCEPTED_MANIFEST)
        seen_candidates: set[str] = set()
        seen_verdicts: set[str] = set()
        seen_accepted: set[str] = set()
        for candidate_chunk, verdict_chunk, accepted_chunk in zip(
            candidate_manifest["chunks"],
            review_manifest["chunks"],
            accepted_manifest["chunks"],
            strict=True,
        ):
            candidates = load(ROOT / candidate_chunk["path"])
            verdicts = load(ROOT / verdict_chunk["path"])
            accepted = load(ROOT / accepted_chunk["path"])
            self.assertEqual(len(candidates), len(verdicts))
            self.assertEqual(len(candidates), len(accepted))
            for candidate, verdict, assertion in zip(
                candidates,
                verdicts,
                accepted,
                strict=True,
            ):
                identifier = candidate["id"]
                self.assertNotIn(identifier, seen_candidates)
                seen_candidates.add(identifier)
                self.assertEqual(verdict["candidate_id"], identifier)
                self.assertEqual(verdict["decision"], "accepted")
                self.assertNotIn(verdict["id"], seen_verdicts)
                seen_verdicts.add(verdict["id"])
                self.assertEqual(assertion["id"], identifier)
                self.assertNotIn(assertion["id"], seen_accepted)
                seen_accepted.add(assertion["id"])
                self.assertEqual(
                    assertion["schema"],
                    "okf-relationship-assertion.v2",
                )
                self.assertEqual(
                    assertion["review_status"],
                    "accepted-independent-review",
                )
                self.assertEqual(
                    assertion["review"]["audit_id"],
                    "codex-assisted-v3-independent-audit-20260726",
                )
                self.assertFalse(
                    assertion["official_legal_classification"]
                )
                fields = [
                    evidence["source_field"]
                    for evidence in assertion["evidence"]
                ]
                self.assertIn(fields, [["title"], ["notes"], ["title", "notes"]])
                self.assertEqual(
                    assertion["support_profile"],
                    {
                        ("title",): "title-only",
                        ("notes",): "notes-only",
                        ("title", "notes"): "multi-field",
                    }[tuple(fields)],
                )
                for evidence in assertion["evidence"]:
                    self.assertEqual(
                        evidence["source_value_sha256"],
                        hashlib.sha256(
                            json.dumps(
                                evidence["source_value"],
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ).encode("utf-8")
                        ).hexdigest(),
                    )
        expected = candidate_manifest["counts"]["assertions"]
        self.assertEqual(len(seen_candidates), expected)
        self.assertEqual(seen_candidates, seen_accepted)
        self.assertEqual(len(seen_verdicts), expected)


if __name__ == "__main__":
    unittest.main()
