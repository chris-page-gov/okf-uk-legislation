#!/usr/bin/env python3
"""Render maintained Markdown as self-contained, accessible Pages HTML."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

LEGACY_AUTHORING = (
    "https://chris-page-gov.github.io/ai-infrastructure-wiki/"
    "docs/okf-bundle-authoring.md"
)
FOUNDRY_AUTHORING = (
    "https://chris-page-gov.github.io/okf-explorer/"
    "docs/beginners/19-foundry-authoring-and-domain-profiles.html"
)
PAGES_ORIGIN = "https://chris-page-gov.github.io"
PAGES_PREFIX = "/okf-uk-legislation/"
FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)


def markdown_renderer() -> MarkdownIt:
    """Return the pinned renderer configuration used by every HTML guide."""

    return MarkdownIt("commonmark", {"html": False, "linkify": True}).enable(
        "table"
    )


def html_target(target: str) -> str:
    """Route Pages Markdown links to their generated HTML representation."""

    if target == LEGACY_AUTHORING:
        return FOUNDRY_AUTHORING
    parsed = urlsplit(target)
    if parsed.scheme in {"http", "https"}:
        if (
            parsed.scheme == "https"
            and parsed.netloc == "chris-page-gov.github.io"
            and parsed.path.startswith(PAGES_PREFIX)
            and parsed.path.endswith(".md")
        ):
            return urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path[:-3] + ".html", parsed.query, parsed.fragment)
            )
        return target
    if parsed.scheme or target.startswith(("#", "mailto:", "tel:")):
        return target
    if parsed.path.endswith(".md"):
        return urlunsplit(("", "", parsed.path[:-3] + ".html", parsed.query, parsed.fragment))
    return target


def first_heading(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def render_markdown_page(
    markdown: str,
    *,
    output_relative: Path,
    fallback_title: str,
    publication_label: str = "UK Legislation and Whole-Law OKF",
) -> bytes:
    """Render one Markdown source with safe links and publication navigation."""

    markdown = FRONTMATTER.sub("", markdown, count=1)
    title = first_heading(markdown, fallback_title)
    fragment = markdown_renderer().render(markdown)
    soup = BeautifulSoup(fragment, "html.parser")
    for element in soup.find_all(["a", "img"]):
        attribute = "href" if element.name == "a" else "src"
        value = element.get(attribute)
        if isinstance(value, str):
            element[attribute] = html_target(value)
        if element.name == "a" and isinstance(element.get("href"), str):
            href = str(element["href"])
            if href.startswith(("http://", "https://")):
                element["rel"] = "noopener noreferrer"
    depth = len(output_relative.parent.parts)
    root = "../" * depth or "./"
    docs = f"{root}docs/"
    explorer = (
        "https://chris-page-gov.github.io/okf-explorer/"
        "?bundle=https%3A%2F%2Fchris-page-gov.github.io%2F"
        "okf-uk-legislation%2Fokf-explorer.json&view=reader#overview"
    )
    document = f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} – {html.escape(publication_label)}</title>
<link rel="stylesheet" href="{root}assets/site.css">
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<header class="site-header">
<p class="eyebrow">{html.escape(publication_label)}</p>
<nav aria-label="Publication"><a href="{root}">Home</a> <a href="{docs}">Documentation</a> <a href="{explorer}">Open Explorer</a></nav>
</header>
<main id="main-content" class="document-page">
{soup.decode_contents()}
</main>
<footer><p>Independent public prototype. Verify legal effect and current text against the cited official source. Model-assisted discovery metadata is not official legal classification or legal advice.</p></footer>
</body>
</html>
"""
    return document.encode("utf-8")
