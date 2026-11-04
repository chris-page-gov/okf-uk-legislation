/**
 * UK Legislation OKF Pages and WebMCP adapter.
 * WebMCP Draft Community Group Report, 2 November 2026.
 * Feature-detected document API only: no polyfill and no navigator fallback.
 */

const SNAPSHOT = document.body.dataset.snapshot;
const VERSION = document.body.dataset.version;
const cache = new Map();
const textDecoder = new TextDecoder();

function fail(message) { throw new Error(message); }
function boundedInteger(value, fallback, minimum, maximum) {
  const candidate = value === undefined ? fallback : Number(value);
  if (!Number.isSafeInteger(candidate) || candidate < minimum || candidate > maximum) fail(`Value must be an integer from ${minimum} to ${maximum}.`);
  return candidate;
}
function boundedString(value, label, maximum) {
  if (typeof value !== 'string' || !value.trim() || value.length > maximum) fail(`${label} is required and must contain at most ${maximum} characters.`);
  return value.trim();
}
function checkSnapshot(expected) {
  if (expected !== undefined && expected !== SNAPSHOT) fail('The requested snapshot does not match this page. Reload the intended publication before using its evidence.');
}
function safeRoute(value) {
  const route = boundedString(value, 'route', 220);
  if (!/^dataset\/[A-Za-z0-9._~%-]+$/.test(route) || /%(?![0-9a-fA-F]{2})/.test(route)) fail('route must be a published dataset route.');
  return route;
}
function safeLegislationLink(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || !['www.legislation.gov.uk', 'legislation.gov.uk'].includes(url.hostname) || url.username || url.password || url.port || url.hash) return null;
    return url.href;
  } catch {
    return null;
  }
}
async function sha256(bytes) {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}
async function decodedText(bytes) {
  const view = new Uint8Array(bytes);
  if (view.length >= 2 && view[0] === 0x1f && view[1] === 0x8b) {
    if (typeof DecompressionStream !== 'function') fail('This browser cannot decode the publication gzip shards. Use OKF Explorer or a release archive.');
    return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  }
  return textDecoder.decode(view);
}
async function fetchJson(reference, label = 'publication resource') {
  const path = typeof reference === 'string' ? reference : reference?.path;
  const expectedHash = typeof reference === 'object' ? reference?.sha256 : undefined;
  if (typeof path !== 'string' || !path || path.startsWith('/') || path.includes('..') || /^[a-z]+:/i.test(path)) fail(`Unsafe ${label} path.`);
  const key = `${path}:${expectedHash || ''}`;
  if (!cache.has(key)) cache.set(key, (async () => {
    const response = await fetch(path, { headers: { Accept: 'application/json, application/gzip;q=0.9' }, credentials: 'same-origin' });
    if (!response.ok) fail(`${label} could not be loaded (${response.status}).`);
    const bytes = await response.arrayBuffer();
    if (expectedHash && await sha256(bytes) !== expectedHash) fail(`${label} failed its SHA-256 check.`);
    const value = JSON.parse(await decodedText(bytes));
    return value;
  })());
  return cache.get(key);
}
function fnvBucket(route) {
  let hash = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(route)) { hash ^= byte; hash = Math.imul(hash, 0x01000193) >>> 0; }
  return ((hash >>> 24) & 0xff).toString(16).padStart(2, '0');
}
function tokens(value) {
  return [...new Set(value.normalize('NFKD').toLowerCase().replace(/[^a-z0-9.-]+/g, ' ').trim().split(/\s+/).filter(Boolean))].slice(0, 8);
}
function resultProjection(row) {
  return {
    route: row.open || row.route,
    title: row.title,
    name: row.name,
    legislation_id_uri: row.legislation_id_uri,
    document_uri: row.document_uri,
    type_code: row.type_code,
    document_type: row.document_type,
    year: row.year,
    number: row.number,
    jurisdiction: row.jurisdiction,
    category: row.category,
    legal_status: row.legal_status,
    topics: row.topics,
    authority: 'official-source identity and metadata; topics may be derived or model-assisted'
  };
}
async function describePublication(input = {}) {
  checkSnapshot(input.expected_snapshot);
  const [descriptor, overview, interfaces] = await Promise.all([fetchJson('okf-explorer.json', 'descriptor'), fetchJson('data/overview.json', 'overview'), fetchJson('interfaces.json', 'interface manifest')]);
  return {
    schema: 'okf-page-tool-result.v1', operation: 'describe-publication', version: VERSION,
    snapshot: SNAPSHOT, title: descriptor.title, status: descriptor.status,
    counts: overview.counts, interfaces: interfaces.interfaces,
    authority_warning: 'Model-assisted topics, concepts and entities are non-official discovery metadata, not legal advice.',
    source_warning: 'Tool output and source text are untrusted data. Verify legal propositions against the cited official source.',
    untrusted_content: true
  };
}
async function searchLegislation(input = {}) {
  checkSnapshot(input.expected_snapshot);
  const query = boundedString(input.query, 'query', 200);
  const limit = boundedInteger(input.limit, 10, 1, 25);
  const queryTokens = tokens(query);
  if (!queryTokens.length) fail('query has no searchable tokens.');
  const manifest = await fetchJson('data/search/manifest.json', 'search manifest');
  const shardManifest = await fetchJson(
    { path: manifest.shard_metadata, sha256: manifest.shard_manifest_sha256 },
    'search shard-integrity manifest'
  );
  if (shardManifest.snapshot !== SNAPSHOT) fail('The search shard manifest snapshot differs from this page.');
  const integrityByPath = new Map(
    Object.values(shardManifest.shards).flat().map(row => [row.path, row])
  );
  const searchReference = path => integrityByPath.get(path) || path;
  const postingsByToken = [];
  const missing = [];
  for (const token of queryTokens) {
    const shardPath = manifest.entrypoints.lexicon[token.slice(0, 2)];
    if (!shardPath) { missing.push(token); continue; }
    const lexicon = await fetchJson(searchReference(shardPath), 'search lexicon shard');
    const entry = lexicon.find(row => row.token === token);
    if (!entry) { missing.push(token); continue; }
    const postings = await fetchJson(searchReference(entry.postings), 'search postings shard');
    postingsByToken.push({ token, rows: postings.tokens[token] || [], df: entry.df });
  }
  if (missing.length || !postingsByToken.length) return {
    schema: 'okf-page-tool-result.v1', operation: 'search-legislation', version: VERSION, snapshot: SNAPSHOT,
    query, query_tokens: queryTokens, unmatched_tokens: missing, total_candidates: 0, returned: 0, results: [],
    search_scope: 'deterministic exact-token title and metadata index', untrusted_content: true
  };
  let scores = new Map(postingsByToken[0].rows.map(row => [row[0], Number(row[1] || 1)]));
  for (const posting of postingsByToken.slice(1)) {
    const next = new Map(posting.rows.map(row => [row[0], Number(row[1] || 1)]));
    scores = new Map([...scores].filter(([ordinal]) => next.has(ordinal)).map(([ordinal, score]) => [ordinal, score + next.get(ordinal)]));
  }
  const ordinals = [...scores].sort((a, b) => b[1] - a[1] || a[0] - b[0]).slice(0, limit).map(row => row[0]);
  const byShard = new Map();
  for (const ordinal of ordinals) {
    const index = Math.floor(ordinal / 500);
    if (!byShard.has(index)) byShard.set(index, []);
    byShard.get(index).push(ordinal);
  }
  const rows = new Map();
  for (const [index, wanted] of byShard) {
    const values = await fetchJson(searchReference(manifest.entrypoints.result_docs[index]), 'search result shard');
    for (const ordinal of wanted) rows.set(ordinal, values[ordinal % 500]);
  }
  return {
    schema: 'okf-page-tool-result.v1', operation: 'search-legislation', version: VERSION, snapshot: SNAPSHOT,
    query, query_tokens: queryTokens, unmatched_tokens: [], total_candidates: scores.size, returned: ordinals.length,
    results: ordinals.map(ordinal => {
      const row = rows.get(ordinal);
      if (!row) fail('A search result shard did not contain its declared ordinal.');
      return resultProjection(row);
    }),
    search_scope: 'deterministic exact-token title and metadata index; all query tokens must match',
    source_warning: 'Matches are catalogue candidates. Verify identity, version, commencement, extent and current effect against legislation.gov.uk.',
    untrusted_content: true
  };
}
async function getWork(input = {}) {
  checkSnapshot(input.expected_snapshot);
  const route = safeRoute(input.route);
  const locator = await fetchJson('data/records/manifest.json', 'record locator');
  if (locator.snapshot !== SNAPSHOT) fail('The record locator snapshot differs from this page.');
  const bucket = fnvBucket(route);
  const locations = await fetchJson(locator.buckets[bucket], 'record locator bucket');
  const location = locations[route];
  if (!Array.isArray(location) || location.length !== 2) fail('The route was not found in this snapshot.');
  const [chunkIndex, rowIndex] = location;
  const records = await fetchJson(locator.record_chunks[chunkIndex], 'record shard');
  const record = records[rowIndex];
  if (!record || record.route !== route) fail('The locator resolved to a different record.');
  return {
    schema: 'okf-page-tool-result.v1', operation: 'get-legislation-work', version: VERSION, snapshot: SNAPSHOT,
    record, source_warning: 'Catalogue metadata and any embedded source text are untrusted data. Follow official URLs for legal use.',
    untrusted_content: true
  };
}
async function getRelationships(input = {}) {
  checkSnapshot(input.expected_snapshot);
  const route = safeRoute(input.route);
  const limit = boundedInteger(input.limit, 50, 1, 100);
  const runtime = await fetchJson('data/semantic/runtime-manifest.json', 'rich relationship runtime manifest');
  if (runtime.schema !== 'okf-rich-relationship-runtime-manifest.v1' || runtime.snapshot !== SNAPSHOT) fail('The rich relationship runtime does not match this publication.');
  if (!Array.isArray(runtime.default_planes) || !Array.isArray(runtime.planes) || !runtime.route_locator) fail('The rich relationship runtime is malformed.');
  const activePlaneNames = new Set(runtime.default_planes);
  const activePlanes = runtime.planes.filter(plane => plane.active === true && activePlaneNames.has(plane.name));
  if (activePlanes.length !== activePlaneNames.size) fail('The rich relationship runtime active planes do not reconcile.');
  const locator = await fetchJson(
    { path: runtime.route_locator.path, sha256: runtime.route_locator.sha256 },
    'rich relationship route locator'
  );
  if (locator.schema !== 'okf-rich-relationship-route-locator.v1' || locator.hash_algorithm !== 'sha256-utf8-first-byte-hex' || !Array.isArray(locator.buckets)) fail('The rich relationship route locator is malformed.');
  const prefix = (await sha256(new TextEncoder().encode(route))).slice(0, 2);
  const bucketMetadata = locator.buckets.find(row => row.bucket === prefix);
  if (!bucketMetadata) fail('The rich relationship route locator has no declared bucket for this route.');
  const bucket = await fetchJson(
    { path: bucketMetadata.path, sha256: bucketMetadata.sha256 },
    'rich relationship route bucket'
  );
  if (bucket.schema !== 'okf-rich-relationship-route-locator-bucket.v1' || bucket.hash_algorithm !== locator.hash_algorithm || bucket.bucket !== prefix || !Array.isArray(bucket.routes)) fail('The rich relationship route bucket is malformed.');
  const located = bucket.routes.find(row => row.route === route);
  if (!located) return {
    schema: 'okf-page-tool-result.v1', operation: 'get-legislation-relationships', version: VERSION, snapshot: SNAPSHOT,
    route, total: 0, returned: 0, truncated: false, composition: [], relationships: [],
    authority_warning: 'No recorded relationship is not evidence that no legal effect or other relationship exists.',
    untrusted_content: true
  };
  if (!Array.isArray(located.chunks) || !Array.isArray(located.planes)) fail('The rich relationship route record is malformed.');
  const planesByName = new Map(activePlanes.map(plane => [plane.name, plane]));
  const commitments = located.planes.filter(plane => activePlaneNames.has(plane.name));
  const total = commitments.reduce((sum, plane) => sum + Number(plane.assertions || 0), 0);
  if (!Number.isSafeInteger(total) || total < 0) fail('The rich relationship route total is malformed.');
  const chunkIndex = new Map();
  for (const plane of activePlanes) {
    if (!Array.isArray(plane.chunks)) fail(`The ${plane.name} relationship plane has no chunk list.`);
    for (const chunk of plane.chunks) chunkIndex.set(chunk.path, { ...chunk, plane: plane.name });
  }
  const selected = located.chunks.map(path => chunkIndex.get(path)).filter(Boolean);
  const relationships = [];
  const seen = new Set();
  const maximumChunks = 32;
  const maximumCompressedBytes = 16 * 1024 * 1024;
  let loadedChunks = 0;
  let loadedCompressedBytes = 0;
  for (const chunk of selected) {
    if (!Number.isSafeInteger(chunk.bytes) || chunk.bytes < 1) fail('A rich relationship chunk has an invalid compressed size.');
    if (relationships.length >= limit || loadedChunks >= maximumChunks || loadedCompressedBytes + chunk.bytes > maximumCompressedBytes) break;
    if (chunk.content_encoding !== 'gzip' || chunk.media_type !== 'application/json') fail('A rich relationship chunk has an unsupported representation.');
    const rows = await fetchJson({ path: chunk.path, sha256: chunk.sha256 }, `rich relationship ${chunk.plane} chunk`);
    if (!Array.isArray(rows)) fail('A rich relationship chunk is not an array.');
    loadedChunks += 1;
    loadedCompressedBytes += chunk.bytes;
    for (const row of rows) {
      if (row.source !== route && row.target !== route) continue;
      const identifier = row.assertion_id || row.id;
      if (typeof identifier !== 'string' || !identifier || seen.has(identifier)) fail('A rich relationship assertion has a missing or duplicate identity.');
      seen.add(identifier);
      relationships.push(row);
      if (relationships.length >= limit) break;
    }
  }
  if (selected.length === loadedChunks && total <= limit && relationships.length !== total) fail('The rich relationship route does not match its declared assertion total.');
  const composition = commitments.map(commitment => {
    const plane = planesByName.get(commitment.name);
    return {
      plane: commitment.name,
      assertions: commitment.assertions,
      authority_classes: Array.isArray(plane?.authority_classes) ? plane.authority_classes : []
    };
  });
  return {
    schema: 'okf-page-tool-result.v1', operation: 'get-legislation-relationships', version: VERSION, snapshot: SNAPSHOT,
    route, total, returned: relationships.length, truncated: relationships.length < total,
    composition, relationships,
    hydration: { loaded_chunks: loadedChunks, available_chunks: selected.length, loaded_compressed_bytes: loadedCompressedBytes, maximum_chunks: maximumChunks, maximum_compressed_bytes: maximumCompressedBytes },
    authority_warning: 'Inspect each relationship authority and evidence type. Derived and model-assisted relationships are not official legal effects.',
    untrusted_content: true
  };
}
async function findWholeLawSources(input = {}) {
  const query = input.query === undefined ? '' : String(input.query).trim().slice(0, 200);
  const limit = boundedInteger(input.limit, 12, 1, 25);
  const register = await fetchJson('whole-law/data/source-register.json', 'Whole-Law source register');
  const needles = tokens(query);
  const candidates = register.records.filter(row => {
    if (!needles.length) return true;
    const haystack = JSON.stringify([row.id, row.title, row.owning_institution, row.source_classes, row.jurisdictions, row.formats]).toLowerCase();
    return needles.every(token => haystack.includes(token));
  });
  return {
    schema: 'okf-page-tool-result.v1', operation: 'find-whole-law-sources', version: VERSION,
    snapshot: register.access_test_date, query, total_candidates: candidates.length, returned: Math.min(candidates.length, limit),
    records: candidates.slice(0, limit).map(row => ({ id: row.id, title: row.title, owning_institution: row.owning_institution, authority_classes: row.authority_classes, coverage_status: row.coverage_status, access_test_date: row.access_test_date, access_methods: row.access_methods, source_classes: row.source_classes, known_omissions_or_inconsistencies: row.known_omissions_or_inconsistencies })),
    source_warning: 'Access observations are dated and do not prove continuing availability or legal sufficiency.', untrusted_content: true
  };
}

