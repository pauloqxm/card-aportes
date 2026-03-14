(function () {
  'use strict';

  const API = '';
  const DEFAULT_SHEET_URL = 'https://docs.google.com/spreadsheets/d/15RrQ7ccfZITr2VslQGi1yglLLabKMVFTv5mUepjcW7g/edit?gid=0#gid=0';
  const DEFAULT_GID = '0';
  let state = { data: null, info: null };
  let PRESET_SHEETS = {};
  let lastDownload = null; // { blob, filename, mimeType }
  let currentBaseFilename = 'monitoramento'; // base para nomes de arquivos (gerência + data/hora)

  const el = (id) => document.getElementById(id);

  /** Exibe apenas a primeira metade do link da planilha; o resto fica oculto. */
  function maskSheetUrl(url) {
    if (!url || typeof url !== 'string') return '';
    const s = url.trim();
    if (s.length <= 8) return s;
    const half = Math.max(1, Math.floor(s.length / 2));
    return s.slice(0, half) + ' …';
  }

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

  function buildGerenciaBaciaKey(row) {
    const g = row && row.gerencia != null ? String(row.gerencia).trim() : '';
    const b = row && row.bacia != null ? String(row.bacia).trim() : '';
    if (!g && !b) return '';
    if (g && b) return `${g} — ${b}`;
    return g || b;
  }

  function buildCurrentBaseFilename(dataRows) {
    const fonteSelect = el('fonte-gerencia');
    let label = '';
    if (fonteSelect && fonteSelect.value) {
      label = fonteSelect.value;
    } else {
      const keys = new Set(
        (Array.isArray(dataRows) ? dataRows : []).map((r) => buildGerenciaBaciaKey(r)).filter(Boolean)
      );
      if (keys.size === 1) {
        label = Array.from(keys)[0];
      } else if (keys.size > 1) {
        label = 'GERAL';
      }
    }
    const now = new Date();
    const pad2 = (n) => String(n).padStart(2, '0');
    const ts = `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}_${pad2(
      now.getHours()
    )}${pad2(now.getMinutes())}`;
    const slug =
      (label &&
        label
          .normalize('NFD')
          .replace(/[\u0300-\u036f]/g, '')
          .replace(/[^a-zA-Z0-9]+/g, '_')
          .replace(/^_+|_+$/g, '')) ||
      'GERAL';
    return `monitoramento_${slug}_${ts}`;
  }

  function getUniqueGerencia(data) {
    const rows = Array.isArray(data) ? data : [];
    const set = new Set();
    rows.forEach((r) => {
      const key = buildGerenciaBaciaKey(r);
      if (key && key.toLowerCase() !== 'n/a') set.add(key);
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
      const key = buildGerenciaBaciaKey(r);
      return selected.has(key);
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

  function updateShareButtonVisibility() {
    const btn = el('btn-share-whatsapp');
    if (!btn) return;
    // Botão global de compartilhamento é usado apenas para PDF
    const isPdf = lastDownload && lastDownload.mimeType === 'application/pdf';
    btn.style.display = isPdf ? 'inline-flex' : 'none';
  }

  async function shareViaWhatsApp() {
    if (!lastDownload) {
      alert('Nenhum arquivo gerado para enviar. Gere o card primeiro.');
      return;
    }
    const { blob, filename, mimeType } = lastDownload;

    try {
      const file = new File([blob], filename, { type: mimeType || 'application/octet-stream' });
      if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: 'Monitoramento de Reservatórios',
          text: 'Card de monitoramento gerado pelo sistema.',
        });
        return;
      }
    } catch (e) {
      // fallback abaixo
    }

    // Fallback: abre WhatsApp Web / App com mensagem de texto
    const text = encodeURIComponent('Card de monitoramento gerado. Anexe o arquivo baixado: ' + filename);
    const url = 'https://wa.me/?text=' + text;
    window.open(url, '_blank');
  }

  async function shareImageViaWhatsApp(imageUrl, ext, pageIndex) {
    try {
      const res = await fetch(imageUrl);
      const blob = await res.blob();
      const filename = `${currentBaseFilename}_p${pageIndex}.${ext}`;
      const mimeType = ext === 'jpg' ? 'image/jpeg' : 'image/png';
      const file = new File([blob], filename, { type: mimeType });

      if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: 'Monitoramento de Reservatórios',
          text: `Card de monitoramento (página ${pageIndex}).`,
        });
        return;
      }
    } catch (e) {
      // continua para o fallback
    }

    const text = encodeURIComponent('Card de monitoramento gerado. Anexe a imagem baixada desta página.');
    const url = 'https://wa.me/?text=' + text;
    window.open(url, '_blank');
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
    // Usa link completo (data-full-url quando existe) para não depender do valor mascarado exibido.
    const urlEl = el('sheet-url');
    const gidEl = el('sheet-gid');
    const fullUrl = urlEl && urlEl.getAttribute('data-full-url');
    const sheetUrl = (fullUrl && fullUrl.trim()) || (urlEl && urlEl.value.trim()) || DEFAULT_SHEET_URL;
    const gid = (gidEl && gidEl.value.trim()) || DEFAULT_GID;

    if (!sheetUrl) {
      setStatus('fonte-status', 'Informe o link/ID da planilha.', 'error');
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

      // Aplica filtro inicial pela combinação selecionada no menu "Gerência / Bacia", se houver
      const fonteSelect = el('fonte-gerencia');
      const selectedKey = fonteSelect && fonteSelect.value ? fonteSelect.value : '';
      let dataAll = json.data || [];
      let dataFiltered = dataAll;
      if (selectedKey) {
        dataFiltered = dataAll.filter((r) => buildGerenciaBaciaKey(r) === selectedKey);
      }

      state.data = dataFiltered;
      state.info = json.info;
      setStatus('fonte-status', `Carregados ${dataFiltered.length} reservatórios.`, 'success');
      renderFilterGerencia(dataFiltered);
      showKpis(dataFiltered);
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

      const fonteSelect = el('fonte-gerencia');
      const selectedKey = fonteSelect && fonteSelect.value ? fonteSelect.value : '';
      let dataAll = json.data || [];
      let dataFiltered = dataAll;
      if (selectedKey) {
        dataFiltered = dataAll.filter((r) => buildGerenciaBaciaKey(r) === selectedKey);
      }

      state.data = dataFiltered;
      state.info = json.info;
      setStatus('fonte-status', `Processados ${dataFiltered.length} reservatórios.`, 'success');
      renderFilterGerencia(dataFiltered);
      showKpis(dataFiltered);
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
      setStatus('generate-status', 'Selecione ao menos uma combinação GERÊNCIA + BACIA.', 'error');
      return;
    }
    const totalItems = dataToSend.length;
    const totalPages = Math.ceil(totalItems / 15);
    const mode = el('mode').value;
    const ordenar = el('ordenar').value;
    const formato = el('formato').value;
    const convert = el('convert-m3').checked;
    const ext = formato.toLowerCase();

    // Define base de nome de arquivo (gerência + data/hora)
    currentBaseFilename = buildCurrentBaseFilename(dataToSend);
    const body = JSON.stringify({ data: dataToSend, info: state.info, mode, ordenar, formato, convert_raw_m3_to_millions: convert });
    const headers = { 'Content-Type': 'application/json' };

    // Fluxo especial para PDF: gera um único PDF (A4) via backend.
    if (formato === 'PDF') {
      const endpoint = totalPages <= 1 ? '/api/generate' : '/api/generate-all';
      setStatus('generate-status', 'Gerando PDF…');
      try {
        const res = await fetch(API + endpoint, { method: 'POST', headers, body });
        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          throw new Error(e.detail || res.statusText);
        }
        const pdfBlob = await res.blob();
        lastDownload = {
          blob: pdfBlob,
          filename: `${currentBaseFilename}.pdf`,
          mimeType: 'application/pdf',
        };
        const pdfUrl = URL.createObjectURL(pdfBlob);

        // Limpa prévia de imagens e só oferece botão de download do PDF.
        const container = el('preview-pages');
        if (container) container.innerHTML = '';
        const actions = el('preview-actions');
        if (actions) {
          actions.style.display = 'flex';
          const zipBtn = el('btn-download-zip');
          if (zipBtn) {
            zipBtn.href = pdfUrl;
            zipBtn.download = `${currentBaseFilename}.pdf`;
            zipBtn.textContent = 'Baixar PDF';
            zipBtn.style.display = 'inline-flex';
          }
          const singleBtn = el('btn-download-single');
          if (singleBtn) {
            singleBtn.style.display = 'none';
          }
        }
        const sectionPreview = el('section-preview');
        if (sectionPreview) {
          sectionPreview.hidden = false;
          sectionPreview.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        updateShareButtonVisibility();
        setStatus('generate-status', 'PDF gerado. Use o botão abaixo para baixar.', 'success');
      } catch (e) {
        setStatus('generate-status', e.message || 'Erro ao gerar PDF.', 'error');
      }
      return;
    }

    // Fluxo original para PNG / JPG
    if (totalPages <= 1) {
      // uma única página → fluxo original
      setStatus('generate-status', 'Gerando imagem…');
      try {
        const res = await fetch(API + '/api/generate', { method: 'POST', headers, body });
        if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.statusText); }
        const blob = await res.blob();
        lastDownload = {
          blob,
          filename: `${currentBaseFilename}_p1.${ext}`,
          mimeType: res.headers.get('Content-Type') || (ext === 'jpg' ? 'image/jpeg' : 'image/png'),
        };
        const url = URL.createObjectURL(blob);
        _showPreviews([{ url, label: 'Página 1', ext }]);
        updateShareButtonVisibility();
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
        lastDownload = {
          blob: zipBlob,
          filename: `${currentBaseFilename}.zip`,
          mimeType: 'application/zip',
        };
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
        updateShareButtonVisibility();
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
      dlBtn.download = `${currentBaseFilename}_p${i + 1}.${p.ext}`;
      dlBtn.className = 'btn btn-download-secondary';
      dlBtn.textContent = `Baixar página ${i + 1}`;

      wrap.appendChild(label);
      wrap.appendChild(imgWrap);
      wrap.appendChild(dlBtn);

      // Para PNG/JPG, adiciona botão de enviar por WhatsApp ao lado do botão de download
      if (p.ext === 'png' || p.ext === 'jpg') {
        const waBtn = document.createElement('button');
        waBtn.type = 'button';
        waBtn.className = 'btn btn-download-secondary';
        waBtn.textContent = 'Enviar por WhatsApp';
        waBtn.addEventListener('click', () => {
          shareImageViaWhatsApp(p.url, p.ext, i + 1);
        });
        wrap.appendChild(waBtn);
      }
      container.appendChild(wrap);
    });

    if (actions) {
      actions.style.display = previews.length > 0 || zipUrl ? 'flex' : 'none';
      const zipBtn = el('btn-download-zip');
      if (zipUrl && zipBtn) {
        zipBtn.href = zipUrl;
        zipBtn.download = zipName || `${currentBaseFilename}.zip`;
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

    const urlInput = el('sheet-url');
    const gidInput = el('sheet-gid');
    // Planilha geral padrão: guarda o link completo e exibe 50% oculto
    if (urlInput) {
      urlInput.setAttribute('data-full-url', DEFAULT_SHEET_URL);
      urlInput.value = maskSheetUrl(DEFAULT_SHEET_URL);
      urlInput.readOnly = true;
    }
    if (gidInput) {
      gidInput.value = DEFAULT_GID;
      gidInput.readOnly = true;
    }

    // Carrega a lista de gerências/bacias para o menu suspenso informativo
    loadFontes();

    const btnShare = el('btn-share-whatsapp');
    if (btnShare) {
      btnShare.addEventListener('click', () => {
        shareViaWhatsApp();
      });
    }

    const topbarToggle = el('topbar-menu-toggle');
    const topbarNav = el('topbar-nav');
    if (topbarToggle && topbarNav) {
      topbarToggle.addEventListener('click', () => {
        const isOpen = topbarNav.classList.toggle('open');
        topbarToggle.classList.toggle('open', isOpen);
      });
      // Fecha o menu ao clicar em qualquer link
      topbarNav.querySelectorAll('a').forEach((link) => {
        link.addEventListener('click', () => {
          topbarNav.classList.remove('open');
          topbarToggle.classList.remove('open');
        });
      });
    }
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

      fonteSelect.innerHTML = fontes.length
        ? '<option value="">Todas as gerências / bacias</option>'
        : '<option value="">Nenhuma gerência encontrada</option>';

      fontes.forEach((f) => {
        const label = f.bacia ? `${f.gerencia} — ${f.bacia}` : f.gerencia;
        const opt = document.createElement('option');
        opt.value = label; // mesmo formato usado em buildGerenciaBaciaKey
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
