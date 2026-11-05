"""Bundled/custom instance icons; IDs, not paths, are stored in configuration."""
import base64
from functools import lru_cache
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile

from .paths import CUBEON_HOME

CUSTOM_DIR = Path(CUBEON_HOME) / 'instance_icons'
_CUSTOM_ID = re.compile(r'custom-[0-9a-f]{64}\Z')
_MAX_STORED_BYTES = 2 * 1024 * 1024
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
    return isinstance(icon_id,str) and (icon_id in _BY_ID or is_custom(icon_id))

def is_custom(icon_id):
    return isinstance(icon_id, str) and _CUSTOM_ID.fullmatch(icon_id) is not None

def import_image(path):
    """Store a small square copy, retaining GIF animation, and return its ID."""
    from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
    path = Path(path)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
        raise ValueError('Choose a PNG, JPG, WebP or GIF image.')
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('Choose an image smaller than 10 MB.')
    def square_frame(frame):
        picture = ImageOps.exif_transpose(frame).convert('RGBA')
        picture.thumbnail((128, 128), Image.Resampling.LANCZOS)
        square = Image.new('RGBA', (128, 128))
        square.paste(picture, ((128 - picture.width) // 2, (128 - picture.height) // 2))
        return square

    extension = '.png'
    try:
        with Image.open(path) as original:
            pixels = original.width * original.height
            if pixels > 16_000_000:
                raise ValueError('Choose an image with fewer than 16 million pixels.')
            output = io.BytesIO()
            if original.format == 'GIF' and original.is_animated:
                count = original.n_frames
                if count > 500 or pixels * count > 64_000_000:
                    raise ValueError('Choose a shorter GIF or one with smaller frames.')
                frames, durations = [], []
                loop = original.info.get('loop')
                for frame in ImageSequence.Iterator(original):
                    square = square_frame(frame)
                    # Reserve one palette index for transparency so opaque
                    # black pixels and the square's clear padding stay distinct.
                    indexed = square.convert('RGB').quantize(colors=255)
                    indexed.putpalette(indexed.getpalette()[:765] + [0, 0, 0])
                    indexed.paste(255, mask=square.getchannel('A').point(lambda alpha: 255 if alpha < 128 else 0))
                    frames.append(indexed)
                    durations.append(frame.info.get('duration', 100))
                frames[0].save(output, 'GIF', save_all=True, append_images=frames[1:],
                               duration=durations, disposal=2, transparency=255, background=255, optimize=False,
                               **({'loop': loop} if loop is not None else {}))
                extension = '.gif'
            else:
                square_frame(original).save(output, 'PNG')
    except (UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValueError("Couldn't read that image.") from error
    data = output.getvalue()
    if len(data) > _MAX_STORED_BYTES:
        raise ValueError('Choose a shorter or simpler GIF (the saved icon must fit in 2 MB).')
    icon_id = 'custom-' + hashlib.sha256(data).hexdigest()
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    dest = CUSTOM_DIR / (icon_id + extension)
    if not dest.is_file():
        fd, temporary = tempfile.mkstemp(prefix='.icon-', dir=CUSTOM_DIR)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, dest)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return icon_id

@lru_cache(maxsize=32)
def _custom_source(icon_id):
    path = CUSTOM_DIR / (icon_id + '.png')
    if not path.is_file():
        path = CUSTOM_DIR / (icon_id + '.gif')
    with path.open('rb') as stream:
        data = stream.read(_MAX_STORED_BYTES + 1)
    if len(data) > _MAX_STORED_BYTES:
        raise ValueError('Icon is too large')
    return base64.b64encode(data).decode('ascii')

def default(loader='vanilla'):
    return {'fabric':'mob-creeper','quilt':'mob-sheep','forge':'block-obsidian',
            'neoforge':'block-diamond_block','optifine':'block-glass'}.get(loader,'block-grass')

def source(icon_id=None, *, loader='vanilla'):
    if is_custom(icon_id):
        try:
            return _custom_source(icon_id)
        except (OSError, ValueError):
            return _BY_ID[default(loader)]['src']
    return _BY_ID[icon_id if valid(icon_id) else default(loader)]['src']
