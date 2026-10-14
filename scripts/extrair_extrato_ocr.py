#!/usr/bin/env python3
"""Extrai texto de extrato BB em PDF imagem (Print to PDF) via OCR.

Uso:
  python scripts/extrair_extrato_ocr.py "C:\\Users\\...\\fundeb CC.pdf"
  python scripts/extrair_extrato_ocr.py arquivo.pdf --saida linhas.txt
  python scripts/extrair_extrato_ocr.py arquivo.pdf --resumo

O mesmo motor é usado automaticamente na importação web quando o PDF
não tem texto selecionável.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import importers, ocr_extrato  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCR de extrato BB (PDF sem texto / Print to PDF)."
    )
    parser.add_argument("pdf", type=Path, help="Caminho do PDF")
    parser.add_argument(
        "--saida",
        "-o",
        type=Path,
        default=None,
        help="Grava as linhas extraídas neste .txt",
    )
    parser.add_argument(
        "--resumo",
        action="store_true",
        help="Mostra receitas classificadas por dia (mesmo parser da importação).",
    )
    args = parser.parse_args()

    if not args.pdf.is_file():
        print(f"Arquivo não encontrado: {args.pdf}", file=sys.stderr)
        return 1

    if not ocr_extrato.ocr_disponivel():
        print(
            "Dependências de OCR ausentes. Instale:\n"
            "  pip install pymupdf rapidocr-onnxruntime",
            file=sys.stderr,
        )
        return 2

    bruto = args.pdf.read_bytes()
    print(f"Lendo {args.pdf.name} ({len(bruto)} bytes)…")
    if importers.pdf_tem_texto_selecionavel(bruto):
        print("PDF já tem texto selecionável — usando extração normal (sem OCR).")
        linhas = importers.extract_lines_from_pdf(bruto, permitir_ocr=False)
    else:
        print("PDF sem texto — aplicando OCR (pode levar alguns segundos)…")
        linhas = ocr_extrato.extract_lines_from_pdf_ocr(bruto)

    print(f"{len(linhas)} linha(s) extraída(s).\n")
    for i, linha in enumerate(linhas, 1):
        print(f"{i:03d}| {linha}")

    if args.saida:
        args.saida.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        print(f"\nSalvo em {args.saida}")

    if args.resumo:
        print("\n=== Receitas detectadas ===")
        dias = importers.datas_nas_linhas(linhas)
        if not dias:
            print("Nenhuma data de movimento encontrada.")
            return 0
        for dia in dias:
            receitas = importers.receita_do_extrato(dia, bruto, lines=linhas)
            detalhe = [
                (r["descricao"], r["realizada"])
                for r in receitas
                if r.get("realizada")
            ]
            total = sum(v for _, v in detalhe)
            print(f"\n{dia.isoformat()} — total R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            for desc, valor in detalhe:
                print(f"  · {desc}: R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
