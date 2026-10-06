from scripts.lib import normalize


def test_normalize_fills_defaults_for_minimal_input():
    raw = {"company": "Acme", "job_title": "BIM Architect"}
    opp = normalize.normalize_opportunity(raw)
    assert opp["company"] == "Acme"
    assert opp["job_title"] == "BIM Architect"
    assert opp["status"] == "new"
    assert opp["skills_required"] == []
    assert opp["source"] == "unknown"
    assert opp["id"]  # auto-generated


def test_normalize_accepts_title_alias():
    raw = {"company": "Acme", "title": "Interior Designer"}
    opp = normalize.normalize_opportunity(raw)
    assert opp["job_title"] == "Interior Designer"


def test_normalize_resolves_region_from_country():
    raw = {"company": "Acme", "job_title": "BIM Architect", "country": "United Arab Emirates"}
    opp = normalize.normalize_opportunity(raw)
    assert opp["region"] == "gulf"


def test_normalize_unknown_country_is_unclassified():
    raw = {"company": "Acme", "job_title": "BIM Architect", "country": "Atlantis"}
    opp = normalize.normalize_opportunity(raw)
    assert opp["region"] == "unclassified"


def test_normalize_coerces_comma_string_to_list():
    raw = {"company": "Acme", "job_title": "BIM Architect", "skills_required": "Revit, Navisworks"}
    opp = normalize.normalize_opportunity(raw)
    assert opp["skills_required"] == ["Revit", "Navisworks"]


def test_normalize_coerces_bool_like_strings():
    raw = {"company": "Acme", "job_title": "BIM Architect", "remote": "yes", "visa_sponsorship": "no"}
    opp = normalize.normalize_opportunity(raw)
    assert opp["remote"] is True
    assert opp["visa_sponsorship"] is False


def test_normalize_preserves_sub_scores_passthrough():
    raw = {"company": "Acme", "job_title": "BIM Architect", "_sub_scores": {"technical": 9}}
    opp = normalize.normalize_opportunity(raw)
    assert opp["_sub_scores"] == {"technical": 9}


def test_validate_opportunity_valid_record_has_no_errors():
    raw = {"company": "Acme", "job_title": "BIM Architect"}
    opp = normalize.normalize_opportunity(raw)
    opp.pop("_sub_scores", None)
    assert normalize.validate_opportunity(opp) == []


def test_validate_opportunity_flags_missing_required_field():
    opp = normalize.normalize_opportunity({"company": "Acme", "job_title": "BIM Architect"})
    opp.pop("_sub_scores", None)
    opp["company"] = ""
    errors = normalize.validate_opportunity(opp)
    assert errors  # empty string fails minLength-less but required check via truthiness in our own contract
