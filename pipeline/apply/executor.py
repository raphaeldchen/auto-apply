"""Playwright form executor — fills a Greenhouse application from a plan.

Hard rules: this module NEVER clicks submit and never touches a CAPTCHA.
It fills exactly what the planner resolved (auto/answered/attachment),
skips sensitive and needs_input rows, reports fields the page didn't have,
and leaves review + submission to the human in the open browser window.
"""
from dataclasses import dataclass, field

from playwright.sync_api import sync_playwright

from pipeline.apply.planner import PlanRow

_FORM_MARKER = '[name="first_name"], #first_name'


@dataclass
class FillReport:
    filled: list[str] = field(default_factory=list)  # labels, read-back verified
    skipped: list[str] = field(default_factory=list)  # "label — reason"
    missing: list[str] = field(default_factory=list)  # labels not found on page
    failed: list[str] = field(default_factory=list)  # found but value didn't stick


def _find(page, name: str):
    for selector in (f'[name="{name}"]', f"#{name}"):
        loc = page.locator(selector)
        if loc.count():
            return loc.first
    return None


def fill_form(page, rows: list[PlanRow], attachments: dict[str, str],
              *, settle_ms: int = 1200, max_passes: int = 3) -> FillReport:
    """attachments maps field name (e.g. "resume") → local file path.

    After the fill loop, settle passes re-verify every filled text field:
    React boards can hydrate late and wipe programmatic values, so we wait,
    re-read, refill anything wiped, and repeat until stable. A field that
    never stabilizes is reported failed, not silently claimed."""
    report = FillReport()
    text_rows: list[PlanRow] = []
    for row in rows:
        if row.status in ("sensitive", "needs_input"):
            reason = row.note or row.status
            report.skipped.append(f"{row.label} — {reason}")
            continue

        if row.status == "attachment":
            path = attachments.get(row.name)
            if not path:
                report.skipped.append(f"{row.label} — no file provided")
                continue
            target = _find(page, row.name)
            if target is None:
                report.missing.append(row.label)
                continue
            target.set_input_files(path)
            report.filled.append(row.label)
            continue

        # auto / answered — every fill is read back and verified; React forms
        # can silently wipe programmatic values during hydration.
        target = _find(page, row.name)
        if target is None:
            report.missing.append(row.label)
            continue
        try:
            if "select" in row.type:
                target.select_option(label=row.answer)  # raises if no option
                report.filled.append(row.label)
                continue
            for attempt in range(2):
                target.fill(row.answer)
                if target.input_value() == row.answer:
                    report.filled.append(row.label)
                    text_rows.append(row)
                    break
                if attempt == 0:
                    page.wait_for_timeout(400)  # let hydration settle, retry
            else:
                report.failed.append(
                    f"{row.label} — value did not stick; enter it in the browser")
        except Exception as exc:
            report.failed.append(f"{row.label} — {exc}")

    _settle(page, text_rows, report, settle_ms, max_passes)
    return report


def _settle(page, text_rows: list[PlanRow], report: FillReport,
            settle_ms: int, max_passes: int) -> None:
    if not text_rows:
        return
    for _ in range(max_passes):
        page.wait_for_timeout(settle_ms)
        wiped = False
        for row in text_rows:
            target = _find(page, row.name)
            if target is not None and target.input_value() != row.answer:
                target.fill(row.answer)
                wiped = True
        if not wiped:
            return
    # never stabilized within max_passes: demote to failed, honestly
    for row in text_rows:
        target = _find(page, row.name)
        if target is None or target.input_value() != row.answer:
            report.filled.remove(row.label)
            report.failed.append(
                f"{row.label} — value kept getting wiped; enter it in the browser")


def _reveal_form(page) -> None:
    """Some boards show the form only after an Apply link — clicking that is
    navigation, not submission."""
    if page.locator(_FORM_MARKER).count():
        return
    apply_link = page.locator('a:has-text("Apply"), button:has-text("Apply")')
    if apply_link.count():
        apply_link.first.click()
    try:
        page.wait_for_selector(_FORM_MARKER, timeout=8000)
        # React boards hydrate after the inputs appear and can wipe values
        # filled too early — wait for the network to go quiet first.
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass  # fill_form verifies by read-back either way


def run_application(url: str, rows: list[PlanRow], attachments: dict[str, str],
                    *, headless: bool = False, pause=None) -> FillReport:
    """Open the job page, fill the plan, then hand off: `pause` is called
    while the browser is still open so the human can review and submit.
    This function never submits."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded")
            _reveal_form(page)
            report = fill_form(page, rows, attachments)
            if pause is not None:
                pause()
            return report
        finally:
            browser.close()
