"""Generate 20 block SVGs and 20 mob-head SVGs. No downloads or bitmap assets."""
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cubeon.instance_icons import BLOCKS, MOBS

ROOT = Path(__file__).resolve().parents[1]

# Accurate, rich, authentic Minecraft palettes (mid-tone base, highlights, shadows, accents)
PALETTES = {
    'grass': ['#5b8e32', '#72ac3f', '#446e22', '#86c24d', '#79553a', '#906747', '#573d26', '#3b2718'],
    'dirt': ['#866043', '#9c7353', '#6f4e34', '#573d26', '#49321e'],
    'stone': ['#7b7b7b', '#8e8e8e', '#686868', '#545454', '#9e9e9e'],
    'cobblestone': ['#747474', '#8a8a8a', '#5c5c5c', '#474747', '#9c9c9c', '#383838'],
    'oak_log': ['#6b5332', '#82653e', '#544026', '#3e2e1a', '#a88c5c', '#bfa373', '#8f7447'],
    'oak_planks': ['#a68553', '#ba9863', '#8f6f40', '#775a30', '#634924'],
    'sand': ['#ded19c', '#ebe0b2', '#cfbf88', '#bdaf77', '#f4eac3'],
    'gravel': ['#7f7875', '#938c89', '#6a6461', '#534e4c', '#a69f9b'],
    'glass': ['#d4f2f7', '#ffffff', '#a8d8e6', '#72b0c4', '#458599'],
    'ice': ['#8ab4f8', '#b2d1fc', '#6596e8', '#4b7cd4', '#cde3fd'],
    'snow': ['#e8f3f8', '#ffffff', '#d3e4ed', '#bed4e0', '#a8c2d1'],
    'obsidian': ['#19132b', '#292042', '#100c1e', '#3c2e5e', '#523c7a'],
    'netherrack': ['#6d2527', '#853235', '#54191b', '#3d1012', '#994043'],
    'end_stone': ['#dedba2', '#ece9b9', '#cbca8d', '#b7b878', '#f6f4cf'],
    'bricks': ['#964639', '#ad5648', '#7e352a', '#64261c', '#cfd0d4', '#aba9ad', '#8e8c90'],
    'bookshelf': ['#a68553', '#ba9863', '#775a30', '#634924', '#b83333', '#2d68a8', '#388038', '#9c7333', '#753b8a', '#e8dfcc', '#241810'],
    'tnt': ['#db3b26', '#f0533e', '#b82a17', '#8f1c0d', '#f3eedf', '#dfd7c2', '#1e1c18', '#523a27', '#6e5138'],
    'crafting_table': ['#a68553', '#ba9863', '#8f6f40', '#775a30', '#4a331c', '#c29d66', '#d6b37c', '#5e4326', '#3b2915'],
    'diamond_block': ['#5ee5df', '#8cf5f0', '#3cc8c2', '#22a49f', '#197c78', '#bbfbf8'],
    'gold_block': ['#f7d33b', '#fae46b', '#deae1d', '#bd8e11', '#8f6805', '#fef2a8'],
}

