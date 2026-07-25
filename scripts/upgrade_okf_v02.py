#!/usr/bin/env python3
"""Deterministically upgrade the checked legislation publication to OKF v0.2."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
ACTOR = "process:legislation-okf-builder"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    raw, body = text[4:].split("\n---\n", 1)
    values: dict[str, Any] = {}
    for line in raw.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        try:
            values[key] = json.loads(value)
        except json.JSONDecodeError:
            values[key] = value
    return values, body


def concept_document(text: str, generated_at: str) -> str:
    values, body = split_frontmatter(text)
    if not values:
        raise ValueError("generated concept is missing legacy frontmatter")
    sources: list[dict[str, str]] = []
    resource = str(values.get("resource") or "")
    if resource:
        sources.append({"id": "official-source", "resource": resource})
    for identifier, label, url in re.findall(
        r"(?m)^\[(\d+)\]\s+\[([^\]]+)\]\(([^)]+)\)\s*$", body
    ):
        if any(source["resource"] == url for source in sources):
            continue
        sources.append(
            {"id": f"reference-{identifier}", "resource": url, "title": label}
        )
    frontmatter = {
        "type": values["type"],
        "title": values.get("title"),
        "description": values.get("description"),
        "resource": resource,
        "tags": values.get("tags") or [],
        "generated": {"by": ACTOR, "at": generated_at},
        "status": "draft",
        "sources": sources,
    }
    rendered = "---\n" + "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in frontmatter.items()
    )
    body = re.sub(r"(?m)^# Citations\s*$", "# Source notes", body)
    return rendered + "\n---\n" + body


def evaluation_document(text: str, generated_at: str, relative: Path) -> str:
    repository_url = (
        "https://github.com/chris-page-gov/okf-uk-legislation/"
        f"blob/main/evaluation/legislation/{relative.as_posix()}"
    )
    frontmatter = {
        "type": "Evaluation Reference",
        "title": relative.stem.replace("-", " ").replace("_", " "),
        "description": "Evaluation contract for the UK Legislation OKF publication.",
        "resource": repository_url,
        "tags": ["evaluation", "quality"],
        "generated": {"by": ACTOR, "at": generated_at},
        "status": "draft",
        "sources": [
            {
                "id": "repository-source",
                "resource": repository_url,
                "title": relative.name,
            }
        ],
    }
    return (
        "---\n"
        + "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in frontmatter.items()
        )
        + "\n---\n\n"
        + text.lstrip("\n")
    )


def main() -> int:
    descriptor_path = BUNDLE / "okf-explorer.json"
    manifest_path = BUNDLE / "data/manifest.json"
    descriptor = load_json(descriptor_path)
    manifest = load_json(manifest_path)
    generated_at = descriptor["generated_at"]
    descriptor.update(
        {
            "okf_version": "0.2",
            "core_conformance": "Markdown concept layer",
        }
    )
    manifest["okf_version"] = "0.2"
    write_json(descriptor_path, descriptor)
    write_json(manifest_path, manifest)
    for name in ("okf-bundle.yamlld", "okf-bundle.jsonld"):
        path = BUNDLE / name
        semantic = load_json(path)
        semantic["okf_version"] = "0.2"
        if name.endswith(".yamlld"):
            path.write_text(
                json.dumps(semantic, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            write_json(path, semantic)

    changed = 0
    for path in sorted(BUNDLE.rglob("*.md")):
        relative = path.relative_to(BUNDLE)
        text = path.read_text(encoding="utf-8")
        if relative == Path("index.md"):
            _values, body = split_frontmatter(text)
            body = re.sub(r"(?m)^# Citations\s*$", "# Source notes", body)
            updated = '---\nokf_version: "0.2"\n---\n\n' + body.lstrip("\n")
        elif path.name == "index.md":
            _values, body = split_frontmatter(text)
            body = re.sub(r"(?m)^# Citations\s*$", "# Source notes", body)
            updated = body.lstrip("\n")
        elif path.name == "log.md":
            _values, body = split_frontmatter(text)
            body = body.lstrip("\n")
            body = re.sub(r"^# Legislation OKF generation log\n+", "", body)
            body = re.sub(r"^# (\d{4}-\d{2}-\d{2})$", r"## \1", body, count=1, flags=re.MULTILINE)
            updated = "# Legislation OKF generation log\n\n" + body
        elif relative.parts[0] == "evaluation" and not text.startswith("---\n"):
            updated = evaluation_document(text, generated_at, Path(*relative.parts[1:]))
        elif text.startswith("---\n") and "\ngenerated:" in text.split("\n---\n", 1)[0]:
            updated = text
        else:
            updated = concept_document(text, generated_at)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    print(f"upgraded {changed} Markdown files to OKF v0.2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
