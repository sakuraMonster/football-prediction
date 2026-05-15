import os
import sys
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.market_script_v2.daily_window import compute_today_window
from scripts.v2_daily_lock_fixtures import lock_today_window
from scripts.v2_daily_collect_snapshots import collect_snapshots_for_window
from scripts.v2_daily_final_predict import run_final_predictions


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    mode = str(mode or "").strip().lower()

    window_tag = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] not in {"-", ""} else None
    if not window_tag:
        _, _, window_tag = compute_today_window(datetime.now())

    if mode == "lock":
        lock_today_window()
        return
    if mode == "snapshot":
        collect_snapshots_for_window(window_tag)
        return
    if mode == "final":
        run_final_predictions(window_tag)
        return

    print("Usage: python scripts/v2_daily_pipeline.py lock|snapshot|final [window_tag]")


if __name__ == "__main__":
    main()

