#!/usr/bin/env python3
"""Generate the approved seasonal pixel-art Play assets; run from the repo root.

Assets are separate, unmasked RGBA trees/ground and tiny particle sprites.
Runtime scales each tree uniformly and positions controls independently; it never
packages the preview screenshot or regenerates artwork during startup.
"""
from pathlib import Path
import argparse
import math
import random
from PIL import Image, ImageDraw

STYLES = {
    'autumn': {
        'shadow':'#512d20',
        'palette':['#713820','#904324','#ab5328','#bc6731','#cd7d3c','#dda052'],
        'highlights':['#ce8644','#e1ab60'],
        'bank':['#292f20','#363b23','#414529'],
        'grass':['#6a6538','#93834a','#626334','#827346'],
        'litter':['#9a5027','#bc7033','#d19543','#715037'],
    },
    'spring': {
        'shadow':'#5b3545',
        'palette':['#784052','#99516a','#b66a84','#d489a5','#e9b3c8','#f7d2df'],
        'highlights':['#edc0d2','#ffe5ed'],
        'bank':['#233828','#2e4930','#405c38'],
        'grass':['#5b7c40','#7b9c52','#446e3a','#93b263'],
        'litter':['#e3a6bd','#f5ccd9','#faf0da','#abc36a'],
        'description':'Blossoming pink trees, fresh green grass, small flowers and drifting petals.',
    },
    'summer': {
        'shadow':'#1c3b29',
        'palette':['#255137','#346842','#4b7b45','#63934f','#80aa5d','#a8c57a'],
        'highlights':['#91b56c','#b5d68b'],
        'bank':['#1e3826','#2b4730','#3e5833'],
        'grass':['#56833c','#84a953','#46763c','#a1bd64'],
        'litter':['#e9c96f','#e8e6c9','#87a5c3','#b9cf83'],
        'description':'Lush green trees, meadow flowers, tiny butterflies and softly pulsing fireflies.',
    },
    'winter': {
        'shadow':'#344f61',
        'palette':['#436479','#63869b','#8eabbc','#b2c9d4','#d4e3e9','#f0f6f8'],
        'highlights':['#dceaf0','#ffffff'],
        'bank':['#789caf','#a0bece','#cfe1e9'],
        'grass':['#94b4c6','#b4ccd9','#dae9ef','#e8f1f4'],
        'litter':['#dceaf0','#eef5f8','#a8c5d7','#bdd6e3'],
        'description':'Snow-covered trees and tilted branches, a frosted grass bank and drifting snowflakes.',
    },
}

