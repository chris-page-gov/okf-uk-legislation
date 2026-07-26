#!/usr/bin/env python3
"""Fail when an authored UK Legislation/Whole-Law page guesses a local route."""

from __future__ import annotations

import re
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
    if failures:
        print("internal link validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"internal link validation passed: {len(pages)} pages, {checked} internal links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
