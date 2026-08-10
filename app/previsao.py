"""Previsão mensal: aplica o mesmo valor em todos os itens, em todos os dias do mês."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from . import historico, repository
from .config import (
    CATEGORIA_PREVISAO_MENSAL,
    DESCRICAO_PREVISAO_MENSAL,
    SOURCE_PREVISAO_MENSAL,
)
from .finance import (
    clean_text,
    last_day_of_month,
    merge_with_template,
    month_key,
    parse_number,
    tem_detalhe_despesa,
    template_for,
)


def eh_linha_previsao_mensal(row: dict | None) -> bool:
    """Linha legada da versão com rateio — removida ao reaplicar."""
    if not row:
        return False
    cat = clean_text(row.get("categoria")).upper()
    desc = clean_text(row.get("descricao")).upper()
    return cat == CATEGORIA_PREVISAO_MENSAL.upper() and desc == DESCRICAO_PREVISAO_MENSAL.upper()


def marcar_linhas_previsao(linhas: list[dict], *, travada_prevista: bool) -> list[dict]:
    """Marca todas as linhas: a coluna Prevista fica travada para não-admin."""
    saida = []
    for row in linhas or []:
        item = dict(row)
        item["previsao_mensal"] = bool(travada_prevista)
        item["travada_prevista"] = bool(travada_prevista)
        item["travada"] = False
        saida.append(item)
    return saida


def proteger_linhas_ao_salvar(
    antes: list[dict],
    depois: list[dict],
    *,
    eh_admin: bool,
    valor_previsao: Optional[float] = None,
) -> list[dict]:
    """Se há previsão mensal e o usuário não é admin, força o valor previsto em todas as linhas."""
    saida = []
    for row in depois or []:
        item = dict(row)
        if eh_linha_previsao_mensal(item):
            continue
        if valor_previsao is not None and not eh_admin:
            item["prevista"] = float(valor_previsao)
        saida.append(item)

    if valor_previsao is not None and not eh_admin and not saida and antes:
        # Evita sumir com o dia se o cliente mandou só a linha legada.
        for row in antes:
            if eh_linha_previsao_mensal(row):
                continue
            item = dict(row)
            item["prevista"] = float(valor_previsao)
            saida.append(item)
    return saida


def init_previsoes() -> None:
    with repository.connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS previsoes_mensais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ano_mes TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('receita','despesa')),
                valor REAL NOT NULL DEFAULT 0,
                dias INTEGER NOT NULL,
                valor_diario REAL NOT NULL DEFAULT 0,
                usuario_id INTEGER,
                usuario_login TEXT,
                criado_em TIMESTAMP NOT NULL,
                atualizado_em TIMESTAMP NOT NULL,
                UNIQUE (ano_mes, tipo)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_previsoes_ano_mes ON previsoes_mensais (ano_mes);"
        )


def obter(ano_mes: str, tipo: str) -> Optional[dict]:
    with repository.connect() as conn:
        row = conn.execute(
            """
            SELECT id, ano_mes, tipo, valor, dias, valor_diario,
                   usuario_id, usuario_login, criado_em, atualizado_em
            FROM previsoes_mensais
            WHERE ano_mes = ? AND tipo = ?
            """,
            (ano_mes, tipo),
        ).fetchone()
    return _row_to_dict(row) if row else None


def listar_mes(ano_mes: str) -> dict[str, Optional[dict]]:
    return {
        "receita": obter(ano_mes, "receita"),
        "despesa": obter(ano_mes, "despesa"),
        "ano_mes": ano_mes,
    }


def _row_to_dict(row: Any) -> dict:
    return {
        "id": row["id"],
        "ano_mes": row["ano_mes"],
        "tipo": row["tipo"],
        "valor": float(row["valor"] or 0),
        "dias": int(row["dias"] or 0),
        "valor_diario": float(row["valor_diario"] or 0),
        "usuario_id": row["usuario_id"],
        "usuario_login": row["usuario_login"],
        "criado_em": row["criado_em"],
        "atualizado_em": row["atualizado_em"],
    }


def _upsert_registro(
    ano_mes: str,
    tipo: str,
    valor: float,
    dias: int,
    usuario: dict,
) -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    # valor_diario guarda o mesmo valor (aplicado igual em cada dia/item).
    with repository.connect() as conn:
        existente = conn.execute(
            "SELECT id FROM previsoes_mensais WHERE ano_mes = ? AND tipo = ?",
            (ano_mes, tipo),
        ).fetchone()
        if existente:
            conn.execute(
                """
                UPDATE previsoes_mensais
                SET valor = ?, dias = ?, valor_diario = ?,
                    usuario_id = ?, usuario_login = ?, atualizado_em = ?
                WHERE id = ?
                """,
                (
                    valor,
                    dias,
                    valor,
                    usuario.get("id"),
                    usuario.get("login"),
                    agora,
                    existente["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO previsoes_mensais (
                    ano_mes, tipo, valor, dias, valor_diario,
                    usuario_id, usuario_login, criado_em, atualizado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ano_mes,
                    tipo,
                    valor,
                    dias,
                    valor,
                    usuario.get("id"),
                    usuario.get("login"),
                    agora,
                    agora,
                ),
            )
    return obter(ano_mes, tipo)  # type: ignore[return-value]


def _remover_registro(ano_mes: str, tipo: str) -> None:
    with repository.connect() as conn:
        conn.execute(
            "DELETE FROM previsoes_mensais WHERE ano_mes = ? AND tipo = ?",
            (ano_mes, tipo),
        )


def _montar_linhas_do_dia(dia: date, tipo: str, valor_prevista: float, source: str) -> list[dict]:
    existentes = [
        dict(r)
        for r in repository.fetch_day(dia, tipo, incluir_ajustes=False)
        if not eh_linha_previsao_mensal(r)
    ]
    # Despesa importada (CSV) não deve voltar ao template de folha/vale.
    if tipo == "despesa" and tem_detalhe_despesa(existentes):
        linhas = existentes
    else:
        linhas = merge_with_template(existentes, template_for(tipo))
    for linha in linhas:
        linha["prevista"] = float(valor_prevista)
        if not linha.get("source"):
            linha["source"] = source
    return linhas


def _aplicar_nos_dias(
    inicio: date,
    fim: date,
    tipo: str,
    valor_prevista: float,
    *,
    source: str,
) -> int:
    """Grava o mesmo valor previsto em todos os itens de todos os dias do mês."""
    alterados = 0
    dia = inicio
    while dia <= fim:
        linhas = _montar_linhas_do_dia(dia, tipo, valor_prevista, source)
        repository.replace_day(dia, tipo, linhas, source=source)
        alterados += 1
        dia = date.fromordinal(dia.toordinal() + 1)
    return alterados


def cadastrar_ou_atualizar(
    ano: int,
    mes: int,
    *,
    receita: Optional[float],
    despesa: Optional[float],
    usuario: dict,
) -> dict:
    """Cadastra/atualiza previsão do mês.

    O valor informado é aplicado integralmente em cada item (receita ou despesa),
    em todos os dias do mês — sem rateio e sem linha extra.

    - Primeiro cadastro de um tipo: qualquer editor autenticado.
    - Alteração posterior: somente administrador.
    Valor 0 remove a previsão daquele tipo (zera previstas; somente admin se já existia).
    """
    if mes < 1 or mes > 12:
        raise ValueError("Mês inválido.")
    if ano < 2000 or ano > 2100:
        raise ValueError("Ano inválido.")

    inicio = date(ano, mes, 1)
    fim = last_day_of_month(inicio)
    dias = fim.day
    ano_mes = month_key(inicio)
    origem = f"{SOURCE_PREVISAO_MENSAL}:{usuario.get('login')}"
    eh_admin = bool(usuario.get("eh_admin"))
    resultado: dict[str, Any] = {
        "ano_mes": ano_mes,
        "receita": None,
        "despesa": None,
        "dias_atualizados": 0,
    }

    for tipo, valor_opcional in (("receita", receita), ("despesa", despesa)):
        if valor_opcional is None:
            resultado[tipo] = obter(ano_mes, tipo)
            continue

        valor = parse_number(valor_opcional)
        if valor < 0:
            raise ValueError(f"A previsão de {tipo} não pode ser negativa.")

        atual = obter(ano_mes, tipo)
        if atual and not eh_admin:
            raise PermissionError(
                f"A previsão de {tipo} de {ano_mes} já foi cadastrada. "
                "Somente o administrador pode alterá-la."
            )

        if valor == 0:
            if not atual:
                resultado[tipo] = None
                continue
            if not eh_admin:
                raise PermissionError(
                    f"Somente o administrador pode remover a previsão de {tipo}."
                )
            _aplicar_nos_dias(inicio, fim, tipo, 0.0, source=origem)
            _remover_registro(ano_mes, tipo)
            historico.registrar(
                acao="previsao_mensal",
                data_ref=inicio,
                tipo=tipo,
                usuario=usuario,
                origem=origem,
                antes=[{"valor": atual["valor"]}],
                depois=[{"valor": 0}],
            )
            resultado[tipo] = None
            resultado["dias_atualizados"] = dias
            continue

        _aplicar_nos_dias(inicio, fim, tipo, valor, source=origem)
        registro = _upsert_registro(ano_mes, tipo, valor, dias, usuario)
        historico.registrar(
            acao="previsao_mensal",
            data_ref=inicio,
            tipo=tipo,
            usuario=usuario,
            origem=origem,
            antes=[{"valor": atual["valor"]}] if atual else [],
            depois=[{"valor": valor, "dias": dias}],
        )
        resultado[tipo] = registro
        resultado["dias_atualizados"] = dias

    return resultado
