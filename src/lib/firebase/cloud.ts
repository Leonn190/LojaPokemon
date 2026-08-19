import { initializeApp, getApps, type FirebaseApp, type FirebaseOptions } from 'firebase/app';
import {
  createUserWithEmailAndPassword,
  deleteUser,
  getAuth,
  onAuthStateChanged,
  reload,
  sendPasswordResetEmail as firebaseSendPasswordResetEmail,
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
  runTransaction,
  startAfter,
  serverTimestamp,
  setDoc,
  where,
  writeBatch,
  type Firestore,
} from 'firebase/firestore';


const configuredVaultApiUrl = String(import.meta.env.PUBLIC_VAULT_API_URL || '').trim();
const VAULT_API_URL = String(
  configuredVaultApiUrl && !/vault-tcg-myp-api-leonn190\.onrender\.com/i.test(configuredVaultApiUrl)
    ? configuredVaultApiUrl
    : 'https://vaulttcgsiteapi.onrender.com',
).replace(/\/+$/, '');

type VaultApiInit = RequestInit & {
  timeoutMs?: number;
  retries?: number;
};

const friendlyApiMessage = (error: any, fallback = 'Não foi possível concluir a operação agora.') => {
  const code = String(error?.code || '');
  const status = Number(error?.status || 0);
  const map: Record<string, string> = {
    AUTH_REQUIRED: 'Sua sessão expirou. Entre novamente.',
    AUTH_EXPIRED: 'Sua sessão expirou. Entre novamente.',
    MYP_TIMEOUT: 'A MYP demorou demais para responder. Tente novamente em alguns segundos.',
    MYP_NETWORK_ERROR: 'Não foi possível consultar a MYP agora. Tente novamente em alguns segundos.',
    MYP_PARSE_FAILED: 'A MYP respondeu, mas não foi possível identificar os dados desta carta.',
    MYP_NOT_FOUND: 'Esta carta não foi encontrada na MYP.',
    MYP_RATE_LIMIT: 'A MYP limitou temporariamente as consultas. Tente novamente em alguns segundos.',
    MYP_ACCESS_DENIED: 'A MYP recusou temporariamente a consulta direta do servidor. Tente novamente em alguns segundos.',
    MYP_FALLBACK_RATE_LIMIT: 'A rota alternativa da MYP atingiu o limite temporário. Aguarde alguns segundos e tente novamente.',
    MYP_FALLBACK_FAILED: 'A rota alternativa da MYP também não respondeu. Tente novamente em alguns segundos.',
    MYP_FALLBACK_INCOMPLETE: 'A rota alternativa da MYP retornou uma página incompleta.',
    MYP_FALLBACK_PARSE_FAILED: 'A rota alternativa recebeu a MYP, mas não conseguiu identificar esta carta.',
    MYP_NO_PRICE: 'A MYP identificou a carta, mas não trouxe nenhum preço disponível agora.',
    MYP_INVALID_URL: 'Cole um link válido de produto da MYP.',
    EMAIL_NOT_VERIFIED: 'Verifique seu Gmail antes de solicitar a alteração de senha.',
    EMAIL_COOLDOWN: 'Aguarde um pouco antes de solicitar outro e-mail.',
    GMAIL_NOT_CONFIGURED: 'O envio de e-mails do Vault ainda não está configurado no servidor.',
    VAULT_PLUS_REQUIRED: 'A cotização geral da coleção é um recurso do Vault+.',
    VAULT_PLUS_INACTIVE: 'Seu Vault+ não está ativo no momento.',
    VAULT_PLUS_EXPIRED: 'Seu Vault+ expirou.',
    VAULT_PLUS_LIMIT_REACHED: 'Você utilizou suas 2 cotizações desta semana.',
    VAULT_PLUS_WEEKLY_LIMIT: 'Você utilizou suas 2 cotizações desta semana.',
    BULK_QUOTE_EMPTY: 'Nenhuma carta da sua coleção corresponde aos filtros escolhidos.',
    NO_MATCHING_CARDS: 'Nenhuma carta da sua coleção corresponde aos filtros escolhidos.',
    JOB_NOT_FOUND: 'Esta cotização não foi encontrada ou já não está disponível.',
    QUOTE_NOT_FOUND: 'Esta cotização não foi encontrada ou já não está disponível.',
    QUOTE_FORBIDDEN: 'Esta cotização pertence a outra conta.',
    TOO_MANY_CARDS: 'Há cartas demais selecionadas para uma única cotização. Ajuste os filtros e tente novamente.',
    PROPOSALS_DISABLED: 'Esta coleção não está aceitando propostas no momento.',
    PROPOSAL_REQUIRES_MULTIPLE: 'Os termos desta coleção exigem pelo menos dois produtos diferentes.',
    PROPOSAL_NOT_FOUND: 'Esta proposta não foi encontrada.',
    PROPOSAL_FORBIDDEN: 'Você não participa desta proposta.',
    PROPOSAL_ALREADY_FINISHED: 'Esta negociação já foi finalizada.',
    PROPOSAL_NOT_YOUR_TURN: 'Aguardando a resposta da outra pessoa.',
    PROPOSAL_AMOUNT_INVALID: 'Informe um valor válido para a proposta.',
    FIREBASE_ADMIN_NOT_CONFIGURED: 'O Firebase Admin do servidor não está configurado no Render.',
    FIREBASE_SERVICE_ACCOUNT_INVALID: 'A conta de serviço Firebase configurada no Render é inválida.',
    FIREBASE_SERVICE_ACCOUNT_INCOMPLETE: 'As credenciais Firebase do Render estão incompletas.',
    FIREBASE_PROJECT_MISMATCH: 'O frontend e o backend estão usando projetos Firebase diferentes.',
  };
  if (map[code]) return map[code];
  if (status === 401) return 'Sua sessão expirou. Entre novamente.';
  if (status === 429) return 'Muitas solicitações em sequência. Aguarde um pouco e tente novamente.';
  if (status >= 500) return 'Não foi possível conectar ao servidor do Vault. Tente novamente em alguns segundos.';
  const message = String(error?.message || '').trim();
  if (!message || /failed to fetch/i.test(message) || /networkerror/i.test(message)) {
    return 'Não foi possível conectar ao servidor do Vault. Tente novamente em alguns segundos.';
  }
  return message || fallback;
};

