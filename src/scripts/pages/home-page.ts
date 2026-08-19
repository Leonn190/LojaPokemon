import { albumMarkup, collectionMarkup, initializeOnlineImages, productMarkup } from '../online-markup';

const heroFlow = document.querySelector<HTMLElement>('.nexus-hero-card-flow');
let heroInView = true;
const syncHeroAnimation = () => heroFlow?.classList.toggle('is-paused', document.hidden || !heroInView);
if (heroFlow && 'IntersectionObserver' in window) {
  const heroObserver = new IntersectionObserver(([entry]) => { heroInView = Boolean(entry?.isIntersecting); syncHeroAnimation(); }, { rootMargin: '120px 0px' });
  heroObserver.observe(heroFlow);
}
document.addEventListener('visibilitychange', syncHeroAnimation);

const allHeroImages = Array.from(document.querySelectorAll<HTMLImageElement>('.nexus-hero-card-flow img'));
const markHeroImageReady = (image: HTMLImageElement) => image.closest('.image-stage')?.classList.add('hero-wall-image-ready');
allHeroImages.forEach((image) => {
  image.addEventListener('load', () => markHeroImageReady(image), { once: true });
  if (image.complete && image.naturalWidth > 0) markHeroImageReady(image);
});

const primaryHeroImages = Array.from(document.querySelectorAll<HTMLImageElement>('.nexus-hero-flow-track .nexus-hero-flow-set:first-child img'));
primaryHeroImages.slice(0, 12).forEach((image) => {
  image.loading = 'eager';
  image.fetchPriority = 'high';
});

const activateDeferredHeroImage = (image: HTMLImageElement) => {
  const source = image.dataset.deferredSrc;
  if (!source || image.getAttribute('src')) return;
  image.loading = 'eager';
  image.removeAttribute('data-defer-load');
  delete image.dataset.deferredSrc;
  image.src = source;
  (window as any).VaultHydrate?.(image.parentElement || document);
};

/* Mantém o primeiro frame leve (12 artes), mas começa a completar a parede
   imediatamente durante a animação de entrada. */
const primaryDeferredHeroImages = primaryHeroImages.filter((image) => image.dataset.deferLoad === 'true');
let primaryDeferredCursor = 0;
const loadPrimaryHeroBatch = () => {
  const end = Math.min(primaryDeferredHeroImages.length, primaryDeferredCursor + 8);
  while (primaryDeferredCursor < end) activateDeferredHeroImage(primaryDeferredHeroImages[primaryDeferredCursor++]);
  if (primaryDeferredCursor < primaryDeferredHeroImages.length) window.setTimeout(loadPrimaryHeroBatch, 70);
};
if (primaryDeferredHeroImages.length) window.setTimeout(loadPrimaryHeroBatch, 20);

/* A cópia usada pelo loop da animação continua progressiva e só começa
   quando a parede principal já está sendo revelada. */
const deferredHeroImages = Array.from(document.querySelectorAll<HTMLImageElement>('.nexus-hero-flow-track .nexus-hero-flow-set:nth-child(2) img[data-defer-load="true"]'));
let deferredHeroCursor = 0;
let deferredHeroStarted = false;
const loadDeferredHeroBatch = () => {
  if (document.hidden) { window.setTimeout(loadDeferredHeroBatch, 320); return; }
  const end = Math.min(deferredHeroImages.length, deferredHeroCursor + 8);
  while (deferredHeroCursor < end) activateDeferredHeroImage(deferredHeroImages[deferredHeroCursor++]);
  if (deferredHeroCursor >= deferredHeroImages.length) return;
  const idle = (window as any).requestIdleCallback;
  if (typeof idle === 'function') idle(loadDeferredHeroBatch, { timeout: 260 });
  else window.setTimeout(loadDeferredHeroBatch, 140);
};
const startDeferredHeroLoad = () => {
  if (deferredHeroStarted) return;
  deferredHeroStarted = true;
  window.setTimeout(loadDeferredHeroBatch, 80);
};

