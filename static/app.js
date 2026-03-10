(function () {
  'use strict';

  const API = '';
  let state = { data: null, info: null };

  const el = (id) => document.getElementById(id);
  const setStatus = (id, text, className = '') => {
    const node = el(id);
    if (!node) return;
    node.textContent = text || '';
    node.className = 'status ' + (className || '');
  };

  function getKpis(data) {
    const rows = Array.isArray(data) ? data : [];
    let total = rows.length;
    let up = 0, down = 0, vertendo = 0, zero = 0;
    rows.forEach((r) => {
      const pct = r.percentual != null ? Number(r.percentual) : NaN;
      const varM = r.variacao_m != null ? Number(r.variacao_m) : NaN;
      const isVert = !Number.isNaN(pct) && pct >= 100;
      if (isVert) vertendo++;
      else if (!Number.isNaN(varM)) {
        if (varM > 0) up++;
        else if (varM < 0) down++;
        else if (pct < 100) zero++;
      }
    });
    return { total, up, down, vertendo, sem_var: zero };
  }

  function showKpis(data) {
    const k = getKpis(data);
    el('kpi-total').textContent = k.total;
    el('kpi-up').textContent = k.up;
    el('kpi-down').textContent = k.down;
    el('kpi-vertendo').textContent = k.vertendo;
    el('kpi-zero').textContent = k.sem_var;
    el('section-kpis').hidden = false;
    el('btn-generate').disabled = false;
  }

  function tabs() {
    const tabs = document.querySelectorAll('.fonte-tabs .tab');
    const panels = document.querySelectorAll('.card.fonte .panel');
    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const source = tab.getAttribute('data-source');
        tabs.forEach((t) => t.classList.remove('active'));
        panels.forEach((p) => p.classList.remove('active'));
        tab.classList.add('active');
        const panel = source === 'sheets' ? el('panel-sheets') : el('panel-csv');
        if (panel) panel.classList.add('active');
      });
    });
  }

  async function loadSheets() {
    const sheetUrl = el('sheet-url').value.trim();
    const gid = el('sheet-gid').value.trim() || '0';
    setStatus('fonte-status', 'Carregando…');
    try {
      const res = await fetch(API + '/api/sheets/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sheet_url: sheetUrl, gid }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }
      const json = await res.json();
      state.data = json.data;
      state.info = json.info;
      setStatus('fonte-status', `Carregados ${json.data.length} reservatórios.`, 'success');
      showKpis(json.data);
    } catch (e) {
      setStatus('fonte-status', e.message || 'Erro ao carregar planilha.', 'error');
    }
  }

  async function processCsv() {
    const input = el('csv-file');
    if (!input || !input.files || !input.files[0]) {
      setStatus('fonte-status', 'Selecione um arquivo .csv.', 'error');
      return;
    }
    setStatus('fonte-status', 'Processando…');
    const form = new FormData();
    form.append('file', input.files[0]);
    try {
      const res = await fetch(API + '/api/csv/process', {
        method: 'POST',
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }
      const json = await res.json();
      state.data = json.data;
      state.info = json.info;
      setStatus('fonte-status', `Processados ${json.data.length} reservatórios.`, 'success');
      showKpis(json.data);
    } catch (e) {
      setStatus('fonte-status', e.message || 'Erro ao processar CSV.', 'error');
    }
  }

  async function generate() {
    if (!state.data || !state.info) {
      setStatus('generate-status', 'Carregue os dados antes.', 'error');
      return;
    }
    setStatus('generate-status', 'Gerando imagem…');
    const mode = el('mode').value;
    const ordenar = el('ordenar').value;
    const formato = el('formato').value;
    const convert = el('convert-m3').checked;
    try {
      const res = await fetch(API + '/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          data: state.data,
          info: state.info,
          mode,
          ordenar,
          formato,
          convert_raw_m3_to_millions: convert,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const img = el('preview-img');
      const link = el('btn-download');
      img.src = url;
      link.href = url;
      link.download = `monitoramento_${formato.toLowerCase() === 'jpg' ? 'stories' : 'feed'}_${Date.now()}.${formato.toLowerCase()}`;
      link.style.display = 'inline-flex';
      el('section-preview').hidden = false;
      setStatus('generate-status', 'Pronto. Use o botão abaixo para baixar.', 'success');
    } catch (e) {
      setStatus('generate-status', e.message || 'Erro ao gerar imagem.', 'error');
    }
  }

  function init() {
    tabs();
    el('btn-load-sheets').addEventListener('click', loadSheets);
    el('btn-process-csv').addEventListener('click', processCsv);
    el('btn-generate').addEventListener('click', generate);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
