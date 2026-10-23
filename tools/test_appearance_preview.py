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
from cubeon.appearance import CharacterModel, Face
from cubeon.appearance_scene import order_faces, _intersection, _area
from ui.appearance_preview import AppearancePreview
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
check("orbit uses one stable native scene", stage.gesture.content is stage.scene)
jobs, loads, paints = [], [], []


class QueuedThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        jobs.append(self.target)


def load_model(cfg, default_cape_path):
    loads.append(dict(cfg))
    if cfg.get("active_skin") == "older.png":
        stage.cfg["active_skin"] = "newest.png"
        stage.refresh(invalidate=True)
        stage.turn(30)
    loaded = CharacterModel(skins.default_base_skin())
    loaded.fixture_name = cfg.get("active_skin")
    return loaded


with patch("ui.appearance_preview.threading.Thread", QueuedThread), \
     patch.object(CharacterModel, "from_config", side_effect=load_model), \
     patch("ui.appearance_preview.thread_safe_ui.refresh", side_effect=paints.append):
    stage.refresh(invalidate=True)
    check("loading starts one background asset worker", len(jobs) == 1)
    jobs.pop(0)()
    check("a stale asset load never replaces the selected skin", stage._model.fixture_name == "newest.png")
    check("queued asset and drag requests do not spawn frame workers", not jobs and len(loads) == 2)
    check("only the newest loaded mesh repaints", paints.count(stage.scene) == 1)
    check("the asset worker exits once the mesh is ready", not stage._running)
    textures = [plane.content for plane in stage._mesh.values()]
    check("all textures stay mounted and use gapless playback", all(texture.gapless_playback for texture in textures) and all(plane.visible for plane in stage._mesh.values()))
    prior_loads = len(loads)
    stage.refresh(invalidate=True)
    jobs.pop(0)()
    check("changing the arm model reloads geometry", len(loads) == prior_loads + 1)
    textures = tuple((id(plane.content), plane.content.src) for plane in stage._mesh.values())
    stage.gesture.on_pan_update(ft.DragUpdateEvent(name="pan_update", control=stage.gesture,
        local_position=ft.Offset(0, 0), global_position=ft.Offset(0, 0), local_delta=ft.Offset(20, 1000)))
    check("real drag payloads rotate horizontally and clamp vertical tilt", stage.yaw == 69 and stage.pitch == 75)
    stage.reset()
    check("reset returns to the initial camera without remounting the scene", stage.yaw == 25 and stage.pitch == 10 and stage.gesture.content is stage.scene)
    encode = configure_encode_object_for_msgpack(BaseControl)
    initial, _added, _removed = ObjectPatch.from_diff(None, stage.scene, BaseControl)
    msgpack.packb(initial.to_message(), default=encode)
    patch_sizes = []
    for angle in (0, 30, 90, 180, 270, 330):
        stage.yaw = angle
        stage.refresh()
        changes, added, removed = ObjectPatch.from_diff(stage.scene, stage.scene, BaseControl)
        encoded = msgpack.packb(changes.to_message(), default=encode)
        patch_sizes.append(len(encoded))
        check(f"orbit {angle}: real transform changes reach the client", len(encoded) > 3 and b"transform" in encoded)
        check(f"orbit {angle}: cached textures and planes never remount", not added and not removed)
        check(f"orbit {angle}: no PNG/image source retransmits", b"src" not in encoded)
    check("dragging neither rebuilds textures nor queues PNG frames",
          not jobs and textures == tuple((id(plane.content), plane.content.src) for plane in stage._mesh.values()))
    check("native transform patches remain small", max(patch_sizes) < 20000)
    print(f"  largest native orbit patch: {max(patch_sizes):,} bytes")

driver = app_driver.build_headless()
driver.open_tab("profile")
switch = inspect.getclosurevars(driver.tabs()["profile"].on_click).nonlocals["switch_tab"]
cosmetics_root = inspect.getclosurevars(switch).nonlocals["_tab_views"]["profile"]
controls = list(walk(cosmetics_root))
check("Cosmetics mounts exactly one draggable 3D character", sum(control.data == "appearance-orbit" for control in controls) == 1)
check("Cosmetics keeps Skin and Cape, not Images", not any(getattr(control, "value", None) == "Images" for control in controls))
driver.open_tab("settings")
settings = next(control for control in every_control(driver.page) if callable(getattr(control, "select_section", None)))
settings.select_section("images")
panes = inspect.getclosurevars(settings.select_section).nonlocals["panes"]
check("Settings owns the screenshot gallery", panes["images"].visible and all(not pane.visible for key, pane in panes.items() if key != "images"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
