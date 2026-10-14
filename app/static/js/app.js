/* ==========================================================================
   Fluxo de Caixa FUNDEB — interação da interface
   ========================================================================== */

(() => {
  'use strict';

  const $ = (seletor) => document.querySelector(seletor);
  const $$ = (seletor) => Array.from(document.querySelectorAll(seletor));

  const estado = {
    filtros: { periodo: 'mes', inicio: null, fim: null, tipo: '', categoria: '', busca: '' },
    dados: null,
    tipoEditor: 'receita',
    linhas: { receita: [], despesa: [] },
    diaEditavel: false,
    diaAtual: window.CONFIG_FUNDEB.hoje,
    modoEvolucao: 'tudo',
    tipoPrevReal: 'despesa',
    ordenacao: { campo: 'data', crescente: false },
    arquivos: { receita: [], despesa: [] },
    usuario: window.CONFIG_FUNDEB.usuario || null,
    mesAtualEncerrado: false,
    mesAtual: null,
    previsaoMensal: null,
    ehAdmin: false,
    ajustesDia: [],
    ajusteExcluirId: null,
    historico: {
      pagina: 1,
      por_pagina: 25,
      total: 0,
      total_paginas: 1,
      datasSincronizadas: false,
    },
  };

  const fmtMoeda = (v) =>
    'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const fmtNumero = (v) =>
    Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const fmtData = (iso) => {
    if (!iso) return '';
    const [a, m, d] = String(iso).slice(0, 10).split('-');
    return `${d}/${m}/${a}`;
  };

  /** Converte texto no formato brasileiro para número. */
  function paraNumero(texto) {
    if (typeof texto === 'number') return texto;
    if (!texto) return 0;
    const limpo = String(texto).replace(/R\$/g, '').replace(/\s/g, '').replace(/\./g, '').replace(',', '.');
    const numero = parseFloat(limpo);
    return isNaN(numero) ? 0 : numero;
  }

  /* ==================== Notificações ==================== */

  const ICONES = {
    sucesso: '<polyline points="20 6 9 17 4 12"/>',
    erro: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    aviso: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  };

  function notificar(mensagem, tipo = 'info', duracao = 4200) {
    const caixa = document.createElement('div');
    caixa.className = `notificacao notificacao--${tipo}`;
    caixa.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${ICONES[tipo] || ICONES.info}</svg>
      <div>${mensagem}</div>`;

    $('#notificacoes').appendChild(caixa);
    setTimeout(() => {
      caixa.classList.add('saindo');
      setTimeout(() => caixa.remove(), 200);
    }, duracao);
  }

  let contadorCarregamento = 0;
  function carregando(ativo) {
    contadorCarregamento += ativo ? 1 : -1;
    contadorCarregamento = Math.max(0, contadorCarregamento);
    $('#barra-carregando').classList.toggle('ativo', contadorCarregamento > 0);
  }

  function withRoot(url) {
    if (typeof window.withRoot === 'function') return window.withRoot(url);
    return url;
  }

  async function requisitar(url, opcoes = {}) {
    carregando(true);
    try {
      const resposta = await fetch(withRoot(url), opcoes);
      const tipoConteudo = resposta.headers.get('content-type') || '';

      if (!resposta.ok) {
        let detalhe = `Erro ${resposta.status}`;
        if (tipoConteudo.includes('application/json')) {
          const corpo = await resposta.json().catch(() => null);
          if (corpo && corpo.erro) detalhe = corpo.erro;
        }
        throw new Error(detalhe);
      }

      return tipoConteudo.includes('application/json') ? resposta.json() : resposta;
    } finally {
      carregando(false);
    }
  }

  /* ==================== Sessão / edição ==================== */

  function atualizarBarraSessao() {
    const status = $('#sessao-status');
    const btnEditar = $('#btn-editar');
    const btnSair = $('#btn-sair');
    const linkUsuarios = $('#link-usuarios');
    const painelBackup = $('#painel-backup');

    if (estado.usuario) {
      AuthUI.preencherBotaoPerfil(status, estado.usuario);
      btnEditar.hidden = true;
      btnSair.hidden = false;
      if (linkUsuarios) linkUsuarios.hidden = !estado.usuario.eh_admin;
      if (painelBackup) painelBackup.hidden = !estado.usuario.eh_admin;
    } else {
      AuthUI.marcarVisualizando(status);
      btnEditar.hidden = false;
      btnSair.hidden = true;
      if (linkUsuarios) linkUsuarios.hidden = true;
      if (painelBackup) painelBackup.hidden = true;
    }
  }

  function aoAutenticar(usuario) {
    estado.usuario = usuario;
    atualizarBarraSessao();
    carregarDia(estado.diaAtual);
  }

  function aoAtualizarPerfil(usuario) {
    estado.usuario = usuario;
    if (window.CONFIG_FUNDEB) window.CONFIG_FUNDEB.usuario = usuario;
    atualizarBarraSessao();
  }

  AuthUI.ligarModalLogin({ onSuccess: aoAutenticar });
  AuthUI.ligarModalPerfil({
    getUsuario: () => estado.usuario,
    onSuccess: aoAtualizarPerfil,
  });
  atualizarBarraSessao();

  $('#btn-editar').addEventListener('click', () => {
    if (estado.usuario) return;
    AuthUI.abrirLogin();
  });

  $('#sessao-status')?.addEventListener('click', () => {
    if (estado.usuario) AuthUI.abrirPerfil(estado.usuario);
  });

  $('#btn-sair').addEventListener('click', async () => {
    await AuthUI.logout();
    estado.usuario = null;
    atualizarBarraSessao();
    notificar('Sessão encerrada. A tela voltou ao modo visualização.', 'info');
    carregarDia(estado.diaAtual);
  });

  /* ==================== Tema ==================== */

  function aplicarTema(tema) {
    document.documentElement.dataset.tema = tema;
    localStorage.setItem('fundeb-tema', tema);
    $('.icone-claro').style.display = tema === 'claro' ? '' : 'none';
    $('.icone-escuro').style.display = tema === 'escuro' ? '' : 'none';

    if (estado.dados) {
      Graficos.destruirTodos();
      requestAnimationFrame(() => desenharGraficos());
    }
  }

  $('#btn-tema').addEventListener('click', () => {
    aplicarTema(document.documentElement.dataset.tema === 'escuro' ? 'claro' : 'escuro');
  });
  aplicarTema(document.documentElement.dataset.tema || 'claro');

  /* ==================== Adaptação ao tamanho da tela ==================== */

  // Alguns gráficos mudam de arranjo no celular (legenda embaixo, eixos sem
  // rótulo). Só redimensionar não basta: eles precisam ser redesenhados quando
  // a largura cruza o limite, o que acontece ao girar o aparelho.
  window.matchMedia('(max-width: 760px)').addEventListener('change', () => {
    if (!estado.dados) return;
    Graficos.destruirTodos();
    requestAnimationFrame(() => desenharGraficos());
  });

  /* ==================== Abas ==================== */

  const ABAS_VALIDAS = new Set(['painel', 'lancamentos', 'movimentos', 'historico', 'importar']);
  const CHAVE_ABA = 'fundeb.abaAtiva';

  function ativarAba(nome, { persistir = true } = {}) {
    if (!ABAS_VALIDAS.has(nome)) nome = 'painel';
    if (!$(`#aba-${nome}`)) nome = 'painel';

    $$('.aba').forEach((a) => a.classList.toggle('ativa', a.dataset.aba === nome));
    $$('.painel-aba').forEach((p) => p.classList.toggle('ativo', p.id === `aba-${nome}`));

    if (persistir) {
      try {
        localStorage.setItem(CHAVE_ABA, nome);
      } catch (_) { /* ignore */ }
      const hash = nome === 'painel' ? '' : `#${nome}`;
      if (location.hash !== hash) {
        history.replaceState(null, '', `${location.pathname}${location.search}${hash}`);
      }
    }

    if (nome === 'painel') setTimeout(() => Graficos.redimensionar(), 60);
    if (nome === 'historico') carregarHistorico();
  }

  function abaSalva() {
    const doHash = (location.hash || '').replace(/^#/, '');
    if (ABAS_VALIDAS.has(doHash)) return doHash;
    try {
      const salva = localStorage.getItem(CHAVE_ABA);
      if (ABAS_VALIDAS.has(salva)) return salva;
    } catch (_) { /* ignore */ }
    return 'painel';
  }

  $$('.aba').forEach((aba) => {
    aba.addEventListener('click', () => ativarAba(aba.dataset.aba));
  });

  window.addEventListener('hashchange', () => {
    const doHash = (location.hash || '').replace(/^#/, '');
    if (ABAS_VALIDAS.has(doHash)) ativarAba(doHash);
    else if (!location.hash) ativarAba('painel');
  });

  /* ==================== Filtros ==================== */

  function parametrosFiltro() {
    const p = new URLSearchParams();
    p.set('periodo', estado.filtros.periodo);
    if (estado.filtros.periodo === 'personalizado') {
      p.set('inicio', $('#filtro-inicio').value);
      p.set('fim', $('#filtro-fim').value);
    }
    if (estado.filtros.tipo) p.set('tipo', estado.filtros.tipo);
    if (estado.filtros.categoria) p.set('categoria', estado.filtros.categoria);
    if (estado.filtros.busca) p.set('busca', estado.filtros.busca);
    return p;
  }

  $$('#chips-periodo .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      $$('#chips-periodo .chip').forEach((c) => c.classList.remove('ativo'));
      chip.classList.add('ativo');
      estado.filtros.periodo = chip.dataset.periodo;
      $('#periodo-personalizado').classList.toggle('visivel', chip.dataset.periodo === 'personalizado');
      carregarPainel();
    });
  });

  ['#filtro-inicio', '#filtro-fim'].forEach((seletor) => {
    $(seletor).addEventListener('change', () => {
      if (estado.filtros.periodo === 'personalizado') carregarPainel();
    });
  });

  $('#filtro-tipo').addEventListener('change', (e) => {
    estado.filtros.tipo = e.target.value;
    carregarPainel();
  });

  $('#filtro-categoria').addEventListener('change', (e) => {
    estado.filtros.categoria = e.target.value;
    carregarPainel();
  });

  let timerBusca;
  $('#filtro-busca').addEventListener('input', (e) => {
    clearTimeout(timerBusca);
    timerBusca = setTimeout(() => {
      estado.filtros.busca = e.target.value.trim();
      carregarPainel();
    }, 380);
  });

  $('#btn-limpar-filtros').addEventListener('click', () => {
    estado.filtros = { periodo: 'mes', inicio: null, fim: null, tipo: '', categoria: '', busca: '' };
    $('#filtro-tipo').value = '';
    $('#filtro-categoria').value = '';
    $('#filtro-busca').value = '';
    $$('#chips-periodo .chip').forEach((c) => c.classList.toggle('ativo', c.dataset.periodo === 'mes'));
    $('#periodo-personalizado').classList.remove('visivel');
    carregarPainel();
  });

  /* ==================== Painel ==================== */

  let sequenciaPainel = 0;
  let abortPainel = null;

  async function carregarPainel() {
    const sequencia = ++sequenciaPainel;
    if (abortPainel) abortPainel.abort();
    abortPainel = typeof AbortController !== 'undefined' ? new AbortController() : null;

    try {
      const dados = await requisitar('/api/painel?' + parametrosFiltro().toString(), {
        signal: abortPainel ? abortPainel.signal : undefined,
      });
      // Resposta atrasada de um filtro anterior — descarta.
      if (sequencia !== sequenciaPainel) return;
      estado.dados = dados;
      $('#rotulo-periodo').textContent = dados.periodo.rotulo;
      renderizarKpis(dados.indicadores);
      desenharGraficos();
      renderizarMovimentos();
      if ($('#aba-historico').classList.contains('ativo')) {
        estado.historico.datasSincronizadas = false;
        carregarHistorico({ resetarPagina: true });
      }
    } catch (erro) {
      if (erro && erro.name === 'AbortError') return;
      if (sequencia !== sequenciaPainel) return;
      notificar(`Não foi possível carregar os dados: ${erro.message}`, 'erro');
    }
  }

  const ICONE_KPI = {
    entrada: '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
    saida: '<polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/>',
    carteira: '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>',
    balanca: '<line x1="12" y1="3" x2="12" y2="21"/><path d="m3 7 9-4 9 4"/><path d="M3 7l3 7H0z"/><path d="M21 7l3 7h-6z"/>',
  };

  function cartaoKpi({ rotulo, valor, classe, icone, rodape, corValor }) {
    const estiloValor = corValor ? ` style="color:${corValor}"` : '';
    return `
      <div class="kpi ${classe}">
        <div class="kpi-topo">
          <span class="kpi-rotulo">${rotulo}</span>
          <span class="kpi-icone">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${icone}</svg>
          </span>
        </div>
        <div class="kpi-valor"${estiloValor}>${fmtMoeda(valor)}</div>
        ${rodape ? `<div class="kpi-rodape">${rodape}</div>` : ''}
      </div>`;
  }

  function renderizarKpis(ind) {
    const execucaoReceita = ind.receita_prevista
      ? `${((ind.receita_realizada / ind.receita_prevista) * 100).toFixed(0)}% da previsão`
      : 'sem previsão lançada';
    const execucaoDespesa = ind.despesa_prevista
      ? `${((ind.despesa_realizada / ind.despesa_prevista) * 100).toFixed(0)}% da previsão`
      : 'sem previsão lançada';

    $('#kpis').innerHTML = [
      cartaoKpi({
        rotulo: 'Saldo inicial',
        valor: ind.saldo_inicial,
        classe: 'kpi--saldo',
        icone: ICONE_KPI.carteira,
        rodape: 'acumulado até o dia anterior',
      }),
      cartaoKpi({
        rotulo: 'Receita realizada',
        valor: ind.receita_realizada,
        classe: 'kpi--receita',
        icone: ICONE_KPI.entrada,
        corValor: 'var(--verde)',
        rodape: execucaoReceita,
      }),
      cartaoKpi({
        rotulo: 'Despesa realizada',
        valor: ind.despesa_realizada,
        classe: 'kpi--despesa',
        icone: ICONE_KPI.saida,
        corValor: 'var(--vermelho)',
        rodape: execucaoDespesa,
      }),
      cartaoKpi({
        rotulo: 'Resultado do período',
        valor: ind.resultado,
        classe: 'kpi--roxo',
        icone: ICONE_KPI.balanca,
        corValor: ind.resultado >= 0 ? 'var(--verde)' : 'var(--vermelho)',
        rodape: `${ind.dias_com_movimento} dia(s) com movimento`,
      }),
      cartaoKpi({
        rotulo: 'Saldo final',
        valor: ind.saldo_final,
        classe: 'kpi--saldo',
        icone: ICONE_KPI.carteira,
        rodape: `${ind.lancamentos} lançamento(s) no período`,
      }),
    ].join('');

    if (ind.despesa_prevista > 0 && ind.despesa_realizada === 0 && !estado.avisouDespesa) {
      estado.avisouDespesa = true;
      notificar(
        'Há despesas previstas mas nenhuma realizada no período. O saldo considera apenas valores realizados.',
        'aviso',
        7000
      );
    }
  }

  function desenharGraficos() {
    const d = estado.dados;
    if (!d) return;
    Graficos.evolucao(d.evolucao, estado.modoEvolucao);
    Graficos.rosca('gr-receita-categoria', d.categorias.receita, 'receita');
    Graficos.rosca('gr-despesa-categoria', d.categorias.despesa, 'despesa');
    Graficos.previstoRealizado(d.previsto_realizado, estado.tipoPrevReal);
    Graficos.mensal(d.mensal);
    Graficos.calendario(d.calendario);
    Graficos.ranking('gr-ranking-entradas', d.ranking.entradas, 'entradas');
    Graficos.ranking('gr-ranking-saidas', d.ranking.saidas, 'saidas');
  }

  $$('#chips-evolucao .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      $$('#chips-evolucao .chip').forEach((c) => c.classList.remove('ativo'));
      chip.classList.add('ativo');
      estado.modoEvolucao = chip.dataset.serie;
      Graficos.evolucao(estado.dados.evolucao, estado.modoEvolucao);
    });
  });

  $$('#chips-prev-real .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      $$('#chips-prev-real .chip').forEach((c) => c.classList.remove('ativo'));
      chip.classList.add('ativo');
      estado.tipoPrevReal = chip.dataset.tipo;
      Graficos.previstoRealizado(estado.dados.previsto_realizado, estado.tipoPrevReal);
    });
  });

  $('#seletor-ano-calendario').addEventListener('change', async (e) => {
    try {
      const dados = await requisitar(`/api/calendario?ano=${e.target.value}`);
      Graficos.calendario(dados);
    } catch (erro) {
      notificar(`Erro ao carregar o calendário: ${erro.message}`, 'erro');
    }
  });

  /* ==================== Tabela de movimentos ==================== */

  function renderizarMovimentos() {
    const movimentos = (estado.dados && estado.dados.movimentos) || [];
    const corpo = $('#corpo-movimentos');

    const comValor = movimentos.filter((m) => m.prevista !== 0 || m.realizada !== 0);
    $('#contador-movimentos').textContent =
      `${comValor.length} lançamento(s) com valor · ${movimentos.length} linha(s) no total`;

    if (!comValor.length) {
      corpo.innerHTML = `<tr><td colspan="9">
        <div class="vazio">
          <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4">
            <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/>
          </svg>
          <strong>Nenhum lançamento com valor</strong>
          <p>Ajuste os filtros acima ou registre movimentos na aba Lançamentos.</p>
        </div></td></tr>`;
      return;
    }

    const { campo, crescente } = estado.ordenacao;
    const ordenados = [...comValor].sort((a, b) => {
      const x = a[campo];
      const y = b[campo];
      const comparacao = typeof x === 'number' ? x - y : String(x || '').localeCompare(String(y || ''), 'pt-BR');
      return crescente ? comparacao : -comparacao;
    });

    corpo.innerHTML = ordenados
      .map((m) => {
        const desvio = m.realizada - m.prevista;
        const classeDesvio = desvio > 0 ? 'positivo' : desvio < 0 ? 'negativo' : '';
        const credor =
          m.tipo === 'despesa'
            ? m.nome_credor || '<span style="color:var(--texto-3)">—</span>'
            : '<span style="color:var(--texto-3)">—</span>';
        const detalhe =
          m.tipo === 'despesa' && (m.op || m.nap || m.processo)
            ? `<div style="font-size:11px;color:var(--texto-3);margin-top:2px">OP ${escapar(m.op || '—')} · NAP ${escapar(m.nap || '—')} · Proc. ${escapar(m.processo || '—')}</div>`
            : '';
        return `<tr>
          <td class="num">${fmtData(m.data)}</td>
          <td class="col-tipo"><span class="etiqueta etiqueta--${m.tipo}">${m.tipo === 'receita' ? 'Receita' : 'Despesa'}</span></td>
          <td class="col-categoria">${m.categoria || m.ug || '<span style="color:var(--texto-3)">—</span>'}</td>
          <td>${credor}</td>
          <td>
            <button type="button" class="celula-entrada celula-entrada--descricao celula-entrada--botao"
                    data-acao="ver-descricao-mov"
                    data-texto="${encodeURIComponent(m.descricao || '')}"
                    title="Clique para ver a descrição completa">
              ${m.descricao ? escapar(m.descricao) : '—'}
            </button>
            ${detalhe}
          </td>
          <td class="alinhado-direita num col-secundaria">${m.prevista ? fmtNumero(m.prevista) : '—'}</td>
          <td class="alinhado-direita num">${m.realizada ? fmtNumero(m.realizada) : '—'}</td>
          <td class="alinhado-direita num col-secundaria ${classeDesvio}">${desvio ? fmtNumero(desvio) : '—'}</td>
          <td class="col-terciaria">
            ${m.ajuste_saldo
              ? '<span class="etiqueta etiqueta--alerta">ajuste</span>'
              : `<span class="etiqueta etiqueta--neutra">${escapar((m.source || '').split(':')[0] || 'manual')}</span>`}
          </td>
        </tr>`;
      })
      .join('');
  }

  $$('#tabela-movimentos th.ordenavel').forEach((th) => {
    th.addEventListener('click', () => {
      const campo = th.dataset.campo;
      estado.ordenacao = {
        campo,
        crescente: estado.ordenacao.campo === campo ? !estado.ordenacao.crescente : true,
      };
      $$('#tabela-movimentos th').forEach((h) => h.classList.remove('ordenado'));
      th.classList.add('ordenado');
      th.querySelector('.seta').textContent = estado.ordenacao.crescente ? '▴' : '▾';
      renderizarMovimentos();
    });
  });

  /* ==================== Editor de lançamentos ==================== */

  async function carregarDia(dia) {
    try {
      const dados = await requisitar(`/api/dia/${dia}`);
      estado.diaAtual = dia;
      estado.linhas.receita = dados.receitas;
      estado.linhas.despesa = dados.despesas;
      estado.diaEditavel = dados.editavel;
      estado.ajustesDia = dados.ajustes_saldo || [];
      estado.previsaoMensal = dados.previsao_mensal || null;
      estado.ehAdmin = !!dados.eh_admin;

      renderizarAvisoMes(dados);
      renderizarAvisoPrevisao(dados);
      renderizarAjustesDia(estado.ajustesDia);
      renderizarKpisDia(dados.totais);
      renderizarGrade();
    } catch (erro) {
      notificar(`Erro ao carregar o dia: ${erro.message}`, 'erro');
    }
  }

  function renderizarAvisoPrevisao(dados) {
    const caixa = $('#aviso-previsao');
    if (!caixa) return;
    const prev = dados.previsao_mensal || {};
    const rec = prev.receita;
    const desp = prev.despesa;
    if (!rec && !desp) {
      caixa.innerHTML = '';
      return;
    }
    const partes = [];
    if (rec) partes.push(`receita ${fmtMoeda(rec.valor)}`);
    if (desp) partes.push(`despesa ${fmtMoeda(desp.valor)}`);
    const trava = dados.eh_admin
      ? 'Você (admin) pode alterar pela opção Previsão mensal.'
      : 'A coluna Prevista está travada — somente o administrador altera a previsão mensal.';
    caixa.innerHTML = `
      <div class="aviso aviso--info">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 17V9"/><path d="M12 17V5"/><path d="M16 17v-6"/>
        </svg>
        <div class="aviso-conteudo">
          <strong>Previsão mensal de ${escapar(dados.mes)}</strong>
          Cada item recebe o valor integral em todos os dias: ${partes.join(' · ')}. ${trava}
        </div>
      </div>`;
  }

  function renderizarAvisoMes(dados) {
    const caixa = $('#aviso-mes');
    estado.mesAtualEncerrado = !!dados.mes_encerrado;
    estado.mesAtual = dados.mes;

    if (!estado.usuario) {
      caixa.innerHTML = `
        <div class="aviso aviso--bloqueado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>Modo visualização</strong>
            Você pode consultar os lançamentos. Clique em <em>Editar</em> no topo para autenticar e alterar.
          </div>
          <button class="btn btn-pequeno btn-primario" id="btn-aviso-editar">Editar</button>
        </div>`;
      $('#btn-aviso-editar').addEventListener('click', () => AuthUI.abrirLogin());
      return;
    }

    if (!dados.mes_encerrado) {
      caixa.innerHTML = `
        <div class="aviso aviso--liberado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>Edição liberada</strong>
            Mês corrente — alterações são salvas em nome de ${escapar(estado.usuario.nome)}.
          </div>
        </div>`;
      return;
    }

    if (dados.editavel) {
      caixa.innerHTML = `
        <div class="aviso aviso--liberado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>Mês histórico ${dados.mes} liberado</strong>
            A liberação vale apenas para esta sessão do navegador.
          </div>
          <button class="btn btn-pequeno" id="btn-bloquear-mes">Bloquear novamente</button>
        </div>`;

      $('#btn-bloquear-mes').addEventListener('click', async () => {
        const corpo = new FormData();
        corpo.append('mes', dados.mes);
        await requisitar('/api/meses/bloquear', { method: 'POST', body: corpo });
        notificar('Mês bloqueado novamente.', 'info');
        carregarDia(estado.diaAtual);
      });
    } else {
      caixa.innerHTML = `
        <div class="aviso aviso--bloqueado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>Mês ${dados.mes} histórico</strong>
            Dados encerrados. Confirme sua senha para liberar a edição nesta sessão.
          </div>
          <button class="btn btn-pequeno btn-primario" id="btn-liberar-mes">Liberar edição</button>
        </div>`;

      $('#btn-liberar-mes').addEventListener('click', () => abrirModalHistorico(dados.mes));
    }
  }

  function renderizarKpisDia(totais) {
    $('#kpis-dia').innerHTML = [
      cartaoKpi({
        rotulo: 'Saldo inicial do dia',
        valor: totais.saldo_inicial,
        classe: 'kpi--saldo',
        icone: ICONE_KPI.carteira,
        rodape: 'acumulado até a véspera',
      }),
      cartaoKpi({
        rotulo: 'Receita do dia',
        valor: totais.receita_realizada,
        classe: 'kpi--receita',
        icone: ICONE_KPI.entrada,
        corValor: 'var(--verde)',
        rodape: `previsto: ${fmtMoeda(totais.receita_prevista)}`,
      }),
      cartaoKpi({
        rotulo: 'Despesa do dia',
        valor: totais.despesa_realizada,
        classe: 'kpi--despesa',
        icone: ICONE_KPI.saida,
        corValor: 'var(--vermelho)',
        rodape: `previsto: ${fmtMoeda(totais.despesa_prevista)}`,
      }),
      cartaoKpi({
        rotulo: 'Saldo final do dia',
        valor: totais.saldo_final,
        classe: 'kpi--saldo',
        icone: ICONE_KPI.balanca,
        rodape: 'inicial + receita − despesa',
      }),
    ].join('');
  }

  function renderizarGrade() {
    const tipo = estado.tipoEditor;
    const linhas = estado.linhas[tipo];
    const categorias =
      tipo === 'receita' ? window.CONFIG_FUNDEB.categoriasReceita : window.CONFIG_FUNDEB.categoriasDespesa;
    const modoDespesa = tipo === 'despesa';

    $('#titulo-grade').textContent = modoDespesa ? 'Despesas do dia' : 'Receitas do dia';
    $('#btn-adicionar-linha').disabled = !estado.diaEditavel;
    $('#btn-salvar-dia').disabled = !estado.diaEditavel;

    if (modoDespesa) {
      $('#cabecalho-grade').innerHTML = `<tr>
        <th style="width:8%">OP</th>
        <th style="width:8%">NAP</th>
        <th style="width:10%">Processo</th>
        <th style="width:8%">UG</th>
        <th style="width:16%">Nome credor</th>
        <th style="width:22%">Histórico</th>
        <th style="width:12%" class="alinhado-direita">Prevista</th>
        <th style="width:12%" class="alinhado-direita">Vr pago</th>
        <th style="width:44px"></th>
      </tr>`;
      $('#rodape-grade').innerHTML = `<tr>
        <td colspan="6" id="rodape-label">Total do dia</td>
        <td class="alinhado-direita" id="total-prevista">R$ 0,00</td>
        <td class="alinhado-direita" id="total-realizada">R$ 0,00</td>
        <td></td>
      </tr>`;
    } else {
      $('#cabecalho-grade').innerHTML = `<tr>
        <th style="width:24%">Categoria</th>
        <th style="width:38%">Descrição</th>
        <th style="width:17%" class="alinhado-direita">Prevista</th>
        <th style="width:17%" class="alinhado-direita">Realizada</th>
        <th style="width:44px"></th>
      </tr>`;
      $('#rodape-grade').innerHTML = `<tr>
        <td colspan="2" id="rodape-label">Total do dia</td>
        <td class="alinhado-direita" id="total-prevista">R$ 0,00</td>
        <td class="alinhado-direita" id="total-realizada">R$ 0,00</td>
        <td></td>
      </tr>`;
    }

    $('#corpo-grade').innerHTML = linhas
      .map((linha, indice) => {
        const travadaPrevista = !!(linha.travada_prevista && !estado.ehAdmin);
        const bloqueioGeral = estado.diaEditavel ? '' : 'disabled';
        const bloqueioPrevista = !estado.diaEditavel || travadaPrevista ? 'disabled' : '';
        const classeLinha = travadaPrevista ? ' class="linha-travada"' : '';
        const tituloTravada = travadaPrevista
          ? 'title="Prevista definida pela previsão mensal — somente administrador altera"'
          : '';

        if (modoDespesa) {
          return `<tr data-indice="${indice}"${classeLinha} ${tituloTravada}>
            <td><input class="celula-entrada" data-campo="op" value="${escapar(linha.op || '')}" ${bloqueioGeral}></td>
            <td><input class="celula-entrada" data-campo="nap" value="${escapar(linha.nap || '')}" ${bloqueioGeral}></td>
            <td><input class="celula-entrada" data-campo="processo" value="${escapar(linha.processo || '')}" ${bloqueioGeral}></td>
            <td><input class="celula-entrada" data-campo="ug" value="${escapar(linha.ug || linha.categoria || '')}" ${bloqueioGeral}></td>
            <td><input class="celula-entrada" data-campo="nome_credor" value="${escapar(linha.nome_credor || '')}" ${bloqueioGeral}></td>
            <td>
              <input class="celula-entrada celula-entrada--descricao" data-campo="descricao" data-acao="ver-descricao"
                     value="${escapar(linha.descricao || '')}" readonly
                     title="Clique para ver o histórico completo"
                     placeholder="Histórico">
            </td>
            <td>
              <input class="celula-entrada numero" data-campo="prevista" inputmode="decimal"
                     value="${linha.prevista ? fmtNumero(linha.prevista) : ''}" placeholder="0,00" ${bloqueioPrevista}>
            </td>
            <td>
              <input class="celula-entrada numero" data-campo="realizada" inputmode="decimal"
                     value="${linha.realizada ? fmtNumero(linha.realizada) : ''}" placeholder="0,00" ${bloqueioGeral}>
            </td>
            <td class="acoes-linha">
              <button class="btn-remover" data-acao="remover" title="Remover linha" ${bloqueioGeral}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </td>
          </tr>`;
        }

        const opcoes = categorias
          .map((c) => `<option value="${c}" ${c === linha.categoria ? 'selected' : ''}>${c}</option>`)
          .join('');
        const extra = categorias.includes(linha.categoria)
          ? ''
          : `<option value="${linha.categoria}" selected>${linha.categoria || '—'}</option>`;

        return `<tr data-indice="${indice}"${classeLinha} ${tituloTravada}>
          <td>
            <select class="celula-entrada" data-campo="categoria" ${bloqueioGeral}>${extra}${opcoes}</select>
          </td>
          <td>
            <input class="celula-entrada celula-entrada--descricao" data-campo="descricao" data-acao="ver-descricao"
                   value="${escapar(linha.descricao || '')}" readonly
                   title="Clique para ver a descrição completa"
                   placeholder="Descrição">
          </td>
          <td>
            <input class="celula-entrada numero" data-campo="prevista" inputmode="decimal"
                   value="${linha.prevista ? fmtNumero(linha.prevista) : ''}" placeholder="0,00" ${bloqueioPrevista}>
          </td>
          <td>
            <input class="celula-entrada numero" data-campo="realizada" inputmode="decimal"
                   value="${linha.realizada ? fmtNumero(linha.realizada) : ''}" placeholder="0,00" ${bloqueioGeral}>
          </td>
          <td class="acoes-linha">
            <button class="btn-remover" data-acao="remover" title="Remover linha" ${bloqueioGeral}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </td>
        </tr>`;
      })
      .join('');

    atualizarTotaisGrade();
  }

  function escapar(texto) {
    return String(texto || '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
  }

  function atualizarTotaisGrade() {
    const linhas = estado.linhas[estado.tipoEditor];
    const prevista = linhas.reduce((s, l) => s + Number(l.prevista || 0), 0);
    const realizada = linhas.reduce((s, l) => s + Number(l.realizada || 0), 0);
    $('#total-prevista').textContent = fmtMoeda(prevista);
    $('#total-realizada').textContent = fmtMoeda(realizada);
  }

  // Delegação: a grade é reconstruída a cada troca de dia ou aba.
  $('#corpo-grade').addEventListener('input', (evento) => {
    const alvo = evento.target;
    const campo = alvo.dataset.campo;
    if (!campo) return;

    const indice = Number(alvo.closest('tr').dataset.indice);
    const linha = estado.linhas[estado.tipoEditor][indice];
    if (!linha) return;

    if (campo === 'prevista' || campo === 'realizada') {
      linha[campo] = paraNumero(alvo.value);
      alvo.classList.add('alterada');
      atualizarTotaisGrade();
    } else if (campo === 'ug') {
      linha.ug = alvo.value;
      linha.categoria = alvo.value || 'DESPESA';
    } else {
      linha[campo] = alvo.value;
    }
  });

  $('#corpo-grade').addEventListener('change', (evento) => {
    if (evento.target.dataset.campo !== 'categoria') return;
    const indice = Number(evento.target.closest('tr').dataset.indice);
    estado.linhas[estado.tipoEditor][indice].categoria = evento.target.value;
  });

  // Reformata o valor quando o campo perde o foco.
  $('#corpo-grade').addEventListener(
    'blur',
    (evento) => {
      const alvo = evento.target;
      if (!alvo.classList || !alvo.classList.contains('numero')) return;
      const valor = paraNumero(alvo.value);
      alvo.value = valor ? fmtNumero(valor) : '';
    },
    true
  );

  $('#corpo-grade').addEventListener('click', (evento) => {
    const verDesc = evento.target.closest('[data-acao="ver-descricao"]');
    if (verDesc) {
      const indice = Number(verDesc.closest('tr').dataset.indice);
      abrirModalDescricaoGrade(indice);
      return;
    }
    const botao = evento.target.closest('[data-acao="remover"]');
    if (!botao) return;
    const indice = Number(botao.closest('tr').dataset.indice);
    estado.linhas[estado.tipoEditor].splice(indice, 1);
    renderizarGrade();
  });

  $('#corpo-movimentos')?.addEventListener('click', (evento) => {
    const botao = evento.target.closest('[data-acao="ver-descricao-mov"]');
    if (!botao) return;
    let texto = '';
    try {
      texto = decodeURIComponent(botao.dataset.texto || '');
    } catch (_) {
      texto = botao.dataset.texto || '';
    }
    abrirModalDescricaoTexto(texto, {
      titulo: 'Descrição / histórico completo',
      editavel: false,
    });
  });

  /* ==================== Modal descrição / histórico completo ==================== */

  let descricaoModal = { origem: null, indice: null, editavel: false };

  function abrirModalDescricaoTexto(texto, { titulo, editavel, ajuda, origem = null, indice = null } = {}) {
    descricaoModal = { origem, indice, editavel: !!editavel };
    $('#modal-descricao-titulo').textContent = titulo || 'Descrição completa';
    $('#modal-descricao-ajuda').textContent =
      ajuda ||
      (editavel
        ? 'Edite o texto completo abaixo e clique em Aplicar para gravar na linha.'
        : 'Texto completo do lançamento para conferência.');
    const campo = $('#modal-descricao-texto');
    campo.value = texto || '';
    campo.readOnly = !editavel;
    campo.classList.toggle('entrada--somente-leitura', !editavel);
    $('#btn-aplicar-descricao').hidden = !editavel;
    $('#modal-descricao-completa').classList.add('aberto');
    setTimeout(() => campo.focus(), 40);
  }

  function abrirModalDescricaoGrade(indice) {
    const linha = estado.linhas[estado.tipoEditor]?.[indice];
    if (!linha) return;
    const modoDespesa = estado.tipoEditor === 'despesa';
    const editavel = !!estado.diaEditavel;
    abrirModalDescricaoTexto(linha.descricao || '', {
      titulo: modoDespesa ? 'Histórico completo' : 'Descrição completa',
      editavel,
      origem: 'grade',
      indice,
      ajuda: editavel
        ? 'Edite o texto completo e clique em Aplicar para atualizar a linha (lembre de Salvar o dia).'
        : 'Texto completo para conferência. Entre no modo edição para alterar.',
    });
  }

  function fecharModalDescricao() {
    $('#modal-descricao-completa').classList.remove('aberto');
    descricaoModal = { origem: null, indice: null, editavel: false };
  }

  function aplicarModalDescricao() {
    if (!descricaoModal.editavel || descricaoModal.origem !== 'grade') {
      fecharModalDescricao();
      return;
    }
    const linha = estado.linhas[estado.tipoEditor]?.[descricaoModal.indice];
    if (!linha) {
      fecharModalDescricao();
      return;
    }
    linha.descricao = $('#modal-descricao-texto').value;
    fecharModalDescricao();
    renderizarGrade();
  }

  $('#btn-fechar-descricao')?.addEventListener('click', fecharModalDescricao);
  $('#btn-aplicar-descricao')?.addEventListener('click', aplicarModalDescricao);
  $('#modal-descricao-completa')?.addEventListener('click', (e) => {
    if (e.target.id === 'modal-descricao-completa') fecharModalDescricao();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if ($('#modal-descricao-completa')?.classList.contains('aberto')) {
      fecharModalDescricao();
    }
  });

  // Enter desce para a mesma coluna na linha seguinte, como numa planilha.
  $('#corpo-grade').addEventListener('keydown', (evento) => {
    if (evento.key !== 'Enter') return;
    evento.preventDefault();
    const celula = evento.target;
    const linha = celula.closest('tr');
    const proxima = linha.nextElementSibling;
    if (!proxima) return;
    const alvo = proxima.querySelector(`[data-campo="${celula.dataset.campo}"]`);
    if (alvo) {
      alvo.focus();
      if (alvo.select) alvo.select();
    }
  });

  $$('.editor-aba').forEach((aba) => {
    aba.addEventListener('click', () => {
      $$('.editor-aba').forEach((a) => a.classList.remove('ativa'));
      aba.classList.add('ativa');
      estado.tipoEditor = aba.dataset.tipo;
      renderizarGrade();
    });
  });

  $('#dia-edicao').addEventListener('change', (e) => carregarDia(e.target.value));

  $('#btn-adicionar-linha').addEventListener('click', () => {
    if (estado.tipoEditor === 'despesa') {
      estado.linhas.despesa.push({
        categoria: 'DESPESA',
        descricao: '',
        prevista: 0,
        realizada: 0,
        op: '',
        nap: '',
        processo: '',
        ug: '',
        nome_credor: '',
      });
    } else {
      const categorias = window.CONFIG_FUNDEB.categoriasReceita;
      estado.linhas.receita.push({
        categoria: categorias[categorias.length - 1],
        descricao: '',
        prevista: 0,
        realizada: 0,
      });
    }

    renderizarGrade();
    const linhas = $$('#corpo-grade tr');
    const ultima = linhas[linhas.length - 1];
    if (ultima) {
      const foco =
        estado.tipoEditor === 'despesa'
          ? ultima.querySelector('[data-campo="nome_credor"]')
          : ultima.querySelector('[data-campo="descricao"]');
      if (foco) foco.focus();
    }
  });

  $('#btn-salvar-dia').addEventListener('click', async () => {
    if (!estado.diaEditavel) {
      if (!estado.usuario) {
        AuthUI.abrirLogin();
        return;
      }
      if (estado.mesAtualEncerrado) {
        abrirModalHistorico(estado.mesAtual);
        return;
      }
      notificar('Este dia não está liberado para edição.', 'aviso');
      return;
    }

    try {
      const resposta = await requisitar(`/api/dia/${estado.diaAtual}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          receitas: estado.linhas.receita,
          despesas: estado.linhas.despesa,
        }),
      });

      notificar(`Lançamentos de ${fmtData(estado.diaAtual)} salvos com sucesso.`, 'sucesso');
      renderizarKpisDia(resposta.totais);
      $$('.celula-entrada.alterada').forEach((c) => c.classList.remove('alterada'));
      carregarPainel();
    } catch (erro) {
      notificar(`Não foi possível salvar: ${erro.message}`, 'erro');
    }
  });

  // Ctrl+S salva o dia quando a aba de lançamentos está aberta.
  document.addEventListener('keydown', (evento) => {
    if ((evento.ctrlKey || evento.metaKey) && evento.key === 's') {
      if ($('#aba-lancamentos').classList.contains('ativo')) {
        evento.preventDefault();
        $('#btn-salvar-dia').click();
      }
    }
  });

  /* ==================== Modal de mês histórico ==================== */

  let mesParaLiberar = null;

  function abrirModalHistorico(mes) {
    if (!estado.usuario) {
      AuthUI.abrirLogin();
      return;
    }
    mesParaLiberar = mes;
    $('#modal-mes').textContent = mes;
    $('#modal-senha-input').value = '';
    $('#modal-historico').classList.add('aberto');
    setTimeout(() => $('#modal-senha-input').focus(), 60);
  }

  function fecharModalHistorico() {
    $('#modal-historico').classList.remove('aberto');
    mesParaLiberar = null;
  }

  $('#btn-cancelar-senha').addEventListener('click', fecharModalHistorico);

  $('#modal-historico').addEventListener('click', (e) => {
    if (e.target.id === 'modal-historico') fecharModalHistorico();
  });

  $('#modal-senha-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('#btn-confirmar-senha').click();
    if (e.key === 'Escape') fecharModalHistorico();
  });

  $('#btn-confirmar-senha').addEventListener('click', async () => {
    const corpo = new FormData();
    corpo.append('mes', mesParaLiberar);
    corpo.append('senha', $('#modal-senha-input').value);

    try {
      await requisitar('/api/meses/liberar', { method: 'POST', body: corpo });
      notificar(`Mês ${mesParaLiberar} liberado para edição nesta sessão.`, 'sucesso');
      fecharModalHistorico();
      carregarDia(estado.diaAtual);
    } catch (erro) {
      notificar(erro.message, 'erro');
      $('#modal-senha-input').select();
    }
  });

  /* ==================== Importação ==================== */

  function extensaoArquivo(nome) {
    const partes = String(nome || '').toLowerCase().split('.');
    return partes.length > 1 ? partes.pop() : '';
  }

  function ligarZonaImportacao({ tipo, zonaId, inputId, listaId, btnLimparId, btnProcessarId, resultadoId, extensoes, rotulo }) {
    const zona = $(zonaId);
    const entrada = $(inputId);
    if (!zona || !entrada) return;

    const aceitas = new Set(extensoes);

    function renderizarLista() {
      const lista = estado.arquivos[tipo];
      const tem = lista.length > 0;
      $(btnProcessarId).disabled = !tem;
      $(btnLimparId).disabled = !tem;

      $(listaId).innerHTML = lista
        .map(
          (arquivo, indice) => `
          <div class="arquivo-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
            </svg>
            <span class="nome">${escapar(arquivo.name)}</span>
            <span style="color:var(--texto-3);font-size:12px">${(arquivo.size / 1024).toFixed(0)} KB</span>
            <button class="btn-remover" data-indice="${indice}" type="button">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>`
        )
        .join('');

      $$(`${listaId} .btn-remover`).forEach((botao) =>
        botao.addEventListener('click', () => {
          estado.arquivos[tipo].splice(Number(botao.dataset.indice), 1);
          renderizarLista();
        })
      );
    }

    function adicionarArquivos(lista) {
      const validos = [];
      const rejeitados = [];
      Array.from(lista || []).forEach((arquivo) => {
        const ext = extensaoArquivo(arquivo.name);
        if (aceitas.has(ext)) validos.push(arquivo);
        else rejeitados.push(arquivo.name);
      });

      if (rejeitados.length) {
        notificar(
          `${rotulo}: arquivo(s) ignorado(s) — use apenas ${extensoes.map((e) => '.' + e).join(', ')}.`,
          'aviso'
        );
      }
      if (!validos.length) return;

      estado.arquivos[tipo] = [...estado.arquivos[tipo], ...validos];
      renderizarLista();
    }

    zona.addEventListener('click', () => entrada.click());
    ['dragenter', 'dragover'].forEach((evento) =>
      zona.addEventListener(evento, (e) => {
        e.preventDefault();
        zona.classList.add('arrastando');
      })
    );
    ['dragleave', 'drop'].forEach((evento) =>
      zona.addEventListener(evento, (e) => {
        e.preventDefault();
        zona.classList.remove('arrastando');
      })
    );
    zona.addEventListener('drop', (e) => adicionarArquivos(e.dataTransfer.files));
    entrada.addEventListener('change', (e) => {
      adicionarArquivos(e.target.files);
      entrada.value = '';
    });

    $(btnLimparId).addEventListener('click', () => {
      estado.arquivos[tipo] = [];
      $(resultadoId).innerHTML = '';
      renderizarLista();
    });

    $(btnProcessarId).addEventListener('click', async () => {
      if (!estado.usuario) {
        notificar('Faça login para importar arquivos.', 'aviso');
        AuthUI.abrirLogin();
        return;
      }
      if (!estado.arquivos[tipo].length) return;

      const corpo = new FormData();
      estado.arquivos[tipo].forEach((arquivo) => corpo.append('arquivos', arquivo));

      try {
        const resultado = await requisitar('/api/importar', { method: 'POST', body: corpo });
        renderizarResultadoImportacao(resultado, resultadoId);

        const totalDias = (resultado.dias || []).length;
        if (totalDias) {
          notificar(`${rotulo}: ${totalDias} dia(s) atualizado(s).`, 'sucesso');
          carregarPainel();
          carregarDia(estado.diaAtual);
        } else {
          notificar(`${rotulo}: nenhum dado novo foi gravado. Veja o detalhe abaixo.`, 'aviso');
        }

        estado.arquivos[tipo] = [];
        renderizarLista();
      } catch (erro) {
        notificar(`Falha na importação de ${rotulo.toLowerCase()}: ${erro.message}`, 'erro');
      }
    });

    renderizarLista();
  }

  ligarZonaImportacao({
    tipo: 'receita',
    zonaId: '#zona-upload-receita',
    inputId: '#entrada-receita',
    listaId: '#lista-arquivos-receita',
    btnLimparId: '#btn-limpar-receita',
    btnProcessarId: '#btn-processar-receita',
    resultadoId: '#resultado-importacao-receita',
    extensoes: ['pdf'],
    rotulo: 'Receita',
  });

  ligarZonaImportacao({
    tipo: 'despesa',
    zonaId: '#zona-upload-despesa',
    inputId: '#entrada-despesa',
    listaId: '#lista-arquivos-despesa',
    btnLimparId: '#btn-limpar-despesa',
    btnProcessarId: '#btn-processar-despesa',
    resultadoId: '#resultado-importacao-despesa',
    extensoes: ['csv'],
    rotulo: 'Despesa',
  });

  function renderizarResultadoImportacao(resultado, seletor) {
    const host = $(seletor);
    if (!host) return;
    const partes = [];

    if (resultado.processados.length) {
      partes.push(`
        <div class="aviso aviso--liberado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>${resultado.processados.length} arquivo(s) processado(s)</strong>
            ${resultado.processados
              .map((p) => `${escapar(p.arquivo)} — ${p.tipo || ''} · ${p.dias_gravados} dia(s)`)
              .join('<br>')}
          </div>
        </div>`);
    }

    if (resultado.dias.length) {
      partes.push(`
        <div class="aviso aviso--info">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>Dias atualizados</strong>
            ${resultado.dias.length <= 12
              ? resultado.dias.map(fmtData).join(', ')
              : `${fmtData(resultado.dias[0])} a ${fmtData(resultado.dias[resultado.dias.length - 1])} (${resultado.dias.length} dias)`}
          </div>
        </div>`);
    }

    if (resultado.ignorados.length) {
      partes.push(`
        <div class="aviso aviso--bloqueado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>${resultado.ignorados.length} dia(s) ignorado(s)</strong>
            Pertencem a meses encerrados. Libere o mês na aba Lançamentos e importe novamente.
          </div>
        </div>`);
    }

    if (resultado.erros && resultado.erros.length) {
      partes.push(`
        <div class="aviso aviso--bloqueado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>${resultado.erros.length} erro(s)</strong>
            ${resultado.erros.map((e) => `${escapar(e.arquivo)}: ${escapar(e.motivo)}`).join('<br>')}
          </div>
        </div>`);
    }

    host.innerHTML = partes.join('');
  }

  /* ==================== Backup / restauração ==================== */

  $('#btn-baixar-backup')?.addEventListener('click', async () => {
    if (!(estado.usuario && estado.usuario.eh_admin)) {
      notificar('Somente o administrador pode baixar o banco.', 'erro');
      return;
    }
    try {
      const resposta = await fetch(withRoot('/api/backup/baixar'), { method: 'GET' });
      if (!resposta.ok) {
        let detalhe = `Erro ${resposta.status}`;
        const tipo = resposta.headers.get('content-type') || '';
        if (tipo.includes('application/json')) {
          const corpo = await resposta.json().catch(() => null);
          if (corpo && corpo.erro) detalhe = corpo.erro;
        }
        throw new Error(detalhe);
      }
      const blob = await resposta.blob();
      const disposicao = resposta.headers.get('content-disposition') || '';
      const match = /filename="?([^"]+)"?/i.exec(disposicao);
      const nome = match ? match[1] : `fluxo_backup_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.db`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = nome;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      notificar('Backup baixado. Guarde o arquivo .db em local seguro.', 'sucesso');
    } catch (erro) {
      notificar(erro.message, 'erro');
    }
  });

  $('#btn-restaurar-backup')?.addEventListener('click', async () => {
    if (!(estado.usuario && estado.usuario.eh_admin)) {
      notificar('Somente o administrador pode restaurar o banco.', 'erro');
      return;
    }
    const arquivo = $('#backup-arquivo')?.files?.[0];
    const senha = $('#backup-senha')?.value || '';
    if (!arquivo) {
      notificar('Selecione o arquivo .db de backup.', 'aviso');
      return;
    }
    if (!senha) {
      notificar('Informe a senha de administrador para restaurar.', 'aviso');
      $('#backup-senha')?.focus();
      return;
    }
    if (
      !confirm(
        'A restauração substitui TODOS os dados atuais pelo conteúdo do backup.\n\nDeseja continuar?'
      )
    ) {
      return;
    }

    const corpo = new FormData();
    corpo.append('arquivo', arquivo);
    corpo.append('senha', senha);

    try {
      const dados = await requisitar('/api/backup/restaurar', { method: 'POST', body: corpo });
      $('#resultado-backup').innerHTML = `
        <div class="aviso aviso--liberado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>Banco restaurado</strong>
            ${dados.movimentos} movimento(s) · ${dados.usuarios} usuário(s).
            ${dados.backup_anterior ? `Cópia anterior salva como ${escapar(dados.backup_anterior)}.` : ''}
            Faça login novamente.
          </div>
        </div>`;
      notificar('Restauração concluída. Entre novamente.', 'sucesso');
      estado.usuario = null;
      atualizarBarraSessao();
      $('#backup-arquivo').value = '';
      $('#backup-senha').value = '';
      AuthUI.abrirLogin();
      carregarPainel();
      carregarDia(estado.diaAtual);
    } catch (erro) {
      notificar(erro.message, 'erro');
      $('#backup-senha')?.select();
    }
  });

  $('#btn-zerar-banco')?.addEventListener('click', async () => {
    if (!(estado.usuario && estado.usuario.eh_admin)) {
      notificar('Somente o administrador pode zerar o banco.', 'erro');
      return;
    }
    const confirmacao = ($('#zerar-confirmacao')?.value || '').trim();
    const senha = $('#zerar-senha')?.value || '';
    if (confirmacao.toUpperCase() !== 'ZERAR') {
      notificar('Digite ZERAR no campo de confirmação.', 'aviso');
      $('#zerar-confirmacao')?.focus();
      return;
    }
    if (!senha) {
      notificar('Informe a senha de administrador para zerar.', 'aviso');
      $('#zerar-senha')?.focus();
      return;
    }
    if (
      !confirm(
        'Isso apaga TODOS os movimentos, previsões e o histórico.\nOs usuários serão mantidos.\n\nDeseja continuar?'
      )
    ) {
      return;
    }

    const corpo = new FormData();
    corpo.append('senha', senha);
    corpo.append('confirmacao', confirmacao);

    try {
      const dados = await requisitar('/api/backup/zerar', { method: 'POST', body: corpo });
      $('#resultado-backup').innerHTML = `
        <div class="aviso aviso--liberado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>Banco zerado</strong>
            ${dados.movimentos_apagados} movimento(s),
            ${dados.previsoes_apagadas} previsão(ões) e
            ${dados.historico_apagado} registro(s) de histórico removidos.
            ${dados.backup_anterior ? `Cópia automática: ${escapar(dados.backup_anterior)}.` : ''}
            Usuários preservados — pode importar os PDFs/CSVs de novo.
          </div>
        </div>`;
      notificar('Dados apagados. Sistema pronto para recomeçar.', 'sucesso');
      $('#zerar-confirmacao').value = '';
      $('#zerar-senha').value = '';
      carregarPainel();
      carregarDia(estado.diaAtual);
    } catch (erro) {
      notificar(erro.message, 'erro');
      $('#zerar-senha')?.select();
    }
  });

  /* ==================== Ajuste de saldo ==================== */

  function renderizarAjustesDia(lista) {
    const caixa = $('#lista-ajustes-dia');
    if (!caixa) return;
    if (!lista || !lista.length) {
      caixa.innerHTML = '';
      return;
    }

    const podeExcluir = !!(estado.usuario && estado.usuario.eh_admin);
    caixa.innerHTML = `
      <div class="aviso aviso--info">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <div class="aviso-conteudo" style="width:100%">
          <strong>Ajustes de saldo neste dia (imutáveis)</strong>
          <div class="ajustes-lista">
            ${lista
              .map((a) => {
                const efeito = Number(a.efeito || 0);
                const sinal = efeito >= 0 ? 'positivo' : 'negativo';
                return `<div class="ajuste-item">
                  <div>
                    <div class="ajuste-valor ${sinal}">${fmtMoeda(efeito)}</div>
                    <div class="ajuste-motivo">${escapar(a.descricao)}</div>
                  </div>
                  ${podeExcluir
                    ? `<button class="btn btn-pequeno" data-excluir-ajuste="${a.id}">Excluir</button>`
                    : '<span class="etiqueta etiqueta--neutra">bloqueado</span>'}
                </div>`;
              })
              .join('')}
          </div>
        </div>
      </div>`;
  }

  function abrirModalAjuste() {
    if (!estado.usuario) {
      AuthUI.abrirLogin();
      return;
    }
    $('#ajuste-data').value = estado.diaAtual || window.CONFIG_FUNDEB.hoje;
    $('#ajuste-valor').value = '';
    $('#ajuste-motivo').value = '';
    $('#ajuste-senha').value = '';
    $('#modal-ajuste-saldo').classList.add('aberto');
    setTimeout(() => $('#ajuste-valor').focus(), 60);
  }

  function fecharModalAjuste() {
    $('#modal-ajuste-saldo').classList.remove('aberto');
  }

  $('#btn-ajuste-saldo').addEventListener('click', abrirModalAjuste);
  $('#btn-cancelar-ajuste').addEventListener('click', fecharModalAjuste);
  $('#modal-ajuste-saldo').addEventListener('click', (e) => {
    if (e.target.id === 'modal-ajuste-saldo') fecharModalAjuste();
  });

  /* ==================== Previsão mensal ==================== */

  function mesDoDia(diaIso) {
    return String(diaIso || '').slice(0, 7);
  }

  async function abrirModalPrevisao() {
    if (!estado.usuario) {
      AuthUI.abrirLogin();
      return;
    }
    const mes = mesDoDia(estado.diaAtual || window.CONFIG_FUNDEB.hoje);
    $('#prev-mes').value = mes;
    await carregarFormularioPrevisao(mes);
    $('#modal-previsao-mensal').classList.add('aberto');
    setTimeout(() => $('#prev-receita').focus(), 60);
  }

  function fecharModalPrevisao() {
    $('#modal-previsao-mensal').classList.remove('aberto');
  }

  async function carregarFormularioPrevisao(anoMes) {
    const dados = await requisitar(`/api/previsao-mensal?ano_mes=${encodeURIComponent(anoMes)}`);
    const rec = dados.receita;
    const desp = dados.despesa;
    $('#prev-receita').value = rec ? fmtNumero(rec.valor) : '';
    $('#prev-despesa').value = desp ? fmtNumero(desp.valor) : '';
    $('#prev-receita').disabled = !dados.pode_alterar_receita;
    $('#prev-despesa').disabled = !dados.pode_alterar_despesa;
    $('#prev-dica-admin').hidden = !dados.eh_admin;

    const status = $('#prev-status');
    const bits = [];
    if (rec) bits.push(`Receita: ${fmtMoeda(rec.valor)} em cada item, todos os dias`);
    if (desp) bits.push(`Despesa: ${fmtMoeda(desp.valor)} em cada item, todos os dias`);
    if (bits.length) {
      status.hidden = false;
      status.innerHTML = bits.map((t) => `<div>${t}</div>`).join('');
    } else {
      status.hidden = true;
      status.innerHTML = '';
    }

    const podeSalvar = dados.pode_alterar_receita || dados.pode_alterar_despesa;
    $('#btn-salvar-previsao').disabled = !podeSalvar;
    return dados;
  }

  $('#btn-previsao-mensal')?.addEventListener('click', () => {
    abrirModalPrevisao().catch((erro) => notificar(erro.message, 'erro'));
  });
  $('#btn-cancelar-previsao')?.addEventListener('click', fecharModalPrevisao);
  $('#modal-previsao-mensal')?.addEventListener('click', (e) => {
    if (e.target.id === 'modal-previsao-mensal') fecharModalPrevisao();
  });
  $('#prev-mes')?.addEventListener('change', () => {
    carregarFormularioPrevisao($('#prev-mes').value).catch((erro) => notificar(erro.message, 'erro'));
  });

  $('#btn-salvar-previsao')?.addEventListener('click', async () => {
    try {
      const meta = await requisitar(
        `/api/previsao-mensal?ano_mes=${encodeURIComponent($('#prev-mes').value)}`
      );
      const corpo = { ano_mes: $('#prev-mes').value };
      if (meta.pode_alterar_receita) corpo.receita = $('#prev-receita').value.trim() || '0';
      if (meta.pode_alterar_despesa) corpo.despesa = $('#prev-despesa').value.trim() || '0';

      if (!('receita' in corpo) && !('despesa' in corpo)) {
        notificar('Nada para alterar neste mês.', 'info');
        return;
      }

      await requisitar('/api/previsao-mensal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
      });
      fecharModalPrevisao();
      notificar('Previsão mensal aplicada em todos os dias do mês.', 'sucesso');
      await carregarDia(estado.diaAtual);
      if (estado.dados) carregarPainel();
    } catch (erro) {
      notificar(erro.message, 'erro');
    }
  });

  $('#btn-confirmar-ajuste').addEventListener('click', async () => {
    const corpo = new FormData();
    corpo.append('data', $('#ajuste-data').value);
    corpo.append('valor', $('#ajuste-valor').value);
    corpo.append('motivo', $('#ajuste-motivo').value.trim());
    corpo.append('senha', $('#ajuste-senha').value);

    try {
      await requisitar('/api/ajustes-saldo', { method: 'POST', body: corpo });
      notificar('Ajuste registrado: o valor passou a ser a nova base do saldo.', 'sucesso');
      fecharModalAjuste();
      carregarDia($('#ajuste-data').value || estado.diaAtual);
      carregarPainel();
    } catch (erro) {
      notificar(erro.message, 'erro');
      $('#ajuste-senha').select();
    }
  });

  $('#lista-ajustes-dia').addEventListener('click', (e) => {
    const botao = e.target.closest('[data-excluir-ajuste]');
    if (!botao) return;
    if (!(estado.usuario && estado.usuario.eh_admin)) {
      notificar('Somente o administrador master pode excluir ajustes.', 'aviso');
      return;
    }
    const id = Number(botao.dataset.excluirAjuste);
    const item = (estado.ajustesDia || []).find((a) => a.id === id);
    estado.ajusteExcluirId = id;
    $('#excluir-ajuste-resumo').textContent = item
      ? `${fmtData(item.data)} · ${fmtMoeda(item.efeito)} · ${item.descricao}`
      : `Ajuste #${id}`;
    $('#excluir-ajuste-senha').value = '';
    $('#modal-excluir-ajuste').classList.add('aberto');
    setTimeout(() => $('#excluir-ajuste-senha').focus(), 60);
  });

  function fecharModalExcluirAjuste() {
    $('#modal-excluir-ajuste').classList.remove('aberto');
    estado.ajusteExcluirId = null;
  }

  $('#btn-cancelar-excluir-ajuste').addEventListener('click', fecharModalExcluirAjuste);
  $('#modal-excluir-ajuste').addEventListener('click', (e) => {
    if (e.target.id === 'modal-excluir-ajuste') fecharModalExcluirAjuste();
  });

  $('#btn-confirmar-excluir-ajuste').addEventListener('click', async () => {
    if (!estado.ajusteExcluirId) return;
    const corpo = new FormData();
    corpo.append('senha', $('#excluir-ajuste-senha').value);
    try {
      await requisitar(`/api/ajustes-saldo/${estado.ajusteExcluirId}`, { method: 'DELETE', body: corpo });
      notificar('Ajuste excluído e registrado no histórico.', 'sucesso');
      fecharModalExcluirAjuste();
      carregarDia(estado.diaAtual);
      carregarPainel();
    } catch (erro) {
      notificar(erro.message, 'erro');
      $('#excluir-ajuste-senha').select();
    }
  });

  /* ==================== Histórico de auditoria ==================== */

  const ROTULOS_ACAO = {
    salvar_dia: 'Edição manual',
    importar: 'Importação',
    restaurar: 'Restauração',
    ajuste_saldo: 'Ajuste de saldo',
    excluir_ajuste: 'Exclusão de ajuste',
  };

  let historicoAbertoId = null;
  let timerHistBusca = null;

  function sincronizarDatasHistorico(forcar = false) {
    if (estado.historico.datasSincronizadas && !forcar) return;
    if (estado.dados && estado.dados.periodo) {
      $('#hist-inicio').value = estado.dados.periodo.inicio || '';
      $('#hist-fim').value = estado.dados.periodo.fim || '';
      estado.historico.datasSincronizadas = true;
      return;
    }
    const globalInicio = $('#filtro-inicio').value;
    const globalFim = $('#filtro-fim').value;
    if (globalInicio && globalFim) {
      $('#hist-inicio').value = globalInicio;
      $('#hist-fim').value = globalFim;
      estado.historico.datasSincronizadas = true;
    }
  }

  function parametrosHistorico() {
    const p = new URLSearchParams();
    const inicio = $('#hist-inicio').value;
    const fim = $('#hist-fim').value;
    if (inicio && fim) {
      p.set('periodo', 'personalizado');
      p.set('inicio', inicio);
      p.set('fim', fim);
    } else {
      parametrosFiltro().forEach((valor, chave) => p.set(chave, valor));
    }

    const usuario = $('#hist-usuario').value;
    const acao = $('#hist-acao').value;
    const tipo = $('#hist-tipo').value;
    const dataRef = $('#hist-data-ref').value;
    const busca = $('#hist-busca').value.trim();

    if (usuario) p.set('usuario', usuario);
    if (acao) p.set('acao', acao);
    if (tipo) p.set('tipo', tipo);
    if (dataRef) p.set('data_ref', dataRef);
    if (busca) p.set('busca', busca);
    p.set('pagina', String(estado.historico.pagina));
    p.set('por_pagina', String(estado.historico.por_pagina));
    return p;
  }

  async function carregarHistorico({ resetarPagina = false } = {}) {
    sincronizarDatasHistorico();
    if (resetarPagina) estado.historico.pagina = 1;
    try {
      const dados = await requisitar('/api/historico?' + parametrosHistorico().toString());
      popularOpcoesHistorico(dados.opcoes || {});
      const pag = dados.paginacao || {};
      estado.historico.total = pag.total || 0;
      estado.historico.pagina = pag.pagina || 1;
      estado.historico.por_pagina = pag.por_pagina || estado.historico.por_pagina;
      estado.historico.total_paginas = pag.total_paginas || 1;
      renderizarHistorico(dados.historico || []);
      renderizarPaginacaoHistorico();
    } catch (erro) {
      notificar(`Erro ao carregar histórico: ${erro.message}`, 'erro');
    }
  }

  function popularOpcoesHistorico(opcoes) {
    const select = $('#hist-usuario');
    const atual = select.value;
    const usuarios = opcoes.usuarios || [];
    select.innerHTML =
      '<option value="">Todos</option>' +
      usuarios
        .map(
          (u) =>
            `<option value="${escapar(u.login)}">${escapar(u.nome)} (@${escapar(u.login)})</option>`
        )
        .join('');
    if (atual && [...select.options].some((o) => o.value === atual)) {
      select.value = atual;
    }

    const selectAcao = $('#hist-acao');
    const acaoAtual = selectAcao.value;
    const conhecidas = new Set(Object.keys(ROTULOS_ACAO));
    (opcoes.acoes || []).forEach((acao) => {
      if (!conhecidas.has(acao) && ![...selectAcao.options].some((o) => o.value === acao)) {
        const opt = document.createElement('option');
        opt.value = acao;
        opt.textContent = ROTULOS_ACAO[acao] || acao;
        selectAcao.appendChild(opt);
      }
    });
    selectAcao.value = acaoAtual;
  }

  function fmtDataHora(iso) {
    if (!iso) return '—';
    const texto = String(iso).replace('T', ' ');
    const [data, hora] = texto.split(' ');
    return `${fmtData(data)}${hora ? ' ' + hora.slice(0, 8) : ''}`;
  }

  function renderizarHistorico(lista) {
    const total = estado.historico.total;
    const pagina = estado.historico.pagina;
    const totalPaginas = estado.historico.total_paginas;
    $('#contador-historico').textContent = total
      ? `${total} alteração(ões) · página ${pagina} de ${totalPaginas}`
      : 'Nenhuma alteração para os filtros atuais';

    if (!lista.length) {
      $('#corpo-historico').innerHTML =
        '<tr><td colspan="7" style="text-align:center;color:var(--texto-3);padding:28px">Sem histórico para os filtros atuais.</td></tr>';
      return;
    }

    $('#corpo-historico').innerHTML = lista
      .map((item) => {
        const quem = item.usuario_nome
          ? `${escapar(item.usuario_nome)} <span class="hist-login">@${escapar(item.usuario_login)}</span>`
          : '—';
        return `<tr>
          <td class="hist-col-quando">${fmtDataHora(item.criado_em)}</td>
          <td class="hist-col-user">${quem}</td>
          <td class="hist-col-acao"><span class="etiqueta etiqueta--neutra">${escapar(ROTULOS_ACAO[item.acao] || item.acao)}</span></td>
          <td class="hist-col-dia">${fmtData(item.data_ref)}</td>
          <td class="hist-col-tipo">${item.tipo ? escapar(item.tipo) : '—'}</td>
          <td class="hist-col-resumo">${escapar(item.resumo)}</td>
          <td class="acoes-linha hist-col-acoes">
            <button class="btn btn-pequeno" data-hist-detalhe="${item.id}">Detalhes</button>
          </td>
        </tr>`;
      })
      .join('');
  }

  function renderizarPaginacaoHistorico() {
    const barra = $('#hist-paginacao');
    const total = estado.historico.total;
    const pagina = estado.historico.pagina;
    const totalPaginas = estado.historico.total_paginas;
    if (!total) {
      barra.hidden = true;
      return;
    }
    barra.hidden = false;
    $('#hist-pag-info').textContent = `Página ${pagina} de ${totalPaginas} · ${total} registro(s)`;
    $('#hist-pag-prev').disabled = pagina <= 1;
    $('#hist-pag-next').disabled = pagina >= totalPaginas;
  }

  ['#hist-usuario', '#hist-acao', '#hist-tipo', '#hist-inicio', '#hist-fim', '#hist-data-ref'].forEach((sel) => {
    $(sel).addEventListener('change', () => carregarHistorico({ resetarPagina: true }));
  });

  $('#hist-por-pagina').addEventListener('change', (e) => {
    estado.historico.por_pagina = Number(e.target.value) || 25;
    carregarHistorico({ resetarPagina: true });
  });

  $('#hist-busca').addEventListener('input', () => {
    clearTimeout(timerHistBusca);
    timerHistBusca = setTimeout(() => carregarHistorico({ resetarPagina: true }), 380);
  });

  $('#btn-hist-aplicar').addEventListener('click', () => carregarHistorico({ resetarPagina: true }));
  $('#btn-hist-limpar').addEventListener('click', () => {
    $('#hist-usuario').value = '';
    $('#hist-acao').value = '';
    $('#hist-tipo').value = '';
    $('#hist-data-ref').value = '';
    $('#hist-busca').value = '';
    $('#hist-por-pagina').value = '25';
    estado.historico.por_pagina = 25;
    estado.historico.datasSincronizadas = false;
    sincronizarDatasHistorico(true);
    carregarHistorico({ resetarPagina: true });
  });

  $('#hist-pag-prev').addEventListener('click', () => {
    if (estado.historico.pagina <= 1) return;
    estado.historico.pagina -= 1;
    carregarHistorico();
  });

  $('#hist-pag-next').addEventListener('click', () => {
    if (estado.historico.pagina >= estado.historico.total_paginas) return;
    estado.historico.pagina += 1;
    carregarHistorico();
  });

  function tabelaSnapshot(linhas, titulo) {
    const comValor = (linhas || []).filter(
      (l) => Number(l.prevista || 0) || Number(l.realizada || 0) || (l.descricao && l.descricao !== 'Editável')
    );

    if (!comValor.length) {
      return `<section class="snap-bloco">
        <header class="snap-titulo">${titulo}</header>
        <p class="snap-vazio">Sem linhas com valor.</p>
      </section>`;
    }

    const cards = comValor
      .map(
        (l) => `<article class="snap-item">
          <div class="snap-item-topo">
            <span class="snap-cat">${escapar(l.categoria || '—')}</span>
            <span class="snap-desc">${escapar(l.descricao || '—')}</span>
          </div>
          <div class="snap-valores">
            <div><span>Prevista</span><strong>${fmtMoeda(l.prevista)}</strong></div>
            <div><span>Realizada</span><strong>${fmtMoeda(l.realizada)}</strong></div>
          </div>
        </article>`
      )
      .join('');

    return `<section class="snap-bloco">
      <header class="snap-titulo">${titulo} <em>${comValor.length} linha(s)</em></header>
      <div class="snap-lista">${cards}</div>
    </section>`;
  }

  async function abrirDetalheHistorico(id) {
    try {
      const item = await requisitar(`/api/historico/${id}`);
      historicoAbertoId = item.id;
      $('#modal-historico-corpo').innerHTML = `
        <div class="historico-meta">
          <div><span>Quando</span><strong>${fmtDataHora(item.criado_em)}</strong></div>
          <div><span>Usuário</span><strong>${escapar(item.usuario_nome || '—')} <small>(@${escapar(item.usuario_login || '—')})</small></strong></div>
          <div><span>Ação</span><strong>${escapar(ROTULOS_ACAO[item.acao] || item.acao)}</strong></div>
          <div><span>Dia / tipo</span><strong>${fmtData(item.data_ref)} · ${escapar(item.tipo || '—')}</strong></div>
          <div class="historico-meta-resumo"><span>Resumo</span><strong>${escapar(item.resumo)}</strong></div>
        </div>
        <div class="historico-comparativo">
          ${tabelaSnapshot(item.antes, 'Antes')}
          ${tabelaSnapshot(item.depois, 'Depois')}
        </div>`;
      $('#btn-restaurar-historico').hidden = !(
        estado.usuario &&
        item.tipo &&
        item.acao !== 'restaurar' &&
        item.acao !== 'ajuste_saldo' &&
        item.acao !== 'excluir_ajuste'
      );
      $('#btn-ir-dia-historico').dataset.dia = item.data_ref;
      $('#modal-historico-detalhe').classList.add('aberto');
      // Garante que o conteúdo começa no topo ao abrir.
      const corpo = $('#modal-historico-corpo');
      if (corpo) corpo.scrollTop = 0;
    } catch (erro) {
      notificar(erro.message, 'erro');
    }
  }

  function fecharDetalheHistorico() {
    $('#modal-historico-detalhe').classList.remove('aberto');
    historicoAbertoId = null;
  }

  $('#corpo-historico').addEventListener('click', (e) => {
    const botao = e.target.closest('[data-hist-detalhe]');
    if (!botao) return;
    abrirDetalheHistorico(Number(botao.dataset.histDetalhe));
  });

  $('#btn-fechar-historico-detalhe').addEventListener('click', fecharDetalheHistorico);
  $('#modal-historico-detalhe').addEventListener('click', (e) => {
    if (e.target.id === 'modal-historico-detalhe') fecharDetalheHistorico();
  });

  $('#btn-ir-dia-historico').addEventListener('click', () => {
    const dia = $('#btn-ir-dia-historico').dataset.dia;
    if (!dia) return;
    fecharDetalheHistorico();
    $('#dia-edicao').value = dia;
    ativarAba('lancamentos');
    carregarDia(dia);
    notificar(`Dia ${fmtData(dia)} aberto na aba Lançamentos.`, 'info');
  });

  $('#btn-restaurar-historico').addEventListener('click', async () => {
    if (!historicoAbertoId) return;
    if (!estado.usuario) {
      AuthUI.abrirLogin();
      return;
    }
    if (!confirm('Restaurar a versão anterior desta alteração? Isso grava um novo evento no histórico.')) return;
    try {
      const resp = await requisitar(`/api/historico/${historicoAbertoId}/restaurar`, { method: 'POST' });
      notificar('Versão anterior restaurada.', 'sucesso');
      fecharDetalheHistorico();
      carregarHistorico();
      carregarPainel();
      if (resp.data) {
        $('#dia-edicao').value = resp.data;
        carregarDia(resp.data);
      }
    } catch (erro) {
      notificar(erro.message, 'erro');
    }
  });

  /* ==================== Exportação ==================== */

  $('#btn-exportar-excel').addEventListener('click', () => {
    window.location.href = withRoot('/api/exportar/excel?' + parametrosFiltro().toString());
    notificar('Gerando a planilha do período filtrado...', 'info', 2600);
  });

  $('#btn-exportar-pdf').addEventListener('click', () => {
    window.location.href = withRoot('/api/exportar/pdf?' + parametrosFiltro().toString());
    notificar('Gerando o relatório em PDF...', 'info', 2600);
  });

  /* ==================== Início ==================== */

  aplicarTema(document.documentElement.dataset.tema);
  ativarAba(abaSalva());
  carregarPainel();
  carregarDia(window.CONFIG_FUNDEB.hoje);
})();
