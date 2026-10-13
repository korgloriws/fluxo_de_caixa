/* Módulo Extrato BB — consulta visual da API Extratos. */
(() => {
  const estado = {
    pagina: 1,
    porPagina: 50,
    glossario: [],
  };

  const $ = (sel) => document.querySelector(sel);

  function temaSync() {
    const atual = document.documentElement.dataset.tema;
    const claro = document.querySelector('.icone-claro');
    const escuro = document.querySelector('.icone-escuro');
    if (claro && escuro) {
      claro.style.display = atual === 'escuro' ? 'none' : '';
      escuro.style.display = atual === 'escuro' ? '' : 'none';
    }
  }

  function notificar(texto, tipo = 'info') {
    const box = $('#notificacoes');
    if (!box) return;
    const el = document.createElement('div');
    el.className = `notificacao notificacao--${tipo}`;
    el.textContent = texto;
    box.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function paramsConsulta() {
    const q = new URLSearchParams();
    const inicio = $('#bb-inicio')?.value;
    const fim = $('#bb-fim')?.value;
    const sinal = $('#bb-sinal')?.value;
    const historico = $('#bb-historico')?.value;
    const busca = $('#bb-busca')?.value?.trim();
    const saldos = $('#bb-saldos')?.checked;
    if (inicio) q.set('inicio', inicio);
    if (fim) q.set('fim', fim);
    if (sinal) q.set('sinal', sinal);
    if (historico) q.set('historico', historico);
    if (busca) q.set('busca', busca);
    if (saldos) q.set('incluir_saldos', 'true');
    q.set('pagina', String(estado.pagina));
    q.set('por_pagina', String(estado.porPagina));
    return q;
  }

  function preencherHistoricos(lista) {
    const sel = $('#bb-historico');
    if (!sel) return;
    const atual = sel.value;
    sel.innerHTML = '<option value="">Todos</option>';
    (lista || []).forEach((h) => {
      const opt = document.createElement('option');
      opt.value = h;
      opt.textContent = h;
      sel.appendChild(opt);
    });
    if (atual && [...sel.options].some((o) => o.value === atual)) {
      sel.value = atual;
    }
  }

  function renderAviso(meta) {
    const el = $('#bb-aviso');
    if (!el) return;
    if (!meta?.aviso) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.className = 'bb-aviso' + (meta.modo === 'sandbox' ? ' bb-aviso--sandbox' : ' bb-aviso--prod');
    const arquivos = (meta.arquivos || []).join(', ') || '—';
    el.innerHTML = `
      <strong>${meta.modo === 'sandbox' ? 'Ambiente de teste (sandbox)' : 'Produção'}</strong>
      <span>${meta.aviso}</span>
      <small>Fonte: ${arquivos} · ${meta.total_carregado || 0} registros carregados</small>
    `;
  }

  function renderResumo(resumo) {
    $('#bb-qtd').textContent = resumo?.quantidade ?? '—';
    $('#bb-total-c').textContent = resumo?.total_creditos_exibicao ?? '—';
    $('#bb-total-d').textContent = resumo?.total_debitos_exibicao ?? '—';
    $('#bb-resultado').textContent = resumo?.resultado_exibicao ?? '—';
    $('#bb-qtd-c').textContent = resumo ? `${resumo.creditos} entradas` : '';
    $('#bb-qtd-d').textContent = resumo ? `${resumo.debitos} saídas` : '';
  }

  function badgeSinal(row) {
    if (row.eh_saldo) return '<span class="bb-badge bb-badge--saldo">Saldo</span>';
    if (row.sinal === 'C') return '<span class="bb-badge bb-badge--c">Crédito</span>';
    if (row.sinal === 'D') return '<span class="bb-badge bb-badge--d">Débito</span>';
    return `<span class="bb-badge">${row.sinal || '?'}</span>`;
  }

  function renderTabela(lancamentos) {
    const corpo = $('#bb-corpo');
    if (!corpo) return;
    if (!lancamentos?.length) {
      corpo.innerHTML = '<tr><td colspan="7" class="bb-vazio">Nenhum lançamento com estes filtros.</td></tr>';
      return;
    }
    corpo.innerHTML = lancamentos
      .map(
        (row) => `
      <tr class="${row.eh_saldo ? 'bb-linha-saldo' : ''}">
        <td class="bb-td-data">${row.data_exibicao || '—'}</td>
        <td class="bb-td-sinal">${badgeSinal(row)}</td>
        <td class="num ${row.sinal === 'D' ? 'bb-valor-d' : 'bb-valor-c'}">${row.valor_exibicao}</td>
        <td class="bb-td-hist">${escapeHtml(row.historico)}</td>
        <td class="bb-col-doc">${escapeHtml(row.numero_documento)}</td>
        <td class="bb-col-comp bb-comp">${escapeHtml(row.complemento || '—')}</td>
        <td class="bb-col-acao"><button type="button" class="btn btn-fantasma btn-sm" data-detalhe="${escapeAttr(row.id)}">Detalhe</button></td>
      </tr>`
      )
      .join('');
  }

  function renderPaginacao(pag) {
    const el = $('#bb-paginacao');
    if (!el || !pag) return;
    el.innerHTML = `
      <button type="button" class="btn" id="bb-ant" ${pag.pagina <= 1 ? 'disabled' : ''}>Anterior</button>
      <span>Página ${pag.pagina} de ${pag.total_paginas} · ${pag.total} registro(s)</span>
      <button type="button" class="btn" id="bb-prox" ${pag.pagina >= pag.total_paginas ? 'disabled' : ''}>Próxima</button>
    `;
    $('#bb-ant')?.addEventListener('click', () => {
      estado.pagina = Math.max(1, estado.pagina - 1);
      carregar();
    });
    $('#bb-prox')?.addEventListener('click', () => {
      estado.pagina += 1;
      carregar();
    });
  }

  function renderGlossario(lista) {
    const box = $('#bb-glossario');
    if (!box) return;
    box.innerHTML = (lista || [])
      .map(
        (g) => `
      <article class="bb-glossa-item">
        <h3>${escapeHtml(g.rotulo)}</h3>
        <code>${escapeHtml(g.campo)}</code>
        <p>${escapeHtml(g.explicacao)}</p>
      </article>`
      )
      .join('');
  }

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, '&#39;');
  }

  async function carregar() {
    const barra = $('#barra-carregando');
    if (barra) barra.classList.add('ativo');
    try {
      const url = `/api/bb-extrato?${paramsConsulta().toString()}`;
      const resp = await fetch(window.withRoot ? window.withRoot(url) : url);
      if (!resp.ok) throw new Error('Falha ao carregar extrato');
      const dados = await resp.json();
      estado.glossario = dados.glossario || estado.glossario;
      renderAviso(dados.meta);
      renderResumo(dados.resumo);
      preencherHistoricos(dados.historicos);
      renderTabela(dados.lancamentos);
      renderPaginacao(dados.paginacao);
      if (!$('#bb-glossario')?.dataset.ready) {
        renderGlossario(dados.glossario);
        if ($('#bb-glossario')) $('#bb-glossario').dataset.ready = '1';
      }
    } catch (err) {
      console.error(err);
      notificar(err.message || 'Erro ao consultar extrato', 'erro');
      $('#bb-corpo').innerHTML =
        '<tr><td colspan="7" class="bb-vazio">Não foi possível carregar o extrato.</td></tr>';
    } finally {
      if (barra) barra.classList.remove('ativo');
    }
  }

  async function abrirDetalhe(id) {
    const modal = $('#bb-modal-detalhe');
    const corpo = $('#bb-detalhe-corpo');
    if (!modal || !corpo) return;
    corpo.innerHTML = '<p>Carregando…</p>';
    modal.hidden = false;
    modal.classList.add('aberto');
    try {
      const url = `/api/bb-extrato/${encodeURIComponent(id)}`;
      const resp = await fetch(window.withRoot ? window.withRoot(url) : url);
      if (!resp.ok) throw new Error('Lançamento não encontrado');
      const row = await resp.json();
      const bruto = row.bruto || {};
      const linhasPrincipais = [
        ['Data', row.data_exibicao],
        ['Data movimento', row.data_movimento_exibicao],
        ['Sinal', row.sinal_rotulo],
        ['Valor', row.valor_exibicao],
        ['Histórico', row.historico],
        ['Complemento', row.complemento || '—'],
        ['Documento', row.numero_documento],
        ['Lote', row.numero_lote],
        ['Cód. histórico', row.codigo_historico],
        ['Cód. subhistórico', row.codigo_subhistorico],
        ['ID transação', row.id_transacao || '—'],
        ['CPF/CNPJ contraparte', row.cpf_cnpj_contraparte || '—'],
        ['Banco / agência / conta contraparte', `${row.banco_contraparte} / ${row.agencia_contraparte} / ${row.conta_contraparte}`],
      ];
      corpo.innerHTML = `
        <dl class="bb-dl">
          ${linhasPrincipais
            .map(
              ([k, v]) =>
                `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v ?? '—'))}</dd></div>`
            )
            .join('')}
        </dl>
        <details class="bb-json">
          <summary>JSON bruto da API</summary>
          <pre>${escapeHtml(JSON.stringify(bruto, null, 2))}</pre>
        </details>
      `;
    } catch (err) {
      corpo.innerHTML = `<p>${escapeHtml(err.message)}</p>`;
    }
  }

  function initAbas() {
    document.querySelectorAll('.abas .aba').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.abas .aba').forEach((b) => b.classList.remove('ativa'));
        document.querySelectorAll('.painel-aba').forEach((p) => p.classList.remove('ativo'));
        btn.classList.add('ativa');
        const alvo = document.querySelector(`.painel-aba[data-painel="${btn.dataset.aba}"]`);
        alvo?.classList.add('ativo');
      });
    });
  }

  function init() {
    temaSync();
    $('#btn-tema')?.addEventListener('click', () => {
      const atual = document.documentElement.dataset.tema === 'escuro' ? 'claro' : 'escuro';
      document.documentElement.dataset.tema = atual;
      localStorage.setItem('fundeb-tema', atual);
      temaSync();
    });

    initAbas();

    $('#bb-aplicar')?.addEventListener('click', () => {
      estado.pagina = 1;
      carregar();
    });
    $('#bb-limpar')?.addEventListener('click', () => {
      ['bb-inicio', 'bb-fim', 'bb-sinal', 'bb-historico', 'bb-busca'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      const chk = $('#bb-saldos');
      if (chk) chk.checked = false;
      estado.pagina = 1;
      carregar();
    });
    $('#bb-busca')?.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        estado.pagina = 1;
        carregar();
      }
    });

    $('#bb-corpo')?.addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-detalhe]');
      if (btn) abrirDetalhe(btn.getAttribute('data-detalhe'));
    });
    $('#bb-fechar-detalhe')?.addEventListener('click', () => {
      const modal = $('#bb-modal-detalhe');
      if (modal) {
        modal.classList.remove('aberto');
        modal.hidden = true;
      }
    });
    $('#bb-modal-detalhe')?.addEventListener('click', (ev) => {
      if (ev.target.id === 'bb-modal-detalhe') {
        ev.currentTarget.classList.remove('aberto');
        ev.currentTarget.hidden = true;
      }
    });

    carregar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
