#!/usr/bin/env python3
"""
test_mega_smoke.py - one-command deep health gate for the Cubeon repo.

The existing suites each prove a slice (friends, mods, UI structure...). This
one answers "is the whole thing still sound?" in four layers, cheapest first,
so a syntax slip fails in under a second instead of after 213 tests:

  1. SYNTAX          - every shippable .py compiles (ast.parse).
  2. IMPORTS         - every cubeon/ui module imports under a sandboxed HOME.
  3. TYPE / CONTRACT - the launcher_core facade covers every `core.X` the UI
                       calls; the Flet API rules the codebase fought for
                       (0.86 dialogs, no ink ripples, no ft.padding.only,
                       no None children in controls lists) hold; THEME and the
                       tab-builder signatures stay in parity.
  4. CONTROL FLOW    - AST pass over every file: unreachable code after a
                       return/raise, duplicate definitions, bare excepts,
                       mutable default args, `except: pass`.
  5. RUNTIME         - boot the real UI headless under safe stubs (no window,
                       no network, no real ~/.minecraft), open every tab and
                       fire every handler, asserting no defects, no None kids,
                       and that a second build is idempotent.

Run:            python3 tools/test_mega_smoke.py
Static only:    python3 tools/test_mega_smoke.py --static
Also run suites: python3 tools/test_mega_smoke.py --suites
JSON report:    python3 tools/test_mega_smoke.py --json
"""
from __future__ import annotations
import ast
import os
import sys
import json
import argparse
import subprocess

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
sys.path.insert(0, REPO)

SKIP_DIRS = {"archive", "dist", "build", ".git", "__pycache__",
             "node_modules", ".wrangler", "agents"}
CHECK_SUBDIRS = ("cubeon", "ui", "tools", "worker", "templates", "ui_new")

# section_imports() calls _sandbox_home.isolate(), which rewrites HOME in this
# process. Child suites inherit os.environ, and a rewritten HOME hides flet in
# the real user site-packages (flet is only needed at interpreter startup to
# land on sys.path). Keep the launch-time HOME so child processes behave like a
# normal run - each suite sandboxes itself again.
REAL_HOME = os.environ.get("HOME")
REAL_USERPROFILE = os.environ.get("USERPROFILE")


# ------------------------------------------------------------------ plumbing ---
passed = 0
failed = 0
G = {"json": False, "static": False}


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        if not G["json"]:
            print(f"  ok   {label}")
    else:
        failed += 1
        if not G["json"]:
            print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))
    return bool(cond)


def header(text):
    if not G["json"]:
        print(text)


