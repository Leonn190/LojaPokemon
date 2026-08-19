const normalizeBase = (value: string) => value.endsWith('/') ? value : `${value}/`;

export const siteBase = () => normalizeBase(document.body?.dataset.siteBase || import.meta.env.BASE_URL || '/');

export const escapeHtml = (value: unknown) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');

export const normalizeText = (value: unknown) => String(value ?? '')
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLowerCase()
  .trim();

export const formatBRL = (value: unknown) => {
  const amount = value === null || value === '' || value === undefined ? null : Number(value);
  if (amount === null || !Number.isFinite(amount)) return 'Consultar';
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 }).format(amount);
};

export const toImageUrl = (path: unknown) => {
  const source = String(path || '').trim();
  if (!source) return '';
  if (/^(?:https?:|data:|blob:)/i.test(source)) return source;
  return `${siteBase()}${source.replace(/^\/+/, '').split('/').map(encodeURIComponent).join('/')}`;
};

const imageCandidates = (item: any) => {
  const candidates = Array.isArray(item?.imageCandidates) ? item.imageCandidates : [];
  const image = item?.image ? [item.image] : [];
  return [...new Set([...candidates, ...image].filter(Boolean).map(toImageUrl))];
};

const rarityTier = (value: unknown) => {
  const rarity = normalizeText(value);
  const compact = rarity.replace(/[^a-z0-9]+/g, '');
  const premium = ['full art', 'ultra rara', 'ultra rare', 'secret', 'secreta', 'gold', 'dourad', 'rainbow', 'illustration rare', 'ilustracao rara', 'arte rara', 'special illustration', 'sir', 'alt art', 'galeria de treinador', 'trainer gallery', 'shiny rare', 'shiny ultra', 'hyper rare']
    .some((token) => rarity.includes(token)) || ['ru', 'sr', 're'].includes(rarity);
  if (premium) return 'premium';
  const holo = ['holo', 'foil', 'reverse', 'radiante', 'radiant', 'vmax', 'v-astro', 'vstar', 'mega ex', ' ex', 'gx', ' v', 'rh', 'rl', 'rd']
    .some((token) => rarity.includes(token)) || /^(?:mega\s+)?(?:ex|gx|v(?:max|star|-astro|-union)?)(?:\b|\s|—|-)/.test(rarity) || /^(?:ex|gx|v|vmax|vstar|v-astro|megaex|rh|rl|rd|s)$/.test(compact);
  return holo ? 'holo' : 'basic';
};

