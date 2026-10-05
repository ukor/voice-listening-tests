"""Voice Pairs: Mansa against each other system, two voices at a time.

Each trial is one script read by a Mansa voice and by one other system's voice from the same
round (same language, variant and voice gender) and, in call-centre English, the same accent. Listeners hear Voice A and Voice B and pick the
better one on naturalness, intelligibility, pronunciation and overall, and can say why (optional).

Blindness: pairs are built here on the server from the private clip key, so the browser only
ever gets two anonymous audio files. Which side Mansa is on is randomised per listener and pair,
and trials from different rounds are interleaved so the same voice does not recur back to back.
Pairs with the fewest judgments so far are served first, so coverage stays even when people stop
early.

    streamlit run streamlit_app.py

The language list is read once, when this process starts.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
from collections import Counter
from datetime import datetime, timezone

import streamlit as st

import common as C
import store

MANSA = "Mansa"
TITLE = "Voice Pairs"
CHOICES = ["A", "Same", "B"]
CHOICE_LABEL = {"A": "Voice A", "B": "Voice B", "Same": "About the same"}
QUESTIONS = [
    ("naturalness", "Which sounds more natural?", "More like a real person talking."),
    ("intelligibility", "Which is easier to understand?", "Every word clear without effort."),
    ("pronunciation", "Which pronounces the words better?",
     "Words, tones, names and numbers said correctly for this language or accent."),
    ("overall", "Overall, which is better?", "The one you would rather use."),
]
GROUP_IDS = [g for g, _, _ in C.GROUPS]
S = C.S
esc = html.escape

# The watercolour's rough edge; every view draws it once, next to the brand.
DEFS = ('<svg class="vp-defs" width="0" height="0" aria-hidden="true"><filter id="wc-rough" x="-10%" y="-10%" '
        'width="120%" height="120%"><feTurbulence type="fractalNoise" baseFrequency="0.007 0.011" numOctaves="3" '
        'seed="7" result="n"></feTurbulence><feDisplacementMap in="SourceGraphic" in2="n" scale="140" '
        'xChannelSelector="R" yChannelSelector="G"></feDisplacementMap><feGaussianBlur stdDeviation="1.5">'
        '</feGaussianBlur></filter></svg>')
LOGO = ('<span class="vp-logo" aria-hidden="true"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 4H4v16h3M17 4h3v16h-3M10 9v6M14 7v10"></path></svg></span>')
BRAND = (f'{DEFS}<a class="vp-brand" href="#top">{LOGO}<span class="vp-name"><b>Voice Pairs</b>'
         '<small>by African Languages Lab</small></span></a>')
RULE = '<div class="vp-rule" aria-hidden="true"></div>'
WASH = '<div class="wc-wash"></div><div class="wc-grain"></div>'
FOOTER = ('<div class="vp-footer"><span>A listening panel by the African Languages Lab</span>'
          '<span>We keep only your name and your answers.</span></div>')
CHECK = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
         'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle>'
         '<path d="M8 12l3 3 5-6"></path></svg>')


# --------------------------------------------------------------------------- data
LOCAL_CSV = C.HERE / "data" / "pairwise_local.csv"  # where answers go when no sheet is configured


@st.cache_resource(show_spinner=False)
def get_store():
    s = store.open_store(store.PAIRS_SHEET, store.PAIR_COLUMNS, "pairwise_local.csv")
    if isinstance(s, store.DriveSheetStore) and LOCAL_CSV.exists():
        # Answers saved while the sheet secrets were missing: copy them in (upsert by row_key, so
        # repeating this is harmless), then keep the file under a new name rather than delete it.
        with open(LOCAL_CSV, encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("row_key")]
        if rows:
            s.upsert(rows)
        LOCAL_CSV.rename(LOCAL_CSV.with_name(f"pairwise_local.migrated-{int(datetime.now().timestamp())}.csv"))
    return s


def export_token() -> str:
    """Owner-only link token, derived from the private answer key so the public repo can't reveal it."""
    key = clip_key()
    blob = json.dumps(sorted([cid, v["system"], v["voice"]] for cid, v in key.items()))
    return hashlib.sha256(("export|" + blob).encode()).hexdigest()[:24]


