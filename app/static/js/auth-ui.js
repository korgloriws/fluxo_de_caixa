/* Utilitários compartilhados de autenticação e tema. */

window.AuthUI = (() => {
  'use strict';

  const $ = (seletor) => document.querySelector(seletor);

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

  async function requisitar(url, opcoes = {}) {
    const resposta = await fetch(url, opcoes);
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

  function renderPortalAuth(usuario) {
    const host = $('#portal-auth');
    if (!host) return;

    const temaBtn = host.querySelector('#btn-tema');
    const fragment = document.createDocumentFragment();

    if (usuario) {
      const status = document.createElement('span');
      status.className = 'sessao-status sessao-status--ativo';
      status.textContent = usuario.nome;
      fragment.appendChild(status);

      if (usuario.eh_admin) {
        const link = document.createElement('a');
        link.className = 'btn btn-portal';
        link.href = '/usuarios';
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
    ligarTema();
    ligarModalLogin({
      onSuccess: (usuario) => {
        if (next) {
          location.href = next;
          return;
        }
        renderPortalAuth(usuario);
      },
    });

    me()
      .then((dados) => {
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
    ligarModalLogin,
    initPortal,
  };
})();
