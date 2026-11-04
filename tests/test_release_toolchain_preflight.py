from __future__ import annotations

import hashlib
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


if __name__ == "__main__":
    unittest.main()
