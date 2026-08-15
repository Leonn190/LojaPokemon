import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

export type CatalogKind = 'card' | 'booster' | 'kit' | 'product';
export type PublicPriceFallback = 'league_average_then_lowest' | 'league_lowest_then_average' | 'consult';
export type ProposalPolicy = 'flexible' | 'none' | 'fixed_price_multi_only' | 'no_defined_price' | 'multi_only';

export interface ProposalDiscountTier {
  minValue: number;
  maxDiscount: number;
}

export interface ProposalTerms {
  policy: ProposalPolicy;
  flexibleDiscounts: boolean;
  discountTiers: ProposalDiscountTier[];
}

interface OwnedItemBase {
  id: string;
  kind: CatalogKind;
  name: string;
  quantity: number;
  price: number | null;
  slug: string;
  image: string;
  imageCandidates: string[];
  searchText: string;
  ownerName: string;
  ownerCollectionName: string;
  ownerCollectionSlug: string;
  ownerPhone: string;
  proposalTerms: ProposalTerms;
  forSale: boolean;
  showQuantity: boolean;
}

export interface PriceHistoryEntry {
  date: string;
  minimumCertain: number | null;
  minimumBuylist: number | null;
  leagueLowest: number | null;
  leagueSecond: number | null;
  leagueThird: number | null;
  leagueAverage: number | null;
  leagueMedian: number | null;
  quickSale: number | null;
  sellersGeneral: number;
  sellersSpecific: number;
  buyersGeneral: number;
  buyersSpecific: number;
}


export interface CollectionMovementEntry {
  eventId: string;
  updateId: string;
  collectionId: string;
  version: number;
  date: string;
  eventType: string;
  itemType: string;
  itemId: string;
  name: string;
  quantityBefore: number;
  quantityDelta: number;
  quantityAfter: number;
  source: string;
  note: string;
}

export interface CardItem extends OwnedItemBase {
  kind: 'card';
  number: string;
  collection: string;
  language: string;
  condition: string;
  year: string;
  type: string;
  linkLiga: string;
  linkMyp: string;
  linkCardmarket: string;
  linkTcgplayer: string;
  linkPriceCharting: string;
  certainMinimumPrice: number | null;
  minimumPrice: number | null;
  quickSalePrice: number | null;
  leaguePrice: number | null;
  secondLeaguePrice: number | null;
  thirdLeaguePrice: number | null;
  averageLeaguePrice: number | null;
  medianLeaguePrice: number | null;
  sellersGeneral: number;
  sellersSpecific: number;
  buyersGeneral: number;
  buyersSpecific: number;
  finalPrice: number | null;
  favorite: boolean;
  priceHistory: PriceHistoryEntry[];
  advancedData: Record<string, unknown>;
}

export interface BoosterItem extends OwnedItemBase {
  kind: 'booster';
  linkLiga: string;
  certainMinimumPrice: number | null;
  minimumPrice: number | null;
  quickSalePrice: number | null;
  leaguePrice: number | null;
  secondLeaguePrice: number | null;
  thirdLeaguePrice: number | null;
  averageLeaguePrice: number | null;
  medianLeaguePrice: number | null;
  sellersGeneral: number;
  sellersSpecific: number;
  buyersGeneral: number;
  buyersSpecific: number;
  finalPrice: number | null;
  priceHistory: PriceHistoryEntry[];
  advancedData: Record<string, unknown>;
}

export interface KitContentItem {
  kind: 'cards' | 'boosters';
  itemId: string;
  slug?: string;
  name: string;
  quantity: number;
  unitPrice: number | null;
  imageCandidates?: string[];
  type?: string;
  number?: string;
  collection?: string;
  language?: string;
  condition?: string;
  year?: string;
  linkLiga?: string;
  ownerName?: string;
  ownerCollectionName?: string;
  ownerCollectionSlug?: string;
  ownerPhone?: string;
}

export interface KitItem extends OwnedItemBase {
  kind: 'kit';
  description: string;
  contents: string;
  contentItems: KitContentItem[];
  sourceTotal: number | null;
}

export interface ProductItem extends OwnedItemBase {
  kind: 'product';
  linkLiga: string;
  description: string;
}

export type CatalogItem = CardItem | BoosterItem | KitItem | ProductItem;

export interface AlbumCardReference {
  itemId: string;
  linkLiga: string;
  language: string;
  condition: string;
  name: string;
  number: string;
  collection: string;
  imageCandidates: string[];
  cardSlug: string;
}

export interface AlbumPage {
  slots: Array<AlbumCardReference | null>;
}

export interface AlbumItem {
  id: string;
  slug: string;
  ownerName: string;
  ownerCollectionName: string;
  ownerCollectionSlug: string;
  searchText: string;
  name: string;
  description: string;
  format: string;
  columns: number;
  rows: number;
  pages: AlbumPage[];
  occupiedSlots: number;
  totalSlots: number;
  coverImageCandidates: string[];
}

export interface CollectorCollection {
  slug: string;
  owner: string;
  title: string;
  description: string;
  selling: boolean;
  featured: boolean;
  phone: string;
  proposalTerms: ProposalTerms;
  profilePhoto: string;
  palette: [string, string, string];
  cards: CardItem[];
  boosters: BoosterItem[];
  kits: KitItem[];
  products: ProductItem[];
  albums: AlbumItem[];
  movements: CollectionMovementEntry[];
  priceDisplayFallback: PublicPriceFallback;
  totalItems: number;
  totalUnits: number;
  estimatedValue: number;
  coverItems: CatalogItem[];
  searchText: string;
}

type CsvRow = Record<string, string>;
type InventoryRow = Record<string, any>;
type ProfileData = {
  owner?: string;
  title?: string;
  description?: string;
  selling?: boolean;
  featured?: boolean;
  showQuantity?: boolean;
  email?: string;
  phone?: string;
  password?: string;
  profilePhoto?: string;
  palette?: string[] | { primary?: string; secondary?: string; accent?: string };
  priceDisplayFallback?: PublicPriceFallback;
  pricingMode?: string;
  proposalTerms?: {
    policy?: ProposalPolicy;
    flexibleDiscounts?: boolean;
    discountTiers?: Array<{ minValue?: string | number; maxDiscount?: string | number }>;
  };
};

const sourceRoot = join(process.cwd(), 'src');
const collectionsRoot = join(sourceRoot, 'colecoes');

