# Fluxo de Caixa

Portal **Fluxo de Caixa** com seleção de módulos. O módulo **FUNDEB** já está disponível
(acompanhamento diário de receitas, despesas e saldo). O módulo **Tesouro** aparece no
portal como *Em construção*.
Interface web em HTML/CSS, backend em Python com FastAPI e banco SQLite.

## Como rodar

```bash
pip install -r requirements.txt
python run.py
```

Acesse `http://localhost:8000` (portal). O módulo FUNDEB fica em `/fluxo`; Tesouro em `/tesouro` (em construção).

Opções úteis:

```bash
python run.py --port 9000      # outra porta
python run.py --host 0.0.0.0   # liberar o acesso pela rede local
python run.py --reload         # recarrega ao salvar o código (desenvolvimento)
python run.py --stop           # encerra o que estiver na porta (útil no Windows)
```

## Deploy com Docker (VPS)

Porta padrão publicada: **3070** → `http://31.97.167.75:3070`

```bash
# 1) Configure as credenciais
cp .env.example .env
nano .env   # ADMIN_LOGIN, ADMIN_PASSWORD, SESSION_SECRET, APP_PORT=3070

# 2) Suba o container
docker compose up -d --build

# 3) Acompanhe os logs
docker compose logs -f
```

Persistência: `./data`, `./uploads` e `./exports` são montados no container (o SQLite fica em `data/fluxo.db`).

Comandos úteis:

```bash
docker compose ps
docker compose restart
docker compose down
```

## Acesso e edição

**Visualizar é livre.** Não precisa de cadastro para consultar Painel, movimentos e lançamentos.

**Editar o módulo** exige usuário cadastrado (editor ou admin). No FUNDEB, clique em **Editar** e informe login/senha.

**Gerenciar usuários** é exclusivo do **administrador master**. Editores não acessam `/usuarios`.

Na primeira execução (banco sem usuários), o sistema cria o administrador com os valores
definidos no arquivo **`.env`** (`ADMIN_LOGIN`, `ADMIN_PASSWORD`, `ADMIN_NOME`).
Não há senha padrão no código — sem `.env` a aplicação não sobe.

Administradores gerenciam responsáveis em `/usuarios`.

**Mês corrente.** Após o login, a edição fica liberada.

**Meses históricos.** Ao tentar editar um mês já encerrado, o sistema avisa que são
dados históricos e pede a **senha do usuário logado** para liberar na sessão do navegador.

## O que o módulo FUNDEB faz

**Painel** — Indicadores do período (saldo inicial, receita, despesa, resultado e saldo final)
e oito visualizações:

| Gráfico | O que mostra |
|---|---|
| Evolução diária | Receita e despesa por dia, com a curva do saldo acumulado |
| Origem das receitas | Participação de cada categoria no total arrecadado |
| Destino das despesas | Participação de cada categoria no total gasto |
| Previsto x Realizado | Desvio e percentual de execução por categoria |
| Comparativo mensal | Receita mês a mês comparando exercícios, com acumulado |
| Calendário | Intensidade da movimentação em cada dia do ano |
| Maiores entradas | Lançamentos de receita mais relevantes |
| Maiores saídas | Lançamentos de despesa mais relevantes |

**Lançamentos** — Grade de digitação por dia, separada em receita e despesa, com os
templates padrão de categorias. Enter desce para a linha seguinte e `Ctrl+S` salva.

**Movimentos** — Tabela completa do período, ordenável por qualquer coluna.

**Histórico** — Auditoria de quem alterou o quê e quando (edição manual, importação,
restauração ou ajuste de saldo), com snapshot antes/depois e opção de restaurar.
Filtros por usuário, tipo de alteração, receita/despesa, datas e busca; lista paginada.

**Ajuste de saldo** — Lançamento especial para saldo inicial ou corte. O valor informado
vira o **saldo inicial** daquela data (o fluxo começa a partir dali, sem herdar o
acumulado anterior). Exige confirmação de senha e motivo; fica imutável.
Somente o admin master pode excluir.

**Importar** — Leitura de extratos bancários em PDF e planilhas `.txt`/`.csv` (requer login).

A barra de filtros no topo (período, tipo, categoria e busca) vale para todas as abas
e também define o recorte usado nas exportações em Excel e PDF.

## Regras de negócio

**Previsto e realizado.** Cada lançamento tem um valor previsto e um realizado.
Os indicadores de saldo consideram **apenas valores realizados**.

**Saldo.** O saldo inicial de um período é o acumulado de
`receita realizada − despesa realizada` de todos os dias anteriores ao início do período.

**Importação de extrato.** O sistema lê as linhas do PDF que começam com uma data,
ignora as terminadas em `D` (débitos), pega o último valor monetário da linha e
classifica pela origem encontrada no texto:

