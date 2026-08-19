(() => {
  const root = document.querySelector('[data-auth-page]');
  if (!root) return;
  const base = root.dataset.base || '/';
  const buttons = [...root.querySelectorAll('[data-auth-mode]')];
  const panels = [...root.querySelectorAll('[data-auth-panel]')];
  const clean = (value) => String(value ?? '').trim();
  let authActionInProgress = false;

  const setMode = (mode) => {
    buttons.forEach((button) => button.classList.toggle('active', button.dataset.authMode === mode));
    panels.forEach((panel) => { panel.hidden = panel.dataset.authPanel !== mode; });
  };
  buttons.forEach((button) => button.addEventListener('click', () => setMode(button.dataset.authMode)));

  const nextDestination = () => {
    const raw = new URLSearchParams(window.location.search).get('next');
    if (raw && raw.startsWith('/')) return raw;
    return `${base}central/`;
  };
  const goToCollection = () => window.location.replace(nextDestination());
  const normalizeProposalTerms = (formData) => {
    const mins = formData.getAll('tierMin');
    const discounts = formData.getAll('tierDiscount');
    return {
      policy: clean(formData.get('proposalPolicy')) || 'flexible',
      flexibleDiscounts: formData.get('flexibleDiscounts') === 'on',
      discountTiers: mins.map((value, index) => ({
        minValue: Math.max(0, Number(value || 0)),
        maxDiscount: Math.min(100, Math.max(0, Number(discounts[index] || 0))),
      })).filter((tier) => tier.minValue > 0 || tier.maxDiscount > 0),
    };
  };
  const friendly = (error) => window.VaultCloud?.friendlyFirebaseError?.(error) || error?.message || 'Não foi possível concluir esta ação.';

  root.querySelector('[data-login-form]')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const feedback = root.querySelector('[data-login-feedback]');
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    authActionInProgress = true;
    feedback.textContent = 'Entrando…';
    try {
      await window.VaultCloud?.ready;
      await window.VaultCloud.signIn(clean(data.get('login')), String(data.get('password') || ''));
      feedback.textContent = '';
      goToCollection();
    } catch (error) {
      feedback.textContent = friendly(error);
      authActionInProgress = false;
    }
  });

  root.querySelector('[data-forgot-password]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    const form = root.querySelector('[data-login-form]');
    const feedback = root.querySelector('[data-login-feedback]');
    const email = clean(form?.elements?.login?.value);
    if (!email) {
      feedback.textContent = 'Informe seu e-mail acima para recuperar a senha.';
      form?.elements?.login?.focus();
      return;
    }
    button.disabled = true;
    feedback.textContent = 'Enviando link de recuperação…';
    try {
      await window.VaultCloud?.ready;
      await window.VaultCloud.requestForgotPassword(email);
      feedback.textContent = 'Se existir uma conta com esse e-mail, o Firebase enviará um link de recuperação.';
    } catch (error) {
      const message = friendly(error);
      // Evita confirmar ou negar a existência de contas pelo texto da interface.
      feedback.textContent = /user-not-found|usu[aá]rio.*n[aã]o/i.test(String(message))
        ? 'Se existir uma conta com esse e-mail, o Firebase enviará um link de recuperação.'
        : message;
    } finally {
      button.disabled = false;
    }
  });

  root.querySelector('[data-signup-form]')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const feedback = root.querySelector('[data-signup-feedback]');
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    authActionInProgress = true;
    feedback.textContent = 'Criando sua conta…';
    try {
      await window.VaultCloud?.ready;
      await window.VaultCloud.createAccountWithCollection({
        owner: clean(data.get('owner')),
        title: clean(data.get('title')),
        email: clean(data.get('email')),
        phone: clean(data.get('phone')),
        password: String(data.get('password') || ''),
        isPublic: data.get('public') === 'on',
        selling: true,
        proposalTerms: normalizeProposalTerms(data),
      });
      feedback.textContent = '';
      goToCollection();
    } catch (error) {
      feedback.textContent = friendly(error);
      authActionInProgress = false;
    }
  });

  window.addEventListener('vault:auth-changed', (event) => {
    if (event.detail?.user && !authActionInProgress) goToCollection();
  });
  window.addEventListener('vault:cloud-error', (event) => {
    const message = event.detail?.message || 'Não foi possível conectar ao serviço de conta.';
    const target = root.querySelector('[data-login-feedback]');
    if (target) target.textContent = message;
  });
})();
