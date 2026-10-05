"""Blind Voice Bake-off: listeners rate vendor TTS voices 1-5 without knowing which system made them.

Each round is one script read by every vendor that produced it, split by voice gender. Voices are
shown as letters in an order fixed per listener, so coming back shows the same letters. The
clip -> system key never ships with the app and never reaches the browser: store.py reads it
server-side from the private "key" tab of the ratings sheet, only to label saved rows.

    streamlit run ratings_app.py
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

import common as C
import store

TITLE = "Blind Voice Bake-off"
SCALE = ["Bad", "Poor", "Fair", "Good", "Excellent"]
LETTERS = "ABCDEFGHIJKL"
S = C.S


# --------------------------------------------------------------------------- setup
@st.cache_resource(show_spinner=False)
def get_store():
    return store.open_store()


@st.cache_data(ttl=900, show_spinner=False)
def clip_key() -> dict:
    return get_store().key()


def init_state() -> None:
    S.setdefault("view", "intro")
    S.setdefault("name", "")
    S.setdefault("lid", "")
    S.setdefault("langs", {"english": "fluent"})
    S.setdefault("status", {})   # round id -> "rated" | "skipped"
    S.setdefault("saved", {})    # round id -> clip id -> {criterion: score, "note": text}
    S.setdefault("queue", [])
    S.setdefault("current", None)
    S.setdefault("scroll", 0)


def order_for(rid: str) -> list[str]:
    return C.seeded([c["id"] for c in C.BY_ID[rid]["clips"]], f"{S.lid}|{rid}")


def build_queue() -> None:
    S.queue = [rid for g, _, _ in C.GROUPS if g in S.langs
               for rid in C.seeded([r["id"] for r in C.ROUNDS if r["group"] == g], f"{S.lid}|{g}")]


def done_count() -> int:
    return sum(1 for rid in S.queue if rid in S.status)


def next_open(after: str | None = None) -> str | None:
    i = S.queue.index(after) if after in S.queue else -1
    for rid in S.queue[i + 1:] + S.queue[:i + 1]:
        if rid not in S.status:
            return rid
    return None


def go(view: str, rid: str | None = None) -> None:
    S.view = view
    if rid:
        S.current = rid
    S.pop("round_error", None)
    S.scroll += 1


def restore(rows: list[dict]) -> None:
    """Rebuild progress from this listener's saved rows."""
    status, saved = {}, {}
    for row in rows:
        rid, cid = row.get("round_id"), row.get("clip_id")
        if rid not in C.BY_ID:
            continue
        status[rid] = "skipped" if row.get("skipped") == "yes" else "rated"
        entry = saved.setdefault(rid, {}).setdefault(cid, {})
        for crit, column in store.SCORE_COLUMNS.items():
            value = str(row.get(column, "")).strip()
            if value.isdigit():
                entry[crit] = int(value)
        if row.get(store.NOTES):
            entry["note"] = row[store.NOTES]
    S.status, S.saved = status, saved


# --------------------------------------------------------------------------- actions
def start() -> None:
    name = C.clean_name(S.get("name_input", ""))
    langs = C.chosen_levels()
    if not name:
        S.intro_error = "Type your name so we can tell listeners apart."
        return
    if not langs:
        S.intro_error = "Choose at least one language you can judge."
        return
    S.pop("intro_error", None)
    lid = C.listener_id(name)
    if lid != S.lid:
        S.status, S.saved = {}, {}
        try:
            restore(get_store().load(lid))
        except Exception as exc:  # a failed read must not block a new listener
            S.store_error = f"Couldn't load earlier ratings: {exc}"
    S.name, S.lid, S.langs = name, lid, langs
    build_queue()
    nxt = next_open()
    go("round", nxt) if nxt else go("done")


