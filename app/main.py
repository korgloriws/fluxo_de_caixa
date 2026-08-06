"""Aplicação web do Fluxo de Caixa FUNDEB (FastAPI + Jinja2)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import analytics, auth, exporters, historico, importers, repository
from .config import (
    APP_NAME,
    CATEGORIAS_DESPESA,
    CATEGORIAS_RECEITA,
    MODULE_DESCRICAO,
    MODULE_NAME,
    MODULE_TESOURO_DESCRICAO,
    MODULE_TESOURO_NAME,
    MODULE_TESOURO_PRONTO,
    PORTAL_NAME,
    get_session_secret,
    get_uploads_dir,
)
from .finance import (
    can_edit_day,
    format_currency,
    is_past_month,
    merge_with_template,
    month_key,
    normalize_lancamentos,
    parse_number,
    resolve_period,
    template_for,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title=PORTAL_NAME, docs_url="/api/docs", redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=get_session_secret(), session_cookie="fundeb_session")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.filters["moeda"] = format_currency


@app.on_event("startup")
def _startup() -> None:
    repository.init_db()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def parse_date(value: Optional[str], padrao: Optional[date] = None) -> date:
    if not value:
        return padrao or date.today()
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), formato).date()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"Data inválida: {value}")


def intervalo_da_requisicao(
    periodo: Optional[str],
    inicio: Optional[str],
    fim: Optional[str],
) -> tuple[date, date]:
    hoje = date.today()
    if periodo and periodo != "personalizado":
        return resolve_period(periodo, hoje)

    start = parse_date(inicio, hoje.replace(day=1))
    end = parse_date(fim, hoje)
    if start > end:
        start, end = end, start
    return start, end


def filtros_da_requisicao(tipo: Optional[str], categoria: Optional[str], busca: Optional[str]) -> dict:
    return {
        "tipo": tipo if tipo in ("receita", "despesa") else None,
        "categoria": categoria or None,
        "busca": (busca or "").strip() or None,
    }


def meses_liberados(request: Request) -> list[str]:
    return list(request.session.get("unlocked_months", []))


def usuario_da_sessao(request: Request) -> Optional[dict]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    usuario = auth.obter_por_id(int(user_id))
    if not usuario or not usuario["ativo"]:
        request.session.pop("user_id", None)
        request.session.pop("unlocked_months", None)
        return None
    return usuario


def esta_autenticado(request: Request) -> bool:
    return usuario_da_sessao(request) is not None


def exige_login(request: Request) -> dict:
    usuario = usuario_da_sessao(request)
    if not usuario:
        raise HTTPException(status_code=401, detail="Faça login para editar.")
    return usuario


def exige_admin(request: Request) -> dict:
    usuario = exige_login(request)
    if not usuario["eh_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Apenas o administrador master pode cadastrar ou editar usuários.",
        )
    return usuario


def exige_permissao(request: Request, dia: date) -> dict:
    usuario = exige_login(request)
    if not can_edit_day(dia, meses_liberados(request), autenticado=True):
        if is_past_month(dia):
            raise HTTPException(
                status_code=403,
                detail=f"O mês {month_key(dia)} é histórico. Confirme sua senha para liberar a edição.",
            )
        raise HTTPException(status_code=403, detail="Sem permissão para editar este dia.")
    return usuario


def contexto_fluxo(request: Request) -> dict:
    hoje = date.today()
    usuario = usuario_da_sessao(request)
    return {
        "request": request,
        "app_name": APP_NAME,
        "portal_name": PORTAL_NAME,
        "hoje": hoje.isoformat(),
        "primeiro_dia_mes": hoje.replace(day=1).isoformat(),
        "categorias_receita": CATEGORIAS_RECEITA,
        "categorias_despesa": CATEGORIAS_DESPESA,
        "categorias_todas": repository.categorias_existentes(),
        "anos": repository.anos_disponiveis() or [hoje.year],
        "usuario": usuario,
    }


# ------------------------------------------------------------------
# Páginas
# ------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def pagina_modulos(request: Request):
    return templates.TemplateResponse(
        "modulos.html",
        {
            "request": request,
            "app_name": PORTAL_NAME,
            "portal_name": PORTAL_NAME,
            "module_name": MODULE_NAME,
            "module_descricao": MODULE_DESCRICAO,
            "module_tesouro_name": MODULE_TESOURO_NAME,
            "module_tesouro_descricao": MODULE_TESOURO_DESCRICAO,
            "module_tesouro_pronto": MODULE_TESOURO_PRONTO,
            "usuario": usuario_da_sessao(request),
        },
    )


@app.get("/fluxo", response_class=HTMLResponse)
def pagina_fluxo(request: Request):
    return templates.TemplateResponse("index.html", contexto_fluxo(request))


@app.get("/tesouro", response_class=HTMLResponse)
def pagina_tesouro(request: Request):
    if MODULE_TESOURO_PRONTO:
        # Quando o módulo estiver pronto, esta rota passa a renderizar a tela real.
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        "em_construcao.html",
        {
            "request": request,
            "app_name": MODULE_TESOURO_NAME,
            "portal_name": PORTAL_NAME,
            "module_name": MODULE_TESOURO_NAME,
            "module_descricao": MODULE_TESOURO_DESCRICAO,
            "usuario": usuario_da_sessao(request),
        },
    )


@app.get("/usuarios", response_class=HTMLResponse)
def pagina_usuarios(request: Request):
    usuario = usuario_da_sessao(request)
    if not usuario:
        return RedirectResponse(url="/?login=1&next=/usuarios", status_code=302)
    if not usuario["eh_admin"]:
        # Editores autenticados não gerenciam usuários — voltam ao portal.
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "usuarios.html",
        {
            "request": request,
            "app_name": PORTAL_NAME,
            "portal_name": PORTAL_NAME,
            "module_name": MODULE_NAME,
            "usuario": usuario,
        },
    )


# ------------------------------------------------------------------
# API — autenticação
# ------------------------------------------------------------------


@app.get("/api/auth/me")
def api_auth_me(request: Request):
    usuario = usuario_da_sessao(request)
    return {
        "autenticado": usuario is not None,
        "usuario": usuario,
        "meses_liberados": meses_liberados(request) if usuario else [],
    }


@app.post("/api/auth/login")
def api_auth_login(request: Request, login: str = Form(...), senha: str = Form(...)):
    usuario = auth.autenticar(login, senha)
    if not usuario:
        raise HTTPException(status_code=401, detail="Login ou senha incorretos.")

    request.session["user_id"] = usuario["id"]
    request.session["unlocked_months"] = []
    return {"ok": True, "usuario": usuario}


@app.post("/api/auth/logout")
def api_auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.post("/api/auth/confirmar-senha")
def api_auth_confirmar_senha(request: Request, senha: str = Form(...)):
    usuario = exige_login(request)
    if not auth.confirmar_senha(usuario["id"], senha):
        raise HTTPException(status_code=401, detail="Senha incorreta.")
    return {"ok": True, "usuario": usuario}


# ------------------------------------------------------------------
# API — usuários (admin)
# ------------------------------------------------------------------


@app.get("/api/usuarios")
def api_listar_usuarios(request: Request):
    exige_admin(request)
    return {"usuarios": auth.listar_usuarios()}


@app.post("/api/usuarios")
async def api_criar_usuario(request: Request):
    exige_admin(request)
    corpo = await request.json()
    try:
        usuario = auth.criar_usuario(
            nome=corpo.get("nome") or "",
            login=corpo.get("login") or "",
            senha=corpo.get("senha") or "",
            eh_admin=bool(corpo.get("eh_admin")),
            ativo=bool(corpo.get("ativo", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "usuario": usuario}


@app.put("/api/usuarios/{user_id}")
async def api_atualizar_usuario(request: Request, user_id: int):
    exige_admin(request)
    corpo = await request.json()
    try:
        usuario = auth.atualizar_usuario(
            user_id,
            nome=corpo.get("nome"),
            login=corpo.get("login"),
            senha=corpo.get("senha"),
            eh_admin=corpo.get("eh_admin"),
            ativo=corpo.get("ativo"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "usuario": usuario}


@app.delete("/api/usuarios/{user_id}")
def api_excluir_usuario(request: Request, user_id: int):
    admin = exige_admin(request)
    if admin["id"] == user_id:
        raise HTTPException(status_code=400, detail="Você não pode excluir a própria conta enquanto estiver logado.")
    try:
        auth.excluir_usuario(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


# ------------------------------------------------------------------
# API — consulta e gráficos
# ------------------------------------------------------------------


@app.get("/api/painel")
def api_painel(
    periodo: str = Query("mes"),
    inicio: Optional[str] = None,
    fim: Optional[str] = None,
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    busca: Optional[str] = None,
):
    """Uma única chamada devolve tudo que a tela precisa após uma mudança de filtro."""
    start, end = intervalo_da_requisicao(periodo, inicio, fim)
    filtros = filtros_da_requisicao(tipo, categoria, busca)

    return {
        "periodo": {
            "inicio": start.isoformat(),
            "fim": end.isoformat(),
            "rotulo": rotulo_periodo(start, end),
        },
        "indicadores": analytics.indicadores(start, end, **filtros),
        "evolucao": analytics.evolucao_diaria(start, end, **filtros),
        "categorias": analytics.composicao_por_categoria(start, end, **filtros),
        "previsto_realizado": analytics.previsto_versus_realizado(start, end, **filtros),
        "mensal": analytics.comparativo_mensal(),
        "calendario": analytics.calendario(
            end.year, end.month if start.year == end.year and start.month == end.month else None
        ),
        "ranking": analytics.ranking(start, end, limite=8, **filtros),
        "movimentos": repository.fetch_movimentos(start, end, **filtros),
    }


@app.get("/api/movimentos")
def api_movimentos(
    periodo: str = Query("mes"),
    inicio: Optional[str] = None,
    fim: Optional[str] = None,
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    busca: Optional[str] = None,
):
    start, end = intervalo_da_requisicao(periodo, inicio, fim)
    filtros = filtros_da_requisicao(tipo, categoria, busca)
    return {"movimentos": repository.fetch_movimentos(start, end, **filtros)}


@app.get("/api/calendario")
def api_calendario(ano: int, mes: Optional[int] = None):
    return analytics.calendario(ano, mes)


@app.get("/api/mensal")
def api_mensal(anos: Optional[str] = None):
    lista = [int(a) for a in anos.split(",") if a.strip().isdigit()] if anos else None
    return analytics.comparativo_mensal(lista)


# ------------------------------------------------------------------
# API — lançamentos do dia
# ------------------------------------------------------------------


@app.get("/api/dia/{dia}")
def api_obter_dia(request: Request, dia: str):
    alvo = parse_date(dia)
    liberados = meses_liberados(request)
    autenticado = esta_autenticado(request)

    receitas = merge_with_template(repository.fetch_day(alvo, "receita"), template_for("receita"))
    despesas = merge_with_template(repository.fetch_day(alvo, "despesa"), template_for("despesa"))
    totais = repository.totais_do_dia(alvo)
    saldo_inicial = repository.saldo_inicial_do_dia(alvo)

    return {
        "data": alvo.isoformat(),
        "editavel": can_edit_day(alvo, liberados, autenticado=autenticado),
        "mes_encerrado": is_past_month(alvo),
        "mes": month_key(alvo),
        "autenticado": autenticado,
        "receitas": receitas,
        "despesas": despesas,
        "ajustes_saldo": repository.listar_ajustes_saldo(alvo, alvo),
        "totais": {
            **totais,
            "saldo_inicial": saldo_inicial,
            "saldo_final": saldo_inicial + totais["receita_realizada"] - totais["despesa_realizada"],
        },
    }


@app.post("/api/dia/{dia}")
async def api_salvar_dia(request: Request, dia: str):
    alvo = parse_date(dia)
    usuario = exige_permissao(request, alvo)

    corpo = await request.json()
    salvos = {}
    origem = f"manual:{usuario['login']}"

    for tipo in ("receita", "despesa"):
        chave = f"{tipo}s"
        if chave not in corpo:
            continue
        linhas = normalize_lancamentos(corpo.get(chave) or [])
        antes = repository.fetch_day(alvo, tipo)
        salvos[tipo] = repository.replace_day(alvo, tipo, linhas, source=origem)
        historico.registrar(
            acao="salvar_dia",
            data_ref=alvo,
            tipo=tipo,
            usuario=usuario,
            origem=origem,
            antes=antes,
            depois=linhas,
        )

    totais = repository.totais_do_dia(alvo)
    saldo_inicial = repository.saldo_inicial_do_dia(alvo)

    return {
        "ok": True,
        "salvos": salvos,
        "totais": {
            **totais,
            "saldo_inicial": saldo_inicial,
            "saldo_final": saldo_inicial + totais["receita_realizada"] - totais["despesa_realizada"],
        },
    }


# ------------------------------------------------------------------
# API — histórico de auditoria
# ------------------------------------------------------------------


@app.get("/api/historico")
def api_historico(
    periodo: str = Query("mes"),
    inicio: Optional[str] = None,
    fim: Optional[str] = None,
    data_ref: Optional[str] = None,
    usuario: Optional[str] = None,
    acao: Optional[str] = None,
    tipo: Optional[str] = None,
    busca: Optional[str] = None,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(25, ge=1, le=100),
):
    start, end = intervalo_da_requisicao(periodo, inicio, fim)
    alvo = parse_date(data_ref) if data_ref else None
    resultado = historico.listar(
        inicio=start,
        fim=end,
        data_ref=alvo,
        usuario_login=usuario,
        acao=acao,
        tipo=tipo,
        busca=busca,
        pagina=pagina,
        por_pagina=por_pagina,
    )
    return {
        "periodo": {"inicio": start.isoformat(), "fim": end.isoformat()},
        "historico": resultado["itens"],
        "paginacao": {
            "total": resultado["total"],
            "pagina": resultado["pagina"],
            "por_pagina": resultado["por_pagina"],
            "total_paginas": resultado["total_paginas"],
        },
        "opcoes": historico.opcoes_filtro(),
    }


@app.get("/api/historico/{evento_id}")
def api_historico_detalhe(evento_id: int):
    item = historico.obter(evento_id)
    if not item:
        raise HTTPException(status_code=404, detail="Registro de histórico não encontrado.")
    return item


@app.post("/api/historico/{evento_id}/restaurar")
def api_historico_restaurar(request: Request, evento_id: int):
    """Restaura o snapshot *antes* da alteração (desfaz a ação registrada)."""
    item = historico.obter(evento_id)
    if not item:
        raise HTTPException(status_code=404, detail="Registro de histórico não encontrado.")
    if not item.get("tipo"):
        raise HTTPException(status_code=400, detail="Este evento não possui tipo restaurável.")

    alvo = parse_date(item["data_ref"])
    usuario = exige_permissao(request, alvo)
    tipo = item["tipo"]
    linhas = normalize_lancamentos(item.get("antes") or [])
    origem = f"restaurar:{usuario['login']}:hist#{evento_id}"

    antes = repository.fetch_day(alvo, tipo)
    repository.replace_day(alvo, tipo, linhas, source=origem)
    novo = historico.registrar(
        acao="restaurar",
        data_ref=alvo,
        tipo=tipo,
        usuario=usuario,
        origem=origem,
        antes=antes,
        depois=linhas,
    )

    return {"ok": True, "historico": novo, "data": alvo.isoformat(), "tipo": tipo}


# ------------------------------------------------------------------
# API — ajuste de saldo (imutável)
# ------------------------------------------------------------------


@app.get("/api/ajustes-saldo")
def api_listar_ajustes(
    periodo: str = Query("mes"),
    inicio: Optional[str] = None,
    fim: Optional[str] = None,
):
    start, end = intervalo_da_requisicao(periodo, inicio, fim)
    return {"ajustes": repository.listar_ajustes_saldo(start, end)}


@app.post("/api/ajustes-saldo")
def api_criar_ajuste(
    request: Request,
    data: str = Form(...),
    valor: str = Form(...),
    motivo: str = Form(...),
    senha: str = Form(...),
):
    """Cria ajuste de saldo. Exige login + confirmação de senha. Não pode ser editado depois."""
    usuario = exige_login(request)
    if not auth.confirmar_senha(usuario["id"], senha):
        raise HTTPException(status_code=401, detail="Senha incorreta.")

    alvo = parse_date(data)
    # Ajuste em mês histórico também exige mês liberado na sessão.
    if is_past_month(alvo) and month_key(alvo) not in meses_liberados(request):
        raise HTTPException(
            status_code=403,
            detail=f"O mês {month_key(alvo)} é histórico. Libere-o antes de lançar o ajuste.",
        )

    try:
        criado = repository.criar_ajuste_saldo(
            alvo,
            parse_number(valor),
            motivo,
            login=usuario["login"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    historico.registrar(
        acao="ajuste_saldo",
        data_ref=alvo,
        tipo=criado["tipo"],
        usuario=usuario,
        origem=criado["source"],
        antes=[],
        depois=[
            {
                "categoria": criado["categoria"],
                "descricao": criado["descricao"],
                "prevista": 0,
                "realizada": criado["realizada"],
            }
        ],
    )

    return {"ok": True, "ajuste": criado}


@app.delete("/api/ajustes-saldo/{ajuste_id}")
def api_excluir_ajuste(request: Request, ajuste_id: int, senha: str = Form(...)):
    """Somente admin master pode excluir ajuste, com confirmação de senha."""
    admin = exige_admin(request)
    if not auth.confirmar_senha(admin["id"], senha):
        raise HTTPException(status_code=401, detail="Senha incorreta.")

    try:
        removido = repository.excluir_ajuste_saldo(ajuste_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    historico.registrar(
        acao="excluir_ajuste",
        data_ref=parse_date(removido["data"]),
        tipo=removido["tipo"],
        usuario=admin,
        origem=f"excluir:{admin['login']}",
        antes=[
            {
                "categoria": removido["categoria"],
                "descricao": removido["descricao"],
                "prevista": 0,
                "realizada": removido["realizada"],
            }
        ],
        depois=[],
    )
    return {"ok": True, "excluido": removido}


# ------------------------------------------------------------------
# API — trava de mês histórico
# ------------------------------------------------------------------


@app.post("/api/meses/liberar")
def api_liberar_mes(request: Request, mes: str = Form(...), senha: str = Form(...)):
    usuario = exige_login(request)
    if not auth.confirmar_senha(usuario["id"], senha):
        raise HTTPException(status_code=401, detail="Senha incorreta.")

    liberados = meses_liberados(request)
    if mes not in liberados:
        liberados.append(mes)
    request.session["unlocked_months"] = liberados

    return {"ok": True, "meses_liberados": liberados}


@app.post("/api/meses/bloquear")
def api_bloquear_mes(request: Request, mes: str = Form(...)):
    exige_login(request)
    liberados = [m for m in meses_liberados(request) if m != mes]
    request.session["unlocked_months"] = liberados
    return {"ok": True, "meses_liberados": liberados}


# ------------------------------------------------------------------
# API — importação
# ------------------------------------------------------------------


@app.post("/api/importar")
async def api_importar(request: Request, arquivos: list[UploadFile]):
    usuario = exige_login(request)
    liberados = meses_liberados(request)
    relatorio = {"processados": [], "ignorados": [], "erros": [], "dias": []}
    dias_afetados: set[date] = set()

    for arquivo in arquivos:
        conteudo = await arquivo.read()
        nome = arquivo.filename or "arquivo"

        destino = os.path.join(
            get_uploads_dir(), f"{datetime.now():%Y%m%d_%H%M%S}_{os.path.basename(nome)}"
        )
        try:
            with open(destino, "wb") as saida:
                saida.write(conteudo)
        except OSError:
            pass

        try:
            if nome.lower().endswith(".pdf"):
                resultado = _importar_pdf(nome, conteudo, liberados, usuario)
            elif nome.lower().endswith(".txt") or nome.lower().endswith(".csv"):
                resultado = _importar_texto(nome, conteudo, liberados, usuario)
            else:
                relatorio["erros"].append({"arquivo": nome, "motivo": "Formato não suportado."})
                continue
        except Exception as exc:
            relatorio["erros"].append({"arquivo": nome, "motivo": str(exc)})
            continue

        relatorio["processados"].append({"arquivo": nome, **resultado["resumo"]})
        relatorio["ignorados"].extend(resultado["ignorados"])
        dias_afetados.update(resultado["dias"])

    relatorio["dias"] = sorted(d.isoformat() for d in dias_afetados)
    return relatorio


def _importar_pdf(nome: str, conteudo: bytes, liberados: list[str], usuario: dict) -> dict:
    login = usuario["login"]
    linhas = importers.extract_lines_from_pdf(conteudo)
    dias = importers.datas_no_extrato(conteudo)

    gravados = 0
    atualizados: list[date] = []
    ignorados: list[dict] = []

    if dias:
        for dia in dias:
            if not can_edit_day(dia, liberados, autenticado=True):
                motivo = "mês histórico bloqueado" if is_past_month(dia) else "sem permissão"
                ignorados.append({"data": dia.isoformat(), "motivo": motivo})
                continue
            receitas = importers.receita_do_extrato(dia, conteudo, lines=linhas)
            if not any(r["realizada"] for r in receitas):
                continue
            origem = f"pdf-auto:{login}:{nome}"
            antes = repository.fetch_day(dia, "receita")
            repository.replace_day(dia, "receita", receitas, source=origem)
            historico.registrar(
                acao="importar",
                data_ref=dia,
                tipo="receita",
                usuario=usuario,
                origem=origem,
                antes=antes,
                depois=receitas,
            )
            gravados += 1
            atualizados.append(dia)

        return {
            "resumo": {"tipo": "extrato bancário", "dias_gravados": gravados, "dias_detectados": len(dias)},
            "dias": atualizados,
            "ignorados": ignorados,
        }

    registros = importers.parse_pdf_tabular(conteudo)
    return _gravar_registros(nome, registros, liberados, usuario=usuario, origem=f"pdf-tabela:{login}")


def _importar_texto(nome: str, conteudo: bytes, liberados: list[str], usuario: dict) -> dict:
    return _gravar_registros(
        nome,
        importers.parse_txt(conteudo),
        liberados,
        usuario=usuario,
        origem=f"upload:{usuario['login']}",
    )


def _gravar_registros(
    nome: str,
    registros: list[dict],
    liberados: list[str],
    *,
    usuario: dict,
    origem: str,
) -> dict:
    por_dia_tipo: dict[tuple[date, str], list[dict]] = {}
    hoje = date.today()

    for registro in registros:
        dia = registro.get("data") or hoje
        tipo = registro.get("tipo") or (
            "despesa" if registro.get("prevista") and not registro.get("realizada") else "receita"
        )
        por_dia_tipo.setdefault((dia, tipo), []).append(registro)

    gravados = 0
    atualizados: list[date] = []
    ignorados: list[dict] = []

    for (dia, tipo), linhas in por_dia_tipo.items():
        if not can_edit_day(dia, liberados, autenticado=True):
            motivo = "mês histórico bloqueado" if is_past_month(dia) else "sem permissão"
            ignorados.append({"data": dia.isoformat(), "motivo": motivo})
            continue
        mescladas = merge_with_template(linhas, template_for(tipo))
        fonte = f"{origem}:{nome}"
        antes = repository.fetch_day(dia, tipo)
        repository.replace_day(dia, tipo, mescladas, source=fonte)
        historico.registrar(
            acao="importar",
            data_ref=dia,
            tipo=tipo,
            usuario=usuario,
            origem=fonte,
            antes=antes,
            depois=mescladas,
        )
        gravados += 1
        atualizados.append(dia)

    return {
        "resumo": {"tipo": "planilha", "dias_gravados": gravados, "linhas_lidas": len(registros)},
        "dias": sorted(set(atualizados)),
        "ignorados": ignorados,
    }

# ------------------------------------------------------------------
# API — exportação
# ------------------------------------------------------------------


@app.get("/api/exportar/excel")
def api_exportar_excel(
    periodo: str = Query("mes"),
    inicio: Optional[str] = None,
    fim: Optional[str] = None,
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    busca: Optional[str] = None,
):
    start, end = intervalo_da_requisicao(periodo, inicio, fim)
    filtros = filtros_da_requisicao(tipo, categoria, busca)

    movimentos = repository.fetch_movimentos(start, end, **filtros)
    resumo = analytics.resumo_diario(start, end, **filtros)
    conteudo, nome = exporters.export_excel(movimentos, resumo, start, end)

    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@app.get("/api/exportar/pdf")
def api_exportar_pdf(
    periodo: str = Query("mes"),
    inicio: Optional[str] = None,
    fim: Optional[str] = None,
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    busca: Optional[str] = None,
):
    start, end = intervalo_da_requisicao(periodo, inicio, fim)
    filtros = filtros_da_requisicao(tipo, categoria, busca)

    movimentos = repository.fetch_movimentos(start, end, **filtros)
    receitas = [m for m in movimentos if m["tipo"] == "receita"]
    despesas = [m for m in movimentos if m["tipo"] == "despesa"]
    resumo = analytics.resumo_diario(start, end, **filtros)
    saldo_inicial = repository.saldo_inicial_do_dia(start)

    conteudo, nome = exporters.export_pdf_periodo(start, end, receitas, despesas, resumo, saldo_inicial)

    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


# ------------------------------------------------------------------


def rotulo_periodo(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%d/%m/%Y")
    return f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"


@app.exception_handler(HTTPException)
def tratar_http_exception(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"erro": exc.detail})
