"""Original owner Store collection, built with the existing cosmetic atlas tools.

Called by gen_cosmetics.py --store-collection. Outputs stay in ignored cosmetics/;
normal bundled-art builds never regenerate or publish this collection.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageChops, ImageFilter
import gen_cosmetics as art

ROOT = Path(art.ROOT)


def material(size, color, face, motif=None):
    """Paint at native atlas resolution: bevels, directional grain and details."""
    width, height = size
    image = Image.new("RGBA", size)
    pixels = image.load()
    directional = {"front": .03, "back": -.13, "left": -.08, "right": -.03,
                   "top": .19, "bottom": -.23}[face]
    for y in range(height):
        for x in range(width):
            grain = ((x*17+y*23+(x//3)*11) % 13-6)/650
            light = directional + .07*(1-y/max(1,height-1)) + grain
            if x == 0 or y == height-1:
                light -= .15
            if y == 0 or (x == 1 and width > 5):
                light += .17
            pixels[x,y] = art.shade(color,light)
    d = ImageDraw.Draw(image)
    if motif == "stitch" and width>5 and height>5:
        for x in range(3,width-2,4):
            for y in (2,height-3):
                d.line((x,y,x+1,y),fill=art.shade(color,.35))
    elif motif == "leather" and width>12 and height>12:
        for x,y in ((width//3,height//3),(width*2//3,height*2//3)):
            d.line((x,y,min(width-1,x+3),y),fill=art.shade(color,.06))
    elif motif == "scale":
        for y in range(2,height,5):
            for x in range(1+(y//5%2)*3,width,6):
                d.line([(x,y),(x+2,y+2),(x+4,y)],fill=art.shade(color,-.08),width=1)
                d.line([(x+1,y),(x+3,y)],fill=art.shade(color,.09),width=1)
    elif motif == "metal":
        if width>24 and height>24:
            d.line((width//3,3,width//3+width//4,3),fill=art.shade(color,.13))
    elif motif == "gem" and min(width,height)>4:
        cx,cy=width//2,height//2
        d.polygon([(cx,1),(width-2,cy),(cx,height-2),(1,cy)],fill=art.shade(color,.25))
        d.polygon([(cx,2),(cx,cy),(2,cy)],fill=art.shade(color,.65))
        d.line((cx,cy,cx,height-2),fill=art.shade(color,-.3))
    elif motif == "eye" and face=="front" and min(width,height)>=4:
        d.rectangle((1,1,width-2,height-2),fill='#11161c')
        d.rectangle((2,max(1,height-3),max(2,width-3),height-2),fill=art.C(color))
        d.rectangle((2,1,min(width-2,3),min(height-2,2)),fill='#fff9e6')
    elif motif == "badge" and face=="front":
        cx,cy=width//2,height//2
        d.polygon([(cx,cy-3),(cx+3,cy-1),(cx+3,cy+2),(cx,cy+4),(cx-3,cy+2),(cx-3,cy-1)],fill='#dfebe1')
        d.line([(cx-3,cy-1),(cx,cy+1),(cx+3,cy-1)],fill='#52785c')
        d.line((cx,cy+1,cx,cy+4),fill='#52785c')
    return image


class Model:
    def __init__(self, slot, key, name, description):
        self.slot, self.key, self.name, self.description = slot, key, name, description
        self.pieces, self.rigs = [], []
        self.mesh_boxes, self.mesh_faces = [], []

    def box(self, origin, size, color, motif=None, motion="none", pivot=(0, 0, 0), mirror=False):
        size=[max(.125,round(value*8)/8) for value in size]
        self.pieces.append((list(origin), size, color, *([motif] if motif else [])))
        self.rigs.append(dict(motion=motion, pivot=list(pivot), mirror=mirror))

    def tube(self, points, thickness, color, motion="none", pivot=(0,0,0), motif="metal"):
        used=set()
        for start,end in zip(points,points[1:]):
            steps=max(1,math.ceil(math.dist(start,end)/(thickness*.8)))
            for i in range(steps+1):
                centre=tuple(round((a+(b-a)*i/steps)*8)/8 for a,b in zip(start,end))
                if centre in used:continue
                used.add(centre)
                self.box([v-thickness/2 for v in centre],[thickness]*3,color,motif,motion=motion,pivot=pivot)

    def mesh(self, image, origin, px=8, depth=.25, motion="none", pivot=(0,0,0), flip=False):
        for x,y,w,h,visible in art.wing_rectangles(image,limit=32):
            face=image.crop((x,y,x+w,y+h))
            if flip:face=face.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            side=max(1,round(depth*px))
            edge=lambda rect,size:face.crop(rect).resize(size,Image.Resampling.NEAREST)
            self.mesh_faces.append(art.faces(face,face.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                edge((w-1,0,w,h),(side,h)),edge((0,0,1,h),(side,h)),
                edge((0,0,w,1),(w,side)),edge((0,h-1,w,h),(w,side))))
            self.mesh_boxes.append(dict(origin=[origin[0]-(x+w)/px if flip else origin[0]+x/px,
                origin[1]+y/px,origin[2]],size=[w/px,h/px,depth],px=px,
                part=len(self.mesh_faces)-1,motion=motion,pivot=list(pivot),
                faces=[{"left":"right","right":"left"}.get(side,side) for side in visible] if flip else visible))

    def panel(self, image, origin, px=16, depth=.125, motion="none", pivot=(0,0,0), flip=False):
        # Small butterfly wings use the existing two-sided cutout approach.
        # Alpha supplies the silhouette; splitting every texel creates needless faces.
        w,h=image.size
        if flip:image=image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        side=max(1,round(depth*px))
        blank=lambda size:Image.new('RGBA',size)
        self.mesh_faces.append(art.faces(image,image.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
            blank((side,h)),blank((side,h)),blank((w,side)),blank((w,side))))
        self.mesh_boxes.append(dict(origin=[origin[0]-w/px if flip else origin[0],origin[1],origin[2]],
            size=[w/px,h/px,depth],px=px,part=len(self.mesh_faces)-1,
            faces=["front","back"],motion=motion,pivot=list(pivot)))

    def slab(self, mask, y, color, thickness=.5, unit=.25, motif=None, offset=(0,0)):
        image=Image.new('RGBA',mask.size);image.putalpha(mask)
        for x,z,w,d in art.silhouette_rectangles(image):
            self.box(((x-mask.width/2)*unit+offset[0],y,(z-mask.height/2)*unit+offset[1]),
                     (w*unit,thickness,d*unit),color,motif)

    def item(self):
        item = art._accessory(self.slot, self.key, self.name, self.description, self.pieces)
        for box, rig, piece in zip(item["boxes"], self.rigs, self.pieces):
            box.update(rig)
            box["px"]=8
            w,h,d=(round(size*8) for size in box["size"])
            color=piece[2]
            motif=piece[3] if len(piece)>3 else None
            item["_faces"][box["part"]]={face:material(size,color,face,motif) for face,size in
                (("front",(w,h)),("back",(w,h)),("left",(d,h)),("right",(d,h)),("top",(w,d)),("bottom",(w,d)))}
        # Reuse compact atlas shelves for detailed headwear and companions.
        start=len(item["_faces"])
        item["boxes"].extend({**box,"part":box["part"]+start} for box in self.mesh_boxes)
        item["_faces"].extend(self.mesh_faces)
        item["feathers"] = []
        return item


WINGS = [
    ("ivory-tide", "Ivory Tide Wings", "feather", '#dfe5ed', '#8eafc1', '#f6dfba'),
    ("midnight-raven", "Midnight Raven Wings", "raven", '#263544', '#5c7888', '#91bbbe'),
    ("canyon-wyvern", "Canyon Wyvern Wings", "wyvern", '#9a5949', '#453946', '#e8b36b'),
    ("cloud-fan", "Cloud Fan Wings", "fan", '#e9ecdf', '#b2c7aa', '#d1af62'),
    ("sunlace-monarch", "Sunlace Monarch Wings", "monarch", '#e7a45c', '#383d4d', '#fff0bf'),
    ("obsidian-seraph", "Obsidian Seraph Wings", "seraph", '#414855', '#c0a97c', '#d7ece5'),
    ("ember-circuit", "Ember Circuit Wings", "mecha", '#8e465b', '#d6b77d', '#9ed4d2'),
    ("moonframe-bat", "Moonframe Bat Wings", "bat", '#465d79', '#cedce2', '#abd4cd'),
    ("amethyst-fae", "Amethyst Fae Wings", "fae", '#aa7ebb', '#534766', '#e9d1ac'),
    ("copper-wyvern", "Copper Wyvern Wings", "wyvern", '#d0a265', '#66537a', '#f4dcb0'),
    ("glacial-morpho", "Glacial Morpho Wings", "morpho", '#649fbe', '#303f65', '#d5f1e4'),
    ("solar-imp", "Solar Imp Wings", "imp", '#d8804b', '#715040', '#f4df99'),
    ("orchid-drake", "Orchid Drake Wings", "drake", '#8b74a7', '#303e50', '#b8dfbd'),
    ("clockwork-kestrel", "Clockwork Kestrel Wings", "clockwork", '#ada27c', '#574f50', '#b8d8da'),
    ("sakura-bough", "Sakura Bough Wings", "floral", '#a18b68', '#5c4c56', '#efb7c6'),
    ("crimson-archfiend", "Crimson Archfiend Wings", "archfiend", '#3c394b', '#b76472', '#e3a877'),
]


def wings():
    output=[]
    for key,name,style,base,trim,glow in WINGS:
        if style in ("feather","raven","fan","seraph","mecha"):
            layers,guides=feather_layers(style,base,trim,glow)
        elif style in ("monarch","morpho","fae"):
            layers,guides=butterfly_layers(style,base,trim,glow)
        elif style=="floral":
            layers,guides=flower_layers()
        else:
            layers,guides=membrane_layers(style,base,trim,glow)
        boxes,painted=[],[]
        # One model unit is six source texels. Separate volumes have their own
        # depth, curvature and feather bone; ribs sit proud of the membranes.
        px=6
        feathers=[]
        for start,end,width,curve,curl in guides:
            feathers.append(dict(start=[1+start[0]/px,-7+start[1]/px],
                end=[1+end[0]/px,-7+end[1]/px],width=width/px,curve=curve/px,curl=curl,tilt=.025))
        for index,(front,guide,depth,offset) in enumerate(layers):
            for x,y,w,h,visible in art.wing_rectangles(front,limit=36,strip=24):
                face=front.crop((x,y,x+w,y+h))
                edge=lambda rect,size:face.crop(rect).resize(size,Image.Resampling.NEAREST)
                painted.append(art.faces(face,face.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                    edge((w-1,0,w,h),(depth,h)),edge((0,0,1,h),(depth,h)),
                    edge((0,0,w,1),(w,depth)),edge((0,h-1,w,h),(w,depth))))
                boxes.append(dict(origin=[1+x/px,-7+y/px,2.5+offset],size=[w/px,h/px,depth/px],px=px,
                    part=len(painted)-1,mirror=True,faces=visible,motion="wing",pivot=[1,3,2.5],
                    **({"feather":guide} if guide>=0 else {})))
        output.append(dict(id=key,slot="back",name=name,
            blurb="Original "+name.lower()+" with sculpted layers, painted surfaces and responsive wing strokes.",
            boxes=boxes,_faces=painted,feathers=feathers,wing_flare=True,separate_feathers=True))
    return output


def tinted_feather(start,end,width,curve,ramp,seed,edge=None):
    # Preserve the proven feather painter's vane grain; shape/placement is new.
    image=art._wing_feather(start,end,width,curve,seed,molten=False,joined=True)
    palette=[art.C(color) for color in art.WING_PALETTE]
    colors={color for count,color in image.getcolors(image.width*image.height) if color[3]}
    lookup={color:art.C(ramp[min(range(len(palette)),key=lambda i:sum((color[c]-palette[i][c])**2 for c in range(3)))]) for color in colors}
    pixels=image.load()
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x,y][3]:pixels[x,y]=lookup[pixels[x,y]]
    if edge:
        mask=image.getchannel('A')
        rim=ImageChops.subtract(mask,mask.filter(ImageFilter.MinFilter(3)))
        image.paste(art.C(edge),(0,0),rim)
    return art._feather_mesh_art(image)


def feather_layers(style,base,trim,glow):
    white=['#606e79','#7b8992','#93a1ab','#a6b5bd','#bdcbd2','#cdd9dd','#dce5e7','#e7eceb','#f0f1eb','#fffaf0','#ffffff']
    raven=['#080d13','#0d151f','#15202a','#1b2a34','#233742','#2d424c','#354e57','#415c65','#506b71','#71888d','#9aacad']
    gold=['#151720','#24232c','#32313b','#40404b','#51515c','#64646d','#787a80','#929398','#aaa8a2','#c4bdac','#ece0ba']
    mech=['#28131e','#402330','#633243','#8a4056','#aa5165','#bc6573','#d18784','#dfb095','#e7c69d','#f4dfac','#fff3d0']
    ramp=white if style in ('feather','fan') else raven if style=='raven' else gold if style=='seraph' else mech
    primaries=[((12,60),(53,166),16,-9),((17,56),(83,158),17,-13),((21,50),(111,136),17,-15),
               ((25,44),(139,108),16,-12),((29,39),(153,77),15,-10),((31,35),(150,43),14,-7),
               ((30,32),(126,13),13,-5)]
    if style=='fan':
        primaries=[((15,57),(64,146),17,-8),((19,51),(103,132),16,-10),((23,45),(134,105),17,-9),
                   ((26,40),(151,76),15,-7),((28,35),(142,40),14,-5),((26,30),(115,10),13,-5)]
    if style=='raven':
        primaries=[(s,(e[0],min(173,e[1]+7)),w-2,c-3) for s,e,w,c in primaries]
    if style=='mecha':
        primaries=[((20,52),(66,134),11,-2),((23,43),(104,101),12,-2),
                   ((27,34),(140,66),10,-1),((27,28),(114,8),10,0)]
    coverts=[((7,56),(39,104),12,-4),((11,47),(62,85),13,-5),((15,38),(80,55),12,-4),((19,30),(79,23),11,-3)]
    guides=[];layers=[]
    for i,(s,e,w,c) in enumerate(primaries+coverts):
        edge='#ffd864' if style=='seraph' else '#d4ab68' if style=='mecha' else None
        image=tinted_feather(s,e,w,c,ramp,i,edge)
        guides.append((s,e,w,c,2.8+i*.23 if i<len(primaries) else .6+i*.12))
        # Coverts genuinely overlap the primary roots, leaving tips independent.
        offset=(i*.08 if i<len(primaries) else 1.25+(i-len(primaries))*.2)
        layers.append((image,i,3 if style=='mecha' else 2,offset))
    root=Image.new('RGBA',art.WING_SIZE)
    d=ImageDraw.Draw(root)
    color='#e0e5e4' if style in ('feather','fan') else '#23323c' if style=='raven' else '#cdb36d' if style=='seraph' else '#c79d66'
    d.polygon([(2,47),(10,32),(20,24),(33,31),(31,46),(20,63),(5,65)],fill=art.C(art.shade(color,-.25)),outline=art.C(color),width=2)
    d.polygon([(7,45),(15,34),(23,30),(29,35),(22,48),(12,57)],fill=art.C(color))
    d.line([(8,45),(18,36),(25,35)],fill=art.C(art.shade(color,.4)),width=2)
    if style in ('seraph','mecha'):
        d.polygon([(13,44),(20,37),(25,44),(20,52)],fill=art.C(glow))
        d.line([(15,44),(20,40),(22,44)],fill='#fff6cb',width=1)
    layers.append((root,-1,5,2.25))
    return layers,guides


def painted_mask(mask,base,trim,light,grain='membrane'):
    image=Image.new('RGBA',mask.size)
    pixels=image.load()
    for y in range(mask.height):
        for x in range(mask.width):
            if not mask.getpixel((x,y)):continue
            shade=.17*math.sin(x/34+y/28)+.055*math.sin(x*.9+y*.31)
            shade+=.13*(1-y/mask.height)
            color=art.shade(base,shade)
            if grain=='membrane' and (x+y*2)%17<2:color=art.shade(color,-.08)
            pixels[x,y]=color
    rim=ImageChops.subtract(mask,mask.filter(ImageFilter.MinFilter(5)))
    image.paste(art.C(trim),(0,0),rim)
    return image


def membrane_layers(style,base,trim,glow):
    # Raised elbow/finger bones and lobes bent in depth. Scallops bow inward
    # between fingers, instead of a filled triangular badge.
    profiles={
        'bat':[(10,72),(43,28),(100,12),(150,47),(126,91),(88,130),(40,153)],
        'wyvern':[(8,68),(34,23),(82,3),(150,36),(134,91),(104,140),(52,166)],
        'drake':[(8,75),(32,35),(105,13),(154,50),(142,110),(86,157),(38,147)],
        'imp':[(8,72),(44,35),(110,19),(154,64),(125,111),(78,153),(32,142)],
        'archfiend':[(8,75),(29,25),(93,5),(146,23),(153,94),(100,156),(48,172)],
        'clockwork':[(8,74),(35,34),(111,12),(149,48),(122,107),(78,152),(35,128)],
    }
    points=profiles[style];root=(10,74);elbow=points[2]
    if style=='archfiend':base,trim,glow='#27101c','#d82432','#ff6953'
    if style=='wyvern':base,trim,glow=('#c87636','#663c58','#ffc06b') if base[1] in 'dD' else ('#6e2427','#382226','#ed9561')
    if style=='bat':base,trim,glow='#172131','#e1e6e5','#c7e1e1'
    if style=='drake':base,trim,glow='#6545a4','#18152d','#aa81e8'
    if style=='imp':base,trim,glow='#ee8229','#933927','#ffe084'
    if style=='clockwork':base,trim,glow='#ae8545','#49372d','#efd99a'
    layers=[];guides=[]
    for i in range(3,len(points)-1):
        a,b=points[i],points[i+1]
        # Curved inner lobe forms the ragged membrane edge.
        midpoint=((a[0]+b[0])/2*.79+root[0]*.21,(a[1]+b[1])/2*.79+root[1]*.21)
        mask=Image.new('L',art.WING_SIZE)
        d=ImageDraw.Draw(mask)
        d.polygon([root,elbow,a,midpoint,b],fill=255)
        membrane=painted_mask(mask,base,art.shade(trim,-.2),glow)
        # Fine creases fan from each finger. No baked drop shadows are needed.
        p=ImageDraw.Draw(membrane)
        for amount in (.22,.42,.63,.8):
            ex=a[0]+(b[0]-a[0])*amount;ey=a[1]+(b[1]-a[1])*amount
            p.line([(root[0]+5,root[1]),(round(ex*.77+root[0]*.23),round(ey*.77+root[1]*.23))],fill=art.C(art.shade(base,-.17)),width=1)
        layers.append((art._feather_mesh_art(membrane),0,2,.2+i*.04))
    ribs=Image.new('RGBA',art.WING_SIZE);p=ImageDraw.Draw(ribs)
    paths=[[root,points[1],elbow,points[3]],*[ [root,points[2],point] for point in points[4:]]]
    for path in paths:
        p.line(path,fill=art.C(art.shade(trim,-.25)),width=7)
        p.line([(x-1,y-1) for x,y in path],fill=art.C(trim),width=4)
        p.line([(x-2,y-2) for x,y in path],fill=art.C(glow),width=1)
    for x,y in (points[1],elbow):
        p.polygon([(x-5,y+3),(x-3,y-6),(x+5,y-14),(x+4,y+1)],fill=art.C(trim),outline=art.C(glow))
    # Shoulder cuff / hinge is a separate thick volume.
    p.polygon([(2,64),(12,54),(26,60),(27,77),(13,91),(3,81)],fill=art.C(art.shade(trim,-.18)),outline=art.C(glow),width=2)
    if style=='clockwork':
        for x,y in ((18,71),(44,51),(103,35)):
            p.ellipse((x-8,y-8,x+8,y+8),fill='#42352c',outline='#e2ba67',width=2)
            p.rectangle((x-2,y-2,x+2,y+2),fill='#ffe7a5')
            for dx,dy in ((-10,0),(8,0),(0,-10),(0,8)):
                p.rectangle((x+dx,y+dy,x+dx+3,y+dy+3),fill='#bda15d')
    # One continuous skin-and-bone rig keeps membrane seams attached through
    # rest curvature, flapping and the larger N flare.
    guides=[(root,(150,95),65,0,1.6)]
    layers.append((art._feather_mesh_art(ribs),0,6,.45))
    return layers,guides


def butterfly_layers(style,base,trim,glow):
    if style=='morpho':base,trim,glow='#179cdb','#102447','#a2edff'
    elif style=='monarch':base,trim,glow='#f0a62a','#35231e','#fff1c9'
    else:base,trim,glow='#a22fe2','#5e158b','#f6b9ff'
    top=[(7,80),(26,34),(80,6),(144,14),(154,46),(137,83),(88,103),(14,96)]
    bottom=[(15,98),(84,100),(133,108),(143,137),(113,168),(55,156),(17,128)]
    if style=='fae':
        top=[(7,83),(21,52),(91,9),(149,0),(122,49),(153,70),(111,97),(14,98)]
        bottom=[(17,98),(79,104),(143,116),(111,133),(75,172),(37,144),(17,121)]
    layers=[];guides=[]
    for i,polygon in enumerate((top,bottom)):
        mask=Image.new('L',art.WING_SIZE);ImageDraw.Draw(mask).polygon(polygon,fill=255)
        im=painted_mask(mask,base,trim,glow,grain='silk');d=ImageDraw.Draw(im)
        root=(9,90)
        for endpoint in polygon[2:-1]:
            d.line([root,endpoint],fill=art.C(trim),width=4)
            d.line([(root[0]+3,root[1]-1),(endpoint[0]-3,endpoint[1]+1)],fill=art.C(art.shade(base,.28)),width=1)
        # Native pixel scales, clustered highlights and crisp white edge spots.
        pixels=im.load()
        for y in range(im.height):
            for x in range(im.width):
                if not pixels[x,y][3]:continue
                if (x*13+y*7)%37<2 and 18<x<140:
                    pixels[x,y]=art.shade(pixels[x,y],.24)
        inset=mask.filter(ImageFilter.MinFilter(13))
        rim=ImageChops.subtract(mask,inset)
        for x,y in polygon[2:-1]:
            for dx,dy in ((-5,5),(-8,9),(-12,12)):
                xx,yy=x+dx,y+dy
                if 0<=xx<160 and 0<=yy<176 and rim.getpixel((xx,yy)):
                    d.rectangle((xx-1,yy-1,xx+1,yy+1),fill=art.C(glow))
        endpoint=(136,43) if i==0 else (107,159)
        guides.append((root,endpoint,28,0,2.75 if i==0 else 3.75))
        layers.append((im,i,2,i*.4))
    # A raised inner frame and two light catchers give the silk lobes depth.
    root=Image.new('RGBA',art.WING_SIZE);d=ImageDraw.Draw(root)
    d.polygon([(3,78),(12,66),(25,77),(23,105),(10,118),(3,108)],fill=art.C(trim),outline=art.C(glow),width=1)
    d.line([(9,76),(14,88),(10,110)],fill=art.C(art.shade(base,.55)),width=3)
    layers.append((root,-1,5,1.1))
    return layers,guides


def flower_layers():
    bark=Image.new('RGBA',art.WING_SIZE);d=ImageDraw.Draw(bark)
    paths=[[(6,89),(33,51),(71,20),(128,11)],[(13,82),(55,61),(104,40),(153,31)],
           [(16,88),(65,94),(112,73),(153,57)],[(17,91),(48,130),(101,149),(134,157)]]
    for path in paths:
        d.line(path,fill='#4a2928',width=8)
        d.line([(x-1,y-1) for x,y in path],fill='#9e6852',width=4)
        d.line([(x-2,y-2) for x,y in path],fill='#cf9771',width=1)
    blossoms=Image.new('RGBA',art.WING_SIZE);p=ImageDraw.Draw(blossoms)
    for i,path in enumerate(paths):
        for j,(x,y) in enumerate(path[1:]):
            for ox,oy in ((0,0),(-12,6),(9,-9)):
                cx,cy=x+ox,y+oy
                p.polygon([(cx-9,cy+3),(cx-2,cy-6),(cx+4,cy-5),(cx,cy+6)],fill='#48734e')
                for dx,dy in ((-5,-1),(2,-2),(-1,-6),(-1,3)):
                    p.rectangle((cx+dx,cy+dy,cx+dx+4,cy+dy+4),fill='#e88cbb',outline='#f9c8db')
                p.rectangle((cx-1,cy-1,cx+1,cy+1),fill='#ffedb4')
    guide=((10,88),(136,83),28,0,1.5)
    return [(art._feather_mesh_art(bark),0,5,.2),(art._feather_mesh_art(blossoms),0,3,.6)],[guide]


def butterfly_wing():
    wing=Image.new('RGBA',(28,40))
    mask=Image.new('L',wing.size)
    d=ImageDraw.Draw(mask)
    d.polygon([(1,20),(6,8),(16,2),(26,1),(27,10),(24,20),(15,24),(1,23)],fill=255)
    d.polygon([(1,24),(18,24),(27,30),(23,39),(11,37),(2,30)],fill=255)
    wing=painted_mask(mask,'#188dd2','#152b4a','#b1f3ff',grain='silk')
    d=ImageDraw.Draw(wing)
    d.line([(2,23),(22,6)],fill='#164a82',width=1)
    d.line([(2,23),(24,16)],fill='#36b7e9',width=1)
    d.line([(2,25),(21,33)],fill='#103860',width=1)
    d.rectangle((21,7,22,8),fill='#a4edff');d.rectangle((20,34,21,35),fill='#93e8ff')
    return wing


def butterfly_aura():
    aura=Model("aura","butterfly","Celestial Butterfly Aura",
        "Eight luminous blue butterflies spiral around your whole body, with gentle wing beats from your shoulders to your ankles.")
    wing=butterfly_wing()
    for i,cy in enumerate((-7,-2,3,7,11,15,19,23)):
        angle=i*2.39996
        radius=9.5+(i%3)*.5
        cx=round(math.cos(angle)*radius*4)/4
        cz=round(math.sin(angle)*radius*4)/4
        aura.box((cx-.125,cy-.875,cz-.125),(.25,1.75,.375),'#172640',motion="orbit",pivot=(cx,cy,cz))
        for flip,motion in ((False,"orbit_wing_right"),(True,"orbit_wing_left")):
            aura.panel(wing,(cx,cy-1.25,cz),px=16,depth=.125,motion=motion,pivot=(cx,cy,cz),flip=flip)
        for side in (-1,1):
            aura.box((cx+side*.25,cy-1.25,cz),(.125,.5,.125),'#385f7d',motion="orbit",pivot=(cx,cy,cz))
    return aura.item()


def headwear():
    output=[]
    halo=Model("head","sunward-halo","Sunward Halo","A substantial floating gold halo with ivory bevels, chamfered corners and a warm polished interior.")
    for y,thickness,color in ((-11.5,.75,'#e7bb35'),(-11.625,.25,'#fff3c2'),(-10.875,.25,'#b37b24')):
        for origin,size in (((-4.5,y,-5.5),(9,thickness,.75)),((-4.5,y,4.75),(9,thickness,.75)),
                            ((-5.5,y,-4.5),(.75,thickness,9)),((4.75,y,-4.5),(.75,thickness,9))):
            halo.box(origin,size,color,"metal",motion="float")
        for x in (-5.25,4.25):
            for z in (-5.25,4.25):
                halo.box((x,y,z),(1,thickness,1),color,"metal",motion="float")
    output.append(halo.item())

    sun=Model("head","dawnflare-halo","Dawnflare Halo","A tall open sunwheel with an amber core and stepped golden rays hovering behind your head.")
    points=[]
    for i in range(17):
        angle=i*math.tau/16
        points.append((round(math.cos(angle)*5*4)/4,-13.5+round(math.sin(angle)*5*4)/4,2.5))
    sun.tube(points,.625,'#e4be3f',motion="float")
    for i in range(12):
        angle=i*math.tau/12
        root=(math.cos(angle)*5,-13.5+math.sin(angle)*5,2.5)
        end=(math.cos(angle)*6.75,-13.5+math.sin(angle)*6.75,2.5)
        sun.tube([root,end],.5,'#fff0a8',motion="float")
    output.append(sun.item())

    crown=Model("head","tidal-crown","Tidal Crown","A floating obsidian diadem with tapered jagged spires, a luminous aqua edge and a faceted central shard.")
    silhouette=Image.new('L',(80,66))
    ImageDraw.Draw(silhouette).polygon([(0,58),(0,30),(8,42),(13,10),(20,33),(28,47),(37,1),
        (44,25),(52,44),(61,14),(67,42),(79,26),(79,58),(65,64),(52,60),(40,65),(26,60),(12,64)],fill=255)
    face=painted_mask(silhouette,'#111f2a','#63eee6','#b9fff4',grain='metal')
    d=ImageDraw.Draw(face)
    d.line([(37,5),(39,43),(31,52),(40,59),(49,51),(43,45)],fill='#b4fff1',width=1)
    d.polygon([(40,42),(48,52),(40,61),(32,52)],fill='#72cec9')
    d.polygon([(40,44),(40,52),(34,52)],fill='#b2fff2')
    crown.mesh(face,(-5,-18,-4.25),depth=.75,motion="float")
    for origin,size in (((-5,-11.25,3.25),(10,1,.75)),((-5.25,-11.25,-3.5),(.75,1,7)),((4.5,-11.25,-3.5),(.75,1,7))):
        crown.box(origin,size,'#15222b',motion="float")
    for x in (-5.25,4.5):
        for z,height in ((-1,3.75),(1.75,4.75)):
            crown.box((x,-11.25-height,z),(.75,height,1.25),'#13242e',motion="float")
            crown.box((x+.125,-11.75-height,z+.25),(.5,.5,.75),'#69ebe5',motion="float")
            crown.box((x-.125,-11.25-height,z-.125),(.25,height,1.5),'#66d8d2',motion="float")
    output.append(crown.item())

    wreath=Model("head","morpho-orbit","Morpho Orbit Halo","Three shaped blue morpho butterflies circle at different heights, with bright silk lobes and independent wing beats.")
    wing=butterfly_wing()
    for i,angle in enumerate((.2,2.3,4.4)):
        cx=round(math.cos(angle)*6*4)/4
        cz=round(math.sin(angle)*6*4)/4
        cy=-12.5+(i%2)*1.25
        wreath.box((cx-.125,cy-1,cz-.125),(.25,1.75,.375),'#172640',motion="orbit")
        for flip,motion in ((False,"orbit_wing_right"),(True,"orbit_wing_left")):
            wreath.mesh(wing,(cx,cy-1.25,cz),px=16,depth=.125,motion=motion,pivot=(cx,cy,cz),flip=flip)
        for side in (-1,1):
            wreath.tube([(cx,cy-.75,cz),(cx+side*.375,cy-1.25,cz)],.125,'#385f7d',motion="orbit",motif=None)
    output.append(wreath.item())

    # Real layered feather textures in miniature, retaining the head attachment.
    layers,_=feather_layers('feather','#eef5ef','#a0b2bc','#ffffff')
    boxes,painted=[],[]
    for index,(source,guide,depth,offset) in enumerate(layers):
        image=source.resize((48,52),Image.Resampling.NEAREST)
        for x,y,w,h,visible in art.wing_rectangles(image,limit=20):
            tile=image.crop((x,y,x+w,y+h))
            edge=lambda rect,size:tile.crop(rect).resize(size,Image.Resampling.NEAREST)
            painted.append(art.faces(tile,tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT),edge((w-1,0,w,h),(2,h)),
                edge((0,0,1,h),(2,h)),edge((0,0,w,1),(w,2)),edge((0,h-1,w,h),(w,2))))
            boxes.append(dict(origin=[4+x/8,-9+y/8,offset*.25],size=[w/8,h/8,.25],px=8,
                part=len(painted)-1,mirror=True,faces=visible,motion="wing",pivot=[4,-5.5,.25]))
    output.append(dict(id='cloudlet-headwings',slot='head',name='Cloudlet Head Wings',
        blurb='A pair of layered ivory feather fins with softly moving tips, worn beside your head.',
        boxes=boxes,_faces=painted,feathers=[],wing_flare=False))

    for key,name,color,trim,ears in (("trailhead-cap","Trailhead Cap",'#a93d39','#ede8dc',False),
                                    ("starlit-cat-cap","Starlit Cat Cap",'#7875b6','#c0c8ed',True),
                                    ("dune-runner-cap","Dune Runner Cap",'#b58b59','#6e5039',False)):
        cap=Model("head",key,name,"A rounded baseball cap with a curved brim, restrained panel seams and a small embroidered patch.")
        # Rounded voxel cross-sections produce a fitted dome, rather than
        # stacked rectangular plates. Lower layers form a hollow cloth shell.
        for y,edge,radius,hollow in ((-7.5,18,5,True),(-8.125,18,5,True),(-8.625,17,6,False),
                                     (-9.125,15,7,False),(-9.5,12,8,False),(-9.875,8,6,False)):
            mask=Image.new('L',(40,40));d=ImageDraw.Draw(mask)
            d.rounded_rectangle((20-edge,20-edge,19+edge,19+edge),radius=radius,fill=255)
            if hollow:
                d.rounded_rectangle((23-edge,23-edge,16+edge,16+edge),radius=max(1,radius-2),fill=0)
            cap.slab(mask,y,color,thickness=.625 if y>-8.5 else .5,motif=None)
        cap.box((-.25,-10.125,-.25),(.5,.25,.5),trim)
        brim=Image.new('L',(40,40));d=ImageDraw.Draw(brim)
        d.ellipse((4,0,35,19),fill=255)
        d.rectangle((0,15,39,39),fill=0)
        cap.slab(brim,-6.75,art.shade(color,-.12),thickness=.25,offset=(0,-2.75))
        cap.slab(brim,-6.875,color,thickness=.125,offset=(0,-2.75))
        front='#e8e2d2' if not ears and key=='trailhead-cap' else art.shade(color,.18)
        cap.box((-1.875,-8.625,-4.625),(3.75,1.75,.125),front)
        cap.box((-.5,-8.25,-4.875),(1,1,.125),art.shade(trim,-.05),'badge')
        for x in (-2.25,2):
            cap.box((x,-8.75,-4.5),(.125,1.75,.125),art.shade(color,-.13))
            cap.box((x,-8.125,-4.75),(.25,.25,.125),art.shade(trim,-.15))
        cap.box((-1.75,-7.25,4.5),(3.5,.5,.125),art.shade(color,-.17))
        if ears:
            for side in (-1,1):
                x=-3.5 if side<0 else 1.75
                ear=Image.new('RGBA',(20,24));d=ImageDraw.Draw(ear)
                d.polygon([(0,23),(3,5),(8,0),(14,5),(19,23)],fill=art.C(color),outline=art.C(art.shade(color,-.23)),width=1)
                d.polygon([(5,19),(8,7),(13,19)],fill=art.C(trim))
                cap.mesh(ear,(x,-12,-1.25),px=8,depth=.5)
        output.append(cap.item())

    sprite=Model("head","zephyr-sprite","Zephyr Sprite","A floating storm spirit with a chamfered face, expressive amber eyes and curling wind ribbons around a tapered cloud core.")
    body=(-10,-3,0);head=(-10,-7,0)
    for origin,size,color in (((-11.5,-7,-1.25),(3,2.75,2.5),'#95afd0'),
                              ((-11.75,-4.25,-1.5),(3.5,1.5,3),'#b3c5dc'),
                              ((-11.25,-2.75,-1),(2.5,1,2),'#8babc7'),
                              ((-10.875,-1.75,-.625),(1.75,.75,1.25),'#c1dbe5'),
                              ((-10.5,-1,-.375),(1,.75,.75),'#daeceb')):
        sprite.box(origin,size,color,motion="hover_body",pivot=body)
    sprite.box((-11.75,-10.75,-1.75),(3.5,3.5,3.5),'#7287b2',motion="hover_head",pivot=head)
    sprite.box((-12,-10.25,-1.5),(4,2.5,3),'#91a3c4',motion="hover_head",pivot=head)
    sprite.box((-11.5,-11,-1.5),(3,.5,3),'#bdcadd',motion="hover_head",pivot=head)
    face=Image.new('RGBA',(32,28));d=ImageDraw.Draw(face)
    d.rounded_rectangle((0,0,31,27),radius=3,fill='#879ac1')
    for x in (5,20):
        d.rectangle((x,10,x+6,16),fill='#24324f')
        d.rectangle((x+1,12,x+5,16),fill='#ead78e')
        d.rectangle((x+2,11,x+3,16),fill='#1b2642')
        d.point((x+1,12),fill='#fff8cf')
    d.line([(3,7),(12,10)],fill='#4f638c',width=3)
    d.line([(19,10),(28,7)],fill='#4f638c',width=3)
    d.line([(13,21),(16,20),(19,21)],fill='#d6e0e8',width=1)
    sprite.mesh(face,(-12,-10.75,-1.875),px=8,depth=.125,motion="hover_head",pivot=head)
    for i,(y,radius) in enumerate(((-9.75,3),(-6,3.5),(-3.5,3.25),(-.75,2.5))):
        angle=i*.9
        points=[]
        for j in range(11):
            a=angle+j*math.pi/8
            points.append((-10+round(math.cos(a)*radius*4)/4,y+round(math.sin(a)*.5*4)/4,round(math.sin(a)*radius*4)/4))
        sprite.tube(points,.25,'#e4f5ef',motion="aura",pivot=(-10,-5,0),motif=None)
    output.append(sprite.item())
    output.extend(themed_headwear())
    from cubeon.cosmetic_retirement import STORE_IDS
    return [item for item in output if "cubeon-" + item["id"].removeprefix("head_") not in STORE_IDS]


def bat_cowl():
    """Fitted, faceted cowl; sculpted details use the existing sealed atlas rig."""
    bat=Model("head","midnight-cowl","Midnight Bat Cowl",
        "A sculpted matte-charcoal cowl with swept pointed ears, a raised angular brow, softly luminous pearl-white eye lenses and a shaped open jaw.")
    # Two shallow chamfered crown tiers meet the native square head cleanly.
    for size,y,thickness,inset,color in ((70,-8.5,.375,5,'#252b35'),(68,-8.75,.25,6,'#2a313c')):
        mask=Image.new('L',(size,size));d=ImageDraw.Draw(mask);end=size-1
        d.polygon([(inset,0),(end-inset,0),(end,inset),(end,end-inset),
                   (end-inset,end),(inset,end),(0,end-inset),(0,inset)],fill=255)
        bat.slab(mask,y,color,thickness=thickness,unit=.125)
    bat.box((-4.375,-8.125,-3.875),(.375,8.25,8),'#171d27')
    bat.box((4,-8.125,-3.875),(.375,8.25,8),'#171d27')
    bat.box((-4,-8.125,4),(8,8.25,.375),'#1b212b')
    bat.box((-3.5,-.375,4.125),(7,.5,.25),'#111721')

    mask=Image.new('L',(70,70));d=ImageDraw.Draw(mask)
    d.polygon([(0,3),(3,0),(66,0),(69,3),(69,62),(65,68),(58,57),
               (55,45),(45,43),(35,53),(24,43),(14,45),(11,57),(4,68),(0,62)],fill=255)
    face=material(mask.size,'#242b35','front')
    d=ImageDraw.Draw(face)
    # Broad restrained facets replace the old conspicuous sinusoidal streaks.
    d.polygon([(3,1),(34,1),(27,28),(7,24)],fill='#2c3440')
    d.polygon([(36,1),(66,1),(63,24),(43,28)],fill='#222a35')
    d.polygon([(34,3),(39,25),(35,45),(30,25)],fill='#343e4b')
    d.polygon([(2,34),(12,40),(13,50),(5,63)],fill='#1a212b')
    d.polygon([(68,34),(58,40),(57,50),(65,63)],fill='#151c26')
    d.line([(5,7),(7,22)],fill='#39434f',width=1)
    d.line([(65,7),(63,22)],fill='#2e3845',width=1)
    face.putalpha(mask)
    bat.mesh(face,(-4.375,-8.375,-4.5),px=8,depth=.25)

    # Each lens is enclosed by a dark rim, with a raised brow above it.
    for flip in (False,True):
        lens=Image.new('RGBA',(70,70));d=ImageDraw.Draw(lens)
        d.polygon([(7,27),(29,33),(30,38),(24,42),(12,38),(8,32)],fill='#090f18')
        d.polygon([(11,31),(27,35),(25,38),(14,35)],fill='#dce8ec')
        d.line([(12,31),(26,35)],fill='#ffffff',width=1)
        if flip:lens=lens.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        bat.mesh(lens,(-4.375,-8.375,-4.75),px=8,depth=.125)
        brow=Image.new('L',(70,70));d=ImageDraw.Draw(brow)
        points=[(5,24),(23,28),(32,32),(29,35),(8,28)]
        d.polygon([(69-x,y) for x,y in points] if flip else points,fill=255)
        bevel=material(brow.size,'#303946','front');bevel.putalpha(brow)
        bat.mesh(bevel,(-4.375,-8.375,-4.875),px=8,depth=.125)
    nose=Image.new('L',(70,70));d=ImageDraw.Draw(nose)
    d.polygon([(32,34),(38,34),(40,43),(35,53),(30,43)],fill=255)
    ridge=material(nose.size,'#202936','front');d=ImageDraw.Draw(ridge)
    d.polygon([(34,35),(35,49),(32,43)],fill='#3b4654')
    d.line([(35,37),(37,44),(35,51)],fill='#101822',width=1)
    ridge.putalpha(nose)
    bat.mesh(ridge,(-4.375,-8.375,-5),px=8,depth=.25)

    # Swept tapered ears carry a narrow lit ridge and a substantial dark side.
    for side in (-1,1):
        mask=Image.new('L',(20,40));d=ImageDraw.Draw(mask)
        d.polygon([(1,39),(3,5),(6,0),(9,4),(19,39)],fill=255)
        ear=material(mask.size,'#232c38','front');d=ImageDraw.Draw(ear)
        d.polygon([(6,2),(7,6),(10,35),(5,37)],fill='#3a4655')
        d.polygon([(8,7),(18,38),(11,37)],fill='#111923')
        ear.putalpha(mask)
        bat.mesh(ear,(-4.5 if side<0 else 4.5,-13.125,-1.75),px=8,depth=1.75,flip=side>0)
        bat.box((-4.125 if side<0 else 2.375,-8.625,-1.875),(1.75,.5,2),'#222b37')
    item=bat.item()
    # Finished side/back panels use quiet seams and bevels, not random grain.
    for box in item['boxes'][:len(bat.pieces)]:
        faces=item['_faces'][box['part']]
        if box['size'][1] < 7:continue
        for side in ('left','right','back'):
            tile=faces[side];d=ImageDraw.Draw(tile);w,h=tile.size
            if w<12:continue
            d.line([(w//2,3),(w//2,h-5)],fill='#111822',width=1)
            d.line([(w//2+1,4),(w//2+1,h-6)],fill='#29333f',width=1)
            d.line([(3,h-8),(w-4,h-8)],fill='#0f1620',width=1)
    return item


def spider_mask():
    """Sculpted fitted mask, with actual relief webs and layered eye frames."""
    web=Model("head","crimson-web-mask","Crimson Web Mask",
        "A sculpted scarlet mask with raised graphite webbing, sweeping three-dimensional eye frames, pearl-white lenses and a fitted beveled crown.")
    web.box((-4.125,-8.125,-4.125),(8.25,8.25,8.25),'#a71f35')
    base=web.item()
    # Fine woven material and coherent webs wrap the whole fitted shell.
    for side,tile in base['_faces'][0].items():
        d=ImageDraw.Draw(tile);w,h=tile.size
        cx,cy=w/2,h*.48
        for angle in range(0,360,45):
            a=math.radians(angle)
            d.line((cx,cy,cx+math.cos(a)*w,cy+math.sin(a)*h),fill='#401c2a',width=1)
        for radius in range(9,max(w,h),11):
            points=[(cx+math.cos(i*math.tau/8)*radius,cy+math.sin(i*math.tau/8)*radius) for i in range(9)]
            d.line(points,fill='#4a1e2c',width=1)
        if side in ('left','right','back'):
            d.line((w//2,1,w//2,h-2),fill='#7b162e',width=1)

    side_web=Image.new('RGBA',(66,66));d=ImageDraw.Draw(side_web)
    for angle in range(0,360,45):
        a=math.radians(angle)
        d.line((33,31.68,33+math.cos(a)*66,31.68+math.sin(a)*66),fill='#401c2a',width=1)
    for radius in range(9,66,11):
        d.line([(33+math.cos(i*math.tau/8)*radius,31.68+math.sin(i*math.tau/8)*radius)
                for i in range(9)],fill='#4a1e2c',width=1)
    side_parts=[]
    for side,origin,dimensions in (('left',(-4.25,-8.125,-4.125),(.125,8.25,8.25)),
                                   ('right',(4.125,-8.125,-4.125),(.125,8.25,8.25)),
                                   ('back',(-4.125,-8.125,4.125),(8.25,8.25,.125))):
        side_parts.append((len(web.pieces),side))
        web.box(origin,dimensions,'#401c2a')

    # An octagonal cap and a second narrow rim soften the square head outline.
    crown_start=len(web.pieces)
    for size,y,thickness,color in ((68,-8.375,.25,'#c02a40'),(66,-8.5,.125,'#d43048')):
        mask=Image.new('L',(size,size));d=ImageDraw.Draw(mask);end=size-1
        d.polygon([(4,0),(end-4,0),(end,4),(end,end-4),
                   (end-4,end),(4,end),(0,end-4),(0,4)],fill=255)
        web.slab(mask,y,color,thickness=thickness,unit=.125)
    crown_end=len(web.pieces)

    size=68
    face=Image.new('RGBA',(size,size))
    for y in range(size):
        for x in range(size):
            # Smooth broad cloth lighting; the model supplies the raised shape.
            centre=1-abs(x-33.5)/34
            light=.05+.10*centre-.12*y/67+((x*5+y*3)%7-3)/500
            face.putpixel((x,y),art.shade('#c82740',light))
    face_mask=Image.new('L',(size,size));d=ImageDraw.Draw(face_mask)
    d.polygon([(4,0),(63,0),(67,4),(67,59),(62,67),(5,67),(0,59),(0,4)],fill=255)
    face.putalpha(face_mask)
    webs=Image.new('RGBA',face.size);d=ImageDraw.Draw(webs)
    centre=(33.5,33)
    for angle in range(0,360,45):
        a=math.radians(angle)
        d.line((*centre,centre[0]+math.cos(a)*80,centre[1]+math.sin(a)*80),fill='#311c29',width=1)
    for radius in (10,21,32,43,54):
        points=[(centre[0]+math.cos(i*math.tau/8)*radius,
                 centre[1]+math.sin(i*math.tau/8)*radius) for i in range(9)]
        d.line(points,fill='#361b28',width=1)
    webs.putalpha(ImageChops.multiply(webs.getchannel('A'),face_mask))

    def relief(image, extra=0, cutout=False):
        # Broad stepped planes give the nose/cheeks depth without texel cubes.
        for y in range(0,size,8):
            for x in range(0,size,8):
                tile=image.crop((x,y,min(size,x+8),min(size,y+8)))
                if not tile.getbbox():continue
                cx=x+tile.width/2;cy=y+tile.height/2
                crown=max(0,1-abs(cx-34)/30)
                cheek=max(0,1-abs(cy-36)/35)
                depth=round((.125+.25*crown+.125*crown*cheek)*8)/8
                build=web.panel if cutout else web.mesh
                build(tile,(-4.25+x/8,-8.25+y/8,-4.125-depth-extra),px=8,depth=.125)
    relief(face)
    relief(webs,.125,cutout=True)

    # Three physical tiers: beveled outer frame, dark gasket, inset white lens.
    outer=[(4,17),(13,21),(27,28),(31,33),(28,42),(23,47),
           (16,46),(10,40),(6,31)]
    gasket=[(7,21),(14,24),(26,30),(28,33),(25,40),(21,44),
            (17,43),(12,37),(9,29)]
    inner=[(10,25),(16,27),(24,31),(25,34),(22,39),(20,41),
           (17,40),(14,35),(12,29)]
    for flip in (False,True):
        for points,color,z,depth in ((outer,'#31323d',-5.125,.25),
                                    (gasket,'#111923',-5.125,.125),
                                    (inner,'#e5edf2',-5.0625,.125)):
            mask=Image.new('L',(size,size));d=ImageDraw.Draw(mask)
            d.polygon([(67-x,y) for x,y in points] if flip else points,fill=255)
            if points is not inner:
                hole=gasket if points is outer else inner
                d.polygon([(67-x,y) for x,y in hole] if flip else hole,fill=0)
            layer=Image.new('RGBA',mask.size,color);d=ImageDraw.Draw(layer)
            if points is outer:
                edge=[(5,18),(13,22),(27,29)]
                d.line([(67-x,y) for x,y in edge] if flip else edge,fill='#60616a',width=1)
            elif points is inner:
                for y in range(size):
                    d.line((0,y,size,y),fill=art.shade('#eaf1f5',.04-.1*y/67))
                edge=[(11,26),(16,28),(23,32)]
                d.line([(67-x,y) for x,y in edge] if flip else edge,fill='#ffffff',width=1)
            layer.putalpha(mask)
            build=web.mesh if points is outer else web.panel
            build(layer,(-4.25,-8.25,z),px=8,depth=depth)

    # A narrow scarlet bridge between the eyes joins the facial planes.
    bridge=Image.new('L',(size,size));d=ImageDraw.Draw(bridge)
    d.polygon([(32,29),(35,29),(37,40),(34,46),(30,40)],fill=255)
    tile=Image.new('RGBA',bridge.size,'#ac2038');d=ImageDraw.Draw(tile)
    d.line([(33,30),(33,39),(34,43)],fill='#e84757',width=1)
    d.line([(34,31),(35,40),(34,45)],fill='#5d172e',width=1)
    tile.putalpha(bridge)
    web.mesh(tile,(-4.25,-8.25,-4.875),px=8,depth=.25)
    item=web.item()
    item['_faces'][0]=base['_faces'][0]
    for part,side in side_parts:
        tiles=item['_faces'][part]
        item['_faces'][part]={face:side_web.copy() if face==side else Image.new('RGBA',tile.size)
                              for face,tile in tiles.items()}
        item['boxes'][part]['faces']=[side]
    crown_web=Image.new('RGBA',(68,68));d=ImageDraw.Draw(crown_web)
    for angle in range(0,360,45):
        a=math.radians(angle)
        d.line((34,34,34+math.cos(a)*68,34+math.sin(a)*68),fill='#501e2d',width=1)
    for radius in (12,25,38):
        d.line([(34+math.cos(i*math.tau/8)*radius,34+math.sin(i*math.tau/8)*radius)
                for i in range(9)],fill='#5b2030',width=1)
    for part in range(crown_start,crown_end):
        box=item['boxes'][part];tile=item['_faces'][part]['top']
        x,z=(round((box['origin'][axis]+4.25)*8) for axis in (0,2))
        tile.alpha_composite(crown_web.crop((x,z,x+tile.width,z+tile.height)))
    return item


def themed_headwear():
    """Head-fitted cloth accessories using the existing box/painted mesh rig."""
    hat=Model("head","winter-snowcap","Christmas Snowcap",
        "A crimson knitted Christmas hat with an ivory fur cuff, a curved drooping crown and a round snow-white pompom.")
    cuff=Image.new('L',(80,80));d=ImageDraw.Draw(cuff)
    d.rounded_rectangle((1,1,78,78),radius=13,fill=255)
    d.rounded_rectangle((9,9,70,70),radius=9,fill=0)
    hat.slab(cuff,-8.875,'#f0eadf',thickness=1.25,unit=.125,motif='cloth')
    hat.slab(cuff,-8.875,'#fff8e9',thickness=.25,unit=.125,motif='cloth')
    for i in range(14):
        t=i/13
        width=8.75-7.25*t
        mask=Image.new('L',(72,72));d=ImageDraw.Draw(mask)
        d.rounded_rectangle((1,1,70,70),radius=18,fill=255)
        hat.slab(mask,-9.25-i*.375,'#b83d46' if i%3 else '#c94a50',thickness=.5,
                 unit=width/72,offset=(3.75*t*t,.25*t),motif='cloth')
    hat.tube([(3.75,-14.125,.25),(4.375,-13.875,.25),(4.875,-13.25,.25),
              (5,-12.625,.25)],1.25,'#bf4149',motif='cloth')
    for i in range(9):
        y=-13.75+i*.375
        radius=math.sqrt(max(0,1.75**2-(y+12.25)**2))
        if radius<.2:continue
        mask=Image.new('L',(32,32));ImageDraw.Draw(mask).ellipse((1,1,30,30),fill=255)
        hat.slab(mask,y,'#fff8eb' if i%2 else '#e8e4d9',thickness=.5,
                 unit=radius*2/32,offset=(5,.25),motif='cloth')

    bat=bat_cowl()

    return [hat.item(),bat,spider_mask()]


def pets():
    dragon=Model("shoulder","jade-cloud-dragon","Jade Cloud Dragon","A sculpted jade cloud dragon with a long curling spine, ivory antlers, copper fins, articulated paws and flowing whiskers.")
    body=(0,-5,3);head=(-8,-8,-1)
    spine=[(-7.5,-6,1),(-6,-8,2.5),(-3.5,-9.5,4.5),(-.5,-10.5,6),
           (2,-10,7.5),(4.25,-8.5,8),(6,-6.25,7.5),(7,-3.5,6.5),
           (7.5,-.5,5.5),(7.5,2,4.5),(7,4,3.5),(6.5,5.5,2.5)]
    for i,(x,y,z) in enumerate(spine):
        thickness=3 if i<6 else max(.75,3-(i-5)*.375)
        height=max(.75,thickness-.5)
        dragon.box((x-thickness/2,y-height/2,z-thickness/2),(thickness,height,thickness),
                   '#29896e' if i%2 else '#36a081',"scale",motion="hover_body",pivot=body)
        dragon.box((x-thickness*.375,y+height*.25,z-thickness*.375),
                   (thickness*.75,.375,thickness*.75),'#c6d7b4',"scale",motion="hover_body",pivot=body)
        dragon.box((x-.375,y-height/2-.75,z-.25),(.75,.875,1),'#c18a54',"metal",motion="hover_body",pivot=body)
        if i in (2,4,6,8):
            dragon.box((x-.25,y-height/2-1.125,z-.125),(.5,.375,.75),'#f1d3a1',motion="hover_body",pivot=body)
    # Sculpted cheek, brow and snout volumes rather than a two-box cube pet.
    dragon.box((-10.25,-11.5,-3),(4.5,3.5,4.5),'#318c72',"scale",motion="hover_head",pivot=head)
    dragon.box((-10,-11.875,-2.25),(4,.5,3.5),'#4fb293',"scale",motion="hover_head",pivot=head)
    dragon.box((-9.75,-9.5,-5.5),(3.5,1.625,3),'#c1ce9e',"scale",motion="hover_head",pivot=head)
    dragon.box((-9.625,-7.875,-5.375),(3.25,.875,3.25),'#82aa82',"scale",motion="hover_head",pivot=head)
    dragon.box((-9.5,-8,-5.625),(3,.25,.25),'#254b41',motion="hover_head",pivot=head)
    for x in (-10.125,-6.875):
        dragon.box((x,-10.5,-3.25),(1,1,.375),'#e8c15c',"eye",motion="hover_head",pivot=head)
        dragon.box((x-.125,-11,-3.375),(1.25,.5,.5),'#22674f',motion="hover_head",pivot=head)
        dragon.box((x+.125,-8.25,-5.25),(.25,.5,.25),'#ffecd0',motion="hover_head",pivot=head)
    for x in (-9.5,-7):
        dragon.tube([(x,-11,0),(x,-12.25,.5),(x+.5,-13,1.5),(x+.75,-13.25,2.5)],.625,'#e4d3ad',motion="hover_head",pivot=head)
        dragon.tube([(x,-12.25,.5),(x-.625,-12.5,1.375)],.5,'#eee1bf',motion="hover_head",pivot=head)
    for side in (-1,1):
        x=-8+side*2.5
        dragon.tube([(x,-8.75,-4),(x+side*1.5,-9,-4.25),(x+side*2.5,-9.75,-3.75),
                     (x+side*3,-10.5,-3.25)],.375,'#f1e3c5',motion="hover_head",pivot=head,motif=None)
        dragon.box((x-.25,-9,.25),(.5,2,2),'#bf9159',"scale",motion="hover_head",pivot=head)
    # Two hooked feet and two smaller hind paws grip the upper back.
    for origin,delta in (((-6.5,-5,3),-1),((2,-8,6),1)):
        x,y,z=origin
        dragon.box((x,y,z),(1,2.5,1.25),'#39856d',"scale",motion="hover_body",pivot=body)
        dragon.box((x+delta*.5,y+2,z-.75),(1.5,.75,2),'#bad0a5',"scale",motion="hover_body",pivot=body)
        for toe in (0,.5,1):
            dragon.box((x+delta*.5+toe,y+2.25,z-1),(.25,.5,.5),'#f2d9b1',motion="hover_body",pivot=body)

    capsule=Model("shoulder","lantern-pilot","Lantern Pilot","A miniature ivory astronaut inside a sculpted open lantern pod with brass hinges, mint braces and a warm glowing beacon.")
    root=(-9.5,-1,0);head=(-9.5,-6.5,0)
    # Rounded pod caps keep the open cage small and light around the pilot.
    for y,color in ((-1,'#769e96'),(-10,'#5b827e')):
        mask=Image.new('L',(24,24));d=ImageDraw.Draw(mask)
        d.rounded_rectangle((1,1,22,22),radius=5,fill=255)
        capsule.slab(mask,y,color,thickness=.5,offset=(-9.5,0))
        rim=mask.copy();d=ImageDraw.Draw(rim)
        d.rounded_rectangle((3,3,20,20),radius=4,fill=0)
        capsule.slab(rim,y-.125,'#c7b37c',thickness=.25,offset=(-9.5,0))
    for x in (-12,-7.375):
        for z in (-1.875,1.5):
            capsule.box((x,-9.25,z),(.375,8.25,.375),'#abc4ae',"metal",motion="float")
            capsule.box((x-.125,-6.5,z-.125),(.625,1.125,.625),'#c9ac71',"metal",motion="float")
    capsule.box((-11.25,-9.25,2.125),(3.5,8.25,.25),'#344f58',"metal",motion="float")
    capsule.box((-10,-11.25,-.5),(1,1.5,1),'#d7be75',"gem",motion="float")
    capsule.box((-10.375,-11.625,-.875),(1.75,.375,1.75),'#eae0be',"metal",motion="float")
    # Helmet, recessed visor, raised rim and neck ring.
    capsule.box((-11,-8.875,-1.5),(3,2.5,3),'#e3ddc7',"metal",motion="hover_head",pivot=head)
    capsule.box((-10.875,-8.5,-1.75),(2.75,1.625,.25),'#243a4b',"metal",motion="hover_head",pivot=head)
    capsule.box((-10.5,-8,-1.875),(.5,.5,.125),'#8adcd0',"eye",motion="hover_head",pivot=head)
    capsule.box((-9.25,-8,-1.875),(.5,.5,.125),'#8adcd0',"eye",motion="hover_head",pivot=head)
    capsule.box((-10.375,-6.625,-.75),(1.75,.5,1.5),'#bba581',"metal",motion="hover_body",pivot=root)
    capsule.box((-10.625,-6.125,-1),(2.25,2.75,2),'#d5ccb5',"leather",motion="hover_body",pivot=root)
    capsule.box((-10.25,-5.875,-1.125),(1.5,1.75,.25),'#6c9a99',"metal",motion="hover_body",pivot=root)
    capsule.box((-10,-5.375,-1.375),(1,.625,.25),'#b7d8c5',"gem",motion="hover_body",pivot=root)
    for side in (-1,1):
        x=-9.5+side*1.5
        capsule.box((x-.375,-6.125,-.625),(.75,1.5,1.25),'#d9d4bb',"leather",motion="hover_body",pivot=root)
        capsule.box((x-.375,-4.875,-1),(.75,1,1),'#939f93',"metal",motion="hover_body",pivot=root)
        x=-10.5 if side<0 else -9.25
        capsule.box((x,-3.5,-.75),(1,1.75,1.5),'#c7c8b5',"leather",motion="hover_body",pivot=root)
        capsule.box((x-.125,-2,-1.25),(1.25,.75,2),'#667e83',"metal",motion="hover_body",pivot=root)
    return [dragon.item(),capsule.item()]


def footwear():
    shoe=Model("feet","harbor-high-tops","Harbor High Tops","Sculpted ruby and ivory high tops with padded collars, raised tongues, copper eyelets, crossed laces and layered rubber soles.")
    for side,x in (("left_leg",0),("right_leg",-4)):
        shoe.box((x-.125,23.5,-2.875),(4.25,.5,5.75),'#303138',"metal",motion=side)
        shoe.box((x-.125,22.875,-2.875),(4.25,.625,5.75),'#eee5d6',"metal",motion=side)
        shoe.box((x,21.5,-2.625),(4,1.375,5.25),'#9b3941',"leather",motion=side)
        shoe.box((x+.125,20.75,-3.125),(3.75,1.5,1.25),'#f2eee1',"leather",motion=side)
        shoe.box((x+.25,18.5,-2.375),(3.5,3.25,.5),'#ad4750',"leather",motion=side)
        shoe.box((x+.25,18.5,1.875),(3.5,3.25,.5),'#85353e',"leather",motion=side)
        for dx in (0,3.5):
            shoe.box((x+dx,18.5,-1.875),(.5,3.25,3.75),'#a8424c',"leather",motion=side)
        shoe.box((x+.75,18.25,-2.625),(2.5,3.5,.5),'#eee8d5',"leather",motion=side)
        shoe.box((x-.125,18.375,-2.375),(4.25,.625,.75),'#e9dfce',"leather",motion=side)
        shoe.box((x-.125,18.375,1.625),(4.25,.625,.75),'#d8ccbb',"leather",motion=side)
        for y in (19.375,20.125,20.875):
            for dx in (.5,3):
                shoe.box((x+dx,y,-2.875),(.5,.375,.25),'#c49c63',"metal",motion=side)
            shoe.tube([(x+.875,y,-3),(x+3.125,y+.5,-3)],.25,'#fff9e8',motion=side,motif=None)
            shoe.tube([(x+3.125,y,-3),(x+.875,y+.5,-3)],.25,'#d9d1bf',motion=side,motif=None)
        outer=x-.25 if side=='right_leg' else x+4
        shoe.box((outer,20.125,-.5),(.25,1.25,1.25),'#eadbc1',"badge",motion=side)
        for z in (-2,0,2):
            shoe.box((x-.25,23.25,z),(4.5,.25,.25),'#c9c2b4',motion=side)
    return [shoe.item()]


def generate(folder=None):
    folder=Path(folder) if folder else ROOT/"cosmetics"
    items=[*wings(),*pets(),*headwear(),*footwear()]
    for item in items:
        directory=folder/{"back":"wings","shoulder":"pets","head":"head","feet":"feet"}[item["slot"]]/"collection"
        directory.mkdir(parents=True,exist_ok=True)
        key=item["id"].removeprefix(item["slot"]+"_")
        texture=key+".png"
        image,boxes=art.render_item(item)
        image.save(directory/texture,optimize=True)
        model=dict(slot=item["slot"],texture=texture,tex_w=image.width,tex_h=image.height,
                   boxes=boxes,feathers=item.get("feathers",[]),wing_flare=item.get("wing_flare",False),
                   separate_feathers=item.get("separate_feathers",False))
        from cubeon.cosmetic_packages import normalize_wing_attachment
        model=normalize_wing_attachment(model)
        glow=glow_texture(image,key)
        if glow is not None:
            name=key+"_glow.png"
            glow.save(directory/name,optimize=True)
            model["emissive_texture"]=name
        recipe=dict(id="cubeon-"+key,name=item["name"],description=item["blurb"],model=model)
        (directory/(key+".json")).write_text(json.dumps(recipe,indent=2)+"\n")
    print(f"Generated {len(items)} original cosmetics in {folder}. Validate and publish with publish-cosmetics.sh.")
    return items


def glow_texture(image,key):
    modes={"ivory-tide":"white","cloud-fan":"white","cloudlet-headwings":"white",
           "obsidian-seraph":"gold","amethyst-fae":"violet","glacial-morpho":"blue",
           "crimson-archfiend":"red","sunward-halo":"gold","dawnflare-halo":"gold",
           "tidal-crown":"cyan","morpho-orbit":"blue","zephyr-sprite":"spirit",
           "lantern-pilot":"beacon","jade-cloud-dragon":"beacon","midnight-cowl":"lenses",
           "crimson-web-mask":"lenses"}
    mode=modes.get(key)
    if mode is None:return None
    result=Image.new('RGBA',image.size)
    pixels=result.load()
    for y in range(image.height):
        for x in range(image.width):
            r,g,b,a=image.getpixel((x,y))
            selected=(mode=='white' and min(r,g,b)>235 or
                      mode=='gold' and r>200 and g>170 and 90<b<225 or
                      mode=='violet' and r>180 and b>235 and g>70 or
                      mode=='blue' and b>215 and g>180 and r>90 or
                      mode=='red' and r>185 and g<120 and b<135 or
                      mode=='cyan' and g>165 and b>150 and r<g*.9 or
                      mode=='lenses' and min(r,g,b)>205 or
                      mode=='spirit' and (min(r,g,b)>205 or r>215 and g>180 and b<175) or
                      mode=='beacon' and (r>215 and 165<g<225 and b<150 or g>190 and b>175 and r<170))
            if a and selected:
                pixels[x,y]=(r,g,b,255)
    return result if result.getbbox() else None


if __name__=="__main__":
    generate()
