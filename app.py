"""Painting Studio Assistant – Streamlit UI.

Run:  .venv/bin/streamlit run app.py
"""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import pickle
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import httpx
import streamlit as st
from PIL import Image

from assistant import image_tools
from assistant.agent import RunResult, run_skill
from assistant.config import settings
from assistant.llm import make_provider
from assistant.llm.ollama_provider import list_ollama_models
from assistant.schemas import OUTPUT_MODELS, CritiqueResult, ReferenceResult
from assistant.skills import load_catalog
from assistant.tools import ToolContext, run_tool

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
ICONS = ROOT / "assets" / "icons"  # Tabler Icons (MIT), outline set
RESULTS_DIR = ROOT / ".cache" / "results"  # saved results, on this computer only (git-ignored)
PAINTINGS_DIR = ROOT / ".cache" / "paintings"  # the user's own paintings (cleaned JPEG + metadata), never in git

st.set_page_config(page_title="Painting Studio Assistant", page_icon=str(ICONS / "brush.svg"), layout="wide")
CATALOG = load_catalog()


# ---------------------------------------------------------------- icons + styling helpers

@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    svg = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    svg = re.sub(r'\s(width|height|class)="[^"]*"', "", svg)
    return re.sub(r"\s+", " ", svg).strip()


def icon(name: str) -> str:
    """Inline Tabler icon (inherits the text color and size)."""
    return f'<span class="fm-icon">{_svg(name)}</span>'


def _mask(name: str) -> str:
    data = base64.b64encode(_svg(name).encode()).decode()
    return f'url("data:image/svg+xml;base64,{data}")'


def _icon_before(selector: str, name: str) -> str:
    """CSS that puts a Tabler icon in front of a Streamlit widget label (buttons, tabs, radios)."""
    m = _mask(name)
    return (f'{selector}::before{{content:"";display:inline-block;width:1.1em;height:1.1em;margin-right:.45em;'
            f'vertical-align:-.2em;background-color:currentColor;-webkit-mask:{m} no-repeat center/contain;'
            f'mask:{m} no-repeat center/contain;}}')


def heading(name: str, text: str, level: int = 4) -> None:
    st.markdown(f'<h{level} class="fm-h">{icon(name)}<span>{html.escape(text)}</span></h{level}>',
                unsafe_allow_html=True)


def callout(kind: str, text: str, title: str | None = None) -> None:
    """kind: info | success | warning | error. The text is escaped (it may come from the model)."""
    ic = {"info": "info-circle", "success": "circle-check", "warning": "alert-triangle", "error": "circle-x"}[kind]
    head = f"<strong>{html.escape(title)}</strong><br>" if title else ""
    st.markdown(f'<div class="fm-callout fm-{kind}">{icon(ic)}<div>{head}{html.escape(text)}</div></div>',
                unsafe_allow_html=True)


