from __future__ import annotations

import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import zstandard


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_pre_rc_assurance_receipts as builder  # noqa: E402
import finalize_release_candidate as finalization  # noqa: E402
import reproduce_release_candidate as reproduction  # noqa: E402

try:  # Standard module invocation from the repository root.
    from tests.test_release_finalization import (  # type: ignore[import-not-found]  # noqa: E402
        FinalizationFixture,
        write_json,
    )
except ModuleNotFoundError:  # ``unittest discover -s tests`` adds tests/ directly.
    from test_release_finalization import (  # type: ignore[no-redef]  # noqa: E402
        FinalizationFixture,
        write_json,
    )


class PreRcAssuranceReceiptBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        fixture_root = self.root / "fixture"
        fixture_root.mkdir()
        self.fixture = FinalizationFixture(fixture_root)
        self.output_dir = self.root / "pre-rc-assurance"
        runtime = self.runtime_document()
        self.fixture.contract["explorer"]["runtime_provenance"] = json.loads(
            json.dumps(self.runtime_provenance)
        )
        provenance = json.loads(
            self.fixture.provenance_path.read_text(encoding="utf-8")
        )
        provenance["explorer_runtime_provenance"] = json.loads(
            json.dumps(self.runtime_provenance)
        )
        write_json(self.fixture.provenance_path, provenance)
        reproduction = json.loads(
            self.fixture.reproduction_path.read_text(encoding="utf-8")
        )
        reproduction["outputs"]["provenance_inputs"] = {
            "filename": self.fixture.provenance_path.name,
            "bytes": self.fixture.provenance_path.stat().st_size,
            "sha256": finalization.sha256_file(
                self.fixture.provenance_path
            ),
        }
        write_json(self.fixture.reproduction_path, reproduction)
        self.write_runtime(runtime)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_production_tar_layout_is_readable_by_finalizer(self) -> None:
        publication = self.root / "production-layout" / "bundle"
        rows = []
        for key, relative in finalization.EMBEDDED_RELEASE_FILES.items():
            body = finalization.render({"key": key})
            path = publication / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            rows.append(
                {
                    "path": relative,
                    "bytes": len(body),
                    "sha256": finalization.sha256_bytes(body),
                }
            )
        rows.sort(key=lambda row: row["path"])

        prefix = "okf-uk-legislation-v0.3.0"
        tar_path = self.root / "production-layout.tar"
        reproduction.deterministic_tar(
            publication,
            {"rows": rows},
            tar_path,
            prefix=prefix,
            limits={"max_tar_bytes": 1024 * 1024},
        )
        archive_path = self.root / f"{prefix}.tar.zst"
        archive_path.write_bytes(
            zstandard.ZstdCompressor(level=1).compress(
                tar_path.read_bytes()
            )
        )

        documents, materials = finalization.read_embedded_release_files(
            archive_path,
            archive_path.name,
        )
        self.assertEqual(
            set(documents),
            set(finalization.EMBEDDED_RELEASE_FILES),
        )
        for key, relative in finalization.EMBEDDED_RELEASE_FILES.items():
            self.assertEqual(documents[key], {"key": key})
            self.assertEqual(
                materials[key]["path"],
                f"bundle/{relative}",
            )

    def test_legacy_root_layout_is_rejected(self) -> None:
        prefix = "okf-uk-legislation-v0.3.0"
        tar_path = self.root / "legacy-root-layout.tar"
        with tarfile.open(tar_path, mode="w") as archive:
            for key, relative in finalization.EMBEDDED_RELEASE_FILES.items():
                body = finalization.render({"key": key})
                info = tarfile.TarInfo(f"{prefix}/{relative}")
                info.size = len(body)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(body))
        archive_path = self.root / f"{prefix}.tar.zst"
        archive_path.write_bytes(
            zstandard.ZstdCompressor(level=1).compress(
                tar_path.read_bytes()
            )
        )

        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "sealed archive omits embedded release evidence",
        ):
            finalization.read_embedded_release_files(
                archive_path,
                archive_path.name,
            )

    def reproduction_context(self) -> dict[str, Any]:
        with mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.fixture.load_json_with_contract,
        ):
            context = builder._verify_reproduction(
                self.fixture.reproduction_dir
            )
        context["contract"] = json.loads(json.dumps(context["contract"]))
        context["contract"]["explorer"]["runtime_provenance"] = (
            self.runtime_provenance
        )
        return context

    def build(self) -> dict[str, Path]:
        context = self.reproduction_context()
        with mock.patch.object(
            builder, "_verify_reproduction", return_value=context
        ):
            return builder.build_pre_rc_assurance_receipts(
                reproduction_dir=self.fixture.reproduction_dir,
                runtime_path=self.fixture.runtime_paths["explorer"],
                explorer_observation_path=self.fixture.explorer_observation,
                pages_observation_path=self.fixture.pages_observation,
                output_dir=self.output_dir,
            )

    def runtime_document(self) -> dict[str, Any]:
        runtime = json.loads(
            self.fixture.runtime_paths["explorer"].read_text(encoding="utf-8")
        )
        runtime_root = self.fixture.runtime_paths["explorer"].parent

        def evidence(relative: str, body: bytes) -> dict[str, Any]:
            path = runtime_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            return {
                "path": relative,
                "bytes": len(body),
                "sha256": finalization.sha256_bytes(body),
            }

        runner = evidence(
            "apps/okf-explorer/scripts/run_legislation_runtime_acceptance.mjs",
            b"// fixture Explorer runtime controller\n",
        )
        runtime["runner"] = runner
        federation_file = evidence(
            "bundle/whole-law/okf-explorer.json",
            b'{"fixture":"federation"}\n',
        )
        federation = {
            **federation_file,
            "path": "whole-law/okf-explorer.json",
        }
        legislation_file = evidence(
            "bundle/okf-explorer.json",
            b'{"fixture":"legislation"}\n',
        )
        legislation = {
            **legislation_file,
            "path": "okf-explorer.json",
        }
        build_files = [
            evidence(f"explorer-build/{relative}", body)
            for relative, body in sorted(
                self.fixture.runtime_build_bodies.items()
            )
        ]
        build_source_materials = [
            {
                **row,
                "path": Path(str(row["path"]))
                .relative_to(builder.EXPLORER_BUILD_ROOT)
                .as_posix(),
            }
            for row in build_files
        ]
        build_tree_sha256 = finalization.sha256_bytes(
            builder._canonical_explorer_build_materials_bytes(
                build_source_materials
            )
        )
        build_manifest = evidence(
            builder.EXPLORER_BUILD_MANIFEST_PATH,
            builder._render_explorer_build_manifest(
                file_count=len(build_source_materials),
                tree_sha256=build_tree_sha256,
                materials=build_source_materials,
            ),
        )
        build_index = next(
            row
            for row in build_files
            if row["path"] == builder.EXPLORER_BUILD_INDEX_PATH
        )
        explorer_build = {
            "root": builder.EXPLORER_BUILD_ROOT,
            "manifest": build_manifest,
            "index": build_index,
            "files": len(build_source_materials),
            "sha256": build_tree_sha256,
            "algorithm": builder.EXPLORER_BUILD_ALGORITHM,
            "materials": build_files,
        }
        runtime["inputs"] = {
            "bundle_root": "bundle",
            "federation_descriptor": federation,
            "legislation_descriptor": legislation,
            "explorer_build": explorer_build,
        }
        screenshots = [
            evidence(
                builder.EXPECTED_SCREENSHOT_PATHS[0],
                b"\x89PNG\r\n\x1a\nfixture graph screenshot\n",
            ),
            evidence(
                builder.EXPECTED_SCREENSHOT_PATHS[1],
                b"\x89PNG\r\n\x1a\nfixture runtime screenshot\n",
            ),
        ]
        runtime["outputs"] = {
            "receipt": builder.RUNTIME_FILENAME,
            "screenshots": screenshots,
        }
        checks = [
            {
                "id": "federation_descriptor",
                "status": "passed",
                **federation,
            },
            {
                "id": "legislation_descriptor",
                "status": "passed",
                **legislation,
            },
            {
                "id": "explorer_build_manifest",
                "status": "passed",
                **build_manifest,
            },
            {
                "id": "explorer_build_materials",
                "status": "passed",
                "files": len(build_files),
            },
            {
                "id": "explorer_build_index",
                "status": "passed",
                "sha256": build_index["sha256"],
            },
            {
                "id": "explorer_build_tree",
                "status": "passed",
                "algorithm": explorer_build["algorithm"],
                "files": explorer_build["files"],
                "sha256": explorer_build["sha256"],
                "computed_sha256": explorer_build["sha256"],
            },
            *[
                {
                    "id": f"screenshot:{screenshot['path']}",
                    "status": "passed",
                    **screenshot,
                }
                for screenshot in screenshots
            ],
        ]
        runtime["integrity"] = {
            "status": "passed",
            "summary": {
                "checks_total": len(checks),
                "checks_passed": len(checks),
                "checks_failed": 0,
                "all_passed": True,
            },
            "checks": checks,
        }
        runtime["gates"]["accessibility"]["standard"] = builder.WCAG_STANDARD
        self.runtime_evidence = {
            row["path"]: (
                runtime_root / row["path"]
            ).read_bytes()
            for row in (
                runner,
                federation_file,
                legislation_file,
                build_manifest,
                *build_files,
                *screenshots,
            )
        }
        self.runtime_provenance = {
            "runner": json.loads(json.dumps(runner)),
            "site_assembly": json.loads(
                json.dumps(
                    self.fixture.contract["explorer"]["runtime_provenance"][
                        "site_assembly"
                    ]
                )
            ),
            "pages": {
                "workflow_path": ".github/workflows/pages.yml",
                "workflow_bytes": 2497,
                "workflow_sha256": (
                    "29a3dcbf2f0bfbe7b2cb03dd6101dcb2293419eb42cd035eba5ceed905791ea4"
                ),
                "run_id": self.fixture.contract["explorer"][
                    "pages_workflow_run_id"
                ],
                "run_attempt": 1,
                "commit": self.fixture.explorer_commit,
                "artifact_id": 8636948739,
                "artifact_name": "github-pages",
                "artifact_zip": {
                    "bytes": 4096,
                    "sha256": "7" * 64,
                },
                "artifact_tar": {
                    "bytes": 16384,
                    "sha256": "8" * 64,
                },
                "build_manifest": json.loads(json.dumps(build_manifest)),
                "build_index": json.loads(json.dumps(build_index)),
                "build_tree": {
                    "algorithm": builder.EXPLORER_BUILD_ALGORITHM,
                    "files": len(build_source_materials),
                    "sha256": build_tree_sha256,
                },
            },
        }
        return runtime

    def write_runtime(self, runtime: dict[str, Any]) -> None:
        write_json(self.fixture.runtime_paths["explorer"], runtime)
        self.fixture.runtime_body = finalization.render(runtime)

    def reseal_archive(
        self,
        extra_members: list[tuple[tarfile.TarInfo, bytes | None]] | None = None,
    ) -> None:
        tar_buffer = io.BytesIO()
        prefix = self.fixture.archive_name.removesuffix(".tar.zst")
        with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
            for key, relative in finalization.EMBEDDED_RELEASE_FILES.items():
                body = (
                    self.fixture.ledger_body
                    if key == "implementation_traceability"
                    else finalization.render(self.fixture.embedded[key])
                )
                info = tarfile.TarInfo(f"{prefix}/bundle/{relative}")
                info.size = len(body)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(body))
            for info, body in extra_members or []:
                archive.addfile(
                    info, None if body is None else io.BytesIO(body)
                )
        tar_body = tar_buffer.getvalue()
        archive_body = zstandard.ZstdCompressor(
            level=1, write_checksum=True
        ).compress(tar_body)
        self.fixture.archive_path.write_bytes(archive_body)
        self.fixture.archive_material = finalization.material(
            self.fixture.archive_path, self.fixture.archive_name
        )

        package = json.loads(
            self.fixture.package_path.read_text(encoding="utf-8")
        )
        package_archive = package["archive"]
        package_archive["bytes"] = len(archive_body)
        package_archive["sha256"] = finalization.sha256_bytes(archive_body)
        package_archive["normalized_tar_bytes"] = len(tar_body)
        package_archive["normalized_tar_sha256"] = (
            finalization.sha256_bytes(tar_body)
        )
        package_archive["compression_ratio"] = len(tar_body) / len(archive_body)
        package["promotion"]["promote_by_sha256"] = package_archive["sha256"]
        write_json(self.fixture.package_path, package)

        reproduction = json.loads(
            self.fixture.reproduction_path.read_text(encoding="utf-8")
        )
        reproduction["archive"] = package_archive
        reproduction["outputs"]["release_package_manifest"] = {
            "filename": self.fixture.package_path.name,
            "bytes": self.fixture.package_path.stat().st_size,
            "sha256": finalization.sha256_file(self.fixture.package_path),
        }
        write_json(self.fixture.reproduction_path, reproduction)

    def test_builds_receipts_accepted_by_finalizer_and_is_idempotent(
        self,
    ) -> None:
        receipts = self.build()
        before = {
            path.relative_to(self.output_dir).as_posix(): path.read_bytes()
            for path in self.output_dir.rglob("*")
            if path.is_file()
        }

        explorer = json.loads(receipts["explorer"].read_text(encoding="utf-8"))
        accessibility = json.loads(
            receipts["accessibility"].read_text(encoding="utf-8")
        )
        performance = json.loads(
            receipts["performance"].read_text(encoding="utf-8")
        )
        self.assertEqual(self.fixture.explorer_commit, explorer["commit"])
        self.assertEqual(self.fixture.candidate_binding, accessibility["candidate"])
        self.assertEqual(
            builder.WCAG_STANDARD, accessibility["wcag"]["standard"]
        )
        self.assertEqual(
            {
                "initial_transfer_bytes": 120,
                "cold_search_ms": 300,
                "warm_search_ms": 80,
                "browser_memory_bytes": 1024,
            },
            performance["measurements"],
        )
        self.assertEqual(
            self.fixture.runtime_body,
            (self.output_dir / builder.RUNTIME_FILENAME).read_bytes(),
        )
        expected_runtime_evidence = [
            {
                "path": relative,
                "bytes": len(body),
                "sha256": finalization.sha256_bytes(body),
            }
            for relative, body in sorted(self.runtime_evidence.items())
        ]
        self.assertEqual(
            expected_runtime_evidence,
            explorer["runtime_evidence"],
        )
        self.assertEqual(
            sorted(row["path"] for row in explorer["runtime_evidence"]),
            [row["path"] for row in explorer["runtime_evidence"]],
        )
        self.assertEqual(
            self.fixture.explorer_observation.read_bytes(),
            (
                self.output_dir
                / builder.RELEASE_DIRECTORY
                / self.fixture.explorer_observation.name
            ).read_bytes(),
        )
        self.assertEqual(
            {"release_observation", "pages_observation", "runtime"},
            {row["role"] for row in explorer["materials"]},
        )
        self.assertEqual(
            self.fixture.pages_observation.read_bytes(),
            (
                self.output_dir
                / builder.PAGES_DIRECTORY
                / self.fixture.pages_observation.name
            ).read_bytes(),
        )
        self.assertEqual(
            8, len(explorer["release_evidence"])
        )
        self.assertEqual(8, len(explorer["pages_evidence"]))
        for relative, body in self.runtime_evidence.items():
            self.assertEqual(
                body,
                (self.output_dir / relative).read_bytes(),
                relative,
            )

        with mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.fixture.load_json_with_contract,
        ):
            authorization = finalization.assemble_receipt(
                command="authorize-rc",
                contract_path=finalization.DEFAULT_CONTRACT,
                reproduction_dir=self.fixture.reproduction_dir,
                explorer_receipt_path=receipts["explorer"],
                security_receipt_path=self.fixture.security_receipt,
                accessibility_receipt_path=receipts["accessibility"],
                performance_receipt_path=receipts["performance"],
            )
        self.assertEqual("rc_eligible", authorization["state"])

        self.assertEqual(receipts, self.build())
        after = {
            path.relative_to(self.output_dir).as_posix(): path.read_bytes()
            for path in self.output_dir.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)

    def test_rejects_pages_contract_without_computed_tree_digest(
        self,
    ) -> None:
        tree = self.fixture.contract["pages_observation"]["archive"][
            "build"
        ]["tree"]
        tree.pop("computed_sha256")
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Pages build tree",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_pages_contract_with_divergent_computed_tree_digest(
        self,
    ) -> None:
        tree = self.fixture.contract["pages_observation"]["archive"][
            "build"
        ]["tree"]
        tree["computed_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Pages build tree",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_tampered_pages_zip(self) -> None:
        pages_zip = (
            self.fixture.pages_observation.parent
            / builder.pages_observation.ZIP_PATH
        )
        body = bytearray(pages_zip.read_bytes())
        body[-1] ^= 0x01
        pages_zip.write_bytes(bytes(body))
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Pages observation reconstruction failed",
        ):
            self.build()

    def test_rejects_missing_pages_closure_material(self) -> None:
        pages_root = self.fixture.pages_observation.parent
        missing = pages_root / builder.pages_observation.RUN_BODY_PATH
        missing.unlink()
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Pages observation reconstruction failed",
        ):
            self.build()

    def test_rejects_extra_pages_closure_material(self) -> None:
        extra = self.fixture.pages_observation.parent / "raw" / "extra.json"
        extra.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Pages observation reconstruction failed",
        ):
            self.build()

    def test_rejects_release_pages_asset_mismatch(self) -> None:
        context = self.reproduction_context()
        runtime = json.loads(
            self.fixture.runtime_paths["explorer"].read_text(
                encoding="utf-8"
            )
        )
        with mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.fixture.load_json_with_contract,
        ):
            release = finalization.verify_github_release_observation(
                observation_path=self.fixture.explorer_observation,
                contract=context["contract"],
                release_observation_controller=context[
                    "release_observation_controller"
                ],
                expected_repository=context["contract"]["explorer"][
                    "repository"
                ],
                expected_tag=context["contract"]["explorer"][
                    "required_tag"
                ],
                expected_commit=self.fixture.explorer_commit,
                expected_filename=self.fixture.explorer_observation.name,
                expected_tag_object=context["contract"]["explorer"][
                    "required_tag_object"
                ],
                expected_asset=context["contract"]["explorer"][
                    "release_asset"
                ],
            )
        release["asset"]["asset_id"] += 1
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Pages/release observed asset ID",
        ):
            builder._pages_evidence_bodies(
                pages_path=self.fixture.pages_observation,
                context=context,
                runtime=runtime,
                release_observation=release,
            )

    def test_rejects_pages_mutation_between_reconstruction_and_copy(
        self,
    ) -> None:
        original = builder.pages_observation._verify_existing
        calls = 0

        def mutate_after_first(
            directory: Path,
            profile: object,
        ) -> Path:
            nonlocal calls
            result = original(directory, profile)
            calls += 1
            if calls == 1:
                inventory = directory / builder.pages_observation.INVENTORY_PATH
                inventory.write_bytes(inventory.read_bytes() + b" ")
            return result

        with (
            mock.patch.object(
                builder.pages_observation,
                "_verify_existing",
                side_effect=mutate_after_first,
            ),
            self.assertRaisesRegex(
                finalization.FinalizationError,
                "retained Pages evidence|Pages observation changed",
            ),
        ):
            self.build()

    def test_rejects_tampered_existing_runtime_evidence_file(self) -> None:
        receipts = self.build()
        explorer = json.loads(receipts["explorer"].read_text(encoding="utf-8"))
        screenshot = next(
            row
            for row in explorer["runtime_evidence"]
            if row["path"].endswith(".png")
        )
        copied = self.output_dir / screenshot["path"]
        original = copied.read_bytes()
        copied.write_bytes(b"x" * len(original))

        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "refusing to replace different immutable",
        ):
            self.build()
        self.assertEqual(b"x" * len(original), copied.read_bytes())

    def test_finalizer_rejects_tampered_runtime_evidence_file(self) -> None:
        receipts = self.build()
        explorer = json.loads(receipts["explorer"].read_text(encoding="utf-8"))
        screenshot = next(
            row
            for row in explorer["runtime_evidence"]
            if row["path"].endswith(".png")
        )
        copied = self.output_dir / screenshot["path"]
        copied.write_bytes(b"x" * screenshot["bytes"])

        with mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.fixture.load_json_with_contract,
        ):
            with self.assertRaisesRegex(
                finalization.FinalizationError,
                "Explorer runtime screenshot 1 actual SHA-256",
            ):
                finalization.assemble_receipt(
                    command="authorize-rc",
                    contract_path=finalization.DEFAULT_CONTRACT,
                    reproduction_dir=self.fixture.reproduction_dir,
                    explorer_receipt_path=receipts["explorer"],
                    security_receipt_path=self.fixture.security_receipt,
                    accessibility_receipt_path=receipts["accessibility"],
                    performance_receipt_path=receipts["performance"],
                )

    def test_finalizer_independently_rejects_tampered_pages_zip(
        self,
    ) -> None:
        receipts = self.build()
        pages_zip = self.output_dir / builder.PAGES_DIRECTORY / (
            builder.pages_observation.ZIP_PATH
        )
        body = bytearray(pages_zip.read_bytes())
        body[-1] ^= 0x01
        pages_zip.write_bytes(bytes(body))
        with (
            mock.patch.object(
                finalization,
                "load_json",
                side_effect=self.fixture.load_json_with_contract,
            ),
            self.assertRaisesRegex(
                finalization.FinalizationError,
                "Pages observation reconstruction failed",
            ),
        ):
            finalization.assemble_receipt(
                command="authorize-rc",
                contract_path=finalization.DEFAULT_CONTRACT,
                reproduction_dir=self.fixture.reproduction_dir,
                explorer_receipt_path=receipts["explorer"],
                security_receipt_path=self.fixture.security_receipt,
                accessibility_receipt_path=receipts["accessibility"],
                performance_receipt_path=receipts["performance"],
            )

    def test_rejects_divergent_existing_output(self) -> None:
        receipts = self.build()
        receipts["performance"].write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "refusing to replace different immutable",
        ):
            self.build()

    def test_rejects_incomplete_existing_output_directory(self) -> None:
        self.output_dir.mkdir()
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "divergent pre-existing",
        ):
            self.build()

    def test_rejects_runtime_explorer_commit_not_required_by_contract(
        self,
    ) -> None:
        runtime = json.loads(
            self.fixture.runtime_paths["explorer"].read_text(encoding="utf-8")
        )
        runtime["explorer"]["commit"] = "e" * 40
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer runtime required commit",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_explorer_tag_object_not_required_by_contract(
        self,
    ) -> None:
        self.fixture.contract["explorer"]["required_tag_object"] = "f" * 40
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "required annotated Git tag object SHA",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_unsafe_unconsumed_archive_member(self) -> None:
        body = b"escape\n"
        info = tarfile.TarInfo("../../escape")
        info.size = len(body)
        self.reseal_archive([(info, body)])
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "safe relative path",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_unconsumed_archive_symlink(self) -> None:
        prefix = self.fixture.archive_name.removesuffix(".tar.zst")
        info = tarfile.TarInfo(f"{prefix}/ignored-link")
        info.type = tarfile.SYMTYPE
        info.linkname = "release-assurance/release-state.json"
        self.reseal_archive([(info, None)])
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "non-regular member",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_embedded_ledger_not_frozen_by_contract(self) -> None:
        self.fixture.ledger["review_poc"] = True
        self.fixture.ledger_body = finalization.render(self.fixture.ledger)
        self.reseal_archive()
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "embedded frozen traceability ledger SHA-256",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_missing_or_invalid_runtime_runner(self) -> None:
        baseline = self.runtime_document()
        cases: list[tuple[str, object | None, str]] = [
            ("missing", None, "required property"),
            ("empty", {}, "required property"),
            (
                "invalid digest",
                {
                    "path": "scripts/runner.mjs",
                    "bytes": 1,
                    "sha256": "not-a-digest",
                },
                "does not match",
            ),
        ]
        for label, runner, error in cases:
            with self.subTest(label=label):
                runtime = json.loads(json.dumps(baseline))
                if runner is None:
                    runtime.pop("runner")
                else:
                    runtime["runner"] = runner
                self.write_runtime(runtime)
                with self.assertRaisesRegex(
                    finalization.FinalizationError, error
                ):
                    self.build()
                self.assertFalse(self.output_dir.exists())

    def test_rejects_self_attested_fake_runner_and_hash(self) -> None:
        runtime = self.runtime_document()
        runner_path = (
            self.fixture.runtime_paths["explorer"].parent
            / runtime["runner"]["path"]
        )
        fake_body = b"// attacker-controlled runtime controller\n"
        runner_path.write_bytes(fake_body)
        runtime["runner"]["bytes"] = len(fake_body)
        runtime["runner"]["sha256"] = finalization.sha256_bytes(fake_body)
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "contract-bound Explorer runtime runner",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_runner_file_not_matching_declared_identity(self) -> None:
        runtime = self.runtime_document()
        runner_path = (
            self.fixture.runtime_paths["explorer"].parent
            / runtime["runner"]["path"]
        )
        original = runner_path.read_bytes()
        runner_path.write_bytes(b"x" * len(original))
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "runner actual SHA-256",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_hardlinked_runtime_evidence_file(self) -> None:
        runtime = self.runtime_document()
        runner_path = (
            self.fixture.runtime_paths["explorer"].parent
            / runtime["runner"]["path"]
        )
        os.link(runner_path, self.root / "runner-hardlink.mjs")
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "runner must not be hard-linked",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_missing_or_invalid_runtime_inputs(self) -> None:
        baseline = self.runtime_document()
        baseline_inputs = dict(baseline["inputs"])
        cases = (
            ("missing", None, "required property"),
            (
                "invalid descriptor",
                {
                    **baseline_inputs,
                    "federation_descriptor": {},
                },
                "required property",
            ),
            (
                "invalid build",
                {
                    **baseline_inputs,
                    "explorer_build": {
                        **baseline_inputs["explorer_build"],
                        "files": 0,
                    },
                },
                "minimum of 1",
            ),
        )
        for label, inputs, error in cases:
            with self.subTest(label=label):
                runtime = json.loads(json.dumps(baseline))
                if inputs is None:
                    runtime.pop("inputs")
                else:
                    runtime["inputs"] = inputs
                self.write_runtime(runtime)
                with self.assertRaisesRegex(
                    finalization.FinalizationError, error
                ):
                    self.build()
                self.assertFalse(self.output_dir.exists())

    def test_rejects_self_attested_fake_pages_build_index(self) -> None:
        runtime = self.runtime_document()
        index = runtime["inputs"]["explorer_build"]["index"]
        index_path = self.fixture.runtime_paths["explorer"].parent / index["path"]
        fake_body = b"<!doctype html><title>attacker build</title>\n"
        index_path.write_bytes(fake_body)
        index["bytes"] = len(fake_body)
        index["sha256"] = finalization.sha256_bytes(fake_body)
        for row in runtime["integrity"]["checks"]:
            if row["id"] == "explorer_build_index":
                row["sha256"] = index["sha256"]
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer build material closure",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_self_attested_replacement_build_closure(self) -> None:
        runtime = self.runtime_document()
        explorer_build = runtime["inputs"]["explorer_build"]
        material = next(
            row
            for row in explorer_build["materials"]
            if row["path"] != builder.EXPLORER_BUILD_INDEX_PATH
        )
        path = (
            self.fixture.runtime_paths["explorer"].parent
            / material["path"]
        )
        fake_body = b"export const attackerControlled = true;\n"
        path.write_bytes(fake_body)
        material["bytes"] = len(fake_body)
        material["sha256"] = finalization.sha256_bytes(fake_body)
        source_materials = [
            {
                **row,
                "path": Path(str(row["path"]))
                .relative_to(builder.EXPLORER_BUILD_ROOT)
                .as_posix(),
            }
            for row in explorer_build["materials"]
        ]
        tree_sha256 = finalization.sha256_bytes(
            builder._canonical_explorer_build_materials_bytes(
                source_materials
            )
        )
        manifest_path = (
            self.fixture.runtime_paths["explorer"].parent
            / builder.EXPLORER_BUILD_MANIFEST_PATH
        )
        manifest_path.write_bytes(
            builder._render_explorer_build_manifest(
                file_count=len(source_materials),
                tree_sha256=tree_sha256,
                materials=source_materials,
            )
        )
        explorer_build["manifest"] = finalization.material(
            manifest_path,
            builder.EXPLORER_BUILD_MANIFEST_PATH,
        )
        explorer_build["sha256"] = tree_sha256
        for row in runtime["integrity"]["checks"]:
            if row["id"] == "explorer_build_tree":
                row["sha256"] = tree_sha256
                row["computed_sha256"] = tree_sha256
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "contract-bound Explorer Pages build manifest",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_missing_explorer_build_material(self) -> None:
        runtime = self.runtime_document()
        material = runtime["inputs"]["explorer_build"]["materials"][0]
        (
            self.fixture.runtime_paths["explorer"].parent
            / material["path"]
        ).unlink()
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer build staged file set",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_extra_explorer_build_material(self) -> None:
        runtime = self.runtime_document()
        extra = (
            self.fixture.runtime_paths["explorer"].parent
            / builder.EXPLORER_BUILD_ROOT
            / "unlisted.js"
        )
        extra.write_bytes(b"throw new Error('unlisted build file');\n")
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer build staged file set",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_tampered_non_index_explorer_build_material(self) -> None:
        runtime = self.runtime_document()
        material = next(
            row
            for row in runtime["inputs"]["explorer_build"]["materials"]
            if row["path"] != builder.EXPLORER_BUILD_INDEX_PATH
        )
        path = (
            self.fixture.runtime_paths["explorer"].parent
            / material["path"]
        )
        path.write_bytes(b"x" * material["bytes"])
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer build material .* actual SHA-256",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_hardlinked_explorer_build_material(self) -> None:
        runtime = self.runtime_document()
        material = runtime["inputs"]["explorer_build"]["materials"][0]
        path = (
            self.fixture.runtime_paths["explorer"].parent
            / material["path"]
        )
        os.link(path, self.root / "explorer-build-hardlink")
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer build material .* must not be hard-linked",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_symlinked_explorer_build_material(self) -> None:
        runtime = self.runtime_document()
        material = runtime["inputs"]["explorer_build"]["materials"][0]
        path = (
            self.fixture.runtime_paths["explorer"].parent
            / material["path"]
        )
        target = self.root / "real-explorer-build-material"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer build evidence contains a symbolic link",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_nonregular_explorer_build_material(self) -> None:
        runtime = self.runtime_document()
        material = runtime["inputs"]["explorer_build"]["materials"][0]
        path = (
            self.fixture.runtime_paths["explorer"].parent
            / material["path"]
        )
        path.unlink()
        os.mkfifo(path)
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer build evidence contains a non-regular entry",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_finalizer_independently_rejects_tampered_build_material(
        self,
    ) -> None:
        receipts = self.build()
        explorer = json.loads(
            receipts["explorer"].read_text(encoding="utf-8")
        )
        material = next(
            row
            for row in explorer["runtime_evidence"]
            if row["path"].startswith(
                f"{builder.EXPLORER_BUILD_ROOT}/"
            )
            and row["path"] not in {
                builder.EXPLORER_BUILD_MANIFEST_PATH,
                builder.EXPLORER_BUILD_INDEX_PATH,
            }
        )
        copied = self.output_dir / material["path"]
        copied.write_bytes(b"x" * material["bytes"])
        with mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.fixture.load_json_with_contract,
        ):
            with self.assertRaisesRegex(
                finalization.FinalizationError,
                "Explorer build material .* actual SHA-256",
            ):
                finalization.assemble_receipt(
                    command="authorize-rc",
                    contract_path=finalization.DEFAULT_CONTRACT,
                    reproduction_dir=self.fixture.reproduction_dir,
                    explorer_receipt_path=receipts["explorer"],
                    security_receipt_path=self.fixture.security_receipt,
                    accessibility_receipt_path=receipts["accessibility"],
                    performance_receipt_path=receipts["performance"],
                )

    def test_finalizer_independently_rejects_extra_build_material(
        self,
    ) -> None:
        receipts = self.build()
        extra = (
            self.output_dir
            / builder.EXPLORER_BUILD_ROOT
            / "unlisted-after-copy.js"
        )
        extra.write_bytes(b"throw new Error('post-copy extra');\n")
        with mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.fixture.load_json_with_contract,
        ):
            with self.assertRaisesRegex(
                finalization.FinalizationError,
                "Explorer build staged file set",
            ):
                finalization.assemble_receipt(
                    command="authorize-rc",
                    contract_path=finalization.DEFAULT_CONTRACT,
                    reproduction_dir=self.fixture.reproduction_dir,
                    explorer_receipt_path=receipts["explorer"],
                    security_receipt_path=self.fixture.security_receipt,
                    accessibility_receipt_path=receipts["accessibility"],
                    performance_receipt_path=receipts["performance"],
                )

    def test_rejects_missing_or_invalid_runtime_screenshots(self) -> None:
        baseline = self.runtime_document()
        canonical = baseline["outputs"]["screenshots"]
        renamed = json.loads(json.dumps(canonical))
        renamed[0]["path"] = "output/playwright/renamed.png"
        invalid_digest = json.loads(json.dumps(canonical))
        invalid_digest[0]["sha256"] = "bad"
        cases: list[tuple[str, object | None, str]] = [
            ("missing", None, "required property"),
            ("wrong type", {}, "not of type 'array'"),
            ("empty", [], "too short"),
            ("one", canonical[:1], "too short"),
            ("extra", [*canonical, canonical[0]], "too long"),
            ("renamed", renamed, "was expected"),
            ("duplicate", [canonical[0], canonical[0]], "was expected|non-unique"),
            ("reversed", list(reversed(canonical)), "was expected"),
            ("invalid digest", invalid_digest, "does not match"),
        ]
        for label, screenshots, error in cases:
            with self.subTest(label=label):
                runtime = json.loads(json.dumps(baseline))
                if screenshots is None:
                    runtime["outputs"].pop("screenshots")
                else:
                    runtime["outputs"]["screenshots"] = screenshots
                self.write_runtime(runtime)
                with self.assertRaisesRegex(
                    finalization.FinalizationError, error
                ):
                    self.build()
                self.assertFalse(self.output_dir.exists())

    def test_rejects_declared_but_absent_runtime_screenshot(self) -> None:
        runtime = self.runtime_document()
        self.write_runtime(runtime)
        screenshot = (
            self.fixture.runtime_paths["explorer"].parent
            / runtime["outputs"]["screenshots"][0]["path"]
        )
        screenshot.unlink()
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "cannot inspect Explorer runtime screenshot 0 path component",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_hardlinked_runtime_screenshot(self) -> None:
        runtime = self.runtime_document()
        screenshot = runtime["outputs"]["screenshots"][0]
        path = (
            self.fixture.runtime_paths["explorer"].parent
            / screenshot["path"]
        )
        os.link(path, self.root / "runtime-screenshot-hardlink.png")
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "screenshot 0 must not be hard-linked",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_finalizer_rejects_hardlinked_copied_runtime_screenshot(
        self,
    ) -> None:
        receipts = self.build()
        runtime = json.loads(
            (self.output_dir / builder.RUNTIME_FILENAME).read_text(
                encoding="utf-8"
            )
        )
        screenshot = runtime["outputs"]["screenshots"][0]
        path = self.output_dir / screenshot["path"]
        os.link(path, self.root / "copied-runtime-screenshot-hardlink.png")
        with mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.fixture.load_json_with_contract,
        ):
            with self.assertRaisesRegex(
                finalization.FinalizationError,
                "screenshot 0 must not be hard-linked",
            ):
                finalization.assemble_receipt(
                    command="authorize-rc",
                    contract_path=finalization.DEFAULT_CONTRACT,
                    reproduction_dir=self.fixture.reproduction_dir,
                    explorer_receipt_path=receipts["explorer"],
                    security_receipt_path=self.fixture.security_receipt,
                    accessibility_receipt_path=receipts["accessibility"],
                    performance_receipt_path=receipts["performance"],
                )

    def test_rejects_noncanonical_runtime_integrity_check_order(self) -> None:
        runtime = self.runtime_document()
        checks = runtime["integrity"]["checks"]
        checks[-1], checks[-2] = checks[-2], checks[-1]
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "integrity check order",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_symlinked_runtime_evidence_file(self) -> None:
        runtime = self.runtime_document()
        screenshot = (
            self.fixture.runtime_paths["explorer"].parent
            / runtime["outputs"]["screenshots"][0]["path"]
        )
        target = self.root / "real-screenshot.png"
        target.write_bytes(screenshot.read_bytes())
        screenshot.unlink()
        screenshot.symlink_to(target)
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "screenshot 0 path contains a symbolic link component",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_arbitrary_runtime_integrity_ids(self) -> None:
        runtime = self.runtime_document()
        checks = runtime["integrity"]["checks"]
        for index, row in enumerate(checks):
            row["id"] = f"arbitrary-{index}"
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "integrity check ID set",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_runtime_integrity_material_mismatch(self) -> None:
        runtime = self.runtime_document()
        runtime["integrity"]["checks"][0]["sha256"] = "f" * 64
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "integrity check federation_descriptor differs",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_runtime_without_explicit_wcag_2_2_aa_evidence(
        self,
    ) -> None:
        runtime = self.runtime_document()
        runtime["gates"]["accessibility"].pop("standard")
        self.write_runtime(runtime)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "required property",
        ):
            self.build()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_nonfinite_runtime_browser_metrics(self) -> None:
        baseline = self.runtime_document()
        cases = (
            ("observed NaN", "observed_max_ms", float("nan")),
            ("browser infinity", "browser_values", float("inf")),
        )
        for label, field, value in cases:
            with self.subTest(label=label):
                runtime = json.loads(json.dumps(baseline))
                if field == "browser_values":
                    runtime["gates"]["cold_search"]["browser_values"][
                        "chrome"
                    ] = value
                else:
                    runtime["gates"]["cold_search"][field] = value
                self.write_runtime(runtime)
                with self.assertRaisesRegex(
                    finalization.FinalizationError, "non-finite"
                ):
                    self.build()
                self.assertFalse(self.output_dir.exists())

    def test_rejects_observation_from_unbound_controller(self) -> None:
        attempt_path = (
            self.fixture.explorer_observation.parent / "attempt-manifest.json"
        )
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt["tool"]["sha256"] = "0" * 64
        write_json(attempt_path, attempt)
        observation = json.loads(
            self.fixture.explorer_observation.read_text(encoding="utf-8")
        )
        observation["integrity"]["attempt_manifest"] = finalization.material(
            attempt_path, attempt_path.name
        )
        write_json(self.fixture.explorer_observation, observation)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "release observation attempt tool SHA-256",
        ):
            self.build()

    def test_rejects_tampered_release_package_manifest(self) -> None:
        package = json.loads(self.fixture.package_path.read_text(encoding="utf-8"))
        package["archive"]["sha256"] = "0" * 64
        write_json(self.fixture.package_path, package)
        with self.assertRaisesRegex(
            finalization.FinalizationError, "sealed archive sha256"
        ):
            self.build()

    def test_rejects_existing_hardlinked_output_file(self) -> None:
        receipts = self.build()
        alias = self.root / "performance-alias.json"
        os.link(receipts["performance"], alias)
        before = receipts["performance"].read_bytes()
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "hard-linked file",
        ):
            self.build()
        self.assertEqual(before, receipts["performance"].read_bytes())
        self.assertEqual(before, alias.read_bytes())

    def test_rejects_output_symlink_component_beneath_inferred_root(
        self,
    ) -> None:
        target = self.root / "real-output-parent"
        target.mkdir()
        linked_parent = self.root / "linked-output-parent"
        linked_parent.symlink_to(target, target_is_directory=True)
        output = linked_parent / "pre-rc-assurance"
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "symbolic link component",
        ):
            builder.build_pre_rc_assurance_receipts(
                reproduction_dir=self.fixture.reproduction_dir,
                runtime_path=self.fixture.runtime_paths["explorer"],
                explorer_observation_path=self.fixture.explorer_observation,
                pages_observation_path=self.fixture.pages_observation,
                output_dir=output,
            )
        self.assertFalse((target / output.name).exists())

    def test_rejects_output_symlink_component_beneath_declared_root(
        self,
    ) -> None:
        safe_root = self.root / "declared-root"
        safe_root.mkdir()
        target = safe_root / "real"
        target.mkdir()
        linked_parent = safe_root / "linked"
        linked_parent.symlink_to(target, target_is_directory=True)
        output = linked_parent / "pre-rc-assurance"
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "symbolic link component",
        ):
            builder.build_pre_rc_assurance_receipts(
                reproduction_dir=self.fixture.reproduction_dir,
                runtime_path=self.fixture.runtime_paths["explorer"],
                explorer_observation_path=self.fixture.explorer_observation,
                pages_observation_path=self.fixture.pages_observation,
                output_dir=output,
                safe_external_root=safe_root,
            )
        self.assertFalse((target / output.name).exists())

    def test_rejects_symbolic_link_runtime(self) -> None:
        link_dir = self.root / "linked-runtime"
        link_dir.mkdir()
        linked_runtime = link_dir / builder.RUNTIME_FILENAME
        linked_runtime.symlink_to(self.fixture.runtime_paths["explorer"])
        context = self.reproduction_context()
        with self.assertRaisesRegex(
            finalization.FinalizationError, "symbolic link"
        ):
            with mock.patch.object(
                builder, "_verify_reproduction", return_value=context
            ):
                builder.build_pre_rc_assurance_receipts(
                    reproduction_dir=self.fixture.reproduction_dir,
                    runtime_path=linked_runtime,
                    explorer_observation_path=self.fixture.explorer_observation,
                    pages_observation_path=self.fixture.pages_observation,
                    output_dir=self.output_dir,
                )


