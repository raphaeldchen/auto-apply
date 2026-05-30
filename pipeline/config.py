from dataclasses import dataclass
import yaml

@dataclass
class UserConfig:
    desired_role: str
    desired_level: str
    resume_path: str

@dataclass
class FilterConfig:
    include_patterns: list[str]
    exclude_patterns: list[str]
    level_patterns: list[str]
    llm_score_threshold: float

@dataclass
class NotificationsConfig:
    type: str

@dataclass
class Config:
    user: UserConfig
    filter: FilterConfig
    notifications: NotificationsConfig

def load_config(path: str = "config.yaml") -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config(
        user=UserConfig(**data["user"]),
        filter=FilterConfig(**data["filter"]),
        notifications=NotificationsConfig(**data["notifications"]),
    )
