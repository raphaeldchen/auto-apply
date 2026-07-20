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


async def test_register_skips_existing(db_conn):
    from pipeline.db import upsert_company, get_all_companies
    from models.company import Company

    upsert_company(db_conn, Company(
        name="Foo", slug="foo", ats_type="workday",
        board_token="foo.wd5/Careers", status="active"))
    with patch("pipeline.discovery.seed.resolve_workday_company",
               new=AsyncMock()) as mock_resolve:
        result = await seed.register_seed_companies(db_conn, ["Foo"])
    mock_resolve.assert_not_called()
    assert result["skipped"] == ["Foo"]
    assert result["registered"] == []
    assert result["missed"] == []
    assert result["errored"] == []


async def test_register_records_hits_and_misses(db_conn):
    from pipeline.db import upsert_company, get_all_companies
    from models.company import Company

    async def fake_resolve(name):
        return ("workday", "bar.wd5/Careers") if name == "Bar" else None

    with patch("pipeline.discovery.seed.resolve_workday_company", new=fake_resolve):
        result = await seed.register_seed_companies(db_conn, ["Bar", "Baz"])
    assert result["registered"] == ["Bar"]
    assert result["missed"] == ["Baz"]
    assert result["errored"] == []
    names = {c.name for c in get_all_companies(db_conn)}
    assert "Bar" in names
    assert "Baz" not in names
    bar = next(c for c in get_all_companies(db_conn) if c.name == "Bar")
    assert bar.ats_type == "workday"
    assert bar.board_token == "bar.wd5/Careers"


async def test_register_continues_after_exception(db_conn):
    from pipeline.db import get_all_companies
    from models.company import Company

    async def fake_resolve(name):
        if name == "BadName":
            raise RuntimeError("Browser launch failed")
        if name == "GoodName":
            return ("workday", "good.wd5/Careers")
        return None

    with patch("pipeline.discovery.seed.resolve_workday_company", new=fake_resolve):
        result = await seed.register_seed_companies(db_conn, ["BadName", "GoodName", "MissName"])
    assert result["registered"] == ["GoodName"]
    assert result["missed"] == ["MissName"]
    assert result["errored"] == ["BadName"]
    names = {c.name for c in get_all_companies(db_conn)}
    assert "GoodName" in names
    assert "BadName" not in names
    assert "MissName" not in names
