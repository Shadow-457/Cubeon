"""Generate antialiased UI masks and Cubeon's existing cube mark (Pillow)."""
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw
import json
import math

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "mod/src/main/resources/assets/cubeon-client/textures/ui"
ARMS = [(-4,-3,-10,-12,4,-3,8,5), (-4,-3,-11,-7,4,-3,10,-11),
        (-2,0,-8,4,4,0,10,4), (-4,-3,-8,5,4,-3,4,-10),
        (-4,-3,-11,-5,4,-3,11,-5), (-4,-3,-8,5,4,-3,14,-3),
        (-4,-3,0,-1,4,-3,0,-1), (-4,-3,1,-7,4,-3,2,3),
        (-4,-3,-7,6,4,-3,7,6), (-4,-3,-8,-14,4,-3,8,-14)]


def save(image, name):
    image.save(TARGET / name, optimize=True)
    (TARGET / (name + ".mcmeta")).write_text(json.dumps({"texture": {"blur": True, "clamp": True}}) + "\n")


def generate_rounded_rims():
    """One GUI-pixel ring for each corner radius, without filling the panel interior."""
    TARGET.mkdir(parents=True, exist_ok=True)
    atlas = Image.new("RGBA", (128 * 16, 128))
    for radius in range(1, 17):
        outer = Image.new("L", (512, 512))
        ImageDraw.Draw(outer).ellipse((0, 0, 511, 511), fill=255)
        inner = Image.new("L", outer.size)
        inset = 256 / radius
        if radius > 1:
            ImageDraw.Draw(inner).ellipse((inset, inset, 511 - inset, 511 - inset), fill=255)
        ring = Image.new("RGBA", outer.size, "white")
        ring.putalpha(ImageChops.subtract(outer, inner))
        atlas.paste(ring.resize((128, 128), Image.Resampling.LANCZOS), ((radius - 1) * 128, 0))
    save(atlas, "rounded-rims.png")