class ExplorerBuildManifestTests(unittest.TestCase):
    @staticmethod
    def manifest_body(
        materials: list[dict[str, Any]],
    ) -> bytes:
        tree_sha256 = finalization.sha256_bytes(
            builder._canonical_explorer_build_materials_bytes(materials)
        )
        return builder._render_explorer_build_manifest(
            file_count=len(materials),
            tree_sha256=tree_sha256,
            materials=materials,
        )

    def test_accepts_raw_unicode_code_point_order(self) -> None:
        paths = ["a.js", "\uffff.js", "\U00010000.js", "\U0001f600.js"]
        self.assertEqual(paths, sorted(paths))
        materials = [
            {
                "path": path,
                "bytes": index + 1,
                "sha256": f"{index + 1:064x}",
            }
            for index, path in enumerate(paths)
        ]
        parsed = builder._parse_explorer_build_manifest(
            self.manifest_body(materials)
        )
        self.assertEqual(materials, parsed["materials"])

    def test_rejects_non_code_point_material_order(self) -> None:
        paths = ["a.js", "\U00010000.js", "\uffff.js"]
        materials = [
            {
                "path": path,
                "bytes": index + 1,
                "sha256": f"{index + 1:064x}",
            }
            for index, path in enumerate(paths)
        ]
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "strictly sorted and unique",
        ):
            builder._parse_explorer_build_manifest(
                self.manifest_body(materials)
            )

    def test_rejects_noncanonical_manifest_bytes(self) -> None:
        materials = [
            {
                "path": "index.html",
                "bytes": 1,
                "sha256": "1" * 64,
            }
        ]
        canonical = self.manifest_body(materials)
        document = json.loads(canonical)
        compact = (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "canonical bytes",
        ):
            builder._parse_explorer_build_manifest(compact)

    def test_rejects_del_and_overlong_utf16_build_paths(self) -> None:
        cases = (
            "bad\u007f.js",
            f"{'😀' * 2049}.js",
        )
        for path in cases:
            with self.subTest(path_kind="del" if "\u007f" in path else "long"):
                materials = [
                    {
                        "path": path,
                        "bytes": 1,
                        "sha256": "1" * 64,
                    }
                ]
                body = self.manifest_body(materials)
                with self.assertRaises(finalization.FinalizationError):
                    builder._parse_explorer_build_manifest(body)
                with self.assertRaises(finalization.FinalizationError):
                    finalization.parse_explorer_build_manifest(body)

    def test_rejects_surrogate_build_paths(self) -> None:
        material = {
            "path": "bad\ud800.js",
            "bytes": 1,
            "sha256": "1" * 64,
        }
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "surrogate",
        ):
            builder._require_material_shape(material, "fixture material")
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "surrogate",
        ):
            finalization.runtime_material(material, "fixture material")


if __name__ == "__main__":
    unittest.main()
