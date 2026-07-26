# Repository working agreement

- Treat `bundle/` as generated publication data and `scripts/` plus official
  source responses as its provenance.
- Keep YAML-LD, JSON-LD, Explorer JSON, documentation, checksums and release
  notes synchronized in the same change.
- Never describe derived topics, entities or model output as official legal
  classification or legal advice.
- Preserve item-level official identifiers, licence metadata, confidence,
  evidence type and timestamps on every relationship.
- Never edit a completed source-acquisition attempt in place. Seal the exact
  run with `scripts/source_access_evidence_archive.py`, verify the extracted
  original integrity manifest, and publish a separately identified metadata
  projection. A redaction or hosting constraint changes only the projection
  and its receipt, never the immutable original.
- Do not invoke LibreOffice, `soffice`, Quick Look or another GUI-backed
  document renderer. `soffice` 26.2.3.2 aborts while registering its macOS GUI
  when launched by Codex, before rendering begins, and repeated attempts create
  crash dialogs without useful output. Extract DOCX evidence with Pandoc or
  `python-docx`; retain the original DOCX and record any rendering limitation.
- Treat an application abort or repeatable helper crash as a stop condition,
  not a retry condition. Record the failed command and observed side effects,
  verify source inputs were not modified, and switch to a bounded non-GUI
  alternative. Do not re-enable the failing path unless its cause has been
  isolated and a controlled test demonstrates that it is safe.
- Keep the live worktree and Codex UI workload bounded. Do not ask the app to
  render or inspect thousands of generated diffs. Use summarized status
  commands, validate in a clean candidate, and commit each green tranche
  before accumulating another broad generated change. A large dirty worktree
  is a stability risk, not proof of a crash cause.
- After a Codex task/app restart, recover from on-disk evidence: verify the
  current branch, source hashes and the narrowest relevant checks before
  continuing. Do not replay an external write, paid call, release action or
  helper invocation merely because its prior completion is uncertain.
- Do not run `scripts/enrich_legislation_semantics.py`. It is a preserved
  historical v1 API prototype whose default output is immutable evidence and
  which lacks the approved model-selection, reviewer, cache, cost-cap and
  append-only attempt contracts. The current release must use the governed
  Codex task/subagent enrichment path and must not be gated on an API key or
  make a direct paid API call. The direct API runner is retained only as an
  optional future profile that would require a new explicit user decision;
  never repurpose or overwrite the historical v1 artefact.
- Report direct OpenAI API spend for the current implementation as exactly
  USD 0 and GBP 0. Codex subscription or weekly-allowance consumption, exact
  underlying deployment identity and billable task-surface token usage are not
  exposed to the repository and must be recorded as unavailable/unmetered,
  never invented or presented as evidence that total economic cost is zero.
- Treat a GitHub CLI failure inside a restricted sandbox as inconclusive about
  the stored credential. Repeat a safe read-only authentication check outside
  the restricted sandbox before diagnosing an invalid token; never print or
  persist the token value.
- Run the unit suite, complete publication validator and checksum check before
  committing. Do not bypass authentication or erase a source constraint.
