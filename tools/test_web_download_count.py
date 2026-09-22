#!/usr/bin/env python3
"""Guards for the website's release download count.

The count has two independent sources, and BOTH have to keep working:

  1. `web/api/download-count.js`  - the Vercel function, exercised here in Node
     with a stubbed `fetch` (no network, no GitHub account, no token).
  2. `web/assets/download-count.json` - written by
     `tools/refresh_download_count.py` from the scheduled workflow.

Everything is faked, so a red test means OUR code broke - never GitHub's mood,
the network, or the private-repo 404 that hid this counter on the live site
(cubeon.vercel.app answered `404 release_unavailable` until the static file
became a fallback).
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
WEB = os.path.join(REPO, "web")
API_JS = os.path.join(WEB, "api", "download-count.js")
SITE_JS = os.path.join(WEB, "assets", "site.js")
COUNTS_JSON = os.path.join(WEB, "assets", "download-count.json")
WORKFLOW = os.path.join(REPO, ".github", "workflows", "download-count.yml")

_passed = 0
_failed = 0


def check(label, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
        print("PASS " + label)
    else:
        _failed += 1
        print("FAIL " + label + (("  (" + detail + ")") if detail else ""))
        raise SystemExit(1)


def skip(label, reason):
    print("SKIP " + label + "  (" + reason + ")")


# ---------------------------------------------------------------------------
# 1. the Vercel function, run for real in Node against a stubbed fetch
# ---------------------------------------------------------------------------
HARNESS = r"""
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const handler = require(process.argv[2]);

let passed = 0;
function check(label, condition) {
  if (condition) { passed++; console.log("PASS " + label); }
  else { console.log("FAIL " + label); process.exit(1); }
}

function fakeRes() {
  return {
    statusCode: null, payload: null, headers: {},
    setHeader(name, value) { this.headers[String(name).toLowerCase()] = value; },
    status(code) { this.statusCode = code; return this; },
    json(payload) { this.payload = payload; return this; },
  };
}

// The four installers the site advertises, plus the kind of leftovers a real
// release carries (portable exe, ZIP, checksum) and junk entries.
const INSTALLERS = {
  "Cubeon-Windows-x64-Setup.exe": 7,
  "Cubeon-x86_64.AppImage": 5,
  "cubeon_1.0.0_amd64.deb": 3,
  "Cubeon-Linux-x86_64-Setup.sh": 2,
};
const RELEASE = {
  tag_name: "v9.9.9",
  assets: Object.keys(INSTALLERS).map((name) => ({ name, download_count: INSTALLERS[name] }))
    .concat([
      { name: "Cubeon-Windows-x64.zip", download_count: 900 },
      { name: "Cubeon-Windows-x64-single.exe", download_count: 400 },
      { name: "Cubeon-x86_64.AppImage.sha256", download_count: 12 },
      { name: "notes.txt" },
      null,
    ]),
};


let calls = [];
let upstream = { ok: true, status: 200, payload: RELEASE };

globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options: options || {} });
  if (upstream.throws) throw new Error("network down");
  return { ok: upstream.ok, status: upstream.status, json: async () => upstream.payload };
};

function reset() { calls = []; upstream = { ok: true, status: 200, payload: RELEASE }; }
function call(method = "GET") {
  const res = fakeRes();
  return handler({ method, url: "/api/download-count", query: {} }, res).then(() => res);
}
function entries(object) {
  return Object.entries(object).sort().map(([k, v]) => k + "=" + v).join(",");
}

delete process.env.GITHUB_TOKEN;
delete process.env.GH_TOKEN;

// 1. the sum covers the four advertised installers and nothing else
reset();
let res = await call();
check("healthy release answers 200", res.statusCode === 200);
check("only advertised installers are summed (17, not 1322)", res.payload.total === 17);
check("per-asset counts come back with the total",
      entries(res.payload.assets) === entries(INSTALLERS));
check("the edge caches the answer for 15 minutes",
      /s-maxage=900/.test(res.headers["cache-control"] || ""));
check("asks GitHub for releases/latest",
      calls.length === 1 && calls[0].url ===
      "https://api.github.com/repos/Shadow-457/Cubeon/releases/latest");
check("identifies itself with Accept + User-Agent",
      calls[0].options.headers.Accept === "application/vnd.github+json" &&
      !!calls[0].options.headers["User-Agent"]);
check("no Authorization header when no token is configured",
      !("Authorization" in calls[0].options.headers));

