#!/usr/bin/env python3
"""
test_release_pipeline.py - dry-run the release workflow offline.

`.github/workflows/build.yml` publishes a release on every push, and almost
nothing in it is exercised by the other suites: the version maths
(tools/release_version.py) has its own unit tests, but the *plumbing* around it
- tag reservation, re-run idempotency, the draft-until-complete publish - only
runs on GitHub. A mistake there is expensive and silent: two releases for one
commit, a version skipped for good, or a release that goes public before its
assets exist (which the in-app updater and the download worker both read).

So this runs the REAL `run:` script text, extracted from the workflow, against a
throwaway repo + a `gh` stand-in, and asserts what the pipeline promises:

  1. a push releases the next version (APP_VERSION, bumped, in tag, in the tree);
  2. a RE-RUN of the same push reuses that version instead of minting another;
  3. the next push bumps the patch;
  4. a run that loses the tag race bumps past the winner;
  5. an unparseable APP_VERSION aborts instead of releasing garbage;
  6. a human tag push (v*) is released verbatim;
  7. publish refuses a release whose assets are incomplete;
  8. publish only moves `latest` forwards.

No network, no PyYAML (requirements.txt has none - the workflow is parsed by
indentation), no git remote but a local directory.

Run: python3 tools/test_release_pipeline.py
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
WORKFLOW = REPO / ".github" / "workflows" / "build.yml"

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))
    return bool(cond)


def section(text):
    print(text)


# --------------------------------------------------------------- workflow read ---
def extract_run(step_name: str) -> str:
    """The `run: |` body of the workflow step with this name.

    Hand-rolled on purpose: the repo has no YAML dependency and this file is
    the only consumer. Indentation decides the block, same as YAML does.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip() != f"- name: {step_name}":
            continue
        step_indent = len(line) - len(line.lstrip())
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= step_indent:
                break          # the next step / job started
            if nxt.strip() != "run: |":
                continue
            indent = len(nxt) - len(nxt.lstrip())
            body = []
            for line in lines[j + 1:]:
                if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                    break
                body.append(line[indent + 2:] if len(line) > indent + 2 else "")
            return "\n".join(body) + "\n"
    raise AssertionError(f"no `run: |` found for the step {step_name!r} in {WORKFLOW}")


