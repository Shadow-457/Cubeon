"""Provider failures recover the modpack list and keep a working provider usable."""
import inspect
import os
import sys
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import thread_safe_ui
from cubeon.theme import THEME, section_label
from _fuzz_common import FakePage
from ui import modpacks_tab as packs


class DeferredThread:
    jobs = []

    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.jobs.append(self.target)


def find_functions(*roots):
    found = {}

    def visit(fn):
        if not inspect.isfunction(fn) or fn.__name__ in found:
            return
        found[fn.__name__] = fn
        for child in inspect.getclosurevars(fn).nonlocals.values():
            visit(child)

    for root in roots:
        visit(root)
    return found


def offline(*args, **kwargs):
    raise OSError("offline fixture")


hit = {"project_id": "test", "slug": "test", "title": "Test pack",
       "description": "Test", "downloads": 1, "provider": "modrinth"}
with (patch.object(packs.threading, "Thread", DeferredThread),
      patch.object(packs.core, "list_installed_modpacks", return_value=[]),
      patch.object(packs._icons, "prefetch"),
      patch.object(thread_safe_ui, "refresh")):
    tab, installed, load = packs.build_modpacks_tab(
        FakePage(), {}, {}, section_label=section_label, go_to_pack=lambda meta: None, **THEME)
    functions = find_functions(load, installed)
    scope = inspect.getclosurevars(functions["_render_page"]).nonlocals
    view, state = scope["results_view"], scope["browse_state"]

    def run(mr, cf, order=(0, 1)):
        DeferredThread.jobs.clear()
        with (patch.object(packs.core, "search_modpacks_modrinth", side_effect=mr),
              patch.object(packs.core, "search_modpacks_curseforge", side_effect=cf)):
            load()
            jobs = list(DeferredThread.jobs)
            assert len(jobs) == 2, "one page must start exactly two provider requests"
            for i in order:
                jobs[i]()
        assert not view.disabled, "finished providers left an inert list"

    for order in ((0, 1), (1, 0)):
        run(offline, offline, order)
        assert state["errors"][0], "total outage must expose a retry state"
        retry = view.controls[0].content.controls[-1]
        assert callable(retry.on_click), "failure state has no retry action"
    run(offline, lambda *a, **k: [])
    assert state["errors"][0], "a failed provider plus empty results is not a successful empty search"
    run(lambda *a, **k: [hit], offline)
    assert state["results"] == [hit] and not state["errors"][0], "working provider results were lost"
    run(lambda *a, **k: [], lambda *a, **k: [])
    assert not state["errors"][0], "successful no-results search was reported as a network failure"
    # A slow old query must never overwrite the current retry's results.
    DeferredThread.jobs.clear()
    with (patch.object(packs.core, "search_modpacks_modrinth", return_value=[hit]),
          patch.object(packs.core, "search_modpacks_curseforge", return_value=[])):
        load()
        old = list(DeferredThread.jobs)
        load()
        new = DeferredThread.jobs[-2:]
        for job in new:
            job()
        rows = tuple(view.controls)
        for job in old:
            job()
        assert tuple(view.controls) == rows, "old query replaced the newer result rows"

print("PASS: outages, partial results, empty results, retry affordance, and stale responses")