const vaultApiFetch = async (path: string, init: VaultApiInit = {}) => {
  const { timeoutMs = 30000, retries = 0, ...fetchInit } = init;
  let lastError: any = null;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), Math.max(1000, timeoutMs));
    const externalSignal = fetchInit.signal;
    const forwardAbort = () => controller.abort();
    if (externalSignal) {
      if (externalSignal.aborted) controller.abort();
      else externalSignal.addEventListener('abort', forwardAbort, { once: true });
    }

    try {
      const response = await fetch(`${VAULT_API_URL}${path}`, {
        ...fetchInit,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          ...(fetchInit.body ? { 'Content-Type': 'application/json' } : {}),
          ...(fetchInit.headers || {}),
        },
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || payload?.ok === false) {
        const error: any = new Error(payload?.error || `A API do Vault respondeu HTTP ${response.status}.`);
        error.status = response.status;
        error.code = payload?.code || '';
        error.retryAfter = payload?.retryAfter;
        error.nextResetDate = payload?.nextResetDate;
        const retryable = [502, 503, 504].includes(response.status);
        if (retryable && attempt < retries) {
          lastError = error;
          await new Promise((resolve) => window.setTimeout(resolve, 900 + attempt * 700));
          continue;
        }
        error.message = friendlyApiMessage(error);
        throw error;
      }
      return payload;
    } catch (caught: any) {
      const aborted = caught?.name === 'AbortError' || controller.signal.aborted;
      const error: any = caught instanceof Error ? caught : new Error(String(caught || 'Falha de rede.'));
      if (aborted && !externalSignal?.aborted) {
        error.code = 'VAULT_API_TIMEOUT';
        error.message = path.includes('/api/myp/')
          ? 'A MYP demorou demais para responder. Tente novamente em alguns segundos.'
          : 'O servidor do Vault demorou demais para responder. Tente novamente.';
      } else if (!error.status) {
        error.code = error.code || 'VAULT_API_NETWORK';
        error.message = 'Não foi possível conectar ao servidor do Vault. Tente novamente em alguns segundos.';
      }
      lastError = error;
      const canRetry = attempt < retries && !externalSignal?.aborted && (!error.status || [502, 503, 504].includes(Number(error.status)));
      if (!canRetry) throw error;
      await new Promise((resolve) => window.setTimeout(resolve, 900 + attempt * 700));
    } finally {
      window.clearTimeout(timeout);
      externalSignal?.removeEventListener?.('abort', forwardAbort);
    }
  }

  throw lastError || new Error('Não foi possível conectar ao servidor do Vault. Tente novamente em alguns segundos.');
};

