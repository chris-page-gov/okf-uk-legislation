# Bounded relationship navigation

Some topics and document types connect to too many records for a single browser graph. The Reader continues to enforce 64 chunks, 100,000 rows for one route, and its existing byte and retained-text limits.

The deterministic [bounded graph catalogue](bounded-relationship-navigation.html) identifies the routes exceeding the count or compressed-byte limits and offers up to 12 work-level examples for each. Every example is linked by an exact retained assertion; its work route is checked against the same count and compressed-byte limits. The examples are not exhaustive, and the Reader still applies its other safety limits. Search for another named work before opening its graph.

Build with `python3 scripts/build_bounded_relationship_navigation.py`; use `--check` to verify the output from hash-bound runtime shards. No sources or model outputs are acquired. This does not improve legal completeness or establish the applicability of a discovery relationship.

## Preserve the selected source

Example links resolve the matching descriptor relative to the displayed bundle.
A pinned or local page does not silently switch to the public main baseline.
Local previews must serve Explorer and the bundle together; unsupported origins
show unavailable navigation. Without JavaScript, links open the matching raw
descriptor. Canonical publication identities remain separate from this transport.
