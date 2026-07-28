import cardsCsv from '../data/inventario-cartas.csv?raw';
import boostersCsv from '../data/inventario-boosters.csv?raw';

export type CatalogKind = 'card' | 'booster';

export interface CardItem {
  kind: 'card';
  name: string;
  number: string;
  collection: string;
  language: string;
  condition: string;
  year: string;
  type: string;
  quantity: number;
  ligaPrice: number | null;
  slug: string;
  imageCandidates: string[];
  searchText: string;
}

export interface BoosterItem {
  kind: 'booster';
  name: string;
  quantity: number;
  price: number | null;
  slug: string;
  imageCandidates: string[];
  searchText: string;
}

export type CatalogItem = CardItem | BoosterItem;

type CsvRow = Record<string, string>;

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
    .replace(/-+/g, '-')
    .trim();

const unique = <T>(values: T[]): T[] => [...new Set(values)];

const addExtensions = (stems: string[]): string[] =>
  unique(stems.flatMap((stem) => ['jpg', 'jpeg', 'png', 'webp'].map((extension) => `${stem}.${extension}`)));

const cardImageCandidates = (
  name: string,
  number: string,
  language: string,
  duplicateIndex: number,
): string[] => {
  const cleanName = cleanFilePart(name);
  const cleanNumber = cleanFilePart(number);
  const cleanLanguage = cleanFilePart(language);
  const asciiName = cleanFilePart(name.normalize('NFD').replace(/[\u0300-\u036f]/g, ''));
  const asciiNumber = cleanFilePart(number.normalize('NFD').replace(/[\u0300-\u036f]/g, ''));
  const asciiLanguage = cleanFilePart(language.normalize('NFD').replace(/[\u0300-\u036f]/g, ''));
  const canonical = `${cleanName}_${cleanNumber}`;
  const asciiCanonical = `${asciiName}_${asciiNumber}`;
  const duplicateNumber = duplicateIndex + 1;

  const stems = unique([
    canonical,
    asciiCanonical,
    `${cleanName}-${cleanNumber}`,
    `${asciiName}-${asciiNumber}`,
    `${canonical}_${cleanLanguage}`,
    `${asciiCanonical}_${asciiLanguage}`,
    ...(duplicateIndex > 0
      ? [
          `${canonical} (${duplicateIndex})`,
          `${asciiCanonical} (${duplicateIndex})`,
          `${canonical}_${duplicateNumber}`,
          `${asciiCanonical}_${duplicateNumber}`,
          `${canonical}-${duplicateNumber}`,
          `${asciiCanonical}-${duplicateNumber}`,
        ]
      : []),
  ]);
  return addExtensions(stems);
};

const boosterImageCandidates = (name: string): string[] => {
  const cleanName = cleanFilePart(name);
  const asciiName = cleanFilePart(name.normalize('NFD').replace(/[\u0300-\u036f]/g, ''));
  return addExtensions(
    unique([
      cleanName,
      asciiName,
      `${cleanName}_Booster`,
      `${asciiName}_Booster`,
      `Booster_${cleanName}`,
      `Booster_${asciiName}`,
    ]),
  );
};

const createUniqueSlug = (base: string, used: Map<string, number>, suffix: string): string => {
  const count = used.get(base) ?? 0;
  used.set(base, count + 1);
  if (count === 0) return base;
  return `${base}-${slugify(suffix)}-${count + 1}`;
};

let cardsCache: CardItem[] | null = null;
let boostersCache: BoosterItem[] | null = null;

export const getCards = (): CardItem[] => {
  if (cardsCache) return cardsCache;

  const usedSlugs = new Map<string, number>();
  const usedImages = new Map<string, number>();
  cardsCache = parseCsv(cardsCsv).map((row) => {
    const name = row['Nome'] || 'Carta sem nome';
    const number = row['Número'] || 'Sem número';
    const collection = row['Coleção'] || 'Coleção não informada';
    const language = row['Idioma'] || 'Não informado';
    const condition = row['Estado'] || 'Não informado';
    const year = row['Ano'] || 'Não informado';
    const type = row['Tipo'] || 'Não informado';
    const quantity = parseQuantity(row['Quantidade']);
    const ligaPrice = parseDecimal(row['Menor Liga']);
    const slug = createUniqueSlug(slugify(`${name}-${number}`), usedSlugs, language);
    const imageKey = normalizeText(`${name} ${number}`);
    const duplicateIndex = usedImages.get(imageKey) ?? 0;
    usedImages.set(imageKey, duplicateIndex + 1);

    return {
      kind: 'card',
      name,
      number,
      collection,
      language,
      condition,
      year,
      type,
      quantity,
      ligaPrice,
      slug,
      imageCandidates: cardImageCandidates(name, number, language, duplicateIndex),
      searchText: normalizeText(`${name} ${number} ${collection} ${language} ${condition} ${year} ${type}`),
    };
  });

  return cardsCache;
};

export const getBoosters = (): BoosterItem[] => {
  if (boostersCache) return boostersCache;

  const usedSlugs = new Map<string, number>();
  boostersCache = parseCsv(boostersCsv)
    .filter((row) => normalizeText(row['Tipo de pacote'] || '') !== 'total')
    .map((row) => {
      const name = row['Tipo de pacote'] || 'Booster sem nome';
      const quantity = parseQuantity(row['Quantidade']);
      const price = parseDecimal(row['Preço']);
      const slug = createUniqueSlug(slugify(name), usedSlugs, String(quantity));

      return {
        kind: 'booster',
        name,
        quantity,
        price,
        slug,
        imageCandidates: boosterImageCandidates(name),
        searchText: normalizeText(name),
      };
    });

  return boostersCache;
};

export const getItemPrice = (item: CatalogItem): number | null =>
  item.kind === 'card' ? item.ligaPrice : item.price;

export const formatBRL = (value: number | null): string => {
  if (value === null) return 'Consultar';
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2,
  }).format(value);
};
