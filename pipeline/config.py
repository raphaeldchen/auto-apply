from dataclasses import dataclass, field
import yaml

@dataclass
class UserConfig:
    desired_role: str
    desired_level: str
    resume_path: str
    profile_path: str = "profile.yaml"
    answers_path: str = "answers.yaml"

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

# Company tier → generation model. Reach companies get the strongest model;
# the harness verifier guarantees truthfulness regardless of model choice,
# so this dial trades polish for cost only.
DEFAULT_TIER_MODELS = {
    "reach": "claude-opus-4-8",
    "target": "claude-sonnet-5",
    "standard": "claude-haiku-4-5",
}

@dataclass
class GenerationConfig:
    tiers: dict = field(default_factory=lambda: dict(DEFAULT_TIER_MODELS))

    def model_for(self, tier: str) -> str:
        return self.tiers.get(tier, self.tiers["standard"])

@dataclass
class Config:
    user: UserConfig
    filter: FilterConfig
    llm: LLMConfig
    notifications: NotificationsConfig
    generation: GenerationConfig = field(default_factory=GenerationConfig)

def load_config(path: str = "config.yaml") -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    gen_data = data.get("generation") or {}
    tiers = {**DEFAULT_TIER_MODELS, **(gen_data.get("tiers") or {})}
    return Config(
        user=UserConfig(**data["user"]),
        filter=FilterConfig(**data["filter"]),
        llm=LLMConfig(**data["llm"]),
        notifications=NotificationsConfig(**data["notifications"]),
        generation=GenerationConfig(tiers=tiers),
    )
