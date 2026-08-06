"""Configuração central do Fluxo de Caixa FUNDEB."""

from __future__ import annotations

import os

APP_NAME = "FUNDEB"
APP_SHORT_NAME = "FUNDEB"
PORTAL_NAME = "Fluxo de Caixa"
MODULE_NAME = "FUNDEB"
MODULE_DESCRICAO = "Receitas, despesas e saldo diário do fundo."

MODULE_TESOURO_NAME = "Tesouro"
MODULE_TESOURO_DESCRICAO = "Controle e acompanhamento das contas do Tesouro."
MODULE_TESOURO_PRONTO = False

# Seed do admin e sessão: somente via variáveis de ambiente (.env).
# Nenhuma senha ou segredo fica embutido no código.
DEFAULT_ADMIN_LOGIN = "admin"
DEFAULT_ADMIN_NOME = "Administrador"

CATEGORIAS_RECEITA = ["IMPOSTOS", "RENDIMENTOS", "OUTROS"]

CATEGORIAS_DESPESA = [
    "FOLHA DE PAGAMENTO",
    "VALE REFEIÇÃO",
    "VALE TRANSPORTE",
    "ONG",
    "CUSTEIO",
    "OUTROS",
]


CATEGORIA_AJUSTE_SALDO = "AJUSTE DE SALDO"
SOURCE_AJUSTE_SALDO = "ajuste-saldo"


def get_base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_dir(env_names: tuple[str, ...], fallback: str) -> str:
    candidate = None
    for name in env_names:
        value = os.environ.get(name)
        if value:
            candidate = value
            break

    if candidate:
        path = os.path.expanduser(str(candidate)).strip()
        if not os.path.isabs(path):
            path = os.path.abspath(os.path.join(get_base_dir(), path))
    else:
        path = os.path.join(get_base_dir(), fallback)

    os.makedirs(path, exist_ok=True)
    return path


def get_data_dir() -> str:
    return _resolve_dir(("DATA_DIR", "APP_DATA_DIR"), "data")


def get_uploads_dir() -> str:
    return _resolve_dir(("UPLOADS_DIR",), "uploads")


def get_exports_dir() -> str:
    return _resolve_dir(("EXPORTS_DIR",), "exports")


def get_db_path() -> str:
    return os.path.join(get_data_dir(), "fluxo.db")


def get_seed_admin_login() -> str:
    login = (os.environ.get("ADMIN_LOGIN") or DEFAULT_ADMIN_LOGIN).strip()
    if not login:
        raise RuntimeError("ADMIN_LOGIN não pode ser vazio. Defina no arquivo .env.")
    return login


def get_seed_admin_password() -> str:
    senha = (os.environ.get("ADMIN_PASSWORD") or os.environ.get("LOCK_PASSWORD") or "").strip()
    if not senha:
        raise RuntimeError(
            "ADMIN_PASSWORD não definido. Copie .env.example para .env e informe a senha do admin. "
            "Nenhuma senha padrão é embutida no código."
        )
    return senha


def get_seed_admin_nome() -> str:
    nome = (os.environ.get("ADMIN_NOME") or DEFAULT_ADMIN_NOME).strip()
    return nome or DEFAULT_ADMIN_NOME


def get_session_secret() -> str:
    secret = (os.environ.get("SESSION_SECRET") or "").strip()
    if not secret:
        raise RuntimeError(
            "SESSION_SECRET não definido. Copie .env.example para .env e gere um valor aleatório. "
            "Nenhum segredo padrão é embutido no código."
        )
    return secret