// 2. a token, when the deployment has one, is sent upstream
reset();
process.env.GITHUB_TOKEN = "ghp_site";
await call();
check("GITHUB_TOKEN becomes a Bearer header",
      calls[0].options.headers.Authorization === "Bearer ghp_site");
delete process.env.GITHUB_TOKEN;
reset();
process.env.GH_TOKEN = "ghp_alt";
await call();
check("GH_TOKEN works too", calls[0].options.headers.Authorization === "Bearer ghp_alt");
delete process.env.GH_TOKEN;

// 3. junk counters are zero, never NaN
reset();
upstream.payload = { tag_name: "v9", assets: [
  { name: "Cubeon-x86_64.AppImage", download_count: "many" },
  { name: "cubeon_1.0.0_amd64.deb", download_count: -4 },
  { name: "Cubeon-Linux-x86_64-Setup.sh" },
  null,
  "not an asset",
]};
res = await call();
check("garbage/negative/missing counters count as 0",
      res.statusCode === 200 && res.payload.total === 0);
reset();
upstream.payload = { assets: [
  { name: "Cubeon-x86_64.AppImage", download_count: 2.5 },
  { name: "Cubeon-Windows-x64-Setup.exe", download_count: true },
]};
res = await call();
check("a fractional or boolean counter is ignored",
      res.statusCode === 200 && res.payload.total === 0);

// 4. releases that carry no assets still answer, with a zero total
reset();
upstream.payload = { assets: null };
res = await call();
check("a release with null assets totals 0", res.statusCode === 200 && res.payload.total === 0);
reset();
upstream.payload = {};
res = await call();
check("a release with no assets key totals 0", res.statusCode === 200 && res.payload.total === 0);

// 5. upstream failures travel as-is and are never dressed up as a count
reset();
upstream = { ok: false, status: 404 };
res = await call();
check("a private repo without a token stays a 404",
      res.statusCode === 404 && res.payload.error === "release_unavailable");
reset();
upstream = { ok: false, status: 403 };
res = await call();
check("rate limiting stays a 403",
      res.statusCode === 403 && res.payload.error === "release_unavailable");
reset();
upstream = { throws: true };
res = await call();
check("a dead network becomes a 503",
      res.statusCode === 503 && res.payload.error === "release_unavailable");

// 6. only GET is served
reset();
res = await call("POST");
check("POST is refused with Allow: GET", res.statusCode === 405 && res.headers.allow === "GET");
check("a refused method never touches GitHub", calls.length === 0);

