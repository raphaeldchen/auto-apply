import sqlite3
from models.job import Job
from pipeline.config import Config
from pipeline.db import update_job_filter_status
from pipeline.filter.keyword import keyword_filter
from pipeline.filter.llm_scorer import score_job

def filter_jobs(
    jobs: list[Job], config: Config, conn: sqlite3.Connection
) -> tuple[list[Job], list[Job], list[Job]]:
    matched, kw_filtered, llm_filtered = [], [], []
    for job in jobs:
        kw_reason = keyword_filter(job, config.filter)
        if kw_reason is not None:
            update_job_filter_status(conn, job.id, job.company_id, "kw_filtered", kw_reason=kw_reason)
            job.filter_status = "kw_filtered"
            job.kw_reason = kw_reason
            kw_filtered.append(job)
            continue
        score, reason = score_job(job, config.user)
        job.llm_score = score
        job.llm_reason = reason
        if score >= config.filter.llm_score_threshold:
            update_job_filter_status(conn, job.id, job.company_id, "matched", score, reason)
            job.filter_status = "matched"
            matched.append(job)
        else:
            update_job_filter_status(conn, job.id, job.company_id, "llm_filtered", score, reason)
            job.filter_status = "llm_filtered"
            llm_filtered.append(job)
    return matched, kw_filtered, llm_filtered