# Authentic, expressive, canon mob faces (8x8 pixel art)
FACES = {
    'creeper': {
        'palette': ['#509b36', '#65b546', '#75c853', '#3f822a', '#346d22'],
        'pattern': [
            '........',
            '........',
            '.##..##.',
            '.##..##.',
            '...##...',
            '..####..',
            '..####..',
            '..#..#..',
        ],
        'colors': {'#': '#152516'},
    },
    'zombie': {
        'palette': ['#4e7939', '#5b8e43', '#689f4e', '#3e632c', '#335223'],
        'pattern': [
            '........',
            '........',
            '.##..##.',
            '.##..##.',
            '........',
            '..####..',
            '..#..#..',
            '........',
        ],
        'colors': {'#': '#1e331b'},
    },
    'skeleton': {
        'palette': ['#bebebe', '#d0d0d0', '#ababab', '#969696', '#e0e0e0'],
        'pattern': [
            '........',
            '........',
            '.##..##.',
            '.##..##.',
            '...##...',
            '........',
            '.######.',
            '..#..#..',
        ],
        'colors': {'#': '#333333'},
    },
    'enderman': {
        'palette': ['#121118', '#1a1924', '#0d0c12', '#232230'],
        'pattern': [
            '........',
            '........',
            '........',
            'PP....PP',
            'pp....pp',
            '........',
            '........',
            '........',
        ],
        'colors': {'P': '#d97ef8', 'p': '#8c35b8'},
    },
    'pig': {
        'palette': ['#e89da2', '#f3afb4', '#db878d', '#cc7379'],
        'pattern': [
            '........',
            '.WW..WW.',
            '.W#..#W.',
            '........',
            '..SSSS..',
            '..S##S..',
            '..SSSS..',
            '........',
        ],
        'colors': {'W': '#ffffff', '#': '#381f21', 'S': '#d6757c'},
    },
    'cow': {
        'palette': ['#4e382d', '#61483b', '#3e2b21', '#2f1f17'],
        'pattern': [
            'HH....HH',
            '........',
            '.WW..WW.',
            '.W#..#W.',
            '..ssss..',
            '.s#ss#s.',
            '..ssss..',
            '........',
        ],
        'colors': {'H': '#c7beaf', 'W': '#ffffff', '#': '#1f1611', 's': '#998679'},
    },
    'sheep': {
        'palette': ['#eae6d8', '#f8f4e6', '#d6d1c0', '#beb8a4'],
        'pattern': [
            '........',
            '.ssssss.',
            '.s#ss#s.',
            '.ssssss.',
            '.ssssss.',
            '..pppp..',
            '...pp...',
            '........',
        ],
        'colors': {'s': '#968172', '#': '#261b15', 'p': '#e09893'},
    },
    'chicken': {
        'palette': ['#ececec', '#ffffff', '#dbdbdb', '#c7c7c7'],
        'pattern': [
            '........',
            '........',
            '.#....#.',
            '.#....#.',
            '..BBBB..',
            '..BBBB..',
            '...RR...',
            '...RR...',
        ],
        'colors': {'#': '#1e1e1e', 'B': '#e59b24', 'R': '#cc2e24'},
    },
    'fox': {
        'palette': ['#d96d1e', '#ea7f2e', '#c1580e', '#a44605'],
        'pattern': [
            '##....##',
            '##....##',
            '........',
            '.#....#.',
            'WW....WW',
            'WWw##wWW',
            '..wwww..',
            '........',
        ],
        'colors': {'#': '#231814', 'W': '#f4eedb', 'w': '#ddd5be'},
    },
    'wolf': {
        'palette': ['#b8b8b8', '#cccccc', '#a3a3a3', '#8f8f8f'],
        'pattern': [
            '##....##',
            '........',
            '.#....#.',
            '.#....#.',
            '..wwww..',
            '..w##w..',
            '..wwww..',
            '........',
        ],
        'colors': {'#': '#23201d', 'w': '#dfdfdf'},
    },
    'cat': {
        'palette': ['#2a292e', '#38373e', '#1c1b20', '#48464f'],
        'pattern': [
            '##....##',
            '........',
            '..G..G..',
            '..#..#..',
            '...PP...',
            '..wwww..',
            '........',
            '........',
        ],
        'colors': {'#': '#151517', 'G': '#6eb840', 'P': '#df8d95', 'w': '#e2ded9'},
    },
    'bee': {
        'palette': ['#ebb328', '#f7c53e', '#d49b16', '#b5800a'],
        'pattern': [
            '##....##',
            '........',
            '.#....#.',
            '.B....B.',
            '..####..',
            '........',
            '########',
            '........',
        ],
        'colors': {'#': '#261b11', 'B': '#254e80'},
    },
    'slime': {
        'palette': ['#62af48', '#75c65a', '#509638', '#3f7c2b'],
        'pattern': [
            '........',
            '........',
            '..#..#..',
            '.##..##.',
            '........',
            '..####..',
            '...##...',
            '........',
        ],
        'colors': {'#': '#1e4816'},
    },
    'magma_cube': {
        'palette': ['#38110b', '#4a1912', '#2a0b06', '#5e231b'],
        'pattern': [
            '........',
            '........',
            '.YY..YY.',
            '.YR..RY.',
            '........',
            '..RRRR..',
            '..ORRO..',
            '........',
        ],
        'colors': {'Y': '#fce344', 'R': '#d83818', 'O': '#ea7524'},
    },
    'blaze': {
        'palette': ['#d98d1a', '#e8a528', '#be740e', '#9b5b05'],
        'pattern': [
            '........',
            '..YY..YY',
            '..#Y..#Y',
            '........',
            '........',
            '..####..',
            '........',
            '........',
        ],
        'colors': {'Y': '#fef162', '#': '#381604'},
    },
    'ghast': {
        'palette': ['#e8e8e8', '#f8f8f8', '#d6d6d6', '#c4c4c4'],
        'pattern': [
            '........',
            '........',
            '.##..##.',
            '.tt..tt.',
            '.tt..tt.',
            '..####..',
            '..####..',
            '........',
        ],
        'colors': {'#': '#444444', 't': '#858585'},
    },
    'panda': {
        'palette': ['#dedede', '#f0f0f0', '#cccccc', '#b8b8b8'],
        'pattern': [
            '##....##',
            '##....##',
            '.##..##.',
            '.#W..W#.',
            '........',
            '...##...',
            '..####..',
            '........',
        ],
        'colors': {'#': '#181a1c', 'W': '#ffffff'},
    },
    'iron_golem': {
        'palette': ['#c6c9be', '#d8dbd0', '#b2b5aa', '#9fa298'],
        'pattern': [
            '........',
            '........',
            '.R#..#R.',
            '........',
            '...ss...',
            '...ss...',
            '...ss...',
            '.vv.....',
        ],
        'colors': {'R': '#8c281e', '#': '#2e2520', 's': '#8a887a', 'v': '#557e3e'},
    },
    'villager': {
        'palette': ['#a66847', '#b97a57', '#935838', '#7a4529'],
        'pattern': [
            '........',
            '..####..',
            '.G#..#G.',
            '...NN...',
            '...NN...',
            '...NN...',
            '..####..',
            '........',
        ],
        'colors': {'#': '#2e1c14', 'G': '#3a7d44', 'N': '#915335'},
    },
    'piglin': {
        'palette': ['#c98971', '#d99a82', '#b3745c', '#9c5e46'],
        'pattern': [
            '........',
            '.WW..WW.',
            '.W#..#W.',
            '........',
            '..SSSS..',
            '..S##S..',
            '.TSssST.',
            '........',
        ],
        'colors': {'W': '#ffffff', '#': '#38201b', 'S': '#a8624d', 'T': '#ffea88', 's': '#783e30'},
    },
}