def render(season, out):
    out.mkdir(parents=True, exist_ok=True)
    style = STYLES[season]
    def save(layer, box, name):
        layer.resize((CW*S,CH*S),Image.Resampling.NEAREST).crop(box).save(out / f'{name}.png')
    W, H = 1259, 772
    S = 3
    CW, CH = math.ceil(W/S), math.ceil(H/S)
    rng = random.Random(46)
    scene = Image.new('RGBA', (CW,CH))
    d = ImageDraw.Draw(scene)

    def block_polygon(points, fill):
        d.polygon(points, fill=fill)

    def crown(cx,cy,rx,ry):
        # Stepped silhouette; shade foliage clusters rather than smooth spheres.
        pts=[(cx-rx,cy-ry//3),(cx-rx+3,cy-ry//3),(cx-rx+3,cy-ry*2//3),
             (cx-rx//2,cy-ry*2//3),(cx-rx//2,cy-ry),(cx+rx//3,cy-ry),
             (cx+rx//3,cy-ry+4),(cx+rx*2//3,cy-ry+4),(cx+rx*2//3,cy-ry//2),
             (cx+rx,cy-ry//2),(cx+rx,cy+ry//3),(cx+rx-4,cy+ry//3),
             (cx+rx-4,cy+ry*2//3),(cx+rx//2,cy+ry*2//3),(cx+rx//2,cy+ry),
             (cx-rx//3,cy+ry),(cx-rx//3,cy+ry-4),(cx-rx*2//3,cy+ry-4),
             (cx-rx*2//3,cy+ry//2),(cx-rx,cy+ry//2)]
        silhouette=Image.new('L',(CW,CH)); ImageDraw.Draw(silhouette).polygon(pts,fill=255)
        foliage=Image.new('RGBA',(CW,CH)); p=ImageDraw.Draw(foliage)
        p.polygon(pts,fill=style['shadow'])
        palette=style['palette']
        for _ in range(165):
            x=int(rng.gauss(cx,rx*.50)); y=int(rng.gauss(cy,ry*.46))
            size=rng.choice([3,4,5,6,7,8])
            shade=min(5,max(0,int((cy+ry-y)/(2*ry)*5)+rng.choice([-1,0,1])))
            color=palette[shade]
            p.polygon([(x,y-size//2),(x+size//2,y-size//2),(x+size//2,y-2),
                       (x+size,y-2),(x+size,y+size//2),(x+size-2,y+size//2),
                       (x+size-2,y+size),(x-2,y+size),(x-2,y+1),(x,y+1)],fill=color)
            if shade>=3 and rng.random()<.62:
                p.rectangle((x,y,x+2,y+1), fill=style['highlights'][int(shade>3)])
        if season == 'winter':
            # Thick stepped snow caps follow the upper part of each crown.
            p.rectangle((cx-rx//2,cy-ry,cx+rx//3-1,cy-ry+2),fill='#f4f9fa')
            p.rectangle((cx+rx//3,cy-ry+4,cx+rx*2//3-1,cy-ry+6),fill='#e4f0f5')
            p.rectangle((cx-rx+3,cy-ry*2//3,cx-rx//2-1,cy-ry*2//3+2),fill='#e4f0f5')
        foliage.putalpha(silhouette)
        scene.alpha_composite(foliage)

    # Narrow edge trunks leave the controls accessible. Trees sit in the existing landscape.
    left_trunk=[(0,CH-6),(0,144),(3,144),(3,130),(6,130),(6,112),(11,112),
                (11,142),(9,142),(9,177),(8,177),(8,212),(12,212),(12,CH-10),(20,CH-4)]
    block_polygon(left_trunk,'#35271c')
    d.polygon([(3,CH-9),(3,160),(5,160),(5,130),(8,130),(8,179),(6,179),(6,CH-11),(12,CH-6)],fill='#76513a')
    d.line([(5,168),(18,143),(19,126)],fill='#61412c',width=4)
    d.line([(7,146),(29,127),(30,109)],fill='#493220',width=4)
    d.line([(5,200),(4,183)],fill='#ac7950',width=1)
    right_trunk=[(CW-5,CH-2),(CW-8,CH-4),(CW-8,205),(CW-10,205),(CW-10,172),
                 (CW-13,172),(CW-13,131),(CW-17,131),(CW-17,107),(CW-10,107),
                 (CW-8,139),(CW-5,139),(CW-5,201),(CW-2,201),(CW-2,CH-6),(CW,CH-2)]
    block_polygon(right_trunk,'#35271c')
    d.line([(CW-9,CH-8),(CW-9,193),(CW-11,165),(CW-12,136)],fill='#805639',width=3)
    d.line([(CW-12,155),(CW-22,136),(CW-35,129),(CW-38,113)],fill='#543720',width=4)
    d.line([(CW-7,207),(CW-6,CH-13)],fill='#bc864e',width=1)
    crown(8,111,31,30)
    crown(38,112,27,24)
    crown(21,91,28,22)
    crown(CW-7,101,35,28)
    crown(CW-38,105,29,23)
    crown(CW-27,76,26,19)
    save(scene, (0, 207, 201, H), 'left-tree')
    save(scene, (W-210, 171, W, H), 'right-tree')
    scene=Image.new('RGBA', (CW,CH)); d=ImageDraw.Draw(scene)
    # A third, wind-bent sapling grows diagonally inward below the Play controls.
    # Its trunk rises leftward from the bank, with a stepped pixel silhouette.
    d.polygon([(CW-3,CH-4),(CW-17,CH-4),(CW-27,CH-13),
               (CW-39,CH-19),(CW-52,CH-26),(CW-63,CH-34),
               (CW-76,CH-42),(CW-83,CH-48),(CW-80,CH-54),
               (CW-70,CH-49),(CW-57,CH-41),(CW-43,CH-33),
               (CW-30,CH-25),(CW-19,CH-17)],fill='#35271c')
    d.line([(CW-11,CH-7),(CW-26,CH-18),(CW-44,CH-28),
            (CW-61,CH-38),(CW-78,CH-49)],fill='#805639',width=3)
    d.line([(CW-15,CH-10),(CW-33,CH-21),(CW-48,CH-30)],fill='#bf8951',width=1)
    d.line([(CW-55,CH-35),(CW-49,CH-44),(CW-49,CH-52)],fill='#4e3523',width=3)
    d.line([(CW-65,CH-41),(CW-81,CH-38),(CW-88,CH-41)],fill='#543720',width=3)
    crown(CW-89,CH-49,19,13)
    crown(CW-68,CH-57,23,15)
    crown(CW-48,CH-52,16,11)
    if season == 'winter':
        d.line([(CW-15,CH-12),(CW-33,CH-23),(CW-48,CH-32),(CW-64,CH-42)],fill='#e1eef4',width=2)
    save(scene, (930, 558, W, H), 'tilted-tree')
    scene=Image.new('RGBA', (CW,CH)); d=ImageDraw.Draw(scene)
    # A sparse grass/leaf bank, not a solid illustrated border.
    for x in range(0,CW,3):
        if rng.random()<.68:
            y=CH-rng.randrange(2,7)
            d.rectangle((x,y,x+rng.randrange(2,5),CH),fill=rng.choice(style['bank']))
    for _ in range(150):
        x=rng.randrange(CW); y=CH-rng.randrange(2,13)
        if rng.random()<.60:
            h=rng.randrange(2,8)
            col=rng.choice(style['grass'])
            d.line((x,y,x-2,y-h),fill=col,width=1)
            d.line((x,y,x+1,y-h-2),fill=col,width=1)
        else:
            col=rng.choice(style['litter'])
            d.rectangle((x,y,x+2,y+1),fill=col)
            d.point((x+1,y-1),fill=col)
    # Seasonal bank details keep the same composition without recoloring the UI.
    if season in ('spring','summer'):
        flowers=random.Random(112)
        for i in range(28):
            x=flowers.randrange(5,CW-5); y=CH-flowers.randrange(4,12)
            d.line((x,y,x,y+4),fill=style['grass'][0],width=1)
            petals=('#f0bfd0','#e7e8ce','#d9b9de') if season=='spring' else ('#e8c463','#e9e6c9','#87a7bf')
            col=petals[i%3]
            d.rectangle((x-1,y-1,x+1,y+1),fill=col)
            d.point((x,y-2),fill=col)
            d.point((x,y),fill='#f8e4a2')
    elif season == 'winter':
        snow=random.Random(127)
        for x in range(0,CW,5):
            height=snow.randrange(2,6)
            d.rectangle((x,CH-height,x+6,CH),fill='#deedf2')
            d.rectangle((x,CH-height,x+6,CH-height),fill='#f4f9fa')
    save(scene, (0, 714, W, H), 'ground')
    def particle_sprite(tone,scale=2):
        img=Image.new('RGBA',(10,10)); q=ImageDraw.Draw(img)
        if season == 'autumn':
            rows=['....h.....','...hho....','.hhhoo.hh.','..hhooooh.','hhhooood..',
                  '.hoooood..','..ooood...','...odd....','....s.....','.....s....']
            colors=({'h':'#f0bd69','o':'#cd8239','d':'#975526','s':'#68402b'},
                    {'h':'#dc9451','o':'#b86632','d':'#803c25','s':'#61402a'},
                    {'h':'#e3b968','o':'#b39445','d':'#817339','s':'#59452b'})[tone]
            for y,row in enumerate(rows):
                for x,c in enumerate(row):
                    if c in colors: q.point((x,y),fill=colors[c])
        elif season == 'spring':
            colors=[('#fff0f5','#e6a4bf'),('#f8dce8','#c781a0'),('#faefd0','#d6be8b')][tone]
            q.polygon([(4,1),(6,1),(6,2),(8,2),(8,5),(6,5),(6,7),(3,7),(3,6),(2,6),(2,3),(4,3)],fill=colors[0])
            q.rectangle((4,4,5,6),fill=colors[1])
        elif season == 'winter':
            col=['#e8f6ff','#d1e7f5','#ffffff'][tone]
            if scale==1:
                q.rectangle((4,3,5,6),fill=col)
                q.rectangle((3,4,6,5),fill=col)
            else:
                q.line((4,1,4,7),fill=col)
                q.line((1,4,7,4),fill=col)
                q.point((2,2),fill=col); q.point((6,2),fill=col)
                q.point((2,6),fill=col); q.point((6,6),fill=col)
                q.point((4,4),fill='#ffffff')
        else:
            q.rectangle((4,4,5,5),fill='#f8eac0')
            q.rectangle((3,4,3,5),fill='#91a851')
            q.rectangle((6,4,6,5),fill='#91a851')
            q.point((4,3),fill='#b8c56a')
            q.point((5,6),fill='#b8c56a')
        return img.resize((10*scale,10*scale),Image.Resampling.NEAREST)

    def butterfly(t,tone):
        img=Image.new('RGBA',(12,10)); q=ImageDraw.Draw(img)
        col=['#f5d27a','#97bbd6','#eac6e2'][tone]
        spread=3 if math.cos(t*6)>0 else 1
        q.rectangle((5-spread,2,4,5),fill=col)
        q.rectangle((7,2,6+spread,5),fill=col)
        q.rectangle((5-spread,6,4,7),fill=col)
        q.rectangle((7,6,6+spread,7),fill=col)
        q.line((5,3,5,7),fill='#4c3c2c')
        q.line((6,3,6,7),fill='#4c3c2c')
        return img.resize((24,20),Image.Resampling.NEAREST)

    for tone in range(3):
        particle_sprite(tone).save(out / f'particle-{tone}.png')
    if season == 'summer':
        for tone in range(3):
            butterfly(0,tone).save(out / f'butterfly-{tone}-open.png')
            butterfly(math.pi/6,tone).save(out / f'butterfly-{tone}-closed.png')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'assets/play-seasons')
    args=parser.parse_args()
    for season in STYLES:
        render(season, args.out / season)
    # Roaming companions use a still pose while resting or in reduced motion.
    assets = Path(__file__).resolve().parents[1] / 'assets'
    for source in [*(assets / 'pets').glob('*.gif'), assets / 'parrot.gif']:
        with Image.open(source) as pet:
            pet.convert('RGBA').save(source.with_name(source.stem + '-rest.png'))
    print(f'Generated four seasonal Play asset sets in {args.out}')
