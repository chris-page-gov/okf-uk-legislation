#!/usr/bin/env python3
"""Run the pinned W3C YAML-LD suite against the release processor stack."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import rdflib
import yaml_ld
from pyld import jsonld
from rdflib.compare import isomorphic
from yaml_ld.compact import CompactOptions
from yaml_ld.document_loaders.local_file import LocalFileDocumentLoader
from yaml_ld.errors import LoadingDocumentFailed, YAMLLDError
from yaml_ld.expand import ExpandOptions, except_json_ld_errors
from yaml_ld.flatten import FlattenOptions
from yaml_ld.frame import FrameOptions
from yaml_ld.to_rdf import ToRDFOptions

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "standards" / "yaml-ld-tests"
MANIFEST = SUITE / "manifest.jsonld"
SOURCE = SUITE / "SOURCE.json"
OUTPUT = ROOT / "whole-law" / "assurance" / "yaml-ld-conformance.json"
GENERATED_AT = "2026-07-25T23:21:42Z"
SUITE_BASE = "https://w3c.github.io/yaml-ld/tests/"
PERSON_CONTEXT = "https://json-ld.org/contexts/person.jsonld"
LOCAL_FILE_LOADER = LocalFileDocumentLoader()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yaml_document(path: Path) -> Any:
    return yaml_ld.load_document(path)["document"]


def suite_document_loader(source: Any, options: Any) -> dict[str, Any]:
    url = str(source)
    if url.startswith(SUITE_BASE):
        local = SUITE / url.removeprefix(SUITE_BASE)
    elif url == PERSON_CONTEXT:
        local = SUITE / "contexts" / "person.jsonld"
    else:
        local = Path(url.removeprefix("file://")).resolve()
        try:
            local.relative_to(SUITE.resolve())
        except ValueError:
            raise ValueError(
                f"unpinned remote document in YAML-LD suite: {url}"
            ) from None
    loaded = LOCAL_FILE_LOADER(local, options)
    if (
        isinstance(loaded.get("document"), dict)
        and "@context" not in loaded["document"]
        and "context" in local.name
    ):
        loaded["document"] = {"@context": loaded["document"]}
    loaded["documentUrl"] = url
    return loaded


def reject_nonfinite(
    value: Any,
    source: Path,
    ancestors: set[int] | None = None,
) -> None:
    ancestors = set() if ancestors is None else ancestors
    if isinstance(value, float) and not math.isfinite(value):
        raise LoadingDocumentFailed(path=str(source))
    if isinstance(value, (dict, list)):
        marker = id(value)
        if marker in ancestors:
            raise LoadingDocumentFailed(path=str(source))
        ancestors.add(marker)
        values = value.values() if isinstance(value, dict) else value
        for item in values:
            reject_nonfinite(item, source, ancestors)
        ancestors.remove(marker)


def release_expand(
    input_path: Path,
    *,
    base: str,
    extract_all_scripts: bool,
) -> list[dict[str, Any]]:
    loader_options = {
        "base": base,
        "extractAllScripts": extract_all_scripts,
        "headers": {},
    }
    loaded = suite_document_loader(input_path, loader_options)
    reject_nonfinite(loaded["document"], input_path)
    options = {
        "base": base,
        "documentLoader": suite_document_loader,
        "extractAllScripts": extract_all_scripts,
    }
    with except_json_ld_errors():
        expanded = jsonld.expand(loaded["document"], options)
        if (
            not expanded
            and isinstance(loaded["document"], dict)
            and "@id" in loaded["document"]
        ):
            expanded = jsonld.expand(
                loaded["document"],
                {**options, "keepFreeFloatingNodes": True},
            )
        return expanded


def equivalent(left: Any, right: Any, *, ordered: bool = False, key: str = "") -> bool:
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            equivalent(left[name], right[name], ordered=ordered, key=name)
            for name in left
        )
    if isinstance(left, list):
        if len(left) != len(right):
            return False
        if ordered or key == "@list":
            return all(
                equivalent(a, b, ordered=ordered)
                for a, b in zip(left, right, strict=True)
            )
        remaining = list(right)
        for item in left:
            for index, candidate in enumerate(remaining):
                if equivalent(item, candidate, ordered=ordered):
                    remaining.pop(index)
                    break
            else:
                return False
        return not remaining
    return left == right


def rdf_graph(value: str) -> rdflib.ConjunctiveGraph:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        graph = rdflib.ConjunctiveGraph()
        graph.parse(data=value, format="nquads")
    return graph


def run_positive(case: dict[str, Any], manifest: dict[str, Any]) -> tuple[bool, str]:
    input_path = SUITE / case["input"]
    expected_path = SUITE / case["expect"]
    options = case.get("option", {})
    base = urljoin(str(manifest["baseIri"]), str(case["input"]))
    common = {
        "base": base,
        "documentLoader": suite_document_loader,
        "extractAllScripts": bool(options.get("extractAllScripts", False)),
    }
    types = set(case["@type"])
    if "jld:ExpandTest" in types:
        actual = release_expand(
            input_path,
            base=base,
            extract_all_scripts=bool(options.get("extractAllScripts", False)),
        )
        expected = yaml_document(expected_path)
    elif "jld:CompactTest" in types:
        actual = yaml_ld.compact(
            input_path,
            yaml_document(SUITE / case["context"]),
            CompactOptions(
                **common,
                compactArrays=bool(options.get("compactArrays", True)),
            ),
        )
        expected = yaml_document(expected_path)
    elif "jld:FlattenTest" in types:
        actual = yaml_ld.flatten(
            input_path,
            yaml_document(SUITE / case["context"]),
            FlattenOptions(
                **common,
                compactArrays=bool(options.get("compactArrays", True)),
            ),
        )
        expected = yaml_document(expected_path)
    elif "jld:FrameTest" in types:
        frame = yaml_document(SUITE / case["frame"])
        actual = yaml_ld.frame(input_path, frame, FrameOptions(**common))
        expected = yaml_document(expected_path)
    elif "jld:ToRDFTest" in types:
        actual_nquads = yaml_ld.to_rdf(
            input_path,
            ToRDFOptions(**common, format="application/n-quads"),
        )
        expected_nquads = expected_path.read_text(encoding="utf-8")
        return (
            isomorphic(rdf_graph(actual_nquads), rdf_graph(expected_nquads)),
            "RDF dataset isomorphism",
        )
    else:
        return False, f"unsupported test type: {sorted(types)}"
    return (
        equivalent(
            actual,
            expected,
            ordered=bool(options.get("ordered", False)),
        ),
        "YAML-LD object comparison",
    )


def run_negative(case: dict[str, Any], manifest: dict[str, Any]) -> tuple[bool, str]:
    input_path = SUITE / case["input"]
    options = case.get("option", {})
    base = urljoin(str(manifest["baseIri"]), str(case["input"]))
    expected_code = str(case["expectErrorCode"])
    try:
        release_expand(
            input_path,
            base=base,
            extract_all_scripts=bool(options.get("extractAllScripts", False)),
        )
    except YAMLLDError as exc:
        actual_code = str(getattr(exc, "code", type(exc).__name__))
        return actual_code == expected_code, f"expected {expected_code}; got {actual_code}"
    except Exception as exc:  # processor errors must still be recorded fail-closed
        return False, f"unexpected {type(exc).__name__}"
    return False, f"expected {expected_code}; no error raised"


def build_result() -> dict[str, Any]:
    source = load_json(SOURCE)
    if sha256(MANIFEST) != source["manifest_sha256"]:
        raise ValueError("vendored YAML-LD manifest does not match SOURCE.json")
    manifest = load_json(MANIFEST)
    results = []
    for case in manifest["sequence"]:
        normative = bool(case.get("option", {}).get("normative", True))
        negative = "jld:NegativeEvaluationTest" in case["@type"]
        try:
            passed, comparison = (
                run_negative(case, manifest)
                if negative
                else run_positive(case, manifest)
            )
        except Exception as exc:
            passed = False
            comparison = f"{type(exc).__name__}: {exc}"
        results.append(
            {
                "id": case["@id"],
                "name": case["name"],
                "normative": normative,
                "requirement_level": case.get("req", "unspecified"),
                "status": "passed" if passed else "failed",
                "test_types": case["@type"],
                "method": comparison,
            }
        )
    normative = [row for row in results if row["normative"]]
    informative = [row for row in results if not row["normative"]]
    counts = {
        "total": len(results),
        "passed": sum(row["status"] == "passed" for row in results),
        "failed": sum(row["status"] == "failed" for row in results),
        "normative_total": len(normative),
        "normative_passed": sum(row["status"] == "passed" for row in normative),
        "normative_failed": sum(row["status"] == "failed" for row in normative),
        "informative_total": len(informative),
        "informative_passed": sum(
            row["status"] == "passed" for row in informative
        ),
        "informative_failed": sum(
            row["status"] == "failed" for row in informative
        ),
    }
    return {
        "schema": "okf-yaml-ld-conformance-receipt.v1",
        "generated_at": GENERATED_AT,
        "processor": {
            "yaml-ld": importlib.metadata.version("yaml-ld"),
            "PyLD": importlib.metadata.version("PyLD"),
            "rdflib": importlib.metadata.version("rdflib"),
        },
        "suite": source,
        "counts": counts,
        "release_effect": (
            "passed"
            if counts["normative_failed"] == 0
            else "blocked-normative-suite-failure"
        ),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        body = render(build_result())
    except Exception as exc:
        print(f"YAML-LD conformance setup failed: {exc}")
        return 1
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != body:
            print("YAML-LD conformance receipt is missing or out of date")
            return 1
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_bytes(body)
    result = json.loads(body)
    counts = result["counts"]
    print(
        "YAML-LD suite: "
        f"{counts['normative_passed']}/{counts['normative_total']} normative; "
        f"{counts['informative_passed']}/{counts['informative_total']} informative"
    )
    return 0 if counts["normative_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
