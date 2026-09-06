"""
Cosmetics: pixel hats baked onto the skin's hat layer.

HOW THIS WORKS (and why it needs no new mods)
The vanilla skin format has a second head layer - the "hat" layer - at a
fixed spot in the sheet: region (32,0)-(64,16) of a 64x64 skin (same
coordinates on the legacy 64x32 layout). Whatever semi-transparent pixels
sit there render floating just off the head, in vanilla, for everyone the
skin is visible to. Skin editors ship hats exactly this way.

Cubeon already syncs the player's skin into CustomSkinLoader's LocalSkin
folder at launch (cubeon/skins.py), and CSL auto-installs with the game.
So a hat is: draw a 32x16 template laid out exactly like that hat region,
alpha-composite it over the active skin (or a built-in default Steve when
no custom skin is set), and let the existing sync do the rest. Click "wear
hat" here, press Play, see the hat on your head.

Honest limits, same as any LocalSkin content: only THIS player sees it
(CSL's LocalSkin is local-only by design - the shared cape is the part
friends see), and hats are pixel art confined to the head box - not
Feather-style 3D models.

Template layout (32x16, mirroring the sheet's hat region shifted by -32x):

    top(8,0)  bottom(16,0)
    right(0,8) front(8,8) left(16,8) back(24,8)     each face 8x8

Row 8 of a side face is the TOP of the head (y grows downward), which is
why every hat paints bands starting at row 8.
"""
import os

from PIL import Image

from .paths import SKINS_DIR

# ---------------------------------------------------------------------------
# Template plumbing
# ---------------------------------------------------------------------------

# Face origins inside the 32x16 hat template.
FACE_TOP, FACE_BOTTOM = (8, 0), (16, 0)
FACE_RIGHT, FACE_FRONT, FACE_LEFT, FACE_BACK = (0, 8), (8, 8), (16, 8), (24, 8)
SIDE_FACES = (FACE_RIGHT, FACE_FRONT, FACE_LEFT, FACE_BACK)

_TEMPLATE_CACHE = {}


def _rgba(img, x, y, color):
    if 0 <= x < img.width and 0 <= y < img.height:
        img.putpixel((x, y), color)


def _rect(img, x0, y0, x1, y1, color):
    """Inclusive-start, exclusive-end rectangle fill."""
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            _rgba(img, xx, yy, color)


def _band(t, row_start, row_end, color, faces=SIDE_FACES):
    """Paints the same horizontal band on every side face. Rows are in
    template space: row 8 == top of the head, row 16 == neck."""
    for fx, fy in faces:
        _rect(t, fx, fy + (row_start - 8), fx + 8, fy + (row_end - 8), color)


# ---------------------------------------------------------------------------
# The hat catalogue - each entry paints one 32x16 hat-layer template.
# ---------------------------------------------------------------------------

def _hat_top_hat(t):
    black, sheen = (26, 26, 30, 255), (44, 44, 50, 255)
    _band(t, 8, 11, black)                     # crown
    _band(t, 11, 13, (13, 13, 15, 255))        # brim shadow line
    fx, fy = FACE_TOP
    _rect(t, fx, fy, fx + 8, fy + 8, black)    # top of the cylinder
    _rect(t, fx + 3, fy + 3, fx + 5, fy + 5, sheen)


def _hat_cap(t):
    red, dark = (201, 58, 52, 255), (150, 40, 36, 255)
    _band(t, 8, 11, red)                       # dome sides
    _band(t, 10, 12, dark, faces=(FACE_FRONT,))  # brim shadow over the eyes
    fx, fy = FACE_TOP
    _rect(t, fx, fy, fx + 8, fy + 8, red)
    _rgba(t, fx + 3, fy + 3, (237, 237, 237, 255))  # button


def _hat_crown(t):
    gold, light = (232, 178, 60, 255), (246, 210, 110, 255)
    ruby, sapphire = (208, 72, 72, 255), (74, 123, 208, 255)
    for fx, fy in SIDE_FACES:
        # Spike tips, then the solid band under them.
        for sx in (1, 3, 5):
            _rgba(t, fx + sx, fy + 0, gold)
        _rect(t, fx, fy + 1, fx + 8, fy + 3, gold)
    # Jewels on the front, a glint on the sides.
    _rgba(t, FACE_FRONT[0] + 2, FACE_FRONT[1] + 2, ruby)
    _rgba(t, FACE_FRONT[0] + 5, FACE_FRONT[1] + 2, sapphire)
    for fx, fy in (FACE_RIGHT, FACE_LEFT, FACE_BACK):
        _rgba(t, fx + 4, fy + 1, light)


