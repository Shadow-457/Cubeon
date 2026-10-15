"""Keep machine text out of anything a user reads.

Status and error lines are assembled from third-party text - requests, urllib3,
minecraft_launcher_lib, Modrinth - and Python cheerfully puts the repr() of any
object that reached an f-string into that text. The result looks like a memory
address and says nothing:

    str(requests.ConnectionError) really contains
    "<urllib3.connection.HTTPSConnection object at 0x7f3c8a1b2d90>: Failed to
    establish a new connection: [Errno -2] Name or service not known"

so a dropped connection painted "0x7f3c8a1b2d90" into the download button,
which is exactly the "why is it showing memory addresses while downloading"
report. The words around it are the useful part - they tell the user whether to
retry, free up disk, or pick another file - so human() removes the reprs and
keeps everything else.

This is deliberately narrow: only object reprs (the " at 0x..." form) are
stripped. Hashes and UUIDs are left alone here, because in an integrity error
they are genuinely diagnostic; the one place a bare hash is meaningless - an
asset's sha1 as a "file name" - is handled where it is generated (see
cubeon/versions.py _FriendlyStatus).
"""
from __future__ import annotations

import re

__all__ = ["human"]

#: "<something.object at 0x7f3c8a1b2d90>" - the address is the giveaway.
_OBJECT_REPR_RE = re.compile(r"<[^<>\n]{0,160}? at 0x[0-9a-fA-F]{4,}>")


def human(text) -> str:
    """`text` with any Python object repr removed.

    Never returns an address, and never returns something empty when the input
    said something: a line that was nothing but a repr becomes "Working…"
    rather than a blank label.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    cleaned = re.sub(r"[ \t]{2,}", " ", _OBJECT_REPR_RE.sub("", text)).strip()
    if cleaned:
        return cleaned
    return "Working…" if text.strip() else ""