console.log(passed + " cases passed");
"""


# ---------------------------------------------------------------------------
# 2. the function and the client script as source: syntax + wiring
# ---------------------------------------------------------------------------
node = shutil.which("node")

if not node:
    skip("the API function runs in Node", "no node on this machine")
    skip("site.js parses", "no node on this machine")
else:
    for path in (API_JS, SITE_JS):
        proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
        check(f"node --check {os.path.relpath(path, REPO)}", proc.returncode == 0,
              (proc.stderr or "").strip()[-200:])

    with tempfile.TemporaryDirectory(prefix="cubeon-download-count-") as tmp:
        harness = os.path.join(tmp, "harness.mjs")
        with open(harness, "w", encoding="utf-8") as handle:
            handle.write(HARNESS)
        proc = subprocess.run([node, harness, API_JS], capture_output=True, text=True)
        lines = (proc.stdout or "").strip().splitlines()
        check("web/api/download-count.js: every Node case passes", proc.returncode == 0,
              ((proc.stdout or "") + (proc.stderr or "")).strip()[-400:])
        check("the harness really ran its cases",
              bool(lines) and re.match(r"^\d+ cases passed$", lines[-1]) is not None,
              lines[-1] if lines else "no output")
        print("       node: " + (lines[-1] if lines else ""))


# ---------------------------------------------------------------------------
# 3. one allow-list, one repository: the JS, the Python and the pages agree
# ---------------------------------------------------------------------------
import importlib.util  # noqa: E402  (kept next to the checks that use it)

_spec = importlib.util.spec_from_file_location(
    "refresh_download_count", os.path.join(TOOLS, "refresh_download_count.py"))
generator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generator)

with open(API_JS, encoding="utf-8") as handle:
    api_source = handle.read()
with open(SITE_JS, encoding="utf-8") as handle:
    site_source = handle.read()

allow_block = re.search(r"const DOWNLOAD_ASSETS = new Set\(\[(.*?)\]\);", api_source, re.S)
check("web/api/download-count.js declares an installer allow-list", bool(allow_block))
js_assets = tuple(re.findall(r'"([^"]+)"', allow_block.group(1))) if allow_block else ()
check("the JS and Python allow-lists are identical",
      js_assets == generator.DOWNLOAD_ASSETS,
      f"js={js_assets} py={generator.DOWNLOAD_ASSETS}")
check("both sides read the same repository",
      "Shadow-457/Cubeon" in api_source
      and generator.DEFAULT_REPOSITORY in api_source
      and generator.DEFAULT_REPOSITORY == "Shadow-457/Cubeon")

check("the page asks the live endpoint first",
      site_source.index("'/api/download-count'")
      < site_source.index("'/assets/download-count.json'"))
check("...and falls back to the file the workflow commits",
      "totalFrom('/assets/download-count.json')" in site_source)
check("it revalidates instead of serving a stale edge copy",
      "cache: 'no-cache'" in site_source)
check("the counter stays hidden until a real number arrives",
      "counter.hidden = false" in site_source)

for page in ("index.html", "download.html"):
    with open(os.path.join(WEB, page), encoding="utf-8") as handle:
        html = handle.read()
    tag = re.search(r"<p[^>]*\bdata-download-count\b[^>]*>", html)
    check(f"{page} carries the counter element", bool(tag))
    check(f"{page} hides it until JavaScript fills it",
          bool(tag) and "hidden" in tag.group(0))


# ---------------------------------------------------------------------------
# 4. the committed static file: the source that needs no hosting config
# ---------------------------------------------------------------------------
with open(COUNTS_JSON, encoding="utf-8") as handle:
    published = json.load(handle)
check("web/assets/download-count.json parses into an object", isinstance(published, dict))
check("its total is the sum of its per-asset counts",
      published.get("total") == sum(published.get("assets", {}).values()),
      f"total={published.get('total')} assets={published.get('assets')}")
check("every published asset is one the site advertises",
      set(published.get("assets", {})) <= set(generator.DOWNLOAD_ASSETS),
      f"stray={sorted(set(published.get('assets', {})) - set(generator.DOWNLOAD_ASSETS))}")
check("it records which release it describes", bool(published.get("release")))
check("it names the repository it was read from",
      published.get("repository") == generator.DEFAULT_REPOSITORY)
check("its generated_at is a UTC timestamp",
      bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                    str(published.get("generated_at")))))


# ---------------------------------------------------------------------------
# 5. the generator's own arithmetic (no network anywhere in this file)
# ---------------------------------------------------------------------------
FAKE = {"tag_name": "v9.9.9", "assets": [
    {"name": "Cubeon-Windows-x64-Setup.exe", "download_count": 7},
    {"name": "Cubeon-x86_64.AppImage", "download_count": 5},
    {"name": "cubeon_1.0.0_amd64.deb", "download_count": 3},
    {"name": "Cubeon-Linux-x86_64-Setup.sh", "download_count": 2},
    {"name": "Cubeon-Windows-x64.zip", "download_count": 900},
    {"name": "Cubeon-Windows-x64-single.exe", "download_count": 400},
    {"name": "Cubeon-x86_64.AppImage.sha256", "download_count": 12},
    {"name": "notes.txt"},
    None,
]}
summary = generator.summarize_release(FAKE)
check("the generator sums the same four installers to the same 17", summary["total"] == 17)
check("...and reports each one by name",
      summary["assets"] == {
          "Cubeon-Windows-x64-Setup.exe": 7, "Cubeon-x86_64.AppImage": 5,
          "cubeon_1.0.0_amd64.deb": 3, "Cubeon-Linux-x86_64-Setup.sh": 2},
      str(summary["assets"]))
check("leftovers and junk entries are ignored",
      "Cubeon-Windows-x64.zip" not in summary["assets"])

junk = generator.summarize_release({"assets": [
    {"name": "Cubeon-x86_64.AppImage", "download_count": "many"},
    {"name": "cubeon_1.0.0_amd64.deb", "download_count": -4},
    {"name": "Cubeon-Linux-x86_64-Setup.sh"},
    {"name": "Cubeon-Windows-x64-Setup.exe", "download_count": True},
    None,
    "not an asset",
]})
check("garbage counters are 0, never NaN or a negative", junk["total"] == 0)
check("a fractional counter is ignored too",
      generator.summarize_release({"assets": [
          {"name": "Cubeon-x86_64.AppImage", "download_count": 2.5}]})["total"] == 0)
check("a release with null assets totals 0", generator.summarize_release({"assets": None})["total"] == 0)
check("...and so does a release with no assets key", generator.summarize_release({})["total"] == 0)

document = generator.build_document(FAKE, repository=generator.DEFAULT_REPOSITORY)
check("a fresh document carries no timestamp", "generated_at" not in document)
check("a timestamp-only difference is not a change",
      generator.counts_match(dict(document, generated_at="2026-01-01T00:00:00Z"), document))
check("a moved count is a change", not generator.counts_match(dict(document, total=18), document))
check("a missing file is a change", not generator.counts_match(None, document))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


captured = []


def fake_urlopen(request, timeout=None):
    captured.append(request)
    return _FakeResponse(FAKE)


release = generator.fetch_latest_release(generator.DEFAULT_REPOSITORY, "tok",
                                         urlopen=fake_urlopen)
check("the generator reads the same endpoint the function does",
      captured[-1].full_url
      == f"https://api.github.com/repos/{generator.DEFAULT_REPOSITORY}/releases/latest",
      captured[-1].full_url)
check("a token becomes a Bearer header",
      captured[-1].get_header("Authorization") == "Bearer tok")
check("the payload is parsed into the release", release.get("tag_name") == "v9.9.9")
generator.fetch_latest_release(generator.DEFAULT_REPOSITORY, None, urlopen=fake_urlopen)
check("with no token, no Authorization header is sent",
      captured[-1].get_header("Authorization") is None)


# ---------------------------------------------------------------------------
# 6. main(): writes, stays quiet when nothing moved, fails loudly when GitHub
#    cannot be read (a scheduled run must go red, not silently stale)
# ---------------------------------------------------------------------------
_real_path = generator.OUTPUT_PATH
_real_fetch = generator.fetch_latest_release
try:
    with tempfile.TemporaryDirectory(prefix="cubeon-download-count-") as tmp:
        target = os.path.join(tmp, "download-count.json")
        generator.OUTPUT_PATH = target
        generator.fetch_latest_release = lambda *a, **k: FAKE

        generator.main([])
        written = json.load(open(target, encoding="utf-8"))
        check("main() writes a document the page can read",
              written.get("total") == 17 and bool(written.get("generated_at")),
              str(written))
        stamp = os.path.getmtime(target)
        generator.main([])
        check("an unchanged count leaves the file (and its timestamp) alone",
              os.path.getmtime(target) == stamp)

        with open(target, "w", encoding="utf-8") as handle:
            json.dump(dict(written, total=99), handle)
        generator.main([])
        check("a moved count is rewritten",
              json.load(open(target, encoding="utf-8")).get("total") == 17)

    with tempfile.TemporaryDirectory(prefix="cubeon-download-count-") as tmp:
        missing = os.path.join(tmp, "download-count.json")
        generator.OUTPUT_PATH = missing
        failure = urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", {}, None)

        def boom(*_args, **_kwargs):
            raise failure

        generator.fetch_latest_release = boom
        stream = io.StringIO()
        real_stderr = sys.stderr
        sys.stderr = stream
        try:
            code = generator.main([])
        finally:
            sys.stderr = real_stderr
        check("an unreadable GitHub exits non-zero", code == 1)
        check("...without writing a half-truth", not os.path.exists(missing))
        check("...and names the fix", "needs a token" in stream.getvalue(),
              stream.getvalue().strip())
finally:
    generator.OUTPUT_PATH = _real_path
    generator.fetch_latest_release = _real_fetch


# ---------------------------------------------------------------------------
# 7. the workflow is what refreshes the file, with no stored secret
# ---------------------------------------------------------------------------
try:
    with open(WORKFLOW, encoding="utf-8") as handle:
        workflow = handle.read()
except OSError:
    workflow = ""
check(".github/workflows/download-count.yml exists", bool(workflow))
check("it uses the runner's own token, not a stored secret",
      "secrets.GITHUB_TOKEN" in workflow)
check("it is allowed to commit the refreshed file", "contents: write" in workflow)
check("it runs on a schedule", "cron:" in workflow)
check("it runs the generator", "python3 tools/refresh_download_count.py" in workflow)
check("it commits only when the number actually moved",
      "git diff --quiet -- web/assets/download-count.json" in workflow)

print(f"\n{_passed} checks passed")

