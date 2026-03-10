"""
API FastAPI: gerador de cards de reservatórios.
Serve o frontend estático e expõe endpoints para dados e geração de imagem.
"""
import os
import csv
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

_BASE = Path(__file__).resolve().parent

# --------------- Fontes de gerências ---------------
# Dados embutidos no código para garantir disponibilidade no Railway.
# Para adicionar novas gerências, inclua um novo dict nesta lista.
_FONTES_BUILTIN = [
    {
        "gerencia": "GRMBJAGUA",
        "bacia": "MÉDIO E BAIXO JAGUARIBE",
        "url": "https://docs.google.com/spreadsheets/d/1fbaYqjee8h4dAA8ew0RXbHOKdnSDoHIB2xPpdveYMDU",
        "gid": "1527901614",
    },
    {
        "gerencia": "GRBANABUIU",
        "bacia": "BANABUIÚ",
        "url": "https://docs.google.com/spreadsheets/d/1fbaYqjee8h4dAA8ew0RXbHOKdnSDoHIB2xPpdveYMDU",
        "gid": "0",
    },
]

def _load_fontes_csv() -> list:
    """Tenta carregar do CSV local (sobrescreve o builtin se existir)."""
    for candidate in [
        _BASE / "Fonde de dados.csv",
        Path.cwd() / "Fonde de dados.csv",
    ]:
        if candidate.exists():
            try:
                fontes = []
                with open(candidate, newline="", encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        gerencia = (row.get("GERÊNCIA") or row.get("GERENCIA") or "").strip()
                        bacia    = (row.get("BACIA") or "").strip()
                        link     = (row.get("Link_Planilha") or "").strip()
                        gid      = (row.get("GID") or "0").strip()
                        if gerencia and link:
                            fontes.append({"gerencia": gerencia, "bacia": bacia, "url": link, "gid": gid})
                if fontes:
                    return fontes
            except Exception:
                pass
    return []

from engine import (
    df_to_json_safe,
    generate_image,
    generate_pages,
    load_csv_from_bytes,
    load_data_from_sheets,
    process_df,
    sheets_to_csv_url,
)

# --------------- Configuração da app ---------------
STATIC_DIR = _BASE / "static"
INDEX_HTML = STATIC_DIR / "index.html"

router = APIRouter()


# --------------- Schemas ---------------
class SheetsLoadRequest(BaseModel):
    sheet_url: str
    gid: str = "0"


class GenerateRequest(BaseModel):
    data: list[dict]
    info: dict
    mode: str = "Feed (1080x1350)"
    ordenar: str = "Manter ordem"
    formato: str = "PNG"
    convert_raw_m3_to_millions: bool = True


# --------------- Endpoints ---------------
@router.get("/api/fontes")
async def api_fontes():
    """Retorna a lista de gerências. Usa CSV local se disponível; senão usa dados embutidos."""
    fontes = _load_fontes_csv() or _FONTES_BUILTIN
    return {"fontes": fontes}


@router.post("/api/sheets/load")
async def api_sheets_load(body: SheetsLoadRequest):
    """Carrega e processa dados a partir de um Google Sheet."""
    sheet_url = (body.sheet_url or "").strip()
    gid = (body.gid or "0").strip() or "0"
    csv_url = sheets_to_csv_url(sheet_url, gid=gid)
    if not csv_url:
        raise HTTPException(
            status_code=400,
            detail="Link ou ID da planilha inválido. Selecione uma gerência no campo 'Gerência' ou cole um link do Google Sheets válido.",
        )
    try:
        df_raw = load_data_from_sheets(csv_url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao ler planilha: {str(e)}")
    if df_raw is None or df_raw.empty:
        raise HTTPException(status_code=422, detail="Planilha vazia ou inacessível.")
    try:
        df_proc, info = process_df(df_raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erro ao processar dados: {str(e)}")
    return {"data": df_to_json_safe(df_proc), "info": info}


@router.post("/api/csv/process")
async def api_csv_process(file: UploadFile = File(...)):
    """Processa um arquivo CSV enviado."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .csv")
    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler arquivo: {str(e)}")
    try:
        df_raw = load_csv_from_bytes(data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erro ao interpretar CSV: {str(e)}")
    if df_raw.empty:
        raise HTTPException(status_code=422, detail="CSV vazio.")
    try:
        df_proc, info = process_df(df_raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erro ao processar dados: {str(e)}")
    return {"data": df_to_json_safe(df_proc), "info": info}


@router.post("/api/generate")
async def api_generate(body: GenerateRequest):
    """Gera a imagem do card a partir dos dados processados."""
    import pandas as pd

    if not body.data:
        raise HTTPException(status_code=422, detail="Nenhum dado para gerar o card.")
    try:
        df = pd.DataFrame(body.data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Dados inválidos: {str(e)}")
    periodo = body.info.get("periodo", {})
    date_anterior = periodo.get("anterior", "")
    date_atual = periodo.get("atual", "")
    try:
        img = generate_image(
            df_all=df,
            mode=body.mode,
            date_anterior=date_anterior,
            date_atual=date_atual,
            ordenar=body.ordenar,
            formato=body.formato,
            convert_raw_m3_to_millions=body.convert_raw_m3_to_millions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar imagem: {str(e)}")
    buf = BytesIO()
    fmt = "JPEG" if body.formato.upper() == "JPG" else "PNG"
    if fmt == "JPEG":
        img.save(buf, format=fmt, quality=95, optimize=True)
        media_type = "image/jpeg"
    else:
        img.save(buf, format=fmt, optimize=True)
        media_type = "image/png"
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type=media_type)


@router.post("/api/generate-all")
async def api_generate_all(body: GenerateRequest):
    """Gera todas as páginas e retorna um ZIP com cada imagem nomeada p1, p2, ..."""
    import io
    import zipfile
    import pandas as pd

    if not body.data:
        raise HTTPException(status_code=422, detail="Nenhum dado para gerar o card.")
    try:
        df = pd.DataFrame(body.data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Dados inválidos: {str(e)}")
    periodo = body.info.get("periodo", {})
    date_anterior = periodo.get("anterior", "")
    date_atual = periodo.get("atual", "")
    try:
        pages = generate_pages(
            df_all=df,
            mode=body.mode,
            date_anterior=date_anterior,
            date_atual=date_atual,
            ordenar=body.ordenar,
            formato=body.formato,
            convert_raw_m3_to_millions=body.convert_raw_m3_to_millions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar imagens: {str(e)}")

    fmt = "JPEG" if body.formato.upper() == "JPG" else "PNG"
    ext = body.formato.lower()
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, img in enumerate(pages, start=1):
            img_buf = io.BytesIO()
            if fmt == "JPEG":
                img.save(img_buf, format=fmt, quality=95, optimize=True)
            else:
                img.save(img_buf, format=fmt, optimize=True)
            img_buf.seek(0)
            zf.writestr(f"pagina_{i}.{ext}", img_buf.getvalue())
    zip_buf.seek(0)
    return Response(
        content=zip_buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=monitoramento_cards.zip"},
    )


def create_app():
    from fastapi import FastAPI

    app = FastAPI(
        title="Card Reservatórios",
        description="API para gerar cards de monitoramento de reservatórios.",
        version="1.0",
    )
    app.include_router(router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    @app.get("/")
    def index():
        if INDEX_HTML.is_file():
            return FileResponse(str(INDEX_HTML), media_type="text/html")
        return {"message": "Card Reservatórios API", "docs": "/docs"}

    return app


app = create_app()