const waitForHeroWall = () => {
  if (!primaryHeroImages.length) return Promise.resolve();
  const waitForImage = (image: HTMLImageElement) => new Promise<void>((resolve) => {
    if (image.complete && image.naturalWidth > 0) { resolve(); return; }
    let settled = false;
    const done = () => { if (!settled) { settled = true; resolve(); } };
    image.addEventListener('load', done, { once: true });
    image.addEventListener('error', done, { once: true });
  });
  return Promise.race([
    Promise.all(primaryHeroImages.map(waitForImage)).then(() => undefined),
    new Promise<void>((resolve) => window.setTimeout(resolve, 1800)),
  ]);
};

const intro = document.querySelector<HTMLElement>('[data-vault-intro]');
const finishIntro = () => {
  if (!intro) return;
  intro.classList.remove('vault-intro-pending', 'vault-intro-running', 'vault-intro-revealing', 'vault-intro-copy');
  intro.classList.add('vault-intro-complete');
  startDeferredHeroLoad();
};
if (intro) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced) finishIntro();
  else {
    intro.classList.add('vault-intro-running');
    (async () => {
      await Promise.all([
        waitForHeroWall(),
        new Promise<void>((resolve) => window.setTimeout(resolve, 720)),
      ]);
      if (intro.classList.contains('vault-intro-complete')) return;
      intro.classList.add('vault-intro-revealing');
      startDeferredHeroLoad();
      window.setTimeout(() => intro.classList.add('vault-intro-copy'), 650);
      window.setTimeout(finishIntro, 1530);
    })();
    window.setTimeout(finishIntro, 3800);
  }
}

const shuffle = <T,>(source: T[]) => {
  const items = [...source];
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
};
const fillLoop = <T,>(source: T[], minimum: number) => source.length
  ? Array.from({ length: Math.max(minimum, source.length) }, (_, index) => source[index % source.length])
  : [];

