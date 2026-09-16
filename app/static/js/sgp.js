/* Módulo SGP Pagamentos — NAP e Empenho. */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const estado = {
    meta: null,
    cache: { nap: [], empenho: [] },
  };

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

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

  function isoHoje() {
    return new Date().toISOString().slice(0, 10);
  }

  function isoPrimeiroDiaMes() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
  }

  function preencherDatasPadrao() {
    const ano = String(new Date().getFullYear());
    ['nap-ano', 'emp-ano'].forEach((id) => {
      const el = document.getElementById(id);
      if (el && !el.value) el.value = ano;
    });
    ['nap-inicio', 'emp-inicio'].forEach((id) => {
      const el = document.getElementById(id);
      if (el && !el.value) el.value = isoPrimeiroDiaMes();
    });
    ['nap-fim', 'emp-fim'].forEach((id) => {
      const el = document.getElementById(id);
      if (el && !el.value) el.value = isoHoje();
    });
  }

  function initAbas() {
    document.querySelectorAll('.abas .aba').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.abas .aba').forEach((b) => b.classList.remove('ativa'));
        document.querySelectorAll('.painel-aba').forEach((p) => p.classList.remove('ativo'));
        btn.classList.add('ativa');
        document.querySelector(`.painel-aba[data-painel="${btn.dataset.aba}"]`)?.classList.add('ativo');
      });
    });
  }

  function renderGlossario() {
    const consultas = estado.meta?.consultas || [];
    consultas.forEach((c) => {
      const box = document.getElementById(`gloss-${c.id}`);
      if (!box) return;
      box.innerHTML = (c.glossario || [])
        .map(
          (g) => `
        <article class="sgp-glossa-item">
          <h4>${escapeHtml(g.rotulo)}</h4>
          <code>${escapeHtml(g.campo)}</code>
          <p>${escapeHtml(g.explicacao)}</p>
        </article>`
        )
        .join('');
    });
  }

  async function carregarMeta() {
    const resp = await fetch('/api/sgp/meta');
    estado.meta = await resp.json();
    renderGlossario();
    const st = estado.meta.status || {};
    if (!st.wsdl_ok) {
      notificar(st.mensagem || 'WSDL SGP indisponível', 'aviso');
    }
  }

  async function carregarGruposUg() {
    const sel = $('#emp-grupo-ug');
    if (!sel) return;
    const ano = $('#emp-ano')?.value || new Date().getFullYear();
    try {
      const resp = await fetch(`/api/sgp/grupos-ug?ano=${encodeURIComponent(ano)}`);
      if (!resp.ok) throw new Error('Falha ao listar grupos UG');
      const dados = await resp.json();
      const atual = sel.value || '86';
      sel.innerHTML = (dados.grupos || [])
        .map(
          (g) =>
            `<option value="${escapeHtml(g.codigo)}">${escapeHtml(g.codigo)} — ${escapeHtml(
              g.descricao
            )}</option>`
        )
        .join('');
      if ([...sel.options].some((o) => o.value === atual)) sel.value = atual;
      else if ([...sel.options].some((o) => o.value === '86')) sel.value = '86';
    } catch (err) {
      console.warn(err);
    }
  }

  function paramsNap() {
    const q = new URLSearchParams();
    const ano = $('#nap-ano')?.value;
    const di = $('#nap-inicio')?.value;
    const df = $('#nap-fim')?.value;
    const ug = $('#nap-ug')?.value?.trim();
    const fonte = $('#nap-fonte')?.value?.trim();
    const busca = $('#nap-busca')?.value?.trim();
    const qtd = $('#nap-qtd')?.value || '100';
    if (ano) q.set('ano', ano);
    if (di) q.set('data_inicial', di);
    if (df) q.set('data_final', df);
    if (ug) q.set('ug', ug);
    if (fonte) q.set('fonte', fonte);
    if (busca) q.set('busca', busca);
    q.set('quantidade', qtd);
    return q;
  }

  function paramsEmpenho() {
    const q = new URLSearchParams();
    const ano = $('#emp-ano')?.value;
    const di = $('#emp-inicio')?.value;
    const df = $('#emp-fim')?.value;
    const grupo = $('#emp-grupo-ug')?.value || '86';
    const fonte = $('#emp-fonte')?.value?.trim();
    const busca = $('#emp-busca')?.value?.trim();
    const qtd = $('#emp-qtd')?.value || '100';
    if (ano) q.set('ano', ano);
    if (di) q.set('data_inicial', di);
    if (df) q.set('data_final', df);
    q.set('cod_grupo_ug', grupo);
    if (fonte) q.set('fonte_recurso', fonte);
    if (busca) q.set('busca', busca);
    q.set('quantidade', qtd);
    return q;
  }

  function prefixo(tipo) {
    return tipo === 'nap' ? 'nap' : 'emp';
  }

  function renderAviso(tipo, meta) {
    const el = document.getElementById(`${prefixo(tipo)}-aviso`);
    if (!el) return;
    if (!meta?.aviso && !meta?.operacao) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.className = 'sgp-aviso' + (meta.aviso ? ' sgp-aviso--warn' : ' sgp-aviso--ok');
    const params = meta.params_enviados
      ? Object.entries(meta.params_enviados)
          .map(([k, v]) => `${k}=${v === '' ? '∅' : v}`)
          .join(' · ')
      : '';
    el.innerHTML = `
      <strong>${escapeHtml(meta.titulo || meta.operacao || '')}</strong>
      <span>${escapeHtml(meta.aviso || meta.descricao || 'Consulta SOAP SGP')}</span>
      <small>${escapeHtml(meta.operacao || '')} · ${meta.registros_soap ?? 0} registro(s) SOAP${
      params ? ' · ' + escapeHtml(params) : ''
    }</small>
    `;
  }

  function renderResumo(tipo, resumo) {
    const p = prefixo(tipo);
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val ?? '—';
    };
    set(`${p}-qtd-reg`, resumo?.quantidade ?? '—');
    set(`${p}-tot-bru`, resumo?.total_bruto_exibicao ?? '—');
    set(`${p}-tot-desc`, resumo?.total_desconto_exibicao ?? '—');
    set(`${p}-tot-liq`, resumo?.total_liquido_exibicao ?? '—');
  }

  function valorCelula(row, col) {
    if (col.moeda) {
      const key = `${col.chave}_exibicao`;
      return row[key] || row[col.chave] || '—';
    }
    return row[col.chave] || '—';
  }

  function renderTabela(tipo, dados) {
    const p = prefixo(tipo);
    const thead = document.getElementById(`${p}-thead`);
    const corpo = document.getElementById(`${p}-corpo`);
    const colunas = dados.colunas || [];
    estado.cache[tipo] = dados.lancamentos || [];

    thead.innerHTML = `<tr>${colunas
      .map((c) => `<th class="${c.moeda ? 'num' : ''}">${escapeHtml(c.rotulo)}</th>`)
      .join('')}<th></th></tr>`;

    const rows = dados.lancamentos || [];
    if (!rows.length) {
      corpo.innerHTML = `<tr><td colspan="${colunas.length + 1}" class="sgp-vazio">Nenhum registro encontrado.</td></tr>`;
      return;
    }

    corpo.innerHTML = rows
      .map((row, idx) => {
        const cells = colunas
          .map((c) => {
            const val = valorCelula(row, c);
            const cls = c.moeda ? 'num sgp-valor' : '';
            const extra = c.chave === 'nome_credor' || c.chave === 'desc_ug' || c.chave === 'desc_elemento_despesa'
              ? 'sgp-td-texto'
              : '';
            return `<td class="${cls} ${extra}">${escapeHtml(val)}</td>`;
          })
          .join('');
        return `<tr>${cells}<td class="sgp-td-acao"><button type="button" class="btn btn-fantasma btn-sm" data-tipo="${tipo}" data-idx="${idx}">Detalhe</button></td></tr>`;
      })
      .join('');
  }

  async function consultar(tipo) {
    const barra = $('#barra-carregando');
    if (barra) barra.classList.add('ativo');
    try {
      const q = tipo === 'nap' ? paramsNap() : paramsEmpenho();
      const resp = await fetch(`/api/sgp/consulta/${tipo}?${q.toString()}`);
      const dados = await resp.json();
      if (!resp.ok) throw new Error(dados.detail || 'Falha na consulta SGP');
      renderAviso(tipo, { ...dados.meta, titulo: dados.meta?.titulo });
      renderResumo(tipo, dados.resumo);
      renderTabela(tipo, dados);
    } catch (err) {
      console.error(err);
      notificar(err.message || 'Erro na consulta', 'erro');
      const p = prefixo(tipo);
      const corpo = document.getElementById(`${p}-corpo`);
      if (corpo) {
        corpo.innerHTML = `<tr><td class="sgp-vazio">${escapeHtml(err.message)}</td></tr>`;
      }
    } finally {
      if (barra) barra.classList.remove('ativo');
    }
  }

  function limpar(tipo) {
    if (tipo === 'nap') {
      ['nap-ug', 'nap-fonte', 'nap-busca'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      const q = $('#nap-qtd');
      if (q) q.value = '100';
    } else {
      ['emp-fonte', 'emp-busca'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      const q = $('#emp-qtd');
      if (q) q.value = '100';
      const g = $('#emp-grupo-ug');
      if (g && [...g.options].some((o) => o.value === '86')) g.value = '86';
    }
    preencherDatasPadrao();
  }

  function abrirDetalhe(tipo, idx) {
    const row = estado.cache[tipo]?.[idx];
    const modal = $('#sgp-modal');
    const corpo = $('#sgp-modal-corpo');
    if (!row || !modal || !corpo) return;
    const gloss = (estado.meta?.consultas || []).find((c) => c.id === tipo)?.glossario || [];
    const mapa = Object.fromEntries(gloss.map((g) => [g.campo, g.rotulo]));
    const keys = Object.keys(row).filter(
      (k) => !k.endsWith('_num') && !k.endsWith('_exibicao') && k !== 'id'
    );
    corpo.innerHTML = `
      <dl class="bb-dl">
        ${keys
          .map(
            (k) => `<div><dt>${escapeHtml(mapa[k] || k)}</dt><dd>${escapeHtml(row[k] || '—')}</dd></div>`
          )
          .join('')}
      </dl>
    `;
    modal.hidden = false;
    modal.classList.add('aberto');
  }

  function fecharModal() {
    const modal = $('#sgp-modal');
    if (!modal) return;
    modal.classList.remove('aberto');
    modal.hidden = true;
  }

  function init() {
    temaSync();
    preencherDatasPadrao();
    initAbas();

    $('#btn-tema')?.addEventListener('click', () => {
      const atual = document.documentElement.dataset.tema === 'escuro' ? 'claro' : 'escuro';
      document.documentElement.dataset.tema = atual;
      localStorage.setItem('fundeb-tema', atual);
      temaSync();
    });

    document.querySelectorAll('[data-consultar]').forEach((btn) => {
      btn.addEventListener('click', () => consultar(btn.getAttribute('data-consultar')));
    });
    document.querySelectorAll('[data-limpar]').forEach((btn) => {
      btn.addEventListener('click', () => limpar(btn.getAttribute('data-limpar')));
    });

    document.body.addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-tipo][data-idx]');
      if (btn) abrirDetalhe(btn.getAttribute('data-tipo'), Number(btn.getAttribute('data-idx')));
    });
    $('#sgp-modal-fechar')?.addEventListener('click', fecharModal);
    $('#sgp-modal')?.addEventListener('click', (ev) => {
      if (ev.target.id === 'sgp-modal') fecharModal();
    });

    ['nap-busca', 'emp-busca'].forEach((id) => {
      document.getElementById(id)?.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') {
          consultar(id.startsWith('nap') ? 'nap' : 'empenho');
        }
      });
    });

    $('#emp-ano')?.addEventListener('change', carregarGruposUg);

    carregarMeta()
      .then(carregarGruposUg)
      .catch((err) => notificar(err.message, 'erro'));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
