"""
MPLADS eSAKSHI - full India downloader (completed-work images + sanctioned-work data)
-----------------------------------------------------------------------------------
Walks every State -> Constituency -> MP, and for each pulls:
  1. "Works Completed" - full data + every attached image.
  2. "Works Sanctioned" - full data table only (no images - see mplads_common.py
     for why sanctioned works never have attachments on this site).

All the actual logic lives in mplads_common.py - this file just drives it
across every state. Keep mplads_common.py in the same folder as this script.

Folder layout produced:
    mplads_india/
        Maharashtra/
            PUNE/
                works_with_images.csv    (completed works + tagged image filenames)
                works_sanctioned.csv     (sanctioned works, no images)
                186052_1.jpg
                ...
        _progress.json      <- tracks completed-works and sanctioned-works progress
                                SEPARATELY per constituency.

IMPORTANT - SCALE:
    India has ~543 Lok Sabha constituencies. This script is polite but a full
    run can still mean tens of thousands of requests and several hours.
    Use LIMIT_STATES / ONLY_STATES to sanity-check on a small set first.
"""

import mplads_common as m

# Only fetch this many states (None = all 37). Use a small number to test first.
LIMIT_STATES = None
# If set, ONLY these states are processed (by CAPTION, case-insensitive).
ONLY_STATES = None
# Skip these state IDs if you want to exclude e.g. UTs with 0 seats, optional.
SKIP_STATE_IDS = set()


def run():
    states = m.get_states()
    progress = m.load_progress()
    done_completed = set(progress["done_completed"])
    done_sanctioned = set(progress["done_sanctioned"])

    if ONLY_STATES:
        wanted = {s.lower() for s in ONLY_STATES}
        states = [s for s in states if s["CAPTION"].lower() in wanted]
        if not states:
            print(f"No matching states found for ONLY_STATES={ONLY_STATES} - check spelling.")
            return

    if LIMIT_STATES:
        states = states[:LIMIT_STATES]

    for state in states:
        state_id, state_name = state["ID"], state["CAPTION"]
        if str(state_id) in SKIP_STATE_IDS:
            continue
        m.process_state(state_id, state_name, progress, done_completed, done_sanctioned)

    print("\nAll done.")


if __name__ == "__main__":
    run()
