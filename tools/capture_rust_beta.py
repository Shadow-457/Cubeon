"""Paint and inspect the existing Rust installer under isolated launcher fixtures."""
import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
os.environ["CUBEON_UX_WIDTH"] = "1280"
os.environ["CUBEON_UX_HEIGHT"] = "720"
import ux_capture as ux
import flet as ft

OUT = ROOT / "archive/ui-captures/rust-beta"


async def inspect(page):
    stubs = ux._prepare(page, False)
    await stubs.app.main(page)
    await page.window.to_front()
    await asyncio.sleep(2)
    OUT.mkdir(parents=True, exist_ok=True)
    from ui.versions import VersionPicker
    from cubeon import rust_engine
    control = next(c for c in ux.every_control(page) if getattr(c, "tooltip", None) == "Pick a Minecraft version")
    picker = next(cell.cell_contents for cell in control.on_click.__closure__
                  if isinstance(cell.cell_contents, VersionPicker))
    nav = ux.discover_nav(page)

    async def capture(name):
        await asyncio.sleep(2)
        from PIL import ImageGrab
        screenshot = ImageGrab.grab(xdisplay=os.environ["DISPLAY"])
        screenshot.save(OUT / (name + ".png"))
        print(name, flush=True)

    picker.open()
    picker._browse()
    await capture("engine-choice")
    picker._set_install_loader("rust")
    picker._next()
    assert [e["id"] for e in picker._available_entries()] == ["26.3"]
    picker._pick("26.3")
    await capture("rust-26.3-only")
    picker.close()
    java_id = next(v["id"] for v in picker.get_instances() if not rust_engine.is_instance(v["id"]))
    picker.on_pick(rust_engine.INSTANCE_ID)
    assert nav["server_console"].disabled
    await capture("rust-servers-unavailable")
    picker.on_pick(java_id)
    assert not nav["server_console"].disabled
    await capture("java-servers-restored")


async def run(page):
    try:
        await inspect(page)
    finally:
        await page.window.close()


if __name__ == "__main__":
    ft.run(run, assets_dir=str(ROOT / "assets"))