def submit(rid: str, skip: bool) -> None:
    order = order_for(rid)
    if not skip:
        missing = []
        for i, cid in enumerate(order):
            gaps = [label for crit, label, _ in C.CRITERIA if S.get(f"{rid}|{cid}|{crit}") is None]
            if gaps:
                missing.append(f"{LETTERS[i]} ({'all four' if len(gaps) == 4 else ', '.join(gaps)})")
        if missing:
            S.round_error = "Still to rate: voice " + "; ".join(missing) + "."
            return

    r, key = C.BY_ID[rid], clip_key()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    rows, saved = [], {}
    for i, cid in enumerate(order):
        known = key.get(cid, {})
        row = {
            "saved_at": now, "listener_name": S.name, "listener_id": S.lid,
            "language": C.GROUP_NAME[r["group"]], "level": C.LEVELS[S.langs.get(r["group"], "fluent")],
            "round_id": rid, "round": r["title"], "voice_gender": r["gender"],
            "voices_in_round": len(order), "letter": LETTERS[i], "clip_id": cid,
            "system": known.get("system", ""), "voice": known.get("voice", ""),
            "skipped": "yes" if skip else "", "row_key": f"{S.lid}|{cid}",
        }
        entry = {}
        for crit, _, _ in C.CRITERIA:
            score = None if skip else S.get(f"{rid}|{cid}|{crit}")
            row[store.SCORE_COLUMNS[crit]] = score if score is not None else ""
            if score is not None:
                entry[crit] = score
        note = "" if skip else (S.get(f"{rid}|{cid}|note") or "").strip()
        row[store.NOTES] = note
        if note:
            entry["note"] = note
        rows.append(row)
        saved[cid] = entry
    try:
        get_store().upsert(rows)
    except Exception as exc:
        S.round_error = f"Not saved. Check your connection and press Save again. ({exc})"
        return
    S.status[rid] = "skipped" if skip else "rated"
    S.saved[rid] = saved
    nxt = next_open(rid)
    go("round", nxt) if nxt else go("done")


# --------------------------------------------------------------------------- views
def legend() -> str:
    return '<div class="legend">' + "".join(f"<span><b>{i + 1}</b>{w}</span>" for i, w in enumerate(SCALE)) + "</div>"


def top_bar() -> None:
    C.top_bar(TITLE, f"{S.name} · {done_count()} of {len(S.queue)} rounds saved", done_count(), len(S.queue),
              go, "All rounds")


def view_intro() -> None:
    returning = bool(S.status)
    C.hero("Listening panel", "Welcome back." if returning else "Listen blind. Rate every voice.",
           "Several text-to-speech systems read the same lines in African languages and accents. Their names "
           "are hidden behind letters, and the order is shuffled for every listener. In each round, play every "
           "voice and rate it from 1 to 5.")
    C.steps("Enter your name and languages", "Play every voice in a round", "Rate each one 1 to 5, add notes")
    C.section("How to rate")
    C.guide([(label, help_) for _, label, help_ in C.CRITERIA], legend())
    C.section("About you")
    C.name_input()
    C.section("Languages you can judge")
    chosen = C.language_picker(lambda g: f"{sum(1 for r in C.ROUNDS if r['group'] == g)} rounds")
    voices = sum(len(r["clips"]) for r in C.ROUNDS if r["group"] in chosen)
    rounds = sum(1 for r in C.ROUNDS if r["group"] in chosen)
    if S.get("intro_error"):
        st.error(S.intro_error)
    c1, c2 = st.columns([1.4, 3], vertical_alignment="center")
    c1.button("Continue listening" if returning else "Start listening", type="primary", on_click=start,
              width="stretch")
    c2.caption(f"{rounds} rounds, {voices} voices, about {max(5, round(voices * 0.6))} minutes. "
               "Ratings save after every round, so you can stop any time." if rounds
               else "Choose at least one language.")
    C.store_notice(get_store())


