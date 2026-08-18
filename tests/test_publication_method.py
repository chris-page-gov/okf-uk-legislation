"""Test the local OKF build and publication lifecycle controls."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise AssertionError(f"could not load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


contract_check = load_script("check_publication_contract")
lockstep_check = load_script("check_documentation_lockstep")


class PublicationMethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(
            (ROOT / "okf.publication.json").read_text(encoding="utf-8")
        )

    def test_repository_contract_invariants_pass(self) -> None:
        self.assertEqual(contract_check.contract_errors(self.contract, ROOT), [])

    def test_controlled_change_requires_docs_and_changelog(self) -> None:
        errors, controlled, documentation = lockstep_check.lockstep_errors(
            self.contract, {"scripts/build_checksums.py"}
        )
        self.assertEqual(controlled, ["scripts/build_checksums.py"])
        self.assertEqual(documentation, [])
        self.assertEqual(len(errors), 2)

    def test_docs_and_changelog_satisfy_lockstep(self) -> None:
        errors, controlled, documentation = lockstep_check.lockstep_errors(
            self.contract,
            {
                ".github/workflows/ci.yml",
                "CHANGELOG.md",
                "PUBLICATION-METHOD.md",
            },
        )
        self.assertEqual(errors, [])
        self.assertEqual(controlled, [".github/workflows/ci.yml"])
        self.assertEqual(documentation, ["PUBLICATION-METHOD.md"])

    def test_changelog_is_not_a_documentation_substitute(self) -> None:
        errors, _, documentation = lockstep_check.lockstep_errors(
            self.contract, {"CHANGELOG.md", "requirements-validation.txt"}
        )
        self.assertEqual(documentation, [])
        self.assertEqual(
            errors,
            ["controlled publication files changed without maintained documentation"],
        )

    def test_double_star_matches_nested_paths(self) -> None:
        self.assertTrue(
            lockstep_check.path_matches(
                "release-assurance/schemas/release-policy.schema.json",
                "release-assurance/**",
            )
        )
        self.assertFalse(
            lockstep_check.path_matches("README.md", "release-assurance/**")
        )


if __name__ == "__main__":
    unittest.main()
