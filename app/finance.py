"""Regras de negócio puras: conversão de valores, templates de lançamento e trava de mês.

Nenhuma função deste módulo acessa banco, rede ou framework web.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

# Cada lançamento é um dicionário com estas quatro chaves.
LANCAMENTO_FIELDS = ("categoria", "descricao", "prevista", "realizada")


def parse_number(value: Any) -> float:
    """Converte texto em número aceitando o formato brasileiro (1.234,56).

    Mantém a mesma tolerância do app original: qualquer entrada inválida vira 0.
    """
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        try:
            if value != value:  # NaN
                return 0.0
        except TypeError:
            return 0.0
        return float(value)

    text = str(value).strip()
    if text in ("", "-", "nan", "NaN", "None", "<NA>"):
        return 0.0

    text = text.replace("R$", "").replace(" ", "").replace("\xa0", "")

    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("()").lstrip("-")

    # No padrão brasileiro o ponto separa milhar e a vírgula separa centavos.
    if "," in text:
        text = text.replace(".", "").replace(",", ".")

    try:
        number = float(text)
    except ValueError:
        return 0.0

    return -number if negative else number


def format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_number_br(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text in ("nan", "NaN", "None", "<NA>"):
        return ""
    return text


# ------------------------------------------------------------------
# Templates padrão do formulário diário
# ------------------------------------------------------------------


def _rows(pairs: Iterable[tuple[str, str]]) -> list[dict]:
    return [
        {"categoria": categoria, "descricao": descricao, "prevista": 0.0, "realizada": 0.0}
        for categoria, descricao in pairs
    ]


def receita_template() -> list[dict]:
    return _rows(
        [
            ("IMPOSTOS", "ORIGEM ITR"),
            ("IMPOSTOS", "ORIGEM IPVA"),
            ("IMPOSTOS", "ORIGEM ITCMD"),
            ("IMPOSTOS", "ORIGEM IPI-EXP"),
            ("IMPOSTOS", "ORIGEM ICMS"),
            ("IMPOSTOS", "ORIGEM FPE"),
            ("IMPOSTOS", "ORIGEM FPM"),
            ("IMPOSTOS", "ORIG LC 198/23"),
            ("IMPOSTOS", "OUTROS"),
            ("RENDIMENTOS", "RENDIMENTOS"),
            ("OUTROS", "Editável"),
        ]
    )


def despesa_template() -> list[dict]:
    return _rows(
        [
            ("FOLHA DE PAGAMENTO", "PROFESSOR (70%)"),
            ("FOLHA DE PAGAMENTO", "ADMINISTRATIVO"),
            ("VALE REFEIÇÃO", "PROFESSOR (70%)"),
            ("VALE REFEIÇÃO", "ADMINISTRATIVO"),
            ("VALE TRANSPORTE", "PROFESSOR (70%)"),
            ("VALE TRANSPORTE", "ADMINISTRATIVO"),
            ("ONG", "Editável"),
            ("CUSTEIO", "Editável"),
            ("OUTROS", "Editável"),
        ]
    )


def template_for(tipo: str) -> list[dict]:
    return receita_template() if tipo == "receita" else despesa_template()


def normalize_lancamentos(rows: Iterable[dict]) -> list[dict]:
    """Garante as quatro chaves esperadas, com valores numéricos já convertidos."""
    normalized = []
    for row in rows or []:
        normalized.append(
            {
                "categoria": clean_text(row.get("categoria")),
                "descricao": clean_text(row.get("descricao")),
                "prevista": parse_number(row.get("prevista")),
                "realizada": parse_number(row.get("realizada")),
            }
        )
    return normalized


def merge_with_template(rows: Iterable[dict], template: list[dict]) -> list[dict]:
    """Exibe sempre as linhas do template, na ordem, preservando linhas extras do usuário.

    A chave de correspondência é (categoria, descrição), igual ao app original.
    """
    existing = normalize_lancamentos(rows)
    by_key: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []

    for row in existing:
        key = (row["categoria"].upper(), row["descricao"].upper())
        if key in by_key:
            # Linhas duplicadas somam, evitando perder valores importados.
            by_key[key]["prevista"] += row["prevista"]
            by_key[key]["realizada"] += row["realizada"]
        else:
            by_key[key] = dict(row)
            order.append(key)

    merged: list[dict] = []
    used: set[tuple[str, str]] = set()

    for tpl_row in template:
        key = (tpl_row["categoria"].upper(), tpl_row["descricao"].upper())
        used.add(key)
        merged.append(dict(by_key[key]) if key in by_key else dict(tpl_row))

    for key in order:
        if key not in used:
            merged.append(dict(by_key[key]))

    return merged


def total_realizada(rows: Iterable[dict]) -> float:
    return float(sum(parse_number(r.get("realizada")) for r in rows or []))


def total_prevista(rows: Iterable[dict]) -> float:
    return float(sum(parse_number(r.get("prevista")) for r in rows or []))


# ------------------------------------------------------------------
# Trava de edição de meses encerrados
# ------------------------------------------------------------------


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def is_past_month(target: date, today: date | None = None) -> bool:
    reference = today or date.today()
    return (target.year, target.month) < (reference.year, reference.month)


def can_edit_day(
    target: date,
    unlocked_months: Iterable[str],
    today: date | None = None,
    *,
    autenticado: bool = False,
) -> bool:
    """Edição exige usuário autenticado.

    Mês corrente/futuro: basta estar logado.
    Mês histórico: logado e mês liberado na sessão (após confirmar senha).
    """
    if not autenticado:
        return False
    if not is_past_month(target, today):
        return True
    return month_key(target) in set(unlocked_months or [])


# ------------------------------------------------------------------
# Períodos
# ------------------------------------------------------------------


def resolve_period(periodo: str, base_day: date) -> tuple[date, date]:
    """Traduz um atalho de período em intervalo de datas."""
    if periodo == "hoje":
        return base_day, base_day

    if periodo == "semana":
        start = base_day - timedelta(days=base_day.weekday())
        return start, start + timedelta(days=6)

    if periodo == "mes":
        start = base_day.replace(day=1)
        return start, last_day_of_month(start)

    if periodo == "mes_anterior":
        first_this_month = base_day.replace(day=1)
        end = first_this_month - timedelta(days=1)
        return end.replace(day=1), end

    if periodo == "ano":
        return date(base_day.year, 1, 1), date(base_day.year, 12, 31)

    if periodo == "12meses":
        start = (base_day.replace(day=1) - timedelta(days=334)).replace(day=1)
        return start, base_day

    return base_day, base_day


def last_day_of_month(day: date) -> date:
    if day.month == 12:
        next_month = day.replace(year=day.year + 1, month=1, day=1)
    else:
        next_month = day.replace(month=day.month + 1, day=1)
    return next_month - timedelta(days=1)


MESES_PT = [
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
]

MESES_PT_LONGO = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