TAB_ICONS = ["message-2", "chart-bar", "building-bank", "list-details", "shield-check"]
CSS = "\n".join([
    """
    /* hide the 'running' animation and the Deploy button in the top-right corner */
    [data-testid="stStatusWidget"], [data-testid="stAppDeployButton"], .stAppDeployButton { display: none !important; }

    .fm-icon { display: inline-flex; width: 1.15em; height: 1.15em; flex: none; }
    .fm-icon svg { width: 100%; height: 100%; }
    .fm-h { display: flex; align-items: center; gap: .5rem; }
    .fm-h .fm-icon { color: var(--fm-accent); margin-right: .5rem; }
    :root { --fm-accent: #d97706; }

    .fm-title { display: flex; align-items: center; gap: .75rem; margin: 0 0 .25rem; font-size: 2.3rem; font-weight: 700; }
    .fm-title .fm-icon { width: 2.4rem; height: 2.4rem; color: var(--fm-accent); }
    .fm-subtitle { opacity: .7; margin-bottom: 1.25rem; }

    .fm-callout { display: flex; gap: .65rem; align-items: flex-start; padding: .75rem 1rem; border-radius: .6rem;
                  border: 1px solid; margin: .25rem 0 .9rem; line-height: 1.45; }
    .fm-callout .fm-icon { margin-top: .1rem; }
    .fm-info    { background: rgba(59,130,246,.10); border-color: rgba(59,130,246,.35); }
    .fm-info .fm-icon { color: #3b82f6; }
    .fm-success { background: rgba(34,197,94,.10);  border-color: rgba(34,197,94,.35); }
    .fm-success .fm-icon { color: #22c55e; }
    .fm-warning { background: rgba(245,158,11,.12); border-color: rgba(245,158,11,.40); }
    .fm-warning .fm-icon { color: #f59e0b; }
    .fm-error   { background: rgba(239,68,68,.10);  border-color: rgba(239,68,68,.40); }
    .fm-error .fm-icon { color: #ef4444; }

    .fm-badge { display: inline-flex; align-items: center; gap: .4rem; padding: .3rem .75rem; border-radius: 999px;
                font-size: .85rem; font-weight: 600; border: 1px solid; margin: .1rem 0 .8rem; }
    .fm-badge.ok    { color: #16a34a; background: rgba(34,197,94,.10);  border-color: rgba(34,197,94,.4); }
    .fm-badge.cloud { color: #2563eb; background: rgba(59,130,246,.10); border-color: rgba(59,130,246,.4); }
    .fm-badge.block { color: #dc2626; background: rgba(239,68,68,.10);  border-color: rgba(239,68,68,.4); }

    .fm-skill { border: 1px solid rgba(128,128,128,.25); border-left: 3px solid rgba(128,128,128,.35);
                border-radius: 0 .6rem .6rem 0; padding: .65rem .85rem; margin-bottom: .6rem;
                font-size: .82rem; line-height: 1.4; }
    .fm-skill.used { border-left-color: var(--fm-accent); }
    .fm-skill-head { display: flex; justify-content: space-between; align-items: center; gap: .6rem; flex-wrap: wrap; }
    .fm-skill-title { display: flex; align-items: center; gap: .45rem; font-weight: 600; }
    .fm-skill-title .fm-icon { color: var(--fm-accent); }
    .fm-skill-title code { font-weight: 400; font-size: .78rem; opacity: .7; }
    .fm-skill p { margin: .35rem 0 .4rem; font-size: .88rem; opacity: .8; line-height: 1.45; }
    .fm-skill .fm-meta { margin-top: .35rem; }
    .fm-tool { display: inline-flex; align-items: center; gap: .3rem; font-size: .78rem; padding: .1rem .6rem;
               margin: 0 .3rem .3rem 0; border-radius: 999px; border: 1px solid rgba(128,128,128,.3); }
    .fm-tool.allowed { color: #e8a54b; border-color: rgba(232,165,75,.45); background: rgba(217,119,6,.12); }
    .fm-tool.denied { opacity: .45; text-decoration: line-through; }
    .fm-tool .fm-icon { width: .95em; height: .95em; }

    .fm-swatches { display: flex; flex-wrap: wrap; gap: .6rem; margin: .25rem 0 .5rem; }
    .fm-swatch { width: 96px; font-size: .75rem; line-height: 1.35; }
    .fm-swatch div { height: 60px; border-radius: .5rem; border: 1px solid rgba(128,128,128,.3); margin-bottom: .3rem; }
    .fm-meta { font-size: .85rem; opacity: .75; }
    .fm-dot { display: inline-block; width: .7em; height: .7em; border-radius: 50%; margin: 0 .3em 0 .1em; }

    .fm-card { border: 1px solid rgba(128,128,128,.25); border-radius: .6rem; padding: .25rem 1rem; margin-bottom: .8rem; }
    .fm-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: .55rem 0; }
    .fm-row + .fm-row { border-top: 1px solid rgba(128,128,128,.18); }
    .fm-pill { font-size: .8rem; font-weight: 600; padding: .1rem .6rem; border-radius: 999px; background: rgba(128,128,128,.15); }
    .fm-pill.ok  { color: #16a34a; background: rgba(34,197,94,.12); }
    .fm-pill.bad { color: #dc2626; background: rgba(239,68,68,.12); }
    .fm-quote { border-left: 3px solid var(--fm-accent); padding: .4rem .9rem; margin: .2rem 0 .6rem;
                background: rgba(128,128,128,.08); border-radius: 0 .4rem .4rem 0; word-break: break-word; }
    .fm-label { font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; opacity: .65; margin-top: .4rem; }

    /* JSON in the Log tab – "Ochre studio" palette (earth pigments, matches the accent) */
    code.language-json .token.property { color: #E8A54B !important; }
    code.language-json .token.string { color: #A8B98A !important; }
    code.language-json .token.number { color: #E07A5F !important; }
    code.language-json .token.boolean, code.language-json .token.null,
    code.language-json .token.keyword { color: #C49BBB !important; }
    code.language-json .token.punctuation, code.language-json .token.operator { color: #8C857A !important; }

    /* analysis: stat cards and proportion bars */
    .fm-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: .6rem; margin: .4rem 0 .9rem; }
    .fm-stat { border: 1px solid rgba(128,128,128,.25); border-radius: .6rem; padding: .6rem .8rem; }
    .fm-stat .lbl { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; opacity: .65; }
    .fm-stat .val { font-size: 1.15rem; font-weight: 600; margin: .1rem 0; }
    .fm-stat .hint { font-size: .82rem; opacity: .8; line-height: 1.35; }
    .fm-bar { display: flex; height: 14px; border-radius: 7px; overflow: hidden; margin: .35rem 0 .25rem;
              border: 1px solid rgba(128,128,128,.25); }
    .fm-bar div { height: 100%; }
    .fm-legend { display: flex; flex-wrap: wrap; gap: .3rem .9rem; font-size: .8rem; opacity: .85; }
    .fm-insight { display: flex; gap: .5rem; align-items: flex-start; font-size: .92rem; line-height: 1.45; margin: .2rem 0 .8rem; }
    .fm-insight .fm-icon { color: var(--fm-accent); margin-top: .15rem; }

    /* references: museum cards */
    .fm-ref h5 { margin: .5rem 0 .1rem; font-size: 1rem; line-height: 1.3; }
    .fm-ref h5 a { color: inherit; text-decoration: none; }
    .fm-ref h5 a:hover { text-decoration: underline; }
    .fm-ref .by { font-size: .85rem; opacity: .75; margin-bottom: .4rem; }
    .fm-src { display: inline-block; font-size: .72rem; font-weight: 600; padding: .1rem .55rem; border-radius: 999px;
              background: rgba(217,119,6,.15); color: var(--fm-accent); margin-bottom: .5rem; }
    .fm-noimg { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: .4rem;
                aspect-ratio: 4 / 3; border-radius: .5rem; border: 1px dashed rgba(128,128,128,.4);
                background: rgba(128,128,128,.07); font-size: .82rem; text-align: center; padding: 1rem; }
    .fm-noimg .fm-icon { width: 1.8rem; height: 1.8rem; opacity: .6; }
    .fm-noimg a { color: var(--fm-accent); }
    .fm-chip { display: inline-block; font-size: .78rem; padding: .1rem .6rem; margin: 0 .3rem .3rem 0; border-radius: 999px;
               border: 1px solid rgba(128,128,128,.3); }

    .stButton button p { white-space: normal; }

    /* own-paintings gallery */
    .fm-gallery-head { display: flex; justify-content: space-between; align-items: center; gap: .8rem; flex-wrap: wrap;
                       margin: .4rem 0 .6rem; }
    .fm-gallery-head .fm-h { font-size: 1.1rem; font-weight: 600; }
    [class*="st-key-tile_"] { gap: .35rem !important; padding: .5rem !important; }
    .fm-thumb { aspect-ratio: 3 / 4; display: flex; align-items: center; justify-content: center; overflow: hidden;
                border-radius: .4rem; background: rgba(128,128,128,.12); margin-bottom: .45rem; }
    .fm-thumb img { max-width: 100%; max-height: 100%; object-fit: contain; display: block; }
    .fm-tname { font-weight: 600; font-size: .85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .fm-tinfo { display: flex; justify-content: space-between; align-items: center; gap: .3rem; margin-top: .15rem;
                flex-wrap: wrap; }
    .fm-tbadges { display: flex; gap: .2rem; flex-wrap: wrap; }
    [class*="st-key-tile_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
    [class*="st-key-tile_"] button, .st-key-add_tile button { padding: .25rem .4rem; min-height: 2.1rem; }
    [class*="st-key-tile_"] button p { white-space: nowrap; font-size: .85rem; }
    [class*="st-key-sel_"] button { color: var(--fm-accent) !important; border-color: rgba(217,119,6,.5) !important;
                                    opacity: 1 !important; background: rgba(217,119,6,.08) !important; }
    .fm-tb { display: inline-flex; align-items: center; gap: .15rem; font-size: .72rem; padding: .05rem .4rem;
             border-radius: 999px; background: rgba(217,119,6,.15); color: #e8a54b; }
    .fm-tb.off { background: rgba(128,128,128,.12); color: rgba(128,128,128,.8); }
    .fm-tb .fm-icon { width: .9em; height: .9em; }
    [class*="st-key-del_"] button p { font-size: 0; }
    [class*="st-key-del_"] button p::before { width: 16px !important; height: 16px !important; margin: 0 !important; }
    .st-key-add_tile { gap: .35rem !important; padding: .5rem !important; }
    .fm-add { flex-direction: column; gap: .25rem; text-align: center; border: 1.5px dashed rgba(128,128,128,.45);
              background: transparent; margin-bottom: 1.1rem; }
    .fm-add span { opacity: .85; }
    .fm-add .fm-icon { width: 1.6rem; height: 1.6rem; color: var(--fm-accent); }
    .fm-add small { opacity: .7; font-size: .72rem; }
    .st-key-add_tile [data-testid="stFileUploaderDropzone"] { padding: 0; background: transparent; border: none;
                                                              justify-content: center; }
    .st-key-add_tile [data-testid="stFileUploaderDropzone"] button { width: 100%; }
    .st-key-add_tile [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
    [class*="st-key-private_"] label p, [class*="st-key-private_"] label div { white-space: normal !important; overflow: visible !important;
                                                         text-overflow: clip !important; }
    .fm-badge { max-width: 100%; }
    """,
    _icon_before(".st-key-run_painting-critique button p", "brush"),
    _icon_before(".st-key-run_reference-finder button p", "building-bank"),
    _icon_before(".st-key-run_quick button p", "chart-bar"),
    _icon_before("[class*='st-key-rerun_'] button p", "refresh"),
    _icon_before('.st-key-backend [role="radiogroup"] label:nth-of-type(1) p', "cpu"),
    _icon_before('.st-key-backend [role="radiogroup"] label:nth-of-type(2) p', "cloud"),
    _icon_before('.st-key-source [role="radiogroup"] label:nth-of-type(1) p', "photo"),
    _icon_before('.st-key-source [role="radiogroup"] label:nth-of-type(2) p', "upload"),
    _icon_before("[class*='st-key-private_'] label p", "lock"),
    _icon_before("[class*='st-key-del_'] button p", "trash"),
    *[_icon_before(f'.stTabs [role="tab"]:nth-of-type({i}) p', n) for i, n in enumerate(TAB_ICONS, 1)],
])
st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------- friendly error messages

