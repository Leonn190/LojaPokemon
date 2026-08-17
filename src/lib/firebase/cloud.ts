import { initializeApp, getApps, type FirebaseApp, type FirebaseOptions } from 'firebase/app';
import {
  createUserWithEmailAndPassword,
  deleteUser,
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  updateProfile,
  type User,
} from 'firebase/auth';
import {
  collection,
  deleteDoc,
  doc,
  documentId,
  getDoc,
  getDocs,
  getFirestore,
  query,
  limit as firestoreLimit,
  orderBy,
  startAfter,
  serverTimestamp,
  setDoc,
  where,
  writeBatch,
  type Firestore,
} from 'firebase/firestore';

const PROJECT_DEFAULTS: FirebaseOptions = {
  apiKey: 'AIzaSyAH2-yNZl048tTL57BCq7gdh82YBZH7GmU',
  authDomain: 'nexustcg-ad9d3.firebaseapp.com',
  projectId: 'nexustcg-ad9d3',
  storageBucket: 'nexustcg-ad9d3.firebasestorage.app',
  messagingSenderId: '887970597243',
  appId: '1:887970597243:web:42ac88e0ac7c55eaab95de',
  measurementId: 'G-L4TS4FY89Y',
};

// A configuracao Web do Firebase e publica por design. Variaveis PUBLIC_*
// continuam aceitas como override, mas o Vault funciona no GitHub Pages
// mesmo sem depender de Repository Variables.
const resolvedConfig: FirebaseOptions = {
  apiKey: import.meta.env.PUBLIC_FIREBASE_API_KEY || PROJECT_DEFAULTS.apiKey,
  authDomain: import.meta.env.PUBLIC_FIREBASE_AUTH_DOMAIN || PROJECT_DEFAULTS.authDomain,
  projectId: import.meta.env.PUBLIC_FIREBASE_PROJECT_ID || PROJECT_DEFAULTS.projectId,
  storageBucket: import.meta.env.PUBLIC_FIREBASE_STORAGE_BUCKET || PROJECT_DEFAULTS.storageBucket,
  messagingSenderId: import.meta.env.PUBLIC_FIREBASE_MESSAGING_SENDER_ID || PROJECT_DEFAULTS.messagingSenderId,
  appId: import.meta.env.PUBLIC_FIREBASE_APP_ID || PROJECT_DEFAULTS.appId,
  measurementId: import.meta.env.PUBLIC_FIREBASE_MEASUREMENT_ID || PROJECT_DEFAULTS.measurementId,
};

let servicesPromise: Promise<{ app: FirebaseApp; auth: ReturnType<typeof getAuth>; db: Firestore }> | null = null;

const PUBLIC_MIRROR_VERSION = 2;
const PUBLIC_CACHE_REVALIDATE_AFTER = 30 * 1000;
const PUBLIC_CACHE_PREFIX = 'vault:public-cache:v2:';
const memoryPublicCache = new Map<string, { savedAt: number; data: any }>();
const publicRequests = new Map<string, Promise<any>>();

