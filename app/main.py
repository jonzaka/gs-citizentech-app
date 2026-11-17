"""API do MVP: serve o site e recebe as pecas das outras disciplinas."""

import csv
import hmac
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

VERSAO = os.getenv("APP_VERSION", "dev")
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "mvp.db"
BASE_DIR = Path(__file__).parent
INDICADORES_CSV = BASE_DIR / "dados" / "indicadores.csv"
BOT_API_KEY = os.getenv("BOT_API_KEY", "")

# Centro de Sao Paulo; a area piloto fica em volta daqui.
SP_LAT, SP_LON = -23.5614, -46.6559
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

app = FastAPI(title="MVP CitizenTech", version=VERSAO, docs_url="/api/docs", redoc_url=None)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def criar_banco() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with closing(db()) as conn, conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS relatos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lat REAL NOT NULL, lon REAL NOT NULL,
                tipo TEXT NOT NULL, severidade TEXT NOT NULL,
                origem TEXT NOT NULL, simulado INTEGER NOT NULL DEFAULT 0,
                data TEXT NOT NULL)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                relato_id INTEGER, nivel TEXT NOT NULL,
                mensagem TEXT NOT NULL, previsao_antiga INTEGER NOT NULL DEFAULT 0,
                data TEXT NOT NULL)"""
        )
        vazio = conn.execute("SELECT COUNT(*) FROM relatos").fetchone()[0] == 0
        if vazio and os.getenv("SEED_DEMO", "0") == "1":
            # Pontos de exemplo, marcados como simulados, so para o mapa nao nascer vazio.
            exemplos = [
                (-23.5869, -46.6823, "buraco", "alta"),
                (-23.5781, -46.6878, "poca", "media"),
                (-23.5712, -46.6911, "desnivel", "baixa"),
                (-23.5636, -46.6544, "buraco", "media"),
                (-23.5578, -46.6608, "buraco", "alta"),
                (-23.5699, -46.6452, "poca", "baixa"),
            ]
            conn.executemany(
                "INSERT INTO relatos (lat, lon, tipo, severidade, origem, simulado, data)"
                " VALUES (?, ?, ?, ?, 'app', 1, ?)",
                [(*e, agora()) for e in exemplos],
            )


criar_banco()


class RelatoEntrada(BaseModel):
    # Limites aproximados do municipio de Sao Paulo.
    lat: float = Field(ge=-24.01, le=-23.35)
    lon: float = Field(ge=-46.83, le=-46.36)
    tipo: Literal["buraco", "poca", "desnivel", "outro"]
    severidade: Literal["baixa", "media", "alta"]
    origem: Literal["app", "visao", "robo"] = "app"


class AlertaEntrada(BaseModel):
    relato_id: int | None = None
    nivel: Literal["atencao", "critico"]
    mensagem: str = Field(min_length=3, max_length=280)
    previsao_antiga: bool = False


@app.get("/health")
def health() -> dict:
    try:
        with closing(db()) as conn:
            conn.execute("SELECT 1")
    except sqlite3.Error as erro:
        raise HTTPException(503, "banco indisponivel") from erro
    return {"status": "ok", "versao": VERSAO}


@app.get("/api/relatos")
def listar_relatos(limite: int = 500) -> list[dict]:
    limite = max(1, min(limite, 2000))
    with closing(db()) as conn:
        linhas = conn.execute(
            "SELECT id, lat, lon, tipo, severidade, origem, simulado, data"
            " FROM relatos ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    return [dict(linha) | {"simulado": bool(linha["simulado"])} for linha in linhas]


@app.post("/api/relatos", status_code=201)
def criar_relato(relato: RelatoEntrada) -> dict:
    # LGPD: guardamos so o ponto do perigo. Nada de trajeto, IP ou identificacao de quem reportou.
    data = agora()
    with closing(db()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO relatos (lat, lon, tipo, severidade, origem, data) VALUES (?, ?, ?, ?, ?, ?)",
            (round(relato.lat, 5), round(relato.lon, 5), relato.tipo, relato.severidade, relato.origem, data),
        )
    return {"id": cursor.lastrowid, "data": data, **relato.model_dump()}


_clima_cache: dict = {"ts": 0.0, "dados": None}


@app.get("/api/clima")
def clima() -> dict:
    """Chuva agora e na proxima hora. Se o Open-Meteo cair, devolve a ultima leitura."""
    if _clima_cache["dados"] and time.time() - _clima_cache["ts"] < 600:
        return _clima_cache["dados"]
    try:
        resposta = httpx.get(
            OPEN_METEO,
            params={
                "latitude": SP_LAT,
                "longitude": SP_LON,
                "current": "precipitation",
                "hourly": "precipitation",
                "forecast_hours": 2,
                "timezone": "America/Sao_Paulo",
            },
            timeout=5,
        )
        resposta.raise_for_status()
        corpo = resposta.json()
        mm_agora = float(corpo["current"]["precipitation"] or 0)
        horas = corpo["hourly"]["precipitation"]
        mm_proxima = float(horas[1] if len(horas) > 1 else horas[0] or 0)
        dados = {
            "chove_agora": mm_agora > 0,
            "chove_proxima_hora": mm_proxima > 0,
            "mm_agora": mm_agora,
            "mm_proxima_hora": mm_proxima,
            "atualizado_em": agora(),
            "fonte": "Open-Meteo",
            "desatualizado": False,
        }
        _clima_cache.update(ts=time.time(), dados=dados)
        return dados
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as erro:
        if _clima_cache["dados"]:
            return _clima_cache["dados"] | {"desatualizado": True}
        raise HTTPException(503, "previsao do tempo indisponivel") from erro


@app.get("/api/alertas")
def listar_alertas(limite: int = 50) -> list[dict]:
    limite = max(1, min(limite, 200))
    with closing(db()) as conn:
        linhas = conn.execute(
            "SELECT id, relato_id, nivel, mensagem, previsao_antiga, data"
            " FROM alertas ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    return [dict(linha) | {"previsao_antiga": bool(linha["previsao_antiga"])} for linha in linhas]


@app.post("/api/alertas", status_code=201)
def criar_alerta(alerta: AlertaEntrada, x_api_key: str = Header(default="")) -> dict:
    # So o bot de triagem escreve alertas. A chave vem por variavel de ambiente.
    if BOT_API_KEY and not hmac.compare_digest(x_api_key, BOT_API_KEY):
        raise HTTPException(401, "chave invalida")
    data = agora()
    with closing(db()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO alertas (relato_id, nivel, mensagem, previsao_antiga, data) VALUES (?, ?, ?, ?, ?)",
            (alerta.relato_id, alerta.nivel, alerta.mensagem, int(alerta.previsao_antiga), data),
        )
    return {"id": cursor.lastrowid, "data": data, **alerta.model_dump()}


@app.get("/api/indicadores")
def indicadores() -> dict:
    """Le o CSV exportado da tabela Ouro. Enquanto ele nao existe, conta direto no banco."""
    if INDICADORES_CSV.exists():
        with INDICADORES_CSV.open(encoding="utf-8", newline="") as arquivo:
            return {"fonte": "tabela_ouro", "linhas": list(csv.DictReader(arquivo))}
    with closing(db()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM relatos").fetchone()[0]
        por_severidade = conn.execute(
            "SELECT severidade, COUNT(*) AS total FROM relatos GROUP BY severidade"
        ).fetchall()
        alertas = conn.execute("SELECT COUNT(*) FROM alertas").fetchone()[0]
    return {
        "fonte": "banco_do_mvp",
        "linhas": [
            {"indicador": "perigos_mapeados", "valor": total},
            {"indicador": "alertas_enviados", "valor": alertas},
            *[{"indicador": f"severidade_{l['severidade']}", "valor": l["total"]} for l in por_severidade],
        ],
    }


@app.post("/api/detectar")
def detectar() -> dict:
    raise HTTPException(503, "detector de buracos ainda nao integrado")


@app.post("/api/perguntar")
def perguntar() -> dict:
    raise HTTPException(503, "assistente ainda nao integrado")


Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)

# O site e servido pela propria API. Fica por ultimo para nao encobrir as rotas acima.
app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="site")
