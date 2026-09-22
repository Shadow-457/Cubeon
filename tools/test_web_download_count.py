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
