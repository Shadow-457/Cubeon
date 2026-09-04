#!/usr/bin/env python3
"""
Tests for cubeon/invites.py - run with:

    python3 tools/test_invites.py

Needs no network and no Cloudflare account: the invite format and the local
record are pure, and the network client is exercised against a stubbed
`requests` module.

Two kinds of check earn their keep here:

  * **Format parity with the Worker.** cubeon/invites.py defines the alphabet
    and worker/cubeon-invites.js mirrors it in a regex. If those drift, the
    launcher mints codes the server rejects - and only in production, because
    nothing local would notice. So this reads the Worker source and compares.

  * **Ordering around the secret.** The secret is the only proof a host owns
    their code. If it isn't on disk before the claim goes out, a crash mid-mint
    strands a claimed code that can never be repointed.
"""
import logging
import os
import re
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The module logs a warning on every simulated network failure, which is correct
# behaviour and pure noise in a test that causes those failures on purpose.
logging.disable(logging.WARNING)

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import invites  # noqa: E402

# Everything below writes to a scratch dir. Pointing the module at the real
# ~/.cubeon_launcher/invites.json would clobber the user's own hosted codes,
# taking their secrets with it.
_scratch = tempfile.mkdtemp(prefix="cubeon-invites-test-")
invites.CUBEON_HOME = _scratch
invites.INVITES_PATH = os.path.join(_scratch, "invites.json")


def reset_store():
    try:
        os.unlink(invites.INVITES_PATH)
    except OSError:
        pass


# ------------------------------------------------------------- code format ---
print("\n1. code format")

codes = [invites.generate() for _ in range(2000)]
check("generate() always produces canonical form",
      all(invites.is_canonical(c) for c in codes),
      next((c for c in codes if not invites.is_canonical(c)), ""))
check("generate() round-trips through normalize()",
      all(invites.normalize(c) == c for c in codes))
check("2000 codes, no duplicates", len(set(codes)) == 2000)

# The whole reason for a restricted alphabet: these pairs are the ones people
# mix up reading a code off a screenshot or hearing it out loud.
for bad in "01258OILZSB":
    check(f"alphabet excludes ambiguous {bad!r}", bad not in invites.ALPHABET)
check("alphabet has no duplicates",
      len(set(invites.ALPHABET)) == len(invites.ALPHABET))
check("code space is large enough to not need collision handling",
      len(invites.ALPHABET) ** (invites.GROUP_LEN * invites.GROUPS) > 10 ** 11,
      f"{len(invites.ALPHABET)}^{invites.GROUP_LEN * invites.GROUPS}")

print("\n2. normalize() forgives how codes actually travel")
for text, expect in [
    ("CUBE-7F4K-9QMN", "CUBE-7F4K-9QMN"),
    ("cube-7f4k-9qmn", "CUBE-7F4K-9QMN"),          # retyped in lower case
    ("CUBE 7F4K 9QMN", "CUBE-7F4K-9QMN"),          # spaces instead of dashes
    ("CUBE7F4K9QMN", "CUBE-7F4K-9QMN"),            # dashes dropped
    ("  cube-7f4k-9qmn\n", "CUBE-7F4K-9QMN"),      # copy-paste whitespace
    ("7F4K-9QMN", "CUBE-7F4K-9QMN"),               # prefix stripped by a human
    ("cubeon.run.place/CUBE-7F4K-9QMN", "CUBE-7F4K-9QMN"),   # pasted as a URL
    ("join: CUBE-7F4K-9QMN !!", "CUBE-7F4K-9QMN"),  # pasted with chat around it
    ("CUBE--7F4K--9QMN", "CUBE-7F4K-9QMN"),        # doubled separators
]:
    check(f"accepts {text!r}", invites.normalize(text) == expect,
          f"got {invites.normalize(text)!r}")

for text in [
    "", "CUBE", "CUBE-7F4K", "CUBE-7F4K-9QM", "CUBE-7F4K-9QMNX",
    "CUBE-0000-0000",   # excluded digits
    "CUBE-IIII-LLLL",   # excluded letters
    "CUBE-7F4K-9QM0",   # one excluded char in an otherwise valid code
    None, 12345, [],
]:
    check(f"rejects {text!r}", invites.normalize(text) is None,
          f"got {invites.normalize(text)!r}")

