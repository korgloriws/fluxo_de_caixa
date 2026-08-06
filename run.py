"""Ponto de entrada do sistema.

Uso:
    python run.py                 # http://localhost:8000
    python run.py --port 9000
    python run.py --reload        # recarrega ao salvar arquivos (desenvolvimento)

Variáveis de ambiente (Docker/VPS):
    HOST, PORT — além de ADMIN_* e SESSION_SECRET no arquivo .env
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env local antes de qualquer import que leia segredos.
load_dotenv(Path(__file__).resolve().parent / ".env")

import uvicorn


def main() -> None:
    host_padrao = os.environ.get("HOST", "127.0.0.1")
    porta_padrao = int(os.environ.get("PORT", "8000"))

    parser = argparse.ArgumentParser(description="Fluxo de Caixa")
    parser.add_argument("--host", default=host_padrao, help="Endereço de escuta (use 0.0.0.0 para a rede)")
    parser.add_argument("--port", type=int, default=porta_padrao, help="Porta HTTP")
    parser.add_argument("--reload", action="store_true", help="Recarregar automaticamente ao editar o código")
    args = parser.parse_args()

    print(f"\n  Fluxo de Caixa rodando em http://{args.host}:{args.port}\n")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
