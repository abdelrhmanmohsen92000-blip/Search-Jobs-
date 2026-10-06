#!/usr/bin/env python3
"""Compute the weighted 0-100 opportunity score defined in docs/scoring-model.md.

Usage:
    python3 score_opportunity.py <technical> <experience> <software> <project> <location> <eligibility> <company_signal>

Each argument is a sub-score from 0-10. Prints the final 0-100 score.
"""
import sys

WEIGHTS = {
    "technical": 0.25,
    "experience": 0.20,
    "software": 0.15,
    "project": 0.10,
    "location": 0.10,
    "eligibility": 0.10,
    "company_signal": 0.10,
}


def score_opportunity(technical, experience, software, project, location, eligibility, company_signal):
    for name, value in locals().items():
        if not 0 <= value <= 10:
            raise ValueError(f"{name} must be between 0 and 10, got {value}")
    weighted = (
        technical * WEIGHTS["technical"]
        + experience * WEIGHTS["experience"]
        + software * WEIGHTS["software"]
        + project * WEIGHTS["project"]
        + location * WEIGHTS["location"]
        + eligibility * WEIGHTS["eligibility"]
        + company_signal * WEIGHTS["company_signal"]
    )
    return round(weighted * 10, 1)


def main():
    if len(sys.argv) != 8:
        print(__doc__)
        sys.exit(1)
    values = [float(x) for x in sys.argv[1:]]
    print(score_opportunity(*values))


if __name__ == "__main__":
    main()