const authorizedVaultApiFetch = async (path: string, init: VaultApiInit = {}) => {
  const { auth } = await getCloud();
  await auth.authStateReady?.();
  const user = auth.currentUser;
  if (!user) throw new Error('Sua sessão expirou. Entre novamente.');

  const execute = async (forceRefresh = false) => {
    const idToken = await user.getIdToken(forceRefresh);
    return vaultApiFetch(path, {
      ...init,
      headers: {
        ...(init.headers || {}),
        Authorization: `Bearer ${idToken}`,
      },
    });
  };

  try {
    // O SDK já renova tokens automaticamente quando necessário. Forçar refresh em
    // toda chamada criava mais uma dependência de rede justamente após o Render
    // acordar. Agora só forçamos uma renovação se o backend realmente responder 401.
    return await execute(false);
  } catch (error: any) {
    if (Number(error?.status || 0) !== 401) throw error;
    return execute(true);
  }
};

export const fetchMypCardInfo = async (url: string) => {
  const link = String(url || '').trim();
  if (!link) throw new Error('Cole o link da carta na MYP.');
  const payload = await vaultApiFetch('/api/myp/card', {
    method: 'POST',
    body: JSON.stringify({ url: link }),
    timeoutMs: 65000,
    retries: 1,
  });
  if (!payload?.data) throw new Error('A MYP não retornou dados para esta carta.');
  return payload.data;
};

export const vaultApiUrl = VAULT_API_URL;

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


export const DEFAULT_ACCOUNT_SCORES = Object.freeze({
  security: 30,
  visibility: 30,
});

const normalizeScoreValue = (value: any, fallback: number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(100, Math.max(0, parsed)) : fallback;
};

const normalizeAccountScores = (value: any) => ({
  security: normalizeScoreValue(value?.security, DEFAULT_ACCOUNT_SCORES.security),
  visibility: normalizeScoreValue(value?.visibility, DEFAULT_ACCOUNT_SCORES.visibility),
});

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
  const average = item?.kind === 'card'
    ? numberOrNull(item?.averageGeneralPrice ?? item?.averageLeaguePrice ?? item?.leagueAverage)
    : numberOrNull(item?.averageLeaguePrice ?? item?.leagueAverage);
  const lowest = item?.kind === 'card'
    ? numberOrNull(item?.cheapestGeneralPrice ?? item?.leaguePrice ?? item?.leagueLowest)
    : numberOrNull(item?.leaguePrice ?? item?.leagueLowest);
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
    const price = item.price ?? item.averageGeneralPrice ?? item.cheapestGeneralPrice ?? item.leaguePrice ?? 0;
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
      scores: { ...DEFAULT_ACCOUNT_SCORES },
      emailVerified: false,
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


export async function sendAccountVerificationEmail() {
  const { auth } = await getCloud();
  const user = auth.currentUser;
  if (!user) throw new Error('Sua sessão expirou. Entre novamente.');
  if (user.emailVerified) return { alreadyVerified: true, email: user.email || '', delivery: 'already-verified' };

  const payload = await authorizedVaultApiFetch('/api/email/verification', {
    method: 'POST',
    body: JSON.stringify({
      returnUrl: typeof window !== 'undefined' ? window.location.href.split('#')[0] : '',
    }),
    timeoutMs: 65000,
  });
  return {
    alreadyVerified: Boolean(payload?.alreadyVerified),
    email: payload?.email || user.email || '',
    delivery: payload?.delivery || 'gmail-render',
  };
}

