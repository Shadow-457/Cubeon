"""Offline camera, per-pixel occlusion, and preview frame lifecycle checks."""
import inspect
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sandbox_home
_sandbox_home.isolate()

import flet as ft
import msgpack
from flet.controls.base_control import BaseControl
from flet.controls.object_patch import ObjectPatch
from flet.messaging.protocol import configure_encode_object_for_msgpack
from PIL import Image, ImageChops
from cubeon import skins
from cubeon import cosmetics
from cubeon.appearance import CharacterModel, Face
from cubeon.appearance_scene import order_faces, _intersection, _area
from ui.appearance_preview import AppearancePreview, render_frame
from ui.settings_tab import SECTIONS
from _fuzz_common import every_control, walk
import app_driver

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'}   {label}")


model = CharacterModel(skins.default_base_skin())
frames = [model.render(yaw, pitch) for yaw, pitch in ((0, 0), (45, 10), (90, 0), (180, 0), (270, 0), (45, 75), (45, -75))]
check("the default character has real geometry from every direction", all(frame.getbbox() for frame in frames))
check("side and rear views keep both legs, not an empty skin sheet", all(frame.getbbox()[3] > 380 for frame in frames[:5]))
check("the rear uses different texture faces, not a mirrored front image",
      frames[3].tobytes() != frames[0].transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()
      and len({frame.tobytes() for frame in frames}) >= 5)
check("all camera frames stay bounded and transparent", all(frame.size == (320, 440) and frame.mode == "RGBA" for frame in frames))
slim = CharacterModel(skins.default_base_skin(), slim=True).render(0, 0)
check("slim skins use narrower arm geometry", slim.getbbox()[2] - slim.getbbox()[0] < frames[0].getbbox()[2] - frames[0].getbbox()[0])
legacy = CharacterModel(skins.default_base_skin().crop((0, 0, 64, 32))).render(180, 0)
check("legacy 64x32 skins have a complete rear view", legacy.getbbox()[3] > 380)

wing_item = cosmetics.get("back_ember_wings")
giant = CharacterModel(skins.default_base_skin(), cosmetics_faces=cosmetics.preview_faces(wing_item))
giant_frames = [giant.render(yaw, pitch) for yaw, pitch in
                ((0, 10), (45, 10), (90, 10), (180, 10), (270, 10), (45, 75), (45, -75))]
check("giant V3 wings fit inside the preview throughout the orbit",
      all(frame.getbbox() and min(frame.getbbox()[:2]) >= 10
          and frame.getbbox()[2] <= 310 and frame.getbbox()[3] <= 430 for frame in giant_frames))
scales = []
for yaw in range(0, 360, 30):
    face = next(face for face in giant.project(yaw, 10)
                if abs(face.vertices[2][1] - face.vertices[0][1]) > 1)
    scales.append(round(abs((face.points[2][1] - face.points[0][1])
                            / (face.vertices[2][1] - face.vertices[0][1])), 6))
check("turning giant wings keeps one fixed camera scale", len(set(scales)) == 1)

# The outer atlas must remain separate from the base and have texel walls,
# including around holes. These use the real turntable rasteriser.
layer_sheet = skins.default_base_skin()
for y in range(64):
    for x in range(64):
        if layer_sheet.getpixel((x, y))[3]:
            layer_sheet.putpixel((x, y), (20, 40, 240, 255))
bare_sheet = layer_sheet.copy()
for x, y in ((41, 11), (21, 39), (45, 39), (53, 55), (5, 39), (5, 55)):
    layer_sheet.putpixel((x, y), (240, 40, 20, 255))
source_bytes = layer_sheet.tobytes()
layer_model = CharacterModel(layer_sheet)
layer_textures = {i: face.texture for i, face in enumerate(layer_model.faces)}
layer_frame = render_frame(layer_model.project(0, 0), layer_textures, supersample=1)
for label, point in (("hat", (129, 82)), ("jacket", (129, 168)),
                     ("right sleeve", (87, 168)), ("left sleeve", (219, 168)),
                     ("right trouser", (131, 300)), ("left trouser", (175, 300))):
    red, green, blue, alpha = layer_frame.getpixel(point)
    check(f"the raised {label} samples its own outer-layer atlas", red > 180 and blue < 40 and alpha == 255)
