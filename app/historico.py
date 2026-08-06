"""Histórico de auditoria das alterações de movimentos."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from .finance import format_currency, parse_number, total_realizada
from .repository import connect


def init_historico() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                criado_em TIMESTAMP NOT NULL,
                usuario_id INTEGER,
                usuario_login TEXT,
                usuario_nome TEXT,
                acao TEXT NOT NULL,
                data_ref DATE NOT NULL,
                tipo TEXT,
                origem TEXT,
                resumo TEXT,
                antes_json TEXT,
                depois_json TEXT
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_historico_criado ON historico (criado_em DESC);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_historico_data_ref ON historico (data_ref);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_historico_usuario ON historico (usuario_login);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_historico_acao ON historico (acao);"
        )


def _serializar_linhas(linhas: list[dict]) -> str:
    limpas = []
    for row in linhas or []:
        limpas.append(
            {
                "categoria": row.get("categoria") or "",
                "descricao": row.get("descricao") or "",
                "prevista": round(parse_number(row.get("prevista")), 2),
                "realizada": round(parse_number(row.get("realizada")), 2),
            }
        )
    return json.dumps(limpas, ensure_ascii=False)


def _desserializar_linhas(texto: Optional[str]) -> list[dict]:
    if not texto:
        return []
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        return []
    return dados if isinstance(dados, list) else []


def _resumo_alteracao(antes: list[dict], depois: list[dict]) -> str:
    total_antes = total_realizada(antes)
    total_depois = total_realizada(depois)
    linhas_antes = len([r for r in antes if parse_number(r.get("realizada")) or parse_number(r.get("prevista"))])
    linhas_depois = len([r for r in depois if parse_number(r.get("realizada")) or parse_number(r.get("prevista"))])
    delta = total_depois - total_antes
    sinal = "+" if delta >= 0 else "−"
    return (
        f"{linhas_antes} -> {linhas_depois} linha(s) com valor · "
        f"realizado {format_currency(total_antes)} -> {format_currency(total_depois)} "
        f"({sinal}{format_currency(abs(delta))})"
    )


def registrar(
    *,
    acao: str,
    data_ref: date,
    tipo: Optional[str],
    usuario: Optional[dict],
    origem: str,
    antes: list[dict],
    depois: list[dict],
) -> dict:
    """Grava um evento de auditoria. Retorna o registro criado."""
    agora = datetime.now().isoformat(timespec="seconds")
    resumo = _resumo_alteracao(antes, depois)
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO historico (
                criado_em, usuario_id, usuario_login, usuario_nome,
                acao, data_ref, tipo, origem, resumo, antes_json, depois_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agora,
                (usuario or {}).get("id"),
                (usuario or {}).get("login") or "",
                (usuario or {}).get("nome") or "",
                acao,
                data_ref.isoformat(),
                tipo,
                origem or "",
                resumo,
                _serializar_linhas(antes),
                _serializar_linhas(depois),
            ),
        )
        novo_id = int(cursor.lastrowid)

    return obter(novo_id)  # type: ignore[return-value]


def _row_to_dict(row: Any, *, com_detalhe: bool = False) -> dict:
    item = {
        "id": row["id"],
        "criado_em": row["criado_em"],
        "usuario_id": row["usuario_id"],
        "usuario_login": row["usuario_login"] or "",
        "usuario_nome": row["usuario_nome"] or "",
        "acao": row["acao"],
        "data_ref": row["data_ref"],
        "tipo": row["tipo"],
        "origem": row["origem"] or "",
        "resumo": row["resumo"] or "",
    }
    if com_detalhe:
        item["antes"] = _desserializar_linhas(row["antes_json"])
        item["depois"] = _desserializar_linhas(row["depois_json"])
    return item


def obter(historico_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM historico WHERE id = ?", (historico_id,)).fetchone()
    return _row_to_dict(row, com_detalhe=True) if row else None


def listar(
    *,
    inicio: Optional[date] = None,
    fim: Optional[date] = None,
    data_ref: Optional[date] = None,
    usuario_login: Optional[str] = None,
    acao: Optional[str] = None,
    tipo: Optional[str] = None,
    busca: Optional[str] = None,
    pagina: int = 1,
    por_pagina: int = 25,
) -> dict:
    """Lista o histórico com filtros e paginação."""
    where = ["1=1"]
    params: list[Any] = []

    if inicio is not None:
        where.append("date(criado_em) >= ?")
        params.append(inicio.isoformat())
    if fim is not None:
        where.append("date(criado_em) <= ?")
        params.append(fim.isoformat())
    if data_ref is not None:
        where.append("data_ref = ?")
        params.append(data_ref.isoformat())
    if usuario_login:
        where.append("usuario_login = ? COLLATE NOCASE")
        params.append(usuario_login.strip())
    if acao:
        where.append("acao = ?")
        params.append(acao)
    if tipo in ("receita", "despesa"):
        where.append("tipo = ?")
        params.append(tipo)
    if busca:
        like = f"%{busca.strip()}%"
        where.append(
            "(resumo LIKE ? OR origem LIKE ? OR usuario_nome LIKE ? OR usuario_login LIKE ? OR COALESCE(tipo, '') LIKE ?)"
        )
        params.extend([like, like, like, like, like])

    clausula = " AND ".join(where)
    pagina = max(1, int(pagina or 1))
    por_pagina = max(1, min(int(por_pagina or 25), 100))

    with connect() as conn:
        total = int(
            conn.execute(f"SELECT COUNT(*) FROM historico WHERE {clausula}", params).fetchone()[0]
        )
        total_paginas = max(1, (total + por_pagina - 1) // por_pagina) if total else 1
        if pagina > total_paginas:
            pagina = total_paginas
        offset = (pagina - 1) * por_pagina
        rows = conn.execute(
            f"""
            SELECT * FROM historico
            WHERE {clausula}
            ORDER BY criado_em DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, por_pagina, offset],
        ).fetchall()

    return {
        "itens": [_row_to_dict(row) for row in rows],
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total_paginas": total_paginas,
    }


def opcoes_filtro() -> dict:
    """Usuários e ações já presentes no histórico (para selects)."""
    with connect() as conn:
        usuarios = conn.execute(
            """
            SELECT DISTINCT usuario_login, usuario_nome
            FROM historico
            WHERE usuario_login IS NOT NULL AND TRIM(usuario_login) <> ''
            ORDER BY usuario_nome COLLATE NOCASE, usuario_login COLLATE NOCASE
            """
        ).fetchall()
        acoes = conn.execute(
            """
            SELECT DISTINCT acao FROM historico
            WHERE acao IS NOT NULL AND TRIM(acao) <> ''
            ORDER BY acao
            """
        ).fetchall()

    return {
        "usuarios": [
            {
                "login": row["usuario_login"],
                "nome": row["usuario_nome"] or row["usuario_login"],
            }
            for row in usuarios
        ],
        "acoes": [row["acao"] for row in acoes],
    }
