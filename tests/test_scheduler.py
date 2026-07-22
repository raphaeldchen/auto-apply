from pipeline.config import Config, UserConfig, FilterConfig, LLMConfig, NotificationsConfig, ScheduleConfig


def _config(interval):
    return Config(
        user=UserConfig(desired_role="SE", desired_level="Senior", resume_path="./r.pdf"),
        filter=FilterConfig(include_patterns=[], exclude_patterns=[], level_patterns=[], llm_score_threshold=7.0),
        llm=LLMConfig(model="llama3.2"),
        notifications=NotificationsConfig(type="terminal"),
        schedule=ScheduleConfig(poll_interval_minutes=interval),
    )


def test_scheduler_uses_interval_trigger(monkeypatch):
    from pipeline import scheduler as sched_mod
    captured = {}

    class FakeScheduler:
        def add_job(self, func, trigger, **kwargs):
            captured["trigger"] = trigger
            captured["kwargs"] = kwargs

        def start(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(sched_mod, "BlockingScheduler", lambda: FakeScheduler())
    try:
        sched_mod.start_scheduler(_config(45), ":memory:")
    except KeyboardInterrupt:
        pass
    assert captured["trigger"] == "interval"
    assert captured["kwargs"]["minutes"] == 45


def test_scheduler_kicks_off_immediately(monkeypatch):
    from datetime import datetime
    from pipeline import scheduler as sched_mod
    captured = {}

    class FakeScheduler:
        def add_job(self, func, trigger, **kwargs):
            captured["kwargs"] = kwargs

        def start(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(sched_mod, "BlockingScheduler", lambda: FakeScheduler())
    try:
        sched_mod.start_scheduler(_config(60), ":memory:")
    except KeyboardInterrupt:
        pass
    assert isinstance(captured["kwargs"]["next_run_time"], datetime)
