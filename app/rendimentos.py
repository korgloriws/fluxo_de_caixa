"""Rendimento dos fundos do FUNDEB.

O overnight fica no Invest. Resgate Automático / BB RF. A variação bruta
desses saldos mistura rendimento com aplicação/resgate de principal
(imposto que “dorme” no fundo, resgate para pagar folha, etc.).

Conferência:
  1) variação por fundo e taxa % ao dia;
  2) se a taxa/dia passar de ~0,15% (acima de RF típico), o excesso é
     tratado como aplicação/resgate, não overnight;
  3) a taxa de referência é a do BB RF CP (quando razoável), senão 0,05%/dia.

Assim dá para ver fundos aplicados, taxa e separar o que é rendimento.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .finance import clean_text, parse_number
from .repository import connect

FUNDO_SD = "BB RF SD Diferenciado"
FUNDO_CP = "BB RF CP Automatico"

# Teto de taxa/dia para RF DI (~0,15%). Acima disso quase sempre é aporte/resgate.
TAXA_MAX_DIA = 0.0015
# Fallback ~CDI/Selic na casa de 0,05%/dia útil quando não há CP confiável.
TAXA_REF_DIA_PADRAO = 0.0005

RE_SALDO_FECHAMENTO = re.compile(
    r"^(\d{2}/\d{2}/\d{4}).*00000999.*S\s*A\s*L\s*D\s*O.*?([\d.]+,\d{2})",
    re.IGNORECASE,
)
RE_INVEST_AUTO = re.compile(
    r"Invest\.?\s*Resgate\s*Autom\.?\s*([\d.]+,\d{2})",
    re.IGNORECASE,
)
RE_SALDO_TOTAL = re.compile(
    r"^Saldo\s+([\d.]+,\d{2})",
    re.IGNORECASE,
)
RE_CABECALHO_FUNDOS = re.compile(
    r"Saldo\s*de\s*fundos\s*de\s*investimento",
    re.IGNORECASE,
)
RE_FUNDO = re.compile(
    r"^(BB\s*RF\s*.+?)\s+([\d.]+,\d{2})\s*[CD]?\s*$",
    re.IGNORECASE,
)


def _parse_data_br(texto: str) -> Optional[date]:
    try:
        return datetime.strptime(texto, "%d/%m/%Y").date()
    except ValueError:
        return None


def normalizar_nome_fundo(nome: str) -> str:
    bruto = re.sub(r"\s+", " ", str(nome or "")).strip().upper()
    bruto = bruto.replace(".", "")
    colado = re.sub(r"\s+", "", bruto)
    if "CP" in colado and "AUTOM" in colado:
        return FUNDO_CP
    if "SD" in colado and "DIFERENC" in colado:
        return FUNDO_SD
    return re.sub(r"\s+", " ", str(nome or "")).strip() or "FUNDO"


def extrair_snapshot_extrato(linhas: list[str]) -> Optional[dict]:
    """Lê o rodapé do extrato: CC, resgate automático e fundos."""
    if not linhas:
        return None

    data_ref: Optional[date] = None
    saldo_cc = None
    invest_auto = None
    saldo_total = None
    fundos: dict[str, float] = {}
    lendo_fundos = False

    for linha in linhas:
        texto = str(linha or "").strip()
        if not texto:
            continue

        fecha = RE_SALDO_FECHAMENTO.search(texto)
        if fecha:
            data_ref = _parse_data_br(fecha.group(1))
            saldo_cc = parse_number(fecha.group(2))
            lendo_fundos = False
            continue

        invest = RE_INVEST_AUTO.search(texto)
        if invest:
            invest_auto = parse_number(invest.group(1))
            continue

        if RE_CABECALHO_FUNDOS.search(texto):
            lendo_fundos = True
            continue

        if lendo_fundos:
            if texto.startswith("---") or texto.startswith("***") or texto.upper().startswith("OBS"):
                lendo_fundos = False
                continue
            if texto.lower().startswith("transacao") or texto.lower().startswith("transação"):
                lendo_fundos = False
                continue
            fundo = RE_FUNDO.match(texto)
            if fundo:
                nome = normalizar_nome_fundo(fundo.group(1))
                fundos[nome] = parse_number(fundo.group(2))
                continue
            # OCR cola o nome (BBRFSDDiferenciad 22.170.073,50)
            dinheiro = re.search(r"([\d.]+,\d{2})\s*[CD]?\s*$", texto)
            if dinheiro and re.search(r"BB\s*RF|BBRF", texto, re.IGNORECASE):
                nome = normalizar_nome_fundo(re.sub(r"[\d.,\sCD]+$", "", texto))
                fundos[nome] = parse_number(dinheiro.group(1))
            continue

        if invest_auto is not None and saldo_total is None:
            total = RE_SALDO_TOTAL.match(texto)
            if total:
                saldo_total = parse_number(total.group(1))

    if data_ref is None and invest_auto is None and not fundos:
        return None

    if saldo_total is None:
        saldo_total = (saldo_cc or 0.0) + (invest_auto or 0.0)

    return {
        "data": data_ref,
        "saldo_cc": float(saldo_cc or 0.0),
        "invest_resgate_auto": float(invest_auto or 0.0),
        "saldo_total": float(saldo_total or 0.0),
        "fundos": fundos,
    }


def patrimonio_fundos(snapshot: dict) -> float:
    """Só o aplicado: resgate automático + fundos extras (CP), sem CC nem SD duplicado."""
    if not snapshot:
        return 0.0
    auto = float(snapshot.get("invest_resgate_auto") or 0.0)
    extra = 0.0
    for nome, valor in (snapshot.get("fundos") or {}).items():
        if normalizar_nome_fundo(nome) == FUNDO_SD:
            continue
        extra += float(valor or 0.0)
    if auto == 0:
        extra = sum(float(v or 0.0) for v in (snapshot.get("fundos") or {}).values())
    return round(auto + extra, 2)


def patrimonio(snapshot: dict) -> float:
    """CC + fundos (uso geral). Para rendimento do FUNDEB preferir patrimonio_fundos."""
    cc = float(snapshot.get("saldo_cc") or 0.0)
    return round(cc + patrimonio_fundos(snapshot), 2)


RE_TRANSFERENCIA_FUNDO = re.compile(
    r"\b(resgate|aplica[cç][aã]o|aplicacao)\b|"
    r"resgate\s+fundo|fundo\s+para\s+cobrir|"
    r"aplica[cç][aã]o\s+em\s+fundo|aplicacao\s+em\s+fundo",
    re.IGNORECASE,
)
RE_RESGATE = re.compile(r"resgate|fundo\s+para\s+cobrir", re.IGNORECASE)
RE_APLICACAO = re.compile(r"aplica[cç][aã]o|aplicacao", re.IGNORECASE)


def _as_date(valor) -> Optional[date]:
    if isinstance(valor, date):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, str) and valor:
        try:
            return date.fromisoformat(valor[:10])
        except ValueError:
            return None
    return None


def movimento_entra_no_rendimento(mov: dict) -> bool:
    """True se o lançamento é crédito/despesa operacional da conferência."""
    if mov.get("ajuste_saldo"):
        return False

    categoria = clean_text(mov.get("categoria")).upper()
    descricao = clean_text(mov.get("descricao"))
    valor = float(mov.get("realizada") or 0.0)

    if categoria == "RENDIMENTOS":
        return False
    if abs(valor) < 0.005:
        return False
    # OUTROS (resgate, Editável, ajuste manual) não entra na conferência.
    if categoria == "OUTROS":
        return False
    if RE_TRANSFERENCIA_FUNDO.search(descricao):
        return False
    # Crédito negativo distorce a fórmula (vira “rendimento” artificial).
    if mov.get("tipo") == "receita" and valor < 0:
        return False
    return True


def totais_operacionais(inicio: date, fim: date) -> dict:
    """Créditos e despesas operacionais do intervalo (sem transferência/ajuste)."""
    from . import repository

    if inicio > fim:
        return {"creditos": 0.0, "despesas": 0.0, "ignorados": 0}

    creditos = 0.0
    despesas = 0.0
    ignorados = 0
    for mov in repository.fetch_movimentos(inicio, fim):
        if not movimento_entra_no_rendimento(mov):
            if float(mov.get("realizada") or 0.0):
                ignorados += 1
            continue
        valor = float(mov.get("realizada") or 0.0)
        if mov.get("tipo") == "receita":
            creditos += valor
        elif mov.get("tipo") == "despesa":
            despesas += valor
    return {
        "creditos": round(creditos, 2),
        "despesas": round(despesas, 2),
        "ignorados": ignorados,
    }


def _classificar_transferencia(mov: dict) -> Optional[str]:
    """Retorna 'resgate', 'aplicacao' ou None."""
    if mov.get("ajuste_saldo"):
        return None
    valor = abs(float(mov.get("realizada") or 0.0))
    if valor < 0.005:
        return None
    descricao = clean_text(mov.get("descricao"))
    categoria = clean_text(mov.get("categoria")).upper()
    texto = f"{categoria} {descricao}"
    # Resgate tem prioridade se os dois termos aparecerem.
    if RE_RESGATE.search(texto):
        return "resgate"
    if RE_APLICACAO.search(texto):
        return "aplicacao"
    return None


def totais_transferencia_fundo(inicio: date, fim: date) -> dict:
    """Soma resgates e aplicações lançados no intervalo (livro)."""
    from . import repository

    if inicio > fim:
        return {"resgates": 0.0, "aplicacoes": 0.0, "qtd": 0}

    resgates = 0.0
    aplicacoes = 0.0
    qtd = 0
    for mov in repository.fetch_movimentos(inicio, fim):
        tipo = _classificar_transferencia(mov)
        if not tipo:
            continue
        valor = abs(float(mov.get("realizada") or 0.0))
        qtd += 1
        if tipo == "resgate":
            resgates += valor
        else:
            aplicacoes += valor
    return {
        "resgates": round(resgates, 2),
        "aplicacoes": round(aplicacoes, 2),
        "qtd": qtd,
    }


def _saldos_fundos_snapshot(snapshot: dict) -> dict[str, float]:
    """Saldos por fundo sem duplicar SD quando já há Invest. Resgate Automático."""
    fundos = dict(snapshot.get("fundos") or {})
    auto = float(snapshot.get("invest_resgate_auto") or 0.0)
    saida: dict[str, float] = {}
    if auto > 0.009:
        saida[FUNDO_SD] = auto
        for nome, valor in fundos.items():
            if normalizar_nome_fundo(nome) == FUNDO_SD:
                continue
            saida[normalizar_nome_fundo(nome)] = float(valor or 0.0)
    else:
        for nome, valor in fundos.items():
            saida[normalizar_nome_fundo(nome)] = float(valor or 0.0)
    return saida


def _taxa_dia(antes: float, variacao: float, dias: int) -> Optional[float]:
    if antes <= 0.009 or dias <= 0:
        return None
    return variacao / antes / dias


def _analise_por_fundo(
    anterior: dict,
    atual: dict,
    *,
    dias: int,
) -> tuple[list[dict], float, float, Optional[float]]:
    """Separa overnight de aporte/resgate por fundo e devolve taxa de referência."""
    ant = _saldos_fundos_snapshot(anterior)
    atu = _saldos_fundos_snapshot(atual)
    dias = max(int(dias or 1), 1)

    # Taxa do CP como referência (fundo que quase não recebe sweep de imposto).
    taxa_ref = None
    cp_ant = float(ant.get(FUNDO_CP) or 0.0)
    cp_atu = float(atu.get(FUNDO_CP) or 0.0)
    if cp_ant > 0.009:
        taxa_cp = _taxa_dia(cp_ant, cp_atu - cp_ant, dias)
        if taxa_cp is not None and abs(taxa_cp) <= TAXA_MAX_DIA:
            taxa_ref = taxa_cp
    if taxa_ref is None:
        taxa_ref = TAXA_REF_DIA_PADRAO

    por_fundo = []
    rendimento = 0.0
    aplicacoes_liq = 0.0
    for nome in sorted(set(ant) | set(atu)):
        antes = float(ant.get(nome) or 0.0)
        depois = float(atu.get(nome) or 0.0)
        variacao = round(depois - antes, 2)
        taxa = _taxa_dia(antes, variacao, dias)
        alerta = bool(taxa is not None and abs(taxa) > TAXA_MAX_DIA)

        if antes <= 0.009:
            # Saldo novo / zerado: variação é aporte ou resgate, não overnight.
            rend_f = 0.0
            aplic_f = variacao
            alerta = abs(variacao) > 0.009
        elif taxa is not None and abs(taxa) > TAXA_MAX_DIA:
            alerta = True
            if variacao < 0:
                # Queda forte: principal saiu (resgate). Overnight só no que ficou,
                # pela taxa de referência e pelo menor saldo do intervalo.
                base = min(antes, depois)
                rend_f = round(base * taxa_ref * dias, 2) if base > 0.009 else 0.0
                aplic_f = round(variacao - rend_f, 2)
            else:
                # Alta forte: principal entrou (aplicação). Overnight pela taxa ref.
                rend_f = round(antes * taxa_ref * dias, 2)
                aplic_f = round(variacao - rend_f, 2)
        else:
            rend_f = variacao
            aplic_f = 0.0

        rendimento += rend_f
        aplicacoes_liq += aplic_f
        por_fundo.append(
            {
                "fundo": nome,
                "anterior": round(antes, 2),
                "atual": round(depois, 2),
                "variacao": variacao,
                "taxa_dia": None if taxa is None else round(taxa * 100, 4),
                "taxa_periodo": None
                if antes <= 0.009
                else round((variacao / antes) * 100, 4),
                "rendimento": round(rend_f, 2),
                "aplicacao": round(aplic_f, 2),
                "alerta": alerta,
            }
        )

    return por_fundo, round(rendimento, 2), round(aplicacoes_liq, 2), taxa_ref


def calcular_rendimento(anterior: dict, atual: dict) -> dict:
    """Rendimento overnight estimado (separa aplicação/resgate pela taxa)."""
    data_ant = anterior.get("data")
    data_atu = atual.get("data")
    if isinstance(data_ant, str):
        data_ant = date.fromisoformat(data_ant[:10])
    if isinstance(data_atu, str):
        data_atu = date.fromisoformat(data_atu[:10])

    saldo_anterior = patrimonio_fundos(anterior)
    saldo_final = patrimonio_fundos(atual)
    variacao = round(saldo_final - saldo_anterior, 2)
    intervalo = (
        (data_atu - data_ant).days
        if isinstance(data_ant, date) and isinstance(data_atu, date)
        else 1
    ) or 1

    por_fundo, rendimento, aplicacoes_est, taxa_ref = _analise_por_fundo(
        anterior, atual, dias=intervalo
    )

    # Confere também resgates/aplicações explícitos no livro.
    resgates_livro = 0.0
    aplicacoes_livro = 0.0
    if isinstance(data_ant, date) and isinstance(data_atu, date):
        if variacao < 0:
            transf = totais_transferencia_fundo(data_ant, data_atu)
            resgates_livro = float(transf["resgates"])
        elif variacao > 0:
            inicio = data_ant + timedelta(days=1)
            if inicio <= data_atu:
                transf = totais_transferencia_fundo(inicio, data_atu)
                aplicacoes_livro = float(transf["aplicacoes"])

    auto_ant = float(anterior.get("invest_resgate_auto") or 0.0)
    auto_atu = float(atual.get("invest_resgate_auto") or 0.0)
    taxa_bruta = _taxa_dia(saldo_anterior, variacao, intervalo)

    return {
        "data_anterior": data_ant,
        "data_atual": data_atu,
        "saldo_anterior": saldo_anterior,
        "creditos": 0.0,
        "despesas": 0.0,
        "saldo_esperado": saldo_anterior,
        "saldo_final": saldo_final,
        "variacao_fundos": variacao,
        "resgates": round(resgates_livro, 2),
        "aplicacoes": round(aplicacoes_est, 2),
        "aplicacoes_livro": round(aplicacoes_livro, 2),
        "rendimento_total": rendimento,
        "taxa_dia": None if taxa_bruta is None else round(taxa_bruta * 100, 4),
        "taxa_dia_ref": round(float(taxa_ref) * 100, 4),
        "taxa_dia_rendimento": (
            None
            if saldo_anterior <= 0.009
            else round((rendimento / saldo_anterior / intervalo) * 100, 4)
        ),
        "alerta_taxa": bool(taxa_bruta is not None and abs(taxa_bruta) > TAXA_MAX_DIA),
        "por_fundo": por_fundo,
        "saldo_cc_anterior": float(anterior.get("saldo_cc") or 0.0),
        "saldo_cc_atual": float(atual.get("saldo_cc") or 0.0),
        "invest_resgate_auto_anterior": auto_ant,
        "invest_resgate_auto_atual": auto_atu,
    }


def init_saldos_extrato() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saldos_extrato (
                data DATE PRIMARY KEY,
                saldo_cc REAL NOT NULL DEFAULT 0,
                invest_resgate_auto REAL NOT NULL DEFAULT 0,
                saldo_total REAL NOT NULL DEFAULT 0,
                fundos_json TEXT NOT NULL DEFAULT '{}',
                origem TEXT,
                atualizado_em TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extratos_arquivos (
                nome TEXT PRIMARY KEY,
                tamanho INTEGER NOT NULL,
                mtime REAL NOT NULL,
                data_saldo DATE,
                ok INTEGER NOT NULL DEFAULT 1,
                motivo TEXT,
                processado_em TIMESTAMP NOT NULL
            )
            """
        )