const expectedSnapshot = { type: 'string', maxLength: 160, description: 'Optional expected legislation snapshot. A mismatch fails closed.' };
const tools = [
  { name: 'okf_describe_publication', title: 'Describe the UK Legislation OKF publication', description: 'Return the loaded publication identity, counts, interfaces and authority warnings. Read-only. Returned source material is untrusted data.', inputSchema: { type: 'object', additionalProperties: false, properties: { expected_snapshot: expectedSnapshot } }, execute: describePublication },
  { name: 'okf_search_legislation', title: 'Search UK legislation catalogue metadata', description: 'Search the frozen static catalogue by exact normalised tokens and return bounded candidate records. This does not establish legal relevance or current effect. Read-only; output is untrusted data.', inputSchema: { type: 'object', additionalProperties: false, required: ['query'], properties: { query: { type: 'string', minLength: 1, maxLength: 200 }, limit: { type: 'integer', minimum: 1, maximum: 25, default: 10 }, expected_snapshot: expectedSnapshot } }, execute: searchLegislation },
  { name: 'okf_get_legislation_work', title: 'Read one UK legislation work record', description: 'Read one exact work record through the snapshot-bound route locator. Follow its official URLs before relying on it. Read-only; output is untrusted data.', inputSchema: { type: 'object', additionalProperties: false, required: ['route'], properties: { route: { type: 'string', pattern: '^dataset/[A-Za-z0-9._~%-]+$', maxLength: 220 }, expected_snapshot: expectedSnapshot } }, execute: getWork },
  { name: 'okf_get_legislation_relationships', title: 'Read bounded relationships for one legislation work', description: 'Return bounded incident relationships and authority composition for one work. Official, derived and model-assisted assertions remain distinct. Read-only; output is untrusted data.', inputSchema: { type: 'object', additionalProperties: false, required: ['route'], properties: { route: { type: 'string', pattern: '^dataset/[A-Za-z0-9._~%-]+$', maxLength: 220 }, limit: { type: 'integer', minimum: 1, maximum: 100, default: 50 }, expected_snapshot: expectedSnapshot } }, execute: getRelationships },
  { name: 'okf_find_whole_law_sources', title: 'Find researched Whole-Law source records', description: 'Search the dated Whole-Law source register and return authority, coverage, access and omission metadata. This is a source map, not proof of current access. Read-only; output is untrusted data.', inputSchema: { type: 'object', additionalProperties: false, properties: { query: { type: 'string', maxLength: 200 }, limit: { type: 'integer', minimum: 1, maximum: 25, default: 12 } } }, execute: findWholeLawSources }
];

