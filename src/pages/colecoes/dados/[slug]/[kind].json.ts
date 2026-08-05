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
  forSale: item.forSale,
  showQuantity: item.showQuantity,
  ...(item.kind === 'card' ? {
    number: item.number,
    collection: item.collection,
    language: item.language,
    condition: item.condition,
    year: item.year,
    type: item.type,
  } : item.kind === 'booster' ? {
    collection: item.name,
    type: 'Booster avulso',
  } : {
    description: item.description,
    contents: item.contents,
    type: 'Kit personalizado',
  }),
});

export const getStaticPaths: GetStaticPaths = () => getCollections().flatMap((collection) => ([
  { params: { slug: collection.slug, kind: 'cards' }, props: { items: collection.cards } },
  { params: { slug: collection.slug, kind: 'boosters' }, props: { items: collection.boosters } },
  { params: { slug: collection.slug, kind: 'kits' }, props: { items: collection.kits } },
]));

export const GET: APIRoute = ({ props }) => new Response(JSON.stringify((props.items as CatalogItem[]).map(serialize)), {
  headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'public, max-age=300' },
});
