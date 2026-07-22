from pipeline.materials.aliases import normalize_term, find_terms


def test_normalize_term_maps_alias_to_canonical():
    assert normalize_term("postgres") == "PostgreSQL"
    assert normalize_term("k8s") == "Kubernetes"
    assert normalize_term("sklearn") == "scikit-learn"


def test_normalize_term_is_case_insensitive():
    assert normalize_term("K8S") == "Kubernetes"
    assert normalize_term("PYTORCH") == "PyTorch"


def test_normalize_term_unknown_returns_stripped_input():
    assert normalize_term("  SomeNicheTool  ") == "SomeNicheTool"


def test_find_terms_counts_occurrences():
    text = "We use Python daily. python is our main language."
    hits = find_terms(text)
    assert hits["Python"] == 2


def test_find_terms_aggregates_aliases_into_canonical():
    text = "Experience with ML required; machine learning projects a plus."
    hits = find_terms(text)
    assert hits["Machine Learning"] == 2


def test_find_terms_respects_word_boundaries():
    # "ml" inside "html" must not count as Machine Learning
    hits = find_terms("Strong html and css skills.")
    assert "Machine Learning" not in hits


def test_find_terms_short_terms_are_case_sensitive():
    assert "Go" not in find_terms("You will go to conferences.")
    assert "Go" in find_terms("Services written in Go and Rust.")
    assert "R" in find_terms("Fluency in R or Python.")
    assert "R" not in find_terms("read the docs carefully")


def test_find_terms_handles_symbol_terms():
    hits = find_terms("Modern C++ codebase; some C# tooling.")
    assert hits["C++"] == 1
    assert hits["C#"] == 1
    assert "C" not in hits


def test_find_terms_matches_multiword_across_hyphens():
    hits = find_terms("Looking for machine-learning experience.")
    assert hits["Machine Learning"] == 1


def test_find_terms_includes_extra_terms():
    hits = find_terms("Built agents with LangGraph.", extra_terms=["LangGraph"])
    assert hits["LangGraph"] == 1


def test_find_terms_prefers_longest_match():
    # "JavaScript" must not also count as "Java"
    hits = find_terms("Frontend in JavaScript.")
    assert "JavaScript" in hits
    assert "Java" not in hits