def _hat_wizard(t):
    purple, dark, gold = (107, 79, 168, 255), (82, 58, 133, 255), (232, 178, 60, 255)
    # Cone: shrinking bands stepping down toward the eyes.
    _band(t, 8, 10, purple)
    for fx, fy in SIDE_FACES:
        _rect(t, fx + 1, fy + 2, fx + 7, fy + 3, purple)
        _rect(t, fx + 2, fy + 3, fx + 6, fy + 4, dark)
    _band(t, 12, 13, gold)                     # brim band


def _hat_halo(t):
    gold = (242, 204, 85, 255)
    fx, fy = FACE_TOP
    for i in range(8):
        _rgba(t, fx + i, fy, gold)
        _rgba(t, fx + i, fy + 7, gold)
        _rgba(t, fx, fy + i, gold)
        _rgba(t, fx + 7, fy + i, gold)


def _hat_headphones(t):
    dark, pad = (35, 38, 43, 255), (94, 106, 120, 255)
    fx, fy = FACE_TOP
    for i in range(8):                         # band over the head
        _rgba(t, fx + i, fy, dark)
        _rgba(t, fx + i, fy + 7, dark)
        _rgba(t, fx, fy + i, dark)
        _rgba(t, fx + 7, fy + i, dark)
    # Ear cups on the side faces.
    rx, ry = FACE_RIGHT
    _rect(t, rx + 5, ry + 1, rx + 8, ry + 6, dark)
    _rect(t, rx + 6, ry + 2, rx + 7, ry + 5, pad)
    lx, ly = FACE_LEFT
    _rect(t, lx, ly + 1, lx + 3, ly + 6, dark)
    _rect(t, lx + 1, ly + 2, lx + 2, ly + 5, pad)


def _hat_santa(t):
    red, white = (201, 58, 52, 255), (242, 242, 242, 255)
    _band(t, 8, 10, red)                       # floppy cone
    _band(t, 10, 12, white)                    # trim
    fx, fy = FACE_TOP
    _rect(t, fx + 3, fy, fx + 5, fy + 2, white)    # pompom, tipped forward
    _rgba(t, FACE_FRONT[0] + 3, FACE_FRONT[1] + 0, white)
    _rgba(t, FACE_FRONT[0] + 4, FACE_FRONT[1] + 0, white)


def _hat_straw(t):
    tan, dark, red = (216, 181, 106, 255), (184, 149, 78, 255), (201, 58, 52, 255)
    _band(t, 8, 10, tan)                       # wide brim
    _band(t, 9, 10, dark, faces=(FACE_RIGHT, FACE_FRONT, FACE_LEFT, FACE_BACK))
    fx, fy = FACE_TOP
    _rect(t, fx, fy, fx + 8, fy + 8, tan)      # brim top
    _rect(t, fx + 2, fy + 2, fx + 6, fy + 6, dark)  # dome
    _band(t, 8, 9, red)                        # hat band


def _hat_veteran(t):
    # Earned at 10 hours played. A weathered explorer's cap with a compass
    # rose pin on the front: olive felt, stitched band, brass button.
    olive, dark, brass = (96, 108, 56, 255), (70, 80, 42, 255), (196, 154, 74, 255)
    _band(t, 8, 11, olive)                     # dome sides
    _band(t, 11, 12, dark)                     # stitched brim
    fx, fy = FACE_TOP
    _rect(t, fx + 1, fy + 1, fx + 7, fy + 7, olive)
    _rgba(t, fx + 3, fy + 3, dark)             # leather patch on top
    # Compass rose: brass plus-sign with a dark nub.
    cx, cy = FACE_FRONT[0] + 4, FACE_FRONT[1] + 2
    _rgba(t, cx, cy - 1, brass); _rgba(t, cx, cy + 1, brass)
    _rgba(t, cx - 1, cy, brass); _rgba(t, cx + 1, cy, brass)
    _rgba(t, cx, cy, dark)


