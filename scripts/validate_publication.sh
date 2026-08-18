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

validation_started="$(date +%s)"
if [ -n "${OKF_VALIDATION_TIMINGS:-}" ]; then
  : > "$OKF_VALIDATION_TIMINGS"
fi

run_step() {
  label="$1"
  shift
  started="$(date +%s)"
  printf '\nVALIDATION START\t%s\n' "$label"
  if "$@"; then
    status=0
  else
    status=$?
  fi
  ended="$(date +%s)"
  elapsed="$((ended - started))"
  printf 'VALIDATION TIMING\t%s seconds\t%s\n' "$elapsed" "$label"
  if [ -n "${OKF_VALIDATION_TIMINGS:-}" ]; then
    printf '%s\t%s\n' "$elapsed" "$label" >> "$OKF_VALIDATION_TIMINGS"
  fi
  return "$status"
}

run_step "publication contract" python3 scripts/check_publication_contract.py
run_step "unit suite" python3 -m unittest discover -s tests -v
run_step "publication documentation" python3 scripts/build_publication_docs.py --check
run_step "internal links" python3 scripts/check_internal_links.py
run_step "legislation discovery" python3 scripts/rebuild_legislation_discovery.py --check
run_step "legislation OKF" python3 scripts/check_legislation_okf.py
run_step "effects evidence archive" python3 scripts/legislation_effects_evidence_archive.py check \
  --snapshot-id legislation-effects-2026-07-25
run_step "effects projection" python3 scripts/build_legislation_effects.py --check
run_step "effects reconciliation" python3 scripts/reconcile_legislation_effects_live.py check
run_step "model input evidence" python3 scripts/build_model_enrichment_input_evidence.py --check
run_step "Codex v2 enrichment" python3 scripts/build_codex_semantic_enrichment.py --check
run_step "Codex v3 enrichment" python3 scripts/build_codex_semantic_enrichment_v3.py check
run_step "Codex v3 audit" python3 scripts/audit_codex_semantic_enrichment_v3.py check
run_step "model-assisted v2 audit" python3 scripts/audit_model_assisted_v2_independent.py --check
run_step "Whole-Law evaluation build" python3 scripts/build_whole_law_evaluation.py --check
run_step "release evaluation" python3 scripts/run_release_evaluation.py --check
run_step "YAML-LD conformance" python3 scripts/run_yaml_ld_conformance.py --check
run_step "ontology competency questions" python3 scripts/run_ontology_competency_questions.py --check
run_step "semantic conformance" python3 scripts/run_semantic_conformance.py --check
run_step "Whole-Law build" python3 scripts/build_whole_law_okf.py --check
run_step "Whole-Law OKF" python3 scripts/check_whole_law_okf.py
run_step "graph enrichment" python3 scripts/audit_graph_enrichment_gate.py check
run_step "release assurance" python3 scripts/build_release_assurance.py --check
run_step "checksums" python3 scripts/build_checksums.py --check
run_step "fixture build" python3 scripts/build_legislation_okf.py \
  --fixture tests/fixtures/legislation_okf/sample.feed.xml \
  --output "$validation_tmp/fixture" \
  --generated-at 2026-07-11T00:00:00Z

validation_ended="$(date +%s)"
printf '\nVALIDATION TOTAL\t%s seconds\n' "$((validation_ended - validation_started))"
