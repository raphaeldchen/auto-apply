from models.job import Job
from pipeline.config import FilterConfig

def keyword_filter(job: Job, config: FilterConfig) -> str | None:
    title = job.title.lower()
    if not any(p.lower() in title for p in config.include_patterns):
        return "no include pattern match"
    matched_exclude = next((p for p in config.exclude_patterns if p.lower() in title), None)
    if matched_exclude:
        return f"excluded pattern: {matched_exclude}"
    if config.level_patterns and not any(p.lower() in title for p in config.level_patterns):
        return "no level pattern match"
    return None
