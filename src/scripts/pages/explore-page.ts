import { albumMarkup, collectionMarkup, initializeOnlineImages, normalizeText, productMarkup } from '../online-markup';

const root = document.querySelector<HTMLElement>('[data-explore-search]');
if (root) {
  const input = root.querySelector<HTMLInputElement>('[data-explore-search-input]');
  const navigation = document.querySelector<HTMLElement>('[data-explore-navigation]');
  const results = root.querySelector<HTMLElement>('[data-explore-search-results]');
  const grid = root.querySelector<HTMLElement>('[data-explore-search-grid]');
  const count = root.querySelector<HTMLElement>('[data-explore-result-count]');
  const label = root.querySelector<HTMLElement>('[data-explore-result-label]');
  const meta = root.querySelector<HTMLElement>('[data-explore-search-meta]');
  const empty = root.querySelector<HTMLElement>('[data-explore-search-empty]');
  const indexLabel = root.querySelector<HTMLElement>('[data-explore-search-index]');
  let records: Array<{ type: string; search: string; html: () => string }> = [];
  let indexReady = false;
  let indexPromise: Promise<void> | null = null;
  let searchTimer = 0;

  const skeletonMarkup = () => Array.from({ length: 6 }, () => '<article class="catalog-skeleton-card"><div class="catalog-skeleton-media skeleton-pulse"></div><div class="catalog-skeleton-copy"><i class="skeleton-pulse"></i><b class="skeleton-pulse"></b><span class="skeleton-pulse"></span><span class="skeleton-pulse short"></span></div></article>').join('');

  const apply = () => {
    const q = normalizeText(input?.value || '');
    const searching = q.length > 0;
    if (navigation) navigation.hidden = searching;
    if (results) results.hidden = !searching;
    if (meta) meta.hidden = !searching;
    root.classList.toggle('is-searching', searching);
    if (!searching) {
      if (empty) empty.hidden = true;
      return;
    }
    if (!indexReady) {
      if (grid) grid.innerHTML = skeletonMarkup();
      if (count) count.textContent = '—';
      if (label) label.textContent = 'preparando resultados';
      if (empty) empty.hidden = true;
      return;
    }
    const visible = records.filter((record) => normalizeText(record.search).includes(q)).slice(0, 120);
    if (grid) {
      grid.innerHTML = visible.map((record) => `<div class="explore-search-entry"><span class="explore-result-kind">${record.type}</span>${record.html()}</div>`).join('');
      initializeOnlineImages(grid);
    }
    if (count) count.textContent = String(visible.length);
    if (label) label.textContent = visible.length === 1 ? 'resultado encontrado' : 'resultados encontrados';
    if (empty) empty.hidden = visible.length !== 0;
  };

  const loadEveryPage = async (method: (size: number, cursor?: string | null) => Promise<any>, size: number) => {
    const collected: any[] = [];
    let cursor: string | null = null;
    let more = true;
    while (more) {
      const page = await method(size, cursor);
      collected.push(...(Array.isArray(page?.items) ? page.items : []));
      cursor = page?.nextCursor || null;
      more = Boolean(page?.hasMore && cursor);
    }
    return collected;
  };

  const ensureIndex = () => {
    if (indexReady) return Promise.resolve();
    if (indexPromise) return indexPromise;
    indexPromise = (async () => {
      const cloud = (window as any).VaultCloud;
      if (!cloud) throw new Error('A pesquisa ainda não está disponível.');
      if (indexLabel) indexLabel.textContent = 'Preparando resultados…';
      const [cards, boosters, kits, products, albums, collections] = await Promise.all([
        loadEveryPage((size, cursor) => cloud.listPublicItemsPage('card', size, cursor), 80),
        loadEveryPage((size, cursor) => cloud.listPublicItemsPage('booster', size, cursor), 80),
        loadEveryPage((size, cursor) => cloud.listPublicItemsPage('kit', size, cursor), 80),
        loadEveryPage((size, cursor) => cloud.listPublicItemsPage('product', size, cursor), 80),
        loadEveryPage((size, cursor) => cloud.listPublicAlbumsPage(size, cursor), 80),
        loadEveryPage((size, cursor) => cloud.listPublicCollectionsPage(size, cursor), 80),
      ]);
      const items = [...cards, ...boosters, ...kits, ...products];
      records = [
        ...items.map((item: any) => ({ type: item.kind === 'card' ? 'Carta' : item.kind === 'booster' ? 'Booster' : item.kind === 'kit' ? 'Kit' : 'Produto', search: `${item.searchText || ''} ${item.name || ''} ${item.number || ''} ${item.collection || ''} ${item.ownerName || ''}`, html: () => productMarkup(item, { compact: true }) })),
        ...albums.map((album: any) => ({ type: 'Álbum', search: `${album.searchText || ''} ${album.name || ''} ${album.ownerName || ''}`, html: () => albumMarkup(album, true) })),
        ...collections.map((profile: any) => ({ type: 'Coleção', search: `${profile.owner || ''} ${profile.title || ''}`, html: () => collectionMarkup(profile, true) })),
      ];
      indexReady = true;
      if (indexLabel) indexLabel.textContent = `${records.length} itens disponíveis para pesquisa`;
      apply();
    })().catch((error: any) => {
      if (indexLabel) indexLabel.textContent = error?.message || 'Pesquisa indisponível';
      if (grid) grid.innerHTML = '';
      if (count) count.textContent = '';
      if (label) label.textContent = 'pesquisa indisponível';
    }).finally(() => { indexPromise = null; });
    return indexPromise;
  };

  input?.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    apply();
    if (normalizeText(input.value)) searchTimer = window.setTimeout(() => ensureIndex().catch(() => {}), 180);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes((document.activeElement as HTMLElement | null)?.tagName || '')) {
      event.preventDefault();
      input?.focus();
    }
  });
}
