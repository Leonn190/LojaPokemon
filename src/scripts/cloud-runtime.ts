import {
  createAccountWithCollection,
  currentUser,
  friendlyFirebaseError,
  fetchMypCardInfo,
  getBulkQuoteStatus,
  getVaultPlusStatus,
  getCloud,
  listPublicAlbums,
  listPublicAlbumsPage,
  listPublicCollectionPreview,
  listPublicCollections,
  listPublicCollectionsPage,
  listPublicItems,
  listPublicItemsPage,
  listMyReceivedProposals,
  loadCollectionBySlug,
  loadMyCollection,
  refreshAccountVerification,
  requestAccountPasswordResetEmail,
  requestForgotPassword,
  saveEditorState,
  sendAccountVerificationEmail,
  signIn,
  signOut,
  startBulkQuote,
  slugify,
  submitProposal,
  watchAuth,
} from '../lib/firebase/cloud';

declare global {
  interface Window {
    VaultCloud?: any;
  }
}

const ready = getCloud().then(() => true);

window.VaultCloud = {
  ready,
  createAccountWithCollection,
  currentUser,
  friendlyFirebaseError,
  fetchMypCardInfo,
  getBulkQuoteStatus,
  getVaultPlusStatus,
  listPublicAlbums,
  listPublicAlbumsPage,
  listPublicCollectionPreview,
  listPublicCollections,
  listPublicCollectionsPage,
  listPublicItems,
  listPublicItemsPage,
  listMyReceivedProposals,
  loadCollectionBySlug,
  loadMyCollection,
  refreshAccountVerification,
  requestAccountPasswordResetEmail,
  requestForgotPassword,
  saveEditorState,
  sendAccountVerificationEmail,
  signIn,
  signOut,
  startBulkQuote,
  slugify,
  submitProposal,
  watchAuth,
};

ready.then(() => window.dispatchEvent(new CustomEvent('vault:cloud-ready'))).catch((error) => {
  console.error('[Vault TCG] Firebase não inicializado:', error);
  window.dispatchEvent(new CustomEvent('vault:cloud-error', { detail: error }));
});

ready.then(async () => {
  await watchAuth((user) => {
    document.body.dataset.authenticated = user ? 'true' : 'false';
    try { window.localStorage.setItem('vault:auth-hint', user ? '1' : '0'); } catch (_) {}
    const siteBase = document.body.dataset.siteBase || '/';
    document.querySelectorAll<HTMLAnchorElement>('[data-auth-nav]').forEach((link) => {
      link.textContent = user ? 'Minha coleção' : 'Entrar';
      link.href = user ? `${siteBase}central/` : `${siteBase}cadastro/`;
      link.setAttribute('aria-label', user ? 'Abrir minha coleção' : 'Entrar ou criar uma conta');
    });
    document.querySelectorAll<HTMLAnchorElement>('[data-auth-footer]').forEach((link) => {
      link.textContent = user ? 'Minha coleção' : 'Entrar';
      link.href = user ? `${siteBase}central/` : `${siteBase}cadastro/`;
    });
    document.querySelectorAll<HTMLAnchorElement>('[data-home-auth-cta]').forEach((link) => {
      const label = link.querySelector('span');
      if (label) label.textContent = user ? 'Minha coleção' : 'Entrar';
      const icon = link.querySelector('b');
      if (icon) icon.textContent = user ? '↗' : '→';
      link.href = user ? `${siteBase}central/` : `${siteBase}cadastro/`;
    });
    window.dispatchEvent(new CustomEvent('vault:auth-changed', { detail: { user } }));
  });
}).catch(() => {});