def owner_export() -> bool:
    """?export=<token>: show where answers are going and any answers held in the local file."""
    token = st.query_params.get("export")
    if not token or not clip_key() or token != export_token():
        return False
    s = get_store()
    st.markdown(f"**Answer store:** {s.label}" + (f" `…{s.file_id[-6:]}`" if hasattr(s, "file_id") else ""))
    files = sorted(LOCAL_CSV.parent.glob("pairwise_local*.csv"))
    if not files:
        st.markdown("No local answer files on this server.")
    for path in files:
        text = path.read_text(encoding="utf-8")
        st.markdown(f"**{path.name}**: {max(text.count(chr(10)) - 1, 0)} rows")
        st.code(text, language=None)
        st.download_button(f"Download {path.name}", text, file_name=path.name, mime="text/csv", key=path.name)
    return True


@st.cache_data(ttl=900, show_spinner=False)
def clip_key() -> dict:
    return get_store().key()


@st.cache_data(ttl=900, show_spinner=False)
def all_pairs() -> dict:
    """Every Mansa clip against every other system's clip in the same round and accent. Only the
    call-centre round mixes accents, so its clips carry one; Nigerian meets Nigerian, and so on."""
    key, pairs = clip_key(), {}
    for r in C.ROUNDS:
        accent = {c["id"]: c.get("accent") for c in r["clips"] if c["id"] in key}
        mansa = [c for c in accent if key[c]["system"] == MANSA]
        for m in mansa:
            for o in accent:
                if key[o]["system"] != MANSA and accent[o] == accent[m]:
                    pid = f"{m}~{o}"
                    pairs[pid] = {"id": pid, "round": r["id"], "mansa": m, "other": o, "accent": accent[m]}
    return pairs


def pair_title(p: dict) -> str:
    title = C.BY_ID[p["round"]]["title"]
    return f"{title}, {C.ACCENT_NAME[p['accent']]} accent" if p.get("accent") else title


def sides(p: dict) -> tuple[str, str]:
    """(clip on A, clip on B), fixed per listener and pair so a returning listener sees the same."""
    mansa_first = C.rank(f"{S.lid}|{p['id']}|side") % 2 == 0
    return (p["mansa"], p["other"]) if mansa_first else (p["other"], p["mansa"])


def group_of(pid: str) -> str:
    return C.BY_ID[all_pairs()[pid]["round"]]["group"]


def pairs_in(group: str) -> int:
    return sum(1 for p in all_pairs().values() if C.BY_ID[p["round"]]["group"] == group)


def init_state() -> None:
    S.setdefault("view", "intro")
    S.setdefault("name", "")
    S.setdefault("lid", "")
    S.setdefault("langs", {})
    S.setdefault("status", {})   # pair id -> "rated" | "skipped"
    S.setdefault("saved", {})    # pair id -> {criterion: "A"|"B"|"Same", "note": text}
    S.setdefault("queue", [])
    S.setdefault("current", None)
    S.setdefault("scroll", 0)


def done_count() -> int:
    return sum(1 for pid in S.queue if pid in S.status)


def next_open(after: str | None = None) -> str | None:
    i = S.queue.index(after) if after in S.queue else -1
    for pid in S.queue[i + 1:] + S.queue[:i + 1]:
        if pid not in S.status:
            return pid
    return None


def go(view: str, pid: str | None = None) -> None:
    S.view = view
    if pid:
        S.current = pid
    S.pop("pair_error", None)
    S.scroll += 1


def jump(group: str) -> None:
    """Switch language: the next unanswered pair in it, else its first pair."""
    ids = [pid for pid in S.queue if group_of(pid) == group]
    nxt = next((pid for pid in ids if pid not in S.status), ids[0] if ids else None)
    if nxt:
        go("pair", nxt)


