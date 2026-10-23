"""Regression: keyword classification must match whole words ('First Appeal' is not an FIR)."""

import pytest

from services.extractor import extract_rules_only

CIVIL = (FIXTURES := __import__("pathlib").Path(__file__).parent / "fixtures" / "civil_case.txt").read_text(encoding="utf-8")
CRIMINAL = (FIXTURES.parent / "criminal_case.txt").read_text(encoding="utf-8")


def test_first_appeal_is_not_mistaken_for_an_fir():
    assert extract_rules_only(CIVIL).case_type == "civil"


def test_real_criminal_matter_still_classifies_as_criminal():
    assert extract_rules_only(CRIMINAL).case_type == "criminal"


@pytest.mark.parametrize("text,expected", [
    ("The firm filed a suit for recovery. First respondent denied. Fire insurance claim; decree sought.", "civil"),
    ("An FIR was lodged and the accused was arrested for murder.", "criminal"),
    ("The appellant is a firm of solicitors and the first respondent is a landlord seeking eviction.", "civil"),
])
def test_whole_word_matching(text, expected):
    assert extract_rules_only(text).case_type == expected
