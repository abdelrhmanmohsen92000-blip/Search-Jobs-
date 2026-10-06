from scripts.lib import dedup


def _opp(company, title, city, url):
    return {"company": company, "job_title": title, "city": city, "source_url": url}


def test_make_id_deterministic():
    id1 = dedup.make_id("Acme", "BIM Architect", "Dubai", "https://x.com/1")
    id2 = dedup.make_id("Acme", "BIM Architect", "Dubai", "https://x.com/1")
    assert id1 == id2


def test_make_id_normalizes_case_and_whitespace():
    id1 = dedup.make_id("Acme Corp", "BIM Architect", "Dubai", "https://x.com/1")
    id2 = dedup.make_id("  acme   corp  ", "bim architect", "dubai", "https://x.com/1")
    assert id1 == id2


def test_exact_duplicate_dropped():
    a = _opp("Acme", "BIM Architect", "Dubai", "https://x.com/1")
    b = _opp("Acme", "BIM Architect", "Dubai", "https://x.com/1")
    unique, duplicates = dedup.deduplicate([a, b])
    assert len(unique) == 1
    assert len(duplicates) == 1


def test_distinct_opportunities_kept():
    a = _opp("Acme", "BIM Architect", "Dubai", "https://x.com/1")
    b = _opp("Beta", "Interior Designer", "London", "https://x.com/2")
    unique, duplicates = dedup.deduplicate([a, b])
    assert len(unique) == 2
    assert len(duplicates) == 0


def test_fuzzy_match_same_posting_different_url():
    a = _opp("Acme Corporation", "Senior BIM Architect", "Dubai", "https://boardA.com/job/1")
    b = _opp("Acme Corp", "Senior BIM Architect", "Dubai", "https://boardB.com/job/1")
    assert dedup.fuzzy_match(a, b) is True


def test_fuzzy_match_requires_same_location():
    a = _opp("Acme Corporation", "Senior BIM Architect", "Dubai", "https://boardA.com/job/1")
    b = _opp("Acme Corporation", "Senior BIM Architect", "London", "https://boardB.com/job/1")
    assert dedup.fuzzy_match(a, b) is False


def test_deduplicate_catches_fuzzy_duplicate_across_sources():
    a = _opp("Acme Corporation", "Senior BIM Architect", "Dubai", "https://boardA.com/job/1")
    b = _opp("Acme Corp", "Senior BIM Architect", "Dubai", "https://boardB.com/job/1")
    unique, duplicates = dedup.deduplicate([a, b])
    assert len(unique) == 1
    assert len(duplicates) == 1
