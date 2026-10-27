"""Textured Minecraft cuboids with an orthographic orbit camera."""
from dataclasses import dataclass
import math
import os

from PIL import Image, ImageChops, ImageEnhance, ImageMath

from cubeon import skins, capes, cosmetics


@dataclass
class Face:
    vertices: tuple
    normal: tuple
    texture: Image.Image


@dataclass
class ProjectedFace:
    index: int
    points: list
    vertices: list
    normal: tuple
    texture: Image.Image

    @property
    def depth(self):
        return (self.vertices[1][2] + self.vertices[2][2]) / 2

    @property
    def polygon(self):
        origin, horizontal, vertical = self.points
        return [origin, horizontal,
                (horizontal[0] + vertical[0] - origin[0], horizontal[1] + vertical[1] - origin[1]), vertical]

    def depth_at(self, point):
        origin, horizontal, vertical = self.points
        horizontal_x, horizontal_y = horizontal[0] - origin[0], horizontal[1] - origin[1]
        vertical_x, vertical_y = vertical[0] - origin[0], vertical[1] - origin[1]
        determinant = horizontal_x * vertical_y - vertical_x * horizontal_y
        delta_x, delta_y = point[0] - origin[0], point[1] - origin[1]
        across = (delta_x * vertical_y - delta_y * vertical_x) / determinant
        down = (horizontal_x * delta_y - horizontal_y * delta_x) / determinant
        return (self.vertices[0][2] + across * (self.vertices[1][2] - self.vertices[0][2])
                + down * (self.vertices[2][2] - self.vertices[0][2]))


def _box(sheet, origin, dimensions, bounds, inflate=0, mirrored=False, cape=False):
    atlas_x, atlas_y = origin
    width, height, depth = dimensions
    left, bottom, back, right, top, front = bounds
    left, bottom, back = left - inflate, bottom - inflate, back - inflate
    right, top, front = right + inflate, top + inflate, front + inflate
    surfaces = [
        (((left, top, front), (right, top, front), (left, bottom, front)), (0, 0, 1), (depth, depth, width, height)),
        (((right, top, back), (left, top, back), (right, bottom, back)), (0, 0, -1), (2 * depth + width, depth, width, height)),
        (((left, top, back), (left, top, front), (left, bottom, back)), (-1, 0, 0), (0, depth, depth, height)),
        (((right, top, front), (right, top, back), (right, bottom, front)), (1, 0, 0), (depth + width, depth, depth, height)),
        (((left, top, back), (right, top, back), (left, top, front)), (0, 1, 0), (depth, 0, width, depth)),
        (((left, bottom, front), (right, bottom, front), (left, bottom, back)), (0, -1, 0), (depth + width, 0, width, depth)),
    ]
    faces = []
    for vertices, normal, region in surfaces:
        texture_x, texture_y, texture_width, texture_height = region
        if cape and normal[2]:
            texture_x = depth if normal[2] < 0 else 2 * depth + width
        texture = sheet.crop((atlas_x + texture_x, atlas_y + texture_y,
                              atlas_x + texture_x + texture_width, atlas_y + texture_y + texture_height))
        if mirrored:
            texture = texture.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        faces.append(Face(vertices, normal, texture))
    return faces


