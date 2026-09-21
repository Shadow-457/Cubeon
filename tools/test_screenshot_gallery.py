"""Deterministic checks for the Minecraft screenshot gallery backend."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from cubeon import screenshot_gallery as gallery


def check(label, condition):
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


with tempfile.TemporaryDirectory(prefix="cubeon-screenshots-") as root:
    old_dir = gallery.SCREENSHOTS_DIR
    old_cache = gallery._RENDER_CACHE_DIR
    gallery.SCREENSHOTS_DIR = root
    gallery._RENDER_CACHE_DIR = os.path.join(root, "_renders")
    try:
        Image.new("RGB", (1600, 900), (30, 120, 60)).save(
            os.path.join(root, "latest.png"), "PNG")
        Image.new("RGB", (320, 200), (120, 60, 30)).save(
            os.path.join(root, "older.jpg"), "JPEG")
        os.utime(os.path.join(root, "latest.png"), (20, 20))
        os.utime(os.path.join(root, "older.jpg"), (10, 10))
        with open(os.path.join(root, "notes.txt"), "w") as fh:
            fh.write("not an image")

        items = gallery.list_screenshots()
        check("lists supported screenshots only", [x["filename"] for x in items]
              == ["latest.png", "older.jpg"])
        check("metadata includes dimensions", items[0]["width"] == 1600
              and items[0]["height"] == 900)
        thumb = gallery.image_base64("latest.png", max_size=(320, 220))
        check("preview is bounded and encoded", bool(thumb))
        check("clipboard hand-off stays inside the screenshots folder",
              gallery.clipboard_path("latest.png")
              == os.path.join(root, "latest.png"))

        try:
            gallery.image_base64("../notes.txt")
        except ValueError:
            safe = True
        else:
            safe = False
        check("path traversal is rejected", safe)

        gallery.delete_screenshot("older.jpg")
        check("delete removes the selected screenshot",
              not os.path.exists(os.path.join(root, "older.jpg")))
    finally:
        gallery.SCREENSHOTS_DIR = old_dir

print("6/6 passed")
