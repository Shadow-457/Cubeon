"""Generate 20 block SVGs and 20 mob-head SVGs. No downloads or bitmap assets."""
from pathlib import Path
import random
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cubeon.instance_icons import BLOCKS,MOBS

ROOT=Path(__file__).resolve().parents[1]
PALETTES={
 'grass':['#6cad39','#85c449','#583e29','#725136'],
 'dirt':['#765436','#936845','#5a3c29'],
 'stone':['#8d9094','#a6a9ad','#73777b'],
 'cobblestone':['#7c8085','#565c62','#a0a5aa'],
 'oak_log':['#6d4c2d','#997144','#463421'],
 'oak_planks':['#bc945c','#d6b075','#956e42'],
 'sand':['#e2d198','#f6e6b5','#c6b17b'],
 'gravel':['#817c7a','#aaa19b','#5f5e5a'],
 'glass':['#83c6d3','#c3eef2','#497e8c'],
 'ice':['#6caae1','#a6d5fa','#4886bd'],
 'snow':['#eef7fa','#fffefd','#c5dbe2'],
 'obsidian':['#251d3b','#3e2e58','#130f25'],
 'netherrack':['#783538','#a04a4d','#51232b'],
 'end_stone':['#dfdfa7','#f2efc1','#bfc18b'],
 'bricks':['#a95442','#cd7057','#73382f'],
 'bookshelf':['#a77f49','#cca061','#785634'],
 'tnt':['#c94d3d','#ef7056','#90332a'],
 'crafting_table':['#9d7042','#c69859','#65482d'],
 'diamond_block':['#3ec1c8','#8be9e5','#23969e'],
 'gold_block':['#e9b72e','#ffe779','#bd8619']}
FACES={
 'creeper':(['#4e9538','#6aaf46','#83bd53'],['........','........','.##..##.','.##..##.','...##...','..####..','..####..','..#..#..'],{'#':'#142517'}),
 'zombie':(['#507b40','#648e47','#779e53'],['........','........','.##..##.','.##..##.','........','..####..','..####..','........'],{'#':'#273b27'}),
 'skeleton':(['#c7c9bc','#e0dfd4','#a5aca1'],['........','........','.##..##.','.##..##.','...##...','........','.######.','........'],{'#':'#424940'}),
 'enderman':(['#1c1626','#2d233a','#15101c'],['........','........','PP....PP','pp....pp','........','........','........','........'],{'P':'#ce82f6','p':'#874bd1'}),
 'pig':(['#eaa4a6','#f4b8b4','#d68592'],['........','........','.W#..#W.','........','..ssss..','..s##s..','..ssss..','........'],{'W':'#fff8ec','#':'#513232','s':'#dd8b98'}),
 'cow':(['#664d3f','#846851','#4d3a32'],['WW....WW','W......W','.W#..#W.','........','.ssssss.','.s#ss#s.','.ssssss.','........'],{'W':'#e9e4d7','#':'#251f1a','s':'#ae9c91'}),
 'sheep':(['#edead9','#fff4e1','#d8d4c4'],['........','.ssssss.','.s#ss#s.','.ssssss.','.ssssss.','..pppp..','...pp...','........'],{'s':'#a99a89','#':'#252a27','p':'#bd8681'}),
 'chicken':(['#eee9db','#fffdf2','#c6d1cc'],['........','........','.##..##.','........','..bbbb..','..bbbb..','...rr...','...rr...'],{'#':'#303531','b':'#eebf43','r':'#bf4d3d'}),
 'fox':(['#d98538','#efae51','#b76a31'],['##....##','........','.##..##.','........','WWWWWWWW','WWW##WWW','WWWWWWWW','WWWWWWWW'],{'#':'#322a27','W':'#f4eddb'}),
 'wolf':(['#aeb5b8','#d1d8d7','#8b959d'],['##....##','........','.##..##.','........','..WWWW..','..W##W..','..WWWW..','........'],{'#':'#343b40','W':'#e8ebdf'}),
 'cat':(['#bf935a','#dbb26e','#9b7047'],['##....##','........','.g#..#g.','........','...pp...','.######.','........','........'],{'#':'#3a342b','g':'#a7c75c','p':'#de9da0'}),
 'bee':(['#efc649','#ffdf70','#d7a635'],['##....##','........','.##..##.','.##..##.','........','########','........','########'],{'#':'#493627'}),
 'slime':(['#5dbb4a','#82d566','#4ba73c'],['........','........','.##..##.','.##..##.','........','..####..','........','........'],{'#':'#235e31'}),
 'magma_cube':(['#5a221c','#783021','#391c1c'],['........','........','.YY..YY.','.Yr..rY.','........','..rrrr..','........','........'],{'Y':'#f7c540','r':'#e4782b'}),
 'blaze':(['#d0a131','#efc94c','#a97523'],['........','........','.##..##.','.##..##.','........','..####..','........','........'],{'#':'#473421'}),
 'ghast':(['#e8e6de','#fffdf5','#c5c7c5'],['........','........','.##..##.','.tt..tt.','.tt..tt.','..####..','..####..','........'],{'#':'#5d6267','t':'#9b9ea1'}),
 'panda':(['#e8e9de','#fafbef','#d0d8ce'],['##....##','#......#','.##..##.','.W#..#W.','........','...##...','..####..','........'],{'#':'#292f33','W':'#ebeadd'}),
 'iron_golem':(['#cdd0c5','#e2e3d7','#afb6a5'],['........','........','.R#..#R.','........','...ss...','...ss...','...ss...','.vv.....'],{'R':'#893f34','#':'#433d35','s':'#94988c','v':'#5c864b'}),
 'villager':(['#b88966','#d0a27a','#926d53'],['........','########','.g#..#g.','...ss...','...ss...','...ss...','..####..','........'],{'#':'#4b3b2d','g':'#70aa6a','s':'#98704f'}),
 'piglin':(['#cb977d','#e0b099','#ae785e'],['........','........','.W#..#W.','........','..ssss..','..s##s..','..TssT..','........'],{'W':'#fff0df','#':'#473328','s':'#b47c68','T':'#faf1cf'})}

