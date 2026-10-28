"""The local-API token file is 0600 before the token is written (10.6).

`_write_token` used `open(tmp, "w")` (default 0666 & umask, typically 0644),
replaced the target and only then chmod'ed it to 0600. For that window another
local user could read the bearer token - it authorises invites, chat and friend
actions.

Locked-in behaviour:
  * the temp file is already 0600 when `os.replace` consumes it;
  * the final `local_api.json` is 0600, valid JSON with port + token;
  * the temp name is unique (a leftover/racing temp is not reused) and no temp
    is left behind;
  * a failure before replace leaves no token file and no temp.

Run: python tools/test_local_api_token_mode.py
"""
import json
import os
import stat
import sys
import tempfile
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import local_api  # noqa: E402

passed = failed = 0

TOKEN = "a-bearer-secret"


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def leftovers(folder):
    return sorted(name for name in os.listdir(folder)
                  if name.startswith(".local-api-"))


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-token-mode-")
    token_file = os.path.join(scratch, "local_api.json")
    local_api._TOKEN_FILE = token_file

    # --- 1. the temp is private before the rename -------------------------
    seen = []
    real_replace = local_api.os.replace

    def spy_replace(src, dst):
        seen.append(mode_of(src))
        return real_replace(src, dst)

    with patch.object(local_api.os, "replace", spy_replace):
        local_api._write_token(1234, TOKEN)

    check("the temp file is already 0600 when it is renamed",
          seen == [0o600],
          f"modes at os.replace: {[oct(m) for m in seen]}")
    check("the token file exists", os.path.isfile(token_file))
    check("the token file is 0600", mode_of(token_file) == 0o600,
          oct(mode_of(token_file)))
    with open(token_file, encoding="utf-8") as fh:
        check("the token file is valid JSON with port + token",
              json.load(fh) == {"port": 1234, "token": TOKEN})
    check("no temp file is left behind", not leftovers(scratch),
          str(leftovers(scratch)))

    # --- 2. a wide-permission old file is replaced, not reused ------------
    os.chmod(token_file, 0o644)
    local_api._write_token(4321, TOKEN + "-2")
    check("an old 0644 token file is replaced with 0600",
          mode_of(token_file) == 0o600, oct(mode_of(token_file)))
    with open(token_file, encoding="utf-8") as fh:
        check("the replaced token file carries the new port",
              json.load(fh)["port"] == 4321)
    check("still no temp file", not leftovers(scratch), str(leftovers(scratch)))

    # --- 3. a failed write leaves nothing behind --------------------------
    os.unlink(token_file)

    def boom(*a, **k):
        raise OSError("disk full")

    with patch.object(local_api.json, "dump", side_effect=boom):
        ex = None
        try:
            local_api._write_token(9999, TOKEN)
        except Exception as e:  # noqa: BLE001 - the assertion is the point
            ex = e
    check("a failed write raises", isinstance(ex, OSError), repr(ex))
    check("a failed write leaves no token file", not os.path.exists(token_file))
    check("a failed write cleans up its temp", not leftovers(scratch),
          str(leftovers(scratch)))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