def _row_to_snapshot(row) -> dict:
    try:
        fundos = json.loads(row["fundos_json"] or "{}")
    except json.JSONDecodeError:
        fundos = {}
    data_ref = row["data"]
    if isinstance(data_ref, str):
        data_ref = date.fromisoformat(data_ref[:10])
    keys = row.keys() if hasattr(row, "keys") else []
    return {
        "data": data_ref,
        "saldo_cc": float(row["saldo_cc"] or 0),
        "invest_resgate_auto": float(row["invest_resgate_auto"] or 0),
        "saldo_total": float(row["saldo_total"] or 0),
        "fundos": fundos,
        "origem": row["origem"] if "origem" in keys else None,
        "atualizado_em": row["atualizado_em"] if "atualizado_em" in keys else None,
    }


def salvar_snapshot(snapshot: dict, origem: str = "") -> dict:
    init_saldos_extrato()
    data_ref = snapshot.get("data")
    if not data_ref:
        raise ValueError("Snapshot de extrato sem data de saldo.")
    if isinstance(data_ref, str):
        data_ref = date.fromisoformat(data_ref[:10])

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO saldos_extrato (
                data, saldo_cc, invest_resgate_auto, saldo_total,
                fundos_json, origem, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(data) DO UPDATE SET
                saldo_cc = excluded.saldo_cc,
                invest_resgate_auto = excluded.invest_resgate_auto,
                saldo_total = excluded.saldo_total,
                fundos_json = excluded.fundos_json,
                origem = excluded.origem,
                atualizado_em = excluded.atualizado_em
            """,
            (
                data_ref.isoformat(),
                float(snapshot.get("saldo_cc") or 0),
                float(snapshot.get("invest_resgate_auto") or 0),
                float(snapshot.get("saldo_total") or 0),
                json.dumps(snapshot.get("fundos") or {}, ensure_ascii=False),
                origem or None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    salvo = dict(snapshot)
    salvo["data"] = data_ref
    salvo["origem"] = origem
    return salvo


def obter_snapshot(dia: date) -> Optional[dict]:
    init_saldos_extrato()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT data, saldo_cc, invest_resgate_auto, saldo_total, fundos_json, origem
            FROM saldos_extrato WHERE data = ?
            """,
            (dia.isoformat(),),
        ).fetchone()
    return _row_to_snapshot(row) if row else None