export const productVisualMarkup = (item: any, interactive = true) => {
  const urls = imageCandidates(item);
  const [primary = '', ...fallbacks] = urls;
  const isCard = item.kind === 'card';
  const isKit = item.kind === 'kit';
  const label = isCard ? 'Carta Pokémon' : item.kind === 'booster' ? 'Booster Pokémon' : isKit ? 'Kit personalizado' : 'Produto Pokémon';
  const initials = isKit ? 'KIT' : String(item.name || 'TCG').split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join('').toUpperCase();

  if (isKit) {
    const contents = Array.isArray(item.contentItems) ? item.contentItems : [];
    const withImages = contents.filter((entry: any) => Array.isArray(entry?.imageCandidates) && entry.imageCandidates.length > 0);
    const firstCard = withImages.find((entry: any) => entry.kind === 'cards');
    const secondCard = withImages.find((entry: any) => entry.kind === 'cards' && entry !== firstCard);
    const firstBooster = withImages.find((entry: any) => entry.kind === 'boosters');
    const preview = [firstCard, secondCard, firstBooster, ...withImages].filter((entry, index, list) => entry && list.indexOf(entry) === index).slice(0, 3);
    if (preview.length) {
      const stack = preview.map((entry: any, index: number) => {
        const entryUrls = (entry.imageCandidates || []).map(toImageUrl).filter(Boolean);
        const [entryPrimary = '', ...entryFallbacks] = entryUrls;
        const entryInitials = String(entry.name || 'TCG').split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join('').toUpperCase();
        return `<span class="kit-stack-card kit-stack-card-${index + 1}${entry.kind === 'boosters' ? ' booster-item' : ''}"><span class="kit-stack-card-surface" data-image-stage><span class="kit-stack-fallback">${escapeHtml(entryInitials || 'TCG')}</span>${entryPrimary ? `<img src="${escapeHtml(entryPrimary)}" alt="" loading="lazy" decoding="async" fetchpriority="low" data-image-candidates="${escapeHtml(JSON.stringify(entryFallbacks))}" />` : ''}</span></span>`;
      }).join('');
      const units = contents.reduce((total: number, entry: any) => total + Math.max(1, Number(entry?.quantity) || 1), 0);
      const sourceTotal = Number(item.sourceTotal || 0);
      const price = itemPrice(item);
      const discount = sourceTotal > 0 && price !== null ? Math.max(0, ((sourceTotal - price) / sourceTotal) * 100) : 0;
      return `<div class="collectible-visual kit-visual kit-composite-visual"${interactive ? ' data-tilt data-tilt-strength="4"' : ''}><div class="image-stage kit-image-stage"><span class="image-fallback" aria-hidden="true"><b>KIT</b><small>${escapeHtml(label)}</small></span><div class="kit-stack" aria-hidden="true">${stack}</div><span class="kit-composite-badge">${units || contents.length} ${units === 1 ? 'item' : 'itens'}</span>${discount > 0 ? `<span class="kit-discount-badge">−${Math.round(discount)}%</span>` : ''}<span class="kit-composite-shine" aria-hidden="true"></span></div></div>`;
    }
  }

  const image = primary
    ? `<img src="${escapeHtml(primary)}" alt="${escapeHtml(item.name || '')}" loading="lazy" decoding="async" fetchpriority="low" data-image-candidates="${escapeHtml(JSON.stringify(fallbacks))}" />`
    : '';
  const visualClass = isCard ? `foil-tier-${rarityTier(item.cardClass || item.type)}` : item.kind === 'booster' ? 'booster-visual' : isKit ? 'kit-visual' : 'sealed-product-visual';
  return `<div class="collectible-visual ${visualClass}"${isCard ? ` data-foil-tier="${rarityTier(item.cardClass || item.type)}"` : ''}${interactive ? ' data-tilt data-tilt-strength="4"' : ''}><div class="image-stage"><span class="image-fallback" aria-hidden="true"><b>${escapeHtml(initials || 'TCG')}</b><small>${escapeHtml(label)}</small></span>${image}${isCard ? '<span class="holo-band" aria-hidden="true"></span><span class="foil-spectrum" aria-hidden="true"></span><span class="glare" aria-hidden="true"></span>' : ''}</div></div>`;
};

const itemPrice = (item: any) => item?.price === null || item?.price === undefined || item?.price === '' ? null : Number(item.price);

