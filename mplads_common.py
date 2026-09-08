"""
MPLADS eSAKSHI - shared logic
------------------------------
All API calls, retry/backoff, and per-constituency processing live here.
Other scripts (mplads_india_downloader.py, mplads_telangana.py,
backfill_sanctioned.py) import from this module instead of duplicating
this code - so a fix made here (like the WORK_ID filter bug) applies
everywhere at once, instead of needing to be copy-pasted into every script.
"""

import json
import time
import re
import csv
import base64
from pathlib import Path

import requests

BASE = "https://mplads.mospi.gov.in/rest"
OUT_DIR = Path("mplads_india")
OUT_DIR.mkdir(exist_ok=True)
PROGRESS_FILE = OUT_DIR / "_progress.json"

TENURE_ID = "2"          # internal tenure id used in combo strings = 18th Lok Sabha
WORK_KEY = "Works Completed"
WORK_FLAG = "3"           # matches "Works Completed" in getAttachIdsbyFlag

REQUEST_DELAY = 0.6        # base seconds between requests - stay polite to a gov server
MAX_RETRIES = 6             # retries on 429 / transient errors before giving up on a call
BACKOFF_BASE = 2.0          # seconds; doubles each retry (2, 4, 8, 16, 32, 64...)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "Referer": "https://mplads.mospi.gov.in/digigov/dashboard.html",
})
session.get("https://mplads.mospi.gov.in/digigov/dashboard.html")