def snapshot_anterior(dia: date) -> Optional[dict]:
    init_saldos_extrato()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT data, saldo_cc, invest_resgate_auto, saldo_total, fundos_json, origem
            FROM saldos_extrato
            WHERE data < ?
            ORDER BY data DESC
            LIMIT 1
            """,
            (dia.isoformat(),),
        ).fetchone()
    return _row_to_snapshot(row) if row else None


def listar_snapshots() -> list[dict]:
    """Todos os rodapés de extrato gravados, do mais antigo ao mais novo."""
    init_saldos_extrato()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT data, saldo_cc, invest_resgate_auto, saldo_total,
                   fundos_json, origem, atualizado_em
            FROM saldos_extrato
            ORDER BY data ASC
            """
        ).fetchall()
    return [_row_to_snapshot(row) for row in rows]


def serie_rendimentos() -> dict:
    """Série entre extratos: rendimento = variação dos fundos no intervalo."""
    snaps = listar_snapshots()
    linhas = []
    total_conferido = 0.0
    dias_conferidos = 0

    for indice, atual in enumerate(snaps):
        data_atu = _as_date(atual.get("data"))
        fundos = patrimonio_fundos(atual)
        item = {
            "data": data_atu.isoformat() if data_atu else atual.get("data"),
            "saldo_cc": atual.get("saldo_cc"),
            "invest_resgate_auto": atual.get("invest_resgate_auto"),
            "saldo_total": atual.get("saldo_total"),
            "patrimonio": fundos,
            "fundos": dict(atual.get("fundos") or {}),
            "origem": atual.get("origem") or "",
            "atualizado_em": atual.get("atualizado_em") or "",
            "conferido": False,
            "data_anterior": None,
            "intervalo_dias": None,
            "saldo_anterior": None,
            "creditos": None,
            "despesas": None,
            "saldo_esperado": None,
            "saldo_final": fundos,
            "variacao_fundos": None,
            "resgates": None,
            "aplicacoes": None,
            "rendimento_total": None,
            "rendimento_diario": None,
            "taxa_dia": None,
            "taxa_dia_ref": None,
            "taxa_dia_rendimento": None,
            "alerta_taxa": False,
            "por_fundo": [],
            "motivo": None,
            "fonte_saldo": "fundos",
            "movimentos_ignorados": 0,
        }

        if indice == 0 or data_atu is None:
            item["motivo"] = (
                "Ponto de partida — o rendimento sai a partir do próximo extrato."
            )
            item["por_fundo"] = [
                {
                    "fundo": nome,
                    "anterior": valor,
                    "atual": valor,
                    "variacao": 0.0,
                    "taxa_dia": None,
                    "rendimento": 0.0,
                    "aplicacao": 0.0,
                    "alerta": False,
                }
                for nome, valor in sorted(_saldos_fundos_snapshot(atual).items())
            ]
            linhas.append(item)
            continue

        anterior = snaps[indice - 1]
        calculo = calcular_rendimento(anterior, atual)
        data_ant = _as_date(anterior.get("data"))
        intervalo = (data_atu - data_ant).days if data_ant else None
        rendimento = float(calculo["rendimento_total"] or 0)
        diario = (
            round(rendimento / intervalo, 2)
            if intervalo and intervalo > 0
            else rendimento
        )

        def _brl(valor: float) -> str:
            texto = f"{valor:,.2f}"
            return texto.replace(",", "X").replace(".", ",").replace("X", ".")

        avisos = []
        if intervalo and intervalo > 1:
            avisos.append(
                f"Intervalo de {intervalo} dia(s): média/dia = total ÷ {intervalo}."
            )
        if calculo.get("alerta_taxa"):
            avisos.append(
                "Taxa bruta acima de 0,15%/dia — parte tratada como aplicação/resgate."
            )
        if abs(float(calculo.get("aplicacoes") or 0)) > 0.009:
            avisos.append(
                f"Aplicação/resgate estimado R$ {_brl(abs(calculo['aplicacoes']))} "
                "separado do overnight."
            )
        if float(calculo.get("resgates") or 0) > 0.009:
            avisos.append(
                f"Resgate no livro R$ {_brl(calculo['resgates'])}."
            )
        if calculo.get("taxa_dia_ref") is not None:
            avisos.append(
                f"Taxa ref. {str(calculo['taxa_dia_ref']).replace('.', ',')}%/dia."
            )

        item.update(
            {
                "conferido": True,
                "data_anterior": calculo["data_anterior"].isoformat()
                if isinstance(calculo["data_anterior"], date)
                else calculo["data_anterior"],
                "intervalo_dias": intervalo,
                "saldo_anterior": calculo["saldo_anterior"],
                "creditos": 0.0,
                "despesas": 0.0,
                "saldo_esperado": calculo["saldo_esperado"],
                "saldo_final": calculo["saldo_final"],
                "variacao_fundos": calculo.get("variacao_fundos"),
                "resgates": calculo.get("resgates"),
                "aplicacoes": calculo.get("aplicacoes"),
                "rendimento_total": rendimento,
                "rendimento_diario": diario,
                "taxa_dia": calculo.get("taxa_dia"),
                "taxa_dia_ref": calculo.get("taxa_dia_ref"),
                "taxa_dia_rendimento": calculo.get("taxa_dia_rendimento"),
                "alerta_taxa": calculo.get("alerta_taxa"),
                "por_fundo": calculo["por_fundo"],
                "motivo": " ".join(avisos) if avisos else None,
            }
        )
        total_conferido += float(calculo["rendimento_total"] or 0)
        dias_conferidos += 1
        linhas.append(item)

    pasta = info_pasta_uploads()
    return {
        "extratos": len(snaps),
        "dias_livro": len(linhas),
        "dias_conferidos": dias_conferidos,
        "rendimento_total": round(total_conferido, 2),
        "linhas": linhas,
        "pasta": pasta["pasta"],
        "arquivos_total": pasta["pdfs"],
        "pendentes": 0,
        "arquivos_lidos": 0,
        "ignorados": [],
        "movimentos_ignorados": 0,
        "modo": "fundos",
    }