def view_round() -> None:
    top_bar()
    rid = S.current
    r = C.BY_ID[rid]
    order = order_for(rid)
    pos = S.queue.index(rid) + 1 if rid in S.queue else 0
    C.script_block(r, f"Round {pos} of {len(S.queue)} · {C.GROUP_NAME[r['group']]}",
                   [("Voices", "Female" if r["gender"] == "female" else "Male"), ("Count", str(len(order))),
                    ("Style", r["style"])])
    st.markdown(legend(), unsafe_allow_html=True)

    saved = S.saved.get(rid, {})
    for cid in order:  # prefill from earlier saves; widget state is dropped once a round is left
        for crit, _, _ in C.CRITERIA:
            if f"{rid}|{cid}|{crit}" not in S and crit in saved.get(cid, {}):
                S[f"{rid}|{cid}|{crit}"] = saved[cid][crit]
        if f"{rid}|{cid}|note" not in S and saved.get(cid, {}).get("note"):
            S[f"{rid}|{cid}|note"] = saved[cid]["note"]

    with st.form(f"form_{rid}", border=False):
        for i, cid in enumerate(order):
            letter = LETTERS[i]
            with st.container(key=f"voice_{i}"):
                C.voice_header(letter)
                st.audio(C.audio_path(cid), format="audio/mpeg")
                cols = st.columns(2)
                for j, (crit, label, help_) in enumerate(C.CRITERIA):
                    cols[j % 2].radio(label, [1, 2, 3, 4, 5], index=None, horizontal=True,
                                      key=f"{rid}|{cid}|{crit}", help=help_)
                st.text_area("Notes / Comments", key=f"{rid}|{cid}|note", height=80,
                             placeholder=f"Optional: what stood out about voice {letter}? "
                                         "Wrong tones, mispronounced names, odd pauses, glitches…")
        if S.get("round_error"):
            st.error(S.round_error)
        c1, c2 = st.columns([2.2, 1])
        c1.form_submit_button("Save and next", type="primary", on_click=submit, args=(rid, False), width="stretch")
        c2.form_submit_button("Skip round", on_click=submit, args=(rid, True), width="stretch")
    C.store_notice(get_store())


def view_list() -> None:
    top_bar()
    st.markdown('<h2 class="round-title" style="margin-top:0.8rem">Your rounds</h2>', unsafe_allow_html=True)
    st.caption(f"{done_count()} of {len(S.queue)} rounds saved. Open any round to listen again or change your ratings.")
    nxt = next_open()
    if nxt:
        st.button("Continue with the next round", type="primary", on_click=go, args=("round", nxt))
    for g, label, _ in C.GROUPS:
        ids = [rid for rid in S.queue if C.BY_ID[rid]["group"] == g]
        if not ids:
            continue
        C.section(f"{label} · {'native' if S.langs.get(g) == 'native' else 'speaker'}")
        for rid in ids:
            r, state = C.BY_ID[rid], S.status.get(rid)
            c1, c2, c3 = st.columns([4, 1.2, 1.2], vertical_alignment="center")
            c1.markdown(f'<div class="round-row-name">{C.esc(r["title"])}<small>'
                        f'{"Female" if r["gender"] == "female" else "Male"} voices · {len(r["clips"])} voices</small></div>',
                        unsafe_allow_html=True)
            c2.markdown(C.pill(state, "Rated"), unsafe_allow_html=True)
            c3.button("Change" if state else "Open", key=f"open_{rid}", on_click=go, args=("round", rid),
                      width="stretch")


def view_done() -> None:
    top_bar()
    rated = sum(1 for rid in S.queue if S.status.get(rid) == "rated")
    skipped = sum(1 for rid in S.queue if S.status.get(rid) == "skipped")
    C.hero("All done", "Thank you. Every round is saved.",
           f"You rated {rated} round{'s' if rated != 1 else ''}"
           f"{f' and skipped {skipped}' if skipped else ''}. You can go back and change any rating.",
           style="margin-top:1rem")
    c1, c2, _ = st.columns([1.4, 1.6, 2])
    c1.button("Review your ratings", on_click=go, args=("list",), width="stretch")
    c2.button("Add another language", on_click=go, args=("intro",), width="stretch")


def main() -> None:
    C.page_setup(TITLE)
    init_state()
    try:
        get_store()
    except Exception as exc:
        st.error(f"The ratings sheet can't be opened, so nothing would be saved. Tell the organiser. ({exc})")
        st.stop()
    if S.view != "intro" and not S.queue:
        S.view = "intro"
    {"intro": view_intro, "round": view_round, "list": view_list, "done": view_done}[S.view]()
    C.scroll_to_top()


main()
