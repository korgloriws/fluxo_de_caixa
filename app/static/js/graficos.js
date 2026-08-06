/* ==========================================================================
   Gráficos do painel (ECharts)
   ========================================================================== */

const Graficos = (() => {
  const instancias = {};

  const CORES = {
    receita: '#16a34a',
    despesa: '#dc2626',
    saldo: '#ca8a04',
    previsto: '#94a3b8',
    paleta: ['#ca8a04', '#16a34a', '#7c3aed', '#dc2626', '#0891b2', '#db2777', '#65a30d', '#ea580c', '#0f766e'],
  };

  const CONSULTA_ESTREITA = window.matchMedia('(max-width: 760px)');
  const telaEstreita = () => CONSULTA_ESTREITA.matches;

  function tokens() {
    const estilo = getComputedStyle(document.documentElement);
    const ler = (nome, padrao) => (estilo.getPropertyValue(nome) || padrao).trim();
    return {
      escuro: document.documentElement.dataset.tema === 'escuro',
      texto: ler('--texto', '#16233a'),
      texto2: ler('--texto-2', '#5a6b85'),
      texto3: ler('--texto-3', '#8695ab'),
      grade: ler('--grade-grafico', '#e6ecf4'),
      superficie: ler('--superficie', '#ffffff'),
      borda: ler('--borda', '#dde4ee'),
    };
  }

  const fmtMoeda = (v) =>
    'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function fmtCompacto(v) {
    const n = Number(v || 0);
    const abs = Math.abs(n);
    if (abs >= 1e9) return (n / 1e9).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' bi';
    if (abs >= 1e6) return (n / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi';
    if (abs >= 1e3) return (n / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 0 }) + ' mil';
    return n.toLocaleString('pt-BR', { maximumFractionDigits: 0 });
  }

  const fmtData = (iso) => {
    if (!iso) return '';
    const [a, m, d] = String(iso).slice(0, 10).split('-');
    return `${d}/${m}/${a}`;
  };

  const fmtDataCurta = (iso) => {
    if (!iso) return '';
    const [, m, d] = String(iso).slice(0, 10).split('-');
    return `${d}/${m}`;
  };

  function obter(id) {
    const elemento = document.getElementById(id);
    if (!elemento) return null;
    if (!instancias[id]) {
      instancias[id] = echarts.init(elemento, null, { renderer: 'canvas' });
    }
    return instancias[id];
  }

  function baseTooltip(t) {
    return {
      backgroundColor: t.superficie,
      borderColor: t.borda,
      borderWidth: 1,
      padding: [9, 13],
      textStyle: { color: t.texto, fontSize: 12.5 },
      extraCssText: 'box-shadow: 0 6px 24px rgba(0,0,0,.14); border-radius: 9px;',
    };
  }

  function semDados(id, mensagem) {
    const grafico = obter(id);
    if (!grafico) return;
    const t = tokens();
    grafico.clear();
    grafico.setOption({
      title: {
        text: mensagem || 'Sem dados no período selecionado',
        left: 'center',
        top: 'middle',
        textStyle: { color: t.texto3, fontSize: 13, fontWeight: 400 },
      },
    });
  }

  /* ---------------- 1. Evolução diária ---------------- */

  function evolucao(dados, modo = 'tudo') {
    const id = 'gr-evolucao';
    const pontos = (dados && dados.pontos) || [];
    if (!pontos.length) return semDados(id, 'Nenhum lançamento no período selecionado');

    const t = tokens();
    const grafico = obter(id);
    const datas = pontos.map((p) => p.data);
    const estreito = telaEstreita();

    const series = [];

    if (modo !== 'acumulado') {
      series.push(
        {
          name: 'Receita',
          type: 'bar',
          data: pontos.map((p) => p.receita),
          itemStyle: { color: CORES.receita, borderRadius: [3, 3, 0, 0] },
          barMaxWidth: 22,
        },
        {
          name: 'Despesa',
          type: 'bar',
          data: pontos.map((p) => p.despesa),
          itemStyle: { color: CORES.despesa, borderRadius: [3, 3, 0, 0] },
          barMaxWidth: 22,
        }
      );
    }

    if (modo !== 'fluxo') {
      series.push({
        name: 'Saldo acumulado',
        type: 'line',
        yAxisIndex: 1,
        data: pontos.map((p) => p.saldo_acumulado),
        smooth: 0.3,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: pontos.length <= 40,
        lineStyle: { width: 2.6, color: CORES.saldo },
        itemStyle: { color: CORES.saldo },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(202,138,4,0.24)' },
            { offset: 1, color: 'rgba(202,138,4,0.01)' },
          ]),
        },
      });
    }

    grafico.setOption(
      {
        tooltip: {
          ...baseTooltip(t),
          trigger: 'axis',
          axisPointer: { type: 'cross', label: { backgroundColor: t.texto2 } },
          formatter: (params) => {
            if (!params.length) return '';
            let html = `<div style="font-weight:650;margin-bottom:6px">${fmtData(params[0].axisValue)}</div>`;
            params.forEach((p) => {
              html += `<div style="display:flex;justify-content:space-between;gap:18px;line-height:1.7">
                <span>${p.marker} ${p.seriesName}</span>
                <strong>${fmtMoeda(p.value)}</strong></div>`;
            });
            return html;
          },
        },
        legend: {
          type: 'scroll',
          top: 8,
          textStyle: { color: t.texto2, fontSize: estreito ? 11 : 12 },
          itemGap: estreito ? 11 : 18,
          icon: 'roundRect',
          itemWidth: 12,
          itemHeight: 12,
        },
        grid: {
          left: estreito ? 4 : 14,
          right: estreito ? 4 : 14,
          top: estreito ? 40 : 48,
          bottom: pontos.length > 20 ? 56 : 34,
          containLabel: true,
        },
        xAxis: {
          type: 'category',
          data: datas,
          axisLabel: { color: t.texto3, fontSize: estreito ? 10 : 11, formatter: fmtDataCurta, hideOverlap: true },
          axisLine: { lineStyle: { color: t.grade } },
          axisTick: { show: false },
        },
        yAxis: [
          {
            type: 'value',
            // Os nomes dos eixos consomem largura preciosa no celular.
            name: estreito ? '' : 'Movimento',
            nameTextStyle: { color: t.texto3, fontSize: 11, padding: [0, 0, 0, 34] },
            axisLabel: { color: t.texto3, fontSize: estreito ? 10 : 11, formatter: fmtCompacto },
            splitLine: { lineStyle: { color: t.grade, type: 'dashed' } },
          },
          {
            type: 'value',
            name: estreito ? '' : 'Acumulado',
            nameTextStyle: { color: t.texto3, fontSize: 11, padding: [0, 34, 0, 0] },
            axisLabel: { color: t.texto3, fontSize: estreito ? 10 : 11, formatter: fmtCompacto },
            splitLine: { show: false },
          },
        ],
        dataZoom:
          pontos.length > 20
            ? [
                { type: 'inside', start: 0, end: 100 },
                {
                  type: 'slider',
                  height: 18,
                  bottom: 8,
                  borderColor: 'transparent',
                  backgroundColor: t.grade,
                  fillerColor: 'rgba(202,138,4,0.18)',
                  handleStyle: { color: CORES.saldo },
                  textStyle: { color: t.texto3, fontSize: 10 },
                  labelFormatter: (i, valor) => fmtDataCurta(valor),
                },
              ]
            : [],
        series,
      },
      true
    );
  }

  /* ---------------- 2. Composição por categoria ---------------- */

  function rosca(id, itens, tipo) {
    const dados = (itens || []).filter((i) => i.realizada > 0);
    if (!dados.length) {
      return semDados(
        id,
        tipo === 'receita' ? 'Nenhuma receita realizada no período' : 'Nenhuma despesa realizada no período'
      );
    }

    const t = tokens();
    const grafico = obter(id);
    const total = dados.reduce((s, i) => s + i.realizada, 0);
    const estreito = telaEstreita();

    // Em tela estreita a legenda lateral espremeria a rosca: ela desce para o rodapé.
    const legenda = estreito
      ? { orient: 'horizontal', bottom: 0, left: 'center', right: 'auto', top: 'auto' }
      : { orient: 'vertical', right: 8, top: 'center' };

    grafico.setOption(
      {
        tooltip: {
          ...baseTooltip(t),
          trigger: 'item',
          formatter: (p) =>
            `<div style="font-weight:650;margin-bottom:4px">${p.name}</div>
             <div>${fmtMoeda(p.value)}</div>
             <div style="color:${t.texto3};font-size:11.5px">${p.percent}% do total</div>`,
        },
        legend: {
          type: 'scroll',
          ...legenda,
          itemGap: estreito ? 13 : 9,
          icon: 'circle',
          itemWidth: 9,
          itemHeight: 9,
          textStyle: { color: t.texto2, fontSize: 11.5 },
          formatter: (nome) => (nome.length > 18 ? nome.slice(0, 17) + '…' : nome),
        },
        series: [
          {
            type: 'pie',
            radius: estreito ? ['48%', '70%'] : ['52%', '76%'],
            center: estreito ? ['50%', '42%'] : ['33%', '52%'],
            avoidLabelOverlap: true,
            itemStyle: { borderColor: t.superficie, borderWidth: 2.5, borderRadius: 5 },
            label: {
              show: true,
              position: 'center',
              formatter: () => `{valor|${fmtCompacto(total)}}\n{rotulo|Total}`,
              rich: {
                valor: { fontSize: 19, fontWeight: 680, color: t.texto, lineHeight: 26 },
                rotulo: { fontSize: 11, color: t.texto3, letterSpacing: 0.5 },
              },
            },
            emphasis: {
              label: {
                show: true,
                formatter: (p) => `{valor|${fmtCompacto(p.value)}}\n{rotulo|${p.percent}%}`,
              },
              itemStyle: { shadowBlur: 14, shadowColor: 'rgba(0,0,0,0.18)' },
            },
            data: dados.map((i, indice) => ({
              name: i.categoria,
              value: i.realizada,
              itemStyle: {
                color:
                  tipo === 'despesa'
                    ? CORES.paleta[(indice + 4) % CORES.paleta.length]
                    : CORES.paleta[indice % CORES.paleta.length],
              },
            })),
          },
        ],
      },
      true
    );
  }

  /* ---------------- 3. Previsto x Realizado ---------------- */

  function previstoRealizado(dados, tipo) {
    const id = 'gr-previsto-realizado';
    const itens = ((dados && dados[tipo]) || []).filter((i) => i.prevista > 0 || i.realizada > 0);

    if (!itens.length) {
      return semDados(id, `Nenhuma ${tipo} com previsão ou realização no período`);
    }

    const t = tokens();
    const grafico = obter(id);
    itens.sort((a, b) => Math.max(b.prevista, b.realizada) - Math.max(a.prevista, a.realizada));

    const categorias = itens.map((i) => i.categoria);
    const corPrincipal = tipo === 'receita' ? CORES.receita : CORES.despesa;

    grafico.setOption(
      {
        tooltip: {
          ...baseTooltip(t),
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params) => {
            const item = itens[params[0].dataIndex];
            const execucao =
              item.execucao_pct === null || item.execucao_pct === undefined
                ? 'sem previsão'
                : item.execucao_pct.toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + '%';
            const corDesvio = item.desvio >= 0 ? CORES.receita : CORES.despesa;
            return `<div style="font-weight:650;margin-bottom:6px">${item.categoria}</div>
              <div style="display:flex;justify-content:space-between;gap:18px"><span>Prevista</span><strong>${fmtMoeda(item.prevista)}</strong></div>
              <div style="display:flex;justify-content:space-between;gap:18px"><span>Realizada</span><strong>${fmtMoeda(item.realizada)}</strong></div>
              <div style="display:flex;justify-content:space-between;gap:18px;margin-top:4px;padding-top:4px;border-top:1px solid ${t.borda}">
                <span>Desvio</span><strong style="color:${corDesvio}">${fmtMoeda(item.desvio)}</strong></div>
              <div style="color:${t.texto3};font-size:11.5px;margin-top:2px">Execução: ${execucao}</div>`;
          },
        },
        legend: {
          top: 6,
          textStyle: { color: t.texto2, fontSize: 12 },
          icon: 'roundRect',
          itemWidth: 12,
          itemHeight: 12,
        },
        grid: { left: 14, right: 24, top: 44, bottom: 14, containLabel: true },
        xAxis: {
          type: 'value',
          axisLabel: { color: t.texto3, fontSize: 11, formatter: fmtCompacto },
          splitLine: { lineStyle: { color: t.grade, type: 'dashed' } },
        },
        yAxis: {
          type: 'category',
          data: categorias,
          inverse: true,
          axisLabel: { color: t.texto2, fontSize: 11.5 },
          axisLine: { lineStyle: { color: t.grade } },
          axisTick: { show: false },
        },
        series: [
          {
            name: 'Prevista',
            type: 'bar',
            data: itens.map((i) => i.prevista),
            itemStyle: { color: CORES.previsto, borderRadius: [0, 4, 4, 0] },
            barGap: '12%',
            barMaxWidth: 16,
          },
          {
            name: 'Realizada',
            type: 'bar',
            data: itens.map((i) => i.realizada),
            itemStyle: { color: corPrincipal, borderRadius: [0, 4, 4, 0] },
            barMaxWidth: 16,
            label: {
              show: true,
              position: 'right',
              color: t.texto3,
              fontSize: 10.5,
              formatter: (p) => (p.value > 0 ? fmtCompacto(p.value) : ''),
            },
          },
        ],
      },
      true
    );
  }

  /* ---------------- 4. Comparativo mensal ---------------- */

  const MESES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

  function mensal(dados) {
    const id = 'gr-mensal';
    const series = (dados && dados.series) || [];
    const comMovimento = series.filter((s) => s.total_receita > 0 || s.total_despesa > 0);

    if (!comMovimento.length) return semDados(id, 'Nenhum movimento registrado');

    const t = tokens();
    const grafico = obter(id);
    const seriesEcharts = [];

    comMovimento.forEach((registro, indice) => {
      seriesEcharts.push({
        name: `Receita ${registro.ano}`,
        type: 'bar',
        data: registro.receita,
        itemStyle: {
          color: CORES.paleta[indice % CORES.paleta.length],
          borderRadius: [3, 3, 0, 0],
          opacity: 0.9,
        },
        barMaxWidth: 24,
      });
    });

    comMovimento.forEach((registro, indice) => {
      seriesEcharts.push({
        name: `Acumulado ${registro.ano}`,
        type: 'line',
        yAxisIndex: 1,
        data: registro.acumulado,
        smooth: 0.3,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2.2, type: indice === 0 ? 'solid' : 'dashed', color: CORES.paleta[indice % CORES.paleta.length] },
        itemStyle: { color: CORES.paleta[indice % CORES.paleta.length] },
      });
    });

    grafico.setOption(
      {
        tooltip: {
          ...baseTooltip(t),
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params) => {
            if (!params.length) return '';
            let html = `<div style="font-weight:650;margin-bottom:6px">${params[0].axisValue}</div>`;
            params
              .filter((p) => p.value)
              .forEach((p) => {
                html += `<div style="display:flex;justify-content:space-between;gap:18px;line-height:1.7">
                  <span>${p.marker} ${p.seriesName}</span><strong>${fmtMoeda(p.value)}</strong></div>`;
              });
            return html;
          },
        },
        legend: {
          type: 'scroll',
          top: 6,
          textStyle: { color: t.texto2, fontSize: 11.5 },
          icon: 'roundRect',
          itemWidth: 11,
          itemHeight: 11,
        },
        grid: { left: 14, right: 14, top: 48, bottom: 10, containLabel: true },
        xAxis: {
          type: 'category',
          data: MESES,
          axisLabel: { color: t.texto3, fontSize: 11 },
          axisLine: { lineStyle: { color: t.grade } },
          axisTick: { show: false },
        },
        yAxis: [
          {
            type: 'value',
            name: 'No mês',
            nameTextStyle: { color: t.texto3, fontSize: 11 },
            axisLabel: { color: t.texto3, fontSize: 11, formatter: fmtCompacto },
            splitLine: { lineStyle: { color: t.grade, type: 'dashed' } },
          },
          {
            type: 'value',
            name: 'Acumulado',
            nameTextStyle: { color: t.texto3, fontSize: 11 },
            axisLabel: { color: t.texto3, fontSize: 11, formatter: fmtCompacto },
            splitLine: { show: false },
          },
        ],
        series: seriesEcharts,
      },
      true
    );
  }

  /* ---------------- 5. Calendário de movimentação ---------------- */

  function calendario(dados) {
    const id = 'gr-calendario';
    const dias = (dados && dados.dias) || [];
    const comValor = dias.filter((d) => d.receita > 0 || d.despesa > 0);

    if (!comValor.length) return semDados(id, 'Nenhuma movimentação no ano selecionado');

    const t = tokens();
    const grafico = obter(id);
    const ano = dados.ano;

    const pontos = comValor.map((d) => [d.data, d.receita - d.despesa]);
    const valores = pontos.map((p) => Math.abs(p[1]));
    const maximo = Math.max(...valores, 1);

    grafico.setOption(
      {
        tooltip: {
          ...baseTooltip(t),
          formatter: (p) => {
            const dia = comValor.find((d) => d.data === p.value[0]);
            if (!dia) return '';
            return `<div style="font-weight:650;margin-bottom:5px">${fmtData(dia.data)}</div>
              <div style="display:flex;justify-content:space-between;gap:18px"><span>Receita</span><strong style="color:${CORES.receita}">${fmtMoeda(dia.receita)}</strong></div>
              <div style="display:flex;justify-content:space-between;gap:18px"><span>Despesa</span><strong style="color:${CORES.despesa}">${fmtMoeda(dia.despesa)}</strong></div>
              <div style="display:flex;justify-content:space-between;gap:18px;margin-top:4px;padding-top:4px;border-top:1px solid ${t.borda}"><span>Saldo</span><strong>${fmtMoeda(dia.saldo)}</strong></div>
              <div style="color:${t.texto3};font-size:11.5px;margin-top:2px">${dia.lancamentos} lançamento(s)</div>`;
          },
        },
        visualMap: {
          min: 0,
          max: maximo,
          calculable: false,
          orient: 'horizontal',
          left: 'center',
          bottom: 2,
          itemWidth: 11,
          itemHeight: 70,
          textStyle: { color: t.texto3, fontSize: 10 },
          formatter: (v) => fmtCompacto(v),
          // No tema escuro a escala vai do dourado profundo ao claro, para que
          // valores baixos não virem manchas quase brancas sobre o fundo.
          inRange: {
            color: t.escuro
              ? ['#3d2c06', '#a16207', '#eab308', '#fde68a']
              : ['#fef3c7', '#fbbf24', '#ca8a04', '#7a5406'],
          },
        },
        calendar: {
          top: 26,
          left: 34,
          right: 12,
          bottom: 62,
          cellSize: ['auto', 13],
          range: String(ano),
          orient: 'vertical',
          splitLine: { lineStyle: { color: t.grade, width: 1.5 } },
          itemStyle: { color: t.escuro ? '#1a2434' : '#f2f5f9', borderColor: t.grade, borderWidth: 1 },
          yearLabel: { show: false },
          monthLabel: { color: t.texto3, fontSize: 10, nameMap: MESES },
          dayLabel: { color: t.texto3, fontSize: 9, firstDay: 1, nameMap: ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'] },
        },
        series: [
          {
            type: 'heatmap',
            coordinateSystem: 'calendar',
            data: pontos.map((p) => [p[0], Math.abs(p[1])]),
            itemStyle: { borderRadius: 2 },
          },
        ],
      },
      true
    );
  }

  /* ---------------- 6. Rankings ---------------- */

  function ranking(id, itens, tipo) {
    const dados = (itens || []).filter((i) => i.valor > 0);
    if (!dados.length) {
      return semDados(id, tipo === 'entradas' ? 'Nenhuma entrada no período' : 'Nenhuma saída no período');
    }

    const t = tokens();
    const grafico = obter(id);
    const ordenados = [...dados].sort((a, b) => a.valor - b.valor);
    const cor = tipo === 'entradas' ? CORES.receita : CORES.despesa;

    grafico.setOption(
      {
        tooltip: {
          ...baseTooltip(t),
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params) => {
            const item = ordenados[params[0].dataIndex];
            return `<div style="font-weight:650;margin-bottom:4px">${item.descricao || item.categoria}</div>
              <div style="color:${t.texto3};font-size:11.5px;margin-bottom:4px">${item.categoria} · ${fmtData(item.data)}</div>
              <strong>${fmtMoeda(item.valor)}</strong>`;
          },
        },
        grid: { left: 10, right: 62, top: 10, bottom: 10, containLabel: true },
        xAxis: { type: 'value', show: false },
        yAxis: {
          type: 'category',
          data: ordenados.map((i) => {
            const rotulo = i.descricao || i.categoria;
            return rotulo.length > 22 ? rotulo.slice(0, 21) + '…' : rotulo;
          }),
          axisLabel: { color: t.texto2, fontSize: 11.5 },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        series: [
          {
            type: 'bar',
            data: ordenados.map((i) => i.valor),
            itemStyle: { color: cor, borderRadius: [0, 5, 5, 0], opacity: 0.88 },
            barMaxWidth: 17,
            label: {
              show: true,
              position: 'right',
              color: t.texto2,
              fontSize: 11,
              fontWeight: 600,
              formatter: (p) => fmtCompacto(p.value),
            },
          },
        ],
      },
      true
    );
  }

  /* ---------------- Utilitários ---------------- */

  function redimensionar() {
    Object.values(instancias).forEach((g) => g && g.resize());
  }

  function destruirTodos() {
    Object.keys(instancias).forEach((id) => {
      instancias[id].dispose();
      delete instancias[id];
    });
  }

  window.addEventListener('resize', () => {
    clearTimeout(window.__timerResize);
    window.__timerResize = setTimeout(redimensionar, 140);
  });

  return {
    evolucao,
    rosca,
    previstoRealizado,
    mensal,
    calendario,
    ranking,
    redimensionar,
    destruirTodos,
    fmtMoeda,
    fmtCompacto,
    fmtData,
    CORES,
  };
})();
