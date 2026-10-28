"""Rendimento a partir dos extratos BB.

Fórmula usada na conferência manual:
    saldo esperado = saldo anterior + créditos − despesas
    rendimento     = saldo final − saldo esperado

O saldo (patrimônio) é conta corrente + Invest. Resgate Automático + fundos
que não estejam nesse resgate (ex.: BB RF CP). Créditos e despesas vêm dos
lançamentos importados no intervalo, sem contar o próprio rendimento.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .finance import parse_number
from .repository import connect

FUNDO_SD = "BB RF SD Diferenciado"
FUNDO_CP = "BB RF CP Automatico"

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


def patrimonio(snapshot: dict) -> float:
    """CC + resgate automático + fundos extras (CP), sem contar o SD duas vezes."""
    cc = float(snapshot.get("saldo_cc") or 0.0)
    auto = float(snapshot.get("invest_resgate_auto") or 0.0)
    extra = 0.0
    for nome, valor in (snapshot.get("fundos") or {}).items():
        if normalizar_nome_fundo(nome) == FUNDO_SD:
            continue
        extra += float(valor or 0.0)
    if auto == 0:
        extra = sum(float(v or 0.0) for v in (snapshot.get("fundos") or {}).values())
    return round(cc + auto + extra, 2)


def totais_operacionais(inicio: date, fim: date) -> dict:
    """Créditos e despesas importados no intervalo, sem rendimento nem ajuste."""
    from . import repository
    from .finance import clean_text

    if inicio > fim:
        return {"creditos": 0.0, "despesas": 0.0}

    creditos = 0.0
    despesas = 0.0
    for mov in repository.fetch_movimentos(inicio, fim):
        if mov.get("ajuste_saldo"):
            continue
        if clean_text(mov.get("categoria")).upper() == "RENDIMENTOS":
            continue
        valor = float(mov.get("realizada") or 0.0)
        if mov.get("tipo") == "receita":
            creditos += valor
        elif mov.get("tipo") == "despesa":
            despesas += valor
    return {"creditos": round(creditos, 2), "despesas": round(despesas, 2)}


def calcular_rendimento(anterior: dict, atual: dict) -> dict:
    """Rendimento = saldo final − (saldo anterior + créditos − despesas)."""
    data_ant = anterior.get("data")
    data_atu = atual.get("data")
    if isinstance(data_ant, str):
        data_ant = date.fromisoformat(data_ant[:10])
    if isinstance(data_atu, str):
        data_atu = date.fromisoformat(data_atu[:10])

    inicio_mov = data_ant + timedelta(days=1) if isinstance(data_ant, date) else data_ant
    totais = totais_operacionais(inicio_mov, data_atu) if isinstance(data_atu, date) else {
        "creditos": 0.0,
        "despesas": 0.0,
    }

    saldo_anterior = patrimonio(anterior)
    saldo_final = patrimonio(atual)
    esperado = round(saldo_anterior + totais["creditos"] - totais["despesas"], 2)
    rendimento = round(saldo_final - esperado, 2)

    fundos_ant = dict(anterior.get("fundos") or {})
    fundos_atu = dict(atual.get("fundos") or {})
    por_fundo = []
    for nome in sorted(set(fundos_ant) | set(fundos_atu)):
        antes = float(fundos_ant.get(nome) or 0.0)
        depois = float(fundos_atu.get(nome) or 0.0)
        por_fundo.append(
            {"fundo": nome, "anterior": antes, "atual": depois, "variacao": round(depois - antes, 2)}
        )

    return {
        "data_anterior": data_ant,
        "data_atual": data_atu,
        "saldo_anterior": saldo_anterior,
        "creditos": totais["creditos"],
        "despesas": totais["despesas"],
        "saldo_esperado": esperado,
        "saldo_final": saldo_final,
        "rendimento_total": rendimento,
        "por_fundo": por_fundo,
        "saldo_cc_anterior": float(anterior.get("saldo_cc") or 0.0),
        "saldo_cc_atual": float(atual.get("saldo_cc") or 0.0),
        "invest_resgate_auto_anterior": float(anterior.get("invest_resgate_auto") or 0.0),
        "invest_resgate_auto_atual": float(atual.get("invest_resgate_auto") or 0.0),
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
    """Monta a série dia a dia: rendimento só existe se houver extrato anterior."""
    snaps = listar_snapshots()
    linhas = []
    total_conferido = 0.0
    dias_conferidos = 0

    for indice, atual in enumerate(snaps):
        item = {
            "data": atual["data"].isoformat() if isinstance(atual["data"], date) else atual["data"],
            "saldo_cc": atual["saldo_cc"],
            "invest_resgate_auto": atual["invest_resgate_auto"],
            "saldo_total": atual["saldo_total"],
            "patrimonio": patrimonio(atual),
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
            "saldo_final": patrimonio(atual),
            "rendimento_total": None,
            "por_fundo": [],
            "motivo": "Primeiro extrato da série — ainda não há saldo anterior para conferir.",
        }
        if indice == 0:
            linhas.append(item)
            continue

        anterior = snaps[indice - 1]
        calculo = calcular_rendimento(anterior, atual)
        data_ant = anterior["data"]
        data_atu = atual["data"]
        if isinstance(data_ant, date) and isinstance(data_atu, date):
            intervalo = (data_atu - data_ant).days
        else:
            intervalo = None
        item.update(
            {
                "conferido": True,
                "data_anterior": calculo["data_anterior"].isoformat()
                if isinstance(calculo["data_anterior"], date)
                else calculo["data_anterior"],
                "intervalo_dias": intervalo,
                "saldo_anterior": calculo["saldo_anterior"],
                "creditos": calculo["creditos"],
                "despesas": calculo["despesas"],
                "saldo_esperado": calculo["saldo_esperado"],
                "saldo_final": calculo["saldo_final"],
                "rendimento_total": calculo["rendimento_total"],
                "por_fundo": calculo["por_fundo"],
                "motivo": None,
            }
        )
        total_conferido += float(calculo["rendimento_total"] or 0)
        dias_conferidos += 1
        linhas.append(item)

    pasta = info_pasta_uploads()
    return {
        "extratos": len(snaps),
        "dias_conferidos": dias_conferidos,
        "rendimento_total": round(total_conferido, 2),
        "linhas": linhas,
        "pasta": pasta["pasta"],
        "arquivos_total": pasta["pdfs"],
        "pendentes": 0,
        "arquivos_lidos": 0,
        "ignorados": [],
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
