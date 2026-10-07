"""Versioned decision model (V1.4 / V1.7).

config/scoring_model.yaml holds every version; `active_version` selects the
one analyses use. New versions are only ever added through
`create_version(...)`, which the learning loop calls on an explicit human
approval — never automatically.
"""
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml  # noqa: E402

from scripts.lib import paths, storage  # noqa: E402

MODEL_PATH = paths.CONFIG_DIR / "scoring_model.yaml"
WEIGHT_GROUPS = ("match_weights", "profile_match_weights", "opportunity_weights")


def default_path():
    """The model file in use: a workspace-local copy (e.g. the demo workspace's
    config/scoring_model.yaml) when one exists, else the repository's. Learning
    approvals in an isolated workspace therefore never touch the real model."""
    local = paths.WORKSPACE / "config" / "scoring_model.yaml"
    return local if paths.WORKSPACE != paths.ROOT and local.exists() else MODEL_PATH


def load_all(path=None):
    path = Path(path) if path else default_path()
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def active_model(path=None):
    data = load_all(path)
    version = str(data.get("active_version"))
    model = dict((data.get("versions") or {})[version])
    model["version"] = version
    return model


def validate_model(model):
    """Every weight group must sum to 100 and contain only non-negative numbers."""
    errors = []
    for group in WEIGHT_GROUPS:
        weights = model.get(group) or {}
        if any((not isinstance(v, (int, float))) or v < 0 for v in weights.values()):
            errors.append(f"{group}: weights must be non-negative numbers")
        elif round(sum(weights.values()), 6) != 100:
            errors.append(f"{group}: weights sum to {sum(weights.values())}, expected 100")
    if "decision_thresholds" not in model:
        errors.append("decision_thresholds missing")
    return errors


def create_version(new_version, changes, notes, created_by, activate=False, path=None):
    """Adds a version derived from the active one with `changes` applied
    ({group: {key: value}}). Refuses an invalid model or an existing version."""
    path = Path(path) if path else default_path()
    data = load_all(path)
    versions = data.setdefault("versions", {})
    if str(new_version) in versions:
        raise ValueError(f"Model version {new_version} already exists")
    base = dict(versions[str(data["active_version"])])
    model = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for group, values in (changes or {}).items():
        model.setdefault(group, {}).update(values)
    model.update(created_at=_dt.date.today().isoformat(), created_by=created_by, notes=notes,
                 derived_from=str(data["active_version"]))
    errors = validate_model(model)
    if errors:
        raise ValueError("; ".join(errors))
    storage.backup_file(path)
    versions[str(new_version)] = model
    if activate:
        data["active_version"] = str(new_version)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return model


def set_active(version, path=None):
    path = Path(path) if path else default_path()
    data = load_all(path)
    if str(version) not in (data.get("versions") or {}):
        raise ValueError(f"Unknown model version {version}")
    storage.backup_file(path)
    data["active_version"] = str(version)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
