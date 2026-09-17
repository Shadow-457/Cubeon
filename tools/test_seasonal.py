#!/usr/bin/env python3
"""
Tests for the seasonal layer: cubeon/seasonal.py + the four seasonal
templates. Run with:

    python tools/test_seasonal.py

No network, no display, no config.json needed - every resolution passes
explicit today/zone/use_env values, which is exactly the handle
cubeon/seasonal.resolve() exposes for tests.

Covers:
  * the meteorological tables (season boundaries, southern flip, tropics)
  * timezone classification and the zone -> country/city tables
  * the resolution precedence matrix (env pin/off > config off/override
    > detection > northern default)
  * the seasonal palettes: complete token sets + WCAG AA contrast
  * the template registry (aliases 8-11, apply_template)
  * the pet wander state machine (ui/seasonal_ui.py, headless with a fake
    thread_safe_ui.refresh): lane bounds, wall turns, facing, rest/walk mix
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import seasonal  # noqa: E402
from cubeon import seasonal_geo as geo  # noqa: E402

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


# ------------------------------------------------------------ season tables ---
N = "north"
S = "south"

check("Aug 31 is still northern summer",
      seasonal.season_for(date(2026, 8, 31)) == seasonal.SUMMER)
check("Sep 1 is the first northern autumn day",
      seasonal.season_for(date(2026, 9, 1)) == seasonal.AUTUMN)
check("Dec 1 starts northern winter",
      seasonal.season_for(date(2026, 12, 1)) == seasonal.WINTER)
check("Mar 1 starts northern spring",
      seasonal.season_for(date(2026, 3, 1)) == seasonal.SPRING)
check("Jun 1 starts northern summer",
      seasonal.season_for(date(2026, 6, 1)) == seasonal.SUMMER)
check("mid-month dates match their month (Sep 15 -> autumn)",
      seasonal.season_for(date(2026, 9, 15)) == seasonal.AUTUMN)

check("southern Sep 1 is spring",
      seasonal.season_for(date(2026, 9, 1), S) == seasonal.SPRING)
check("southern Dec 1 is summer",
      seasonal.season_for(date(2026, 12, 1), S) == seasonal.SUMMER)
check("southern Jan 15 is summer",
      seasonal.season_for(date(2026, 1, 15), S) == seasonal.SUMMER)
check("southern Jun 1 is winter",
      seasonal.season_for(date(2026, 6, 1), S) == seasonal.WINTER)

check("northern tropics May 15 -> wet season (spring palette)",
      seasonal.season_for(date(2026, 5, 15), N, "tropical") == seasonal.SPRING)
check("northern tropics Jan 15 -> dry season (summer palette)",
      seasonal.season_for(date(2026, 1, 15), N, "tropical") == seasonal.SUMMER)
check("southern tropics May 15 -> dry season (wet is the other half)",
      seasonal.season_for(date(2026, 5, 15), S, "tropical") == seasonal.SUMMER)
check("tropical labels say Wet/Dry, not season names",
      seasonal.label_for(seasonal.SPRING, "tropical") == "Wet season"
      and seasonal.label_for(seasonal.SUMMER, "tropical") == "Dry season")
check("temperate labels are the season names",
      seasonal.label_for(seasonal.AUTUMN, "temperate") == "Autumn")

check("season_year: Jan/Feb winter belongs to the previous year",
      seasonal.season_year(date(2026, 1, 15)) == 2025
      and seasonal.season_year(date(2026, 2, 28)) == 2025)
check("season_year: Sep-Dec belong to their own year",
      seasonal.season_year(date(2026, 9, 1)) == 2026
      and seasonal.season_year(date(2026, 12, 31)) == 2026)

# ---------------------------------------------------------- zone geography ---
check("Europe/Vienna -> northern temperate",
      seasonal.classify_zone("Europe/Vienna") == (N, "temperate"))
check("Asia/Karachi -> northern temperate",
      seasonal.classify_zone("Asia/Karachi") == (N, "temperate"))
check("Australia/Sydney -> southern",
      seasonal.classify_zone("Australia/Sydney") == (S, "temperate"))
check("America/Sao_Paulo -> southern",
      seasonal.classify_zone("America/Sao_Paulo") == (S, "temperate"))
check("Africa/Nairobi -> tropical",
      seasonal.classify_zone("Africa/Nairobi")[1] == "tropical")
check("Asia/Singapore -> tropical",
      seasonal.classify_zone("Asia/Singapore")[1] == "tropical")
check("America/Lima -> tropical (coastal Peru)",
      seasonal.classify_zone("America/Lima")[1] == "tropical")
check("None zone -> the northern temperate default",
      seasonal.classify_zone(None) == (N, "temperate"))
check("Australia/ prefix catches zones missing from the table",
      seasonal.classify_zone("Australia/Unlisted_Zone") == (S, "temperate"))
check("completely unknown zone -> northern temperate default",
      seasonal.classify_zone("Mars/Olympus") == (N, "temperate"))

check("zone tables agree: every zone is single-country",
      all(v and len(v) == 2 for v in geo.ZONE_COUNTRY.values()))
check("COUNTRY_NAME covers every mapped country",
      all(cc in geo.COUNTRY_NAME for cc in set(geo.ZONE_COUNTRY.values())))
check("city table covers Vienna and Sydney",
      seasonal.city_from_zone("Europe/Vienna") is not None
      and seasonal.city_from_zone("Australia/Sydney") is not None)

check("zone_from_path parses a symlink target",
      seasonal.zone_from_path(
          "/usr/share/zoneinfo/Europe/Vienna") == "Europe/Vienna")
check("zone_from_path rejects non-zoneinfo paths",
      seasonal.zone_from_path("/etc/localtime") is None
      and seasonal.zone_from_path("") is None)
check("zone_from_path rejects a copy without a name",
      seasonal.zone_from_path("/usr/share/zoneinfo/localtime") is None)

# ------------------------------------------------------- resolution matrix ---
def _default_probe():
    """resolve() with the OS unable to answer (detect_timezone patched to
    return None) must fall back to the northern-temperate guess."""
    orig = seasonal.detect_timezone
    seasonal.detect_timezone = lambda: None
    try:
        info = seasonal.resolve(use_env=False, today=date(2026, 9, 15))
        return info.source == "default" and info.season == seasonal.AUTUMN
    finally:
        seasonal.detect_timezone = orig


def res(**kw):
    """resolve() with explicit knobs - never touches the real OS state."""
    use_env = kw.pop("use_env", True)
    return seasonal.resolve(cfg=kw.pop("cfg", None), use_env=use_env, **kw)


base = dict(today=date(2026, 9, 15), zone="Europe/Vienna")
info = res(**base)
check("normal path: Vienna mid-September -> autumn, detected",
      info.season == seasonal.AUTUMN and info.source == "detected"
      and info.seasonal and info.zone == "Europe/Vienna")
check("detection carries country + city",
      info.country == "AT" and info.country_name == "Austria"
      and info.city == "Vienna")
check("slug is the once-per-year greeting key",
      info.slug == "2026-autumn")

check("southern detection: Sydney Sep 15 -> spring",
      res(today=date(2026, 9, 15),
          zone="Australia/Sydney").season == seasonal.SPRING)
info = res(today=date(2026, 9, 15), zone="Asia/Singapore")
check("tropical detection: Singapore Sep 15 -> wet season label",
      info.season == seasonal.SPRING and info.label == "Wet season"
      and info.climate == "tropical")

check("no zone at all -> the northern default guess", _default_probe())
check("unknown zone -> northern default too",
      res(today=date(2026, 9, 15), zone="Not/A_Zone").hemisphere == N)

check("config: seasonal_theme off wins before detection",
      not res(cfg={"seasonal_theme": False}, **base).seasonal)
off = res(cfg={"seasonal_theme": False}, **base)
check("config-off keeps the detected season but marks it off",
      off.season == seasonal.AUTUMN and off.source == "config")

check("config: season_override pins a season",
      res(cfg={"season_override": "winter"}, **base).season == seasonal.WINTER)
pin = res(cfg={"season_override": "winter"}, **base)
check("override source is 'config' and label is the season name",
      pin.source == "config" and pin.label == "Winter")
check("config override=auto is just the normal detection",
      res(cfg={"season_override": "auto"}, **base).source == "detected")
check("config override garbage is ignored",
      res(cfg={"season_override": "carrots"}, **base).source == "detected")

os.environ["CUBEON_SEASON"] = "autumn"
try:
    check("env pin outranks the detection AND the config override",
          res(cfg={"season_override": "winter"}, **base).source == "env")
    check("env pin: season is the pinned one, still seasonal",
          res(**base).season == seasonal.AUTUMN and res(**base).seasonal)
    os.environ["CUBEON_SEASON"] = "off"
    check("env off disables the seasonal look",
          not res(cfg={"season_override": "winter"}, **base).seasonal)
    os.environ["CUBEON_SEASON"] = "auto"
    auto = res(cfg={"season_override": "winter"}, **base)
    check("env auto ignores a config override (screenshots must be stable)",
          auto.source == "env" and auto.season == seasonal.AUTUMN,
          f"source={auto.source} season={auto.season}")
    os.environ["CUBEON_SEASON"] = "carrots"
    check("a garbage env value is ignored, not fatal",
          res(**base).source == "detected")
finally:
    os.environ.pop("CUBEON_SEASON", None)

check("use_env=False ignores the env var entirely (the UI's refresh path)",
      res(use_env=False, cfg={"season_override": "winter"},
          **base).source == "config")


# ------------------------------------------------------- palette integrity ---
from cubeon import color_templates as ct  # noqa: E402


def _rel_lum(hexc):
    """WCAG relative luminance of #RRGGBB."""
    n = int(str(hexc).lstrip("#"), 16)
    ch = [(n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF]
    lin = []
    for v in ch:
        v /= 255.0
        lin.append(v / 12.92 if v <= 0.04045 else
                   ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    la, lb = _rel_lum(a), _rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


for key in seasonal.SEASONS:
    mod = __import__(f"templates.color_{key}", fromlist=["PALETTE"])
    pal = mod.PALETTE
    missing = [k for k in ct.REQUIRED_KEYS if k not in pal]
    check(f"{key}: declares every required token", not missing,
          f"missing: {', '.join(missing)}")
    check(f"{key}: accent reads on its ON_ACCENT (AA, 4.5:1)",
          _ratio(pal["ACCENT"], pal["ON_ACCENT"]) >= 4.5,
          f"ratio {_ratio(pal['ACCENT'], pal['ON_ACCENT']):.2f}")
    check(f"{key}: body text reads on the background (AA, 4.5:1)",
          _ratio(pal["TEXT"], pal["BG"]) >= 4.5,
          f"ratio {_ratio(pal['TEXT'], pal['BG']):.2f}")
    check(f"{key}: dim text reads on the raised surface (AA, 4.5:1)",
          _ratio(pal["TEXT_DIM"], pal["SURFACE_HI"]) >= 4.5,
          f"ratio {_ratio(pal['TEXT_DIM'], pal['SURFACE_HI']):.2f}")
    check(f"{key}: accent is visible on the background (3:1 UI component)",
          _ratio(pal["ACCENT"], pal["BG"]) >= 3.0,
          f"ratio {_ratio(pal['ACCENT'], pal['BG']):.2f}")
    check(f"{key}: has a DESCRIPTION for --color list",
          bool(getattr(mod, "DESCRIPTION", "")))

# ------------------------------------------------------------- the registry ---
for i, key in enumerate(("autumn", "spring", "winter", "summer"), start=8):
    check(f"alias --color{i} -> {key}", ct.resolve(str(i)) == key)
    check(f"--color {key} resolves by name", ct.resolve(key) == key)
try:
    ct.resolve("carrots")
    check("unknown template name raises", False)
except ValueError:
    check("unknown template name raises", True)

check("apply_template('autumn') returns the key",
      ct.apply_template("autumn") == "autumn")
import cubeon.theme as theme  # noqa: E402
check("apply_template patched the live theme accent",
      theme.ACCENT == __import__("templates.color_autumn",
                                 fromlist=["PALETTE"]).PALETTE["ACCENT"])
check("apply_template derived the translucent tokens",
      bool(getattr(theme, "ACCENT_TINT", None))
      and bool(getattr(theme, "CARD_FILL", None)))
ct.apply_template("green")   # restore the default for anything after us

# -------------------------------------------------------------------- pins ----
# Note: importing the cubeon package runs seasonal.boot() (its palette hook),
# so _current is already cached by now - refresh() re-resolves with the pin.
seasonal._pinned = "autumn"
info = seasonal.refresh({"season_override": "autumn"})
check("a --color pin marks the resolution non-seasonal 'pinned'",
      info.source == "pinned" and not info.seasonal)
check("theme_key_for is None when the seasonal look is off",
      seasonal.theme_key_for(info) is None)
seasonal._pinned = None
check("theme_key_for returns the palette key when seasonal",
      seasonal.theme_key_for(res(**base)) == "autumn")

# ------------------------------------------------------------ pet wander ------
# The wanderer runs headless: thread_safe_ui.refresh is swapped for a counter
# (the real one is exception-guarded, but counting lets us assert the budget),
# and the "control" is a plain object with the attributes the machine touches.
from ui import seasonal_ui as sui  # noqa: E402

_refresh_count = [0]


def _fake_refresh(ctrl):
    _refresh_count[0] += 1


class _FakeCtrl:
    def __init__(self):
        self.left = 0
        self.top = 0
        self.scale = None


sui.thread_safe_ui.refresh = _fake_refresh

_span = sui.PERCH_W - sui.PERCH_CELL


def _fresh_pet():
    return {"ctrl": _FakeCtrl(), "x": sui.PERCH_W // 2.0,
            "dir": sui.DIR_RIGHT, "state": "rest", "wait": 0, "air": 0,
            "rest_left": 20, "rest_right": 46}


_tracked = _fresh_pet()
anim = sui.SeasonalAnimator()
anim.add_pet(_tracked)
_lo, _hi = _tracked["x"], _tracked["x"]
_left_moves = _right_moves = _moves = _rests = 0
_prev = _tracked["x"]
for _ in range(2000):
    with anim._lock:
        anim._wander(_tracked)
    _lo, _hi = min(_lo, _tracked["x"]), max(_hi, _tracked["x"])
    if _tracked["x"] != _prev:
        _moves += 1
        if _tracked["x"] > _prev:
            _right_moves += 1
        else:
            _left_moves += 1
    else:
        _rests += 1
    _prev = _tracked["x"]
check("the pet uses BOTH ends of the lane (goes all the way across)",
      _lo <= 2 and _hi >= _span - 2, f"lo={_lo} hi={_hi} span={_span}")
check("the pet turns around in both directions over a session",
      _left_moves > 100 and _right_moves > 100,
      f"L={_left_moves} R={_right_moves}")
check("the pet pauses too (walk/rest mix, no metronome)",
      0.2 < _rests / (_rests + _moves) < 0.8,
      f"rest share={_rests / (_rests + _moves):.2f}")
check("the sprite faces the way it walks (scale_x mirror)",
      _tracked["ctrl"].scale is not None
      and _tracked["ctrl"].scale.scale_x == (-1 if _tracked["dir"] < 0 else 1))
check("rests cost no repaints (diff budget: moves repaint, rests don't)",
      _refresh_count[0] <= _moves * 2 + 50,
      f"refreshes={_refresh_count[0]} moves={_moves}")
check("idle-hop lift stays inside the lane's air space",
      _tracked["ctrl"].top in (0, -sui.HOP_LIFT_PX),
      f"top={_tracked['ctrl'].top}")

# Legacy registration (bare control) still hops in place without raising.
class _OldCtrl:
    def __init__(self):
        self.offset = None


_old = _OldCtrl()
_anim2 = sui.SeasonalAnimator()
_anim2.add_pet(_old)
try:
    for _ in range(120):
        # NOTE: _frame() takes the animator's own (non-reentrant) lock inside,
        # so it must be called WITHOUT holding anim._lock.
        anim._frame()
    check("legacy bare-control pets still hop without raising", True)
except Exception as _ex:  # pragma: no cover
    check("legacy bare-control pets still hop without raising", False, str(_ex))

# Put the real refresh machinery back for any later use of this module.
from cubeon import thread_safe_ui as _tsu  # noqa: E402
sui.thread_safe_ui.refresh = _tsu.refresh

# ---------------------------------------------------------------------
# LIVE season changes - the Settings picker re-skins the runtime half
# (badge chip, pet sprite, weather strip) without rebuilding the window.
# ---------------------------------------------------------------------
_info_a = seasonal.SeasonInfo(
    season=seasonal.AUTUMN, label=seasonal.label_for(seasonal.AUTUMN),
    hemisphere="north", climate="temperate", zone="Europe/Vienna",
    city="Vienna", country="AT", country_name="Austria",
    source="config", seasonal=True)
_info_w = seasonal.SeasonInfo(
    season=seasonal.WINTER, label=seasonal.label_for(seasonal.WINTER),
    hemisphere="north", climate="temperate", zone="Europe/Vienna",
    city="Vienna", country="AT", country_name="Austria",
    source="config", seasonal=True)

class _BadgeIcon:
    def __init__(self):
        self.name = None

class _BadgeLabel:
    def __init__(self):
        self.value = None

class _BadgeRow:
    def __init__(self):
        self.controls = [_BadgeIcon(), _BadgeLabel()]

class _Badge:
    def __init__(self):
        self.content = _BadgeRow()
        self.tooltip = None

_b = _Badge()
sui.update_badge(_b, _info_a)
_check_a = (_b.content.controls[0].name == sui.SEASON_ICONS[seasonal.AUTUMN]
            and _b.content.controls[1].value == _info_a.label)
sui.update_badge(_b, _info_w)
check("update_badge re-skins the chip (icon + label) for the new season",
      _check_a and _b.content.controls[0].name
      == sui.SEASON_ICONS[seasonal.WINTER]
      and _b.content.controls[1].value == _info_w.label)

class _PetInner:
    def __init__(self):
        self.src = None
        self.tooltip = None

class _PetCtrl:
    def __init__(self):
        self.content = _PetInner()
        self.tooltip = None

_pet = {"ctrl": _PetCtrl(), "season": seasonal.AUTUMN, "x": 40.0,
        "dir": 1, "rest": 3, "hop": 0}
sui.update_pet(_pet, _info_w)
check("update_pet swaps the sprite in place (animator keeps its registration)",
      _pet["season"] == seasonal.WINTER
      and _pet["ctrl"].content.src == sui.pet_src(_info_w)
      and "golem" in (_pet["ctrl"].tooltip or "").lower())

_bounds = (200, 56, 5, 0.6, 0.4, False)
_parts = sui.build_ambience(_info_a, width=200, height=56)[1]
_new = sui.reflow_ambience(_parts, _bounds, _info_w)
check("reflow_ambience re-seeds particles + returns winter bounds",
      _new[2] == sui.WEATHER[seasonal.WINTER][1]
      and _new[4] == sui.WEATHER[seasonal.WINTER][3]
      and all(0 <= p["y"] <= 56 for p in _parts)
      and all(p["ctrl"].width == _new[2] for p in _parts))

# The env pin outranks the config pick BY DESIGN - but the UI must be able to
# SEE that it is doing so (a silently ignored dropdown reads as "broken").
import os as _os  # noqa: E402
_os.environ["CUBEON_SEASON"] = "autumn"
check("env_pin() reports the CUBEON_SEASON season pin",
      seasonal.env_pin() == "autumn")
_pin_info = seasonal.resolve({"season_override": "winter"})
check("env pin outranks a config override (documented precedence #1)",
      _pin_info.season == "autumn" and _pin_info.source == "env")
del _os.environ["CUBEON_SEASON"]
check("no env pin -> env_pin() is None", seasonal.env_pin() is None)
_no_pin = seasonal.resolve({"season_override": "winter"})
check("without the pin, the config override wins",
      _no_pin.season == "winter" and _no_pin.source == "config")

# REGRESSION GUARD (2026-09-17): Flet 0.86's Dropdown fires on_select, NOT
# on_change. The season picker (and three other dropdowns) were wired to
# .on_change, which Flet silently ignores - the user's picks never saved and
# every headless probe "passed" only because it CALLED the dead handler.
# Guard: no dropdown may carry an .on_change assignment, and the season
# dropdown must be wired via .on_select.
import re as _re
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _py in ("main.py", "ui/settings_tab.py", "ui/modpacks_tab.py",
            "ui/server_tab.py"):
    for _i, _line in enumerate(open(_os.path.join(_ROOT, _py)), 1):
        if _re.search(r"\.on_change\s*=", _line) and _re.search(
                r"dropdown|_dd\b", _line, _re.IGNORECASE):
            check(f"{_py}:{_i} dropdown uses on_select, not on_change",
                  False, _line.strip())
_main_src = open(_os.path.join(_ROOT, "main.py")).read()
check("season_dropdown is wired via .on_select",
      "season_dropdown.on_select = _on_season_change" in _main_src)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

