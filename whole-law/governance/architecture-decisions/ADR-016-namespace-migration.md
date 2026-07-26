# ADR-016: migrate the Whole-Law namespace without breaking published identifiers

- Status: accepted
- Decision date: 2026-07-26
- Applies from: `okf-uk-legislation` v0.3 release candidates
- Permanent-domain choice: deferred

## Context

The Whole-Law profile currently uses the repository-controlled, versioned
namespace:

`https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#`

This namespace is controlled by the publication repository and can be
dereferenced through the existing GitHub Pages deployment. It deliberately
does not claim an unregistered `w3id.org` namespace. A suitable permanent
government domain has not yet been selected, and selecting it is outside this
release.

Published identifiers are API contracts. Moving them in place, silently
rewriting historical evidence, or treating two identifiers as equivalent
without a reviewed mapping would break existing consumers and overstate
semantic identity.

## Decision

The current namespace remains canonical for v1. A later domain migration is a
release-controlled change and cannot begin until all prerequisites below are
met. The permanent-domain selection remains explicitly deferred; deferral does
not block the v0.3 release.

### Migration prerequisites and triggers

Migration may be proposed only when:

1. an accountable government service owner approves a durable HTTPS domain,
   namespace path and operating model;
2. the new host can serve versioned contexts and vocabularies with correct
   media types, stable cache behaviour and monitored availability;
3. ownership, incident response, archival retention and decommissioning
   responsibilities are documented;
4. redirects from every old dereferenceable document route can be kept for the
   lifetime of published releases;
5. a term-by-term mapping has been reviewed for semantic equivalence,
   replacement, narrowing, broadening and deprecation;
6. Explorer, YAML-LD, JSON-LD, RDF, SHACL, release archives and compatibility
   routes can be tested against both namespaces;
7. release governance approves a migration release, support window and
   rollback plan.

A domain becoming available by itself is not a trigger. Migration requires the
operational and semantic prerequisites as well.

### Mapping and publication plan

The migration release will:

1. publish an immutable mapping manifest from every v1 term and document IRI
   to its reviewed outcome at the new namespace;
2. issue a new namespace version rather than editing v1 in place;
3. dual-publish old and new contexts, vocabularies, shapes and descriptors for
   at least one major release support window;
4. keep all historical v1 release assets and evidence byte-identical;
5. redirect old human-facing and vocabulary document routes only where the
   target is stable and semantically reviewed;
6. retain the old context as a directly downloadable fallback even when an
   HTTP redirect is supplied;
7. add explicit replacement or mapping terms only where review supports them.

The migration must not apply blanket `owl:sameAs`. Exact, close, broad, narrow
and related mappings remain distinct. Source-native legal identifiers do not
change merely because the profile namespace changes.

### Backwards compatibility

- Existing v1 IRIs remain valid identifiers and resolvable publication
  contracts.
- Existing descriptors continue to declare their original namespace and
  release-specific contexts.
- Consumers may remain on v1 for the documented support window without
  rewriting stored graphs.
- New releases declare their canonical namespace and alternates explicitly;
  consumers never have to infer a repository path.
- Redirects and mappings are additive. No migration job mutates old research,
  source envelopes, model receipts, candidate packages or release assets.
- If the new host fails its availability or semantic-equivalence gates, the
  release rolls back to v1 publication without changing v1 bytes.

## Validation and release evidence

Before a migration candidate can be promoted, automated tests must prove:

- old and new contexts expand the declared compatibility examples as expected;
- term mappings pass SHACL and competency-question review;
- old descriptor, raw, archive and documentation routes remain resolvable;
- redirect chains are bounded, HTTPS-only and free from open redirects;
- YAML-LD and JSON-LD fallbacks remain semantically equivalent;
- release manifests identify the mapping digest and dual-publication window.

The migration decision, mapping manifest, route observations and rollback
exercise become new immutable evidence. They do not replace this ADR or the
evidence for earlier releases.

## Consequences

The v0.3 implementation can use a truthful, controlled namespace now without
pretending that a permanent government domain has been resolved. A later move
requires more publication surface during the compatibility window, but it
preserves identifiers, evidence and downstream graphs.
