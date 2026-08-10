"""Leitura de arquivos externos: extratos bancários em PDF e planilhas em texto.

As expressões de mapeamento e as regras de leitura do extrato foram preservadas
integralmente da versão Streamlit para não alterar resultados já consolidados.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Optional

from .finance import (
    clean_text,
    merge_with_template,
    parse_number,
    receita_template,
)

# Palavras-chave que identificam a origem do crédito na linha do extrato.
RECEITA_BANK_PATTERNS: dict[tuple[str, str], list[str]] = {
    ("IMPOSTOS", "ORIGEM ITR"): [r"\bITR\b"],
    ("IMPOSTOS", "ORIGEM IPVA"): [r"\bIPVA\b"],
    ("IMPOSTOS", "ORIGEM ITCMD"): [r"\bITCMD\b"],
    ("IMPOSTOS", "ORIGEM IPI-EXP"): [r"\bIPI[- ]?EXP\b"],
    ("IMPOSTOS", "ORIGEM ICMS"): [r"RECEBIMENTO DE ICMS", r"\bICMS\b"],
    ("IMPOSTOS", "ORIGEM FPM"): [r"FPE/FPM", r"\bFPM\b"],
}

DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\b")
MONEY_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*[CD]?")

# Linhas de fechamento do extrato (saldo, total, subtotal) não são movimento:
# importá-las duplicaria o valor já somado pelos lançamentos do período.
LINHAS_NAO_MOVIMENTO = re.compile(
    r"\b(SALDO|SALDOS|TOTAL|TOTAIS|SUBTOTAL|SUB-TOTAL|ACUMULADO|"
    r"TRANSPORTE\s+DE\s+SALDO|SALDO\s+ANTERIOR|SALDO\s+FINAL|SALDO\s+INICIAL|"
    r"RESUMO|EXTRATO\s+DE)\b",
    flags=re.IGNORECASE,
)


def eh_linha_de_fechamento(texto: str) -> bool:
    return bool(LINHAS_NAO_MOVIMENTO.search(str(texto or "")))


class ImportError_(Exception):
    """Falha tratável durante a leitura de um arquivo."""


def extract_lines_from_pdf(file_bytes: bytes) -> list[str]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependência declarada em requirements
        raise ImportError_("Biblioteca pdfplumber não instalada.") from exc

    lines: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            except Exception:
                text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if line:
                    lines.append(line)
    return lines


def datas_no_extrato(file_bytes: bytes) -> list[date]:
    """Todas as datas encontradas no início das linhas do extrato."""
    encontradas: set[date] = set()
    for line in extract_lines_from_pdf(file_bytes):
        match = DATE_RE.match(line)
        if not match:
            continue
        try:
            encontradas.add(datetime.strptime(match.group(1), "%d/%m/%Y").date())
        except ValueError:
            continue
    return sorted(encontradas)


def receita_do_extrato(day: date, file_bytes: bytes, lines: Optional[list[str]] = None) -> list[dict]:
    """Monta as linhas de receita de um dia a partir do extrato bancário.

    Considera apenas créditos: linhas terminadas em " D" (débito) são ignoradas.
    O valor usado é o último número monetário da linha.
    """
    if lines is None:
        lines = extract_lines_from_pdf(file_bytes)
    if not lines:
        return receita_template()

    alvo = day.strftime("%d/%m/%Y")
    totais: dict[tuple[str, str], float] = {}

    for line in lines:
        match = DATE_RE.match(line)
        if not match or match.group(1) != alvo:
            continue
        if line.rstrip().endswith(" D"):
            continue
        if eh_linha_de_fechamento(line):
            continue

        valores = MONEY_RE.findall(line)
        if not valores:
            continue

        valor = parse_number(valores[-1])
        if valor <= 0:
            continue

        for chave, padroes in RECEITA_BANK_PATTERNS.items():
            if any(re.search(p, line, flags=re.IGNORECASE) for p in padroes):
                totais[chave] = totais.get(chave, 0.0) + valor
                break

    if not totais:
        return receita_template()

    linhas = [
        {"categoria": categoria, "descricao": descricao, "prevista": 0.0, "realizada": valor}
        for (categoria, descricao), valor in totais.items()
    ]
    return merge_with_template(linhas, receita_template())


# ------------------------------------------------------------------
# Planilhas em texto e tabelas de PDF
# ------------------------------------------------------------------


def _normalize_tabular(df) -> list[dict]:
    """Converte um DataFrame heterogêneo no formato interno de lançamentos."""
    import pandas as pd

    colunas = {str(c).lower().strip(): c for c in df.columns}
    mapa: dict[str, Optional[str]] = {
        "data": None,
        "tipo": None,
        "categoria": None,
        "descricao": None,
        "prevista": None,
        "realizada": None,
    }

    for chave, original in colunas.items():
        if chave in ("data", "date", "dia"):
            mapa["data"] = original
        elif chave in ("tipo", "natureza", "classificacao", "classificação"):
            mapa["tipo"] = original
        elif chave in ("categoria", "grupo"):
            mapa["categoria"] = original
        elif chave.startswith("desc") or chave in ("historico", "histórico"):
            mapa["descricao"] = original
        elif chave in ("prevista", "previsto", "valor1", "valor_1", "v1"):
            mapa["prevista"] = original
        elif chave in ("realizada", "realizado", "valor2", "valor_2", "v2"):
            mapa["realizada"] = original
        elif chave in ("valor", "valor_total", "vlr", "quantia") and mapa["realizada"] is None:
            mapa["realizada"] = original

    registros: list[dict] = []
    for _, row in df.iterrows():
        data_valor = None
        if mapa["data"]:
            parsed = pd.to_datetime(row[mapa["data"]], errors="coerce", dayfirst=True)
            if not pd.isna(parsed):
                data_valor = parsed.date()

        tipo = clean_text(row[mapa["tipo"]]).lower() if mapa["tipo"] else ""
        if tipo not in ("receita", "despesa"):
            tipo = ""

        descricao = clean_text(row[mapa["descricao"]]) if mapa["descricao"] else ""
        categoria = clean_text(row[mapa["categoria"]]) if mapa["categoria"] else ""
        prevista = parse_number(row[mapa["prevista"]]) if mapa["prevista"] else 0.0
        realizada = parse_number(row[mapa["realizada"]]) if mapa["realizada"] else 0.0

        if not descricao and prevista == 0.0 and realizada == 0.0:
            continue
        if eh_linha_de_fechamento(descricao) or eh_linha_de_fechamento(categoria):
            continue

        registros.append(
            {
                "data": data_valor,
                "tipo": tipo,
                "categoria": categoria,
                "descricao": descricao,
                "prevista": prevista,
                "realizada": realizada,
            }
        )

    return registros


def parse_txt(file_bytes: bytes) -> list[dict]:
    import pandas as pd

    texto = file_bytes.decode("utf-8", errors="ignore")
    amostra = texto[:2048]

    delimitador = None
    for candidato in (";", ",", "\t", "|"):
        if candidato in amostra:
            delimitador = candidato
            break

    try:
        df = pd.read_csv(io.StringIO(texto), sep=delimitador, engine="python")
    except Exception:
        try:
            df = pd.read_csv(io.StringIO(texto), sep=r"\s+", engine="python")
        except Exception as exc:
            raise ImportError_(f"Não foi possível interpretar o arquivo de texto: {exc}") from exc

    return _normalize_tabular(df)


def parse_pdf_tabular(file_bytes: bytes) -> list[dict]:
    """Tenta ler tabelas estruturadas de um PDF. Retorna vazio se não houver."""
    try:
        import pandas as pd
        import pdfplumber
    except ImportError:
        return []

    tabelas = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            try:
                extraidas = page.extract_tables() or []
            except Exception:
                extraidas = []

            for tabela in extraidas:
                if not tabela or len(tabela) < 2:
                    continue
                df = pd.DataFrame(tabela).astype(str)
                cabecalho = df.iloc[0].astype(str).str.lower().tolist()
                if any(("desc" in h) or ("valor" in h) or ("data" in h) for h in cabecalho):
                    df.columns = _dedupe(cabecalho)
                    df = df.iloc[1:].reset_index(drop=True)
                    tabelas.append(df)

    if not tabelas:
        return []

    registros: list[dict] = []
    for df in tabelas:
        registros.extend(_normalize_tabular(df))
    return registros


def _dedupe(labels: list[str]) -> list[str]:
    contagem: dict[str, int] = {}
    saida: list[str] = []
    for label in labels:
        base = str(label).strip().lower() or "col"
        if base in contagem:
            contagem[base] += 1
            saida.append(f"{base}_{contagem[base]}")
        else:
            contagem[base] = 0
            saida.append(base)
    return saida


# ------------------------------------------------------------------
# CSV de despesa (ISO-8859-1, separador ;)
# ------------------------------------------------------------------


def _normalizar_cabecalho(nome: str) -> str:
    texto = clean_text(nome).lower()
    # Remove acentos simples sem depender de unicodedata complexo.
    for origem, destino in (
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"),
        ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"),
        ("ç", "c"),
    ):
        texto = texto.replace(origem, destino)
    return texto.replace(" ", "_")


def eh_csv_despesa(file_bytes: bytes) -> bool:
    """Detecta CSV de despesa pelas colunas típicas (vr_pago, nome_credor, etc.)."""
    for encoding in ("latin-1", "cp1252", "iso-8859-1", "utf-8"):
        try:
            texto = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        texto = file_bytes.decode("latin-1", errors="ignore")

    primeira = ""
    for linha in texto.splitlines():
        if linha.strip():
            primeira = linha
            break
    if not primeira:
        return False

    cols = {_normalizar_cabecalho(c) for c in primeira.split(";")}
    obrigatorias = {"data", "vr_pago"}
    fortes = {"nome_credor", "historico", "op", "nap", "processo", "ug"}
    return obrigatorias.issubset(cols) and len(cols & fortes) >= 2


def parse_despesa_csv(file_bytes: bytes) -> dict[date, list[dict]]:
    """Lê CSV ISO (;), agrupa por data e soma linhas idênticas no mesmo dia.

    Colunas: op, nap, processo, data, ug, nome_credor, historico, vr_pago.
    Retorna {data: [lançamentos de despesa]}.
    """
    import pandas as pd

    texto = None
    encoding_usado = "latin-1"
    for encoding in ("latin-1", "cp1252", "iso-8859-1", "utf-8-sig", "utf-8"):
        try:
            texto = file_bytes.decode(encoding)
            encoding_usado = encoding
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        texto = file_bytes.decode("latin-1", errors="ignore")

    try:
        df = pd.read_csv(
            io.StringIO(texto),
            sep=";",
            engine="python",
            dtype=str,
            keep_default_na=False,
        )
    except Exception as exc:
        raise ImportError_(
            f"Não foi possível ler o CSV de despesa ({encoding_usado}): {exc}"
        ) from exc

    if df.empty:
        return {}

    colunas = {_normalizar_cabecalho(str(c)): c for c in df.columns}
    mapa = {
        "op": colunas.get("op"),
        "nap": colunas.get("nap"),
        "processo": colunas.get("processo"),
        "data": colunas.get("data"),
        "ug": colunas.get("ug"),
        "nome_credor": colunas.get("nome_credor") or colunas.get("credor"),
        "historico": colunas.get("historico") or colunas.get("descricao"),
        "vr_pago": colunas.get("vr_pago")
        or colunas.get("valor_pago")
        or colunas.get("valor"),
    }
    if not mapa["data"] or not mapa["vr_pago"]:
        raise ImportError_(
            "CSV de despesa precisa das colunas 'data' e 'vr_pago' (separador ;)."
        )

    # (data, op, nap, processo, ug, nome_credor, historico) -> soma vr_pago
    agregados: dict[tuple, float] = {}
    ordem: list[tuple] = []

    for _, row in df.iterrows():
        bruto_data = clean_text(row[mapa["data"]])
        if not bruto_data:
            continue
        parsed = pd.to_datetime(bruto_data, errors="coerce", dayfirst=True)
        if pd.isna(parsed):
            continue
        dia = parsed.date()

        op = clean_text(row[mapa["op"]]) if mapa["op"] else ""
        nap = clean_text(row[mapa["nap"]]) if mapa["nap"] else ""
        processo = clean_text(row[mapa["processo"]]) if mapa["processo"] else ""
        ug = clean_text(row[mapa["ug"]]) if mapa["ug"] else ""
        nome_credor = clean_text(row[mapa["nome_credor"]]) if mapa["nome_credor"] else ""
        historico = clean_text(row[mapa["historico"]]) if mapa["historico"] else ""
        valor = parse_number(row[mapa["vr_pago"]])

        if valor == 0 and not any((op, nap, processo, ug, nome_credor, historico)):
            continue
        if eh_linha_de_fechamento(historico) or eh_linha_de_fechamento(nome_credor):
            continue

        chave = (dia, op, nap, processo, ug, nome_credor, historico)
        if chave not in agregados:
            agregados[chave] = 0.0
            ordem.append(chave)
        agregados[chave] += valor

    por_dia: dict[date, list[dict]] = {}
    for chave in ordem:
        dia, op, nap, processo, ug, nome_credor, historico = chave
        por_dia.setdefault(dia, []).append(
            {
                "categoria": ug or "DESPESA",
                "descricao": historico,
                "prevista": 0.0,
                "realizada": agregados[chave],
                "op": op,
                "nap": nap,
                "processo": processo,
                "ug": ug,
                "nome_credor": nome_credor,
            }
        )

    return por_dia
