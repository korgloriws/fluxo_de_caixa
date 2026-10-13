/* Utilitários compartilhados de autenticação e tema. */

window.AuthUI = (() => {
  'use strict';

  const $ = (seletor) => document.querySelector(seletor);

  let onPerfilAtualizado = null;

  function notificar(mensagem, tipo = 'info') {
    const caixa = document.createElement('div');
    caixa.className = `notificacao notificacao--${tipo}`;
    caixa.innerHTML = `<div>${mensagem}</div>`;
    const host = $('#notificacoes');
    if (!host) return;
    host.appendChild(caixa);
    setTimeout(() => {
      caixa.classList.add('saindo');
      setTimeout(() => caixa.remove(), 200);
    }, 4000);
  }

  function withRoot(url) {
    if (typeof window.withRoot === 'function') return window.withRoot(url);
    return url;
  }

  async function requisitar(url, opcoes = {}) {
    const resposta = await fetch(withRoot(url), opcoes);
    const tipo = resposta.headers.get('content-type') || '';
    if (!resposta.ok) {
      let detalhe = `Erro ${resposta.status}`;
      if (tipo.includes('application/json')) {
        const corpo = await resposta.json().catch(() => null);
        if (corpo && corpo.erro) detalhe = corpo.erro;
      }
      throw new Error(detalhe);
    }
    return tipo.includes('application/json') ? resposta.json() : resposta;
  }

  function aplicarTema(tema) {
    document.documentElement.dataset.tema = tema;
    localStorage.setItem('fundeb-tema', tema);
    const claro = document.querySelector('.icone-claro');
    const escuro = document.querySelector('.icone-escuro');
    if (claro) claro.style.display = tema === 'claro' ? '' : 'none';
    if (escuro) escuro.style.display = tema === 'escuro' ? '' : 'none';
  }

  function ligarTema() {
    const btn = $('#btn-tema');
    if (!btn) return;
    aplicarTema(document.documentElement.dataset.tema || 'claro');
    btn.addEventListener('click', () => {
      aplicarTema(document.documentElement.dataset.tema === 'escuro' ? 'claro' : 'escuro');
    });
  }

  function abrirLogin() {
    const modal = $('#modal-login');
    if (!modal) return;
    $('#login-usuario').value = '';
    $('#login-senha').value = '';
    modal.classList.add('aberto');
    setTimeout(() => $('#login-usuario').focus(), 60);
  }

  function fecharLogin() {
    const modal = $('#modal-login');
    if (modal) modal.classList.remove('aberto');
  }

  async function login(login, senha) {
    const corpo = new FormData();
    corpo.append('login', login);
    corpo.append('senha', senha);
    return requisitar('/api/auth/login', { method: 'POST', body: corpo });
  }

  async function logout() {
    return requisitar('/api/auth/logout', { method: 'POST' });
  }

  async function me() {
    return requisitar('/api/auth/me');
  }

  async function atualizarPerfil(payload) {
    return requisitar('/api/auth/perfil', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  function escaparHtml(texto) {
    return String(texto || '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
  }

  function iniciaisNome(nome) {
    const partes = String(nome || '')
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!partes.length) return '?';
    if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
    return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
  }

  function htmlBotaoPerfil(usuario) {
    const nome = escaparHtml(usuario.nome || 'Usuário');
    const iniciais = escaparHtml(iniciaisNome(usuario.nome));
    return `
      <span class="btn-perfil-avatar" aria-hidden="true">${iniciais}</span>
      <span class="btn-perfil-corpo">
        <span class="btn-perfil-rotulo">Perfil</span>
        <span class="btn-perfil-nome">${nome}</span>
      </span>
      <svg class="btn-perfil-seta" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <polyline points="9 18 15 12 9 6"/>
      </svg>
    `;
  }

  function preencherBotaoPerfil(el, usuario) {
    if (!el || !usuario) return;
    el.className = 'btn-perfil';
    el.type = 'button';
    el.disabled = false;
    el.hidden = false;
    el.title = 'Abrir meu perfil — alterar nome ou senha';
    el.setAttribute('aria-label', `Perfil de ${usuario.nome}`);
    el.innerHTML = htmlBotaoPerfil(usuario);
  }

  function marcarVisualizando(el) {
    if (!el) return;
    el.className = 'sessao-status';
    el.type = 'button';
    el.disabled = true;
    el.hidden = false;
    el.title = '';
    el.removeAttribute('aria-label');
    el.textContent = 'Visualizando';
  }

  function abrirPerfil(usuario) {
    const modal = $('#modal-perfil');
    if (!modal) return;
    if (!usuario) {
      notificar('Faça login para editar seu perfil.', 'erro');
      return;
    }
    $('#perfil-nome').value = usuario.nome || '';
    $('#perfil-login').value = usuario.login || '';
    $('#perfil-senha-atual').value = '';
    $('#perfil-senha-nova').value = '';
    $('#perfil-senha-conf').value = '';
    modal.classList.add('aberto');
    setTimeout(() => $('#perfil-nome').focus(), 60);
  }

  function fecharPerfil() {
    const modal = $('#modal-perfil');
    if (modal) modal.classList.remove('aberto');
  }

  function ligarModalLogin({ onSuccess } = {}) {
    const modal = $('#modal-login');
    if (!modal) return;

    $('#btn-cancelar-login')?.addEventListener('click', fecharLogin);
    modal.addEventListener('click', (e) => {
      if (e.target.id === 'modal-login') fecharLogin();
    });

    const confirmar = async () => {
      try {
        const dados = await login($('#login-usuario').value.trim(), $('#login-senha').value);
        fecharLogin();
        notificar(`Bem-vindo(a), ${dados.usuario.nome}.`, 'sucesso');
        if (onSuccess) onSuccess(dados.usuario);
      } catch (erro) {
        notificar(erro.message, 'erro');
        $('#login-senha')?.select();
      }
    };

    $('#btn-confirmar-login')?.addEventListener('click', confirmar);
    $('#login-senha')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') confirmar();
      if (e.key === 'Escape') fecharLogin();
    });
    $('#login-usuario')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') $('#login-senha')?.focus();
      if (e.key === 'Escape') fecharLogin();
    });
  }

  function ligarModalPerfil({ getUsuario, onSuccess } = {}) {
    if (onSuccess !== undefined) onPerfilAtualizado = onSuccess;

    const modal = $('#modal-perfil');
    if (!modal || modal.dataset.ligado === '1') return;
    modal.dataset.ligado = '1';

    $('#btn-cancelar-perfil')?.addEventListener('click', fecharPerfil);
    modal.addEventListener('click', (e) => {
      if (e.target.id === 'modal-perfil') fecharPerfil();
    });

    const salvar = async () => {
      const senhaNova = $('#perfil-senha-nova')?.value || '';
      const senhaConf = $('#perfil-senha-conf')?.value || '';
      if (senhaNova || senhaConf) {
        if (senhaNova !== senhaConf) {
          notificar('A confirmação da nova senha não confere.', 'erro');
          $('#perfil-senha-conf')?.select();
          return;
        }
      }
      if (!($('#perfil-senha-atual')?.value || '')) {
        notificar('Informe a senha atual para salvar.', 'erro');
        $('#perfil-senha-atual')?.focus();
        return;
      }

      try {
        const dados = await atualizarPerfil({
          nome: $('#perfil-nome').value.trim(),
          login: $('#perfil-login').value.trim(),
          senha_atual: $('#perfil-senha-atual').value,
          senha_nova: senhaNova,
          senha_nova_conf: senhaConf,
        });
        fecharPerfil();
        notificar('Perfil atualizado.', 'sucesso');
        if (onPerfilAtualizado) onPerfilAtualizado(dados.usuario);
      } catch (erro) {
        notificar(erro.message, 'erro');
        $('#perfil-senha-atual')?.select();
      }
    };

    $('#btn-salvar-perfil')?.addEventListener('click', salvar);
    ['#perfil-senha-atual', '#perfil-senha-nova', '#perfil-senha-conf'].forEach((sel) => {
      $(sel)?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') salvar();
        if (e.key === 'Escape') fecharPerfil();
      });
    });
  }

  function renderPortalAuth(usuario) {
    const host = $('#portal-auth');
    if (!host) return;

    const temaBtn = host.querySelector('#btn-tema');
    const fragment = document.createDocumentFragment();

    if (usuario) {
      const status = document.createElement('button');
      preencherBotaoPerfil(status, usuario);
      status.addEventListener('click', () => abrirPerfil(usuario));
      fragment.appendChild(status);

      if (usuario.eh_admin) {
        const link = document.createElement('a');
        link.className = 'btn btn-portal';
        link.href = withRoot('/usuarios');
        link.textContent = 'Usuários';
        link.title = 'Somente administrador';
        fragment.appendChild(link);
      }

      const sair = document.createElement('button');
      sair.className = 'btn btn-portal';
      sair.textContent = 'Sair';
      sair.addEventListener('click', async () => {
        await logout();
        location.reload();
      });
      fragment.appendChild(sair);
    } else {
      const entrar = document.createElement('button');
      entrar.className = 'btn btn-primario';
      entrar.textContent = 'Entrar';
      entrar.title = 'Para editar módulos';
      entrar.addEventListener('click', abrirLogin);
      fragment.appendChild(entrar);
    }

    host.innerHTML = '';
    host.appendChild(fragment);
    if (temaBtn) {
      temaBtn.classList.add('btn-portal');
      host.appendChild(temaBtn);
    }
  }

  function initPortal({ next } = {}) {
    let usuarioPortal = null;
    ligarTema();
    ligarModalLogin({
      onSuccess: (usuario) => {
        if (next) {
          location.href = withRoot(next);
          return;
        }
        usuarioPortal = usuario;
        renderPortalAuth(usuario);
      },
    });
    ligarModalPerfil({
      getUsuario: () => usuarioPortal,
      onSuccess: (usuario) => {
        usuarioPortal = usuario;
        renderPortalAuth(usuario);
      },
    });

    me()
      .then((dados) => {
        usuarioPortal = dados.usuario;
        renderPortalAuth(dados.usuario);
        const params = new URLSearchParams(location.search);
        if (params.get('login') === '1' && !dados.autenticado) abrirLogin();
      })
      .catch(() => renderPortalAuth(null));
  }

  return {
    notificar,
    requisitar,
    aplicarTema,
    ligarTema,
    abrirLogin,
    fecharLogin,
    login,
    logout,
    me,
    atualizarPerfil,
    abrirPerfil,
    fecharPerfil,
    preencherBotaoPerfil,
    marcarVisualizando,
    ligarModalLogin,
    ligarModalPerfil,
    initPortal,
  };
})();
