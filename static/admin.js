(function () {
  'use strict';

  const API = '';

  const el = (id) => document.getElementById(id);

  async function checkSession() {
    const loginBox = el('admin-login-box');
    const dashboard = el('admin-dashboard');
    try {
      const res = await fetch(API + '/api/admin/me', { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        el('admin-username').textContent = data.username || '';
        if (loginBox) loginBox.hidden = true;
        if (dashboard) dashboard.hidden = false;
        return;
      }
    } catch (_) {}
    if (loginBox) loginBox.hidden = false;
    if (dashboard) dashboard.hidden = true;
  }

  function init() {
    checkSession();

    const form = document.getElementById('login-form');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const user = el('admin-user').value.trim();
        const pwd = el('admin-password').value;
        const errEl = el('login-error');
        errEl.hidden = true;
        errEl.textContent = '';
        try {
          const res = await fetch(API + '/api/admin/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ username: user, password: pwd }),
          });
          if (res.ok) {
            await checkSession();
            return;
          }
          const data = await res.json().catch(() => ({}));
          errEl.textContent = data.detail || 'Usuário ou senha inválidos.';
          errEl.hidden = false;
        } catch (_) {
          errEl.textContent = 'Erro de conexão.';
          errEl.hidden = false;
        }
      });
    }

    const logoutBtn = el('admin-logout');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', async () => {
        try {
          await fetch(API + '/api/admin/logout', {
            method: 'POST',
            credentials: 'include',
          });
        } catch (_) {}
        await checkSession();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
