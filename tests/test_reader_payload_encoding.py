from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_reader_transport as transport  # noqa: E402
import check_whole_law_okf as whole_law_checker  # noqa: E402
import reader_payload_encoding as encoding  # noqa: E402


class ReaderPayloadEncodingTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.bundle = Path(self.temporary_directory.name) / "bundle"
        self.bundle.mkdir()
        self.execution = self.bundle / encoding.ORIGINAL_PATH
        self.execution.parent.mkdir(parents=True)
        self.original = b'{ "exact": [1,  2], "unicode": "\xe2\x98\x83" }\n'
        self.execution.write_bytes(self.original)
        self.report = self.bundle / encoding.REPORT_PATH
        self.report.write_bytes(b"<html><code>answers.json</code></html>\n")
        (self.bundle / encoding.EXECUTION_INDEX_PATH).write_text(
            json.dumps({"latest_run_id": encoding.APPROVED_RUN_ID}), encoding="utf-8"
        )
        inner_files = []
        for relative in (encoding.ORIGINAL_PATH, encoding.REPORT_PATH, encoding.EXECUTION_INDEX_PATH):
            body = (self.bundle / relative).read_bytes()
            inner_files.append({
                "path": relative.removeprefix("whole-law/"),
                "bytes": len(body),
                "sha256": sha256(body).hexdigest(),
            })
        for name in ("okf-bundle.yamlld", "okf-bundle.jsonld", "okf-bundle.ttl"):
            path = self.bundle / "whole-law" / name
            path.write_bytes((name + " fixture\n").encode())
            body = path.read_bytes()
            inner_files.append({
                "path": name,
                "bytes": len(body),
                "sha256": sha256(body).hexdigest(),
            })
        integrity = {"schema": "fixture", "files": inner_files}
        (self.bundle / "whole-law/integrity.json").write_text(json.dumps(integrity), encoding="utf-8")
        self._write_checksums()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_checksums(self):
        rows = {}
        for path in sorted(self.bundle.rglob("*")):
            if path.is_file() and path.name != "checksums.json":
                body = path.read_bytes()
                rows[path.relative_to(self.bundle).as_posix()] = {
                    "bytes": len(body), "sha256": sha256(body).hexdigest(),
                }
        (self.bundle / "checksums.json").write_text(json.dumps({"files": rows}), encoding="utf-8")

    def _project_and_validate(self):
        manifest = encoding.project(self.bundle, "a" * 40)
        (self.bundle / "checksums.json").write_text(transport.build_checksums(self.bundle), encoding="utf-8")
        return manifest, encoding.validate(self.bundle)

    def test_projects_exact_original_bytes_and_binds_both_routes(self):
        manifest, paths = self._project_and_validate()
        self.assertEqual({encoding.ORIGINAL_PATH, encoding.REPORT_PATH}, paths)
        self.assertFalse((self.bundle / encoding.ORIGINAL_PATH).exists())
        compressed = (self.bundle / encoding.COMPRESSED_PATH).read_bytes()
        self.assertEqual(self.original, encoding.inflate_single_gzip(compressed, expected_bytes=len(self.original)))
        self.assertEqual(compressed, encoding.deterministic_gzip(self.original))
        self.assertEqual(encoding.ORIGINAL_PATH, manifest["ai_access"]["payload_path"])
        report = (self.bundle / encoding.REPORT_PATH).read_text(encoding="utf-8")
        self.assertIn("answers.json.gz", report)
        self.assertIn(manifest["payloads"][0]["source_url"], report)
        self.assertIn(encoding.ARCHIVE_FALLBACK, report)

    def test_rejects_unknown_mapping_missing_file_and_tampered_bytes(self):
        manifest, _ = self._project_and_validate()
        manifest["payloads"][0]["path"] = "whole-law/other/answers.json"
        (self.bundle / encoding.POLICY_PATH).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "approved answers object"):
            encoding.validate(self.bundle)

        manifest["payloads"][0]["path"] = encoding.ORIGINAL_PATH
        (self.bundle / encoding.POLICY_PATH).write_text(json.dumps(manifest), encoding="utf-8")
        (self.bundle / encoding.COMPRESSED_PATH).unlink()
        with self.assertRaisesRegex(ValueError, "regular contained file"):
            encoding.validate(self.bundle)

        (self.bundle / encoding.COMPRESSED_PATH).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "differs from its manifest"):
            encoding.validate(self.bundle)

    def test_rejects_trailing_members_and_decompression_bombs(self):
        compressed = encoding.deterministic_gzip(self.original)
        with self.assertRaisesRegex(ValueError, "exactly one gzip member"):
            encoding.inflate_single_gzip(compressed + b"trailing", expected_bytes=len(self.original))
        with self.assertRaisesRegex(ValueError, "exactly one gzip member"):
            encoding.inflate_single_gzip(compressed + encoding.deterministic_gzip(b""), expected_bytes=len(self.original))
        with self.assertRaisesRegex(ValueError, "exceeds its declared size"):
            encoding.inflate_single_gzip(encoding.deterministic_gzip(b"x" * 10_000), expected_bytes=8)
        with self.assertRaisesRegex(ValueError, "decompression bound"):
            encoding.inflate_single_gzip(compressed, expected_bytes=encoding.MAX_ORIGINAL_BYTES + 1)

    def test_canonical_integrity_requires_original_but_typed_mode_accepts_verified_encoding(self):
        errors = []
        whole_law_checker.check_integrity(errors, pack=self.bundle / "whole-law")
        self.assertEqual([], errors)

        encoding.project(self.bundle, "a" * 40)
        (self.bundle / "checksums.json").write_text(transport.build_checksums(self.bundle), encoding="utf-8")
        canonical_errors = []
        whole_law_checker.check_integrity(canonical_errors, pack=self.bundle / "whole-law")
        self.assertTrue(any("integrity target missing" in error for error in canonical_errors))
        typed_errors = []
        whole_law_checker.check_integrity(
            typed_errors, pack=self.bundle / "whole-law", typed_site_root=self.bundle
        )
        self.assertEqual([], typed_errors)

    def test_rejects_path_alias_and_unknown_commit(self):
        manifest, _ = self._project_and_validate()
        manifest["payloads"][0]["transport_path"] = "../../outside.json.gz"
        (self.bundle / encoding.POLICY_PATH).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "approved answers object"):
            encoding.validate(self.bundle)
        with self.assertRaisesRegex(ValueError, "full lowercase Git SHA"):
            encoding.project(self.bundle, "not-a-commit")

    def test_rejects_a_superseded_encoding_selection_before_mutating(self):
        (self.bundle / encoding.EXECUTION_INDEX_PATH).write_text(
            json.dumps({"latest_run_id": "eval-newer-execution"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "current evaluation execution"):
            encoding.project(self.bundle, "a" * 40)
        self.assertEqual(self.original, self.execution.read_bytes())
        self.assertFalse((self.bundle / encoding.COMPRESSED_PATH).exists())


if __name__ == "__main__":
    unittest.main()
