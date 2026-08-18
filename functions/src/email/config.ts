const normalizeAppPassword = (value: string) => value.replace(/\s+/g, '');

export const VAULT_GMAIL_CONFIG = Object.freeze({
  host: 'smtp.gmail.com',
  port: 465,
  secure: true,
  user: String(process.env.GMAIL_USER || '').trim(),
  // Mantido exatamente como solicitado como fallback/placeholder server-side.
  appPassword: normalizeAppPassword(String(process.env.GMAIL_APP_PASSWORD || 'aryd uqik xmct wvqs')),
  senderName: 'Vault TCG',
});

export const DEFAULT_RETURN_URL = String(
  process.env.VAULT_SITE_URL || 'https://leonn190.github.io/LojaPokemon/central/',
).trim();