def generate_tool_icons():
    """Seven clean toolbar masks, rendered large and downsampled for a crisp 20px UI."""
    cell = 512
    atlas = Image.new("RGBA", (128 * 7, 128))

    def icon_canvas():
        image = Image.new("RGBA", (cell, cell))
        return image, ImageDraw.Draw(image)

    def p(value):
        return round(value * cell / 64)

    def round_line(draw, points, width=5):
        scaled = [(p(x), p(y)) for x, y in points]
        stroke = p(width)
        draw.line(scaled, fill="white", width=stroke, joint="curve")
        radius = stroke // 2
        for x, y in (scaled[0], scaled[-1]):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill="white")

    def paste(index, image):
        atlas.paste(image.resize((128, 128), Image.Resampling.LANCZOS), (index * 128, 0))

    # HUD settings: three compact sliders.
    image, draw = icon_canvas()
    for y, knob in ((18, 26), (32, 41), (46, 22)):
        round_line(draw, [(14, y), (50, y)], 4)
        draw.ellipse((p(knob-5), p(y-5), p(knob+5), p(y+5)), fill="white")
        draw.ellipse((p(knob-2), p(y-2), p(knob+2), p(y+2)), fill=(0, 0, 0, 0))
    paste(0, image)

    # Themes: painter's palette with three colour wells and a thumb hole.
    image, draw = icon_canvas()
    draw.ellipse((p(10), p(12), p(54), p(52)), outline="white", width=p(5))
    draw.ellipse((p(39), p(35), p(55), p(51)), fill=(0, 0, 0, 0))
    for x, y in ((23, 24), (34, 20), (19, 35)):
        draw.ellipse((p(x-3), p(y-3), p(x+3), p(y+3)), fill="white")
    paste(1, image)

    # Cosmetics: a simple coat hanger.
    image, draw = icon_canvas()
    round_line(draw, [(32, 20), (32, 16), (35, 12), (40, 12), (43, 15), (43, 19), (38, 24)], 4)
    round_line(draw, [(38, 24), (53, 43), (11, 43), (26, 25)], 5)
    paste(2, image)

    # Reset layout: circular arrow with a clear arrowhead.
    image, draw = icon_canvas()
    draw.arc((p(12), p(12), p(52), p(52)), start=38, end=330, fill="white", width=p(5))
    draw.polygon([(p(47), p(11)), (p(54), p(22)), (p(41), p(22))], fill="white")
    paste(3, image)

    # Emotes: outlined smile.
    image, draw = icon_canvas()
    draw.ellipse((p(11), p(11), p(53), p(53)), outline="white", width=p(5))
    for x in (24, 40):
        draw.ellipse((p(x-3), p(25-3), p(x+3), p(25+3)), fill="white")
    draw.arc((p(20), p(24), p(44), p(45)), start=0, end=180, fill="white", width=p(4))
    paste(4, image)

    # Friends / chat: two overlapping speech bubbles.
    image, draw = icon_canvas()
    draw.rounded_rectangle((p(10), p(13), p(42), p(37)), radius=p(7), outline="white", width=p(4))
    draw.polygon([(p(18), p(35)), (p(18), p(44)), (p(27), p(36))], fill="white")
    draw.rounded_rectangle((p(24), p(27), p(54), p(49)), radius=p(7), outline="white", width=p(4))
    draw.polygon([(p(44), p(47)), (p(49), p(55)), (p(50), p(46))], fill="white")
    paste(5, image)

    # Done / close: a balanced rounded X.
    image, draw = icon_canvas()
    round_line(draw, [(17, 17), (47, 47)], 5)
    round_line(draw, [(47, 17), (17, 47)], 5)
    paste(6, image)

    save(atlas, "tools.png")


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    size = 512
    rounded = Image.new("RGBA", (size, size))
    ImageDraw.Draw(rounded).ellipse((0, 0, size-1, size-1), fill="white")
    save(rounded.resize((128, 128), Image.Resampling.LANCZOS), "rounded.png")
    generate_rounded_rims()
    generate_tool_icons()
    icons = Image.new("RGBA", (128 * 11, 128))
    for pose, arms in enumerate(ARMS):
        icon = Image.new("RGBA", (512, 512))
        draw = ImageDraw.Draw(icon)
        def point(x, y):
            return 256 + x*12, 256 + y*12
        def line(x0, y0, x1, y1):
            draw.line([point(x0,y0), point(x1,y1)], fill="white", width=22)
            for x,y in [point(x0,y0),point(x1,y1)]:
                draw.ellipse((x-11,y-11,x+11,y+11), fill="white")
        hx,hy = (3,-5) if pose == 2 else (0,-10)
        x,y = point(hx,hy)
        draw.ellipse((x-30,y-30,x+30,y+30), fill="white")
        line(hx,hy+5,0,5)
        line(0,5,-5,7 if pose == 8 else 13)
        line(0,5,5,7 if pose == 8 else 13)
        if pose == 8:
            line(-5,7,-10,7); line(5,7,10,7)
        line(*arms[:4]); line(*arms[4:])
        icons.paste(icon.resize((128,128), Image.Resampling.LANCZOS), (pose*128,0))
    cube = Image.new("RGBA", (512,512))
    draw = ImageDraw.Draw(cube)
    def face(points, color):
        # The same three faces and colors as web/assets/icon.svg.
        draw.polygon([((x-140)*512/232,(y-92)*512/232) for x,y in points], fill=color)
    face([(154,156),(256,212),(256,324),(154,268)], "#628A38")
    face([(256,212),(358,156),(358,268),(256,324)], "#3E5A22")
    face([(256,100),(358,156),(256,212),(154,156)], "#A6D065")
    icons.paste(cube.resize((128,128), Image.Resampling.LANCZOS), (1280,0))
    save(icons, "icons.png")
    # Circle, sector boundaries and rim have coverage alpha at texture resolution.
    # Each favorite count loads one atlas; changing hover only changes quad tint.
    cell = 512
    samples = [(-.25,-.25),(.25,-.25),(-.25,.25),(.25,.25)]
    for slots in range(1,9):
        masks = [bytearray(cell*cell) for _ in range(2*slots+2)]
        step = math.tau/slots
        for py in range(cell):
            for px in range(cell):
                coverage = {}
                for ox,oy in samples:
                    x = (px+.5+ox-cell/2) * 232/cell
                    y = (py+.5+oy-cell/2) * 232/cell
                    distance = math.hypot(x,y)
                    if distance > 116: continue
                    angle = math.atan2(y,x)+math.pi/2
                    slot = int(((angle+step/2+math.tau)%math.tau)/step)
                    if distance < 116*.37: kind = slots
                    elif distance < 116*.40: kind = slots+1
                    elif distance > 114: kind = slots+2+slot
                    else:
                        within = (angle+step/2+math.tau)%step
                        kind = slots+1 if slots>1 and min(within,step-within)*distance<1.1 else slot
                    coverage[kind] = coverage.get(kind,0)+1
                index = py*cell+px
                for kind,count in coverage.items(): masks[kind][index] = round(count*255/4)
        atlas = Image.new("RGBA", (cell*4,cell*5))
        for kind,alpha in enumerate(masks):
            mask = Image.new("RGBA", (cell,cell), "white")
            mask.putalpha(Image.frombytes("L",(cell,cell),bytes(alpha)))
            atlas.paste(mask, ((kind%4)*cell,(kind//4)*cell))
        save(atlas, f"wheel-{slots}.png")
        print(f"Generated smooth {slots}-slot wheel")


if __name__ == "__main__":
    main()