def shade(color,factor):
 return '#'+''.join(f'{max(0,min(255,round(int(color[i:i+2],16)*factor))):02x}' for i in (1,3,5))

def block(name,face,x,y,rng):
 palette=PALETTES[name]
 if name=='grass': return rng.choice(palette[:2] if face=='top' or y<2 else palette[2:])
 if name=='oak_log':
  if face=='top': return palette[min(min(x,y,7-x,7-y)%3,2)]
  return palette[x%3]
 if name=='oak_planks': return palette[2] if y%3==2 else palette[(x//4)%2]
 if name=='cobblestone': return palette[1] if y%3==0 or (x+(y//3)*2)%4==0 else rng.choice([palette[0],palette[2]])
 if name=='bricks': return '#c5baa0' if y%3==2 or (x+(y//3)*2)%4==0 else rng.choice(palette)
 if name=='bookshelf' and face!='top':
  if y in (0,3,4,7): return palette[1]
  return ['#956450','#638763','#718ba0','#d7a453','#a05842','#654c77','#c2aa80','#729d8e'][x]
 if name=='tnt':
  if face=='top': return '#443127' if x in (3,4) or y in (3,4) else palette[1]
  if 2<=y<=5: return '#342725' if y in (3,4) and x in (1,3,4,6) else '#eee4cc'
 if name=='crafting_table':
  return palette[2] if (face=='top' and (x%3==1 or y%3==1)) or (face!='top' and x in (1,6)) else palette[1]
 if name in ('diamond_block','gold_block'): return palette[2] if x in (0,7) or y in (0,7) else palette[1] if x+y<5 else palette[0]
 if name in ('glass','ice'): return palette[1] if x in (0,7) or y in (0,7) or x==y or x==y+1 else palette[0]
 return rng.choice(palette)

def generate(name,mob=False):
 rng=random.Random(name)
 grids=[]
 transforms={'top':'matrix(6.75 -3.75 6.75 3.75 10 46)','front':'matrix(6.75 3.75 0 6.75 10 46)','side':'matrix(6.75 -3.75 0 6.75 64 76)'}
 for face in ('top','front','side'):
  cells=[]
  for y in range(8):
   for x in range(8):
    if mob:
     palette,pattern,colors=FACES[name];color=rng.choice(palette)
     if face=='front' and pattern[y][x]!='.': color=colors[pattern[y][x]]
    else: color=block(name,face,x,y,rng)
    color=shade(color,1 if face=='top' else .9 if face=='front' else .72)
    cells.append(f'<rect x="{x}" y="{y}" width="1.015" height="1.015" fill="{color}"/>')
  grids.append(f'<g transform="{transforms[face]}">'+''.join(cells)+'</g>')
 label=name.replace('_',' ').title()+(' head' if mob else ' block')
 return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 144" role="img"><title>{label}</title>'+''.join(grids)+'<path d="M64 16 118 46V100L64 130 10 100V46Z M10 46 64 76 118 46 M64 76V130" fill="none" stroke="#162019" stroke-width="2" stroke-linejoin="round"/></svg>\n'

def main():
 out=ROOT/'assets/instance_icons';out.mkdir(parents=True,exist_ok=True)
 for name in BLOCKS: (out/f'block-{name}.svg').write_text(generate(name))
 for name in MOBS: (out/f'mob-{name}.svg').write_text(generate(name,True))
 print('Generated 20 block and 20 mob-head SVGs.')

if __name__=='__main__': main()