const parseCsv = (source: string): CsvRow[] => {
  const text = source.replace(/^\uFEFF/, '');
  const records: string[][] = [];
  let record: string[] = [];
  let field = '';
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];

    if (char === '"') {
      if (quoted && next === '"') {
        field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
      continue;
    }

    if (char === ',' && !quoted) {
      record.push(field);
      field = '';
      continue;
    }

    if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') index += 1;
      record.push(field);
      field = '';
      if (record.some((value) => value.trim() !== '')) records.push(record);
      record = [];
      continue;
    }

    field += char;
  }

  if (field.length > 0 || record.length > 0) {
    record.push(field);
    if (record.some((value) => value.trim() !== '')) records.push(record);
  }

  const [headers = [], ...rows] = records;
  return rows.map((values) =>
    Object.fromEntries(headers.map((header, index) => [header.trim(), (values[index] ?? '').trim()])),
  );
};

const readText = (path: string): string => {
  try {
    return readFileSync(path, 'utf8');
  } catch (_) {
    return '';
  }
};

const readRows = (folder: string, filename: string): CsvRow[] => {
  const source = readText(join(folder, filename));
  return source ? parseCsv(source) : [];
};

// JSON é o formato oficial. CSV fica somente como leitor de compatibilidade para
// coleções antigas que ainda não passaram pela migração.
const readInventory = (folder: string, baseName: string): InventoryRow[] => {
  const jsonSource = readText(join(folder, `${baseName}.json`));
  if (jsonSource) {
    try {
      const parsed = JSON.parse(jsonSource) as unknown;
      if (Array.isArray(parsed)) return parsed.filter((item): item is InventoryRow => Boolean(item) && typeof item === 'object');
    } catch (_) {}
  }
  return readRows(folder, `${baseName}.csv`);
};


const readJsonLines = (path: string): InventoryRow[] => {
  const source = readText(path);
  if (!source) return [];
  return source.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).flatMap((line) => {
    try {
      const parsed = JSON.parse(line) as unknown;
      return parsed && typeof parsed === 'object' ? [parsed as InventoryRow] : [];
    } catch (_) {
      return [];
    }
  });
};

const normalizeColor = (value: unknown, fallback: string): string => {
  const raw = String(value ?? '').trim();
  return /^#[0-9a-f]{6}$/i.test(raw) ? raw : fallback;
};

const normalizePalette = (profile: ProfileData): [string, string, string] => {
  const raw = profile.palette;
  if (Array.isArray(raw)) return [normalizeColor(raw[0], '#54e8df'), normalizeColor(raw[1], '#bc91ff'), normalizeColor(raw[2], '#f4c25c')];
  if (raw && typeof raw === 'object') return [
    normalizeColor(raw.primary, '#54e8df'),
    normalizeColor(raw.secondary, '#bc91ff'),
    normalizeColor(raw.accent, '#f4c25c'),
  ];
  return ['#54e8df', '#bc91ff', '#f4c25c'];
};
const readProfile = (folder: string): ProfileData => {
  try {
    return JSON.parse(readFileSync(join(folder, 'perfil.json'), 'utf8')) as ProfileData;
  } catch (_) {
    return {};
  }
};

const parseDecimal = (value: unknown): number | null => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const raw = String(value ?? '').trim();
  if (!raw || raw === '-') return null;
  const cleaned = raw.replace(/R\$/gi, '').replace(/\s/g, '');
  const normalized = cleaned.includes(',')
    ? cleaned.replace(/\./g, '').replace(',', '.')
    : cleaned;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
};

const parseQuantity = (value: unknown): number => {
  const parsed = Number(String(value ?? '').replace(/[^0-9-]/g, ''));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
};

const parseBoolean = (value: unknown, fallback: boolean): boolean => {
  if (typeof value === 'boolean') return value;
  const normalized = normalizeText(String(value ?? ''));
  if (['false', 'nao', 'não', '0', 'no'].includes(normalized)) return false;
  if (['true', 'sim', 's', '1', 'yes'].includes(normalized)) return true;
  return fallback;
};

const proposalPolicies: ProposalPolicy[] = ['flexible', 'none', 'fixed_price_multi_only', 'no_defined_price', 'multi_only'];

const normalizeProposalTerms = (profile: ProfileData): ProposalTerms => {
  const raw = profile.proposalTerms ?? {};
  const policy = proposalPolicies.includes(raw.policy as ProposalPolicy) ? raw.policy as ProposalPolicy : 'flexible';
  const discountTiers = (Array.isArray(raw.discountTiers) ? raw.discountTiers : [])
    .map((tier) => ({ minValue: parseDecimal(tier.minValue) ?? 0, maxDiscount: parseDecimal(tier.maxDiscount) ?? 0 }))
    .filter((tier) => tier.minValue >= 0 && tier.maxDiscount >= 0)
    .map((tier) => ({ ...tier, maxDiscount: Math.min(100, tier.maxDiscount) }))
    .sort((left, right) => left.minValue - right.minValue);
  return {
    policy,
    flexibleDiscounts: raw.flexibleDiscounts !== false,
    discountTiers,
  };
};

export const normalizeText = (value: string): string =>
  value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('pt-BR')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();

export const slugify = (value: string): string =>
  normalizeText(value).replace(/\s+/g, '-').replace(/^-|-$/g, '') || 'item';

