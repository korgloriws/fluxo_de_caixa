"""Cliente HTTP da API Extratos BB (OAuth + mTLS).

Usado pelo módulo Extrato BB em modo produção. Datas vêm do filtro da UI,
não do .env.
"""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]

PRESETS = {
    "producao": {
        "token_url": "https://oauth.bb.com.br/oauth/token",
        "base_url": "https://extratos.mtls.api.bb.com.br/v2",
        "path_tpl": "/conta-corrente/agencia/{agencia}/conta/{conta}",
        "exige_mtls": True,
    },
    "homologacao": {
        "token_url": "https://oauth.hm.bb.com.br/oauth/token",
        "base_url": "https://extratos.mtls.api.hm.bb.com.br/v2",
        "path_tpl": "/conta-corrente/agencia/{agencia}/conta/{conta}",
        "exige_mtls": True,
    },
}

# Cache simples de token (processo).
_token_cache: dict[str, Any] = {"token": None, "expira_em": 0.0}


class BbClientError(Exception):
    """Falha controlada ao falar com a API BB."""


def _obrigatorio(nome: str) -> str:
    valor = (os.environ.get(nome) or "").strip()
    if not valor:
        raise BbClientError(f"Variável {nome} ausente ou vazia no .env.")
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


def data_para_bb(valor: date | str | None) -> Optional[str]:
    """Converte date/ISO/DDMMAAAA para o formato aceito pela API (dígitos DDMMAAAA)."""
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor.strftime("%d%m%Y")
    digitos = re.sub(r"\D", "", str(valor))
    if not digitos:
        return None
    # Remove zeros à esquerda como o script de teste (API aceita).
    return str(int(digitos))


