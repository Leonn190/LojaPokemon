import { initializeApp, getApps } from 'firebase-admin/app';
import { getAuth } from 'firebase-admin/auth';
import { HttpsError, onCall } from 'firebase-functions/v2/https';
import nodemailer from 'nodemailer';
import { DEFAULT_RETURN_URL, VAULT_GMAIL_CONFIG } from './email/config';
import { buildVaultVerificationEmail } from './email/template';

if (!getApps().length) initializeApp();

const safeReturnUrl = (raw: unknown) => {
  const fallback = DEFAULT_RETURN_URL;
  try {
    const candidate = new URL(String(raw || fallback));
    const allowed = candidate.hostname === 'leonn190.github.io'
      || candidate.hostname === 'localhost'
      || candidate.hostname === '127.0.0.1';
    return allowed ? candidate.toString() : fallback;
  } catch (_) {
    return fallback;
  }
};

export const sendVaultVerificationEmail = onCall(
  {
    region: 'us-central1',
    timeoutSeconds: 30,
    memory: '256MiB',
    maxInstances: 3,
  },
  async (request) => {
    if (!request.auth?.uid) throw new HttpsError('unauthenticated', 'Entre na sua conta antes de verificar o Gmail.');

    const user = await getAuth().getUser(request.auth.uid);
    if (!user.email) throw new HttpsError('failed-precondition', 'Sua conta não possui um e-mail válido.');
    if (user.emailVerified) return { ok: true, alreadyVerified: true, delivery: 'already-verified' };

    if (!VAULT_GMAIL_CONFIG.user) {
      throw new HttpsError('failed-precondition', 'O Gmail remetente ainda não foi configurado no backend.');
    }

    const verificationUrl = await getAuth().generateEmailVerificationLink(user.email, {
      url: safeReturnUrl(request.data?.returnUrl),
      handleCodeInApp: false,
    });

    const message = buildVaultVerificationEmail({
      collectorName: user.displayName || undefined,
      verificationUrl,
    });

    const transporter = nodemailer.createTransport({
      host: VAULT_GMAIL_CONFIG.host,
      port: VAULT_GMAIL_CONFIG.port,
      secure: VAULT_GMAIL_CONFIG.secure,
      auth: {
        user: VAULT_GMAIL_CONFIG.user,
        pass: VAULT_GMAIL_CONFIG.appPassword,
      },
    });

    await transporter.sendMail({
      from: `"${VAULT_GMAIL_CONFIG.senderName}" <${VAULT_GMAIL_CONFIG.user}>`,
      to: user.email,
      subject: message.subject,
      text: message.text,
      html: message.html,
    });

    return { ok: true, alreadyVerified: false, delivery: 'gmail' };
  },
);
