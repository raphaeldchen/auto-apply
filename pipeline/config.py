from dataclasses import dataclass, field
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
class LLMConfig:
    model: str
    base_url: str = "http://localhost:11434"

@dataclass
class NotificationsConfig:
    type: str

@dataclass
class ScheduleConfig:
    poll_interval_minutes: int = 60

@dataclass
class Config:
    user: UserConfig
    filter: FilterConfig
    llm: LLMConfig
    notifications: NotificationsConfig
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)

def load_config(path: str = "config.yaml") -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config(
        user=UserConfig(**data["user"]),
        filter=FilterConfig(**data["filter"]),
        llm=LLMConfig(**data["llm"]),
        notifications=NotificationsConfig(**data["notifications"]),
        schedule=ScheduleConfig(**data.get("schedule", {})),
    )