def iter_py_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, REPO)
        if rel != "." and rel.split(os.sep)[0] not in CHECK_SUBDIRS:
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def parse_file(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    return src, ast.parse(src, filename=path)


# --------------------------------------------------------------- 1. syntax ---
def section_syntax():
    header("\n1. syntax - every shippable .py compiles")
    bad = []
    n = 0
    for path in iter_py_files():
        n += 1
        try:
            compile(open(path, encoding="utf-8").read(), path, "exec")
        except SyntaxError as ex:
            bad.append(f"{os.path.relpath(path, REPO)}:{ex.lineno}: {ex.msg}")
        except Exception as ex:
            bad.append(f"{os.path.relpath(path, REPO)}: {type(ex).__name__}: {ex}")
    check(f"all {n} python files compile", not bad, "\n       ".join(bad[:10]))


# --------------------------------------------------------------- 2. imports ---
def section_imports():
    header("\n2. imports - every module loads under a sandboxed HOME")
    import _sandbox_home
    _sandbox_home.isolate()
    import importlib
    mods = []
    for path in iter_py_files():
        rel = os.path.relpath(path, REPO)
        if rel.startswith("tools" + os.sep) or rel.startswith("templates" + os.sep):
            continue
        name = rel[:-3].replace(os.sep, ".").replace("__init__", "").rstrip(".")
        if name == "main" or name.startswith("cubeon") or name.startswith("ui"):
            mods.append((name, rel))
    bad = []
    for name, rel in sorted(set(mods)):
        try:
            importlib.import_module(name)
        except Exception as ex:
            bad.append(f"{rel}: {type(ex).__name__}: {ex}")
    check(f"imported {len(set(mods))} app modules with no errors", not bad,
          "\n       ".join(bad[:12]))


# ------------------------------------------------- 3. type / contract checks ---
def _live_ui_files():
    """main.py + ui/*.py - the code the launcher's own UI surface runs."""
    yield os.path.join(REPO, "main.py")
    ui = os.path.join(REPO, "ui")
    for f in sorted(os.listdir(ui)):
        if f.endswith(".py"):
            yield os.path.join(ui, f)


def _core_alias_attrs():
    """Every `core.NAME` referenced where `core` is launcher_core."""
    import re
    uses = {}
    for path in _live_ui_files():
        rel = os.path.relpath(path, REPO)
        src = open(path, encoding="utf-8").read()
        if not re.search(r"import\s+launcher_core\s+as\s+(\w+)", src):
            continue
        for m in re.finditer(r"import\s+launcher_core\s+as\s+(\w+)", src):
            alias = m.group(1)
            for a in re.finditer(rf"\b{re.escape(alias)}\.([A-Za-z_]\w*)", src):
                uses.setdefault(a.group(1), set()).add(rel)
    return uses


def _flet_none_in_controls(tree, rel):
    """AST: a list literal with a bare/dynamic None handed to a Flet control.

    The gray-box bug: `ft.Column([ft.Text(...) if c else None])` serializes a
    null child the Dart client can't build. Catch Constant None and an IfExp
    with a None branch in any list literal that is a call argument.
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if not isinstance(arg, ast.List):
                continue
            for i, el in enumerate(arg.elts):
                if isinstance(el, ast.Constant) and el.value is None:
                    hits.append(f"{rel}:{getattr(el, 'lineno', '?')} "
                                f"None literal in list arg")
                elif isinstance(el, ast.IfExp) and (
                        (isinstance(el.orelse, ast.Constant)
                         and el.orelse.value is None)
                        or (isinstance(el.body, ast.Constant)
                            and el.body.value is None)):
                    hits.append(f"{rel}:{getattr(el, 'lineno', '?')} "
                                f"conditional None in list arg")
    return hits


FLET_FORBIDDEN = [
    ("page.open(", "use cubeon.dialogs.open_dialog (0.86 removed Page.open)"),
    ("page.close(", "use cubeon.dialogs.close_dialog (0.86 removed Page.close)"),
    ("ink=True", "user preference: no Material ink ripples"),
    ("ink=not ", "user preference: no Material ink ripples"),
    ("ft.padding.only", "Flet 0.86 has no ft.padding.only"),
    ("ft.border.all", "Flet 0.86 has no ft.border.all"),
    ("ft.margin.only", "Flet 0.86 has no ft.margin.only"),
    ("ft.margin.symmetric", "Flet 0.86 has no ft.margin.symmetric"),
]


def section_contracts():
    header("\n3. type / contract - facade, Flet API, theme + signatures")
    import launcher_core as core

    # 3a. launcher_core facade covers everything the UI calls.
    uses = _core_alias_attrs()
    missing = {name: sorted(files) for name, files in uses.items()
               if not hasattr(core, name)}
    check(f"launcher_core exposes all {len(uses)} `core.*` names the UI calls",
          not missing,
          "; ".join(f"{n} (used in {', '.join(f[:30])})"
                    for n, f in list(missing.items())[:8]))

    # 3b. forbidden Flet APIs / preferences (live UI only: cubeon/dialogs.py
    # is the compatibility shim that is *supposed* to touch page.open/close).
    offenders = []
    for path in _live_ui_files():
        rel = os.path.relpath(path, REPO)
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            for needle, why in FLET_FORBIDDEN:
                if needle in line:
                    offenders.append(f"{rel}:{i} {needle!r} -> {why}")
    check("no removed/forbidden Flet API usage in the live UI",
          not offenders, "\n       ".join(offenders[:10]))

    # 3c. no conditional/None children in control lists.
    none_hits = []
    for path in iter_py_files():
        rel = os.path.relpath(path, REPO)
        if rel.startswith("archive") or "ui_new" in rel:
            continue
        try:
            _, tree = parse_file(path)
        except SyntaxError:
            continue
        none_hits.extend(_flet_none_in_controls(tree, rel))
    check("no None children in Flet controls lists (gray-box guard)",
          not none_hits, "\n       ".join(none_hits[:10]))

    # 3d. THEME exact keys + every tab builder accepts them.
    from cubeon.theme import THEME
    expect = {"BG", "SURFACE", "SURFACE_HI", "BORDER", "ACCENT", "ACCENT_DIM",
              "TEXT", "TEXT_DIM", "DANGER", "FONT_DISPLAY", "FONT_MONO"}
    check("THEME key set is exactly what builders accept",
          set(THEME) == expect, f"got {sorted(set(THEME) ^ expect)}")

    import inspect
    from ui.mods_tab import build_mods_tab
    from ui.modpacks_tab import build_modpacks_tab
    from ui.server_tab import build_server_tab
    from ui.stats_tab import build_stats_tab
    from ui.settings_tab import build_settings_tab
    from ui.chat_tab import build_chat_tab
    builders = [build_mods_tab, build_modpacks_tab, build_server_tab,
                build_stats_tab, build_settings_tab, build_chat_tab]
    bad_sig = []
    for b in builders:
        sig = inspect.signature(b)
        has_var_kw = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
        if has_var_kw:
            continue
        accepted = {p.name for p in sig.parameters.values()
                    if p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD)}
        missing_tokens = set(THEME) - accepted
        if missing_tokens:
            bad_sig.append(f"{b.__name__} cannot accept {sorted(missing_tokens)}")
    check("every tab builder accepts the shared **THEME token set",
          not bad_sig, "; ".join(bad_sig))

    # 3e. annotated code resolves its own type hints (lightweight type check).
    import importlib
    import typing
    hint_bad = []
    for name in ("cubeon.config", "cubeon.paths", "cubeon.versions",
                 "cubeon.mod_loaders", "cubeon.friends", "cubeon.e2ee",
                 "cubeon.skins", "cubeon.capes", "cubeon.milestones", "cubeon.thread_safe_ui"):
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        for oname, obj in vars(mod).items():
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            if getattr(obj, "__module__", None) != name:
                continue
            try:
                typing.get_type_hints(obj)
            except Exception as ex:
                hint_bad.append(f"{name}.{oname}: {type(ex).__name__}: {ex}")
    check("annotated public functions resolve their type hints",
          not hint_bad, "\n       ".join(hint_bad[:10]))


# ---------------------------------------------------------- 4. control flow ---
def _iter_stmt_lists(node):
    for field in ("body", "orelse", "finalbody", "handlers"):
        lst = getattr(node, field, None)
        if isinstance(lst, list):
            yield lst
    for child in ast.iter_child_nodes(node):
        yield from _iter_stmt_lists(child)


TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def _control_flow_findings(node, rel):
    findings = []
    for lst in _iter_stmt_lists(node):
        for i, stmt in enumerate(lst[:-1]):
            if isinstance(stmt, TERMINATORS):
                findings.append((stmt.lineno, "unreachable",
                                 f"code after {type(stmt).__name__.lower()}"))
                break
    for sub in ast.walk(node):
        if isinstance(sub, ast.ExceptHandler):
            if sub.type is None:
                findings.append((sub.lineno, "bare-except", "bare `except:`"))
            elif isinstance(sub.type, ast.Name) and sub.type.id in (
                    "Exception", "BaseException", "OSError", "IOError"):
                for st in sub.body:
                    if isinstance(st, ast.Pass):
                        findings.append((st.lineno, "swallowed",
                                         f"`except {sub.type.id}: pass`"))
        if isinstance(sub, ast.FunctionDef):
            for d in (sub.args.defaults + sub.args.kw_defaults):
                if isinstance(d, (ast.List, ast.Dict, ast.Set,
                                  ast.ListComp, ast.DictComp, ast.SetComp)):
                    findings.append((sub.lineno, "mutable-default",
                                     f"{sub.name} has a mutable default arg"))
        if isinstance(sub, ast.While) and isinstance(sub.test, ast.Constant) \
                and sub.test.value is True:
            if not any(isinstance(x, ast.Break) for x in ast.walk(sub)):
                findings.append((sub.lineno, "while-true",
                                 "`while True` with no break"))
    return findings


def section_control_flow():
    header("\n4. control flow - dead code, defaults, bare excepts")
    buckets = {"unreachable": [], "bare-except": [], "mutable-default": [],
               "swallowed": [], "while-true": [], "dup-def": []}
    for path in iter_py_files():
        rel = os.path.relpath(path, REPO)
        if rel.startswith("archive") or "ui_new" in rel:
            continue
        try:
            _, tree = parse_file(path)
        except SyntaxError:
            continue
        for lineno, kind, msg in _control_flow_findings(tree, rel):
            if kind in buckets:
                buckets[kind].append(f"{rel}:{lineno} {msg}")
        # duplicate top-level defs/classes (a later def silently shadows).
        seen = {}
        for sub in tree.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if sub.name in seen:
                    buckets["dup-def"].append(
                        f"{rel}:{sub.lineno} duplicate def {sub.name!r} "
                        f"(first at {seen[sub.name]})")
                else:
                    seen[sub.name] = sub.lineno
    check("no unreachable code after return/raise/break/continue",
          not buckets["unreachable"], "\n       ".join(buckets["unreachable"][:10]))
    check("no duplicate top-level definitions", not buckets["dup-def"],
          "\n       ".join(buckets["dup-def"][:10]))
    check("no bare `except:` clauses", not buckets["bare-except"],
          "\n       ".join(buckets["bare-except"][:10]))
    check("no mutable default arguments", not buckets["mutable-default"],
          "\n       ".join(buckets["mutable-default"][:10]))
    # informational only (repo has tuned, intentional ones).
    if buckets["swallowed"] or buckets["while-true"]:
        header(f"  info  {len(buckets['swallowed'])} `except: pass`, "
               f"{len(buckets['while-true'])} `while True` w/o break "
               "(intentional patterns - not failures)")


# -------------------------------------------------------------- 5. runtime ---
def section_runtime():
    header("\n5. runtime - build the real UI headless and use every tab")
    try:
        import app_driver
        d = app_driver.build_headless()
    except Exception:
        import traceback
        check("the app builds headlessly under safety stubs", False,
              traceback.format_exc())
        return None

    rep = app_driver._run_usage(d, hostile=False, mode="explore")
    check("every nav tab opens", all(rep["tabs_opened"].values()),
          f"not opened: {[k for k, v in rep['tabs_opened'].items() if not v]}")
    check("no handler raised on a normal usage pass",
          not rep["errors"], "\n       ".join(
              f"{e['where']} {e['type']}: {e['message']}"
              for e in rep["errors"][:10]))
    check("no None children in any built controls list",
          not rep["none_children"], ", ".join(rep["none_children"][:10]))

    # idempotence: a second independent build catches leaked module state.
    try:
        d2 = app_driver.build_headless()
        rep2 = d2.report("rebuild")
        check("a second independent build also succeeds", not rep2["errors"],
              "\n       ".join(e["where"] for e in rep2["errors"][:5]))
    except Exception:
        import traceback
        check("a second independent build also succeeds", False,
              traceback.format_exc())
    return rep


# ----------------------------------------------------------- 6. sub-suites ----
SUITES = [
    "test_friends_service.py", "test_friends.py", "test_mod_bridge.py",
    "test_capes.py", "test_ui_smoke.py", "test_invites.py",
    "test_modpacks.py", "test_mod_store.py", "test_net.py",
    "test_fuzz.py", "test_production.py", "test_content_instance.py",
    "test_version_integrity.py", "test_local_api_gate.py",
    "test_wedge_watchdog.py", "test_web_download_count.py",
]


def section_suites():
    header("\n6. sub-suites - run the repo's own harnesses")
    for name in SUITES:
        path = os.path.join(TOOLS, name)
        if not os.path.exists(path):
            continue
        try:
            env = dict(os.environ)
            if REAL_HOME:
                env["HOME"] = REAL_HOME
            if REAL_USERPROFILE:
                env["USERPROFILE"] = REAL_USERPROFILE
            proc = subprocess.run([sys.executable, path], capture_output=True,
                                  text=True, timeout=900, env=env)
            tail = (proc.stdout or "").strip().splitlines()
            summary = tail[-1] if tail else ""
            check(f"{name}: exit {proc.returncode}  ({summary[-80:]})",
                  proc.returncode == 0)
        except subprocess.TimeoutExpired:
            check(f"{name}: timed out", False)


# ----------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser(description="Deep health gate for Cubeon.")
    ap.add_argument("--static", action="store_true",
                    help="skip the runtime + sub-suite sections")
    ap.add_argument("--suites", action="store_true",
                    help="also run the repo's own test_*.py harnesses")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--out", help="write the JSON report here")
    args = ap.parse_args()
    G["json"] = args.json
    G["static"] = args.static

    if not args.json:
        print("Cubeon mega smoke - syntax, contracts, control flow, runtime")
    section_syntax()
    section_imports()
    section_contracts()
    section_control_flow()
    # Sub-suites must run BEFORE the runtime layer: install_safe_stubs()
    # monkeypatches subprocess.Popen process-wide, which would break
    # subprocess.run() here.
    if args.suites:
        section_suites()
    runtime = None
    if not args.static:
        runtime = section_runtime()

    if args.json:
        print(json.dumps({
            "passed": passed, "failed": failed,
            "ok": failed == 0,
            "runtime": runtime,
        }, indent=2))
    else:
        print(f"\n{passed} passed, {failed} failed")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"passed": passed, "failed": failed, "ok": failed == 0},
                      f, indent=2)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
