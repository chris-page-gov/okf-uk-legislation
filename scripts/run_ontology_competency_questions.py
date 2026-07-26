#!/usr/bin/env python3
"""Execute the Whole-Law ontology competency questions deterministically."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any

import rdflib

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "whole-law" / "ontology"
ASSURANCE = ROOT / "whole-law" / "assurance"
QUESTIONS = ONTOLOGY / "competency-questions.json"
EXAMPLES = ONTOLOGY / "examples.jsonld"
VOCABULARY = ONTOLOGY / "vocabulary.ttl"
SHAPES = ONTOLOGY / "shapes.ttl"
OUTPUT = ASSURANCE / "competency-question-results.json"

OKFLAW = "https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#"
PREFIXES = {
    "okflaw": OKFLAW,
    "prov": "http://www.w3.org/ns/prov#",
    "eli": "http://data.europa.eu/eli/ontology#",
    "dcterms": "http://purl.org/dc/terms/",
    "oa": "http://www.w3.org/ns/oa#",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expand_term(term: str) -> str:
    if ":" not in term:
        return OKFLAW + term
    prefix, local = term.split(":", 1)
    if prefix not in PREFIXES:
        raise ValueError(f"unsupported competency-question prefix: {prefix}")
    return PREFIXES[prefix] + local


def graph_contains_term(graph: rdflib.Graph, iri: str) -> bool:
    value = rdflib.URIRef(iri)
    return any(value in triple for triple in graph)


def build_receipt() -> dict[str, Any]:
    suite = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    questions = suite.get("questions", [])
    if not questions:
        raise ValueError("competency-question suite is empty")

    examples = rdflib.Graph()
    vocabulary = rdflib.Graph()
    shapes = rdflib.Graph()
    examples.parse(EXAMPLES, format="json-ld")
    vocabulary.parse(VOCABULARY, format="turtle")
    shapes.parse(SHAPES, format="turtle")
    contract_graph = examples + vocabulary + shapes

    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for question in questions:
        question_id = question.get("id")
        query = question.get("ask")
        required_terms = question.get("required_terms")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("competency question lacks a non-empty id")
        if question_id in seen:
            raise ValueError(f"duplicate competency-question id: {question_id}")
        seen.add(question_id)
        if not isinstance(query, str) or not query.lstrip().upper().startswith("PREFIX"):
            raise ValueError(f"{question_id} lacks an executable SPARQL ASK query")
        if not isinstance(required_terms, list) or not required_terms:
            raise ValueError(f"{question_id} lacks required_terms")

        term_results = []
        for term in required_terms:
            iri = expand_term(term)
            local = iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            declared_or_used = graph_contains_term(contract_graph, iri)
            referenced_by_query = iri in query or f":{local}" in query
            term_results.append(
                {
                    "term": term,
                    "iri": iri,
                    "declared_or_used": declared_or_used,
                    "referenced_by_query": referenced_by_query,
                    "passed": declared_or_used and referenced_by_query,
                }
            )

        query_result = examples.query(query)
        ask_passed = bool(getattr(query_result, "askAnswer", False))
        passed = ask_passed and all(row["passed"] for row in term_results)
        results.append(
            {
                "id": question_id,
                "question": question["question"],
                "ask_result": ask_passed,
                "required_terms": term_results,
                "passed": passed,
            }
        )

    passed = sum(1 for row in results if row["passed"])
    return {
        "schema": "okf-ontology-competency-results.v1",
        "suite": suite["schema"],
        "status": "passed" if passed == len(results) else "failed",
        "counts": {
            "questions": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "sources": {
            "competency_questions": {
                "path": str(QUESTIONS.relative_to(ROOT)),
                "sha256": sha256(QUESTIONS),
            },
            "examples": {
                "path": str(EXAMPLES.relative_to(ROOT)),
                "sha256": sha256(EXAMPLES),
                "triples": len(examples),
            },
            "vocabulary": {
                "path": str(VOCABULARY.relative_to(ROOT)),
                "sha256": sha256(VOCABULARY),
                "triples": len(vocabulary),
            },
            "shapes": {
                "path": str(SHAPES.relative_to(ROOT)),
                "sha256": sha256(SHAPES),
                "triples": len(shapes),
            },
        },
        "processor": {
            "python": ".".join(map(str, sys.version_info[:3])),
            "rdflib": importlib.metadata.version("rdflib"),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    receipt = build_receipt()
    rendered = canonical(receipt)
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"stale or missing competency-question receipt: {OUTPUT.relative_to(ROOT)}")
            return 1
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered, encoding="utf-8")

    counts = receipt["counts"]
    print(
        "Ontology competency questions "
        f"{receipt['status']}: {counts['passed']}/{counts['questions']} passed"
    )
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