def shade(color, factor):
    """Accurate, perceptually grounded directional lighting."""
    return '#' + ''.join(f'{max(0, min(255, round(int(color[i:i+2], 16) * factor))):02x}' for i in (1, 3, 5))


def block_pixel(name, face, x, y, rng):
    """Authentic procedural pixel recreation for each block type."""
    p = PALETTES[name]

    if name == 'grass':
        if face == 'top':
            # Lush varied grass top
            return p[0] if (x + y * 3) % 4 == 0 else p[1] if (x * 2 + y) % 3 == 0 else p[3] if (x + y) % 5 == 0 else p[2]
        # Side faces: grass overhang dripping onto dirt
        # Hanging grass overhang varies from row 1 to row 3
        overhang = 2 + ((x * 7 + (3 if face == 'side' else 0)) % 3 == 0) - (x % 4 == 1)
        if y < overhang:
            return p[0] if y == 0 else p[1] if (x + y) % 2 == 0 else p[2]
        elif y == overhang and (x * 3 + y) % 4 == 0:
            return p[2]  # grass drip tip
        else:
            # Dirt
            d = p[4:]
            return d[0] if (x * 3 + y * 5) % 4 == 0 else d[1] if (x + y * 2) % 3 == 0 else d[3] if (x * y) % 5 == 0 else d[2]

    if name == 'dirt':
        return p[0] if (x * 3 + y * 5) % 4 == 0 else p[1] if (x + y * 2) % 3 == 0 else p[3] if (x * y) % 5 == 0 else p[2]

    if name == 'stone':
        # Classic subtle noisy stone texture with soft flecks
        return p[0] if (x * 3 + y * 7) % 5 == 0 else p[1] if (x + y * 4) % 4 == 0 else p[3] if (x * 2 + y * 3) % 7 == 0 else p[2]

    if name == 'cobblestone':
        # Stone blocks arranged with mortar lines
        is_mortar = (y in (0, 4) and (x % 4 != 2)) or (x in (0, 4) and (y % 4 != 2)) or (y == 7) or (x == 7)
        if is_mortar:
            return p[3] if (x + y) % 2 == 0 else p[5]
        return p[1] if (x + y) % 3 == 0 else p[0] if (x * y) % 2 == 0 else p[2]

    if name == 'oak_log':
        if face == 'top':
            # Tree growth rings
            dist = max(abs(x - 3.5), abs(y - 3.5))
            if dist < 1.2:
                return p[4]
            elif dist < 2.5:
                return p[5] if (x + y) % 2 == 0 else p[4]
            elif dist < 3.2:
                return p[6]
            else:
                return p[0] if (x + y) % 2 == 0 else p[2]
        else:
            # Vertical bark ridges
            col = x % 4
            if col == 0:
                return p[3]  # deep bark crevice
            elif col == 1:
                return p[1] if (y % 3 != 0) else p[0]
            elif col == 2:
                return p[0] if (y % 2 == 0) else p[2]
            else:
                return p[2]

    if name == 'oak_planks':
        # 4 horizontal wooden planks with seam lines and nail marks
        plank_idx = y // 2
        stagger = (x == 3 and plank_idx % 2 == 0) or (x == 6 and plank_idx % 2 == 1)
        if y in (1, 3, 5, 7) or stagger:
            return p[3] if not stagger else p[4]
        return p[1] if (x + plank_idx) % 3 == 0 else p[0] if (x * 2 + y) % 2 == 0 else p[2]

    if name == 'sand':
        return p[0] if (x * 2 + y * 3) % 4 == 0 else p[1] if (x + y) % 3 == 0 else p[4] if (x * y) % 7 == 0 else p[2]

    if name == 'gravel':
        return p[0] if (x * 5 + y * 3) % 4 == 0 else p[1] if (x + y * 2) % 5 == 0 else p[3] if (x * y) % 4 == 0 else p[2]

    if name == 'glass':
        # Clear glass with white diagonal reflection streaks and border rim
        is_border = (x in (0, 7) or y in (0, 7))
        is_sheen1 = (x == y and 1 <= x <= 4)
        is_sheen2 = (x == y + 3 and 3 <= x <= 6)
        if is_sheen1 or is_sheen2:
            return p[1]  # bright white reflection
        if is_border:
            return p[3] if (x + y) % 2 == 0 else p[4]
        return p[0] if (x + y) % 2 == 0 else p[2]

    if name == 'ice':
        # Translucent ice with crystal cracks
        is_crack = (x == y) or (x + y == 7 and 2 <= x <= 5) or (x in (1, 6) and y in (2, 5))
        if is_crack:
            return p[1] if (x + y) % 2 == 0 else p[4]
        return p[0] if (x * 2 + y) % 3 == 0 else p[2]

    if name == 'snow':
        return p[0] if (x + y * 2) % 3 == 0 else p[1] if (x * 3 + y) % 4 == 0 else p[2]

    if name == 'obsidian':
        # Dark purple crystal matrix with bright reflective flecks
        is_crystal = (x, y) in ((2, 2), (5, 3), (3, 6), (6, 5))
        if is_crystal:
            return p[4]
        return p[0] if (x * 2 + y * 3) % 3 == 0 else p[1] if (x + y) % 4 == 0 else p[2]

    if name == 'netherrack':
        return p[0] if (x * 3 + y * 2) % 3 == 0 else p[1] if (x + y) % 4 == 0 else p[3] if (x * y) % 5 == 0 else p[2]

    if name == 'end_stone':
        # Inverted cobblestone-like porous texture
        return p[0] if (x * 3 + y * 7) % 4 == 0 else p[1] if (x + y * 2) % 3 == 0 else p[4] if (x * y) % 6 == 0 else p[2]

    if name == 'bricks':
        # Running bond brick pattern with mortar
        mortar = (y in (0, 3, 6)) or (y < 3 and x == 3) or (3 <= y < 6 and (x in (0, 6))) or (y >= 6 and x == 3)
        if mortar:
            return p[4] if (x + y) % 2 == 0 else p[5]
        return p[1] if (x + y) % 3 == 0 else p[0] if (x * 2 + y) % 2 == 0 else p[2]

    if name == 'bookshelf':
        if face == 'top':
            return p[0] if (x + y) % 2 == 0 else p[1]
        # Side faces: wooden shelf borders containing colorful books
        if y in (0, 3, 4, 7):
            return p[2] if (x + y) % 3 == 0 else p[0]
        # Book spines
        book_colors = [p[4], p[5], p[6], p[7], p[8], p[9], p[5], p[4]]
        return book_colors[x] if y in (1, 5) else (p[10] if (x + y) % 2 == 0 else book_colors[x])

    if name == 'tnt':
        if face == 'top':
            if (x, y) in ((3, 3), (3, 4), (4, 3), (4, 4)):
                return p[6]  # central fuse
            elif (x, y) in ((2, 3), (4, 2), (5, 4), (3, 5)):
                return p[7]
            return p[0] if (x + y) % 2 == 0 else p[1]
        # Side faces: red dynamite sticks wrapped with cream "TNT" label band
        if 2 <= y <= 5:
            # White banner with TNT letters
            # T: col 1; N: col 3,4; T: col 6
            is_letter = (
                (y == 3 and x in (1, 3, 4, 6)) or
                (y == 4 and x in (1, 3, 5, 6))
            )
            return p[6] if is_letter else (p[4] if (x + y) % 2 == 0 else p[5])
        return p[1] if (x % 2 == 0) else p[0]

    if name == 'crafting_table':
        if face == 'top':
            # 3x3 crafting grid inlay
            is_grid_line = (x in (2, 5) or y in (2, 5))
            if is_grid_line:
                return p[4]
            return p[6] if (x + y) % 2 == 0 else p[5]
        # Side faces: wooden tools hanging on wood planks
        if y in (0, 7) or x in (0, 7):
            return p[3]
        if (x, y) in ((3, 2), (4, 3), (3, 4), (2, 3)):
            return p[8]  # tool head / handle
        return p[1] if (x + y) % 2 == 0 else p[0]

    if name == 'diamond_block':
        # Chiseled beveled border and glowing crystalline center
        is_border = (x in (0, 7) or y in (0, 7))
        is_inner_corner = (x, y) in ((1, 1), (6, 1), (1, 6), (6, 6))
        if is_border:
            return p[3] if (x == 7 or y == 7) else p[2]
        if is_inner_corner:
            return p[4]
        if (x + y) in (4, 5, 6, 7):
            return p[5] if (x, y) in ((2, 2), (3, 3), (4, 4)) else p[1]
        return p[0]

    if name == 'gold_block':
        # Rich beveled metallic sheen
        is_border = (x in (0, 7) or y in (0, 7))
        is_inner_corner = (x, y) in ((1, 1), (6, 1), (1, 6), (6, 6))
        if is_border:
            return p[3] if (x == 7 or y == 7) else p[2]
        if is_inner_corner:
            return p[4]
        if (x + y) in (4, 5, 6, 7):
            return p[5] if (x, y) in ((2, 2), (3, 3), (4, 4)) else p[1]
        return p[0]

    return rng.choice(p)


