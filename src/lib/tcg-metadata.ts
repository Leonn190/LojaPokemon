export type TcgGroupId = 'pokemon' | 'trainer' | 'energy';
export type TcgEraId = 'mega_evolution' | 'scarlet_violet' | 'sword_shield' | 'sun_moon' | 'xy' | 'black_white';

export interface TcgOption { id: string; label: string; code?: string; }
export interface TcgEraConfig {
  id: TcgEraId;
  label: string;
  collections: TcgOption[];
  classes: Record<TcgGroupId, string[]>;
  pokemonTypes: string[];
}

const MODERN_TYPES = ['Grama', 'Fogo', 'Água', 'Elétrico', 'Psíquico', 'Luta', 'Escuridão', 'Metálico', 'Dragão', 'Incolor'];
const FAIRY_TYPES = ['Grama', 'Fogo', 'Água', 'Elétrico', 'Psíquico', 'Luta', 'Escuridão', 'Metálico', 'Fada', 'Dragão', 'Incolor'];

export const TCG_CONFIG = {
  eras: {
    mega_evolution: {
      id: 'mega_evolution', label: 'MegaEvolução',
      collections: [
        { id: 'mega_evolution', label: 'Megaevolução', code: 'ME01' },
        { id: 'phantasmal_flames', label: 'Fogo Fantasmagórico', code: 'ME02' },
        { id: 'ascended_heroes', label: 'Heróis Excelsos', code: 'ME2.5' },
        { id: 'perfect_balance', label: 'Equilíbrio Perfeito', code: 'ME03' },
        { id: 'rising_chaos', label: 'Caos Ascendente', code: 'ME04' },
        { id: 'absolute_darkness', label: 'Escuridão Absoluta', code: 'ME05' },
      ],
      classes: {
        pokemon: ['Normal', 'ex', 'Mega ex', 'Full Art', 'Ilustração Rara', 'Art Secreta', 'Golden', 'Mega Attack Rare'],
        trainer: ['Normal', 'Full Art', 'Art Secreta'],
        energy: ['Normal'],
      },
      pokemonTypes: MODERN_TYPES,
    },
    scarlet_violet: {
      id: 'scarlet_violet', label: 'Scarlet Violet',
      collections: [
        { id: 'scarlet_violet', label: 'Escarlate e Violeta', code: 'SV01' },
        { id: 'paldea_evolved', label: 'Evoluções em Paldea', code: 'SV02' },
        { id: 'obsidian_flames', label: 'Obsidiana em Chamas', code: 'SV03' },
        { id: 'sv_151', label: '151', code: 'SV3.5' },
        { id: 'paradox_rift', label: 'Fenda Paradoxal', code: 'SV04' },
        { id: 'paldean_fates', label: 'Destinos de Paldea', code: 'SV4.5' },
        { id: 'temporal_forces', label: 'Forças Temporais', code: 'SV05' },
        { id: 'twilight_masquerade', label: 'Máscaras do Crepúsculo', code: 'SV06' },
        { id: 'shrouded_fable', label: 'Fábulas Nebulosas', code: 'SV6.5' },
        { id: 'stellar_crown', label: 'Coroa Estelar', code: 'SV07' },
        { id: 'surging_sparks', label: 'Fagulhas Impetuosas', code: 'SV08' },
        { id: 'prismatic_evolutions', label: 'Evoluções Prismáticas', code: 'SV8.5' },
        { id: 'journey_together', label: 'Amigos de Jornada', code: 'SV09' },
        { id: 'destined_rivals', label: 'Rivais Predestinados', code: 'SV10' },
        { id: 'black_bolt', label: 'Raio Preto', code: 'SV10.5' },
        { id: 'white_flare', label: 'Fogo Branco', code: 'SV10.5' },
      ],
      classes: {
        pokemon: ['Normal', 'ex', 'Tera ex', 'Full Art', 'Ilustração Rara', 'Art Secreta', 'Golden', 'Shiny', 'Black/White Rare'],
        trainer: ['Normal', 'ACE SPEC', 'Full Art', 'Art Secreta', 'Golden'],
        energy: ['Normal', 'ACE SPEC', 'Golden'],
      },
      pokemonTypes: MODERN_TYPES,
    },
    sword_shield: {
      id: 'sword_shield', label: 'Sword and Shield',
      collections: [
        { id: 'sword_shield', label: 'Espada e Escudo', code: 'SWSH1' },
        { id: 'rebel_clash', label: 'Rixa Rebelde', code: 'SWSH2' },
        { id: 'darkness_ablaze', label: 'Escuridão Incandescente', code: 'SWSH3' },
        { id: 'champions_path', label: 'Caminho do Campeão', code: 'SWSH3.5' },
        { id: 'vivid_voltage', label: 'Voltagem Vívida', code: 'SWSH4' },
        { id: 'shining_fates', label: 'Destinos Brilhantes', code: 'SWSH4.5' },
        { id: 'battle_styles', label: 'Estilos de Batalha', code: 'SWSH5' },
        { id: 'chilling_reign', label: 'Reinado Arrepiante', code: 'SWSH6' },
        { id: 'evolving_skies', label: 'Céus em Evolução', code: 'SWSH7' },
        { id: 'celebrations', label: 'Celebrações', code: 'SWSH7.5' },
        { id: 'fusion_strike', label: 'Golpe Fusão', code: 'SWSH8' },
        { id: 'brilliant_stars', label: 'Astros Cintilantes', code: 'SWSH9' },
        { id: 'astral_radiance', label: 'Estrelas Radiantes', code: 'SWSH10' },
        { id: 'pokemon_go', label: 'Pokémon GO', code: 'SWSH10.5' },
        { id: 'lost_origin', label: 'Origem Perdida', code: 'SWSH11' },
        { id: 'silver_tempest', label: 'Tempestade Prateada', code: 'SWSH12' },
        { id: 'crown_zenith', label: 'Realeza Absoluta', code: 'SWSH12.5' },
      ],
      classes: {
        pokemon: ['Normal', 'V', 'VMAX', 'V-ASTRO', 'V-UNION', 'Rara Incrível', 'Radiante', 'Shiny', 'Full Art', 'Arte Alternativa', 'Rainbow', 'Golden', 'Galeria de Treinadores', 'Galeria de Galar'],
        trainer: ['Normal', 'Full Art', 'Rainbow', 'Golden', 'Galeria de Treinadores', 'Galeria de Galar'],
        energy: ['Normal', 'Golden'],
      },
      pokemonTypes: MODERN_TYPES,
    },
    sun_moon: {
      id: 'sun_moon', label: 'Sun And Moon',
      collections: [
        { id: 'sun_moon', label: 'Sol e Lua', code: 'SM1' },
        { id: 'guardians_rising', label: 'Guardiões Ascendentes', code: 'SM2' },
        { id: 'burning_shadows', label: 'Sombras Ardentes', code: 'SM3' },
        { id: 'shining_legends', label: 'Lendas Luminescentes', code: 'SM3.5' },
        { id: 'crimson_invasion', label: 'Invasão Carmim', code: 'SM4' },
        { id: 'ultra_prism', label: 'Ultraprisma', code: 'SM5' },
        { id: 'forbidden_light', label: 'Luz Proibida', code: 'SM6' },
        { id: 'celestial_storm', label: 'Tempestade Celestial', code: 'SM7' },
        { id: 'dragon_majesty', label: 'Dragões Soberanos', code: 'SM7.5' },
        { id: 'lost_thunder', label: 'Trovões Perdidos', code: 'SM8' },
        { id: 'team_up', label: 'União de Aliados', code: 'SM9' },
        { id: 'detective_pikachu', label: 'Detetive Pikachu' },
        { id: 'unbroken_bonds', label: 'Elos Inquebráveis', code: 'SM10' },
        { id: 'unified_minds', label: 'Sintonia Mental', code: 'SM11' },
        { id: 'hidden_fates', label: 'Destinos Ocultos', code: 'SM11.5' },
        { id: 'cosmic_eclipse', label: 'Eclipse Cósmico', code: 'SM12' },
      ],
      classes: {
        pokemon: ['Normal', 'GX', 'TAG TEAM GX', 'Prisma', 'Luminescente', 'Shiny', 'Full Art', 'Arte Alternativa', 'Rainbow', 'Golden', 'Character Rare'],
        trainer: ['Normal', 'TAG TEAM', 'Prisma', 'Full Art', 'Golden'],
        energy: ['Normal', 'Prisma', 'Golden'],
      },
      pokemonTypes: FAIRY_TYPES,
    },
    xy: {
      id: 'xy', label: 'XY',
      collections: [
        { id: 'xy', label: 'XY', code: 'XY1' },
        { id: 'flashfire', label: 'Flash de Fogo', code: 'XY2 / FLF' },
        { id: 'furious_fists', label: 'Punhos Furiosos', code: 'XY3 / FFI' },
        { id: 'phantom_forces', label: 'Força Fantasma', code: 'XY4 / PHF' },
        { id: 'primal_clash', label: 'Conflito Primitivo', code: 'XY5 / PRC' },
        { id: 'double_crisis', label: 'Crise Dupla', code: 'DCR' },
        { id: 'roaring_skies', label: 'Céus Estrondosos', code: 'XY6 / ROS' },
        { id: 'ancient_origins', label: 'Origens Ancestrais', code: 'XY7 / AOR' },
        { id: 'breakthrough', label: 'Turbo Revolução', code: 'XY8 / BKT' },
        { id: 'breakpoint', label: 'Turbo Colisão', code: 'XY9 / BKP' },
        { id: 'generations', label: 'Gerações', code: 'GEN' },
        { id: 'fates_collide', label: 'Fusão de Destinos', code: 'XY10 / FCO' },
        { id: 'steam_siege', label: 'Cerco de Vapor', code: 'XY11 / STS' },
        { id: 'evolutions', label: 'Evolutions', code: 'XY12 / EVO' },
      ],
      classes: {
        pokemon: ['Normal', 'EX', 'Mega EX', 'TURBO / BREAK', 'Full Art', 'Art Secreta', 'Golden'],
        trainer: ['Normal', 'Full Art', 'Golden'],
        energy: ['Normal', 'Golden'],
      },
      pokemonTypes: FAIRY_TYPES,
    },
    black_white: {
      id: 'black_white', label: 'Black And White',
      collections: [
        { id: 'black_white', label: 'Black & White', code: 'BW1' },
        { id: 'emerging_powers', label: 'Poderes Emergentes', code: 'BW2 / EPO' },
        { id: 'noble_victories', label: 'Vitórias Nobres', code: 'BW3 / NVI' },
        { id: 'next_destinies', label: 'Próximos Destinos', code: 'BW4 / NXD' },
        { id: 'dark_explorers', label: 'Exploradores da Escuridão', code: 'BW5 / DEX' },
        { id: 'dragons_exalted', label: 'Dragões Enaltecidos', code: 'BW6 / DRX' },
        { id: 'dragon_vault', label: 'Dragon Vault', code: 'DRV' },
        { id: 'boundaries_crossed', label: 'Fronteiras Cruzadas', code: 'BW7 / BCR' },
        { id: 'plasma_storm', label: 'Tempestade de Plasma', code: 'BW8 / PLS' },
        { id: 'plasma_freeze', label: 'Congelamento de Plasma', code: 'BW9 / PLF' },
        { id: 'plasma_blast', label: 'Explosão de Plasma', code: 'BW10 / PLB' },
        { id: 'legendary_treasures', label: 'Legendary Treasures', code: 'BW11 / LTR' },
      ],
      classes: {
        pokemon: ['Normal', 'EX', 'Full Art', 'Art Secreta', 'Golden'],
        trainer: ['Normal', 'Full Art', 'ACE SPEC', 'Golden'],
        energy: ['Normal'],
      },
      pokemonTypes: MODERN_TYPES,
    },
  } satisfies Record<TcgEraId, TcgEraConfig>,
  groups: [
    { id: 'pokemon', label: 'Pokémon' },
    { id: 'trainer', label: 'Treinador' },
    { id: 'energy', label: 'Energia' },
  ] as TcgOption[],
  languages: [
    { id: 'ING', label: 'Inglês (ING)' },
    { id: 'BR', label: 'Português PT BR (BR)' },
    { id: 'JAP', label: 'Japonês (JAP)' },
    { id: 'CH', label: 'Chinês (CH)' },
    { id: 'ALE', label: 'Alemão (ALE)' },
    { id: 'FRA', label: 'Francês (FRA)' },
    { id: 'POR', label: 'Português (POR)' },
    { id: 'ESP', label: 'Espanhol (ESP)' },
  ] as TcgOption[],
  conditions: {
    D: { min: 1, max: 20 },
    HP: { min: 21, max: 40 },
    MP: { min: 41, max: 60 },
    SP: { min: 61, max: 80 },
    NM: { min: 81, max: 100 },
  } as Record<'D' | 'HP' | 'MP' | 'SP' | 'NM', { min: number; max: number }>,
} as const;

