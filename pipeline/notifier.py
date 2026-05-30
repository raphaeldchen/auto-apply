from models.digest import DigestResult

def format_digest(result: DigestResult) -> str:
    lines = [f"=== Auto-Apply Daily Digest — {result.date} ===\n"]
    for cd in result.companies:
        ats = cd.company.ats_type.capitalize() if cd.company.ats_type else "Unknown"
        lines.append(f"{cd.company.name} ({ats})")
        for job in cd.matched:
            score = f"{job.llm_score:.1f}" if job.llm_score is not None else "N/A"
            lines.append(f'  ✓ {job.title} — score {score} — "{job.llm_reason}"')
        for job in cd.kw_filtered:
            lines.append(f"  ✗ [kw_filtered] {job.title}")
        for job in cd.llm_filtered:
            score = f"{job.llm_score:.1f}" if job.llm_score is not None else "N/A"
            lines.append(f"  ✗ [llm_filtered] {job.title} — score {score}")
        if not (cd.matched or cd.kw_filtered or cd.llm_filtered):
            lines.append("  (no new postings)")
        lines.append("")
    for company in result.unsupported_companies:
        lines.append(f"{company.name}")
        lines.append(f'  ⚠ Unsupported ATS — run: python main.py add-company --name "{company.name}" --slug <slug>')
        lines.append("")
    total = sum(len(cd.matched) for cd in result.companies)
    lines.append(f"{total} new matched job(s). Run `python main.py show-matches` to review.")
    return "\n".join(lines)

def print_digest(result: DigestResult) -> None:
    print(format_digest(result))
