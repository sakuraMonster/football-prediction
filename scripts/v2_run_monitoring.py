import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from loguru import logger

from src.db.database import Database, V2ScriptOutput
from src.market_script_v2.config import load_v2_subclass_configs
from src.market_script_v2.monitoring.metrics import compute_window_metrics, ewma


def _status_upgrade_downgrade(
    *,
    current_status: str,
    short_metrics,
    mid_metrics,
):
    status = str(current_status or "gray")
    if status == "white":
        if short_metrics.n >= 60 and (short_metrics.clv_magnitude is not None) and short_metrics.clv_magnitude < 0:
            return "gray"
        return status

    if status == "gray":
        if mid_metrics.n >= 200 and (mid_metrics.clv_rate is not None) and (mid_metrics.clv_magnitude is not None):
            if mid_metrics.clv_rate >= 0.54 and mid_metrics.clv_magnitude >= 0.005:
                return "white"
        return status

    if status == "black":
        return status
    return status


def run_monitoring(league_filter=None):
    cfg = load_v2_subclass_configs()
    db = Database()

    updated = 0
    for subclass_id, subclass_cfg in cfg.items():
        league_query = db.session.query(V2ScriptOutput.league).filter(V2ScriptOutput.subclass == subclass_id)
        if league_filter:
            league_query = league_query.filter(V2ScriptOutput.league == league_filter)
        leagues = [r[0] for r in league_query.distinct().all()]
        leagues = [str(x or "").strip() for x in leagues if str(x or "").strip()]
        if not leagues:
            leagues = [""]

        for league in leagues:
            base = db.session.query(V2ScriptOutput).filter(V2ScriptOutput.subclass == subclass_id)
            if league:
                base = base.filter(V2ScriptOutput.league == league)
            base = base.order_by(V2ScriptOutput.created_at.desc())

            short_rows = base.limit(int(subclass_cfg.monitoring.short_window)).all()
            mid_rows = base.limit(int(subclass_cfg.monitoring.mid_window)).all()

            def _row_to_dict(r: V2ScriptOutput):
                return {
                    "clv_prob": r.clv_prob,
                    "dispersion": r.dispersion,
                }

            short_metrics = compute_window_metrics([_row_to_dict(r) for r in short_rows])
            mid_metrics = compute_window_metrics([_row_to_dict(r) for r in mid_rows])

            prev_short = db.fetch_v2_monitor_metric(
                subclass=subclass_id,
                league=league,
                regime="default",
                window_name="short",
            )
            prev_mid = db.fetch_v2_monitor_metric(
                subclass=subclass_id,
                league=league,
                regime="default",
                window_name="mid",
            )
            prev_ewma_short = getattr(prev_short, "ewma_clv", None) if prev_short else None
            prev_ewma_mid = getattr(prev_mid, "ewma_clv", None) if prev_mid else None

            ewma_short = ewma(prev_ewma_short, short_metrics.clv_magnitude, subclass_cfg.monitoring.alpha)
            ewma_mid = ewma(prev_ewma_mid, mid_metrics.clv_magnitude, subclass_cfg.monitoring.alpha)

            current_status = getattr(prev_mid, "status", None) or subclass_cfg.monitoring.status
            status = _status_upgrade_downgrade(
                current_status=current_status,
                short_metrics=short_metrics,
                mid_metrics=mid_metrics,
            )

            db.upsert_v2_monitor_metric(
                subclass=subclass_id,
                league=league,
                regime="default",
                window_name="short",
                n=short_metrics.n,
                clv_rate=short_metrics.clv_rate,
                clv_magnitude=short_metrics.clv_magnitude,
                dispersion=short_metrics.dispersion,
                ewma_clv=ewma_short,
                status=status,
            )
            db.upsert_v2_monitor_metric(
                subclass=subclass_id,
                league=league,
                regime="default",
                window_name="mid",
                n=mid_metrics.n,
                clv_rate=mid_metrics.clv_rate,
                clv_magnitude=mid_metrics.clv_magnitude,
                dispersion=mid_metrics.dispersion,
                ewma_clv=ewma_mid,
                status=status,
            )

            updated += 2
            logger.info(f"v2 monitor updated subclass={subclass_id} league={league or 'ALL'} status={status}")

    db.close()
    return updated


if __name__ == "__main__":
    league_arg = sys.argv[1] if len(sys.argv) > 1 else None
    count = run_monitoring(league_arg)
    print(f"✅ v2 监控更新完成: {count}")
