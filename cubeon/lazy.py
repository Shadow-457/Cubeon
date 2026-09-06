"""
Deferred module import.

WHY: `import minecraft_launcher_lib` costs ~116 ms of the launcher's ~300 ms
startup, and ~97 ms of that is the `requests` stack it pulls in transitively.
Four modules import it at top level (versions, launch, mod_loaders, server),
so every launch paid for it before the window appeared - even though nothing
touches it until the user picks a version, launches, or hosts a server.

The obvious fix - moving each `import` inside the functions that use it -
means editing every call site and repeating the import in dozens of places.
LazyModule keeps the module-level name (`mll.utils.get_version_list()` still
reads exactly the same) and does the real import on first attribute access.

Deliberately NOT a general "make imports lazy" tool: it fits libraries whose
submodules are eagerly bound by their own __init__ (as mll's are), which is
why attribute access alone is enough to reach `mll.utils`, `mll.install` etc.
Thread-safe: two workers racing the first access get one import, because
import itself is guarded by Python's own module lock and the assignment below
is atomic.
"""
from __future__ import annotations

import importlib
from typing import Any


class LazyModule:
    """Stands in for a module until something actually uses it."""

    __slots__ = ("_lazy_name", "_lazy_mod")

    def __init__(self, name: str):
        object.__setattr__(self, "_lazy_name", name)
        object.__setattr__(self, "_lazy_mod", None)

    def _load(self):
        mod = object.__getattribute__(self, "_lazy_mod")
        if mod is None:
            mod = importlib.import_module(
                object.__getattribute__(self, "_lazy_name"))
            object.__setattr__(self, "_lazy_mod", mod)
        return mod

    def __getattr__(self, item: str) -> Any:
        return getattr(self._load(), item)

    def __setattr__(self, item: str, value: Any) -> None:
        setattr(self._load(), item, value)

    def __dir__(self):
        return dir(self._load())

    def __repr__(self) -> str:
        loaded = object.__getattribute__(self, "_lazy_mod") is not None
        return (f"<LazyModule {object.__getattribute__(self, '_lazy_name')} "
                f"{'loaded' if loaded else 'not yet imported'}>")
