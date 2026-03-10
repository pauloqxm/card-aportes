(function () {
  'use strict';

  const API = '';
  let state = { data: null, info: null };
  let PRESET_SHEETS = {};

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

  function getUniqueGerencia(data) {
    const rows = Array.isArray(data) ? data : [];
    const set = new Set();
    rows.forEach((r) => {
      const g = r.gerencia != null ? String(r.gerencia).trim() : '';
      if (g && g.toLowerCase() !== 'n/a') set.add(g);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }

  function getFilteredData() {
    if (!state.data) return [];
    const list = el('filter-gerencia-list');
    if (!list) return state.data;
    const checked = list.querySelectorAll('input[type="checkbox"]:checked');
    if (checked.length === 0) return state.data;
    const selected = new Set(Array.from(checked).map((c) => c.value));
    return state.data.filter((r) => {
      const g = r.gerencia != null ? String(r.gerencia).trim() : '';
      return selected.has(g);
    });
  }

  function renderFilterGerencia(data) {
    const container = el('filter-gerencia-list');
    const section = el('section-filter-gerencia');
    if (!container || !section) return;
    const gerenciaList = getUniqueGerencia(data);
    if (gerenciaList.length === 0) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    container.innerHTML = gerenciaList
      .map(
        (g) =>
          `<label class="filtro-check"><input type="checkbox" name="gerencia" value="${escapeAttr(g)}" checked> ${escapeText(g)}</label>`
      )
      .join('');
    container.querySelectorAll('input[name="gerencia"]').forEach((cb) => {
      cb.addEventListener('change', () => {
        showKpis(getFilteredData());
      });
    });
  }

  function escapeAttr(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML.replace(/"/g, '&quot;');
  }
  function escapeText(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function selectAllGerencia(checked) {
    const list = el('filter-gerencia-list');
    if (!list) return;
    list.querySelectorAll('input[name="gerencia"]').forEach((cb) => {
      cb.checked = checked;
    });
    showKpis(getFilteredData());
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
    // Prioridade: preset da gerência selecionada; fallback: campos manuais
    const fonteSelect = el('fonte-gerencia');
    let sheetUrl = '';
    let gid = '0';

    if (fonteSelect && fonteSelect.value && PRESET_SHEETS[fonteSelect.value]) {
      const cfg = PRESET_SHEETS[fonteSelect.value];
      sheetUrl = cfg.url;
      gid = cfg.gid;
      const urlEl = el('sheet-url');
      const gidEl = el('sheet-gid');
      if (urlEl) { urlEl.value = sheetUrl; urlEl.readOnly = true; }
      if (gidEl) { gidEl.value = gid; gidEl.readOnly = true; }
    } else {
      sheetUrl = el('sheet-url') ? el('sheet-url').value.trim() : '';
      gid      = el('sheet-gid') ? (el('sheet-gid').value.trim() || '0') : '0';
    }

    if (!sheetUrl) {
      setStatus('fonte-status', 'Selecione uma gerência no campo acima ou informe o link/ID da planilha.', 'error');
      return;
    }
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
      renderFilterGerencia(json.data);
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
      renderFilterGerencia(json.data);
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
    const dataToSend = getFilteredData();
    if (dataToSend.length === 0) {
      setStatus('generate-status', 'Selecione ao menos uma GERÊNCIA.', 'error');
      return;
    }
    const totalItems = dataToSend.length;
    const totalPages = Math.ceil(totalItems / 15);
    const mode = el('mode').value;
    const ordenar = el('ordenar').value;
    const formato = el('formato').value;
    const convert = el('convert-m3').checked;
    const ext = formato.toLowerCase();
    const body = JSON.stringify({ data: dataToSend, info: state.info, mode, ordenar, formato, convert_raw_m3_to_millions: convert });
    const headers = { 'Content-Type': 'application/json' };

    if (totalPages <= 1) {
      // uma única página → fluxo original
      setStatus('generate-status', 'Gerando imagem…');
      try {
        const res = await fetch(API + '/api/generate', { method: 'POST', headers, body });
        if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.statusText); }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        _showPreviews([{ url, label: 'Página 1', ext }]);
        setStatus('generate-status', 'Pronto. Use o botão abaixo para baixar.', 'success');
      } catch (e) {
        setStatus('generate-status', e.message || 'Erro ao gerar imagem.', 'error');
      }
    } else {
      // múltiplas páginas → gera ZIP e extrai cada imagem para prévia
      setStatus('generate-status', `Gerando ${totalPages} páginas…`);
      try {
        const res = await fetch(API + '/api/generate-all', { method: 'POST', headers, body });
        if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.statusText); }
        const zipBlob = await res.blob();
        const zipUrl = URL.createObjectURL(zipBlob);

        // Usa JSZip para extrair as imagens do ZIP e mostrar prévia
        let previews = [];
        try {
          const JSZip = window.JSZip;
          if (JSZip) {
            const zip = await JSZip.loadAsync(zipBlob);
            const files = Object.keys(zip.files).sort();
            for (const fname of files) {
              const imgBlob = await zip.files[fname].async('blob');
              previews.push({ url: URL.createObjectURL(imgBlob), label: fname.replace(/_/g, ' ').replace('.'+ext,''), ext });
            }
          }
        } catch (_) {}

        if (previews.length === 0) {
          // sem JSZip: apenas botão de download do ZIP
          previews = [];
        }
        _showPreviews(previews, zipUrl, `monitoramento_cards.zip`);
        setStatus('generate-status', `${totalPages} páginas geradas. Baixe o ZIP com todas.`, 'success');
      } catch (e) {
        setStatus('generate-status', e.message || 'Erro ao gerar imagens.', 'error');
      }
    }
  }

  function _showPreviews(previews, zipUrl, zipName) {
    const container = el('preview-pages');
    const actions = el('preview-actions');
    if (!container) return;
    container.innerHTML = '';

    previews.forEach((p, i) => {
      const wrap = document.createElement('div');
      wrap.className = 'preview-page-block';
      const label = document.createElement('p');
      label.className = 'preview-page-label';
      label.textContent = p.label || `Página ${i + 1}`;
      const imgWrap = document.createElement('div');
      imgWrap.className = 'preview-img-wrap';
      const img = document.createElement('img');
      img.src = p.url;
      img.alt = p.label || `Página ${i + 1}`;
      img.className = 'preview-page-img';
      img.loading = 'lazy';
      imgWrap.appendChild(img);
      const dlBtn = document.createElement('a');
      dlBtn.href = p.url;
      dlBtn.download = `monitoramento_p${i + 1}.${p.ext}`;
      dlBtn.className = 'btn btn-download-secondary';
      dlBtn.textContent = `Baixar página ${i + 1}`;
      wrap.appendChild(label);
      wrap.appendChild(imgWrap);
      wrap.appendChild(dlBtn);
      container.appendChild(wrap);
    });

    if (actions) {
      actions.style.display = previews.length > 0 || zipUrl ? 'flex' : 'none';
      const zipBtn = el('btn-download-zip');
      if (zipUrl && zipBtn) {
        zipBtn.href = zipUrl;
        zipBtn.download = zipName || 'monitoramento_cards.zip';
        zipBtn.style.display = 'inline-flex';
      } else if (zipBtn) {
        zipBtn.style.display = 'none';
      }
    }
    const sectionPreview = el('section-preview');
    if (sectionPreview) {
      sectionPreview.hidden = false;
      sectionPreview.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function init() {
    tabs();
    el('btn-load-sheets').addEventListener('click', loadSheets);
    el('btn-process-csv').addEventListener('click', processCsv);
    el('btn-generate').addEventListener('click', generate);
    const btnSelectAll = el('btn-select-all-gerencia');
    const btnClearAll = el('btn-clear-all-gerencia');
    if (btnSelectAll) btnSelectAll.addEventListener('click', () => selectAllGerencia(true));
    if (btnClearAll) btnClearAll.addEventListener('click', () => selectAllGerencia(false));

    const fonteSelect = el('fonte-gerencia');
    const urlInput = el('sheet-url');
    const gidInput = el('sheet-gid');
    if (fonteSelect) {
      fonteSelect.addEventListener('change', () => {
        const cfg = PRESET_SHEETS[fonteSelect.value];
        if (cfg) {
          if (urlInput) { urlInput.value = cfg.url; urlInput.readOnly = true; }
          if (gidInput) { gidInput.value = cfg.gid; gidInput.readOnly = true; }
        } else {
          if (urlInput) { urlInput.value = ''; urlInput.readOnly = false; }
          if (gidInput) { gidInput.value = '0'; gidInput.readOnly = false; }
        }
      });
    }

    loadFontes();
  }

  async function loadFontes() {
    const fonteSelect = el('fonte-gerencia');
    if (!fonteSelect) return;
    try {
      const res = await fetch(API + '/api/fontes', { credentials: 'same-origin' });
      if (!res.ok) {
        fonteSelect.innerHTML = '<option value="">Erro ao carregar gerências</option>';
        return;
      }
      const json = await res.json();
      const fontes = json.fontes || [];
      PRESET_SHEETS = {};
      fontes.forEach((f) => { PRESET_SHEETS[f.gerencia] = { url: f.url, gid: f.gid }; });

      fonteSelect.innerHTML = fontes.length
        ? '<option value="">Selecione uma gerência...</option>'
        : '<option value="">Nenhuma gerência (informe o link abaixo)</option>';
      fontes.forEach((f) => {
        const label = f.bacia ? `${f.gerencia} — ${f.bacia}` : f.gerencia;
        const opt = document.createElement('option');
        opt.value = f.gerencia;
        opt.textContent = label;
        fonteSelect.appendChild(opt);
      });
    } catch (_) {
      fonteSelect.innerHTML = '<option value="">Erro ao carregar gerências</option>';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
