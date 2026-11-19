#!/usr/bin/env python3
"""Refresh public, high-resolution previews from the validated owner folder.

No database writes. Existing API thumbnails keep new uploads discoverable
without a deployment; these larger images are pinned to each package checksum.
"""
import argparse
import base64
import html
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from cubeon import appearance, cosmetic_packages, cosmetics

KINDS = {"wing": "Wings", "pet": "Pets", "head": "Headwear", "feet": "Footwear", "cape": "Capes"}


def preview(values):
    if len(values) == 8:
        with Image.open(io.BytesIO(base64.b64decode(values[7]))) as source:
            image = source.convert("RGBA")
            image.thumbnail((240, 380), Image.Resampling.NEAREST)
            result = Image.new("RGBA", (420, 420))
            result.alpha_composite(image, ((420 - image.width) // 2, (420 - image.height) // 2))
            return result
    package = json.loads(base64.b64decode(values[4]))
    item = package["item"]
    with tempfile.TemporaryDirectory() as temporary:
        for name, data in cosmetic_packages.validate(package).items():
            (Path(temporary) / name).write_bytes(data)
        model = appearance.CharacterModel(Image.open(ROOT / "assets/skins/steve.png"))
        if item["slot"] == "head":
            model.faces = [face for face in model.faces if min(v[1] for v in face.vertices) >= 23.5
                           and max(v[1] for v in face.vertices) > 24]
        elif item["slot"] == "feet":
            model.faces = [face for face in model.faces if max(v[1] for v in face.vertices) <= 12.5]
        elif item["slot"] == "shoulder":
            model.faces = [face for face in model.faces if min(v[1] for v in face.vertices) >= 11.5]
        for emission in (False, True):
            model.faces.extend(appearance.Face(vertices, normal, texture) for vertices, normal, texture
                               in cosmetics.preview_faces(item, temporary, emissive=emission))
        vertices = [v for face in model.faces for v in face.vertices]
        model._orbit_radius = max(math.hypot(x, z) for x, y, z in vertices)
        model._vertical_extent = max(abs(y - 16) for x, y, z in vertices)
        image = model.render(yaw=155 if item["slot"] == "back" else 25, pitch=8, size=(640, 700))
        image = image.crop(image.getbbox())
        image.thumbnail((396, 396), Image.Resampling.NEAREST)
        result = Image.new("RGBA", (420, 420))
        result.alpha_composite(image, ((420 - image.width) // 2, (420 - image.height) // 2))
        return result


def generate(folder):
    spec = importlib.util.spec_from_file_location("owner_cosmetics", ROOT / "worker/manage-cosmetics.py")
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    values = publisher.prepare_folder(folder)
    output = ROOT / "web/assets/store"
    output.mkdir(parents=True, exist_ok=True)
    cards = []
    for entry in sorted(values, key=lambda value: value[1]):
        item_id, name, description = entry[:3]
        sha = entry[6]
        kind = entry[8] if len(entry) == 9 else "cape"
        filename = item_id + "-" + sha[:12] + ".webp"
        preview(entry).save(output / filename, lossless=True, method=6)
        safe = {key: html.escape(value, quote=True) for key, value in
                {"id": item_id, "name": name, "description": description}.items()}
        cards.append(f'''      <article class="store-card" data-id="{safe['id']}" data-sha="{sha}" data-kind="{kind}" data-name="{safe['name']}" data-description="{safe['description']}">
        <img src="/assets/store/{filename}" width="420" height="420" loading="lazy" decoding="async" alt="{safe['name']} on a Minecraft character">
        <div class="store-card-info">
          <span class="store-kind">{KINDS[kind]}</span>
          <h2>{safe['name']}</h2>
          <p>{safe['description']}</p>
          <div class="store-card-bottom"><span class="store-free">Free</span><button class="store-view" type="button" aria-label="View {safe['name']}">View cosmetic</button></div>
        </div>
      </article>''')
    page = ROOT / "web/store.html"
    source = page.read_text()
    before, rest = source.split("<!-- STORE CARDS START -->", 1)
    _, after = rest.split("<!-- STORE CARDS END -->", 1)
    page.write_text(before + "<!-- STORE CARDS START -->\n" + "\n".join(cards) +
                    "\n      <!-- STORE CARDS END -->" + after)
    print(f"Prepared {len(cards)} checksum-pinned Store previews. No uploads.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=ROOT / "cosmetics")
    generate(parser.parse_args().folder)
