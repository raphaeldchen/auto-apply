from models.company import Company
from models.job import Job
from models.digest import DigestResult, CompanyDigest
from pipeline.notifier import format_digest

def _company(name="Stripe", ats="greenhouse"):
    return Company(name=name, slug=name.lower(), ats_type=ats, board_token=name.lower(), status="active")

def _job(title="Senior SWE", score=8.5, reason="good match", status="matched"):
    j = Job(id="1", company_id=1, title=title, url=None, location=None, description=None)
    j.filter_status = status
    j.llm_score = score
    j.llm_reason = reason
    return j

def test_format_digest_includes_matched_job():
    digest = DigestResult(date="2026-05-30", companies=[CompanyDigest(company=_company(), matched=[_job()])])
    output = format_digest(digest)
    assert "Senior SWE" in output
    assert "8.5" in output
    assert "good match" in output
    assert "✓" in output

def test_format_digest_includes_kw_filtered_job():
    kw_job = _job(title="Staff Engineer", status="kw_filtered", score=None, reason=None)
    kw_job.llm_score = None
    digest = DigestResult(date="2026-05-30", companies=[CompanyDigest(company=_company(), kw_filtered=[kw_job])])
    output = format_digest(digest)
    assert "kw_filtered" in output
    assert "Staff Engineer" in output

def test_format_digest_includes_unsupported_company():
    unsupported = Company(name="Acme", slug="acme", ats_type=None, board_token=None, status="unsupported")
    digest = DigestResult(date="2026-05-30", unsupported_companies=[unsupported])
    output = format_digest(digest)
    assert "Acme" in output
    assert "Unsupported" in output

def test_format_digest_shows_total_matched_count():
    digest = DigestResult(date="2026-05-30", companies=[CompanyDigest(company=_company(), matched=[_job(), _job(title="SWE II")])])
    output = format_digest(digest)
    assert "2 new matched" in output
