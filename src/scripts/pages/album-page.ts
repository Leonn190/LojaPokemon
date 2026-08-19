import { escapeHtml, formatBRL, initializeOnlineImages, productVisualMarkup, toImageUrl } from '../online-markup';

const root = document.querySelector<HTMLElement>('[data-immersive-album]');
const params = new URLSearchParams(location.search);
const collectionSlug = params.get('collection') || '';
const albumSlug = params.get('album') || '';
const setText = (selector: string, value: unknown) => { const el = root?.querySelector<HTMLElement>(selector); if (el) el.textContent = String(value ?? ''); };
const escapeAttr = (value: unknown) => escapeHtml(String(value ?? ''));
const normalizeLink = (value: unknown) => String(value || '').replace(/([?&])(?:show|srsltid|utm_[^=]+)=[^&]*/gi, '$1').replace(/[?&]+$/, '');

const showError = (message: string) => {
  const error = root?.querySelector<HTMLElement>('[data-album-error]');
  if (error) error.hidden = false;
  setText('[data-album-error-message]', message || 'Confira o endereço e tente novamente.');
  const zone = root?.querySelector<HTMLElement>('.album-reading-zone');
  if (zone) zone.hidden = true;
};

const cardAttributes = (card: any) => {
  const policy = card.proposalTerms?.policy || 'flexible';
  const blocksDefinedPrice = policy === 'no_defined_price' || policy === 'fixed_price_multi_only';
  const price = card.price === null || card.price === undefined || card.price === '' ? null : Number(card.price);
  const canPropose = card.forSale !== false && policy !== 'none' && !(price !== null && blocksDefinedPrice);
  return [
    ['data-product-id', `card:${card.slug || card.id || card._id || ''}`],
    ['data-kind', 'card'], ['data-name', card.name], ['data-number', card.number], ['data-collection', card.collection],
    ['data-era', card.era], ['data-collection-id', card.collectionId], ['data-collection-code', card.collectionCode], ['data-group', card.group], ['data-card-class', card.cardClass], ['data-pokemon-type', card.cardClass ? card.type : card.pokemonType],
    ['data-language', card.language], ['data-condition', card.condition], ['data-integrity', card.integrity], ['data-year', card.year], ['data-type', card.cardClass || card.type || 'Carta Pokémon'],
    ['data-description', ''], ['data-contents', ''], ['data-link-liga', card.linkLiga], ['data-owner', card.ownerName],
    ['data-owner-uid', card.ownerUid || card.collectionUid], ['data-owner-collection', card.ownerCollectionName], ['data-owner-slug', card.ownerCollectionSlug],
    ['data-owner-phone', card.ownerPhone], ['data-proposal-policy', policy], ['data-proposal-flexible', card.proposalTerms?.flexibleDiscounts === false ? 'false' : 'true'],
    ['data-proposal-tiers', JSON.stringify(card.proposalTerms?.discountTiers || [])], ['data-proposal-allowed', canPropose ? 'true' : 'false'],
    ['data-price-value', price === null ? '' : price], ['data-price-label', formatBRL(price)], ['data-stock', Math.max(0, Number(card.quantity || 0))],
    ['data-for-sale', card.forSale === false ? 'false' : 'true'], ['data-show-quantity', 'false'],
  ].map(([name, value]) => `${name}="${escapeAttr(value)}"`).join(' ');
};

