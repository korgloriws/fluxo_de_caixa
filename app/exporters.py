"""Geração dos relatórios em Excel e PDF."""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Iterable

from .config import APP_NAME
from .finance import MESES_PT, format_currency

MONEY_FMT = "R$ #,##0.00"


def _safe_pdf_text(value: str) -> str:
    """As fontes nativas do FPDF cobrem latin-1; troca o que estiver fora."""
    return str(value).encode("latin-1", errors="replace").decode("latin-1")


# ------------------------------------------------------------------
# Excel
# ------------------------------------------------------------------


def export_excel(
    movimentos: list[dict],
    resumo_diario: list[dict],
    start: date,
    end: date,
) -> tuple[bytes, str]:
    import pandas as pd

    buffer = io.BytesIO()
    filename = f"fluxo_fundeb_{start:%Y%m%d}_a_{end:%Y%m%d}.xlsx"

    receitas = [m for m in movimentos if m["tipo"] == "receita"]
    despesas = [m for m in movimentos if m["tipo"] == "despesa"]

    def to_frame(rows: Iterable[dict]) -> "pd.DataFrame":
        data = [
            {
                "Data": r["data"],
                "Categoria": r["categoria"],
                "Descrição": r["descricao"],
                "Prevista": r["prevista"],
                "Realizada": r["realizada"],
                "Desvio": r["realizada"] - r["prevista"],
                "Origem": r["source"],
            }
            for r in rows
        ]
        return pd.DataFrame(
            data,
            columns=["Data", "Categoria", "Descrição", "Prevista", "Realizada", "Desvio", "Origem"],
        )

    df_resumo = pd.DataFrame(
        [
            {
                "Data": r["data"],
                "Receita Realizada": r["receita"],
                "Despesa Realizada": r["despesa"],
                "Saldo do Dia": r["saldo"],
                "Saldo Acumulado": r["saldo_acumulado"],
            }
            for r in resumo_diario
        ],
        columns=["Data", "Receita Realizada", "Despesa Realizada", "Saldo do Dia", "Saldo Acumulado"],
    )

    total_receita = sum(r["realizada"] for r in receitas)
    total_despesa = sum(r["realizada"] for r in despesas)
    df_totais = pd.DataFrame(
        [
            {"Indicador": "Período", "Valor": f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"},
            {"Indicador": "Receita realizada", "Valor": format_currency(total_receita)},
            {"Indicador": "Despesa realizada", "Valor": format_currency(total_despesa)},
            {"Indicador": "Saldo do período", "Valor": format_currency(total_receita - total_despesa)},
            {"Indicador": "Lançamentos", "Valor": len(movimentos)},
            {"Indicador": "Gerado em", "Valor": datetime.now().strftime("%d/%m/%Y %H:%M")},
        ]
    )

    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        book = writer.book
        money = book.add_format({"num_format": MONEY_FMT})
        header = book.add_format(
            {"bold": True, "bg_color": "#A16207", "font_color": "white", "border": 1}
        )

        sheets = {
            "Resumo": df_totais,
            "Por Dia": df_resumo,
            "Receitas": to_frame(receitas),
            "Despesas": to_frame(despesas),
        }

        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False, startrow=1, header=False)
            sheet = writer.sheets[name]

            for col_idx, col_name in enumerate(frame.columns):
                sheet.write(0, col_idx, col_name, header)
                largura = max(12, min(40, int(frame[col_name].astype(str).str.len().max() or 12) + 4))
                is_money = col_name in (
                    "Prevista", "Realizada", "Desvio",
                    "Receita Realizada", "Despesa Realizada",
                    "Saldo do Dia", "Saldo Acumulado",
                )
                sheet.set_column(col_idx, col_idx, largura, money if is_money else None)

            sheet.freeze_panes(1, 0)
            if len(frame) > 0:
                sheet.autofilter(0, 0, len(frame), len(frame.columns) - 1)

    buffer.seek(0)
    return buffer.getvalue(), filename


# ------------------------------------------------------------------
# PDF
# ------------------------------------------------------------------


