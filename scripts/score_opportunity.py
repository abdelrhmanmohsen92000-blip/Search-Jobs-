#!/usr/bin/env python3
"""Compute the weighted 0-100 opportunity score (V1.1 model, see
docs/scoring-model.md and scripts/lib/scoring.py).

V1.1 weights (replaces the original 7-criterion model):
    technical=25 experience=20 software=15 project=10 location=10
    eligibility=10 career_value=5 compensation=5

Usage:
    python3 score_opportunity.py <technical> <experience> <software> <project> \
        <location> <eligibility> <career_value> <compensation>

Each argument is a sub-score from 0-10. Prints the final 0-100 score.
For the full result object (priority, recommendation, matched/missing
skills, strengths/risks) use scripts/lib/scoring.score_opportunity_record
or `python3 career_hunter.py score`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib.scoring import WEIGHTS, compute_weighted_score  # noqa: E402

ARG_ORDER = ["technical", "experience", "software", "project", "location", "eligibility", "career_value", "compensation"]


def main():
    if len(sys.argv) != len(ARG_ORDER) + 1:
        print(__doc__)
        print(f"Expected order: {' '.join(ARG_ORDER)}  (weights: {WEIGHTS})")
        sys.exit(1)
    values = [float(x) for x in sys.argv[1:]]
    sub_scores = dict(zip(ARG_ORDER, values))
    print(compute_weighted_score(sub_scores))


if __name__ == "__main__":
    main()
