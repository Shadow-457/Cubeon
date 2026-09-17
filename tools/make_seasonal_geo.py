#!/usr/bin/env python3
"""
Regenerates cubeon/seasonal_geo.py - the offline tz -> country/hemisphere data
the seasonal theme resolver reads.

WHY A GENERATOR AND NOT A RUNTIME LOOKUP
----------------------------------------
Detecting the season needs three things: which timezone the user is in, which
country that zone belongs to, and whether that place is north/south of the
equator (plus whether it's in the tropics, where "autumn" doesn't mean much).
The first comes from the OS (see cubeon/seasonal.py). The other two come from
the IANA timezone database, which ships as /usr/share/zoneinfo/zone.tab on
Linux/macOS - but NOT on Windows, and not in a packaged AppImage/PyInstaller
build either. So the table is generated HERE, at development time, and the
result is committed. The runtime never reads zone.tab and never touches the
network: a fresh install on a machine with no tzdata still knows that
Australia/Sydney is southern.

Sources (all public domain / permissively licensed):
  /usr/share/zoneinfo/zone.tab       - CC <tab> +-DDMM+-DDDMM <tab> TZ <tab> note
  /usr/share/zoneinfo/zone1970.tab   - same shape, fewer (post-1970-identical) zones
  /usr/share/iso-codes/json/iso_3166-1.json - cc -> English country name

Hemisphere comes from the zone's representative-point LATITUDE SIGN, and the
tropics from |latitude| <= 23.5. That is exact enough for a themed palette and
deliberately honest about its own imprecision: a country straddling the equator
(Indonesia, Kenya, Brazil, Ecuador) is represented by ONE point, so the curated
overrides below fix the cases where that point misrepresents the bulk of the
population. Anything still wrong is fixable by the user - the Settings >
Seasonal override outranks all of this data, and is the source of truth when
the guess is wrong.

Run from the repo root:
    python3 tools/make_seasonal_geo.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "cubeon", "seasonal_geo.py")

ZONE_TABS = ("/usr/share/zoneinfo/zone.tab", "/usr/share/zoneinfo/zone1970.tab")
ISO_3166 = "/usr/share/iso-codes/json/iso_3166-1.json"

# The tropics: beyond these latitudes a place has four real seasons.
TROPIC_LAT = 23.5

# Zones the tab files can't tell us about (a user with TZ=UTC, or an
# Etc/GMT+n zone, has no country at all). Only zones that are UNAMBIGUOUSLY
# southern are listed - everything else falls back to "northern", the right
# guess for ~87% of the world's population, and always overridable in Settings.
EXTRA_SOUTH = (
    "Antarctica/Casey", "Antarctica/Davis", "Antarctica/DumontDUrville",
    "Antarctica/Macquarie", "Antarctica/Mawson", "Antarctica/McMurdo",
    "Antarctica/Palmer", "Antarctica/Rothera", "Antarctica/Syowa",
    "Antarctica/Troll", "Antarctica/Vostok", "Atlantic/South_Georgia",
)


def _parse_tab(path):
    """zone.tab rows -> {tz: (cc, latitude_degrees)}. Missing file -> {}."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                cc, coord, tz = parts[0], parts[1], parts[2]
                if not tz or "/" not in tz:
                    continue
                # First file wins per zone (zone.tab is the fuller table).
                out.setdefault(tz, (cc.split(",")[0], _parse_lat(coord)))
    except OSError:
        pass
    return out


def _parse_lat(coord):
    """'+DDMM+-DDDMM' -> signed degrees. None when unparseable."""
    try:
        sign = 1 if coord[0] == "+" else -1
        return sign * (int(coord[1:3]) + int(coord[3:5]) / 60.0)
    except (ValueError, IndexError):
        return None


def _country_names(needed):
    """cc -> English name, from iso-codes when installed; code as fallback."""
    names = {}
    try:
        with open(ISO_3166, encoding="utf-8") as fh:
            data = json.load(fh)
        for entry in data.get("3166-1", []):
            cc = entry.get("alpha_2")
            if cc:
                names[cc] = entry.get("name")
    except (OSError, ValueError, AttributeError):
        pass
    return {cc: (names.get(cc) or cc) for cc in sorted(needed)}
