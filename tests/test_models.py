from models.company import Company
from models.job import Job, RawJob
from models.digest import DigestResult, CompanyDigest


def test_company_defaults():
    c = Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                board_token="stripe", status="active")
    assert c.id is None
    assert c.detected_at is None


def test_job_defaults():
    j = Job(id="123", company_id=1, title="Senior SWE",
            url=None, location=None, description=None)
    assert j.filter_status == "new"
    assert j.llm_score is None


def test_raw_job_construction():
    r = RawJob(id="abc", title="Engineer", url=None, location=None, description=None)
    assert r.id == "abc"


def test_digest_result_defaults():
    d = DigestResult(date="2026-05-30")
    assert d.companies == []
    assert d.unsupported_companies == []


def test_company_digest_defaults():
    c = Company(name="X", slug="x", ats_type=None, board_token=None, status="active")
    cd = CompanyDigest(company=c)
    assert cd.matched == []
    assert cd.kw_filtered == []
    assert cd.llm_filtered == []
