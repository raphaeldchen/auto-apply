import re
from unittest.mock import MagicMock

from pipeline.apply.executor import fill_form
from pipeline.apply.planner import PlanRow


def _row(status, label="Q", name="field", type="input_text",
         answer=None, **kwargs):
    return PlanRow(label=label, name=name, required=True, status=status,
                   type=type, answer=answer, **kwargs)


def _key(selector):
    if selector.startswith("#"):
        return selector[1:]
    m = re.search(r'name="([^"]+)"', selector)
    return m.group(1) if m else selector


def _page(present):
    """Mock page whose locator() 'finds' only field keys in `present`.
    fill() mocks a well-behaved input: read-back returns what was filled."""
    page = MagicMock()
    locators = {}

    def locator(sel):
        loc = locators.setdefault(sel, MagicMock())
        loc.count.return_value = 1 if _key(sel) in present else 0
        first = loc.first
        if not first.fill.side_effect:
            first.fill.side_effect = (
                lambda v, f=first: f.input_value.configure_mock(return_value=v))
        return loc

    page.locator.side_effect = locator
    return page, locators


def test_fills_text_fields(tmp_path):
    page, locs = _page({"first_name"})
    report = fill_form(page, [
        _row("auto", label="First Name", name="first_name", answer="Ada")], {})
    locs['[name="first_name"]'].first.fill.assert_called_once_with("Ada")
    assert report.filled == ["First Name"]


def test_selects_use_option_label():
    page, locs = _page({"q1"})
    fill_form(page, [
        _row("answered", label="Auth?", name="q1",
             type="multi_value_single_select", answer="Yes",
             options=["Yes", "No"])], {})
    locs['[name="q1"]'].first.select_option.assert_called_once_with(label="Yes")


def test_id_selector_fallback():
    page, locs = _page({"email"})
    # [name="email"] misses; #email hits — simulate by making name-selector
    # key different from present key via a custom present set.
    page2, locs2 = _page(set())

    def locator(sel):
        loc = locs2.setdefault(sel, MagicMock())
        loc.count.return_value = 1 if sel == "#email" else 0
        first = loc.first
        if not first.fill.side_effect:
            first.fill.side_effect = (
                lambda v, f=first: f.input_value.configure_mock(return_value=v))
        return loc

    page2.locator.side_effect = locator
    report = fill_form(page2, [
        _row("auto", label="Email", name="email", answer="a@b.c")], {})
    locs2["#email"].first.fill.assert_called_once_with("a@b.c")
    assert report.filled == ["Email"]


def test_attachment_uploads_provided_file():
    page, locs = _page({"resume"})
    fill_form(page, [
        _row("attachment", label="Resume", name="resume", type="input_file")],
        {"resume": "/tmp/resume.pdf"})
    locs['[name="resume"]'].first.set_input_files.assert_called_once_with(
        "/tmp/resume.pdf")


def test_attachment_without_file_skipped():
    page, locs = _page({"resume"})
    report = fill_form(page, [
        _row("attachment", label="Resume", name="resume", type="input_file")], {})
    page.locator.assert_not_called()  # skipped before touching the page
    assert any("Resume" in s for s in report.skipped)


def test_sensitive_and_needs_input_skipped():
    page, _ = _page({"q1", "q2"})
    report = fill_form(page, [
        _row("sensitive", label="Gender", name="q1"),
        _row("needs_input", label="Essay", name="q2"),
    ], {})
    assert report.filled == []
    assert len(report.skipped) == 2


def test_missing_field_reported_not_fatal():
    page, _ = _page(set())
    report = fill_form(page, [
        _row("auto", label="First Name", name="first_name", answer="Ada")], {})
    assert report.missing == ["First Name"]
    assert report.filled == []


def test_text_fill_verified_by_readback():
    # A React form that swallows the value (hydration wipe): the fill must be
    # retried once and then reported as failed — never as filled.
    page = MagicMock()
    loc = MagicMock()
    loc.count.return_value = 1
    loc.first.input_value.return_value = ""  # value never sticks
    page.locator.return_value = loc
    report = fill_form(page, [
        _row("auto", label="First Name", name="first_name", answer="Ada")], {})
    assert loc.first.fill.call_count == 2  # initial + one retry
    assert report.filled == []
    assert any("First Name" in f for f in report.failed)


def test_select_option_error_reported_not_fatal():
    page = MagicMock()
    loc = MagicMock()
    loc.count.return_value = 1
    loc.first.select_option.side_effect = Exception("no option matched")
    page.locator.return_value = loc
    report = fill_form(page, [
        _row("answered", label="Auth?", name="q1",
             type="multi_value_single_select", answer="Yes")], {})
    assert report.filled == []
    assert any("Auth?" in f for f in report.failed)


class _FakeInput:
    """Stateful input stub: remembers its value and counts fills."""

    def __init__(self):
        self.value = ""
        self.fills = 0

    def fill(self, v):
        self.value = v
        self.fills += 1

    def input_value(self):
        return self.value


def test_late_hydration_wipe_detected_and_refilled():
    # The value sticks at fill time, then React hydration wipes it AFTER the
    # fill loop. A settle pass must catch the wipe and refill.
    fake = _FakeInput()
    page = MagicMock()
    loc = MagicMock()
    loc.count.return_value = 1
    loc.first.fill.side_effect = fake.fill
    loc.first.input_value.side_effect = fake.input_value
    page.locator.return_value = loc
    hydrated = {"done": False}

    def wait(ms):
        if not hydrated["done"]:
            fake.value = ""  # hydration wipe during the settle wait
            hydrated["done"] = True

    page.wait_for_timeout.side_effect = wait
    report = fill_form(page, [
        _row("auto", label="First Name", name="first_name", answer="Ada")], {})
    assert fake.fills == 2  # initial + refill after the wipe
    assert fake.value == "Ada"
    assert report.filled == ["First Name"]
    assert report.failed == []


def test_run_application_wires_browser_and_pauses(tmp_path):
    from unittest.mock import patch
    from pipeline.apply.executor import run_application

    pause = MagicMock()
    with patch("pipeline.apply.executor.sync_playwright") as sp:
        page = MagicMock()
        browser = MagicMock()
        browser.new_page.return_value = page
        sp.return_value.__enter__.return_value.chromium.launch.return_value = browser
        report = run_application("https://boards.greenhouse.io/x/jobs/1",
                                 [], {}, headless=False, pause=pause)
    page.goto.assert_called_once()
    assert page.goto.call_args.args[0] == "https://boards.greenhouse.io/x/jobs/1"
    launch_kwargs = sp.return_value.__enter__.return_value.chromium.launch.call_args.kwargs
    assert launch_kwargs["headless"] is False
    pause.assert_called_once()
    browser.close.assert_called_once()
    assert report.filled == []


def test_never_clicks_anything():
    page, locs = _page({"first_name", "q1", "resume"})
    fill_form(page, [
        _row("auto", label="First Name", name="first_name", answer="Ada"),
        _row("answered", label="Auth?", name="q1",
             type="multi_value_single_select", answer="Yes"),
        _row("attachment", label="Resume", name="resume", type="input_file"),
    ], {"resume": "/x.pdf"})
    page.click.assert_not_called()
    for loc in locs.values():
        loc.click.assert_not_called()
        loc.first.click.assert_not_called()
