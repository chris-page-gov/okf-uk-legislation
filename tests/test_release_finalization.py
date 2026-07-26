from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finalize_release_candidate as finalization  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(finalization.render(value))


def role_material(path: Path, role: str) -> dict[str, object]:
    return {"role": role, **finalization.material(path, path.name)}


class FinalizationFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.contract = finalization.load_json(finalization.DEFAULT_CONTRACT)
        self.commit = "a" * 40
        self.tree = "b" * 40
        self.inventory = "c" * 64
        self.explorer_commit = "d" * 40
        self.snapshot_digest = "e" * 64
        self.archive_name = self.contract["archive"]["filename"]
        self.reproduction_dir = root / "reproduction"
        self.reproduction_dir.mkdir()
        self.explorer_dir = root / "explorer"
        self.security_dir = root / "security"
        self.accessibility_dir = root / "accessibility"
        self.performance_dir = root / "performance"
        for directory in (
            self.explorer_dir,
            self.security_dir,
            self.accessibility_dir,
            self.performance_dir,
        ):
            directory.mkdir()
        self.runtime = self._runtime_document()
        self.runtime_body = finalization.render(self.runtime)
        self.runtime_paths: dict[str, Path] = {}
        for name, directory in (
            ("explorer", self.explorer_dir),
            ("accessibility", self.accessibility_dir),
            ("performance", self.performance_dir),
        ):
            path = directory / "explorer-runtime-acceptance.json"
            path.write_bytes(self.runtime_body)
            self.runtime_paths[name] = path
        self._build_embedded_documents()
        self._seal_archive()
        self._write_reproduction_evidence()
        self._write_explorer_evidence()
        self._write_security_evidence()
        self._write_accessibility_evidence()
        self._write_performance_evidence()

    def _runtime_document(self) -> dict[str, object]:
        browsers = ["chrome", "firefox", "webkit"]
        pass_summary = {
            "checks_total": 1,
            "checks_passed": 1,
            "checks_failed": 0,
            "all_passed": True,
        }
        gates: dict[str, object] = {
            "startup_transfer": {
                "status": "passed",
                "limit_bytes": 1048576,
                "observed_max_bytes": 120,
                "browser_values": {
                    "chrome": 100,
                    "firefox": 110,
                    "webkit": 120,
                },
            },
            "cold_search": {
                "status": "passed",
                "limit_ms": 3000,
                "observed_max_ms": 300,
                "browser_values": {
                    "chrome": 280,
                    "firefox": 300,
                    "webkit": 290,
                },
            },
            "warm_search": {
                "status": "passed",
                "limit_ms": 1000,
                "observed_max_ms": 80,
                "browser_values": {
                    "chrome": 70,
                    "firefox": 80,
                    "webkit": 75,
                },
            },
            "browser_memory": {
                "status": "passed",
                "limit_bytes": 268435456,
                "observed_max_bytes": 1024,
            },
        }
        for gate_id in (
            "federation_and_child",
            "graph_relationship_rendering",
            "model_assisted_styling_and_filtering",
            "live_reconciliation_states",
            "facet_count_colour_and_space",
            "keyboard",
            "accessibility",
        ):
            gates[gate_id] = {"status": "passed"}
        gates["cross_browser"] = {
            "status": "passed",
            "required": browsers,
            "completed": browsers,
        }
        return {
            "schema": "okf-explorer-runtime-acceptance.v2",
            "measured_at": "2026-07-26T04:00:00Z",
            "status": "passed",
            "candidate": {
                "repository": self.contract["candidate"]["repository"],
                "commit": self.commit,
                "tree": self.tree,
                "bundle_tree_sha256": self.inventory,
            },
            "explorer": {
                "repository": self.contract["explorer"]["repository"],
                "tag": self.contract["explorer"]["required_tag"],
                "commit": self.explorer_commit,
            },
            "runtime": {"status": "passed", "summary": pass_summary},
            "cross_engine": {
                "status": "passed",
                "required": browsers,
                "completed": browsers,
            },
            "accessibility": {
                "status": "passed",
                "serious_or_critical_total": 0,
                "browsers": [
                    {
                        "browser": browser,
                        "run_status": "passed",
                        "serious_or_critical": 0,
                    }
                    for browser in browsers
                ],
            },
            "performance": {
                "status": "passed",
                "summary": {
                    "checks_total": 4,
                    "checks_passed": 4,
                    "checks_failed": 0,
                    "all_passed": True,
                },
            },
            "integrity": {
                "status": "passed",
                "summary": {
                    "checks_total": 2,
                    "checks_passed": 2,
                    "checks_failed": 0,
                    "all_passed": True,
                },
                "checks": [
                    {"id": "bundle", "status": "passed"},
                    {"id": "explorer", "status": "passed"},
                ],
            },
            "scope": "Exact frozen fixture publication.",
            "runner": {"path": "runner.mjs"},
            "inputs": {
                "bundle_root": "bundle",
                "federation_descriptor": {},
                "legislation_descriptor": {},
                "explorer_build": {},
            },
            "outputs": {"receipt": "receipt.json", "screenshots": []},
            "gates": gates,
            "browsers": [{"browser": browser} for browser in browsers],
            "failures": [],
            "limitations": [],
        }

    def _build_embedded_documents(self) -> None:
        self.ledger_body = (
            ROOT / "release-assurance" / "implementation-traceability.json"
        ).read_bytes()
        self.ledger = json.loads(self.ledger_body)
        report = {
            "schema": "okf-release-report.v1",
            "status": "passed",
            "gate": "GATE-12",
            "generated_at": "2026-07-26T04:00:00Z",
            "release": {"archive": self.archive_name},
            "sections": {
                key: {"status": "passed"}
                for key in (
                    "relationship_composition",
                    "coverage_and_freshness",
                    "gaps",
                    "licence_and_access_escalations",
                    "evaluation",
                    "model_cost",
                    "yaml_ld_mime_exception",
                )
            },
            "checksum_binding": {"sha256": "f" * 64},
            "limitations": ["External publication gates remain pending."],
        }
        report_body = finalization.render(report)
        report_material = {
            "path": "bundle/release-assurance/release-report.json",
            "bytes": len(report_body),
            "sha256": finalization.sha256_bytes(report_body),
        }
        gate_rows = []
        embedded = set(finalization.EMBEDDED_RC_GATES)
        for number in range(1, 15):
            gate_id = f"GATE-{number:02d}"
            gate_rows.append(
                {
                    "id": gate_id,
                    "group": "validation",
                    "evidence_plane": (
                        "embedded" if gate_id in embedded else "external"
                    ),
                    "status": "passed" if gate_id in embedded else "pending",
                }
            )
        release_gates = {
            "schema": "okf-release-gates.v1",
            "gates": gate_rows,
        }
        state_rows = [
            {key: value for key, value in row.items() if key != "evidence_plane"}
            for row in gate_rows
        ]
        state = {
            "schema": "okf-release-state.v1",
            "current_state": "validated",
            "maximum_evidenced_state": "validated",
            "fail_closed": True,
            "state_consistent": True,
            "gate_counts": {"passed": 7, "pending": 7},
            "gates": state_rows,
            "embedded_state": {
                "release_report": report_material,
                "gates": {"GATE-12": "passed"},
            },
        }
        self.embedded = {
            "release_state": state,
            "release_gates": release_gates,
            "implementation_traceability": self.ledger,
            "release_report": report,
        }

    def _seal_archive(self) -> None:
        tar_buffer = io.BytesIO()
        prefix = self.archive_name.removesuffix(".tar.zst")
        with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
            for key, relative in finalization.EMBEDDED_RELEASE_FILES.items():
                body = (
                    self.ledger_body
                    if key == "implementation_traceability"
                    else finalization.render(self.embedded[key])
                )
                info = tarfile.TarInfo(f"{prefix}/{relative}")
                info.size = len(body)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(body))
        self.tar_body = tar_buffer.getvalue()
        archive_body = zstandard.ZstdCompressor(
            level=1, write_checksum=True
        ).compress(self.tar_body)
        self.archive_path = self.reproduction_dir / self.archive_name
        self.archive_path.write_bytes(archive_body)
        self.archive_material = finalization.material(
            self.archive_path, self.archive_name
        )

    def _write_reproduction_evidence(self) -> None:
        package = {
            "schema": "okf-release-package-manifest.v1",
            "commit": self.commit,
            "tree": self.tree,
            "archive": {
                "filename": self.archive_name,
                "format": "application/zstd",
                "content_profile": "application/x-tar",
                "bytes": self.archive_material["bytes"],
                "sha256": self.archive_material["sha256"],
                "normalized_tar_bytes": len(self.tar_body),
                "normalized_tar_sha256": finalization.sha256_bytes(
                    self.tar_body
                ),
                "compression_ratio": (
                    len(self.tar_body) / self.archive_material["bytes"]
                ),
                "zstandard": {
                    "distribution": "zstandard",
                    "version": zstandard.__version__,
                    "level": 1,
                    "threads": 0,
                    "checksum": True,
                    "content_size": True,
                    "dictionary_id": False,
                },
                "validation": {
                    "safe_paths": True,
                    "regular_files_only": True,
                    "bounded_members": True,
                    "bounded_uncompressed_bytes": True,
                    "all_member_hashes_match": True,
                },
            },
            "publication": {
                "files": 4,
                "bytes": 100,
                "inventory_sha256": self.inventory,
            },
            "semantic_digests": [
                {
                    "id": "fixture",
                    "yaml_ld": {
                        "path": "fixture.yamlld",
                        "bytes": 1,
                        "sha256": "1" * 64,
                    },
                    "json_ld": {
                        "path": "fixture.jsonld",
                        "bytes": 1,
                        "sha256": "2" * 64,
                    },
                    "canonical_nquads_sha256": "3" * 64,
                    "canonical_nquads_bytes": 1,
                    "canonical_nquads_statements": 1,
                    "representations_equivalent": True,
                }
            ],
            "promotion": {
                "candidate_tag": self.contract["candidate"]["rc_tag"],
                "final_tag": self.contract["candidate"]["final_tag"],
                "asset_filename": self.archive_name,
                "asset_name_preserved": True,
                "archive_bytes_reused": True,
                "rebuild_prohibited": True,
                "rename_prohibited": True,
                "promote_by_sha256": self.archive_material["sha256"],
                "rule": "Reuse the exact immutable archive.",
            },
        }
        self.package_path = self.reproduction_dir / "release-package-manifest.json"
        write_json(self.package_path, package)
        schema_materials = [
            finalization.material(path, relative)
            for relative, path in sorted(
                finalization.finalization_schema_paths(self.contract).items()
            )
        ]
        provenance = {
            "schema": "okf-reproduction-provenance-inputs.v1",
            "commit": self.commit,
            "tree": self.tree,
            "commit_time": "2026-07-26T04:00:00Z",
            "controller": finalization.material(
                ROOT / "scripts" / "reproduce_release_candidate.py",
                "scripts/reproduce_release_candidate.py",
            ),
            "profile": finalization.material(
                ROOT / "release-assurance" / "reproduction-profile.json",
                "release-assurance/reproduction-profile.json",
            ),
            "dependency_lock": finalization.material(
                ROOT / "requirements-validation.txt",
                "requirements-validation.txt",
            ),
            "dependencies": [
                {
                    "name": "jsonschema",
                    "required": "1",
                    "installed": "1",
                    "matches": True,
                }
            ],
            "command_scripts": [
                finalization.material(
                    ROOT / "scripts" / "build_checksums.py",
                    "scripts/build_checksums.py",
                )
            ],
            "commands": [
                {
                    "index": 1,
                    "category": "validation_commands",
                    "argv": ["python", "check.py"],
                    "exit_code": 0,
                    "log": "logs/01-check.log",
                    "log_identity_note": "Fixture log.",
                }
            ],
            "environment": {
                "python": {
                    "major": sys.version_info.major,
                    "minor": sys.version_info.minor,
                    "micro": sys.version_info.micro,
                },
                "zstandard": {
                    "distribution": "zstandard",
                    "version": zstandard.__version__,
                    "module_version": zstandard.__version__,
                    "level": 1,
                    "threads": 0,
                },
                "source_date_epoch": 0,
                "timezone": "UTC",
                "locale": "C",
                "credentials_inherited": False,
                "diagnostic_logs_identity_bearing": False,
                "network_guard": {
                    "kind": "python-sitecustomize-socket-and-cli-guard",
                    "sha256": "4" * 64,
                },
            },
            "network_policy": {
                "dependency_installation_during_run": False,
                "build_commands_are_offline": True,
                "credentials_inherited": False,
                "python_socket_guard": True,
                "network_cli_guard": True,
            },
            "finalization_controller": finalization.material(
                finalization.FINALIZER_PATH,
                "scripts/finalize_release_candidate.py",
            ),
            "release_observation_controller": finalization.material(
                finalization.RELEASE_OBSERVATION_CONTROLLER_PATH,
                finalization.CANONICAL_RELEASE_OBSERVATION_CONTROLLER,
            ),
            "finalization_contract": finalization.material(
                finalization.DEFAULT_CONTRACT,
                "release-assurance/external-finalization-contract.json",
            ),
            "finalization_schemas": schema_materials,
        }
        self.provenance_path = self.reproduction_dir / "provenance-inputs.json"
        write_json(self.provenance_path, provenance)
        runtime_material = finalization.material(
            self.runtime_paths["explorer"],
            "release-assurance/explorer-runtime-acceptance.json",
        )
        reproduction = {
            "schema": "okf-reproduction-receipt.v1",
            "status": "passed",
            "run_id": "1" * 24,
            "generated_at": "2026-07-26T04:00:00Z",
            "timestamp_basis": "Fixture timestamp.",
            "candidate": {
                "requested_ref": self.commit,
                "commit": self.commit,
                "tree": self.tree,
                "exact_ref": True,
                "declared_frozen": True,
                "fixture": False,
            },
            "environment": {
                "python": {
                    "major": sys.version_info.major,
                    "minor": sys.version_info.minor,
                    "micro": sys.version_info.micro,
                },
                "dependencies_exact": True,
                "zstandard": {
                    "distribution": "zstandard",
                    "version": zstandard.__version__,
                    "module_version": zstandard.__version__,
                    "level": 1,
                    "threads": 0,
                },
                "network_access_required": False,
                "network_access_guarded": True,
                "network_guard_sha256": "4" * 64,
                "credentials_inherited": False,
            },
            "comparison": {
                "byte_identical": True,
                "semantic_identical": True,
                "candidate_inventory_sha256": self.inventory,
                "rebuilt_inventory_sha256": self.inventory,
                "files": package["publication"]["files"],
                "bytes": package["publication"]["bytes"],
                "semantic_digests": package["semantic_digests"],
            },
            "archive": package["archive"],
            "outputs": {
                "archive": self.archive_name,
                "release_package_manifest": {
                    "filename": self.package_path.name,
                    "bytes": self.package_path.stat().st_size,
                    "sha256": finalization.sha256_file(self.package_path),
                },
                "provenance_inputs": {
                    "filename": self.provenance_path.name,
                    "bytes": self.provenance_path.stat().st_size,
                    "sha256": finalization.sha256_file(self.provenance_path),
                },
            },
            "required_receipts": [
                {
                    "id": "okf-explorer-runtime-v0.5.0",
                    "schema": "okf-explorer-runtime-acceptance.v2",
                    "material": runtime_material,
                    "assertions": [
                        {
                            "pointer": "/status",
                            "equals": "passed",
                            "passed": True,
                        }
                    ],
                    "status": "passed",
                }
            ],
            "release_gate": {
                "gate": "GATE-06",
                "eligible": True,
                "reason": "Exact frozen candidate reproduced.",
            },
            "ledger_mutated": False,
        }
        self.reproduction_path = self.reproduction_dir / "reproduction-receipt.json"
        write_json(self.reproduction_path, reproduction)

    def _observation(
        self,
        directory: Path,
        *,
        repository: str,
        tag: str,
        commit: str,
        filename: str,
        asset: bool,
    ) -> tuple[Path, Path | None, str | None]:
        directory.mkdir(parents=True, exist_ok=True)
        release_id = 100 + len(tag)
        asset_id = 200 + len(tag)
        release_url = (
            f"{repository}/releases/download/{tag}/{self.archive_name}"
            if asset
            else None
        )
        asset_rows = []
        asset_path: Path | None = None
        if asset:
            asset_path = directory / self.archive_name
            asset_path.write_bytes(self.archive_path.read_bytes())
            asset_rows = [
                {
                    "id": asset_id,
                    "name": self.archive_name,
                    "browser_download_url": release_url,
                    "size": asset_path.stat().st_size,
                }
            ]
        release_headers = directory / "release-headers.json"
        release_body = directory / "release-body.json"
        tag_headers = directory / "tag-headers.json"
        tag_body = directory / "tag-body.json"
        attempt = directory / "attempt-manifest.json"
        write_json(release_headers, {"etag": '"release"'})
        write_json(
            release_body,
            {
                "id": release_id,
                "html_url": f"{repository}/releases/tag/{tag}",
                "tag_name": tag,
                "draft": False,
                "assets": asset_rows,
            },
        )
        write_json(tag_headers, {"etag": '"tag"'})
        write_json(
            tag_body,
            {
                "ref": f"refs/tags/{tag}",
                "object": {"type": "commit", "sha": commit},
            },
        )
        attempt_materials = [
            finalization.material(release_headers, release_headers.name),
            finalization.material(release_body, release_body.name),
            finalization.material(tag_headers, tag_headers.name),
            finalization.material(tag_body, tag_body.name),
        ]
        asset_headers: Path | None = None
        if asset and asset_path is not None:
            asset_headers = directory / "asset-headers.json"
            write_json(asset_headers, {"etag": '"asset"'})
            attempt_materials.extend(
                [
                    finalization.material(asset_headers, asset_headers.name),
                    finalization.material(asset_path, asset_path.name),
                ]
            )
        write_json(
            attempt,
            {
                "schema": "okf-github-release-observation-attempt.v1",
                "status": "complete",
                "write_once": True,
                "repository": repository,
                "tag": tag,
                "expected_commit": commit,
                "materials": attempt_materials,
                "tool": {
                    "name": (
                        finalization.RELEASE_OBSERVATION_CONTROLLER_PATH.name
                    ),
                    "version": "fixture",
                    "sha256": finalization.sha256_file(
                        finalization.RELEASE_OBSERVATION_CONTROLLER_PATH
                    ),
                },
            },
        )
        observation: dict[str, object] = {
            "schema": "okf-github-release-observation.v1",
            "status": "verified",
            "observed_at": "2026-07-26T04:10:00Z",
            "repository": repository,
            "tag": tag,
            "expected_commit": commit,
            "release": {
                "api_url": (
                    f"https://api.github.com/repos/"
                    f"{repository.removeprefix('https://github.com/')}/"
                    f"releases/tags/{tag}"
                ),
                "http_status": 200,
                "release_id": release_id,
                "html_url": f"{repository}/releases/tag/{tag}",
                "tag_name": tag,
                "response_headers": finalization.material(
                    release_headers, release_headers.name
                ),
                "response_body": finalization.material(
                    release_body, release_body.name
                ),
            },
            "tag_resolution": {
                "ref_api_url": (
                    f"https://api.github.com/repos/"
                    f"{repository.removeprefix('https://github.com/')}/"
                    f"git/ref/tags/{tag}"
                ),
                "http_status": 200,
                "object_type": "commit",
                "object_sha": commit,
                "peeled_commit": commit,
                "response_headers": finalization.material(
                    tag_headers, tag_headers.name
                ),
                "response_bodies": [
                    finalization.material(tag_body, tag_body.name)
                ],
            },
            "integrity": {
                "attempt_manifest": finalization.material(attempt, attempt.name),
                "write_once": True,
            },
        }
        if asset and asset_path is not None and release_url is not None:
            assert asset_headers is not None
            observation["asset"] = {
                "name": self.archive_name,
                "asset_id": asset_id,
                "download_url": release_url,
                "http_status": 200,
                "bytes": asset_path.stat().st_size,
                "sha256": finalization.sha256_file(asset_path),
                "response_headers": finalization.material(
                    asset_headers, asset_headers.name
                ),
                "response_body": finalization.material(
                    asset_path, asset_path.name
                ),
            }
        observation_path = directory / filename
        write_json(observation_path, observation)
        return observation_path, asset_path, release_url

    def _write_explorer_evidence(self) -> None:
        observation_name = self.contract["release_observations"]["explorer"]
        self.explorer_observation, _, _ = self._observation(
            self.explorer_dir / "release",
            repository=self.contract["explorer"]["repository"],
            tag=self.contract["explorer"]["required_tag"],
            commit=self.explorer_commit,
            filename=observation_name,
            asset=False,
        )
        # Receipt-relative paths may use a subdirectory, while the canonical
        # leaf filenames remain fixed.
        observation_row = finalization.material(
            self.explorer_observation,
            f"release/{self.explorer_observation.name}",
        )
        runtime_row = finalization.material(
            self.runtime_paths["explorer"],
            self.runtime_paths["explorer"].name,
        )
        receipt = {
            "schema": "okf-explorer-release-receipt.v2",
            "status": "published",
            "repository": self.contract["explorer"]["repository"],
            "tag": self.contract["explorer"]["required_tag"],
            "commit": self.explorer_commit,
            "release_url": (
                f"{self.contract['explorer']['repository']}/releases/tag/"
                f"{self.contract['explorer']['required_tag']}"
            ),
            "materials": [
                {"role": "release_observation", **observation_row},
                {"role": "runtime", **runtime_row},
            ],
        }
        self.explorer_receipt = (
            self.explorer_dir / finalization.CANONICAL_INPUT_NAMES["explorer"]
        )
        write_json(self.explorer_receipt, receipt)

    def _write_security_evidence(self) -> None:
        findings_path = self.security_dir / "findings.json"
        coverage_path = self.security_dir / "coverage.json"
        manifest_path = self.security_dir / "scan-manifest.json"
        report_path = self.security_dir / "report.md"
        checks = self.contract["required_security_checks"]
        findings = {
            "documentType": "codex-security.findings",
            "schemaVersion": "1.0",
            "scanId": "scan-fixture",
            "findings": [],
        }
        coverage = {
            "documentType": "codex-security.coverage",
            "schemaVersion": "1.0",
            "scanId": "scan-fixture",
            "mode": "commit",
            "completeness": "complete",
            "inventoryStrategy": "repository",
            "includePaths": ["."],
            "excludePaths": [],
            "surfaces": [
                {
                    "id": check,
                    "label": check,
                    "disposition": "no_issue_found",
                    "receiptRefs": [],
                }
                for check in checks
            ],
            "explicitExclusions": [],
            "deferred": [],
            "openQuestions": [],
        }
        write_json(findings_path, findings)
        write_json(coverage_path, coverage)
        manifest = {
            "documentType": "codex-security.scan-manifest",
            "schemaVersion": "1.0",
            "scan": {
                "id": "scan-fixture",
                "producer": {"name": "codex-security-plugin", "version": "1"},
                "status": "completed",
                "startedAt": "2026-07-26T04:00:00Z",
                "completedAt": "2026-07-26T04:01:00Z",
                "sealedAt": "2026-07-26T04:01:00Z",
                "target": {
                    "kind": "git_diff",
                    "targetId": "fixture",
                    "displayName": "fixture",
                    "remote": self.contract["candidate"]["repository"],
                    "headRevision": self.commit,
                    "snapshotDigest": (
                        "codex-security-snapshot/v1:sha256:"
                        + self.snapshot_digest
                    ),
                },
                "scope": {"includePaths": ["."], "excludePaths": []},
                "coverageRef": "coverage.json",
                "findingsRef": "findings.json",
                "artifacts": [
                    {
                        "path": "findings.json",
                        "sha256": finalization.sha256_file(findings_path),
                        "mediaType": "application/json",
                    },
                    {
                        "path": "coverage.json",
                        "sha256": finalization.sha256_file(coverage_path),
                        "mediaType": "application/json",
                    },
                ],
            },
        }
        write_json(manifest_path, manifest)
        report_path.write_text("# Passed\n", encoding="utf-8")
        receipt = {
            "schema": "okf-security-assurance-receipt.v2",
            "status": "passed",
            "gate": "GATE-10",
            "scan_id": "scan-fixture",
            "candidate": {
                "repository": self.contract["candidate"]["repository"],
                "commit": self.commit,
                "tree": self.tree,
            },
            "scan_target": {
                "repository": self.contract["candidate"]["repository"],
                "commit": self.commit,
                "snapshot_digest": self.snapshot_digest,
            },
            "checks": checks,
            "finding_summary": {
                "reportable_total": 0,
                "unresolved_total": 0,
            },
            "materials": [
                role_material(manifest_path, "scan_manifest"),
                role_material(findings_path, "findings"),
                role_material(coverage_path, "coverage"),
                role_material(report_path, "report"),
            ],
            "assurance_boundary": "Exact frozen candidate.",
        }
        self.security_receipt = (
            self.security_dir / finalization.CANONICAL_INPUT_NAMES["security"]
        )
        write_json(self.security_receipt, receipt)

    @property
    def candidate_binding(self) -> dict[str, str]:
        return {
            "repository": self.contract["candidate"]["repository"],
            "commit": self.commit,
            "tree": self.tree,
            "bundle_tree_sha256": self.inventory,
        }

    @property
    def explorer_binding(self) -> dict[str, str]:
        return {
            "repository": self.contract["explorer"]["repository"],
            "tag": self.contract["explorer"]["required_tag"],
            "commit": self.explorer_commit,
        }

    def _write_accessibility_evidence(self) -> None:
        receipt = {
            "schema": "okf-accessibility-assurance-receipt.v2",
            "status": "passed",
            "gate": "GATE-07",
            "candidate": self.candidate_binding,
            "archive": self.archive_material,
            "explorer": self.explorer_binding,
            "browsers": ["chrome", "firefox", "webkit"],
            "keyboard_operable": True,
            "wcag": {
                "standard": "WCAG 2.2 AA",
                "serious_violations": 0,
                "critical_violations": 0,
            },
            "materials": [
                role_material(self.runtime_paths["accessibility"], "runtime")
            ],
            "assurance_boundary": "Runtime v2 receipt.",
        }
        self.accessibility_receipt = (
            self.accessibility_dir
            / finalization.CANONICAL_INPUT_NAMES["accessibility"]
        )
        write_json(self.accessibility_receipt, receipt)

    def _write_performance_evidence(self) -> None:
        receipt = {
            "schema": "okf-performance-assurance-receipt.v2",
            "status": "passed",
            "gate": "GATE-08",
            "candidate": self.candidate_binding,
            "archive": self.archive_material,
            "explorer": self.explorer_binding,
            "measurements": {
                "initial_transfer_bytes": 120,
                "cold_search_ms": 300,
                "warm_search_ms": 80,
                "browser_memory_bytes": 1024,
            },
            "materials": [
                role_material(self.runtime_paths["performance"], "runtime")
            ],
            "assurance_boundary": "Runtime v2 receipt.",
        }
        self.performance_receipt = (
            self.performance_dir
            / finalization.CANONICAL_INPUT_NAMES["performance"]
        )
        write_json(self.performance_receipt, receipt)

    def base_args(self) -> dict[str, object]:
        return {
            "contract_path": finalization.DEFAULT_CONTRACT,
            "reproduction_dir": self.reproduction_dir,
            "explorer_receipt_path": self.explorer_receipt,
            "security_receipt_path": self.security_receipt,
            "accessibility_receipt_path": self.accessibility_receipt,
            "performance_receipt_path": self.performance_receipt,
        }

    def authorize_rc(self) -> dict[str, object]:
        return finalization.assemble_receipt(
            command="authorize-rc", **self.base_args()
        )

    def set_embedded_gate(self, gate_id: str, status: str) -> None:
        for document_key in ("release_state", "release_gates"):
            for row in self.embedded[document_key]["gates"]:
                if row["id"] == gate_id:
                    row["status"] = status
        statuses = [
            row["status"] for row in self.embedded["release_state"]["gates"]
        ]
        self.embedded["release_state"]["gate_counts"] = {
            value: statuses.count(value) for value in sorted(set(statuses))
        }
        self._seal_archive()
        package = json.loads(self.package_path.read_text(encoding="utf-8"))
        package["archive"]["bytes"] = self.archive_material["bytes"]
        package["archive"]["sha256"] = self.archive_material["sha256"]
        package["promotion"]["promote_by_sha256"] = self.archive_material["sha256"]
        write_json(self.package_path, package)
        reproduction = json.loads(
            self.reproduction_path.read_text(encoding="utf-8")
        )
        reproduction["archive"] = package["archive"]
        reproduction["outputs"]["release_package_manifest"] = (
            {
                "filename": self.package_path.name,
                "bytes": self.package_path.stat().st_size,
                "sha256": finalization.sha256_file(self.package_path),
            }
        )
        write_json(self.reproduction_path, reproduction)
        self._write_accessibility_evidence()
        self._write_performance_evidence()

    def create_post_rc_evidence(self) -> dict[str, object]:
        pre_rc = self.authorize_rc()
        self.pre_rc_path = self.root / "pre-rc-authorization-receipt.json"
        self.pre_rc_path.write_bytes(finalization.render(pre_rc))
        self.public_attempt = self.root / "public-attempt"
        self.public_attempt.mkdir()
        public_candidate = {
            "repository": self.contract["candidate"]["repository"],
            "git_commit": self.commit,
            "bundle_tree_sha256": self.inventory,
            "release_tag": self.contract["candidate"]["rc_tag"],
            "explorer_release": self.contract["explorer"]["required_tag"],
        }
        write_json(
            self.public_attempt / "attempt.json",
            {"status": "passed", "candidate": public_candidate},
        )
        write_json(
            self.public_attempt / "projection.json",
            {
                "gate_evidence_status": "passed",
                "candidate": public_candidate,
                "summary": {
                    "routes_total": 1,
                    "routes_passed": 1,
                    "routes_failed": 0,
                    "cross_assertions_total": 1,
                    "cross_assertions_passed": 1,
                    "cross_assertions_failed": 0,
                },
            },
        )
        write_json(
            self.public_attempt / "route-manifest.json",
            {"candidate": public_candidate},
        )
        write_json(self.public_attempt / "integrity.json", {"status": "passed"})

        traceability_dir = self.root / "traceability"
        traceability_dir.mkdir()
        ledger_path = traceability_dir / "implementation-traceability.json"
        ledger_path.write_bytes(self.ledger_body)
        evidence_path = traceability_dir / "evidence.txt"
        evidence_path.write_text("evidence\n", encoding="utf-8")
        evidence = finalization.material(evidence_path, evidence_path.name)
        closures = []
        for row in self.ledger["requirements"]:
            disposition = "passed" if row["status"] == "verified" else "deferred"
            closure = {
                "id": row["id"],
                "frozen_status": row["status"],
                "disposition": disposition,
                "must_have": False,
                "rationale": "Fixture closure.",
                "evidence": [evidence],
            }
            if disposition == "deferred":
                closure["accepted_exception"] = {
                    "accepted": True,
                    "authority": "Fixture authority",
                    "decision_evidence": evidence,
                }
            closures.append(closure)
        traceability = {
            "schema": "okf-traceability-closure-receipt.v2",
            "status": "passed",
            "gate": "GATE-14",
            "candidate": {
                "repository": self.contract["candidate"]["repository"],
                "commit": self.commit,
                "tree": self.tree,
            },
            "requirements_total": len(closures),
            "requirements_closed": len(closures),
            "unresolved_must_haves": 0,
            "source_ledger": finalization.material(
                ledger_path, ledger_path.name
            ),
            "closures": closures,
            "closure_rule": "Every frozen requirement has a terminal disposition.",
        }
        self.traceability_receipt = (
            traceability_dir / finalization.CANONICAL_INPUT_NAMES["traceability"]
        )
        write_json(self.traceability_receipt, traceability)
        self.rc_observation, self.rc_asset, self.rc_url = self._observation(
            self.root / "rc-release",
            repository=self.contract["candidate"]["repository"],
            tag=self.contract["candidate"]["rc_tag"],
            commit=self.commit,
            filename=self.contract["release_observations"]["rc"],
            asset=True,
        )
        return {
            **self.base_args(),
            "pre_rc_authorization_path": self.pre_rc_path,
            "public_attempt_dir": self.public_attempt,
            "traceability_receipt_path": self.traceability_receipt,
            "rc_release_observation_path": self.rc_observation,
            "rc_asset_path": self.rc_asset,
            "rc_release_url": self.rc_url,
        }


class ReleaseFinalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="okf-finalization-", dir="/private/tmp"
        )
        self.fixture = FinalizationFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_authorize_rc_reconstructs_embedded_and_runtime_gates(self) -> None:
        receipt = self.fixture.authorize_rc()
        self.assertEqual("rc_eligible", receipt["state"])
        self.assertEqual("validated", receipt["embedded_validation"]["current_state"])
        for gate_id in finalization.EMBEDDED_RC_GATES:
            self.assertEqual("passed", receipt["gates"][gate_id])

    def test_pending_embedded_gate_blocks_rc_authorization(self) -> None:
        self.fixture.set_embedded_gate("GATE-12", "pending")
        with self.assertRaisesRegex(
            finalization.FinalizationError, "GATE-12.*differs"
        ):
            self.fixture.authorize_rc()

    def test_wrapper_measurement_is_reconstructed_from_runtime(self) -> None:
        receipt = json.loads(
            self.fixture.performance_receipt.read_text(encoding="utf-8")
        )
        receipt["measurements"]["warm_search_ms"] = 1
        write_json(self.fixture.performance_receipt, receipt)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "reconstructed performance measurements",
        ):
            self.fixture.authorize_rc()

    def test_security_coverage_tampering_with_updated_hashes_is_rejected(self) -> None:
        coverage_path = self.fixture.security_dir / "coverage.json"
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage["surfaces"][0]["disposition"] = "needs_follow_up"
        write_json(coverage_path, coverage)
        manifest_path = self.fixture.security_dir / "scan-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for row in manifest["scan"]["artifacts"]:
            if row["path"] == "coverage.json":
                row["sha256"] = finalization.sha256_file(coverage_path)
        write_json(manifest_path, manifest)
        receipt = json.loads(
            self.fixture.security_receipt.read_text(encoding="utf-8")
        )
        for row in receipt["materials"]:
            source = self.fixture.security_dir / row["path"]
            row["bytes"] = source.stat().st_size
            row["sha256"] = finalization.sha256_file(source)
        write_json(self.fixture.security_receipt, receipt)
        with self.assertRaisesRegex(
            finalization.FinalizationError, "security coverage"
        ):
            self.fixture.authorize_rc()

    def test_unbound_release_observation_controller_is_rejected(self) -> None:
        provenance = json.loads(
            self.fixture.provenance_path.read_text(encoding="utf-8")
        )
        provenance["release_observation_controller"]["sha256"] = "0" * 64
        write_json(self.fixture.provenance_path, provenance)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "release observation controller SHA-256",
        ):
            self.fixture.authorize_rc()

    def test_observation_attempt_from_different_controller_is_rejected(
        self,
    ) -> None:
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

        explorer_receipt = json.loads(
            self.fixture.explorer_receipt.read_text(encoding="utf-8")
        )
        for row in explorer_receipt["materials"]:
            if row["role"] == "release_observation":
                row.update(
                    {
                        "bytes": self.fixture.explorer_observation.stat().st_size,
                        "sha256": finalization.sha256_file(
                            self.fixture.explorer_observation
                        ),
                    }
                )
        write_json(self.fixture.explorer_receipt, explorer_receipt)

        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "release observation attempt tool SHA-256",
        ):
            self.fixture.authorize_rc()

    def test_declared_material_symlink_is_rejected_before_resolve(self) -> None:
        coverage_path = self.fixture.security_dir / "coverage.json"
        target = self.fixture.security_dir / "coverage-target.json"
        coverage_path.rename(target)
        try:
            os.symlink(target.name, coverage_path)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.assertRaisesRegex(
            finalization.FinalizationError, "symbolic link"
        ):
            self.fixture.authorize_rc()

    def test_default_contract_and_output_filename_are_enforced(self) -> None:
        alternate = Path(self.temporary.name) / "contract.json"
        alternate.write_bytes(finalization.DEFAULT_CONTRACT.read_bytes())
        with self.assertRaisesRegex(
            finalization.FinalizationError, "default finalization contract"
        ):
            finalization.require_default_contract(alternate)
        namespace = argparse.Namespace(
            command="authorize-rc",
            contract=finalization.DEFAULT_CONTRACT,
            receipt=Path(self.temporary.name) / "wrong.json",
            pre_rc_authorization=None,
            public_attempt=None,
            traceability_receipt=None,
            rc_release_observation=None,
            rc_asset=None,
            rc_release_url=None,
            final_promotion_authorization=None,
            final_release_observation=None,
            final_asset=None,
            final_release_url=None,
        )
        with self.assertRaisesRegex(
            finalization.FinalizationError, "output receipt filename"
        ):
            finalization.validate_cli_arguments(namespace)

    def test_write_once_converts_filesystem_errors(self) -> None:
        output = Path(self.temporary.name) / "external-finalization-receipt.json"
        with mock.patch.object(
            finalization.os, "link", side_effect=PermissionError("denied")
        ):
            with self.assertRaisesRegex(
                finalization.FinalizationError,
                "cannot write immutable finalization output",
            ):
                finalization.write_once(output, b"{}\n")

    def test_final_promotion_precedes_post_publication_finalization(self) -> None:
        post_args = self.fixture.create_post_rc_evidence()
        real_load_json = finalization.load_json

        def load_with_fixture_ledger(path: Path) -> dict[str, object]:
            document = real_load_json(path)
            if path.resolve() == finalization.DEFAULT_CONTRACT.resolve():
                document["traceability"]["frozen_ledger_sha256"] = (
                    finalization.sha256_bytes(self.fixture.ledger_body)
                )
            return document

        with mock.patch.object(
            finalization.deployed_probe, "verify_attempt", return_value=[]
        ), mock.patch.object(
            finalization, "load_json", side_effect=load_with_fixture_ledger
        ):
            promotion = finalization.assemble_receipt(
                command="authorize-final-promotion", **post_args
            )
        self.assertEqual("final_promotion_eligible", promotion["state"])
        promotion_path = (
            Path(self.temporary.name)
            / "final-promotion-authorization-receipt.json"
        )
        promotion_path.write_bytes(finalization.render(promotion))
        final_observation, final_asset, final_url = self.fixture._observation(
            Path(self.temporary.name) / "final-release",
            repository=self.fixture.contract["candidate"]["repository"],
            tag=self.fixture.contract["candidate"]["final_tag"],
            commit=self.fixture.commit,
            filename=self.fixture.contract["release_observations"]["final"],
            asset=True,
        )
        final_args = {
            **post_args,
            "final_promotion_authorization_path": promotion_path,
            "final_release_observation_path": final_observation,
            "final_asset_path": final_asset,
            "final_release_url": final_url,
        }
        with mock.patch.object(
            finalization.deployed_probe, "verify_attempt", return_value=[]
        ), mock.patch.object(
            finalization, "load_json", side_effect=load_with_fixture_ledger
        ):
            receipt = finalization.assemble_receipt(
                command="finalize", **final_args
            )
        self.assertEqual("published", receipt["state"])
        self.assertEqual(
            promotion["authorization_id"],
            receipt["final_promotion_authorization"]["authorization_id"],
        )


if __name__ == "__main__":
    unittest.main()
