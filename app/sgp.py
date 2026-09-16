"""Camada SGP — consultas NAP e Pagamento por Empenho."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from . import sgp_client
from .config import get_base_dir
from .finance import format_currency, parse_number

OP_NAP = "getDadosRelacaoDiariaPagamentoNap"
OP_EMPENHO = "getDadosPagamentoPorEmpenho"

CONSULTAS: dict[str, dict[str, Any]] = {
    "nap": {
        "id": "nap",
        "operacao": OP_NAP,
        "titulo": "Relação diária de pagamento (NAP)",
        "descricao": "Pagamentos diários por NAP — OP, UG, fonte, credor e valores.",
        "colunas": [
            {"chave": "data_pagamento", "rotulo": "Data"},
            {"chave": "nap", "rotulo": "NAP"},
            {"chave": "op", "rotulo": "OP"},
            {"chave": "nome_credor", "rotulo": "Credor"},
            {"chave": "vr_liquido", "rotulo": "Líquido", "moeda": True},
            {"chave": "fonte_recurso", "rotulo": "Fonte"},
            {"chave": "ug", "rotulo": "UG"},
            {"chave": "desc_ug", "rotulo": "Descrição UG"},
        ],
        "glossario": [
            {"campo": "data_pagamento", "rotulo": "Data do pagamento", "explicacao": "Data em que o pagamento foi efetuado."},
            {"campo": "nap", "rotulo": "NAP", "explicacao": "Número da Nota de Autorização de Pagamento."},
            {"campo": "op", "rotulo": "OP", "explicacao": "Ordem de Pagamento vinculada."},
            {"campo": "processo", "rotulo": "Processo", "explicacao": "Número do processo administrativo."},
            {"campo": "nome_credor", "rotulo": "Nome do credor", "explicacao": "Favorecido do pagamento."},
            {"campo": "credor", "rotulo": "Código do credor", "explicacao": "Código interno do credor no SGP."},
            {"campo": "vr_bruto", "rotulo": "Valor bruto", "explicacao": "Valor antes de descontos."},
            {"campo": "vr_desconto", "rotulo": "Desconto", "explicacao": "Valor descontado (impostos, retenções etc.)."},
            {"campo": "vr_liquido", "rotulo": "Valor líquido", "explicacao": "Valor efetivamente pago."},
            {"campo": "fonte_recurso", "rotulo": "Fonte de recurso", "explicacao": "Código da fonte orçamentária."},
            {"campo": "ug", "rotulo": "UG", "explicacao": "Código da Unidade Gestora."},
            {"campo": "desc_ug", "rotulo": "Descrição da UG", "explicacao": "Nome da unidade gestora."},
            {"campo": "banco", "rotulo": "Banco", "explicacao": "Código do banco da conta pagadora."},
            {"campo": "agencia", "rotulo": "Agência", "explicacao": "Agência da conta pagadora."},
            {"campo": "conta_corrente", "rotulo": "Conta corrente", "explicacao": "Conta usada no pagamento."},
            {"campo": "tipo_doc", "rotulo": "Tipo documento", "explicacao": "Tipo do documento de pagamento (ex.: RB)."},
            {"campo": "desc_nat_despesa", "rotulo": "Natureza da despesa", "explicacao": "Classificação (orçamentária, restos etc.)."},
        ],
    },
    "empenho": {
        "id": "empenho",
        "operacao": OP_EMPENHO,
        "titulo": "Pagamento por empenho",
        "descricao": "Pagamentos vinculados a empenho — NAP, elemento de despesa e valores.",
        "colunas": [
            {"chave": "data_pagamento", "rotulo": "Data pag."},
            {"chave": "num_nap", "rotulo": "NAP"},
            {"chave": "num_empenho", "rotulo": "Empenho"},
            {"chave": "ano_empenho", "rotulo": "Ano emp."},
            {"chave": "nome_credor", "rotulo": "Credor"},
            {"chave": "vr_liquido", "rotulo": "Líquido", "moeda": True},
            {"chave": "fonte_recurso", "rotulo": "Fonte"},
            {"chave": "elemento_despesa", "rotulo": "Elemento"},
            {"chave": "desc_elemento_despesa", "rotulo": "Descrição elemento"},
        ],
        "glossario": [
            {"campo": "num_nap", "rotulo": "Nº NAP", "explicacao": "Número da NAP (sem o ano no sufixo)."},
            {"campo": "data_doc_nap", "rotulo": "Data documento NAP", "explicacao": "Data de emissão/documento da NAP."},
            {"campo": "num_empenho", "rotulo": "Nº empenho", "explicacao": "Número do empenho."},
            {"campo": "ano_empenho", "rotulo": "Ano do empenho", "explicacao": "Exercício do empenho."},
            {"campo": "data_pagamento", "rotulo": "Data do pagamento", "explicacao": "Data em que o valor foi pago."},
            {"campo": "fonte_recurso", "rotulo": "Fonte de recurso", "explicacao": "Código completo da fonte."},
            {"campo": "fonte_recurso_referencia", "rotulo": "Fonte referência", "explicacao": "Código resumido/referência da fonte."},
            {"campo": "nome_credor", "rotulo": "Credor", "explicacao": "Favorecido do pagamento."},
            {"campo": "vr_bruto", "rotulo": "Valor bruto", "explicacao": "Valor antes de descontos."},
            {"campo": "vr_desconto", "rotulo": "Desconto", "explicacao": "Retenções/descontos."},
            {"campo": "vr_liquido", "rotulo": "Valor líquido", "explicacao": "Valor pago."},
            {"campo": "elemento_despesa", "rotulo": "Elemento de despesa", "explicacao": "Código do elemento (ex.: 31901100)."},
            {"campo": "desc_elemento_despesa", "rotulo": "Descrição do elemento", "explicacao": "Nome do elemento de despesa."},
            {"campo": "codGrupoUg", "rotulo": "Grupo UG (filtro)", "explicacao": "Grupo de unidades gestoras no SOAP (ex.: 86 = Educação)."},
        ],
    },
}

# Catálogo legado (ainda usado por /api/sgp/operacoes).
OPERACOES_CRUZAMENTO: list[dict[str, str]] = [
    {
        "nome": OP_EMPENHO,
        "grupo": "despesa",
        "uso_previsto": "Pagamentos por empenho — cruzar débitos do extrato BB (NAP/OP/credor).",
    },
    {
        "nome": OP_NAP,
        "grupo": "despesa",
        "uso_previsto": "Relação diária de pagamento por NAP — alinhar com saídas do dia no BB.",
    },
]


def _catalogo_arquivo() -> Path:
    return Path(get_base_dir()) / "data" / "sgp_operacoes_cruzamento.json"


def garantir_catalogo_arquivo() -> Path:
    caminho = _catalogo_arquivo()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(OPERACOES_CRUZAMENTO, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return caminho


def catalogo_cruzamento() -> list[dict[str, str]]:
    caminho = garantir_catalogo_arquivo()
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(dados, list) and dados:
            return dados
    except (OSError, json.JSONDecodeError):
        pass
    return list(OPERACOES_CRUZAMENTO)


def status() -> dict[str, Any]:
    user, _pwd = sgp_client.get_sgp_credentials()
    wsdl = sgp_client.get_wsdl_url()
    info: dict[str, Any] = {
        "configurado": True,
        "wsdl_url": wsdl,
        "autenticacao": "basic" if user else "nenhuma (apenas WSDL público)",
        "usuario": user,
        "zeep_instalado": False,
        "wsdl_ok": False,
        "total_operacoes_wsdl": 0,
        "consultas": list(CONSULTAS.keys()),
        "mensagem": "",
    }
    try:
        import zeep  # noqa: F401

        info["zeep_instalado"] = True
    except ImportError:
        info["mensagem"] = "Instale zeep: pip install zeep requests"
        info["configurado"] = False
        return info

    try:
        meta = sgp_client.carregar_metadados_wsdl()
        info["wsdl_ok"] = True
        info["total_operacoes_wsdl"] = len(meta)
        info["mensagem"] = f"WSDL acessível — {len(meta)} operações disponíveis."
    except Exception as exc:
        info["mensagem"] = f"Não foi possível carregar o WSDL: {exc}"
        info["configurado"] = False
    return info


def listar_operacoes(*, apenas_cruzamento: bool = False) -> dict[str, Any]:
    cruzamento = catalogo_cruzamento()
    nomes = {item["nome"] for item in cruzamento}
    wsdl_ops: list[dict[str, Any]] = []
    erro = None
    try:
        meta = sgp_client.carregar_metadados_wsdl()
        for nome, info in sorted(meta.items()):
            if apenas_cruzamento and nome not in nomes:
                continue
            wsdl_ops.append(
                {
                    "name": nome,
                    "param_count": len(info.get("params") or []),
                    "signature": info.get("signature"),
                    "output": info.get("output"),
                    "candidata_cruzamento": nome in nomes,
                }
            )
    except Exception as exc:
        erro = str(exc)
        if apenas_cruzamento:
            wsdl_ops = [
                {
                    "name": item["nome"],
                    "param_count": None,
                    "signature": None,
                    "output": None,
                    "candidata_cruzamento": True,
                    "uso_previsto": item.get("uso_previsto"),
                    "grupo": item.get("grupo"),
                }
                for item in cruzamento
            ]
    return {
        "cruzamento": cruzamento,
        "operacoes": wsdl_ops,
        "total": len(wsdl_ops),
        "erro_wsdl": erro,
        "consultas": CONSULTAS,
    }


def detalhe_operacao(nome: str) -> Optional[dict[str, Any]]:
    cruz = next((c for c in catalogo_cruzamento() if c["nome"] == nome), None)
    try:
        meta = sgp_client.carregar_metadados_wsdl().get(nome)
    except Exception:
        meta = None
    if not meta and not cruz:
        return None
    return {
        "name": nome,
        "params": (meta or {}).get("params") or [],
        "signature": (meta or {}).get("signature"),
        "output": (meta or {}).get("output"),
        "cruzamento": cruz,
        "wsdl_disponivel": meta is not None,
    }


def invocar_operacao(
    nome: str,
    params: dict[str, Any],
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: int = 60,
) -> dict[str, Any]:
    resultado = sgp_client.invocar(
        nome,
        params,
        username=username,
        password=password,
        timeout=timeout,
    )
    return {"operation": nome, "params": params, "result": resultado}


# ------------------------------------------------------------------
# Consultas normalizadas (UI)
# ------------------------------------------------------------------


def data_iso_para_sgp(valor: str | date | None) -> str:
    """Converte YYYY-MM-DD (ou date) para DD/MM/YYYY exigido pelo SGP."""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor).strip()
    if re.match(r"^\d{2}/\d{2}/\d{4}$", texto):
        return texto
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return texto


def extrair_registros(json_object: Any) -> list[dict[str, Any]]:
    """Extrai lista de registros de <dados><key_N>...</key_N></dados>."""
    if not json_object or not isinstance(json_object, dict):
        return []

    # raiz: { Operacao: { dados: { key_0: {...}, ... }, mensagens?: ... } }
    raiz = next(iter(json_object.values())) if len(json_object) == 1 else json_object
    if not isinstance(raiz, dict):
        return []

    dados = raiz.get("dados")
    if dados is None:
        return []
    if isinstance(dados, dict):
        itens = []
        for chave, valor in dados.items():
            if isinstance(valor, dict):
                itens.append(valor)
            elif chave == "#text":
                continue
        # ordena key_0, key_1, ...
        def ordem(item_chave: tuple[str, Any]) -> tuple:
            k = item_chave[0]
            m = re.search(r"(\d+)$", k)
            return (0, int(m.group(1))) if m else (1, k)

        ordenados = sorted(
            ((k, v) for k, v in dados.items() if isinstance(v, dict)),
            key=ordem,
        )
        return [v for _, v in ordenados]
    if isinstance(dados, list):
        return [x for x in dados if isinstance(x, dict)]
    return []


def _fmt_moeda_br(texto: Any) -> str:
    valor = parse_number(texto)
    return format_currency(valor)


def normalizar_linha(row: dict[str, Any], *, origem: str, indice: int) -> dict[str, Any]:
    limpo = {str(k): ("" if v is None else str(v).strip()) for k, v in row.items()}
    liquido = parse_number(limpo.get("vr_liquido"))
    bruto = parse_number(limpo.get("vr_bruto"))
    desconto = parse_number(limpo.get("vr_desconto"))
    return {
        "id": f"{origem}-{indice}",
        **limpo,
        "vr_liquido_num": liquido,
        "vr_bruto_num": bruto,
        "vr_desconto_num": desconto,
        "vr_liquido_exibicao": _fmt_moeda_br(limpo.get("vr_liquido")),
        "vr_bruto_exibicao": _fmt_moeda_br(limpo.get("vr_bruto")),
        "vr_desconto_exibicao": _fmt_moeda_br(limpo.get("vr_desconto")),
    }


def filtrar_linhas(
    linhas: list[dict],
    *,
    busca: Optional[str] = None,
    ug: Optional[str] = None,
    fonte: Optional[str] = None,
    credor: Optional[str] = None,
) -> list[dict]:
    busca_n = (busca or "").strip().casefold()
    ug_n = (ug or "").strip()
    fonte_n = (fonte or "").strip()
    credor_n = (credor or "").strip().casefold()

    saida = []
    for row in linhas:
        if ug_n and str(row.get("ug") or "").strip() != ug_n:
            continue
        if fonte_n and fonte_n not in str(row.get("fonte_recurso") or ""):
            continue
        if credor_n:
            nome = str(row.get("nome_credor") or "").casefold()
            cod = str(row.get("credor") or "").casefold()
            if credor_n not in nome and credor_n not in cod:
                continue
        if busca_n:
            blob = " ".join(str(v) for v in row.values()).casefold()
            if busca_n not in blob:
                continue
        saida.append(row)
    return saida


def resumir_linhas(linhas: list[dict]) -> dict[str, Any]:
    total_liq = sum(float(r.get("vr_liquido_num") or 0) for r in linhas)
    total_bru = sum(float(r.get("vr_bruto_num") or 0) for r in linhas)
    total_desc = sum(float(r.get("vr_desconto_num") or 0) for r in linhas)
    return {
        "quantidade": len(linhas),
        "total_liquido": total_liq,
        "total_bruto": total_bru,
        "total_desconto": total_desc,
        "total_liquido_exibicao": format_currency(total_liq),
        "total_bruto_exibicao": format_currency(total_bru),
        "total_desconto_exibicao": format_currency(total_desc),
    }


def listar_grupos_ug(ano: int | str) -> list[dict[str, str]]:
    resultado = sgp_client.invocar("getListaGrupoUg", {"ano": str(ano)})
    rows = extrair_registros(resultado.get("json_object"))
    grupos = []
    for row in rows:
        codigo = str(row.get("gug_codigo") or "").strip()
        desc = str(row.get("gug_descricao") or "").strip()
        if codigo:
            grupos.append({"codigo": codigo, "descricao": desc})
    grupos.sort(key=lambda g: g["descricao"].casefold())
    return grupos


def consultar(
    tipo: str,
    *,
    ano: Optional[int] = None,
    data_inicial: Optional[str] = None,
    data_final: Optional[str] = None,
    registro_inicial: int = 0,
    quantidade: int = 100,
    filtro_opcional: str = "",
    cod_grupo_ug: int = 86,
    fonte_recurso: str = "",
    busca: Optional[str] = None,
    ug: Optional[str] = None,
    fonte: Optional[str] = None,
    credor: Optional[str] = None,
) -> dict[str, Any]:
    cfg = CONSULTAS.get(tipo)
    if not cfg:
        raise sgp_client.SgpError(f"Consulta desconhecida: {tipo}. Use: {', '.join(CONSULTAS)}")

    hoje = date.today()
    ano_n = int(ano or hoje.year)
    di = data_iso_para_sgp(data_inicial) or hoje.replace(day=1).strftime("%d/%m/%Y")
    df = data_iso_para_sgp(data_final) or hoje.strftime("%d/%m/%Y")
    qtd = max(1, min(500, int(quantidade or 100)))
    reg = max(0, int(registro_inicial or 0))

    if tipo == "nap":
        params = {
            "ano": str(ano_n),
            "dataInicial": di,
            "dataFinal": df,
            "registroInicialRetorno": str(reg),
            "quantidadeRegistroRetornados": str(qtd),
            "filtroOpcional": filtro_opcional if filtro_opcional is not None else "",
        }
    else:
        params = {
            "ano": ano_n,
            "dataInicial": di,
            "dataFinal": df,
            "codGrupoUg": int(cod_grupo_ug),
            "fonteRecurso": fonte_recurso if fonte_recurso is not None else "",
            "registroInicialRetorno": reg,
            "quantidadeRegistroRetornados": qtd,
            "filtroOpcional": filtro_opcional if filtro_opcional is not None else "",
        }

    bruto = sgp_client.invocar(cfg["operacao"], params)
    registros = extrair_registros(bruto.get("json_object"))
    linhas = [
        normalizar_linha(row, origem=tipo, indice=i) for i, row in enumerate(registros)
    ]
    filtradas = filtrar_linhas(linhas, busca=busca, ug=ug, fonte=fonte or fonte_recurso, credor=credor)

    return {
        "tipo": tipo,
        "meta": {
            "operacao": cfg["operacao"],
            "titulo": cfg["titulo"],
            "descricao": cfg["descricao"],
            "params_enviados": params,
            "registros_soap": len(linhas),
            "aviso": None
            if linhas
            else "Nenhum registro retornado pelo SGP para estes parâmetros.",
        },
        "colunas": cfg["colunas"],
        "glossario": cfg["glossario"],
        "resumo": resumir_linhas(filtradas),
        "filtros": {
            "ano": ano_n,
            "data_inicial": di,
            "data_final": df,
            "registro_inicial": reg,
            "quantidade": qtd,
            "cod_grupo_ug": int(cod_grupo_ug) if tipo == "empenho" else None,
            "fonte_recurso": fonte_recurso or None,
            "busca": busca or None,
            "ug": ug or None,
            "fonte": fonte or None,
            "credor": credor or None,
        },
        "lancamentos": filtradas,
        "mensagens": _extrair_mensagens(bruto.get("json_object")),
    }


def _extrair_mensagens(json_object: Any) -> list[str]:
    if not isinstance(json_object, dict):
        return []
    raiz = next(iter(json_object.values())) if len(json_object) == 1 else json_object
    if not isinstance(raiz, dict):
        return []
    msg = raiz.get("mensagens")
    if not msg:
        return []
    if isinstance(msg, str) and msg.strip():
        return [msg.strip()]
    if isinstance(msg, dict):
        return [str(v).strip() for v in msg.values() if str(v).strip()]
    return []


def meta_ui() -> dict[str, Any]:
    return {
        "consultas": [
            {
                "id": c["id"],
                "operacao": c["operacao"],
                "titulo": c["titulo"],
                "descricao": c["descricao"],
                "colunas": c["colunas"],
                "glossario": c["glossario"],
            }
            for c in CONSULTAS.values()
        ],
        "status": status(),
    }
