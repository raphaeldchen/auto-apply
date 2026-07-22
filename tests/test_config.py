import pytest
import yaml
from pathlib import Path
from pipeline.config import load_config, Config, UserConfig, FilterConfig

@pytest.fixture
def config_file(tmp_path):
    content = {
        "user": {"desired_role": "Software Engineer", "desired_level": "Senior", "resume_path": "./resume.pdf"},
        "filter": {"include_patterns": ["software engineer"], "exclude_patterns": ["intern"], "level_patterns": ["senior"], "llm_score_threshold": 7.0},
        "llm": {"model": "llama3.2", "base_url": "http://localhost:11434"},
        "notifications": {"type": "terminal"},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(content))
    return str(p)

def test_load_config_returns_typed_config(config_file):
    config = load_config(config_file)
    assert isinstance(config, Config)
    assert isinstance(config.user, UserConfig)
    assert isinstance(config.filter, FilterConfig)

def test_load_config_user_fields(config_file):
    config = load_config(config_file)
    assert config.user.desired_role == "Software Engineer"
    assert config.user.desired_level == "Senior"

def test_load_config_filter_fields(config_file):
    config = load_config(config_file)
    assert config.filter.llm_score_threshold == 7.0
    assert "intern" in config.filter.exclude_patterns

def test_load_config_profile_path_defaults(config_file):
    config = load_config(config_file)
    assert config.user.profile_path == "profile.yaml"

def test_generation_defaults_when_block_absent(config_file):
    config = load_config(config_file)
    assert config.generation.tiers == {
        "reach": "claude-opus-4-8",
        "target": "claude-sonnet-5",
        "standard": "claude-haiku-4-5",
    }

def test_generation_partial_override_merges_with_defaults(tmp_path, config_file):
    data = yaml.safe_load(Path(config_file).read_text())
    data["generation"] = {"tiers": {"standard": "my-local-model"}}
    p = tmp_path / "override.yaml"
    p.write_text(yaml.dump(data))
    config = load_config(str(p))
    assert config.generation.tiers["standard"] == "my-local-model"
    assert config.generation.tiers["reach"] == "claude-opus-4-8"

def test_generation_model_for_tier_falls_back_to_standard(config_file):
    config = load_config(config_file)
    assert config.generation.model_for("reach") == "claude-opus-4-8"
    assert config.generation.model_for("unknown-tier") == "claude-haiku-4-5"
