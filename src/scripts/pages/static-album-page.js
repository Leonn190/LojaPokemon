(() => {
  const root = document.querySelector('[data-immersive-album]');
  if (!root) return;
  const pages = [...root.querySelectorAll('[data-album-page]')];
  const bookWrap = root.querySelector('[data-album-book-wrap]');
  const prev = root.querySelector('[data-album-previous]');
  const next = root.querySelector('[data-album-next]');
  const label = root.querySelector('[data-album-page-label]');
  const rail = root.querySelector('[data-album-page-rail]');
  const endpaper = root.querySelector('[data-album-endpaper]');
  const focusButton = root.querySelector('[data-album-focus]');
  const focusExit = root.querySelector('[data-album-focus-exit]');
  const mobile = window.matchMedia('(max-width: 760px)');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let start = 0;
  let timer = 0;
  const perView = () => mobile.matches ? 1 : 2;
  const lastStart = () => Math.max(0, pages.length - perView());
  const normalizedStart = (value) => {
    const clamped = Math.max(0, Math.min(value, lastStart()));
    return perView() === 2 ? Math.floor(clamped / 2) * 2 : clamped;
  };
  const render = (direction = 0) => {
    start = normalizedStart(start);
    const count = perView();
    pages.forEach((page, index) => { page.hidden = index < start || index >= start + count; });
    if (endpaper) endpaper.hidden = mobile.matches || pages.length % 2 === 0 || start + count < pages.length;
    const end = Math.min(pages.length, start + count);
    if (label) label.textContent = end - start > 1 ? `Páginas ${start + 1}–${end}` : `Página ${start + 1}`;
    if (prev) prev.disabled = start === 0;
    if (next) next.disabled = start + count >= pages.length;
    rail?.querySelectorAll('[data-album-page-jump]').forEach((button) => {
      const index = Number(button.dataset.albumPageJump || 0);
      button.classList.toggle('active', index >= start && index < end);
    });
    if (direction && bookWrap && !reduced) {
      window.clearTimeout(timer);
      bookWrap.classList.remove('turn-forward', 'turn-backward');
      void bookWrap.offsetWidth;
      bookWrap.classList.add(direction > 0 ? 'turn-forward' : 'turn-backward');
      timer = window.setTimeout(() => bookWrap.classList.remove('turn-forward', 'turn-backward'), 780);
    }
  };
  const step = (direction) => { start += direction * perView(); render(direction); };
  prev?.addEventListener('click', () => step(-1));
  next?.addEventListener('click', () => step(1));
  rail?.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target.closest('[data-album-page-jump]') : null;
    if (!target) return;
    const requested = Number(target.dataset.albumPageJump || 0);
    const direction = requested >= start ? 1 : -1;
    start = requested;
    render(direction);
  });
  document.addEventListener('keydown', (event) => {
    if (document.body.classList.contains('modal-open')) return;
    if (event.key === 'ArrowLeft' && start > 0) step(-1);
    if (event.key === 'ArrowRight' && start + perView() < pages.length) step(1);
  });
  mobile.addEventListener?.('change', render);
  const setFocusMode = (active) => {
    document.body.classList.toggle('album-focus-mode', active);
    focusButton?.setAttribute('aria-pressed', String(active));
    if (focusButton) focusButton.innerHTML = active ? '<span>◇</span> Sair do modo imersivo' : '<span>◈</span> Modo imersivo';
    if (active) root.querySelector('[data-album-stage]')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
  };
  focusButton?.addEventListener('click', () => setFocusMode(!document.body.classList.contains('album-focus-mode')));
  focusExit?.addEventListener('click', () => setFocusMode(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.body.classList.contains('album-focus-mode') && !document.body.classList.contains('modal-open')) setFocusMode(false);
  });
  render();
})();
