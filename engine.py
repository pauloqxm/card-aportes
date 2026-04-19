"""
Motor de processamento e geração de cards de monitoramento de reservatórios.
Usado pela API FastAPI (api.py) e independente do Streamlit.
"""
import json
import re
import unicodedata
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont
from zoneinfo import ZoneInfo

BASE_LAYOUT_PATH = "base_card.png"
TZ_FORTALEZA = ZoneInfo("America/Fortaleza")
FONTS_DIR = Path(__file__).parent / "fonts"


# ------------------------------
# Fontes
# ------------------------------
def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    size = int(size) if size is not None else 14
    if size < 1:
        size = 1

    local_bold = [
        FONTS_DIR / "DejaVuSans-Bold.ttf",
        FONTS_DIR / "NotoSans-Bold.ttf",
        FONTS_DIR / "NotoSansDisplay-Bold.ttf",
    ]
    local_regular = [
        FONTS_DIR / "DejaVuSans.ttf",
        FONTS_DIR / "NotoSans-Regular.ttf",
        FONTS_DIR / "NotoSansDisplay-Regular.ttf",
    ]

    for p in (local_bold if bold else local_regular):
        try:
            if p.exists():
                return ImageFont.truetype(str(p), size)
        except Exception:
            pass

    paths_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    paths_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    for path in (paths_bold if bold else paths_regular):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def norm_txt(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    return unicodedata.normalize("NFC", s)


def smart_to_float(x):
    if pd.isna(x):
        return None
    s = str(x).strip()
    if s == "":
        return None
    s = s.replace("m³", "").replace("m3", "").replace("%", "")
    s = s.replace(" ", "")
    s = re.sub(r"[^0-9\-\+\,\.]", "", s)
    if s.count(",") > 0 and s.count(".") > 0:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") > 0 and s.count(".") == 0:
        s = s.replace(",", ".")
    else:
        if s.count(".") > 1:
            s = s.replace(".", "")
    try:
        return float(s)
    except Exception:
        return None


def to_num_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.map(smart_to_float), errors="coerce")


def fmt_m_2dp_dot(v) -> str:
    if pd.isna(v):
        return "N/A"
    try:
        return f"{float(v):.2f} m"
    except Exception:
        return "N/A"


def _fmt_num_br(x: float) -> str:
    """Formata número com separador de milhar PT-BR (vírgula decimal)."""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_milhoes_br(v, convert_raw_m3_to_millions: bool) -> str:
    """Formata volume em milhões/m³ ou bilhões/m³ (se > 999 milhões)."""
    if pd.isna(v):
        return "N/A"
    try:
        val = float(v)
        if convert_raw_m3_to_millions:
            val_millions = val / 1_000_000.0
            if val_millions > 999:
                return f"{_fmt_num_br(val_millions / 1000.0)} bilhões/m³"
            return f"{_fmt_num_br(val_millions)} milhões/m³"
        # Raw m³
        if val > 999_000_000:
            return f"{_fmt_num_br(val / 1_000_000_000.0)} bilhões/m³"
        return f"{_fmt_num_br(val)} milhões/m³"
    except Exception:
        return "N/A"


def fmt_pct_br(v) -> str:
    if pd.isna(v):
        return "N/A"
    try:
        return f"{float(v):.1f}".replace(".", ",")
    except Exception:
        return "N/A"


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    text = norm_txt(text)
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(bbox[2] - bbox[0])


def ellipsize_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    text = norm_txt((text or "").strip())
    if not text:
        return "N/A"
    if text_width(draw, text, font) <= max_width:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    best = ell
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = text[:mid].rstrip() + ell
        if text_width(draw, cand, font) <= max_width:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def load_csv_from_bytes(data: bytes) -> pd.DataFrame:
    try:
        df = pd.read_csv(BytesIO(data), sep=";", dtype=str, encoding="utf-8")
        if df.shape[1] == 1:
            raise ValueError("CSV com 1 coluna")
        return df
    except Exception:
        return pd.read_csv(BytesIO(data), sep=",", dtype=str, encoding="utf-8")


def sheets_to_csv_url(sheet_url_or_id: str, gid: str = "0") -> str:
    s = (sheet_url_or_id or "").strip()
    if not s:
        return ""
    if "docs.google.com/spreadsheets" in s:
        m = re.search(r"/d/([a-zA-Z0-9\-_]+)", s)
        if not m:
            return ""
        sheet_id = m.group(1)
    else:
        sheet_id = s
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def _read_csv_bytes_robusto(content: bytes) -> pd.DataFrame:
    try:
        txt = content.decode("utf-8")
        return pd.read_csv(StringIO(txt), dtype=str)
    except Exception:
        pass
    try:
        txt = content.decode("utf-8-sig")
        return pd.read_csv(StringIO(txt), dtype=str)
    except Exception:
        pass
    txt = content.decode("latin-1", errors="replace")
    return pd.read_csv(StringIO(txt), dtype=str)