class CharacterModel:
    def __init__(self, sheet, *, slim=False, cape=None, cosmetics_faces=()):
        sheet = sheet.convert("RGBA")
        legacy = sheet.height == 32
        arm_width = 3 if slim and not legacy else 4
        parts = [
            ((0, 0), (8, 8, 8), (-4, 24, -4, 4, 32, 4), (32, 0)),
            ((16, 16), (8, 12, 4), (-4, 12, -2, 4, 24, 2), (16, 32)),
            ((40, 16), (arm_width, 12, 4), (-4 - arm_width, 12, -2, -4, 24, 2), (40, 32)),
            ((40, 16) if legacy else (32, 48), (arm_width, 12, 4), (4, 12, -2, 4 + arm_width, 24, 2), (48, 48)),
            ((0, 16), (4, 12, 4), (-4, 0, -2, 0, 12, 2), (0, 32)),
            ((0, 16) if legacy else (16, 48), (4, 12, 4), (0, 0, -2, 4, 12, 2), (0, 48)),
        ]
        self.faces = []
        for index, (origin, dimensions, bounds, overlay) in enumerate(parts):
            mirrored = legacy and index in (3, 5)
            base_faces = _box(sheet, origin, dimensions, bounds, mirrored=mirrored)
            if not legacy or index == 0:
                overlay_faces = _box(sheet, overlay, dimensions, bounds)
                for base, outer in zip(base_faces, overlay_faces):
                    base.texture.alpha_composite(outer.texture)
            self.faces.extend(base_faces)
        if cape is not None:
            cape = cape.convert("RGBA").resize((64, 32), Image.Resampling.NEAREST)
            self.faces.extend(_box(cape, (0, 0), (10, 16, 1), (-5, 7, -3.5, 5, 23, -2.5), cape=True))
        for vertices, normal, texture in cosmetics_faces:
            self.faces.append(Face(vertices, normal, texture))

    @classmethod
    def from_config(cls, cfg, default_cape_path=None, cosmetics_dir=None):
        sheet = skins.compose_skin(cfg)
        slim = False
        if cfg.get("active_skin"):
            entry = next((entry for entry in skins.list_custom_skins() if entry.get("filename") == cfg["active_skin"]), {})
            slim = entry.get("model") == "slim" or (entry.get("model") != "classic" and skins._detect_slim_model(sheet))
        cape_path = capes.get_custom_cape_path(cfg["active_cape"]) if cfg.get("active_cape") else default_cape_path
        cape = None
        if cape_path and os.path.isfile(cape_path):
            with Image.open(cape_path) as source:
                cape = source.convert("RGBA")
        worn = []
        for key in ("active_back_item", "active_shoulder_item"):
            item = cosmetics.get(cfg.get(key), cosmetics_dir)
            if item is not None:
                worn.extend(cosmetics.preview_faces(item, cosmetics_dir))
        return cls(sheet, slim=slim, cape=cape, cosmetics_faces=worn)

    def project(self, yaw=25, pitch=10, size=(320, 440)):
        yaw, pitch = math.radians(yaw), math.radians(pitch)
        yaw_cos, yaw_sin = math.cos(yaw), math.sin(yaw)
        pitch_cos, pitch_sin = math.cos(pitch), math.sin(pitch)
        scale = min(size[0] / 24, size[1] / 40)

        def rotate(vertex, centered=True):
            horizontal, vertical, depth = vertex
            if centered:
                vertical -= 16
            camera_x = horizontal * yaw_cos + depth * yaw_sin
            camera_depth = -horizontal * yaw_sin + depth * yaw_cos
            return (camera_x, vertical * pitch_cos - camera_depth * pitch_sin,
                    vertical * pitch_sin + camera_depth * pitch_cos)

        visible = []
        for index, face in enumerate(self.faces):
            normal = rotate(face.normal, centered=False)
            if normal[2] <= 0.001 or not face.texture.getbbox():
                continue
            vertices = [rotate(vertex) for vertex in face.vertices]
            projected = [(size[0] / 2 + vertex[0] * scale, size[1] / 2 - vertex[1] * scale) for vertex in vertices]
            visible.append(ProjectedFace(index, projected, vertices, normal, face.texture))
        return visible

    def render(self, yaw=25, pitch=10, size=(320, 440)):
        canvas = Image.new("RGBA", size)
        depth_buffer = Image.new("F", size, -100000)
        for face in sorted(self.project(yaw, pitch, size), key=lambda face: face.depth):
            projected, texture, normal, vertices = face.points, face.texture, face.normal, face.vertices
            origin, horizontal, vertical = projected
            horizontal_x, horizontal_y = horizontal[0] - origin[0], horizontal[1] - origin[1]
            vertical_x, vertical_y = vertical[0] - origin[0], vertical[1] - origin[1]
            determinant = horizontal_x * vertical_y - vertical_x * horizontal_y
            if abs(determinant) < 0.01:
                continue
            fourth = (horizontal[0] + vertical[0] - origin[0], horizontal[1] + vertical[1] - origin[1])
            corners = [origin, horizontal, vertical, fourth]
            left = max(0, math.floor(min(point[0] for point in corners)))
            top = max(0, math.floor(min(point[1] for point in corners)))
            right = min(size[0], math.ceil(max(point[0] for point in corners)))
            bottom = min(size[1], math.ceil(max(point[1] for point in corners)))
            if right <= left or bottom <= top:
                continue
            inverse_x = texture.width * vertical_y / determinant
            inverse_y = -texture.width * vertical_x / determinant
            inverse_vertical_x = -texture.height * horizontal_y / determinant
            inverse_vertical_y = texture.height * horizontal_x / determinant
            transform = (inverse_x, inverse_y, inverse_x * (left - origin[0]) + inverse_y * (top - origin[1]),
                         inverse_vertical_x, inverse_vertical_y,
                         inverse_vertical_x * (left - origin[0]) + inverse_vertical_y * (top - origin[1]))
            lighting = 0.72 + 0.28 * max(0, normal[1] * 0.5 + normal[2] * 0.8)
            shaded = ImageEnhance.Brightness(texture).enhance(lighting)
            tile = shaded.transform((right - left, bottom - top), Image.Transform.AFFINE,
                                    transform, resample=Image.Resampling.NEAREST)
            horizontal_depth = vertices[1][2] - vertices[0][2]
            vertical_depth = vertices[2][2] - vertices[0][2]
            depth_x = (vertical_y * horizontal_depth - horizontal_y * vertical_depth) / determinant
            depth_y = (horizontal_x * vertical_depth - vertical_x * horizontal_depth) / determinant
            depth_origin = vertices[0][2] + depth_x * (left + 0.5 - origin[0]) + depth_y * (top + 0.5 - origin[1])
            coordinates_x = Image.new("F", (right - left, 1))
            coordinates_x.putdata(range(right - left))
            coordinates_y = Image.new("F", (1, bottom - top))
            coordinates_y.putdata(range(bottom - top))
            candidate_depth = ImageMath.lambda_eval(
                lambda values: values["horizontal"] * depth_x + values["vertical"] * depth_y + depth_origin,
                horizontal=coordinates_x.resize(tile.size, Image.Resampling.NEAREST),
                vertical=coordinates_y.resize(tile.size, Image.Resampling.NEAREST))
            alpha = tile.getchannel("A")
            stored_depth = depth_buffer.crop((left, top, right, bottom))
            visible_pixels = ImageMath.lambda_eval(
                lambda values: (values["candidate"] > values["stored"]) * (values["alpha"] > 0) * 255,
                candidate=candidate_depth, stored=stored_depth, alpha=alpha).convert("L")
            tile.putalpha(ImageChops.multiply(alpha, visible_pixels))
            canvas.alpha_composite(tile, (left, top))
            opaque_pixels = ImageMath.lambda_eval(
                lambda values: (values["alpha"] == 255) * (values["visible"] > 0) * 255,
                alpha=alpha, visible=visible_pixels).convert("L")
            depth_buffer.paste(candidate_depth, (left, top), opaque_pixels)
        return canvas