def export_pdf_periodo(
    start: date,
    end: date,
    receitas: list[dict],
    despesas: list[dict],
    resumo_diario: list[dict],
    saldo_inicial: float,
) -> tuple[bytes, str]:
    from fpdf import FPDF

    try:
        from fpdf.enums import XPos, YPos

        def quebra(pdf):
            return {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}
    except ImportError:  # PyFPDF antigo
        def quebra(pdf):
            return {"ln": 1}

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    total_receita = sum(r["realizada"] for r in receitas)
    total_despesa = sum(d["realizada"] for d in despesas)
    saldo_periodo = total_receita - total_despesa

    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _safe_pdf_text(APP_NAME), **quebra(pdf))

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    periodo = f"Período: {start:%d/%m/%Y} a {end:%d/%m/%Y}"
    pdf.cell(0, 6, _safe_pdf_text(periodo), **quebra(pdf))
    pdf.cell(0, 6, _safe_pdf_text(f"Emitido em {datetime.now():%d/%m/%Y às %H:%M}"), **quebra(pdf))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    # Quadro de indicadores
    indicadores = [
        ("Saldo inicial", saldo_inicial),
        ("Receita realizada", total_receita),
        ("Despesa realizada", total_despesa),
        ("Saldo final", saldo_inicial + saldo_periodo),
    ]
    largura = 45
    pdf.set_font("Helvetica", "B", 8)
    for rotulo, _ in indicadores:
        pdf.cell(largura, 6, _safe_pdf_text(rotulo.upper()), border="LTR", align="C")
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 10)
    for _, valor in indicadores:
        pdf.cell(largura, 8, _safe_pdf_text(format_currency(valor)), border="LBR", align="C")
    pdf.ln(12)

    def tabela(titulo: str, linhas: list[dict], total: float) -> None:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _safe_pdf_text(titulo), **quebra(pdf))

        larguras = [26, 40, 60, 32, 32]
        cabecalhos = ["Data", "Categoria", "Descrição", "Prevista", "Realizada"]

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(161, 98, 7)
        pdf.set_text_color(255, 255, 255)
        for largura_col, titulo_col in zip(larguras, cabecalhos):
            pdf.cell(largura_col, 6, _safe_pdf_text(titulo_col), border=1, align="C", fill=True)
        pdf.ln(6)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 8)

        visiveis = [l for l in linhas if l["prevista"] or l["realizada"]]
        if not visiveis:
            pdf.cell(sum(larguras), 6, _safe_pdf_text("Sem lançamentos no período"), border=1, align="C")
            pdf.ln(6)
        else:
            for idx, linha in enumerate(visiveis):
                if idx % 2 == 0:
                    pdf.set_fill_color(245, 247, 250)
                    preencher = True
                else:
                    preencher = False

                data_fmt = _fmt_data(linha.get("data"))
                pdf.cell(larguras[0], 5.5, _safe_pdf_text(data_fmt), border=1, fill=preencher)
                pdf.cell(larguras[1], 5.5, _safe_pdf_text(linha["categoria"][:22]), border=1, fill=preencher)
                pdf.cell(larguras[2], 5.5, _safe_pdf_text(linha["descricao"][:36]), border=1, fill=preencher)
                pdf.cell(larguras[3], 5.5, _safe_pdf_text(format_currency(linha["prevista"])), border=1, align="R", fill=preencher)
                pdf.cell(larguras[4], 5.5, _safe_pdf_text(format_currency(linha["realizada"])), border=1, align="R", fill=preencher)
                pdf.ln(5.5)

        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(sum(larguras[:3]), 6, _safe_pdf_text(f"Total {titulo.lower()}"), border=1, align="R")
        pdf.cell(larguras[3] + larguras[4], 6, _safe_pdf_text(format_currency(total)), border=1, align="R")
        pdf.ln(10)

    tabela("Receitas", receitas, total_receita)
    tabela("Despesas", despesas, total_despesa)

    if resumo_diario:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _safe_pdf_text("Resumo por dia"), **quebra(pdf))

        larguras = [30, 40, 40, 40, 40]
        cabecalhos = ["Data", "Receita", "Despesa", "Saldo do dia", "Acumulado"]
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(161, 98, 7)
        pdf.set_text_color(255, 255, 255)
        for largura_col, titulo_col in zip(larguras, cabecalhos):
            pdf.cell(largura_col, 6, _safe_pdf_text(titulo_col), border=1, align="C", fill=True)
        pdf.ln(6)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 8)

        for linha in resumo_diario:
            pdf.cell(larguras[0], 5.5, _safe_pdf_text(_fmt_data(linha["data"])), border=1)
            pdf.cell(larguras[1], 5.5, _safe_pdf_text(format_currency(linha["receita"])), border=1, align="R")
            pdf.cell(larguras[2], 5.5, _safe_pdf_text(format_currency(linha["despesa"])), border=1, align="R")
            pdf.cell(larguras[3], 5.5, _safe_pdf_text(format_currency(linha["saldo"])), border=1, align="R")
            pdf.cell(larguras[4], 5.5, _safe_pdf_text(format_currency(linha["saldo_acumulado"])), border=1, align="R")
            pdf.ln(5.5)

    saida = pdf.output()
    conteudo = bytes(saida) if isinstance(saida, (bytes, bytearray)) else str(saida).encode("latin-1")

    if start == end:
        filename = f"fluxo_fundeb_{start:%Y%m%d}.pdf"
    else:
        filename = f"fluxo_fundeb_{start:%Y%m%d}_a_{end:%Y%m%d}.pdf"

    return conteudo, filename


def _fmt_data(value) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    texto = str(value)
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return texto


def nome_mes(mes: int) -> str:
    return MESES_PT[mes - 1] if 1 <= mes <= 12 else str(mes)