const cleanFilePart = (value: string): string =>
  value
    .replace(/[–—]/g, '-')
    .replace(/[\\/:*?"<>|]/g, '-')
    .replace(/\s+/g, ' ')
    .trim();

const asciiFilePart = (value: string): string =>
  cleanFilePart(value.normalize('NFD').replace(/[\u0300-\u036f]/g, ''));

const unique = <T>(values: T[]): T[] => [...new Set(values.filter(Boolean))];
const supportedImage = /\.(?:avif|jpe?g|png|webp)$/i;
const imageFolderCache = new Map<string, string[]>();

const readImageFiles = (folder: string): string[] => {
  const cached = imageFolderCache.get(folder);
  if (cached) return cached;
  try {
    const files = readdirSync(join(process.cwd(), 'public', folder), { withFileTypes: true })
      .filter((entry) => entry.isFile() && supportedImage.test(entry.name))
      .map((entry) => `${folder}/${entry.name}`);
    imageFolderCache.set(folder, files);
    return files;
  } catch (_) {
    imageFolderCache.set(folder, []);
    return [];
  }
};

const imagePool = (collectionSlug: string, kind: CatalogKind): string[] => {
  const folderByKind: Record<CatalogKind, string> = { card: 'imagens', booster: 'imagensboosters', kit: 'imagenskits', product: 'imagensprodutos' };
  const folder = folderByKind[kind];
  return unique([...readImageFiles(`colecoes/${collectionSlug}/${folder}`), ...readImageFiles(folder)]);
};

const compactImageKey = (value: string): string => normalizeText(value).replace(/\s+/g, '');
const stemOf = (path: string): string => path.split('/').pop()?.replace(/\.[^.]+$/, '') ?? '';

const cardImageCandidates = (
  collectionSlug: string,
  name: string,
  number: string,
  language: string,
  duplicateIndex: number,
  explicit: string = '',
): string[] => {
  const explicitCandidates = explicit ? (explicit.includes('/') ? [explicit] : [`colecoes/${collectionSlug}/imagens/${explicit}`, `imagens/${explicit}`]) : [];
  const pool = imagePool(collectionSlug, 'card');
  const exactKey = normalizeText(`${name} ${number}`);
  const normalizedName = normalizeText(name);
  const normalizedNumber = normalizeText(number);
  const existing = pool.filter((path) => {
    const key = normalizeText(stemOf(path));
    return key === exactKey || (key.includes(normalizedName) && key.includes(normalizedNumber));
  });
  const preferredExisting = existing.length > 1 ? [existing[duplicateIndex] ?? existing[0], ...existing] : existing;

  const names = unique([cleanFilePart(name), asciiFilePart(name)]);
  const numbers = unique([
    cleanFilePart(number),
    asciiFilePart(number),
    cleanFilePart(number).replace(/\s+/g, ''),
    asciiFilePart(number).replace(/\s+/g, ''),
  ]);
  const languages = unique([cleanFilePart(language), asciiFilePart(language)]);
  const stems = unique(names.flatMap((cardName) => numbers.flatMap((cardNumber) => [
    `${cardName}_${cardNumber}`,
    `${cardName}-${cardNumber}`,
    `${cardName} ${cardNumber}`,
  ])));
  const duplicateNumber = duplicateIndex + 1;
  const duplicateVariants = duplicateIndex > 0
    ? stems.flatMap((stem) => [
        `${stem} (${duplicateIndex})`,
        `${stem} (${duplicateNumber})`,
        `${stem}_${duplicateNumber}`,
        ...languages.map((languageName) => `${stem}_${languageName}`),
      ])
    : [];
  const generated = unique([...stems, ...duplicateVariants]).flatMap((stem) =>
    ['jpg', 'jpeg', 'png', 'webp', 'avif'].map((extension) => `imagens/${stem}.${extension}`),
  );
  return unique([...explicitCandidates, ...preferredExisting, ...generated]);
};

const boosterAliases: Record<string, string[]> = {
  lostorigin: ['origemperdida'],
  chillingreign: ['reinadoarrepiante'],
  fusionstrike: ['golpefusao'],
  paradoxrift: ['fendaparadoxal'],
  shiningfates: ['shinigfates'],
};

const boosterKeys = (name: string): string[] => {
  const exact = compactImageKey(name);
  const withoutQualifier = compactImageKey(name.replace(/\s*\([^)]*\)\s*/g, ' '));
  return unique([exact, withoutQualifier, ...(boosterAliases[exact] ?? []), ...(boosterAliases[withoutQualifier] ?? [])]);
};

const boosterVariantNumber = (path: string): number => {
  const match = compactImageKey(stemOf(path)).match(/(\d+)$/);
  return match ? Number(match[1]) : 0;
};

const boosterImageCandidates = (collectionSlug: string, name: string, explicit: string = ''): string[] => {
  const explicitCandidates = explicit ? (explicit.includes('/') ? [explicit] : [`colecoes/${collectionSlug}/imagensboosters/${explicit}`, `imagensboosters/${explicit}`]) : [];
  const pool = imagePool(collectionSlug, 'booster');
  const keys = boosterKeys(name);
  const existing = pool
    .filter((path) => {
      const stem = compactImageKey(stemOf(path));
      return keys.some((key) => stem === key || (stem.startsWith(key) && /^\d+$/.test(stem.slice(key.length))));
    })
    .sort((left, right) => boosterVariantNumber(left) - boosterVariantNumber(right) || left.localeCompare(right, 'pt-BR'));
  if (existing.length > 0) return unique([...explicitCandidates, ...existing]);

  const baseNames = unique([
    cleanFilePart(name),
    asciiFilePart(name),
    cleanFilePart(name).replace(/\s*\([^)]*\)\s*/g, ' ').trim(),
    asciiFilePart(name).replace(/\s*\([^)]*\)\s*/g, ' ').trim(),
  ]);
  const stems = unique(baseNames.flatMap((boosterName) => {
    const compact = boosterName.replace(/\s+/g, '');
    return [boosterName, compact].flatMap((stem) => [stem, `${stem}1`, `${stem}2`, `${stem}3`, `${stem}4`]);
  }));
  const generated = stems.flatMap((stem) => ['jpg', 'jpeg', 'png', 'webp', 'avif'].map((extension) => `imagensboosters/${stem}.${extension}`));
  return unique([...explicitCandidates, ...generated]);
};

const kitImageCandidates = (collectionSlug: string, name: string, explicit: string): string[] => {
  const pool = imagePool(collectionSlug, 'kit');
  const explicitCandidates = explicit
    ? (explicit.includes('/') ? [explicit] : [`colecoes/${collectionSlug}/imagenskits/${explicit}`, `imagenskits/${explicit}`])
    : [];
  const key = normalizeText(name);
  const existing = pool.filter((path) => normalizeText(stemOf(path)).includes(key));
  const stems = unique([cleanFilePart(name), asciiFilePart(name), slugify(name)]);
  const generated = stems.flatMap((stem) => ['jpg', 'jpeg', 'png', 'webp', 'avif'].map((extension) => `imagenskits/${stem}.${extension}`));
  return unique([...explicitCandidates, ...existing, ...generated]);
};

const productImageCandidates = (collectionSlug: string, name: string, explicit: string): string[] => {
  const pool = imagePool(collectionSlug, 'product');
  const explicitCandidates = explicit ? (explicit.includes('/') || /^(?:https?:|data:|blob:)/i.test(explicit) ? [explicit] : [`colecoes/${collectionSlug}/imagensprodutos/${explicit}`, `imagensprodutos/${explicit}`]) : [];
  const key = normalizeText(name);
  const existing = pool.filter((path) => normalizeText(stemOf(path)).includes(key));
  const stems = unique([cleanFilePart(name), asciiFilePart(name), slugify(name)]);
  const generated = stems.flatMap((stem) => ['jpg', 'jpeg', 'png', 'webp', 'avif'].map((extension) => `imagensprodutos/${stem}.${extension}`));
  return unique([...explicitCandidates, ...existing, ...generated]);
};

