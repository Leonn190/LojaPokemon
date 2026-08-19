import { albumMarkup, escapeHtml, formatBRL, initializeOnlineImages, productMarkup, toImageUrl } from '../online-markup';
const root = document.querySelector<HTMLElement>('[data-online-collection-page]');
const params = new URLSearchParams(location.search);
const slug = params.get('slug') || location.pathname.match(/\/colecoes\/([^/]+)/)?.[1] || '';
const policyLabels: Record<string, string> = {
  flexible: 'Aceita propostas flexíveis', none: 'Não aceita propostas', fixed_price_multi_only: 'Propostas em múltiplos itens sem preço fixo', no_defined_price: 'Propostas em itens sem preço definido', multi_only: 'Propostas com mais de um item',
};
const setText = (selector: string, value: unknown) => { const el = root?.querySelector<HTMLElement>(selector); if (el) el.textContent = String(value ?? ''); };
const quantity = (item: any) => Math.max(0, Number(item?.quantity ?? 1) || 0);
const isActive = (item: any) => item?.quantity === undefined || item?.quantity === null || quantity(item) > 0;
const units = (items: any[]) => items.reduce((sum, item) => sum + quantity(item), 0);
const mediaUrl = (raw: unknown) => toImageUrl(String(raw || ''));
const showError = (title: string, message: string) => {
  root?.querySelector<HTMLElement>('[data-online-collection-content]')?.setAttribute('hidden', '');
  const box = root?.querySelector<HTMLElement>('[data-collection-error]'); if (box) box.hidden = false;
  setText('[data-error-title]', title); setText('[data-error-message]', message);
};
const activateTab = (tab: string, scroll = false) => {
  root?.querySelectorAll<HTMLElement>('[data-profile-tab]').forEach((button) => button.classList.toggle('active', button.dataset.profileTab === tab));
  root?.querySelectorAll<HTMLElement>('[data-profile-panel]').forEach((panel) => { const active = panel.dataset.profilePanel === tab; panel.hidden = !active; panel.classList.toggle('active', active); });
  if (scroll) root?.querySelector('[data-profile-tabs]')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
};
const distributionMarkup = (entries: [string, number][], emptyLabel: string) => {
  if (!entries.length) return `<div class="collector-bar-empty">${escapeHtml(emptyLabel)}</div>`;
  const max = Math.max(...entries.map(([, value]) => value), 1);
  return entries.slice(0, 6).map(([label, value]) => `<div class="collector-stat-bar"><div><span>${escapeHtml(label)}</span><strong>${value}</strong></div><i><b style="--bar-size:${Math.max(7, Math.round(value / max * 100))}%"></b></i></div>`).join('');
};
const load = async () => {
  try {
    if (!slug) throw new Error('Endereço da coleção ausente.');
    const cloud = (window as any).VaultCloud;
    if (!cloud) throw new Error('Coleção ainda não foi inicializada.');
    const data = await cloud.loadCollectionBySlug(decodeURIComponent(slug));
    if (!data) throw new Error('Esta coleção não existe.');
    const profile = data.profile || {};
    const palette = Array.isArray(profile.palette) ? profile.palette : ['#54e8df','#bc91ff','#f4c25c'];
    root?.style.setProperty('--collector-primary', palette[0] || '#54e8df'); root?.style.setProperty('--collector-secondary', palette[1] || '#bc91ff'); root?.style.setProperty('--collector-accent', palette[2] || '#f4c25c');
    document.title = `${profile.title || 'Coleção'} · Vault TCG`;
    setText('[data-profile-owner]', profile.owner || 'Colecionador'); setText('[data-profile-owner-name]', profile.owner || 'Colecionador'); setText('[data-profile-title]', profile.title || 'Minha coleção');
    setText('[data-profile-sale-status]', profile.selling === false ? 'Coleção para exposição' : 'Itens selecionados à venda');
    const sale = root?.querySelector<HTMLElement>('[data-profile-sale-status]'); sale?.classList.toggle('selling', profile.selling !== false); sale?.classList.toggle('showcase-only', profile.selling === false);
    const avatar = root?.querySelector<HTMLElement>('[data-profile-avatar]');
    if (avatar) { const photo = mediaUrl(profile.profilePhoto || ''); if (photo) { avatar.classList.add('has-photo'); avatar.innerHTML = `<img src="${escapeHtml(photo)}" alt="Foto de ${escapeHtml(profile.owner || 'colecionador')}" />`; } else avatar.textContent = String(profile.owner || 'VT').slice(0,2).toUpperCase(); }
    const banner = root?.querySelector<HTMLElement>('[data-profile-banner]');
    if (banner) { const url = mediaUrl(profile.profileBanner || ''); banner.classList.toggle('has-image', Boolean(url)); if (url) banner.style.backgroundImage = `linear-gradient(100deg, rgba(3,8,15,.18), rgba(3,8,15,.72)), url("${url.replace(/"/g, '\\"')}")`; }

    const allCards = Array.isArray(data.cards) ? data.cards : [];
    const allBoosters = Array.isArray(data.boosters) ? data.boosters : [];
    const allKits = Array.isArray(data.kits) ? data.kits : [];
    const allProducts = Array.isArray(data.products) ? data.products : [];
    const allAlbums = Array.isArray(data.albums) ? data.albums : [];
    const sold = [...allCards, ...allBoosters, ...allKits, ...allProducts].filter((item: any) => !isActive(item));
    const groups: Record<string, any[]> = {
      cards: allCards.filter(isActive), boosters: allBoosters.filter(isActive), kits: allKits.filter(isActive), products: allProducts.filter(isActive), albums: allAlbums, sold,
    };

    setText('[data-stat-cards]', units(groups.cards)); setText('[data-stat-boosters]', units(groups.boosters)); setText('[data-stat-kits]', groups.kits.length); setText('[data-stat-albums]', groups.albums.length); setText('[data-stat-products]', groups.products.length);
    const forSaleCount = [...groups.cards, ...groups.boosters, ...groups.kits, ...groups.products].filter((item: any) => item.forSale !== false).length;
    setText('[data-stat-for-sale]', forSaleCount);
    const years = groups.cards.map((card: any) => Number(card.year)).filter((year: number) => Number.isFinite(year) && year > 1900 && year < 2200);
    setText('[data-stat-oldest]', years.length ? String(Math.min(...years)) : 'Não informado');
    const setNames = groups.cards.map((card: any) => String(card.collection || '').trim()).filter(Boolean);
    setText('[data-stat-sets]', new Set(setNames.map((name: string) => name.toLowerCase())).size || '—');

    const terms = profile.proposalTerms || {}; setText('[data-proposal-policy]', policyLabels[terms.policy] || 'Aceita propostas');
    setText('[data-proposal-detail]', terms.flexibleDiscounts === false && Array.isArray(terms.discountTiers) && terms.discountTiers.length ? terms.discountTiers.map((tier: any) => `A partir de R$ ${Number(tier.minValue || 0).toFixed(2).replace('.', ',')}: até ${Number(tier.maxDiscount || 0)}%`).join(' · ') : 'Entre na sua conta para montar e enviar uma proposta.');
    const estimatedValue = Number(profile.stats?.estimatedValue ?? [...groups.cards, ...groups.boosters, ...groups.products].reduce((sum: number, item: any) => sum + quantity(item) * Math.max(0, Number(item.price || 0)), 0));
    const publicValue = profile.showCollectionValue !== false;
    setText('[data-profile-value]', formatBRL(estimatedValue));
    root?.querySelectorAll<HTMLElement>('[data-public-value-stat]').forEach((node) => node.hidden = !publicValue);

    const rarityMap = new Map<string, number>();
    groups.cards.forEach((card: any) => { const label = String(card.cardClass || card.rarity || card.type || 'Não informada').trim() || 'Não informada'; rarityMap.set(label, (rarityMap.get(label) || 0) + quantity(card)); });
    const setMap = new Map<string, number>();
    groups.cards.forEach((card: any) => { const label = String(card.collection || 'Não informada').trim() || 'Não informada'; setMap.set(label, (setMap.get(label) || 0) + quantity(card)); });
    const sortedEntries = (map: Map<string, number>) => [...map.entries()].sort((a, b) => b[1] - a[1]);
    const rarityBars = root?.querySelector<HTMLElement>('[data-rarity-bars]'); if (rarityBars) rarityBars.innerHTML = distributionMarkup(sortedEntries(rarityMap), 'Sem raridade/tipo suficiente para comparar.');
    const setBars = root?.querySelector<HTMLElement>('[data-set-bars]'); if (setBars) setBars.innerHTML = distributionMarkup(sortedEntries(setMap), 'Sem coleção/era informada nas cartas.');

    Object.entries(groups).forEach(([key, items]) => {
      setText(`[data-tab-count="${key}"]`, items.length);
      const grid = root?.querySelector<HTMLElement>(`[data-grid="${key}"]`);
      if (grid) { grid.innerHTML = key === 'albums' ? items.map((item) => albumMarkup(item)).join('') : items.map((item) => productMarkup(item, { hideOwner: true })).join(''); initializeOnlineImages(grid); }
      const empty = root?.querySelector<HTMLElement>(`[data-panel-empty="${key}"]`); if (empty) empty.hidden = items.length !== 0;
    });
    const overviewAlbums = root?.querySelector<HTMLElement>('[data-grid="overview-albums"]');
    if (overviewAlbums && groups.albums.length) { overviewAlbums.innerHTML = groups.albums.slice(0, 4).map((item) => albumMarkup(item, true)).join(''); initializeOnlineImages(overviewAlbums); const wrap = root?.querySelector<HTMLElement>('[data-overview-albums]'); if (wrap) wrap.hidden = false; }
    const highlightedCards = [...groups.cards].sort((a: any, b: any) => Number(Boolean(b.favorite)) - Number(Boolean(a.favorite)) || Number(b.price || b.averageGeneralPrice || b.cheapestGeneralPrice || b.leaguePrice || 0) - Number(a.price || a.averageGeneralPrice || a.cheapestGeneralPrice || a.leaguePrice || 0)).slice(0, 8);
    const overviewCards = root?.querySelector<HTMLElement>('[data-grid="overview-cards"]');
    if (overviewCards && highlightedCards.length) { overviewCards.innerHTML = highlightedCards.map((item) => productMarkup(item, { hideOwner: true })).join(''); initializeOnlineImages(overviewCards); const wrap = root?.querySelector<HTMLElement>('[data-overview-cards]'); if (wrap) wrap.hidden = false; }

    const ambientCards = [...groups.cards].filter((card: any) => Array.isArray(card.imageCandidates) && card.imageCandidates.length).sort((a: any, b: any) => Number(Boolean(b.favorite)) - Number(Boolean(a.favorite)) || Number(b.price || 0) - Number(a.price || 0)).slice(0, 8);
    const backdrop = root?.querySelector<HTMLElement>('[data-online-collection-backdrop]'); if (backdrop) backdrop.innerHTML = ambientCards.map((card: any, index: number) => `<img src="${escapeHtml(toImageUrl(card.imageCandidates[0]))}" alt="" loading="lazy" style="--favorite-index:${index}" />`).join('');

    const total = groups.cards.length + groups.boosters.length + groups.kits.length + groups.products.length + groups.albums.length;
    const content = root?.querySelector<HTMLElement>('[data-online-collection-content]'); if (content) content.hidden = false;
    const empty = root?.querySelector<HTMLElement>('[data-collection-is-empty]'); if (empty) empty.hidden = total !== 0;
    const proposal = root?.querySelector<HTMLElement>('[data-proposal-start]'); if (proposal) proposal.hidden = profile.selling === false || forSaleCount === 0;
  } catch (error: any) {
    showError(error?.message === 'Esta coleção é privada.' ? 'Coleção privada' : 'Não foi possível abrir a coleção', error?.message || 'Tente novamente em alguns instantes.');
  }
};
root?.querySelector('[data-profile-tabs]')?.addEventListener('click', (event) => { const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-profile-tab]') : null; if (target) activateTab(target.dataset.profileTab || 'overview'); });
root?.addEventListener('click', (event) => { const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-open-tab]') : null; if (target) activateTab(target.dataset.openTab || 'overview', true); });
root?.querySelector('[data-proposal-start]')?.addEventListener('click', () => activateTab('cards', true));
root?.querySelector('[data-share-collection]')?.addEventListener('click', async () => { try { await navigator.clipboard.writeText(location.href); const button = root.querySelector<HTMLElement>('[data-share-collection] span'); if (button) { const old = button.textContent; button.textContent = 'Link copiado'; setTimeout(() => button.textContent = old, 1800); } } catch (_) {} });
if ((window as any).VaultCloud) load(); else window.addEventListener('vault:cloud-ready', load, { once: true });
