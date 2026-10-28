"""Bundled SVG instance icons; IDs, not paths, are stored in configuration."""
BLOCKS = ('grass','dirt','stone','cobblestone','oak_log','oak_planks','sand','gravel',
          'glass','ice','snow','obsidian','netherrack','end_stone','bricks','bookshelf',
          'tnt','crafting_table','diamond_block','gold_block')
MOBS = ('creeper','zombie','skeleton','enderman','pig','cow','sheep','chicken','fox',
        'wolf','cat','bee','slime','magma_cube','blaze','ghast','panda','iron_golem',
        'villager','piglin')
CATALOG = tuple({'id':f'{kind}-{name}', 'name':name.replace('_',' ').title(),
                 'category':kind, 'src':f'instance_icons/{kind}-{name}.svg'}
                for kind,names in (('block',BLOCKS),('mob',MOBS)) for name in names)
_BY_ID = {item['id']:item for item in CATALOG}

def valid(icon_id):
    return isinstance(icon_id,str) and icon_id in _BY_ID

def default(loader='vanilla'):
    return {'fabric':'mob-creeper','quilt':'mob-sheep','forge':'block-obsidian',
            'neoforge':'block-diamond_block','optifine':'block-glass'}.get(loader,'block-grass')

def source(icon_id=None, *, loader='vanilla'):
    return _BY_ID[icon_id if valid(icon_id) else default(loader)]['src']
