#!/usr/bin/env python3
"""Fail when an authored UK Legislation/Whole-Law page guesses a local route."""

from __future__ import annotations

import re
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES_HOST = "chris-page-gov.github.io"
PAGES_PREFIX = "/okf-uk-legislation"
GITHUB_REPO = ("chris-page-gov", "okf-uk-legislation")
SKIP_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "bundle",
    "evidence",
    "node_modules",
    "research",
    "yaml-ld-tests",
}
INLINE = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)")
REFERENCE = re.compile(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)")
HTML = re.compile(
    r"""(?:href|src)\s*=\s*(?P<quote>["'])(?P<target>.*?)(?P=quote)""",
    re.IGNORECASE,
)
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
JSON_URL = re.compile(r"https?://[^\s\"'<>\\\\]+")

REPOSITORY = "https://github.com/chris-page-gov/okf-uk-legislation"
RELEASES = f"{REPOSITORY}/releases"
LEGISLATION_DESCRIPTOR = (
    "https://chris-page-gov.github.io/okf-uk-legislation/okf-explorer.json"
)
WHOLE_LAW_DESCRIPTOR = (
    "https://chris-page-gov.github.io/okf-uk-legislation/"
    "whole-law/okf-explorer.json"
)
WHOLE_LAW_SEMANTIC_PATHS = (
    "okf-bundle.yamlld",
    "okf-bundle.jsonld",
    "okf-bundle.ttl",
)
OFFICIAL_SERVICE = "https://www.legislation.gov.uk/"
OFFICIAL_DATA_DOCS = "https://legislation.github.io/data-documentation/"
GOVUK_DATA_DOCS = "https://guidance.data.gov.uk/get_data/api_documentation/"
CKAN_DESCRIPTOR = (
    "https://chris-page-gov.github.io/"
    "ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json"
)
BUNDLE_AUTHORING = (
    "https://chris-page-gov.github.io/"
    "ai-infrastructure-wiki/docs/okf-bundle-authoring.md"
)
COMPATIBILITY_PREFIX = "https://chris-page-gov.github.io/ai-infrastructure-wiki/"
COMPATIBILITY_LABELS = ("compatibility", "preserved", "historical")
STALE_MACHINE_PREFIXES = (
    "https://chris-page-gov.github.io/ai-infrastructure-wiki/legislation/",
    "https://chris-page-gov.github.io/okf-uk-legislation/legislation/",
)
COMMON_LANDING_REQUIREMENTS = (
    REPOSITORY,
    RELEASES,
    OFFICIAL_SERVICE,
    OFFICIAL_DATA_DOCS,
    GOVUK_DATA_DOCS,
    CKAN_DESCRIPTOR,
    BUNDLE_AUTHORING,
)
LANDING_REQUIREMENTS = {
    Path("README.md"): COMMON_LANDING_REQUIREMENTS
    + (LEGISLATION_DESCRIPTOR, WHOLE_LAW_DESCRIPTOR, "`bundle`", "`bundle/whole-law`"),
    Path("docs/index.md"): COMMON_LANDING_REQUIREMENTS
    + (LEGISLATION_DESCRIPTOR, WHOLE_LAW_DESCRIPTOR, "`bundle`", "`bundle/whole-law`"),
    Path("docs/roles/index.md"): COMMON_LANDING_REQUIREMENTS
    + (LEGISLATION_DESCRIPTOR, WHOLE_LAW_DESCRIPTOR, "`bundle`", "`bundle/whole-law`"),
    Path("whole-law/index.md"): COMMON_LANDING_REQUIREMENTS
    + (
        WHOLE_LAW_DESCRIPTOR,
        "`bundle/whole-law`",
        *WHOLE_LAW_SEMANTIC_PATHS,
    ),
    Path("bundle/index.md"): COMMON_LANDING_REQUIREMENTS
    + (LEGISLATION_DESCRIPTOR, "`bundle`"),
    Path("bundle/docs/index.md"): COMMON_LANDING_REQUIREMENTS
    + (LEGISLATION_DESCRIPTOR, WHOLE_LAW_DESCRIPTOR, "`bundle`", "`bundle/whole-law`"),
    Path("bundle/docs/roles/index.md"): COMMON_LANDING_REQUIREMENTS
    + (LEGISLATION_DESCRIPTOR, WHOLE_LAW_DESCRIPTOR, "`bundle`", "`bundle/whole-law`"),
    Path("bundle/docs/index.html"): COMMON_LANDING_REQUIREMENTS
    + (LEGISLATION_DESCRIPTOR, WHOLE_LAW_DESCRIPTOR, "bundle", "bundle/whole-law"),
    Path("bundle/index.html"): COMMON_LANDING_REQUIREMENTS
    + (
        LEGISLATION_DESCRIPTOR,
        WHOLE_LAW_DESCRIPTOR,
        "v0.3.0",
        "27 July 2026",
        "OKF 0.2",
    ),
    Path("bundle/evaluation/index.html"): COMMON_LANDING_REQUIREMENTS
    + (LEGISLATION_DESCRIPTOR, "bundle"),
    Path("bundle/whole-law/index.md"): COMMON_LANDING_REQUIREMENTS
    + (
        WHOLE_LAW_DESCRIPTOR,
        "`bundle/whole-law`",
        *WHOLE_LAW_SEMANTIC_PATHS,
    ),
    Path("bundle/whole-law/index.html"): COMMON_LANDING_REQUIREMENTS
    + (
        WHOLE_LAW_DESCRIPTOR,
        "bundle/whole-law",
        *WHOLE_LAW_SEMANTIC_PATHS,
    ),
    Path("bundle/whole-law/docs/index.md"): COMMON_LANDING_REQUIREMENTS
    + (
        WHOLE_LAW_DESCRIPTOR,
        "`bundle/whole-law`",
        *WHOLE_LAW_SEMANTIC_PATHS,
    ),
    Path("bundle/whole-law/docs/index.html"): COMMON_LANDING_REQUIREMENTS
    + (
        WHOLE_LAW_DESCRIPTOR,
        "bundle/whole-law",
        *WHOLE_LAW_SEMANTIC_PATHS,
    ),
    Path("bundle/whole-law/evaluation/index.md"): COMMON_LANDING_REQUIREMENTS
    + (WHOLE_LAW_DESCRIPTOR, "`bundle/whole-law`"),
    Path("bundle/whole-law/evaluation/index.html"): COMMON_LANDING_REQUIREMENTS
    + (WHOLE_LAW_DESCRIPTOR, "bundle/whole-law"),
}
CANONICAL_MACHINE_IDENTIFIERS = {
    Path("evaluation/legislation/answer-schema.json"): {
        "$id": (
            "https://chris-page-gov.github.io/okf-uk-legislation/"
            "evaluation/answer-schema.json"
        )
    },
    Path("evaluation/legislation/questions.json"): {
        "target_bundle": LEGISLATION_DESCRIPTOR
    },
    Path("whole-law/evaluation/answer-schema.json"): {
        "$id": (
            "https://chris-page-gov.github.io/okf-uk-legislation/"
            "whole-law/evaluation/answer-schema.json"
        )
    },
}