def describe_error(raw: str) -> tuple[str, str]:
    """Raw exception text -> (short title, reason the user can act on). The raw text stays in the Log tab."""
    s, low = raw or "", (raw or "").lower()
    if "private artwork cannot be sent" in low:
        return ("Blocked to protect your privacy",
                "This image is marked as your own private artwork, so it cannot be sent to a cloud model. "
                "Switch to the local model (Ollama).")
    if s.startswith("QuotaExceeded") or ("429" in s and "perday" in low):
        return ("Daily Gemini quota used up",
                "The free tier allows about 20 requests per day for each model. Try again tomorrow, "
                "pick another Gemini model, or use the local model.")
    if "429" in s or "resource_exhausted" in low:
        return ("Too many requests",
                "Gemini is rate-limiting this API key. Wait a minute and try again, or pick another Gemini model.")
    if "gemini_api_key is missing" in low:
        return ("Gemini API key missing", "Add GEMINI_API_KEY to the .env file (see .env.example).")
    if "api_key_invalid" in low or "api key not valid" in low or "permission_denied" in low:
        return ("Gemini rejected the API key", "Check that GEMINI_API_KEY in the .env file is correct and active.")
    if "404" in s and "not found" in low:
        return ("Model not found", "The selected model is not available. Pick another model in the sidebar.")
    if any(x in low for x in ("503", "500 ", "unavailable", "overloaded", "internal")):
        return ("The model service is busy", "The AI service is temporarily overloaded. Try again in a few minutes.")
    if "museum apis are unreachable" in low:
        return ("Museum search unavailable",
                "The Met and the Art Institute of Chicago could not be reached. Check your internet connection.")
    if "ollama" in low or "failed to connect" in low or "connection refused" in low:
        return ("Local model not reachable",
                "Ollama is not running, or the selected model is not downloaded. Start Ollama and pull the model "
                "(see README).")
    if "timeout" in low or "timed out" in low:
        return ("The request timed out", "The model took too long to answer. Try again.")
    if "does not match the schema" in low:
        return ("Unusable answer from the model",
                "The model's answer did not match the expected format, even after automatic repair attempts. "
                "Try again, or lower the temperature.")
    if "did not recommend a single real" in low:
        return ("No valid references",
                "The model only suggested artworks that the museum search did not return, so all were dropped. "
                "Try again.")
    return ("Something went wrong", "The run failed unexpectedly. The technical details are in the Log tab.")


def show_error(raw: str) -> None:
    title, reason = describe_error(raw)
    callout("error", reason, title)


# ---------------------------------------------------------------- museum images

@st.cache_data(ttl=24 * 3600, show_spinner=False)
def museum_image(url: str) -> bytes | None:
    """Fetches a museum image server-side. Some hosts (e.g. the Art Institute of Chicago IIIF server) sit behind a
    bot challenge and refuse direct loading – then we return None and the UI shows a link instead of a broken image."""
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True,
                      headers={"User-Agent": "festomuhely-asszisztens/0.1 (university project)"})
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        return None
    return r.content


# ---------------------------------------------------------------- plain-language reading of the measurements

def bar(parts: list[tuple[float, str, str]]) -> str:
    """Proportion bar + legend. parts: (percent, css color, label)."""
    segs = "".join(f'<div style="width:{p}%;background:{c}" title="{html.escape(lbl)} {p}%"></div>' for p, c, lbl in parts)
    legend = "".join(f'<span><span class="fm-dot" style="background:{c}"></span>{html.escape(lbl)} {p:g}%</span>'
                     for p, c, lbl in parts)
    return f'<div class="fm-bar">{segs}</div><div class="fm-legend">{legend}</div>'


