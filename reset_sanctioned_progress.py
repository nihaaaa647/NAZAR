"""
Run this ONCE before your next mplads_india_downloader.py run.

It clears ONLY the "done_sanctioned" progress list, so works_sanctioned.csv
gets correctly regenerated (with the WORK_ID filter bug fixed) for every
constituency you've already processed.

It does NOT touch "done_completed" at all - so no images will be
re-downloaded. This is safe.
"""
import json
from pathlib import Path

progress_file = Path("mplads_india") / "_progress.json"

data = json.loads(progress_file.read_text())
print(f"Before: {len(data.get('done_completed', []))} constituencies with images done, "
      f"{len(data.get('done_sanctioned', []))} with sanctioned data done")

data["done_sanctioned"] = []

progress_file.write_text(json.dumps(data, indent=2))
print(f"After:  {len(data['done_completed'])} constituencies with images done (untouched), "
      f"{len(data['done_sanctioned'])} with sanctioned data done (cleared)")
print("\nSafe to run mplads_india_downloader.py now - it will only backfill "
      "works_sanctioned.csv, no images will be re-downloaded.")