check("constructing the voxel model preserves the original skin sheet", layer_sheet.tobytes() == source_bytes)
base_front = next(face for face in layer_model.faces
                  if face.normal == (0, 0, 1) and face.vertices[0] == (-4, 32, 4))
check("the base texture retains its pixels underneath the raised hat",
      base_front.texture.tobytes() == bare_sheet.crop((8, 8, 16, 16)).tobytes())
red, green, blue, alpha = layer_frame.getpixel((143, 82))
check("a transparent outer texel exposes the opaque base", blue > 180 and red < 40 and alpha == 255)

edge_sheet = bare_sheet.copy()
edge_sheet.putpixel((40, 11), (240, 40, 20, 255))
edge_model = CharacterModel(edge_sheet)
edge_frame = render_frame(edge_model.project(0, 0), {i: f.texture for i, f in enumerate(edge_model.faces)}, 1)
check("a raised edge texel protrudes beyond the base silhouette",
      edge_frame.getpixel((112, 82))[0] > 180 and CharacterModel(bare_sheet).render(0, 0).getpixel((112, 82))[3] == 0)
relief_frame = edge_model.render(35, 10)
relief_reds = {red for count, (red, green, blue, alpha) in relief_frame.getcolors(320 * 440)
              if red > 100 and green < 50 and blue < 50 and alpha == 255}
check("turning reveals shaded side walls on individual skin pixels", len(relief_reds) >= 2)
check("empty outer layers add no geometry", len(CharacterModel(bare_sheet).faces) == 36)
check("fully opaque layers merge their caps and hide internal voxel walls",
      len(CharacterModel(Image.new("RGBA", (64, 64), "white")).faces) == 72)

slim_layers = CharacterModel(layer_sheet, slim=True)
slim_layer_frame = render_frame(slim_layers.project(0, 0), {i: f.texture for i, f in enumerate(slim_layers.faces)}, 1)
check("both Alex sleeves retain their outer pixels on three-pixel arms",
      all(slim_layer_frame.getpixel(point)[0] > 180 for point in ((99, 168), (221, 168))))
legacy_layers = CharacterModel(layer_sheet.crop((0, 0, 64, 32)))
legacy_layer_frame = render_frame(legacy_layers.project(0, 0), {i: f.texture for i, f in enumerate(legacy_layers.faces)}, 1)
check("legacy skins extrude the hat without inventing jacket or sleeve layers",
      legacy_layer_frame.getpixel((129, 82))[0] > 180
      and legacy_layer_frame.getpixel((129, 168))[2] > 180
      and len(legacy_layers.faces) == len(edge_model.faces))

# Cape "None" hides the shared Cubeon cape in the preview too, so the 3D box
# and the game agree (offline shows vanilla Steve/Alex with no cape).
import tempfile
with tempfile.TemporaryDirectory() as _cape_dir:
    _default_cape = os.path.join(_cape_dir, "cubeon-cape.png")
    Image.new("RGBA", (64, 32), (0, 0, 0, 0)).save(_default_cape)
    _bare = CharacterModel(skins.default_base_skin())
    _shown = CharacterModel.from_config(
        {"username": "tester"}, default_cape_path=_default_cape)
    _hidden = CharacterModel.from_config(
        {"username": "tester", "hide_cubeon_cape": True},
        default_cape_path=_default_cape)
    check("the shared cape is in the preview by default",
          len(_shown.faces) == len(_bare.faces) + 6)
    check("Cape None removes the shared cape from the preview",
          len(_hidden.faces) == len(_bare.faces))

crossing = CharacterModel(skins.default_base_skin())
crossing.faces = [
    Face(((-4, 20, -3), (4, 20, 3), (-4, 12, -3)), (0, 0, 1), Image.new("RGBA", (8, 8), "red")),
    Face(((-4, 20, 0), (4, 20, 0), (-4, 12, 0)), (0, 0, 1), Image.new("RGBA", (8, 8), "blue")),
]
depth_frame = crossing.render(0, 0)
check("crossing surfaces depth-test each pixel, not each whole face",
      depth_frame.getpixel((138, 220))[2] > 200 and depth_frame.getpixel((182, 220))[0] > 200)
