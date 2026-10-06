from scripts import company_intelligence, networking_intelligence
from scripts.lib import scoring


def test_company_classify_open_vacancy_wins_over_fit_score():
    company = {"hiring_activity": "2 open vacancies posted this week"}
    assert company_intelligence.classify(company, fit_score=10) == "OPEN_VACANCY"


def test_company_classify_hidden_opportunity_without_vacancy():
    company = {"hiring_activity": "", "bim_activity": "Growing BIM team"}
    assert company_intelligence.classify(company, fit_score=60) == "HIDDEN_OPPORTUNITY"


def test_company_classify_low_priority_when_fit_is_low():
    company = {}
    assert company_intelligence.classify(company, fit_score=10) == "LOW_PRIORITY"


def test_compute_fit_score_rewards_bim_and_hiring_signals():
    strong = {"bim_activity": "x", "hiring_activity": "x", "relevant_titles": "BIM Architect",
              "relevant_projects": "Residential", "website": "https://x.com"}
    weak = {}
    assert company_intelligence.compute_fit_score(strong) > company_intelligence.compute_fit_score(weak)


def test_networking_priority_bands_match_scoring_style():
    assert networking_intelligence.priority_for_score(90) == "A"
    assert networking_intelligence.priority_for_score(60) == "B"
    assert networking_intelligence.priority_for_score(10) == "C"


def test_networking_role_authority_founder_outranks_unknown_role():
    high = networking_intelligence.compute_network_value_score({"role": "Founder"})
    low = networking_intelligence.compute_network_value_score({"role": "Office Manager"})
    assert high > low


def test_scoring_priority_consistent_with_recommendation_direction():
    # higher score should never produce a "weaker" priority/recommendation than a lower score
    low = scoring.compute_weighted_score({k: 2 for k in scoring.WEIGHTS})
    high = scoring.compute_weighted_score({k: 9 for k in scoring.WEIGHTS})
    bands = [b for _, b in scoring.PRIORITY_BANDS]
    assert bands.index(scoring.priority_for_score(high)) < bands.index(scoring.priority_for_score(low))
