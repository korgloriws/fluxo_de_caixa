"""Acesso ao banco SQLite. Mantém o mesmo schema e semântica do app original.

Convenção herdada da versão Streamlit:
    valor1 = valor previsto
    valor2 = valor realizado
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Iterable, Iterator, Optional

from .config import CATEGORIA_AJUSTE_SALDO, SOURCE_AJUSTE_SALDO, get_db_path
from .finance import clean_text, parse_number

TIPOS = ("receita", "despesa")
AJUSTE_SOURCE_LIKE = f"{SOURCE_AJUSTE_SALDO}:%"


def eh_ajuste_saldo(source: Optional[str]) -> bool:
    texto = clean_text(source)
    return texto.startswith(f"{SOURCE_AJUSTE_SALDO}:")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS movimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data DATE NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('receita','despesa')),
                descricao TEXT,
                valor1 REAL DEFAULT 0,
                valor2 REAL DEFAULT 0,
                valor_total REAL GENERATED ALWAYS AS (COALESCE(valor1,0) + COALESCE(valor2,0)) VIRTUAL,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movimentos_data_tipo ON movimentos (data, tipo);")

        columns = [row[1] for row in conn.execute("PRAGMA table_info('movimentos')").fetchall()]
        if "categoria" not in columns:
            conn.execute("ALTER TABLE movimentos ADD COLUMN categoria TEXT")

        # Registros antigos gravados pelo pandas guardaram a string literal "<NA>".
        conn.execute("UPDATE movimentos SET categoria = '' WHERE categoria = '<NA>'")

    from . import auth, historico

    auth.init_usuarios()
    historico.init_historico()


def _row_to_lancamento(row: sqlite3.Row) -> dict:
    return {
        "categoria": clean_text(row["categoria"]),
        "descricao": clean_text(row["descricao"]),
        "prevista": parse_number(row["valor1"]),
        "realizada": parse_number(row["valor2"]),
    }


def fetch_movimentos(
    start: Optional[date] = None,
    end: Optional[date] = None,
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    busca: Optional[str] = None,
) -> list[dict]:
    query = [
        "SELECT id, data, tipo, categoria, descricao, valor1, valor2, source",
        "FROM movimentos WHERE 1=1",
    ]
    params: list = []

    if start is not None:
        query.append("AND data >= ?")
        params.append(start.isoformat())
    if end is not None:
        query.append("AND data <= ?")
        params.append(end.isoformat())
    if tipo in TIPOS:
        query.append("AND tipo = ?")
        params.append(tipo)
    if categoria:
        query.append("AND categoria = ?")
        params.append(categoria)
    if busca:
        query.append("AND (descricao LIKE ? OR categoria LIKE ?)")
        like = f"%{busca}%"
        params.extend([like, like])

    query.append("ORDER BY data ASC, tipo ASC, id ASC")

    with connect() as conn:
        rows = conn.execute(" ".join(query), params).fetchall()

    return [
        {
            "id": row["id"],
            "data": row["data"],
            "tipo": row["tipo"],
            "categoria": clean_text(row["categoria"]),
            "descricao": clean_text(row["descricao"]),
            "prevista": parse_number(row["valor1"]),
            "realizada": parse_number(row["valor2"]),
            "source": clean_text(row["source"]),
            "ajuste_saldo": eh_ajuste_saldo(row["source"]),
        }
        for row in rows
    ]


def fetch_day(day: date, tipo: str, *, incluir_ajustes: bool = False) -> list[dict]:
    query = [
        "SELECT categoria, descricao, valor1, valor2, source",
        "FROM movimentos",
        "WHERE data = ? AND tipo = ?",
    ]
    params: list = [day.isoformat(), tipo]
    if not incluir_ajustes:
        query.append("AND (source IS NULL OR source NOT LIKE ?)")
        params.append(AJUSTE_SOURCE_LIKE)
    query.append("ORDER BY id ASC")

    with connect() as conn:
        rows = conn.execute(" ".join(query), params).fetchall()
    return [_row_to_lancamento(row) for row in rows]


def replace_day(day: date, tipo: str, rows: Iterable[dict], source: str = "manual") -> int:
    """Substitui lançamentos editáveis do dia/tipo.

    Ajustes de saldo (`ajuste-saldo:*`) são preservados — são imutáveis.
    """
    if tipo not in TIPOS:
        raise ValueError(f"tipo inválido: {tipo}")

    # Nunca regravar um ajuste pela grade diária.
    payload = [
        (
            day.isoformat(),
            tipo,
            clean_text(row.get("descricao")),
            parse_number(row.get("prevista")),
            parse_number(row.get("realizada")),
            source or "manual",
            clean_text(row.get("categoria")),
        )
        for row in rows or []
        if not eh_ajuste_saldo(row.get("source"))
        and clean_text(row.get("categoria")).upper() != CATEGORIA_AJUSTE_SALDO
    ]

    with connect() as conn:
        conn.execute(
            """
            DELETE FROM movimentos
            WHERE data = ? AND tipo = ?
              AND (source IS NULL OR source NOT LIKE ?)
            """,
            (day.isoformat(), tipo, AJUSTE_SOURCE_LIKE),
        )
        if payload:
            conn.executemany(
                """
                INSERT INTO movimentos (data, tipo, descricao, valor1, valor2, source, categoria)
                VALUES (?,?,?,?,?,?,?)
                """,
                payload,
            )

    return len(payload)


def criar_ajuste_saldo(
    day: date,
    valor: float,
    motivo: str,
    *,
    login: str,
) -> dict:
    """Cria lançamento imutável de ajuste de saldo.

    Valor positivo aumenta o saldo (receita); negativo reduz (despesa).
    """
    motivo_limpo = clean_text(motivo)
    if len(motivo_limpo) < 5:
        raise ValueError("Informe o motivo do ajuste com pelo menos 5 caracteres.")

    valor_num = parse_number(valor)
    if valor_num == 0:
        raise ValueError("O valor do ajuste não pode ser zero.")

    tipo = "receita" if valor_num > 0 else "despesa"
    realizado = abs(valor_num)
    source = f"{SOURCE_AJUSTE_SALDO}:{login}"

    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO movimentos (data, tipo, descricao, valor1, valor2, source, categoria)
            VALUES (?, ?, ?, 0, ?, ?, ?)
            """,
            (day.isoformat(), tipo, motivo_limpo, realizado, source, CATEGORIA_AJUSTE_SALDO),
        )
        novo_id = int(cursor.lastrowid)

    return obter_movimento(novo_id)  # type: ignore[return-value]


