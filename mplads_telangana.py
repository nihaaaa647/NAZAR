"""
MPLADS eSAKSHI - Telangana only
---------------------------------
Same as mplads_india_downloader.py but hardcoded to just Telangana, then
stops. Uses the exact same _progress.json and mplads_india/ folder as the
main script, so anything done here counts toward a later full-India run too.

Requires mplads_common.py in the same folder.
"""

import mplads_common as m

TARGET_STATE = "Telangana"


def run():
    states = m.get_states()
    state = next((s for s in states if s["CAPTION"].lower() == TARGET_STATE.lower()), None)
    if not state:
        print(f"State '{TARGET_STATE}' not found in the states list.")
        return

    progress = m.load_progress()
    done_completed = set(progress["done_completed"])
    done_sanctioned = set(progress["done_sanctioned"])

    m.process_state(state["ID"], state["CAPTION"], progress, done_completed, done_sanctioned)

    print(f"\n{TARGET_STATE} done.")


if __name__ == "__main__":
    run()