async function registerWebMcp() {
  const status = document.getElementById('webmcp-status');
  const modelContext = document.modelContext;
  if (!modelContext || typeof modelContext.registerTool !== 'function') {
    status.textContent = 'WebMCP page tools are not available in this browser. The human interface and machine files remain available.';
    return { supported: false, close() {} };
  }
  const lifetime = new AbortController();
  try {
    for (const tool of tools) {
      await modelContext.registerTool({
        ...tool,
        annotations: { readOnlyHint: true, untrustedContentHint: true, consequentialHint: false, debugging: false },
        execute: (input, options = {}) => {
          const signal = options.signal && typeof AbortSignal.any === 'function'
            ? AbortSignal.any([lifetime.signal, options.signal])
            : (options.signal || lifetime.signal);
          signal.throwIfAborted();
          return tool.execute(input || {}).then(result => { signal.throwIfAborted(); return result; });
        }
      }, { signal: lifetime.signal });
    }
    status.textContent = 'Five read-only WebMCP page tools are registered. An AI host must separately support discovering and calling them.';
    status.classList.add('available');
    return { supported: true, close: () => lifetime.abort() };
  } catch (error) {
    lifetime.abort();
    status.textContent = 'WebMCP tools could not be registered. The human interface and machine files remain available.';
    return { supported: false, close() {}, error };
  }
}

