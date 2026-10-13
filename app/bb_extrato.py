"""Consulta visual do Extrato BB (API Extratos).

Modo controlado por BB_MODO no .env:
  - sandbox  → JSON locais em exports/
  - producao → API real (datas vêm do filtro da UI, não do .env)
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from .bb_client import BbClientError, buscar_extrato, listar_contas_configuradas
from .config import get_exports_dir
from .finance import format_currency, parse_number

# Arquivos locais usados no modo sandbox.
ARQUIVOS_SANDBOX = (
    "bb_extrato_sandbox.json",
    "bb_extrato_sandbox_p2.json",
)

# Cache da última carga (detalhe /api/bb-extrato/{id}).
_cache_lancamentos: list[dict] = []


def get_modo() -> str:
    raw = (os.environ.get("BB_MODO") or "").strip().lower()
    if raw in {"producao", "produção", "prod", "production"}:
        return "producao"
    if raw in {"sandbox", "teste", "homolog", "homologacao", "homologação"}:
        return "sandbox"
    # Auto: se houver credenciais + cert, assume produção.
    if (os.environ.get("BB_CLIENT_ID") or "").strip() and (os.environ.get("BB_CERT_FILE") or "").strip():
        return "producao"
    return "sandbox"


MODO_ATUAL = get_modo()  # valor inicial; consultar() relê via get_modo()

GLOSSARIO: list[dict[str, str]] = [
    {
        "campo": "dataLancamento",
        "rotulo": "Data do lançamento",
        "explicacao": "Data contábil do movimento no extrato (formato BB: DDMMAAAA).",
    },
    {
        "campo": "dataMovimento",
        "rotulo": "Data do movimento",
        "explicacao": "Data em que o valor efetivamente movimentou. Pode vir 0 quando não informada.",
    },
    {
        "campo": "indicadorSinalLancamento",
        "rotulo": "Sinal (C/D)",
        "explicacao": "C = crédito (entrada). D = débito (saída).",
    },
    {
        "campo": "indicadorTipoLancamento",
        "rotulo": "Tipo de lançamento",
        "explicacao": "Classificação do registro na API. Valores comuns: 1 = movimento; SA = saldo atual; linhas de saldo do dia aparecem no histórico.",
    },
    {
        "campo": "valorLancamento",
        "rotulo": "Valor",
        "explicacao": "Valor do lançamento em reais. O sinal C/D define se é entrada ou saída.",
    },
    {
        "campo": "textoDescricaoSubHistorico",
        "rotulo": "Histórico",
        "explicacao": "Descrição do tipo de operação (ex.: Folha de Pagamento, DRC-CREDITO, Saldo do dia).",
    },
    {
        "campo": "textoInformacaoComplementar",
        "rotulo": "Informação complementar",
        "explicacao": "Texto extra do banco sobre o lançamento, quando houver.",
    },
    {
        "campo": "codigoHistorico",
        "rotulo": "Código histórico",
        "explicacao": "Código interno BB do histórico contábil.",
    },
    {
        "campo": "codigoSubHistorico",
        "rotulo": "Código subhistórico",
        "explicacao": "Detalhamento do histórico (subcódigo BB).",
    },
    {
        "campo": "numeroDocumento",
        "rotulo": "Nº documento",
        "explicacao": "Número do documento associado ao lançamento.",
    },
    {
        "campo": "numeroLote",
        "rotulo": "Nº lote",
        "explicacao": "Lote de processamento do banco.",
    },
    {
        "campo": "textoIdentificadorUnicoTransacao",
        "rotulo": "ID único da transação",
        "explicacao": "Identificador único do movimento (útil para conciliação e evitar duplicidade).",
    },
    {
        "campo": "codigoAgenciaOrigem",
        "rotulo": "Agência origem",
        "explicacao": "Agência de origem do lançamento, quando informada.",
    },
    {
        "campo": "numeroCadastroPessoaFisicaCadastroNacPessoasJuridicasContrapartida",
        "rotulo": "CPF/CNPJ contraparte",
        "explicacao": "Documento da contraparte da operação, se o banco enviar.",
    },
    {
        "campo": "codigoBancoContrapartida",
        "rotulo": "Banco contraparte",
        "explicacao": "Código do banco da contraparte.",
    },
    {
        "campo": "codigoAgenciaContrapartida",
        "rotulo": "Agência contraparte",
        "explicacao": "Agência da conta da contraparte.",
    },
    {
        "campo": "numeroContaContrapartida",
        "rotulo": "Conta contraparte",
        "explicacao": "Número da conta da contraparte (pode vir zerado no sandbox).",
    },
    {
        "campo": "textoDigitoVerificadorContaContrapartida",
        "rotulo": "Dígito conta contraparte",
        "explicacao": "DV da conta da contraparte.",
    },
    {
        "campo": "indicadorTipoPessoaContrapartida",
        "rotulo": "Tipo pessoa contraparte",
        "explicacao": "F = física, J = jurídica (quando informado).",
    },
    {
        "campo": "codigoIdentificadorSisPgtoBrl",
        "rotulo": "ID sistema de pagamentos",
        "explicacao": "Identificador em sistemas de pagamento (ex.: PIX/STR), quando houver.",
    },
    {
        "campo": "codigoConfederacaoNacionalBancos",
        "rotulo": "Código Febraban/CNAB",
        "explicacao": "Código relacionado a padrões bancários nacionais, quando preenchido.",
    },
    {
        "campo": "textoCampoIndeterminado",
        "rotulo": "Campo complementar BB",
        "explicacao": "Campo livre/reservado da API — conteúdo varia conforme o produto.",
    },
]


def _parse_data_bb(valor: Any) -> Optional[date]:
    """Converte data BB (int/str DDMMAAAA, com ou sem zero à esquerda) em date."""
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", str(valor))
    if not digitos or digitos == "0":
        return None
    digitos = digitos.zfill(8)
    if len(digitos) != 8:
        return None
    try:
        return datetime.strptime(digitos, "%d%m%Y").date()
    except ValueError:
        return None


def _eh_linha_saldo(item: dict) -> bool:
    tipo = str(item.get("indicadorTipoLancamento") or "").strip().upper()
    hist = str(item.get("textoDescricaoSubHistorico") or "").strip().upper()
    if tipo in {"SA", "RA"}:
        return True
    return hist in {"SALDO ANTERIOR", "SALDO DO DIA", "SALDO ATUAL", "SALDO FINAL"}


def normalizar_lancamento(
    item: dict,
    *,
    origem: str,
    indice: int,
    agencia: str | None = None,
    conta: str | None = None,
) -> dict:
    data_lanc = _parse_data_bb(item.get("dataLancamento"))
    data_mov = _parse_data_bb(item.get("dataMovimento"))
    sinal = str(item.get("indicadorSinalLancamento") or "").strip().upper() or "?"
    valor = abs(parse_number(item.get("valorLancamento")))
    valor_assinado = valor if sinal == "C" else (-valor if sinal == "D" else valor)
    historico = str(item.get("textoDescricaoSubHistorico") or "").strip()
    complemento = str(item.get("textoInformacaoComplementar") or "").strip()
    eh_saldo = _eh_linha_saldo(item)
    ag = str(agencia or item.get("_agencia") or "").strip()
    ct = str(conta or item.get("_conta") or "").strip()
    conta_id = f"{ag}:{ct}" if ag and ct else ""

    return {
        "id": f"{origem}-{indice}" if not conta_id else f"{origem}-{ag}-{ct}-{indice}",
        "data": data_lanc.isoformat() if data_lanc else None,
        "data_exibicao": data_lanc.strftime("%d/%m/%Y") if data_lanc else "—",
        "data_movimento": data_mov.isoformat() if data_mov else None,
        "data_movimento_exibicao": data_mov.strftime("%d/%m/%Y") if data_mov else "—",
        "sinal": sinal,
        "sinal_rotulo": "Crédito" if sinal == "C" else ("Débito" if sinal == "D" else sinal),
        "tipo_lancamento": str(item.get("indicadorTipoLancamento") or "").strip(),
        "eh_saldo": eh_saldo,
        "valor": valor,
        "valor_assinado": valor_assinado,
        "valor_exibicao": format_currency(valor),
        "historico": historico or "—",
        "complemento": complemento,
        "codigo_historico": item.get("codigoHistorico") or 0,
        "codigo_subhistorico": item.get("codigoSubHistorico") or 0,
        "numero_documento": str(item.get("numeroDocumento") or "").strip() or "—",
        "numero_lote": str(item.get("numeroLote") or "").strip() or "—",
        "id_transacao": str(item.get("textoIdentificadorUnicoTransacao") or "").strip(),
        "agencia_origem": item.get("codigoAgenciaOrigem") or 0,
        "agencia": ag,
        "conta": ct,
        "conta_id": conta_id,
        "conta_exibicao": f"{ag}/{ct}" if ag and ct else "—",
        "cpf_cnpj_contraparte": str(
            item.get("numeroCadastroPessoaFisicaCadastroNacPessoasJuridicasContrapartida") or ""
        ).strip(),
        "banco_contraparte": item.get("codigoBancoContrapartida") or 0,
        "agencia_contraparte": item.get("codigoAgenciaContrapartida") or 0,
        "conta_contraparte": str(item.get("numeroContaContrapartida") or "").strip(),
        "bruto": item,
    }


def _carregar_json(caminho: Path) -> dict:
    with caminho.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def carregar_lancamentos_sandbox() -> tuple[list[dict], dict]:
    """Une as páginas exportadas do sandbox e devolve (lançamentos, meta)."""
    pasta = Path(get_exports_dir())
    lancamentos: list[dict] = []
    arquivos_usados: list[str] = []
    meta_paginas: list[dict] = []

    for nome in ARQUIVOS_SANDBOX:
        caminho = pasta / nome
        if not caminho.exists():
            continue
        dados = _carregar_json(caminho)
        arquivos_usados.append(nome)
        meta_paginas.append(
            {
                "arquivo": nome,
                "pagina": dados.get("numeroPaginaAtual"),
                "registros_pagina": dados.get("quantidadeRegistroPaginaAtual"),
                "total_paginas": dados.get("quantidadeTotalPagina"),
                "total_registros_api": dados.get("quantidadeTotalRegistro"),
            }
        )
        for idx, item in enumerate(dados.get("listaLancamento") or []):
            if not isinstance(item, dict):
                continue
            lancamentos.append(normalizar_lancamento(item, origem=nome, indice=idx))

    # Ordena por data e mantém ordem estável do arquivo.
    def chave(row: dict) -> tuple:
        return (row.get("data") or "9999-99-99", row["id"])

    lancamentos.sort(key=chave)

    meta = {
        "modo": MODO_ATUAL,
        "fonte": "arquivo_local",
        "arquivos": arquivos_usados,
        "paginas": meta_paginas,
        "total_carregado": len(lancamentos),
        "aviso": (
            "Exibindo extrato de HOMOLOGAÇÃO (sandbox). "
            "Os valores são fictícios até a aplicação BB ir para produção."
        ),
        "producao_pronta": False,
    }
    return lancamentos, meta


def listar_historicos(lancamentos: list[dict]) -> list[str]:
    valores = sorted(
        {
            str(row.get("historico") or "").strip()
            for row in lancamentos
            if str(row.get("historico") or "").strip() and str(row.get("historico")) != "—"
        },
        key=lambda s: s.casefold(),
    )
    return valores


def filtrar_lancamentos(
    lancamentos: list[dict],
    *,
    inicio: Optional[date] = None,
    fim: Optional[date] = None,
    sinal: Optional[str] = None,
    historico: Optional[str] = None,
    busca: Optional[str] = None,
    conta_id: Optional[str] = None,
    incluir_saldos: bool = False,
) -> list[dict]:
    sinal_n = (sinal or "").strip().upper() or None
    if sinal_n and sinal_n not in {"C", "D"}:
        sinal_n = None
    hist_n = (historico or "").strip()
    busca_n = (busca or "").strip().casefold()
    conta_n = (conta_id or "").strip()

    saida: list[dict] = []
    for row in lancamentos:
        if not incluir_saldos and row.get("eh_saldo"):
            continue
        data_row = row.get("data")
        if inicio and data_row and data_row < inicio.isoformat():
            continue
        if fim and data_row and data_row > fim.isoformat():
            continue
        if inicio and not data_row:
            continue
        if fim and not data_row:
            continue
        if sinal_n and row.get("sinal") != sinal_n:
            continue
        if hist_n and str(row.get("historico") or "") != hist_n:
            continue
        if conta_n and str(row.get("conta_id") or "") != conta_n:
            continue
        if busca_n:
            blob = " ".join(
                [
                    str(row.get("historico") or ""),
                    str(row.get("complemento") or ""),
                    str(row.get("numero_documento") or ""),
                    str(row.get("id_transacao") or ""),
                    str(row.get("cpf_cnpj_contraparte") or ""),
                    str(row.get("conta_exibicao") or ""),
                ]
            ).casefold()
            if busca_n not in blob:
                continue
        saida.append(row)
    return saida


def resumir(lancamentos: list[dict]) -> dict:
    creditos = [r for r in lancamentos if r.get("sinal") == "C" and not r.get("eh_saldo")]
    debitos = [r for r in lancamentos if r.get("sinal") == "D" and not r.get("eh_saldo")]
    total_c = sum(float(r.get("valor") or 0) for r in creditos)
    total_d = sum(float(r.get("valor") or 0) for r in debitos)
    return {
        "quantidade": len(lancamentos),
        "creditos": len(creditos),
        "debitos": len(debitos),
        "saldos": sum(1 for r in lancamentos if r.get("eh_saldo")),
        "total_creditos": total_c,
        "total_debitos": total_d,
        "resultado": total_c - total_d,
        "total_creditos_exibicao": format_currency(total_c),
        "total_debitos_exibicao": format_currency(total_d),
        "resultado_exibicao": format_currency(total_c - total_d),
    }


def carregar_lancamentos_producao(
    *,
    inicio: Optional[date],
    fim: Optional[date],
    conta_id: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """Chama a API BB; datas obrigatórias (filtro da UI)."""
    if not inicio or not fim:
        return [], {
            "modo": "producao",
            "fonte": "api_bb",
            "arquivos": [],
            "paginas": [],
            "total_carregado": 0,
            "aviso": (
                "Selecione a data inicial e final no filtro para consultar o extrato real do BB."
            ),
            "producao_pronta": True,
            "erro": False,
            "precisa_periodo": True,
        }

    brutos, meta_api = buscar_extrato(inicio=inicio, fim=fim, conta_id=conta_id)
    lancamentos: list[dict] = []
    for idx, item in enumerate(brutos):
        origem = f"api-{meta_api.get('ambiente', 'bb')}"
        lancamentos.append(
            normalizar_lancamento(
                item,
                origem=origem,
                indice=idx,
                agencia=str(item.get("_agencia") or ""),
                conta=str(item.get("_conta") or ""),
            )
        )

    def chave(row: dict) -> tuple:
        return (row.get("data") or "9999-99-99", row.get("conta_id") or "", row["id"])

    lancamentos.sort(key=chave)

    contas = meta_api.get("contas") or []
    contas_txt = ", ".join(f"{c.get('agencia')}/{c.get('conta')}" for c in contas) or "—"
    meta = {
        "modo": "producao",
        "fonte": "api_bb",
        "arquivos": [f"BB {contas_txt}", str(meta_api.get("base_url") or "")],
        "paginas": meta_api.get("paginas") or [],
        "total_carregado": len(lancamentos),
        "aviso": (
            f"Extrato real do Banco do Brasil ({meta_api.get('ambiente', 'producao')}). "
            f"Período {inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')} · conta(s) {contas_txt}."
        ),
        "producao_pronta": True,
        "erro": False,
        "api": meta_api,
    }
    return lancamentos, meta


def consultar(
    *,
    inicio: Optional[date] = None,
    fim: Optional[date] = None,
    sinal: Optional[str] = None,
    historico: Optional[str] = None,
    busca: Optional[str] = None,
    conta_id: Optional[str] = None,
    incluir_saldos: bool = False,
    pagina: int = 1,
    por_pagina: int = 50,
) -> dict:
    global _cache_lancamentos, MODO_ATUAL
    modo = get_modo()
    MODO_ATUAL = modo
    contas_disponiveis = listar_contas_configuradas()

    if modo == "producao":
        try:
            todos, meta = carregar_lancamentos_producao(
                inicio=inicio, fim=fim, conta_id=conta_id
            )
        except BbClientError as exc:
            todos, meta = [], {
                "modo": "producao",
                "fonte": "api_bb",
                "arquivos": [],
                "paginas": [],
                "total_carregado": 0,
                "aviso": f"Falha ao consultar a API do BB: {exc}",
                "producao_pronta": True,
                "erro": True,
            }
    else:
        todos, meta = carregar_lancamentos_sandbox()

    _cache_lancamentos = list(todos)

    # Em produção período/conta já vieram da API; em sandbox filtramos localmente.
    filtrados = filtrar_lancamentos(
        todos,
        inicio=None if modo == "producao" else inicio,
        fim=None if modo == "producao" else fim,
        sinal=sinal,
        historico=historico,
        busca=busca,
        conta_id=None if modo == "producao" else conta_id,
        incluir_saldos=incluir_saldos,
    )

    pagina = max(1, int(pagina or 1))
    por_pagina = min(200, max(10, int(por_pagina or 50)))
    total = len(filtrados)
    total_paginas = max(1, (total + por_pagina - 1) // por_pagina) if total else 1
    if pagina > total_paginas:
        pagina = total_paginas
    inicio_idx = (pagina - 1) * por_pagina
    fatia = filtrados[inicio_idx : inicio_idx + por_pagina]

    itens = []
    for row in fatia:
        item = dict(row)
        item.pop("bruto", None)
        itens.append(item)

    return {
        "meta": meta,
        "resumo": resumir(filtrados),
        "filtros": {
            "inicio": inicio.isoformat() if inicio else None,
            "fim": fim.isoformat() if fim else None,
            "sinal": (sinal or "").upper() or None,
            "historico": historico or None,
            "busca": busca or None,
            "conta": conta_id or None,
            "incluir_saldos": bool(incluir_saldos),
        },
        "contas": contas_disponiveis,
        "historicos": listar_historicos(todos),
        "paginacao": {
            "pagina": pagina,
            "por_pagina": por_pagina,
            "total": total,
            "total_paginas": total_paginas,
        },
        "lancamentos": itens,
        "glossario": GLOSSARIO,
    }


def obter_detalhe(item_id: str) -> Optional[dict]:
    for row in _cache_lancamentos:
        if row.get("id") == item_id:
            return row
    # Fallback sandbox se cache vazio (ex.: refresh direto no detalhe).
    if get_modo() != "producao":
        todos, _meta = carregar_lancamentos_sandbox()
        for row in todos:
            if row.get("id") == item_id:
                return row
    return None