def _hat_party(t):
    # Earned at 3 friends. A bright party hat with confetti dots and a
    # pompom tip: the classic cone, magenta with cyan/yellow sprinkles.
    magenta, deep, cyan, yellow = (211, 47, 132, 255), (150, 30, 92, 255), \
        (66, 205, 219, 255), (250, 214, 90, 255)
    # Cone that tapers toward the crown: full band at the eyes, one pixel
    # narrower one row up, single column of pompom above the front face.
    _band(t, 11, 12, deep)                     # brim
    _band(t, 10, 11, magenta)
    for fx, fy in SIDE_FACES:
        _rgba(t, fx + 1, fy + 2, magenta)
        _rgba(t, fx + 6, fy + 2, magenta)
    # Confetti sprinkles, same pattern on every face so it reads from any
    # angle at 8px.
    for fx, fy in SIDE_FACES:
        _rgba(t, fx + 2, fy + 0, cyan)
        _rgba(t, fx + 5, fy + 0, yellow)
    fx, fy = FACE_TOP
    _rect(t, fx + 3, fy + 3, fx + 5, fy + 5, magenta)
    _rgba(t, fx + 4, fy + 4, yellow)           # pompom on top


def _hat_host(t):
    # Earned by hosting a world/server. A broadcaster's headset-mic: dark
    # band, ear cups, and a boom arm reaching around the front to the mouth.
    dark, pad, silver = (32, 34, 40, 255), (94, 106, 120, 255), (176, 182, 190, 255)
    fx, fy = FACE_TOP
    for i in range(8):                         # band over the head
        _rgba(t, fx + i, fy, dark)
        _rgba(t, fx + i, fy + 7, dark)
        _rgba(t, fx, fy + i, dark)
        _rgba(t, fx + 7, fy + i, dark)
    # Ear cups.
    rx, ry = FACE_RIGHT
    _rect(t, rx + 5, ry + 2, rx + 8, ry + 6, dark)
    _rect(t, rx + 6, ry + 3, rx + 7, ry + 5, pad)
    lx, ly = FACE_LEFT
    _rect(t, lx, ly + 2, lx + 3, ly + 6, dark)
    _rect(t, lx + 1, ly + 3, lx + 2, ly + 5, pad)
    # Boom arm: from the right ear cup around the front to a mic dot by
    # the mouth (front face, low-left).
    frx, fry = FACE_FRONT
    _rgba(t, frx + 0, fry + 5, silver)
    _rgba(t, frx + 1, fry + 5, silver)
    _rgba(t, frx + 2, fry + 5, silver)
    _rgba(t, frx + 2, fry + 4, dark)           # mic capsule


def _hat_founder(t):
    # Early-adopter hat: a laurel-wreath circlet in gold. Just the band
    # (no tall crown) so it reads as "medal for the head" at a glance.
    gold, light = (232, 178, 60, 255), (246, 210, 110, 255)
    _band(t, 10, 11, gold)                     # circlet
    # Leaves: alternating light/dark ticks above the band, all around.
    for fx, fy in SIDE_FACES:
        for lx in range(0, 8, 2):
            _rgba(t, fx + lx, fy + 0, light)
            _rgba(t, fx + lx + 1, fy + 0, gold)
    fx, fy = FACE_FRONT
    _rgba(t, fx + 3, fy + 0, light)            # a small crest on the front
    _rgba(t, fx + 4, fy + 0, light)


HATS = [
    {"id": "tophat", "name": "Top Hat", "draw": _hat_top_hat},
    {"id": "cap", "name": "Cap", "draw": _hat_cap},
    {"id": "crown", "name": "Crown", "draw": _hat_crown},
    {"id": "wizard", "name": "Wizard", "draw": _hat_wizard},
    {"id": "halo", "name": "Halo", "draw": _hat_halo},
    {"id": "headphones", "name": "Headphones", "draw": _hat_headphones},
    {"id": "santa", "name": "Santa", "draw": _hat_santa},
    {"id": "straw", "name": "Straw Hat", "draw": _hat_straw},
    # Earnable hats - unlock conditions live in cubeon/milestones.py and
    # set_hat() refuses to wear a locked one. "require" is the milestone id.
    {"id": "veteran", "name": "Veteran's Cap", "draw": _hat_veteran,
     "require": "veteran"},
    {"id": "party", "name": "Party Hat", "draw": _hat_party,
     "require": "party"},
    {"id": "host", "name": "Host Headset", "draw": _hat_host,
     "require": "host"},
    {"id": "founder", "name": "Founder Laurel", "draw": _hat_founder,
     "require": "founder"},
]


