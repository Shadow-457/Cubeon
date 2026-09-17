"""
Seasonal look: figures out the season where the user actually is, so the
launcher can wear it.

WHY THIS EXISTS
---------------
Cubeon's palette is not a runtime setting: cubeon/color_templates.py patches
cubeon.theme's tokens while the `cubeon` package is being imported, and every UI
module then binds those values with `from cubeon.theme import ACCENT`. A palette
is therefore fixed for the life of the process (see the module map). That is
exactly the right shape for a season - it changes four times a year - so this
module is deliberately a *startup-time* resolver: it answers "which template
should this launch use?", and the seasonal greeting/restart prompt in the UI
exists because switching needs a relaunch.

HOW THE SEASON IS FOUND (all offline)
-------------------------------------
    timezone (the OS)  ->  country + hemisphere (cubeon/seasonal_geo.py)
                       ->  season (this module, meteorological dates)

The timezone comes from, in order: CUBEON_TZ, the TZ variable, the
/etc/localtime symlink (Linux/macOS - the reliable one), /etc/timezone, and on
Windows `tzutil /g`. Nothing here touches the network: an offline launcher must
not need geolocation to know it's October.

WHAT IT DELIBERATELY DOESN'T PRETEND TO KNOW
--------------------------------------------
* A timezone is not a person. The classic failure is a country straddling the
  equator or a tropical highland; the curated tables in seasonal_geo.py fix the
  big cases, and everything else is overridable by the user in
  Settings > Seasonal, which always outranks this module.
* Seasons are METEOROLOGICAL (Mar 1 / Jun 1 / Sep 1 / Dec 1), not astronomical.
  It's one table below, it matches how autumn actually feels, and swapping it
  for equinox dates would be a change to _NORTH/_SOUTH alone.
* The tropics don't have autumn, so tropical users get an honest wet/dry
  season (wet -> the lush spring palette, dry -> the sun palette) rather than a
  fake leaf-fall. They still get a visual change twice a year.

Used by:
  * cubeon/__init__.py     - picks the palette template at import time
  * main.py                - the badge, the pet, the greeting card, Settings
  * tools/ux_capture.py    - CUBEON_SEASON pins a season for determinism
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, replace
from datetime import date, datetime

from . import seasonal_geo as _geo

# The four palette keys (== templates/color_<key>.py and the "season" field).
SPRING, SUMMER, AUTUMN, WINTER = "spring", "summer", "autumn", "winter"
SEASONS = (SPRING, SUMMER, AUTUMN, WINTER)

# Season per month, by hemisphere. Meteorological: autumn IS September, so a
# user never sees spring orange or a leaf-fall in July.
_NORTH = {1: WINTER, 2: WINTER, 3: SPRING, 4: SPRING, 5: SPRING,
          6: SUMMER, 7: SUMMER, 8: SUMMER, 9: AUTUMN, 10: AUTUMN, 11: AUTUMN,
          12: WINTER}
_SOUTH = {1: SUMMER, 2: SUMMER, 3: AUTUMN, 4: AUTUMN, 5: AUTUMN,
          6: WINTER, 7: WINTER, 8: WINTER, 9: SPRING, 10: SPRING, 11: SPRING,
          12: SUMMER}

# Tropical wet season = the rainy months; it borrows the spring palette (lush,
# growing) and the dry months borrow summer (sun). Both are labels only - the
# palette itself is unchanged from the temperate one, so nothing has to be
# designed or contrast-checked twice.
_WET_MONTHS_NORTH = frozenset({5, 6, 7, 8, 9, 10})
THEMES = {
    SPRING: "spring", SUMMER: "summer", AUTUMN: "autumn", WINTER: "winter",
}
PRETTY = {SPRING: "Spring", SUMMER: "Summer", AUTUMN: "Autumn",
          WINTER: "Winter"}

# Zone-name prefixes that are southern no matter what the tables say. Short on
# purpose: seasonal_geo covers every real zone, this only catches a hand-set
# TZ=Australia/... or Antarctica/... in a stripped-down environment.
_SOUTH_PREFIXES = ("Australia/", "Antarctica/")

_OVERRIDE_KEYS = frozenset(SEASONS) | {"auto", "off", "none", "detected"}


@dataclass(frozen=True)
class SeasonInfo:
    """Everything the UI needs to talk about the current season honestly.

    `season` is the palette key (always one of SEASONS). `label` is what a
    human should read - for the tropics it says "Wet season", not "Autumn".
    `source` records WHY this answer was chosen so Settings can say it out
    loud instead of guessing.
    """
    season: str
    label: str
    hemisphere: str          # "north" | "south"
    climate: str             # "temperate" | "tropical"
    zone: "str | None"
    city: "str | None"
    country: "str | None"    # ISO-3166 alpha-2
    country_name: "str | None"
    source: str              # "env" | "config" | "detected" | "default"
    seasonal: bool           # seasonal themes enabled at all

    @property
    def place(self) -> str:
        """'Vienna, Austria' - the human half of the detection line. Falls
        back through city -> country -> the raw zone -> nothing."""
        if self.city and self.country_name:
            return f"{self.city}, {self.country_name}"
        return self.city or self.country_name or self.zone or "an unknown place"

    @property
    def slug(self) -> str:
        """'2026-autumn' - the once-per-season-per-year greeting key. Winter is
        the awkward one: it starts in December, so without season_year() a
        January launch would greet the user all over again."""
        return f"{season_year(date.today())}-{self.season}"


# ---------------------------------------------------------------------------
# Timezone detection
# ---------------------------------------------------------------------------

def zone_from_path(path: str) -> "str | None":
    """/usr/share/zoneinfo/Europe/Vienna -> 'Europe/Vienna'. None if the path
    isn't inside a zoneinfo tree (on some systems /etc/localtime is a COPY, not
    a symlink - then there is no name to read and we must not invent one)."""
    if not path:
        return None
    marker = "zoneinfo/"
    idx = path.find(marker)
    if idx < 0:
        return None
    name = path[idx + len(marker):].strip("/")
    # A lone 'posixrules'/'localtime' (or nothing) is not a timezone.
    if not name or "/" not in name or name in ("posixrules", "localtime"):
        return None
    return name


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _windows_zone() -> "str | None":
    """Windows has no IANA name, only `tzutil /g`'s Windows zone name."""
    try:
        out = subprocess.run(["tzutil", "/g"], capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return _geo.WIN_ZONES.get((out.stdout or "").strip())


def detect_timezone() -> "str | None":
    """The user's IANA timezone, or None when the OS won't say.

    CUBEON_TZ is checked first so screenshots/tests can pin a place without
    changing the machine's clock settings; TZ comes next because it is what
    containers and shells set. The /etc/localtime symlink is the one that
    actually answers for a normal Linux/macOS desktop.
    """
    for name in (os.environ.get("CUBEON_TZ"), os.environ.get("TZ")):
        if name and "/" in name:
            return name.strip()

    zone = zone_from_path(os.path.realpath("/etc/localtime"))
    if zone:
        return zone
    # /etc/timezone (Debian-style) is a plain name, not a path.
    raw = _read_text("/etc/timezone")
    if "/" in raw and " " not in raw:
        return raw
    # macOS keeps the real file here when /etc/localtime is a copy.
    zone = zone_from_path(os.path.realpath("/var/db/timezone/localtime"))
    if zone:
        return zone
    return _windows_zone()


def city_from_zone(zone: "str | None") -> "str | None":
    """'Europe/Vienna' -> 'Vienna'. The city is already in the zone string, so
    the detection line can name a real place without a lookup table."""
    if not zone or "/" not in zone:
        return None
    return zone.split("/")[-1].replace("_", " ")


# ---------------------------------------------------------------------------
# Hemisphere / climate / season
# ---------------------------------------------------------------------------

def classify_zone(zone: "str | None") -> "tuple[str, str]":
    """(hemisphere, climate) for an IANA zone.

    Tropical wins over southern/northern, because |latitude| <= 23.5 is the
    fact that decides which season model applies: the tropics get wet/dry
    instead of the four-season table. Unknown or absent zones default to
    northern + temperate - the right answer for the large majority of users,
    and override-able in Settings.
    """
    if zone:
        if zone in _geo.TROPIC_ZONES:
            hemi = "south" if zone in _geo.SOUTH_ZONES else "north"
            return hemi, "tropical"
        if zone in _geo.SOUTH_ZONES:
            return "south", "temperate"
        if zone.startswith(_SOUTH_PREFIXES):
            return "south", "temperate"
    return "north", "temperate"


def season_for(day: date, hemisphere: str = "north",
               climate: str = "temperate") -> str:
    """The palette key for a date. `day` may be a date or a datetime."""
    if climate == "tropical":
        wet = day.month in _WET_MONTHS_NORTH
        if hemisphere == "south":     # the wet season is the other half-year
            wet = not wet
        return SPRING if wet else SUMMER
    table = _SOUTH if hemisphere == "south" else _NORTH
    return table[day.month]


def label_for(season: str, climate: str = "temperate") -> str:
    if climate == "tropical":
        return "Wet season" if season == SPRING else "Dry season"
    return PRETTY.get(season, "Season")


def season_year(day: date) -> int:
    """The year the current season STARTED. Meteorological winter runs Dec-Feb,
    so a January date belongs to the previous year's winter."""
    return day.year - 1 if day.month in (1, 2) else day.year


# ---------------------------------------------------------------------------
# Resolution: env -> config -> detection -> default
# ---------------------------------------------------------------------------

ENV_VAR = "CUBEON_SEASON"
_OFF_WORDS = frozenset({"off", "0", "false", "no", "none", "disable", "disabled"})


def _env_choice() -> "tuple[str | None, bool]":
    """(override, seasonal_enabled) from CUBEON_SEASON.

    (None, True) means "the env var had nothing useful to say". This exists so
    a launch can be pinned (CUBEON_SEASON=autumn for screenshots/tests) or
    switched off (CUBEON_SEASON=off) without touching config.json.
    """
    raw = (os.environ.get(ENV_VAR) or "").strip().lower()
    if not raw:
        return None, True
    if raw in _OFF_WORDS:
        return None, False
    if raw in _OVERRIDE_KEYS:      # 'auto' / 'detected' -> ignore config override
        return ("auto" if raw in ("auto", "detected") else raw), True
    logging.getLogger(__name__).warning(
        "%s=%r is not a season (%s) - ignoring it", ENV_VAR, raw,
        ", ".join(SEASONS + ("off", "auto")))
    return None, True


def resolve(cfg: "dict | None" = None, *, today: "date | None" = None,
            zone: "str | None" = None, use_env: bool = True) -> SeasonInfo:
    """Decide which season this launch is in.

    Order (first one that speaks wins):
      1. CUBEON_SEASON                       - pin/disable, for tests + screenshots
      2. cfg["seasonal_theme"] is off        - the user turned it off
      3. cfg["season_override"] is a season  - the user corrected the guess
      4. the detected timezone               - the normal path
      5. today's date, northern temperate    - no OS answer at all

    `today`/`zone`/`use_env` exist for tests: never read them from the UI.
    """
    day = today or date.today()
    cfg = cfg or {}
    override, enabled, source = None, True, "detected"

    if use_env:
        env_override, env_enabled = _env_choice()
        if not env_enabled:
            enabled, override, source = False, None, "env"
        elif env_override == "auto":
            override, source = None, "env"      # pinned to auto, ignore config
        elif env_override:
            override, source = env_override, "env"

    if enabled and source == "detected":
        if cfg.get("seasonal_theme") is False:
            enabled, source = False, "config"
        else:
            cfg_override = str(cfg.get("season_override") or "auto").lower()
            if cfg_override in SEASONS:
                override, source = cfg_override, "config"

    if zone is None:
        zone = detect_timezone()
    hemisphere, climate = classify_zone(zone)

    season = (override if override in SEASONS
              else season_for(day, hemisphere, climate))
    # A forced season is a season, not a wet/dry label: a user who picks
    # "Autumn" means autumn, whatever the tropics table would have said.
    label = (PRETTY[season] if override in SEASONS
             else label_for(season, climate))
    if zone is None and source == "detected":
        source = "default"

    country = _geo.ZONE_COUNTRY.get(zone) if zone else None
    return SeasonInfo(
        season=season,
        label=label,
        hemisphere=hemisphere,
        climate=climate,
        zone=zone,
        city=city_from_zone(zone),
        country=country,
        country_name=_geo.COUNTRY_NAME.get(country) if country else None,
        source=source,
        seasonal=enabled,
    )


# The answer the *palette* was chosen from: set once at import (see boot()),
# then kept up to date when the user changes the setting, so the badge and the
# Settings pane always describe the season the running window is wearing.
_current: "SeasonInfo | None" = None

# An explicit --color on the command line outranks the season entirely. It is
# recorded here (by cubeon/__init__'s hook) so the UI can say "pinned" instead
# of claiming the season chose the palette the window is actually wearing.
_pinned: "str | None" = None


def note_palette_pinned(name: str) -> None:
    """Records that this launch's palette was pinned with --color."""
    global _pinned
    _pinned = str(name or "").strip().lower() or None
    if _current is not None:
        set_current(_apply_pin(_current))


def pinned_template() -> "str | None":
    """The --color value this launch was pinned to, or None."""
    return _pinned


def env_pin() -> "str | None":
    """The season the CUBEON_SEASON environment variable pins, if any.

    Public on purpose: the Settings handler needs to notice when a user's
    pick is being outranked by the env (the env wins by design - it is the
    test/screenshot contract - but a silently-ignored dropdown is a bug the
    user will report as "it just goes back to autumn").
    """
    override, _enabled = _env_choice()
    return override if override in SEASONS else None


def _apply_pin(info: SeasonInfo) -> SeasonInfo:
    """Marks a resolved season as 'the palette was pinned instead'."""
    if not _pinned:
        return info
    return replace(info, seasonal=False, source="pinned")


def set_current(info: SeasonInfo) -> SeasonInfo:
    global _current
    _current = _apply_pin(info)
    return _current


def current(cfg: "dict | None" = None) -> SeasonInfo:
    """The cached SeasonInfo, resolving on first use (a tool that imports
    cubeon.theme directly never ran boot())."""
    if _current is None:
        return set_current(resolve(cfg))
    return _current


def refresh(cfg: "dict | None" = None) -> SeasonInfo:
    """Re-resolve and re-cache - called after the user edits the setting so the
    UI reflects the new choice immediately (the palette itself still needs a
    relaunch; the greeting card in main.py is what explains that)."""
    return set_current(resolve(cfg))


def theme_key_for(info: "SeasonInfo | None" = None) -> "str | None":
    """The templates/color_<key>.py key for this season, or None when the
    seasonal look is off (the caller then keeps its normal default template)."""
    if info is None:
        info = current()
    return info.season if info.seasonal else None


def describe_source(info: SeasonInfo) -> str:
    """One honest line for Settings about WHY this season was picked."""
    if info.source == "pinned":
        return (f"You launched with --color {_pinned} - the seasonal look is "
                "paused until Cubeon starts without it.")
    if not info.seasonal:
        return "Off - the launcher keeps its normal colors."
    if info.source == "env":
        return f"Pinned by {ENV_VAR}."
    if info.source == "config":
        return f"You picked {PRETTY[info.season]} yourself."
    if info.zone:
        if info.climate == "tropical":
            tail = " Wet and dry seasons here, so you get a wet/dry look."
        elif info.hemisphere == "south":
            tail = " Southern hemisphere - the seasons are the other way round."
        else:
            tail = ""
        return f"Detected from {info.zone}.{tail}"
    return ("Couldn't read your timezone, so this is the northern-hemisphere "
            "guess (change it below).")


def boot() -> "tuple[str | None, SeasonInfo]":
    """Resolve the season at import time and cache it for the UI.

    Called from cubeon/__init__.py's palette hook - i.e. before main.py binds
    any design token. Reads config.json directly (the launcher's own settings,
    available before main() runs) and never raises: a broken or absent config
    just means "detect it", because a seasonal palette must never be the reason
    a launcher fails to start.
    """
    cfg = {}
    try:
        from .config import load_config
        cfg = load_config() or {}
    except Exception:      # noqa: BLE001 - startup must not die here
        logging.getLogger(__name__).debug("seasonal: no config yet", exc_info=True)
    info = set_current(resolve(cfg))
    return theme_key_for(info), info