const normalize = (value: unknown) => String(value ?? '').trim().normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

const eraAliases: Record<string, TcgEraId> = {
  megaevolucao: 'mega_evolution', 'mega evolucao': 'mega_evolution', 'mega evolution': 'mega_evolution', mega_evolution: 'mega_evolution',
  'scarlet violet': 'scarlet_violet', 'scarlet and violet': 'scarlet_violet', 'escarlate e violeta': 'scarlet_violet', scarlet_violet: 'scarlet_violet',
  'sword and shield': 'sword_shield', 'sword & shield': 'sword_shield', 'espada e escudo': 'sword_shield', sword_shield: 'sword_shield',
  'sun and moon': 'sun_moon', 'sun & moon': 'sun_moon', 'sol e lua': 'sun_moon', sun_moon: 'sun_moon',
  xy: 'xy',
  'black and white': 'black_white', 'black & white': 'black_white', black_white: 'black_white',
};

export const getEraId = (value: unknown): TcgEraId | null => {
  const key = normalize(value);
  if (!key) return null;
  return eraAliases[key] || (Object.keys(TCG_CONFIG.eras) as TcgEraId[]).find((id) => normalize(id) === key) || null;
};

export const getEra = (value: unknown): TcgEraConfig | null => {
  const id = getEraId(value);
  return id ? TCG_CONFIG.eras[id] : null;
};

