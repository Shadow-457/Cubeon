"""Two background threads must not poll while the launcher is idle (B2).

`_bar_loop` re-checked the hidden progress bar every 0.1 s (10 wakeups/second)
and `_wedge_watchdog` re-checked for an armed client every 0.25 s (4/second) for
the whole life of the process - measured at 10.0/s and 4.0/s, and 0.0/s after
they block on an Event instead.

Both loops live somewhere a headless harness cannot reach (the bar ticker runs,
but the watchdog only starts in main.py's `__main__` block, i.e. during a real
launch), so this test pins the shape of the code: the idle branch waits on its
Event and does not sleep-poll, and the code that changes the state sets that
Event. `tools/test_bar_idle_wake.py` proves the bar ticker still animates and
resumes; the watchdog's armed path (`time.sleep(0.5)`) is deliberately
unchanged.

Run: python tools/test_idle_wakeups.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


SOURCE = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
TREE = ast.parse(SOURCE)


def find_function(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    raise AssertionError(f"main.py has no {name}()")


def calls_named(node, dotted):
    """Every `dotted(...)` call inside node, e.g. 'time.sleep' / '_bar_wake.wait'."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if f"{fn.value.id}.{fn.attr}" == dotted:
                    out.append(sub)
            elif isinstance(fn, ast.Name) and fn.id == dotted:
                out.append(sub)
    return out


def branch_guarded_by(fn, predicate):
    """The body of the first `if <predicate>:` inside fn."""
    for sub in ast.walk(fn):
        if isinstance(sub, ast.If) and predicate(sub.test):
            return sub.body
    return None


def is_not_visible(test):
    return (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Attribute)
            and test.operand.attr == "visible")


def is_unarmed(test):
    """`pid is None or armed_at is None`"""
    return isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or)


bar_loop = find_function("_bar_loop")
set_bar = find_function("set_bar")
watchdog = find_function("_wedge_watchdog")
wedge_arm = find_function("_wedge_arm")

# --- the bar ticker -------------------------------------------------------
hidden = branch_guarded_by(bar_loop, is_not_visible)
check("_bar_loop has the 'bar hidden' branch", hidden is not None)
check("the hidden branch blocks on the wake event",
      bool(hidden) and any(calls_named(stmt, "_bar_wake.wait")
                           for stmt in hidden))
check("the hidden branch does not sleep-poll",
      hidden is not None and not calls_named(hidden[0], "time.sleep"),
      "still calls time.sleep()")
check("set_bar signals the ticker", bool(calls_named(set_bar, "_bar_wake.set")),
      "set_bar never sets _bar_wake")

# --- the wedge watchdog ---------------------------------------------------
unarmed = branch_guarded_by(watchdog, is_unarmed)
check("_wedge_watchdog has the 'no client armed' branch", unarmed is not None)
check("the unarmed branch blocks on the wake event",
      bool(unarmed) and any(calls_named(stmt, "_wedge_wake.wait")
                            for stmt in unarmed))
check("the unarmed branch does not sleep-poll",
      unarmed is not None and not calls_named(unarmed[0], "time.sleep"),
      "still calls time.sleep()")
check("_wedge_arm signals the watchdog",
      bool(calls_named(wedge_arm, "_wedge_wake.set")),
      "_wedge_arm never sets _wedge_wake")
check("the armed path still polls (behaviour unchanged)",
      bool(calls_named(watchdog, "time.sleep")),
      "the active 0.5s judging poll was removed")

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
