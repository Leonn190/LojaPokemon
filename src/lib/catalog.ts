import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

export type CatalogKind = 'card' | 'booster' | 'kit';
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
  kind: CatalogKind;
  name: string;
  quantity: number;
  price: number | null;
  slug: string;
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
  minimumPrice: number | null;
  quickSalePrice: number | null;
  leaguePrice: number | null;
  finalPrice: number | null;
}

export interface BoosterItem extends OwnedItemBase {
  kind: 'booster';
  linkLiga: string;
  minimumPrice: number | null;
  quickSalePrice: number | null;
  leaguePrice: number | null;
  finalPrice: number | null;
}

export interface KitContentItem {
  kind: 'cards' | 'boosters';
  name: string;
  quantity: number;
  unitPrice: number | null;
  imageCandidates?: string[];
}

export interface KitItem extends OwnedItemBase {
  kind: 'kit';
  description: string;
  contents: string;
  contentItems: KitContentItem[];
  sourceTotal: number | null;
}

export type CatalogItem = CardItem | BoosterItem | KitItem;

export interface AlbumCardReference {
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
  cards: CardItem[];
  boosters: BoosterItem[];
  kits: KitItem[];
  albums: AlbumItem[];
  totalItems: number;
  totalUnits: number;
  estimatedValue: number;
  coverItems: CatalogItem[];
  searchText: string;
}

type CsvRow = Record<string, string>;
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

const readProfile = (folder: string): ProfileData => {
  try {
    return JSON.parse(readFileSync(join(folder, 'perfil.json'), 'utf8')) as ProfileData;
  } catch (_) {
    return {};
  }
};

