from __future__ import annotations

import argparse
import copy
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finalize_release_candidate as finalization  # noqa: E402
import capture_github_pages_observation as pages_capture  # noqa: E402

try:
    from tests.test_github_pages_observation import (  # type: ignore[import-not-found]  # noqa: E402
        FakeTransport as PagesFakeTransport,
        fixture_archive,
        resolver as pages_resolver,
        responses as pages_responses,
    )
except ModuleNotFoundError:
    from test_github_pages_observation import (  # type: ignore[no-redef]  # noqa: E402
        FakeTransport as PagesFakeTransport,
        fixture_archive,
        resolver as pages_resolver,
        responses as pages_responses,
    )

REAL_LOAD_JSON = finalization.load_json


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(finalization.render(value))


def role_material(path: Path, role: str) -> dict[str, object]:
    return {"role": role, **finalization.material(path, path.name)}


def synthetic_security_schemas() -> dict[str, dict[str, object]]:
    """Return small producer schemas for the hermetic finalizer fixture."""

    artifact = {
        "type": "object",
        "required": ["path", "sha256", "mediaType"],
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "mediaType": {"type": "string", "minLength": 1},
        },
    }
    return {
        "scan_manifest": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["documentType", "schemaVersion", "scan"],
            "properties": {
                "documentType": {"const": "codex-security.scan-manifest"},
                "schemaVersion": {"const": "1.0"},
                "scan": {
                    "type": "object",
                    "required": [
                        "id",
                        "producer",
                        "status",
                        "startedAt",
                        "completedAt",
                        "sealedAt",
                        "target",
                        "scope",
                        "coverageRef",
                        "findingsRef",
                        "artifacts",
                    ],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "producer": {"type": "object"},
                        "status": {"const": "completed"},
                        "startedAt": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "completedAt": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "sealedAt": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "target": {"type": "object"},
                        "scope": {"type": "object"},
                        "coverageRef": {"const": "coverage.json"},
                        "findingsRef": {"const": "findings.json"},
                        "artifacts": {
                            "type": "array",
                            "minItems": 1,
                            "items": artifact,
                        },
                    },
                },
            },
        },
        "findings": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": [
                "documentType",
                "schemaVersion",
                "scanId",
                "findings",
            ],
            "properties": {
                "documentType": {"const": "codex-security.findings"},
                "schemaVersion": {"const": "1.0"},
                "scanId": {"type": "string", "minLength": 1},
                "findings": {"type": "array"},
            },
        },
        "coverage": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": [
                "documentType",
                "schemaVersion",
                "scanId",
                "mode",
                "completeness",
                "inventoryStrategy",
                "includePaths",
                "excludePaths",
                "surfaces",
                "explicitExclusions",
                "deferred",
                "openQuestions",
            ],
            "properties": {
                "documentType": {"const": "codex-security.coverage"},
                "schemaVersion": {"const": "1.0"},
                "scanId": {"type": "string", "minLength": 1},
                "mode": {"type": "string"},
                "completeness": {"type": "string"},
                "inventoryStrategy": {"type": "string"},
                "includePaths": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "excludePaths": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "surfaces": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "label",
                            "disposition",
                            "receiptRefs",
                        ],
                        "properties": {
                            "id": {"type": "string", "minLength": 1},
                            "label": {"type": "string", "minLength": 1},
                            "disposition": {"type": "string"},
                            "receiptRefs": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                            },
                        },
                    },
                },
                "explicitExclusions": {"type": "array"},
                "deferred": {"type": "array"},
                "openQuestions": {"type": "array"},
            },
        },
    }


class FinalizationFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.contract = finalization.load_json(finalization.DEFAULT_CONTRACT)
        self.commit = "a" * 40
        self.tree = "b" * 40
        self.inventory = "c" * 64
        self.explorer_commit = self.contract["explorer"]["required_commit"]
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
        self._prepare_runtime_evidence()
        self._prepare_pages_evidence()
        self._prepare_security_schema_pins()
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

    def _prepare_runtime_evidence(self) -> None:
        runner_relative = self.contract["explorer"]["runtime_provenance"][
            "runner"
        ]["path"]
        build_bodies = {
            "explorer-build/assets/app.js": (
                b"export const fixture = 'Explorer build closure';\n"
            ),
            "explorer-build/404.html": (
                b"<!doctype html><title>Explorer fixture not found</title>\n"
            ),
            "explorer-build/index.html": (
                b"<!doctype html><title>Explorer fixture</title>\n"
            ),
        }
        build_source_materials = [
            {
                "path": relative.removeprefix("explorer-build/"),
                "bytes": len(body),
                "sha256": finalization.sha256_bytes(body),
            }
            for relative, body in sorted(build_bodies.items())
        ]
        build_tree_sha256 = finalization.sha256_bytes(
            finalization.canonical_explorer_build_materials_bytes(
                build_source_materials
            )
        )
        build_manifest_body = finalization.render_explorer_build_manifest(
            file_count=len(build_source_materials),
            tree_sha256=build_tree_sha256,
            materials=build_source_materials,
        )
        bodies = {
            runner_relative: b"// deterministic Explorer runner fixture\n",
            "bundle/whole-law/okf-explorer.json": (
                b'{"id":"whole-law-fixture"}\n'
            ),
            "bundle/okf-explorer.json": (
                b'{"id":"legislation-fixture"}\n'
            ),
            **build_bodies,
            finalization.EXPLORER_BUILD_MANIFEST_PATH: build_manifest_body,
            finalization.EXPECTED_EXPLORER_SCREENSHOT_PATHS[0]: (
                b"\x89PNG\r\n\x1a\nExplorer graph fixture screenshot\n"
            ),
            finalization.EXPECTED_EXPLORER_SCREENSHOT_PATHS[1]: (
                b"\x89PNG\r\n\x1a\nExplorer reader fixture screenshot\n"
            ),
        }
        for directory in (
            self.explorer_dir,
            self.accessibility_dir,
            self.performance_dir,
        ):
            for relative, body in bodies.items():
                path = directory / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
        runner_path = self.explorer_dir / runner_relative
        build_manifest_path = (
            self.explorer_dir / finalization.EXPLORER_BUILD_MANIFEST_PATH
        )
        build_index_path = (
            self.explorer_dir / finalization.EXPLORER_BUILD_INDEX_PATH
        )
        self.contract["explorer"]["runtime_provenance"]["runner"] = (
            finalization.material(runner_path, runner_relative)
        )
        pages = self.contract["explorer"]["runtime_provenance"]["pages"]
        pages["build_manifest"] = finalization.material(
            build_manifest_path,
            finalization.EXPLORER_BUILD_MANIFEST_PATH,
        )
        pages["build_index"] = finalization.material(
            build_index_path,
            finalization.EXPLORER_BUILD_INDEX_PATH,
        )
        pages["build_tree"] = {
            "algorithm": finalization.EXPLORER_BUILD_ALGORITHM,
            "files": len(build_source_materials),
            "sha256": build_tree_sha256,
        }
        self.runtime_evidence = [
            finalization.material(self.explorer_dir / relative, relative)
            for relative in sorted(bodies)
        ]
        self.runtime_build_bodies = {
            relative.removeprefix("explorer-build/"): body
            for relative, body in build_bodies.items()
        }

    def _prepare_pages_evidence(self) -> None:
        profile, zipped = fixture_archive(
            actual_files=self.runtime_build_bodies
        )
        profile = replace(profile, head_sha=self.explorer_commit)
        destination = self.explorer_dir / "pages"
        transport = PagesFakeTransport(pages_responses(profile, zipped))
        self.pages_observation = pages_capture.capture_observation(
            output_dir=destination,
            transport=transport,
            resolver=pages_resolver,
            clock=lambda: "2026-07-27T10:00:00Z",
            observed_at="2026-07-27T10:00:00Z",
            profile=profile,
        )
        self.pages_profile = profile
        self.pages_zip_body = zipped
        document = json.loads(
            self.pages_observation.read_text(encoding="utf-8")
        )
        observed_archive = document["archive"]
        build = observed_archive["build"]
        not_found = next(
            row
            for row in build["materials"]
            if row["path"] == "404.html"
        )
        self.contract["pages_observation"] = {
            "controller": finalization.CANONICAL_PAGES_OBSERVATION_CONTROLLER,
            "schema": finalization.CANONICAL_PAGES_OBSERVATION_SCHEMA,
            "output": pages_capture.OBSERVATION_FILENAME,
            "target": copy.deepcopy(document["target"]),
            "archive": {
                "zip": copy.deepcopy(observed_archive["zip"]["material"]),
                "tar": copy.deepcopy(observed_archive["tar"]),
                "inventory": {
                    **copy.deepcopy(observed_archive["inventory"]["material"]),
                    "file_count": observed_archive["inventory"]["file_count"],
                    "total_file_bytes": observed_archive["inventory"][
                        "total_file_bytes"
                    ],
                    "materials_sha256": observed_archive["inventory"][
                        "materials_sha256"
                    ],
                },
                "build": {
                    "manifest": copy.deepcopy(build["manifest"]),
                    "index": copy.deepcopy(build["index"]),
                    "not_found": copy.deepcopy(not_found),
                    "tree": copy.deepcopy(build["tree"]),
                },
            },
            "durable_alternate": copy.deepcopy(
                document["durable_alternate"]
            ),
        }
        self.contract["explorer"]["pages_workflow_run_id"] = profile.run_id
        self.contract["explorer"]["git_tree"] = profile.git_tree
        pages_runtime = self.contract["explorer"]["runtime_provenance"][
            "pages"
        ]
        pages_runtime.update(
            {
                "run_id": profile.run_id,
                "run_attempt": profile.run_attempt,
                "commit": profile.head_sha,
                "artifact_id": profile.artifact_id,
                "artifact_name": profile.artifact_name,
                "artifact_zip": {
                    "bytes": profile.zip_bytes,
                    "sha256": profile.zip_sha256,
                },
                "artifact_tar": {
                    "bytes": profile.tar_bytes,
                    "sha256": profile.tar_sha256,
                },
                "build_manifest": {
                    **copy.deepcopy(build["manifest"]),
                    "path": (
                        f"{finalization.EXPLORER_BUILD_ROOT}/"
                        f"{build['manifest']['path']}"
                    ),
                },
                "build_index": {
                    **copy.deepcopy(build["index"]),
                    "path": (
                        f"{finalization.EXPLORER_BUILD_ROOT}/"
                        f"{build['index']['path']}"
                    ),
                },
                "build_tree": {
                    "algorithm": build["tree"]["algorithm"],
                    "files": build["tree"]["files"],
                    "sha256": build["tree"]["sha256"],
                },
            }
        )

    def _prepare_security_schema_pins(self) -> None:
        schema_dir = self.security_dir / "schemas"
        schema_dir.mkdir()
        self.security_schema_paths: dict[str, Path] = {}
        filenames = {
            "scan_manifest": "scan-manifest.schema.json",
            "findings": "findings.schema.json",
            "coverage": "coverage.schema.json",
        }
        for role, schema in synthetic_security_schemas().items():
            path = schema_dir / filenames[role]
            write_json(path, schema)
            self.security_schema_paths[role] = path
            self.contract["codex_security"]["schemas"][role]["sha256"] = (
                finalization.sha256_file(path)
            )

    def load_json_with_contract(self, path: Path) -> dict[str, object]:
        if Path(path).resolve() == finalization.DEFAULT_CONTRACT.resolve():
            return copy.deepcopy(self.contract)
        return REAL_LOAD_JSON(path)

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
        gates["accessibility"] = {
            "status": "passed",
            "standard": "WCAG 2.2 AA",
        }
        runner = copy.deepcopy(
            self.contract["explorer"]["runtime_provenance"]["runner"]
        )
        build_index = copy.deepcopy(
            self.contract["explorer"]["runtime_provenance"]["pages"][
                "build_index"
            ]
        )
        build_manifest = copy.deepcopy(
            self.contract["explorer"]["runtime_provenance"]["pages"][
                "build_manifest"
            ]
        )
        build_tree = copy.deepcopy(
            self.contract["explorer"]["runtime_provenance"]["pages"][
                "build_tree"
            ]
        )
        manifest = finalization.parse_explorer_build_manifest(
            (
                self.explorer_dir
                / finalization.EXPLORER_BUILD_MANIFEST_PATH
            ).read_bytes()
        )
        build_materials = [
            {
                **row,
                "path": f"{finalization.EXPLORER_BUILD_ROOT}/{row['path']}",
            }
            for row in manifest["materials"]
        ]
        federation = finalization.material(
            self.explorer_dir / "bundle/whole-law/okf-explorer.json",
            "whole-law/okf-explorer.json",
        )
        legislation = finalization.material(
            self.explorer_dir / "bundle/okf-explorer.json",
            "okf-explorer.json",
        )
        screenshots = [
            finalization.material(
                self.explorer_dir / relative,
                relative,
            )
            for relative in finalization.EXPECTED_EXPLORER_SCREENSHOT_PATHS
        ]
        integrity_checks = [
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
                "files": len(build_materials),
            },
            {
                "id": "explorer_build_index",
                "status": "passed",
                "sha256": build_index["sha256"],
            },
            {
                "id": "explorer_build_tree",
                "status": "passed",
                "algorithm": build_tree["algorithm"],
                "files": build_tree["files"],
                "sha256": build_tree["sha256"],
                "computed_sha256": build_tree["sha256"],
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
                    "checks_total": len(integrity_checks),
                    "checks_passed": len(integrity_checks),
                    "checks_failed": 0,
                    "all_passed": True,
                },
                "checks": integrity_checks,
            },
            "scope": "Exact frozen fixture publication.",
            "runner": runner,
            "inputs": {
                "bundle_root": "bundle",
                "federation_descriptor": federation,
                "legislation_descriptor": legislation,
                "explorer_build": {
                    "root": finalization.EXPLORER_BUILD_ROOT,
                    "manifest": build_manifest,
                    "index": build_index,
                    "files": build_tree["files"],
                    "sha256": build_tree["sha256"],
                    "algorithm": build_tree["algorithm"],
                    "materials": build_materials,
                },
            },
            "outputs": {
                "receipt": "explorer-runtime-acceptance.json",
                "screenshots": screenshots,
            },
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
        cost_boundary = (
            "Exact incremental direct OpenAI API cost only. The selected "
            "Codex workflow made zero direct API calls; this does not claim "
            "that total economic or subscription cost is zero."
        )
        codex_service_cost = {
            "attributable_subscription_cost": None,
            "billing_boundary": (
                "Codex subscription/task-surface cost and weekly-allowance "
                "consumption are not exposed."
            ),
            "subscription_usage": "unavailable-unmetered",
            "weekly_allowance_usage": "unavailable-unmetered",
        }
        usage = {
            "api_calls": 0,
            "api_input_tokens": 0,
            "api_output_tokens": 0,
            "codex_subscription_token_usage": "not exposed",
            "codex_weekly_allowance_usage": "not exposed",
        }
        enrichment_gate = {
            "status": "passed",
            "accepted_assertions": 1,
        }
        model_cost = {
            "schema": "okf-model-cost-report.v2",
            "provider": "OpenAI",
            "accepted_assertions": 1,
            "cost_boundary": cost_boundary,
            "codex_service_cost": codex_service_cost,
            "cost_per_accepted_assertion": {"usd": 0.0, "gbp": 0.0},
            "enrichment_gate": enrichment_gate,
            "incremental_cost": {"usd": 0.0, "gbp": 0.0},
            "model_deployment_identity_available": False,
            "model_identity": "Codex interactive task surface",
            "model_identity_limitation": "Exact deployment is not exposed.",
            "optional_direct_api_profile": {"status": "not-invoked"},
            "release_effect": "candidate",
            "run_id": "fixture-codex-run",
            "source_kind": "governed-codex-assisted-v3",
            "usage": usage,
            "validation_errors": [],
        }
        model_cost_body = finalization.render(model_cost)
        model_cost_material = {
            "path": "bundle/release-assurance/model-cost-report.json",
            "bytes": len(model_cost_body),
            "sha256": finalization.sha256_bytes(model_cost_body),
        }
        model_cost_section = {
            "boundary": cost_boundary,
            "codex_service_cost": codex_service_cost,
            "cost_per_accepted_assertion": {"usd": 0.0, "gbp": 0.0},
            "enrichment_gate": enrichment_gate,
            "incremental_cost": {"usd": 0.0, "gbp": 0.0},
            "model_deployment_identity_available": False,
            "model_identity": "Codex interactive task surface",
            "model_identity_limitation": "Exact deployment is not exposed.",
            "optional_direct_api_profile": {"status": "not-invoked"},
            "release_effect": "candidate",
            "run_id": "fixture-codex-run",
            "source": model_cost_material,
            "source_kind": "governed-codex-assisted-v3",
            "usage": usage,
        }
        report = {
            "schema": "okf-release-report.v1",
            "status": "passed",
            "gate": "GATE-12",
            "generated_at": "2026-07-26T04:00:00Z",
            "release": {"archive": self.archive_name},
            "sections": {
                **{
                    key: {"status": "passed"}
                    for key in (
                    "relationship_composition",
                    "coverage_and_freshness",
                    "gaps",
                    "licence_and_access_escalations",
                    "evaluation",
                    "yaml_ld_mime_exception",
                    )
                },
                "model_cost": model_cost_section,
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
            gate_row = {
                "id": gate_id,
                "group": "validation",
                "evidence_plane": (
                    "embedded" if gate_id in embedded else "external"
                ),
                "status": "passed" if gate_id in embedded else "pending",
            }
            if gate_id == "GATE-05":
                gate_row["observed_evidence"] = enrichment_gate
            gate_rows.append(gate_row)
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
            "model_cost_report": model_cost,
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
                info = tarfile.TarInfo(f"{prefix}/bundle/{relative}")
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
            "schema": "okf-reproduction-provenance-inputs.v2",
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
            "pages_observation_controller": finalization.material(
                finalization.PAGES_OBSERVATION_CONTROLLER_PATH,
                finalization.CANONICAL_PAGES_OBSERVATION_CONTROLLER,
            ),
            "pages_observation_schema": finalization.material(
                finalization.PAGES_OBSERVATION_SCHEMA_PATH,
                finalization.CANONICAL_PAGES_OBSERVATION_SCHEMA,
            ),
            "assurance_receipt_controllers": [
                finalization.material(
                    ROOT / relative,
                    relative,
                )
                for relative in (
                    "scripts/build_pre_rc_assurance_receipts.py",
                    "scripts/build_post_rc_assurance_receipts.py",
                )
            ],
            "deployed_manifest_template": finalization.material(
                ROOT / finalization.CANONICAL_DEPLOYED_MANIFEST_TEMPLATE,
                finalization.CANONICAL_DEPLOYED_MANIFEST_TEMPLATE,
            ),
            "deployed_probe_controller": finalization.material(
                finalization.DEPLOYED_PROBE_CONTROLLER_PATH,
                finalization.CANONICAL_DEPLOYED_PROBE_CONTROLLER,
            ),
            "finalization_contract": finalization.material(
                finalization.DEFAULT_CONTRACT,
                "release-assurance/external-finalization-contract.json",
            ),
            "finalization_schemas": schema_materials,
            "explorer_runtime_provenance": copy.deepcopy(
                self.contract["explorer"]["runtime_provenance"]
            ),
        }
        self.provenance_path = self.reproduction_dir / "provenance-inputs.json"
        write_json(self.provenance_path, provenance)
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
        asset_name: str | None = None,
        asset_body: bytes | None = None,
        asset_id_override: int | None = None,
        annotated_tag_sha: str | None = None,
        observed_at: str = "2026-07-26T04:10:00Z",
    ) -> tuple[Path, Path | None, str | None]:
        directory.mkdir(parents=True, exist_ok=True)
        release_id = 100 + len(tag)
        asset_id = asset_id_override or (200 + len(tag))
        published_asset_name = asset_name or self.archive_name
        release_url = (
            f"{repository}/releases/download/{tag}/{published_asset_name}"
            if asset
            else None
        )
        asset_rows = []
        asset_path: Path | None = None
        if asset:
            asset_path = directory / published_asset_name
            asset_path.write_bytes(
                self.archive_path.read_bytes()
                if asset_body is None
                else asset_body
            )
            asset_rows = [
                {
                    "id": asset_id,
                    "name": published_asset_name,
                    "browser_download_url": release_url,
                    "size": asset_path.stat().st_size,
                }
            ]
        release_headers = directory / "release-headers.json"
        release_body = directory / "release-body.json"
        tag_headers = directory / "tag-headers.json"
        tag_body = directory / "tag-body.json"
        annotated_tag_body = (
            directory / "annotated-tag-body.json"
            if annotated_tag_sha is not None
            else None
        )
        attempt = directory / "attempt-manifest.json"
        release_api_url = (
            f"https://api.github.com/repos/"
            f"{repository.removeprefix('https://github.com/')}/"
            f"releases/tags/{tag}"
        )
        ref_api_url = (
            f"https://api.github.com/repos/"
            f"{repository.removeprefix('https://github.com/')}/"
            f"git/ref/tags/{tag}"
        )
        write_json(
            release_headers,
            {
                "requests": [
                    {
                        "purpose": "release",
                        "hops": [
                            {
                                "headers": [
                                    {"name": "ETag", "value": '"release"'}
                                ],
                                "reason": "OK",
                                "status": 200,
                                "url": release_api_url,
                            }
                        ],
                    }
                ]
            },
        )
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
        write_json(
            tag_headers,
            {
                "requests": [
                    {
                        "purpose": "tag-ref",
                        "hops": [
                            {
                                "headers": [
                                    {"name": "ETag", "value": '"tag"'}
                                ],
                                "reason": "OK",
                                "status": 200,
                                "url": ref_api_url,
                            }
                        ],
                    }
                ]
            },
        )
        write_json(
            tag_body,
            {
                "ref": f"refs/tags/{tag}",
                "object": {
                    "type": "tag" if annotated_tag_sha is not None else "commit",
                    "sha": annotated_tag_sha or commit,
                },
            },
        )
        if annotated_tag_body is not None:
            write_json(
                annotated_tag_body,
                {
                    "sha": annotated_tag_sha,
                    "object": {"type": "commit", "sha": commit},
                },
            )
        attempt_materials = [
            finalization.material(release_headers, release_headers.name),
            finalization.material(release_body, release_body.name),
            finalization.material(tag_headers, tag_headers.name),
            finalization.material(tag_body, tag_body.name),
        ]
        if annotated_tag_body is not None:
            attempt_materials.append(
                finalization.material(
                    annotated_tag_body, annotated_tag_body.name
                )
            )
        asset_headers: Path | None = None
        if asset and asset_path is not None:
            asset_headers = directory / "asset-headers.json"
            write_json(
                asset_headers,
                {
                    "requests": [
                        {
                            "purpose": "release-asset",
                            "hops": [
                                {
                                    "headers": [
                                        {
                                            "name": "ETag",
                                            "value": '"asset"',
                                        }
                                    ],
                                    "reason": "OK",
                                    "status": 200,
                                    "url": release_url,
                                }
                            ],
                        }
                    ]
                },
            )
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
            "observed_at": observed_at,
            "repository": repository,
            "tag": tag,
            "expected_commit": commit,
            "release": {
                "api_url": (
                    release_api_url
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
                    ref_api_url
                ),
                "http_status": 200,
                "object_type": (
                    "tag" if annotated_tag_sha is not None else "commit"
                ),
                "object_sha": annotated_tag_sha or commit,
                "peeled_commit": commit,
                "response_headers": finalization.material(
                    tag_headers, tag_headers.name
                ),
                "response_bodies": [
                    finalization.material(tag_body, tag_body.name),
                    *(
                        [
                            finalization.material(
                                annotated_tag_body,
                                annotated_tag_body.name,
                            )
                        ]
                        if annotated_tag_body is not None
                        else []
                    ),
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
                "name": published_asset_name,
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
        self.explorer_observation, explorer_asset_path, explorer_asset_url = (
            self._observation(
                self.explorer_dir / "release",
                repository=self.contract["explorer"]["repository"],
                tag=self.contract["explorer"]["required_tag"],
                commit=self.explorer_commit,
                filename=observation_name,
                asset=True,
                asset_name=self.pages_profile.alternate_asset_name,
                asset_body=self.pages_zip_body,
                asset_id_override=self.pages_profile.alternate_asset_id,
                annotated_tag_sha=self.contract["explorer"][
                    "required_tag_object"
                ],
            )
        )
        assert explorer_asset_path is not None
        assert explorer_asset_url is not None
        explorer_observation = json.loads(
            self.explorer_observation.read_text(encoding="utf-8")
        )
        observed_asset = explorer_observation["asset"]
        self.contract["explorer"]["release_asset"] = {
            "asset_id": observed_asset["asset_id"],
            "name": observed_asset["name"],
            "bytes": observed_asset["bytes"],
            "sha256": observed_asset["sha256"],
            "url": explorer_asset_url,
        }
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
        pages_observation_row = finalization.material(
            self.pages_observation,
            f"pages/{self.pages_observation.name}",
        )
        release_evidence = [
            finalization.material(
                path,
                f"release/{path.name}",
            )
            for path in sorted(
                self.explorer_observation.parent.iterdir(),
                key=lambda value: value.name,
            )
            if path.is_file() and path != self.explorer_observation
        ]
        pages_evidence = [
            finalization.material(
                self.pages_observation.parent / relative,
                f"pages/{relative}",
            )
            for relative in sorted(finalization.PAGES_SUPPORT_PATHS)
        ]
        receipt = {
            "schema": "okf-explorer-release-receipt.v3",
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
                {"role": "pages_observation", **pages_observation_row},
                {"role": "runtime", **runtime_row},
            ],
            "release_evidence": release_evidence,
            "pages_evidence": pages_evidence,
            "runtime_evidence": copy.deepcopy(self.runtime_evidence),
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
        inventory_path = self.security_dir / "artifact-inventory.json"
        checks = self.contract["required_security_checks"]
        review_relative = "artifacts/security-review.json"
        review_path = self.security_dir / review_relative
        write_json(
            review_path,
            {
                "status": "passed",
                "candidate": {
                    "repository": self.contract["candidate"]["repository"],
                    "commit": self.commit,
                    "tree": self.tree,
                },
            },
        )
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
                    "receiptRefs": [review_relative],
                }
                for check in checks
            ],
            "explicitExclusions": [],
            "deferred": [],
            "openQuestions": [],
        }
        write_json(findings_path, findings)
        write_json(coverage_path, coverage)
        artifact_sources = {
            "findings.json": (findings_path, "application/json"),
            "coverage.json": (coverage_path, "application/json"),
            review_relative: (review_path, "application/json"),
        }
        manifest = {
            "documentType": "codex-security.scan-manifest",
            "schemaVersion": "1.0",
            "scan": {
                "id": "scan-fixture",
                "producer": copy.deepcopy(
                    self.contract["codex_security"]["producer"]
                ),
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
                        "path": relative,
                        "sha256": finalization.sha256_file(source),
                        "mediaType": media_type,
                    }
                    for relative, (source, media_type) in artifact_sources.items()
                ],
            },
        }
        write_json(manifest_path, manifest)
        report_path.write_text(
            "# Codex Security Report\n\n"
            "This report is a deterministic projection of the sealed scan.\n\n"
            "| Result | Count |\n"
            "| --- | ---: |\n"
            "| Reportable findings | 0 |\n\n"
            "## Findings\n\n"
            "### No findings\n\n"
            "The completed scan contains no reportable findings.\n",
            encoding="utf-8",
        )
        evidence_dir = self.security_dir / "scan-evidence"
        inventory_entries = []
        for relative, (source, media_type) in artifact_sources.items():
            copied = evidence_dir / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(source.read_bytes())
            inventory_entries.append(
                {
                    "source_path": relative,
                    "path": f"scan-evidence/{relative}",
                    "bytes": copied.stat().st_size,
                    "sha256": finalization.sha256_file(copied),
                    "media_type": media_type,
                }
            )
        write_json(
            inventory_path,
            {
                "schema": "okf-codex-security-artifact-inventory.v1",
                "scan_id": "scan-fixture",
                "entries": inventory_entries,
            },
        )
        schema_roles = {
            "scan_manifest": "scan_manifest_schema",
            "findings": "findings_schema",
            "coverage": "coverage_schema",
        }
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
                *[
                    {
                        "role": material_role,
                        **finalization.material(
                            self.security_schema_paths[role],
                            (
                                "schemas/"
                                + self.security_schema_paths[role].name
                            ),
                        ),
                    }
                    for role, material_role in schema_roles.items()
                ],
                role_material(inventory_path, "artifact_inventory"),
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
        with mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.load_json_with_contract,
        ):
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

    def create_traceability_evidence(
        self,
        external_sources: dict[str, list[Path]] | None = None,
    ) -> None:
        traceability_dir = self.root / "traceability"
        traceability_dir.mkdir()
        ledger_path = traceability_dir / "implementation-traceability.json"
        ledger_path.write_bytes(self.ledger_body)
        evidence_path = traceability_dir / "evidence.txt"
        evidence_path.write_text("evidence\n", encoding="utf-8")
        evidence = finalization.material(evidence_path, evidence_path.name)
        ledger_material = finalization.material(ledger_path, ledger_path.name)
        external_ids = set(
            self.contract["traceability"]["externally_closable_ids"]
        )
        if external_sources is not None:
            self.assert_external_source_ids(external_sources, external_ids)
        closures = []
        for row in self.ledger["requirements"]:
            requirement_id = row["id"]
            if row["status"] == "verified" or requirement_id in external_ids:
                disposition = "passed"
            elif requirement_id == "D-06":
                disposition = "deferred"
            else:
                disposition = "superseded"
            if requirement_id in external_ids:
                if external_sources is None:
                    closure_evidence = [evidence]
                else:
                    closure_evidence = []
                    for index, source in enumerate(
                        external_sources[requirement_id], start=1
                    ):
                        destination = (
                            traceability_dir
                            / f"{requirement_id}-{index:02d}-{source.name}"
                        )
                        destination.write_bytes(source.read_bytes())
                        closure_evidence.append(
                            finalization.material(destination, destination.name)
                        )
            else:
                closure_evidence = [ledger_material]
            closure = {
                "id": requirement_id,
                "frozen_status": row["status"],
                "disposition": disposition,
                "must_have": requirement_id != "D-06",
                "rationale": row["release_disposition"]["reason"],
                "evidence": closure_evidence,
            }
            if requirement_id == "D-06":
                closure["accepted_exception"] = {
                    "accepted": True,
                    "authority": row["source_clause"]["source"],
                    "decision_evidence": ledger_material,
                }
            if disposition == "superseded":
                closure["superseded_by"] = "D-13"
            closures.append(closure)
        traceability = {
            "schema": "okf-traceability-closure-receipt.v2",
            "status": "candidate",
            "gate": "GATE-14",
            "candidate": {
                "repository": self.contract["candidate"]["repository"],
                "commit": self.commit,
                "tree": self.tree,
            },
            "requirements_total": len(closures),
            "requirements_closed": len(closures),
            "unresolved_must_haves": 0,
            "source_ledger": ledger_material,
            "closures": closures,
            "closure_rule": "Every frozen requirement has a terminal disposition.",
        }
        self.traceability_receipt = (
            traceability_dir / finalization.CANONICAL_INPUT_NAMES["traceability"]
        )
        write_json(self.traceability_receipt, traceability)

    @staticmethod
    def assert_external_source_ids(
        external_sources: dict[str, list[Path]],
        expected: set[str],
    ) -> None:
        if set(external_sources) != expected:
            raise AssertionError("fixture external source IDs differ")

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
            "explorer_commit": self.contract["explorer"]["required_commit"],
            "explorer_release": self.contract["explorer"]["required_tag"],
        }
        write_json(
            self.public_attempt / "attempt.json",
            {
                "status": "passed",
                "candidate": public_candidate,
                "executed_at": "2026-07-26T04:20:00Z",
                "tool": {
                    "name": (
                        finalization.DEPLOYED_PROBE_CONTROLLER_PATH.name
                    ),
                    "version": self.contract[
                        "deployed_probe_controller"
                    ]["version"],
                    "sha256": finalization.sha256_file(
                        finalization.DEPLOYED_PROBE_CONTROLLER_PATH
                    ),
                },
            },
        )
        write_json(
            self.public_attempt / "projection.json",
            {
                "gate_evidence_status": "passed",
                "candidate": public_candidate,
                "executed_at": "2026-07-26T04:20:00Z",
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
        route_manifest_text = (
            ROOT
            / finalization.CANONICAL_DEPLOYED_MANIFEST_TEMPLATE
        ).read_text(encoding="utf-8")
        route_manifest = json.loads(
            route_manifest_text.replace(
                "__CANDIDATE_COMMIT__", self.commit
            )
            .replace("__BUNDLE_TREE_SHA256__", self.inventory)
            .replace(
                "__RC_TAG__",
                self.contract["candidate"]["rc_tag"],
            )
        )
        route_manifest["state"] = "locked"
        write_json(
            self.public_attempt / "route-manifest.json",
            route_manifest,
        )
        write_json(self.public_attempt / "integrity.json", {"status": "passed"})

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
            "rc_release_observation_path": self.rc_observation,
            "rc_asset_path": self.rc_asset,
            "rc_release_url": self.rc_url,
        }


class ReleaseFinalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="okf-finalization-"
        )
        self.fixture = FinalizationFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def traceability_case(
        self,
    ) -> tuple[dict[str, object], dict[str, object]]:
        self.fixture.create_post_rc_evidence()
        self.fixture.create_traceability_evidence()
        receipt = json.loads(
            self.fixture.traceability_receipt.read_text(encoding="utf-8")
        )
        contract = copy.deepcopy(self.fixture.contract)
        contract["traceability"]["frozen_ledger_sha256"] = receipt[
            "source_ledger"
        ]["sha256"]
        return receipt, contract

    @staticmethod
    def traceability_closure(
        receipt: dict[str, object], requirement_id: str
    ) -> dict[str, object]:
        return next(
            row
            for row in receipt["closures"]
            if row["id"] == requirement_id
        )

    def test_authorize_rc_reconstructs_embedded_and_runtime_gates(self) -> None:
        reproduction = json.loads(
            self.fixture.reproduction_path.read_text(encoding="utf-8")
        )
        self.assertNotIn("required_receipts", reproduction)
        receipt = self.fixture.authorize_rc()
        self.assertEqual("rc_eligible", receipt["state"])
        self.assertEqual("validated", receipt["embedded_validation"]["current_state"])
        for gate_id in finalization.EMBEDDED_RC_GATES:
            self.assertEqual("passed", receipt["gates"][gate_id])

    def test_external_v2_runtime_candidate_mismatch_is_rejected(self) -> None:
        runtime_path = self.fixture.runtime_paths["explorer"]
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["candidate"]["commit"] = "f" * 40
        write_json(runtime_path, runtime)
        explorer_receipt = json.loads(
            self.fixture.explorer_receipt.read_text(encoding="utf-8")
        )
        for row in explorer_receipt["materials"]:
            if row["role"] == "runtime":
                row["bytes"] = runtime_path.stat().st_size
                row["sha256"] = finalization.sha256_file(runtime_path)
        write_json(self.fixture.explorer_receipt, explorer_receipt)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "Explorer runtime candidate binding",
        ):
            self.fixture.authorize_rc()

    def test_explorer_build_integrity_rows_are_exactly_reconstructed(
        self,
    ) -> None:
        runtime_path = self.fixture.runtime_paths["explorer"]
        baseline_runtime = json.loads(
            runtime_path.read_text(encoding="utf-8")
        )
        baseline_receipt = json.loads(
            self.fixture.explorer_receipt.read_text(encoding="utf-8")
        )

        def mutate_manifest(row: dict[str, Any]) -> None:
            check = next(
                value
                for value in row["integrity"]["checks"]
                if value["id"] == "explorer_build_manifest"
            )
            check["sha256"] = "0" * 64

        def mutate_material_count(row: dict[str, Any]) -> None:
            check = next(
                value
                for value in row["integrity"]["checks"]
                if value["id"] == "explorer_build_materials"
            )
            check["files"] += 1

        def mutate_tree_algorithm(row: dict[str, Any]) -> None:
            check = next(
                value
                for value in row["integrity"]["checks"]
                if value["id"] == "explorer_build_tree"
            )
            check["algorithm"] = "attacker-selected-tree-v1"

        def mutate_computed_tree(row: dict[str, Any]) -> None:
            check = next(
                value
                for value in row["integrity"]["checks"]
                if value["id"] == "explorer_build_tree"
            )
            check["computed_sha256"] = "0" * 64

        def mutate_check_order(row: dict[str, Any]) -> None:
            checks = row["integrity"]["checks"]
            checks[-1], checks[-2] = checks[-2], checks[-1]

        cases = (
            (
                "manifest identity",
                mutate_manifest,
                "integrity check explorer_build_manifest differs",
            ),
            (
                "material count",
                mutate_material_count,
                "integrity check explorer_build_materials differs",
            ),
            (
                "tree algorithm",
                mutate_tree_algorithm,
                "integrity check explorer_build_tree differs",
            ),
            (
                "computed tree",
                mutate_computed_tree,
                "integrity check explorer_build_tree differs",
            ),
            (
                "integrity check order",
                mutate_check_order,
                "integrity check order differs",
            ),
        )
        for label, mutate, error in cases:
            with self.subTest(label=label):
                runtime = copy.deepcopy(baseline_runtime)
                mutate(runtime)
                write_json(runtime_path, runtime)
                explorer_receipt = copy.deepcopy(baseline_receipt)
                for material_row in explorer_receipt["materials"]:
                    if material_row["role"] == "runtime":
                        material_row["bytes"] = runtime_path.stat().st_size
                        material_row["sha256"] = finalization.sha256_file(
                            runtime_path
                        )
                write_json(
                    self.fixture.explorer_receipt,
                    explorer_receipt,
                )
                with self.assertRaisesRegex(
                    finalization.FinalizationError,
                    error,
                ):
                    self.fixture.authorize_rc()

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

    def test_unbound_assurance_receipt_controller_is_rejected(self) -> None:
        provenance = json.loads(
            self.fixture.provenance_path.read_text(encoding="utf-8")
        )
        provenance["assurance_receipt_controllers"][0]["sha256"] = "0" * 64
        write_json(self.fixture.provenance_path, provenance)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "assurance receipt controller SHA-256",
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

    def test_cli_reserves_traceability_for_terminal_finalization(self) -> None:
        root = Path(self.temporary.name)
        namespace = argparse.Namespace(
            command="authorize-final-promotion",
            contract=finalization.DEFAULT_CONTRACT,
            receipt=root / "final-promotion-authorization-receipt.json",
            pre_rc_authorization=root / "pre-rc-authorization-receipt.json",
            public_attempt=root / "public-attempt",
            traceability_receipt=None,
            rc_release_observation=root / "rc-release-observation.json",
            rc_asset=root / self.fixture.archive_name,
            rc_release_url="https://example.test/rc",
            final_promotion_authorization=None,
            final_release_observation=None,
            final_asset=None,
            final_release_url=None,
        )
        finalization.validate_cli_arguments(namespace)

        namespace.traceability_receipt = (
            root / "traceability-closure-receipt.json"
        )
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "rejects post-publication arguments: traceability_receipt",
        ):
            finalization.validate_cli_arguments(namespace)

        namespace.command = "finalize"
        namespace.receipt = root / "external-finalization-receipt.json"
        namespace.traceability_receipt = None
        namespace.final_promotion_authorization = (
            root / "final-promotion-authorization-receipt.json"
        )
        namespace.final_release_observation = (
            root / "final-release-observation.json"
        )
        namespace.final_asset = root / self.fixture.archive_name
        namespace.final_release_url = "https://example.test/final"
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "finalize requires: traceability_receipt",
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

    def test_contract_declared_release_obligations_can_close_externally(
        self,
    ) -> None:
        original, contract = self.traceability_case()
        expected_ids = contract["traceability"]["externally_closable_ids"]
        for requirement_id in expected_ids:
            with self.subTest(requirement_id=requirement_id):
                receipt = copy.deepcopy(original)
                closure = self.traceability_closure(
                    receipt, requirement_id
                )
                self.assertIn(
                    closure["frozen_status"], {"started", "blocked"}
                )
                closure["disposition"] = "passed"
                closure.pop("accepted_exception", None)
                source = finalization.reconstruct_traceability(
                    receipt=receipt,
                    receipt_path=self.fixture.traceability_receipt,
                    contract=contract,
                    commit=self.fixture.commit,
                    tree=self.fixture.tree,
                )
                self.assertEqual(
                    receipt["source_ledger"]["sha256"], source["sha256"]
                )

    def test_undeclared_started_requirement_cannot_close_as_passed(
        self,
    ) -> None:
        receipt, contract = self.traceability_case()
        requirement_id = "P01-01"
        self.assertNotIn(
            requirement_id,
            contract["traceability"]["externally_closable_ids"],
        )
        ledger_path = (
            self.fixture.traceability_receipt.parent
            / "implementation-traceability.json"
        )
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        requirement = next(
            row
            for row in ledger["requirements"]
            if row["id"] == requirement_id
        )
        requirement["status"] = "started"
        write_json(ledger_path, ledger)
        receipt["source_ledger"] = finalization.material(
            ledger_path, ledger_path.name
        )
        contract["traceability"]["frozen_ledger_sha256"] = receipt[
            "source_ledger"
        ]["sha256"]
        closure = self.traceability_closure(receipt, requirement_id)
        closure["frozen_status"] = "started"
        closure["disposition"] = "passed"
        closure.pop("accepted_exception", None)

        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "P01-01 cannot pass from frozen status 'started'",
        ):
            finalization.reconstruct_traceability(
                receipt=receipt,
                receipt_path=self.fixture.traceability_receipt,
                contract=contract,
                commit=self.fixture.commit,
                tree=self.fixture.tree,
            )

    def test_external_passage_requires_nonempty_verified_evidence(
        self,
    ) -> None:
        receipt, contract = self.traceability_case()
        requirement_id = contract["traceability"]["externally_closable_ids"][0]
        closure = self.traceability_closure(receipt, requirement_id)
        closure["disposition"] = "passed"
        closure["evidence"] = []
        closure.pop("accepted_exception", None)

        with self.assertRaisesRegex(
            finalization.FinalizationError,
            f"{requirement_id} evidence is empty",
        ):
            finalization.reconstruct_traceability(
                receipt=receipt,
                receipt_path=self.fixture.traceability_receipt,
                contract=contract,
                commit=self.fixture.commit,
                tree=self.fixture.tree,
            )

    def test_external_closure_contract_fails_closed_when_malformed(
        self,
    ) -> None:
        receipt, original = self.traceability_case()
        missing = copy.deepcopy(original)
        missing["traceability"].pop("externally_closable_ids")
        duplicate = copy.deepcopy(original)
        duplicate["traceability"]["externally_closable_ids"].append(
            duplicate["traceability"]["externally_closable_ids"][0]
        )
        unknown = copy.deepcopy(original)
        unknown["traceability"]["externally_closable_ids"].append("P99-99")

        cases = (
            (missing, "externally closable traceability IDs must be an array"),
            (duplicate, "invalid or duplicated"),
            (unknown, "is not frozen: P99-99"),
        )
        for contract, pattern in cases:
            with self.subTest(pattern=pattern), self.assertRaisesRegex(
                finalization.FinalizationError, pattern
            ):
                finalization.reconstruct_traceability(
                    receipt=receipt,
                    receipt_path=self.fixture.traceability_receipt,
                    contract=contract,
                    commit=self.fixture.commit,
                    tree=self.fixture.tree,
                )

    def test_external_closure_contract_rejects_terminal_frozen_status(
        self,
    ) -> None:
        receipt, contract = self.traceability_case()
        requirement_id = "P01-01"
        contract["traceability"]["externally_closable_ids"].append(
            requirement_id
        )
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "P01-01 has ineligible frozen status 'verified'",
        ):
            finalization.reconstruct_traceability(
                receipt=receipt,
                receipt_path=self.fixture.traceability_receipt,
                contract=contract,
                commit=self.fixture.commit,
                tree=self.fixture.tree,
            )

    def test_final_promotion_precedes_post_publication_finalization(self) -> None:
        post_args = self.fixture.create_post_rc_evidence()

        def load_with_fixture_ledger(path: Path) -> dict[str, object]:
            document = self.fixture.load_json_with_contract(path)
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
        self.assertEqual(
            "okf-final-promotion-authorization-receipt.v2",
            promotion["schema"],
        )
        self.assertEqual({"GATE-09": "passed"}, promotion["gates"])
        self.assertNotIn("traceability", promotion)
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
            observed_at="2026-07-26T04:30:00Z",
        )
        model_cost_path = Path(self.temporary.name) / "model-cost-report.json"
        model_cost_path.write_bytes(
            finalization.render(
                self.fixture.embedded["model_cost_report"]
            )
        )
        projection_path = self.fixture.public_attempt / "projection.json"
        route_manifest_path = (
            self.fixture.public_attempt / "route-manifest.json"
        )
        external_sources = {
            "P06-03": [
                self.fixture.package_path,
                self.fixture.rc_observation,
                final_observation,
            ],
            "P08-06": [
                self.fixture.runtime_paths["explorer"],
                projection_path,
            ],
            "P09-05": [projection_path, route_manifest_path],
            "P10-02": [
                self.fixture.reproduction_path,
                self.fixture.provenance_path,
                self.fixture.security_receipt,
            ],
            "P10-03": [
                self.fixture.pre_rc_path,
                self.fixture.rc_observation,
                final_observation,
            ],
            "P10-04": [
                self.fixture.explorer_receipt,
                self.fixture.rc_observation,
                final_observation,
                projection_path,
            ],
            "D-01": [
                self.fixture.pre_rc_path,
                promotion_path,
                final_observation,
            ],
            "D-05": [model_cost_path, final_observation],
            "D-07": [
                self.fixture.pre_rc_path,
                promotion_path,
                final_observation,
            ],
        }
        self.fixture.create_traceability_evidence(external_sources)
        final_args = {
            **post_args,
            "traceability_receipt_path": self.fixture.traceability_receipt,
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

    def test_public_probe_from_unbound_controller_is_rejected(self) -> None:
        post_args = self.fixture.create_post_rc_evidence()
        attempt_path = self.fixture.public_attempt / "attempt.json"
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt["tool"]["sha256"] = "0" * 64
        write_json(attempt_path, attempt)
        with mock.patch.object(
            finalization.deployed_probe, "verify_attempt", return_value=[]
        ), mock.patch.object(
            finalization,
            "load_json",
            side_effect=self.fixture.load_json_with_contract,
        ), self.assertRaisesRegex(
            finalization.FinalizationError,
            "public probe controller identity",
        ):
            finalization.assemble_receipt(
                command="authorize-final-promotion",
                **post_args,
            )


if __name__ == "__main__":
    unittest.main()
