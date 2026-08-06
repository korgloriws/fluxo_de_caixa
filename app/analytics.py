"""Agregações que alimentam os gráficos e indicadores do painel.

Tudo é calculado direto no SQLite para manter a resposta rápida mesmo com o
histórico completo carregado.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .repository import AJUSTE_SOURCE_LIKE, connect, saldo_acumulado_ate, saldo_inicial_do_dia


def _filtros(
    start: date,
    end: date,
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    busca: Optional[str] = None,
    *,
    excluir_ajustes: bool = False,
) -> tuple[str, list]:
    clausulas = ["data >= ?", "data <= ?"]
    params: list = [start.isoformat(), end.isoformat()]

    if tipo in ("receita", "despesa"):
        clausulas.append("tipo = ?")
        params.append(tipo)
    if categoria:
        clausulas.append("categoria = ?")
        params.append(categoria)
    if busca:
        clausulas.append("(descricao LIKE ? OR categoria LIKE ?)")
        like = f"%{busca}%"
        params.extend([like, like])
    if excluir_ajustes:
        clausulas.append("(source IS NULL OR source NOT LIKE ?)")
        params.append(AJUSTE_SOURCE_LIKE)

    return " AND ".join(clausulas), params


def indicadores(start: date, end: date, **filtros) -> dict:
    """Totais do período mais o saldo herdado dos dias anteriores."""
    where, params = _filtros(start, end, excluir_ajustes=True, **filtros)

    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN tipo='receita' THEN valor2 END), 0) AS receita_realizada,
                COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor2 END), 0) AS despesa_realizada,
                COALESCE(SUM(CASE WHEN tipo='receita' THEN valor1 END), 0) AS receita_prevista,
                COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor1 END), 0) AS despesa_prevista,
                COUNT(*) AS lancamentos,
                COUNT(DISTINCT data) AS dias
            FROM movimentos WHERE {where}
            """,
            params,
        ).fetchone()

    saldo_inicial = saldo_inicial_do_dia(start)
    saldo_final = saldo_acumulado_ate(end)
    receita = float(row["receita_realizada"])
    despesa = float(row["despesa_realizada"])

    return {
        "receita_realizada": receita,
        "despesa_realizada": despesa,
        "receita_prevista": float(row["receita_prevista"]),
        "despesa_prevista": float(row["despesa_prevista"]),
        "resultado": receita - despesa,
        "saldo_inicial": saldo_inicial,
        "saldo_final": saldo_final,
        "lancamentos": int(row["lancamentos"]),
        "dias_com_movimento": int(row["dias"]),
        "media_diaria_receita": receita / int(row["dias"]) if row["dias"] else 0.0,
        "media_diaria_despesa": despesa / int(row["dias"]) if row["dias"] else 0.0,
    }


def evolucao_diaria(start: date, end: date, **filtros) -> dict:
    """Gráfico 1 — receita, despesa e saldo acumulado dia a dia."""
    where, params = _filtros(start, end, excluir_ajustes=True, **filtros)

    with connect() as conn:
        linhas = conn.execute(
            f"""
            SELECT data,
                   COALESCE(SUM(CASE WHEN tipo='receita' THEN valor2 END), 0) AS receita,
                   COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor2 END), 0) AS despesa
            FROM movimentos WHERE {where}
            GROUP BY data ORDER BY data
            """,
            params,
        ).fetchall()

    saldo_inicial = saldo_inicial_do_dia(start)

    pontos = []
    for linha in linhas:
        receita = float(linha["receita"])
        despesa = float(linha["despesa"])
        dia = date.fromisoformat(str(linha["data"])[:10])
        pontos.append(
            {
                "data": linha["data"],
                "receita": receita,
                "despesa": despesa,
                "saldo": receita - despesa,
                "saldo_acumulado": saldo_acumulado_ate(dia),
            }
        )

    return {"saldo_inicial": saldo_inicial, "pontos": pontos}


def composicao_por_categoria(start: date, end: date, **filtros) -> dict:
    """Gráfico 2 — de onde vem a receita e para onde vai a despesa."""
    where, params = _filtros(start, end, **filtros)

    with connect() as conn:
        linhas = conn.execute(
            f"""
            SELECT tipo,
                   CASE WHEN categoria IS NULL OR TRIM(categoria) = '' THEN 'SEM CATEGORIA'
                        ELSE categoria END AS categoria,
                   COALESCE(SUM(valor2), 0) AS realizada,
                   COALESCE(SUM(valor1), 0) AS prevista,
                   COUNT(*) AS lancamentos
            FROM movimentos WHERE {where}
            GROUP BY tipo, categoria
            HAVING realizada <> 0 OR prevista <> 0
            ORDER BY realizada DESC
            """,
            params,
        ).fetchall()

    resultado = {"receita": [], "despesa": []}
    for linha in linhas:
        resultado[linha["tipo"]].append(
            {
                "categoria": linha["categoria"],
                "realizada": float(linha["realizada"]),
                "prevista": float(linha["prevista"]),
                "lancamentos": int(linha["lancamentos"]),
            }
        )

    for tipo in resultado:
        total = sum(item["realizada"] for item in resultado[tipo])
        for item in resultado[tipo]:
            item["participacao"] = (item["realizada"] / total * 100) if total else 0.0

    return resultado