def stat(label: str, value: str, hint: str) -> str:
    return (f'<div class="fm-stat"><div class="lbl">{html.escape(label)}</div><div class="val">{html.escape(value)}</div>'
            f'<div class="hint">{html.escape(hint)}</div></div>')


def insight(text: str) -> None:
    st.markdown(f'<div class="fm-insight">{icon("bulb")}<div>{html.escape(text)}</div></div>', unsafe_allow_html=True)


def saturation_word(s: float) -> tuple[str, str]:
    if s < 25:
        return "Muted", "Mostly greyed, subdued colors."
    if s < 50:
        return "Moderate", "A balance of muted and saturated colors."
    return "Vivid", "Strong, saturated colors dominate."


def contrast_word(c: float) -> tuple[str, str]:
    if c < 15:
        return "Low", "Values are close together – a soft, quiet image. Squint to check if shapes still read."
    if c < 25:
        return "Medium", "A moderate value range – readable, without dramatic light."
    return "Strong", "A wide value range – bold light and shadow."


def key_hint(value_key: str) -> str:
    if value_key.startswith("light"):
        return "Mostly light values – an airy, bright painting."
    if value_key.startswith("dark"):
        return "Mostly dark values – a moody, low-key painting."
    return "Mostly middle values – check that lights and darks are clear enough."


def weight_hint(left: float, right: float) -> str:
    if abs(left - right) < 10:
        return "Visual weight is evenly balanced left to right."
    side = "left" if left > right else "right"
    return f"Visual weight leans to the {side} ({max(left, right):g}%)."


# ---------------------------------------------------------------- model lists

@st.cache_data(ttl=3600, show_spinner=False)
def gemini_models(api_key: str) -> list[str]:
    if not api_key:
        return []
    try:
        from assistant.llm.gemini_provider import list_gemini_models
        names = list_gemini_models(api_key)
    except Exception:  # noqa: BLE001 – offline or bad key: fall back to the configured model
        return []
    skip = ("image", "banana", "tts", "embedding", "live", "audio")
    return [n for n in names if not any(x in n for x in skip)]


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    heading("settings", "Settings", 3)
    backend = st.radio("Model", ["Local (Ollama)", "Gemini (cloud)"], key="backend",
                       help="Local: the image never leaves this computer. Gemini: Google cloud – stronger, "
                            "but the image is uploaded.")
    is_local = backend.startswith("Local")
    if is_local:
        models = list_ollama_models(settings.ollama_host)
        if models:
            default = models.index(settings.ollama_model) if settings.ollama_model in models else 0
            model = st.selectbox("Local model", models, index=default)
        else:
            callout("warning", "Ollama is not running, or no model is downloaded. See the README.")
            model = st.text_input("Local model", settings.ollama_model)
    else:
        options = gemini_models(settings.gemini_api_key)
        if settings.gemini_model not in options:
            options = [settings.gemini_model, *options]
        model = st.selectbox("Gemini model", options, index=options.index(settings.gemini_model),
                             help="The free tier allows about 20 requests per day per model; a critique uses ~3.")
        if not settings.gemini_api_key:
            callout("error", "GEMINI_API_KEY is missing from the .env file.")
    temperature = st.slider("Temperature", 0.0, 1.0, settings.temperature, 0.1,
                            help="Lower = more consistent critique.")
    precheck = st.toggle("Image prompt-injection pre-screening", value=True)

# ---------------------------------------------------------------- saved results + own paintings (on this computer)

SKILL_KINDS = ("painting-critique", "reference-finder")


def image_id_of(jpeg_bytes: bytes) -> str:
    return hashlib.sha256(jpeg_bytes).hexdigest()[:20]


def _results_file(img_id: str) -> Path:
    return RESULTS_DIR / f"{img_id}.pkl"


def load_saved(img_id: str) -> dict:
    """kind -> {"value": RunResult | ToolContext, "saved_at": datetime}. Unreadable files count as empty."""
    try:
        with _results_file(img_id).open("rb") as f:
            data = pickle.load(f)  # only files this app wrote itself, in a git-ignored local folder
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 – missing or outdated file
        return {}