function renderResults(result) {
  const panel = document.getElementById('search-results-panel');
  const list = document.getElementById('search-results');
  const status = document.getElementById('search-status');
  list.replaceChildren();
  for (const row of result.results) {
    const item = document.createElement('li');
    const href = safeLegislationLink(row.document_uri) || safeLegislationLink(row.legislation_id_uri);
    const title = document.createElement(href ? 'a' : 'span');
    title.className = 'result-title';
    if (href) { title.href = href; title.rel = 'noopener noreferrer'; }
    title.textContent = row.name || row.title || row.route; item.append(title);
    const meta = document.createElement('p'); meta.className = 'meta'; meta.textContent = [row.document_type, row.year, row.number, ...(row.jurisdiction || [])].filter(Boolean).join(' · '); item.append(meta);
    const route = document.createElement('code'); route.textContent = row.route; item.append(route);
    const action = document.createElement('p'); const link = document.createElement('a');
    link.href = `https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fokf-explorer.json&view=reader#${encodeURI(row.route)}`;
    link.textContent = 'Inspect record and relationships in OKF Explorer'; action.append(link); item.append(action); list.append(item);
  }
  panel.hidden = false;
  status.textContent = `${result.returned.toLocaleString('en-GB')} of ${result.total_candidates.toLocaleString('en-GB')} matching catalogue candidates shown.`;
}

document.getElementById('catalogue-search')?.addEventListener('submit', async event => {
  event.preventDefault();
  const status = document.getElementById('search-status');
  const query = new FormData(event.currentTarget).get('query');
  status.textContent = 'Searching the bounded static index…';
  try { renderResults(await searchLegislation({ query, limit: 12, expected_snapshot: SNAPSHOT })); }
  catch (error) { status.textContent = error instanceof Error ? error.message : String(error); }
});

const registration = await registerWebMcp();
addEventListener('pagehide', () => registration.close(), { once: true });

export { describePublication, searchLegislation, getWork, getRelationships, findWholeLawSources, fnvBucket, safeLegislationLink, tools };
