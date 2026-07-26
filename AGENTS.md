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
- Run the unit suite, complete publication validator and checksum check before
  committing. Do not bypass authentication or erase a source constraint.