crossing.faces.reverse()
check("opaque occlusion is independent of face submission order", crossing.render(0, 0).tobytes() == depth_frame.tobytes())
live_crossing = render_frame(crossing.project(0, 0), {i: f.texture for i, f in enumerate(crossing.faces)}, 1)
check("cached turntable frames also depth-test crossing surfaces per pixel", live_crossing.tobytes() == depth_frame.tobytes())

transparent_model = CharacterModel(bare_sheet)
transparent_model.faces = [
    Face(((-4, 20, 3), (4, 20, 3), (-4, 12, 3)), (0, 0, 1), Image.new("RGBA", (8, 8), (240, 0, 0, 128))),
    Face(((-4, 20, 0), (4, 20, 0), (-4, 12, 0)), (0, 0, 1), Image.new("RGBA", (8, 8), (0, 0, 240, 255))),
    Face(((-4, 20, -3), (4, 20, -3), (-4, 12, -3)), (0, 0, 1), Image.new("RGBA", (8, 8), (0, 240, 0, 128))),
]
transparent_frame = render_frame(transparent_model.project(0, 0), {i: f.texture for i, f in enumerate(transparent_model.faces)}, 1)
red, green, blue, alpha = transparent_frame.getpixel((160, 220))
check("translucent outer pixels blend over the base and hide rear layers",
      90 < red < 120 and green == 0 and 90 < blue < 120 and alpha == 255)
transparent_model.faces.reverse()
check("translucent skin blending is independent of face submission order",
      transparent_model.render(0, 0).tobytes() == transparent_frame.tobytes())

cape_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "capes", "cubeon_cape.png")
with Image.open(cape_path) as source:
    cape_model = CharacterModel(skins.default_base_skin(), cape=source)
cape_front = cape_model.render(0, 0)
difference = ImageChops.difference(frames[0].convert("RGB"), cape_front.convert("RGB"))
masked_difference = ImageChops.multiply(difference, frames[0].getchannel("A").convert("RGB"))
check("the cape cannot paint through the opaque front of the character", masked_difference.getbbox() is None)
check("the cape is visible on the character's back", cape_model.render(180, 0).getpixel((160, 220)) != frames[3].getpixel((160, 220)))

def correct_native_order(yaw, pitch):
    ordered = order_faces(cape_model.project(yaw, pitch))
    for first_index, first in enumerate(ordered):
        for second in ordered[first_index + 1:]:
            overlap = _intersection(first.polygon, second.polygon)
            if len(overlap) >= 3 and abs(_area(overlap)) > 0.01:
                if any(first.depth_at(point) - second.depth_at(point) > 1e-4 for point in overlap):
                    return False
    return True


check("native face ordering keeps the cape outside the body across the orbit",
      all(correct_native_order(yaw, pitch) for yaw in range(0, 360, 15) for pitch in (-60, -20, 0, 20, 60)))

stage = AppearancePreview({"active_skin": "older.png"})
check("rotation uses one stable scene without drag handlers",
      stage.gesture.content is stage.scene and type(stage.gesture).__name__ == "Container")
jobs, loads, paints = [], [], []


class QueuedThread:
    def __init__(self, target, args=(), **kwargs):
        self.target = lambda: target(*args)

    def start(self):
        jobs.append(self.target)


class InlinePool:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def map(self, fn, values):
        return map(fn, values)


def load_model(cfg, default_cape_path, cosmetics_dir=None):
    loads.append(dict(cfg))
    if cfg.get("active_skin") == "older.png":
        stage.cfg["active_skin"] = "newest.png"
        stage.refresh(invalidate=True)
        stage.turn(30)
    return CharacterModel(skins.default_base_skin())