const renderCarousel = (kind: string, items: any[], markup: (item: any) => string, minimum = 10) => {
  const section = document.querySelector<HTMLElement>(`[data-home-carousel="${kind}"]`);
  if (!section) return;
  const loading = section.querySelector<HTMLElement>('[data-home-carousel-loading]');
  const track = section.querySelector<HTMLElement>('[data-home-carousel-track]');
  const empty = section.querySelector<HTMLElement>('[data-home-carousel-empty]');
  const primary = section.querySelector<HTMLElement>('[data-home-carousel-sequence="primary"]');
  const copy = section.querySelector<HTMLElement>('[data-home-carousel-sequence="copy"]');
  if (loading) loading.hidden = true;
  if (!items.length) {
    if (track) track.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  const loop = fillLoop(shuffle(items), minimum);
  const html = loop.map(markup).join('');
  if (primary) primary.innerHTML = html;
  if (copy) copy.innerHTML = html;
  if (empty) empty.hidden = true;
  if (track) track.hidden = false;
  initializeOnlineImages(section);
};

const loadHome = async () => {
  try {
    const cloud = (window as any).VaultCloud;
    if (!cloud) throw new Error('Catálogo ainda não foi inicializado.');
    const [collections, cardPage, boosterPage, kitPage, productPage, albumPage] = await Promise.all([
      cloud.listPublicCollections(),
      cloud.listPublicItemsPage('card', 24),
      cloud.listPublicItemsPage('booster', 20),
      cloud.listPublicItemsPage('kit', 20),
      cloud.listPublicItemsPage('product', 20),
      cloud.listPublicAlbumsPage(18),
    ]);
    const cards = cardPage.items || [];
    const boosters = boosterPage.items || [];
    const kits = kitPage.items || [];
    const products = productPage.items || [];
    const albums = albumPage.items || [];

    const cardCount = collections.reduce((sum: number, profile: any) => sum + Number(profile.stats?.cards || 0), 0);
    const itemCount = collections.reduce((sum: number, profile: any) => sum
      + Number(profile.stats?.cards || 0)
      + Number(profile.stats?.boosters || 0)
      + Number(profile.stats?.kits || 0)
      + Number(profile.stats?.products || 0), 0);
    const collectionMetric = document.querySelector<HTMLElement>('[data-home-collections]');
    const cardMetric = document.querySelector<HTMLElement>('[data-home-cards]');
    const itemMetric = document.querySelector<HTMLElement>('[data-home-items]');
    if (collectionMetric) collectionMetric.textContent = String(collections.length);
    if (cardMetric) cardMetric.textContent = String(cardCount);
    if (itemMetric) itemMetric.textContent = String(itemCount);

    const previewMap = new Map<string, any[]>();
    cards.forEach((card: any) => {
      [card.collectionUid, card.ownerUid, card.ownerCollectionSlug].filter(Boolean).forEach((key: string) => {
        const list = previewMap.get(String(key)) || [];
        if (list.length < 12) list.push(card);
        previewMap.set(String(key), list);
      });
    });
    const hasUsablePreview = (profile: any) => Array.isArray(profile.previewCards) && profile.previewCards.some((card: any) =>
      (Array.isArray(card?.imageCandidates) && card.imageCandidates.some(Boolean)) || Boolean(card?.image)
    );
    const collectionsWithCovers = collections.map((profile: any) => {
      const keys = [profile.uid, profile.ownerUid, profile.slug, profile.collectionId].filter(Boolean).map(String);
      const mappedPreview = keys.flatMap((key) => previewMap.get(key) || []).filter((card, index, list) => list.indexOf(card) === index).slice(0, 12);
      const storedPreview = Array.isArray(profile.previewCards) ? profile.previewCards : [];
      const previewCards = storedPreview.length ? storedPreview : mappedPreview;
      return { ...profile, previewCards };
    });

    renderCarousel('cards', shuffle(cards).slice(0, 14), (item) => productMarkup(item, { compact: true }), 14);
    renderCarousel('boosters', shuffle(boosters).slice(0, 14), (item) => productMarkup(item, { compact: true }), 12);
    renderCarousel('kits', shuffle(kits).slice(0, 14), (item) => productMarkup(item, { compact: true }), 10);
    renderCarousel('products', shuffle(products).slice(0, 14), (item) => productMarkup(item, { compact: true }), 10);
    renderCarousel('albums', shuffle(albums).slice(0, 14), (item) => albumMarkup(item, true), 12);

    const previewQueue = collectionsWithCovers.filter((profile: any) => !hasUsablePreview(profile));
    if (previewQueue.length && typeof cloud.listPublicCollectionPreview === 'function') {
      const worker = async () => {
        while (previewQueue.length) {
          const profile = previewQueue.shift();
          if (!profile) return;
          const uid = String(profile.uid || profile.ownerUid || '').trim();
          if (!uid) continue;
          try {
            const preview = await cloud.listPublicCollectionPreview(uid, 12);
            if (Array.isArray(preview) && preview.length) profile.previewCards = preview;
          } catch (_) {}
        }
      };
      await Promise.all([worker(), worker(), worker()]);
    }
    renderCarousel('collections', shuffle(collectionsWithCovers), (item) => collectionMarkup(item, true), Math.max(1, collectionsWithCovers.length));
  } catch (_) {
    document.querySelectorAll<HTMLElement>('[data-home-carousel]').forEach((section) => {
      const loading = section.querySelector<HTMLElement>('[data-home-carousel-loading]');
      const empty = section.querySelector<HTMLElement>('[data-home-carousel-empty]');
      if (loading) loading.hidden = true;
      if (empty) empty.hidden = false;
    });
  }
};

const scheduleHomeLoad = () => {
  const idle = (window as any).requestIdleCallback;
  if (typeof idle === 'function') idle(loadHome, { timeout: 700 });
  else window.setTimeout(loadHome, 40);
};
if ((window as any).VaultCloud) scheduleHomeLoad();
else window.addEventListener('vault:cloud-ready', scheduleHomeLoad, { once: true });
