#!/usr/bin/env python3
"""Guards for the website's download counters and download routes.

Three things must keep holding at once, because each of them once broke the
site in a way code review couldn't see:

  1. The visible count is the SHARED press total served by Abacus
     (abacus.jasoncameron.dev) - it is global, not per-device, and the page
     must never fetch anything else for it. All of this is exercised by
     running the REAL web/assets/site.js in Node on a DOM stub.
  2. The download routes stream from the cubeon-downloads Worker, because the
     repository is PRIVATE (GitHub answers anonymous visitors with an auth
     wall) and signed asset URLs expire within the hour.
  3. Every page loads web/assets/site.js - index.html once shipped without the
     tag, which silently killed the counter, cookie note and mobile menu.

No test here touches the network: GitHub and Abacus are both stubbed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
WEB = os.path.join(REPO, "web")
SITE_JS = os.path.join(WEB, "assets", "site.js")
WORKER_JS = os.path.join(REPO, "worker", "cubeon-downloads.js")
WORKER_URL = "https://cubeon-downloads.hamza-457-shahbaz.workers.dev"
ABACUS = "https://abacus.jasoncameron.dev"
GONE = [  # the rejected GitHub-count plumbing; kept out on purpose
    os.path.join(WEB, "api", "download-count.js"),
    os.path.join(WEB, "assets", "download-count.json"),
    os.path.join(REPO, ".github", "workflows", "download-count.yml"),
    os.path.join(REPO, "tools", "refresh_download_count.py"),
]

_passed = 0


def check(label, condition, detail=""):
    global _passed
    if condition:
        _passed += 1
        print("PASS " + label)
    else:
        print("FAIL " + label + (("  (" + detail + ")") if detail else ""))
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# 1. the shared counter, driven through the REAL site.js in Node
# ---------------------------------------------------------------------------
HARNESS = r"""
import { readFileSync } from "node:fs";

const source = readFileSync(process.argv[2], "utf8");

let passed = 0;
function check(label, condition) {
  if (condition) { passed++; console.log("PASS " + label); }
  else { console.log("FAIL " + label); process.exit(1); }
}

const counter = { textContent: "", hidden: true };
let clicks = [];
function makeElement() {
  return {
    setAttribute() {}, addEventListener() {}, appendChild() {}, remove() {},
    querySelector: makeElement,
    classList: { add() {}, remove() {}, toggle() { return false; }, contains() { return false; } },
  };
}
globalThis.document = {
  documentElement: { classList: { add() {} } },
  body: { appendChild() {} },
  getElementById() { return null; },
  createElement: makeElement,
  addEventListener(type, handler) { if (type === "click") clicks.push(handler); },
  querySelectorAll(selector) {
    return selector === "[data-download-count]" ? [counter] : [];
  },
};
globalThis.window = globalThis;
// Node 21+ exposes `navigator` as a getter only, so define rather than assign.
Object.defineProperty(globalThis, "navigator", {
  configurable: true, writable: true,
  value: { platform: "Linux x86_64", userAgent: "Mozilla/5.0 (X11; Linux x86_64)" },
});
globalThis.matchMedia = () => ({ matches: false });
globalThis.localStorage = { getItem() { return null; }, setItem() {} };

// A stand-in for Abacus: records every request, answers with a value.
let value = 0;
let hitFails = false;
let getFails = false;
let requested = [];
function urlFor(action) {
  return "https://abacus.jasoncameron.dev/" + action + "/cubeon-site/downloads";
}
globalThis.fetch = async (url, options) => {
  const target = String(url);
  const action = target.indexOf("/hit/") !== -1 ? "hit" : "get";
  requested.push({ action, keepalive: !!(options && options.keepalive) });
  if ((action === "hit" && hitFails) || (action === "get" && getFails)) {
    throw new Error("counter unreachable");
  }
  if (action === "hit") value += 1;
  return { ok: true, status: 200, json: async () => ({ value }) };
};