def list_hats():
    """Catalogue for the UI: [{id, name, require?}]. Earnable hats carry
    their milestone id so the UI can render lock state + progress."""
    return [{"id": h["id"], "name": h["name"],
             **({"require": h["require"]} if h.get("require") else {})}
            for h in HATS]


def hat_requirement(hat_id):
    """The milestone id gating a hat, or None when it's freely wearable."""
    hat = get_hat(hat_id)
    return hat.get("require") if hat else None


def hat_unlocked(hat_id) -> bool:
    """Whether an earnable hat's milestone is met (trivially True for
    freely-wearable hats). Import lives inside so the cosmetics module
    stays importable without the milestones state (tests, previews)."""
    req = hat_requirement(hat_id)
    if req is None:
        return True
    from . import milestones
    return milestones.is_unlocked(req)


def get_hat(hat_id):
    for h in HATS:
        if h["id"] == hat_id:
            return h
    return None


def hat_template(hat_id) -> Image.Image | None:
    """The 32x16 hat-layer template for a hat (drawn once, then cached)."""
    hat = get_hat(hat_id)
    if not hat:
        return None
    if hat_id not in _TEMPLATE_CACHE:
        t = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
        hat["draw"](t)
        _TEMPLATE_CACHE[hat_id] = t
    return _TEMPLATE_CACHE[hat_id]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def apply_hat_layer(skin: Image.Image, hat_id: str) -> Image.Image:
    """Returns a copy of the skin with the hat's pixels composited over the
    hat region (32,0)-(64,16). Works for 64x64 and legacy 64x32 sheets -
    the hat region lives at the same coordinates on both."""
    template = hat_template(hat_id)
    if not template:
        return skin
    out = skin.convert("RGBA").copy()
    out.alpha_composite(template, dest=(32, 0))
    return out


def default_base_skin() -> Image.Image:
    """A built-in Steve-style 64x64 skin, so a hat is wearable even before
    the user uploads any custom skin. Only the head really matters for the
    hat, but CSL expects a whole valid sheet, so the body is filled in too."""
    s = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    skin = (200, 144, 108, 255)
    skin_shade = (180, 131, 107, 255)
    hair = (59, 42, 26, 255)
    shirt, shirt_shade = (15, 169, 169, 255), (12, 143, 143, 255)
    jeans, shoes = (58, 75, 168, 255), (86, 86, 86, 255)
    white, iris = (255, 255, 255, 255), (82, 61, 137, 255)

    # Head - base faces.
    _rect(s, 8, 8, 16, 16, skin)        # face
    _rect(s, 0, 8, 8, 16, skin)         # right
    _rect(s, 16, 8, 24, 16, skin)       # left
    _rect(s, 24, 8, 32, 16, skin)       # back
    _rect(s, 16, 0, 24, 8, skin_shade)  # chin/underside
    # Hair: top of the head plus a fringe around the upper sides.
    _rect(s, 8, 0, 16, 8, hair)
    for hx in (0, 16, 24):              # right / left / back side faces
        _rect(s, hx, 8, hx + 8, 11, hair)
    _rect(s, 24, 8, 32, 13, hair)       # back of the head is mostly hair
    # Face: eyes with the classic white-outside/purple-inside layout, nose, mouth.
    _rgba(s, 9, 11, white); _rgba(s, 10, 11, iris)
    _rgba(s, 13, 11, iris); _rgba(s, 14, 11, white)
    _rect(s, 11, 12, 13, 13, skin_shade)
    _rect(s, 11, 13, 13, 14, (126, 79, 61, 255))

    # Body: teal shirt, bare arms (classic Steve), jeans with grey shoes.
    _rect(s, 20, 20, 28, 32, shirt)
    _rect(s, 20, 20, 28, 21, shirt_shade)
    for ax, ay in ((44, 20), (36, 52)):
        _rect(s, ax, ay, ax + 4, ay + 12, skin)
        _rect(s, ax, ay + 10, ax + 4, ay + 12, skin_shade)   # hands
    for lx, ly in ((4, 20), (20, 52)):
        _rect(s, lx, ly, lx + 4, ly + 12, jeans)
        _rect(s, lx, ly + 9, lx + 4, ly + 12, shoes)         # shoes
    return s