def build_queue(counts: Counter) -> None:
    """Least-judged pairs first (random among equals), then spread so rounds don't repeat back to back."""
    cand = [p for p in all_pairs().values() if C.BY_ID[p["round"]]["group"] in S.langs]
    cand.sort(key=lambda p: (counts.get(p["id"], 0), C.rank(f"{S.lid}|{p['id']}")))
    out = []
    while cand:
        prev = out[-1]["round"] if out else None
        i = next((k for k, p in enumerate(cand[:12]) if p["round"] != prev), 0)
        out.append(cand.pop(i))
    S.queue = [p["id"] for p in out]


# --------------------------------------------------------------------------- actions
def start() -> None:
    name = C.clean_name(S.get("name_input", ""))
    picked = [g for g in GROUP_IDS if g in (S.get("langs_pick") or [])]
    native = set(S.get("native_pick") or [])
    langs = {g: ("native" if g in native else "fluent") for g in picked}
    if not name:
        S.intro_error = "Type your name so we can tell listeners apart."
        return
    if not langs:
        S.intro_error = "Choose at least one language you speak."
        return
    if not all_pairs():
        S.intro_error = "The test isn't set up yet (no answer key), so there are no pairs to play. Tell the organiser."
        return
    S.pop("intro_error", None)
    lid = C.listener_id(name)
    counts: Counter = Counter()
    try:
        rows = get_store().rows()
        counts = Counter(r["pair_id"] for r in rows if r.get("skipped") != "yes")
        if lid != S.lid:
            S.status, S.saved = {}, {}
            for r in rows:
                if r.get("listener_id") != lid or r.get("pair_id") not in all_pairs():
                    continue
                S.status[r["pair_id"]] = "skipped" if r.get("skipped") == "yes" else "rated"
                S.saved[r["pair_id"]] = {c: r.get(col) for c, col in store.PAIR_CHOICE_COLUMNS.items()
                                         if r.get(col) in CHOICES}
                if r.get(store.PAIR_NOTES):
                    S.saved[r["pair_id"]]["note"] = r[store.PAIR_NOTES]
    except Exception as exc:  # a failed read must not block a new listener
        S.store_error = f"Couldn't load earlier answers: {exc}"
    S.name, S.lid, S.langs = name, lid, langs
    build_queue(counts)
    nxt = next_open()
    if nxt:
        go("pair", nxt)
    else:
        go("done")


def submit(pid: str, skip: bool) -> None:
    p = all_pairs()[pid]
    if not skip:
        missing = [q for crit, q, _ in QUESTIONS if S.get(f"{pid}|{crit}") is None]
        if missing:
            S.pair_error = "Still to answer: " + "; ".join(missing)
            return
    a, b = sides(p)
    mansa_side = "A" if a == p["mansa"] else "B"
    key, r = clip_key(), C.BY_ID[p["round"]]
    row = {
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "listener_name": S.name, "listener_id": S.lid,
        "language": C.GROUP_NAME[r["group"]], "level": C.LEVELS[S.langs.get(r["group"], "fluent")],
        "round_id": p["round"], "round": pair_title(p), "voice_gender": r["gender"],
        "pair_id": pid, "voice_a_clip": a, "voice_b_clip": b, "mansa_is": mansa_side,
        "competitor": key[p["other"]]["system"], "competitor_voice": key[p["other"]]["voice"],
        "mansa_voice": key[p["mansa"]]["voice"],
        "skipped": "yes" if skip else "", "row_key": f"{S.lid}|{pid}",
    }
    saved = {}
    for crit, _, _ in QUESTIONS:
        choice = None if skip else S.get(f"{pid}|{crit}")
        row[store.PAIR_CHOICE_COLUMNS[crit]] = choice or ""
        row[store.PAIR_SCORE_COLUMNS[crit]] = ("" if choice is None else
                                               0.5 if choice == "Same" else 1 if choice == mansa_side else 0)
        if choice:
            saved[crit] = choice
    note = "" if skip else (S.get(f"{pid}|note") or "").strip()
    row[store.PAIR_NOTES] = note
    if note:
        saved["note"] = note
    try:
        get_store().upsert([row])
    except Exception as exc:
        S.pair_error = f"Not saved. Check your connection and press Save again. ({exc})"
        return
    S.status[pid] = "skipped" if skip else "rated"
    S.saved[pid] = saved
    nxt = next_open(pid)
    if nxt:
        go("pair", nxt)
    else:
        go("done")


