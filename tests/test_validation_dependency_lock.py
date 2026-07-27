from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validation_dependency_lock import (  # noqa: E402
    DependencyLockError,
    VersionMismatch,
    compare_installed_versions,
    load_validation_dependency_lock,
    parse_direct_requirements_text,
    parse_locked_requirements_text,
)


DIRECT = ROOT / "requirements-validation.in"
LOCK = ROOT / "requirements-validation.txt"
GUIDE = ROOT / "docs" / "validation-dependency-lock.md"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / ".github" / "workflows" / "pages.yml",
    ROOT / ".github" / "workflows" / "drift.yml",
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def minimal_lock() -> str:
    return (
        "alpha==1.0 \\\n"
        f"    --hash=sha256:{HASH_A} \\\n"
        f"    --hash=sha256:{HASH_B}\n"
        "beta==2.0 \\\n"
        f"    --hash=sha256:{HASH_C}\n"
    )


class ValidationDependencyLockTests(unittest.TestCase):
    def test_lock_is_platform_scoped_and_hash_complete(self) -> None:
        header = "\n".join(LOCK.read_text(encoding="utf-8").splitlines()[:3])
        self.assertIn("uv pip compile", header)
        self.assertIn("--python-version 3.12", header)
        self.assertIn("--python-platform x86_64-manylinux_2_28", header)
        self.assertIn("--generate-hashes", header)
        self.assertIn("--only-binary :all:", header)
        self.assertIn("--exclude-newer 2026-07-27T00:00:00Z", header)
        self.assertIn("`uv 0.11.8`", GUIDE.read_text(encoding="utf-8"))

        dependency_lock = load_validation_dependency_lock(LOCK, DIRECT)
        self.assertEqual(len(dependency_lock.requirements), 52)
        self.assertEqual(len(dependency_lock.direct_requirements), 7)
        self.assertEqual(len(dependency_lock.transitive_names), 45)
        self.assertEqual(len(dependency_lock.artifact_hashes), 1159)
        self.assertEqual(
            dependency_lock.direct_names,
            (
                "jsonschema",
                "pyld",
                "pyshacl",
                "pyyaml",
                "rdflib",
                "yaml-ld",
                "zstandard",
            ),
        )
        self.assertEqual(
            tuple(
                requirement.name
                for requirement in dependency_lock.requirements
            ),
            tuple(
                sorted(
                    requirement.name
                    for requirement in dependency_lock.requirements
                )
            ),
        )
        self.assertEqual(
            dependency_lock.artifact_hashes,
            tuple(sorted(dependency_lock.artifact_hashes)),
        )

    def test_inventory_and_sbom_helpers_are_deterministic(self) -> None:
        dependency_lock = load_validation_dependency_lock(LOCK, DIRECT)
        inventory = dependency_lock.inventory()
        self.assertEqual(inventory, dependency_lock.inventory())
        self.assertEqual(inventory["package_count"], 52)
        self.assertEqual(inventory["artifact_hash_count"], 1159)
        self.assertEqual(
            dependency_lock.identity_digest,
            "9542649bd62f7064e1bf6bfc82b4db0bc3260015649fd20cc804077076bc0c97",
        )
        self.assertEqual(
            dependency_lock.artifact_hash_digest,
            "e8a43fc379630e059925a1a892476a23b7bccd0ca459d07da2015594755a191c",
        )

        components = dependency_lock.sbom_components()
        self.assertEqual(len(components), 52)
        self.assertEqual(
            [component["name"] for component in components],
            sorted(component["name"] for component in components),
        )
        self.assertEqual(
            components[0]["purl"],
            "pkg:pypi/annotated-doc@0.0.4",
        )
        direct_components = [
            component
            for component in components
            if component["properties"][0]["value"] == "direct"
        ]
        self.assertEqual(len(direct_components), 7)

    def test_installed_environment_comparison(self) -> None:
        dependency_lock = load_validation_dependency_lock(LOCK, DIRECT)
        installed = {
            requirement.name: requirement.version
            for requirement in dependency_lock.requirements
        }
        self.assertTrue(
            compare_installed_versions(dependency_lock, installed).matches
        )

        changed = dict(installed)
        changed["attrs"] = "25.0.0"
        comparison = compare_installed_versions(dependency_lock, changed)
        self.assertFalse(comparison.matches)
        self.assertEqual(
            comparison.mismatched,
            (VersionMismatch("attrs", "26.1.0", "25.0.0"),),
        )

        incomplete = dict(installed)
        incomplete.pop("attrs")
        incomplete["Local_Tooling"] = "1.0"
        comparison = compare_installed_versions(dependency_lock, incomplete)
        self.assertEqual(comparison.missing, ("attrs",))
        self.assertEqual(comparison.unexpected, ("local-tooling",))
        allowed = compare_installed_versions(
            dependency_lock,
            incomplete,
            allow_extra=("local-tooling",),
        )
        self.assertEqual(allowed.unexpected, ())

    def test_strict_lock_parser_accepts_only_canonical_hash_form(self) -> None:
        requirements = parse_locked_requirements_text(minimal_lock())
        self.assertEqual(
            tuple(requirement.identity for requirement in requirements),
            ("alpha==1.0", "beta==2.0"),
        )
        self.assertEqual(requirements[0].hashes, (HASH_A, HASH_B))

    def test_strict_lock_parser_rejects_unsafe_or_ambiguous_forms(self) -> None:
        invalid_locks = {
            "pip option": "--index-url https://example.invalid/simple\n",
            "url": (
                "alpha @ https://example.invalid/alpha.whl \\\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "vcs": "git+https://example.invalid/alpha.git\n",
            "editable": "-e https://example.invalid/alpha\n",
            "marker": (
                "alpha==1.0; python_version >= '3.12' \\\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "duplicate package": (
                "alpha==1.0 \\\n"
                f"    --hash=sha256:{HASH_A}\n"
                "alpha==1.0 \\\n"
                f"    --hash=sha256:{HASH_B}\n"
            ),
            "noncanonical name": (
                "Alpha_Beta==1.0 \\\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "noncanonical version": (
                "alpha==01.0 \\\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "unhashed": "alpha==1.0\n",
            "uppercase hash": (
                "alpha==1.0 \\\n"
                f"    --hash=sha256:{HASH_A.upper()}\n"
            ),
            "wrong algorithm": (
                "alpha==1.0 \\\n"
                f"    --hash=sha512:{HASH_A}\n"
            ),
            "short hash": (
                "alpha==1.0 \\\n"
                "    --hash=sha256:abc123\n"
            ),
            "duplicate hash": (
                "alpha==1.0 \\\n"
                f"    --hash=sha256:{HASH_A} \\\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "unsorted hashes": (
                "alpha==1.0 \\\n"
                f"    --hash=sha256:{HASH_B} \\\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "stray hash": f"    --hash=sha256:{HASH_A}\n",
            "stray continuation": "\\\n",
            "unfinished continuation": "alpha==1.0 \\\n",
            "comment in continuation": (
                "alpha==1.0 \\\n"
                "    # hashes follow\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "hash after final": (
                "alpha==1.0 \\\n"
                f"    --hash=sha256:{HASH_A}\n"
                f"    --hash=sha256:{HASH_B}\n"
            ),
            "unsorted packages": (
                "beta==2.0 \\\n"
                f"    --hash=sha256:{HASH_B}\n"
                "alpha==1.0 \\\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "trailing space": (
                "alpha==1.0 \\ \n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
            "tab": (
                "alpha==1.0 \\\n"
                f"\t--hash=sha256:{HASH_A}\n"
            ),
            "crlf": (
                "alpha==1.0 \\\r\n"
                f"    --hash=sha256:{HASH_A}\r\n"
            ),
            "missing final LF": minimal_lock().removesuffix("\n"),
        }
        for label, content in invalid_locks.items():
            with self.subTest(label=label):
                with self.assertRaises(DependencyLockError):
                    parse_locked_requirements_text(content)

    def test_direct_parser_rejects_non_pins_and_duplicate_aliases(self) -> None:
        direct = parse_direct_requirements_text(
            "Alpha_Beta==1.0\nzeta==2.0\n"
        )
        self.assertEqual(
            tuple(requirement.name for requirement in direct),
            ("alpha-beta", "zeta"),
        )

        invalid_direct = {
            "option": "--index-url https://example.invalid/simple\n",
            "url": "alpha @ https://example.invalid/alpha.whl\n",
            "marker": "alpha==1.0; python_version >= '3.12'\n",
            "editable": "-e ./alpha\n",
            "continuation": "alpha==1.0 \\\n",
            "duplicate alias": "alpha-beta==1.0\nAlpha_Beta==1.0\n",
            "unsorted": "zeta==1.0\nalpha==1.0\n",
            "noncanonical version": "alpha==01.0\n",
            "missing final LF": "alpha==1.0",
        }
        for label, content in invalid_direct.items():
            with self.subTest(label=label):
                with self.assertRaises(DependencyLockError):
                    parse_direct_requirements_text(content)

    def test_validation_workflows_enforce_hashes(self) -> None:
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                body = workflow.read_text(encoding="utf-8")
                self.assertEqual(body.count("--require-hashes"), 1)
                self.assertIn(
                    "--requirement requirements-validation.txt",
                    body,
                )
                self.assertIn(
                    "cache-dependency-path: requirements-validation.txt",
                    body,
                )


if __name__ == "__main__":
    unittest.main()