const normalizePriceFallback = (profile: ProfileData): PublicPriceFallback => {
  if (profile.priceDisplayFallback === 'league_lowest_then_average' || profile.priceDisplayFallback === 'consult') return profile.priceDisplayFallback;
  if (normalizeText(String(profile.pricingMode ?? '')) === 'menor') return 'league_lowest_then_average';
  return 'league_average_then_lowest';
};

const resolvePublicPrice = (finalPrice: number | null, average: number | null, lowest: number | null, fallback: PublicPriceFallback): number | null => {
  if (finalPrice !== null) return finalPrice;
  if (fallback === 'consult') return null;
  if (fallback === 'league_lowest_then_average') return lowest ?? average;
  return average ?? lowest;
};

const normalizeReferenceLink = (value: string): string => {
  const raw = value.trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    const entries = [...parsed.searchParams.entries()]
      .filter(([key]) => key.toLowerCase() !== 'show' && key.toLowerCase() !== 'srsltid' && !key.toLowerCase().startsWith('utm_'))
      .sort(([leftKey, leftValue], [rightKey, rightValue]) => leftKey.localeCompare(rightKey) || leftValue.localeCompare(rightValue));
    const search = entries.map(([key, item]) => `${key}=${item}`).join('&');
    return normalizeText(`${parsed.hostname}${parsed.pathname}?${search}`);
  } catch (_) {
    return normalizeText(raw);
  }
};

const albumFormat = (value: string): { format: string; columns: number; rows: number } => {
  const match = value.match(/([2-6])\s*(?:x|por)\s*([2-6])/i);
  const columns = match ? Number(match[1]) : 3;
  const rows = match ? Number(match[2]) : 3;
  return { format: `${columns}x${rows}`, columns, rows };
};

const resolveAlbumCard = (raw: unknown, cards: CardItem[]): AlbumCardReference | null => {
  if (!raw || typeof raw !== 'object') return null;
  const slot = raw as Record<string, unknown>;
  const itemId = String(slot.itemId ?? slot.cardId ?? slot.Id ?? '').trim();
  const linkLiga = String(slot.linkLiga ?? slot.link ?? '').trim();
  const language = String(slot.language ?? slot.idioma ?? '').trim();
  const condition = String(slot.condition ?? slot.estado ?? '').trim();
  const name = String(slot.name ?? slot.nome ?? '').trim();
  const number = String(slot.number ?? slot.numero ?? slot['número'] ?? '').trim();
  const linkKey = normalizeReferenceLink(linkLiga);
  const byId = itemId ? cards.find((card) => card.id === itemId) : undefined;
  const exact = byId ?? cards.find((card) => linkKey && normalizeReferenceLink(card.linkLiga) === linkKey && (!language || normalizeText(card.language) === normalizeText(language)) && (!condition || normalizeText(card.condition) === normalizeText(condition)));
  const byLink = exact ?? cards.find((card) => linkKey && normalizeReferenceLink(card.linkLiga) === linkKey);
  const byIdentity = byLink ?? cards.find((card) => name && normalizeText(card.name) === normalizeText(name) && (!number || normalizeText(card.number) === normalizeText(number)));
  const card = byIdentity;
  const candidates = card?.imageCandidates ?? (Array.isArray(slot.imageCandidates) ? slot.imageCandidates.map(String) : []);
  if (!card && !linkLiga && !name && !itemId) return null;
  return {
    itemId: card?.id || itemId,
    linkLiga: card?.linkLiga || linkLiga,
    language: card?.language || language,
    condition: card?.condition || condition,
    name: card?.name || name || 'Carta não localizada',
    number: card?.number || number,
    collection: card?.collection || String(slot.collection ?? slot.colecao ?? ''),
    imageCandidates: candidates,
    cardSlug: card?.slug || '',
  };
};

const parseAlbumPages = (raw: unknown, columns: number, rows: number, cards: CardItem[]): AlbumPage[] => {
  const capacity = columns * rows;
  let parsed: unknown = raw;
  if (typeof raw === 'string') {
    try { parsed = JSON.parse(raw || '[]'); } catch (_) { parsed = []; }
  }
  const sourcePages = Array.isArray(parsed) ? parsed : [];
  const pages = sourcePages.map((page): AlbumPage => {
    const sourceSlots = Array.isArray(page) ? page : page && typeof page === 'object' && Array.isArray((page as Record<string, unknown>).slots) ? (page as Record<string, unknown>).slots as unknown[] : [];
    return { slots: Array.from({ length: capacity }, (_, index) => resolveAlbumCard(sourceSlots[index], cards)) };
  });
  return pages.length ? pages : [{ slots: Array.from({ length: capacity }, () => null) }];
};

const createUniqueSlug = (base: string, used: Map<string, number>, suffix: string): string => {
  const count = used.get(base) ?? 0;
  used.set(base, count + 1);
  if (count === 0) return base;
  return `${base}-${slugify(suffix)}-${count + 1}`;
};

