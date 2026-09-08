"""
MPLADS eSAKSHI - backfill sanctioned-works data
--------------------------------------------------
Scans _progress.json for every constituency already marked done for
completed-works+images, and for any of them NOT yet marked done for
sanctioned-works, fetches works_sanctioned.csv for it.

This NEVER touches images or works_with_images.csv - it only ever calls
process_sanctioned(), which writes a separate file. Safe to run any time,
including mid-way through a larger mplads_india_downloader.py run (though
best to let that finish first to avoid two scripts writing _progress.json
at the same moment).

Requires mplads_common.py in the same folder.
"""

import mplads_common as m


def run():
    states = {s["ID"]: s["CAPTION"] for s in m.get_states()}

    progress = m.load_progress()
    done_completed = set(progress["done_completed"])
    done_sanctioned = set(progress["done_sanctioned"])

    missing = sorted(done_completed - done_sanctioned)
    print(f"{len(done_completed)} constituencies have completed-works+images done.")
    print(f"{len(done_sanctioned)} already have sanctioned-works done.")
    print(f"{len(missing)} need sanctioned-works backfilled.\n")

    if not missing:
        print("Nothing to do.")
        return

    # group by state so we only call get_constituencies once per state
    by_state = {}
    for key in missing:
        state_id_str, const_id_str = key.split(":")
        by_state.setdefault(state_id_str, []).append(const_id_str)

    for state_id_str, const_ids in by_state.items():
        state_id = int(state_id_str)
        state_name = states.get(state_id, f"UnknownState{state_id}")
        print(f"=== {state_name} ({len(const_ids)} constituencies to backfill) ===")

        try:
            constituencies = m.get_constituencies(state_id)
        except Exception as e:
            print(f"  failed to fetch constituencies: {e}")
            continue
        const_lookup = {str(c["ID"]): c["CAPTION"] for c in constituencies}

        for const_id_str in const_ids:
            const_name = const_lookup.get(const_id_str, f"UnknownConstituency{const_id_str}")
            key = f"{state_id}:{const_id_str}"

            mp = m.get_mp_for_constituency(const_id_str)
            if not mp:
                print(f"  {const_name}: no MP found, skipping")
                continue

            try:
                success = m.process_sanctioned(state_name, state_id, const_name, const_id_str, mp["ID"])
                if success:
                    done_sanctioned.add(key)
                    progress["done_sanctioned"] = list(done_sanctioned)
                    m.save_progress(progress)
            except Exception as e:
                print(f"  {const_name}: FAILED - {e}")

    print("\nBackfill done.")


if __name__ == "__main__":
    run()
