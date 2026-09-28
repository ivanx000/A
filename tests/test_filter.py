from app.filtering.filter import (
    _intern_match,
    _keyword_match,
    _location_ok,
    filter_reason,
    is_relevant,
)


# ---------------------------------------------------------------------------
# _keyword_match
# ---------------------------------------------------------------------------

def test_keyword_match_hits_on_title():
    assert _keyword_match("Machine Learning Intern", "some description")


def test_keyword_match_hits_on_description():
    assert _keyword_match("Intern", "We need a full-stack developer")


def test_keyword_match_is_case_insensitive():
    assert _keyword_match("SAAS Intern", "")


def test_keyword_match_requires_word_boundary():
    # "saas" inside "bonsaas" shouldn't count as a keyword hit
    assert not _keyword_match("Bonsaas Intern", "")


def test_keyword_match_no_target_keywords():
    assert not _keyword_match("Barista Intern", "serving coffee")


def test_keyword_match_broad_tech_titles():
    assert _keyword_match("Engineer Intern", "")
    assert _keyword_match("Student, Emerging Technologies (Winter 2027)", "")
    assert _keyword_match("PepsiCo Canada: Commercial IT Winter 2027 Co-op", "")


def test_keyword_match_broad_terms_title_only():
    assert not _keyword_match("Barista Intern", "Our data shows customers love it")


def test_keyword_match_broad_terms_skip_other_disciplines():
    assert not _keyword_match("Mechanical Engineering Co-op", "")
    # a specific target keyword still wins
    assert _keyword_match("AI & ML Intern - Electrical Engineer", "")


# ---------------------------------------------------------------------------
# _intern_match
# ---------------------------------------------------------------------------

def test_intern_match_title_says_intern():
    assert _intern_match("Software Engineering Intern", "")


def test_intern_match_co_op_variants():
    assert _intern_match("Co-op Developer", "")
    assert _intern_match("Coop Developer", "")


def test_intern_match_student_title():
    assert _intern_match("Student Software Developer", "")


def test_intern_match_rejects_when_no_signal_in_title():
    assert not _intern_match("Software Engineer", "we love hiring interns and co-ops")


def test_intern_match_rejects_senior_even_if_title_mentions_intern():
    assert not _intern_match("Senior Engineer (mentors interns)", "")


def test_intern_match_rejects_new_grad_and_junior_titles():
    assert not _intern_match("New Grad Software Engineer", "")
    assert not _intern_match("Junior Developer", "")


def test_intern_match_allows_junior_co_op():
    assert _intern_match("Junior Full Stack Developer Coop", "")


def test_intern_match_pey_and_french_titles():
    assert _intern_match("2027 Investor Services, PEY Software Engineer (12 months)", "")
    assert _intern_match("Stagiaire ou étudiant(e) en alternance, Données", "")


def test_intern_match_term_with_length():
    assert _intern_match("2027 Wealth Management, Winter Technology/Developer (4-16 months)", "")
    assert _intern_match("Data Scientist, GTB, Winter 2027 Analyst (8 Months)", "")
    assert not _intern_match("Software Developer, Summer start", "")


def test_intern_match_only_checks_title_not_description():
    # Description mentioning "intern" doesn't count if the title doesn't
    assert not _intern_match("Software Engineer", "This role involves mentoring interns")


# ---------------------------------------------------------------------------
# _location_ok
# ---------------------------------------------------------------------------

def test_location_ok_remote_anywhere():
    assert _location_ok("Remote ML Intern", "work from anywhere")


def test_location_ok_onsite_in_canada():
    assert _location_ok("Software Intern", "onsite in Toronto, Ontario")


def test_location_ok_rejects_onsite_outside_canada():
    assert not _location_ok("Software Intern", "onsite in New York")


def test_location_ok_hybrid_outside_canada_rejected():
    assert not _location_ok("Software Intern", "hybrid role based in Austin, TX")


def test_location_ok_no_location_signal_defaults_to_allowed():
    assert _location_ok("Software Intern", "great opportunity to learn")


def test_location_ok_remote_wins_even_if_onsite_mentioned_elsewhere():
    # e.g. "remote-first, occasional onsite events" — remote signal present
    assert _location_ok("Remote Intern", "remote-first team, optional onsite socials")


# ---------------------------------------------------------------------------
# is_relevant / filter_reason (integration of all three checks)
# ---------------------------------------------------------------------------

def test_is_relevant_true_for_qualifying_posting():
    assert is_relevant(
        "Machine Learning Intern",
        "Remote internship working on ML pipelines.",
    )


def test_is_relevant_false_missing_keyword():
    assert not is_relevant("Intern", "Remote internship, no relevant tech mentioned.")


def test_is_relevant_false_not_intern_role():
    assert not is_relevant(
        "Senior Software Engineer",
        "Remote, full-stack, 10 years experience required.",
    )


def test_is_relevant_false_bad_location():
    assert not is_relevant(
        "Software Engineering Intern",
        "Onsite in San Francisco, full-stack team.",
    )


def test_filter_reason_reports_keyword_mismatch_first():
    assert filter_reason("Intern", "no matching keywords here") == "keyword_mismatch"


def test_filter_reason_reports_not_intern_role():
    assert filter_reason("Software Engineer", "full-stack, remote") == "not_intern_role"


def test_filter_reason_reports_location_rejected():
    assert (
        filter_reason("Software Intern", "onsite in Chicago, full-stack")
        == "location_rejected"
    )


def test_filter_reason_pass():
    assert filter_reason("Full Stack Intern", "remote, full-stack team") == "pass"


# ---------------------------------------------------------------------------
# Software + AI/ML titles (keyword list matches on word boundaries)
# ---------------------------------------------------------------------------

def test_keyword_match_software_and_ai_ml_title_variants():
    for title in [
        "Software Engineering Intern",
        "Software Development Co-op",
        "ML Intern",
        "AI Research Intern",
        "Data Science Intern",
    ]:
        assert _keyword_match(title, ""), title


def test_keyword_match_ignores_ai_inside_words():
    assert not _keyword_match("Retail Intern", "maintain displays")


# ---------------------------------------------------------------------------
# Strict location (company career sites)
# ---------------------------------------------------------------------------

def test_location_strict_rejects_bare_non_canadian_city():
    # No onsite/hybrid wording, so the lenient check would let this through
    assert _location_ok("Software Intern", "San Francisco, CA")
    assert not _location_ok("Software Intern", "San Francisco, CA", strict=True)


def test_location_strict_allows_canada_or_remote():
    assert _location_ok("Software Intern", "Toronto, ON", strict=True)
    assert _location_ok("Software Intern", "Remote", strict=True)


def test_location_strict_rejects_missing_location():
    assert not _location_ok("Software Intern", "", strict=True)