def _pasta_uploads() -> Path:
    from .config import get_uploads_dir

    pasta = Path(get_uploads_dir())
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def listar_pdfs_uploads() -> list[Path]:
    pasta = _pasta_uploads()
    return sorted(
        [p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
        key=lambda p: p.name,
    )


def _arquivo_ja_processado(arquivo: Path) -> bool:
    init_saldos_extrato()
    try:
        tamanho = arquivo.stat().st_size
        mtime = arquivo.stat().st_mtime
    except OSError:
        return False
    with connect() as conn:
        row = conn.execute(
            "SELECT tamanho, mtime FROM extratos_arquivos WHERE nome = ?",
            (arquivo.name,),
        ).fetchone()
    if not row:
        return False
    return int(row["tamanho"]) == int(tamanho) and abs(float(row["mtime"]) - float(mtime)) < 1


def _marcar_arquivo(
    arquivo: Path,
    *,
    data_saldo: Optional[date] = None,
    ok: bool = True,
    motivo: str = "",
) -> None:
    init_saldos_extrato()
    try:
        stat = arquivo.stat()
        tamanho = stat.st_size
        mtime = stat.st_mtime
    except OSError:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO extratos_arquivos (
                nome, tamanho, mtime, data_saldo, ok, motivo, processado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nome) DO UPDATE SET
                tamanho = excluded.tamanho,
                mtime = excluded.mtime,
                data_saldo = excluded.data_saldo,
                ok = excluded.ok,
                motivo = excluded.motivo,
                processado_em = excluded.processado_em
            """,
            (
                arquivo.name,
                int(tamanho),
                float(mtime),
                data_saldo.isoformat() if isinstance(data_saldo, date) else data_saldo,
                1 if ok else 0,
                motivo or None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def registrar_upload(caminho: str, snapshot: Optional[dict] = None) -> None:
    """Marca o PDF gravado na importação para a aba não reprocessar à toa."""
    path = Path(caminho)
    if not path.exists():
        return
    data_ref = (snapshot or {}).get("data")
    _marcar_arquivo(path, data_saldo=data_ref, ok=bool(snapshot), motivo="" if snapshot else "sem rodapé")


def info_pasta_uploads() -> dict:
    pasta = _pasta_uploads()
    pdfs = listar_pdfs_uploads()
    return {
        "pasta": str(pasta),
        "pdfs": len(pdfs),
        "arquivos": [p.name for p in pdfs],
    }


def sincronizar_uploads(*, forcar: bool = False, limite: int = 4) -> dict:
    """Lê PDFs novos/alterados da pasta que recebe os uploads diários."""
    from . import importers

    pdfs = listar_pdfs_uploads()
    pendentes = [p for p in pdfs if forcar or not _arquivo_ja_processado(p)]
    lidos = 0
    ignorados = []
    for arquivo in pendentes[: max(1, limite) if not forcar else len(pendentes)]:
        try:
            linhas = importers.extract_lines_from_pdf(
                arquivo.read_bytes(), permitir_ocr=True
            )
            snapshot = extrair_snapshot_extrato(linhas)
            if not snapshot or not snapshot.get("data"):
                motivo = "rodapé de fundos não encontrado"
                ignorados.append({"arquivo": arquivo.name, "motivo": motivo})
                _marcar_arquivo(arquivo, ok=False, motivo=motivo)
                continue
            salvar_snapshot(snapshot, origem=f"uploads:{arquivo.name}")
            _marcar_arquivo(arquivo, data_saldo=snapshot["data"], ok=True)
            lidos += 1
        except Exception as exc:
            ignorados.append({"arquivo": arquivo.name, "motivo": str(exc)})

    restantes = max(0, len(pendentes) - (lidos + len(ignorados))) if not forcar else 0
    if forcar:
        restantes = 0

    serie = serie_rendimentos()
    pasta = info_pasta_uploads()
    serie["pasta"] = pasta["pasta"]
    serie["arquivos_total"] = pasta["pdfs"]
    serie["arquivos_lidos"] = lidos
    serie["pendentes"] = restantes
    serie["ignorados"] = ignorados
    return serie


def reler_uploads() -> dict:
    """Reprocessa todos os PDFs da pasta de uploads."""
    return sincronizar_uploads(forcar=True, limite=500)


def serializar_snapshot(snapshot: Optional[dict]) -> Optional[dict]:
    if not snapshot:
        return None
    data_ref = snapshot.get("data")
    return {
        "data": data_ref.isoformat() if isinstance(data_ref, date) else data_ref,
        "saldo_cc": float(snapshot.get("saldo_cc") or 0),
        "invest_resgate_auto": float(snapshot.get("invest_resgate_auto") or 0),
        "saldo_total": float(snapshot.get("saldo_total") or 0),
        "fundos": dict(snapshot.get("fundos") or {}),
    }


def serializar_calculo(calculo: dict) -> dict:
    def iso(valor):
        if isinstance(valor, date):
            return valor.isoformat()
        return valor

    saida = dict(calculo)
    saida["data_anterior"] = iso(calculo.get("data_anterior"))
    saida["data_atual"] = iso(calculo.get("data_atual"))
    return saida


def preservar_rendimentos(existentes: list[dict], novas: list[dict]) -> list[dict]:
    """Mantém RENDIMENTOS já lançados quando a importação de impostos viria zerada."""
    from .finance import clean_text

    valor = 0.0
    for row in existentes or []:
        if clean_text(row.get("categoria")).upper() == "RENDIMENTOS":
            valor += float(row.get("realizada") or 0)
    if valor == 0:
        return novas
    for row in novas:
        if clean_text(row.get("categoria")).upper() == "RENDIMENTOS":
            if not float(row.get("realizada") or 0):
                row["realizada"] = valor
            break
    return novas


def lancar_rendimento(
    dia: date,
    valor: float,
    *,
    usuario: dict,
    origem: str,
    liberados: list[str],
) -> dict:
    """Grava o total de rendimento na linha RENDIMENTOS do dia (sem apagar impostos)."""
    from . import historico, repository
    from .finance import (
        can_edit_day,
        clean_text,
        is_past_month,
        merge_with_template,
        receita_template,
    )

    if not can_edit_day(dia, liberados, autenticado=True):
        motivo = "mês histórico bloqueado" if is_past_month(dia) else "sem permissão"
        return {"ok": False, "motivo": motivo, "data": dia.isoformat(), "valor": valor}

    antes = repository.fetch_day(dia, "receita")
    linhas = merge_with_template(antes, receita_template())
    achou = False
    for row in linhas:
        if clean_text(row.get("categoria")).upper() == "RENDIMENTOS":
            row["realizada"] = float(valor)
            row["descricao"] = clean_text(row.get("descricao")) or "RENDIMENTOS"
            row["source"] = origem
            achou = True
            break
    if not achou:
        linhas.append(
            {
                "categoria": "RENDIMENTOS",
                "descricao": "RENDIMENTOS",
                "prevista": 0.0,
                "realizada": float(valor),
                "source": origem,
            }
        )

    repository.replace_day(dia, "receita", linhas, source=origem)
    historico.registrar(
        acao="rendimentos",
        data_ref=dia,
        tipo="receita",
        usuario=usuario,
        origem=origem,
        antes=antes,
        depois=linhas,
    )
    return {"ok": True, "data": dia.isoformat(), "valor": float(valor)}


def processar_snapshots(
    snapshots: list[dict],
    *,
    usuario: dict,
    origem: str,
    liberados: list[str],
) -> list[dict]:
    """Salva snapshots e lança o rendimento contra o extrato imediatamente anterior."""
    resultados = []
    ordenados = sorted(
        [s for s in snapshots if s and s.get("data")],
        key=lambda s: s["data"],
    )
    vistos: set[date] = set()
    for snap in ordenados:
        dia = snap["data"]
        if dia in vistos:
            continue
        vistos.add(dia)
        salvar_snapshot(snap, origem=origem)
        anterior = snapshot_anterior(dia)
        if not anterior:
            resultados.append(
                {
                    "data": dia.isoformat(),
                    "lancado": False,
                    "motivo": "sem extrato anterior gravado para comparar",
                    "snapshot": serializar_snapshot(snap),
                }
            )
            continue
        calculo = calcular_rendimento(anterior, snap)
        lancamento = lancar_rendimento(
            dia,
            calculo["rendimento_total"],
            usuario=usuario,
            origem=origem,
            liberados=liberados,
        )
        resultados.append(
            {
                **serializar_calculo(calculo),
                "lancado": bool(lancamento.get("ok")),
                "motivo": lancamento.get("motivo"),
                "snapshot": serializar_snapshot(snap),
            }
        )
    return resultados