def obter_movimento(mov_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, data, tipo, categoria, descricao, valor1, valor2, source
            FROM movimentos WHERE id = ?
            """,
            (mov_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "data": row["data"],
        "tipo": row["tipo"],
        "categoria": clean_text(row["categoria"]),
        "descricao": clean_text(row["descricao"]),
        "prevista": parse_number(row["valor1"]),
        "realizada": parse_number(row["valor2"]),
        "source": clean_text(row["source"]),
        "ajuste_saldo": eh_ajuste_saldo(row["source"]),
    }


def excluir_ajuste_saldo(mov_id: int) -> dict:
    atual = obter_movimento(mov_id)
    if not atual:
        raise ValueError("Lançamento não encontrado.")
    if not atual["ajuste_saldo"]:
        raise ValueError("Somente lançamentos de ajuste de saldo podem ser excluídos por esta rota.")

    with connect() as conn:
        conn.execute("DELETE FROM movimentos WHERE id = ?", (mov_id,))
    return atual


def listar_ajustes_saldo(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> list[dict]:
    query = [
        "SELECT id, data, tipo, categoria, descricao, valor1, valor2, source",
        "FROM movimentos",
        "WHERE source LIKE ?",
    ]
    params: list = [AJUSTE_SOURCE_LIKE]
    if start is not None:
        query.append("AND data >= ?")
        params.append(start.isoformat())
    if end is not None:
        query.append("AND data <= ?")
        params.append(end.isoformat())
    query.append("ORDER BY data DESC, id DESC")

    with connect() as conn:
        rows = conn.execute(" ".join(query), params).fetchall()

    return [
        {
            "id": row["id"],
            "data": row["data"],
            "tipo": row["tipo"],
            "categoria": clean_text(row["categoria"]),
            "descricao": clean_text(row["descricao"]),
            "prevista": parse_number(row["valor1"]),
            "realizada": parse_number(row["valor2"]),
            "source": clean_text(row["source"]),
            "ajuste_saldo": True,
            "efeito": parse_number(row["valor2"]) if row["tipo"] == "receita" else -parse_number(row["valor2"]),
        }
        for row in rows
    ]


def _efeito_ajuste(row) -> float:
    valor = float(row["valor2"] or 0.0)
    return -valor if row["tipo"] == "despesa" else valor


def saldo_inicial_do_dia(day: date) -> float:
    """Saldo no começo do dia.

    Se houver corte/ajuste nessa data, o valor do ajuste é a nova base
    (começa a partir dali). Caso contrário, herda o saldo do dia anterior.
    """
    with connect() as conn:
        ajuste = conn.execute(
            """
            SELECT tipo, valor2
            FROM movimentos
            WHERE data = ? AND source LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (day.isoformat(), AJUSTE_SOURCE_LIKE),
        ).fetchone()

    if ajuste:
        return _efeito_ajuste(ajuste)
    return saldo_acumulado_ate(day - timedelta(days=1))