def _base_skin_for(cfg) -> Image.Image:
    """The active custom skin if there is one on disk, else the built-in
    default. The hat composites over whatever this returns."""
    filename = cfg.get("active_skin")
    if filename:
        path = os.path.join(SKINS_DIR, filename)
        if os.path.isfile(path):
            try:
                with Image.open(path) as sheet:
                    return sheet.convert("RGBA")
            except OSError:
                pass
    return default_base_skin()


def compose_skin_with_hat(cfg) -> Image.Image:
    """The full skin sheet that should currently be in-game: active skin
    (or default Steve) with the configured hat (if any) baked on."""
    img = _base_skin_for(cfg)
    hat_id = cfg.get("cosmetic_hat")
    if hat_id and get_hat(hat_id):
        # If a worn hat somehow lost its unlock locally (state file deleted
        # before the Worker restore ran), still render it: the unlock was
        # earned, stripping it mid-session helps nobody. set_hat() is the
        # enforcement point for NEW wear requests.
        img = apply_hat_layer(img, hat_id)
    return img


# ---------------------------------------------------------------------------
# Persistence + previews
# ---------------------------------------------------------------------------

# Face shading multipliers for the isometric render, mimicking Minecraft's
# directional light: the top face catches full light, the head's LEFT side
# (viewer's left, angled toward the light) a step dimmer, the FRONT face
# (viewer's right, angled away) another step down.
_ISO_SHADE = {"top": 1.00, "left": 0.80, "right": 0.62}


def _shade(img, factor):
    """Multiplies an RGBA face's RGB by a light factor, alpha untouched."""
    if factor >= 1.0:
        return img
    r, g, b, a = img.split()
    r = r.point(lambda v: int(v * factor))
    g = g.point(lambda v: int(v * factor))
    b = b.point(lambda v: int(v * factor))
    return Image.merge("RGBA", (r, g, b, a))


def render_head_isometric(cfg, out_path: str, hat_id=None, zoom: int = 10,
                          pad: int = 6) -> str | None:
    """Renders the player's head as a 3D isometric cube (Minecraft item-
    render style): top + two visible side faces, each the real skin pixels
    with its hat-layer tile composited on, shaded per face to fake a light
    from the upper left. `hat_id` overrides cfg's worn hat (hat tiles pass
    their own id to preview not-yet-worn hats).

    Geometry: classic 2:1 pixel isometric. The three visible faces of the
    8x8x8 head are sheared onto one lattice with PIL AFFINE transforms
    (dest->source inverse maps, NEAREST resample so pixel art stays crisp,
    fillcolor transparent so out-of-face dest pixels stay empty). Total
    cube: 16s x 12s screen px for lattice step s.

    Which faces show: the camera looks down at the head from the front-
    right, so the visible sides are the head's LEFT face (sheet 16,8 - the
    viewer's left) and the FRONT face (sheet 8,8 - viewer's right). The
    hat template mirrors the head layout 1:1, so the same crops work for
    both layers. Painter's order: sides first, top last, so the top face's
    front edges overdraw the side shears cleanly.
    """
    base = _base_skin_for(cfg)
    if hat_id is None:
        hat_id = cfg.get("cosmetic_hat")
    template = hat_template(hat_id) if hat_id and get_hat(hat_id) else None

    def face(ox, oy):
        """One 8x8 head face with its hat tile layered on (or bare)."""
        piece = base.crop((ox, oy, ox + 8, oy + 8)).copy()
        if template is not None:
            piece.alpha_composite(template.crop((ox, oy, ox + 8, oy + 8)))
        return piece

    top = face(8, 0)     # top of the head
    left = _shade(face(16, 8), _ISO_SHADE["left"])   # head's left side
    right = _shade(face(8, 8), _ISO_SHADE["right"])  # the face itself

    s = max(1, int(zoom))
    W, H = 16 * s, 12 * s
    cube = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Dest->source affine inverses. Source (u,v) in 0..8; screen:
    #   top:   X = s(u - v + 8), Y = s(u + v)/2
    #   left:  X = s u,           Y = s(u/2 + v + 4)
    #   right: X = s(u + 8),      Y = s(-u/2 + v + 8)
    top_t = top.transform(
        (W, H), Image.AFFINE,
        (0.5 / s, -0.5 / s, 4.0, 0.5 / s, 0.5 / s, 0.0),
        resample=Image.NEAREST, fillcolor=(0, 0, 0, 0))
    left_t = left.transform(
        (W, H), Image.AFFINE,
        (1.0 / s, 0.0, 0.0, -0.5 / s, 1.0 / s, 4.0),
        resample=Image.NEAREST, fillcolor=(0, 0, 0, 0))
    right_t = right.transform(
        (W, H), Image.AFFINE,
        (1.0 / s, 0.0, -8.0, 0.5 / s, 1.0 / s, 8.0),
        resample=Image.NEAREST, fillcolor=(0, 0, 0, 0))

    for layer in (left_t, right_t, top_t):
        cube.alpha_composite(layer)

    if pad:
        pw, ph = W + 2 * pad, H + 2 * pad
        padded = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        padded.paste(cube, (pad, pad), cube)
        cube = padded
    cube.save(out_path)
    return out_path


