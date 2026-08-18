import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollections, type CatalogItem } from '../../../../lib/catalog';

const serialize = (item: CatalogItem) => ({
  kind: item.kind,
  name: item.name,
  quantity: item.quantity,
  price: item.price,
  slug: item.slug,
  imageCandidates: item.imageCandidates,
  searchText: item.searchText,
  ownerName: item.ownerName,
  ownerCollectionName: item.ownerCollectionName,
  ownerCollectionSlug: item.ownerCollectionSlug,
  ownerPhone: item.ownerPhone,
  proposalTerms: item.proposalTerms,
  forSale: item.forSale,
  showQuantity: false,
  ...(item.kind === 'card' ? {
    number: item.number,
    era: item.era,
    collection: item.collection,
    collectionId: item.collectionId,
    collectionCode: item.collectionCode,
    group: item.group,
    cardClass: item.cardClass,
    type: item.type,
    language: item.language,
    languageLabel: item.languageLabel,
    condition: item.condition,
    integrity: item.integrity,
    year: item.year,
  } : item.kind === 'booster' ? {
    year: item.year,
    era: item.era,
    collection: item.collection || item.name,
    collectionId: item.collectionId,
    collectionCode: item.collectionCode,
    language: item.language,
    languageLabel: item.languageLabel,
    images: item.images,
    type: 'Booster avulso',
  } : item.kind === 'kit' ? {
    description: item.description,
    contents: item.contents,
    contentItems: item.contentItems,
    sourceTotal: item.sourceTotal,
    type: 'Kit personalizado',
  } : {
    description: item.description,
    linkLiga: item.linkLiga,
    type: 'Produto lacrado',
  }),
});

export const getStaticPaths: GetStaticPaths = () => getCollections().flatMap((collection) => ([
  { params: { slug: collection.slug, kind: 'cards' }, props: { items: collection.cards } },
  { params: { slug: collection.slug, kind: 'boosters' }, props: { items: collection.boosters } },
  { params: { slug: collection.slug, kind: 'kits' }, props: { items: collection.kits } },
  { params: { slug: collection.slug, kind: 'produtos' }, props: { items: collection.products } },
]));

export const GET: APIRoute = ({ props }) => new Response(JSON.stringify((props.items as CatalogItem[]).map(serialize)), {
  headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'public, max-age=300' },
});
