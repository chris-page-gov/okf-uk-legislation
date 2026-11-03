"""Verify the non-duplicating, fail-closed CI and Pages publication gates."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
VALIDATION_PHASE_WORKFLOW = (
    ROOT / ".github" / "workflows" / "validation-phase.yml"
)
VALIDATION_SCRIPT = ROOT / "scripts" / "validate_publication.sh"
VALIDATION_COMMAND = "sh scripts/validate_publication.sh"
LOCAL_VALIDATION_WORKFLOW = "uses: ./.github/workflows/validation-phase.yml"
PINNED_ACTION = re.compile(
    r"^\s*(?:-\s+)?uses:\s+\S+@([0-9a-f]{40})(?:\s+#.*)?$"
)
REQUIRED_VALIDATION_COMMANDS = (
    "python3 scripts/check_publication_contract.py",
    "python3 -m unittest discover -s tests -v",
    "python3 scripts/build_release_metadata.py --check",
    "python3 scripts/build_publication_docs.py --check",
    "python3 scripts/check_internal_links.py",
    "python3 scripts/rebuild_legislation_discovery.py --check",
    "python3 scripts/check_legislation_okf.py",
    "python3 scripts/legislation_effects_evidence_archive.py check",
    "--snapshot-id legislation-effects-2026-07-25",
    "python3 scripts/build_legislation_effects.py --check",
    "python3 scripts/reconcile_legislation_effects_live.py check",
    "python3 scripts/build_model_enrichment_input_evidence.py --check",
    "python3 scripts/build_codex_semantic_enrichment.py --check",
    "python3 scripts/build_codex_semantic_enrichment_v3.py check",
    "python3 scripts/audit_codex_semantic_enrichment_v3.py check",
    "python3 scripts/audit_model_assisted_v2_independent.py --check",
    "python3 scripts/build_whole_law_evaluation.py --check",
    "python3 scripts/run_release_evaluation.py --check",
    "python3 scripts/run_yaml_ld_conformance.py --check",
    "python3 scripts/run_ontology_competency_questions.py --check",
    "python3 scripts/run_semantic_conformance.py --check",
    "python3 scripts/build_whole_law_okf.py --check",
    "python3 scripts/check_whole_law_okf.py",
    "python3 scripts/audit_graph_enrichment_gate.py check",
    "python3 scripts/build_release_assurance.py --check",
    "python3 scripts/build_checksums.py --check",
    "python3 scripts/build_legislation_okf.py",
    "--fixture tests/fixtures/legislation_okf/sample.feed.xml",
    '--output "$validation_tmp/fixture"',
    "--generated-at 2026-07-11T00:00:00Z",
)
EXPECTED_PHASE_LABELS = {
    "core": {
        "publication contract",
        "unit suite",
        "release metadata",
        "publication documentation",
        "internal links",
        "fixture build",
    },
    "legislation": {
        "legislation discovery",
        "legislation OKF",
        "effects evidence archive",
        "effects projection",
        "effects reconciliation",
        "model input evidence",
        "Codex v2 enrichment",
        "Codex v3 enrichment",
        "Codex v3 audit",
        "model-assisted v2 audit",
    },
    "semantics": {
        "Whole-Law evaluation build",
        "release evaluation",
        "YAML-LD conformance",
        "ontology competency questions",
        "semantic conformance",
    },
    "federation": {
        "Whole-Law build",
        "Whole-Law OKF",
        "graph enrichment",
        "release assurance",
        "checksums",
    },
}


def job_block(workflow: str, job: str) -> str:
    lines = workflow.splitlines()
    marker = f"  {job}:"
    try:
        start = lines.index(marker)
    except ValueError as error:
        raise AssertionError(f"missing {job!r} job") from error

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.fullmatch(r"  [A-Za-z0-9_-]+:", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def validation_phase_block(script: str, phase: str) -> str:
    marker = f"if phase_enabled {phase}; then"
    start = script.index(marker)
    end = script.index("\nfi", start)
    return script[start:end]


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci = CI.read_text(encoding="utf-8")
        cls.pages = PAGES.read_text(encoding="utf-8")
        cls.phase_workflow = VALIDATION_PHASE_WORKFLOW.read_text(
            encoding="utf-8"
        )
        cls.validation = VALIDATION_SCRIPT.read_text(encoding="utf-8")

    def test_both_workflows_use_the_shared_validation_entrypoint(self) -> None:
        self.assertIn(VALIDATION_COMMAND, self.phase_workflow)
        for workflow in (self.ci, self.pages):
            for phase in ("core", "legislation", "semantics", "federation"):
                block = job_block(workflow, phase)
                self.assertIn(LOCAL_VALIDATION_WORKFLOW, block)
                self.assertIn(f"phase: {phase}", block)

    def test_ci_validates_pull_requests_without_duplicating_feature_pushes(self) -> None:
        trigger = self.ci.split("\npermissions:\n", 1)[0]
        self.assertIn("  pull_request:", trigger)
        self.assertIn("  workflow_dispatch:", trigger)
        self.assertNotIn("  push:", trigger)

    def test_pages_is_the_only_main_push_validation(self) -> None:
        trigger = self.pages.split("\npermissions:\n", 1)[0]
        self.assertIn("  push:\n    branches: [main]", trigger)
        self.assertNotIn("branches: [main]", self.ci)

    def test_only_read_only_ci_cancels_superseded_runs(self) -> None:
        self.assertIn(
            "group: okf-bundle-ci-${{ github.event.pull_request.number || github.ref }}",
            self.ci,
        )
        self.assertIn("cancel-in-progress: true", self.ci)
        self.assertIn("group: pages", self.pages)
        self.assertIn("cancel-in-progress: false", self.pages)

    def test_lockstep_compares_the_complete_candidate_change(self) -> None:
        self.assertIn("fetch-depth: 2", self.phase_workflow)
        self.assertIn(
            'check_documentation_lockstep.py --base "$LOCKSTEP_BASE"',
            self.phase_workflow,
        )
        self.assertIn("lockstep_base: HEAD^1", job_block(self.ci, "core"))
        self.assertIn("lockstep_base: HEAD^", job_block(self.pages, "core"))

    def test_shared_entrypoint_covers_the_complete_validation_sequence(self) -> None:
        for command in REQUIRED_VALIDATION_COMMANDS:
            self.assertIn(command, self.validation)
            self.assertEqual(
                1,
                self.validation.count(command),
                f"validation command is not assigned exactly once: {command}",
            )

    def test_each_step_is_assigned_to_exactly_one_declared_phase(self) -> None:
        all_labels: list[str] = []
        for phase, expected in EXPECTED_PHASE_LABELS.items():
            block = validation_phase_block(self.validation, phase)
            actual = set(re.findall(r'run_step "([^"]+)"', block))
            self.assertEqual(actual, expected, phase)
            all_labels.extend(actual)

        self.assertEqual(len(all_labels), len(set(all_labels)))
        self.assertEqual(
            len(all_labels),
            len(re.findall(r'run_step "([^"]+)"', self.validation)),
        )

    def test_default_local_mode_enables_every_phase(self) -> None:
        self.assertIn(
            'validation_phase="${OKF_VALIDATION_PHASE:-all}"',
            self.validation,
        )
        self.assertIn(
            '[ "$validation_phase" = "all" ] || [ "$validation_phase" = "$1" ]',
            self.validation,
        )

    def test_shared_entrypoint_emits_per_step_and_total_timings(self) -> None:
        self.assertIn('run_step "unit suite"', self.validation)
        self.assertIn(
            'validation_phase="${OKF_VALIDATION_PHASE:-all}"',
            self.validation,
        )
        for phase in ("core", "legislation", "semantics", "federation"):
            self.assertIn(f"if phase_enabled {phase}; then", self.validation)
        self.assertIn("VALIDATION TIMING", self.validation)
        self.assertIn("VALIDATION TOTAL", self.validation)

    def test_validate_is_a_fail_closed_phase_aggregator(self) -> None:
        for workflow in (self.ci, self.pages):
            validate = job_block(workflow, "validate")
            self.assertIn("if: ${{ always() }}", validate)
            self.assertIn(
                "needs: [core, legislation, semantics, federation]",
                validate,
            )
            for result in (
                "CORE_RESULT",
                "LEGISLATION_RESULT",
                "SEMANTICS_RESULT",
                "FEDERATION_RESULT",
            ):
                self.assertIn(f'test "${result}" = success', validate)

    def test_pages_deploy_requires_validation(self) -> None:
        self.assertRegex(
            job_block(self.pages, "deploy"),
            r"(?m)^    needs: validate$",
        )

    def test_pages_write_permissions_are_deploy_scoped(self) -> None:
        pre_jobs = self.pages.split("\njobs:\n", 1)[0]
        self.assertIn("permissions:\n  contents: read", pre_jobs)
        self.assertNotIn("pages: write", pre_jobs)
        self.assertNotIn("id-token: write", pre_jobs)

        validate = job_block(self.pages, "validate")
        self.assertNotIn("pages: write", validate)
        self.assertNotIn("id-token: write", validate)

        deploy = job_block(self.pages, "deploy")
        self.assertIn("permissions:\n      contents: read", deploy)
        self.assertIn("pages: write", deploy)
        self.assertIn("id-token: write", deploy)

    def test_all_workflow_actions_are_commit_pinned(self) -> None:
        for path, workflow in (
            (CI, self.ci),
            (PAGES, self.pages),
            (VALIDATION_PHASE_WORKFLOW, self.phase_workflow),
        ):
            action_lines = [
                line for line in workflow.splitlines() if "uses:" in line
            ]
            self.assertTrue(action_lines, path.as_posix())
            for line in action_lines:
                if LOCAL_VALIDATION_WORKFLOW in line:
                    self.assertEqual(LOCAL_VALIDATION_WORKFLOW, line.strip())
                    continue
                self.assertIsNotNone(
                    PINNED_ACTION.fullmatch(line),
                    f"{path.relative_to(ROOT)} has an unpinned action: {line.strip()}",
                )


if __name__ == "__main__":
    unittest.main()
