"""Cliente SOAP do SGP (sistema financeiro da prefeitura).

Baseado no padrão do projeto SOAP_SGP: zeep + WSDL + Basic Auth opcional,
com conversão de XML de resposta para JSON.
"""

from __future__ import annotations

import json
import os
import xml.dom.minidom
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth

WSDL_PADRAO = "http://pm-contagem.sgpcloud.com.br/sgp/webservice/portal/wsdl"


class SgpError(Exception):
    """Falha tratável na integração SGP."""


def get_wsdl_url() -> str:
    return (os.environ.get("SGP_WSDL_URL") or WSDL_PADRAO).strip()


def get_sgp_credentials() -> tuple[Optional[str], Optional[str]]:
    user = (os.environ.get("SGP_USERNAME") or "").strip() or None
    pwd = (os.environ.get("SGP_PASSWORD") or "").strip() or None
    return user, pwd


def pretty_xml(raw_xml: str) -> str:
    try:
        return xml.dom.minidom.parseString(raw_xml.encode("utf-8")).toprettyxml(indent="  ")
    except Exception:
        return raw_xml


def _xml_element_to_obj(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        return (element.text or "").strip()

    parsed: dict[str, Any] = {}
    for child in children:
        value = _xml_element_to_obj(child)
        if child.tag in parsed:
            existing = parsed[child.tag]
            if isinstance(existing, list):
                existing.append(value)
            else:
                parsed[child.tag] = [existing, value]
        else:
            parsed[child.tag] = value
    return parsed


def xml_to_object(raw_xml: str) -> dict[str, Any]:
    root = ET.fromstring(raw_xml)
    return {root.tag: _xml_element_to_obj(root)}


def _normalize_type(type_repr: str) -> str:
    texto = str(type_repr)
    if "Int(" in texto:
        return "int"
    if "Double(" in texto:
        return "double"
    if "Boolean(" in texto:
        return "boolean"
    if "AnyType" in texto:
        return "any"
    if "Array(" in texto:
        return "array"
    return "string"


def coerce_value(raw_value: Any, param_type: str) -> Any:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        return raw_value
    value = raw_value.strip()
    if param_type == "int":
        return int(value)
    if param_type == "double":
        return float(value)
    if param_type == "boolean":
        return value.lower() in {"1", "true", "sim", "yes", "s"}
    return value


def build_client(
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: int = 60,
    wsdl_url: Optional[str] = None,
):
    try:
        from zeep import Client
        from zeep.transports import Transport
    except ImportError as exc:
        raise SgpError(
            "Pacote 'zeep' não instalado. Rode: pip install zeep requests"
        ) from exc

    session = requests.Session()
    user = username
    pwd = password
    if user is None and pwd is None:
        user, pwd = get_sgp_credentials()
    if user and pwd:
        session.auth = HTTPBasicAuth(user, pwd)

    transport = Transport(session=session, timeout=timeout)
    return Client(wsdl=(wsdl_url or get_wsdl_url()), transport=transport)


def _extract_params(operation: Any) -> list[dict[str, Any]]:
    params: list[dict[str, Any]] = []
    body_type = getattr(getattr(operation, "input", None), "body", None)
    body_type = getattr(body_type, "type", None)
    if not body_type or not hasattr(body_type, "elements"):
        return params

    for name, element in body_type.elements:
        type_repr = str(element.type) if element.type else "string"
        params.append(
            {
                "name": name,
                "type": _normalize_type(type_repr),
                "raw_type": type_repr,
                "required": not element.is_optional,
            }
        )
    return params


@lru_cache(maxsize=2)
def carregar_metadados_wsdl(wsdl_url: str = "") -> dict[str, dict[str, Any]]:
    client = build_client(wsdl_url=wsdl_url or None)
    metadata: dict[str, dict[str, Any]] = {}
    for service in client.wsdl.services.values():
        for port in service.ports.values():
            for name, operation in port.binding._operations.items():
                metadata[name] = {
                    "name": name,
                    "signature": operation.input.signature(),
                    "params": _extract_params(operation),
                    "output": operation.output.signature() if operation.output else None,
                }
    return metadata


def limpar_cache_metadados() -> None:
    carregar_metadados_wsdl.cache_clear()


def invocar(
    nome: str,
    params: dict[str, Any],
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: int = 60,
) -> dict[str, Any]:
    meta = carregar_metadados_wsdl().get(nome)
    if meta is None:
        raise SgpError(f"Operação '{nome}' não encontrada no WSDL.")

    kwargs: dict[str, Any] = {}
    for param in meta["params"]:
        pname = param["name"]
        if pname not in params:
            if param["required"]:
                raise SgpError(f"Parâmetro obrigatório ausente: {pname}")
            continue
        # String vazia é válida (ex.: filtroOpcional="") — o WSDL marca como required.
        kwargs[pname] = coerce_value(params[pname], param["type"])

    client = build_client(username=username, password=password, timeout=timeout)
    try:
        response = getattr(client.service, nome)(**kwargs)
    except Exception as exc:
        raise SgpError(f"Falha ao invocar '{nome}': {exc}") from exc

    if isinstance(response, str):
        obj = None
        json_error = None
        try:
            obj = xml_to_object(response)
        except Exception as exc:
            json_error = str(exc)
        return {
            "kind": "xml",
            "xml_raw": response,
            "xml_pretty": pretty_xml(response),
            "json_object": obj,
            "json_pretty": json.dumps(obj, indent=2, ensure_ascii=False) if obj else None,
            "json_error": json_error,
        }

    return {
        "kind": "value",
        "value": response,
        "value_text": json.dumps(response, indent=2, ensure_ascii=False, default=str),
    }
