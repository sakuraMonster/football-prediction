import argparse
import os
import sqlite3


def _disp_bin(x):
    try:
        v = float(x)
    except Exception:
        return "unknown"
    if v <= 0.06:
        return "low<=0.06"
    if v <= 0.10:
        return "mid<=0.10"
    return "high>0.10"


def _draw_delta_bin(x):
    try:
        v = float(x)
    except Exception:
        return "unknown"
    if v >= 0.015:
        return ">=+0.015"
    if v >= 0.010:
        return ">=+0.010"
    if v <= -0.010:
        return "<=-0.010"
    return "(-0.010,+0.010)"


def _ratio(n, d):
    return (n / d) if d else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.path.join("data", "football.db"))
    parser.add_argument("--run-a", type=int, required=True)
    parser.add_argument("--run-b", type=int, required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))
    cur = conn.cursor()

    def load(run_id):
        cur.execute(
            "SELECT league, COALESCE(prediction_bias,''), COALESCE(dispersion,0), COALESCE(clv_prob,0), COALESCE(draw_prob_delta,0) FROM v2_backtest_rows WHERE run_id=?",
            (run_id,),
        )
        rows = cur.fetchall()
        out = []
        for league, bias, disp, clv, draw_delta in rows:
            out.append(
                {
                    "league": league or "",
                    "bias": bias or "",
                    "disp_bin": _disp_bin(disp),
                    "clv": float(clv) if clv is not None else 0.0,
                    "draw_delta_bin": _draw_delta_bin(draw_delta),
                }
            )
        return out

    a = load(int(args.run_a))
    b = load(int(args.run_b))

    def summarize(rows, key):
        buckets = {}
        for r in rows:
            k = r.get(key) or ""
            buckets.setdefault(k, []).append(r)
        out = []
        for k, items in buckets.items():
            n = len(items)
            non_empty = sum(1 for x in items if x.get("bias"))
            draw_cov = sum(1 for x in items if "平" in (x.get("bias") or ""))
            clv_mean = sum(x.get("clv", 0.0) for x in items) / n if n else 0.0
            out.append(
                {
                    "key": k,
                    "n": n,
                    "bias_non_empty": _ratio(non_empty, n),
                    "bias_draw_covered": _ratio(draw_cov, n),
                    "clv_mean": clv_mean,
                }
            )
        out.sort(key=lambda x: x["n"], reverse=True)
        return out

    print("== dispersion bins ==")
    sa = summarize(a, "disp_bin")
    sb = summarize(b, "disp_bin")
    print("A", sa)
    print("B", sb)

    print("== top leagues ==")
    la = summarize(a, "league")[:15]
    lb = summarize(b, "league")[:15]
    print("A", la)
    print("B", lb)

    print("== draw_prob_delta bins ==")
    da = summarize(a, "draw_delta_bin")
    dbb = summarize(b, "draw_delta_bin")
    print("A", da)
    print("B", dbb)

    conn.close()


if __name__ == "__main__":
    main()