const parseDecimal = (value: string | number | null | undefined): number | null => {
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

const parseQuantity = (value: string | number | null | undefined): number => {
  const parsed = Number(String(value ?? '').replace(/[^0-9-]/g, ''));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
};

const parseBoolean = (value: string | boolean | null | undefined, fallback: boolean): boolean => {
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
  const localFolder = `colecoes/${collectionSlug}/${kind === 'card' ? 'imagens' : kind === 'booster' ? 'imagensboosters' : 'imagenskits'}`;
  const globalFolder = kind === 'card' ? 'imagens' : kind === 'booster' ? 'imagensboosters' : 'imagenskits';
  return unique([...readImageFiles(localFolder), ...readImageFiles(globalFolder)]);
};

const compactImageKey = (value: string): string => normalizeText(value).replace(/\s+/g, '');
const stemOf = (path: string): string => path.split('/').pop()?.replace(/\.[^.]+$/, '') ?? '';

const cardImageCandidates = (
  collectionSlug: string,
  name: string,
  number: string,
  language: string,
  duplicateIndex: number,
): string[] => {
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
  return unique([...preferredExisting, ...generated]);
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

const boosterImageCandidates = (collectionSlug: string, name: string): string[] => {
  const pool = imagePool(collectionSlug, 'booster');
  const keys = boosterKeys(name);
  const existing = pool
    .filter((path) => {
      const stem = compactImageKey(stemOf(path));
      return keys.some((key) => stem === key || (stem.startsWith(key) && /^\d+$/.test(stem.slice(key.length))));
    })
    .sort((left, right) => boosterVariantNumber(left) - boosterVariantNumber(right) || left.localeCompare(right, 'pt-BR'));
  if (existing.length > 0) return existing;

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
  return stems.flatMap((stem) => ['jpg', 'jpeg', 'png', 'webp', 'avif'].map((extension) => `imagensboosters/${stem}.${extension}`));
};

const kitImageCandidates = (collectionSlug: string, name: string, explicit: string): string[] => {
  const pool = imagePool(collectionSlug, 'kit');
  const explicitCandidates = explicit
    ? [explicit.includes('/') ? explicit : `imagenskits/${explicit}`]
    : [];
  const key = normalizeText(name);
  const existing = pool.filter((path) => normalizeText(stemOf(path)).includes(key));
  const stems = unique([cleanFilePart(name), asciiFilePart(name), slugify(name)]);
  const generated = stems.flatMap((stem) => ['jpg', 'jpeg', 'png', 'webp', 'avif'].map((extension) => `imagenskits/${stem}.${extension}`));
  return unique([...explicitCandidates, ...existing, ...generated]);
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
  const linkLiga = String(slot.linkLiga ?? slot.link ?? '').trim();
  const language = String(slot.language ?? slot.idioma ?? '').trim();
  const condition = String(slot.condition ?? slot.estado ?? '').trim();
  const name = String(slot.name ?? slot.nome ?? '').trim();
  const number = String(slot.number ?? slot.numero ?? slot['número'] ?? '').trim();
  const linkKey = normalizeReferenceLink(linkLiga);
  const exact = cards.find((card) => linkKey && normalizeReferenceLink(card.linkLiga) === linkKey && (!language || normalizeText(card.language) === normalizeText(language)) && (!condition || normalizeText(card.condition) === normalizeText(condition)));
  const byLink = exact ?? cards.find((card) => linkKey && normalizeReferenceLink(card.linkLiga) === linkKey);
  const byIdentity = byLink ?? cards.find((card) => name && normalizeText(card.name) === normalizeText(name) && (!number || normalizeText(card.number) === normalizeText(number)));
  const card = byIdentity;
  const candidates = card?.imageCandidates ?? (Array.isArray(slot.imageCandidates) ? slot.imageCandidates.map(String) : []);
  if (!card && !linkLiga && !name) return null;
  return {
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

const parseAlbumPages = (raw: string, columns: number, rows: number, cards: CardItem[]): AlbumPage[] => {
  const capacity = columns * rows;
  let parsed: unknown = [];
  try { parsed = JSON.parse(raw || '[]'); } catch (_) { parsed = []; }
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
    const description = profile.description?.trim() || 'Coleção Pokémon organizada no Nexus TCG.';
    const showQuantity = profile.showQuantity !== false;
    const proposalTerms = normalizeProposalTerms(profile);
    const ownerPhone = profile.phone?.trim() || '';
    const usedImages = new Map<string, number>();

    const cards: CardItem[] = readRows(folder, 'inventario-cartas.csv').map((row) => {
      const name = row['Nome'] || 'Carta sem nome';
      const number = row['Número'] || row['Numeração'] || 'Sem número';
      const pokemonCollection = row['Coleção'] || 'Coleção não informada';
      const language = row['Idioma'] || 'Não informado';
      const condition = row['Estado'] || 'Não informado';
      const year = row['Ano'] || 'Não informado';
      const type = row['Tipo'] || 'Não informado';
      const quantity = parseQuantity(row['Quantidade']);
      const minimumPrice = parseDecimal(row['Minimo']) ?? parseDecimal(row['Preço mínimo']);
      const quickSalePrice = parseDecimal(row['Venda Rapida']) ?? parseDecimal(row['Venda rápida']);
      const leaguePrice = parseDecimal(row['Menor Liga']) ?? parseDecimal(row['Preço Liga mais barato']);
      const finalPrice = parseDecimal(row['Preço']);
      const price = finalPrice ?? leaguePrice;
      const forSale = profile.selling !== false && parseBoolean(row['À venda'] ?? row['Venda'], true);
      const imageKey = normalizeText(`${name} ${number}`);
      const duplicateIndex = usedImages.get(imageKey) ?? 0;
      usedImages.set(imageKey, duplicateIndex + 1);
      const localSlug = createUniqueSlug(slugify(`${name}-${number}`), globalSlugs, `${owner}-${language}`);

      return {
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
        linkLiga: row['Link Liga'] || '',
        linkMyp: row['Link MYP'] || '',
        linkCardmarket: row['Link Cardmarket'] || '',
        linkTcgplayer: row['Link Tcgplayer'] || row['Link TCGPlayer'] || '',
        linkPriceCharting: row['Link PriceCharting'] || '',
        minimumPrice,
        quickSalePrice,
        leaguePrice,
        finalPrice,
        slug: `${collectionSlug}-${localSlug}`,
        imageCandidates: cardImageCandidates(collectionSlug, name, number, language, duplicateIndex),
        ownerName: owner,
        ownerCollectionName: title,
        ownerCollectionSlug: collectionSlug,
        ownerPhone,
        proposalTerms,
        searchText: normalizeText(`${name} ${number} ${pokemonCollection} ${language} ${condition} ${year} ${type} ${owner} ${title}`),
      };
    });

    const boosters: BoosterItem[] = readRows(folder, 'inventario-boosters.csv')
      .filter((row) => normalizeText(row['Tipo de pacote'] || '') !== 'total')
      .map((row) => {
        const name = row['Coleção'] || row['Tipo de pacote'] || 'Booster sem nome';
        const quantity = parseQuantity(row['Quantidade']);
        const minimumPrice = parseDecimal(row['Preço mínimo']) ?? parseDecimal(row['Minimo']);
        const quickSalePrice = parseDecimal(row['Venda rápida']) ?? parseDecimal(row['Venda Rapida']);
        const leaguePrice = parseDecimal(row['Preço Liga mais barato']) ?? parseDecimal(row['Preço Mais Baixo Liga']) ?? parseDecimal(row['Menor Liga']);
        const finalPrice = parseDecimal(row['Preço']);
        const price = finalPrice ?? leaguePrice;
        const forSale = profile.selling !== false && parseBoolean(row['À venda'] ?? row['Venda'], true);
        const localSlug = createUniqueSlug(slugify(name), globalSlugs, `${owner}-${quantity}`);
        return {
          kind: 'booster',
          name,
          quantity,
          price,
          forSale,
          showQuantity,
          linkLiga: row['Link Liga'] || '',
          minimumPrice,
          quickSalePrice,
          leaguePrice,
          finalPrice,
          slug: `${collectionSlug}-${localSlug}`,
          imageCandidates: boosterImageCandidates(collectionSlug, name),
          ownerName: owner,
          ownerCollectionName: title,
          ownerCollectionSlug: collectionSlug,
          ownerPhone,
          proposalTerms,
          searchText: normalizeText(`${name} booster pacote ${owner} ${title}`),
        };
      });

    const kits: KitItem[] = readRows(folder, 'inventario-kits.csv').map((row) => {
      const name = row['Nome'] || 'Kit sem nome';
      const description = row['Descrição'] || 'Conjunto personalizado pelo colecionador.';
      const contents = row['Conteúdo'] || 'Conteúdo informado pelo colecionador.';
      const quantity = parseQuantity(row['Quantidade']) || 1;
      const price = parseDecimal(row['Preço']);
      const sourceTotal = parseDecimal(row['Valor avulso']);
      let contentItems: KitContentItem[] = [];
      try {
        const parsed = JSON.parse(row['Conteúdo JSON'] || '[]');
        if (Array.isArray(parsed)) contentItems = parsed;
      } catch (_) {}
      const forSale = profile.selling !== false && parseBoolean(row['À venda'] ?? row['Venda'], true);
      const localSlug = createUniqueSlug(slugify(name), globalSlugs, owner);
      return {
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
        imageCandidates: kitImageCandidates(collectionSlug, name, row['Imagem'] || ''),
        ownerName: owner,
        ownerCollectionName: title,
        ownerCollectionSlug: collectionSlug,
        ownerPhone,
        proposalTerms,
        searchText: normalizeText(`${name} ${description} ${contents} ${owner} ${title}`),
      };
    });

    const albums: AlbumItem[] = readRows(folder, 'inventario-albuns.csv').map((row, albumIndex) => {
      const layout = albumFormat(row['Formato'] || '3x3');
      const pages = parseAlbumPages(row['Páginas JSON'] || row['Paginas JSON'] || '', layout.columns, layout.rows, cards);
      const occupiedSlots = pages.reduce((total, page) => total + page.slots.filter(Boolean).length, 0);
      const firstCard = pages.flatMap((page) => page.slots).find(Boolean);
      return {
        id: row['ID'] || `${collectionSlug}-album-${albumIndex + 1}`,
        name: row['Nome'] || `Álbum ${albumIndex + 1}`,
        description: row['Descrição'] || '',
        format: layout.format,
        columns: layout.columns,
        rows: layout.rows,
        pages,
        occupiedSlots,
        totalSlots: pages.length * layout.columns * layout.rows,
        coverImageCandidates: firstCard?.imageCandidates || (row['Imagem'] ? [row['Imagem']] : []),
      };
    });

    const allItems: CatalogItem[] = [...cards, ...boosters, ...kits];
    const totalUnits = allItems.reduce((total, item) => total + item.quantity, 0);
    const estimatedValue = [...cards, ...boosters].reduce((total, item) => total + (item.price ?? 0) * item.quantity, 0);
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
      cards,
      boosters,
      kits,
      albums,
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
    },
    cards: collection.cards.map(({ name, number, collection: set, language, condition, year, type, quantity, finalPrice, forSale, linkLiga, linkMyp, linkCardmarket, linkTcgplayer, linkPriceCharting, minimumPrice, quickSalePrice, leaguePrice, imageCandidates }) => ({
      name, number, collection: set, language, condition, year, type, quantity, price: finalPrice, forSale, linkLiga, linkMyp, linkCardmarket, linkTcgplayer, linkPriceCharting, minimumPrice, quickSalePrice, leaguePrice, imageCandidates,
    })),
    boosters: collection.boosters.map(({ name, quantity, finalPrice, forSale, linkLiga, minimumPrice, quickSalePrice, leaguePrice, imageCandidates }) => ({ name, quantity, price: finalPrice, forSale, linkLiga, minimumPrice, quickSalePrice, leaguePrice, imageCandidates })),
    kits: collection.kits.map(({ name, description, contents, contentItems, sourceTotal, quantity, price, forSale, imageCandidates }) => ({ name, description, contents, contentItems, sourceTotal, quantity, price, forSale, imageCandidates })),
    albums: collection.albums.map((album) => ({
      albumId: album.id,
      name: album.name,
      description: album.description,
      format: album.format,
      pages: album.pages.map((page) => ({ slots: page.slots.map((slot) => slot ? { ...slot } : null) })),
      imageCandidates: album.coverImageCandidates,
    })),
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

export const getAllItems = (): CatalogItem[] => [...getCards(), ...getBoosters(), ...getKits()];

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
