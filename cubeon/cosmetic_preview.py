"""Cache coplanar preview fragments without changing downloaded game models."""
from collections import OrderedDict, defaultdict
import hashlib
import json
import math
import os
import threading

from PIL import Image

_CACHE = OrderedDict()
_LOCK = threading.Lock()
_MAX_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 6
_DENSITY = 18  # Above the texel density of the large-wing 640px settled viewport.


def clear_cache():
    with _LOCK:
        _CACHE.clear()


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _corners(vertices):
    p, q, r = vertices
    return (*vertices, tuple(q[i] + r[i] - p[i] for i in range(3)))


def compact_faces(faces, *, density=_DENSITY):
    """Bake opaque fragments on each actual plane, retaining its depth/normal.

    Sparse rectangles contain transparent texels, so preserve the original
    geometry bounds for camera fitting. Translucent fragments stay separate:
    they require the reference renderer's individual depth/blending order.
    """
    groups = defaultdict(list)
    for index, (vertices, normal, texture) in enumerate(faces):
        translucent = bool(texture.getchannel("A").point([0] + [255] * 254 + [0]).getbbox())
        key = (tuple(round(value, 7) for value in normal),
               round(_dot(normal, vertices[0]), 7),
               bool(texture.info.get("cubeon_emissive")),
               bool(texture.info.get("cubeon_preview_detail")))
        if translucent:
            key += (index,)
        groups[key].append((index, vertices, normal, texture))
    output = []
    for entries in groups.values():
        index, vertices, normal, texture = entries[0]
        original = [(i, (v, n, t)) for i, v, n, t in entries]
        if len(entries) < 2:
            output.extend(original)
            continue
        origin = vertices[0]
        across = tuple(vertices[1][i] - origin[i] for i in range(3))
        length = math.sqrt(_dot(across, across))
        if length < .000001:
            output.extend(original)
            continue
        across = tuple(value / length for value in across)
        down = (normal[1] * across[2] - normal[2] * across[1],
                normal[2] * across[0] - normal[0] * across[2],
                normal[0] * across[1] - normal[1] * across[0])
        placements = []
        source_vertices = []
        for _, vertices, _, tile in entries:
            corners = _corners(vertices)
            if any(abs(_dot(normal, tuple(v[i] - origin[i] for i in range(3)))) > .000001
                   for v in corners):
                break
            source_vertices.extend(corners)
            coords = [(_dot(tuple(v[i] - origin[i] for i in range(3)), across),
                       _dot(tuple(v[i] - origin[i] for i in range(3)), down)) for v in corners]
            placements.append((coords, tile))
        else:
            left = min(p[0] for coords, _ in placements for p in coords)
            top = min(p[1] for coords, _ in placements for p in coords)
            right = max(p[0] for coords, _ in placements for p in coords)
            bottom = max(p[1] for coords, _ in placements for p in coords)
            width, height = math.ceil((right - left) * density), math.ceil((bottom - top) * density)
            # Avoid sparse/untrusted geometry allocating an enormous plane.
            if 0 < width <= 1536 and 0 < height <= 1536 and width * height <= 1024 * 1024:
                canvas = Image.new("RGBA", (width, height))
                sx, sy = width / (right - left), height / (bottom - top)
                for coords, tile in placements:
                    points = [((x - left) * sx, (y - top) * sy) for x, y in coords]
                    p, q, r = points[:3]
                    x0, y0 = max(0, math.floor(min(x for x, y in points))), max(0, math.floor(min(y for x, y in points)))
                    x1, y1 = min(width, math.ceil(max(x for x, y in points))), min(height, math.ceil(max(y for x, y in points)))
                    ax, ay, bx, by = q[0] - p[0], q[1] - p[1], r[0] - p[0], r[1] - p[1]
                    determinant = ax * by - bx * ay
                    if abs(determinant) < .000001 or x1 <= x0 or y1 <= y0:
                        continue
                    a, b = tile.width * by / determinant, -tile.width * bx / determinant
                    c, d = -tile.height * ay / determinant, tile.height * ax / determinant
                    baked = tile.transform((x1 - x0, y1 - y0), Image.Transform.AFFINE,
                        (a, b, a * (x0 - p[0]) + b * (y0 - p[1]),
                         c, d, c * (x0 - p[0]) + d * (y0 - p[1])), Image.Resampling.NEAREST)
                    canvas.alpha_composite(baked, (x0, y0))
                canvas.info.update(texture.info)
                canvas.info["cubeon_preview_bounds"] = (
                    max(math.hypot(x, z) for x, y, z in source_vertices),
                    max(abs(y - 16) for x, y, z in source_vertices))

                def point(x, y):
                    return tuple(origin[i] + across[i] * x + down[i] * y for i in range(3))

                output.append((index, ((point(left, top), point(right, top), point(left, bottom)), normal, canvas)))
                continue
        output.extend(original)
    return [face for _, face in sorted(output)]


def prepared(item, directory, emissive):
    from . import cosmetics
    name = item.get("emissive_texture") if emissive else item["texture"]
    if not name:
        return []
    path = cosmetics.texture_path({**item, "texture": name}, directory)
    stat = os.stat(path)
    fingerprint = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).digest()
    key = (os.path.realpath(path), stat.st_mtime_ns, stat.st_size, fingerprint, emissive)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return list(_CACHE[key][0])
    faces = cosmetics.preview_faces(item, directory, emissive=emissive)
    # Fine feather edge walls return in the settled frame, as skin walls do.
    for _, normal, texture in faces:
        if abs(normal[2]) < .001:
            texture.info["cubeon_preview_detail"] = True
    result = compact_faces(faces)
    cost = sum(texture.width * texture.height * 4 for _, _, texture in result)
    if cost > _MAX_BYTES * .75:
        # Very layered wings need more planes. Keep both base/glow revisions
        # cacheable by lowering oversampling, never below the source's 6px/unit.
        density = max(6, int(_DENSITY * math.sqrt(_MAX_BYTES * .75 / cost)) // 6 * 6)
        del result
        result = compact_faces(faces, density=density)
        cost = sum(texture.width * texture.height * 4 for _, _, texture in result)
    with _LOCK:
        if cost <= _MAX_BYTES:
            _CACHE[key] = (tuple(result), cost)
            while len(_CACHE) > _MAX_ENTRIES or sum(entry[1] for entry in _CACHE.values()) > _MAX_BYTES:
                _CACHE.popitem(last=False)
    return result
