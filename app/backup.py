"""Backup e restauração do banco SQLite (mesmo arquivo .db para baixar e subir)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import get_db_path, get_exports_dir
from . import repository

TABELAS_OBRIGATORIAS = ("movimentos", "usuarios")


class BackupError(Exception):
    """Falha tratável de backup/restauração."""


def _caminhos_auxiliares(db_path: str) -> list[str]:
    return [f"{db_path}-wal", f"{db_path}-shm", f"{db_path}-journal"]


def checkpoint() -> None:
    """Consolida o WAL no arquivo principal para um snapshot consistente."""
    caminho = get_db_path()
    if not os.path.exists(caminho):
        return
    conn = sqlite3.connect(caminho)
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL);")
        conn.commit()
    finally:
        conn.close()


def gerar_backup_arquivo() -> Path:
    """Gera um .db completo (VACUUM INTO) pronto para download e reupload."""
    origem = get_db_path()
    if not os.path.exists(origem):
        raise BackupError("Banco de dados ainda não existe.")

    checkpoint()
    exports = Path(get_exports_dir())
    exports.mkdir(parents=True, exist_ok=True)
    destino = exports / f"fluxo_backup_{datetime.now():%Y%m%d_%H%M%S}.db"

    # Remove destino residual, se houver.
    if destino.exists():
        destino.unlink()

    conn = sqlite3.connect(origem)
    try:
        # Cópia consistente em um único arquivo (sem -wal/-shm).
        conn.execute(f"VACUUM INTO '{destino.as_posix()}'")
    finally:
        conn.close()

    if not destino.exists() or destino.stat().st_size < 100:
        raise BackupError("Falha ao gerar o arquivo de backup.")

    return destino


def validar_arquivo_sqlite(caminho: str | Path) -> dict:
    """Confere se o arquivo é SQLite e contém as tabelas essenciais."""
    caminho = Path(caminho)
    if not caminho.exists() or caminho.stat().st_size < 100:
        raise BackupError("Arquivo de backup inválido ou vazio.")

    with open(caminho, "rb") as f:
        cabecalho = f.read(16)
    if not cabecalho.startswith(b"SQLite format 3"):
        raise BackupError("O arquivo não é um banco SQLite válido (.db).")

    conn = sqlite3.connect(str(caminho))
    try:
        tabelas = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        faltando = [t for t in TABELAS_OBRIGATORIAS if t not in tabelas]
        if faltando:
            raise BackupError(
                "Backup incompleto: faltam as tabelas "
                + ", ".join(faltando)
                + ". Use um arquivo gerado por este sistema."
            )

        movimentos = int(conn.execute("SELECT COUNT(*) FROM movimentos").fetchone()[0])
        usuarios = int(conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0])
    finally:
        conn.close()

    return {
        "tabelas": sorted(tabelas),
        "movimentos": movimentos,
        "usuarios": usuarios,
        "tamanho_bytes": caminho.stat().st_size,
    }


def restaurar_de_bytes(conteudo: bytes) -> dict:
    """Substitui o banco atual pelo conteúdo enviado (mesmo formato do download)."""
    if not conteudo or len(conteudo) < 100:
        raise BackupError("Arquivo de backup vazio ou inválido.")

    with tempfile.TemporaryDirectory(prefix="fundeb_restore_") as tmp:
        candidato = Path(tmp) / "restore.db"
        candidato.write_bytes(conteudo)
        info = validar_arquivo_sqlite(candidato)

        destino = Path(get_db_path())
        destino.parent.mkdir(parents=True, exist_ok=True)

        # Guarda o banco atual antes de trocar.
        checkpoint()
        if destino.exists():
            reserva = (
                Path(get_exports_dir())
                / f"fluxo_antes_restore_{datetime.now():%Y%m%d_%H%M%S}.db"
            )
            shutil.copy2(destino, reserva)
            info["backup_anterior"] = reserva.name
        else:
            info["backup_anterior"] = None

        # Remove WAL/SHM para não misturar journals antigos com o novo arquivo.
        for auxiliar in _caminhos_auxiliares(str(destino)):
            if os.path.exists(auxiliar):
                try:
                    os.remove(auxiliar)
                except OSError:
                    pass

        shutil.copy2(candidato, destino)

        for auxiliar in _caminhos_auxiliares(str(destino)):
            if os.path.exists(auxiliar):
                try:
                    os.remove(auxiliar)
                except OSError:
                    pass

    # Garante migrações/colunas novas no banco restaurado.
    repository.init_db()
    info["ok"] = True
    return info


def zerar_dados() -> dict:
    """Apaga movimentos, histórico e previsões. Mantém usuários e o schema.

    Antes de limpar, grava uma cópia automática em exports/ para recuperação.
    """
    destino = Path(get_db_path())
    if not destino.exists():
        raise BackupError("Banco de dados ainda não existe.")

    checkpoint()
    reserva = (
        Path(get_exports_dir())
        / f"fluxo_antes_zerar_{datetime.now():%Y%m%d_%H%M%S}.db"
    )
    Path(get_exports_dir()).mkdir(parents=True, exist_ok=True)
    shutil.copy2(destino, reserva)

    with repository.connect() as conn:
        movimentos = int(conn.execute("SELECT COUNT(*) FROM movimentos").fetchone()[0])
        try:
            historico = int(conn.execute("SELECT COUNT(*) FROM historico").fetchone()[0])
        except sqlite3.OperationalError:
            historico = 0
        try:
            previsoes = int(
                conn.execute("SELECT COUNT(*) FROM previsoes_mensais").fetchone()[0]
            )
        except sqlite3.OperationalError:
            previsoes = 0
        try:
            saldos = int(conn.execute("SELECT COUNT(*) FROM saldos_extrato").fetchone()[0])
        except sqlite3.OperationalError:
            saldos = 0

        conn.execute("DELETE FROM movimentos")
        try:
            conn.execute("DELETE FROM historico")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("DELETE FROM previsoes_mensais")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("DELETE FROM saldos_extrato")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("DELETE FROM extratos_arquivos")
        except sqlite3.OperationalError:
            pass
        # Reinicia sequências dos IDs limpos (usuarios permanece).
        for tabela in ("movimentos", "historico", "previsoes_mensais"):
            try:
                conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tabela,))
            except sqlite3.OperationalError:
                pass

    repository.init_db()
    return {
        "ok": True,
        "movimentos_apagados": movimentos,
        "historico_apagado": historico,
        "previsoes_apagadas": previsoes,
        "backup_anterior": reserva.name,
    }
