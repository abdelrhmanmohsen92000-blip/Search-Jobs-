"""Learning engine (V1.4).

Computes response/interview/offer/networking rates grouped by country, job
title, source, company, and work mode from tracking/applications.csv and
tracking/networking.csv. Every rate is reported WITH its sample size, and a
segment with too few data points is explicitly flagged rather than used to
draw a conclusion ("Germany: 22%, n=9" is a signal; "Germany: 100%, n=1" is not).
"""
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, storage  # noqa: E402

MIN_SAMPLE_SIZE = 3
RESPONSE_STATUSES = {"FOLLOW_UP", "INTERVIEW", "OFFER", "ACCEPTED", "REJECTED"}
APPLIED_STATUSES = {"APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "ACCEPTED", "REJECTED", "CLOSED"}


def _status(row):
    return (row.get("status") or "").strip().upper()


def _rate_by_segment(rows, segment_key, numerator_fn, denominator_fn, min_sample_size=MIN_SAMPLE_SIZE):
    """Generic grouped-rate computation. Returns {segment: {rate, sample_size,
    insufficient_sample}}. `rate` is None when sample_size is 0.
    """
    denom_counter = collections.Counter()
    numer_counter = collections.Counter()

    for row in rows:
        segment = row.get(segment_key)
        if not segment:
            continue
        if denominator_fn(row):
            denom_counter[segment] += 1
            if numerator_fn(row):
                numer_counter[segment] += 1

    results = {}
    for segment, n in denom_counter.items():
        rate = round(numer_counter[segment] / n * 100, 1) if n else None
        results[segment] = {
            "rate": rate,
            "sample_size": n,
            "insufficient_sample": n < min_sample_size,
        }
    return results


def response_rate_by(segment_key, applications=None, min_sample_size=MIN_SAMPLE_SIZE):
    applications = applications if applications is not None else storage.read_csv(paths.APPLICATIONS_CSV)
    return _rate_by_segment(
        applications, segment_key,
        numerator_fn=lambda r: _status(r) in RESPONSE_STATUSES,
        denominator_fn=lambda r: _status(r) in APPLIED_STATUSES,
        min_sample_size=min_sample_size,
    )


def interview_rate_by(segment_key, applications=None, min_sample_size=MIN_SAMPLE_SIZE):
    applications = applications if applications is not None else storage.read_csv(paths.APPLICATIONS_CSV)
    return _rate_by_segment(
        applications, segment_key,
        numerator_fn=lambda r: _status(r) in ("INTERVIEW", "OFFER", "ACCEPTED"),
        denominator_fn=lambda r: _status(r) in APPLIED_STATUSES,
        min_sample_size=min_sample_size,
    )


def offer_rate_by(segment_key, applications=None, min_sample_size=MIN_SAMPLE_SIZE):
    applications = applications if applications is not None else storage.read_csv(paths.APPLICATIONS_CSV)
    return _rate_by_segment(
        applications, segment_key,
        numerator_fn=lambda r: _status(r) in ("OFFER", "ACCEPTED"),
        denominator_fn=lambda r: _status(r) in APPLIED_STATUSES,
        min_sample_size=min_sample_size,
    )


def networking_response_rate(networking=None, min_sample_size=MIN_SAMPLE_SIZE):
    networking = networking if networking is not None else storage.read_csv(paths.NETWORKING_CSV)
    sent = [n for n in networking if (n.get("message_status") or "").lower() in ("sent", "replied")]
    responded = [n for n in sent if (n.get("message_status") or "").lower() == "replied"]
    n = len(sent)
    rate = round(len(responded) / n * 100, 1) if n else None
    return {"rate": rate, "sample_size": n, "insufficient_sample": n < min_sample_size}


def full_learning_report(applications=None, networking=None, segment_keys=("country", "job_title", "source", "company")):
    """Returns {dimension: {segment: {rate, sample_size, insufficient_sample}}}
    for response/interview/offer rate, plus overall networking response rate.
    Segment key 'work_mode' is intentionally left out of applications.csv's
    current schema — add it there before trusting that breakdown.
    """
    applications = applications if applications is not None else storage.read_csv(paths.APPLICATIONS_CSV)
    networking = networking if networking is not None else storage.read_csv(paths.NETWORKING_CSV)

    report = {"response_rate": {}, "interview_rate": {}, "offer_rate": {}}
    for key in segment_keys:
        if applications and key not in applications[0]:
            continue
        report["response_rate"][key] = response_rate_by(key, applications)
        report["interview_rate"][key] = interview_rate_by(key, applications)
        report["offer_rate"][key] = offer_rate_by(key, applications)

    report["networking_response_rate"] = networking_response_rate(networking)
    return report


def record_learning_snapshot(report, csv_path=None):
    """Appends every segment/metric combination to tracking/learning.csv as
    one timestamped snapshot — never overwrites prior history.
    """
    import datetime as _dt

    csv_path = csv_path or paths.LEARNING_CSV
    today = _dt.date.today().isoformat()
    fieldnames = ["date", "dimension", "segment", "metric", "rate", "sample_size", "note"]
    rows = []
    for dimension in ("response_rate", "interview_rate", "offer_rate"):
        for segment_key, segment_map in report.get(dimension, {}).items():
            for segment_value, stats in segment_map.items():
                rows.append({
                    "date": today, "dimension": dimension, "segment": f"{segment_key}={segment_value}",
                    "metric": dimension, "rate": stats["rate"], "sample_size": stats["sample_size"],
                    "note": "insufficient sample" if stats["insufficient_sample"] else "",
                })
    networking_stats = report.get("networking_response_rate", {})
    if networking_stats.get("sample_size"):
        rows.append({
            "date": today, "dimension": "networking_response_rate", "segment": "all", "metric": "networking_response_rate",
            "rate": networking_stats["rate"], "sample_size": networking_stats["sample_size"],
            "note": "insufficient sample" if networking_stats["insufficient_sample"] else "",
        })
    if rows:
        storage.append_csv_rows(csv_path, fieldnames, rows)
    return rows