def post_with_retry(url: str, json_body: dict, timeout: int = 30):
    """POST with exponential backoff on 429 (rate limit) and transient 5xx errors.
    Respects a Retry-After header if the server sends one. Raises the final
    error only after MAX_RETRIES is exhausted."""
    for attempt in range(MAX_RETRIES + 1):
        r = session.post(url, json=json_body, timeout=timeout)
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == MAX_RETRIES:
                r.raise_for_status()
            retry_after = r.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else BACKOFF_BASE * (2 ** attempt)
            print(f"    [rate limited] waiting {wait:.0f}s (attempt {attempt + 1}/{MAX_RETRIES})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("unreachable")


def safe_name(name: str) -> str:
    """Make a string safe to use as a folder/file name."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        data = json.loads(PROGRESS_FILE.read_text())
        # migrate old progress files (pre-sanctioned-tracking) to the new shape
        if "done_completed" not in data and "done_constituencies" in data:
            data["done_completed"] = data.pop("done_constituencies")
        data.setdefault("done_completed", [])
        data.setdefault("done_sanctioned", [])
        return data
    return {"done_completed": [], "done_sanctioned": []}


def save_progress(progress: dict):
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


# ---------- API calls ----------

def get_states():
    """Full list of states/UTs with their internal IDs, captured directly from
    the site's own State dropdown (id="demo") - the site has no standalone
    API endpoint for this, it's just baked into the page's HTML options."""
    return [
        {"ID": 35, "CAPTION": "Andaman And Nicobar Islands"},
        {"ID": 2, "CAPTION": "Andhra Pradesh"},
        {"ID": 3, "CAPTION": "Arunachal Pradesh"},
        {"ID": 5, "CAPTION": "Assam"},
        {"ID": 6, "CAPTION": "Bihar"},
        {"ID": 7, "CAPTION": "Chandigarh"},
        {"ID": 8, "CAPTION": "Chhattisgarh"},
        {"ID": 11, "CAPTION": "Delhi"},
        {"ID": 12, "CAPTION": "Goa"},
        {"ID": 27, "CAPTION": "Gujarat"},
        {"ID": 14, "CAPTION": "Haryana"},
        {"ID": 15, "CAPTION": "Himachal Pradesh"},
        {"ID": 16, "CAPTION": "Jammu And Kashmir"},
        {"ID": 17, "CAPTION": "Jharkhand"},
        {"ID": 18, "CAPTION": "Karnataka"},
        {"ID": 36, "CAPTION": "Kerala"},
        {"ID": 130, "CAPTION": "Ladakh"},
        {"ID": 19, "CAPTION": "Lakshadweep"},
        {"ID": 20, "CAPTION": "Madhya Pradesh"},
        {"ID": 21, "CAPTION": "Maharashtra"},
        {"ID": 22, "CAPTION": "Manipur"},
        {"ID": 23, "CAPTION": "Meghalaya"},
        {"ID": 13, "CAPTION": "Mizoram"},
        {"ID": 24, "CAPTION": "Nagaland"},
        {"ID": 25, "CAPTION": "Odisha"},
        {"ID": 26, "CAPTION": "Puducherry"},
        {"ID": 1, "CAPTION": "Punjab"},
        {"ID": 28, "CAPTION": "Rajasthan"},
        {"ID": 29, "CAPTION": "Sikkim"},
        {"ID": 30, "CAPTION": "Tamil Nadu"},
        {"ID": 129, "CAPTION": "Telangana"},
        {"ID": 10, "CAPTION": "The Dadra And Nagar Haveli And Daman And Diu"},
        {"ID": 31, "CAPTION": "Tripura"},
        {"ID": 33, "CAPTION": "Uttar Pradesh"},
        {"ID": 32, "CAPTION": "Uttarakhand"},
        {"ID": 34, "CAPTION": "West Bengal"},
    ]


def get_constituencies(state_id: str):
    r = post_with_retry(f"{BASE}/PreLoginDashboardData/getConstituencyData",
                         {"id": str(state_id)})
    return r.json()  # [{"ID": const_id, "CAPTION": name}, ...]


def get_mp_for_constituency(constituency_id: str):
    r = post_with_retry(f"{BASE}/PreLoginDashboardData/getMpAndConstCombo",
                         {"const_combo": f"{constituency_id},{TENURE_ID},"})
    mps = r.json()
    return mps[0] if mps else None  # {"ID": mp_id, "CAPTION": name}


def get_works(combo: str, key: str = WORK_KEY):
    r = post_with_retry(f"{BASE}/PreLoginDashboardData/getTilesReportData",
                         {"combo": combo, "key": key})
    data = r.json()
    inner_key = next((k for k in data if k.startswith("Total")), None)
    if not inner_key:
        return []
    works = json.loads(data[inner_key])
    # Filter out the trailing "grand totals" row. Use WORK_RECOMMENDATION_DTL_ID,
    # not WORK_ID - "Works Sanctioned" rows have NO "WORK_ID" field at all (that
    # field only exists on Completed rows, since it's what images key off of),
    # but WORK_RECOMMENDATION_DTL_ID is present on every real row in both.
    return [w for w in works if "WORK_RECOMMENDATION_DTL_ID" in w]


def get_attachments(work_id, flag: str = WORK_FLAG):
    r = post_with_retry(f"{BASE}/PreLoginDashboardData/getAttachIdsbyFlag",
                         {"json": {"FLAG": flag, "WORK_ID": str(work_id)}})
    return r.json()


def download_attachment(attach_id: str, out_path: Path):
    r = post_with_retry(f"{BASE}/PreLoginCitizenWorkRcmdRest/getAttachmentById",
                         {"id": attach_id})
    payload = r.json()
    b64_data = payload[0]["URL"]  # misleadingly named - it's base64 file content
    out_path.write_bytes(base64.b64decode(b64_data))


# ---------- Per-constituency workers ----------

def process_constituency(state_name: str, state_id: str, constituency_name: str, constituency_id: str, mp_id) -> bool:
    """Returns True only if every work and every image for this constituency
    was successfully processed - that's the only case it's safe to mark 'done'."""
    combo = f"{state_id},{constituency_id},{mp_id},{TENURE_ID}"
    works = get_works(combo)

    const_dir = OUT_DIR / safe_name(state_name) / safe_name(constituency_name)
    const_dir.mkdir(parents=True, exist_ok=True)

    if not works:
        print(f"  {constituency_name}: 0 completed works")
        return True

    # Different works can have different sets of fields (some carry extra
    # keys like ATTACH_ID/FILE_STATUS, some don't) - build columns from the
    # union of every work's keys, not just the first one, or DictWriter
    # crashes the moment it hits a row with an unseen field.
    fieldnames = []
    seen = set()
    for w in works:
        for k in w.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)
    fieldnames += ["local_image_filenames", "image_count"]
    rows = []
    total_images = 0
    any_failures = False

    for w in works:
        work_id = w["WORK_ID"]
        row_id = w.get("WORK_RECOMMENDATION_DTL_ID", work_id)
        attach_info = get_attachments(work_id)
        saved_names = []

        for entry in attach_info:
            file_names = entry.get("FILE_NAME", [])
            attach_ids = entry.get("ATTACH_ID", [])
            if isinstance(file_names, str):
                file_names = [file_names]
            if isinstance(attach_ids, str):
                attach_ids = [attach_ids]
            for seq, (fname, aid) in enumerate(zip(file_names, attach_ids), start=1):
                ext = fname.split(".")[-1] if "." in fname else "jpg"
                out_name = f"{row_id}_{seq}.{ext}"
                out_path = const_dir / out_name

                if out_path.exists():
                    # already downloaded in a previous (interrupted) run - skip cheaply
                    saved_names.append(out_name)
                    continue

                try:
                    download_attachment(aid, out_path)
                    saved_names.append(out_name)
                except Exception as e:
                    print(f"    FAILED {out_name}: {e}")
                    any_failures = True
                time.sleep(REQUEST_DELAY)

        total_images += len(saved_names)
        row = dict(w)
        row["local_image_filenames"] = ";".join(saved_names)
        row["image_count"] = len(saved_names)
        rows.append(row)
        time.sleep(REQUEST_DELAY)

    csv_path = const_dir / "works_with_images.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    status = "COMPLETE" if not any_failures else "INCOMPLETE (will retry next run)"
    print(f"  {constituency_name}: {len(works)} works, {total_images} images -> {const_dir}  [{status}]")
    return not any_failures


def process_sanctioned(state_name: str, state_id: str, constituency_name: str, constituency_id: str, mp_id) -> bool:
    """Works Sanctioned has no Image column on this site at all - a work that's
    only sanctioned (not yet completed) has no completion photo to attach.
    So this just writes the full data table, no attachment/image step."""
    combo = f"{state_id},{constituency_id},{mp_id},{TENURE_ID}"
    works = get_works(combo, key="Works Sanctioned")

    const_dir = OUT_DIR / safe_name(state_name) / safe_name(constituency_name)
    const_dir.mkdir(parents=True, exist_ok=True)

    if not works:
        print(f"  {constituency_name}: 0 sanctioned works")
        return True

    fieldnames = []
    seen = set()
    for w in works:
        for k in w.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)

    csv_path = const_dir / "works_sanctioned.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(works)

    print(f"  {constituency_name}: {len(works)} sanctioned works -> {csv_path}")
    return True


# ---------- Reusable "process one state, both completed+sanctioned" loop ----------

def process_state(state_id, state_name: str, progress: dict, done_completed: set, done_sanctioned: set):
    """Walks every constituency in one state, doing whichever of
    completed-works / sanctioned-works each constituency still needs.
    Mutates done_completed/done_sanctioned and saves progress as it goes."""
    print(f"\n=== {state_name} ===")
    try:
        constituencies = get_constituencies(state_id)
    except Exception as e:
        print(f"  failed to fetch constituencies: {e}")
        return
    time.sleep(REQUEST_DELAY)

    for const in constituencies:
        const_id, const_name = const["ID"], const["CAPTION"]
        key = f"{state_id}:{const_id}"

        need_completed = key not in done_completed
        need_sanctioned = key not in done_sanctioned

        if not need_completed and not need_sanctioned:
            print(f"  {const_name}: already fully done, skipping")
            continue

        mp = get_mp_for_constituency(const_id)
        time.sleep(REQUEST_DELAY)
        if not mp:
            print(f"  {const_name}: no MP found, skipping")
            done_completed.add(key)
            done_sanctioned.add(key)
            progress["done_completed"] = list(done_completed)
            progress["done_sanctioned"] = list(done_sanctioned)
            save_progress(progress)
            continue
        mp_id = mp["ID"]

        if need_completed:
            try:
                success = process_constituency(state_name, state_id, const_name, const_id, mp_id)
                if success:
                    done_completed.add(key)
                    progress["done_completed"] = list(done_completed)
                    save_progress(progress)
                else:
                    print(f"  {const_name}: completed-works NOT marked done - will retry next run")
            except Exception as e:
                print(f"  {const_name}: completed-works FAILED - {e}")
            time.sleep(REQUEST_DELAY)

        if need_sanctioned:
            try:
                success = process_sanctioned(state_name, state_id, const_name, const_id, mp_id)
                if success:
                    done_sanctioned.add(key)
                    progress["done_sanctioned"] = list(done_sanctioned)
                    save_progress(progress)
            except Exception as e:
                print(f"  {const_name}: sanctioned-works FAILED - {e}")
            time.sleep(REQUEST_DELAY)