export const productMarkup = (item: any, options: { compact?: boolean; hideOwner?: boolean; freeMode?: boolean } = {}) => {
  const price = itemPrice(item);
  const itemType = item.kind === 'card' ? (item.cardClass || item.type || 'Carta Pokémon') : item.kind === 'booster' ? 'Booster avulso' : item.kind === 'kit' ? 'Kit personalizado' : 'Produto lacrado';
  const policy = item.proposalTerms?.policy || 'flexible';
  const blocksDefinedPrice = policy === 'no_defined_price' || policy === 'fixed_price_multi_only';
  const canPropose = item.forSale !== false && policy !== 'none' && !(item.kind === 'card' && price !== null && blocksDefinedPrice);
  const ownerSlug = item.ownerCollectionSlug || item.collectionSlug || '';
  const collectionUrl = `${siteBase()}colecao/?slug=${encodeURIComponent(ownerSlug)}`;
  const description = item.kind === 'card'
    ? `<strong>${escapeHtml(item.number || '')}</strong><span>•</span>${escapeHtml(item.collection || '')}`
    : item.kind === 'booster'
      ? 'Pacote lacrado publicado pelo colecionador.'
      : escapeHtml(item.description || (item.kind === 'product' ? 'Produto Pokémon lacrado.' : ''));
  const kitItems = item.kind === 'kit' ? (item.contentItems || []).map((entry: any) => ({
    kind: entry.kind,
    name: entry.name,
    quantity: entry.quantity,
    type: entry.type || '',
    imageCandidates: entry.imageCandidates || [],
  })) : [];
  const sourceTotal = Number(item.sourceTotal || 0);
  const kitDiscount = item.kind === 'kit' && sourceTotal > 0 && price !== null ? Math.max(0, ((sourceTotal - price) / sourceTotal) * 100) : 0;
  const ownerName = item.ownerName || '';
  const quantity = Math.max(0, Number(item.quantity || 0));
  const showQuantity = false;

  return `<article class="product-card${options.compact ? ' compact-card' : ''}${options.freeMode ? ' free-catalog-card' : ''}" data-product-card data-product-id="${escapeHtml(`${item.kind}:${item.slug || item.id || item._docId || ''}`)}" data-kind="${escapeHtml(item.kind)}" data-name="${escapeHtml(item.name)}" data-number="${escapeHtml(item.number || '')}" data-era="${escapeHtml(item.era || '')}" data-collection="${escapeHtml(item.collection || item.name || '')}" data-collection-id="${escapeHtml(item.collectionId || '')}" data-collection-code="${escapeHtml(item.collectionCode || '')}" data-group="${escapeHtml(item.group || '')}" data-card-class="${escapeHtml(item.cardClass || '')}" data-pokemon-type="${escapeHtml(item.kind === 'card' ? (item.cardClass ? item.type || '' : item.pokemonType || '') : '')}" data-language="${escapeHtml(item.language || '')}" data-language-label="${escapeHtml(item.languageLabel || '')}" data-condition="${escapeHtml(item.condition || '')}" data-integrity="${escapeHtml(item.integrity ?? '')}" data-year="${escapeHtml(item.year || '')}" data-type="${escapeHtml(itemType)}" data-description="${escapeHtml(item.description || '')}" data-contents="${escapeHtml(item.contents || '')}" data-link-liga="${escapeHtml(item.linkLiga || '')}" data-kit-items="${escapeHtml(JSON.stringify(kitItems))}" data-kit-discount="${kitDiscount.toFixed(1)}" data-kit-source-total="${sourceTotal || ''}" data-owner="${escapeHtml(ownerName)}" data-owner-uid="${escapeHtml(item.ownerUid || item.collectionUid || '')}" data-owner-collection="${escapeHtml(item.ownerCollectionName || '')}" data-owner-slug="${escapeHtml(ownerSlug)}" data-owner-phone="${escapeHtml(item.ownerPhone || '')}" data-proposal-policy="${escapeHtml(policy)}" data-proposal-flexible="${item.proposalTerms?.flexibleDiscounts === false ? 'false' : 'true'}" data-proposal-tiers="${escapeHtml(JSON.stringify(item.proposalTerms?.discountTiers || []))}" data-proposal-allowed="${canPropose ? 'true' : 'false'}" data-price-value="${price === null ? '' : price}" data-price-label="${escapeHtml(formatBRL(price))}" data-stock="${quantity}" data-for-sale="${item.forSale === false ? 'false' : 'true'}" data-show-quantity="${showQuantity ? 'true' : 'false'}" data-search="${escapeHtml(item.searchText || `${item.name || ''} ${item.number || ''} ${item.collection || ''} ${item.collectionCode || ''} ${item.era || ''} ${item.cardClass || ''} ${item.type || ''} ${ownerName}`)}" data-price="${price ?? -1}" data-quantity="${quantity}" data-filter-era="${escapeHtml(item.era || '')}" data-filter-collection="${escapeHtml(item.collectionId || '')}" data-filter-group="${escapeHtml(item.group || '')}" data-filter-class="${escapeHtml(item.cardClass || '')}" data-filter-type="${escapeHtml(item.kind === 'card' ? (item.cardClass ? item.type || '' : item.pokemonType || '') : '')}" data-filter-language="${escapeHtml(item.language || '')}" data-filter-condition="${escapeHtml(item.condition || '')}" data-filter-integrity="${escapeHtml(item.integrity ?? '')}" data-filter-owner="${escapeHtml(ownerSlug)}"><button class="product-open-button" type="button" data-open-product aria-label="Ver detalhes de ${escapeHtml(item.name)}"><div class="product-card-media">${productVisualMarkup(item)}${showQuantity ? `<span class="quantity-chip">${quantity} ${quantity === 1 ? 'unidade' : 'unidades'}</span>` : ''}</div><div class="product-card-body"><div class="product-card-heading"><div><span class="product-kicker">${escapeHtml(itemType)}</span><h3>${escapeHtml(item.name)}</h3></div><span class="open-arrow" aria-hidden="true">⌗</span></div><p class="product-description">${description}</p><div class="product-card-footer"><div class="price-block"><small>Preço</small>${item.kind === 'kit' && sourceTotal > 0 && price !== null && sourceTotal > price ? `<del class="kit-original-price">${escapeHtml(formatBRL(sourceTotal))}</del>` : ''}<strong>${escapeHtml(formatBRL(price))}</strong></div>${item.kind === 'card' ? `<span class="condition-badge condition-${escapeHtml(normalizeText(item.condition).replace(/\s+/g, '-'))}">${escapeHtml(item.condition || '')}</span>` : ''}</div></div></button>${!options.hideOwner ? `<a class="collection-origin" href="${escapeHtml(collectionUrl)}"><span class="origin-avatar">${escapeHtml(ownerName.slice(0, 2).toUpperCase() || 'VT')}</span><span><small>Publicado por</small><strong>${escapeHtml(ownerName || item.ownerCollectionName || 'Colecionador')}</strong></span><b aria-hidden="true">↗</b></a>` : ''}${canPropose ? '<div class="product-purchase-actions single-action"><button class="add-proposal-button" type="button" data-add-proposal><span aria-hidden="true">◇</span>Adicionar à proposta</button></div>' : item.forSale !== false ? '<span class="not-for-sale-label">Os termos desta coleção não permitem proposta para este item</span>' : '<span class="not-for-sale-label">Não está à venda</span>'}</article>`;
};