const renderAlbum = (album: any, data: any) => {
  const profile = data.profile || {};
  const palette = Array.isArray(profile.palette) ? profile.palette : ['#54e8df','#bc91ff','#f4c25c'];
  root?.style.setProperty('--album-primary', palette[0] || '#54e8df');
  root?.style.setProperty('--album-secondary', palette[1] || '#bc91ff');
  root?.style.setProperty('--album-accent', palette[2] || '#f4c25c');
  const cards = Array.isArray(data.cards) ? data.cards : [];
  const cardById = new Map<string, any>();
  const cardBySlug = new Map<string, any>();
  cards.forEach((card: any) => {
    [card.id, card._id, card.itemId].filter(Boolean).forEach((key: any) => cardById.set(String(key), card));
    if (card.slug) cardBySlug.set(String(card.slug), card);
  });
  const resolveCard = (slot: any) => {
    if (!slot) return null;
    const direct = cardById.get(String(slot.itemId || slot.id || '')) || cardBySlug.get(String(slot.cardSlug || slot.slug || ''));
    if (direct) return direct;
    const link = normalizeLink(slot.linkLiga);
    if (link) {
      const match = cards.find((card: any) => normalizeLink(card.linkLiga) === link);
      if (match) return match;
    }
    return cards.find((card: any) => String(card.name || '').toLowerCase() === String(slot.name || '').toLowerCase() && (!slot.number || String(card.number || '') === String(slot.number || ''))) || null;
  };

  const pages = (Array.isArray(album.pages) ? album.pages : []).map((page: any) => {
    const slots = Array.isArray(page?.slots) ? page.slots : [];
    return { slots, cards: slots.map(resolveCard) };
  });
  const columns = Number(album.columns || String(album.format || '3x3').split('x')[0] || 3);
  const rows = Number(album.rows || String(album.format || '3x3').split('x')[1] || 3);
  const format = album.format || `${columns}x${rows}`;
  const occupied = Number(album.occupiedSlots ?? pages.flatMap((page: any) => page.slots).filter(Boolean).length);
  const total = Number(album.totalSlots ?? pages.reduce((sum: number, page: any) => sum + page.slots.length, 0));
  const progress = total > 0 ? Math.round((occupied / total) * 100) : 0;
  const owner = album.ownerName || profile.owner || 'Colecionador';
  const ownerSlug = album.ownerCollectionSlug || profile.slug || collectionSlug;

  document.title = `${album.name || 'Álbum'} · Vault TCG`;
  setText('[data-album-name]', album.name || 'Álbum');
  setText('[data-album-name-breadcrumb]', album.name || 'Álbum');
  setText('[data-album-description]', album.description || `Álbum organizado por ${owner}.`);
  setText('[data-album-kicker]', `Álbum virtual · ${String(format).replace('x', ' por ')}`);
  setText('[data-album-owner]', owner);
  setText('[data-album-owner-initials]', String(owner).slice(0, 2).toUpperCase());
  setText('[data-album-pages]', pages.length);
  setText('[data-album-format]', String(format).replace('x', ' × '));
  setText('[data-album-occupied]', occupied);
  setText('[data-album-progress]', `${progress}%`);
  const progressBar = root?.querySelector<HTMLElement>('[data-album-progress-bar]');
  progressBar?.style.setProperty('--album-progress', `${progress}%`);
  const ownerLink = root?.querySelector<HTMLAnchorElement>('[data-album-owner-link]');
  if (ownerLink) ownerLink.href = `${document.body.dataset.siteBase || '/'}colecao/?slug=${encodeURIComponent(ownerSlug)}`;

  const coverElement = root?.querySelector<HTMLElement>('[data-album-cover]');
  if (coverElement) {
    const allowedStyles = ['vault', 'leather', 'holo', 'minimal'];
    const coverStyle = allowedStyles.includes(String(album.coverStyle || '')) ? String(album.coverStyle) : 'vault';
    allowedStyles.forEach((style) => coverElement.classList.remove(`binder-style-${style}`));
    coverElement.classList.add(`binder-style-${coverStyle}`);
    const coverColor = /^#[0-9a-f]{6}$/i.test(String(album.coverColor || '')) ? String(album.coverColor) : '#14253d';
    coverElement.style.setProperty('--binder-cover', coverColor);
    const customImage = toImageUrl(album.coverImage || '');
    coverElement.classList.toggle('has-custom-cover-image', Boolean(customImage));
    if (customImage) coverElement.style.setProperty('--binder-image', `url("${customImage.replace(/"/g, '\\"')}")`);
    else coverElement.style.removeProperty('--binder-image');
  }
  setText('[data-album-cover-title]', album.coverTitle || album.name || 'Álbum');

  const coverItems = pages.flatMap((page: any) => page.slots.map((slot: any, index: number) => page.cards[index] || slot)).filter(Boolean).slice(0, 8);
  const cover = root?.querySelector<HTMLElement>('[data-album-cover-mosaic]');
  if (cover) {
    cover.innerHTML = coverItems.map((item: any) => {
      const candidates = (Array.isArray(item.imageCandidates) ? item.imageCandidates : []).map(toImageUrl).filter(Boolean);
      const [primary = '', ...fallbacks] = candidates;
      return `<span>${primary ? `<img src="${escapeAttr(primary)}" alt="" loading="eager" decoding="async" data-image-candidates="${escapeAttr(JSON.stringify(fallbacks))}" />` : `<b>${escapeHtml(String(item.name || 'TC').slice(0, 2).toUpperCase())}</b>`}</span>`;
    }).join('') + Array.from({ length: Math.max(0, 8 - coverItems.length) }, () => '<span class="empty"></span>').join('');
  }

  const book = root?.querySelector<HTMLElement>('[data-album-book]');
  if (!book) return;
  book.innerHTML = pages.map((page: any, pageIndex: number) => {
    const slots = page.slots.map((slot: any, slotIndex: number) => {
      const card = page.cards[slotIndex];
      if (!slot) return `<div class="immersive-album-slot empty"><span>${slotIndex + 1}</span><small>espaço livre</small></div>`;
      if (!card) {
        const candidates = (Array.isArray(slot.imageCandidates) ? slot.imageCandidates : []).map(toImageUrl).filter(Boolean);
        const [primary = '', ...fallbacks] = candidates;
        return `<article class="immersive-album-slot unresolved"><div class="immersive-card-image">${primary ? `<img src="${escapeAttr(primary)}" alt="${escapeAttr(slot.name || 'Carta')}" loading="lazy" decoding="async" data-image-candidates="${escapeAttr(JSON.stringify(fallbacks))}" />` : `<span>${escapeHtml(String(slot.name || 'TC').slice(0, 2).toUpperCase())}</span>`}</div><div class="immersive-card-caption"><strong>${escapeHtml(slot.name || 'Carta')}</strong><small>${escapeHtml(slot.number || '')}</small></div></article>`;
      }
      return `<article class="immersive-album-slot occupied" data-product-card ${cardAttributes(card)}><button class="immersive-card-button" type="button" data-open-product aria-label="Abrir informações avançadas de ${escapeAttr(card.name || 'Carta')}"><div class="immersive-card-visual">${productVisualMarkup(card)}</div><div class="immersive-card-caption"><strong>${escapeHtml(card.name || 'Carta')}</strong><small>${escapeHtml(card.number || '')}</small></div><span class="immersive-card-open">Ver detalhes <b>⌗</b></span></button></article>`;
    }).join('');
    return `<section class="immersive-album-sheet ${pageIndex % 2 === 0 ? 'left' : 'right'}" data-album-page="${pageIndex}" ${pageIndex > 1 ? 'hidden' : ''}><header><span>Página ${pageIndex + 1}</span><b>${escapeHtml(String(format).replace('x', ' × '))}</b></header><div class="immersive-pocket-grid" style="--album-columns:${columns};--album-rows:${rows}">${slots}</div><span class="immersive-page-texture" aria-hidden="true"></span><span class="immersive-page-edge" aria-hidden="true"></span></section>`;
  }).join('') + (pages.length % 2 === 1 ? `<section class="immersive-album-sheet right immersive-album-endpaper" data-album-endpaper hidden aria-hidden="true"><div class="album-endpaper-mark"><span>VT</span><strong>Fim do álbum</strong><small>${escapeHtml(album.name || 'Álbum')}</small></div><span class="immersive-page-texture" aria-hidden="true"></span><span class="immersive-page-edge" aria-hidden="true"></span></section>` : '');

  const rail = root?.querySelector<HTMLElement>('[data-album-page-rail]');
  if (rail) rail.innerHTML = pages.map((_: any, index: number) => `<button type="button" data-album-page-jump="${index}" class="${index === 0 ? 'active' : ''}"><span>${index + 1}</span></button>`).join('');
  initializeOnlineImages(root || document);
  initializeReader();
};

