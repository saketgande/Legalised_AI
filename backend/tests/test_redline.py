"""Unit tests for the inbound redline engine's pure logic:
parsing, classification, and the deterministic/semantic checks. No DB.
"""
from app.services import redline as R


def test_extract_months_variants():
    assert R.extract_months("for six (6) months") == 6
    assert R.extract_months("twelve (12) months preceding") == 12
    assert R.extract_months("sixty (60) months from the Effective Date") == 60
    assert R.extract_months("a period of 3 months") == 3
    assert R.extract_months("two (2) years") == 24
    assert R.extract_months("no duration mentioned") is None


def test_detect_jurisdiction():
    assert R.detect_jurisdiction("governed by the laws of England and Wales") == "England & Wales"
    assert R.detect_jurisdiction("State of Delaware") == "Delaware"
    assert R.detect_jurisdiction("nothing here") is None


def test_segment_numbered_clauses():
    text = "1. Purpose\nUse it for X.\n2. Term\nLasts 12 months."
    segs = R.segment(text)
    assert len(segs) == 2
    assert segs[0][1] == "Purpose"
    assert "Use it for X" in segs[0][2]
    assert segs[1][1] == "Term"


def test_classify():
    assert R.classify("Limitation of Liability", "liability shall not exceed") == "limitation_of_liability"
    assert R.classify("Governing Law", "governed by the laws of") == "governing_law"
    assert R.classify("Term and Survival", "remain in effect for") == "term"
    assert R.classify("Random Heading", "unrelated prose about nothing") is None


def test_liability_check_flags_low_cap():
    # deterministic layer: numeric cap only (carve-out moved to the semantic layer)
    dev, checks = R._check_liability("total liability exceed the fees paid in the six (6) months")
    assert dev is True
    assert checks[0]["name"] == "liability_cap_floor"
    assert checks[0]["passed"] is False   # 6 < 12
    assert checks[0]["kind"] == "DETERMINISTIC"


def test_liability_check_passes_compliant_cap():
    dev, checks = R._check_liability("liability shall not exceed the fees paid in the twelve (12) months")
    assert dev is False


def test_term_check():
    assert R._check_term("in effect for sixty (60) months")[0] is True   # 60 > 24 -> deviation
    assert R._check_term("continues for 12 months")[0] is False


def test_governing_law_check():
    assert R._check_governing_law("laws of England and Wales")[0] is True
    assert R._check_governing_law("State of Delaware")[0] is False
