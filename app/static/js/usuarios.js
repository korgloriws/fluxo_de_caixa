(() => {
  'use strict';

  const $ = (s) => document.querySelector(s);

  function notificar(mensagem, tipo = 'info') {
    const caixa = document.createElement('div');
    caixa.className = `notificacao notificacao--${tipo}`;
    caixa.innerHTML = `<div>${mensagem}</div>`;
    $('#notificacoes').appendChild(caixa);
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
    $('.icone-claro').style.display = tema === 'claro' ? '' : 'none';
    $('.icone-escuro').style.display = tema === 'escuro' ? '' : 'none';
  }

  $('#btn-tema').addEventListener('click', () => {
    aplicarTema(document.documentElement.dataset.tema === 'escuro' ? 'claro' : 'escuro');
  });
  aplicarTema(document.documentElement.dataset.tema || 'claro');

  let editandoId = null;

  function abrirModal(usuario) {
    editandoId = usuario ? usuario.id : null;
    $('#modal-usuario-titulo').textContent = usuario ? 'Editar usuário' : 'Novo usuário';
    $('#usuario-id').value = usuario ? usuario.id : '';
    $('#usuario-nome').value = usuario ? usuario.nome : '';
    $('#usuario-login').value = usuario ? usuario.login : '';
    $('#usuario-senha').value = '';
    $('#senha-dica').textContent = usuario ? '(deixe em branco para manter)' : '(mín. 4)';
    $('#usuario-admin').checked = !!(usuario && usuario.eh_admin);
    $('#usuario-ativo').checked = usuario ? !!usuario.ativo : true;
    $('#modal-usuario').classList.add('aberto');
    setTimeout(() => $('#usuario-nome').focus(), 60);
  }

  function fecharModal() {
    $('#modal-usuario').classList.remove('aberto');
    editandoId = null;
  }

  async function carregar() {
    const dados = await requisitar('/api/usuarios');
    $('#corpo-usuarios').innerHTML = dados.usuarios
      .map(
        (u) => `
      <tr>
        <td>${escapar(u.nome)}</td>
        <td><code>${escapar(u.login)}</code></td>
        <td>${u.eh_admin ? '<span class="etiqueta etiqueta--alerta">Admin</span>' : '<span class="etiqueta etiqueta--neutra">Editor</span>'}</td>
        <td>${u.ativo ? '<span class="etiqueta etiqueta--ok">Ativo</span>' : '<span class="etiqueta etiqueta--erro">Inativo</span>'}</td>
        <td class="acoes-linha">
          <button class="btn btn-pequeno" data-editar="${u.id}">Editar</button>
          <button class="btn btn-pequeno" data-excluir="${u.id}">Excluir</button>
        </td>
      </tr>`
      )
      .join('');

    window.__usuariosCache = dados.usuarios;
  }

  function escapar(texto) {
    return String(texto || '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
  }

  $('#btn-novo-usuario').addEventListener('click', () => abrirModal(null));
  $('#btn-cancelar-usuario').addEventListener('click', fecharModal);
  $('#modal-usuario').addEventListener('click', (e) => {
    if (e.target.id === 'modal-usuario') fecharModal();
  });

  $('#corpo-usuarios').addEventListener('click', (e) => {
    const editar = e.target.closest('[data-editar]');
    const excluir = e.target.closest('[data-excluir]');
    if (editar) {
      const id = Number(editar.dataset.editar);
      const usuario = (window.__usuariosCache || []).find((u) => u.id === id);
      if (usuario) abrirModal(usuario);
    }
    if (excluir) {
      const id = Number(excluir.dataset.excluir);
      if (!confirm('Excluir este usuário?')) return;
      requisitar(`/api/usuarios/${id}`, { method: 'DELETE' })
        .then(() => {
          notificar('Usuário excluído.', 'sucesso');
          carregar();
        })
        .catch((erro) => notificar(erro.message, 'erro'));
    }
  });

  $('#btn-salvar-usuario').addEventListener('click', async () => {
    const payload = {
      nome: $('#usuario-nome').value.trim(),
      login: $('#usuario-login').value.trim(),
      senha: $('#usuario-senha').value,
      eh_admin: $('#usuario-admin').checked,
      ativo: $('#usuario-ativo').checked,
    };

    try {
      if (editandoId) {
        if (!payload.senha) delete payload.senha;
        await requisitar(`/api/usuarios/${editandoId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        notificar('Usuário atualizado.', 'sucesso');
      } else {
        await requisitar('/api/usuarios', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        notificar('Usuário criado.', 'sucesso');
      }
      fecharModal();
      carregar();
    } catch (erro) {
      notificar(erro.message, 'erro');
    }
  });

  carregar().catch((erro) => {
    notificar(erro.message, 'erro');
    if (String(erro.message).includes('401') || String(erro.message).toLowerCase().includes('login')) {
      location.href = '/?login=1&next=/usuarios';
    }
  });
})();