export const getCollectionByValue = (eraValue: unknown, collectionValue: unknown): TcgOption | null => {
  const era = getEra(eraValue);
  if (!era) return null;
  const target = normalize(collectionValue);
  const direct = era.collections.find((collection) => [collection.id, collection.label].some((value) => normalize(value) === target));
  if (direct) return direct;
  const byCode = era.collections.filter((collection) => normalize(collection.code) === target);
  return byCode.length === 1 ? byCode[0] : null;
};

export const getEraFromCollection = (collectionValue: unknown): TcgEraId | null => {
  const target = normalize(collectionValue);
  if (!target) return null;
  const matches = (Object.values(TCG_CONFIG.eras) as TcgEraConfig[]).filter((era) => era.collections.some((collection) => [collection.id, collection.label, collection.code].some((value) => normalize(value) === target)));
  return matches.length === 1 ? matches[0].id : null;
};

export const getGroupId = (value: unknown): TcgGroupId | null => {
  const key = normalize(value);
  if (['pokemon', 'pokémon'].map(normalize).includes(key)) return 'pokemon';
  if (['trainer', 'treinador'].includes(key)) return 'trainer';
  if (['energy', 'energia'].includes(key)) return 'energy';
  return null;
};

export const getLanguageCode = (value: unknown): string | null => {
  const key = normalize(value);
  if (!key) return null;
  const aliases: Record<string, string> = {
    ing: 'ING', en: 'ING', ingles: 'ING', 'ingles (ing)': 'ING',
    br: 'BR', 'pt-br': 'BR', 'pt br': 'BR', 'portugues pt br': 'BR', 'portugues (pt-br)': 'BR', 'portugues pt br (br)': 'BR',
    jap: 'JAP', japones: 'JAP', ch: 'CH', chines: 'CH', ale: 'ALE', alemao: 'ALE', fra: 'FRA', frances: 'FRA', por: 'POR', portugues: 'POR', esp: 'ESP', espanhol: 'ESP',
  };
  return aliases[key] || TCG_CONFIG.languages.find((language) => normalize(language.id) === key || normalize(language.label) === key)?.id || null;
};

