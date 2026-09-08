"""
MPLADS eSAKSHI - full India image downloader
-----------------------------------------------
Walks every State -> Constituency -> MP -> Completed Work -> Image,
using the site's own internal API (no browser, no scraping HTML).

Folder layout produced:
    mplads_india/
        Maharashtra/
            PUNE/
                works_with_images.csv   (all fields + tagged image filenames)
                186052_1.jpg
                186058_1.jpg
                ...
        Manipur/
            OUTER MANIPUR(ST)/
                works_with_images.csv
                ...
        _progress.json      <- tracks which constituencies are already done,
                                so you can safely stop and re-run this script
                                without redownloading everything.

IMPORTANT - SCALE:
    India has ~543 Lok Sabha constituencies. Each has its own MP and its own
    set of "Works Completed" (can be 0 to 50+, each with 0-several images).
    This script is polite (small delay between requests) but a full run
    can still mean tens of thousands of requests and easily several hours.
    Start with LIMIT_STATES set to a small number to sanity-check things
    before committing to a full overnight run.
"""

import json
import time
import re
import csv
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

# Only fetch this many states (None = all 37). Use a small number to test first.
LIMIT_STATES = None
# Skip these state IDs if you want to exclude e.g. UTs with 0 seats, optional.
SKIP_STATE_IDS = set()

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
        return json.loads(PROGRESS_FILE.read_text())
    return {"done_constituencies": []}


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
    return [w for w in works if "WORK_ID" in w]


def get_attachments(work_id, flag: str = WORK_FLAG):
    r = post_with_retry(f"{BASE}/PreLoginDashboardData/getAttachIdsbyFlag",
                         {"json": {"FLAG": flag, "WORK_ID": str(work_id)}})
    return r.json()


def download_attachment(attach_id: str, out_path: Path):
    r = post_with_retry(f"{BASE}/PreLoginCitizenWorkRcmdRest/getAttachmentById",
                         {"id": attach_id})
    import base64
    payload = r.json()
    b64_data = payload[0]["URL"]  # misleadingly named - it's base64 file content
    out_path.write_bytes(base64.b64decode(b64_data))


# ---------- Per-constituency worker ----------

def process_constituency(state_name: str, state_id: str, constituency_name: str, constituency_id: str) -> bool:
    """Returns True only if every work and every image for this constituency
    was successfully processed - that's the only case it's safe to mark 'done'."""
    mp = get_mp_for_constituency(constituency_id)
    if not mp:
        print(f"  no MP found for {constituency_name}, skipping")
        return True  # nothing to do here, safe to mark done

    combo = f"{state_id},{constituency_id},{mp['ID']},{TENURE_ID}"
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


# ---------- Main orchestration ----------

def run():
    states = get_states()  # you must fill this in - see instructions at bottom
    progress = load_progress()
    done = set(progress["done_constituencies"])

    if LIMIT_STATES:
        states = states[:LIMIT_STATES]

    for state in states:
        state_id, state_name = state["ID"], state["CAPTION"]
        if str(state_id) in SKIP_STATE_IDS:
            continue

        print(f"\n=== {state_name} ===")
        try:
            constituencies = get_constituencies(state_id)
        except Exception as e:
            print(f"  failed to fetch constituencies: {e}")
            continue
        time.sleep(REQUEST_DELAY)

        for const in constituencies:
            const_id, const_name = const["ID"], const["CAPTION"]
            key = f"{state_id}:{const_id}"
            if key in done:
                print(f"  {const_name}: already done, skipping")
                continue

            try:
                success = process_constituency(state_name, state_id, const_name, const_id)
                if success:
                    done.add(key)
                    progress["done_constituencies"] = list(done)
                    save_progress(progress)
                else:
                    print(f"  {const_name}: NOT marked done - will retry remaining images next run")
            except Exception as e:
                print(f"  {const_name}: FAILED - {e}")
            time.sleep(REQUEST_DELAY)

    print("\nAll done.")


if __name__ == "__main__":
    run()
