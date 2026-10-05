"""Pieces shared by the two listening tests: pairwise Mansa-vs-other (streamlit_app.py, the one
deployed) and 1-5 ratings (ratings_app.py). Same rounds, audio, languages, criteria and look."""
from __future__ import annotations

import hashlib
import html
import json
import random
import re
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
STYLESHEET = HERE / "assets" / "styles.css"


def _load_rounds() -> list:
    """The dataset's rounds.json (every language), else the copy in data/ (local development)."""
    import store
    try:
        path = store.hf_file("rounds.json")
    except Exception:  # dataset unreachable: use the bundled copy
        path = None
    return json.loads(Path(path or HERE / "data" / "rounds.json").read_text(encoding="utf-8"))


ROUNDS = _load_rounds()
BY_ID = {r["id"]: r for r in ROUNDS}
ENGLISH_NOTE = "Nigerian, Ghanaian and East African accents, plus call-centre lines"
OLD_NAMES = {"english": "English", "twi": "Twi (Akan)"}
GROUPS = []  # (id, name, note) in the order the build wrote them: English first, then A-Z
for _r in ROUNDS:
    if _r["group"] not in {g for g, _, _ in GROUPS}:
        GROUPS.append((_r["group"], _r.get("group_name") or OLD_NAMES.get(_r["group"], _r["group"].title()),
                       ENGLISH_NOTE if _r["group"] == "english" else ""))
# BCP-47 tags for the script's lang attribute (screen readers, font shaping)
LANG_TAG = {"english": "en", "afrikaans": "af", "amharic": "am", "arabic": "ar", "bambara": "bm", "bemba": "bem",
            "berber": "ber", "chichewa": "ny", "ewe": "ee", "fon": "fon", "fula": "ff", "hausa": "ha", "igbo": "ig",
            "kanuri": "kr", "kikuyu": "ki", "kinyarwanda": "rw", "krio": "kri", "lingala": "ln", "luganda": "lg",
            "malagasy": "mg", "ndebele": "nd", "oromo": "om", "sepedi": "nso", "sesotho": "st", "shona": "sn",
            "somali": "so", "swahili": "sw", "swati": "ss", "tigrinya": "ti", "tsonga": "ts", "tswana": "tn", "twi": "ak",
            "umbundu": "umb", "venda": "ve", "wolof": "wo", "xhosa": "xh", "yoruba": "yo", "zulu": "zu"}


def text_lang(r: dict) -> str:
    return "en" if r["id"].startswith(("en-", "callcentre")) else LANG_TAG.get(r["group"], "")


def audio_path(cid: str) -> str:
    """A clip's mp3: the local audio/ folder in development, else fetched from the private dataset."""
    import store
    local = AUDIO / f"{cid}.mp3"
    return str(local) if local.exists() else store.hf_file(f"audio/{cid}.mp3")


GROUP_NAME = {g: name for g, name, _ in GROUPS}
ACCENT_NAME = {"nigerian": "Nigerian", "ghanaian": "Ghanaian", "east_african": "East African", "american": "American"}
LEVELS = {"skip": "Skip", "fluent": "I speak it", "native": "Native"}
CRITERIA = [
    ("naturalness", "Naturalness",
     "Does it sound like a real person talking? 1 = clearly robotic, 5 = could be a real person."),
    ("intelligibility", "Intelligibility",
     "Can you understand every word without effort? 1 = hard to follow, 5 = every word is clear."),
    ("pronunciation", "Pronunciation",
     "Are words, tones, names and numbers said correctly for this language or accent? 1 = many errors, 5 = no errors."),
    ("overall", "Overall",
     "How good is this voice overall? 1 = you would not use it, 5 = excellent."),
]
BARS = '<span class="app-hero-bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>'
esc = html.escape
S = st.session_state


@st.cache_data(show_spinner=False)
def _stylesheet(mtime: float) -> str:
    return STYLESHEET.read_text(encoding="utf-8")


def page_setup(title: str) -> None:
    st.set_page_config(page_title=title, page_icon="◈", layout="wide", initial_sidebar_state="collapsed")
    st.markdown(f"<style>{_stylesheet(STYLESHEET.stat().st_mtime)}</style>", unsafe_allow_html=True)


def listener_id(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip()


def rank(seed: str) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16)


def seeded(items: list, seed: str) -> list:
    out = list(items)
    random.Random(rank(seed)).shuffle(out)
    return out


def section(title: str) -> None:
    st.markdown(f'<div class="eval-section-title">{esc(title)}</div>', unsafe_allow_html=True)


def hero(kicker: str, title: str, lede: str, style: str = "") -> None:
    st.markdown(
        f'<div class="app-hero"{f" style={chr(34)}{style}{chr(34)}" if style else ""}>'
        f'<div class="app-hero-mark">{BARS}</div><div>'
        f'<p class="app-kicker">{esc(kicker)}</p><h1>{esc(title)}</h1>'
        f'<p class="app-lede">{esc(lede)}</p></div></div>',
        unsafe_allow_html=True)


