"""Verify that CI and Pages share one fail-closed publication gate."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
VALIDATION_SCRIPT = ROOT / "scripts" / "validate_publication.sh"
VALIDATION_COMMAND = "sh scripts/validate_publication.sh"
PINNED_ACTION = re.compile(
    r"^\s*(?:-\s+)?uses:\s+\S+@([0-9a-f]{40})(?:\s+#.*)?$"
)
REQUIRED_VALIDATION_COMMANDS = (
    "python3 -m unittest discover -s tests -v",
    "python3 scripts/build_publication_docs.py --check",
    "python3 scripts/check_internal_links.py",
    "python3 scripts/rebuild_legislation_discovery.py --check",
    "python3 scripts/check_legislation_okf.py",
    "python3 scripts/legislation_effects_evidence_archive.py check",
    "--snapshot-id legislation-effects-2026-07-25",
    "python3 scripts/build_legislation_effects.py --check",
    "python3 scripts/reconcile_legislation_effects_live.py check",
    "python3 scripts/build_codex_semantic_enrichment.py --check",
    "python3 scripts/audit_model_assisted_v2_independent.py --check",
    "python3 scripts/build_whole_law_evaluation.py --check",
    "python3 scripts/run_release_evaluation.py --check",
    "python3 scripts/run_yaml_ld_conformance.py --check",
    "python3 scripts/run_ontology_competency_questions.py --check",
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


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ci = CI.read_text(encoding="utf-8")
        cls.pages = PAGES.read_text(encoding="utf-8")
        cls.validation = VALIDATION_SCRIPT.read_text(encoding="utf-8")

    def test_both_workflows_use_the_shared_validation_entrypoint(self) -> None:
        self.assertIn(VALIDATION_COMMAND, job_block(self.ci, "validate"))
        self.assertIn(VALIDATION_COMMAND, job_block(self.pages, "validate"))

    def test_shared_entrypoint_covers_the_complete_validation_sequence(self) -> None:
        for command in REQUIRED_VALIDATION_COMMANDS:
            self.assertIn(command, self.validation)

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
        for path, workflow in ((CI, self.ci), (PAGES, self.pages)):
            action_lines = [
                line for line in workflow.splitlines() if "uses:" in line
            ]
            self.assertTrue(action_lines, path.as_posix())
            for line in action_lines:
                self.assertIsNotNone(
                    PINNED_ACTION.fullmatch(line),
                    f"{path.relative_to(ROOT)} has an unpinned action: {line.strip()}",
                )


if __name__ == "__main__":
    unittest.main()
