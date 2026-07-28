import cardsCsv from '../data/inventario-cartas.csv?raw';
import boostersCsv from '../data/inventario-boosters.csv?raw';
import { readdirSync } from 'node:fs';
import { join } from 'node:path';

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
  price: number | null;
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
    .trim();

const asciiFilePart = (value: string): string =>
  cleanFilePart(value.normalize('NFD').replace(/[\u0300-\u036f]/g, ''));

const unique = <T>(values: T[]): T[] => [...new Set(values.filter(Boolean))];

const supportedImage = /\.(?:jpe?g|png|webp)$/i;
const availableImageFiles = (() => {
  try {
    return readdirSync(join(process.cwd(), 'public', 'imagens'), { withFileTypes: true })
      .filter((entry) => entry.isFile() && supportedImage.test(entry.name))
      .map((entry) => entry.name);
  } catch (_) {
    return [] as string[];
  }
})();

const imagesByNormalizedStem = new Map<string, string[]>();
availableImageFiles.forEach((filename) => {
  const stem = filename.replace(/\.[^.]+$/, '');
  const key = normalizeText(stem);
  const current = imagesByNormalizedStem.get(key) ?? [];
  current.push(filename);
  imagesByNormalizedStem.set(key, current);
});

const findExistingImages = (name: string, number?: string): string[] => {
  const exactKeys = number
    ? [normalizeText(`${name} ${number}`)]
    : [normalizeText(name), normalizeText(`${name} booster`), normalizeText(`booster ${name}`)];
  const exact = unique(exactKeys.flatMap((key) => imagesByNormalizedStem.get(key) ?? []));
  if (exact.length > 0) return exact;

  const normalizedName = normalizeText(name);
  const normalizedNumber = normalizeText(number ?? '');
  return availableImageFiles.filter((filename) => {
    const key = normalizeText(filename.replace(/\.[^.]+$/, ''));
    if (number) return key.includes(normalizedName) && key.includes(normalizedNumber);
    return key.includes(normalizedName);
  });
};

const addExtensions = (stems: string[]): string[] =>
  unique(stems.flatMap((stem) => ['jpg', 'jpeg', 'png', 'webp'].map((extension) => `${stem}.${extension}`)));

const joinFileParts = (left: string, right: string): string[] =>
  unique([
    `${left}_${right}`,
    `${left}-${right}`,
    `${left} ${right}`,
  ]);

const cardImageCandidates = (
  name: string,
  number: string,
  language: string,
  duplicateIndex: number,
): string[] => {
  const names = unique([cleanFilePart(name), asciiFilePart(name)]);
  const numbers = unique([
    cleanFilePart(number),
    asciiFilePart(number),
    cleanFilePart(number).replace(/\s+/g, ''),
    asciiFilePart(number).replace(/\s+/g, ''),
  ]);
  const languages = unique([cleanFilePart(language), asciiFilePart(language)]);
  const duplicateNumber = duplicateIndex + 1;

  const canonical = unique(names.flatMap((cardName) => numbers.flatMap((cardNumber) => joinFileParts(cardName, cardNumber))));
  const languageVariants = duplicateIndex > 0
    ? canonical.flatMap((stem) => languages.map((languageName) => `${stem}_${languageName}`))
    : [];
  const duplicateVariants = duplicateIndex > 0
    ? canonical.flatMap((stem) => [
        `${stem} (${duplicateIndex})`,
        `${stem} (${duplicateNumber})`,
        `${stem}_${duplicateNumber}`,
        `${stem}-${duplicateNumber}`,
      ])
    : [];

  const generated = addExtensions(unique([...canonical, ...duplicateVariants, ...languageVariants]));
  const existing = findExistingImages(name, number);
  const preferredExisting = existing.length > 1 ? [existing[duplicateIndex] ?? existing[0], ...existing] : existing;
  return unique([...preferredExisting, ...generated]);
};

const boosterImageCandidates = (name: string): string[] => {
  const names = unique([cleanFilePart(name), asciiFilePart(name)]);
  const stems = names.flatMap((boosterName) => [
    boosterName,
    `${boosterName}_Booster`,
    `${boosterName}-Booster`,
    `${boosterName} Booster`,
    `Booster_${boosterName}`,
    `Booster-${boosterName}`,
    `Booster ${boosterName}`,
    boosterName.replace(/\s+/g, '_'),
    boosterName.replace(/\s+/g, '-'),
  ]);
  return unique([...findExistingImages(name), ...addExtensions(unique(stems))]);
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
    const price = parseDecimal(row['Menor Liga']);
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
      price,
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

export const getItemPrice = (item: CatalogItem): number | null => item.price;

export const formatBRL = (value: number | null): string => {
  if (value === null) return 'Consultar';
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2,
  }).format(value);
};
