"""Ponto de entrada do sistema.

Uso:
    python run.py                 # http://localhost:8000
    python run.py --port 9000
    python run.py --reload        # recarrega ao salvar arquivos (desenvolvimento)
    python run.py --stop          # encerra o que estiver na porta

Variáveis de ambiente (Docker/VPS):
    HOST, PORT — além de ADMIN_* e SESSION_SECRET no arquivo .env
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env local antes de qualquer import que leia segredos.
load_dotenv(Path(__file__).resolve().parent / ".env")

import uvicorn


def pids_escutando(porta: int) -> list[int]:
    """PIDs em LISTENING na porta TCP (Windows e Unix)."""
    pids: list[int] = []
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(["netstat", "-ano", "-p", "TCP"], text=True, errors="ignore")
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []
        alvo = f":{porta}"
        for line in out.splitlines():
            if "LISTENING" not in line or alvo not in line:
                continue
            parts = line.split()
            # Garante que a porta local é exatamente :porta (evita 18000 etc.)
            if len(parts) < 5:
                continue
            local = parts[1]
            if not (local.endswith(alvo) or local.endswith(f":{porta}")):
                continue
            # Confirma sufixo de porta (127.0.0.1:8000 ou [::]:8000)
            host_port = local.rsplit(":", 1)
            if len(host_port) != 2 or host_port[1] != str(porta):
                continue
            try:
                pid = int(parts[-1])
            except ValueError:
                continue
            if pid > 0:
                pids.append(pid)
        return list(dict.fromkeys(pids))

    # Unix: lsof
    try:
        out = subprocess.check_output(["lsof", "-t", f"-iTCP:{porta}", "-sTCP:LISTEN"], text=True)
        return [int(p) for p in out.split() if p.strip().isdigit()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def encerrar_porta(porta: int) -> int:
    """Encerra a árvore de processos que estão escutando na porta. Retorna qtd encerrada."""
    pids = [p for p in pids_escutando(porta) if p != os.getpid()]
    if not pids:
        print(f"Nenhum processo escutando na porta {porta}.")
        return 0

    encerrados = 0
    for pid in pids:
        try:
            if sys.platform == "win32":
                # /T mata a árvore (reloader + worker do --reload)
                r = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                )
                if r.returncode == 0:
                    print(f"Encerrado PID {pid} (e filhos) na porta {porta}.")
                    encerrados += 1
                else:
                    print(f"Falha ao encerrar PID {pid}: {(r.stderr or r.stdout).strip()}")
            else:
                os.kill(pid, signal.SIGTERM)
                print(f"Enviado SIGTERM ao PID {pid} na porta {porta}.")
                encerrados += 1
        except OSError as exc:
            print(f"Não foi possível encerrar PID {pid}: {exc}")
    return encerrados


def main() -> None:
    host_padrao = os.environ.get("HOST", "127.0.0.1")
    porta_padrao = int(os.environ.get("PORT", "8000"))

    parser = argparse.ArgumentParser(description="Fluxo de Caixa")
    parser.add_argument("--host", default=host_padrao, help="Endereço de escuta (use 0.0.0.0 para a rede)")
    parser.add_argument("--port", type=int, default=porta_padrao, help="Porta HTTP")
    parser.add_argument("--reload", action="store_true", help="Recarregar automaticamente ao editar o código")
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Encerra o processo que estiver usando a porta e sai",
    )
    args = parser.parse_args()

    if args.stop:
        encerrar_porta(args.port)
        return

    ocupados = [p for p in pids_escutando(args.port) if p != os.getpid()]
    if ocupados:
        print(
            f"Porta {args.port} em uso pelos PIDs: {', '.join(map(str, ocupados))}.\n"
            f"Encerre com: python run.py --stop --port {args.port}"
        )
        sys.exit(1)

    print(f"\n  Fluxo de Caixa rodando em http://{args.host}:{args.port}\n")
    try:
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            timeout_graceful_shutdown=5,
        )
    except KeyboardInterrupt:
        pass
    finally:
        # No Windows, Ctrl+C / fechar terminal às vezes deixa worker órfão (sobretudo com --reload).
        if sys.platform == "win32":
            encerrar_porta(args.port)


if __name__ == "__main__":
    main()