check("is_valid agrees with normalize",
      invites.is_valid("cube7f4k9qmn") and not invites.is_valid("CUBE-0000-0000"))
check("is_canonical is stricter than is_valid",
      invites.is_valid("cube7f4k9qmn") and not invites.is_canonical("cube7f4k9qmn"))

print("\n3. secrets")
secrets_seen = [invites.generate_secret() for _ in range(200)]
check("secrets are unique", len(set(secrets_seen)) == 200)
check("secrets are long enough to be unguessable",
      all(len(s) >= 40 for s in secrets_seen), f"min={min(len(s) for s in secrets_seen)}")
check("secrets survive an HTTP header unencoded",
      all(re.fullmatch(r"[A-Za-z0-9_-]+", s) for s in secrets_seen))
# The Worker's own bearer regex has to accept what this produces, or every
# publish 401s in production while every local test passes. Compare by
# compiling the Worker's actual character class - checking membership in the
# raw class *string* would silently pass anything, since 'q' is not literally
# in "A-Za-z0-9._~+/=-".
worker_src = open(os.path.join(PROJECT, "worker", "cubeon-invites.js"),
                  encoding="utf-8").read()
bearer_re = re.search(r"\^Bearer \((\[[^\]]+\]\{\d+,\d+\})\)\$", worker_src)
check("Worker's bearer pattern was found in source", bearer_re is not None)
if bearer_re:
    worker_bearer = re.compile("^" + bearer_re.group(1) + "$")
    check("Worker accepts the secrets this module generates",
          all(worker_bearer.match(s) for s in secrets_seen),
          f"worker accepts {bearer_re.group(1)}; "
          f"first rejected: "
          f"{next((s for s in secrets_seen if not worker_bearer.match(s)), '-')!r}")
    # token_urlsafe emits base64url, so these two characters appear routinely
    # and are exactly what a hand-written class tends to forget.
    check("...including the '-' and '_' that base64url produces",
          worker_bearer.match("a" * 20 + "-_") is not None)

print("\n4. the launcher's alphabet matches the Worker's regex")
# The one cross-language coupling in the whole feature.
worker_alpha = re.search(r"CODE_RE = /\^CUBE-\[([A-Z0-9]+)\]", worker_src)
check("Worker CODE_RE was found in source", worker_alpha is not None)
if worker_alpha:
    check("alphabets are identical",
          worker_alpha.group(1) == invites.ALPHABET,
          f"worker={worker_alpha.group(1)}\n       python={invites.ALPHABET}")
check("Worker group length matches",
      f"{{{invites.GROUP_LEN}}}" in worker_src)
check("Worker prefix matches", f"/^{invites.PREFIX}-" in worker_src)

# And end-to-end: real generated codes must satisfy the Worker's actual regex.
if worker_alpha:
    js_equivalent = re.compile(
        f"^CUBE-[{worker_alpha.group(1)}]{{4}}-[{worker_alpha.group(1)}]{{4}}$")
    check("every generated code passes the Worker's regex",
          all(js_equivalent.match(c) for c in codes))

# ------------------------------------------------------------ local record ---
print("\n5. local record")
reset_store()

check("no store yet -> nothing hosted", invites.get_hosted("1.21.11") is None)
check("no store yet -> empty lists",
      invites.list_hosted() == [] and invites.list_joined() == [])

code = invites.generate()
secret = invites.generate_secret()
invites.remember_hosted(code, "1.21.11", secret, address="a.example.com:25565")

got = invites.get_hosted("1.21.11")
check("get_hosted finds it", got is not None and got[0] == code)
check("the secret is kept - without it the code can never be repointed",
      got[1]["secret"] == secret)
check("get_hosted is scoped to the version",
      invites.get_hosted("1.20.1") is None)

check("list_hosted strips the secret",
      "secret" not in invites.list_hosted()[0],
      str(invites.list_hosted()[0]))
check("list_hosted still returns the useful fields",
      invites.list_hosted()[0]["code"] == code and
      invites.list_hosted()[0]["address"] == "a.example.com:25565")