const getCollectionFolders = (): string[] => {
  if (!existsSync(collectionsRoot)) return [];
  return readdirSync(collectionsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort((a, b) => a.localeCompare(b, 'pt-BR'));
};

let collectionsCache: CollectorCollection[] | null = null;

export const getCollections = (): CollectorCollection[] => {
  if (collectionsCache) return collectionsCache;
  const globalSlugs = new Map<string, number>();

  collectionsCache = getCollectionFolders().map((folderName) => {
    const folder = join(collectionsRoot, folderName);
    const profile = readProfile(folder);
    const owner = profile.owner?.trim() || folderName;
    const collectionSlug = slugify(folderName);
    const title = profile.title?.trim() || `Coleção de ${owner}`;
    const description = profile.description?.trim() || 'Coleção Pokémon organizada no Vault TCG.';
    const showQuantity = profile.showQuantity !== false;
    const proposalTerms = normalizeProposalTerms(profile);
    const ownerPhone = profile.phone?.trim() || '';
    const usedImages = new Map<string, number>();
    const palette = normalizePalette(profile);
    const profilePhoto = String(profile.profilePhoto ?? '').trim();
    const priceDisplayFallback = normalizePriceFallback(profile);
    const movements: CollectionMovementEntry[] = readJsonLines(join(folder, 'historico', 'movimentacoes.jsonl')).map((entry) => ({
      eventId: String(entry.eventId ?? ''),
      updateId: String(entry.updateId ?? entry.sourceId ?? ''),
      collectionId: String(entry.collectionId ?? folderName),
      version: parseQuantity(entry.version),
      date: String(entry.date ?? entry.data ?? ''),
      eventType: String(entry.eventType ?? entry.tipo ?? 'ajuste'),
      itemType: String(entry.itemType ?? entry.tipoItem ?? 'cartas'),
      itemId: String(entry.itemId ?? entry.Id ?? ''),
      name: String(entry.name ?? entry.nome ?? ''),
      quantityBefore: parseQuantity(entry.quantityBefore),
      quantityDelta: Number(entry.quantityDelta ?? entry.delta ?? 0) || 0,
      quantityAfter: parseQuantity(entry.quantityAfter),
      source: String(entry.source ?? ''),
      note: String(entry.note ?? entry.observacao ?? ''),
    })).filter((entry) => entry.itemId && entry.date).sort((left, right) => left.date.localeCompare(right.date));
    const rawCardHistory = readJsonLines(join(folder, 'historico', 'cartas.jsonl'));
    const cardHistory = new Map<string, PriceHistoryEntry[]>();
    rawCardHistory.forEach((entry) => {
      const itemId = String(entry.itemId ?? entry.Id ?? '').trim();
      if (!itemId || entry.sucesso === false || entry.erro) return;
      const historyEntry: PriceHistoryEntry = {
        date: String(entry.data ?? ''),
        minimumCertain: parseDecimal(entry['Minimo Certeiro'] ?? entry['Mínimo Certeiro']),
        minimumBuylist: parseDecimal(entry['Minimo'] ?? entry['Preço mínimo']),
        leagueLowest: parseDecimal(entry['Menor Liga'] ?? entry['Preço Liga mais barato']),
        leagueSecond: parseDecimal(entry['Segundo Menor Liga']),
        leagueThird: parseDecimal(entry['Terceiro Menor Liga']),
        leagueAverage: parseDecimal(entry['Media Liga'] ?? entry['Preço Médio Liga'] ?? entry['Preço médio Liga']),
        leagueMedian: parseDecimal(entry['Mediana Liga']),
        quickSale: parseDecimal(entry['Venda Rapida'] ?? entry['Venda rápida']),
        sellersGeneral: parseQuantity(entry['Vendedores Geral']),
        sellersSpecific: parseQuantity(entry['Vendedores Específicos']),
        buyersGeneral: parseQuantity(entry['Compradores Geral']),
        buyersSpecific: parseQuantity(entry['Compradores Específicos']),
      };
      const list = cardHistory.get(itemId) ?? [];
      list.push(historyEntry);
      cardHistory.set(itemId, list);
    });
    cardHistory.forEach((entries) => entries.sort((left, right) => left.date.localeCompare(right.date)));

    const rawBoosterHistory = readJsonLines(join(folder, 'historico', 'boosters.jsonl'));
    const boosterHistory = new Map<string, PriceHistoryEntry[]>();
    rawBoosterHistory.forEach((entry) => {
      const itemId = String(entry.itemId ?? entry.Id ?? '').trim();
      if (!itemId || entry.sucesso === false || entry.erro) return;
      const historyEntry: PriceHistoryEntry = {
        date: String(entry.data ?? ''),
        minimumCertain: parseDecimal(entry['Minimo Certeiro'] ?? entry['Mínimo Certeiro']),
        minimumBuylist: parseDecimal(entry['Minimo'] ?? entry['Preço mínimo']),
        leagueLowest: parseDecimal(entry['Menor Liga'] ?? entry['Preço Liga mais barato']),
        leagueSecond: parseDecimal(entry['Segundo Menor Liga']),
        leagueThird: parseDecimal(entry['Terceiro Menor Liga']),
        leagueAverage: parseDecimal(entry['Media Liga'] ?? entry['Preço Médio Liga'] ?? entry['Preço médio Liga']),
        leagueMedian: parseDecimal(entry['Mediana Liga']),
        quickSale: parseDecimal(entry['Venda Rapida'] ?? entry['Venda rápida']),
        sellersGeneral: parseQuantity(entry['Vendedores Geral']),
        sellersSpecific: parseQuantity(entry['Vendedores Específicos']),
        buyersGeneral: parseQuantity(entry['Compradores Geral']),
        buyersSpecific: parseQuantity(entry['Compradores Específicos']),
      };
      const list = boosterHistory.get(itemId) ?? [];
      list.push(historyEntry);
      boosterHistory.set(itemId, list);
    });
    boosterHistory.forEach((entries) => entries.sort((left, right) => left.date.localeCompare(right.date)));

    const cards: CardItem[] = readInventory(folder, 'inventario-cartas').map((row) => {
      const name = String(row['Nome'] ?? '').trim() || 'Carta sem nome';
      const number = String(row['Número'] ?? row['Numeração'] ?? '').trim() || 'Sem número';
      const pokemonCollection = String(row['Coleção'] ?? '').trim() || 'Coleção não informada';
      const language = String(row['Idioma'] ?? '').trim() || 'Não informado';
      const condition = String(row['Estado'] ?? '').trim() || 'Não informado';
      const year = String(row['Ano'] ?? '').trim() || 'Não informado';
      const type = String(row['Tipo'] ?? '').trim() || 'Não informado';
      const quantity = parseQuantity(row['Quantidade']);
      const certainMinimumPrice = parseDecimal(row['Minimo Certeiro']) ?? parseDecimal(row['Mínimo Certeiro']);
      const minimumPrice = parseDecimal(row['Minimo']) ?? parseDecimal(row['Preço mínimo']);
      const quickSalePrice = parseDecimal(row['Venda Rapida']) ?? parseDecimal(row['Venda rápida']);
      const leaguePrice = parseDecimal(row['Menor Liga']) ?? parseDecimal(row['Preço Liga mais barato']);
      const secondLeaguePrice = parseDecimal(row['Segundo Menor Liga']);
      const thirdLeaguePrice = parseDecimal(row['Terceiro Menor Liga']);
      const averageLeaguePrice = parseDecimal(row['Media Liga']) ?? parseDecimal(row['Preço Médio Liga']) ?? parseDecimal(row['Preço médio Liga']);
      const medianLeaguePrice = parseDecimal(row['Mediana Liga']);
      const sellersGeneral = parseQuantity(row['Vendedores Geral']);
      const sellersSpecific = parseQuantity(row['Vendedores Específicos']);
      const buyersGeneral = parseQuantity(row['Compradores Geral']);
      const buyersSpecific = parseQuantity(row['Compradores Específicos']);
      const finalPrice = parseDecimal(row['Preço']);
      const price = resolvePublicPrice(finalPrice, averageLeaguePrice, leaguePrice, priceDisplayFallback);
      const forSale = profile.selling !== false && parseBoolean(row['À venda'] ?? row['Venda'], true);
      const imageKey = normalizeText(`${name} ${number}`);
      const duplicateIndex = usedImages.get(imageKey) ?? 0;
      usedImages.set(imageKey, duplicateIndex + 1);
      const localSlug = createUniqueSlug(slugify(`${name}-${number}`), globalSlugs, `${owner}-${language}`);
      const id = String(row['Id'] ?? row['ID'] ?? '').trim() || `${collectionSlug}:card:${normalizeText(`${row['Link Liga'] ?? ''}|${name}|${number}|${language}|${condition}`)}`;

      return {
        id,
        kind: 'card',
        name,
        number,
        collection: pokemonCollection,
        language,
        condition,
        year,
        type,
        quantity,
        price,
        forSale,
        showQuantity,
        linkLiga: String(row['Link Liga'] ?? ''),
        linkMyp: String(row['Link MYP'] ?? ''),
        linkCardmarket: String(row['Link Cardmarket'] ?? ''),
        linkTcgplayer: String(row['Link Tcgplayer'] ?? row['Link TCGPlayer'] ?? ''),
        linkPriceCharting: String(row['Link PriceCharting'] ?? ''),
        certainMinimumPrice,
        minimumPrice,
        quickSalePrice,
        leaguePrice,
        secondLeaguePrice,
        thirdLeaguePrice,
        averageLeaguePrice,
        medianLeaguePrice,
        sellersGeneral,
        sellersSpecific,
        buyersGeneral,
        buyersSpecific,
        finalPrice,
        favorite: parseBoolean(row['Favorita'] ?? row['Favorito'], false),
        priceHistory: cardHistory.get(id) ?? [],
        advancedData: { ...row },
        slug: `${collectionSlug}-${localSlug}`,
        image: String(row['Imagem'] ?? ''),
        imageCandidates: cardImageCandidates(collectionSlug, name, number, language, duplicateIndex, String(row['Imagem'] ?? '')),
        ownerName: owner,
        ownerCollectionName: title,
        ownerCollectionSlug: collectionSlug,
        ownerPhone,
        proposalTerms,
        searchText: normalizeText(`${name} ${number} ${pokemonCollection} ${language} ${condition} ${year} ${type} ${owner} ${title}`),
      };
    });

    const boosters: BoosterItem[] = readInventory(folder, 'inventario-boosters')
      .filter((row) => normalizeText(String(row['Tipo de pacote'] ?? '')) !== 'total')
      .map((row) => {
        const name = String(row['Tipo de pacote'] ?? row['Coleção'] ?? row['Nome'] ?? '').trim() || 'Booster sem nome';
        const quantity = parseQuantity(row['Quantidade']);
        const certainMinimumPrice = parseDecimal(row['Minimo Certeiro']) ?? parseDecimal(row['Mínimo Certeiro']);
        const minimumPrice = parseDecimal(row['Preço mínimo']) ?? parseDecimal(row['Minimo']);
        const quickSalePrice = parseDecimal(row['Venda rápida']) ?? parseDecimal(row['Venda Rapida']);
        const leaguePrice = parseDecimal(row['Preço Liga mais barato']) ?? parseDecimal(row['Preço Mais Baixo Liga']) ?? parseDecimal(row['Menor Liga']);
        const secondLeaguePrice = parseDecimal(row['Segundo Menor Liga']);
        const thirdLeaguePrice = parseDecimal(row['Terceiro Menor Liga']);
        const averageLeaguePrice = parseDecimal(row['Media Liga']) ?? parseDecimal(row['Preço médio Liga']) ?? parseDecimal(row['Preço Médio Liga']);
        const medianLeaguePrice = parseDecimal(row['Mediana Liga']);
        const sellersGeneral = parseQuantity(row['Vendedores Geral']);
        const sellersSpecific = parseQuantity(row['Vendedores Específicos']);
        const buyersGeneral = parseQuantity(row['Compradores Geral']);
        const buyersSpecific = parseQuantity(row['Compradores Específicos']);
        const finalPrice = parseDecimal(row['Preço']);
        const price = resolvePublicPrice(finalPrice, averageLeaguePrice, leaguePrice, priceDisplayFallback);
        const forSale = profile.selling !== false && parseBoolean(row['À venda'] ?? row['Venda'], true);
        const localSlug = createUniqueSlug(slugify(name), globalSlugs, `${owner}-${quantity}`);
        const id = String(row['Id'] ?? row['ID'] ?? '').trim() || `${collectionSlug}:booster:${normalizeText(`${row['Link Liga'] ?? ''}|${name}`)}`;
        return {
          id,
          kind: 'booster',
          name,
          quantity,
          price,
          forSale,
          showQuantity,
          linkLiga: String(row['Link Liga'] ?? ''),
          certainMinimumPrice,
          minimumPrice,
          quickSalePrice,
          leaguePrice,
          secondLeaguePrice,
          thirdLeaguePrice,
          averageLeaguePrice,
          medianLeaguePrice,
          sellersGeneral,
          sellersSpecific,
          buyersGeneral,
          buyersSpecific,
          finalPrice,
          priceHistory: boosterHistory.get(id) ?? [],
          advancedData: { ...row },
          slug: `${collectionSlug}-${localSlug}`,
          image: String(row['Imagem'] ?? ''),
          imageCandidates: boosterImageCandidates(collectionSlug, name, String(row['Imagem'] ?? '')),
          ownerName: owner,
          ownerCollectionName: title,
          ownerCollectionSlug: collectionSlug,
          ownerPhone,
          proposalTerms,
          searchText: normalizeText(`${name} booster pacote ${owner} ${title}`),
        };
      });

    const kits: KitItem[] = readInventory(folder, 'inventario-kits').map((row) => {
      const name = String(row['Nome'] ?? '').trim() || 'Kit sem nome';
      const description = String(row['Descrição'] ?? '').trim() || 'Conjunto personalizado pelo colecionador.';
      const quantity = row['Quantidade'] === undefined || row['Quantidade'] === null || row['Quantidade'] === '' ? 1 : parseQuantity(row['Quantidade']);
      const price = parseDecimal(row['Preço']);
      const sourceTotal = parseDecimal(row['Valor avulso'] ?? row['Preço bruto']);
      let rawContents: unknown = row['Conteúdo'];
      if (!Array.isArray(rawContents) && row['Conteúdo JSON']) {
        try { rawContents = JSON.parse(String(row['Conteúdo JSON'])); } catch (_) { rawContents = []; }
      }
      const contentItems: KitContentItem[] = (Array.isArray(rawContents) ? rawContents : [])
        .filter((entry): entry is Record<string, any> => Boolean(entry) && typeof entry === 'object')
        .map((entry) => {
          const kind: 'cards' | 'boosters' = normalizeText(String(entry.kind ?? entry.tipo ?? 'cards')).startsWith('booster') ? 'boosters' : 'cards';
          const itemId = String(entry.itemId ?? entry.item_id ?? entry.Id ?? '').trim();
          const entryName = String(entry.name ?? entry.nome ?? '').trim() || 'Item';
          const source = kind === 'cards'
            ? cards.find((card) => (itemId && card.id === itemId) || (!itemId && normalizeText(card.name) === normalizeText(entryName)))
            : boosters.find((booster) => (itemId && booster.id === itemId) || (!itemId && normalizeText(booster.name) === normalizeText(entryName)));
          return {
            kind,
            itemId: source?.id || itemId,
            slug: source?.slug,
            name: source?.name || entryName,
            quantity: parseQuantity(entry.quantity ?? entry.quantidade) || 1,
            unitPrice: parseDecimal(entry.unitPrice ?? entry.precoUnitario) ?? source?.price ?? null,
            imageCandidates: source?.imageCandidates,
            type: kind === 'cards' && source?.kind === 'card' ? source.type : String(entry.type ?? entry.tipoCarta ?? ''),
            number: kind === 'cards' && source?.kind === 'card' ? source.number : '',
            collection: kind === 'cards' && source?.kind === 'card' ? source.collection : '',
            language: kind === 'cards' && source?.kind === 'card' ? source.language : '',
            condition: kind === 'cards' && source?.kind === 'card' ? source.condition : '',
            year: kind === 'cards' && source?.kind === 'card' ? source.year : '',
            linkLiga: source && 'linkLiga' in source ? source.linkLiga : '',
            ownerName: source?.ownerName || owner,
            ownerCollectionName: source?.ownerCollectionName || title,
            ownerCollectionSlug: source?.ownerCollectionSlug || collectionSlug,
            ownerPhone: source?.ownerPhone || ownerPhone,
          };
        });
      const legacyContents = typeof row['Conteúdo'] === 'string' ? row['Conteúdo'] : '';
      const contents = contentItems.length
        ? contentItems.map((entry) => `${entry.quantity}x ${entry.name}`).join(' | ')
        : legacyContents || 'Conteúdo informado pelo colecionador.';
      const forSale = profile.selling !== false && parseBoolean(row['À venda'] ?? row['Venda'], true);
      const localSlug = createUniqueSlug(slugify(name), globalSlugs, owner);
      const id = String(row['Id'] ?? row['ID'] ?? '').trim() || `${collectionSlug}:kit:${normalizeText(name)}`;
      return {
        id,
        kind: 'kit',
        name,
        description,
        contents,
        contentItems,
        sourceTotal,
        quantity,
        price,
        forSale,
        showQuantity,
        slug: `${collectionSlug}-${localSlug}`,
        image: String(row['Imagem'] ?? ''),
        imageCandidates: kitImageCandidates(collectionSlug, name, String(row['Imagem'] ?? '')),
        ownerName: owner,
        ownerCollectionName: title,
        ownerCollectionSlug: collectionSlug,
        ownerPhone,
        proposalTerms,
        searchText: normalizeText(`${name} ${description} ${contents} ${owner} ${title}`),
      };
    });

    const products: ProductItem[] = readInventory(folder, 'inventario-produtos').map((row, productIndex) => {
      const name = String(row['Nome'] ?? row['Produto'] ?? '').trim() || `Produto ${productIndex + 1}`;
      const price = parseDecimal(row['Preço']);
      const linkLiga = String(row['Link Liga'] ?? '').trim();
      const description = String(row['Descrição'] ?? '').trim() || 'Produto Pokémon lacrado.';
      const quantity = row['Quantidade'] === undefined || row['Quantidade'] === null || row['Quantidade'] === '' ? 1 : parseQuantity(row['Quantidade']);
      const forSale = profile.selling !== false && parseBoolean(row['À venda'] ?? row['Venda'], true);
      const localSlug = createUniqueSlug(slugify(name), globalSlugs, owner);
      const id = String(row['Id'] ?? row['ID'] ?? '').trim() || `${collectionSlug}:product:${normalizeText(`${linkLiga}|${name}`)}`;
      return {
        id, kind: 'product', name, description, quantity, price, forSale, showQuantity: false, linkLiga,
        slug: `${collectionSlug}-${localSlug}`, image: String(row['Imagem'] ?? ''),
        imageCandidates: productImageCandidates(collectionSlug, name, String(row['Imagem'] ?? '')),
        ownerName: owner, ownerCollectionName: title, ownerCollectionSlug: collectionSlug, ownerPhone, proposalTerms,
        searchText: normalizeText(`${name} ${description} produto lacrado ${owner} ${title}`),
      };
    });

    const albums: AlbumItem[] = readInventory(folder, 'inventario-albuns').map((row, albumIndex) => {
      const layout = albumFormat(String(row['Formato'] ?? '3x3'));
      const rawPages = Array.isArray(row['Páginas']) ? row['Páginas'] : row['Páginas JSON'] ?? row['Paginas JSON'] ?? [];
      const pages = parseAlbumPages(rawPages, layout.columns, layout.rows, cards);
      const occupiedSlots = pages.reduce((total, page) => total + page.slots.filter(Boolean).length, 0);
      const firstCard = pages.flatMap((page) => page.slots).find(Boolean);
      const albumName = String(row['Nome'] ?? '').trim() || `Álbum ${albumIndex + 1}`;
      const albumId = String(row['Id'] ?? row['ID'] ?? '').trim() || `${collectionSlug}-album-${albumIndex + 1}`;
      return {
        id: albumId,
        slug: `${slugify(albumId || albumName)}-${albumIndex + 1}`,
        ownerName: owner, ownerCollectionName: title, ownerCollectionSlug: collectionSlug,
        searchText: normalizeText(`${albumName} ${row['Descrição'] ?? ''} ${owner} ${title}`),
        name: albumName,
        description: String(row['Descrição'] ?? ''),
        format: layout.format,
        columns: layout.columns,
        rows: layout.rows,
        pages,
        occupiedSlots,
        totalSlots: pages.length * layout.columns * layout.rows,
        coverImageCandidates: firstCard?.imageCandidates || (row['Imagem'] ? [String(row['Imagem'])] : []),
      };
    });

    const allItems: CatalogItem[] = [...cards, ...boosters, ...kits, ...products];
    const totalUnits = allItems.reduce((total, item) => total + item.quantity, 0);
    const estimatedValue = [...cards, ...boosters, ...products].reduce((total, item) => total + (item.price ?? 0) * item.quantity, 0);
    const coverItems = [...allItems]
      .sort((a, b) => (b.price ?? 0) - (a.price ?? 0))
      .slice(0, 4);

    return {
      slug: collectionSlug,
      owner,
      title,
      description,
      selling: profile.selling !== false,
      featured: profile.featured === true,
      phone: ownerPhone,
      proposalTerms,
      profilePhoto,
      palette,
      cards,
      boosters,
      kits,
      products,
      albums,
      movements,
      priceDisplayFallback,
      totalItems: allItems.length,
      totalUnits,
      estimatedValue,
      coverItems,
      searchText: normalizeText(`${owner} ${title} ${description}`),
    };
  });

  return collectionsCache;
};

export const getCollection = (slug: string): CollectorCollection | undefined =>
  getCollections().find((collection) => collection.slug === slug);

export const getEditableCollections = () => getCollections().map((collection) => {
  const folderName = getCollectionFolders().find((folder) => slugify(folder) === collection.slug) || collection.slug;
  const profile = readProfile(join(collectionsRoot, folderName));
  return {
    slug: collection.slug,
    profile: {
      owner: collection.owner,
      title: collection.title,
      description: collection.description,
      email: profile.email || '',
      phone: profile.phone || '',
      password: profile.password || '',
      selling: collection.selling,
      showQuantity: profile.showQuantity !== false,
      featured: collection.featured,
      proposalTerms: collection.proposalTerms,
      version: Number((profile as Record<string, unknown>).version || 1),
      collectionId: folderName,
      profilePhoto: collection.profilePhoto,
      palette: collection.palette,
      priceDisplayFallback: collection.priceDisplayFallback,
    },
    cards: collection.cards.map(({ id, name, number, collection: set, language, condition, year, type, quantity, finalPrice, forSale, linkLiga, linkMyp, linkCardmarket, linkTcgplayer, linkPriceCharting, certainMinimumPrice, minimumPrice, quickSalePrice, leaguePrice, secondLeaguePrice, thirdLeaguePrice, averageLeaguePrice, medianLeaguePrice, sellersGeneral, sellersSpecific, buyersGeneral, buyersSpecific, favorite, priceHistory, advancedData, image, imageCandidates }) => ({
      id, name, number, collection: set, language, condition, year, type, quantity, price: finalPrice, forSale, linkLiga, linkMyp, linkCardmarket, linkTcgplayer, linkPriceCharting, certainMinimumPrice, minimumPrice, quickSalePrice, leaguePrice, secondLeaguePrice, thirdLeaguePrice, averageLeaguePrice, medianLeaguePrice, sellersGeneral, sellersSpecific, buyersGeneral, buyersSpecific, favorite, priceHistory, advancedData, image, imageCandidates,
    })),
    boosters: collection.boosters.map(({ id, name, quantity, finalPrice, forSale, linkLiga, certainMinimumPrice, minimumPrice, quickSalePrice, leaguePrice, secondLeaguePrice, thirdLeaguePrice, averageLeaguePrice, medianLeaguePrice, sellersGeneral, sellersSpecific, buyersGeneral, buyersSpecific, priceHistory, advancedData, image, imageCandidates }) => ({ id, name, quantity, price: finalPrice, forSale, linkLiga, certainMinimumPrice, minimumPrice, quickSalePrice, leaguePrice, secondLeaguePrice, thirdLeaguePrice, averageLeaguePrice, medianLeaguePrice, sellersGeneral, sellersSpecific, buyersGeneral, buyersSpecific, priceHistory, advancedData, image, imageCandidates })),
    kits: collection.kits.map(({ id, name, description, contents, contentItems, sourceTotal, quantity, price, forSale, image, imageCandidates }) => ({ id, name, description, contents, contentItems, sourceTotal, quantity, price, forSale, image, imageCandidates })),
    products: collection.products.map(({ id, name, description, quantity, price, forSale, linkLiga, image, imageCandidates }) => ({ id, name, description, quantity, price, forSale, linkLiga, image, imageCandidates })),
    albums: collection.albums.map((album) => ({
      albumId: album.id,
      name: album.name,
      description: album.description,
      format: album.format,
      pages: album.pages.map((page) => ({ slots: page.slots.map((slot) => slot ? { ...slot } : null) })),
      imageCandidates: album.coverImageCandidates,
    })),
    movements: collection.movements.map((movement) => ({ ...movement })),
  };
});

export const getCards = (collectionSlug?: string): CardItem[] => {
  const collections = collectionSlug ? getCollections().filter((item) => item.slug === collectionSlug) : getCollections();
  return collections.flatMap((collection) => collection.cards);
};

export const getBoosters = (collectionSlug?: string): BoosterItem[] => {
  const collections = collectionSlug ? getCollections().filter((item) => item.slug === collectionSlug) : getCollections();
  return collections.flatMap((collection) => collection.boosters);
};

export const getKits = (collectionSlug?: string): KitItem[] => {
  const collections = collectionSlug ? getCollections().filter((item) => item.slug === collectionSlug) : getCollections();
  return collections.flatMap((collection) => collection.kits);
};

export const getProducts = (collectionSlug?: string): ProductItem[] => {
  const collections = collectionSlug ? getCollections().filter((item) => item.slug === collectionSlug) : getCollections();
  return collections.flatMap((collection) => collection.products);
};

export const getAlbums = (collectionSlug?: string): AlbumItem[] => {
  const collections = collectionSlug ? getCollections().filter((item) => item.slug === collectionSlug) : getCollections();
  return collections.flatMap((collection) => collection.albums);
};

export const getAllItems = (): CatalogItem[] => [...getCards(), ...getBoosters(), ...getKits(), ...getProducts()];

export const shuffleItems = <T>(items: T[]): T[] => {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }
  return result;
};

export const getItemPrice = (item: CatalogItem): number | null => item.price;

export const formatBRL = (value: number | null): string => {
  if (value === null) return 'Consultar';
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2,
  }).format(value);
};