# --------------------------------------------------------------------------- pieces
def md(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def illustration(mini: bool = False) -> str:
    heights = (12, 26, 40, 20, 32) if mini else (20, 44, 70, 34, 56, 24)
    bars = "".join(f'<i style="height:{h}px"></i>' for h in heights)
    cap = "" if mini else '<span class="cap">Two voices. One line. You choose.</span>'
    return (f'<div class="vp-illus wc{" vp-mini" if mini else ""}" aria-hidden="true">{WASH}<div class="wc-fleck"></div>'
            f'<div class="vp-illus-in"><div class="pair"><div class="ab">A</div><div class="bars">{bars}</div>'
            f'<div class="ab">B</div></div>{cap}</div></div>')


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def me_html() -> str:
    return f'<div class="vp-me"><span class="av">{esc(initials(S.name))}</span><span class="nm">{esc(S.name)}</span></div>'


def app_header(pid: str | None = None) -> None:
    """Brand, language switcher with progress, then Your pairs and the listener."""
    with st.container(key="topbar"):
        c1, c2, c3 = st.columns([1.1, 2.4, 1.5], vertical_alignment="center")
    with c1.container(key="tb_brand"):
        md(BRAND)
    with c2.container(key="tb_nav"):
        if pid:
            g = group_of(pid)
            ids = [x for x in S.queue if group_of(x) == g]
            answered = sum(1 for x in ids if x in S.status)
            s1, s2 = st.columns([1, 2.2], vertical_alignment="center")
            with s1.popover(C.GROUP_NAME[g]):
                md('<div class="vp-section" style="margin:0 0 .5rem">Your languages</div>')
                for lg in GROUP_IDS:
                    if lg not in S.langs:
                        continue
                    lids = [x for x in S.queue if group_of(x) == lg]
                    done = sum(1 for x in lids if x in S.status)
                    st.button(f"{C.GROUP_NAME[lg]} · {done} of {len(lids)} answered", key=f"sw_{lg}",
                              on_click=jump, args=(lg,), width="stretch",
                              icon=":material/check:" if lg == g else None)
                st.button("Add or change languages", key="sw_change", on_click=go, args=("intro",), width="stretch")
            pct = round(100 * answered / len(ids)) if ids else 0
            s2.markdown(f'<div class="vp-progress"><span>Pair {ids.index(pid) + 1} of {len(ids)}</span>'
                        f'<span class="track"><i style="width:{pct}%"></i></span></div>', unsafe_allow_html=True)
    with c3.container(key="tb_me"):
        b1, b2 = st.columns([1, 1.3], vertical_alignment="center")
        if S.view == "list":
            nxt = S.current if S.current in S.queue else next_open()
            b1.button("Back to listening", on_click=go, args=("pair", nxt), width="stretch", disabled=not nxt)
        else:
            b1.button("Your pairs", on_click=go, args=("list",), width="stretch")
        b2.markdown(me_html(), unsafe_allow_html=True)
    md(RULE)


# --------------------------------------------------------------------------- views
def view_intro() -> None:
    returning = bool(S.status)
    md(f'<div class="vp-header">{BRAND}<a class="vp-link" href="#how">How it works</a></div>')
    left, right = st.columns([1.12, 1], gap="large", vertical_alignment="center")
    with left:
        md(illustration(mini=True)
           + f'<h1 class="vp-h1">{"Welcome back." if returning else "Help African voices sound like home."}</h1>'
           + '<p class="vp-lede">Listen to two AI voices read the same line, then tell us which one sounds right.</p>')
        with st.container(key="start_card"):
            S.setdefault("name_input", S.name)
            st.text_input("Your name", key="name_input", placeholder="e.g. Amina Bello")
            S.setdefault("langs_pick", [g for g in GROUP_IDS if g in S.langs])
            st.multiselect("Languages you speak", [g for g in GROUP_IDS if pairs_in(g)], format_func=C.GROUP_NAME.get, key="langs_pick",
                           placeholder="Choose languages")
            chosen = [g for g in GROUP_IDS if g in (S.langs_pick or [])]
            if chosen:  # keep the native picks valid for the languages still chosen
                earlier = S.get("native_pick", [g for g in chosen if S.langs.get(g) == "native"])
                S.native_pick = [g for g in earlier if g in chosen]
                st.pills("Native speaker of", chosen, format_func=C.GROUP_NAME.get, selection_mode="multi",
                         key="native_pick", help="Tap each language you grew up speaking.")
            if S.get("intro_error"):
                st.error(S.intro_error)
            st.button("Continue listening  →" if returning else "Start listening  →", type="primary",
                      on_click=start, width="stretch", key="start_btn")
            n = sum(pairs_in(g) for g in chosen)
            md(f'<p class="vp-note">{n} pairs, about {max(3, round(n * 0.75))} minutes. '
               'Your answers save as you go, so you can stop any time.</p>' if n else
               '<p class="vp-note">About 45 seconds a pair. Stop any time.</p>')
    with right:
        md(illustration())
    md(RULE + '<div id="how" class="vp-steps">'
       '<div class="vp-step"><span class="n">1</span><div><b>Choose your languages</b><span>Only the ones you speak well.</span></div></div>'
       '<div class="vp-step"><span class="n">2</span><div><b>Listen to two voices</b><span>Their names stay hidden.</span></div></div>'
       '<div class="vp-step"><span class="n">3</span><div><b>Pick the better one</b><span>Add why, if you like.</span></div></div>'
       '</div>' + FOOTER)
    C.store_notice(get_store())


def view_pair() -> None:
    pid = S.current
    app_header(pid)
    p = all_pairs()[pid]
    r = C.BY_ID[p["round"]]
    a, b = sides(p)
    gender = "Female" if r["gender"] == "female" else "Male"
    note = f'<em>{esc(r["note"])}</em>' if r.get("note") else ""
    md(f'<div class="vp-crumb">{esc(pair_title(p))} · {gender} voices</div>'
       '<h2 class="vp-h2">Which voice sounds more like home?</h2>'
       f'<div class="vp-script"><div class="vp-script-art wc" aria-hidden="true">{WASH}</div><small>BOTH VOICES READ</small><p lang="{C.text_lang(r)}">{esc(r["text"])}</p>{note}</div>')

    cols = st.columns(2, gap="medium")
    for col, letter, cid in ((cols[0], "A", a), (cols[1], "B", b)):
        with col.container(key=f"voice_{letter}"):
            md(f'<div class="vp-voice"><span class="ab">{letter}</span>'
               f'<div><b>Voice {letter}</b><span>Play it, then compare</span></div></div>')
            st.audio(C.audio_path(cid), format="audio/mpeg")

    saved = S.saved.get(pid, {})
    for crit, _, _ in QUESTIONS:  # prefill a revisited pair; widget state is dropped once a pair is left
        if f"{pid}|{crit}" not in S and crit in saved:
            S[f"{pid}|{crit}"] = saved[crit]
    if f"{pid}|note" not in S and saved.get("note"):
        S[f"{pid}|note"] = saved["note"]

    with st.form(f"form_{pid}", border=False):
        with st.container(key="judge"):
            md('<div class="vp-judge-head"><b>Which voice is better?</b>'
               '<span>Choose Voice A, Voice B or About the same for each.</span></div>')
            for crit, question, help_ in QUESTIONS:
                qc, oc = st.columns([1, 1.15], vertical_alignment="center")
                qc.markdown(f'<div class="vp-q"><b>{esc(question)}</b><span>{esc(help_)}</span></div>',
                            unsafe_allow_html=True)
                oc.radio(question, CHOICES, format_func=CHOICE_LABEL.get, index=None, horizontal=True,
                         key=f"{pid}|{crit}", label_visibility="collapsed", width="stretch")
            md('<div class="vp-why"><b>Why? <em>Optional</em></b><span>What made the better voice better, or what went wrong in the other?</span></div>')
            st.text_area("Why?", key=f"{pid}|note", height=100, label_visibility="collapsed",
                         placeholder="Wrong tones, mispronounced names, robotic rhythm, glitches…")
        if S.get("pair_error"):
            st.error(S.pair_error)
        c1, c2, c3 = st.columns([1.5, 0.9, 1.3], vertical_alignment="center")
        c1.markdown(f'<div class="vp-saved">{CHECK}Your answers save automatically</div>', unsafe_allow_html=True)
        with c2.container(key="skip_wrap"):
            st.form_submit_button("Skip this pair", on_click=submit, args=(pid, True), width="stretch")
        c3.form_submit_button("Save and continue  →", type="primary", on_click=submit, args=(pid, False),
                              width="stretch")
    md(FOOTER)
    C.store_notice(get_store())


def view_list() -> None:
    app_header()
    md(f'<h2 class="vp-h2" style="margin-top:1rem !important">Your pairs</h2>'
       f'<p class="vp-lede" style="font-size:17px">{done_count()} of {len(S.queue)} pairs answered. '
       'Open any pair to listen again or change your answer.</p>')
    for g in GROUP_IDS:
        ids = [pid for pid in S.queue if group_of(pid) == g]
        if not ids:
            continue
        md(f'<div class="vp-section">{esc(C.GROUP_NAME[g])} · {"native" if S.langs.get(g) == "native" else "speaker"}</div>')
        for n, pid in enumerate(ids, 1):
            p = all_pairs()[pid]
            r = C.BY_ID[p["round"]]
            state = S.status.get(pid)
            c1, c2, c3 = st.columns([4, 1.2, 1.2], vertical_alignment="center")
            c1.markdown(f'<div class="vp-row">Pair {n} · {esc(pair_title(p))}<small>'
                        f'{"Female" if r["gender"] == "female" else "Male"} voices</small></div>',
                        unsafe_allow_html=True)
            c2.markdown(C.pill(state, "Answered"), unsafe_allow_html=True)
            c3.button("Change" if state else "Open", key=f"open_{pid}", on_click=go, args=("pair", pid),
                      width="stretch")
    md(FOOTER)


def view_done() -> None:
    app_header()
    answered = sum(1 for pid in S.queue if S.status.get(pid) == "rated")
    skipped = sum(1 for pid in S.queue if S.status.get(pid) == "skipped")
    md('<div class="vp-done"><h2>Thank you. Every pair is saved.</h2>'
       f'<p>You answered {answered} pair{"s" if answered != 1 else ""}'
       f'{f" and skipped {skipped}" if skipped else ""}. You can go back and change any answer, '
       'or add another language.</p></div>')
    c1, c2, _ = st.columns([1.3, 1.5, 2])
    c1.button("Review your answers", on_click=go, args=("list",), width="stretch")
    c2.button("Add another language", on_click=go, args=("intro",), width="stretch")
    md(FOOTER)


def main() -> None:
    C.page_setup(TITLE)
    init_state()
    try:
        get_store()
    except Exception as exc:
        st.error(f"The answer sheet can't be opened, so nothing would be saved. Tell the organiser. ({exc})")
        st.stop()
    if isinstance(get_store(), store.LocalStore) and store.secret(store.PAIRS_SHEET) and store.secret("GOOGLE_SERVICE_ACCOUNT"):
        get_store.clear()  # the sheet secrets were added after the local store was cached: switch now
    if owner_export():
        st.stop()
    if isinstance(get_store(), store.LocalStore) and not os.environ.get("BAKEOFF_ALLOW_LOCAL"):
        # Without the sheet secrets, answers would land in a server file that a restart wipes.
        st.error("The answer sheet isn't connected yet, so answers can't be saved. Please tell the organiser.")
        st.stop()
    if S.view != "intro" and not S.queue:
        S.view = "intro"
    {"intro": view_intro, "pair": view_pair, "list": view_list, "done": view_done}[S.view]()
    C.scroll_to_top()


main()
