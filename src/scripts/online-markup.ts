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

const productVisual = (item: any) => {
  const urls = imageCandidates(item);
  const [primary = '', ...fallbacks] = urls;
  const isCard = item.kind === 'card';
  const isKit = item.kind === 'kit';
  const label = isCard ? 'Carta Pokémon' : item.kind === 'booster' ? 'Booster Pokémon' : isKit ? 'Kit personalizado' : 'Produto Pokémon';
  const initials = isKit ? 'KIT' : String(item.name || 'TCG').split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join('').toUpperCase();
  const image = primary
    ? `<img src="${escapeHtml(primary)}" alt="${escapeHtml(item.name || '')}" loading="lazy" decoding="async" data-image-candidates="${escapeHtml(JSON.stringify(fallbacks))}" />`
    : '';
  return `<div class="collectible-visual ${isCard ? 'foil-tier-basic' : item.kind === 'booster' ? 'booster-visual' : isKit ? 'kit-visual' : 'sealed-product-visual'}" data-tilt data-tilt-strength="4"><div class="image-stage"><span class="image-fallback" aria-hidden="true"><b>${escapeHtml(initials || 'TCG')}</b><small>${escapeHtml(label)}</small></span>${image}${isCard ? '<span class="holo-band" aria-hidden="true"></span><span class="foil-spectrum" aria-hidden="true"></span><span class="glare" aria-hidden="true"></span>' : ''}</div></div>`;
};

const itemPrice = (item: any) => item?.price === null || item?.price === undefined || item?.price === '' ? null : Number(item.price);