def steps(*labels: str) -> None:
    st.markdown('<div class="flow-steps">' + "".join(
        f'<div class="flow-step"><span class="flow-step-num">{i}</span><span>{esc(t)}</span></div>'
        for i, t in enumerate(labels, 1)) + "</div>", unsafe_allow_html=True)


def guide(items: list[tuple[str, str]], legend_html: str = "") -> None:
    st.markdown('<div class="guide">' + "".join(
        f'<div class="guide-item"><b>{esc(t)}</b><span>{esc(h)}</span></div>' for t, h in items)
        + "</div>" + legend_html, unsafe_allow_html=True)


def name_input() -> None:
    S.setdefault("name_input", S.get("name", ""))
    st.text_input("Your name", key="name_input", placeholder="e.g. Amina Bello",
                  help="Use the same name each time you come back to pick up where you left off.")


def language_picker(count_label) -> list[str]:
    """One row per language with Skip / I speak it / Native. Returns the chosen group ids.
    count_label(group) gives the small text under the language name, e.g. '8 rounds'."""
    for g, label, note in GROUPS:
        S.setdefault(f"lvl_{g}", S.get("langs", {}).get(g, "skip"))
        c1, c2 = st.columns([3, 2.4], vertical_alignment="center")
        c1.markdown(f'<div class="lang-name"><b>{esc(label)}</b><small>{esc(note) + " · " if note else ""}'
                    f'{esc(count_label(g))}</small></div>', unsafe_allow_html=True)
        c2.radio(label, list(LEVELS), format_func=LEVELS.get, key=f"lvl_{g}", horizontal=True,
                 label_visibility="collapsed")
    return [g for g, _, _ in GROUPS if S.get(f"lvl_{g}", "skip") != "skip"]


def chosen_levels() -> dict[str, str]:
    return {g: S.get(f"lvl_{g}") for g, _, _ in GROUPS if S.get(f"lvl_{g}", "skip") != "skip"}


def top_bar(title: str, count_text: str, done: int, total: int, go, list_label: str) -> None:
    c1, c2, c3 = st.columns([4, 1.3, 1.3], vertical_alignment="center")
    c1.markdown(
        f'<div class="topline"><span class="topline-mark">{BARS}</span><span class="topline-copy">'
        f'<span class="topline-title">{esc(title)}</span>'
        f'<span class="topline-count">{esc(count_text)}</span></span></div>',
        unsafe_allow_html=True)
    c2.button("Languages", on_click=go, args=("intro",), width="stretch")
    c3.button(list_label, on_click=go, args=("list",), width="stretch")
    st.progress(done / total if total else 0.0)


def script_block(r: dict, position: str, chips: list[tuple[str, str]]) -> None:
    note = f'<span class="eval-sentence-note">{esc(r["note"])}</span>' if r.get("note") else ""
    st.markdown(
        f'<p class="round-eyebrow">{esc(position)}</p>'
        f'<h2 class="round-title">{esc(r["title"])}</h2>'
        '<div class="eval-chips">' + "".join(
            f'<span class="eval-chip"><span class="eval-chip-key">{esc(k)}</span>{esc(v)}</span>' for k, v in chips)
        + "</div>"
        f'<div class="eval-sentence"><span class="eval-sentence-label">Every voice was asked to say</span>'
        f'{esc(r["text"])}{note}</div>',
        unsafe_allow_html=True)


def voice_header(letter: str) -> None:
    st.markdown(
        f'<div class="sample-card-head"><span class="sample-badge">{letter}</span>'
        f'<div class="sample-card-copy"><span class="sample-card-kicker">Voice</span>'
        f'<span class="sample-card-title">Voice {letter}</span></div></div>',
        unsafe_allow_html=True)


def pill(state: str | None, done_label: str) -> str:
    return {"rated": f'<span class="pill pill-done">{esc(done_label)}</span>',
            "skipped": '<span class="pill pill-skip">Skipped</span>'}.get(state, '<span class="pill">To do</span>')


def store_notice(active_store) -> None:
    if S.get("store_error"):
        st.warning(S.pop("store_error"))


def scroll_to_top() -> None:
    """Start each new view at the top; the token changes per navigation so the script re-runs."""
    with st.container(key="scroll_helper"):
        st.iframe(
            f"<script>/* {S.get('scroll', 0)} */ const d = window.parent.document;"
            "for (const s of ['[data-testid=\"stMain\"]', 'section.main', '[data-testid=\"stAppViewContainer\"]'])"
            "{ const el = d.querySelector(s); if (el) el.scrollTo({top: 0}); } window.parent.scrollTo(0, 0);</script>",
            height=1)