const initializeReader = () => {
  if (!root || root.dataset.readerReady === 'true') return;
  root.dataset.readerReady = 'true';
  const pages = [...root.querySelectorAll<HTMLElement>('[data-album-page]')];
  const bookWrap = root.querySelector<HTMLElement>('[data-album-book-wrap]');
  const prev = root.querySelector<HTMLButtonElement>('[data-album-previous]');
  const next = root.querySelector<HTMLButtonElement>('[data-album-next]');
  const label = root.querySelector<HTMLElement>('[data-album-page-label]');
  const rail = root.querySelector<HTMLElement>('[data-album-page-rail]');
  const endpaper = root.querySelector<HTMLElement>('[data-album-endpaper]');
  const focusButton = root.querySelector<HTMLButtonElement>('[data-album-focus]');
  const focusExit = root.querySelector<HTMLButtonElement>('[data-album-focus-exit]');
  const mobile = window.matchMedia('(max-width: 760px)');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let start = 0;
  let timer = 0;
  const perView = () => mobile.matches ? 1 : 2;
  const lastStart = () => Math.max(0, pages.length - perView());
  const normalizedStart = (value: number) => {
    const clamped = Math.max(0, Math.min(value, lastStart()));
    return perView() === 2 ? Math.floor(clamped / 2) * 2 : clamped;
  };
  const render = (direction = 0) => {
    start = normalizedStart(start);
    const count = perView();
    pages.forEach((page, index) => { page.hidden = index < start || index >= start + count; });
    if (endpaper) endpaper.hidden = mobile.matches || pages.length % 2 === 0 || start + count < pages.length;
    const end = Math.min(pages.length, start + count);
    if (label) label.textContent = end - start > 1 ? `Páginas ${start + 1}–${end}` : `Página ${start + 1}`;
    if (prev) prev.disabled = start === 0;
    if (next) next.disabled = start + count >= pages.length;
    rail?.querySelectorAll<HTMLElement>('[data-album-page-jump]').forEach((button) => {
      const index = Number(button.dataset.albumPageJump || 0);
      button.classList.toggle('active', index >= start && index < end);
    });
    if (direction && bookWrap && !reduced) {
      window.clearTimeout(timer);
      bookWrap.classList.remove('turn-forward', 'turn-backward');
      void bookWrap.offsetWidth;
      bookWrap.classList.add(direction > 0 ? 'turn-forward' : 'turn-backward');
      timer = window.setTimeout(() => bookWrap.classList.remove('turn-forward', 'turn-backward'), 780);
    }
  };
  const step = (direction: number) => { start += direction * perView(); render(direction); };
  prev?.addEventListener('click', () => step(-1));
  next?.addEventListener('click', () => step(1));
  rail?.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-album-page-jump]') : null;
    if (!target) return;
    const requested = Number(target.dataset.albumPageJump || 0);
    const direction = requested >= start ? 1 : -1;
    start = requested;
    render(direction);
  });
  document.addEventListener('keydown', (event) => {
    if (document.body.classList.contains('modal-open')) return;
    if (event.key === 'ArrowLeft' && start > 0) step(-1);
    if (event.key === 'ArrowRight' && start + perView() < pages.length) step(1);
  });
  mobile.addEventListener?.('change', () => render());
  const setFocusMode = (active: boolean) => {
    const readingZone = root.querySelector<HTMLElement>('[data-album-reading-zone]');
    if (active && readingZone) readingZone.hidden = false;
    document.body.classList.toggle('album-focus-mode', active);
    focusButton?.setAttribute('aria-pressed', String(active));
    if (focusButton) focusButton.innerHTML = active ? '<span>◇</span> Sair da apresentação' : '<span>◈</span> Apresentar álbum';
    if (active) root.querySelector('[data-album-stage]')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
  };
  root.querySelector<HTMLButtonElement>('[data-album-open]')?.addEventListener('click', () => {
    const readingZone = root.querySelector<HTMLElement>('[data-album-reading-zone]');
    if (readingZone) readingZone.hidden = false;
    root.querySelector('[data-album-stage]')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
  });
  focusButton?.addEventListener('click', () => setFocusMode(!document.body.classList.contains('album-focus-mode')));
  focusExit?.addEventListener('click', () => setFocusMode(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.body.classList.contains('album-focus-mode') && !document.body.classList.contains('modal-open')) setFocusMode(false);
  });
  render();
};

const load = async () => {
  try {
    if (!collectionSlug || !albumSlug) throw new Error('Endereço do álbum incompleto.');
    const cloud = (window as any).VaultCloud;
    if (!cloud) throw new Error('Álbuns ainda não foram inicializados.');
    const data = await cloud.loadCollectionBySlug(decodeURIComponent(collectionSlug));
    if (!data) throw new Error('Coleção não encontrada.');
    const album = (data.albums || []).find((entry: any) => {
      const id = String(entry.slug || entry.albumId || entry.id || entry._id || entry._docId || '');
      const aliases = [entry.slug, entry.albumId, entry.id, entry._id, entry._docId].filter(Boolean).map(String);
      return id === albumSlug || aliases.includes(albumSlug);
    });
    if (!album) throw new Error('Álbum não encontrado nesta coleção.');
    renderAlbum(album, data);
  } catch (error: any) {
    showError(error?.message || 'Confira o endereço e tente novamente.');
  }
};

if ((window as any).VaultCloud) load();
else window.addEventListener('vault:cloud-ready', load, { once: true });
