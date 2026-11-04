from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preflight_release_toolchain as preflight


class ReleaseToolchainPreflightTests(unittest.TestCase):
    def test_rejects_non_assurance_bundle_changes(self) -> None:
        with mock.patch.object(preflight, "git", side_effect=[b"bundle/data/works.json\n", b""]):
            with self.assertRaisesRegex(RuntimeError, "non-assurance publication changes"):
                preflight.verify_preservation("a" * 40)

    def test_rejects_untracked_bundle_content(self) -> None:
        with mock.patch.object(preflight, "git", side_effect=[b"", b"bundle/new.json\n"]):
            with self.assertRaisesRegex(RuntimeError, "untracked"):
                preflight.verify_preservation("a" * 40)

    def test_rehashes_protected_bytes_and_allows_only_assurance(self) -> None:
        body = b"unchanged legal evidence\n"
        blob = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
        inventory = f"100644 blob {blob}\tbundle/data/works.json\0".encode()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "bundle/data/works.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(body)
            with mock.patch.object(preflight, "ROOT", root), mock.patch.object(
                preflight, "git", side_effect=[b"bundle/release-assurance/schema.json\n", b"", inventory]
            ):
                result = preflight.verify_preservation("a" * 40)
                self.assertEqual(1, result["protected_files"])
                self.assertEqual(len(body), result["protected_bytes"])
            target.write_bytes(b"altered legal evidence\n")
            with mock.patch.object(preflight, "ROOT", root), mock.patch.object(
                preflight, "git", side_effect=[b"", b"", inventory]
            ):
                with self.assertRaisesRegex(RuntimeError, "protected publication bytes changed"):
                    preflight.verify_preservation("a" * 40)

    def test_baseline_is_an_exact_revision_not_shell_or_revision_syntax(self) -> None:
        for invalid in ("HEAD", "main", "a" * 40 + "^", "--help", "a" * 39):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(RuntimeError, "exact full Git commit"):
                preflight.verify_preservation(invalid)

    def _inventory_preflight_fixture(self, root: Path, explorer_root: Path) -> dict:
        contract_dir = root / "release-assurance"
        contract_dir.mkdir(parents=True)
        (contract_dir / "external-finalization-contract.json").write_text(
            json.dumps({"explorer": {"required_commit": "a" * 40}}),
            encoding="utf-8",
        )
        (contract_dir / "reproduction-profile.json").write_text(
            json.dumps({"archive": {"max_files": 10}}),
            encoding="utf-8",
        )
        helper_path = "apps/okf-explorer/scripts/runtime_acceptance_contract.mjs"
        helper = explorer_root / helper_path
        helper.parent.mkdir(parents=True)
        helper.write_text("// pinned helper fixture\n", encoding="utf-8")
        helper_material = {
            "path": helper_path,
            "bytes": helper.stat().st_size,
            "sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
        }
        runtime = {
            "candidate": {"bundle_tree_sha256": "b" * 64},
            "invocation": {
                "executable_materials": {
                    "runtime_acceptance_contract": helper_material,
                },
                "repository_identity": {"candidate": {"bundle_tree": {}}},
                "snapshots": {"bundle": {}},
            },
        }
        inventory = {
            "rows": [{"path": "bundle/example.json", "bytes": 2, "sha256": "c" * 64}],
            "files": 1,
            "bytes": 2,
            "inventory_sha256": "b" * 64,
        }
        return runtime, inventory, helper_material

    def test_inventory_interoperability_rejects_wrong_or_dirty_explorer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "candidate"
            explorer_root = Path(temporary) / "explorer"
            root.mkdir()
            explorer_root.mkdir()
            runtime, _inventory, _helper_material = self._inventory_preflight_fixture(
                root, explorer_root
            )

            cases = (
                ("wrong checkout", "d" * 40, ""),
                ("dirty checkout", "a" * 40, " M changed.js\n"),
            )
            for label, observed, dirty in cases:
                with self.subTest(label=label):
                    with mock.patch.object(preflight, "ROOT", root), mock.patch.object(
                        preflight.subprocess,
                        "run",
                        side_effect=[
                            mock.Mock(stdout=observed),
                            mock.Mock(stdout=dirty),
                        ],
                    ), self.assertRaisesRegex(RuntimeError, "exact clean pinned Explorer checkout"):
                        preflight.verify_inventory_interoperability(
                            explorer_root, runtime
                        )

    def test_inventory_interoperability_rejects_native_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "candidate"
            explorer_root = Path(temporary) / "explorer"
            root.mkdir()
            explorer_root.mkdir()
            runtime, inventory, helper_material = self._inventory_preflight_fixture(
                root, explorer_root
            )
            native = {
                "algorithm": "sha256-canonical-json-inventory-v1",
                "files": inventory["files"],
                "bytes": inventory["bytes"],
                "sha256": "e" * 64,
            }
            process_results = [
                mock.Mock(stdout="a" * 40),
                mock.Mock(stdout=""),
                mock.Mock(stdout=json.dumps(native)),
            ]
            with mock.patch.object(preflight, "ROOT", root), mock.patch.object(
                preflight, "material", return_value=helper_material
            ), mock.patch.object(
                preflight.reproduction,
                "inventory_publication",
                return_value=inventory,
            ), mock.patch.object(
                preflight.subprocess, "run", side_effect=process_results
            ), self.assertRaisesRegex(
                RuntimeError, "producer/Explorer publication inventory mismatch"
            ):
                preflight.verify_inventory_interoperability(
                    explorer_root, runtime
                )


if __name__ == "__main__":
    unittest.main()
