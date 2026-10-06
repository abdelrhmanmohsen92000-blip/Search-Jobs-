"""CSV + JSON storage helpers with archival so no research cycle silently
overwrites prior data.
"""
import csv
import datetime as _dt
import json
import shutil

from . import paths


def _timestamp():
    return _dt.datetime.now().strftime("%Y%m%dT%H%M%S")


def backup_file(path):
    """Copy an existing file into data/archive/ with a timestamp suffix
    before it gets overwritten. No-op if the file doesn't exist yet.
    """
    if not path.exists():
        return None
    paths.DATA_ARCHIVE.mkdir(parents=True, exist_ok=True)
    dest = paths.DATA_ARCHIVE / f"{path.stem}.{_timestamp()}{path.suffix}"
    shutil.copy2(path, dest)
    return dest


def read_csv(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fieldnames, rows, backup=True):
    """Overwrite a CSV, backing up the previous version first."""
    if backup:
        backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def append_csv_rows(path, fieldnames, rows):
    """Append rows to a CSV, creating it with a header if missing. Backs up
    first since this still mutates tracked data.
    """
    existing = read_csv(path)
    write_csv(path, fieldnames, existing + rows, backup=True)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def load_json(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_run_snapshot(subdir, name, data):
    """Save a timestamped JSON snapshot under data/<subdir>/, e.g. for every
    daily_research.py run, so raw collection results are never lost even if
    processed/normalized output has a bug.
    """
    target_dir = paths.DATA_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{name}.{_timestamp()}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return out_path
