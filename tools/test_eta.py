"""
Offline suite for the launcher's two download-courtesy features:

  1. cubeon/eta.py - the measured "~2m 10s left" appended to download labels.
     There is no way to know how much is left of a download (mll reports file
     COUNTS per phase, mod installs report file units, content downloads report
     bytes - none of them carry a size), so the only honest estimate is
     measured from how fast the fraction has actually been moving.

  2. cubeon/versions.py _FriendlyStatus - the translation that keeps a raw
     asset sha1 out of the status line. mll names the file it is fetching by
     its basename; for the asset phase that basename is the object's 40-hex
     sha1, so the launcher showed "Download c4dbabc820f04ba685694c63359429b2
     2e3a62b5" - a wall of hex that reads like a memory address and tells the
     user nothing.

  3. cubeon/status_text.py human() - the same report from the other direction:
     str(requests.ConnectionError) contains the repr of a urllib3 object
     ("<urllib3.connection.HTTPSConnection object at 0x7f3c8a1b2d90>: Failed to
     establish a new connection..."), so a dropped connection painted an actual
     memory address into the UI. The words are kept, the reprs are not.

The contract pinned here: an ETA is SILENT until there is real movement, it
follows a steady rate, a backwards jump (a new phase) drops the history rather
than averaging two phases together, a stalled download stops promising a time,
and a finished one promises nothing at all. The clock is injected, so none of
this sleeps.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

from cubeon import eta  # noqa: E402
from cubeon.versions import _FriendlyStatus  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


class Clock:
    """A monotonic clock the test drives by hand."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def tick(self, dt):
        self.t += dt


# ---------------------------------------------------------------------------
print("\n1. format_duration says it short")
# ---------------------------------------------------------------------------
check("under five seconds is not a number worth reading",
      eta.format_duration(1.2) == "a few seconds", eta.format_duration(1.2))
check("seconds", eta.format_duration(45) == "45s", eta.format_duration(45))
check("a minute and change", eta.format_duration(70) == "1m 10s",
      eta.format_duration(70))
check("a whole minute drops the :00", eta.format_duration(120) == "2m",
      eta.format_duration(120))
check("hours", eta.format_duration(3900) == "1h 05m", eta.format_duration(3900))

# ---------------------------------------------------------------------------
print("\n2. the estimator is silent until it has something to say")
# ---------------------------------------------------------------------------
clock = Clock()
est = eta.EtaEstimator(now=clock)

check("the first sample alone is not an estimate",
      est.note(0, 100) is None)
clock.tick(1.0)
est.note(1, 100)
check("under two seconds of movement is still not an estimate",
      est.text() is None, est.text())
check("an unknown total has no estimate",
      eta.EtaEstimator(now=clock).note(0, 0) is None)
check("junk values don't raise",
      eta.EtaEstimator(now=clock).note(None, None) is None)

# ---------------------------------------------------------------------------
print("\n3. a steady rate becomes a time left")
# ---------------------------------------------------------------------------
clock.tick(1.5)
est.note(3, 100)          # 0% -> 3% over 2.5s
# 0.03 / 2.5s = 0.012/s, so the remaining 97% is ~80.8s.
check("the estimate matches the rate actually observed",
      est.text() == "~1m 21s left", est.text())
check("note() returns the same estimate it stores",
      est.note(3, 100) == "~1m 21s left", est.note(3, 100))

# ---------------------------------------------------------------------------
print("\n4. a new phase drops the history instead of averaging two rates")
# ---------------------------------------------------------------------------
clock.tick(1.0)
check("a backwards jump produces no estimate yet",
      est.note(0, 50) is None, est.note(0, 50))
clock.tick(5.0)
est.note(25, 50)          # the new phase: 0% -> 50% over 5s
# 0.5 / 5s = 0.1/s, so the remaining 50% is ~5s.
check("the new phase is measured on its own, not against the old one",
      est.text() == "~5s left", est.text())

# ---------------------------------------------------------------------------
print("\n5. a stall stops promising a time")
# ---------------------------------------------------------------------------
clock.tick(20.0)          # no samples for 20s
check("a stalled download shows no estimate",
      est.text() is None, est.text())

# ---------------------------------------------------------------------------
print("\n6. a finished download promises nothing")
# ---------------------------------------------------------------------------
clock.tick(1.0)
est.note(50, 50)
check("100% has no time left to report", est.text() is None, est.text())
check("reset() forgets everything", est.reset() is None and est.text() is None)

# ---------------------------------------------------------------------------
print("\n7. an asset sha1 never reaches the status line as a file name")
# ---------------------------------------------------------------------------
SHA1 = "c4dbabc820f04ba685694c63359429b22e3a62b5"

friendly = _FriendlyStatus()
check("a normal library name is left alone",
      friendly.status("Download authlib-6.0.54.jar")
      == "Download authlib-6.0.54.jar")
check("phase names are untouched",
      friendly.status("Download Assets") == "Download Assets")
check("non-download text is untouched",
      friendly.status("Running installer") == "Running installer")

friendly.maximum(2586)
friendly.progress(412)
check("an asset's sha1 is replaced by the phase and a count",
      friendly.status("Download " + SHA1)
      == "Downloading game assets (412/2586)",
      friendly.status("Download " + SHA1))


def _counted(status, current, maximum):
    status.maximum(maximum)
    status.progress(current)
    return status.status("Download " + SHA1)


check("a count can never exceed the phase's max",
      _counted(_FriendlyStatus(), 9000, 2586) == "Downloading game assets (2586/2586)",
      _counted(_FriendlyStatus(), 9000, 2586))
check("without a max it still says what it is doing",
      _FriendlyStatus().status("Download " + SHA1)
      == "Downloading game assets",
      _FriendlyStatus().status("Download " + SHA1))
check("a 40-character name that isn't hex is a real file",
      friendly.status("Download " + "z" * 40) == "Download " + "z" * 40,
      friendly.status("Download " + "z" * 40))
check("an asset index file keeps its name",
      friendly.status("Download 1.21.4.json") == "Download 1.21.4.json",
      friendly.status("Download 1.21.4.json"))

# ---------------------------------------------------------------------------
print("\n8. a Python object repr never reaches the user")
# ---------------------------------------------------------------------------
# The other half of the same report: a failed connection paints the repr of a
# urllib3 object - memory address and all - into the download button, because
# that is genuinely what str(requests.ConnectionError) contains.
from cubeon.status_text import human  # noqa: E402

CONNECTION_ERROR = (
    "HTTPSConnectionPool(host='cdn.modrinth.com', port=443): Max retries "
    "exceeded with url: /data/sodium (Caused by NewConnectionError("
    "'<urllib3.connection.HTTPSConnection object at 0x7f3c8a1b2d90>: Failed "
    "to establish a new connection: [Errno -2] Name or service not known'))")

cleaned = human(CONNECTION_ERROR)
check("the address is gone", "0x7f3c8a1b2d90" not in cleaned, cleaned)
check("the words that tell the user what happened stay",
      "Failed to establish a new connection" in cleaned
      and "Name or service not known" in cleaned, cleaned)
check("plain text is untouched",
      human("Download authlib-6.0.54.jar") == "Download authlib-6.0.54.jar")
check("a line that was nothing but a repr still says something",
      human("<Foo object at 0x7f00>") == "Working…",
      human("<Foo object at 0x7f00>"))
check("empty stays empty", human("") == "" and human(None) == "")
check("a hash is left alone - it is diagnostic in an integrity error",
      human("checksum mismatch: abcdef0123456789") == "checksum mismatch: abcdef0123456789")


print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