export async function refreshAccountVerification() {
  const { auth, db } = await getCloud();
  const user = auth.currentUser;
  if (!user) throw new Error('Sua sessão expirou. Entre novamente.');
  await reload(user);
  if (!user.emailVerified) {
    const accountSnapshot = await getDoc(doc(db, 'users', user.uid));
    return {
      verified: false,
      scores: normalizeAccountScores(accountSnapshot.data()?.scores),
    };
  }

  const accountRef = doc(db, 'users', user.uid);
  const result = await runTransaction(db, async (transaction) => {
    const snapshot = await transaction.get(accountRef);
    const data = snapshot.data() || {};
    const scores = normalizeAccountScores(data.scores);
    const wasVerified = data.emailVerified === true;
    const nextScores = wasVerified
      ? scores
      : { ...scores, security: Math.min(100, scores.security + 5) };

    transaction.set(accountRef, {
      email: user.email || data.email || '',
      emailVerified: true,
      emailVerifiedAt: wasVerified ? (data.emailVerifiedAt || serverTimestamp()) : serverTimestamp(),
      scores: nextScores,
      updatedAt: serverTimestamp(),
    }, { merge: true });

    return { verified: true, scores: nextScores, awarded: !wasVerified };
  });
  return result;
}

export async function requestForgotPassword(email: string) {
  const { auth } = await getCloud();
  const address = String(email || '').trim();
  if (!address) throw new Error('Informe seu e-mail para recuperar a senha.');
  await firebaseSendPasswordResetEmail(auth, address);
  return { ok: true, email: address };
}

export async function requestAccountPasswordResetEmail() {
  const { auth } = await getCloud();
  const user = auth.currentUser;
  if (!user?.email) throw new Error('Sua sessão expirou. Entre novamente.');
  await reload(user);
  if (!user.emailVerified) throw new Error('Verifique seu Gmail antes de solicitar a alteração de senha.');
  return authorizedVaultApiFetch('/api/email/password-reset', {
    method: 'POST',
    body: JSON.stringify({
      returnUrl: typeof window !== 'undefined' ? window.location.href.split('#')[0] : '',
    }),
    timeoutMs: 65000,
  });
}

export async function getVaultPlusStatus() {
  return authorizedVaultApiFetch('/api/vault-plus/status', { timeoutMs: 25000, retries: 1 });
}

export async function startBulkQuote(filters: { minValue?: number | null; staleDays?: number | null } = {}) {
  return authorizedVaultApiFetch('/api/quotes/bulk/start', {
    method: 'POST',
    body: JSON.stringify({ filters }),
    timeoutMs: 70000,
  });
}

export async function getBulkQuoteStatus(jobId: string) {
  const id = encodeURIComponent(String(jobId || '').trim());
  if (!id) throw new Error('Cotização inválida.');
  return authorizedVaultApiFetch(`/api/quotes/bulk/${id}/status`, { timeoutMs: 25000, retries: 1 });
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
    batch.set(doc(db, 'users', uid), {
      displayName: profile.owner,
      email: profile.email,
      collectionSlug: slug,
      scores: { ...DEFAULT_ACCOUNT_SCORES },
      emailVerified: active.emailVerified === true,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    }, { merge: true });
    batch.set(doc(db, 'slugs', slug), { ownerUid: uid, collectionUid: uid, slug, createdAt: serverTimestamp() });
    await batch.commit();
    snapshot = await getDoc(collectionRef);
  }
  const data = snapshot.data() || {};
  const accountRef = doc(db, 'users', uid);
  const [accountSnapshot, cards, boosters, kits, products, albums] = await Promise.all([
    getDoc(accountRef),
    readSubcollection(db, uid, 'cards'),
    readSubcollection(db, uid, 'boosters'),
    readSubcollection(db, uid, 'kits'),
    readSubcollection(db, uid, 'products'),
    readSubcollection(db, uid, 'albums'),
  ]);
  const accountData = accountSnapshot.data() || {};
  const scores = normalizeAccountScores(accountData.scores);
  if (!accountSnapshot.exists() || !accountData.scores) {
    await setDoc(accountRef, {
      displayName: data.owner || active.displayName || '',
      email: active.email || '',
      collectionSlug: data.slug || data.collectionId || uid,
      scores,
      emailVerified: active.emailVerified === true || accountData.emailVerified === true,
      updatedAt: serverTimestamp(),
    }, { merge: true });
  }
  // Vault+ é autoritativo apenas no backend (`vaultPlusSubscriptions/{uid}`).
  // Ignora qualquer flag legada/spoofável que eventualmente exista no documento público da coleção.
  const { vaultPlus: _ignoredVaultPlus, ...collectionProfile } = data as any;
  const profile = {
    ...collectionProfile,
    ownerUid: uid,
    collectionId: data.slug || data.collectionId || uid,
    email: active.email || data.email || '',
    password: '',
    version: Number(data.version || 1),
    scores,
    emailVerified: active.emailVerified === true || accountData.emailVerified === true,
  };
  return { profile, cards, boosters, kits, products, albums };
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
    cheapestCertifiedPrice: numberOrNull(card.cheapestCertifiedPrice),
    cheapestGeneralPrice: numberOrNull(card.cheapestGeneralPrice),
    averageCertifiedPrice: numberOrNull(card.averageCertifiedPrice),
    averageGeneralPrice: numberOrNull(card.averageGeneralPrice),
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

  await commitOperations(db, operations);
  clearPublicCache();
  for (const kind of kinds) (state[kind] || []).forEach((item: any) => { item._isNew = false; item._isDirty = false; });
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