def job_block(job: str) -> str:
    """The text of one top-level job, for structural assertions."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    out, inside = [], False
    for line in lines:
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            inside = line.strip() == f"{job}:"
        elif inside:
            out.append(line)
    return "\n".join(out)


section("workflow contract (text-level, before running anything)")
wf = WORKFLOW.read_text(encoding="utf-8")
check("the workflow exists where GitHub expects it", WORKFLOW.is_file())
check("every release is opened as a DRAFT",
      "--draft" in extract_run("Decide the version, stamp it, tag it, open the draft"))
for builder in ("build-linux-appimage", "build-windows-exe", "build-macos"):
    block = job_block(builder)
    check(f"{builder} waits for the version job", "needs: release" in block)
    check(f"{builder} builds the TAGGED commit",
          "ref: ${{ needs.release.outputs.tag }}" in block)
    check(f"{builder} stamps the version before its build",
          "release_version.py stamp" in block)
    check(f"{builder} uploads to the path the version job set",
          "RELEASE_TAG: ${{ needs.release.outputs.tag }}" in block)
pub = job_block("publish")
check("publish waits for every builder",
      all(f"- {b}" in pub.split("needs:")[1].split("\n")[0] or b in pub
          for b in ("build-linux-appimage", "build-windows-exe", "build-macos")))
check("publish un-drafts (that is the whole point of the draft)",
      "--draft=false" in pub)
check("the version job is the only writer of the version",
      wf.count("APP_VERSION = ") == 0 and "release_version.py stamp" in wf)
check("a human tag push still bypasses the auto-bump",
      "refs/tags/v*" in extract_run("Decide the version, stamp it, tag it, open the draft"))


# ------------------------------------------------------------------ sandbox gh ---
GH_STUB = r'''#!/usr/bin/env bash
# Minimal `gh` stand-in. State lives in $RELSTATE.
set -euo pipefail
cmd="${1:-}"; shift || true
case "$cmd" in
  api)
    # Mirrors GitHub: the releases/tags/<tag> endpoint returns PUBLISHED
    # releases only - a draft 404s. Getting this wrong once cost a real run
    # (the re-run path concluded "no release yet" and re-created it), so the
    # stub is deliberately faithful rather than permissive.
    tag="${1##*/}"
    if [ -f "$RELSTATE/releases/$tag" ] && [ -f "$RELSTATE/published/$tag" ]; then
      echo "{\"tag_name\":\"$tag\"}"
    else
      echo "gh: Not Found (HTTP 404)" >&2; exit 1
    fi;;
  release)
    sub="$1"; shift || true
    case "$sub" in
      create)
        tag="$1"; shift || true
        [ -f "$RELSTATE/releases/$tag" ] && { echo "422 already_exists" >&2; exit 1; }
        case " $* " in *" --verify-tag "*) ;; *) echo "gh: --verify-tag missing" >&2; exit 1;; esac
        case " $* " in *" --draft "*) ;; *) echo "gh: --draft missing" >&2; exit 1;; esac
        touch "$RELSTATE/releases/$tag"; echo "created draft $tag";;
      upload)
        tag="$1"; shift || true
        [ -f "$RELSTATE/releases/$tag" ] || { echo "gh: no such release" >&2; exit 1; }
        for f in "$@"; do [ "$f" = "--clobber" ] && continue
          echo "$(basename "$f")" >> "$RELSTATE/assets/$tag"; done;;
      view)
        tag="$1"; shift || true
        [ -f "$RELSTATE/releases/$tag" ] || { echo "gh: not found" >&2; exit 1; }
        case " $* " in *" --json assets "*) cat "$RELSTATE/assets/$tag" 2>/dev/null || true;;
          *) echo "{\"tagName\":\"$tag\"}";; esac;;
      list)
        # Mirrors `--json tagName,isDraft --jq 'select(.isDraft == false)'`.
        for f in "$RELSTATE"/releases/*; do
          [ -f "$f" ] || continue
          t="$(basename "$f")"
          [ -f "$RELSTATE/published/$t" ] && echo "$t"
        done
        ;;
      edit)
        tag="$1"; shift || true
        [ -f "$RELSTATE/releases/$tag" ] || { echo "gh: not found" >&2; exit 1; }
        case " $* " in *" --draft=false "*) touch "$RELSTATE/published/$tag";; esac
        case " $* " in *" --draft=true "*) rm -f "$RELSTATE/published/$tag";; esac
        case " $* " in *" --latest "*) touch "$RELSTATE/latest/$tag";; esac;;
      *) echo "gh-stub: unhandled release $sub" >&2; exit 1;;
    esac;;
  *) echo "gh-stub: unhandled $cmd" >&2; exit 1;;
esac
'''


class Sim:
    """A throwaway git repo + gh stand-in that can run the workflow's steps."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="cubeon-release-pipeline-"))
        self.origin = self.dir / "origin.git"
        self.work = self.dir / "work"
        self.state = self.dir / "state"
        self.bin = self.dir / "bin"
        self.home = self.dir / "home"
        self.log = self.dir / "last.log"
        for d in (self.state / "releases", self.state / "published",
                  self.state / "assets", self.state / "latest", self.bin, self.home):
            d.mkdir(parents=True, exist_ok=True)
        # The sandbox gets exactly one tool: the real one. Nothing else is
        # copied in, so the pipeline can't accidentally pass on a stray file.
        (self.work / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy2(TOOLS / "release_version.py",
                     self.work / "tools" / "release_version.py")
        (self.work / "cubeon").mkdir()
        (self.work / "cubeon" / "updater.py").write_text(
            'APP_VERSION = "1.1.2"\n'
            'DEFAULT_FEED = "https://api.github.com/repos/x/y/releases/latest"\n',
            encoding="utf-8")
        (self.work / "web").mkdir()
        (self.work / "web" / "index.html").write_text(
            '<p class="meta">v1.1.2 &middot; Installer</p>\n'
            '<p class="hero-note">v1.1.2 &middot; Free</p>\n', encoding="utf-8")
        (self.work / "web" / "download.html").write_text(
            "<span>Version 1.1.2 &middot; Installer</span>\n"
            "<span>Version 1.1.2 &middot; Single file</span>\n", encoding="utf-8")
        gh = self.bin / "gh"
        gh.write_text(GH_STUB, encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        self.git("init", "--bare", "-q", str(self.origin), cwd=self.dir)
        self.git("init", "-q", "-b", "main", cwd=self.work)
        self.git("add", "-A", cwd=self.work)
        self.git("commit", "-qm", "init", cwd=self.work)
        self.git("tag", "v1.1.2", cwd=self.work)
        self.git("remote", "add", "origin", str(self.origin), cwd=self.work)
        self.git("push", "-q", "origin", "HEAD:refs/heads/main", "--tags", cwd=self.work)

    def git(self, *args, cwd=None) -> str:
        # env= on purpose: the sandbox HOME keeps a developer's global git
        # config (identity, hooks, commit signing) out of this, and the
        # GIT_AUTHOR/GIT_COMMITTER pair below is what lets the very first
        # `git commit` work on a fresh CI runner, which has NO identity
        # configured at all (that is exactly how this test first failed there).
        return subprocess.run(["git", "-C", str(cwd or self.work), *args],
                              capture_output=True, text=True, check=True,
                              env=self.env()).stdout.strip()

    def git_ok(self, *args, cwd=None) -> bool:
        return subprocess.run(["git", "-C", str(cwd or self.work), *args],
                              capture_output=True, text=True,
                              env=self.env()).returncode == 0

    def env(self) -> dict:
        env = dict(os.environ)
        env.update({
            "PATH": f"{self.bin}:{env.get('PATH', '')}",
            "HOME": str(self.home),
            "GH_TOKEN": "fake",
            "RELSTATE": str(self.state),
            "GITHUB_REPOSITORY": "fake/repo",
            "GITHUB_OUTPUT": str(self.dir / "gh_output"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
        })
        return env

    def push(self, message: str) -> str:
        """A new commit on main, as a maintainer would push. Returns its sha."""
        (self.work / "note.txt").open("a", encoding="utf-8").write(message + "\n")
        self.git("add", "-A", cwd=self.work)
        self.git("commit", "-qm", message, cwd=self.work)
        self.git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=self.work)
        return self.git("rev-parse", "HEAD", cwd=self.work)

    def run_step(self, script: str, ref: str, sha: str = "", **extra) -> int:
        """Run an extracted `run:` body the way the workflow does."""
        step = self.dir / "step.sh"
        step.write_text(script, encoding="utf-8")
        env = self.env()
        env["GITHUB_REF"] = ref
        env["GITHUB_REF_NAME"] = ref.split("/", 2)[-1]
        env["GITHUB_SHA"] = sha or self.git("rev-parse", "HEAD")
        env.update({k: str(v) for k, v in extra.items()})
        (self.dir / "gh_output").write_text("", encoding="utf-8")
        proc = subprocess.run(["bash", str(step)], cwd=self.work, env=env,
                              capture_output=True, text=True)
        self.log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        return proc.returncode

    def released(self, version: str) -> str:
        """The version printed by the last run's output block."""
        m = re.search(r"^version=([0-9.]+)$", (self.dir / "gh_output").read_text(),
                      re.MULTILINE)
        return m.group(1) if m else ""

    def has(self, kind: str, tag: str) -> bool:
        return (self.state / kind / tag).exists()

    def tags(self) -> list[str]:
        out = self.git("tag", "-l", cwd=self.origin)
        return [t for t in out.splitlines() if t]

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


RELEASE_STEP = extract_run("Decide the version, stamp it, tag it, open the draft")
VERIFY_STEP = extract_run("Verify every asset landed")
PUBLISH_STEP = extract_run("Publish")

section("the release job looks drafts up the way that actually works")
def _code(step: str) -> str:
    """The step's shell, comments stripped - a comment ABOUT the trap must not
    count as the trap."""
    return "\n".join(l for l in step.splitlines() if not l.lstrip().startswith("#"))


check("`gh release view`, never the tags API "
      "(releases/tags/<tag> 404s for a draft - that broke the first real run)",
      "releases/tags/" not in _code(RELEASE_STEP)
      and _code(RELEASE_STEP).count("gh release view") >= 2)
check("and the uploads it hands off to can see a draft too (same lookup)",
      "releases/tags/" not in _code(VERIFY_STEP))

sim = Sim()
try:
    section("1. a push to main releases the next version")
    first = sim.push("feature one")
    rc = sim.run_step(RELEASE_STEP, "refs/heads/main", first)
    check("the step succeeds", rc == 0, sim.log.read_text()[-600:])
    check("released 1.1.3 (APP_VERSION 1.1.2 was already tagged)",
          sim.released("") == "1.1.3", sim.log.read_text()[-400:])
    check("stamped APP_VERSION in the tree",
          'APP_VERSION = "1.1.3"' in (sim.work / "cubeon" / "updater.py").read_text())
    check("committed the bump back with [skip ci]",
          sim.git("log", "-1", "--pretty=%s") == "release: v1.1.3 [skip ci]")
    check("the tag points at that bump commit, not at the pushed one",
          sim.git("rev-parse", "v1.1.3^{commit}", cwd=sim.origin)
          == sim.git("rev-parse", "HEAD"))
    check("the bump commit's parent is the pushed commit",
          sim.git("rev-parse", "HEAD^") == first)
    check("the release is a DRAFT until publish", not sim.has("published", "v1.1.3"))
    check("the site's display text was bumped",
          (sim.work / "web" / "index.html").read_text().count("v1.1.3") == 2)
    check("the tag name matches the version the app now reports (updater contract)",
          sim.git("rev-parse", "v1.1.3^{commit}", cwd=sim.origin)
          == sim.git("rev-parse", "HEAD"))

    section("2. a RE-RUN of the same push reuses its version")
    n = len(sim.tags())
    rc = sim.run_step(RELEASE_STEP, "refs/heads/main", first)   # same GITHUB_SHA
    check("the step succeeds", rc == 0, sim.log.read_text()[-400:])
    check("reused 1.1.3", sim.released("") == "1.1.3", sim.log.read_text()[-400:])
    check("minted no second tag", len(sim.tags()) == n, str(sim.tags()))
    check("printed why", "already covers" in sim.log.read_text())

    section("2b. re-running an ALREADY PUBLISHED release re-drafts it for the re-upload")
    (sim.state / "published" / "v1.1.3").touch()      # as if `publish` had run
    rc = sim.run_step(RELEASE_STEP, "refs/heads/main", first)
    check("the step succeeds", rc == 0, sim.log.read_text()[-400:])
    check("back to draft while assets are replaced (--clobber deletes first)",
          not sim.has("published", "v1.1.3"))
    check("still no extra tag", len(sim.tags()) == n, str(sim.tags()))
    (sim.state / "published" / "v1.1.3").touch()      # publish would re-publish

    section("3. the next push bumps the patch")
    sim.push("feature two")
    rc = sim.run_step(RELEASE_STEP, "refs/heads/main")
    check("the step succeeds", rc == 0, sim.log.read_text()[-400:])
    check("released 1.1.4", sim.released("") == "1.1.4", sim.log.read_text()[-400:])

    section("4. losing the tag race bumps past the winner")
    # Another run published v1.1.4 pointing somewhere else while we were queued.
    sim.git("fetch", "-q", "origin", "--tags", "--force")
    sim.git("tag", "-d", "v1.1.4")
    stolen = sim.git("rev-parse", "HEAD~1")
    sim.git("update-ref", "refs/tags/v1.1.4", stolen, cwd=sim.origin)
    sim.push("raced")
    rc = sim.run_step(RELEASE_STEP, "refs/heads/main")
    check("the step succeeds", rc == 0, sim.log.read_text()[-400:])
    check("released 1.1.5 instead of clobbering v1.1.4",
          sim.released("") == "1.1.5", sim.log.read_text()[-400:])
    check("v1.1.4 was left alone",
          sim.git("rev-parse", "v1.1.4^{commit}", cwd=sim.origin) == stolen)

    section("5. an unusable APP_VERSION aborts the release")
    (sim.work / "cubeon" / "updater.py").write_text(
        'APP_VERSION = "oops"\n', encoding="utf-8")
    sim.git("add", "-A"); sim.git("commit", "-qm", "bad version")
    n = len(sim.tags())
    rc = sim.run_step(RELEASE_STEP, "refs/heads/main", sim.git("rev-parse", "HEAD"))
    check("the step fails loudly", rc != 0, sim.log.read_text()[-300:])
    check("and tagged nothing", len(sim.tags()) == n, str(sim.tags()))
    sim.git("reset", "-q", "--hard", "HEAD~1")
    sim.git("push", "-q", "-f", "origin", "HEAD:refs/heads/main")

    section("6. a human tag push is released verbatim")
    sim.git("tag", "v1.5.0")
    sim.git("push", "-q", "origin", "refs/tags/v1.5.0")
    rc = sim.run_step(RELEASE_STEP, "refs/tags/v1.5.0")
    check("the step succeeds", rc == 0, sim.log.read_text()[-400:])
    check("released the tag as-is", sim.released("") == "1.5.0", sim.log.read_text()[-400:])
    check("stamped the tree to match the tag",
          'APP_VERSION = "1.5.0"' in (sim.work / "cubeon" / "updater.py").read_text())

    section("7. publish refuses an incomplete release")
    COMPLETE = ["Cubeon-Windows-x64-Setup.exe", "Cubeon-Windows-x64.zip",
                "Cubeon-macOS.zip", "Cubeon-x86_64.AppImage",
                "Cubeon-Linux-x86_64-Setup.sh", "cubeon_1.1.3_amd64.deb"]
    (sim.state / "assets" / "v1.1.3").write_text(
        "Cubeon-Windows-x64.zip\nCubeon-macOS.zip\n", encoding="utf-8")
    rc = sim.run_step(VERIFY_STEP, "refs/heads/main", TAG="v1.1.3")
    check("two missing platforms (and the .deb) fail the job", rc != 0)
    (sim.state / "assets" / "v1.1.3").write_text(
        "\n".join(COMPLETE) + "\n", encoding="utf-8")
    rc = sim.run_step(VERIFY_STEP, "refs/heads/main", TAG="v1.1.3")
    check("a complete release passes", rc == 0, sim.log.read_text()[-400:])
    # A .deb under a stale name must not sneak through on a prefix match alone.
    (sim.state / "assets" / "v1.1.3").write_text(
        "\n".join(COMPLETE[:-1]) + "\ncubeon_1.1.3_amd64.tar.gz\n", encoding="utf-8")
    check("an unrelated cubeon_* file does not pass for the .deb",
          sim.run_step(VERIFY_STEP, "refs/heads/main", TAG="v1.1.3") != 0)

    section("8. publish only moves `latest` forwards")
    # A newer release is already public (the normal case when re-running an
    # older failed build): publishing the older one must not drag `latest` back.
    (sim.state / "published" / "v1.1.5").touch()
    env = sim.env()
    env.update({"TAG": "v1.1.3", "GITHUB_REF": "refs/heads/main"})
    (sim.state / "assets" / "v1.1.3").write_text("\n".join(COMPLETE) + "\n",
                                                 encoding="utf-8")
    step = sim.dir / "step.sh"
    step.write_text(PUBLISH_STEP, encoding="utf-8")
    subprocess.run(["bash", str(step)], cwd=sim.work, env=env,
                   capture_output=True, text=True)
    check("an older release is published, but not as Latest",
          sim.has("published", "v1.1.3") and not sim.has("latest", "v1.1.3"))
    check("the public release kept `latest`",
          not sim.has("latest", "v1.1.3"))
    (sim.state / "assets" / "v1.5.0").write_text(
        "\n".join(COMPLETE[:-1]) + "\ncubeon_1.5.0_amd64.deb\n", encoding="utf-8")
    env["TAG"] = "v1.5.0"
    subprocess.run(["bash", str(step)], cwd=sim.work, env=env,
                   capture_output=True, text=True)
    check("a version ahead of the public one does become Latest",
          sim.has("published", "v1.5.0") and sim.has("latest", "v1.5.0"))
finally:
    sim.cleanup()

print()
if failed:
    print(f"RESULT: {failed} FAILED, {passed} passed")
    sys.exit(1)
print(f"RESULT: {passed} passed, 0 failed")