def saldo_acumulado_ate(day: date) -> float:
    """Saldo realizado acumulado até a data (inclusive).

    Se existir um ajuste de saldo na data ou antes dela, esse ajuste vira a
    nova base (saldo inicial). Movimentos operacionais a partir da data do
    ajuste entram em cima dessa base. Ajustes anteriores ficam supersedidos.
    """
    with connect() as conn:
        ajuste = conn.execute(
            """
            SELECT data, tipo, valor2
            FROM movimentos
            WHERE data <= ? AND source LIKE ?
            ORDER BY data DESC, id DESC
            LIMIT 1
            """,
            (day.isoformat(), AJUSTE_SOURCE_LIKE),
        ).fetchone()

        if not ajuste:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN tipo = 'receita' THEN valor2 ELSE -valor2 END), 0)
                FROM movimentos WHERE data <= ?
                """,
                (day.isoformat(),),
            ).fetchone()
            return float(row[0] or 0.0)

        base = _efeito_ajuste(ajuste)

        # Operacional a partir do dia do ajuste (o próprio ajuste não entra de novo).
        row = conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN tipo = 'receita' THEN valor2 ELSE -valor2 END), 0)
            FROM movimentos
            WHERE data >= ? AND data <= ?
              AND (source IS NULL OR source NOT LIKE ?)
            """,
            (ajuste["data"], day.isoformat(), AJUSTE_SOURCE_LIKE),
        ).fetchone()
        return base + float(row[0] or 0.0)


def totais_do_dia(day: date) -> dict:
    """Totais operacionais do dia (ajuste de saldo fica de fora — ele é a base)."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN tipo='receita' THEN valor2 END), 0) AS receita_realizada,
                COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor2 END), 0) AS despesa_realizada,
                COALESCE(SUM(CASE WHEN tipo='receita' THEN valor1 END), 0) AS receita_prevista,
                COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor1 END), 0) AS despesa_prevista
            FROM movimentos
            WHERE data = ?
              AND (source IS NULL OR source NOT LIKE ?)
            """,
            (day.isoformat(), AJUSTE_SOURCE_LIKE),
        ).fetchone()

    return {
        "receita_realizada": float(row["receita_realizada"]),
        "despesa_realizada": float(row["despesa_realizada"]),
        "receita_prevista": float(row["receita_prevista"]),
        "despesa_prevista": float(row["despesa_prevista"]),
    }


def intervalo_disponivel() -> tuple[Optional[str], Optional[str]]:
    with connect() as conn:
        row = conn.execute("SELECT MIN(data), MAX(data) FROM movimentos").fetchone()
    return (row[0], row[1]) if row else (None, None)


def anos_disponiveis() -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(data, 1, 4) AS ano FROM movimentos ORDER BY ano DESC"
        ).fetchall()
    return [int(row["ano"]) for row in rows if row["ano"]]


def categorias_existentes() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT categoria FROM movimentos
            WHERE categoria IS NOT NULL AND TRIM(categoria) <> ''
            ORDER BY categoria
            """
        ).fetchall()
    return [row["categoria"] for row in rows]