# Windows zone names (tzutil /g) for the zones where getting it WRONG would
# visibly mis-theme someone - i.e. the whole southern hemisphere plus the big
# tropical populations. Northern Windows zones are intentionally absent: the
# "northern" default already covers them, so a missing entry costs nothing.
# (CLDR windowsZones mapping, trimmed to the entries that carry information.)
WIN_ZONES = {
    # --- southern hemisphere ------------------------------------------------
    "AUS Central Standard Time": "Australia/Darwin",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "E. Australia Standard Time": "Australia/Brisbane",
    "Tasmania Standard Time": "Australia/Hobart",
    "W. Australia Standard Time": "Australia/Perth",
    "New Zealand Standard Time": "Pacific/Auckland",
    "South Africa Standard Time": "Africa/Johannesburg",
    "South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "E. South America Standard Time": "America/Sao_Paulo",
    "SA Eastern Standard Time": "America/Cayenne",
    "SA Pacific Standard Time": "America/Bogota",
    "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago",
    "Paraguay Standard Time": "America/Asuncion",
    "Montevideo Standard Time": "America/Montevideo",
    "Magallanes Standard Time": "America/Punta_Arenas",
    "West Central Africa": "Africa/Luanda",
    "Namibia Standard Time": "Africa/Windhoek",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Réunion Standard Time": "Indian/Reunion",
    "Sudan Standard Time": "Africa/Khartoum",
    # --- tropics (labelled wet/dry, not spring/summer) ----------------------
    "Singapore Standard Time": "Asia/Singapore",
    "Malay Peninsula Standard Time": "Asia/Kuala_Lumpur",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Myanmar Standard Time": "Asia/Yangon",
    "India Standard Time": "Asia/Kolkata",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Nepal Standard Time": "Asia/Kathmandu",
    "Arab Standard Time": "Asia/Riyadh",
    "Arabian Standard Time": "Asia/Dubai",
    "E. Africa Standard Time": "Africa/Nairobi",
    "Central America Standard Time": "America/Guatemala",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Venezuela Standard Time": "America/Caracas",
}


def _fmt_dict(name, mapping, per_line=3):
    """A dict literal, several short entries per line - keeps the generated
    file scannable and diffable instead of 400 one-per-line rows."""
    items = [f'"{k}": "{v}"' for k, v in sorted(mapping.items())]
    lines, row = [], []
    for it in items:
        row.append(it)
        if len(row) == per_line:
            lines.append("    " + ", ".join(row) + ",")
            row = []
    if row:
        lines.append("    " + ", ".join(row) + ",")
    return f"{name} = {{\n" + "\n".join(lines) + "\n}\n"


def _fmt_set(name, values):
    items = [f'"{v}"' for v in sorted(values)]
    lines, row = [], []
    for it in items:
        row.append(it)
        if len(row) == 3:
            lines.append("    " + ", ".join(row) + ",")
            row = []
    if row:
        lines.append("    " + ", ".join(row) + ",")
    return f"{name} = frozenset({{\n" + "\n".join(lines) + "\n})\n"


