"""OCR de extratos BB em PDF sem texto (Print to PDF / captura).

Renderiza cada página com PyMuPDF e lê com RapidOCR. O texto é normalizado
para o mesmo parser de linhas do extrato com camada de texto.
"""

from __future__ import annotations

import io
import re
from typing import Optional

# Tokens que o OCR costuma colar em números/histórico do extrato BB.
_TOKENS_OCR = (
    "RECEBIMENTODEICMS",
    "RECEBIMENTO",
    "ITCMD",
    "IPVA",
    "ITR",
    "ICMS",
    "FPM",
    "IPI",
    "SALDO",
    "ANTERIOR",
)


def ocr_disponivel() -> bool:
    try:
        import fitz  # noqa: F401
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401

        return True
    except ImportError:
        return False


def normalizar_texto_ocr(texto: str) -> str:
    """Insere espaços em palavras-chave coladas pelo OCR."""
    t = str(texto or "")
    t = re.sub(
        r"RECEBIMENTO\s*DE\s*ICMS|RECEBIMENTODEICMS",
        "RECEBIMENTO DE ICMS",
        t,
        flags=re.IGNORECASE,
    )
    for token in _TOKENS_OCR:
        if token.upper() == "RECEBIMENTODEICMS":
            continue
        t = re.sub(
            rf"(?<=[A-Za-z0-9])({re.escape(token)})(?![A-Za-z])",
            r" \1",
            t,
            flags=re.IGNORECASE,
        )
    # Valor colado no C/D: 1.234,56C → 1.234,56 C
    t = re.sub(r"(\d,\d{2})\s*([CDcd])\b", r"\1 \2", t)
    # Datas coladas: de14/10/2026ate14/10/2026
    t = re.sub(r"(?<=[a-zA-Z])(\d{2}/\d{2}/\d{4})", r" \1", t)
    t = re.sub(r"(\d{2}/\d{2}/\d{4})(?=[a-zA-Z])", r"\1 ", t)
    return re.sub(r"\s+", " ", t).strip()


def _agrupar_linhas(itens: list[dict], tolerancia_y: float = 14.0) -> list[str]:
    """Agrupa caixas OCR por proximidade vertical (leitura esquerda→direita)."""
    if not itens:
        return []

    itens = sorted(itens, key=lambda i: (i["y"], i["x"]))
    linhas: list[str] = []
    grupo: list[dict] = []
    y_ref: Optional[float] = None

    for item in itens:
        if y_ref is None or abs(item["y"] - y_ref) <= tolerancia_y:
            grupo.append(item)
            y_ref = item["y"] if y_ref is None else (y_ref * 0.65 + item["y"] * 0.35)
            continue
        grupo.sort(key=lambda i: i["x"])
        linhas.append(normalizar_texto_ocr(" ".join(i["texto"] for i in grupo)))
        grupo = [item]
        y_ref = item["y"]

    if grupo:
        grupo.sort(key=lambda i: i["x"])
        linhas.append(normalizar_texto_ocr(" ".join(i["texto"] for i in grupo)))

    return [linha for linha in linhas if linha]


def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def extract_lines_from_pdf_ocr(
    file_bytes: bytes,
    *,
    escala: float = 2.0,
) -> list[str]:
    """Renderiza o PDF e devolve linhas de texto via OCR."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF (pymupdf) não instalado. Rode: pip install pymupdf"
        ) from exc
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "RapidOCR não instalado. Rode: pip install rapidocr-onnxruntime"
        ) from exc

    if not file_bytes:
        return []

    engine = _ocr_engine()
    matriz = fitz.Matrix(escala, escala)
    linhas: list[str] = []

    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        for pagina in doc:
            pixmap = pagina.get_pixmap(matrix=matriz, alpha=False)
            png = pixmap.tobytes("png")
            resultado, _ = engine(png)
            itens: list[dict] = []
            for entrada in resultado or []:
                if not entrada or len(entrada) < 2:
                    continue
                box, texto = entrada[0], str(entrada[1] or "").strip()
                if not texto:
                    continue
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                itens.append(
                    {
                        "texto": texto,
                        "x": min(xs),
                        "y": min(ys),
                    }
                )
            linhas.extend(_agrupar_linhas(itens))

    return linhas


def extrair_para_arquivo(
    caminho_pdf: str,
    caminho_saida: Optional[str] = None,
) -> list[str]:
    """Utilitário de script: lê PDF imagem e opcionalmente grava .txt."""
    with open(caminho_pdf, "rb") as f:
        linhas = extract_lines_from_pdf_ocr(f.read())
    if caminho_saida:
        with open(caminho_saida, "w", encoding="utf-8") as saida:
            saida.write("\n".join(linhas))
            saida.write("\n")
    return linhas