invites.update_hosted_address(code, "b.example.com:60000")
check("update_hosted_address repoints without changing the code",
      invites.get_hosted("1.21.11")[1]["address"] == "b.example.com:60000")
check("...and keeps the secret", invites.get_hosted("1.21.11")[1]["secret"] == secret)

try:
    invites.update_hosted_address(invites.generate(), "c.example.com:1")
    check("updating an unknown code raises", False)
except KeyError:
    check("updating an unknown code raises", True)

try:
    invites.remember_hosted("not-a-code", "1.21.11", secret)
    check("remembering a malformed code raises", False)
except ValueError:
    check("remembering a malformed code raises", True)

# Codes are stored canonically, so a lower-case lookup hits the same record
# instead of silently creating a second one.
invites.update_hosted_address(code.lower(), "d.example.com:1234")
check("a lower-case code updates the same record, not a new one",
      len(invites.list_hosted()) == 1 and
      invites.get_hosted("1.21.11")[1]["address"] == "d.example.com:1234")

if os.name != "nt":
    mode = os.stat(invites.INVITES_PATH).st_mode & 0o777
    check("invites.json is not readable by other users (it holds secrets)",
          mode == 0o600, f"mode={oct(mode)}")

invites.remember_joined(code, "d.example.com:1234")
check("joined codes are recorded", invites.list_joined()[0]["code"] == code)

check("forget_hosted removes it", invites.forget_hosted(code) is True)
check("forget_hosted on an absent code is False",
      invites.forget_hosted(code) is False)
check("forgetting a hosted code leaves joined history alone",
      len(invites.list_joined()) == 1)

