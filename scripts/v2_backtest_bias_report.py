import os
import sqlite3


def main():
    db = os.path.join("data", "football.db")
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, default=None)
    args = parser.parse_args()
    conn = sqlite3.connect(db)
    cur = conn.cursor()

    if args.run_id is not None:
        cur.execute("SELECT id, created_at, evaluated FROM v2_backtest_runs WHERE id=?", (int(args.run_id),))
        run = cur.fetchone()
    else:
        cur.execute("SELECT id, created_at, evaluated FROM v2_backtest_runs ORDER BY id DESC LIMIT 1")
        run = cur.fetchone()
    if not run:
        print("no v2_backtest_runs")
        return
    run_id, created_at, evaluated = run
    print("latest_run", {"id": run_id, "created_at": created_at, "evaluated": evaluated})

    cur.execute("SELECT COUNT(1) FROM v2_backtest_rows WHERE run_id=?", (run_id,))
    total = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(1) FROM v2_backtest_rows WHERE run_id=? AND COALESCE(prediction_bias,'') != ''",
        (run_id,),
    )
    non_empty = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(1) FROM v2_backtest_rows WHERE run_id=? AND prediction_bias LIKE '%平%'",
        (run_id,),
    )
    draw_covered = cur.fetchone()[0]

    print(
        "coverage",
        {
            "total": total,
            "bias_non_empty": non_empty,
            "bias_non_empty_rate": (non_empty / total) if total else 0,
            "bias_draw_covered": draw_covered,
            "bias_draw_covered_rate": (draw_covered / total) if total else 0,
        },
    )

    cur.execute(
        "SELECT COALESCE(actual_result,''), COUNT(1) FROM v2_backtest_rows WHERE run_id=? GROUP BY COALESCE(actual_result,'') ORDER BY COUNT(1) DESC",
        (run_id,),
    )
    print("actual_result_dist", cur.fetchall())

    cur.execute(
        "SELECT COALESCE(prediction_bias,''), COUNT(1) FROM v2_backtest_rows WHERE run_id=? GROUP BY COALESCE(prediction_bias,'') ORDER BY COUNT(1) DESC",
        (run_id,),
    )
    print("prediction_bias_dist_top", cur.fetchall()[:20])

    conn.close()


if __name__ == "__main__":
    main()