def previsto_versus_realizado(start: date, end: date, **filtros) -> dict:
    """Gráfico 3 — desvio entre o que foi planejado e o que aconteceu."""
    where, params = _filtros(start, end, **filtros)

    with connect() as conn:
        linhas = conn.execute(
            f"""
            SELECT tipo,
                   CASE WHEN categoria IS NULL OR TRIM(categoria) = '' THEN 'SEM CATEGORIA'
                        ELSE categoria END AS categoria,
                   COALESCE(SUM(valor1), 0) AS prevista,
                   COALESCE(SUM(valor2), 0) AS realizada
            FROM movimentos WHERE {where}
            GROUP BY tipo, categoria
            HAVING prevista <> 0 OR realizada <> 0
            ORDER BY tipo, categoria
            """,
            params,
        ).fetchall()

    resultado = {"receita": [], "despesa": []}
    for linha in linhas:
        prevista = float(linha["prevista"])
        realizada = float(linha["realizada"])
        desvio = realizada - prevista
        resultado[linha["tipo"]].append(
            {
                "categoria": linha["categoria"],
                "prevista": prevista,
                "realizada": realizada,
                "desvio": desvio,
                "desvio_pct": (desvio / prevista * 100) if prevista else None,
                "execucao_pct": (realizada / prevista * 100) if prevista else None,
            }
        )

    return resultado


def comparativo_mensal(anos: Optional[list[int]] = None) -> dict:
    """Gráfico 4 — receita e despesa por mês, comparando anos."""
    query = """
        SELECT substr(data, 1, 4) AS ano,
               CAST(substr(data, 6, 2) AS INTEGER) AS mes,
               COALESCE(SUM(CASE WHEN tipo='receita' THEN valor2 END), 0) AS receita,
               COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor2 END), 0) AS despesa
        FROM movimentos
    """
    params: list = []
    if anos:
        marcadores = ",".join("?" for _ in anos)
        query += f" WHERE substr(data, 1, 4) IN ({marcadores})"
        params = [str(a) for a in anos]
    query += " GROUP BY ano, mes ORDER BY ano, mes"

    with connect() as conn:
        linhas = conn.execute(query, params).fetchall()

    por_ano: dict[int, dict] = {}
    for linha in linhas:
        ano = int(linha["ano"])
        registro = por_ano.setdefault(
            ano, {"ano": ano, "receita": [0.0] * 12, "despesa": [0.0] * 12}
        )
        indice = int(linha["mes"]) - 1
        registro["receita"][indice] = float(linha["receita"])
        registro["despesa"][indice] = float(linha["despesa"])

    series = []
    for ano in sorted(por_ano):
        registro = por_ano[ano]
        acumulado = 0.0
        acumulados = []
        for i in range(12):
            acumulado += registro["receita"][i] - registro["despesa"][i]
            acumulados.append(acumulado)
        registro["acumulado"] = acumulados
        registro["total_receita"] = sum(registro["receita"])
        registro["total_despesa"] = sum(registro["despesa"])
        series.append(registro)

    return {"series": series}


def calendario(ano: int, mes: Optional[int] = None) -> dict:
    """Gráfico 5 — intensidade de movimentação por dia."""
    if mes:
        prefixo = f"{ano:04d}-{mes:02d}"
    else:
        prefixo = f"{ano:04d}"

    with connect() as conn:
        linhas = conn.execute(
            """
            SELECT data,
                   COALESCE(SUM(CASE WHEN tipo='receita' THEN valor2 END), 0) AS receita,
                   COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor2 END), 0) AS despesa,
                   COUNT(*) AS lancamentos
            FROM movimentos
            WHERE substr(data, 1, ?) = ?
            GROUP BY data ORDER BY data
            """,
            (len(prefixo), prefixo),
        ).fetchall()

    dias = [
        {
            "data": linha["data"],
            "receita": float(linha["receita"]),
            "despesa": float(linha["despesa"]),
            "saldo": float(linha["receita"]) - float(linha["despesa"]),
            "lancamentos": int(linha["lancamentos"]),
        }
        for linha in linhas
    ]

    return {"ano": ano, "mes": mes, "dias": dias}


def ranking(start: date, end: date, limite: int = 10, **filtros) -> dict:
    """Gráfico 6 — maiores entradas e saídas individuais do período."""
    where, params = _filtros(start, end, **filtros)

    def consultar(tipo: str) -> list[dict]:
        with connect() as conn:
            linhas = conn.execute(
                f"""
                SELECT data, categoria, descricao, valor2 AS realizada
                FROM movimentos
                WHERE {where} AND tipo = ? AND valor2 > 0
                ORDER BY valor2 DESC LIMIT ?
                """,
                [*params, tipo, limite],
            ).fetchall()
        return [
            {
                "data": linha["data"],
                "categoria": linha["categoria"] or "SEM CATEGORIA",
                "descricao": linha["descricao"] or "",
                "valor": float(linha["realizada"]),
            }
            for linha in linhas
        ]

    return {"entradas": consultar("receita"), "saidas": consultar("despesa")}


def resumo_diario(start: date, end: date, **filtros) -> list[dict]:
    """Tabela usada nas exportações: um registro por dia com saldo acumulado."""
    return evolucao_diaria(start, end, **filtros)["pontos"]