def _resolver_caminho(caminho: str) -> Path:
    path = Path(caminho).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _pfx_para_pem(cert_path: Path, senha: str | None) -> tuple[str, str]:
    try:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            pkcs12,
        )
    except ImportError as exc:
        raise BbClientError(
            "Pacote 'cryptography' necessário para ler .pfx. Inclua em requirements.txt."
        ) from exc

    bruto = cert_path.read_bytes()
    if senha is None:
        tentativas: list[bytes | None] = [None, b""]
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
        raise BbClientError(
            "Não foi possível abrir o .pfx (senha incorreta ou arquivo inválido). "
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
            raise BbClientError(
                "Host mTLS exige certificado. Defina BB_CERT_FILE e BB_CERT_PASSWORD no .env."
            )
        return None

    cert_path = _resolver_caminho(cert)
    if not cert_path.exists():
        raise BbClientError(f"BB_CERT_FILE não encontrado: {cert_path}")

    if cert_path.suffix.lower() in {".pfx", ".p12"}:
        certfile, keyfile = _pfx_para_pem(cert_path, senha)
    else:
        certfile = str(cert_path)
        keyfile = str(_resolver_caminho(key)) if key else None
        if keyfile and not Path(keyfile).exists():
            raise BbClientError(f"BB_KEY_FILE não encontrado: {keyfile}")

    ctx = ssl.create_default_context()
    try:
        ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    except Exception as exc:
        raise BbClientError(f"Falha ao carregar certificado mTLS: {exc}") from exc
    return ctx


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 60.0,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[int, Any]:
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
        raise BbClientError(f"Falha de rede ao chamar {url}: {exc}") from exc

    try:
        dados = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        dados = raw
    return status, dados


def obter_token(*, ssl_context: ssl.SSLContext | None, token_url: str, scope: str) -> str:
    agora = time.time()
    if _token_cache["token"] and agora < float(_token_cache["expira_em"]) - 30:
        return str(_token_cache["token"])

    client_id = _obrigatorio("BB_CLIENT_ID")
    client_secret = _obrigatorio("BB_CLIENT_SECRET")
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
        detalhe = dados
        if isinstance(dados, dict):
            detalhe = dados.get("error_description") or dados.get("error") or dados
        raise BbClientError(
            f"Token OAuth falhou (HTTP {status}): {detalhe}. "
            "Se for produção, o app precisa estar cadastrado no portal developers do BB "
            "(ambiente de produção), não só em homologação."
        )

    token = str(dados["access_token"])
    expires_in = int(dados.get("expires_in") or 600)
    _token_cache["token"] = token
    _token_cache["expira_em"] = agora + max(60, expires_in)
    return token


def listar_contas_configuradas() -> list[dict[str, str]]:
    """Contas do .env para o filtro da UI (a API BB não lista contas)."""
    try:
        pares = _resolver_contas()
    except BbClientError:
        return []
    return [
        {
            "id": f"{ag}:{ct}",
            "agencia": ag,
            "conta": ct,
            "rotulo": f"Ag {ag} · Conta {ct}",
        }
        for ag, ct in pares
    ]


def _resolver_contas() -> list[tuple[str, str]]:
    contas_env = _opcional("BB_CONTAS")
    if contas_env:
        pares: list[tuple[str, str]] = []
        for pedaco in contas_env.split(","):
            item = pedaco.strip()
            if not item:
                continue
            if ":" not in item:
                raise BbClientError(f"BB_CONTAS inválido: '{item}'. Use agencia:conta")
            ag, ct = item.split(":", 1)
            pares.append((_normalizar_numero(ag), _normalizar_numero(ct)))
        if pares:
            return pares

    agencia = _opcional("BB_AGENCIA")
    conta = _opcional("BB_CONTA")
    if agencia and conta:
        return [(_normalizar_numero(agencia), _normalizar_numero(conta))]

    raise BbClientError("Informe BB_AGENCIA/BB_CONTA (ou BB_CONTAS) no .env.")


def _filtrar_contas(conta_id: str | None) -> list[tuple[str, str]]:
    """conta_id = 'agencia:conta' ou vazio = todas as configuradas."""
    todas = _resolver_contas()
    if not conta_id or not str(conta_id).strip():
        return todas
    bruto = str(conta_id).strip()
    if ":" not in bruto:
        raise BbClientError("Filtro de conta inválido. Use agencia:conta.")
    ag, ct = bruto.split(":", 1)
    alvo = (_normalizar_numero(ag), _normalizar_numero(ct))
    if alvo not in todas:
        raise BbClientError(
            f"Conta {alvo[0]}/{alvo[1]} não está em BB_CONTAS/BB_AGENCIA no .env."
        )
    return [alvo]


def _preset_ativo() -> tuple[str, dict[str, Any]]:
    nome = (_opcional("BB_AMBIENTE") or "producao").strip().lower()
    if nome in {"hm", "homolog", "homologacao", "homologação", "sandbox"}:
        ambiente = "homologacao"
        base = dict(PRESETS["homologacao"])
    else:
        ambiente = "producao"
        base = dict(PRESETS["producao"])
    if _opcional("BB_TOKEN_URL"):
        base["token_url"] = _opcional("BB_TOKEN_URL")
    if _opcional("BB_EXTRATO_BASE_URL"):
        base["base_url"] = _opcional("BB_EXTRATO_BASE_URL")
    return ambiente, base


@dataclass
class ExtratoPagina:
    status: int
    dados: dict
    url: str
    agencia: str
    conta: str


def consultar_pagina(
    *,
    token: str,
    app_key: str,
    agencia: str,
    conta: str,
    data_inicio: str | None,
    data_fim: str | None,
    pagina: int,
    page_size: int,
    ssl_context: ssl.SSLContext | None,
    base_url: str,
    path_tpl: str,
) -> ExtratoPagina:
    path = path_tpl.format(agencia=agencia, conta=conta)
    url_base = f"{base_url.rstrip('/')}{path}"
    query: dict[str, str] = {
        "gw-dev-app-key": app_key,
        "numeroPaginaSolicitacao": str(pagina),
        "quantidadeRegistroPaginaSolicitacao": str(page_size),
    }
    if data_inicio:
        query["dataInicioSolicitacao"] = data_inicio
    if data_fim:
        query["dataFimSolicitacao"] = data_fim
    url = f"{url_base}?{urllib.parse.urlencode(query)}"
    status, dados = _http_json(
        "GET",
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        ssl_context=ssl_context,
    )
    if not isinstance(dados, dict):
        raise BbClientError(f"Resposta inesperada da API (HTTP {status}): {dados!r}")
    return ExtratoPagina(status=status, dados=dados, url=url, agencia=agencia, conta=conta)


def buscar_extrato(
    *,
    inicio: date | None,
    fim: date | None,
    conta_id: str | None = None,
    page_size: int = 50,
    max_paginas: int = 50,
) -> tuple[list[dict], dict]:
    """Busca páginas do período. Cada item bruto ganha _agencia/_conta."""
    ambiente, preset = _preset_ativo()
    # OAuth: cert opcional; extrato mTLS: cert obrigatório no host mtls.
    ssl_token = montar_ssl_context(exige_cert=False)
    ssl_extrato = montar_ssl_context(exige_cert=bool(preset["exige_mtls"]))
    scope = _opcional("BB_SCOPE") or "extrato-info"
    token = obter_token(
        ssl_context=ssl_token,
        token_url=str(preset["token_url"]),
        scope=scope,
    )

    app_key = _obrigatorio("BB_APP_KEY")
    contas = _filtrar_contas(conta_id)
    di = data_para_bb(inicio)
    df = data_para_bb(fim)

    todos: list[dict] = []
    paginas_meta: list[dict] = []
    urls: list[str] = []

    for agencia, conta in contas:
        pagina = 1
        total_paginas = 1
        while pagina <= total_paginas and pagina <= max_paginas:
            resp = consultar_pagina(
                token=token,
                app_key=app_key,
                agencia=agencia,
                conta=conta,
                data_inicio=di,
                data_fim=df,
                pagina=pagina,
                page_size=page_size,
                ssl_context=ssl_extrato,
                base_url=str(preset["base_url"]),
                path_tpl=str(preset["path_tpl"]),
            )
            if resp.status != 200:
                detalhe = resp.dados
                if isinstance(detalhe, dict):
                    detalhe = (
                        detalhe.get("message")
                        or detalhe.get("detail")
                        or detalhe.get("error_description")
                        or detalhe
                    )
                raise BbClientError(
                    f"Extrato HTTP {resp.status} (ag {agencia} cc {conta}): {detalhe}"
                )
            dados = resp.dados
            urls.append(resp.url)
            total_paginas = int(dados.get("quantidadeTotalPagina") or 1) or 1
            paginas_meta.append(
                {
                    "agencia": agencia,
                    "conta": conta,
                    "pagina": dados.get("numeroPaginaAtual", pagina),
                    "registros_pagina": dados.get("quantidadeRegistroPaginaAtual"),
                    "total_paginas": total_paginas,
                    "total_registros_api": dados.get("quantidadeTotalRegistro"),
                }
            )
            for item in dados.get("listaLancamento") or []:
                if isinstance(item, dict):
                    row = dict(item)
                    row["_agencia"] = agencia
                    row["_conta"] = conta
                    todos.append(row)
            pagina += 1

    meta = {
        "ambiente": ambiente,
        "base_url": preset["base_url"],
        "contas": [{"agencia": a, "conta": c, "id": f"{a}:{c}"} for a, c in contas],
        "paginas": paginas_meta,
        "urls_exemplo": urls[:3],
        "total_bruto": len(todos),
    }
    return todos, meta
