"""Autenticação e cadastro de usuários (PBKDF2 + SQLite)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Any, Optional

from .config import get_seed_admin_login, get_seed_admin_password, get_seed_admin_nome
from .repository import connect

PBKDF2_ITERATIONS = 120_000
HASH_PREFIX = "pbkdf2_sha256"


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt_bytes = (salt or secrets.token_hex(16)).encode("utf-8")
    if salt is None:
        salt = salt_bytes.decode("utf-8")
    else:
        salt_bytes = salt.encode("utf-8")

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERATIONS,
    )
    return f"{HASH_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, iterations_s, salt, digest_hex = stored.split("$", 3)
        if prefix != HASH_PREFIX:
            return False
        iterations = int(iterations_s)
    except (ValueError, AttributeError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(candidate.hex(), digest_hex)


def _row_to_user(row: Any, include_hash: bool = False) -> dict:
    data = {
        "id": row["id"],
        "nome": row["nome"],
        "login": row["login"],
        "eh_admin": bool(row["eh_admin"]),
        "ativo": bool(row["ativo"]),
        "criado_em": row["criado_em"],
    }
    if include_hash:
        data["senha_hash"] = row["senha_hash"]
    return data


def init_usuarios() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                login TEXT NOT NULL UNIQUE COLLATE NOCASE,
                senha_hash TEXT NOT NULL,
                eh_admin INTEGER NOT NULL DEFAULT 0,
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        total = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        if total == 0:
            conn.execute(
                """
                INSERT INTO usuarios (nome, login, senha_hash, eh_admin, ativo)
                VALUES (?, ?, ?, 1, 1)
                """,
                (
                    get_seed_admin_nome(),
                    get_seed_admin_login(),
                    hash_password(get_seed_admin_password()),
                ),
            )


def contar_usuarios() -> int:
    with connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0])


def contar_admins_ativos(exceto_id: Optional[int] = None) -> int:
    with connect() as conn:
        if exceto_id is None:
            row = conn.execute(
                "SELECT COUNT(*) FROM usuarios WHERE eh_admin = 1 AND ativo = 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM usuarios WHERE eh_admin = 1 AND ativo = 1 AND id <> ?",
                (exceto_id,),
            ).fetchone()
    return int(row[0])


def listar_usuarios() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, nome, login, eh_admin, ativo, criado_em
            FROM usuarios
            ORDER BY eh_admin DESC, nome COLLATE NOCASE ASC
            """
        ).fetchall()
    return [_row_to_user(row) for row in rows]


def obter_por_id(user_id: int, include_hash: bool = False) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE id = ?",
            (user_id,),
        ).fetchone()
    return _row_to_user(row, include_hash=include_hash) if row else None


def obter_por_login(login: str, include_hash: bool = False) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE login = ? COLLATE NOCASE",
            (login.strip(),),
        ).fetchone()
    return _row_to_user(row, include_hash=include_hash) if row else None


def autenticar(login: str, senha: str) -> Optional[dict]:
    usuario = obter_por_login(login, include_hash=True)
    if not usuario or not usuario["ativo"]:
        return None
    if not verify_password(senha, usuario["senha_hash"]):
        return None
    usuario.pop("senha_hash", None)
    return usuario


def confirmar_senha(user_id: int, senha: str) -> bool:
    usuario = obter_por_id(user_id, include_hash=True)
    if not usuario or not usuario["ativo"]:
        return False
    return verify_password(senha, usuario["senha_hash"])


def criar_usuario(
    nome: str,
    login: str,
    senha: str,
    *,
    eh_admin: bool = False,
    ativo: bool = True,
) -> dict:
    nome = (nome or "").strip()
    login = (login or "").strip()
    if not nome:
        raise ValueError("Informe o nome.")
    if not login:
        raise ValueError("Informe o login.")
    if len(senha or "") < 4:
        raise ValueError("A senha deve ter pelo menos 4 caracteres.")
    if obter_por_login(login):
        raise ValueError("Já existe um usuário com este login.")

    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO usuarios (nome, login, senha_hash, eh_admin, ativo, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                nome,
                login,
                hash_password(senha),
                1 if eh_admin else 0,
                1 if ativo else 0,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        user_id = int(cursor.lastrowid)

    return obter_por_id(user_id)  # type: ignore[return-value]


def atualizar_usuario(
    user_id: int,
    *,
    nome: Optional[str] = None,
    login: Optional[str] = None,
    senha: Optional[str] = None,
    eh_admin: Optional[bool] = None,
    ativo: Optional[bool] = None,
) -> dict:
    atual = obter_por_id(user_id)
    if not atual:
        raise ValueError("Usuário não encontrado.")

    novo_nome = (nome if nome is not None else atual["nome"]).strip()
    novo_login = (login if login is not None else atual["login"]).strip()
    novo_admin = atual["eh_admin"] if eh_admin is None else bool(eh_admin)
    novo_ativo = atual["ativo"] if ativo is None else bool(ativo)

    if not novo_nome:
        raise ValueError("Informe o nome.")
    if not novo_login:
        raise ValueError("Informe o login.")

    outro = obter_por_login(novo_login)
    if outro and outro["id"] != user_id:
        raise ValueError("Já existe um usuário com este login.")

    # Não permitir desativar / rebaixar o último admin ativo.
    perderia_admin = atual["eh_admin"] and atual["ativo"] and (not novo_admin or not novo_ativo)
    if perderia_admin and contar_admins_ativos(exceto_id=user_id) == 0:
        raise ValueError("Não é possível remover ou desativar o último administrador.")

    campos = ["nome = ?", "login = ?", "eh_admin = ?", "ativo = ?"]
    params: list[Any] = [novo_nome, novo_login, 1 if novo_admin else 0, 1 if novo_ativo else 0]

    if senha is not None and senha != "":
        if len(senha) < 4:
            raise ValueError("A senha deve ter pelo menos 4 caracteres.")
        campos.append("senha_hash = ?")
        params.append(hash_password(senha))

    params.append(user_id)
    with connect() as conn:
        conn.execute(
            f"UPDATE usuarios SET {', '.join(campos)} WHERE id = ?",
            params,
        )

    return obter_por_id(user_id)  # type: ignore[return-value]


def excluir_usuario(user_id: int) -> None:
    atual = obter_por_id(user_id)
    if not atual:
        raise ValueError("Usuário não encontrado.")
    if atual["eh_admin"] and atual["ativo"] and contar_admins_ativos(exceto_id=user_id) == 0:
        raise ValueError("Não é possível excluir o último administrador.")

    with connect() as conn:
        conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