export const collectionFlowMarkup = (cards: any[], compact = false) => {
  const usable = (Array.isArray(cards) ? cards : [])
    .filter((card) => imageCandidates(card).length > 0)
    .sort((left, right) => (Number(right?.price ?? right?.averageGeneralPrice ?? right?.cheapestGeneralPrice ?? right?.leaguePrice ?? 0) - Number(left?.price ?? left?.averageGeneralPrice ?? left?.cheapestGeneralPrice ?? left?.leaguePrice ?? 0)) || String(left?.name || '').localeCompare(String(right?.name || ''), 'pt-BR'))
    .slice(0, compact ? 12 : 18);
  if (!usable.length) return '<div class="collection-flow collection-flow-empty"><span>VT</span><small>Coleção em construção</small></div>';
  const minimum = compact ? 9 : 15;
  const flowCards = Array.from({ length: Math.max(minimum, usable.length) }, (_, index) => usable[index % usable.length]);
  const lanes = Array.from({ length: 3 }, (_, laneIndex) => flowCards.filter((_, index) => index % 3 === laneIndex));
  const laneHtml = lanes.map((lane, laneIndex) => {
    const sequence = lane.map((card) => `<div class="collection-flow-card">${productVisualMarkup({ ...card, kind: 'card' }, false)}</div>`).join('');
    return `<div class="collection-flow-lane collection-flow-lane-${laneIndex + 1}"><div class="collection-flow-track"><div class="collection-flow-set">${sequence}</div><div class="collection-flow-set" aria-hidden="true">${sequence}</div></div></div>`;
  }).join('');
  return `<div class="collection-flow ${compact ? 'collection-flow-compact' : 'collection-flow-hero'}" aria-label="Prévia animada da coleção"><div class="collection-flow-perspective"><div class="collection-flow-lanes" aria-hidden="true">${laneHtml}</div><span class="collection-flow-glow" aria-hidden="true"></span><span class="collection-flow-sheen" aria-hidden="true"></span></div></div>`;
};