def set_hat(cfg, hat_id: str | None) -> None:
    """Wear/remove a hat and re-sync the composed skin through the existing
    CustomSkinLoader pipeline. Mirrors set_active_skin()'s sync-then-save
    ordering (the sync records bookkeeping that must land in one save).
    Earnable hats must be unlocked first (cubeon/milestones.py) - wearing
    a locked one raises, which the UI turns into an "earn it" hint."""
    if hat_id is not None and not get_hat(hat_id):
        raise ValueError(f"Unknown hat: {hat_id}")
    if hat_id is not None and not hat_unlocked(hat_id):
        raise PermissionError(f"Locked hat: {hat_id}")
    cfg["cosmetic_hat"] = hat_id
    from . import skins  # lazy: skins imports this module at the top
    skins.sync_local_skin_to_csl(cfg)
    from .config import save_config
    save_config(cfg)


def render_hat_preview(hat_id, cfg, out_path: str, scale: int = 10) -> str | None:
    """Renders a hat thumbnail as a 3D isometric head cube wearing the hat
    (see render_head_isometric). `scale` is the lattice zoom. Falls back to
    bare when the hat id is unknown."""
    if not get_hat(hat_id):
        return None
    return render_head_isometric(cfg, out_path, hat_id=hat_id, zoom=scale)


def preview_composed_body(cfg, out_path: str, scale: int = 8) -> str | None:
    """Preview of exactly what would be in-game right now (active skin +
    hat): the body in its flat front view with the head drawn as a 3D
    isometric cube (see render_head_isometric) - hats read as they will
    in-game: on a head, seen from an angle, shaded. The flat head the body
    renderer would draw is replaced by the cube (body starts right under
    it), so there's no doubled head."""
    from . import skins
    body_path = os.path.join(SKINS_DIR, "_cosmetic_preview.png")
    compose_skin_with_hat(cfg).save(body_path)
    flat = skins.render_local_skin_preview("_cosmetic_preview.png",
                                           out_path, scale)
    body = Image.open(flat).convert("RGBA")
    bw, bh = body.size
    # The flat renderer draws the head as a 24px-wide, 24px-tall block at
    # factor 3 scaled by scale//3, centered horizontally, rows 0..24*(scale//3).
    f = max(1, scale // 3)
    head_px = 24 * f                     # flat head size in output px
    # Erase the flat head (its full band, incl. hat layer already in it).
    body.paste((0, 0, 0, 0), (bw // 2 - head_px // 2, 0,
                              bw // 2 + head_px // 2, head_px))
    # Draw the iso cube scaled to a bit wider than the flat head was, and
    # extend the canvas upward for hat headroom (tall hats need space).
    cube = render_head_isometric(cfg, os.path.join(SKINS_DIR, "_iso_tmp.png"),
                                 hat_id=None, zoom=max(2, f))
    if cube is None:
        body.save(out_path)
        return out_path
    cube_img = Image.open(cube)
    target_w = min(bw, int(head_px * 1.5))
    ratio = target_w / cube_img.width
    target_h = int(cube_img.height * ratio)
    cube_img = cube_img.resize((target_w, target_h), Image.NEAREST)
    headroom = max(0, target_h - head_px)
    canvas = Image.new("RGBA", (bw, bh + headroom), (0, 0, 0, 0))
    canvas.paste(body, (0, headroom), body)
    canvas.alpha_composite(cube_img, ((bw - target_w) // 2, 0))
    canvas.save(out_path)
    return out_path
