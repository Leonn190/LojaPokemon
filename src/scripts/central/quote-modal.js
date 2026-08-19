const priceFormatter = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

const numberOrNull = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const money = (value) => numberOrNull(value) === null ? '—' : priceFormatter.format(Number(value));
const clampInt = (value, fallback = 0) => Number.isFinite(Number(value)) ? Math.max(0, Math.floor(Number(value))) : fallback;

const dateMillis = (value) => {
  if (!value) return 0;
  if (typeof value?.toDate === 'function') return value.toDate().getTime();
  if (value?.seconds) return Number(value.seconds) * 1000;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
};

const quotedUnitValue = (card) => (
  numberOrNull(card?.cheapestCertifiedPrice)
  ?? numberOrNull(card?.cheapestGeneralPrice)
  ?? numberOrNull(card?.averageGeneralPrice)
  ?? numberOrNull(card?.price)
  ?? 0
);

const lastQuotedMillis = (card) => {
  const direct = dateMillis(card?.lastQuotedAt || card?.lastQuoteAt);
  if (direct) return direct;
  const advanced = dateMillis(card?.advancedData?.['Última cotação']?.data || card?.advancedData?.['Ultima cotacao']?.data);
  if (advanced) return advanced;
  const history = Array.isArray(card?.priceHistory) ? card.priceHistory : [];
  return history.length ? dateMillis(history[history.length - 1]?.date) : 0;
};

