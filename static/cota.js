(function () {
  'use strict';

  const API = '';

  const el = (id) => document.getElementById(id);
  const setStatus = (id, text, className = '') => {
    const node = el(id);
    if (!node) return;
    node.textContent = text || '';
    node.className = 'status ' + (className || '');
  };

  async function loadCavMeta() {
    const baciaSelect = el('cav-bacia');
    const resSelect = el('cav-reservatorio');
    if (!baciaSelect || !resSelect) return;
    try {
      const res = await fetch(API + '/api/cav/meta');
      if (!res.ok) {
        baciaSelect.innerHTML = '<option value="">Erro ao carregar bacias</option>';
        resSelect.innerHTML = '<option value="">Erro ao carregar reservatórios</option>';
        resSelect.disabled = true;
        return;
      }
      const json = await res.json();
      const bacias = json.bacias || [];
      if (!bacias.length) {
        baciaSelect.innerHTML = '<option value="">Nenhuma bacia encontrada</option>';
        resSelect.innerHTML = '<option value="">Nenhum reservatório</option>';
        resSelect.disabled = true;
        return;
      }

      baciaSelect.innerHTML = '<option value="">Selecione uma bacia...</option>';
      bacias.forEach((b) => {
        const opt = document.createElement('option');
        opt.value = b.bacia;
        opt.textContent = b.bacia;
        baciaSelect.appendChild(opt);
      });

      baciaSelect.addEventListener('change', () => {
        const sel = baciaSelect.value;
        const group = bacias.find((b) => b.bacia === sel);
        resSelect.innerHTML = '';
        if (!sel || !group) {
          resSelect.disabled = true;
          resSelect.innerHTML = '<option value="">Selecione uma bacia primeiro</option>';
          return;
        }
        resSelect.disabled = false;
        resSelect.innerHTML = '<option value="">Selecione um reservatório...</option>';
        (group.reservatorios || []).forEach((r) => {
          const opt = document.createElement('option');
          opt.value = r;
          opt.textContent = r;
          resSelect.appendChild(opt);
        });
      });
    } catch (_) {
      const baciaSelectEl = el('cav-bacia');
      const resSelectEl = el('cav-reservatorio');
      if (baciaSelectEl) baciaSelectEl.innerHTML = '<option value="">Erro ao carregar bacias</option>';
      if (resSelectEl) {
        resSelectEl.innerHTML = '<option value="">Erro ao carregar reservatórios</option>';
        resSelectEl.disabled = true;
      }
    }
  }

  async function lookupCota() {
    const bacia = el('cav-bacia')?.value || '';
    const reserv = el('cav-reservatorio')?.value || '';
    const barroteStr = el('cav-barrote')?.value || '';
    const leituraStr = el('cav-leitura')?.value || '';

    if (!bacia || !reserv) {
      setStatus('cav-status', 'Selecione bacia e reservatório.', 'error');
      return;
    }
    if (!barroteStr || !leituraStr) {
      setStatus('cav-status', 'Informe barrote e leitura.', 'error');
      return;
    }

    const barrote = parseInt(barroteStr, 10);
    const leitura = parseInt(leituraStr, 10);
    if (Number.isNaN(barrote) || Number.isNaN(leitura)) {
      setStatus('cav-status', 'Barrote e leitura devem ser números inteiros.', 'error');
      return;
    }

    setStatus('cav-status', 'Buscando cota...');
    try {
      const res = await fetch(API + '/api/cav/lookup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bacia, reservatorio: reserv, barrote, leitura }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }
      const json = await res.json();
      if (el('cav-cota')) el('cav-cota').value = json.cota || '';
      if (el('cav-area')) el('cav-area').value = json.area_km2 || '';
      if (el('cav-volume')) el('cav-volume').value = json.volume_m3 || '';
      setStatus('cav-status', 'Cota encontrada.', 'success');
    } catch (e) {
      if (el('cav-cota')) el('cav-cota').value = '';
      if (el('cav-area')) el('cav-area').value = '';
      if (el('cav-volume')) el('cav-volume').value = '';
      setStatus('cav-status', e.message || 'Erro ao buscar cota.', 'error');
    }
  }

  function initTopbar() {
    const topbarToggle = document.getElementById('topbar-menu-toggle');
    const topbarNav = document.getElementById('topbar-nav');
    if (topbarToggle && topbarNav) {
      topbarToggle.addEventListener('click', () => {
        const isOpen = topbarNav.classList.toggle('open');
        topbarToggle.classList.toggle('open', isOpen);
      });
      topbarNav.querySelectorAll('a').forEach((link) => {
        link.addEventListener('click', () => {
          topbarNav.classList.remove('open');
          topbarToggle.classList.remove('open');
        });
      });
    }
  }

  function init() {
    initTopbar();
    loadCavMeta();
    const btnBuscar = el('btn-cav-buscar');
    if (btnBuscar) {
      btnBuscar.addEventListener('click', lookupCota);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

