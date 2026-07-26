#!/bin/sh
set -eu

if [ -x ".venv/bin/python3" ]; then
  PATH="$(pwd)/.venv/bin:$PATH"
  export PATH
fi

validation_tmp="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/okf-publication-validation.XXXXXX")"
cleanup() {
  rm -rf "$validation_tmp"
}
trap cleanup EXIT INT TERM

python3 -m unittest discover -s tests -v
python3 scripts/build_publication_docs.py --check
python3 scripts/check_internal_links.py
python3 scripts/rebuild_legislation_discovery.py --check
python3 scripts/check_legislation_okf.py
python3 scripts/legislation_effects_evidence_archive.py check \
  --snapshot-id legislation-effects-2026-07-25
python3 scripts/build_legislation_effects.py --check
python3 scripts/reconcile_legislation_effects_live.py check
python3 scripts/build_model_enrichment_input_evidence.py --check
python3 scripts/build_codex_semantic_enrichment.py --check
python3 scripts/build_model_enrichment_paid_publication.py --check
python3 scripts/audit_model_assisted_v2_independent.py --check
python3 scripts/build_whole_law_evaluation.py --check
python3 scripts/run_release_evaluation.py --check
python3 scripts/run_yaml_ld_conformance.py --check
python3 scripts/run_ontology_competency_questions.py --check
python3 scripts/build_whole_law_okf.py --check
python3 scripts/check_whole_law_okf.py
python3 scripts/audit_graph_enrichment_gate.py check
python3 scripts/build_release_assurance.py --check
python3 scripts/build_checksums.py --check
python3 scripts/build_legislation_okf.py \
  --fixture tests/fixtures/legislation_okf/sample.feed.xml \
  --output "$validation_tmp/fixture" \
  --generated-at 2026-07-11T00:00:00Z
