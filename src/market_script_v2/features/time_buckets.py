from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BucketedSnapshots:
    open: list[dict]
    t_24: list[dict]
    t_12: list[dict]
    t_6: list[dict]
    t_1: list[dict]
    close: list[dict]

    def bucket_counts(self) -> dict[str, int]:
        return {
            "open": len(self.open),
            "T-24": len(self.t_24),
            "T-12": len(self.t_12),
            "T-6": len(self.t_6),
            "T-1": len(self.t_1),
            "close": len(self.close),
        }


def parse_datetime_maybe(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _bucket_key(dt_hours: float):
    if dt_hours >= 18:
        return "T-24"
    if dt_hours >= 9:
        return "T-12"
    if dt_hours >= 4:
        return "T-6"
    if dt_hours >= 0.75:
        return "T-1"
    return "close"


def bucket_by_kickoff(snapshots: list[dict], kickoff_time: datetime | None) -> BucketedSnapshots:
    if not snapshots:
        return BucketedSnapshots(open=[], t_24=[], t_12=[], t_6=[], t_1=[], close=[])

    ordered = sorted(
        [s for s in snapshots if s.get("snapshot_time")],
        key=lambda s: s["snapshot_time"],
    )
    open_bucket = [ordered[0]]
    if kickoff_time is None:
        if len(ordered) == 1:
            return BucketedSnapshots(open=open_bucket, t_24=[], t_12=[], t_6=[], t_1=[], close=open_bucket)
        close_bucket = [ordered[-1]]
        mid = ordered[1:-1]
        split_1 = int(len(mid) * 0.25)
        split_2 = int(len(mid) * 0.50)
        split_3 = int(len(mid) * 0.75)
        return BucketedSnapshots(
            open=open_bucket,
            t_24=mid[:split_1],
            t_12=mid[split_1:split_2],
            t_6=mid[split_2:split_3],
            t_1=mid[split_3:],
            close=close_bucket,
        )

    t24, t12, t6, t1, close = [], [], [], [], []
    for snap in ordered[1:]:
        dt = kickoff_time - snap["snapshot_time"]
        dt_hours = dt.total_seconds() / 3600.0
        key = _bucket_key(dt_hours)
        if key == "T-24":
            t24.append(snap)
        elif key == "T-12":
            t12.append(snap)
        elif key == "T-6":
            t6.append(snap)
        elif key == "T-1":
            t1.append(snap)
        else:
            close.append(snap)
    if not close:
        close = [ordered[-1]]
    return BucketedSnapshots(open=open_bucket, t_24=t24, t_12=t12, t_6=t6, t_1=t1, close=close)
