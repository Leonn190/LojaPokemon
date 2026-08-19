import { albumMarkup, initializeOnlineImages, normalizeText } from '../online-markup';

const root = document.querySelector<HTMLElement>('[data-online-albums]');
if (root) {
  const input = root.querySelector<HTMLInputElement>('[data-album-search]');
  const grid = root.querySelector<HTMLElement>('[data-album-grid]');
  const filterToggle = root.querySelector<HTMLButtonElement>('[data-album-filter-toggle]');
  const filterDrawer = root.querySelector<HTMLElement>('[data-album-filter-drawer]');
  const filterIndicator = root.querySelector<HTMLElement>('[data-album-filter-indicator]');
  const ownerFilter = root.querySelector<HTMLSelectElement>('[data-album-owner]');
  const ownerWrap = root.querySelector<HTMLElement>('[data-album-owner-wrap]');
  const sort = root.querySelector<HTMLSelectElement>('[data-album-sort]');
  const clearFilters = root.querySelector<HTMLButtonElement>('[data-album-clear-filters]');
  const skeleton = root.querySelector<HTMLElement>('[data-album-skeleton]');
  const sentinel = root.querySelector<HTMLElement>('[data-album-sentinel]');
  const count = root.querySelector<HTMLElement>('[data-album-count]');
  const empty = root.querySelector<HTMLElement>('[data-album-empty]');
  const total = document.querySelector<HTMLElement>('[data-album-total]');
  const cards = document.querySelector<HTMLElement>('[data-album-cards]');
  const pageSize = 18;
  let albums: any[] = [];
  let cursor: string | null = null;
  let hasMore = true;
  let fullyLoaded = false;
  let pagePromise: Promise<void> | null = null;
  let completePromise: Promise<void> | null = null;
  let searchTimer = 0;

  const escapeOption = (value: string) => String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  const hydrateFilters = () => {
    if (!ownerFilter) return;
    const ownerMap = new Map<string, string>();
    albums.forEach((album) => {
      const slug = String(album.ownerCollectionSlug || album.collectionSlug || album.ownerUid || '');
      if (slug) ownerMap.set(slug, String(album.ownerName || album.ownerCollectionName || slug));
    });
    const owners = [...ownerMap.entries()].sort((a, b) => a[1].localeCompare(b[1], 'pt-BR'));
    const current = ownerFilter.value;
    ownerFilter.innerHTML = `<option value="">Todos</option>${owners.map(([slug, label]) => `<option value="${escapeOption(slug)}">${escapeOption(label)}</option>`).join('')}`;
    if ([...ownerFilter.options].some((option) => option.value === current)) ownerFilter.value = current;
    if (ownerWrap) ownerWrap.hidden = owners.length <= 1;
  };

  const hasFilterSelection = () => Boolean(ownerFilter?.value);
  const hasActiveRefinement = () => Boolean(normalizeText(input?.value || '') || hasFilterSelection() || (sort?.value && sort.value !== 'name'));
  const updateFilterState = () => {
    const active = hasFilterSelection();
    filterToggle?.classList.toggle('is-active', active);
    if (filterIndicator) filterIndicator.hidden = !active;
  };

  const mergeAlbums = (incoming: any[]) => {
    const known = new Set(albums.map((album) => String(album._docId || album.id || album.slug || '')));
    incoming.forEach((album) => {
      const key = String(album._docId || album.id || album.slug || '');
      if (!key || !known.has(key)) { albums.push(album); if (key) known.add(key); }
    });
  };

  const updateMetrics = () => {
    if (total) total.textContent = String(albums.length);
    if (cards) cards.textContent = String(albums.reduce((sum, album) => sum + Number(album.occupiedSlots || 0), 0));
  };

  const render = () => {
    const q = normalizeText(input?.value || '');
    const owner = ownerFilter?.value || '';
    const sortValue = sort?.value || 'name';
    const visible = albums
      .filter((album) => {
        if (q && !normalizeText(`${album.searchText || ''} ${album.name || ''} ${album.ownerName || ''} ${album.ownerCollectionName || ''}`).includes(q)) return false;
        const ownerKey = String(album.ownerCollectionSlug || album.collectionSlug || album.ownerUid || '');
        if (owner && ownerKey !== owner) return false;
        return true;
      })
      .sort((a, b) => {
        if (sortValue === 'name-desc') return String(b.name || '').localeCompare(String(a.name || ''), 'pt-BR');
        if (sortValue === 'filled-desc') return Number(b.occupiedSlots || 0) - Number(a.occupiedSlots || 0);
        if (sortValue === 'filled-asc') return Number(a.occupiedSlots || 0) - Number(b.occupiedSlots || 0);
        return String(a.name || '').localeCompare(String(b.name || ''), 'pt-BR');
      });
    if (grid) {
      grid.innerHTML = visible.map((album) => albumMarkup(album)).join('');
      grid.hidden = false;
      initializeOnlineImages(grid);
    }
    if (skeleton) skeleton.hidden = true;
    if (count) count.textContent = `${visible.length} ${visible.length === 1 ? 'álbum' : 'álbuns'}`;
    if (empty) empty.hidden = !(fullyLoaded && visible.length === 0);
    updateFilterState();
    updateMetrics();
  };

  const loadNextPage = (renderAfter = true): Promise<void> => {
    if (!hasMore) return Promise.resolve();
    if (pagePromise) return pagePromise;
    pagePromise = (async () => {
      const cloud = (window as any).VaultCloud;
      if (!cloud) throw new Error('Os álbuns ainda não estão disponíveis.');
      const page = await cloud.listPublicAlbumsPage(pageSize, cursor);
      mergeAlbums(Array.isArray(page?.items) ? page.items : []);
      cursor = page?.nextCursor || null;
      hasMore = Boolean(page?.hasMore && cursor);
      fullyLoaded = !hasMore;
      hydrateFilters();
      if (renderAfter) render();
    })().finally(() => { pagePromise = null; });
    return pagePromise;
  };

  const ensureComplete = () => {
    if (fullyLoaded) return Promise.resolve();
    if (completePromise) return completePromise;
    completePromise = (async () => {
      while (hasMore) await loadNextPage(false);
      fullyLoaded = true;
      render();
    })().finally(() => { completePromise = null; });
    return completePromise;
  };

  const load = async () => {
    try {
      await loadNextPage();
    } catch (error: any) {
      if (skeleton) skeleton.hidden = true;
      if (grid) grid.hidden = true;
      if (count) count.textContent = '';
      if (empty) {
        empty.hidden = false;
        const title = empty.querySelector('h2');
        const text = empty.querySelector('p');
        if (title) title.textContent = 'Não foi possível carregar';
        if (text) text.textContent = error?.message || 'Não foi possível carregar os álbuns agora.';
      }
    }
  };

  input?.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(async () => {
      if (hasActiveRefinement() && !fullyLoaded) await ensureComplete();
      else render();
    }, 180);
  });

  filterToggle?.addEventListener('click', () => {
    if (!filterDrawer) return;
    const opening = filterDrawer.hidden;
    filterDrawer.hidden = !opening;
    filterToggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
    filterToggle.classList.toggle('is-open', opening);
    if (opening && !fullyLoaded) ensureComplete().catch(() => {});
  });
  ownerFilter?.addEventListener('change', async () => {
    if (hasActiveRefinement() && !fullyLoaded) await ensureComplete();
    else render();
  });
  sort?.addEventListener('change', async () => {
    if (hasActiveRefinement() && !fullyLoaded) await ensureComplete();
    else render();
  });
  clearFilters?.addEventListener('click', () => {
    if (ownerFilter) ownerFilter.value = '';
    render();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes((document.activeElement as HTMLElement | null)?.tagName || '')) {
      event.preventDefault();
      input?.focus();
    }
  });

  if (sentinel && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting) && !hasActiveRefinement()) loadNextPage().catch(() => {});
    }, { rootMargin: '700px 0px' });
    observer.observe(sentinel);
  }

  if ((window as any).VaultCloud) load();
  else window.addEventListener('vault:cloud-ready', load, { once: true });
}
