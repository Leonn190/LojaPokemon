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
  getDoc,
  getDocs,
  getFirestore,
  query,
  limit as firestoreLimit,
  serverTimestamp,
  setDoc,
  where,
  writeBatch,
  type Firestore,
} from 'firebase/firestore';

const PROJECT_DEFAULTS: Partial<FirebaseOptions> = {
  authDomain: 'nexustcg-ad9d3.firebaseapp.com',
  projectId: 'nexustcg-ad9d3',
  storageBucket: 'nexustcg-ad9d3.firebasestorage.app',
  messagingSenderId: '887970597243',
  appId: '1:887970597243:web:42ac88e0ac7c55eaab95de',
};

const envConfig: FirebaseOptions = {
  apiKey: import.meta.env.PUBLIC_FIREBASE_API_KEY || '',
  authDomain: import.meta.env.PUBLIC_FIREBASE_AUTH_DOMAIN || PROJECT_DEFAULTS.authDomain || '',
  projectId: import.meta.env.PUBLIC_FIREBASE_PROJECT_ID || PROJECT_DEFAULTS.projectId || '',
  storageBucket: import.meta.env.PUBLIC_FIREBASE_STORAGE_BUCKET || PROJECT_DEFAULTS.storageBucket || '',
  messagingSenderId: import.meta.env.PUBLIC_FIREBASE_MESSAGING_SENDER_ID || PROJECT_DEFAULTS.messagingSenderId || '',
  appId: import.meta.env.PUBLIC_FIREBASE_APP_ID || PROJECT_DEFAULTS.appId || '',
};

let servicesPromise: Promise<{ app: FirebaseApp; auth: ReturnType<typeof getAuth>; db: Firestore }> | null = null;

const loadHostingConfig = async (): Promise<FirebaseOptions | null> => {
  if (typeof window === 'undefined') return null;
  try {
    const response = await fetch('/__/firebase/init.json', { cache: 'no-store' });
    if (!response.ok) return null;
    const data = await response.json();
    return data && data.apiKey ? data : null;
  } catch (_) {
    return null;
  }
};

const resolveConfig = async (): Promise<FirebaseOptions> => {
  if (envConfig.apiKey) return envConfig;
  const hosting = await loadHostingConfig();
  if (hosting?.apiKey) return { ...PROJECT_DEFAULTS, ...hosting } as FirebaseOptions;
  throw new Error(
    'Firebase ainda não recebeu a API key do app Web. Defina PUBLIC_FIREBASE_API_KEY ou publique pelo Firebase Hosting, que fornece /__/firebase/init.json automaticamente.',
  );
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
  showQuantity: profile.showQuantity !== false,
  profilePhoto: profile.profilePhoto || '',
  palette: Array.isArray(profile.palette) ? profile.palette.slice(0, 3) : ['#54e8df', '#bc91ff', '#f4c25c'],
  priceDisplayFallback: profile.priceDisplayFallback || 'league_average_then_lowest',
  proposalTerms: profile.proposalTerms || { policy: 'flexible', flexibleDiscounts: true, discountTiers: [] },
  version: Number(profile.version || 1),
  stats: profile.stats || {},
  updatedAt: serverTimestamp(),
});

const publicMirror = (item: any, kind: string, profile: any, uid: string) => stripUndefined({
  ...toStoredItem(item),
  kind,
  ownerUid: uid,
  collectionUid: uid,
  collectionSlug: profile.collectionId || profile.slug || '',
  ownerName: profile.owner || '',
  ownerCollectionName: profile.title || '',
  ownerCollectionSlug: profile.collectionId || profile.slug || '',
  ownerPhone: profile.phone || '',
  proposalTerms: profile.proposalTerms || { policy: 'flexible', flexibleDiscounts: true, discountTiers: [] },
  showQuantity: profile.showQuantity !== false,
  forSale: profile.selling !== false && item.forSale !== false,
  public: true,
  updatedAt: serverTimestamp(),
});

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
      showQuantity: true,
      profilePhoto: '',
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
  state.profile.stats = buildStats(state);
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
      const mirrorNeedsRefresh = itemChanged || options.mirrorDirty === true || options.privacyDirty === true;
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
  for (const kind of kinds) (state[kind] || []).forEach((item: any) => { item._isNew = false; item._isDirty = false; });
  state.movements = [...(state.movements || []), ...(state.pendingMovements || [])];
  state.pendingMovements = [];
  state.removed = { cards: [], boosters: [], kits: [], products: [], albums: [] };
  return state;
}

export async function listPublicCollections() {
  const { db } = await getCloud();
  const snapshot = await getDocs(query(collection(db, 'collections'), where('public', '==', true)));
  return snapshot.docs.map((entry) => ({ uid: entry.id, ...entry.data() }));
}

export async function listPublicItems(kind?: string, maxResults?: number) {
  const { db } = await getCloud();
  const baseQuery = kind
    ? query(collection(db, 'publicItems'), where('kind', '==', kind))
    : query(collection(db, 'publicItems'));
  const source = maxResults && maxResults > 0
    ? query(baseQuery, firestoreLimit(Math.max(1, Math.floor(maxResults))))
    : baseQuery;
  const snapshot = await getDocs(source);
  return snapshot.docs.map((entry) => ({ _docId: entry.id, ...entry.data() }));
}

export async function listPublicAlbums() {
  const { db } = await getCloud();
  const snapshot = await getDocs(collection(db, 'publicAlbums'));
  return snapshot.docs.map((entry) => ({ _docId: entry.id, ...entry.data() }));
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
    const publicItems = itemSnapshot.docs.map((entry) => ({ _docId: entry.id, ...entry.data() } as any));
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
    ownerUid: uid,
    ownerName: profile.owner || '',
    ownerCollectionName: profile.title || '',
    ownerCollectionSlug: profile.slug || slug,
    ownerPhone: profile.phone || '',
    proposalTerms: profile.proposalTerms || { policy: 'flexible', flexibleDiscounts: true, discountTiers: [] },
    showQuantity: profile.showQuantity !== false,
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

export async function submitProposal(group: any) {
  const { auth, db } = await getCloud();
  const user = auth.currentUser;
  if (!user) throw new Error('Entre na sua conta para enviar propostas.');
  const sellerUid = String(group?.ownerUid || '');
  if (!sellerUid) throw new Error('Esta coleção ainda não foi migrada para o sistema online.');
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
    'permission-denied': 'O Firebase bloqueou esta operação pelas regras de segurança.',
    'firestore/permission-denied': 'O Firebase bloqueou esta operação pelas regras de segurança.',
  };
  return map[code] || error?.message || 'Não foi possível concluir a operação agora.';
}
