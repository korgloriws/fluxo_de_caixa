"""Teste da API Extratos do Banco do Brasil (OAuth + mTLS).

Uso:
  python scripts/teste_bb_extrato.py --token-only
  python scripts/teste_bb_extrato.py --preset hm-v1 --inicio 01082026 --fim 20082026
  python scripts/teste_bb_extrato.py --probe --inicio 01082026 --fim 20082026

.env:
  BB_CLIENT_ID, BB_CLIENT_SECRET, BB_APP_KEY
  BB_AGENCIA, BB_CONTA
  BB_CERT_FILE=app/certificado/arquivo.pfx
  BB_CERT_PASSWORD="senha#com#hash"
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PRESETS = {
    "hm-v2-mtls": {
        "token_url": "https://oauth.hm.bb.com.br/oauth/token",
        "base_url": "https://extratos.mtls.api.hm.bb.com.br/v2",
        "path_tpl": "/conta-corrente/agencia/{agencia}/conta/{conta}",
        "exige_mtls": True,
    },
    "hm-v1": {
        "token_url": "https://oauth.hm.bb.com.br/oauth/token",
        "base_url": "https://api.hm.bb.com.br/extratos/v1",
        "path_tpl": "/conta-corrente/agencia/{agencia}/conta/{conta}",
        "exige_mtls": False,
    },
    "prod-v2-mtls": {
        "token_url": "https://oauth.bb.com.br/oauth/token",
        "base_url": "https://extratos.mtls.api.bb.com.br/v2",
        "path_tpl": "/conta-corrente/agencia/{agencia}/conta/{conta}",
        "exige_mtls": True,
    },
    "prod-v1": {
        "token_url": "https://oauth.bb.com.br/oauth/token",
        "base_url": "https://api-extratos.bb.com.br/extratos/v1",
        "path_tpl": "/conta-corrente/agencia/{agencia}/conta/{conta}",
        "exige_mtls": True,
    },
}


def _obrigatorio(nome: str) -> str:
    valor = (os.environ.get(nome) or "").strip()
    if not valor:
        raise SystemExit(f"Variável {nome} ausente ou vazia no .env.")
    return valor


def _opcional(nome: str) -> str:
    return (os.environ.get(nome) or "").strip()


def _normalizar_numero(valor: str) -> str:
    texto = (valor or "").strip()
    if not texto:
        return texto
    if "-" in texto:
        texto = texto.split("-", 1)[0]
    texto = re.sub(r"\D", "", texto)
    return texto.lstrip("0") or "0"


def _normalizar_data_bb(valor: str | None) -> str | None:
    if not valor:
        return None
    digitos = re.sub(r"\D", "", valor)
    if not digitos:
        return None
    return str(int(digitos))


def _resolver_caminho(caminho: str) -> Path:
    path = Path(caminho).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _parse_contas(
    *,
    agencia_cli: str,
    conta_cli: str,
    contas_env: str,
    agencia_env: str,
    conta_env: str,
) -> list[tuple[str, str]]:
    if agencia_cli or conta_cli:
        if not agencia_cli or not conta_cli:
            raise SystemExit("Use --agencia e --conta juntos.")
        return [(_normalizar_numero(agencia_cli), _normalizar_numero(conta_cli))]

    if contas_env:
        pares: list[tuple[str, str]] = []
        for pedaco in contas_env.split(","):
            item = pedaco.strip()
            if not item:
                continue
            if ":" not in item:
                raise SystemExit(f"BB_CONTAS inválido: '{item}'. Use agencia:conta")
            ag, ct = item.split(":", 1)
            pares.append((_normalizar_numero(ag), _normalizar_numero(ct)))
        if pares:
            return pares

    if agencia_env and conta_env:
        return [(_normalizar_numero(agencia_env), _normalizar_numero(conta_env))]

    raise SystemExit(
        "Informe BB_AGENCIA/BB_CONTA no .env ou use --agencia/--conta.\n"
        "Para só validar OAuth: python scripts/teste_bb_extrato.py --token-only"
    )


def _pfx_para_pem(cert_path: Path, senha: str | None) -> tuple[str, str]:
    try:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            pkcs12,
        )
    except ImportError as exc:
        raise SystemExit(
            "Pacote 'cryptography' necessário para ler .pfx.\n"
            "Instale com: pip install cryptography"
        ) from exc

    bruto = cert_path.read_bytes()
    tentativas: list[bytes | None]
    if senha is None:
        tentativas = [None, b""]
    else:
        tentativas = [senha.encode("utf-8"), senha.encode("latin-1")]

    ultimo_erro: Exception | None = None
    key = cert = extras = None
    for pwd in tentativas:
        try:
            key, cert, extras = pkcs12.load_key_and_certificates(bruto, pwd)
            break
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            key = cert = extras = None

    if key is None or cert is None:
        raise SystemExit(
            "Não foi possível abrir o .pfx (senha incorreta ou arquivo inválido).\n"
            "Defina BB_CERT_PASSWORD no .env com aspas se tiver #.\n"
            f"Detalhe: {ultimo_erro}"
        )

    cert_pem = cert.public_bytes(Encoding.PEM)
    for extra in extras or []:
        cert_pem += extra.public_bytes(Encoding.PEM)
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

    tmp = Path(tempfile.mkdtemp(prefix="bb_mtls_"))
    cert_file = tmp / "client-cert.pem"
    key_file = tmp / "client-key.pem"
    cert_file.write_bytes(cert_pem)
    key_file.write_bytes(key_pem)
    return str(cert_file), str(key_file)


def montar_ssl_context(*, exige_cert: bool) -> ssl.SSLContext | None:
    cert = _opcional("BB_CERT_FILE")
    key = _opcional("BB_KEY_FILE")
    senha = _opcional("BB_CERT_PASSWORD") or None

    if not cert:
        if exige_cert:
            raise SystemExit(
                "Host mtls exige certificado cliente.\n"
                "No .env:\n"
                "  BB_CERT_FILE=app/certificado/seu_arquivo.pfx\n"
                '  BB_CERT_PASSWORD="senha"'
            )
        return None

    cert_path = _resolver_caminho(cert)
    if not cert_path.exists():
        raise SystemExit(f"BB_CERT_FILE não encontrado:\n  {cert_path}")

    if cert_path.suffix.lower() in {".pfx", ".p12"}:
        certfile, keyfile = _pfx_para_pem(cert_path, senha)
    else:
        certfile = str(cert_path)
        keyfile = str(_resolver_caminho(key)) if key else None
        if keyfile and not Path(keyfile).exists():
            raise SystemExit(f"BB_KEY_FILE não encontrado:\n  {keyfile}")

    ctx = ssl.create_default_context()
    try:
        ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    except Exception as exc:
        raise SystemExit(f"Falha ao carregar certificado mTLS: {exc}") from exc
    return ctx


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 60.0,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[int, dict | list | str]:
    req = urllib.request.Request(url, data=body, method=method)
    for chave, valor in (headers or {}).items():
        req.add_header(chave, valor)

    handlers: list[urllib.request.BaseHandler] = []
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    opener = urllib.request.build_opener(*handlers)

    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except urllib.error.URLError as exc:
        raise SystemExit(f"Falha de rede ao chamar {url}: {exc}") from exc

    try:
        dados = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        dados = raw
    return status, dados


def obter_token(
    client_id: str,
    client_secret: str,
    token_url: str,
    scope: str,
    ssl_context: ssl.SSLContext | None = None,
) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    corpo = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "scope": scope}
    ).encode("utf-8")
    status, dados = _http_json(
        "POST",
        token_url,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        body=corpo,
        ssl_context=ssl_context,
    )
    if status != 200 or not isinstance(dados, dict) or not dados.get("access_token"):
        print("=== ERRO NO TOKEN ===")
        print(json.dumps(dados, ensure_ascii=False, indent=2))
        raise SystemExit(f"Token falhou (HTTP {status}).")
    return str(dados["access_token"])


def consultar_extrato(
    *,
    base_url: str,
    path_tpl: str,
    token: str,
    app_key: str,
    agencia: str,
    conta: str,
    data_inicio: str | None,
    data_fim: str | None,
    pagina: int,
    page_size: int,
    ssl_context: ssl.SSLContext | None,
    headers_extra: dict[str, str] | None = None,
) -> tuple[int, dict | list | str, str]:
    path = path_tpl.format(agencia=agencia, conta=conta)
    url_base = f"{base_url.rstrip('/')}{path}"
    query: dict[str, str] = {
        "gw-dev-app-key": app_key,
        "numeroPaginaSolicitacao": str(pagina),
        "quantidadeRegistroPaginaSolicitacao": str(page_size),
    }
    di = _normalizar_data_bb(data_inicio)
    df = _normalizar_data_bb(data_fim)
    if di:
        query["dataInicioSolicitacao"] = di
    if df:
        query["dataFimSolicitacao"] = df
    url = f"{url_base}?{urllib.parse.urlencode(query)}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if headers_extra:
        headers.update(headers_extra)
    status, dados = _http_json("GET", url, headers=headers, ssl_context=ssl_context)
    return status, dados, url


def resumir_lancamentos(dados: dict) -> None:
    lista = dados.get("listaLancamento") or []
    print(f"\nRegistros em listaLancamento: {len(lista)}")
    print(
        "Paginação:",
        {
            "pagina": dados.get("numeroPaginaAtual"),
            "total_paginas": dados.get("quantidadeTotalPagina"),
            "total_registros": dados.get("quantidadeTotalRegistro"),
        },
    )
    saldos = [i for i in lista if str(i.get("indicadorTipoLancamento", "")).upper() == "SA"]
    movimentos = [
        i for i in lista if str(i.get("indicadorTipoLancamento", "")).upper() not in {"SA", "RA"}
    ]
    print(f"\nLinhas de saldo atual (SA): {len(saldos)}")
    for item in saldos:
        print(
            json.dumps(
                {
                    "tipo": item.get("indicadorTipoLancamento"),
                    "data": item.get("dataLancamento"),
                    "valor": item.get("valorLancamento"),
                    "sinal": item.get("indicadorSinalLancamento"),
                    "historico": item.get("textoDescricaoSubHistorico"),
                },
                ensure_ascii=False,
            )
        )
    print(f"\nPrimeiros movimentos (até 8 de {len(movimentos)}):")
    for item in movimentos[:8]:
        print(
            json.dumps(
                {
                    "tipo": item.get("indicadorTipoLancamento"),
                    "data": item.get("dataLancamento"),
                    "valor": item.get("valorLancamento"),
                    "sinal": item.get("indicadorSinalLancamento"),
                    "historico": item.get("textoDescricaoSubHistorico"),
                },
                ensure_ascii=False,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa API Extratos BB")
    parser.add_argument("--token-only", action="store_true")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Testa vários hosts (hm-v1, hm-v2-mtls, prod-*)",
    )
    parser.add_argument(
        "--preset",
        default=_opcional("BB_PRESET") or "hm-v2-mtls",
        choices=sorted(PRESETS.keys()),
    )
    parser.add_argument("--agencia", default="")
    parser.add_argument("--conta", default="")
    parser.add_argument("--inicio", default=os.environ.get("BB_DATA_INICIO", ""))
    parser.add_argument("--fim", default=os.environ.get("BB_DATA_FIM", ""))
    parser.add_argument("--pagina", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=120)
    parser.add_argument("--salvar", default="")
    args = parser.parse_args()

    client_id = _obrigatorio("BB_CLIENT_ID")
    client_secret = _obrigatorio("BB_CLIENT_SECRET")
    app_key = _obrigatorio("BB_APP_KEY")
    scope = _opcional("BB_SCOPE") or "extrato-info"
    mci_teste = _opcional("BB_MCI_TESTE")

    presets = ["hm-v1", "hm-v2-mtls"] if args.probe else [args.preset]
    # Em probe, produção só se o usuário pedir explicitamente via env
    if args.probe and _opcional("BB_PROBE_PROD") == "1":
        presets.extend(["prod-v1", "prod-v2-mtls"])

    contas = (
        []
        if args.token_only
        else _parse_contas(
            agencia_cli=args.agencia.strip(),
            conta_cli=args.conta.strip(),
            contas_env=_opcional("BB_CONTAS"),
            agencia_env=_opcional("BB_AGENCIA"),
            conta_env=_opcional("BB_CONTA"),
        )
    )

    falhas = 0
    for nome in presets:
        cfg = PRESETS[nome]
        token_url = _opcional("BB_TOKEN_URL") or cfg["token_url"]
        base_url = _opcional("BB_EXTRATO_BASE_URL") or cfg["base_url"]
        path_tpl = cfg["path_tpl"]
        exige_mtls = bool(cfg["exige_mtls"]) or ("mtls" in base_url.lower())

        print("\n" + "=" * 60)
        print(f"Preset: {nome}")
        print(f"  token_url = {token_url}")
        print(f"  base_url  = {base_url}")
        print(f"  scope     = {scope}")
        print(f"  app_key   = ***{app_key[-4:] if len(app_key) >= 4 else '****'}")
        print(f"  cert      = {_opcional('BB_CERT_FILE') or '(não definido)'}")
        print(f"  mTLS      = {'obrigatório' if exige_mtls else 'opcional'}")

        ssl_token = montar_ssl_context(exige_cert=False)
        print("1) Token…")
        try:
            token = obter_token(client_id, client_secret, token_url, scope, ssl_context=ssl_token)
            print("   Token OK.")
        except SystemExit as exc:
            print(f"   Token falhou: {exc}")
            falhas += 1
            continue

        if args.token_only:
            continue

        try:
            ssl_extrato = montar_ssl_context(exige_cert=exige_mtls)
        except SystemExit as exc:
            # Em hm-v1 o mTLS é opcional: tenta sem certificado.
            if exige_mtls:
                print(f"   Certificado: {exc}")
                falhas += 1
                continue
            ssl_extrato = None

        headers_extra: dict[str, str] = {}
        if mci_teste and ".hm." in base_url:
            headers_extra["x-br-com-bb-ipa-mciteste"] = mci_teste

        for idx, (agencia, conta) in enumerate(contas, start=1):
            print(f"2.{idx}) Extrato agência={agencia} conta={conta}…")
            status, dados, url = consultar_extrato(
                base_url=base_url,
                path_tpl=path_tpl,
                token=token,
                app_key=app_key,
                agencia=agencia,
                conta=conta,
                data_inicio=(args.inicio or None),
                data_fim=(args.fim or None),
                pagina=args.pagina,
                page_size=args.page_size,
                ssl_context=ssl_extrato,
                headers_extra=headers_extra or None,
            )
            # Não imprimir app key na URL
            url_log = re.sub(r"(gw-dev-app-key=)[^&]+", r"\1***", url)
            print(f"   URL: {url_log}")
            print(f"   HTTP {status}")

            if args.salvar and not args.probe:
                destino = Path(args.salvar)
                if not destino.is_absolute():
                    destino = ROOT / destino
                if len(contas) > 1:
                    destino = destino.with_name(
                        f"{destino.stem}_{agencia}_{conta}{destino.suffix or '.json'}"
                    )
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(
                    json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"   JSON salvo em: {destino}")

            if status != 200 or not isinstance(dados, dict):
                falhas += 1
                print("   === RESPOSTA ===")
                print(
                    json.dumps(dados, ensure_ascii=False, indent=2)
                    if not isinstance(dados, str)
                    else dados
                )
                continue
            resumir_lancamentos(dados)

    if args.token_only:
        print("\nModo --token-only concluído.")
        return
    if falhas:
        raise SystemExit(1)
    print("\nOK — linhas SA = saldo atual do BB.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
