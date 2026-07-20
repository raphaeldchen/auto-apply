from unittest.mock import patch, AsyncMock

from pipeline.discovery import seed


def test_load_seed_companies_reads_list(tmp_path):
    f = tmp_path / "seed.yaml"
    f.write_text("companies:\n  - Foo\n  - Bar\n")
    assert seed.load_seed_companies(str(f)) == ["Foo", "Bar"]


def test_load_seed_companies_empty_file(tmp_path):
    f = tmp_path / "seed.yaml"
    f.write_text("")
    assert seed.load_seed_companies(str(f)) == []


async def test_resolve_workday_company_returns_first_hit():
    with patch("pipeline.discovery.seed.generate_slug_variants", return_value=["a", "b"]), \
         patch("pipeline.discovery.seed.probe_workday",
               new=AsyncMock(side_effect=[None, ("workday", "b.wd5/Careers")])):
        result = await seed.resolve_workday_company("Foo")
    assert result == ("workday", "b.wd5/Careers")


async def test_resolve_workday_company_returns_none_when_no_hit():
    with patch("pipeline.discovery.seed.generate_slug_variants", return_value=["a", "b"]), \
         patch("pipeline.discovery.seed.probe_workday", new=AsyncMock(return_value=None)):
        result = await seed.resolve_workday_company("Nope")
    assert result is None