def authored_pages() -> list[Path]:
    pages: list[Path] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if (
            path.is_file()
            and path.suffix.lower() in {".md", ".html"}
            and not any(part in SKIP_PARTS for part in relative.parts)
        ):
            pages.append(path)
    return sorted(pages)


def markdown_targets(text: str) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    fence_marker: str | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)[0]
            fence_marker = marker if fence_marker is None else (
                None if marker == fence_marker else fence_marker
            )
            continue
        if fence_marker is not None:
            continue
        targets.extend((line_number, match.group(1)) for match in INLINE.finditer(line))
        reference = REFERENCE.match(line)
        if reference:
            targets.append((line_number, reference.group(1)))
        targets.extend((line_number, match.group("target")) for match in HTML.finditer(line))
    return targets


def html_targets(text: str) -> list[tuple[int, str]]:
    return [
        (text.count("\n", 0, match.start()) + 1, match.group("target"))
        for match in HTML.finditer(text)
    ]


def json_targets(text: str) -> list[tuple[int, str]]:
    """Return URL strings from valid JSON with useful source line numbers."""

    json.loads(text)
    targets: list[tuple[int, str]] = []
    for match in JSON_URL.finditer(text):
        target = match.group(0)
        targets.append((text.count("\n", 0, match.start()) + 1, target))
    return targets


