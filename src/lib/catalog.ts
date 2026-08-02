import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

export type CatalogKind = 'card' | 'booster' | 'kit';

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
}

export interface CardItem extends OwnedItemBase {
  kind: 'card';
  number: string;
  collection: string;
  language: string;
  condition: string;
  year: string;
  type: string;
}

export interface BoosterItem extends OwnedItemBase {
  kind: 'booster';
}

export interface KitItem extends OwnedItemBase {
  kind: 'kit';
  description: string;
  contents: string;
}

export type CatalogItem = CardItem | BoosterItem | KitItem;

export interface CollectorCollection {
  slug: string;
  owner: string;
  title: string;
  description: string;
  selling: boolean;
  featured: boolean;
  cards: CardItem[];
  boosters: BoosterItem[];
  kits: KitItem[];
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
};

const collectionsRoot = [
  join(process.cwd(), 'src', 'coleções'),
  join(process.cwd(), 'src', 'colecoes'),
].find((path) => existsSync(path)) ?? join(process.cwd(), 'src', 'coleções');

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
    const usedImages = new Map<string, number>();

    const cards: CardItem[] = readRows(folder, 'inventario-cartas.csv').map((row) => {
      const name = row['Nome'] || 'Carta sem nome';
      const number = row['Número'] || 'Sem número';
      const pokemonCollection = row['Coleção'] || 'Coleção não informada';
      const language = row['Idioma'] || 'Não informado';
      const condition = row['Estado'] || 'Não informado';
      const year = row['Ano'] || 'Não informado';
      const type = row['Tipo'] || 'Não informado';
      const quantity = parseQuantity(row['Quantidade']);
      const price = parseDecimal(row['Preço']) ?? parseDecimal(row['Menor Liga']);
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
        slug: `${collectionSlug}-${localSlug}`,
        imageCandidates: cardImageCandidates(collectionSlug, name, number, language, duplicateIndex),
        ownerName: owner,
        ownerCollectionName: title,
        ownerCollectionSlug: collectionSlug,
        searchText: normalizeText(`${name} ${number} ${pokemonCollection} ${language} ${condition} ${year} ${type} ${owner} ${title}`),
      };
    });

    const boosters: BoosterItem[] = readRows(folder, 'inventario-boosters.csv')
      .filter((row) => normalizeText(row['Tipo de pacote'] || '') !== 'total')
      .map((row) => {
        const name = row['Tipo de pacote'] || 'Booster sem nome';
        const quantity = parseQuantity(row['Quantidade']);
        const price = parseDecimal(row['Preço']);
        const localSlug = createUniqueSlug(slugify(name), globalSlugs, `${owner}-${quantity}`);
        return {
          kind: 'booster',
          name,
          quantity,
          price,
          slug: `${collectionSlug}-${localSlug}`,
          imageCandidates: boosterImageCandidates(collectionSlug, name),
          ownerName: owner,
          ownerCollectionName: title,
          ownerCollectionSlug: collectionSlug,
          searchText: normalizeText(`${name} booster pacote ${owner} ${title}`),
        };
      });

    const kits: KitItem[] = readRows(folder, 'inventario-kits.csv').map((row) => {
      const name = row['Nome'] || 'Kit sem nome';
      const description = row['Descrição'] || 'Conjunto personalizado pelo colecionador.';
      const contents = row['Conteúdo'] || 'Conteúdo informado pelo colecionador.';
      const quantity = parseQuantity(row['Quantidade']) || 1;
      const price = parseDecimal(row['Preço']);
      const localSlug = createUniqueSlug(slugify(name), globalSlugs, owner);
      return {
        kind: 'kit',
        name,
        description,
        contents,
        quantity,
        price,
        slug: `${collectionSlug}-${localSlug}`,
        imageCandidates: kitImageCandidates(collectionSlug, name, row['Imagem'] || ''),
        ownerName: owner,
        ownerCollectionName: title,
        ownerCollectionSlug: collectionSlug,
        searchText: normalizeText(`${name} ${description} ${contents} ${owner} ${title}`),
      };
    });

    const allItems: CatalogItem[] = [...cards, ...boosters, ...kits];
    const totalUnits = allItems.reduce((total, item) => total + item.quantity, 0);
    const estimatedValue = allItems.reduce((total, item) => total + (item.price ?? 0) * item.quantity, 0);
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
      cards,
      boosters,
      kits,
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
