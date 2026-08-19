const root = document.querySelector<HTMLElement>('[data-vault-plus-page]');

if (root) {
  const setText = (selector: string, value: string) => {
    const node = root.querySelector<HTMLElement>(selector);
    if (node) node.textContent = value;
  };

  const renderLoggedOut = () => {
    setText('[data-vault-plus-status-pill]', 'Entre para consultar');
    setText('[data-vault-plus-status-title]', 'Vault+');
    setText('[data-vault-plus-status-copy]', 'Entre na sua conta para consultar o status do plano e suas cotizações semanais.');
    const quota = root.querySelector<HTMLElement>('[data-vault-plus-status-quota]');
    if (quota) quota.hidden = true;
  };

  const renderStatus = (payload: any) => {
    const plus = payload?.vaultPlus || {};
    const estimate = payload?.quoteEstimate || {};
    const active = plus.active === true;
    const remaining = Math.max(0, Number(plus.remaining || 0));
    const limit = Math.max(1, Number(plus.weeklyLimit || 2));
    setText('[data-vault-plus-status-pill]', active ? 'Vault+ ativo' : 'Plano não ativo');
    setText('[data-vault-plus-status-title]', active ? 'Seu Vault+ está ativo' : 'Conheça o Vault+');
    setText('[data-vault-plus-status-copy]', active
      ? `Você tem o bônus de visibilidade ativo e ${remaining} de ${limit} cotizações gerais disponíveis nesta semana.`
      : 'A estrutura do plano já está pronta, mas sua conta não possui uma assinatura Vault+ ativa.');
    const quota = root.querySelector<HTMLElement>('[data-vault-plus-status-quota]');
    if (quota) quota.hidden = !active;
    setText('[data-vault-plus-remaining]', `${remaining}/${limit}`);
    if (plus.nextResetDate) {
      const date = new Date(`${plus.nextResetDate}T12:00:00`);
      setText('[data-vault-plus-reset]', `Renova em ${date.toLocaleDateString('pt-BR')}`);
    } else {
      setText('[data-vault-plus-reset]', 'Renovação semanal');
    }
    const card = root.querySelector<HTMLElement>('[data-vault-plus-status-card]');
    if (card) {
      card.dataset.active = active ? 'true' : 'false';
      card.dataset.secondsPerCard = String(estimate.secondsPerCard || '');
    }
  };

  const loadStatus = async (user?: any) => {
    if (!user) {
      user = await window.VaultCloud?.currentUser?.();
    }
    if (!user) { renderLoggedOut(); return; }
    setText('[data-vault-plus-status-pill]', 'Consultando plano…');
    try {
      const payload = await window.VaultCloud?.getVaultPlusStatus?.();
      renderStatus(payload);
    } catch (error: any) {
      setText('[data-vault-plus-status-pill]', 'Status indisponível');
      setText('[data-vault-plus-status-copy]', error?.message || 'Não foi possível consultar seu plano agora.');
    }
  };

  window.addEventListener('vault:auth-changed', (event: Event) => {
    const user = (event as CustomEvent).detail?.user || null;
    void loadStatus(user);
  });
  window.addEventListener('vault:cloud-ready', () => { void loadStatus(); });
}
