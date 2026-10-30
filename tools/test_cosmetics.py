"""Offline checks for the cosmetics bundle, the launcher preview, and the game.

Cosmetics exist twice on purpose: the launcher reads ``assets/cosmetics`` and
the Cubeon Client reads its own copy from the mod jar. One generator writes
both, and this test is what keeps that promise honest. It checks:

* the catalogue's shape (25 items, 10 shoulder / 15 back, unique ids, valid boxes);
* the atlas layout and every preview quad, including the mirrored wing;
* that the wing's cut-out silhouette has real thickness on its edges, so it
  cannot render as a flat plank;
* thumbnails, selection persistence and the atomic game-sync file;
* that the launcher bundle and the mod bundle are byte-identical;
* that the committed PNGs are still the generator's own output;
* and, when a JDK is available, that the Java renderer builds EXACTLY the same
  quads as the Python preview - the one check that catches "looks right in the
  Skin tab, hangs wrong in game".

No display and no network: everything is read from the repository, and HOME is
redirected into a scratch directory before cubeon binds its paths.
"""
import importlib.util
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home

_sandbox_home.isolate()

from PIL import Image  # noqa: E402

from cubeon import config, cosmetics  # noqa: E402

_passed = _failed = _skipped = 0

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER_BUNDLE = os.path.join(REPO, "assets", "cosmetics")
MOD_RESOURCES = os.path.join(REPO, "mod", "src", "main", "resources",
                             "assets", "cubeon-client")
MOD_BUNDLE = os.path.join(MOD_RESOURCES, "cosmetics")
MOD_TEXTURES = os.path.join(MOD_RESOURCES, "textures", "cosmetics")
JAVA_SRC = os.path.join(REPO, "mod", "src", "main", "java")


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


