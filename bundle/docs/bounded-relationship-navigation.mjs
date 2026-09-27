export function explorerLink(page, route) {
  const parent = new URL(page);
  const local = ['127.0.0.1', 'localhost', '[::1]'].includes(parent.hostname);
  if (parent.username || parent.password || (parent.protocol !== 'https:' && !(local && parent.protocol === 'http:'))) throw new Error('Unsupported navigation origin');
  if (!/^dataset\/[A-Za-z0-9_./~-]+$/.test(route) || route.split('/').includes('..')) throw new Error('Unsupported work route');
  const descriptor = new URL('../okf-explorer.json', parent);
  const explorer = new URL(local ? '/explore/' : 'https://chris-page-gov.github.io/okf-explorer/explore/', parent);
  explorer.searchParams.set('bundle', descriptor.href);
  explorer.searchParams.set('view', 'graph');
  explorer.hash = route;
  return explorer.href;
}
if (typeof document !== 'undefined') {
  for (const link of document.querySelectorAll('a.work[data-route]')) {
    try { link.href = explorerLink(location.href, link.dataset.route); link.textContent = link.dataset.route; }
    catch { link.removeAttribute('href'); link.textContent += ' — navigation unavailable'; }
  }
}
