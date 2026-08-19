import { collectionMarkup, initializeOnlineImages, normalizeText } from '../online-markup';

const root = document.querySelector<HTMLElement>('[data-online-collections]');
if (root) {
  const search = root.querySelector<HTMLInputElement>('[data-collection-search]');
  const grid = root.querySelector<HTMLElement>('[data-collections-grid]');
  const filterToggle = root.querySelector<HTMLButtonElement>('[data-collection-filter-toggle]');
  const filterDrawer = root.querySelector<HTMLElement>('[data-collection-filter-drawer]');
  const filterIndicator = root.querySelector<HTMLElement>('[data-collection-filter-indicator]');
  const availability = root.querySelector<HTMLSelectElement>('[data-collection-availability]');
  const sort = root.querySelector<HTMLSelectElement>('[data-collection-sort]');
  const clearFilters = root.querySelector<HTMLButtonElement>('[data-collection-clear-filters]');
  const skeleton = root.querySelector<HTMLElement>('[data-collection-skeleton]');
  const sentinel = root.querySelector<HTMLElement>('[data-collection-sentinel]');
  const count = root.querySelector<HTMLElement>('[data-collection-count]');
  const label = root.querySelector<HTMLElement>('[data-collection-label]');
  const empty = root.querySelector<HTMLElement>('[data-collection-empty]');
  const status = root.querySelector<HTMLElement>('[data-collection-status]');
  const totalElement = document.querySelector<HTMLElement>('[data-online-collection-total]');
  const cardElement = document.querySelector<HTMLElement>('[data-online-card-total]');
  const boosterElement = document.querySelector<HTMLElement>('[data-online-booster-total]');
  const pageSize = 12;
  let collections: any[] = [];
  let cursor: string | null = null;
  let hasMore = true;
  let fullyLoaded = false;
  let pagePromise: Promise<void> | null = null;
  let completePromise: Promise<void> | null = null;
  let searchTimer = 0;
  const previewResolved = new Set<string>();
  const previewLoading = new Set<string>();

  const profileKey = (profile: any) => String(profile.uid || profile.ownerUid || profile.collectionId || profile.slug || '');

  const mergeCollections = (incoming: any[]) => {
    const known = new Set(collections.map(profileKey));
    const added: any[] = [];
    incoming.forEach((profile) => {
      const key = profileKey(profile);
      if (!key || !known.has(key)) {
        collections.push(profile);
        added.push(profile);
        if (key) known.add(key);
      }
    });
    return added;
  };

  const hasFilterSelection = () => Boolean(availability?.value);

  const updateFilterState = () => {
    const active = hasFilterSelection();
    filterToggle?.classList.toggle('is-active', active);
    if (filterIndicator) filterIndicator.hidden = !active;
  };

  const hasActiveRefinement = () => Boolean(normalizeText(search?.value || '') || hasFilterSelection() || (sort?.value && sort.value !== 'name'));

  const visibleCollections = () => {
    const query = normalizeText(search?.value || '');
    const availabilityValue = availability?.value || '';
    const sortValue = sort?.value || 'name';
    return collections
      .filter((profile) => {
        if (query && !normalizeText(`${profile.owner || ''} ${profile.title || ''} ${profile.slug || ''}`).includes(query)) return false;
        if (availabilityValue === 'selling' && profile.selling === false) return false;
        if (availabilityValue === 'showcase' && profile.selling !== false) return false;
        return true;
      })
      .sort((a, b) => {
        if (sortValue === 'name-desc') return String(b.title || '').localeCompare(String(a.title || ''), 'pt-BR');
        if (sortValue === 'cards-desc') return Number(b.stats?.cards || 0) - Number(a.stats?.cards || 0);
        if (sortValue === 'items-desc') {
          const total = (profile: any) => Number(profile.stats?.cards || 0) + Number(profile.stats?.boosters || 0) + Number(profile.stats?.kits || 0) + Number(profile.stats?.products || 0) + Number(profile.stats?.albums || 0);
          return total(b) - total(a);
        }
        return String(a.title || '').localeCompare(String(b.title || ''), 'pt-BR');
      });
  };

  const updateMetrics = () => {
    if (totalElement) totalElement.textContent = String(collections.length);
    if (cardElement) cardElement.textContent = String(collections.reduce((sum, profile) => sum + Number(profile.stats?.cards || 0), 0));
    if (boosterElement) boosterElement.textContent = String(collections.reduce((sum, profile) => sum + Number(profile.stats?.boosters || 0), 0));
  };

  const render = () => {
    const visible = visibleCollections();
    if (grid) {
      grid.innerHTML = visible.map((profile) => collectionMarkup(profile)).join('');
      grid.hidden = false;
      initializeOnlineImages(grid);
    }
    if (skeleton) skeleton.hidden = true;
    if (count) count.textContent = String(visible.length);
    if (label) label.textContent = visible.length === 1 ? 'coleção' : 'coleções';
    if (empty) empty.hidden = !(fullyLoaded && visible.length === 0);
    if (status) status.textContent = hasMore && !hasActiveRefinement() ? '· role para ver mais' : '';
    updateFilterState();
    updateMetrics();
  };

  const hydratePreviews = async (profiles: any[]) => {
    const cloud = (window as any).VaultCloud;
    if (!cloud?.listPublicCollectionPreview) return;
    const queue = profiles.filter((profile) => {
      const key = profileKey(profile);
      if (!key || previewResolved.has(key) || previewLoading.has(key)) return false;
      if (Array.isArray(profile.previewCards) && profile.previewCards.length) {
        previewResolved.add(key);
        return false;
      }
      previewLoading.add(key);
      return true;
    });
    if (!queue.length) return;

    let changed = false;
    const worker = async () => {
      while (queue.length) {
        const profile = queue.shift();
        if (!profile) return;
        const key = profileKey(profile);
        try {
          profile.previewCards = await cloud.listPublicCollectionPreview(key, 8);
          changed = true;
        } catch (_) {
          profile.previewCards = [];
        } finally {
          previewLoading.delete(key);
          previewResolved.add(key);
        }
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (changed) render();
  };

  const loadNextPage = (renderAfter = true): Promise<void> => {
    if (!hasMore) return Promise.resolve();
    if (pagePromise) return pagePromise;
    pagePromise = (async () => {
      const cloud = (window as any).VaultCloud;
      if (!cloud) throw new Error('As coleções ainda não estão disponíveis.');
      const page = await cloud.listPublicCollectionsPage(pageSize, cursor);
      const added = mergeCollections(Array.isArray(page?.items) ? page.items : []);
      cursor = page?.nextCursor || null;
      hasMore = Boolean(page?.hasMore && cursor);
      fullyLoaded = !hasMore;
      if (renderAfter) {
        render();
        hydratePreviews(added).catch(() => {});
      }
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
      hydratePreviews(visibleCollections()).catch(() => {});
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
      if (label) label.textContent = '';
      if (status) status.textContent = '';
      if (empty) {
        empty.hidden = false;
        const title = empty.querySelector('h2');
        const text = empty.querySelector('p');
        if (title) title.textContent = 'Não foi possível carregar';
        if (text) text.textContent = error?.message || 'Não foi possível carregar as coleções agora.';
      }
    }
  };

  search?.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(async () => {
      if (hasActiveRefinement() && !fullyLoaded) await ensureComplete();
      else {
        render();
        hydratePreviews(visibleCollections()).catch(() => {});
      }
    }, 180);
  });

  filterToggle?.addEventListener('click', () => {
    if (!filterDrawer) return;
    const opening = filterDrawer.hidden;
    filterDrawer.hidden = !opening;
    filterToggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
    filterToggle.classList.toggle('is-open', opening);
  });

  availability?.addEventListener('change', async () => {
    if (hasActiveRefinement() && !fullyLoaded) await ensureComplete();
    else render();
  });
  sort?.addEventListener('change', async () => {
    if (hasActiveRefinement() && !fullyLoaded) await ensureComplete();
    else render();
  });
  clearFilters?.addEventListener('click', () => {
    if (availability) availability.value = '';
    render();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes((document.activeElement as HTMLElement | null)?.tagName || '')) {
      event.preventDefault();
      search?.focus();
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
