import { initializeOnlineImages, normalizeText, productMarkup } from './online-markup';

const roots = document.querySelectorAll<HTMLElement>('[data-online-catalog]');
roots.forEach((root) => {
  if (root.dataset.initialized === 'true') return;
  root.dataset.initialized = 'true';

  const kind = root.dataset.kind || 'card';
  const noun = kind === 'card' ? 'cartas' : kind === 'booster' ? 'boosters' : kind === 'kit' ? 'kits' : 'produtos';
  const supportsFreeMode = kind === 'card' || kind === 'booster' || kind === 'kit';
  const pageSize = kind === 'card' ? 24 : 20;
  const grid = root.querySelector<HTMLElement>('[data-online-grid]');
  const skeleton = root.querySelector<HTMLElement>('[data-online-skeleton]');
  const sentinel = root.querySelector<HTMLElement>('[data-online-sentinel]');
  const count = root.querySelector<HTMLElement>('[data-online-count]');
  const countLabel = root.querySelector<HTMLElement>('[data-online-count-label]');
  const status = root.querySelector<HTMLElement>('[data-online-status]');
  const empty = root.querySelector<HTMLElement>('[data-online-empty]');
  const search = root.querySelector<HTMLInputElement>('[data-online-search]');
  const filterToggle = root.querySelector<HTMLButtonElement>('[data-online-filter-toggle]');
  const filterDrawer = root.querySelector<HTMLElement>('[data-online-filter-drawer]');
  const filterIndicator = root.querySelector<HTMLElement>('[data-online-filter-indicator]');
  const clearFilters = root.querySelector<HTMLButtonElement>('[data-online-clear-filters]');
  const freeToggle = root.querySelector<HTMLButtonElement>('[data-online-free-toggle]');
  const eraFilter = root.querySelector<HTMLSelectElement>('[data-online-era]');
  const collectionFilter = root.querySelector<HTMLSelectElement>('[data-online-collection]');
  const groupFilter = root.querySelector<HTMLSelectElement>('[data-online-group]');
  const classFilter = root.querySelector<HTMLSelectElement>('[data-online-class]');
  const typeFilter = root.querySelector<HTMLSelectElement>('[data-online-type]');
  const languageFilter = root.querySelector<HTMLSelectElement>('[data-online-language]');
  const conditionFilter = root.querySelector<HTMLSelectElement>('[data-online-condition]');
  const integrityFilter = root.querySelector<HTMLInputElement>('[data-online-integrity]');
  const ownerFilter = root.querySelector<HTMLSelectElement>('[data-online-owner]');
  const ownerWrap = root.querySelector<HTMLElement>('[data-online-owner-wrap]');
  const sort = root.querySelector<HTMLSelectElement>('[data-online-sort]');

  let items: any[] = [];
  let cursor: string | null = null;
  let hasMore = true;
  let pagePromise: Promise<void> | null = null;
  let fullyLoaded = false;
  let completePromise: Promise<void> | null = null;
  let searchTimer = 0;
  let freeMode = false;
  let tcgConfig: any = { eras: {}, groups: [], languages: [], conditions: {} };
  try { tcgConfig = JSON.parse(root.dataset.tcgConfig || '{}'); } catch (_) {}

  const escapeOption = (value: string) => String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  const uniqueItems = (incoming: any[]) => {
    const known = new Set(items.map((item) => String(item._docId || item.id || item.slug || '')));
    incoming.forEach((item) => {
      const key = String(item._docId || item.id || item.slug || '');
      if (!key || !known.has(key)) { items.push(item); if (key) known.add(key); }
    });
  };

  const fillSelect = (select: HTMLSelectElement | null, values: Array<string | { value: string; label: string }>, firstLabel: string, reset = false) => {
    if (!select) return;
    const current = reset ? '' : select.value;
    select.innerHTML = `<option value="">${firstLabel}</option>${values.map((entry) => { const value = typeof entry === 'string' ? entry : entry.value; const label = typeof entry === 'string' ? entry : entry.label; return `<option value="${escapeOption(value)}">${escapeOption(label)}</option>`; }).join('')}`;
    if ([...select.options].some((option) => option.value === current)) select.value = current;
  };

  const syncDependentFilters = ({ resetCollection = false, resetClass = false, resetType = false } = {}) => {
    const era: any = eraFilter?.value ? tcgConfig.eras?.[eraFilter.value] : null;
    const group = groupFilter?.value || '';
    fillSelect(collectionFilter, era ? (era.collections || []).map((entry: any) => ({ value: entry.id, label: `${entry.label}${entry.code ? ` — ${entry.code}` : ''}` })) : [], 'Todas', resetCollection);
    if (collectionFilter) collectionFilter.disabled = !era;
    fillSelect(classFilter, era && group ? (era.classes?.[group] || []) : [], 'Todas', resetClass);
    if (classFilter) classFilter.disabled = !(era && group);
    fillSelect(typeFilter, era && group === 'pokemon' ? (era.pokemonTypes || []) : [], 'Todos', resetType);
    if (typeFilter) typeFilter.disabled = !(era && group === 'pokemon');
  };

  const hydrateFilters = () => {
    syncDependentFilters();
    const ownerMap = new Map<string, string>();
    items.forEach((item) => {
      const slug = String(item.ownerCollectionSlug || item.collectionSlug || '');
      if (slug) ownerMap.set(slug, String(item.ownerCollectionName || item.ownerName || slug));
    });
    const owners = [...ownerMap.entries()].sort((a, b) => a[1].localeCompare(b[1], 'pt-BR'));
    if (ownerFilter) {
      const current = ownerFilter.value;
      ownerFilter.innerHTML = `<option value="">Todas</option>${owners.map(([slug, label]) => `<option value="${escapeOption(slug)}">${escapeOption(label)}</option>`).join('')}`;
      if ([...ownerFilter.options].some((option) => option.value === current)) ownerFilter.value = current;
      if (ownerWrap) ownerWrap.hidden = owners.length <= 1;
    }
  };

  const hasFilterSelection = () => Boolean(
    eraFilter?.value
    || collectionFilter?.value
    || groupFilter?.value
    || classFilter?.value
    || typeFilter?.value
    || languageFilter?.value
    || conditionFilter?.value
    || integrityFilter?.value
    || ownerFilter?.value
  );

  const updateFilterState = () => {
    const active = hasFilterSelection();
    filterToggle?.classList.toggle('is-active', active);
    if (filterIndicator) filterIndicator.hidden = !active;
  };

  const hasActiveRefinement = () => Boolean(
    normalizeText(search?.value || '')
    || hasFilterSelection()
    || (sort?.value && sort.value !== 'name')
  );

  const apply = () => {
    const query = normalizeText(search?.value || '');
    let visible = items.filter((item) => {
      const text = normalizeText(`${item.searchText || ''} ${item.name || ''} ${item.number || ''} ${item.collection || ''} ${item.collectionCode || ''} ${item.era || ''} ${item.group || ''} ${item.cardClass || ''} ${item.type || ''} ${item.language || ''} ${item.condition || ''} ${item.integrity ?? ''} ${item.ownerName || ''} ${item.ownerCollectionName || ''}`);
      if (query && !text.includes(query)) return false;
      if (eraFilter?.value && item.era !== eraFilter.value) return false;
      if (collectionFilter?.value && item.collectionId !== collectionFilter.value) return false;
      if (groupFilter?.value && item.group !== groupFilter.value) return false;
      if (classFilter?.value && item.cardClass !== classFilter.value) return false;
      if (typeFilter?.value && item.type !== typeFilter.value && item.pokemonType !== typeFilter.value) return false;
      if (languageFilter?.value && item.language !== languageFilter.value) return false;
      if (conditionFilter?.value && item.condition !== conditionFilter.value) return false;
      if (integrityFilter?.value && Number(item.integrity) !== Number(integrityFilter.value)) return false;
      if (ownerFilter?.value && String(item.ownerCollectionSlug || item.collectionSlug || '') !== ownerFilter.value) return false;
      return true;
    });
    const sortValue = sort?.value || 'name';
    visible = [...visible].sort((a, b) => {
      const leftPrice = a.price === null || a.price === undefined ? null : Number(a.price);
      const rightPrice = b.price === null || b.price === undefined ? null : Number(b.price);
      if (sortValue === 'price-asc') return (leftPrice ?? Infinity) - (rightPrice ?? Infinity);
      if (sortValue === 'price-desc') return (rightPrice ?? -Infinity) - (leftPrice ?? -Infinity);
      if (sortValue === 'name-desc') return String(b.name || '').localeCompare(String(a.name || ''), 'pt-BR');
      return String(a.name || '').localeCompare(String(b.name || ''), 'pt-BR');
    });

    if (grid) {
      grid.classList.toggle('free-catalog-grid', freeMode && supportsFreeMode);
      grid.innerHTML = visible.map((item) => productMarkup(item, { freeMode: freeMode && supportsFreeMode })).join('');
      grid.hidden = false;
      initializeOnlineImages(grid);
    }
    if (skeleton) skeleton.hidden = true;
    if (count) count.textContent = String(visible.length);
    if (countLabel) countLabel.textContent = noun;
    const canBeEmpty = fullyLoaded || !hasMore;
    if (empty) empty.hidden = !(canBeEmpty && visible.length === 0);
    if (status) status.textContent = hasMore && !hasActiveRefinement() ? 'Role para ver mais' : '';
    updateFilterState();
  };

  const loadNextPage = (renderAfter = true): Promise<void> => {
    if (!hasMore) return Promise.resolve();
    if (pagePromise) return pagePromise;
    pagePromise = (async () => {
      const cloud = (window as any).VaultCloud;
      if (!cloud) throw new Error('O catálogo ainda não está disponível.');
      const page = await cloud.listPublicItemsPage(kind, pageSize, cursor);
      uniqueItems(Array.isArray(page?.items) ? page.items : []);
      cursor = page?.nextCursor || null;
      hasMore = Boolean(page?.hasMore && cursor);
      fullyLoaded = !hasMore;
      hydrateFilters();
      if (renderAfter) apply();
    })().finally(() => { pagePromise = null; });
    return pagePromise;
  };

  const ensureComplete = () => {
    if (fullyLoaded) return Promise.resolve();
    if (completePromise) return completePromise;
    completePromise = (async () => {
      if (status) status.textContent = 'Atualizando resultados…';
      while (hasMore) await loadNextPage(false);
      fullyLoaded = true;
      hydrateFilters();
      apply();
    })().finally(() => { completePromise = null; });
    return completePromise;
  };

  const handleRefinement = async () => {
    if (hasActiveRefinement() && !fullyLoaded) await ensureComplete();
    else apply();
  };

  const load = async () => {
    try {
      await loadNextPage();
    } catch (error: any) {
      if (grid) grid.hidden = true;
      if (skeleton) skeleton.hidden = true;
      if (empty) {
        empty.hidden = false;
        const title = empty.querySelector('h2');
        const text = empty.querySelector('p');
        if (title) title.textContent = 'Não foi possível carregar';
        if (text) text.textContent = error?.message || 'Tente novamente em alguns instantes.';
      }
      if (count) count.textContent = '—';
      if (countLabel) countLabel.textContent = noun;
      if (status) status.textContent = '';
    }
  };

  filterToggle?.addEventListener('click', () => {
    if (!filterDrawer) return;
    const opening = filterDrawer.hidden;
    filterDrawer.hidden = !opening;
    filterToggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
    filterToggle.classList.toggle('is-open', opening);
    if (opening && !fullyLoaded) ensureComplete().catch(() => {});
  });

  freeToggle?.addEventListener('click', () => {
    freeMode = !freeMode;
    freeToggle.setAttribute('aria-pressed', freeMode ? 'true' : 'false');
    freeToggle.classList.toggle('is-active', freeMode);
    root.classList.toggle('is-free-mode', freeMode);
    apply();
  });

  clearFilters?.addEventListener('click', () => {
    [eraFilter, collectionFilter, groupFilter, classFilter, typeFilter, languageFilter, conditionFilter, ownerFilter].forEach((element) => {
      if (element) element.value = '';
    });
    if (integrityFilter) integrityFilter.value = '';
    syncDependentFilters({ resetCollection: true, resetClass: true, resetType: true });
    handleRefinement();
  });

  search?.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(handleRefinement, 180);
  });
  eraFilter?.addEventListener('change', async () => { syncDependentFilters({ resetCollection: true, resetClass: true, resetType: true }); await handleRefinement(); });
  groupFilter?.addEventListener('change', async () => { syncDependentFilters({ resetClass: true, resetType: true }); await handleRefinement(); });
  [collectionFilter, classFilter, typeFilter, languageFilter, conditionFilter, ownerFilter, sort].forEach((element) => element?.addEventListener('change', handleRefinement));
  integrityFilter?.addEventListener('input', () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(handleRefinement, 150); });
  syncDependentFilters();
  updateFilterState();

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
});