function boot() {

// 1. page load reads the shared total and shows it to everyone
value = 7;
boot();
check("page load shows the shared total",
      counter.textContent === "7 downloads so far" && counter.hidden === false);
check("loading only READS the counter (no /hit, exactly one request)",
      requested.length === 1 && requested[0].action === "get");

// 2. a press adds one, globally, and repaints with the fresh shared value
press("/windowsdownload");
check("pressing bumps the shared total",
      counter.textContent === "8 downloads so far");
check("the press went to /hit exactly once with keepalive",
      requested.length === 2 && requested[1].action === "hit" && requested[1].keepalive === true);

// 3. singular
value = 1;
boot();
check("one press reads singular", counter.textContent === "1 download so far");

// 4. zero is a real number and is shown
value = 0;
boot();
check("zero is shown, not hidden", counter.textContent === "0 downloads so far");

// 5. only routes that hand over a FILE are counted
boot();
press("/");
press("/help");
press("/download");
press("/privacy");
check("nav and page links never touch the counter",
      requested.length === 1 && counter.textContent === "0 downloads so far");

// 6. junk clicks are ignored without crashing
boot();
clicks.forEach((handler) => handler({ target: null }));
clicks.forEach((handler) => handler({ target: { tagName: "DIV" } }));
check("a click with no anchor behind it changes nothing",
      requested.length === 1 && counter.hidden === true);

// 7. an unreachable counter hides the line - until it answers again
value = 12;
getFails = true;
boot();
check("an unreachable counter hides the line", counter.hidden === true);
getFails = false;
press("/linuxdownload");
check("...and the first working press brings it back with the shared value",
      counter.textContent === "13 downloads so far");

// 8. big numbers stay readable
value = 12345;
boot();
check("thousands are grouped", /1\D?2345 downloads so far/.test(counter.textContent));

console.log(passed + " cases passed");
"""

  clicks = [];
  requested = [];
  counter.textContent = "";
  counter.hidden = true;
  new Function(source)();
}
function anchor(href) {
  const element = {
    pathname: href,
    getAttribute(name) { return name === "href" ? href : null; },
  };
  element.closest = () => element;
  return element;
}
function press(href) {
  clicks.forEach((handler) => handler({ target: anchor(href) }));
}

// sentinel: cases are appended right after this line
"""


# ---------------------------------------------------------------------------
# 2. run the harness against the real site.js
# ---------------------------------------------------------------------------
node = shutil.which("node")
check("node is available for the browser harness", bool(node))
if node:
    for path in (SITE_JS, WORKER_JS):
        proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
        check(f"node --check {os.path.relpath(path, REPO)}", proc.returncode == 0,
              (proc.stderr or "").strip()[-200:])

    with tempfile.TemporaryDirectory(prefix="cubeon-download-count-") as tmp:
        harness = os.path.join(tmp, "harness.mjs")
        with open(harness, "w", encoding="utf-8") as handle:
            handle.write(HARNESS)
        proc = subprocess.run([node, harness, SITE_JS], capture_output=True, text=True)
        lines = (proc.stdout or "").strip().splitlines()
        check("web/assets/site.js: every browser case passes", proc.returncode == 0,
              ((proc.stdout or "") + (proc.stderr or "")).strip()[-400:])
        check("the harness really ran its cases",
              bool(lines) and re.match(r"^\d+ cases passed$", lines[-1]) is not None,
              lines[-1] if lines else "no output")
        print("       node: " + (lines[-1] if lines else ""))


# ---------------------------------------------------------------------------
# 3. the page source: one shared counter, no per-device leftovers
# ---------------------------------------------------------------------------
with open(SITE_JS, encoding="utf-8") as handle:
    site_source = handle.read()

check("the count is the shared Abacus total",
      ABACUS in site_source and "/hit/" in site_source and "/get/" in site_source)
count_block = site_source.split("(function downloadCount")[1].split("})();")[0] \
    if "(function downloadCount" in site_source else ""
check("the counter block holds no per-device storage", "localStorage" not in count_block,
      count_block[:80])
check("nothing of the rejected GitHub plumbing remains on the page",
      "/api/download-count" not in site_source and "download-count.json" not in site_source)

routes_block = re.search(r"var ROUTES = \[(.*?)\];", site_source, re.S)
check("site.js declares which routes count as a download", bool(routes_block))
site_routes = tuple(re.findall(r"'([^']+)'", routes_block.group(1))) if routes_block else ()
with open(os.path.join(WEB, "vercel.json"), encoding="utf-8") as handle:
    vercel_config = json.load(handle)
asset_routes = tuple(rule.get("source") for rule in vercel_config.get("redirects", []))
check("every counted route is a real download route, and all of them are counted",
      set(site_routes) == set(asset_routes),
      f"site.js={sorted(site_routes)} web/vercel.json={sorted(asset_routes)}")
check("all download routes point at the streaming Worker, not GitHub",
      all(rule.get("destination", "").startswith(WORKER_URL + "/")
          for rule in vercel_config.get("redirects", [])))

# the rejected plumbing must stay rejected
for path in GONE:
    check(f"{os.path.relpath(path, REPO)} stays gone", not os.path.exists(path))

# continued: worker checks, page wiring, legal copy, loop guard

# ---------------------------------------------------------------------------
# 4. the Worker: routes, secrets, and no token in any repo file
# ---------------------------------------------------------------------------
with open(WORKER_JS, encoding="utf-8") as handle:
    worker_source = handle.read()
worker_routes = re.findall(r'"(/\w+download)":', worker_source)
check("the Worker serves every route the site counts",
      tuple(sorted(worker_routes)) == tuple(sorted(site_routes)),
      f"worker={sorted(worker_routes)} site.js={sorted(site_routes)}")
check("the Worker reads its token from a secret, never from source",
      "env.GITHUB_TOKEN" in worker_source and "Bearer " in worker_source)

leak = subprocess.run(
    ["grep", "-rl", "--exclude-dir=.git", "--exclude-dir=archive",
     "--exclude-dir=dist", "--exclude-dir=build", "--exclude-dir=node_modules",
     "--exclude-dir=__pycache__", "--exclude-dir=.wrangler",
     "github_pat_\\|ghp_[A-Za-z0-9]\\{20,\\}", REPO],
    capture_output=True, text=True)
check("no GitHub token is committed anywhere", leak.stdout.strip() == "",
      leak.stdout.strip())

with open(os.path.join(REPO, "worker", "wrangler-downloads.toml"), encoding="utf-8") as handle:
    toml_source = handle.read()
check("the Worker's config names it and has no KV to maintain",
      'name = "cubeon-downloads"' in toml_source and "kv_namespaces" not in toml_source)

# ---------------------------------------------------------------------------
# 5. every page wires the shared file (index.html once shipped without it)
# ---------------------------------------------------------------------------
web_pages = sorted(name for name in os.listdir(WEB) if name.endswith(".html"))
check("there are pages to check", len(web_pages) >= 3)
for page in web_pages:
    with open(os.path.join(WEB, page), encoding="utf-8") as handle:
        html = handle.read()
    check(f"{page} loads the shared assets/site.js",
          re.search(r"<script[^>]*assets/site\.js", html) is not None)
    check(f"{page} keeps only one copy of the shared handlers",
          "q.querySelector('.q-a')" not in html and "classList.toggle('on'" not in html)

for page in ("index.html", "download.html"):
    with open(os.path.join(WEB, page), encoding="utf-8") as handle:
        html = handle.read()
    tag = re.search(r"<p[^>]*\bdata-download-count\b[^>]*>", html)
    check(f"{page} carries the counter element", bool(tag))
    check(f"{page} hides it until a number exists",
          bool(tag) and "hidden" in tag.group(0))

# the cookies/privacy pages must keep describing the counter honestly
with open(os.path.join(WEB, "cookies.html"), encoding="utf-8") as handle:
    cookies_html = handle.read()
check("cookies.html discloses the counter service",
      "Abacus" in cookies_html and "abacus" in cookies_html)
with open(os.path.join(WEB, "privacy.html"), encoding="utf-8") as handle:
    privacy_html = handle.read()
check("privacy.html discloses the shared press total", "download counter" in privacy_html)

# a /page -> /page.html redirect under cleanUrls is a ERR_TOO_MANY_REDIRECTS loop
for config_path in (os.path.join(REPO, "vercel.json"), os.path.join(WEB, "vercel.json")):
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)
    loops = [rule.get("source") for rule in config.get("redirects", [])
             if config.get("cleanUrls") and rule.get("source") + ".html" == rule.get("destination")]
    check(f"{os.path.relpath(config_path, REPO)}: no page redirect that cleanUrls undoes",
          not loops, f"looping rules: {loops}")

print(f"\n{_passed} checks passed")