const formatDuration = (seconds) => {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) return `≈ ${total}s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `≈ ${minutes}m${rest ? ` ${rest}s` : ''}`;
};

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));

export const createBulkQuoteController = ({
  root,
  getCards,
  getVaultPlus,
  setVaultPlus,
  onQuoteEntry,
  onCompleted,
}) => {
  const modal = root.querySelector('[data-bulk-quote-modal]');
  if (!modal) return { open() {}, refresh() {}, destroy() {} };

  const q = (selector) => modal.querySelector(selector);
  const qa = (selector) => [...modal.querySelectorAll(selector)];
  const states = qa('[data-bulk-quote-state]');
  const openButton = root.querySelector('[data-open-bulk-quote]');
  const startButton = q('[data-bulk-quote-start]');
  const againButton = q('[data-bulk-quote-again]');
  const minInput = q('[data-bulk-min-value]');
  const daysInput = q('[data-bulk-stale-days]');
  const minWrap = q('[data-bulk-min-wrap]');
  const daysWrap = q('[data-bulk-days-wrap]');
  let running = false;
  let pollTimer = 0;
  let activeJobId = '';
  let seenEntries = new Set();

  const setState = (name) => {
    states.forEach((node) => { node.hidden = node.dataset.bulkQuoteState !== name; });
  };

  const selectedFilters = () => {
    const scope = q('[data-bulk-scope]:checked')?.value || 'all';
    const stale = q('[data-bulk-stale]:checked')?.value || 'any';
    return {
      minValue: scope === 'min' ? Math.max(0, Number(minInput?.value || 0)) : null,
      staleDays: stale === 'days' ? Math.max(1, Math.floor(Number(daysInput?.value || 30))) : null,
    };
  };

  const filteredCards = () => {
    const filters = selectedFilters();
    const now = Date.now();
    return (getCards?.() || []).filter((card) => {
      if (filters.minValue !== null && quotedUnitValue(card) <= filters.minValue) return false;
      if (filters.staleDays !== null) {
        const last = lastQuotedMillis(card);
        const threshold = now - filters.staleDays * 86400000;
        if (last && last >= threshold) return false;
      }
      return true;
    });
  };

  const renderPrep = () => {
    const plus = getVaultPlus?.() || {};
    const filters = selectedFilters();
    const cards = filteredCards();
    const missing = cards.filter((card) => !String(card?.linkMyp || '').trim()).length;
    const secondsPerCard = Math.max(.5, Number(plus?.quoteEstimate?.secondsPerCard || plus?.secondsPerCard || 2.5));
    const estimate = formatDuration(cards.length * secondsPerCard);
    const remaining = clampInt(plus.remaining, 0);

    if (minWrap) minWrap.hidden = filters.minValue === null;
    if (daysWrap) daysWrap.hidden = filters.staleDays === null;
    if (q('[data-bulk-match-count]')) q('[data-bulk-match-count]').textContent = String(cards.length);
    if (q('[data-bulk-missing-count]')) q('[data-bulk-missing-count]').textContent = String(missing);
    if (q('[data-bulk-estimate]')) q('[data-bulk-estimate]').textContent = estimate;
    if (q('[data-bulk-summary-cards]')) q('[data-bulk-summary-cards]').textContent = String(cards.length);
    if (q('[data-bulk-summary-stale]')) q('[data-bulk-summary-stale]').textContent = filters.staleDays === null ? 'Qualquer data' : `> ${filters.staleDays} dias`;
    if (q('[data-bulk-summary-min]')) q('[data-bulk-summary-min]').textContent = filters.minValue === null ? 'Sem mínimo' : money(filters.minValue);
    if (q('[data-bulk-summary-time]')) q('[data-bulk-summary-time]').textContent = estimate;
    if (q('[data-bulk-summary-remaining]')) q('[data-bulk-summary-remaining]').textContent = String(Math.max(0, remaining - 1));
    if (startButton) startButton.disabled = cards.length === 0 || remaining <= 0 || plus.active !== true;
    const feedback = q('[data-bulk-prep-feedback]');
    if (feedback) {
      feedback.textContent = cards.length ? '' : 'Nenhuma carta corresponde aos filtros escolhidos.';
      feedback.dataset.state = cards.length ? 'neutral' : 'warning';
    }
  };

  const renderLocked = () => {
    const plus = getVaultPlus?.() || {};
    const title = q('[data-bulk-quote-locked-title]');
    const copy = q('[data-bulk-quote-locked-copy]');
    if (plus.active && Number(plus.remaining || 0) <= 0) {
      if (title) title.textContent = 'Limite semanal utilizado';
      if (copy) copy.textContent = plus.nextResetDate
        ? `Você utilizou suas 2 cotizações desta semana. Novas cotizações ficam disponíveis a partir de ${new Date(`${plus.nextResetDate}T12:00:00`).toLocaleDateString('pt-BR')}.`
        : 'Você utilizou suas 2 cotizações desta semana.';
    } else {
      if (title) title.textContent = 'Recurso Vault+';
      if (copy) copy.textContent = 'A cotização geral da coleção é exclusiva do Vault+. O preenchimento individual por link MYP continua gratuito e ilimitado.';
    }
  };

  const syncCloseAvailability = () => {
    qa('[data-bulk-quote-close]').forEach((button) => { button.disabled = running; });
  };

  const open = () => {
    const plus = getVaultPlus?.() || {};
    modal.hidden = false;
    document.body.classList.add('bulk-quote-open');
    if (plus.active === true && Number(plus.remaining || 0) > 0) {
      setState('prep');
      renderPrep();
    } else {
      renderLocked();
      setState('locked');
    }
    syncCloseAvailability();
  };

  const close = () => {
    if (running) return;
    modal.hidden = true;
    document.body.classList.remove('bulk-quote-open');
  };

  const patchLatestEntries = (job) => {
    (Array.isArray(job?.latest) ? job.latest : []).forEach((entry) => {
      if (entry?.status !== 'success' || !entry?.cardId) return;
      const key = `${entry.cardId}:${entry.quote?.lastQuotedAt || entry.after || ''}`;
      if (seenEntries.has(key)) return;
      seenEntries.add(key);
      onQuoteEntry?.(entry);
    });
  };

  const renderProgress = (job) => {
    const total = clampInt(job?.total, 0);
    const processed = clampInt(job?.processed, 0);
    const percent = total ? Math.min(100, Math.round(processed / total * 100)) : 0;
    q('[data-bulk-progress-processed]').textContent = String(processed);
    q('[data-bulk-progress-total]').textContent = String(total);
    q('[data-bulk-progress-percent]').textContent = `${percent}%`;
    q('[data-bulk-progress-bar]').style.width = `${percent}%`;

    const current = job?.current;
    q('[data-bulk-current-name]').textContent = current?.name || (processed >= total && total ? 'Finalizando…' : 'Preparando…');
    q('[data-bulk-current-number]').textContent = current?.number || '';
    q('[data-bulk-current-before]').textContent = current ? money(current.before) : '—';
    q('[data-bulk-current-after]').textContent = current?.status === 'success' ? money(current.after) : current?.status === 'error' ? 'Falha' : 'consultando…';
    const currentDelta = q('[data-bulk-current-delta]');
    if (currentDelta) {
      const delta = numberOrNull(current?.delta);
      currentDelta.textContent = delta === null ? '' : `${delta >= 0 ? '+' : ''}${money(delta)}`;
      currentDelta.dataset.direction = delta === null ? '' : delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
    }

    const latest = (Array.isArray(job?.latest) ? job.latest : []).slice(-8).reverse();
    const list = q('[data-bulk-recent-list]');
    if (list) list.innerHTML = latest.length ? latest.map((entry) => {
      if (entry.status === 'success') return `<div class="bulk-recent-row success"><span>✓</span><strong>${escapeHtml(entry.name || 'Carta')}</strong><small>${escapeHtml(entry.number || '')}</small><em>${escapeHtml(money(entry.before))} → ${escapeHtml(money(entry.after))}</em></div>`;
      return `<div class="bulk-recent-row error"><span>!</span><strong>${escapeHtml(entry.name || 'Carta')}</strong><small>${escapeHtml(entry.number || '')}</small><em>${escapeHtml(entry.message || 'Falha na cotização')}</em></div>`;
    }).join('') : '<div class="bulk-recent-empty">A primeira carta aparecerá aqui quando terminar.</div>';
    patchLatestEntries(job);
  };

  const renderDone = (job) => {
    setState('done');
    const interrupted = job?.status === 'failed';
    const title = q('[data-bulk-done-title]');
    const mark = q('[data-bulk-done-mark]');
    const jobError = q('[data-bulk-done-error]');
    if (title) title.textContent = interrupted ? 'Cotização interrompida' : 'Cotização concluída';
    if (mark) { mark.textContent = interrupted ? '!' : '✓'; mark.dataset.state = interrupted ? 'error' : 'success'; }
    if (jobError) {
      jobError.hidden = !interrupted;
      jobError.textContent = interrupted ? (job?.jobError || 'O servidor interrompeu a execução. As cartas já concluídas continuam salvas.') : '';
      jobError.dataset.state = interrupted ? 'error' : 'neutral';
    }
    q('[data-bulk-done-success]').textContent = String(clampInt(job?.success, 0));
    q('[data-bulk-done-failed]').textContent = String(clampInt(job?.failed, 0));
    q('[data-bulk-done-before]').textContent = money(job?.beforeValue || 0);
    q('[data-bulk-done-after]').textContent = money(job?.afterValue || 0);
    const delta = Number(job?.deltaValue || 0);
    q('[data-bulk-done-delta]').textContent = `${delta >= 0 ? '+' : ''}${money(delta)}`;
    const pct = Number(job?.deltaPercent || 0);
    q('[data-bulk-done-percent]').textContent = `${pct >= 0 ? '+' : ''}${pct.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`;
    const failures = Array.isArray(job?.failures) ? job.failures : [];
    const wrap = q('[data-bulk-failures-wrap]');
    if (wrap) wrap.hidden = failures.length === 0;
    q('[data-bulk-failure-count]').textContent = String(Number(job?.failureCount || failures.length || 0));
    const list = q('[data-bulk-failures]');
    if (list) list.innerHTML = failures.map((entry) => `<div><strong>${escapeHtml(entry.name || 'Carta')} ${escapeHtml(entry.number || '')}</strong><small>${escapeHtml(entry.message || 'Não foi possível cotizar esta carta.')}</small></div>`).join('');
  };

  const finish = async (job) => {
    running = false;
    activeJobId = '';
    window.clearTimeout(pollTimer);
    syncCloseAvailability();
    patchLatestEntries(job);
    renderDone(job);
    try { await onCompleted?.(job); } catch (error) { console.warn('[Vault TCG] Falha ao recarregar cartas após a cotização:', error); }
  };

  const poll = async () => {
    if (!running || !activeJobId) return;
    try {
      const payload = await window.VaultCloud.getBulkQuoteStatus(activeJobId);
      const job = payload?.job || payload;
      renderProgress(job);
      if (job?.status === 'completed' || job?.status === 'failed') { await finish(job); return; }
      pollTimer = window.setTimeout(poll, 1100);
    } catch (error) {
      const feedback = q('[data-bulk-progress-feedback]');
      if (feedback) { feedback.textContent = error?.message || 'Reconectando ao andamento da cotização…'; feedback.dataset.state = 'warning'; }
      pollTimer = window.setTimeout(poll, 2200);
    }
  };

  const start = async () => {
    if (running) return;
    const plus = getVaultPlus?.() || {};
    if (plus.active !== true || Number(plus.remaining || 0) <= 0) { renderLocked(); setState('locked'); return; }
    const filters = selectedFilters();
    const cards = filteredCards();
    const feedback = q('[data-bulk-prep-feedback]');
    if (!cards.length) { if (feedback) { feedback.textContent = 'Nenhuma carta corresponde aos filtros escolhidos.'; feedback.dataset.state = 'warning'; } return; }
    running = true;
    seenEntries = new Set();
    syncCloseAvailability();
    if (startButton) startButton.disabled = true;
    if (feedback) { feedback.textContent = 'Criando a fila segura de cotização no backend…'; feedback.dataset.state = 'loading'; }
    try {
      await window.VaultCloud?.ready;
      const payload = await window.VaultCloud.startBulkQuote(filters);
      const job = payload?.job || payload;
      activeJobId = job?.jobId || '';
      if (!activeJobId) throw new Error('O servidor não retornou o identificador da cotização.');
      setVaultPlus?.({
        ...plus,
        weeklyQuotesUsed: Math.max(0, Number(plus.weeklyLimit || 2) - Number(job.remainingAfterStart || 0)),
        remaining: Number(job.remainingAfterStart || 0),
        nextResetDate: job.nextResetDate || plus.nextResetDate,
      });
      setState('progress');
      renderProgress(job);
      pollTimer = window.setTimeout(poll, 500);
    } catch (error) {
      running = false;
      syncCloseAvailability();
      if (startButton) startButton.disabled = false;
      if (error?.nextResetDate && setVaultPlus) setVaultPlus({ ...plus, remaining: 0, nextResetDate: error.nextResetDate });
      if (feedback) { feedback.textContent = error?.message || 'Não foi possível iniciar a cotização.'; feedback.dataset.state = 'error'; }
      if (String(error?.code || '').includes('VAULT_PLUS')) { renderLocked(); setState('locked'); }
    }
  };

  const refresh = () => {
    if (modal.hidden || running) return;
    const plus = getVaultPlus?.() || {};
    if (plus.active && Number(plus.remaining || 0) > 0) { setState('prep'); renderPrep(); }
    else { renderLocked(); setState('locked'); }
  };

  openButton?.addEventListener('click', open);
  qa('[data-bulk-quote-close]').forEach((button) => button.addEventListener('click', close));
  startButton?.addEventListener('click', start);
  againButton?.addEventListener('click', refresh);
  qa('[data-bulk-scope], [data-bulk-stale]').forEach((input) => input.addEventListener('change', renderPrep));
  minInput?.addEventListener('input', renderPrep);
  daysInput?.addEventListener('input', renderPrep);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !modal.hidden) close(); });

  return {
    open,
    refresh,
    destroy() { window.clearTimeout(pollTimer); },
  };
};