def main():
    zones = {}
    used = []
    for path in ZONE_TABS:
        before = len(zones)
        for tz, val in _parse_tab(path).items():
            zones.setdefault(tz, val)
        if os.path.exists(path):
            used.append(f"{os.path.basename(path)} (+{len(zones) - before})")
    if not zones:
        raise SystemExit("no zone.tab found - install tzdata or point ZONE_TABS "
                         "at one; refusing to write an empty table")

    south = {tz for tz, (_, lat) in zones.items()
             if lat is not None and lat < 0}
    tropic = {tz for tz, (_, lat) in zones.items()
              if lat is not None and abs(lat) <= TROPIC_LAT}
    south |= set(EXTRA_SOUTH)

    # The tropics where the representative point lies outside the band but most
    # people live inside it (and the four-season model would be a lie).
    tropic |= {
        "Asia/Kolkata", "Asia/Colombo", "Asia/Dhaka", "Asia/Yangon",
        "Asia/Bangkok", "Asia/Ho_Chi_Minh", "Asia/Phnom_Penh", "Asia/Vientiane",
        "Asia/Kuala_Lumpur", "Asia/Singapore", "Asia/Manila", "Asia/Makassar",
        "Asia/Jakarta", "Asia/Pontianak", "Asia/Brunei", "Asia/Dili",
        "America/Guatemala", "America/Tegucigalpa", "America/Managua",
        "America/San_Salvador", "America/Costa_Rica", "America/Panama",
        "America/Caracas", "America/Bogota", "Africa/Kampala", "Africa/Kigali",
        "Africa/Bujumbura", "Africa/Dar_es_Salaam", "Africa/Nairobi",
        "Africa/Kinshasa", "Africa/Brazzaville", "Africa/Libreville",
        "Africa/Douala", "Africa/Lagos", "Africa/Accra", "Africa/Abidjan",
        "Africa/Dakar", "Africa/Bamako", "Africa/Ouagadougou", "Africa/Lome",
        "Africa/Cotonou", "Africa/Niamey", "Africa/Ndjamena", "Africa/Bangui",
        "Africa/Khartoum", "Africa/Mogadishu", "Indian/Antananarivo",
        "Indian/Maldives", "Indian/Comoro", "Indian/Mayotte",
    }
    # ...and the reverse: points inside the band whose places are temperate in
    # practice (altitude / sea currents).
    tropic -= {"Asia/Kathmandu", "Asia/Thimphu", "America/Mexico_City",
               "Asia/Taipei", "Asia/Hong_Kong", "Asia/Macau", "Asia/Shanghai"}

    cc_by_zone = {tz: cc for tz, (cc, _) in zones.items()}
    names = _country_names(set(cc_by_zone.values()))

    header = f'''"""
GENERATED FILE - do not edit by hand.  Regenerate with:

    python3 tools/make_seasonal_geo.py

Offline timezone geography for the seasonal themes (cubeon/seasonal.py). All of
this is derived data from the public-domain IANA tz database + iso-codes; it is
committed so a shipped Cubeon knows where its user is without reading
/usr/share/zoneinfo (absent on Windows) and without a network call.

How the classification is made:
  * ZONE_COUNTRY - the ISO-3166 country of an IANA zone (zone.tab column 1).
  * SOUTH_ZONES  - zones whose representative latitude is south of the equator.
  * TROPIC_ZONES - |latitude| <= {TROPIC_LAT}, where the four-season model does not
                   apply: those users get a wet/dry season (see seasonal.py)
                   instead of a fake "autumn".
  * WIN_ZONES    - Windows zone names (tzutil /g) mapped to IANA, trimmed to the
                   entries where being wrong would visibly mis-theme someone.
Anything not listed is assumed northern/temperate - the right guess for ~87% of
people, and always overridable in Settings > Seasonal.

Sources: {", ".join(used) or "n/a"} and iso_3166-1 (country names).
"""

GENERATED_AT = "2026-09-17"
'''

    body = "\n\n".join([
        header,
        _fmt_dict("ZONE_COUNTRY", cc_by_zone),
        _fmt_dict("COUNTRY_NAME", names),
        _fmt_set("SOUTH_ZONES", south),
        _fmt_set("TROPIC_ZONES", tropic),
        _fmt_dict("WIN_ZONES", WIN_ZONES, per_line=2),
    ]) + "\n"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # The output is code, so it must compile before it is allowed onto disk: a
    # broken table used to be invisible until the launcher tried to import it
    # (the palette hook swallowed the SyntaxError and quietly kept the default).
    compile(body, OUT, "exec")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"wrote {OUT}")
    print(f"  zones={len(cc_by_zone)} countries={len(names)} "
          f"south={len(south)} tropic={len(tropic)} "
          f"windows={len(WIN_ZONES)}")


if __name__ == "__main__":
    sys.exit(main())

