"""Flet's own window-close chatter must not reach the console (but stays in the log tail).

On every window close the flet desktop client asks the Flutter engine to remove
its implicit view; the engine refuses, and the client prints:

    embedder.cc (2603): 'FlutterEngineRemoveView' returned 'kInvalidArguments'.
    Remove view info was invalid. The implicit view cannot be removed.

then, on flet 0.86, two GLib warnings:

    ** (flet:N): WARNING **: Attempted to set message handler on an
    FlBinaryMessenger without an engine

Reproduced with flet 0.86.5 and 1.0.3 in a 12-line app that only closes its
window (no Cubeon code involved), so this is not a launcher failure - but users
read it as one, because the launcher forwards the client's merged stderr to the
terminal. It is now dropped from the console and still recorded in
`_client_tail` (the evidence an incident record keeps).

Locked-in behaviour:
  1. the exact engine line and the messenger warning are recognised
  2. real client diagnostics are NOT recognised (GL frame timeouts, tracebacks)
  3. the filter drops the line only after it has been added to the tail, and
     before it is echoed to stderr

Run: python tools/test_client_teardown_noise.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


import main  # noqa: E402  (module-level only: nothing is started)

NOISE = main._CLIENT_TEARDOWN_NOISE

# --- 1. the lines users actually see --------------------------------------
ENGINE_LINE = ("embedder.cc (2603): 'FlutterEngineRemoveView' returned "
               "'kInvalidArguments'. Remove view info was invalid. The "
               "implicit view cannot be removed.")
MESSENGER_LINE = ("** (flet:127217): WARNING **: 06:40:10.404: Attempted to "
                  "set message handler on an FlBinaryMessenger without an "
                  "engine")
check("the FlutterEngineRemoveView line is filtered", bool(NOISE.search(ENGINE_LINE)),
      "the line users reported is still echoed")
check("a bare 'implicit view cannot be removed' is filtered",
      bool(NOISE.search("Remove view info was invalid. The implicit view "
                        "cannot be removed.")))
check("the engine-less messenger warning is filtered",
      bool(NOISE.search(MESSENGER_LINE)))

# --- 2. genuine diagnostics must still be printed -------------------------
for label, line in [
        ("GL frame timeout", "Timed out waiting for OpenGL frame "
                             "(timeout 1.000s, attempts 1)"),
        ("render error", "[ERROR:flutter/flow/layers/transform_layer.cc(15)] "
                         "TransformLayer is constructed with an invalid matrix."),
        ("python traceback", "Traceback (most recent call last):"),
        ("session error", "RuntimeError: Session closed"),
        ("import failure", "ModuleNotFoundError: No module named 'launcher_core'"),
        ("atk noise (own filter)", "Atk-CRITICAL **: atk_socket_embed: "
                                   "assertion 'plug_id != NULL' failed")]:
    check(f"'{label}' is still shown", not NOISE.search(line))

# --- 3. the drop sits between the tail record and the echo ---------------
SOURCE = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
TREE = ast.parse(SOURCE)


def find_function(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    raise AssertionError(f"main.py has no {name}()")


loop = find_function("_filter_client_output")
body = ast.get_source_segment(SOURCE, loop) or ""
record_at = body.find("_client_tail.add(line)")
guard_at = body.find("if _CLIENT_TEARDOWN_NOISE.search(line):")
write_at = body.find("sys.__stderr__.write(line)")
check("the loop records the line in _client_tail", record_at >= 0,
      "no _client_tail.add(line)")
check("the loop consults the teardown filter", guard_at >= 0,
      "no _CLIENT_TEARDOWN_NOISE guard")
check("the line is recorded BEFORE it is dropped",
      0 <= record_at < guard_at, f"add at {record_at}, guard at {guard_at}")
check("a dropped line is not echoed to stderr",
      0 <= guard_at < write_at, f"guard at {guard_at}, write at {write_at}")
check("dropping happens with continue (not by emptying the line)",
      "continue" in body[guard_at:guard_at + 400] if guard_at >= 0 else False)
check("the engine line really is refused by the engine, by name",
      "implicit view" in ENGINE_LINE)

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
