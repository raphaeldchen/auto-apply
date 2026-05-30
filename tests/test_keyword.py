from models.job import Job
from pipeline.config import FilterConfig
from pipeline.filter.keyword import keyword_filter

def _job(title: str) -> Job:
    return Job(id="1", company_id=1, title=title, url=None, location=None, description=None)

def _config(**overrides) -> FilterConfig:
    defaults = {"include_patterns": ["software engineer"], "exclude_patterns": ["intern", "manager"], "level_patterns": ["senior"], "llm_score_threshold": 7.0}
    defaults.update(overrides)
    return FilterConfig(**defaults)

def test_matching_include_pattern_passes():
    assert keyword_filter(_job("Senior Software Engineer"), _config()) is True

def test_no_include_match_fails():
    assert keyword_filter(_job("Product Manager"), _config()) is False

def test_exclude_pattern_rejects():
    assert keyword_filter(_job("Software Engineer Intern"), _config()) is False

def test_no_level_match_fails_when_level_patterns_set():
    assert keyword_filter(_job("Software Engineer"), _config()) is False

def test_empty_level_patterns_allows_any_level():
    assert keyword_filter(_job("Software Engineer"), _config(level_patterns=[])) is True

def test_case_insensitive_matching():
    assert keyword_filter(_job("SENIOR SOFTWARE ENGINEER"), _config()) is True
