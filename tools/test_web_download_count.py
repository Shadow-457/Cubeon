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

async function settle() { await new Promise((resolve) => setTimeout(resolve, 5)); }

// 1. page load reads the shared total and shows it to everyone
value = 7;
boot();
await settle();
check("page load shows the shared total",
      counter.textContent === "7 downloads so far" && counter.hidden === false);
check("loading only READS the counter (no /hit, exactly one request)",
      requested.length === 1 && requested[0].action === "get");

// 2. a press adds one, globally, and repaints with the fresh shared value
press("/windowsdownload");
await settle();
check("pressing bumps the shared total",
      counter.textContent === "8 downloads so far");
check("the press went to /hit exactly once with keepalive",
      requested.length === 2 && requested[1].action === "hit" && requested[1].keepalive === true);

// 3. singular
value = 1;
boot();
await settle();
check("one press reads singular", counter.textContent === "1 download so far");

// 4. zero is a real number and is shown
value = 0;
boot();
await settle();
check("zero is shown, not hidden", counter.textContent === "0 downloads so far");

// 5. only routes that hand over a FILE are counted
boot();
await settle();
press("/");
press("/help");
press("/download");
press("/privacy");
await settle();
check("nav and page links never touch the counter",
      requested.length === 1 && counter.textContent === "0 downloads so far");

// 6. junk clicks are ignored without crashing
boot();
await settle();
clicks.forEach((handler) => handler({ target: null }));
clicks.forEach((handler) => handler({ target: { tagName: "DIV" } }));
await settle();
check("a click with no anchor behind it changes nothing",
      requested.length === 1 && counter.textContent === "0 downloads so far");

// 7. an unreachable counter hides the line - until it answers again
value = 12;
getFails = true;
boot();
await settle();
check("an unreachable counter hides the line", counter.hidden === true);
getFails = false;
press("/linuxdownload");
await settle();
check("...and the first working press brings it back with the shared value",
      counter.textContent === "13 downloads so far");

// 8. big numbers stay readable
value = 12345;
boot();
await settle();
check("thousands are grouped",
      counter.textContent.replace(/\D/g, "") === "12345" &&
      /downloads so far$/.test(counter.textContent) &&
      /\D/.test(counter.textContent.replace(/^\d+/, "")));

console.log(passed + " cases passed");
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
      ABACUS in site_source and "ask('get')" in site_source and "ask('hit')" in site_source)
count_block = site_source.split("(function downloadCount")[1].split("})();")[0] \
    if "(function downloadCount" in site_source else ""
# The count itself must never be read from or written to localStorage - it only
# ever comes from Abacus. The one localStorage use allowed here is the testing
# mode's local flag (Ctrl+Shift+T / ?nocount=1): it stores nothing about the
# count, and every line touching storage for it names TEST_FLAG.
per_device_storage = [line.strip() for line in count_block.splitlines()
                      if "localStorage." in line and "TEST_FLAG" not in line]
check("the counter block holds no per-device storage", not per_device_storage,
      per_device_storage[0] if per_device_storage else count_block[:80])
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
files_block = re.search(r"const FILES = \{(.*?)\};", worker_source, re.S)
check("the Worker declares its file routes", bool(files_block))
worker_routes = tuple(re.findall(r'"(/[\w-]+)"', files_block.group(1))) if files_block else ()
check("the Worker serves every route the site counts",
      tuple(sorted(worker_routes)) == tuple(sorted(site_routes)),
      f"worker={sorted(worker_routes)} site.js={sorted(site_routes)}")
check("the Worker reads its token from a secret, never from source",
      "env.GITHUB_TOKEN" in worker_source and "Bearer " in worker_source)

leak = subprocess.run(
    ["grep", "-rl", "--exclude-dir=.git", "--exclude-dir=archive",
     "--exclude-dir=dist", "--exclude-dir=build", "--exclude-dir=node_modules",
     "--exclude-dir=__pycache__", "--exclude-dir=.wrangler",
     "--exclude=test_web_download_count.py",  # this file quotes the patterns
     "github_pat_\\|ghp_[A-Za-z0-9]\\{20,\\}", REPO],
    capture_output=True, text=True)
check("no GitHub token is committed anywhere", leak.stdout.strip() == "",
      leak.stdout.strip())

with open(os.path.join(REPO, "worker", "wrangler-downloads.toml"), encoding="utf-8") as handle:
    toml_source = handle.read()
check("the Worker's config names it and has no KV to maintain",
      'name = "cubeon-downloads"' in toml_source and "kv_namespaces" not in toml_source)

# ---------------------------------------------------------------------------
# 4b. abuse protection for the Worker that holds a credential
#
# The URL is public - the site and the launcher both hand it out, and it is in
# this repo - so "who can call it" is everyone, fork or not. The scarce resource
# is the GitHub token's 5000/hour API budget, and before this the Worker spent
# one call on every single press: ~1.4 requests/second for an hour took the
# download buttons down for every user. The edge cache is the fix that matters
# (a flood then costs ZERO API calls); the optional RATE_LIMITER is the second
# gate. Pinned here because CI runs Python and NOT the Node worker tests, and
# because "just fetch the release each time" is exactly the simplification a
# later edit would make.
# ---------------------------------------------------------------------------
check("the release lookup is edge-cached, not refetched per request",
      "caches.default" in worker_source and "cache.match(" in worker_source
      and "cache.put(" in worker_source)