| Categoria | Descrição | Padrão procurado |
|---|---|---|
| IMPOSTOS | ORIGEM ITR | `ITR` |
| IMPOSTOS | ORIGEM IPVA | `IPVA` |
| IMPOSTOS | ORIGEM ITCMD | `ITCMD` |
| IMPOSTOS | ORIGEM IPI-EXP | `IPI-EXP` |
| IMPOSTOS | ORIGEM ICMS | `RECEBIMENTO DE ICMS`, `ICMS` |
| IMPOSTOS | ORIGEM FPM | `FPE/FPM`, `FPM` |

Importar um dia **substitui** os lançamentos daquele dia e tipo.

## Configuração

Credenciais e segredos **somente** no arquivo `.env` (não versionado). Use `.env.example` como modelo.

| Variável | Obrigatória | Função |
|---|---|---|
| `ADMIN_PASSWORD` | Sim (1ª execução) | Senha do administrador seed |
| `SESSION_SECRET` | Sim | Chave de assinatura dos cookies |
| `ADMIN_LOGIN` | Não (`admin`) | Login do administrador seed |
| `ADMIN_NOME` | Não (`Administrador`) | Nome exibido do admin seed |
| `APP_PORT` | Não (`3070`) | Porta publicada no Docker |
| `DATA_DIR` | Não | Pasta do banco `fluxo.db` |
| `UPLOADS_DIR` | Não | Arquivos importados |
| `EXPORTS_DIR` | Não | Pasta de exportações |

```bash
cp .env.example .env
# preencha ADMIN_PASSWORD e SESSION_SECRET
python -c "import secrets; print(secrets.token_hex(32))"  # sugestão de SESSION_SECRET
```

## Estrutura do projeto

```
app/
  config.py       Caminhos, seed do admin e listas de categorias
  auth.py         Hash de senha, CRUD de usuários
  historico.py    Auditoria de alterações (quem/quando/antes/depois)
  finance.py      Regras puras: conversão de valores, templates, trava de mês
  repository.py   Acesso ao SQLite (movimentos)
  analytics.py    Agregações que alimentam os gráficos
  importers.py    Leitura de extratos PDF e planilhas
  exporters.py    Geração de Excel e PDF
  main.py         Rotas HTTP
  templates/      HTML (Jinja2)
  static/         CSS, JavaScript e ECharts
data/fluxo.db     Banco de dados
run.py            Ponto de entrada
```

As camadas `finance`, `repository`, `analytics`, `importers`, `exporters` e `auth`
não dependem do framework web e podem ser usadas em scripts ou testes.

## Banco de dados

Tabela `movimentos`:

| Coluna | Conteúdo |
|---|---|
| `data` | Data do lançamento (`YYYY-MM-DD`) |
| `tipo` | `receita` ou `despesa` |
| `categoria` | Categoria padronizada |
| `descricao` | Descrição da linha |
| `valor1` | Valor **previsto** |
| `valor2` | Valor **realizado** |
| `source` | Origem do dado (`manual:login`, `upload:…`, `pdf-auto:…`) |

Tabela `usuarios`:

| Coluna | Conteúdo |
|---|---|
| `nome` | Nome de exibição |
| `login` | Login único |
| `senha_hash` | PBKDF2-SHA256 |
| `eh_admin` | Pode gerenciar usuários |
| `ativo` | Conta habilitada |

O schema de `movimentos` é o mesmo da versão anterior, então o histórico é preservado.

## Páginas e API

| Rota | Função |
|---|---|
| `GET /` | Portal Fluxo de Caixa (seleção de módulos) |
| `GET /fluxo` | Módulo FUNDEB |
| `GET /tesouro` | Módulo Tesouro (em construção) |
| `GET /usuarios` | Cadastro de usuários (somente admin master) |
| `POST /api/auth/login` | Autentica e grava sessão |
| `POST /api/auth/logout` | Encerra sessão |
| `GET /api/auth/me` | Estado da sessão |
| `POST /api/auth/confirmar-senha` | Revalida senha do usuário logado |
| `GET/POST/PUT/DELETE /api/usuarios` | CRUD de usuários (admin) |
| `POST /api/ajustes-saldo` | Cria ajuste de saldo (senha + motivo; imutável) |
| `DELETE /api/ajustes-saldo/{id}` | Exclui ajuste (somente admin + senha) |
| `GET /api/historico` | Lista alterações com filtros e paginação |
| `GET /api/historico/{id}` | Detalhe com snapshot antes/depois |
| `POST /api/historico/{id}/restaurar` | Restaura a versão anterior (requer login) |
| `GET /api/painel` | Indicadores, séries e movimentos |
| `GET /api/dia/{data}` | Lançamentos do dia |
| `POST /api/dia/{data}` | Grava lançamentos (requer login) |
| `POST /api/meses/liberar` | Libera mês histórico (senha do usuário) |
| `POST /api/importar` | Importa arquivos (requer login) |
| `GET /api/exportar/excel` | Planilha do período filtrado |
| `GET /api/exportar/pdf` | Relatório em PDF do período filtrado |

Documentação interativa: `/api/docs`.

## Funcionamento offline

O ECharts está incluído em `app/static/vendor/`, então o sistema não depende de
internet nem de CDN.