print("\n6. a corrupt store never breaks the launcher")
for content in ["", "{", "null", "[]", '{"hosted": "nope"}', '{"hosted": {"X": 1}}']:
    with open(invites.INVITES_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        invites.list_hosted()
        invites.list_joined()
        invites.get_hosted("1.21.11")
        ok = True
        detail = ""
    except Exception as ex:
        ok = False
        detail = f"{type(ex).__name__}: {ex}"
    check(f"survives store content {content!r}", ok, detail)

# ---------------------------------------------------------- network client ---
print("\n7. network client (stubbed requests)")
reset_store()


class FakeResponse:
    def __init__(self, status, body=None, raw=None):
        self.status_code = status
        self._body = body
        self._raw = raw

    def json(self):
        if self._raw is not None:
            raise ValueError("not json")
        return self._body


class FakeRequests:
    """Records calls and replays queued responses.

    Mirrors only what invites.py uses: put/get/delete plus RequestException.
    """
    RequestException = invites.requests.RequestException

    def __init__(self):
        self.calls = []
        self.queue = []

    def _next(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        if not self.queue:
            raise AssertionError(f"unexpected {method} {url}")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def put(self, url, **kw):
        return self._next("PUT", url, **kw)

    def get(self, url, **kw):
        return self._next("GET", url, **kw)

    def delete(self, url, **kw):
        return self._next("DELETE", url, **kw)


real_requests = invites.requests
fake = FakeRequests()
invites.requests = fake
API = "https://invite.test.invalid"

# --- publish_new: the mint-and-claim path -----------------------------------
fake.queue = [FakeResponse(200, {"written": True, "claimed": True})]
res = invites.publish_new("1.21.11", "bluefox-1234.gl.joinmc.link:52341",
                          version="1.21.11", loader="fabric", base_url=API)
check("publish_new succeeds", res["ok"] is True, str(res))
check("...returns a canonical code", invites.is_canonical(res["code"]))
check("...and remembers it locally",
      invites.get_hosted("1.21.11")[0] == res["code"])
check("...with the address the server accepted",
      invites.get_hosted("1.21.11")[1]["address"] == "bluefox-1234.gl.joinmc.link:52341")

call = fake.calls[-1]
check("PUTs to /i/<CODE>", call["url"] == f"{API}/i/{res['code']}", call["url"])
check("sends the secret as a bearer token",
      call["headers"]["Authorization"]
      == f"Bearer {invites.get_hosted('1.21.11')[1]['secret']}")
check("sends address, version and loader",
      call["json"] == {"address": "bluefox-1234.gl.joinmc.link:52341",
                       "version": "1.21.11", "loader": "fabric"},
      str(call["json"]))
check("the secret is never put in the URL",
      invites.get_hosted("1.21.11")[1]["secret"] not in call["url"])
check("requests are given a timeout (a hung host click reads as a crash)",
      call.get("timeout") is not None)

# --- publish: the repeat-host path ------------------------------------------
hosted_code, hosted_meta = invites.get_hosted("1.21.11")
fake.queue = [FakeResponse(200, {"written": False, "claimed": False})]
res = invites.publish(hosted_code, hosted_meta["secret"],
                      "bluefox-1234.gl.joinmc.link:52341", base_url=API)
check("re-publishing an unchanged address reports no write",
      res["ok"] and res["written"] is False, str(res))

fake.queue = [FakeResponse(200, {"written": True})]
res = invites.publish(hosted_code, hosted_meta["secret"],
                      "bluefox-1234.gl.joinmc.link:60000", base_url=API)
check("a new port is published", res["ok"] and res["written"] is True)
check("...and the local record follows the new address",
      invites.get_hosted("1.21.11")[1]["address"] == "bluefox-1234.gl.joinmc.link:60000")
check("...while the code stays the same (friends keep the old link)",
      invites.get_hosted("1.21.11")[0] == hosted_code)

check("a malformed code fails locally, with no request",
      invites.publish("nope", "s", "a.example.com:1", base_url=API)["error"] == "bad_code")

# --- collision retry --------------------------------------------------------
before = len(fake.calls)
fake.queue = [FakeResponse(409, {"error": "code_taken"}),
              FakeResponse(200, {"written": True, "claimed": True})]
res = invites.publish_new("1.20.1", "a.example.com:25565", base_url=API)
check("a taken code is retried with a fresh one", res["ok"] is True, str(res))
check("...and it took exactly two requests", len(fake.calls) - before == 2)
check("...leaving no record of the code that was never claimed",
      len([e for e in invites.list_hosted() if e.get("version_id") == "1.20.1"]) == 1,
      str(invites.list_hosted()))

# A non-collision failure must not burn three more codes on a retry that
# cannot possibly help.
before = len(fake.calls)
fake.queue = [FakeResponse(400, {"error": "bad_address"})]
res = invites.publish_new("1.19.4", "not-an-address", base_url=API)
check("a bad address fails without retrying", res["ok"] is False and
      len(fake.calls) - before == 1, str(res))
check("...with a human sentence, not an error code",
      res["message"] == invites._MESSAGES["bad_address"], res["message"])
check("...and no local record left behind",
      invites.get_hosted("1.19.4") is None)

# --- the ordering that protects the secret ----------------------------------
# If the process dies between claiming a code and writing its secret down, the
# host owns a code they can never repoint. So the write must come first.
reset_store()
observed = {}


def dying_put(url, **kw):
    observed["hosted_at_request_time"] = invites.list_hosted()
    raise real_requests.ConnectionError("network died mid-claim")


fake.queue = []
fake.put = dying_put
res = invites.publish_new("1.21.11", "a.example.com:25565", base_url=API)
check("a dead network is reported, not raised", res["ok"] is False)
check("...as an offline message the user can act on",
      res["error"] == "offline" and "internet" in res["message"].lower())
check("the secret was on disk BEFORE the claim left the machine",
      len(observed["hosted_at_request_time"]) == 1,
      str(observed["hosted_at_request_time"]))
check("an unclaimed code is not left cluttering the store",
      invites.list_hosted() == [])
fake.put = types.MethodType(FakeRequests.put, fake)

# --- resolve: the joining friend's path -------------------------------------
print("\n8. resolve (the friend's side)")
reset_store()

fake.queue = [FakeResponse(200, {
    "code": "CUBE-7F4K-9QMN", "address": "bluefox-1234.gl.joinmc.link:52341",
    "version": "1.21.11", "loader": "fabric", "age": 42, "expires_in": 86000})]
res = invites.resolve("cube 7f4k 9qmn", base_url=API)
check("resolve accepts a sloppily typed code", res["ok"] is True, str(res))
check("...returns the address to connect to",
      res["address"] == "bluefox-1234.gl.joinmc.link:52341")
check("...and the version/loader so the join can be set up",
      res["version"] == "1.21.11" and res["loader"] == "fabric")
check("...and records it in joined history",
      invites.list_joined()[0]["code"] == "CUBE-7F4K-9QMN")
check("GETs the canonical code, not what was typed",
      fake.calls[-1]["url"] == f"{API}/i/CUBE-7F4K-9QMN", fake.calls[-1]["url"])
check("resolve sends no Authorization (joining needs no secret)",
      "headers" not in fake.calls[-1] or
      "Authorization" not in (fake.calls[-1].get("headers") or {}))

fake.queue = [FakeResponse(404)]
res = invites.resolve("CUBE-3333-4444", base_url=API)
check("an unknown code is a clean failure", res["ok"] is False and res["error"] == "unknown")
check("...whose message names all three real causes",
      all(word in res["message"].lower() for word in ("typo", "host", "expire")),
      res["message"])

before = len(fake.calls)
res = invites.resolve("garbage", base_url=API)
check("a malformed code is caught before any request",
      res["error"] == "bad_code" and len(fake.calls) == before)
check("...and the message shows the expected shape",
      "CUBE-" in res["message"], res["message"])

fake.queue = [FakeResponse(200, {"address": "no-colon-here"})]
check("a nonsense address from the server is rejected, not connected to",
      invites.resolve("CUBE-7F4K-9QMN", base_url=API)["ok"] is False)

fake.queue = [FakeResponse(200, raw="<html>captive portal</html>")]
check("a non-JSON response (captive portal) is handled",
      invites.resolve("CUBE-7F4K-9QMN", base_url=API)["ok"] is False)

fake.queue = [real_requests.Timeout("slow")]
res = invites.resolve("CUBE-7F4K-9QMN", base_url=API)
check("a timeout is reported as offline", res["error"] == "offline")

# --- unpublish --------------------------------------------------------------
print("\n9. unpublish")
fake.queue = [FakeResponse(204)]
res = invites.unpublish("CUBE-7F4K-9QMN", "s" * 43, base_url=API)
check("unpublish succeeds on 204", res["ok"] is True)
check("...via DELETE with the bearer secret",
      fake.calls[-1]["method"] == "DELETE" and
      fake.calls[-1]["headers"]["Authorization"] == "Bearer " + "s" * 43)

fake.queue = [FakeResponse(404)]
check("unpublishing an already-expired code is success, not an error",
      invites.unpublish("CUBE-7F4K-9QMN", "s" * 43, base_url=API)["ok"] is True)

fake.queue = [FakeResponse(403, {"error": "not_yours"})]
res = invites.unpublish("CUBE-7F4K-9QMN", "s" * 43, base_url=API)
check("someone else's code can't be unpublished",
      res["ok"] is False and res["error"] == "not_yours")
check("...with a message that explains rather than blames",
      res["message"] == invites._MESSAGES["not_yours"])

# --- API root resolution ----------------------------------------------------
print("\n10. API root")
check("defaults to the deployed Worker",
      invites._api_root() == invites.DEFAULT_API_ROOT)
os.environ["CUBEON_INVITE_API"] = "http://127.0.0.1:8787/"
check("CUBEON_INVITE_API overrides it (for wrangler dev)",
      invites._api_root() == "http://127.0.0.1:8787")
check("an explicit base_url wins over the env var",
      invites._api_root("https://other.invalid") == "https://other.invalid")
del os.environ["CUBEON_INVITE_API"]
check("trailing slashes never produce a double slash",
      invites._api_root("https://x.invalid/") == "https://x.invalid")
check("the default root is https (a code is an address people trust)",
      invites.DEFAULT_API_ROOT.startswith("https://"))

# Every mapped error must have a real sentence, since these go straight on screen.
print("\n11. every error message is user-ready")
for key, msg in invites._MESSAGES.items():
    check(f"{key} reads as a sentence",
          msg[0].isupper() and msg.rstrip().endswith(".") and len(msg) < 140,
          msg)
check("an unmapped error still gets a message",
      invites._fail("http_500")["message"] == invites._OFFLINE)

invites.requests = real_requests
shutil.rmtree(_scratch, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