export const collectionMarkup = (profile: any, compact = false) => {
  const stats = profile.stats || {};
  const owner = profile.owner || 'Colecionador';
  const slug = profile.slug || profile.collectionId || '';
  const url = `${siteBase()}colecao/?slug=${encodeURIComponent(slug)}`;
  const photo = toImageUrl(profile.profilePhoto || '');
  const initials = String(owner).slice(0, 2).toUpperCase();
  const status = profile.selling === false ? 'Somente exposição' : 'Itens à venda';
  const statEntries = [
    ['cards', 'cartas'], ['boosters', 'boosters'], ['kits', 'kits'], ['products', 'produtos'], ['albums', 'álbuns'],
  ].filter(([key]) => Number(stats[key] || 0) > 0);
  const statHtml = statEntries.length
    ? statEntries.map(([key, label]) => `<span><strong>${Number(stats[key] || 0)}</strong> ${label}</span>`).join('')
    : '<span>Nenhum item publicado</span>';
  const previewCards = Array.isArray(profile.previewCards) ? profile.previewCards : Array.isArray(profile.coverCards) ? profile.coverCards : [];
  const cover = previewCards.length
    ? collectionFlowMarkup(previewCards, true)
    : `<div class="collection-flow collection-flow-placeholder" aria-hidden="true"><span>VAULT</span><strong>${escapeHtml(profile.title || 'Minha coleção')}</strong></div>`;
  return `<a class="collection-card${compact ? ' compact-collection-card' : ''}" href="${escapeHtml(url)}" data-online-collection><div class="collection-card-preview">${cover}<span class="collection-status">${escapeHtml(status)}</span></div><div class="collection-card-body"><div class="collection-owner-row"><span class="collection-avatar${photo ? ' has-photo' : ''}">${photo ? `<img src="${escapeHtml(photo)}" alt="" loading="lazy" />` : escapeHtml(initials)}</span><div><small>Colecionador</small><strong>${escapeHtml(owner)}</strong></div><b aria-hidden="true">↗</b></div><h3>${escapeHtml(profile.title || 'Minha coleção')}</h3><div class="collection-card-stats">${statHtml}</div></div></a>`;
};