export const productMarkup = (item: any, options: { compact?: boolean; hideOwner?: boolean } = {}) => {
  const price = itemPrice(item);
  const itemType = item.kind === 'card' ? (item.type || 'Carta Pokémon') : item.kind === 'booster' ? 'Booster avulso' : item.kind === 'kit' ? 'Kit personalizado' : 'Produto lacrado';
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
  const showQuantity = item.kind === 'kit' && item.showQuantity === true;

  return `<article class="product-card${options.compact ? ' compact-card' : ''}" data-product-card data-product-id="${escapeHtml(`${item.kind}:${item.slug || item.id || item._docId || ''}`)}" data-kind="${escapeHtml(item.kind)}" data-name="${escapeHtml(item.name)}" data-number="${escapeHtml(item.number || '')}" data-collection="${escapeHtml(item.collection || item.name || '')}" data-language="${escapeHtml(item.language || '')}" data-condition="${escapeHtml(item.condition || '')}" data-year="${escapeHtml(item.year || '')}" data-type="${escapeHtml(itemType)}" data-description="${escapeHtml(item.description || '')}" data-contents="${escapeHtml(item.contents || '')}" data-link-liga="${escapeHtml(item.linkLiga || '')}" data-kit-items="${escapeHtml(JSON.stringify(kitItems))}" data-kit-discount="${kitDiscount.toFixed(1)}" data-kit-source-total="${sourceTotal || ''}" data-owner="${escapeHtml(ownerName)}" data-owner-uid="${escapeHtml(item.ownerUid || item.collectionUid || '')}" data-owner-collection="${escapeHtml(item.ownerCollectionName || '')}" data-owner-slug="${escapeHtml(ownerSlug)}" data-owner-phone="${escapeHtml(item.ownerPhone || '')}" data-proposal-policy="${escapeHtml(policy)}" data-proposal-flexible="${item.proposalTerms?.flexibleDiscounts === false ? 'false' : 'true'}" data-proposal-tiers="${escapeHtml(JSON.stringify(item.proposalTerms?.discountTiers || []))}" data-proposal-allowed="${canPropose ? 'true' : 'false'}" data-price-value="${price === null ? '' : price}" data-price-label="${escapeHtml(formatBRL(price))}" data-stock="${quantity}" data-for-sale="${item.forSale === false ? 'false' : 'true'}" data-show-quantity="${showQuantity ? 'true' : 'false'}" data-search="${escapeHtml(item.searchText || `${item.name || ''} ${item.number || ''} ${item.collection || ''} ${ownerName}`)}" data-price="${price ?? -1}" data-quantity="${quantity}" data-filter-collection="${escapeHtml(item.collection || '')}" data-filter-condition="${escapeHtml(item.condition || '')}" data-filter-type="${escapeHtml(item.type || '')}" data-filter-owner="${escapeHtml(ownerSlug)}"><button class="product-open-button" type="button" data-open-product aria-label="Ver detalhes de ${escapeHtml(item.name)}"><div class="product-card-media">${productVisual(item)}${showQuantity ? `<span class="quantity-chip">${quantity} ${quantity === 1 ? 'unidade' : 'unidades'}</span>` : ''}</div><div class="product-card-body"><div class="product-card-heading"><div><span class="product-kicker">${escapeHtml(itemType)}</span><h3>${escapeHtml(item.name)}</h3></div><span class="open-arrow" aria-hidden="true">⌗</span></div><p class="product-description">${description}</p><div class="product-card-footer"><div class="price-block"><small>Preço</small>${item.kind === 'kit' && sourceTotal > 0 && price !== null && sourceTotal > price ? `<del class="kit-original-price">${escapeHtml(formatBRL(sourceTotal))}</del>` : ''}<strong>${escapeHtml(formatBRL(price))}</strong></div>${item.kind === 'card' ? `<span class="condition-badge condition-${escapeHtml(normalizeText(item.condition).replace(/\s+/g, '-'))}">${escapeHtml(item.condition || '')}</span>` : ''}</div></div></button>${!options.hideOwner ? `<a class="collection-origin" href="${escapeHtml(collectionUrl)}"><span class="origin-avatar">${escapeHtml(ownerName.slice(0, 2).toUpperCase() || 'VT')}</span><span><small>Publicado por</small><strong>${escapeHtml(ownerName || item.ownerCollectionName || 'Colecionador')}</strong></span><b aria-hidden="true">↗</b></a>` : ''}${canPropose ? '<div class="product-purchase-actions single-action"><button class="add-proposal-button" type="button" data-add-proposal><span aria-hidden="true">◇</span>Adicionar à proposta</button></div>' : item.forSale !== false ? '<span class="not-for-sale-label">Os termos desta coleção não permitem proposta para este item</span>' : '<span class="not-for-sale-label">Não está à venda</span>'}</article>`;
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
    : '<span><strong>0</strong> itens publicados</span>';
  return `<a class="collection-card${compact ? ' compact-collection-card' : ''}" href="${escapeHtml(url)}" data-online-collection><div class="collection-card-preview"><div class="collection-flow collection-flow-placeholder" aria-hidden="true"><span>VAULT</span><strong>${escapeHtml(profile.title || 'Minha coleção')}</strong></div><span class="collection-status">${escapeHtml(status)}</span></div><div class="collection-card-body"><div class="collection-owner-row"><span class="collection-avatar${photo ? ' has-photo' : ''}">${photo ? `<img src="${escapeHtml(photo)}" alt="" loading="lazy" />` : escapeHtml(initials)}</span><div><small>Colecionador</small><strong>${escapeHtml(owner)}</strong></div><b aria-hidden="true">↗</b></div><h3>${escapeHtml(profile.title || 'Minha coleção')}</h3><p>${escapeHtml(profile.description || 'Coleção Vault TCG.')}</p><div class="collection-card-stats">${statHtml}</div></div></a>`;
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
  return `<a class="album-product-card${compact ? ' compact' : ''}" href="${escapeHtml(href)}" aria-label="Abrir o álbum ${escapeHtml(album.name || '')}"><div class="album-product-visual" aria-hidden="true"><div class="album-product-spine"><span>VT</span></div><div class="album-product-grid">${preview}${empties}</div><i class="album-product-glare"></i><i class="album-product-shadow"></i></div><div class="album-product-copy"><small>${escapeHtml(String(format).replace('x', ' por '))} · ${pages.length} ${pages.length === 1 ? 'página' : 'páginas'}</small><h3>${escapeHtml(album.name || 'Álbum')}</h3><p>${escapeHtml(album.description || `Álbum virtual de ${owner}.`)}</p><div class="album-product-progress"><i style="--album-progress:${progress}%"></i><span>${occupied} / ${total}</span></div><div class="album-product-owner"><span>${escapeHtml(String(owner).slice(0, 2).toUpperCase())}</span><strong>${escapeHtml(owner)}</strong><b>↗</b></div></div></a>`;
};

export const initializeOnlineImages = (container: ParentNode = document) => {
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
