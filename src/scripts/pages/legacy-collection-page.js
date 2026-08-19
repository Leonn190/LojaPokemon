(() => {
  const base = document.body.dataset.siteBase || '/';
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
  const normalize = (value) => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const formatBRL = (value) => value === null || value === undefined ? 'Consultar' : new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(value));
  const imageUrl = (path) => /^(?:https?:|data:|blob:)/i.test(path || '') ? path : `${base}${String(path || '').replace(/^\/+/, '').split('/').map(encodeURIComponent).join('/')}`;

  document.querySelector('[data-share-collection]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    const original = button.innerHTML;
    try {
      if (navigator.share) await navigator.share({ title: document.title, url: location.href });
      else await navigator.clipboard.writeText(location.href);
      button.innerHTML = '<span>Link copiado</span><b>✓</b>';
    } catch (_) {}
    setTimeout(() => { button.innerHTML = original; }, 1400);
  });

  const dynamicImage = (candidates, alt = '') => {
    const urls = (Array.isArray(candidates) ? candidates : []).map(imageUrl);
    const primary = urls[0] || '';
    if (!primary) return '';
    return `<img src="${escapeHtml(primary)}" alt="${escapeHtml(alt)}" loading="lazy" decoding="async" data-image-candidates="${escapeHtml(JSON.stringify(urls.slice(1)))}" />`;
  };
  const rarityTier = (type) => {
    const value = normalize(type);
    const premiumTokens = ['full art', 'ultra rara', 'ultra rare', 'secret', 'gold', 'rainbow', 'illustration rare', 'ilustracao rara', 'arte rara', 'special illustration', 'sir', 'alt art', 'trainer gallery', 'shiny', 'hyper'];
    if (premiumTokens.some((token) => value.includes(token)) || /(^|\s)(ru|sr|re)(\s|$)/i.test(String(type || ''))) return 'premium';
    const holoTokens = ['holo', 'foil', 'reverse', 'radiante', 'radiant', 'vmax', 'v-astro', 'vstar', 'mega ex', ' ex', 'gx', 'rh', 'rl', 'rd'];
    if (holoTokens.some((token) => value.includes(token)) || /^(?:mega\s+)?(?:ex|gx|v(?:max|star|-astro|-union)?)(?:\b|\s|—|-)/i.test(value) || /(^|\s)v(\s|$)/i.test(String(type || ''))) return 'holo';
    return 'basic';
  };
  const dynamicVisual = (item) => {
    const initials = item.kind === 'kit' ? 'KIT' : String(item.name || 'TCG').split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
    if (item.kind === 'kit') {
      const allContents = (Array.isArray(item.contentItems) ? item.contentItems : []).filter((entry) => Array.isArray(entry.imageCandidates) && entry.imageCandidates.length);
      const cards = allContents.filter((entry) => entry.kind === 'cards').slice(0, 2);
      const boosters = allContents.filter((entry) => entry.kind === 'boosters').slice(0, 1);
      const contents = [...cards, ...boosters, ...allContents.filter((entry) => !cards.includes(entry) && !boosters.includes(entry))].slice(0, 3);
      if (contents.length) {
        const units = (item.contentItems || []).reduce((total, entry) => total + Math.max(1, Number(entry.quantity) || 1), 0);
        const discount = item.sourceTotal > 0 && item.price !== null ? Math.max(0, ((item.sourceTotal - item.price) / item.sourceTotal) * 100) : 0;
        const stack = contents.map((entry, index) => {
          const entryInitials = String(entry.name || 'TCG').split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
          return `<span class="kit-stack-card kit-stack-card-${index + 1} ${entry.kind === 'boosters' ? 'booster-item' : ''}"><span class="kit-stack-card-surface" data-image-stage><span class="kit-stack-fallback">${escapeHtml(entryInitials || 'TCG')}</span>${dynamicImage(entry.imageCandidates, '')}</span></span>`;
        }).join('');
        return `<div class="collectible-visual kit-visual kit-composite-visual" data-tilt data-tilt-strength="4"><div class="image-stage kit-image-stage"><span class="image-fallback"><b>KIT</b><small>Kit personalizado</small></span><div class="kit-stack" aria-hidden="true">${stack}</div><span class="kit-composite-badge">${units || contents.length} ${units === 1 ? 'item' : 'itens'}</span>${discount > 0 ? `<span class="kit-discount-badge">-${discount.toFixed(0)}%</span>` : ''}<span class="kit-composite-shine"></span></div></div>`;
      }
    }
    const image = dynamicImage(item.imageCandidates, item.name || '');
    const cardTier = item.kind === 'card' ? ` foil-tier-${rarityTier(item.cardClass || item.type)}` : '';
    return `<div class="collectible-visual ${item.kind === 'booster' ? 'booster-visual' : item.kind === 'kit' ? 'kit-visual' : item.kind === 'product' ? 'sealed-product-visual' : ''}${cardTier}" data-tilt data-tilt-strength="${item.kind === 'booster' ? '3' : item.kind === 'product' ? '4' : item.kind === 'kit' ? '4' : '5'}"><div class="image-stage"><span class="image-fallback"><b>${escapeHtml(initials)}</b><small>${item.kind === 'card' ? 'Carta Pokémon' : item.kind === 'booster' ? 'Booster Pokémon' : item.kind === 'kit' ? 'Kit personalizado' : 'Produto Pokémon'}</small></span>${image}${item.kind === 'card' ? '<span class="holo-band"></span><span class="foil-spectrum"></span><span class="glare"></span>' : ''}</div></div>`;
  };
  const productMarkup = (item) => {
    const itemType = item.kind === 'card' ? (item.cardClass || item.type || 'Carta Pokémon') : item.kind === 'booster' ? 'Booster avulso' : item.kind === 'kit' ? 'Kit personalizado' : 'Produto lacrado';
    const description = item.kind === 'card' ? `<strong>${escapeHtml(item.number || '')}</strong><span>•</span>${escapeHtml(item.collection || '')}` : item.kind === 'kit' || item.kind === 'product' ? escapeHtml(item.description || (item.kind === 'product' ? 'Produto Pokémon lacrado.' : '')) : 'Pacote lacrado publicado pelo colecionador.';
    const policy = item.proposalTerms?.policy || 'flexible';
    const blocksDefinedPrice = policy === 'no_defined_price' || policy === 'fixed_price_multi_only';
    const canPropose = item.forSale && policy !== 'none' && !(item.kind === 'card' && item.price !== null && item.price !== undefined && blocksDefinedPrice);
    const tiers = escapeHtml(JSON.stringify(item.proposalTerms?.discountTiers || []));
    return `<article class="product-card compact-card" data-product-card data-product-id="${escapeHtml(`${item.kind}:${item.slug}`)}" data-kind="${escapeHtml(item.kind)}" data-name="${escapeHtml(item.name)}" data-number="${escapeHtml(item.number || '')}" data-era="${escapeHtml(item.era || '')}" data-collection="${escapeHtml(item.collection || item.name || '')}" data-collection-id="${escapeHtml(item.collectionId || '')}" data-collection-code="${escapeHtml(item.collectionCode || '')}" data-group="${escapeHtml(item.group || '')}" data-card-class="${escapeHtml(item.cardClass || '')}" data-pokemon-type="${escapeHtml(item.kind === 'card' && item.cardClass ? (item.type || '') : (item.pokemonType || ''))}" data-language="${escapeHtml(item.language || '')}" data-condition="${escapeHtml(item.condition || '')}" data-integrity="${escapeHtml(item.integrity ?? '')}" data-year="${escapeHtml(item.year || '')}" data-type="${escapeHtml(itemType)}" data-description="${escapeHtml(item.description || '')}" data-contents="${escapeHtml(item.contents || '')}" data-kit-items="${escapeHtml(JSON.stringify(item.kind === 'kit' ? (item.contentItems || []).map((entry) => ({ kind: entry.kind, name: entry.name, quantity: entry.quantity, type: entry.type || '', imageCandidates: entry.imageCandidates || [] })) : []))}" data-kit-discount="${item.kind === 'kit' && item.sourceTotal > 0 && item.price !== null ? Math.max(0, ((item.sourceTotal - item.price) / item.sourceTotal) * 100).toFixed(1) : '0'}" data-link-liga="${escapeHtml(item.linkLiga || '')}" data-owner="${escapeHtml(item.ownerName)}" data-owner-collection="${escapeHtml(item.ownerCollectionName)}" data-owner-slug="${escapeHtml(item.ownerCollectionSlug)}" data-owner-phone="${escapeHtml(item.ownerPhone || '')}" data-proposal-policy="${escapeHtml(policy)}" data-proposal-flexible="${item.proposalTerms?.flexibleDiscounts !== false ? 'true' : 'false'}" data-proposal-tiers="${tiers}" data-proposal-allowed="${canPropose ? 'true' : 'false'}" data-price-value="${item.price ?? ''}" data-price-label="${escapeHtml(formatBRL(item.price))}" data-stock="${item.quantity}" data-for-sale="${item.forSale ? 'true' : 'false'}" data-show-quantity="false"><button class="product-open-button" type="button" data-open-product><div class="product-card-media">${dynamicVisual(item)}</div><div class="product-card-body"><div class="product-card-heading"><div><span class="product-kicker">${escapeHtml(itemType)}</span><h3>${escapeHtml(item.name)}</h3></div><span class="open-arrow">⌗</span></div><p class="product-description">${description}</p><div class="product-card-footer"><div class="price-block"><small>Preço</small>${item.kind === 'kit' && item.sourceTotal > 0 && item.price !== null && item.sourceTotal > item.price ? `<del class="kit-original-price">${escapeHtml(formatBRL(item.sourceTotal))}</del>` : ''}<strong>${escapeHtml(formatBRL(item.price))}</strong></div>${item.kind === 'card' ? `<span class="condition-badge condition-${escapeHtml(normalize(item.condition).replace(/\s+/g, '-'))}">${escapeHtml(item.condition || '')}</span>` : ''}</div></div></button>${canPropose ? '<div class="product-purchase-actions single-action"><button class="add-proposal-button" type="button" data-add-proposal><span>◇</span>Adicionar à proposta</button></div>' : item.forSale ? '<span class="not-for-sale-label">Os termos desta coleção não permitem proposta para este item</span>' : '<span class="not-for-sale-label">Não está à venda</span>'}</article>`;
  };
  const initializeDynamicCards = (container) => {
    container.querySelectorAll('img[data-image-candidates]').forEach((image) => {
      if (image.dataset.dynamicReady) return;
      image.dataset.dynamicReady = 'true';
      const show = () => { image.hidden = false; image.closest('[data-image-stage], .image-stage')?.classList.add('has-image'); };
      const nextCandidate = () => {
        let candidates = [];
        try { candidates = JSON.parse(image.dataset.imageCandidates || '[]'); } catch (_) {}
        const next = candidates.shift();
        if (next) { image.dataset.imageCandidates = JSON.stringify(candidates); image.src = next; }
        else image.remove();
      };
      image.addEventListener('load', show);
      image.addEventListener('error', nextCandidate);
      if (image.complete) image.naturalWidth > 0 ? show() : nextCandidate();
    });
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!finePointer || reducedMotion) return;
    container.querySelectorAll('[data-tilt]').forEach((element) => {
      if (element.dataset.dynamicTiltReady) return;
      element.dataset.dynamicTiltReady = 'true';
      element.addEventListener('pointermove', (event) => {
        const bounds = element.getBoundingClientRect();
        const x = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
        const y = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height));
        const strength = Number(element.dataset.tiltStrength || 5);
        element.style.setProperty('--mx', `${x * 100}%`);
        element.style.setProperty('--my', `${y * 100}%`);
        element.style.setProperty('--ry', `${(x - .5) * strength * 2}deg`);
        element.style.setProperty('--rx', `${(.5 - y) * strength * 2}deg`);
        element.classList.add('is-tilting');
      });
      element.addEventListener('pointerleave', () => {
        element.style.setProperty('--rx', '0deg');
        element.style.setProperty('--ry', '0deg');
        element.style.setProperty('--mx', '50%');
        element.style.setProperty('--my', '50%');
        element.classList.remove('is-tilting');
      });
    });
  };

  document.querySelectorAll('[data-collection-shelf]').forEach((shelf) => {
    const button = shelf.querySelector('[data-expand-shelf]');
    const expanded = shelf.querySelector('[data-expanded-catalog]');
    const preview = shelf.querySelector('[data-shelf-preview]');
    const grid = shelf.querySelector('[data-shelf-grid]');
    const search = shelf.querySelector('[data-shelf-search]');
    const filters = shelf.querySelector('[data-shelf-filters]');
    const count = shelf.querySelector('[data-shelf-count]');
    const kind = shelf.dataset.kind;
    let items = null;
    let loading = false;
    const buildFilters = () => {
      filters.innerHTML = `<label class="shelf-sort-only"><span>Ordenar</span><select data-shelf-sort><option value="name">Nome</option><option value="price-asc">Menor preço</option><option value="price-desc">Maior preço</option></select></label>`;
      filters.querySelector('[data-shelf-sort]')?.addEventListener('change', applyFilters);
    };
    const applyFilters = () => {
      if (!items) return;
      const query = normalize(search.value);
      let visible = items.filter((item) => !query || normalize(`${item.searchText || ''} ${item.name || ''}`).includes(query));
      const sort = filters.querySelector('[data-shelf-sort]')?.value || 'name';
      visible = [...visible].sort((left, right) => sort === 'price-asc' ? (left.price ?? Infinity) - (right.price ?? Infinity) : sort === 'price-desc' ? (right.price ?? -1) - (left.price ?? -1) : String(left.name).localeCompare(String(right.name), 'pt-BR'));
      grid.innerHTML = visible.length ? visible.map(productMarkup).join('') : '<div class="collection-filter-empty"><span>⌕</span><strong>Nenhum item encontrado</strong><p>Tente outro nome ou termo.</p></div>';
      count.textContent = `${visible.length} ${visible.length === 1 ? 'resultado' : 'resultados'}`;
      initializeDynamicCards(grid);
    };
    const load = async () => {
      if (items || loading) return;
      loading = true;
      try {
        const response = await fetch(shelf.dataset.endpoint);
        if (!response.ok) throw new Error('Falha ao carregar');
        items = await response.json();
        buildFilters();
        applyFilters();
      } catch (_) {
        grid.innerHTML = '<div class="collection-filter-empty"><span>!</span><strong>Não foi possível carregar agora</strong><p>Recarregue a página e tente novamente.</p></div>';
        count.textContent = 'Erro no carregamento';
      } finally { loading = false; }
    };
    button?.addEventListener('click', async () => {
      const opening = expanded.hidden;
      expanded.hidden = !opening;
      if (preview) preview.hidden = opening;
      button.classList.toggle('active', opening);
      button.querySelector('span').textContent = opening ? 'Voltar ao carrossel' : 'Pesquisar coleção';
      button.querySelector('b').textContent = opening ? '↩' : '⌕';
      if (opening) { await load(); search?.focus(); shelf.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    });
    search?.addEventListener('input', applyFilters);
  });
})();
