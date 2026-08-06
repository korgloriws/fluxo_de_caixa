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
    arquivos: [],
    usuario: window.CONFIG_FUNDEB.usuario || null,
    mesAtualEncerrado: false,
    mesAtual: null,
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

  async function requisitar(url, opcoes = {}) {
    carregando(true);
    try {
      const resposta = await fetch(url, opcoes);
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

    if (estado.usuario) {
      status.textContent = `Editando como ${estado.usuario.nome}`;
      status.classList.add('sessao-status--ativo');
      btnEditar.hidden = true;
      btnSair.hidden = false;
      if (linkUsuarios) linkUsuarios.hidden = !estado.usuario.eh_admin;
    } else {
      status.textContent = 'Visualizando';
      status.classList.remove('sessao-status--ativo');
      btnEditar.hidden = false;
      btnSair.hidden = true;
      if (linkUsuarios) linkUsuarios.hidden = true;
    }
  }

  function aoAutenticar(usuario) {
    estado.usuario = usuario;
    atualizarBarraSessao();
    carregarDia(estado.diaAtual);
  }

  AuthUI.ligarModalLogin({ onSuccess: aoAutenticar });
  atualizarBarraSessao();

  $('#btn-editar').addEventListener('click', () => {
    if (estado.usuario) return;
    AuthUI.abrirLogin();
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

  async function carregarPainel() {
    try {
      const dados = await requisitar('/api/painel?' + parametrosFiltro().toString());
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
      corpo.innerHTML = `<tr><td colspan="8">
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
      const comparacao = typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'pt-BR');
      return crescente ? comparacao : -comparacao;
    });

    corpo.innerHTML = ordenados
      .map((m) => {
        const desvio = m.realizada - m.prevista;
        const classeDesvio = desvio > 0 ? 'positivo' : desvio < 0 ? 'negativo' : '';
        return `<tr>
          <td class="num">${fmtData(m.data)}</td>
          <td class="col-tipo"><span class="etiqueta etiqueta--${m.tipo}">${m.tipo === 'receita' ? 'Receita' : 'Despesa'}</span></td>
          <td class="col-categoria">${m.categoria || '<span style="color:var(--texto-3)">—</span>'}</td>
          <td>${m.descricao || '<span style="color:var(--texto-3)">—</span>'}</td>
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

      renderizarAvisoMes(dados);
      renderizarAjustesDia(estado.ajustesDia);
      renderizarKpisDia(dados.totais);
      renderizarGrade();
    } catch (erro) {
      notificar(`Erro ao carregar o dia: ${erro.message}`, 'erro');
    }
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

    $('#titulo-grade').textContent = tipo === 'receita' ? 'Receitas do dia' : 'Despesas do dia';
    $('#btn-adicionar-linha').disabled = !estado.diaEditavel;
    $('#btn-salvar-dia').disabled = !estado.diaEditavel;

    const desabilitado = estado.diaEditavel ? '' : 'disabled';

    $('#corpo-grade').innerHTML = linhas
      .map((linha, indice) => {
        const opcoes = categorias
          .map((c) => `<option value="${c}" ${c === linha.categoria ? 'selected' : ''}>${c}</option>`)
          .join('');
        const extra = categorias.includes(linha.categoria)
          ? ''
          : `<option value="${linha.categoria}" selected>${linha.categoria || '—'}</option>`;

        return `<tr data-indice="${indice}">
          <td>
            <select class="celula-entrada" data-campo="categoria" ${desabilitado}>${extra}${opcoes}</select>
          </td>
          <td>
            <input class="celula-entrada" data-campo="descricao" value="${escapar(linha.descricao)}" ${desabilitado}>
          </td>
          <td>
            <input class="celula-entrada numero" data-campo="prevista" inputmode="decimal"
                   value="${linha.prevista ? fmtNumero(linha.prevista) : ''}" placeholder="0,00" ${desabilitado}>
          </td>
          <td>
            <input class="celula-entrada numero" data-campo="realizada" inputmode="decimal"
                   value="${linha.realizada ? fmtNumero(linha.realizada) : ''}" placeholder="0,00" ${desabilitado}>
          </td>
          <td class="acoes-linha">
            <button class="btn-remover" data-acao="remover" title="Remover linha" ${desabilitado}>
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
    const botao = evento.target.closest('[data-acao="remover"]');
    if (!botao) return;
    const indice = Number(botao.closest('tr').dataset.indice);
    estado.linhas[estado.tipoEditor].splice(indice, 1);
    renderizarGrade();
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
    const categorias =
      estado.tipoEditor === 'receita'
        ? window.CONFIG_FUNDEB.categoriasReceita
        : window.CONFIG_FUNDEB.categoriasDespesa;

    estado.linhas[estado.tipoEditor].push({
      categoria: categorias[categorias.length - 1],
      descricao: '',
      prevista: 0,
      realizada: 0,
    });

    renderizarGrade();
    const linhas = $$('#corpo-grade tr');
    const ultima = linhas[linhas.length - 1];
    if (ultima) ultima.querySelector('[data-campo="descricao"]').focus();
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

  const zona = $('#zona-upload');
  const entradaArquivos = $('#entrada-arquivos');

  zona.addEventListener('click', () => entradaArquivos.click());

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
  entradaArquivos.addEventListener('change', (e) => adicionarArquivos(e.target.files));

  function adicionarArquivos(lista) {
    estado.arquivos = [...estado.arquivos, ...Array.from(lista)];
    renderizarArquivos();
  }

  function renderizarArquivos() {
    const temArquivos = estado.arquivos.length > 0;
    $('#btn-processar').disabled = !temArquivos;
    $('#btn-limpar-arquivos').disabled = !temArquivos;

    $('#lista-arquivos').innerHTML = estado.arquivos
      .map(
        (arquivo, indice) => `
        <div class="arquivo-item">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
          </svg>
          <span class="nome">${escapar(arquivo.name)}</span>
          <span style="color:var(--texto-3);font-size:12px">${(arquivo.size / 1024).toFixed(0)} KB</span>
          <button class="btn-remover" data-indice="${indice}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>`
      )
      .join('');

    $$('#lista-arquivos .btn-remover').forEach((botao) =>
      botao.addEventListener('click', () => {
        estado.arquivos.splice(Number(botao.dataset.indice), 1);
        renderizarArquivos();
      })
    );
  }

  $('#btn-limpar-arquivos').addEventListener('click', () => {
    estado.arquivos = [];
    entradaArquivos.value = '';
    $('#resultado-importacao').innerHTML = '';
    renderizarArquivos();
  });

  $('#btn-processar').addEventListener('click', async () => {
    if (!estado.usuario) {
      notificar('Faça login para importar arquivos.', 'aviso');
      AuthUI.abrirLogin();
      return;
    }

    const corpo = new FormData();
    estado.arquivos.forEach((arquivo) => corpo.append('arquivos', arquivo));

    try {
      const resultado = await requisitar('/api/importar', { method: 'POST', body: corpo });
      renderizarResultadoImportacao(resultado);

      const totalDias = resultado.dias.length;
      if (totalDias) {
        notificar(`Importação concluída: ${totalDias} dia(s) atualizado(s).`, 'sucesso');
        carregarPainel();
        carregarDia(estado.diaAtual);
      } else {
        notificar('Nenhum dado novo foi gravado. Verifique o detalhamento abaixo.', 'aviso');
      }

      estado.arquivos = [];
      entradaArquivos.value = '';
      renderizarArquivos();
    } catch (erro) {
      notificar(`Falha na importação: ${erro.message}`, 'erro');
    }
  });

  function renderizarResultadoImportacao(resultado) {
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
              .map((p) => `${escapar(p.arquivo)} — ${p.dias_gravados} dia(s) gravado(s)`)
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

    if (resultado.erros.length) {
      partes.push(`
        <div class="aviso aviso--bloqueado">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <div class="aviso-conteudo">
            <strong>Erros</strong>
            ${resultado.erros.map((e) => `${escapar(e.arquivo)}: ${escapar(e.motivo)}`).join('<br>')}
          </div>
        </div>`);
    }

    $('#resultado-importacao').innerHTML = partes.join('');
  }

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
    window.location.href = '/api/exportar/excel?' + parametrosFiltro().toString();
    notificar('Gerando a planilha do período filtrado...', 'info', 2600);
  });

  $('#btn-exportar-pdf').addEventListener('click', () => {
    window.location.href = '/api/exportar/pdf?' + parametrosFiltro().toString();
    notificar('Gerando o relatório em PDF...', 'info', 2600);
  });

  /* ==================== Início ==================== */

  aplicarTema(document.documentElement.dataset.tema);
  ativarAba(abaSalva());
  carregarPainel();
  carregarDia(window.CONFIG_FUNDEB.hoje);
})();
