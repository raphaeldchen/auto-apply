from pipeline.discovery import seed


def test_load_seed_companies_reads_list(tmp_path):
    f = tmp_path / "seed.yaml"
    f.write_text("companies:\n  - Foo\n  - Bar\n")
    assert seed.load_seed_companies(str(f)) == ["Foo", "Bar"]


def test_load_seed_companies_empty_file(tmp_path):
    f = tmp_path / "seed.yaml"
    f.write_text("")
    assert seed.load_seed_companies(str(f)) == []
