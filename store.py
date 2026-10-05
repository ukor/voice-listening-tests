"""Where answers are kept.

Deployed: one Google Sheet per test in John's Drive (secrets RATINGS_SHEET_ID, PAIRS_SHEET_ID),
written by the service account in GOOGLE_SERVICE_ACCOUNT through the Drive API alone. Each save
reads the sheet as CSV, rewrites this listener's rows and uploads the whole sheet back, which Drive
converts in place. (The Sheets API is switched off in that service account's project; Drive is on.)
One row per listener per item, so a changed answer replaces its row. Streamlit Cloud runs one
process, so a lock is enough to keep two saves from overwriting each other. Locally without those
secrets: a CSV in data/.

The clip -> system key comes from the BAKEOFF_KEY secret (BAKEOFF_KEY_FILE locally). It is used on
the server only, to label rows and build pairs; it never reaches the browser, the repo or a sheet
listeners could open.
"""
from __future__ import annotations

import csv
import io
import json
import os
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- 1-5 ratings (ratings_app.py) -----------------------------------------------------------
SCORE_COLUMNS = {
    "naturalness": "Naturalness (1–5)",
    "intelligibility": "Intelligibility (1–5)",
    "pronunciation": "Pronunciation (1–5)",
    "overall": "Overall (1–5)",
}
NOTES = "Notes / Comments"
COLUMNS = ["saved_at", "listener_name", "listener_id", "language", "level", "round_id", "round",
           "voice_gender", "voices_in_round", "letter", "clip_id", "system", "voice",
           *SCORE_COLUMNS.values(), NOTES, "skipped", "row_key"]
RATINGS_SHEET = "RATINGS_SHEET_ID"

# --- pairwise Mansa vs other (streamlit_app.py) ----------------------------------------------
# What the listener picked, as they saw it: "A", "B" or "Same".
PAIR_CHOICE_COLUMNS = {
    "naturalness": "Naturalness: better voice",
    "intelligibility": "Intelligibility: better voice",
    "pronunciation": "Pronunciation: better voice",
    "overall": "Overall: better voice",
}
# The same answer from Mansa's side: 1 = Mansa preferred, 0.5 = about the same, 0 = the other.
# Averaging a column gives Mansa's win share against whoever is in the competitor column.
PAIR_SCORE_COLUMNS = {
    "naturalness": "Mansa score: Naturalness",
    "intelligibility": "Mansa score: Intelligibility",
    "pronunciation": "Mansa score: Pronunciation",
    "overall": "Mansa score: Overall",
}
PAIR_NOTES = "Why / Notes"
PAIR_COLUMNS = ["saved_at", "listener_name", "listener_id", "language", "level", "round_id", "round",
                "voice_gender", "pair_id", "voice_a_clip", "voice_b_clip", "mansa_is", "competitor",
                "competitor_voice", "mansa_voice", *PAIR_CHOICE_COLUMNS.values(), *PAIR_SCORE_COLUMNS.values(),
                PAIR_NOTES, "skipped", "row_key"]
PAIRS_SHEET = "PAIRS_SHEET_ID"


def secret(name: str):
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:  # no secrets.toml locally
        pass
    return os.getenv(name)


HF_REPO = "all-lab/voice-pairs-audio"  # private dataset: audio/<id>.mp3, rounds.json, key.json


def hf_file(name: str) -> str | None:
    """Local path of a file from the private dataset (downloaded once, then cached), or None."""
    token = secret("HF_TOKEN")
    if not token:
        return None
    from huggingface_hub import hf_hub_download
    return hf_hub_download(HF_REPO, name, repo_type="dataset", token=str(token))


def load_key() -> dict:
    """clip id -> {"system", "voice"}: the dataset's key.json, else the BAKEOFF_KEY secret, else a local file."""
    try:
        path = hf_file("key.json")
    except Exception:  # dataset unreachable: fall back to the secret
        path = None
    if path:
        key = json.loads(Path(path).read_text(encoding="utf-8"))
        return {cid: {"system": v["vendor_name"], "voice": v["voice"]} for cid, v in key.items()}
    raw = secret("BAKEOFF_KEY")
    if raw:
        data = json.loads(raw) if isinstance(raw, str) else {k: raw[k] for k in raw}
        return {cid: {"system": v[0], "voice": v[1]} for cid, v in data.items()}
    path = os.getenv("BAKEOFF_KEY_FILE")
    if path and Path(path).exists():
        key = json.loads(Path(path).read_text(encoding="utf-8"))
        return {cid: {"system": v["vendor_name"], "voice": v["voice"]} for cid, v in key.items()}
    return {}


def account_info(raw) -> dict:
    info = json.loads(raw) if isinstance(raw, str) else {k: raw[k] for k in raw}
    info["private_key"] = info.get("private_key", "").replace("\\n", "\n")
    return info


def open_store(sheet_secret: str = RATINGS_SHEET, columns: list[str] = COLUMNS,
               local_file: str = "ratings_local.csv"):
    file_id, account = secret(sheet_secret), secret("GOOGLE_SERVICE_ACCOUNT")
    if file_id and account:
        return DriveSheetStore(str(file_id), account_info(account), columns)
    return LocalStore(HERE / "data" / local_file, columns)


def as_text(value):
    """Uploaded CSV cells that start with = + - @ run as formulas; a leading ' keeps them text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


class DriveSheetStore:
    label = "Google Sheet"

    def __init__(self, file_id: str, info: dict, columns: list[str]):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        cred = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
        self.svc = build("drive", "v3", credentials=cred, cache_discovery=False)
        self.file_id, self.columns = file_id, columns
        self.lock = threading.Lock()
        self.svc.files().get(fileId=file_id, fields="id", supportsAllDrives=True).execute()  # fail fast

    def key(self) -> dict:
        return load_key()

    def rows(self) -> list[dict]:
        data = self.svc.files().export(fileId=self.file_id, mimeType="text/csv").execute()
        table = [r for r in csv.reader(io.StringIO(data.decode("utf-8"))) if any(c.strip() for c in r)]
        if not table:
            return []
        header = table[0]
        return [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in table[1:]]

    def load(self, listener_id: str) -> list[dict]:
        return [r for r in self.rows() if r.get("listener_id") == listener_id]

    def upsert(self, rows: list[dict]) -> None:
        from googleapiclient.http import MediaIoBaseUpload

        with self.lock:
            existing = self.rows()
            index = {r.get("row_key"): i for i, r in enumerate(existing)}
            for row in rows:
                if row["row_key"] in index:
                    existing[index[row["row_key"]]] = row
                else:
                    existing.append(row)
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(self.columns)
            writer.writerows([[as_text(r.get(c, "")) for c in self.columns] for r in existing])
            media = MediaIoBaseUpload(io.BytesIO(buf.getvalue().encode("utf-8")), mimetype="text/csv")
            self.svc.files().update(fileId=self.file_id, media_body=media, supportsAllDrives=True).execute()


class LocalStore:
    label = "local file"

    def __init__(self, path: Path, columns: list[str] = COLUMNS):
        self.path = path
        self.columns = columns
        self.lock = threading.Lock()

    def key(self) -> dict:
        return load_key()

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def load(self, listener_id: str) -> list[dict]:
        return [r for r in self.rows() if r.get("listener_id") == listener_id]

    def upsert(self, rows: list[dict]) -> None:
        with self.lock:
            existing = {r["row_key"]: r for r in self.rows()}
            for row in rows:
                existing[row["row_key"]] = {c: row.get(c, "") for c in self.columns}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.columns)
                writer.writeheader()
                writer.writerows(existing.values())