def load_data_from_sheets(csv_url: str) -> pd.DataFrame:
    resp = requests.get(csv_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return _read_csv_bytes_robusto(resp.content)


def _norm_col(c: str) -> str:
    return re.sub(r"\s+", " ", str(c).strip()).upper()


def find_date_cols(cols: list) -> list:
    date_like = []
    for c in cols:
        s = str(c).strip()
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", s):
            date_like.append(c)
    return date_like[:2]


def process_df(df_raw: pd.DataFrame):
    df_raw = df_raw.copy()
    df_raw.columns = [norm_txt(c) for c in df_raw.columns]
    for col in df_raw.columns:
        if df_raw[col].dtype == object:
            df_raw[col] = df_raw[col].map(lambda x: norm_txt(x).strip() if x is not None else x)

    cols = list(df_raw.columns)
    norm_map = {_norm_col(c): c for c in cols}

    def col(name_upper: str):
        return norm_map.get(name_upper)

    c_ger = col("GERÊNCIA")
    c_bacia = col("BACIA")
    # Nome do reservatório / açude (nova planilha usa "RESERVATÓRIO")
    c_acude = col("AÇUDE") or col("RESERVATÓRIO") or col("RESERVATORIO")
    c_mun = col("MUNICÍPIO") or col("MUNICIPIO")
    c_var_m = col("VARIAÇÃO_M") or col("VARIAÇÃO EM M") or col("VARIACAO EM M")
    c_var_m3 = col("VARIAÇÃO_M³") or col("VARIAÇÃO EM M³") or col("VARIACAO EM M3") or col("VARIAÇÃO_M3")
    c_capacidade = col("CAPACIDADE (M³)") or col("CAPACIDADE (M3)") or col("CAPACIDADE TOTAL (M³)") or col("CAPACIDADE TOTAL (M3)")
    c_vol_atual = col("SITUAÇÃO ATUAL") or col("VOLUME ATUAL")
    c_pct_atual = col("PERCENTUAL ATUAL") or col("PERCENTUAL")
    c_falta_sangrar = col("FALTA P/ SANGRAR") or col("FALTA P SANGRAR")

    date_cols = find_date_cols(cols)
    date_ant = date_cols[0] if len(date_cols) > 0 else ""
    date_atu = date_cols[1] if len(date_cols) > 1 else ""

    df = pd.DataFrame({
        "gerencia": (df_raw[c_ger].astype(str).str.strip() if c_ger else "N/A"),
        "bacia": (df_raw[c_bacia].astype(str).str.strip() if c_bacia else "N/A"),
        "nome": (df_raw[c_acude].astype(str).str.strip() if c_acude else df_raw.iloc[:, 0].astype(str).str.strip()),
        "municipio": (df_raw[c_mun].astype(str).str.strip() if c_mun else "N/A"),
        "data_anterior": str(date_ant).strip(),
        "data_atual": str(date_atu).strip(),
        "nivel_anterior": to_num_series(df_raw[date_ant]) if date_ant in df_raw.columns else pd.Series([None] * len(df_raw)),
        "nivel_atual": to_num_series(df_raw[date_atu]) if date_atu in df_raw.columns else pd.Series([None] * len(df_raw)),
        "variacao_m": to_num_series(df_raw[c_var_m]) if c_var_m else pd.Series([None] * len(df_raw)),
        "variacao_m3": to_num_series(df_raw[c_var_m3]) if c_var_m3 else pd.Series([None] * len(df_raw)),
        "capacidade_m3": to_num_series(df_raw[c_capacidade]) if c_capacidade else pd.Series([None] * len(df_raw)),
        "volume_atual_m3": to_num_series(df_raw[c_vol_atual]) if c_vol_atual else pd.Series([None] * len(df_raw)),
        "percentual": to_num_series(df_raw[c_pct_atual]) if c_pct_atual else pd.Series([None] * len(df_raw)),
        "falta_sangrar": to_num_series(df_raw[c_falta_sangrar]) if c_falta_sangrar else pd.Series([None] * len(df_raw)),
    })

    df = df[
        df["nome"].notna()
        & (df["nome"].astype(str).str.strip() != "")
        & (~df["nome"].astype(str).str.lower().isin(["nan", "none", "n/a"]))
    ].reset_index(drop=True)

    if df["variacao_m"].isna().all():
        df["variacao_m"] = (df["nivel_atual"] - df["nivel_anterior"]).round(2)

    for c in ["variacao_m", "variacao_m3", "capacidade_m3", "volume_atual_m3", "percentual"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    info = {"periodo": {"anterior": str(date_ant).strip(), "atual": str(date_atu).strip()}, "colunas": cols}
    return df, info


def build_fonte_gerencia(df: pd.DataFrame) -> str:
    uniques = [g for g in df.get("gerencia", pd.Series([])).dropna().astype(str).str.strip().unique().tolist() if g]
    if not uniques:
        return "Fonte: N/A"
    if len(uniques) <= 3:
        return "Fonte: " + " • ".join(uniques)
    return "Fonte: " + " • ".join(uniques[:3]) + f" • +{len(uniques) - 3}"


def build_bacia_label(df: pd.DataFrame) -> str:
    uniques = [b for b in df.get("bacia", pd.Series([])).dropna().astype(str).str.strip().unique().tolist() if b]
    if not uniques:
        return "N/A"
    if len(uniques) == 1:
        return uniques[0]
    if len(uniques) <= 3:
        return " / ".join(uniques)
    return " / ".join(uniques[:3]) + f" / +{len(uniques) - 3}"


def draw_rounded_rect(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                      r: int, fill, outline=None, width: int = 2):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill, outline=outline, width=width)


def draw_arrow(draw: ImageDraw.ImageDraw, x: int, y: int, up: bool, size: int, color):
    w, h = size, size
    if up:
        tri = [(x + w // 2, y), (x + w, y + h // 2), (x, y + h // 2)]
        shaft = [x + w // 2 - max(2, w // 10), y + h // 2, x + w // 2 + max(2, w // 10), y + h]
    else:
        tri = [(x, y + h // 2), (x + w, y + h // 2), (x + w // 2, y + h)]
        shaft = [x + w // 2 - max(2, w // 10), y, x + w // 2 + max(2, w // 10), y + h // 2]
    draw.polygon(tri, fill=color)
    draw.rectangle(shaft, fill=color)


def draw_equal_sign(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color):
    w, h = size, size // 4
    draw.rectangle([x, y + size//3 - h//2, x + w, y + size//3 + h//2], fill=color)
    draw.rectangle([x, y + 2*size//3 - h//2, x + w, y + 2*size//3 + h//2], fill=color)


def draw_kpi_pill(draw, x, y, w, h, label, value, outline, big=False, filled=False):
    bg = outline
    text = (255, 255, 255, 255)
    sub = (255, 255, 255, 255)
    r = 16 if big else 14
    draw_rounded_rect(draw, x, y, w, h, r, fill=bg, outline=None, width=0)
    f_lab = get_font(15 if big else 14, True)
    f_val = get_font(22 if big else 20, True)
    draw.text((x + 12, y + 6), norm_txt(label), fill=sub, font=f_lab)
    draw.text((x + w - 12, y + 4), norm_txt(str(value)), fill=text, font=f_val, anchor="ra")


def draw_kpis_grid(draw, x, y, total, up, down, vertendo, sem_var, big=False):
    gap = 12
    h = 42 if big else 38
    w = (1080 - 2*70 - 4*gap) // 5
    o_total = (148, 163, 184, 255)
    o_up = (59, 130, 246, 255)
    o_down = (244, 63, 94, 255)
    o_vertendo = (34, 197, 94, 255)
    o_sem_var = (156, 163, 175, 255)
    draw_kpi_pill(draw, x + 0*(w+gap), y, w, h, "Total", total, o_total, big)
    draw_kpi_pill(draw, x + 1*(w+gap), y, w, h, "Var. +", up, o_up, big)
    draw_kpi_pill(draw, x + 2*(w+gap), y, w, h, "Var. -", down, o_down, big)
    draw_kpi_pill(draw, x + 3*(w+gap), y, w, h, "Vertendo", vertendo, o_vertendo, big)
    draw_kpi_pill(draw, x + 4*(w+gap), y, w, h, "Sem var.", sem_var, o_sem_var, big)
    return y + h


def _safe_sum(series: pd.Series | None) -> float:
    if series is None:
        return 0.0
    try:
        return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0


def draw_global_kpis_and_pie(draw, x, y, w, h, df_all: pd.DataFrame,
                              convert_raw_m3_to_millions: bool, big: bool = True):
    """Painel de KPIs globais + donut chart.
    Layout:  col1 (Capacidade + Volume Atual) | col2 (Evolução no Período) | col3 (Percentual Atual)
    """
    cap_total  = max(0.0, _safe_sum(df_all.get("capacidade_m3")))
    aporte_total = _safe_sum(df_all.get("variacao_m3"))

    # Volume para exibição no KPI "Volume Atual" (soma bruta, sem cap)
    vol_total  = max(0.0, _safe_sum(df_all.get("volume_atual_m3")))

    # Volume para o cálculo do percentual: cada reservatório limitado à sua capacidade,
    # evitando que reservatórios acima de 100% inflem o percentual global da bacia.
    try:
        cap_s = pd.to_numeric(df_all.get("capacidade_m3"), errors="coerce").fillna(0.0)
        vol_s = pd.to_numeric(df_all.get("volume_atual_m3"), errors="coerce").fillna(0.0)
        vol_capped_total = float(vol_s.clip(upper=cap_s).sum())
    except Exception:
        vol_capped_total = vol_total

    # Paleta do projeto
    C_SKY    = (56,  189, 248, 255)   # --accent
    C_TEAL   = (34,  211, 238, 255)   # azul-ciano
    C_ORANGE = (251, 146,  60, 255)   # aporte positivo
    C_RED    = (248, 113, 113, 255)   # aporte negativo
    C_SURF   = (30,   41,  59, 255)   # --surface
    C_MUTED  = (100, 116, 139, 255)
    C_TEXT   = (241, 245, 249, 255)
    C_TITLE  = (255, 255, 255, 255)  # títulos dos KPIs em branco
    C_RING_EMPTY = (30, 64, 175, 220)

    gap_col = 18
    col_w   = (w - 2 * gap_col) // 3

    pad_i   = 14
    bar_top = 5   # altura da barra colorida no topo de cada card
    r_card  = 18

    def _card_bg(cx, cy, cw, ch, accent):
        draw_rounded_rect(draw, cx, cy, cw, ch, r_card,
                          fill=C_SURF, outline=(*accent[:3], 180), width=2)
        # barra de acento no topo
        draw_rounded_rect(draw, cx + 2, cy, cw - 4, bar_top, 3,
                          fill=accent, outline=None, width=0)

    f_lbl_sz = 17 if big else 15
    f_val_sz = 26 if big else 22
    f_sm_sz  = 14 if big else 13

    # ── COLUNA 1: Capacidade (cima) + Volume Atual (baixo) ─────────────────────
    col1_x  = x
    sub_gap = 10
    sub_h   = (h - sub_gap) // 2
    sub_h2  = h - sub_h - sub_gap   # garante que somam h exato

    def _draw_stacked_kpi(cx, cy, cw, ch, label, value_str, accent):
        _card_bg(cx, cy, cw, ch, accent)
        f_l = get_font(f_lbl_sz, False)
        f_v = get_font(f_val_sz, True)
        draw.text((cx + pad_i, cy + bar_top + 8),
                  norm_txt(label.upper()), fill=C_TITLE, font=f_l)
        val_y = cy + bar_top + 8 + f_l.size + 6
        draw.text((cx + pad_i, val_y), norm_txt(value_str), fill=accent, font=f_v)

    cap_txt    = fmt_milhoes_br(cap_total, convert_raw_m3_to_millions)
    vol_txt    = fmt_milhoes_br(vol_total, convert_raw_m3_to_millions)
    _draw_stacked_kpi(col1_x, y,               col_w, sub_h,  "Capacidade da Bacia", cap_txt, C_SKY)
    _draw_stacked_kpi(col1_x, y + sub_h + sub_gap, col_w, sub_h2, "Volume Atual",  vol_txt, C_TEAL)

    # ── COLUNA 2: Evolução no Período (altura total) ───────────────────────────
    col2_x = x + col_w + gap_col
    aporte_color = C_ORANGE if aporte_total >= 0 else C_RED
    aporte_txt   = fmt_milhoes_br(aporte_total, convert_raw_m3_to_millions)

    _card_bg(col2_x, y, col_w, h, aporte_color)

    f_lbl2 = get_font(f_lbl_sz, False)
    draw.text((col2_x + pad_i, y + bar_top + 8),
              norm_txt("EVOLUÇÃO NO PERÍODO"), fill=C_TITLE, font=f_lbl2)

    f_val2 = get_font(f_val_sz + 6, True)
    val_cy = y + h // 2 + 6
    draw.text((col2_x + col_w // 2, val_cy),
              norm_txt(aporte_txt), fill=aporte_color, font=f_val2, anchor="mm")

    # ── COLUNA 3: Percentual Atual (Donut chart) ───────────────────────────────
    col3_x = x + 2 * (col_w + gap_col)
    _card_bg(col3_x, y, col_w, h, C_SKY)

    f_lbl3 = get_font(f_lbl_sz, False)
    draw.text((col3_x + pad_i, y + bar_top + 8),
              norm_txt("PERCENTUAL ATUAL"), fill=C_TITLE, font=f_lbl3)

    if cap_total > 0:
        filled = min(vol_capped_total, cap_total)
        pct_preench = 100.0 * (filled / cap_total)

        margin  = 18
        label_h = bar_top + 8 + f_lbl3.size + 10   # espaço do label no topo
        avail_h = h - label_h - margin
        dia     = min(col_w - 2 * margin, avail_h)
        dia     = max(40, dia)

        cx_d = col3_x + col_w // 2
        cy_d = y + label_h + avail_h // 2

        r_out  = dia // 2
        r_hole = int(r_out * 0.58)

        # anel vazio (capacidade total)
        draw.ellipse([cx_d - r_out, cy_d - r_out, cx_d + r_out, cy_d + r_out],
                     fill=C_RING_EMPTY, outline=None)

        # arco preenchido (situação atual — usa vol_capped_total para não ultrapassar 100%)
        if filled > 0:
            draw.pieslice([cx_d - r_out, cy_d - r_out, cx_d + r_out, cy_d + r_out],
                          start=-90.0, end=-90.0 + 360.0 * (filled / cap_total),
                          fill=C_SKY, outline=None)

        # buraco central (donut)
        draw.ellipse([cx_d - r_hole, cy_d - r_hole, cx_d + r_hole, cy_d + r_hole],
                     fill=C_SURF, outline=None)

        # borda sutil do buraco
        draw.ellipse([cx_d - r_hole, cy_d - r_hole, cx_d + r_hole, cy_d + r_hole],
                     fill=None, outline=(*C_SKY[:3], 60), width=2)

        # % no centro
        f_pct_big = get_font(f_val_sz + 4, True)
        f_pct_sub = get_font(f_sm_sz, False)
        draw.text((cx_d, cy_d - 4), norm_txt(f"{pct_preench:.2f}%"),
                  fill=C_TEXT, font=f_pct_big, anchor="mm")
        draw.text((cx_d, cy_d + f_pct_big.size // 2 + 4),
                  norm_txt("da capacidade"), fill=C_MUTED, font=f_pct_sub, anchor="mm")


def draw_bacia_pill(draw, right_x, y, text_value, big=False, min_left_x=70, max_w=None):
    outline = (147, 197, 253, 255)
    bg = (255, 255, 255, 255)
    tx = (30, 64, 175, 255)
    f = get_font(22 if big else 20, True)
    if max_w is None:
        max_w = max(220, right_x - min_left_x)
    prefix = "Bacia: "
    inner_max = max_w - 34
    prefix_w = text_width(draw, prefix, f)
    value_max = max(40, inner_max - prefix_w)
    clipped_value = ellipsize_text(draw, str(text_value), f, value_max)
    label = norm_txt(f"{prefix}{clipped_value}")
    w = min(text_width(draw, label, f) + 34, max_w)
    h = 44 if big else 40
    x = right_x - w
    draw_rounded_rect(draw, x, y, w, h, 18, fill=bg, outline=outline, width=3)
    draw.text((x + 18, y + 9), label, fill=tx, font=f)
    return x


def generate_pages(df_all: pd.DataFrame, mode: str, date_anterior: str, date_atual: str,
                   ordenar: str, formato: str, convert_raw_m3_to_millions: bool) -> list:
    """Gera todas as páginas necessárias (cada uma com até 15 cards) e retorna lista de imagens."""
    # Montar lista ordenada completa (sem limite de 15)
    df = df_all.copy()
    df_vertendo = df[df["percentual"] >= 100].copy()
    df_nao_vertendo = df[df["percentual"] < 100].copy()
    df_pos = df_nao_vertendo[(df_nao_vertendo["variacao_m"] > 0) & (~df_nao_vertendo["variacao_m"].isna())].copy()
    df_neg = df_nao_vertendo[(df_nao_vertendo["variacao_m"] < 0) & (~df_nao_vertendo["variacao_m"].isna())].copy()
    df_zero = df_nao_vertendo[(df_nao_vertendo["variacao_m"] == 0) & (~df_nao_vertendo["variacao_m"].isna())].copy()

    if ordenar == "Maior variação positiva":
        df_pos = df_pos.sort_values("variacao_m", ascending=False)
        df_neg = df_neg.sort_values("variacao_m", ascending=True)
    elif ordenar == "Maior variação negativa":
        df_neg = df_neg.sort_values("variacao_m", ascending=True)
        df_pos = df_pos.sort_values("variacao_m", ascending=False)
    elif ordenar == "Maior variação absoluta":
        df_vertendo = df[df["percentual"] >= 100].copy()
        tmp_nao_vert = df[df["percentual"] < 100].copy()
        tmp = tmp_nao_vert.assign(_abs=tmp_nao_vert["variacao_m"].abs()).sort_values("_abs", ascending=False).drop(columns=["_abs"])
        df_pos = tmp[(tmp["variacao_m"] > 0) & (~tmp["variacao_m"].isna())]
        df_neg = tmp[(tmp["variacao_m"] < 0) & (~tmp["variacao_m"].isna())]
        df_zero = tmp[(tmp["variacao_m"] == 0) & (~tmp["variacao_m"].isna())]

    ordered = pd.concat([df_vertendo, df_pos, df_neg, df_zero], ignore_index=True)
    ordered = ordered.drop_duplicates(subset=["nome"], keep="first").reset_index(drop=True)

    total_rows = len(ordered)
    # Página 1 tem espaço para 12 cards (1 linha reservada para KPIs globais).
    # Páginas seguintes têm 15 cards (grade completa 3×5).
    PAGE1_CARDS = 12
    PAGE_N_CARDS = 15

    if total_rows == 0:
        slices = [ordered]
    else:
        slices = []
        remaining = ordered
        # Página 1
        slices.append(remaining.iloc[:PAGE1_CARDS].reset_index(drop=True))
        remaining = remaining.iloc[PAGE1_CARDS:].reset_index(drop=True)
        # Páginas 2+
        while len(remaining) > 0:
            slices.append(remaining.iloc[:PAGE_N_CARDS].reset_index(drop=True))
            remaining = remaining.iloc[PAGE_N_CARDS:].reset_index(drop=True)

    n_pages = len(slices)
    pages = []
    for p, slice_df in enumerate(slices):
        img = _render_page(
            df_all=df_all,
            ordered_slice=slice_df,
            mode=mode,
            date_anterior=date_anterior,
            date_atual=date_atual,
            formato=formato,
            convert_raw_m3_to_millions=convert_raw_m3_to_millions,
            page_num=p + 1,
            total_pages=n_pages,
        )
        pages.append(img)
    return pages


def _render_page(df_all: pd.DataFrame, ordered_slice: pd.DataFrame, mode: str,
                 date_anterior: str, date_atual: str, formato: str,
                 convert_raw_m3_to_millions: bool,
                 page_num: int = 1, total_pages: int = 1) -> Image.Image:
    """Renderiza uma única página com os cards do slice fornecido."""
    if mode == "Feed (1080x1350)":
        try:
            base = Image.open(BASE_LAYOUT_PATH).convert("RGBA")
        except Exception:
            base = Image.new("RGBA", (1080, 1350), (255, 255, 255, 255))
        W, H = base.size
        img = base.copy()
        draw = ImageDraw.Draw(img)
        big = False
        cols_grid, rows_grid = 3, 5
    else:
        W, H = 1080, 1920
        img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        big = True
        cols_grid, rows_grid = 3, 5

    dark = (15, 23, 42, 255)
    gray = (71, 85, 105, 255)
    blue_bg = (219, 234, 254, 255)
    blue_bd = (59, 130, 246, 255)
    blue_tx = (29, 78, 216, 255)
    red_bg = (255, 241, 242, 255)
    red_bd = (251, 113, 133, 255)
    red_tx = (225, 29, 72, 255)
    neutral_bg = (241, 245, 249, 255)
    neutral_bd = (148, 163, 184, 255)
    neutral_tx = (51, 65, 85, 255)
    f_name_base = 22 if big else 18
    f_line_base = 17 if big else 15
    f_var_base = 22 if big else 18
    pad = 70

    total = int(len(df_all))
    vertendo = int(((df_all["percentual"] >= 100) & (~df_all["percentual"].isna())).sum()) if "percentual" in df_all.columns else 0
    up = int(((df_all["variacao_m"] > 0) & (df_all["percentual"] < 100) & (~df_all["variacao_m"].isna())).sum()) if "variacao_m" in df_all.columns and "percentual" in df_all.columns else 0
    down = int(((df_all["variacao_m"] < 0) & (~df_all["variacao_m"].isna()) & ((df_all["percentual"] < 100) | (df_all["percentual"].isna()))).sum()) if "variacao_m" in df_all.columns and "percentual" in df_all.columns else (int(((df_all["variacao_m"] < 0) & (~df_all["variacao_m"].isna())).sum()) if "variacao_m" in df_all.columns else 0)
    sem_var = int(((df_all["variacao_m"] == 0) & (df_all["percentual"] < 100) & (~df_all["variacao_m"].isna())).sum()) if "variacao_m" in df_all.columns and "percentual" in df_all.columns else 0
    bacia_txt = build_bacia_label(df_all)

    y = 70
    if big:
        f_title = get_font(66, True)
        draw.text((pad, y), norm_txt("Monitoramento dos Reservatórios"), fill=dark, font=f_title)
        y += 92
    if not big:
        y = 150

    comp_y, comp_h = y, 44 if big else 40
    comp_w, comp_x = 420 if big else 380, pad
    draw_rounded_rect(draw, comp_x, comp_y, comp_w, comp_h, 18, fill=(248, 250, 252, 255), outline=(203, 213, 225, 255), width=2)
    comparativo = norm_txt(f"Comparativo  {date_anterior}  →  {date_atual}")
    f_comp = get_font(16 if big else 15, True)
    draw.text((comp_x + 18, comp_y + (comp_h // 2)), comparativo, fill=gray, font=f_comp, anchor="lm")
    bacia_y = comp_y + 2
    min_left = comp_x + comp_w + 20
    draw_bacia_pill(draw, right_x=W - pad, y=bacia_y, text_value=bacia_txt, big=big, min_left_x=min_left)
    y = comp_y + comp_h + 18
    y = draw_kpis_grid(draw, pad, y, total=total, up=up, down=down, vertendo=vertendo, sem_var=sem_var, big=big)
    y += 20
    draw.line((pad, y, W - pad, y), fill=(226, 232, 240, 255), width=3)
    y += 24

    gap_x, gap_y = 18, 16
    grid_x, grid_y = pad, y
    grid_w = W - 2 * pad
    grid_h = H - grid_y - (110 if big else 95)
    card_w = int((grid_w - (cols_grid - 1) * gap_x) / cols_grid)
    card_h = int((grid_h - (rows_grid - 1) * gap_y) / rows_grid)

    ordered = ordered_slice

    # Na primeira página, usamos a área do primeiro "andar" de cards
    # para mostrar os KPIs globais + donut chart.
    first_row_y = grid_y
    if page_num == 1:
        draw_global_kpis_and_pie(
            draw=draw,
            x=grid_x,
            y=first_row_y,
            w=grid_w,
            h=card_h,
            df_all=df_all,
            convert_raw_m3_to_millions=convert_raw_m3_to_millions,
            big=big,
        )
        # Cards começam a partir da segunda linha visual (12 cards na pg1)
        cards_start_y = first_row_y + card_h + gap_y
    else:
        cards_start_y = grid_y

    def draw_item(ix: int, row: pd.Series, x: int, y: int):
        nome = norm_txt(str(row.get("nome", "N/A"))).strip()
        municipio = norm_txt(str(row.get("municipio", "N/A"))).strip()
        var_m, var_m3 = row.get("variacao_m", None), row.get("variacao_m3", None)
        vol, pct = row.get("volume_atual_m3", None), row.get("percentual", None)
        falta_sangrar = row.get("falta_sangrar", None)
        is_vertendo = (not pd.isna(pct)) and (float(pct) >= 100)
        is_pos = (not pd.isna(var_m)) and (float(var_m) > 0) and not is_vertendo
        is_neg = (not pd.isna(var_m)) and (float(var_m) < 0)
        is_zero = (not pd.isna(var_m)) and (float(var_m) == 0)
        green_bg, green_bd, green_tx = (220, 252, 231, 255), (34, 197, 94, 255), (22, 163, 74, 255)
        if is_vertendo:
            bg, bd, tx, up_arrow = green_bg, green_bd, green_tx, None
            track, track_border = (22, 163, 74, 70), (22, 163, 74, 120)
        elif is_pos:
            bg, bd, tx, up_arrow = blue_bg, blue_bd, blue_tx, True
            track, track_border = (30, 64, 175, 70), (30, 64, 175, 120)
        elif is_neg:
            bg, bd, tx, up_arrow = red_bg, red_bd, red_tx, False
            track, track_border = (159, 18, 57, 70), (159, 18, 57, 120)
        else:
            bg, bd, tx, up_arrow = neutral_bg, neutral_bd, neutral_tx, None
            track, track_border = (15, 23, 42, 45), (15, 23, 42, 70)
        draw_rounded_rect(draw, x, y, card_w, card_h, 22, fill=bg, outline=bd, width=2)
        rank_w = 44
        draw_rounded_rect(draw, x + card_w - rank_w - 10, y + 10, rank_w, 30, 14, fill=bd, outline=None, width=0)
        # número global: pg1 = 1..12, pg2 = 13..27, pg3 = 28..42, …
        page_offset = 0 if page_num == 1 else 12 + (page_num - 2) * 15
        global_ix = page_offset + ix + 1
        draw.text((x + card_w - 10 - rank_w / 2, y + 25), norm_txt(str(global_ix)), fill=(255, 255, 255, 255), font=get_font(16, True), anchor="mm")
        name_area_w = card_w - 28 - 54
        f_name = get_font(f_name_base, True)
        nome_1linha = ellipsize_text(draw, nome.upper(), f_name, name_area_w)
        draw.text((x + 14, y + 10), nome_1linha, fill=dark, font=f_name)
        f_mun = get_font(14 if big else 13, False)
        muni_text = ellipsize_text(draw, f"Município: {municipio}", f_mun, card_w - 28)
        y_mun = y + 10 + f_name.size + 2
        draw.text((x + 14, y_mun), muni_text, fill=(100, 116, 139, 255), font=f_mun)
        # Lâmina de sangria = valor absoluto de falta_sangrar quando negativo (vertendo)
        def _lamina_txt() -> str:
            try:
                v = float(falta_sangrar)
                return fmt_m_2dp_dot(abs(v))
            except Exception:
                return "N/A"

        f_var = get_font(f_var_base, True)
        arrow_x, arrow_y = x + 14, y + (58 if big else 54)
        if is_vertendo:
            draw.text((x + 14, arrow_y - 2), norm_txt("Vertendo"), fill=tx, font=f_var)
        else:
            if up_arrow is None:
                draw_equal_sign(draw, arrow_x, arrow_y, 22 if big else 20, tx)
            else:
                draw_arrow(draw, arrow_x, arrow_y, up_arrow, 22 if big else 20, tx)
            var_txt = "N/A" if pd.isna(var_m) else f"{'+' if float(var_m) > 0 else ''}{fmt_m_2dp_dot(var_m)}"
            draw.text((x + 44, arrow_y - 2), norm_txt(var_txt), fill=tx, font=f_var)
        f_line = get_font(f_line_base, False)
        l1 = f"Variação m³: {fmt_milhoes_br(var_m3, convert_raw_m3_to_millions)}"
        l2 = f"Vertendo / Lâmina: {_lamina_txt()}" if is_vertendo else f"Falta p/ sangrar: {fmt_m_2dp_dot(falta_sangrar)}"
        l3 = f"Vol. atual: {fmt_milhoes_br(vol, convert_raw_m3_to_millions)}"
        draw.text((x + 14, y + (86 if big else 78)), norm_txt(l1), fill=(51, 65, 85, 255), font=f_line)
        draw.text((x + 14, y + (108 if big else 98)), norm_txt(l2), fill=(51, 65, 85, 255), font=f_line)
        draw.text((x + 14, y + (130 if big else 118)), norm_txt(l3), fill=(51, 65, 85, 255), font=f_line)
        pct_val = 0.0
        if not pd.isna(pct):
            try:
                pct_val = float(pct)
            except Exception:
                pass
        pct_val = max(0.0, min(100.0, pct_val))
        bar_x, bar_w, bar_h = x + 14, card_w - 28, 10 if big else 8
        bar_y = y + card_h - (30 if big else 28)
        draw_rounded_rect(draw, bar_x, bar_y, bar_w, bar_h, r=6, fill=track, outline=track_border, width=1)
        fill_w = int(bar_w * (pct_val / 100.0))
        if fill_w > 0:
            draw_rounded_rect(draw, bar_x, bar_y, fill_w, bar_h, r=6, fill=tx, outline=None, width=0)
        draw_rounded_rect(draw, bar_x, bar_y, bar_w, max(2, bar_h // 3), r=6, fill=(255, 255, 255, 28), outline=None, width=0)
        f_pct = get_font(16 if big else 14, True)
        draw.text((x + card_w - 14, bar_y - (18 if big else 16)), norm_txt(f"{fmt_pct_br(pct_val)}%"), fill=tx, font=f_pct, anchor="ra")

    for i in range(len(ordered)):
        ri, ci = i // cols_grid, i % cols_grid
        cx = grid_x + ci * (card_w + gap_x)
        cy = cards_start_y + ri * (card_h + gap_y)
        draw_item(i, ordered.iloc[i], cx, cy)

    fonte_txt = build_fonte_gerencia(df_all)
    foot_y = H - (72 if big else 70)
    draw.line((pad, foot_y - 18, W - pad, foot_y - 18), fill=(226, 232, 240, 255), width=2)
    f_foot = get_font(26 if big else 22, False)
    page_label = f"Pág. {page_num}/{total_pages}  •  {fonte_txt}" if total_pages > 1 else fonte_txt
    draw.text((pad, foot_y), norm_txt(page_label), fill=(100, 116, 139, 255), font=f_foot)
    ts = datetime.now(TZ_FORTALEZA).strftime("%d/%m/%Y %H:%M")
    draw.text((W - pad, foot_y), norm_txt(f"Gerado em {ts}"), fill=(100, 116, 139, 255), font=f_foot, anchor="ra")
    return img.convert("RGB") if formato.upper() == "JPG" else img


def generate_image(df_all: pd.DataFrame, mode: str, date_anterior: str, date_atual: str,
                   ordenar: str, formato: str, convert_raw_m3_to_millions: bool) -> Image.Image:
    """Mantido por compatibilidade — retorna somente a primeira página."""
    pages = generate_pages(df_all, mode, date_anterior, date_atual, ordenar, formato, convert_raw_m3_to_millions)
    return pages[0]


def df_to_json_safe(df: pd.DataFrame) -> list:
    """Converte DataFrame para lista de dicts serializável em JSON (NaN -> null)."""
    return json.loads(df.to_json(orient="records", date_format="iso", default_handler=str))
