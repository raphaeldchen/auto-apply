from models.job import Job
from pipeline.config import FilterConfig

def keyword_filter(job: Job, config: FilterConfig) -> bool:
    title = job.title.lower()
    if not any(p.lower() in title for p in config.include_patterns):
        return False
    if any(p.lower() in title for p in config.exclude_patterns):
        return False
    if config.level_patterns and not any(p.lower() in title for p in config.level_patterns):
        return False
    return True