export const languageLabel = (value: unknown): string => {
  const code = getLanguageCode(value);
  return TCG_CONFIG.languages.find((language) => language.id === code)?.label || String(value ?? '');
};

export const conditionForIntegrity = (integrity: unknown): 'D' | 'HP' | 'MP' | 'SP' | 'NM' | null => {
  const value = Number(integrity);
  if (!Number.isFinite(value) || value < 1 || value > 100) return null;
  if (value <= 20) return 'D';
  if (value <= 40) return 'HP';
  if (value <= 60) return 'MP';
  if (value <= 80) return 'SP';
  return 'NM';
};

export const isIntegrityValid = (condition: unknown, integrity: unknown): boolean => {
  const key = String(condition ?? '').toUpperCase() as keyof typeof TCG_CONFIG.conditions;
  const range = TCG_CONFIG.conditions[key];
  const value = Number(integrity);
  return Boolean(range && Number.isFinite(value) && value >= range.min && value <= range.max);
};

export const isClassValid = (eraValue: unknown, groupValue: unknown, classValue: unknown): boolean => {
  const era = getEra(eraValue);
  const group = getGroupId(groupValue);
  if (!era || !group) return false;
  return era.classes[group].includes(String(classValue ?? '') as never);
};

export const isPokemonTypeValid = (eraValue: unknown, typeValue: unknown): boolean => {
  const era = getEra(eraValue);
  return Boolean(era && era.pokemonTypes.includes(String(typeValue ?? '') as never));
};