def policy_documents() -> list[Path]:
    """Return mutable documentation/contracts subject to canonical URL policy."""

    paths = set(authored_pages())
    for root in (ROOT / "docs", ROOT / "evaluation", ROOT / "whole-law" / "evaluation"):
        if root.exists():
            paths.update(path for path in root.rglob("*.json") if path.is_file())
    paths.update(ROOT / relative for relative in LANDING_REQUIREMENTS)
    paths.update((ROOT / "bundle" / "docs" / "assets").rglob("*.json"))
    return sorted(path for path in paths if path.is_file())


def url_policy_failures(source: Path, text: str) -> list[str]:
    failures: list[str] = []
    decoded = text
    for _ in range(2):
        decoded = unquote(decoded)
    lowered = decoded.lower()
    for prefix in STALE_MACHINE_PREFIXES:
        if prefix.lower() in lowered:
            failures.append(
                f"{source.relative_to(ROOT)}: stale or guessed machine route {prefix!r}"
            )
    if (
        COMPATIBILITY_PREFIX.lower() in lowered
        and not any(label in text.lower() for label in COMPATIBILITY_LABELS)
    ):
        failures.append(
            f"{source.relative_to(ROOT)}: compatibility-site URL is not labelled "
            "as preserved, historical or compatibility"
        )
    return failures


def landing_requirement_failures(
    relative: Path,
    text: str,
    requirements: tuple[str, ...] | None = None,
) -> list[str]:
    required = requirements if requirements is not None else LANDING_REQUIREMENTS[relative]
    return [
        f"{relative}: missing required landing-page route or declaration {token!r}"
        for token in required
        if token not in text
    ]


def hosted_relative_path(target: str) -> str | None:
    parsed = urlsplit(target)
    if parsed.scheme not in {"http", "https"}:
        return None
    parts = [part for part in unquote(parsed.path).split("/") if part]
    if parsed.netloc == PAGES_HOST:
        if not parts or parts[0] != PAGES_PREFIX.lstrip("/"):
            return None
        return "/".join(parts[1:])
    if parsed.netloc == "github.com":
        if tuple(parts[:2]) != GITHUB_REPO:
            return None
        remainder = parts[2:]
        if remainder and remainder[0] in {
            "actions",
            "issues",
            "pulls",
            "releases",
            "security",
        }:
            return None
        if remainder and remainder[0] in {"blob", "tree"}:
            remainder = remainder[2:]
        return "/".join(remainder)
    if parsed.netloc == "raw.githubusercontent.com":
        if tuple(parts[:2]) != GITHUB_REPO:
            return None
        return "/".join(parts[3:])
    return None


def nested_internal_urls(target: str) -> list[str]:
    return [
        value
        for values in parse_qs(urlsplit(target).query).values()
        for value in values
        if hosted_relative_path(value) is not None
    ]