export const albumMarkup = (album: any, compact = false) => {
  const pages = Array.isArray(album.pages) ? album.pages : [];
  const cards = pages.flatMap((page: any) => Array.isArray(page?.slots) ? page.slots : []).filter(Boolean).slice(0, 6);
  const occupied = Number(album.occupiedSlots ?? pages.flatMap((page: any) => page?.slots || []).filter(Boolean).length);
  const total = Number(album.totalSlots ?? pages.reduce((sum: number, page: any) => sum + (Array.isArray(page?.slots) ? page.slots.length : 0), 0));
  const progress = total > 0 ? Math.round((occupied / total) * 100) : 0;
  const ownerSlug = album.ownerCollectionSlug || album.collectionSlug || '';
  const href = `${siteBase()}album/?collection=${encodeURIComponent(ownerSlug)}&album=${encodeURIComponent(album.slug || album.id || '')}`;
  const preview = cards.map((card: any) => {
    const urls = Array.isArray(card.imageCandidates) ? card.imageCandidates.map(toImageUrl) : [];
    const [primary = '', ...fallbacks] = urls;
    return `<span>${primary ? `<img src="${escapeHtml(primary)}" alt="" loading="lazy" decoding="async" data-image-candidates="${escapeHtml(JSON.stringify(fallbacks))}" />` : `<b>${escapeHtml(String(card.name || 'TCG').slice(0, 2).toUpperCase())}</b>`}</span>`;
  }).join('');
  const empties = Array.from({ length: Math.max(0, 6 - cards.length) }, () => '<span class="empty"></span>').join('');
  const owner = album.ownerName || 'Colecionador';
  const rows = Number(album.rows || 0);
  const columns = Number(album.columns || 0);
  const format = album.format || (columns && rows ? `${columns}x${rows}` : 'Álbum');
  const allowedStyles = new Set(['vault', 'leather', 'holo', 'minimal']);
  const coverStyle = allowedStyles.has(String(album.coverStyle || '')) ? String(album.coverStyle) : 'vault';
  const coverColor = /^#[0-9a-f]{6}$/i.test(String(album.coverColor || '')) ? String(album.coverColor) : '#14253d';
  const coverImage = toImageUrl(album.coverImage || '');
  const coverTitle = album.coverTitle || album.name || 'Álbum';
  const visualStyle = `--binder-cover:${escapeHtml(coverColor)}${coverImage ? `;--binder-image:url('${escapeHtml(coverImage).replace(/'/g, '&#39;')}')` : ''}`;
  return `<a class="album-product-card binder-shelf-card binder-style-${coverStyle}${compact ? ' compact' : ''}" href="${escapeHtml(href)}" aria-label="Abrir o álbum ${escapeHtml(album.name || '')}"><div class="album-product-visual binder-cover" style="${visualStyle}" aria-hidden="true"><div class="album-product-spine"><span>VT</span></div>${coverImage ? '<i class="binder-custom-image"></i>' : ''}<div class="binder-cover-title"><small>VAULT TCG</small><strong>${escapeHtml(coverTitle)}</strong></div><div class="album-product-grid">${preview}${empties}</div><i class="album-product-glare"></i><i class="album-product-shadow"></i></div><div class="album-product-copy"><small>${escapeHtml(String(format).replace('x', ' por '))} · ${pages.length} ${pages.length === 1 ? 'página' : 'páginas'}</small><h3>${escapeHtml(album.name || 'Álbum')}</h3><p>${escapeHtml(album.description || `Álbum virtual de ${owner}.`)}</p><div class="album-product-progress"><i style="--album-progress:${progress}%"></i><span>${occupied} / ${total}</span></div><div class="album-product-owner"><span>${escapeHtml(String(owner).slice(0, 2).toUpperCase())}</span><strong>${escapeHtml(owner)}</strong><b>↗</b></div></div></a>`;
};

export const initializeOnlineImages = (container: ParentNode = document) => {
  const globalHydrate = (window as any).VaultHydrate;
  if (typeof globalHydrate === 'function') {
    globalHydrate(container);
    return;
  }
  // Se o layout ainda estiver terminando de inicializar, reidrata assim que
  // o controlador global de imagens/tilt estiver disponível.
  window.addEventListener('vault:hydrator-ready', () => (window as any).VaultHydrate?.(container), { once: true });
  container.querySelectorAll<HTMLImageElement>('img[data-image-candidates]').forEach((image) => {
    if (image.dataset.onlineImageReady) return;
    image.dataset.onlineImageReady = 'true';
    const show = () => {
      image.hidden = false;
      image.closest('[data-image-stage], .image-stage')?.classList.add('has-image');
    };
    const nextCandidate = () => {
      let candidates: string[] = [];
      try { candidates = JSON.parse(image.dataset.imageCandidates || '[]'); } catch (_) {}
      const next = candidates.shift();
      if (next) {
        image.dataset.imageCandidates = JSON.stringify(candidates);
        image.src = next;
      } else image.remove();
    };
    image.addEventListener('load', show);
    image.addEventListener('error', nextCandidate);
    if (image.complete) image.naturalWidth > 0 ? show() : nextCandidate();
  });
};
