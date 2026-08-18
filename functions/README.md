# Backend de e-mail · Vault TCG

A função `sendVaultVerificationEmail` gera um link oficial de verificação do Firebase Admin e envia esse link pelo Gmail com o template visual do Vault TCG.

## Estrutura

- `src/index.ts` — Cloud Function callable autenticada.
- `src/email/config.ts` — SMTP e URL de retorno.
- `src/email/template.ts` — HTML do e-mail.
- `.env.example` — campos que precisam existir no ambiente.

O frontend tenta essa função primeiro. Se ela ainda não estiver publicada/configurada, cai automaticamente no e-mail padrão do Firebase Authentication para não quebrar a verificação.