def generate(name, mob=False):
    rng = random.Random(name)
    grids = []
    # Isometric transformation matrices for 8x8 cube projection
    transforms = {
        'top': 'matrix(6.75 -3.75 6.75 3.75 10 46)',
        'front': 'matrix(6.75 3.75 0 6.75 10 46)',
        'side': 'matrix(6.75 -3.75 0 6.75 64 76)',
    }

    for face in ('top', 'front', 'side'):
        cells = []
        for y in range(8):
            for x in range(8):
                if mob:
                    mob_data = FACES[name]
                    palette = mob_data['palette']
                    pattern = mob_data['pattern']
                    colors = mob_data['colors']
                    color = rng.choice(palette)
                    if face == 'front':
                        char = pattern[y][x]
                        if char != '.':
                            color = colors[char]
                else:
                    color = block_pixel(name, face, x, y, rng)

                # Consistent lighting: top face (sunlight = 1.0), front (0.90), side (0.72)
                color = shade(color, 1.0 if face == 'top' else 0.90 if face == 'front' else 0.72)
                cells.append(f'<rect x="{x}" y="{y}" width="1.015" height="1.015" fill="{color}"/>')
        grids.append(f'<g transform="{transforms[face]}">' + ''.join(cells) + '</g>')

    label = name.replace('_', ' ').title() + (' head' if mob else ' block')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 144" role="img">'
        f'<title>{label}</title>'
        + ''.join(grids)
        + '<path d="M64 16 118 46V100L64 130 10 100V46Z M10 46 64 76 118 46 M64 76V130" '
        'fill="none" stroke="#162019" stroke-width="2" stroke-linejoin="round"/></svg>\n'
    )


def main():
    out = ROOT / 'assets/instance_icons'
    out.mkdir(parents=True, exist_ok=True)
    for name in BLOCKS:
        (out / f'block-{name}.svg').write_text(generate(name))
    for name in MOBS:
        (out / f'mob-{name}.svg').write_text(generate(name, True))
    print('Generated 20 block and 20 mob-head SVGs.')


if __name__ == '__main__':
    main()