check("a failed lookup is NOT cached (an outage must not be pinned for 5 minutes)",
      "if (cache && assets.length)" in worker_source)
check("only name/url/size reach the cache (no private release fields)",
      ".map((a) => ({ name: a.name, url: a.url, size: a.size }))" in worker_source)
ttl = re.search(r"const RELEASE_CACHE_SECONDS = (\d+)", worker_source)
check("the cached release carries a TTL",
      bool(ttl) and f"max-age=${{RELEASE_CACHE_SECONDS}}" in worker_source)
check("...measured in minutes (seconds re-costs, hours hides a release)",
      bool(ttl) and 60 <= int(ttl.group(1)) <= 3600, ttl.group(1) if ttl else "no constant")
check("the streamed installer is cacheable, not no-store",
      '"no-store"' not in worker_source)
check("an optional RATE_LIMITER gate is honoured, with a 429",
      "env.RATE_LIMITER" in worker_source and "429" in worker_source)
check("...and a broken/unbound limiter degrades to serving, never to an error",
      ".catch(() => null)" in worker_source)
check("a missing cache degrades to the old one-call-per-request path",
      "function edgeCache()" in worker_source and "return null;" in worker_source)
check("the rate-limit opt-in is documented in the Worker's own config",
      "RATE_LIMITER" in toml_source)


def _before(source, first, second):
    """True when `first` appears in `source` and strictly before `second`.

    A plain `first in source` check is not enough for an ORDER property: the
    throttle can sit anywhere in the file and still be found. Indexing is what
    makes the assertion mean "this gate runs first".
    """
    a, b = source.find(first), source.find(second)
    return a != -1 and b != -1 and a < b


def _post_branch(source):
    """The slice of fetch() that handles a POST, up to the first dispatch.

    Returns "" when either anchor is missing, so a check built on it fails
    rather than raising. The end anchor is the POST-branch unsubscribe handler,
    NOT the pathname test - the GET branch tests the same path, and a
    `find` for it would land above the start anchor.
    """
    start = source.find('if (request.method === "POST")')
    end = source.find("return handleUnsubscribe(request, env)")
    if start == -1 or end == -1 or start > end:
        return ""
    return source[start:end]


# Order, not mere presence: the whole point of the throttle is that it costs
# nothing, so it has to run before the token is read or GitHub is called.
check("the throttle runs before the token check and before GitHub",
      _before(worker_source, "await throttle(request, env)", "if (!env.GITHUB_TOKEN)")
      and _before(worker_source, "await throttle(request, env)", "await latestRelease(env)"))

with open(os.path.join(REPO, "worker", "cubeon-waitlist.js"), encoding="utf-8") as handle:
    waitlist_source = handle.read()
with open(os.path.join(REPO, "worker", "wrangler-waitlist.toml"), encoding="utf-8") as handle:
    waitlist_toml = handle.read()
# The waitlist is the only Worker whose writes carry no identity - it is a
# public signup form - and it shares its namespace with the tally, so a script
# posting made-up addresses used to be able to spend the free tier's
# account-wide ~1k writes/day and take every REAL signup down with it.
#
# The gate must sit INSIDE the POST branch and above the dispatch, which is why
# this slices the source between those two anchors instead of searching the
# whole file: "env.RATE_LIMITER" placed after the handlers would still be found
# by a naive check while protecting nothing.
check("the waitlist throttles POSTs before dispatching to any handler",
      "env.RATE_LIMITER" in _post_branch(waitlist_source))
check("...and the opt-in is documented in its config",
      "RATE_LIMITER" in waitlist_toml)

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

# the community link must exist everywhere it was promised
INVITE = "https://discord.gg/Vj7g7vVY8K"
for page in web_pages:
    with open(os.path.join(WEB, page), encoding="utf-8") as handle:
        html = handle.read()
    check(f"{page} links to the Discord server", INVITE in html)
with open(os.path.join(WEB, "index.html"), encoding="utf-8") as handle:
    index_html = handle.read()
check("the landing page has a hero Discord button", "discord-cta" in index_html)
check("subpages carry the Discord nav link",
      all("nav-discord" in open(os.path.join(WEB, p), encoding="utf-8").read()
          for p in web_pages if p != "index.html"))

# a /page -> /page.html redirect under cleanUrls is a ERR_TOO_MANY_REDIRECTS loop
for config_path in (os.path.join(REPO, "vercel.json"), os.path.join(WEB, "vercel.json")):
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)
    loops = [rule.get("source") for rule in config.get("redirects", [])
             if config.get("cleanUrls") and rule.get("source") + ".html" == rule.get("destination")]
    check(f"{os.path.relpath(config_path, REPO)}: no page redirect that cleanUrls undoes",
          not loops, f"looping rules: {loops}")

print(f"\n{_passed} checks passed")

