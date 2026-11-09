"""Expired OAuth states are swept on a schedule, not only on reuse."""

from app.tasks import pricing_tasks


def test_cleanup_job_registered(monkeypatch):
    added = {}

    class _Sched:
        def add_job(self, func, trigger, id, **_kw):
            added[id] = func

        def start(self):
            pass

    monkeypatch.setattr(pricing_tasks, "AsyncIOScheduler", _Sched)
    monkeypatch.setattr(pricing_tasks, "scheduler", None)
    pricing_tasks.start_scheduler()
    assert added["cleanup_oauth_states"] is pricing_tasks.cleanup_oauth_states_task
    monkeypatch.setattr(pricing_tasks, "scheduler", None)
