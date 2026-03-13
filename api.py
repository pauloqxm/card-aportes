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
# Planilha geral consolidada (nova estrutura GERAL_BASE_CARD - geral).
_GERAL_SHEET_URL = "https://docs.google.com/spreadsheets/d/15RrQ7ccfZITr2VslQGi1yglLLabKMVFTv5mUepjcW7g"
_GERAL_SHEET_GID = "0"

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


def _load_fontes_from_geral_sheet() -> list:
    """Lê a planilha geral do Google Sheets e retorna combinações únicas GERÊNCIA + BACIA."""
    try:
        csv_url = sheets_to_csv_url(_GERAL_SHEET_URL, gid=_GERAL_SHEET_GID)
        if not csv_url:
            return []
        df = load_data_from_sheets(csv_url)
    except Exception:
        return []

    if df is None or df.empty:
        return []

    # Tenta localizar colunas GERÊNCIA / GERENCIA e BACIA
    cols = {str(c).strip().upper(): c for c in df.columns}
    c_ger = cols.get("GERÊNCIA") or cols.get("GERENCIA")
    c_bacia = cols.get("BACIA")
    if not c_ger:
        return []

    seen = set()
    fontes: list[dict] = []
    for _, row in df.iterrows():
        ger = str(row.get(c_ger, "") or "").strip()
        bac = str(row.get(c_bacia, "") or "").strip() if c_bacia else ""
        if not ger:
            continue
        key = (ger, bac)
        if key in seen:
            continue
        seen.add(key)
        fontes.append(
            {
                "gerencia": ger,
                "bacia": bac,
                # URL/GID não são usados mais para carregar dados, mas mantemos campos por compatibilidade.
                "url": "",
                "gid": "",
            }
        )

    return sorted(fontes, key=lambda x: (x["gerencia"], x["bacia"]))

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
    """Retorna a lista de gerências/bacias para o menu suspenso.

    Ordem de prioridade:
    1. Planilha geral no Google Sheets (nova estrutura)
    2. CSV local "Fonde de dados.csv" (legado)
    """
    fontes = _load_fontes_from_geral_sheet() or _load_fontes_csv()
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
    """Gera imagem única ou PDF (uma ou mais páginas A4) a partir dos dados processados."""
    import pandas as pd
    from PIL import Image

    if not body.data:
        raise HTTPException(status_code=422, detail="Nenhum dado para gerar o card.")
    try:
        df = pd.DataFrame(body.data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Dados inválidos: {str(e)}")
    periodo = body.info.get("periodo", {})
    date_anterior = periodo.get("anterior", "")
    date_atual = periodo.get("atual", "")

    fmt_req = (body.formato or "PNG").upper()

    # Se PDF, gera todas as páginas necessárias e empacota em folhas A4 (até 2 por folha).
    if fmt_req == "PDF":
        try:
            pages = generate_pages(
                df_all=df,
                mode=body.mode,
                date_anterior=date_anterior,
                date_atual=date_atual,
                ordenar=body.ordenar,
                formato="PNG",  # base interna em imagem
                convert_raw_m3_to_millions=body.convert_raw_m3_to_millions,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao gerar páginas: {str(e)}")

        if not pages:
            raise HTTPException(status_code=500, detail="Nenhuma página gerada para o PDF.")

        # A4 em pixels (300 DPI aprox.): 2480 x 3508 (retrato)
        A4_W, A4_H = 2480, 3508
        margin = 80
        pdf_pages: list[Image.Image] = []

        i = 0
        while i < len(pages):
            group = pages[i : i + 2]
            sheet = Image.new("RGB", (A4_W, A4_H), (255, 255, 255))

            if len(group) == 1:
                img = group[0].convert("RGB")
                w, h = img.size
                scale = min((A4_W - 2 * margin) / w, (A4_H - 2 * margin) / h)
                new_size = (int(w * scale), int(h * scale))
                img_resized = img.resize(new_size, Image.LANCZOS)
                x = (A4_W - new_size[0]) // 2
                y = (A4_H - new_size[1]) // 2
                sheet.paste(img_resized, (x, y))
            else:
                top, bottom = [p.convert("RGB") for p in group]
                avail_h_each = (A4_H - 3 * margin) // 2

                def _place(img_src: Image.Image, y_top: int):
                    w, h = img_src.size
                    scale = min((A4_W - 2 * margin) / w, avail_h_each / h)
                    new_size = (int(w * scale), int(h * scale))
                    img_resized = img_src.resize(new_size, Image.LANCZOS)
                    x = (A4_W - new_size[0]) // 2
                    y = y_top + (avail_h_each - new_size[1]) // 2
                    sheet.paste(img_resized, (x, y))

                _place(top, margin)
                _place(bottom, margin * 2 + avail_h_each)

            pdf_pages.append(sheet)
            i += 2

        pdf_buf = BytesIO()
        pdf_pages[0].save(
            pdf_buf,
            format="PDF",
            save_all=True,
            append_images=pdf_pages[1:],
        )
        pdf_buf.seek(0)
        return Response(
            content=pdf_buf.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="monitoramento_cards.pdf"'},
        )

    # PNG / JPG (comportamento original)
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
    fmt = "JPEG" if fmt_req == "JPG" else "PNG"
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
    """Gera todas as páginas.

    - Para PNG/JPG: retorna um ZIP com cada imagem nomeada p1, p2, ...
    - Para PDF: retorna um único PDF com folhas A4; até 2 páginas por folha.
    """
    import io
    import zipfile
    import pandas as pd
    from PIL import Image

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

    fmt_req = (body.formato or "PNG").upper()

    if fmt_req == "PDF":
        if not pages:
            raise HTTPException(status_code=500, detail="Nenhuma página gerada para o PDF.")

        A4_W, A4_H = 2480, 3508
        margin = 80
        pdf_pages: list[Image.Image] = []

        i = 0
        while i < len(pages):
            group = pages[i : i + 2]
            sheet = Image.new("RGB", (A4_W, A4_H), (255, 255, 255))

            if len(group) == 1:
                img = group[0].convert("RGB")
                w, h = img.size
                scale = min((A4_W - 2 * margin) / w, (A4_H - 2 * margin) / h)
                new_size = (int(w * scale), int(h * scale))
                img_resized = img.resize(new_size, Image.LANCZOS)
                x = (A4_W - new_size[0]) // 2
                y = (A4_H - new_size[1]) // 2
                sheet.paste(img_resized, (x, y))
            else:
                top, bottom = [p.convert("RGB") for p in group]
                avail_h_each = (A4_H - 3 * margin) // 2

                def _place(img_src: Image.Image, y_top: int):
                    w, h = img_src.size
                    scale = min((A4_W - 2 * margin) / w, avail_h_each / h)
                    new_size = (int(w * scale), int(h * scale))
                    img_resized = img_src.resize(new_size, Image.LANCZOS)
                    x = (A4_W - new_size[0]) // 2
                    y = y_top + (avail_h_each - new_size[1]) // 2
                    sheet.paste(img_resized, (x, y))

                _place(top, margin)
                _place(bottom, margin * 2 + avail_h_each)

            pdf_pages.append(sheet)
            i += 2

        pdf_buf = io.BytesIO()
        pdf_pages[0].save(
            pdf_buf,
            format="PDF",
            save_all=True,
            append_images=pdf_pages[1:],
        )
        pdf_buf.seek(0)
        return Response(
            content=pdf_buf.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="monitoramento_cards.pdf"'},
        )

    # PNG / JPG (ZIP de imagens)
    fmt = "JPEG" if fmt_req == "JPG" else "PNG"
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
        headers={"Content-Disposition": f'attachment; filename="monitoramento_cards.zip"'},
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
