type VerifyGmailTemplateInput = {
  collectorName?: string;
  verificationUrl: string;
};

const escapeHtml = (value: unknown) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');

export function buildVaultVerificationEmail({ collectorName, verificationUrl }: VerifyGmailTemplateInput) {
  const name = escapeHtml(collectorName || 'Colecionador');
  const url = escapeHtml(verificationUrl);

  return {
    subject: 'Verifique seu Gmail · Vault TCG',
    text: `Olá, ${collectorName || 'Colecionador'}! Verifique seu Gmail no Vault TCG: ${verificationUrl}`,
    html: `<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Verifique seu Gmail · Vault TCG</title>
  </head>
  <body style="margin:0;padding:0;background:#050b13;font-family:Inter,Arial,sans-serif;color:#edf7ff;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#050b13;padding:34px 14px;">
      <tr><td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;border:1px solid #1d3345;border-radius:22px;overflow:hidden;background:#08131f;box-shadow:0 24px 70px rgba(0,0,0,.35);">
          <tr><td style="padding:30px 32px 18px;background:linear-gradient(135deg,#0c1d2b,#0a1422);">
            <div style="font-size:12px;font-weight:900;letter-spacing:.18em;color:#54e8df;text-transform:uppercase;">VAULT TCG</div>
            <h1 style="margin:12px 0 8px;font-size:29px;line-height:1.08;color:#ffffff;">Confirme seu Gmail</h1>
            <p style="margin:0;color:#91a8b9;font-size:14px;line-height:1.65;">Olá, ${name}. Falta só confirmar que este endereço pertence a você.</p>
          </td></tr>
          <tr><td style="padding:24px 32px 8px;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #173344;border-radius:15px;background:#071824;">
              <tr><td style="padding:17px 18px;">
                <div style="font-size:11px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:#54e8df;">+5 SCORE DE SEGURANÇA</div>
                <div style="margin-top:6px;color:#b8c9d6;font-size:13px;line-height:1.55;">A confirmação adiciona cinco pontos ao seu score uma única vez.</div>
              </td></tr>
            </table>
          </td></tr>
          <tr><td align="center" style="padding:25px 32px 14px;">
            <a href="${url}" style="display:inline-block;padding:14px 25px;border-radius:12px;background:#54e8df;color:#051118;text-decoration:none;font-size:13px;font-weight:900;box-shadow:0 10px 30px rgba(84,232,223,.18);">Verificar meu Gmail</a>
          </td></tr>
          <tr><td style="padding:7px 32px 29px;">
            <p style="margin:0;color:#708697;font-size:11px;line-height:1.65;text-align:center;">Se você não solicitou esta verificação, pode ignorar esta mensagem.</p>
          </td></tr>
        </table>
        <div style="padding-top:14px;color:#526879;font-size:10px;">Vault TCG · Seu acervo, sua vitrine.</div>
      </td></tr>
    </table>
  </body>
</html>`,
  };
}