def candidate_path(source: Path, target: str) -> Path | None:
    target = target.strip().strip("<>")
    if not target or target.startswith("#"):
        return source
    parsed = urlsplit(target)
    if parsed.scheme:
        relative = hosted_relative_path(target)
        return None if relative is None else (ROOT / relative).resolve()
    relative = unquote(parsed.path)
    if not relative:
        return source
    if relative == PAGES_PREFIX or relative.startswith(f"{PAGES_PREFIX}/"):
        relative = relative[len(PAGES_PREFIX) :].lstrip("/")
        return (ROOT / relative).resolve()
    if relative.startswith("/"):
        return (ROOT / relative.lstrip("/")).resolve()
    return (source.parent / relative).resolve()


def target_exists(path: Path) -> bool:
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return False
    # Authored links deliberately use their public Pages routes. Pages deploys
    # bundle/, so a target can be generated there while retaining the same
    # repository-relative route in its published URL.
    for candidate_root in (path, ROOT / "bundle" / relative):
        if candidate_root.exists():
            return True
        if not candidate_root.suffix and any(
            candidate.is_file()
            for candidate in (
                candidate_root.with_suffix(".md"),
                candidate_root.with_suffix(".html"),
                candidate_root / "index.md",
                candidate_root / "index.html",
            )
        ):
            return True
    return False


def main() -> int:
    failures: list[str] = []
    checked = 0
    pages = authored_pages()
    for source in pages:
        text = source.read_text(encoding="utf-8")
        targets = markdown_targets(text) if source.suffix.lower() == ".md" else html_targets(text)
        for line_number, target in targets:
            for candidate in (target, *nested_internal_urls(target)):
                path = candidate_path(source, candidate)
                if path is None:
                    continue
                checked += 1
                if target_exists(path):
                    continue
                rendered = (
                    path.relative_to(ROOT).as_posix()
                    if path.is_relative_to(ROOT)
                    else str(path)
                )
                failures.append(
                    f"{source.relative_to(ROOT)}:{line_number}: "
                    f"missing internal target {candidate!r} -> {rendered}"
                )
    json_manifests = sorted((ROOT / "docs" / "assets").rglob("*.json"))
    for source in json_manifests:
        text = source.read_text(encoding="utf-8")
        try:
            targets = json_targets(text)
        except json.JSONDecodeError as exc:
            failures.append(
                f"{source.relative_to(ROOT)}:{exc.lineno}: invalid JSON: {exc.msg}"
            )
            continue
        for line_number, target in targets:
            for candidate in (target, *nested_internal_urls(target)):
                path = candidate_path(source, candidate)
                if path is None:
                    continue
                checked += 1
                if not target_exists(path):
                    rendered = (
                        path.relative_to(ROOT).as_posix()
                        if path.is_relative_to(ROOT)
                        else str(path)
                    )
                    failures.append(
                        f"{source.relative_to(ROOT)}:{line_number}: "
                        f"missing internal target {candidate!r} -> {rendered}"
                    )
    for source in policy_documents():
        failures.extend(url_policy_failures(source, source.read_text(encoding="utf-8")))
    for relative in LANDING_REQUIREMENTS:
        source = ROOT / relative
        if not source.is_file():
            failures.append(f"{relative}: required landing page is missing")
            continue
        failures.extend(
            landing_requirement_failures(
                relative,
                source.read_text(encoding="utf-8"),
            )
        )
    for relative, expected_fields in CANONICAL_MACHINE_IDENTIFIERS.items():
        source = ROOT / relative
        if not source.is_file():
            failures.append(f"{relative}: required machine entry point is missing")
            continue
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{relative}:{exc.lineno}: invalid JSON: {exc.msg}")
            continue
        for field, expected in expected_fields.items():
            if payload.get(field) != expected:
                failures.append(
                    f"{relative}: {field} must be canonical {expected!r}, "
                    f"found {payload.get(field)!r}"
                )
    if failures:
        print("internal link validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "internal link validation passed: "
        f"{len(pages)} authored pages, {len(json_manifests)} JSON manifests, "
        f"{len(policy_documents())} URL-policy documents, "
        f"{len(LANDING_REQUIREMENTS)} landing pages, {checked} internal links"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