export async function listMyProposals(scope: 'all' | 'sent' | 'received' | 'completed' = 'all', maxResults = 100) {
  const normalized = ['all', 'sent', 'received', 'completed'].includes(scope) ? scope : 'all';
  const size = Math.min(100, Math.max(1, Math.floor(Number(maxResults) || 100)));
  const payload = await authorizedVaultApiFetch(`/api/proposals?scope=${encodeURIComponent(normalized)}&limit=${size}`, {
    timeoutMs: 30000,
    retries: 1,
  });
  return Array.isArray(payload?.proposals) ? payload.proposals : [];
}

export async function listMyReceivedProposals(maxResults = 60) {
  return listMyProposals('received', maxResults);
}

export async function actOnProposal(proposalId: string, action: 'accept' | 'reject' | 'counter', options: { amount?: number; message?: string } = {}) {
  const id = encodeURIComponent(String(proposalId || '').trim());
  if (!id) throw new Error('Proposta inválida.');
  return authorizedVaultApiFetch(`/api/proposals/${id}/action`, {
    method: 'POST',
    body: JSON.stringify({ action, ...options }),
    timeoutMs: 45000,
  });
}

export async function submitProposal(group: any) {
  const payload = await authorizedVaultApiFetch('/api/proposals', {
    method: 'POST',
    body: JSON.stringify({
      ownerUid: group?.ownerUid || '',
      ownerSlug: group?.ownerSlug || '',
      ownerCollection: group?.ownerCollection || '',
      owner: group?.owner || '',
      items: (group?.items || []).map((item: any) => ({
        id: item?.id || '',
        kind: item?.kind || '',
        name: item?.name || '',
        number: item?.number || '',
        quantity: Number(item?.quantity || 1),
        price: Number.isFinite(Number(item?.price)) ? Number(item.price) : null,
      })),
      publishedTotal: Number(group?.publishedTotal || 0),
      discount: Number(group?.discount || 0),
      proposedTotal: Number(group?.proposedTotal || 0),
      reason: group?.reason || '',
      buyerName: group?.buyerName || '',
      address: group?.address || '',
    }),
    timeoutMs: 45000,
  });
  return payload;
}

export function friendlyFirebaseError(error: any) {
  const code = String(error?.code || '');
  const map: Record<string, string> = {
    'auth/email-already-in-use': 'Este e-mail já possui uma conta. Entre com sua senha.',
    'auth/invalid-email': 'O e-mail informado não é válido.',
    'auth/weak-password': 'Use uma senha mais forte, com pelo menos 6 caracteres.',
    'auth/invalid-credential': 'E-mail ou senha incorretos.',
    'auth/wrong-password': 'A senha atual está incorreta.',
    'auth/requires-recent-login': 'Confirme sua senha atual e tente novamente.',
    'auth/user-disabled': 'Esta conta foi desativada.',
    'auth/too-many-requests': 'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
    'permission-denied': 'Você não tem permissão para concluir esta operação.',
    'firestore/permission-denied': 'Você não tem permissão para concluir esta operação.',
  };
  return map[code] || error?.message || 'Não foi possível concluir a operação agora.';
}
