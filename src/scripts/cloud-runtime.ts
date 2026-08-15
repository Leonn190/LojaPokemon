import {
  createAccountWithCollection,
  currentUser,
  friendlyFirebaseError,
  getCloud,
  listPublicAlbums,
  listPublicCollections,
  listPublicItems,
  loadCollectionBySlug,
  loadMyCollection,
  saveEditorState,
  signIn,
  signOut,
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
  listPublicAlbums,
  listPublicCollections,
  listPublicItems,
  loadCollectionBySlug,
  loadMyCollection,
  saveEditorState,
  signIn,
  signOut,
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
    document.querySelectorAll<HTMLElement>('[data-auth-nav]').forEach((link) => {
      link.textContent = user ? 'Minha coleção' : 'Entrar';
      link.setAttribute('aria-label', user ? 'Abrir minha coleção' : 'Entrar ou criar uma conta');
    });
    document.querySelectorAll<HTMLElement>('[data-auth-footer]').forEach((link) => {
      link.textContent = user ? 'Minha coleção' : 'Entrar';
    });
    document.querySelectorAll<HTMLAnchorElement>('[data-home-auth-cta]').forEach((link) => {
      const label = link.querySelector('span');
      if (label) label.textContent = user ? 'Minha coleção' : 'Entrar';
      const icon = link.querySelector('b');
      if (icon) icon.textContent = user ? '↗' : '→';
    });
    window.dispatchEvent(new CustomEvent('vault:auth-changed', { detail: { user } }));
  });
}).catch(() => {});