def save_all(img_id: str, saved: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with _results_file(img_id).open("wb") as f:
        pickle.dump(saved, f)


def _pfile(pid: str, suffix: str) -> Path:
    return PAINTINGS_DIR / f"{pid}{suffix}"


def list_paintings() -> list[dict]:
    """The user's own paintings, newest first: {"id", "name", "added_at", "private", "summary"}."""
    items = []
    for meta_path in PAINTINGS_DIR.glob("*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _pfile(meta_path.stem, ".jpg").exists():
            items.append({**meta, "id": meta_path.stem})
    return sorted(items, key=lambda m: m.get("added_at", ""), reverse=True)


def save_painting(prep: image_tools.PreparedImage, name: str) -> str:
    """Stores the cleaned JPEG (no EXIF/GPS) once; the same photo uploaded again is not duplicated."""
    pid = image_id_of(prep.jpeg_bytes)
    if not _pfile(pid, ".json").exists():
        PAINTINGS_DIR.mkdir(parents=True, exist_ok=True)
        _pfile(pid, ".jpg").write_bytes(prep.jpeg_bytes)
        thumb = prep.image.copy()
        thumb.thumbnail((360, 360))
        thumb.save(_pfile(pid, "_thumb.jpg"), format="JPEG", quality=85)
        _pfile(pid, ".json").write_text(json.dumps({
            "name": name, "added_at": datetime.now().isoformat(timespec="seconds"), "private": True, "summary": {},
        }), encoding="utf-8")
    return pid


def load_painting(pid: str) -> image_tools.PreparedImage:
    """Reopens a stored painting from its exact bytes (no re-encoding → same id → same saved results)."""
    data = _pfile(pid, ".jpg").read_bytes()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return image_tools.PreparedImage(img, data, "JPEG", img.size)


def update_meta(pid: str, **changes) -> None:
    path = _pfile(pid, ".json")
    if path.exists():
        meta = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({**meta, **changes}), encoding="utf-8")


def delete_painting(pid: str) -> None:
    for path in (_pfile(pid, ".jpg"), _pfile(pid, "_thumb.jpg"), _pfile(pid, ".json"), _results_file(pid)):
        path.unlink(missing_ok=True)


def summary_of(results: dict) -> dict:
    """Small summary for the gallery badges (so tiles don't have to open every results file)."""
    out = {"analysis": "quick" in results or "painting-critique" in results}
    if "painting-critique" in results:
        scores = [c.score for c in results["painting-critique"]["value"].result.categories]
        out["critique"] = round(sum(scores) / len(scores), 1)
    if "reference-finder" in results:
        out["refs"] = len(results["reference-finder"]["value"].result.references)
    return out


def tile_badges(summary: dict) -> str:
    def badge(ic: str, text: str, on: bool, tip: str) -> str:
        return f'<span class="fm-tb{"" if on else " off"}" title="{tip}">{icon(ic)}{text}</span>'
    crit, refs = summary.get("critique"), summary.get("refs")
    return (badge("brush", f"{crit:g}" if crit else "", bool(crit), "Critique (average score)")
            + badge("chart-bar", "", bool(summary.get("analysis")), "Analysis")
            + badge("building-bank", str(refs) if refs else "", bool(refs), "Museum references"))


def thumb_uri(pid: str) -> str:
    data = base64.b64encode(_pfile(pid, "_thumb.jpg").read_bytes()).decode()
    return f"data:image/jpeg;base64,{data}"


def add_tile() -> None:
    with st.container(key="add_tile", border=True):
        st.markdown(f'<div class="fm-thumb fm-add">{icon("upload")}<span>Add painting</span>'
                    '<small>JPEG, PNG, WEBP<br>max 15 MB</small></div>', unsafe_allow_html=True)
        n = st.session_state.get("uploader_n", 0)
        up = st.file_uploader("Add painting", type=["jpg", "jpeg", "png", "webp"], label_visibility="collapsed",
                              key=f"uploader_{n}")
    if up:
        try:
            prep = image_tools.prepare_image(up.getvalue())
        except image_tools.ImageValidationError as exc:
            st.session_state.upload_error = str(exc)
        else:
            st.session_state.selected_painting = save_painting(prep, up.name)
            st.session_state.pop("upload_error", None)
        st.session_state.uploader_n = n + 1  # fresh, empty uploader
        st.rerun()


def painting_tile(meta: dict, selected: bool) -> None:
    pid = meta["id"]
    with st.container(key=f"tile_{pid}", border=True):
        added = datetime.fromisoformat(meta["added_at"]) if meta.get("added_at") else None
        st.markdown(f'<div class="fm-thumb"><img src="{thumb_uri(pid)}" alt=""></div>'
                    f'<div class="fm-tinfo"><span class="fm-meta">{f"{added:%b %d}" if added else ""}</span>'
                    f'<span class="fm-tbadges">{tile_badges(meta.get("summary", {}))}</span></div>',
                    unsafe_allow_html=True)
        if st.session_state.get("confirm_delete") == pid:
            st.markdown('<div class="fm-meta">Delete this painting and its saved results?</div>',
                        unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            if c1.button("Delete", key=f"delyes_{pid}", type="primary", width="stretch"):
                delete_painting(pid)
                st.session_state.pop("confirm_delete", None)
                if selected:
                    st.session_state.pop("selected_painting", None)
                st.rerun()
            if c2.button("Cancel", key=f"delno_{pid}", width="stretch"):
                st.session_state.pop("confirm_delete", None)
                st.rerun()
        else:
            c1, c2 = st.columns([5, 2], gap="small", vertical_alignment="center")
            if selected:
                c1.button("Selected", key=f"sel_{pid}", disabled=True, width="stretch")
            elif c1.button("Open", key=f"open_{pid}", width="stretch"):
                st.session_state.selected_painting = pid
                st.rerun()
            if c2.button("Delete", key=f"del_{pid}", help="Delete this painting", width="stretch"):
                st.session_state.confirm_delete = pid
                st.rerun()


def gallery() -> None:
    items = list_paintings()
    selected = st.session_state.get("selected_painting")
    st.markdown(f'<div class="fm-gallery-head"><span class="fm-h" style="margin:0">{icon("photo")}<span>Your paintings'
                f'</span><span class="fm-meta">&nbsp;· {len(items)}</span></span><span class="fm-badge ok" style="margin:0">'
                f'{icon("lock")}Stored only on this computer</span></div>', unsafe_allow_html=True)
    if selected:  # accent border on the selected tile
        st.markdown(f"<style>.st-key-tile_{selected} {{ border: 2px solid var(--fm-accent) !important; }}</style>",
                    unsafe_allow_html=True)
    cells: list = ["add", *items]
    for i in range(0, len(cells), 6):
        for col, cell in zip(st.columns(6, gap="small"), cells[i:i + 6]):
            with col:
                if cell == "add":
                    add_tile()
                else:
                    painting_tile(cell, cell["id"] == selected)
    if err := st.session_state.get("upload_error"):
        callout("error", err, "This file could not be added")
    st.markdown(f'<div class="fm-legend" style="margin:.2rem 0 1rem">'
                f'<span>{icon("brush")} critique (average score)</span><span>{icon("chart-bar")} analysis</span>'
                f'<span>{icon("building-bank")} references</span><span>faded = not run yet</span></div>',
                unsafe_allow_html=True)


# ---------------------------------------------------------------- image selection

st.markdown(f'<div class="fm-title">{icon("brush")}<span>Painting Studio Assistant</span></div>'
            '<div class="fm-subtitle">An AI painting tutor: critique grounded in measured image data, plus museum '
            'references to learn from. It never paints for you.</div>', unsafe_allow_html=True)

source = st.radio("Image source", ["Sample (public-domain masterpieces)", "Your own paintings"],
                  horizontal=True, key="source")
own = source.startswith("Your own")
if own:
    gallery()

prepared = None
note_key, note_default = "note_none", ""  # one note per painting / sample
col_in, col_img = st.columns([1, 1.3], gap="large")
with col_in:
    if not own:
        files = sorted(SAMPLES.glob("*.jpg"), key=lambda p: (p.name.startswith("INJECTION"), p.name))
        if not files:
            callout("info", "No sample images yet – run: .venv/bin/python scripts/fetch_samples.py")
        else:
            pick = st.selectbox("Sample image", files,
                                format_func=lambda p: p.stem.replace("INJECTION_", "[injection test] ")
                                .replace("_", " ").title().replace("[Injection Test]", "[injection test]"))
            try:
                prepared = image_tools.prepare_image(pick.read_bytes())
            except image_tools.ImageValidationError as exc:
                callout("error", str(exc), "Invalid image")
            note_key = f"note_sample_{pick.stem}"  # samples: kept for this session
            note_default = st.session_state.setdefault("sample_notes", {}).get(pick.stem, "")
        private = False
    else:
        pid = st.session_state.get("selected_painting")
        meta = next((m for m in list_paintings() if m["id"] == pid), None)
        private = True
        if not meta:
            callout("info", "Add a painting above, or open one from your gallery.")
        else:
            private = st.checkbox("This is my own, unpublished artwork (only a local model may see it)",
                                  value=meta.get("private", True), key=f"private_{pid}")
            if private != meta.get("private", True):
                update_meta(pid, private=private)
            prepared = load_painting(pid)
            note_key, note_default = f"note_{pid}", meta.get("note", "")  # own paintings: saved with the painting

    # privacy status – always visible
    if private and not is_local:
        callout("error", "Private artwork + Gemini: the system will block sending it. Choose the local model.",
                "Blocked: private artwork")
    elif private:
        st.markdown(f'<span class="fm-badge ok">{icon("lock")}Private – the image stays on this computer</span>',
                    unsafe_allow_html=True)
    elif is_local:
        st.markdown(f'<span class="fm-badge ok">{icon("cpu")}Processed locally</span>', unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="fm-badge cloud">{icon("cloud")}Public image – sent to Gemini (Google cloud)</span>',
                    unsafe_allow_html=True)

    if note_key not in st.session_state:
        st.session_state[note_key] = note_default
    note = st.text_area("Note from the painter (optional)", max_chars=500, key=note_key,
                        placeholder="e.g. Oil on canvas, 40×50 cm. The background feels too flat to me.",
                        help="Each painting keeps its own note. Notes on your own paintings are saved with them.")
    if own and prepared and note != note_default:
        update_meta(st.session_state.selected_painting, note=note)
    elif not own and prepared:
        st.session_state.sample_notes[pick.stem] = note

with col_img:
    if prepared:
        st.image(prepared.image, width="stretch")

img_id = image_id_of(prepared.jpeg_bytes) if prepared else None
if st.session_state.get("image_id") != img_id:  # another image → load its saved results
    st.session_state.image_id = img_id
    st.session_state.saved = load_saved(img_id) if img_id else {}
    st.session_state.failed = {}  # kind -> latest failed RunResult (shown, never saved)
saved: dict = st.session_state.saved
failed: dict = st.session_state.failed


def store(kind: str, value) -> None:
    if isinstance(value, RunResult) and not value.ok:
        failed[kind] = value
        return
    failed.pop(kind, None)
    saved[kind] = {"value": value, "saved_at": datetime.now()}
    save_all(img_id, saved)
    update_meta(img_id, summary=summary_of(saved))  # only does something for own paintings


SPINNER = {"painting-critique": "Measuring the painting and writing the critique",
           "reference-finder": "Searching The Met and the Art Institute of Chicago"}


def run_ai(kind: str) -> None:
    try:
        provider = make_provider("ollama" if is_local else "gemini", model, temperature)
    except Exception as exc:  # noqa: BLE001
        store(kind, RunResult(skill=kind, provider=f"{'ollama' if is_local else 'gemini'}:{model}",
                              error=f"{type(exc).__name__}: {exc}"))
        return
    with st.spinner(f"{SPINNER[kind]} ({provider.label})…"):
        store(kind, run_skill(CATALOG[kind], provider, prepared, note=note, private=private, precheck=precheck))


def run_quick() -> None:
    with st.spinner("Measuring palette, values and composition…"):
        ctx = ToolContext(image=prepared.image)
        for name in ("analyze_palette", "analyze_values", "analyze_composition"):
            run_tool(ctx, name, {}, {name})
    store("quick", ctx)


def action_bar(kind: str, run_label: str, rerun_label: str, intro: str, ai: bool) -> None:
    """Top of a tab: the run button, or – when a saved result exists – its date and a rerun button."""
    if not prepared:
        callout("info", "Choose a sample or upload your painting above first.")
        return
    entry = saved.get(kind)
    model_hint = f"Runs with the model selected in the sidebar ({'ollama' if is_local else 'gemini'}:{model})." if ai \
        else "Runs on this computer, no AI involved."
    if entry:
        value = entry["value"]
        who = f" &nbsp;·&nbsp; {icon('cpu')} {html.escape(value.provider)}" if isinstance(value, RunResult) else ""
        took = f" &nbsp;·&nbsp; {icon('clock')} {value.seconds} s" if isinstance(value, RunResult) else ""
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.markdown(f'<div class="fm-meta">{icon("history")} Saved result from {entry["saved_at"]:%b %d, %H:%M}'
                    f'{who}{took}</div>', unsafe_allow_html=True)
        clicked = c2.button(rerun_label, key=f"rerun_{kind}", width="stretch", help=model_hint)
    else:
        st.markdown(f'<div class="fm-meta" style="margin-bottom:.5rem">{html.escape(intro)}</div>',
                    unsafe_allow_html=True)
        clicked = st.button(run_label, key=f"run_{kind}", type="primary", help=model_hint)
    if clicked:
        if ai:
            run_ai(kind)
        else:
            run_quick()
        st.rerun()
    if kind in failed:
        title, reason = describe_error(failed[kind].error)
        if entry:
            reason += " Your previous result is shown below."
        callout("error", reason, title)


def current_run(kind: str) -> RunResult | None:
    """The run to show in Log / Security: the latest attempt, failed or saved."""
    if kind in failed:
        return failed[kind]
    entry = saved.get(kind)
    return entry["value"] if entry else None


# ---------------------------------------------------------------- results

runs = {k: r for k in SKILL_KINDS if (r := current_run(k))}
artifacts: dict = {}
for k in SKILL_KINDS:
    if k in saved and saved[k]["value"].ctx:
        artifacts.update(saved[k]["value"].ctx.artifacts)
if "quick" in saved:
    artifacts.update(saved["quick"]["value"].artifacts)


def pct(values: list[float]) -> str:
    return " / ".join(f"{v:g}" for v in values) + " %"


TAB_LABELS = ["Critique", "Analysis", "References", "Log (tool calls)", "Security"]
tab_c, tab_a, tab_r, tab_log, tab_sec = st.tabs(TAB_LABELS, key="result_tab", on_change="rerun")

with tab_c:
    action_bar("painting-critique", "Request critique", "Rerun critique",
               "Get structured feedback from an AI painting tutor: strengths, five scored categories and up to three "
               "concrete suggestions, grounded in measured image data.", ai=True)
    entry = saved.get("painting-critique")
    if entry:
        res: CritiqueResult = entry["value"].result
        heading("message-2", "Overall impression")
        st.markdown(res.overall_impression)
        heading("star", "Strengths")
        st.markdown("\n".join(f"- {s}" for s in res.strengths))
        heading("chart-bar", "Categories")
        for c in res.categories:
            with st.expander(f"**{c.name.capitalize()}** — {c.score}/10"):
                st.progress(c.score / 10)
                st.markdown(f"**Observation:** {c.observation}\n\n**Interpretation:** {c.reasoning}")
        weak = getattr(res, "weakest_area", None)  # results saved before skill v2.0 have no such field
        if weak:
            heading("focus-2", "Needs the most work")
            callout("warning", weak.problem, title=weak.area[:1].upper() + weak.area[1:])
            areas = getattr(res, "area_review", None) or []
            if areas:
                with st.expander("Area-by-area check"):
                    st.markdown("\n".join(f"- **{a.area}:** {a.assessment}" for a in areas))
        heading("target", "Suggestions")
        for s in sorted(res.suggestions, key=lambda s: s.priority):
            st.markdown(f"**{s.priority}. {s.title}** — {s.how}")
        heading("palette", "Respecting the style")
        st.markdown(res.style_respected)
        st.caption(f"Limitations: {res.limitations}")

with tab_a:
    action_bar("quick", "Quick analysis (no AI)", "Measure again",
               "Measure the palette, values and composition with classical image processing. It runs on this "
               "computer in a second and sends nothing anywhere." + (" The numbers below come from the critique run."
                                                                     if artifacts else ""), ai=False)
    if artifacts:
        st.markdown('<div class="fm-meta">Measured with classical image processing – no AI involved. '
                    'The critique builds on these same numbers.</div>', unsafe_allow_html=True)
    if "palette" in artifacts:
        pal = artifacts["palette"]
        heading("palette", "Palette")
        st.markdown('<div class="fm-swatches">' + "".join(
            f'<div class="fm-swatch"><div style="background:{c["hex"]}"></div>'
            f'{html.escape(c["name"])}<br><span class="fm-meta">{c["share_percent"]:g}% · {c["hex"]}</span></div>'
            for c in pal["colors"]) + "</div>", unsafe_allow_html=True)
        t = pal["temperature_balance_percent"]
        sat_word, sat_hint = saturation_word(pal["mean_saturation_percent"])
        warm, cool = t.get("warm", 0), t.get("cool", 0)
        temp_word = "Warm" if warm > cool + 10 else ("Cool" if cool > warm + 10 else "Balanced")
        st.markdown('<div class="fm-stats">'
                    + stat("Color temperature", temp_word, "Share of warm, cool and neutral colors in the painting.")
                    + stat("Saturation", f"{sat_word} ({pal['mean_saturation_percent']:g}%)", sat_hint)
                    + "</div>" + bar([(warm, "#e07a5f", "Warm"), (cool, "#5b8fc9", "Cool"),
                                      (t.get("neutral", 0), "#9a958c", "Neutral")]), unsafe_allow_html=True)
        top = pal["colors"][0]
        insight(f"The dominant color is {top['name']} ({top['share_percent']:g}% of the surface). "
                f"{temp_word} overall, with {sat_word.lower()} saturation.")

    c1, c2 = st.columns(2, gap="large")
    if "value_image" in artifacts:
        with c1:
            v = artifacts["value_stats"]
            dark, mid, light = v["dark_mid_light_percent"]
            con_word, con_hint = contrast_word(v["contrast_std"])
            heading("contrast", "Value study")
            st.image(artifacts["value_image"], width="stretch",
                     caption="The painting reduced to a few grey values – squint and compare.")
            st.markdown('<div class="fm-stats">'
                        + stat("Value key", v["value_key"].split(" (")[0].capitalize(), key_hint(v["value_key"]))
                        + stat("Contrast", con_word, con_hint) + "</div>"
                        + bar([(dark, "#2b2a28", "Dark"), (mid, "#8a8680", "Mid"), (light, "#e6e2da", "Light")]),
                        unsafe_allow_html=True)
    if "composition_image" in artifacts:
        with c2:
            comp = artifacts["composition"]
            left, right = comp["left_right_weight_percent"]
            heading("layout-grid", "Composition")
            st.image(artifacts["composition_image"], width="stretch",
                     caption="White lines: rule-of-thirds grid.")
            st.markdown('<div class="fm-legend" style="margin-bottom:.6rem">'
                        '<span><span class="fm-dot" style="background:#ff3c3c"></span>Red circle: most detailed area</span>'
                        '<span><span class="fm-dot" style="background:#3cc8ff"></span>Blue cross: visual center of mass</span>'
                        '</div>', unsafe_allow_html=True)
            if comp["on_thirds_point"]:
                focal, focal_hint = "On a thirds point", "The most detailed area sits on a classic, dynamic spot."
            elif comp["detail_in_center"]:
                focal, focal_hint = "Centered", "The most detailed area is in the middle – calm and static. Intended?"
            else:
                focal, focal_hint = "Off the thirds", "Check whether the focal point placement is deliberate."
            st.markdown('<div class="fm-stats">'
                        + stat("Focal area", focal, focal_hint)
                        + stat("Left / right weight", f"{left:g} / {right:g} %", weight_hint(left, right)) + "</div>",
                        unsafe_allow_html=True)

with tab_r:
    action_bar("reference-finder", "Find museum references", "Search again",
               "Find 2–4 public-domain masterpieces from The Met and the Art Institute of Chicago that you can learn "
               "from for this painting. This uses the AI model.", ai=True)
    entry = saved.get("reference-finder")
    if entry:
        run = entry["value"]
        res: ReferenceResult = run.result
        queries = run.ctx.artifacts.get("museum_queries", [])
        if queries:
            st.markdown('<div class="fm-label">Searched for</div>'
                        + "".join(f'<span class="fm-chip">{html.escape(q)}</span>' for q in queries),
                        unsafe_allow_html=True)
        st.markdown(res.summary)
        if not res.references:
            callout("info", "None of the museum results really fit this painting, so the assistant recommends "
                            "nothing rather than something irrelevant. Modern and abstract art is rarely public "
                            "domain in these collections. The practice exercise below still applies.",
                    title="No fitting public-domain artwork found")
        for i in range(0, len(res.references), 2):
            cols = st.columns(2, gap="large")
            for col, ref in zip(cols, res.references[i:i + 2]):
                work = run.ctx.museum_results[ref.id]
                with col, st.container(border=True):
                    img = museum_image(work["image_url"])
                    if img:
                        st.image(img, width="stretch")
                    else:
                        st.markdown(f'<div class="fm-noimg">{icon("photo-off")}<div>The museum does not allow this '
                                    f'image to be shown here.</div><a href="{html.escape(work["url"])}" target="_blank">'
                                    f'View it on the museum’s website</a></div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="fm-ref"><h5><a href="{html.escape(work["url"])}" target="_blank">'
                                f'{html.escape(work["title"])} {icon("external-link")}</a></h5>'
                                f'<div class="by">{html.escape(work["artist"])}, {html.escape(work["date"])}</div>'
                                f'<span class="fm-src">{html.escape(work["source"])}</span></div>',
                                unsafe_allow_html=True)
                    st.markdown(f"**Why it fits:** {ref.why}\n\n**What to look for:** {ref.what_to_study}")
        heading("pencil", "Practice exercise")
        callout("info", res.study_exercise)

TOOL_LABELS = {"analyze_palette": ("palette", "palette"), "analyze_values": ("contrast", "values"),
               "analyze_composition": ("layout-grid", "composition"), "search_museum": ("search", "museum search")}
SKILL_UI = {"painting-critique": ("brush", "Painting critique", "Critique"),
            "reference-finder": ("building-bank", "Reference finder", "References")}


def skill_card(skill) -> str:
    ic, title, tab = SKILL_UI.get(skill.name, ("puzzle", skill.name, ""))
    run = current_run(skill.name)
    if run and skill.name in failed:
        status = '<span class="fm-pill bad">Loaded · last run failed</span>'
    elif run:
        status = f'<span class="fm-pill ok">Loaded · ran {saved[skill.name]["saved_at"]:%b %d, %H:%M}</span>'
    else:
        status = '<span class="fm-pill">Not used yet</span>'
    tools = ""
    for name, (t_ic, label) in TOOL_LABELS.items():
        if name in skill.allowed_tools:
            req = " (required)" if name in skill.required_tools else ""
            tools += f'<span class="fm-tool allowed">{icon(t_ic)}{label}{req}</span>'
        else:
            tools += f'<span class="fm-tool denied" title="Not allowed for this skill">{icon("lock")}{label}</span>'
    return (f'<div class="fm-skill{" used" if run else ""}"><div class="fm-skill-head">'
            f'<span class="fm-skill-title">{icon(ic)}{html.escape(title)} <code>{html.escape(skill.name)}</code></span>'
            f'{status}</div><p>{html.escape(skill.description)}</p>{tools}'
            f'<div class="fm-meta">Output schema: <code>{OUTPUT_MODELS[skill.output_model].__name__}</code>'
            + (f' &nbsp;·&nbsp; shown in the {tab} tab' if tab else "") + "</div></div>")


with tab_log:
    heading("puzzle", "Skills")
    st.markdown('<div class="fm-meta" style="margin-bottom:.6rem">At startup only each skill’s name and description '
                'are loaded (catalog). The full SKILL.md instructions enter the prompt only when the skill runs, and '
                'each skill may only call its allowed tools – crossed-out tools are blocked in code.</div>'
                + "".join(skill_card(s) for s in CATALOG.values()), unsafe_allow_html=True)
    heading("list-details", "Tool calls")
    if not runs:
        callout("info", "No AI call has run for this image yet. The quick analysis does not use AI, so it has no log.")
    for name, run in runs.items():
        st.markdown(f'<div class="fm-label" style="font-size:.9rem">{html.escape(name)} · '
                    f'{html.escape(run.provider)} · {run.seconds} s</div>', unsafe_allow_html=True)
        if run.error:
            st.markdown('<div class="fm-label">Error (raw)</div>', unsafe_allow_html=True)
            st.code(run.error[:3000], language="text", wrap_lines=True)
        for t in run.trace:
            st.code(json.dumps(t, ensure_ascii=False, indent=1, default=str)[:1500], language="json",
                    wrap_lines=True)


def yes_no(flag: bool, bad_when_yes: bool) -> str:
    cls = ("bad" if flag else "ok") if bad_when_yes else ""
    return f'<span class="fm-pill {cls}">{"Yes" if flag else "No"}</span>'


with tab_sec:
    if not runs:
        callout("info", "No AI call has run for this image yet.")
    for name, run in runs.items():
        heading("shield-check", name)
        if run.injection:
            inj = run.injection
            st.markdown('<div class="fm-label">Image pre-screening</div>'
                        '<div class="fm-card">'
                        f'<div class="fm-row"><span>Text found in the image</span>{yes_no(inj.has_text, False)}</div>'
                        f'<div class="fm-row"><span>Instruction aimed at the AI</span>'
                        f'{yes_no(inj.addressed_to_ai, True)}</div></div>', unsafe_allow_html=True)
            if inj.text:
                st.markdown('<div class="fm-label">Detected text</div>'
                            f'<div class="fm-quote">{html.escape(inj.text[:300])}</div>', unsafe_allow_html=True)
            if inj.explanation:
                st.caption(inj.explanation)
        elif precheck is False or not run.ok:
            st.caption("Image pre-screening did not run for this call.")
        for w in run.warnings:
            callout("warning", w)
        if run.error:
            show_error(run.error)
        elif not run.warnings and not (run.injection and run.injection.addressed_to_ai):
            callout("success", "No security warnings.")