def skip(label, why):
    global _skipped
    _skipped += 1
    print(f"skip  {label}  ({why})")


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def test_catalog():
    print("\n-- catalogue --")
    catalog = cosmetics.catalog()
    check("catalogue version is 1", catalog.get("version") == 1,
          repr(catalog.get("version")))

    every = cosmetics.items()
    shoulder = cosmetics.items("shoulder")
    back = cosmetics.items("back")
    check("25 cosmetics", len(every) == 25, str(len(every)))
    check("10 shoulder items", len(shoulder) == 10, str(len(shoulder)))
    check("15 back items", len(back) == 15, str(len(back)))
    check("every item is in one slot", len(shoulder) + len(back) == len(every))

    ids = [item["id"] for item in every]
    textures = [item["texture"] for item in every]
    names = [item["name"] for item in every]
    check("ids are unique", len(set(ids)) == len(ids), str(len(ids) - len(set(ids))))
    check("textures are unique", len(set(textures)) == len(textures))
    check("display names are unique", len(set(names)) == len(names))

    for slot in cosmetics.SLOTS:
        anchor = catalog.get("anchors", {}).get(slot)
        check(f"{slot} anchor is a 3-vector", isinstance(anchor, list) and len(anchor) == 3,
              repr(anchor))
        if isinstance(anchor, list) and anchor:
            check(f"{slot} anchor matches the runtime constant",
                  abs(anchor[0] - cosmetics.ANCHORS[slot][0]) < 1e-9,
                  f"{anchor[0]} vs {cosmetics.ANCHORS[slot][0]}")

    problems = []
    for item in every:
        item_id = item.get("id", "?")
        if not isinstance(item.get("id"), str) or not item["id"]:
            problems.append((item_id, "missing id"))
        if item.get("slot") not in cosmetics.SLOTS:
            problems.append((item_id, "bad slot " + repr(item.get("slot"))))
        for key in ("name", "blurb"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                problems.append((item_id, f"empty {key}"))
        texture = item.get("texture", "")
        if not texture or os.path.basename(texture) != texture:
            problems.append((item_id, "texture is not a bare file name"))
            continue
        path = os.path.join(LAUNCHER_BUNDLE, texture)
        if not os.path.isfile(path):
            problems.append((item_id, "missing PNG " + texture))
            continue
        with Image.open(path) as image:
            if image.mode != "RGBA":
                problems.append((item_id, "PNG is " + image.mode + ", not RGBA"))
            if image.size != (item.get("tex_w"), item.get("tex_h")):
                problems.append((item_id, "tex_w/tex_h disagree with the PNG: "
                                 f"{image.size} vs "
                                 f"{(item.get('tex_w'), item.get('tex_h'))}"))
        if not isinstance(item.get("tex_w"), int) or item["tex_w"] <= 0:
            problems.append((item_id, "bad tex_w"))
        if not isinstance(item.get("tex_h"), int) or item["tex_h"] <= 0:
            problems.append((item_id, "bad tex_h"))

        boxes = item.get("boxes")
        if not isinstance(boxes, list) or not boxes:
            problems.append((item_id, "no boxes"))
            continue
        rects = []
        for index, box in enumerate(boxes):
            origin, size, uv = box.get("origin"), box.get("size"), box.get("uv")
            px = box.get("px")
            if not (isinstance(origin, list) and len(origin) == 3
                    and all(_is_number(v) for v in origin)):
                problems.append((item_id, f"box {index} bad origin"))
                continue
            if not (isinstance(size, list) and len(size) == 3
                    and all(_is_number(v) and v > 0 for v in size)):
                problems.append((item_id, f"box {index} bad size"))
                continue
            if not isinstance(px, int) or px <= 0:
                problems.append((item_id, f"box {index} bad px"))
                continue
            if not (isinstance(uv, list) and len(uv) == 2
                    and all(isinstance(v, int) and v >= 0 for v in uv)):
                problems.append((item_id, f"box {index} bad uv"))
                continue
            if not isinstance(box.get("mirror"), bool):
                problems.append((item_id, f"box {index} mirror is not a bool"))
            for face, (x, y, w, h) in cosmetics.face_rects(box).items():
                if any(abs(value - round(value)) > 1e-6 for value in (x, y, w, h)):
                    problems.append((item_id, f"box {index} {face} fractional texel boundary"))
                if x < 0 or y < 0 or x + w > item["tex_w"] or y + h > item["tex_h"]:
                    problems.append((item_id, f"box {index} {face} leaves the atlas"))
                rects.append((index, face, x, y, w, h))
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                _, face_a, xa, ya, wa, ha = rects[i]
                _, face_b, xb, yb, wb, hb = rects[j]
                if xa < xb + wb and xb < xa + wa and ya < yb + hb and yb < ya + ha:
                    problems.append((item_id, f"{face_a}/{face_b} atlas overlap"))

    check("every item is well formed", not problems, "; ".join(
        f"{i}: {p}" for i, p in problems[:6]))


def test_face_layout():
    print("\n-- atlas layout --")
    problems = []
    for item in cosmetics.items():
        for box in item["boxes"]:
            width, height, depth = box["size"]
            px = box["px"]
            rects = cosmetics.face_rects(box)
            expected = {
                "front": (width * px, height * px),
                "back": (width * px, height * px),
                "left": (depth * px, height * px),
                "right": (depth * px, height * px),
                "top": (width * px, depth * px),
                "bottom": (width * px, depth * px),
            }
            for face, (w, h) in expected.items():
                x, y, rw, rh = rects[face]
                if (rw, rh) != (w, h):
                    problems.append((item["id"], face, (rw, rh), (w, h)))
                if face == "front" and (x, y) != ((box["uv"][0] + depth * px),
                                                 box["uv"][1] + depth * px):
                    problems.append((item["id"], "front offset", (x, y)))
    check("all six tiles use the documented sizes", not problems,
          str(problems[:4]))


# ---------------------------------------------------------------------------
# Preview geometry
# ---------------------------------------------------------------------------


def _face_sizes(item):
    sizes = set()
    for box in item["boxes"]:
        for rect in cosmetics.face_rects(box).values():
            sizes.add((rect[2], rect[3]))
    return sizes


def test_preview_faces():
    print("\n-- preview geometry --")
    problems = []
    for item in cosmetics.items():
        faces = cosmetics.preview_faces(item)
        if not faces:
            problems.append((item["id"], "no visible faces"))
            continue
        sizes = _face_sizes(item)
        for vertices, normal, tile in faces:
            if len(vertices) != 3:
                problems.append((item["id"], "quad does not have 3 anchors"))
            if tile.size not in sizes:
                problems.append((item["id"], f"tile {tile.size} is not an atlas slot"))
            if tile.getbbox() is None:
                problems.append((item["id"], "transparent tile was emitted"))
            if tile.size[0] <= 0 or tile.size[1] <= 0:
                problems.append((item["id"], "empty tile"))
            nonzero = [abs(v) for v in normal if abs(v) > 1e-9]
            if len(nonzero) != 1 or abs(nonzero[0] - 1.0) > 1e-9:
                problems.append((item["id"], f"normal is not an axis unit: {normal}"))

        mirror_boxes = [box for box in item["boxes"] if box.get("mirror")]
        if mirror_boxes:
            xs = [vertex[0] for face in faces for vertex in face[0]]
            anchor = cosmetics.ANCHORS[item["slot"]][0]
            if abs(min(xs) + max(xs) - 2 * anchor) > 1e-6:
                problems.append((item["id"], "mirrored wing is not symmetric "
                                 f"about x={anchor}: {min(xs)}..{max(xs)}"))
    check("every preview quad is well formed", not problems,
          str(problems[:4]))

    # Every mirrored feather piece must produce both wings.
    for item in cosmetics.items("back"):
        boxes = item["boxes"]
        if boxes and all(box.get("mirror") for box in boxes):
            faces = cosmetics.preview_faces(item)
            single = sum(1 for box in boxes
                         for name, rect in cosmetics.face_rects(box).items()
                         if name in box.get("faces", cosmetics.face_rects(box)) and rect[2] and rect[3])
            if len(faces) != 2 * single:
                check(f"{item['id']} has both wings", False, str(len(faces)))
            else:
                check(f"{item['id']} has both wings", True)


def test_wing_thickness():
    print("\n-- sealed cosmetics and wing silhouette --")
    wings = [item for item in cosmetics.items("back") if item.get("feathers")]
    check("five small and five giant wing pairs", len(wings) == 10, str(len(wings)))
    problems = []
    generator = _load_generator()
    for item in cosmetics.items():
        sheet = cosmetics.texture(item)
        for index, box in enumerate(item["boxes"]):
            for face, (x, y, w, h) in cosmetics.face_rects(box).items():
                tile = sheet.crop((x, y, x + w, y + h))
                if tile.getchannel("A").getextrema() != (255, 255):
                    problems.append((item["id"], index, face, "open surface"))
    check("every solid pet/pack/feather face is sealed", not problems, str(problems[:6]))
    problems = []
    originals = {
        "ember": "3ddae1544aa507c91a6a03e06a8d58daee1b0d4789fbd2507404838f5f455edc",
        "frost": "f551765686889d0500d0b160fb82c728fab41b03d6bb900cdd718ed82fd8bf5a",
        "leaf": "d51f63cef0ed459766b9955713ea84901affe5b544d54212772bdbe7e76548ae",
        "void": "00e7ae55a54458ea475281d49a5ec1c4e2aab80771e638c8006c7ea99dee72a2",
        "aurora": "2ba769751259ef2575956e171d7610367cbeba8ceb13bf122def7e4b917dd87e",
    }
    for item in wings:
        small = item["id"].endswith("_small")
        palette = generator.PALETTES[item["id"].removeprefix("back_").removesuffix("_small")]
        base, _ = generator.small_wing_art(palette) if small else generator.wing_art(palette)
        if small:
            base = base.resize((40, 52), Image.Resampling.NEAREST)
        reconstructed = Image.new("RGBA", base.size)
        occupied = set()
        actual_edges = set()
        if len(item["boxes"]) < 2:
            problems.append((item["id"], "still one rectangular slab"))
        for box in item["boxes"]:
            if not box["mirror"] or box["size"][2] != (0.5 if small else 0.75):
                problems.append((item["id"], "wrong thickness/mirror"))
            if "front" not in box.get("faces", ["front"]):
                left = round((box["origin"][0] - 1) * 4)
                top = round((box["origin"][1] + (0 if small else 11)) * 4)
                width, height = (round(value * 4) for value in box["size"][:2])
                for side in box["faces"]:
                    for y in range(top, top + height):
                        for x in range(left, left + width):
                            key = (x, y, side)
                            if key in actual_edges:
                                problems.append((item["id"], "duplicate edge wall"))
                            actual_edges.add(key)
                continue
            left = round((box["origin"][0] - 1) * 4)
            top = round((box["origin"][1] + (0 if small else 11)) * 4)
            width, height = (round(value * 4) for value in box["size"][:2])
            for y in range(top, top + height):
                for x in range(left, left + width):
                    if (x, y) in occupied or not (0 <= x < base.width and 0 <= y < base.height):
                        problems.append((item["id"], "overlapping/outside feather pieces"))
                    occupied.add((x, y))
            rects = cosmetics.face_rects(box)
            sheet = cosmetics.texture(item)
            x, y, w, h = rects["front"]
            tile = sheet.crop((x, y, x + w, y + h))
            reconstructed.paste(tile, (left, top))
            x, y, w, h = rects["back"]
            rear = sheet.crop((x, y, x + w, y + h)).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            if tile.tobytes() != rear.tobytes():
                problems.append((item["id"], "front/back mask shifted"))
        expected_edges = set()
        alpha = base.getchannel("A")
        for y in range(base.height):
            for x in range(base.width):
                if not alpha.getpixel((x, y)):
                    continue
                for side, dx, dy in (("left", 1, 0), ("right", -1, 0), ("top", 0, -1), ("bottom", 0, 1)):
                    if not (0 <= x + dx < base.width and 0 <= y + dy < base.height and alpha.getpixel((x + dx, y + dy))):
                        expected_edges.add((x, y, side))
        if expected_edges != actual_edges:
            problems.append((item["id"], "missing/extraneous silhouette wall"))
        if small:
            theme = item["id"].removeprefix("back_").removesuffix("_wings_small")
            if hashlib.sha256(reconstructed.tobytes()).hexdigest() != originals[theme]:
                problems.append((item["id"], "original cute artwork changed"))
        if reconstructed.tobytes() != base.tobytes():
            problems.append((item["id"], "feather geometry leaves gaps or a detached strip"))
    check("closed feather geometry exactly follows the native silhouette", not problems, str(problems[:6]))


def test_thumbnails():
    print("\n-- thumbnails --")
    problems = []
    for item in cosmetics.items():
        try:
            image = cosmetics.render_thumbnail(item)
        except Exception as exc:  # noqa: BLE001 - report, never abort the suite
            problems.append((item["id"], repr(exc)))
            continue
        if image.size != (96, 96):
            problems.append((item["id"], f"size {image.size}"))
        if image.mode != "RGBA":
            problems.append((item["id"], f"mode {image.mode}"))
        if image.getbbox() is None:
            problems.append((item["id"], "renders empty"))
    check("all 25 cards render a visible thumbnail", not problems,
          str(problems[:4]))


# ---------------------------------------------------------------------------
# Selection + game sync
# ---------------------------------------------------------------------------


def test_selection():
    print("\n-- selection and game sync --")
    scratch = tempfile.mkdtemp(prefix="cubeon-cosmetics-")
    cfg = dict(config.load_config())

    cosmetics.set_active(cfg, "shoulder", "shoulder_ember_fox")
    check("set_active stores the shoulder id",
          cfg.get("active_shoulder_item") == "shoulder_ember_fox")
    cosmetics.set_active(cfg, "back", "back_ember_wings")
    check("set_active stores the back id",
          cfg.get("active_back_item") == "back_ember_wings")

    saved = config.load_config()
    check("selection survives a config reload",
          saved.get("active_shoulder_item") == "shoulder_ember_fox"
          and saved.get("active_back_item") == "back_ember_wings")

    path = cosmetics.game_config_path(scratch)
    check("game config path is <game>/config/cubeon-cosmetics.json",
          path == os.path.join(scratch, "config", "cubeon-cosmetics.json"))
    written = cosmetics.sync_to_game(cfg, scratch)
    check("sync returns the path it wrote", written == path)
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    check("payload shape", payload == {"version": 1,
                                       "shoulder": "shoulder_ember_fox",
                                       "back": "back_ember_wings"},
          repr(payload))

    mtime = os.stat(path).st_mtime_ns
    cosmetics.sync_to_game(cfg, scratch)
    check("unchanged selection is not rewritten",
          os.stat(path).st_mtime_ns == mtime)
    leftovers = [name for name in os.listdir(os.path.dirname(path))
                 if name.startswith(".cubeon-cosmetics-")]
    check("no temp files are left behind", not leftovers, str(leftovers))

    cosmetics.set_active(cfg, "shoulder", None)
    check("set_active can clear a slot", cfg.get("active_shoulder_item") is None)
    # set_active mirrors into the real (sandboxed) game dir; copy that choice
    # into the scratch dir so the assertion reads what the user would ship.
    cosmetics.sync_to_game(cfg, scratch)
    with open(path, encoding="utf-8") as fh:
        check("payload drops a cleared slot", json.load(fh)["shoulder"] is None)

    for label, args in (
        ("unknown slot", ("head", None)),
        ("unknown item", ("shoulder", "shoulder_does_not_exist")),
        ("item in the wrong slot", ("shoulder", "back_ember_wings")),
    ):
        try:
            cosmetics.set_active(cfg, *args)
        except ValueError:
            check(f"set_active rejects {label}", True)
        else:
            check(f"set_active rejects {label}", False)

    # The mod ignores unknown ids; the launcher must still write them without
    # raising, because a downgraded jar is a normal situation.
    stale = dict(cfg, active_shoulder_item="shoulder_from_a_newer_launcher")
    try:
        cosmetics.sync_to_game(stale, scratch)
        check("sync tolerates an id the catalogue does not know", True)
    except Exception as exc:  # noqa: BLE001
        check("sync tolerates an id the catalogue does not know", False, repr(exc))

    read_only = tempfile.mkdtemp(prefix="cubeon-cosmetics-ro-")
    os.chmod(read_only, 0o500)
    try:
        try:
            cosmetics.sync_to_game(cfg, read_only)
            check("a read-only game folder never blocks a launch", True)
        except Exception as exc:  # noqa: BLE001
            check("a read-only game folder never blocks a launch", False, repr(exc))
    finally:
        os.chmod(read_only, 0o700)
        shutil.rmtree(read_only, ignore_errors=True)

    # No explicit folder means the instance being played. This is the bug
    # that made a selected cosmetic invisible in game: the launcher wrote the
    # shared root's config/, while the mod reads <instance>/config/.
    from cubeon import paths
    previous = paths.active_game_dir()
    instance = tempfile.mkdtemp(prefix="cubeon-cosmetics-instance-")
    try:
        paths.set_active_game_dir(instance)
        default_path = cosmetics.game_config_path()
        check("no explicit folder targets the active instance",
              default_path == os.path.join(instance, "config",
                                           "cubeon-cosmetics.json"),
              default_path)
        cosmetics.sync_to_game(cfg)
        check("the sync creates the instance's config folder",
              os.path.isfile(default_path), default_path)
        with open(default_path, encoding="utf-8") as fh:
            same = json.load(fh) == cosmetics.selection_payload(cfg)
        check("the instance file holds the current selection", same)
    finally:
        paths.set_active_game_dir(previous)
        shutil.rmtree(instance, ignore_errors=True)
    check("the active instance is restored after the check",
          paths.active_game_dir() == previous)
    shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# One generator, two bundles
# ---------------------------------------------------------------------------


def _same_bytes(left, right):
    try:
        with open(left, "rb") as a, open(right, "rb") as b:
            return a.read() == b.read()
    except OSError:
        return False


def test_bundles():
    print("\n-- launcher and mod bundles --")
    check("mod catalogue exists",
          os.path.isfile(os.path.join(MOD_BUNDLE, "catalog.json")))
    check("catalogues are byte-identical",
          _same_bytes(os.path.join(LAUNCHER_BUNDLE, "catalog.json"),
                      os.path.join(MOD_BUNDLE, "catalog.json")))
    missing = []
    differing = []
    for item in cosmetics.items():
        launcher = os.path.join(LAUNCHER_BUNDLE, item["texture"])
        jar = os.path.join(MOD_TEXTURES, item["texture"])
        if not os.path.isfile(jar):
            missing.append(item["texture"])
        elif not _same_bytes(launcher, jar):
            differing.append(item["texture"])
    check("every texture is in the mod bundle", not missing, str(missing[:4]))
    check("textures are byte-identical", not differing, str(differing[:4]))


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "cubeon_gen_cosmetics", os.path.join(REPO, "tools", "gen_cosmetics.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_output():
    print("\n-- generator is the source of truth --")
    try:
        generator = _load_generator()
    except Exception as exc:  # noqa: BLE001
        check("generator imports", False, repr(exc))
        return

    catalog = cosmetics.catalog()
    generated_ids = [item["id"] for item in generator.ITEMS]
    check("generator and catalogue list the same ids",
          generated_ids == [item["id"] for item in catalog["items"]],
          f"{len(generated_ids)} vs {len(catalog['items'])}")

    by_id = {item["id"]: item for item in catalog["items"]}
    problems = []
    for item in generator.ITEMS:
        entry = by_id.get(item["id"])
        if entry is None:
            problems.append((item["id"], "not in catalogue"))
            continue
        if entry["slot"] != item["slot"]:
            problems.append((item["id"], "slot drift"))
        image, boxes = generator.render_item(item)
        committed = os.path.join(LAUNCHER_BUNDLE, entry["texture"])
        with Image.open(committed) as disk:
            disk = disk.convert("RGBA")
            if disk.size != image.size:
                problems.append((item["id"], f"size drift {disk.size} vs {image.size}"))
            elif disk.tobytes() != image.tobytes():
                problems.append((item["id"], "art drift from the generator"))
        if boxes != entry["boxes"]:
            problems.append((item["id"], "box/UV drift from the generator"))
    check("committed art and geometry are the generator's output",
          not problems, str(problems[:4]))


# ---------------------------------------------------------------------------
# Java renderer vs Python preview
# ---------------------------------------------------------------------------

_HARNESS = r"""
import com.cubeon.client.cosmetics.CosmeticCatalog;
import com.cubeon.client.cosmetics.CosmeticGeometry;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;

public final class DumpCosmetics {
    public static void main(String[] args) throws Exception {
        String text = Files.readString(Path.of(args[0]), StandardCharsets.UTF_8);
        CosmeticCatalog.Catalog catalog = CosmeticCatalog.Catalog.parse(text);
        for (CosmeticCatalog.Item item : catalog.items()) {
            float anchor = catalog.anchorX(item.slot);
            for (CosmeticGeometry.Quad q : CosmeticGeometry.build(item, anchor)) {
                StringBuilder line = new StringBuilder(item.id);
                for (int i = 0; i < 4; i++) {
                    line.append('|').append(f(q.x[i])).append(',').append(f(q.y[i]))
                            .append(',').append(f(q.z[i]));
                }
                line.append('|').append(f(q.normalX)).append(',').append(f(q.normalY))
                        .append(',').append(f(q.normalZ));
                for (int i = 0; i < 4; i++) {
                    line.append('|').append(f(q.u[i])).append(',').append(f(q.v[i]));
                }
                System.out.println(line);
            }
        }
    }

    private static String f(float value) {
        return String.format(Locale.ROOT, "%.5f", value);
    }
}
"""


def _java_tool(name):
    tool = shutil.which(name)
    if not tool:
        return None
    try:
        version = subprocess.run([tool, "-version"], capture_output=True,
                                 text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (version.stderr or "") + (version.stdout or "")
    # JVM startup warnings can contain timestamps before the real version.
    match = re.search(r'(?:version\s+"|^javac\s+)(\d+)', text, re.MULTILINE)
    if version.returncode != 0 or not match:
        return None
    if int(match.group(1)) < 17:
        return None
    return tool


def _model_vertex(vertex):
    x, y, z = vertex
    return (round(x, 5), round(24 - y, 5), round(-z, 5))


def _model_corners(vertices):
    """The four model-space corners of a preview face.

    ``preview_faces`` returns three anchors (TL, TR, BL); the fourth is implied,
    exactly as the Java renderer implies it when it emits a quad cycle.
    """
    a, b, c = (_model_vertex(vertex) for vertex in vertices)
    d = (b[0] + c[0] - a[0], b[1] + c[1] - a[1], b[2] + c[2] - a[2])
    return tuple(sorted((a, b, c, d)))


def test_java_crosscheck():
    print("\n-- Java renderer vs Python preview --")
    javac = _java_tool("javac")
    java = _java_tool("java")
    if not javac or not java:
        skip("Java geometry cross-check", "no JDK 17+ on PATH")
        return

    scratch = tempfile.mkdtemp(prefix="cubeon-cosmetics-java-")
    try:
        harness = os.path.join(scratch, "DumpCosmetics.java")
        with open(harness, "w", encoding="utf-8") as fh:
            fh.write(_HARNESS)
        sources = [os.path.join(JAVA_SRC, "com", "cubeon", "client", "Json.java"),
                   os.path.join(JAVA_SRC, "com", "cubeon", "client", "cosmetics",
                                "CosmeticCatalog.java"),
                   os.path.join(JAVA_SRC, "com", "cubeon", "client", "cosmetics",
                                "CosmeticGeometry.java"),
                   harness]
        compile_run = subprocess.run([javac, "-d", scratch] + sources,
                                     capture_output=True, text=True, timeout=180)
        if compile_run.returncode != 0:
            check("Java cosmetics classes compile", False,
                  (compile_run.stderr or "")[-800:])
            return
        check("Java cosmetics classes compile", True)

        dump = subprocess.run(
            [java, "-cp", scratch, "DumpCosmetics",
             os.path.join(LAUNCHER_BUNDLE, "catalog.json")],
            capture_output=True, text=True, timeout=180)
        if dump.returncode != 0:
            check("Java geometry runs", False, (dump.stderr or "")[-800:])
            return
        check("Java geometry runs", True)

        quads = {}
        for line in dump.stdout.splitlines():
            parts = line.split("|")
            item_id = parts[0]
            corners = [tuple(round(float(v), 5) for v in part.split(","))
                       for part in parts[1:5]]
            normal = tuple(round(float(v), 5) for v in parts[5].split(","))
            uvs = [tuple(round(float(v), 5) for v in part.split(","))
                   for part in parts[6:10]]
            quads.setdefault(item_id, []).append({
                "key": tuple(sorted(corners)),
                "normal": normal,
                "corners": corners,
                "uvs": uvs,
            })

        problems = []
        for item_id, item_quads in quads.items():
            for quad in item_quads:
                # TL, TR, BR, BL: u is (u0, u1, u1, u0) and v is
                # (v0, v0, v1, v1), so the two columns and two rows repeat.
                if (quad["uvs"][0][0] != quad["uvs"][3][0]
                        or quad["uvs"][1][0] != quad["uvs"][2][0]
                        or quad["uvs"][0][1] != quad["uvs"][1][1]
                        or quad["uvs"][2][1] != quad["uvs"][3][1]):
                    problems.append((item_id, "UVs are not a rectangle"))
                p0, p1, p2, p3 = quad["corners"]
                # TL and BR are opposite corners, so BL = TL + BR - TR.
                implied = (p0[0] + p2[0] - p1[0], p0[1] + p2[1] - p1[1],
                           p0[2] + p2[2] - p1[2])
                if any(abs(a - b) > 1e-5 for a, b in zip(implied, p3)):
                    problems.append((item_id, "corners do not form a quad"))
        check("Java quads are well formed", not problems, str(problems[:4]))

        problems = []
        used = {item_id: set() for item_id in quads}
        for item in cosmetics.items():
            item_id = item["id"]
            sheet = cosmetics.texture(item)
            width, height = sheet.size
            item_quads = quads.get(item_id, [])
            for face_index, (vertices, normal, tile) in enumerate(
                    cosmetics.preview_faces(item)):
                key = _model_corners(vertices)
                model_normal = (round(normal[0], 5), round(-normal[1], 5),
                                round(-normal[2], 5))
                match = None
                for index, quad in enumerate(item_quads):
                    if index in used[item_id]:
                        continue
                    if quad["key"] != key or quad["normal"] != model_normal:
                        continue
                    us = [uv[0] for uv in quad["uvs"]]
                    vs = [uv[1] for uv in quad["uvs"]]
                    x0 = max(0, min(width, round(min(us) * width - 0.5)))
                    x1 = max(0, min(width, round(max(us) * width + 0.5)))
                    y0 = max(0, min(height, round(min(vs) * height - 0.5)))
                    y1 = max(0, min(height, round(max(vs) * height + 0.5)))
                    crop = sheet.crop((x0, y0, x1, y1))
                    if us[0] > us[1]:
                        crop = crop.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    if crop.size == tile.size and crop.tobytes() == tile.tobytes():
                        match = index
                        break
                if match is None:
                    problems.append((item_id, f"preview face {face_index} has no "
                                              "Java quad/tile"))
                else:
                    used[item_id].add(match)

            for index, quad in enumerate(item_quads):
                if index in used[item_id]:
                    continue
                us = [uv[0] for uv in quad["uvs"]]
                vs = [uv[1] for uv in quad["uvs"]]
                x0 = max(0, min(width, round(min(us) * width - 0.5)))
                x1 = max(0, min(width, round(max(us) * width + 0.5)))
                y0 = max(0, min(height, round(min(vs) * height - 0.5)))
                y1 = max(0, min(height, round(max(vs) * height + 0.5)))
                if sheet.crop((x0, y0, x1, y1)).getbbox() is not None:
                    problems.append((item_id, f"Java quad {index} draws something "
                                              "the preview does not"))
        check("Java and Python agree on every quad", not problems,
              str(problems[:4]))
        total = sum(len(value) for value in quads.values())
        check("the cross-check covered the whole catalogue",
              len(quads) == len(cosmetics.items()) and total > 0,
              f"{len(quads)} items, {total} quads")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    test_catalog()
    test_face_layout()
    test_preview_faces()
    test_wing_thickness()
    test_thumbnails()
    test_selection()
    test_bundles()
    test_generator_output()
    test_java_crosscheck()
    print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
