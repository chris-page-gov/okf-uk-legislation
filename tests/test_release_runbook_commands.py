from __future__ import annotations

import io
import json
import re
import shlex
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_post_rc_assurance_receipts as post_rc  # noqa: E402
import build_pre_rc_assurance_receipts as pre_rc  # noqa: E402
import capture_github_pages_observation as pages_observation  # noqa: E402
import capture_github_release_observation as observation  # noqa: E402
import finalize_release_candidate as finalization  # noqa: E402
import probe_deployed_entrypoints as deployed_probe  # noqa: E402
import reproduce_release_candidate as reproduction  # noqa: E402


RUNBOOK = ROOT / "release-assurance" / "reproduction-and-promotion.md"
README = ROOT / "README.md"
PROFILE = ROOT / "release-assurance" / "reproduction-profile.json"

EXPLORER_REPOSITORY = "https://github.com/chris-page-gov/okf-explorer"
LEGISLATION_REPOSITORY = (
    "https://github.com/chris-page-gov/okf-uk-legislation"
)
HEX40 = "1" * 40
HEX64 = "2" * 64

SHELL_VALUES = {
    "ARCHIVE_BYTES": "123",
    "ARCHIVE_SHA256": HEX64,
    "ASSET_NAME": "okf-uk-legislation-v0.3.0.tar.zst",
    "BUNDLE_TREE_SHA256": HEX64,
    "CANDIDATE_COMMIT": HEX40,
    "CANDIDATE_TREE": "3" * 40,
    "CODEX_SECURITY_SCHEMA_DIR": "/external/codex-security-schemas",
    "EVIDENCE": "/external/okf-v0.3.0",
    "EXPLORER_COMMIT": "4" * 40,
    "EXPLORER_REPOSITORY": EXPLORER_REPOSITORY,
    "EXPLORER_ROOT": "/checkout/okf-explorer",
    "EXPLORER_TAG": "v0.5.4",
    "FINAL_ASSET": (
        "/external/okf-v0.3.0/final-download/"
        "okf-uk-legislation-v0.3.0.tar.zst"
    ),
    "FINAL_TAG": "v0.3.0",
    "LEGISLATION_REPOSITORY": LEGISLATION_REPOSITORY,
    "LEGISLATION_ROOT": "/checkout/okf-uk-legislation",
    "PUBLIC_ATTEMPT": "/external/okf-v0.3.0/public-attempt",
    "RC_ASSET": (
        "/external/okf-v0.3.0/rc-download/"
        "okf-uk-legislation-v0.3.0.tar.zst"
    ),
    "RC_TAG": "v0.3.0-rc.1",
    "SEALED_ARCHIVE": (
        "/external/okf-v0.3.0/reproduction/"
        "okf-uk-legislation-v0.3.0.tar.zst"
    ),
    "SECURITY_SCAN_DIR": "/external/okf-v0.3.0/security-scan",
    "TRACE_INPUT": "/external/okf-v0.3.0/traceability-input",
}


def shell_blocks(document: str) -> list[str]:
    blocks: list[str] = []
    marker = "```sh\n"
    start = 0
    while True:
        fence = document.find(marker, start)
        if fence < 0:
            return blocks
        body_start = fence + len(marker)
        body_end = document.find("\n```", body_start)
        if body_end < 0:
            raise AssertionError("unterminated shell fence")
        blocks.append(document[body_start:body_end])
        start = body_end + 4


def logical_shell_lines(block: str) -> list[str]:
    commands: list[str] = []
    pending = ""
    for raw in block.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if pending:
            pending += " " + stripped
        else:
            pending = stripped
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        commands.append(pending)
        pending = ""
    if pending:
        commands.append(pending)
    return commands


def documented_python_controllers(document: str) -> list[list[str]]:
    commands: list[list[str]] = []
    for block in shell_blocks(document):
        for command in logical_shell_lines(block):
            if not command.startswith(".venv/bin/python scripts/"):
                continue
            tokens = shlex.split(command)
            commands.append([expand_shell_token(token) for token in tokens])
    return commands


def expand_shell_token(token: str) -> str:
    for name, value in sorted(
        SHELL_VALUES.items(), key=lambda row: len(row[0]), reverse=True
    ):
        marker = f"${name}"
        if token == marker:
            return value
        if token.startswith(marker + "/"):
            return value + token[len(marker) :]
    return token


class ReleaseRunbookCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = RUNBOOK.read_text(encoding="utf-8")
        cls.commands = documented_python_controllers(cls.document)

    def test_numbered_steps_are_complete_and_ordered(self) -> None:
        headings = [
            int(line.split(".", 1)[0][3:])
            for line in self.document.splitlines()
            if line.startswith("## ") and line[3:4].isdigit()
        ]
        self.assertEqual(list(range(13)), headings)

    def test_every_documented_python_controller_uses_its_real_parser(
        self,
    ) -> None:
        counts: dict[str, int] = {}
        for command in self.commands:
            script = command[1]
            counts[script] = counts.get(script, 0) + 1
            with self.subTest(command=shlex.join(command)):
                self.assert_controller_parser_accepts(command)
        self.assertEqual(
            {
                "scripts/build_post_rc_assurance_receipts.py": 3,
                "scripts/build_pre_rc_assurance_receipts.py": 1,
                "scripts/capture_github_pages_observation.py": 1,
                "scripts/capture_github_release_observation.py": 3,
                "scripts/finalize_release_candidate.py": 5,
                "scripts/probe_deployed_entrypoints.py": 3,
                "scripts/reproduce_release_candidate.py": 1,
            },
            counts,
        )

    def assert_controller_parser_accepts(self, command: list[str]) -> None:
        script = command[1]
        arguments = command[2:]
        if script == "scripts/reproduce_release_candidate.py":
            receipt = {
                "archive": {"sha256": HEX64},
                "comparison": {"files": 1},
                "release_gate": {"eligible": True},
                "run_id": "run",
            }
            with (
                mock.patch.object(
                    reproduction, "run_reproduction", return_value=receipt
                ),
                mock.patch.object(sys, "argv", [script, *arguments]),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(0, reproduction.main())
            return
        if script == "scripts/capture_github_release_observation.py":
            with (
                mock.patch.object(
                    observation,
                    "capture_observation",
                    return_value=Path("/external/observation.json"),
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(0, observation.main(arguments))
            return
        if script == "scripts/capture_github_pages_observation.py":
            with (
                mock.patch.object(
                    pages_observation,
                    "capture_observation",
                    return_value=Path(
                        "/external/github-pages-observation.json"
                    ),
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(0, pages_observation.main(arguments))
            return
        if script == "scripts/build_pre_rc_assurance_receipts.py":
            pre_rc.parser().parse_args(arguments)
            return
        if script == "scripts/build_post_rc_assurance_receipts.py":
            post_rc.parser().parse_args(arguments)
            return
        if script == "scripts/finalize_release_candidate.py":
            parsed = finalization.parser().parse_args(arguments)
            finalization.validate_cli_arguments(parsed)
            return
        if script == "scripts/probe_deployed_entrypoints.py":
            self.assert_probe_parser_accepts(script, arguments)
            return
        self.fail(f"undispatched documented controller: {script}")

    def assert_probe_parser_accepts(
        self, script: str, arguments: list[str]
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="okf-runbook-probe-") as temp:
            manifest = Path(temp) / "manifest.json"
            manifest.write_text(
                '{"routes":[],"state":"locked"}\n', encoding="utf-8"
            )
            parsed = list(arguments)
            if "--manifest" in parsed:
                parsed[parsed.index("--manifest") + 1] = str(manifest)
            projection = {"gate_evidence_status": "passed"}
            patches = (
                mock.patch.object(
                    deployed_probe, "validate_manifest", return_value=[]
                ),
                mock.patch.object(
                    deployed_probe,
                    "run_probe",
                    return_value=({}, projection, {}),
                ),
                mock.patch.object(
                    deployed_probe,
                    "write_attempt",
                    return_value=Path(temp) / "attempt",
                ),
                mock.patch.object(
                    deployed_probe, "verify_attempt", return_value=[]
                ),
                mock.patch.object(sys, "argv", [script, *parsed]),
            )
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(0, deployed_probe.main())

    def test_security_and_traceability_commands_use_directory_contracts(
        self,
    ) -> None:
        security = next(
            row
            for row in self.commands
            if row[1]
            == "scripts/build_post_rc_assurance_receipts.py"
            and row[2] == "build-security"
        )
        self.assertIn("--codex-security-schema-dir", security)
        self.assertIn("--output-dir", security)
        self.assertNotIn("--output", security)

        traceability = next(
            row
            for row in self.commands
            if row[1]
            == "scripts/build_post_rc_assurance_receipts.py"
            and row[2] == "build-traceability"
        )
        self.assertIn("--output-dir", traceability)
        self.assertNotIn("--output", traceability)

    def test_runtime_screenshot_source_is_outside_receipt_evidence_root(
        self,
    ) -> None:
        runner = next(
            command
            for block in shell_blocks(self.document)
            for command in logical_shell_lines(block)
            if command.startswith(
                'node "$EXPLORER_ROOT/apps/okf-explorer/scripts/'
                'run_legislation_runtime_acceptance.mjs"'
            )
        )
        tokens = [expand_shell_token(token) for token in shlex.split(runner)]
        output = Path(tokens[tokens.index("--output") + 1])
        screenshot_source = Path(
            tokens[tokens.index("--screenshot-root") + 1]
        )
        receipt_evidence_root = output.parent
        self.assertNotEqual(receipt_evidence_root, screenshot_source)
        self.assertFalse(
            screenshot_source.is_relative_to(receipt_evidence_root),
            "mutable screenshot source must not be nested under the "
            "write-once receipt evidence root",
        )
        self.assertEqual(
            Path("/external/okf-v0.3.0/runtime-screenshot-source"),
            screenshot_source,
        )
        self.assertIn(
            "$EVIDENCE/explorer-runtime/output/playwright",
            self.document,
        )

    def test_explorer_build_uses_deterministic_release_command(self) -> None:
        self.assertIn(
            'pnpm --dir "$EXPLORER_ROOT/apps/okf-explorer" '
            "build:determinism",
            self.document,
        )
        self.assertNotIn(
            'pnpm --dir "$EXPLORER_ROOT/apps/okf-explorer" build\n',
            self.document,
        )

    def test_explorer_observation_binds_durable_pages_release_asset(
        self,
    ) -> None:
        command = next(
            row
            for row in self.commands
            if row[1] == "scripts/capture_github_release_observation.py"
            and row[row.index("--repository") + 1] == EXPLORER_REPOSITORY
        )
        self.assertEqual(
            "okf-explorer-v0.5.4-pages-artifact.zip",
            command[command.index("--asset-name") + 1],
        )
        self.assertEqual(
            "185023908",
            command[command.index("--expected-asset-bytes") + 1],
        )
        self.assertEqual(
            "357c2fcfbdb4fda34a830d933feb290dd8980cc61b0a82f51cd5e0e5a226c1c0",
            command[command.index("--expected-asset-sha256") + 1],
        )

    def test_pages_observation_is_a_distinct_pre_rc_input(self) -> None:
        pages_capture = next(
            row
            for row in self.commands
            if row[1] == "scripts/capture_github_pages_observation.py"
        )
        self.assertEqual(
            "/external/okf-v0.3.0/explorer-pages-observation",
            pages_capture[pages_capture.index("--output-dir") + 1],
        )
        self.assertIn("--allow-network", pages_capture)

        builder = next(
            row
            for row in self.commands
            if row[1] == "scripts/build_pre_rc_assurance_receipts.py"
        )
        self.assertEqual(
            (
                "/external/okf-v0.3.0/explorer-pages-observation/"
                "github-pages-observation.json"
            ),
            builder[builder.index("--pages-observation") + 1],
        )

    def test_traceability_map_has_exact_contract_rows_and_keys(self) -> None:
        rows = []
        for line in self.document.splitlines():
            stripped = line.strip()
            if not stripped.startswith('{"id": '):
                continue
            self.assertRegex(
                stripped,
                r'^\{"id": "[^"]+", "evidence": selected\([^)]*\)\},$',
            )
            match = re.match(r'^\{"id": "([^"]+)"', stripped)
            self.assertIsNotNone(match)
            rows.append(match.group(1))
        contract = json.loads(
            (
                ROOT
                / "release-assurance"
                / "external-finalization-contract.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(contract["traceability"]["externally_closable_ids"], rows)
        self.assertNotIn("D-06", rows)

    def test_readme_commands_exactly_match_reproduction_profile(self) -> None:
        readme = README.read_text(encoding="utf-8")
        blocks = shell_blocks(readme)
        build_block = next(
            block
            for block in blocks
            if "scripts/build_legislation_okf.py --from-existing" in block
        )
        validation_block = next(
            block
            for block in blocks
            if "-m unittest discover -s tests -v" in block
        )

        def parse(block: str) -> list[list[str]]:
            return [
                shlex.split(command)
                for command in logical_shell_lines(block)
                if command.startswith(".venv/bin/python ")
            ]

        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        expected_build = [
            [".venv/bin/python", *row[1:]]
            for row in profile["build_commands"]
        ]
        expected_validation = [
            [".venv/bin/python", *row[1:]]
            for row in profile["validation_commands"]
        ]
        self.assertEqual(expected_build, parse(build_block))
        self.assertEqual(expected_validation, parse(validation_block))


if __name__ == "__main__":
    unittest.main()