# Camera/mesh geometry is checked above. These fixtures focus on lifecycle
# and the real Flet patch size without rasterising sixty full-size images.
with patch("ui.appearance_preview.threading.Thread", QueuedThread), \
     patch("ui.appearance_preview.ThreadPoolExecutor", InlinePool), \
     patch("ui.appearance_preview.render_frame", return_value=Image.new("RGBA", (320, 440), "white")), \
     patch.object(CharacterModel, "from_config", side_effect=load_model), \
     patch("ui.appearance_preview.thread_safe_ui.refresh", side_effect=paints.append):
    stage.refresh(invalidate=True)
    check("loading starts one background asset worker", len(jobs) == 1)
    jobs.pop(0)()
    check("a stale asset load never replaces the selected skin",
          len(loads) == 2 and loads[-1]["active_skin"] == "newest.png" and len(stage._frames) == 60)
    check("the asset worker exits once frames are ready", not stage._running)
    textures = tuple((id(frame.content), frame.content.src) for frame in stage._frames)
    stage.turn(30)
    jobs.pop(0)()
    check("the rotation button changes the camera", stage.yaw == 85)
    stage.reset()
    jobs.pop(0)()
    check("reset restores the camera without remounting the scene",
          stage.yaw == 25 and stage.pitch == 10 and stage.gesture.content is stage.scene)
    encode = configure_encode_object_for_msgpack(BaseControl)
    initial, _added, _removed = ObjectPatch.from_diff(None, stage.scene, BaseControl)
    msgpack.packb(initial.to_message(), default=encode)
    patch_sizes = []
    for angle in (0, 30, 90, 180, 270, 330):
        stage._set_yaw(angle)
        changes, added, removed = ObjectPatch.from_diff(stage.scene, stage.scene, BaseControl)
        encoded = msgpack.packb(changes.to_message(), default=encode)
        patch_sizes.append(len(encoded))
        check(f"orbit {angle}: frame opacity changes reach the client", len(encoded) > 3 and b"opacity" in encoded)
        check(f"orbit {angle}: cached frames never remount", not added and not removed)
        check(f"orbit {angle}: no image source retransmits", b"src" not in encoded)
    check("rotation keeps every cached image and starts no asset workers",
          not jobs and textures == tuple((id(frame.content), frame.content.src) for frame in stage._frames))
    check("rotation patches remain small", max(patch_sizes) < 20000)

driver = app_driver.build_headless()
driver.open_tab("profile")
switch = inspect.getclosurevars(driver.tabs()["profile"].on_click).nonlocals["switch_tab"]
cosmetics_root = inspect.getclosurevars(switch).nonlocals["_tab_views"]["profile"]
controls = list(walk(cosmetics_root))
check("Cosmetics mounts exactly one character preview", sum(control.data == "appearance-orbit" for control in controls) == 1)
check("Cosmetics keeps Skin and Cape, not Images", not any(getattr(control, "value", None) == "Images" for control in controls))
check("Cosmetics offers rotation buttons without drag gestures",
      any(getattr(c, "tooltip", None) == "Rotate left" for c in controls)
      and any(getattr(c, "tooltip", None) == "Rotate right" for c in controls)
      and not any(type(c).__name__ == "GestureDetector" for c in controls))
check("Cosmetics has no global arm dropdown or separate Apply button",
      not any(getattr(c, "label", None) == "Arm model" for c in controls)
      and not any(getattr(c, "value", None) == "Apply model to active skin" for c in controls))
driver.open_tab("settings")
settings = next(control for control in every_control(driver.page) if callable(getattr(control, "select_section", None)))
panes = inspect.getclosurevars(settings.select_section).nonlocals["panes"]
check("Settings initially shows one section, not screenshots",
      not panes["images"].visible and sum(bool(pane.visible) for pane in panes.values()) == 1)
check("Screenshots has its own Settings section", any(key == "images" and label == "Screenshots" for key, icon, label in SECTIONS))
settings.select_section("images")
check("Settings owns the screenshot gallery", panes["images"].visible and all(not pane.visible for key, pane in panes.items() if key != "images"))
settings.select_section("memory")
check("leaving Screenshots hides the gallery", panes["memory"].visible and all(not pane.visible for key, pane in panes.items() if key != "memory"))
driver.open_tab("play")
driver.open_tab("settings")
check("returning to Settings keeps the selected section without showing screenshots", panes["memory"].visible and not panes["images"].visible)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
