"""Aplicação web do Fluxo de Caixa FUNDEB (FastAPI + Jinja2)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import analytics, auth, backup, bb_extrato, exporters, historico, importers, previsao, repository, sgp
from .config import (
    APP_NAME,
    CATEGORIAS_DESPESA,
    CATEGORIAS_RECEITA,
    MODULE_DESCRICAO,
    MODULE_EXTRATO_BB_DESCRICAO,
    MODULE_EXTRATO_BB_NAME,
    MODULE_EXTRATO_BB_PRONTO,
    MODULE_NAME,
    MODULE_SGP_DESCRICAO,
    MODULE_SGP_NAME,
    MODULE_SGP_PRONTO,
    MODULE_TESOURO_DESCRICAO,
    MODULE_TESOURO_NAME,
    MODULE_TESOURO_PRONTO,
    PORTAL_NAME,
    app_url,
    get_root_path,
    get_session_secret,
    get_uploads_dir,
)
from .finance import (
    can_edit_day,
    clean_text,
    format_currency,
    is_past_month,
    merge_with_template,
    month_key,
    normalize_lancamentos,
    parse_number,
    resolve_period,
    tem_detalhe_despesa,
    template_for,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_PATH = get_root_path()

app = FastAPI(title=PORTAL_NAME, docs_url="/api/docs", redoc_url=None, root_path=ROOT_PATH)
app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret(),
    session_cookie="fundeb_session",
    path=ROOT_PATH or "/",
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.filters["moeda"] = format_currency
templates.env.globals["root_path"] = ROOT_PATH
templates.env.globals["app_url"] = app_url


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
        request,
        "modulos.html",
        {
            "app_name": PORTAL_NAME,
            "portal_name": PORTAL_NAME,
            "module_name": MODULE_NAME,
            "module_descricao": MODULE_DESCRICAO,
            "module_tesouro_name": MODULE_TESOURO_NAME,
            "module_tesouro_descricao": MODULE_TESOURO_DESCRICAO,
            "module_tesouro_pronto": MODULE_TESOURO_PRONTO,
            "module_extrato_bb_name": MODULE_EXTRATO_BB_NAME,
            "module_extrato_bb_descricao": MODULE_EXTRATO_BB_DESCRICAO,
            "module_extrato_bb_pronto": MODULE_EXTRATO_BB_PRONTO,
            "module_sgp_name": MODULE_SGP_NAME,
            "module_sgp_descricao": MODULE_SGP_DESCRICAO,
            "module_sgp_pronto": MODULE_SGP_PRONTO,
            "usuario": usuario_da_sessao(request),
        },
    )


@app.get("/fluxo", response_class=HTMLResponse)
def pagina_fluxo(request: Request):
    return templates.TemplateResponse(request, "index.html", contexto_fluxo(request))


@app.get("/extrato-bb", response_class=HTMLResponse)
def pagina_extrato_bb(request: Request):
    return templates.TemplateResponse(
        request,
        "extrato_bb.html",
        {
            "app_name": MODULE_EXTRATO_BB_NAME,
            "portal_name": PORTAL_NAME,
            "module_name": MODULE_EXTRATO_BB_NAME,
            "module_descricao": MODULE_EXTRATO_BB_DESCRICAO,
            "usuario": usuario_da_sessao(request),
        },
    )


@app.get("/sgp", response_class=HTMLResponse)
def pagina_sgp(request: Request):
    return templates.TemplateResponse(
        request,
        "sgp.html",
        {
            "app_name": MODULE_SGP_NAME,
            "portal_name": PORTAL_NAME,
            "module_name": MODULE_SGP_NAME,
            "module_descricao": MODULE_SGP_DESCRICAO,
            "usuario": usuario_da_sessao(request),
        },
    )


@app.get("/tesouro", response_class=HTMLResponse)
def pagina_tesouro(request: Request):
    if MODULE_TESOURO_PRONTO:
        # Quando o módulo estiver pronto, esta rota passa a renderizar a tela real.
        return RedirectResponse(url=app_url("/"), status_code=302)
    return templates.TemplateResponse(
        request,
        "em_construcao.html",
        {
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
        return RedirectResponse(
            url=app_url("/?login=1&next=") + app_url("/usuarios"),
            status_code=302,
        )
    if not usuario["eh_admin"]:
        # Editores autenticados não gerenciam usuários — voltam ao portal.
        return RedirectResponse(url=app_url("/"), status_code=302)

    return templates.TemplateResponse(
        request,
        "usuarios.html",
        {
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


@app.put("/api/auth/perfil")
async def api_auth_atualizar_perfil(request: Request):
    """Qualquer usuário autenticado altera o próprio nome, login e/ou senha."""
    logado = exige_login(request)
    corpo = await request.json()
    senha_nova = (corpo.get("senha_nova") or "").strip() or None
    senha_nova_conf = (corpo.get("senha_nova_conf") or "").strip() or None
    if senha_nova or senha_nova_conf:
        if senha_nova != senha_nova_conf:
            raise HTTPException(status_code=400, detail="A confirmação da nova senha não confere.")
    try:
        usuario = auth.atualizar_perfil(
            logado["id"],
            nome=corpo.get("nome") or "",
            login=corpo.get("login") or "",
            senha_atual=corpo.get("senha_atual") or "",
            senha_nova=senha_nova,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    usuario = usuario_da_sessao(request)
    eh_admin = bool(usuario and usuario.get("eh_admin"))
    ano_mes = month_key(alvo)
    prev_mes = previsao.listar_mes(ano_mes)
    # Com previsão mensal ativa, a coluna Prevista fica travada para não-admin.
    receitas_db = repository.fetch_day(alvo, "receita")
    despesas_db = repository.fetch_day(alvo, "despesa")
    receitas = merge_with_template(receitas_db, template_for("receita"))
    # Despesa importada (CSV) mantém as linhas detalhadas; sem isso usa o template.
    if tem_detalhe_despesa(despesas_db):
        despesas = normalize_lancamentos(despesas_db)
    else:
        despesas = merge_with_template(despesas_db, template_for("despesa"))
    receitas = previsao.marcar_linhas_previsao(
        receitas, travada_prevista=bool(prev_mes["receita"]) and not eh_admin
    )
    despesas = previsao.marcar_linhas_previsao(
        despesas, travada_prevista=bool(prev_mes["despesa"]) and not eh_admin
    )
    totais = repository.totais_do_dia(alvo)
    saldo_inicial = repository.saldo_inicial_do_dia(alvo)

    return {
        "data": alvo.isoformat(),
        "editavel": can_edit_day(alvo, liberados, autenticado=autenticado),
        "mes_encerrado": is_past_month(alvo),
        "mes": ano_mes,
        "autenticado": autenticado,
        "eh_admin": eh_admin,
        "previsao_mensal": prev_mes,
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
    eh_admin = bool(usuario.get("eh_admin"))

    for tipo in ("receita", "despesa"):
        chave = f"{tipo}s"
        if chave not in corpo:
            continue
        linhas = normalize_lancamentos(corpo.get(chave) or [])
        antes = repository.fetch_day(alvo, tipo)
        valor_prev = None
        registro_prev = previsao.obter(month_key(alvo), tipo)
        if registro_prev:
            valor_prev = float(registro_prev["valor"])
        linhas = previsao.proteger_linhas_ao_salvar(
            antes,
            linhas,
            eh_admin=eh_admin,
            valor_previsao=valor_prev,
        )
        # Mantém source por linha quando existir; novas linhas usam origem manual.
        for linha in linhas:
            if not linha.get("source"):
                linha["source"] = origem
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


@app.get("/api/previsao-mensal")
def api_obter_previsao_mensal(
    request: Request,
    ano: Optional[int] = None,
    mes: Optional[int] = None,
    ano_mes: Optional[str] = None,
):
    if ano_mes:
        chave = ano_mes.strip()
    else:
        hoje = date.today()
        chave = f"{(ano or hoje.year):04d}-{(mes or hoje.month):02d}"
    usuario = usuario_da_sessao(request)
    dados = previsao.listar_mes(chave)
    return {
        **dados,
        "autenticado": usuario is not None,
        "eh_admin": bool(usuario and usuario.get("eh_admin")),
        "pode_alterar_receita": bool(
            usuario and (usuario.get("eh_admin") or not dados["receita"])
        ),
        "pode_alterar_despesa": bool(
            usuario and (usuario.get("eh_admin") or not dados["despesa"])
        ),
    }


@app.post("/api/previsao-mensal")
async def api_salvar_previsao_mensal(request: Request):
    corpo = await request.json()
    ano_mes = clean_text(corpo.get("ano_mes") or "")
    if ano_mes and len(ano_mes) >= 7:
        ano = int(ano_mes[:4])
        mes = int(ano_mes[5:7])
    else:
        ano = int(corpo.get("ano") or 0)
        mes = int(corpo.get("mes") or 0)

    try:
        inicio = date(ano, mes, 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Informe um mês válido (AAAA-MM).") from exc

    usuario = exige_permissao(request, inicio)

    def _campo(nome: str) -> Optional[float]:
        if nome not in corpo:
            return None
        return parse_number(corpo.get(nome))

    try:
        resultado = previsao.cadastrar_ou_atualizar(
            ano,
            mes,
            receita=_campo("receita"),
            despesa=_campo("despesa"),
            usuario=usuario,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, **resultado, "eh_admin": bool(usuario.get("eh_admin"))}


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
# API — backup / restauração do banco
# ------------------------------------------------------------------


@app.get("/api/backup/baixar")
def api_backup_baixar(request: Request):
    """Baixa o SQLite completo (mesmo formato usado na restauração)."""
    exige_admin(request)
    try:
        caminho = backup.gerar_backup_arquivo()
    except backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        path=str(caminho),
        media_type="application/x-sqlite3",
        filename=caminho.name,
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/backup/restaurar")
async def api_backup_restaurar(
    request: Request,
    arquivo: UploadFile = File(...),
    senha: str = Form(...),
):
    """Restaura o sistema a partir de um .db baixado anteriormente."""
    admin = exige_admin(request)
    if not auth.confirmar_senha(admin["id"], senha):
        raise HTTPException(status_code=401, detail="Senha incorreta.")

    nome = (arquivo.filename or "").lower()
    if not (nome.endswith(".db") or nome.endswith(".sqlite") or nome.endswith(".sqlite3")):
        raise HTTPException(
            status_code=400,
            detail="Envie o arquivo .db gerado pelo botão de backup deste sistema.",
        )

    conteudo = await arquivo.read()
    try:
        info = backup.restaurar_de_bytes(conteudo)
    except backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Sessões antigas podem apontar para usuários que não existem no backup.
    request.session.clear()
    return {
        "ok": True,
        "movimentos": info["movimentos"],
        "usuarios": info["usuarios"],
        "backup_anterior": info.get("backup_anterior"),
        "mensagem": "Banco restaurado. Faça login novamente.",
    }


@app.post("/api/backup/zerar")
async def api_backup_zerar(
    request: Request,
    senha: str = Form(...),
    confirmacao: str = Form(""),
):
    """Zera movimentos, histórico e previsões. Mantém cadastro de usuários."""
    admin = exige_admin(request)
    if not auth.confirmar_senha(admin["id"], senha):
        raise HTTPException(status_code=401, detail="Senha incorreta.")
    if (confirmacao or "").strip().upper() != "ZERAR":
        raise HTTPException(
            status_code=400,
            detail='Digite ZERAR no campo de confirmação para prosseguir.',
        )

    try:
        info = backup.zerar_dados()
    except backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "movimentos_apagados": info["movimentos_apagados"],
        "historico_apagado": info["historico_apagado"],
        "previsoes_apagadas": info["previsoes_apagadas"],
        "backup_anterior": info.get("backup_anterior"),
        "mensagem": "Dados operacionais apagados. Usuários preservados.",
    }


# ------------------------------------------------------------------
# API — Extrato Banco do Brasil (consulta visual)
# ------------------------------------------------------------------


@app.get("/api/bb-extrato")
def api_bb_extrato(
    inicio: Optional[str] = Query(None),
    fim: Optional[str] = Query(None),
    sinal: Optional[str] = Query(None),
    historico: Optional[str] = Query(None),
    busca: Optional[str] = Query(None),
    conta: Optional[str] = Query(None, description="agencia:conta ou vazio para todas"),
    incluir_saldos: bool = Query(False),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=10, le=200),
):
    start = parse_date(inicio) if inicio else None
    end = parse_date(fim) if fim else None
    if start and end and start > end:
        start, end = end, start
    return bb_extrato.consultar(
        inicio=start,
        fim=end,
        sinal=sinal,
        historico=historico,
        busca=busca,
        conta_id=conta,
        incluir_saldos=incluir_saldos,
        pagina=pagina,
        por_pagina=por_pagina,
    )


@app.get("/api/bb-extrato/glossario")
def api_bb_extrato_glossario():
    return {"glossario": bb_extrato.GLOSSARIO, "modo": bb_extrato.get_modo()}


@app.get("/api/bb-extrato/contas")
def api_bb_extrato_contas():
    from .bb_client import listar_contas_configuradas

    return {"contas": listar_contas_configuradas()}


@app.get("/api/bb-extrato/{item_id}")
def api_bb_extrato_detalhe(item_id: str):
    item = bb_extrato.obter_detalhe(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado.")
    return item


# ------------------------------------------------------------------
# API — SGP (sistema financeiro da prefeitura / SOAP)
# ------------------------------------------------------------------


@app.get("/api/sgp/status")
def api_sgp_status():
    return sgp.status()


@app.get("/api/sgp/meta")
def api_sgp_meta():
    return sgp.meta_ui()


@app.get("/api/sgp/grupos-ug")
def api_sgp_grupos_ug(ano: Optional[int] = Query(None)):
    try:
        return {"ano": ano or date.today().year, "grupos": sgp.listar_grupos_ug(ano or date.today().year)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao listar grupos UG: {exc}") from exc


@app.get("/api/sgp/consulta/{tipo}")
def api_sgp_consulta(
    tipo: str,
    ano: Optional[int] = Query(None),
    data_inicial: Optional[str] = Query(None),
    data_final: Optional[str] = Query(None),
    registro_inicial: int = Query(0, ge=0),
    quantidade: int = Query(100, ge=1, le=500),
    filtro_opcional: str = Query(""),
    cod_grupo_ug: int = Query(86),
    fonte_recurso: str = Query(""),
    busca: Optional[str] = Query(None),
    ug: Optional[str] = Query(None),
    fonte: Optional[str] = Query(None),
    credor: Optional[str] = Query(None),
):
    if tipo not in sgp.CONSULTAS:
        raise HTTPException(status_code=404, detail="Tipo de consulta inválido. Use nap ou empenho.")
    try:
        from .sgp_client import SgpError

        return sgp.consultar(
            tipo,
            ano=ano,
            data_inicial=data_inicial,
            data_final=data_final,
            registro_inicial=registro_inicial,
            quantidade=quantidade,
            filtro_opcional=filtro_opcional,
            cod_grupo_ug=cod_grupo_ug,
            fonte_recurso=fonte_recurso,
            busca=busca,
            ug=ug,
            fonte=fonte,
            credor=credor,
        )
    except SgpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha SGP: {exc}") from exc


@app.get("/api/sgp/operacoes")
def api_sgp_operacoes(cruzamento: bool = Query(False)):
    return sgp.listar_operacoes(apenas_cruzamento=cruzamento)


@app.get("/api/sgp/operacoes/{nome}")
def api_sgp_operacao_detalhe(nome: str):
    detalhe = sgp.detalhe_operacao(nome)
    if not detalhe:
        raise HTTPException(status_code=404, detail=f"Operação '{nome}' não encontrada.")
    return detalhe


@app.post("/api/sgp/invocar")
async def api_sgp_invocar(request: Request):
    """Invoca uma operação SOAP. Útil para explorar; o cruzamento usará wrappers depois."""
    exige_login(request)
    payload = await request.json()
    nome = (payload.get("operation") or payload.get("operacao") or "").strip()
    params = payload.get("params") or {}
    if not nome:
        raise HTTPException(status_code=400, detail="Informe o nome da operação.")
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="params deve ser um objeto.")

    try:
        from .sgp_client import SgpError

        return sgp.invocar_operacao(
            nome,
            params,
            username=payload.get("username"),
            password=payload.get("password"),
            timeout=int(payload.get("timeout") or 60),
        )
    except SgpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha SGP: {exc}") from exc


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
            elif nome.lower().endswith(".csv") and importers.eh_csv_despesa(conteudo):
                resultado = _importar_despesa_csv(nome, conteudo, liberados, usuario)
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

    # Print to PDF / scan = só imagem. Sem texto não há como ler ICMS/FPM etc.
    # O fallback tabular antigo podia travar ou gravar lixo e zerar o dia.
    if not importers.pdf_tem_texto_selecionavel(conteudo):
        raise importers.ImportError_(
            "Este PDF não tem texto selecionável (parece impressão ou captura de tela). "
            "No portal do Banco do Brasil, use a opção de baixar/salvar o extrato em PDF "
            "(arquivo com texto, como o Fundeb.pdf gerado pelo sistema do banco) — "
            "não use 'Imprimir para PDF' do Windows. Nenhum dado foi alterado."
        )

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

        if gravados == 0 and not ignorados:
            raise importers.ImportError_(
                "O extrato foi lido, mas nenhum crédito de receita (ICMS, FPM, IPI-EXP, "
                "IPVA, ITCMD, ITR) foi encontrado nos dias do arquivo. "
                "Nenhum dado foi alterado."
            )

        return {
            "resumo": {"tipo": "extrato bancário", "dias_gravados": gravados, "dias_detectados": len(dias)},
            "dias": atualizados,
            "ignorados": ignorados,
        }

    registros = importers.parse_pdf_tabular(conteudo)
    if not registros:
        raise importers.ImportError_(
            "Não foi possível ler lançamentos neste PDF. "
            "Envie o extrato de conta corrente baixado pelo portal do BB. "
            "Nenhum dado foi alterado."
        )
    return _gravar_registros(nome, registros, liberados, usuario=usuario, origem=f"pdf-tabela:{login}")


def _importar_despesa_csv(nome: str, conteudo: bytes, liberados: list[str], usuario: dict) -> dict:
    """Importa CSV de despesa: substitui o dia inteiro (mesmo comportamento da receita)."""
    login = usuario["login"]
    por_dia = importers.parse_despesa_csv(conteudo)
    gravados = 0
    atualizados: list[date] = []
    ignorados: list[dict] = []
    origem = f"csv-despesa:{login}:{nome}"

    for dia, linhas in sorted(por_dia.items()):
        if not can_edit_day(dia, liberados, autenticado=True):
            motivo = "mês histórico bloqueado" if is_past_month(dia) else "sem permissão"
            ignorados.append({"data": dia.isoformat(), "motivo": motivo})
            continue

        # Preserva previsão mensal já cadastrada ao reimportar o dia.
        registro_prev = previsao.obter(month_key(dia), "despesa")
        valor_prev = float(registro_prev["valor"]) if registro_prev else 0.0
        if valor_prev:
            for linha in linhas:
                linha["prevista"] = valor_prev

        antes = repository.fetch_day(dia, "despesa")
        repository.replace_day(dia, "despesa", linhas, source=origem)
        historico.registrar(
            acao="importar",
            data_ref=dia,
            tipo="despesa",
            usuario=usuario,
            origem=origem,
            antes=antes,
            depois=linhas,
        )
        gravados += 1
        atualizados.append(dia)

    return {
        "resumo": {
            "tipo": "despesa CSV",
            "dias_gravados": gravados,
            "dias_detectados": len(por_dia),
            "linhas": sum(len(v) for v in por_dia.values()),
        },
        "dias": atualizados,
        "ignorados": ignorados,
    }


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
