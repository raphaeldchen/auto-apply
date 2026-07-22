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