const readPublicCache = (key: string) => {
  const memory = memoryPublicCache.get(key);
  if (memory) return memory;
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(`${PUBLIC_CACHE_PREFIX}${key}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !Object.prototype.hasOwnProperty.call(parsed, 'data') || !Number.isFinite(Number(parsed.savedAt))) return null;
    const entry = { savedAt: Number(parsed.savedAt), data: parsed.data };
    memoryPublicCache.set(key, entry);
    return entry;
  } catch (_) {
    return null;
  }
};

const writePublicCache = (key: string, data: any) => {
  const entry = { savedAt: Date.now(), data };
  memoryPublicCache.set(key, entry);
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(`${PUBLIC_CACHE_PREFIX}${key}`, JSON.stringify(entry)); } catch (_) {}
};

const clearPublicCache = () => {
  memoryPublicCache.clear();
  publicRequests.clear();
  if (typeof window === 'undefined') return;
  try {
    const keys: string[] = [];
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key?.startsWith(PUBLIC_CACHE_PREFIX)) keys.push(key);
    }
    keys.forEach((key) => window.localStorage.removeItem(key));
  } catch (_) {}
};

const dispatchPublicCacheUpdate = (key: string, data: any) => {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent('vault:public-cache-updated', { detail: { key, data } }));
};

const refreshPublicQuery = async <T>(key: string, loader: () => Promise<T>): Promise<T> => {
  const running = publicRequests.get(key);
  if (running) return running as Promise<T>;
  const request = loader()
    .then((data) => {
      writePublicCache(key, data);
      dispatchPublicCacheUpdate(key, data);
      return data;
    })
    .finally(() => publicRequests.delete(key));
  publicRequests.set(key, request);
  return request;
};

// Catálogos públicos usam cache-first: voltar para uma página é imediato, e
// uma revalidação curta acontece em paralelo quando o cache envelhece.
const cachedPublicQuery = async <T>(key: string, loader: () => Promise<T>): Promise<T> => {
  const cached = readPublicCache(key);
  if (cached) {
    const age = Date.now() - cached.savedAt;
    if (age >= PUBLIC_CACHE_REVALIDATE_AFTER) refreshPublicQuery(key, loader).catch(() => {});
    return cached.data as T;
  }
  return refreshPublicQuery(key, loader);
};

const numberOrNull = (value: any): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const resolvePublicPrice = (item: any, fallback = 'league_average_then_lowest') => {
  const direct = numberOrNull(item?.price);
  if (direct !== null) return direct;
  if (item?.kind !== 'card' && item?.kind !== 'booster') return null;
  if (fallback === 'consult') return null;
  const average = numberOrNull(item?.averageLeaguePrice ?? item?.leagueAverage);
  const lowest = numberOrNull(item?.leaguePrice ?? item?.leagueLowest);
  return fallback === 'league_lowest_then_average' ? (lowest ?? average) : (average ?? lowest);
};

const normalizePublicItem = (item: any, fallback?: string) => {
  const priceDisplayFallback = fallback || item?.priceDisplayFallback || 'league_average_then_lowest';
  return {
    ...item,
    price: resolvePublicPrice(item, priceDisplayFallback),
    imageCandidates: Array.isArray(item?.imageCandidates) ? item.imageCandidates.filter(Boolean) : (item?.image ? [item.image] : []),
  };
};

const resolveConfig = async (): Promise<FirebaseOptions> => {
  if (!resolvedConfig.apiKey || !resolvedConfig.projectId || !resolvedConfig.appId) {
    throw new Error('O serviço de dados não está disponível no momento.');
  }
  return resolvedConfig;
};

export const getCloud = async () => {
  if (!servicesPromise) {
    servicesPromise = (async () => {
      const config = await resolveConfig();
      const app = getApps().length ? getApps()[0] : initializeApp(config);
      return { app, auth: getAuth(app), db: getFirestore(app) };
    })();
  }
  return servicesPromise;
};

export const slugify = (value: unknown) => String(value ?? '')
  .trim()
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-z0-9]+/gi, '-')
  .replace(/(^-|-$)/g, '')
  .toLowerCase() || 'colecao';

const stripUndefined = (value: any): any => {
  if (Array.isArray(value)) return value.map(stripUndefined).filter((entry) => entry !== undefined);
  if (value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, entry]) => entry !== undefined)
        .map(([key, entry]) => [key, stripUndefined(entry)]),
    );
  }
  if (typeof value === 'number' && !Number.isFinite(value)) return null;
  return value;
};

const editorItem = (raw: any, id: string) => ({
  ...raw,
  _id: raw?._id || raw?.id || raw?.albumId || id,
  _isNew: false,
  _isDirty: false,
});

const toStoredItem = (item: any) => {
  const clean = { ...item };
  Object.keys(clean).forEach((key) => {
    if (key.startsWith('_')) delete clean[key];
  });
  clean.id = item?._id || item?.id || item?.albumId || clean.id;
  return stripUndefined(clean);
};

const profileForFirestore = (profile: any, uid: string) => stripUndefined({
  ownerUid: uid,
  slug: profile.collectionId || profile.slug || 'colecao',
  owner: profile.owner || '',
  title: profile.title || 'Minha coleção',
  description: profile.description || '',
  phone: profile.phone || '',
  public: profile.public === true,
  selling: profile.selling !== false,
  featured: profile.featured === true,
  showQuantity: false,
  showCollectionValue: profile.showCollectionValue !== false,
  profilePhoto: profile.profilePhoto || '',
  profileBanner: profile.profileBanner || '',
  palette: Array.isArray(profile.palette) ? profile.palette.slice(0, 3) : ['#54e8df', '#bc91ff', '#f4c25c'],
  priceDisplayFallback: profile.priceDisplayFallback || 'league_average_then_lowest',
  proposalTerms: profile.proposalTerms || { policy: 'flexible', flexibleDiscounts: true, discountTiers: [] },
  version: Number(profile.version || 1),
  mirrorVersion: PUBLIC_MIRROR_VERSION,
  stats: profile.stats || {},
  previewCards: Array.isArray(profile.previewCards) ? profile.previewCards.slice(0, 8) : [],
  updatedAt: serverTimestamp(),
});

const publicMirror = (item: any, kind: string, profile: any, uid: string) => {
  const stored = toStoredItem(item);
  // Dados de depuração e históricos pesados não são necessários no catálogo público.
  delete stored.advancedData;
  delete stored.priceHistory;
  const priceDisplayFallback = profile.priceDisplayFallback || 'league_average_then_lowest';
  return stripUndefined({
    ...stored,
    kind,
    price: resolvePublicPrice({ ...stored, kind }, priceDisplayFallback),
    priceDisplayFallback,
    mirrorVersion: PUBLIC_MIRROR_VERSION,
    ownerUid: uid,
    collectionUid: uid,
    collectionSlug: profile.collectionId || profile.slug || '',
    ownerName: profile.owner || '',
    ownerCollectionName: profile.title || '',
    ownerCollectionSlug: profile.collectionId || profile.slug || '',
    ownerPhone: profile.phone || '',
    proposalTerms: profile.proposalTerms || { policy: 'flexible', flexibleDiscounts: true, discountTiers: [] },
    showQuantity: false,
    forSale: profile.selling !== false && item.forSale !== false,
    public: true,
    updatedAt: serverTimestamp(),
  });
};

const itemKey = (uid: string, kind: string, id: string) => `${uid}__${kind}__${encodeURIComponent(id).replace(/%/g, '_')}`.slice(0, 1450);

const buildStats = (state: any) => {
  const cards = state?.cards || [];
  const boosters = state?.boosters || [];
  const kits = state?.kits || [];
  const products = state?.products || [];
  const albums = state?.albums || [];
  const totalUnits = [...cards, ...boosters, ...kits, ...products].reduce((sum, item) => sum + Math.max(0, Number(item.quantity || 0)), 0);
  const estimatedValue = [...cards, ...boosters, ...kits, ...products].reduce((sum, item) => {
    const price = item.price ?? item.leaguePrice ?? 0;
    return sum + Math.max(0, Number(item.quantity || 0)) * Math.max(0, Number(price || 0));
  }, 0);
  return { cards: cards.length, boosters: boosters.length, kits: kits.length, products: products.length, albums: albums.length, totalUnits, estimatedValue };
};

const findAvailableSlug = async (db: Firestore, baseSlug: string) => {
  const base = slugify(baseSlug);
  for (let suffix = 0; suffix < 50; suffix += 1) {
    const candidate = suffix === 0 ? base : `${base}-${suffix + 1}`;
    const snapshot = await getDoc(doc(db, 'slugs', candidate));
    if (!snapshot.exists()) return candidate;
  }
  return `${base}-${Date.now().toString(36)}`;
};

export async function createAccountWithCollection(input: {
  email: string;
  password: string;
  owner: string;
  title: string;
  description?: string;
  phone?: string;
  isPublic?: boolean;
  selling?: boolean;
  proposalTerms?: any;
}) {
  const { auth, db } = await getCloud();
  const credential = await createUserWithEmailAndPassword(auth, input.email.trim(), input.password);
  try {
    await updateProfile(credential.user, { displayName: input.owner.trim() });
    const uid = credential.user.uid;
    const slug = await findAvailableSlug(db, input.title);
    const profile = {
      collectionId: slug,
      slug,
      owner: input.owner.trim(),
      title: input.title.trim() || 'Minha coleção',
      description: input.description?.trim() || '',
      email: input.email.trim().toLowerCase(),
      phone: input.phone?.trim() || '',
      public: input.isPublic === true,
      selling: input.selling !== false,
      featured: false,
      showQuantity: false,
      showCollectionValue: true,
      profilePhoto: '',
      profileBanner: '',
      palette: ['#54e8df', '#bc91ff', '#f4c25c'],
      priceDisplayFallback: 'league_average_then_lowest',
      proposalTerms: input.proposalTerms || { policy: 'flexible', flexibleDiscounts: true, discountTiers: [] },
      version: 1,
      stats: { cards: 0, boosters: 0, kits: 0, products: 0, albums: 0, totalUnits: 0, estimatedValue: 0 },
    };
    const batch = writeBatch(db);
    batch.set(doc(db, 'users', uid), {
      displayName: profile.owner,
      email: profile.email,
      collectionSlug: slug,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });
    batch.set(doc(db, 'collections', uid), { ...profileForFirestore(profile, uid), createdAt: serverTimestamp() });
    batch.set(doc(db, 'slugs', slug), { ownerUid: uid, collectionUid: uid, slug, createdAt: serverTimestamp() });
    await batch.commit();
    clearPublicCache();
    return { user: credential.user, profile };
  } catch (error) {
    try { await deleteUser(credential.user); } catch (_) {}
    throw error;
  }
}

export async function signIn(email: string, password: string) {
  const { auth } = await getCloud();
  return signInWithEmailAndPassword(auth, email.trim(), password);
}

export async function signOut() {
  const { auth } = await getCloud();
  return firebaseSignOut(auth);
}

export async function currentUser(): Promise<User | null> {
  const { auth } = await getCloud();
  if (auth.currentUser) return auth.currentUser;
  return new Promise((resolve) => {
    let unsubscribe = () => {};
    unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      resolve(user);
    }, () => {
      unsubscribe();
      resolve(null);
    });
  });
}

export async function watchAuth(callback: (user: User | null) => void) {
  const { auth } = await getCloud();
  return onAuthStateChanged(auth, callback);
}

const readSubcollection = async (db: Firestore, uid: string, name: string) => {
  const snapshot = await getDocs(collection(db, 'collections', uid, name));
  return snapshot.docs.map((item) => editorItem(item.data(), item.id));
};

export async function loadMyCollection(user?: User | null) {
  const { auth, db } = await getCloud();
  const active = user || auth.currentUser;
  if (!active) return null;
  const uid = active.uid;
  const collectionRef = doc(db, 'collections', uid);
  let snapshot = await getDoc(collectionRef);
  if (!snapshot.exists()) {
    const slug = await findAvailableSlug(db, active.displayName || active.email?.split('@')[0] || 'colecao');
    const profile = {
      collectionId: slug,
      owner: active.displayName || active.email?.split('@')[0] || 'Colecionador',
      title: `Coleção de ${active.displayName || active.email?.split('@')[0] || 'colecionador'}`,
      email: active.email || '',
      public: false,
      selling: false,
      showCollectionValue: true,
      profileBanner: '',
      version: 1,
      stats: { cards: 0, boosters: 0, kits: 0, products: 0, albums: 0, totalUnits: 0, estimatedValue: 0 },
    };
    const batch = writeBatch(db);
    batch.set(collectionRef, { ...profileForFirestore(profile, uid), createdAt: serverTimestamp() });
    batch.set(doc(db, 'users', uid), { displayName: profile.owner, email: profile.email, collectionSlug: slug, createdAt: serverTimestamp(), updatedAt: serverTimestamp() }, { merge: true });
    batch.set(doc(db, 'slugs', slug), { ownerUid: uid, collectionUid: uid, slug, createdAt: serverTimestamp() });
    await batch.commit();
    snapshot = await getDoc(collectionRef);
  }
  const data = snapshot.data() || {};
  const [cards, boosters, kits, products, albums, movements] = await Promise.all([
    readSubcollection(db, uid, 'cards'),
    readSubcollection(db, uid, 'boosters'),
    readSubcollection(db, uid, 'kits'),
    readSubcollection(db, uid, 'products'),
    readSubcollection(db, uid, 'albums'),
    readSubcollection(db, uid, 'movements'),
  ]);
  const profile = {
    ...data,
    ownerUid: uid,
    collectionId: data.slug || data.collectionId || uid,
    email: active.email || data.email || '',
    password: '',
    version: Number(data.version || 1),
  };
  return { profile, cards, boosters, kits, products, albums, movements };
}

const commitOperations = async (db: Firestore, operations: Array<(batch: ReturnType<typeof writeBatch>) => void>) => {
  for (let offset = 0; offset < operations.length; offset += 350) {
    const batch = writeBatch(db);
    operations.slice(offset, offset + 350).forEach((operation) => operation(batch));
    await batch.commit();
  }
};

export async function saveEditorState(state: any, options: { profileDirty?: boolean; privacyDirty?: boolean; mirrorDirty?: boolean } = {}) {
  const { auth, db } = await getCloud();
  const user = auth.currentUser;
  if (!user) throw new Error('Sua sessão expirou. Entre novamente.');
  const uid = user.uid;
  const mirrorUpgrade = Number(state.profile?.mirrorVersion || 0) < PUBLIC_MIRROR_VERSION;
  state.profile.mirrorVersion = PUBLIC_MIRROR_VERSION;
  state.profile.stats = buildStats(state);
  state.profile.previewCards = (state.cards || []).slice(0, 8).map((card: any) => stripUndefined({
    name: card.name || 'Carta',
    number: card.number || '',
    rarity: card.rarity || card.type || '',
    type: card.type || '',
    price: resolvePublicPrice({ ...card, kind: 'card' }, state.profile.priceDisplayFallback),
    leaguePrice: numberOrNull(card.leaguePrice),
    imageCandidates: Array.isArray(card.imageCandidates) ? card.imageCandidates.filter(Boolean).slice(0, 5) : (card.image ? [card.image] : []),
  }));
  state.profile.email = user.email || state.profile.email || '';
  state.profile.ownerUid = uid;
  const operations: Array<(batch: ReturnType<typeof writeBatch>) => void> = [];
  operations.push((batch) => batch.set(doc(db, 'collections', uid), profileForFirestore(state.profile, uid), { merge: true }));
  if (options.profileDirty === true) {
    operations.push((batch) => batch.set(doc(db, 'users', uid), {
      displayName: state.profile.owner || user.displayName || '',
      email: user.email || '',
      collectionSlug: state.profile.collectionId,
      updatedAt: serverTimestamp(),
    }, { merge: true }));
  }

  const kinds = ['cards', 'boosters', 'kits', 'products', 'albums'] as const;
  for (const kind of kinds) {
    const singularKind = kind === 'cards' ? 'card' : kind === 'boosters' ? 'booster' : kind === 'kits' ? 'kit' : kind === 'products' ? 'product' : 'album';
    const items = state[kind] || [];
    items.forEach((item: any) => {
      const itemChanged = item._isNew || item._isDirty;
      const mirrorNeedsRefresh = itemChanged || mirrorUpgrade || options.mirrorDirty === true || options.privacyDirty === true;
      if (!itemChanged && !mirrorNeedsRefresh) return;
      const id = String(item._id || item.id || item.albumId || crypto.randomUUID());
      item._id = id;
      if (itemChanged) {
        const stored = toStoredItem(item);
        operations.push((batch) => batch.set(doc(db, 'collections', uid, kind, id), stored, { merge: true }));
      }
      const mirrorCollection = kind === 'albums' ? 'publicAlbums' : 'publicItems';
      const mirrorRef = doc(db, mirrorCollection, itemKey(uid, singularKind, id));
      if (state.profile.public === true && mirrorNeedsRefresh) {
        operations.push((batch) => batch.set(mirrorRef, publicMirror(item, singularKind, state.profile, uid), { merge: true }));
      } else if (options.privacyDirty === true && !item._isNew) {
        operations.push((batch) => batch.delete(mirrorRef));
      }
    });

    for (const removed of state.removed?.[kind] || []) {
      const id = String(removed.Id || removed.id || removed._id || removed.albumId || '');
      if (!id) continue;
      operations.push((batch) => batch.delete(doc(db, 'collections', uid, kind, id)));
      const mirrorCollection = kind === 'albums' ? 'publicAlbums' : 'publicItems';
      operations.push((batch) => batch.delete(doc(db, mirrorCollection, itemKey(uid, singularKind, id))));
    }
  }

  for (const movement of state.pendingMovements || []) {
    const id = String(movement.eventId || movement._id || crypto.randomUUID());
    movement.eventId = id;
    operations.push((batch) => batch.set(doc(db, 'collections', uid, 'movements', id), toStoredItem(movement), { merge: true }));
  }

  await commitOperations(db, operations);
  clearPublicCache();
  for (const kind of kinds) (state[kind] || []).forEach((item: any) => { item._isNew = false; item._isDirty = false; });
  state.movements = [...(state.movements || []), ...(state.pendingMovements || [])];
  state.pendingMovements = [];
  state.removed = { cards: [], boosters: [], kits: [], products: [], albums: [] };
  return state;
}

export type PublicPage<T = any> = {
  items: T[];
  nextCursor: string | null;
  hasMore: boolean;
};

const pageSize = (value?: number, fallback = 24) => Math.min(80, Math.max(1, Math.floor(Number(value) || fallback)));
const pageCacheKey = (scope: string, cursor?: string | null, size?: number) => `${scope}:page:${size || 24}:${cursor || 'first'}`;

export async function listPublicCollections() {
  return cachedPublicQuery('collections', async () => {
    const { db } = await getCloud();
    const snapshot = await getDocs(query(collection(db, 'collections'), where('public', '==', true)));
    return snapshot.docs.map((entry) => ({ uid: entry.id, ...entry.data() }));
  });
}

export async function listPublicCollectionsPage(maxResults = 18, cursor?: string | null): Promise<PublicPage<any>> {
  const size = pageSize(maxResults, 18);
  const key = pageCacheKey('collections', cursor, size);
  return cachedPublicQuery(key, async () => {
    const { db } = await getCloud();
    const constraints: any[] = [where('public', '==', true), orderBy(documentId()), firestoreLimit(size)];
    if (cursor) constraints.splice(2, 0, startAfter(cursor));
    const snapshot = await getDocs(query(collection(db, 'collections'), ...constraints));
    const items = snapshot.docs.map((entry) => ({ uid: entry.id, ...entry.data() }));
    return { items, nextCursor: snapshot.docs[snapshot.docs.length - 1]?.id || null, hasMore: snapshot.size === size };
  });
}

export async function listPublicItems(kind?: string, maxResults?: number) {
  const normalizedKind = kind || 'all';
  const normalizedLimit = maxResults && maxResults > 0 ? Math.max(1, Math.floor(maxResults)) : 0;
  const cacheKey = `items:${normalizedKind}:${normalizedLimit || 'all'}`;
  return cachedPublicQuery(cacheKey, async () => {
    const { db } = await getCloud();
    const baseQuery = kind
      ? query(collection(db, 'publicItems'), where('kind', '==', kind))
      : query(collection(db, 'publicItems'));
    const source = normalizedLimit ? query(baseQuery, firestoreLimit(normalizedLimit)) : baseQuery;
    const snapshot = await getDocs(source);
    return snapshot.docs.map((entry) => normalizePublicItem({ _docId: entry.id, ...entry.data() }));
  });
}

export async function listPublicItemsPage(kind: string, maxResults = 24, cursor?: string | null): Promise<PublicPage<any>> {
  const size = pageSize(maxResults, 24);
  const key = pageCacheKey(`items:${kind}`, cursor, size);
  return cachedPublicQuery(key, async () => {
    const { db } = await getCloud();
    const constraints: any[] = [where('kind', '==', kind), orderBy(documentId()), firestoreLimit(size)];
    if (cursor) constraints.splice(2, 0, startAfter(cursor));
    const snapshot = await getDocs(query(collection(db, 'publicItems'), ...constraints));
    const items = snapshot.docs.map((entry) => normalizePublicItem({ _docId: entry.id, ...entry.data() }));
    return { items, nextCursor: snapshot.docs[snapshot.docs.length - 1]?.id || null, hasMore: snapshot.size === size };
  });
}

export async function listPublicCollectionPreview(collectionUid: string, maxResults = 8) {
  const uid = String(collectionUid || '').trim();
  if (!uid) return [];
  const size = pageSize(maxResults, 8);
  return cachedPublicQuery(`collection-preview:${uid}:${size}`, async () => {
    const { db } = await getCloud();
    const snapshot = await getDocs(query(
      collection(db, 'publicItems'),
      where('collectionUid', '==', uid),
      where('kind', '==', 'card'),
      firestoreLimit(size),
    ));
    return snapshot.docs.map((entry) => normalizePublicItem({ _docId: entry.id, ...entry.data() }));
  });
}

export async function listPublicAlbums() {
  return cachedPublicQuery('albums', async () => {
    const { db } = await getCloud();
    const snapshot = await getDocs(collection(db, 'publicAlbums'));
    return snapshot.docs.map((entry) => ({ _docId: entry.id, ...entry.data() }));
  });
}

export async function listPublicAlbumsPage(maxResults = 18, cursor?: string | null): Promise<PublicPage<any>> {
  const size = pageSize(maxResults, 18);
  const key = pageCacheKey('albums', cursor, size);
  return cachedPublicQuery(key, async () => {
    const { db } = await getCloud();
    const constraints: any[] = [orderBy(documentId()), firestoreLimit(size)];
    if (cursor) constraints.splice(1, 0, startAfter(cursor));
    const snapshot = await getDocs(query(collection(db, 'publicAlbums'), ...constraints));
    const items = snapshot.docs.map((entry) => ({ _docId: entry.id, ...entry.data() }));
    return { items, nextCursor: snapshot.docs[snapshot.docs.length - 1]?.id || null, hasMore: snapshot.size === size };
  });
}

export async function loadCollectionBySlug(slug: string) {
  const { auth, db } = await getCloud();
  const slugSnapshot = await getDoc(doc(db, 'slugs', slugify(slug)));
  if (!slugSnapshot.exists()) return null;
  const uid = String(slugSnapshot.data().collectionUid || slugSnapshot.data().ownerUid || '');
  if (!uid) return null;
  let collectionSnapshot;
  try {
    collectionSnapshot = await getDoc(doc(db, 'collections', uid));
  } catch (error: any) {
    if (String(error?.code || '').includes('permission-denied')) throw new Error('Esta coleção é privada.');
    throw error;
  }
  if (!collectionSnapshot.exists()) return null;
  const profile = { uid, ...collectionSnapshot.data(), collectionId: collectionSnapshot.data().slug || slug } as any;
  if (profile.public !== true && auth.currentUser?.uid !== uid) throw new Error('Esta coleção é privada.');
  const viewingOwnCollection = auth.currentUser?.uid === uid;
  if (!viewingOwnCollection) {
    const [itemSnapshot, albumSnapshot] = await Promise.all([
      getDocs(query(collection(db, 'publicItems'), where('collectionUid', '==', uid))),
      getDocs(query(collection(db, 'publicAlbums'), where('collectionUid', '==', uid))),
    ]);
    const publicItems = itemSnapshot.docs.map((entry) => normalizePublicItem({ _docId: entry.id, ...entry.data() } as any, profile.priceDisplayFallback));
    const publicAlbums = albumSnapshot.docs.map((entry) => ({ _docId: entry.id, ...entry.data() } as any));
    return {
      profile,
      cards: publicItems.filter((item) => item.kind === 'card'),
      boosters: publicItems.filter((item) => item.kind === 'booster'),
      kits: publicItems.filter((item) => item.kind === 'kit'),
      products: publicItems.filter((item) => item.kind === 'product'),
      albums: publicAlbums,
    };
  }

  const [cards, boosters, kits, products, albums] = await Promise.all([
    readSubcollection(db, uid, 'cards'),
    readSubcollection(db, uid, 'boosters'),
    readSubcollection(db, uid, 'kits'),
    readSubcollection(db, uid, 'products'),
    readSubcollection(db, uid, 'albums'),
  ]);
  const addOwner = (item: any, kind: string) => ({
    ...item,
    kind,
    price: resolvePublicPrice({ ...item, kind }, profile.priceDisplayFallback || 'league_average_then_lowest'),
    ownerUid: uid,
    ownerName: profile.owner || '',
    ownerCollectionName: profile.title || '',
    ownerCollectionSlug: profile.slug || slug,
    ownerPhone: profile.phone || '',
    proposalTerms: profile.proposalTerms || { policy: 'flexible', flexibleDiscounts: true, discountTiers: [] },
    showQuantity: false,
    forSale: profile.selling !== false && item.forSale !== false,
  });
  return {
    profile,
    cards: cards.map((item) => addOwner(item, 'card')),
    boosters: boosters.map((item) => addOwner(item, 'booster')),
    kits: kits.map((item) => addOwner(item, 'kit')),
    products: products.map((item) => addOwner(item, 'product')),
    albums: albums.map((item) => addOwner(item, 'album')),
  };
}

export async function listMyReceivedProposals(maxResults = 60) {
  const { auth, db } = await getCloud();
  const user = auth.currentUser;
  if (!user) return [];
  const size = Math.min(100, Math.max(1, Math.floor(Number(maxResults) || 60)));
  const snapshot = await getDocs(query(collection(db, 'proposals'), where('sellerUid', '==', user.uid), firestoreLimit(size)));
  return snapshot.docs.map((entry) => ({ id: entry.id, ...entry.data() })).sort((left: any, right: any) => {
    const time = (value: any) => Number(value?.toMillis?.() || value?.seconds * 1000 || new Date(value || 0).getTime() || 0);
    return time(right.createdAt) - time(left.createdAt);
  });
}

export async function submitProposal(group: any) {
  const { auth, db } = await getCloud();
  const user = auth.currentUser;
  if (!user) throw new Error('Entre na sua conta para enviar propostas.');
  const sellerUid = String(group?.ownerUid || '');
  if (!sellerUid) throw new Error('Esta coleção não está disponível para propostas no momento.');
  if (sellerUid === user.uid) throw new Error('Você não pode enviar proposta para a própria coleção.');
  const buyerSnapshot = await getDoc(doc(db, 'users', user.uid));
  const buyer = buyerSnapshot.exists() ? buyerSnapshot.data() : {};
  const proposalRef = doc(collection(db, 'proposals'));
  await setDoc(proposalRef, stripUndefined({
    buyerUid: user.uid,
    buyerEmail: user.email || '',
    buyerAccountName: buyer.displayName || user.displayName || '',
    sellerUid,
    sellerCollectionSlug: group.ownerSlug || '',
    sellerCollectionName: group.ownerCollection || '',
    sellerName: group.owner || '',
    items: (group.items || []).map((item: any) => ({
      id: item.id || '', kind: item.kind || '', name: item.name || '', number: item.number || '', quantity: Number(item.quantity || 1), price: Number.isFinite(item.price) ? item.price : null,
    })),
    publishedTotal: Number(group.publishedTotal || 0),
    discount: Number(group.discount || 0),
    proposedTotal: Number(group.proposedTotal || 0),
    reason: group.reason || '',
    buyerName: group.buyerName || '',
    address: group.address || '',
    status: 'pending',
    createdAt: serverTimestamp(),
    updatedAt: serverTimestamp(),
  }));
  return proposalRef.id;
}

export function friendlyFirebaseError(error: any) {
  const code = String(error?.code || '');
  const map: Record<string, string> = {
    'auth/email-already-in-use': 'Este e-mail já possui uma conta. Entre com sua senha.',
    'auth/invalid-email': 'O e-mail informado não é válido.',
    'auth/weak-password': 'Use uma senha mais forte, com pelo menos 6 caracteres.',
    'auth/invalid-credential': 'E-mail ou senha incorretos.',
    'auth/user-disabled': 'Esta conta foi desativada.',
    'auth/too-many-requests': 'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
    'permission-denied': 'Você não tem permissão para concluir esta operação.',
    'firestore/permission-denied': 'Você não tem permissão para concluir esta operação.',
  };
  return map[code] || error?.message || 'Não foi possível concluir a operação agora.';
}
