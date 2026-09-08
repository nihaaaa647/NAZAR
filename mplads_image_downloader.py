"""
MPLADS eSAKSHI image downloader
--------------------------------
Bypasses the broken on-page DataTable entirely and pulls work data + images
straight from the site's own REST API.

HOW TO GET YOUR `combo` STRING (per MP/constituency you care about):
1. Open the dashboard in Chrome, open DevTools -> Network -> filter "getTilesReportData"
2. Pick your Tenure/State/Constituency/MP Name in the search box, click a tile
   (e.g. "Works Completed")
3. Click the getTilesReportData request -> Payload/Request tab -> copy the
   "combo" value (looks like "21,255,3042414,2")
4. Paste it below. One combo = one MP's data.

Usage:
    python mplads_image_downloader.py
"""

import json
import time
from pathlib import Path

import requests

BASE = "https://mplads.mospi.gov.in/rest"
OUT_DIR = Path("mplads_images")
OUT_DIR.mkdir(exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "Referer": "https://mplads.mospi.gov.in/digigov/dashboard.html",
})
# Prime any cookies the site sets on first load
session.get("https://mplads.mospi.gov.in/digigov/dashboard.html")


def get_works(combo: str, key: str = "Works Completed"):
    """Fetch the full work list for a given MP/constituency combo."""
    r = session.post(
        f"{BASE}/PreLoginDashboardData/getTilesReportData",
        json={"combo": combo, "key": key},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    # The payload is a JSON *string* nested inside the response, under a key
    # like "Total Works Completed" - find whichever key holds it.
    inner_key = next(k for k in data if k.startswith("Total"))
    works = json.loads(data[inner_key])
    # last row is usually a totals row with no WORK_ID - drop it
    return [w for w in works if "WORK_ID" in w]


def get_attachments(work_id, flag: str = "3"):
    """Returns list of {"FILE_NAME": [...], "ATTACH_ID": [...]} for a work."""
    r = session.post(
        f"{BASE}/PreLoginDashboardData/getAttachIdsbyFlag",
        json={"json": {"FLAG": flag, "WORK_ID": str(work_id)}},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def download_attachment(attach_id: str, out_path: Path):
    r = session.post(
        f"{BASE}/PreLoginCitizenWorkRcmdRest/getAttachmentById",
        json={"id": attach_id},
        timeout=30,
    )
    r.raise_for_status()
    # Response is NOT raw image bytes - it's JSON:
    #   [{"FILE_NAME": "Photo_After.jpg", "URL": "<base64-encoded image data>"}]
    # (the "URL" field is misleadingly named - it's actually base64 file content)
    import base64
    payload = r.json()
    b64_data = payload[0]["URL"]
    out_path.write_bytes(base64.b64decode(b64_data))


def run(combo: str, key: str = "Works Completed", flag: str = "3"):
    works = get_works(combo, key)
    print(f"Found {len(works)} works for combo={combo}")

    if not works:
        print("No works returned - check your combo string.")
        return

    # Use every field the API gives us for each work, plus our own extra columns.
    # This becomes the ONLY csv you need - no separate manual CSV download.
    base_fields = list(works[0].keys())
    extra_fields = ["local_image_filenames", "image_count"]
    fieldnames = base_fields + extra_fields

    rows = []
    total_images = 0

    for w in works:
        work_id = w["WORK_ID"]
        row_id = w.get("WORK_RECOMMENDATION_DTL_ID", work_id)  # unique per-row id

        attach_info = get_attachments(work_id, flag)
        saved_names = []

        for entry in attach_info:
            file_names = entry.get("FILE_NAME", [])
            attach_ids = entry.get("ATTACH_ID", [])
            for seq, (fname, aid) in enumerate(zip(file_names, attach_ids), start=1):
                ext = fname.split(".")[-1] if "." in fname else "jpg"
                out_name = f"{row_id}_{seq}.{ext}"
                out_path = OUT_DIR / out_name
                try:
                    download_attachment(aid, out_path)
                    saved_names.append(out_name)
                    print(f"  saved {out_name}")
                except Exception as e:
                    print(f"  FAILED {out_name}: {e}")
                time.sleep(0.3)  # be polite to a government server

        total_images += len(saved_names)

        row = dict(w)  # every original field: category, description, MP, dates, amounts, status...
        row["local_image_filenames"] = ";".join(saved_names)  # tagged right in the row
        row["image_count"] = len(saved_names)
        rows.append(row)

    # single, complete CSV - work details + tagged image filenames, one row per work
    import csv
    csv_path = OUT_DIR / "works_with_images.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {total_images} images saved to {OUT_DIR}/")
    print(f"Full CSV (work details + tagged images) written to {csv_path}")


if __name__ == "__main__":
    # EDIT THIS: your combo string from DevTools (see instructions above)
    COMBO = "21,255,3042414,2"
    run(COMBO, key="Works Completed")
