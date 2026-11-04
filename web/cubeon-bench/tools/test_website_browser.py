#!/usr/bin/env python3
"""Exercise native textures, folder browsing, editing, 3D materials, and scrolling."""

import argparse
import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HASH_JS = """cv => {
  let hash=2166136261;
  const pixels=cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data;
  for(let i=0;i<pixels.length;i+=4)for(let j=0;j<4;j++) {
    const byte=j<3?Math.round(pixels[i+j]*pixels[i+3]/255):pixels[i+3];
    hash=Math.imul(hash^byte,16777619);
  }
  return {w:cv.width,h:cv.height,hash:hash>>>0};
}"""


def image_state(texture):
    with Image.open(ROOT / 'textures' / (texture + '.png')) as original:
        im = original.convert('RGBA')
        value = 2166136261
        pixels = bytearray(im.tobytes())
        for i in range(0, len(pixels), 4):
            for j in range(3):
                pixels[i + j] = (pixels[i + j] * pixels[i + 3] + 127) // 255
        for byte in pixels:
            value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
        return {'w': im.width, 'h': im.height, 'hash': value}


def canvas_state(page):
    return page.locator('#ec').evaluate(HASH_JS)


def assert_native(page, texture):
    with Image.open(ROOT / 'textures' / (texture + '.png')) as original:
        im = original.convert('RGBA')
        reference = {'w': im.width, 'h': im.height, 'pixels': base64.b64encode(im.tobytes()).decode('ascii')}
    error = page.locator('#ec').evaluate("""(cv, reference) => {
      if(cv.width!==reference.w||cv.height!==reference.h)return 'dimensions';
      const actual=cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data,expected=atob(reference.pixels);
      for(let i=0;i<actual.length;i+=4){
        const alpha=expected.charCodeAt(i+3);
        if(actual[i+3]!==alpha)return 'alpha at '+i/4;
        // Canvas uses premultiplied alpha, which quantizes translucent RGB values.
        const tolerance=alpha===255?0:alpha?Math.ceil(255/alpha):255;
        for(let j=0;j<3;j++)if(Math.abs(actual[i+j]-expected.charCodeAt(i+j))>tolerance)return 'color at '+i/4;
      }
      return '';
    }""", reference)
    assert not error, f'Native PNG {texture}: {error}'


def wait_texture(page, texture):
    page.wait_for_function("path => document.querySelector('#edPath').textContent===path && document.querySelector('#edArea').style.display!=='none'", arg='textures/' + texture + '.png')


def open_fixture(page, texture, kind='pack', size=16):
    identifier = page.evaluate("""options => {
      const now=Date.now(),p={id:'test'+now+Math.random(),name:options.texture,type:options.kind,
        size:options.size,pal:'meadow',texture:options.texture,created:now,edited:now};
      window.CB.D.projects.unshift(p);window.Ed.open(p);return p.id;
    }""", {'texture': texture, 'kind': kind, 'size': size})
    wait_texture(page, texture)
    return identifier


def search_texture(page, texture):
    page.locator('#edQ').fill(texture)
    page.locator('#edRes [data-id="' + texture + '"]').click()
    wait_texture(page, texture)


def preview(page):
    page.locator('#edTabs [data-id="preview"]').click()
    page.wait_for_function("document.querySelector('#pvW .pv-face') && !document.querySelector('#pvT').textContent.includes('Loading')")
    if page.locator('#pvAuto').inner_text().endswith('on'):
        page.locator('#pvAuto').click()
    page.locator('#pvReset').click()


def start_app(page, url, errors):
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.route('https://fonts.googleapis.com/**', lambda route: route.fulfill(status=200, content_type='text/css', body=''))
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function('window.Ed && window.MinecraftTextures')
    page.evaluate("window.enterApp({name:'Texture tester'})")
    page.locator('#app.on').wait_for()


def run(browser, url, artifacts):
    errors = []
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, color_scheme='light')
    page = context.new_page()
    start_app(page, url, errors)
    assert page.evaluate('window.MinecraftTextures.entries.length') == 3964
    assert page.evaluate('window.MinecraftTextures.roots.length') == 15
    page.locator('[data-go="library"]').click()
    assert page.locator('#libCount').inner_text() == '3,964 textures'
    page.locator('#libCat').select_option('entity')
    assert page.locator('#libCount').inner_text() == '743 textures'
    page.locator('#libFolders [data-folder="entity/creeper"]').click()
    page.locator('#lib-grid button[data-texture="entity/creeper/creeper"]').click()
    page.locator('#mcreate').click()
    wait_texture(page, 'entity/creeper/creeper')
    assert_native(page, 'entity/creeper/creeper')
    expected = canvas_state(page)
    identifier = page.evaluate('window.CB.D.projects[0].id')
    page.locator('[data-a="rot"]').click()
    rotated = canvas_state(page)
    assert (rotated['w'], rotated['h']) == (32, 64)
    page.locator('#edUndo').click()
    assert canvas_state(page) == expected
    page.locator('#edRedo').click()
    assert canvas_state(page) == rotated
    page.locator('#edBack').click()
    page.evaluate('()=>window.LocalStore.flush()')
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('window.Ed && window.CB')
    page.evaluate('async id=>{await window.CB.ready;return window.Ed.open(window.CB.find(id))}', identifier)
    wait_texture(page, 'entity/creeper/creeper')
    assert canvas_state(page) == rotated, 'Saved dimensions/pixels were lost'
    page.locator('[data-a="reset"]').click()
    page.wait_for_function("document.querySelector('#ec').width===64")
    assert canvas_state(page) == expected
    print('PASS: library folders, native pixels, rectangular rotation, undo/redo, and saved edits', flush=True)

    page.locator('#edCat').select_option('')
    assert page.locator('#edCount').inner_text() == '3,964 textures'
    page.locator('#edCat').select_option('entity')
    page.locator('#edFolders [data-folder="entity/player"]').click()
    page.locator('#edFolders [data-folder="entity/player/wide"]').click()
    assert 'wide' in page.locator('#edFolders').inner_text()
    search_texture(page, 'block/stone')
    assert canvas_state(page) == image_state('block/stone')
    page.locator('#edHex').fill('#FF0000')
    bounds = page.locator('#ec').bounding_box()
    page.mouse.click(bounds['x'] + bounds['width'] / 32, bounds['y'] + bounds['height'] / 32)
    assert canvas_state(page) != image_state('block/stone')
    page.locator('#edUndo').click()
    assert canvas_state(page) == image_state('block/stone')
    page.locator('#edRedo').click()
    assert page.locator('#ec').evaluate("cv=>Array.from(cv.getContext('2d').getImageData(0,0,1,1).data)") == [255, 0, 0, 255]
    print('PASS: nested editor folders, global path search, painting, and undo/redo', flush=True)

    open_fixture(page, 'block/grass_block_top')
    preview(page)
    assert page.locator('#pvW .pv-face').count() == 6
    faces = page.locator('#pvW .pv-face').evaluate_all("els=>els.map(e=>({className:e.className,texture:e.dataset.texture,padding:getComputedStyle(e).padding,width:e.getBoundingClientRect().width}))")
    assert all(f['padding'] == '0px' and f['width'] > 1 for f in faces)
    assert page.locator('.pv-face-top').get_attribute('data-texture') == 'textures/block/grass_block_top.png'
    assert page.locator('.pv-face-bottom').get_attribute('data-texture') == 'textures/block/dirt.png'
    assert page.locator('.pv-face-front').get_attribute('data-texture') == 'textures/block/grass_block_side.png'
    page.screenshot(path=str(artifacts / 'grass-preview.png'))
    old_transform = page.locator('#pvW').get_attribute('style')
    bounds = page.locator('#pvS').bounding_box()
    cx, cy = bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2
    page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + 80, cy + 30); page.mouse.up()
    assert page.locator('#pvW').get_attribute('style') != old_transform
    transform = page.locator('#pvW').get_attribute('style')
    page.mouse.wheel(0, -150)
    page.wait_for_function('previous=>document.querySelector("#pvW").getAttribute("style")!==previous', arg=transform)
    page.locator('#pvReset').click()
    assert 'rotateX(-22deg) rotateY(-35deg)' in page.locator('#pvW').get_attribute('style')
    open_fixture(page, 'block/oak_log')
    preview(page)
    assert page.locator('.pv-face-top').get_attribute('data-texture') == 'textures/block/oak_log_top.png'
    assert page.locator('.pv-face-front').get_attribute('data-texture') == 'textures/block/oak_log.png'
    print('PASS: cube face geometry, grass/log materials, drag rotation, zoom, and reset', flush=True)

    open_fixture(page, 'block/water_still')
    assert_native(page, 'block/water_still')
    preview(page)
    current = page.locator('.pv-face-front').evaluate("e=>getComputedStyle(e).backgroundImage")
    frame_size = page.locator('.pv-face-front').evaluate("""async e=>{
      const image=new Image();image.src=getComputedStyle(e).backgroundImage.slice(5,-2);await image.decode();return [image.width,image.height];
    }""")
    assert frame_size == [16, 16], 'Animated strip was stretched over a face'
    page.wait_for_function('before=>getComputedStyle(document.querySelector(".pv-face-front")).backgroundImage!==before', arg=current)
    open_fixture(page, 'item/diamond_sword')
    assert canvas_state(page) == image_state('item/diamond_sword')
    preview(page)
    assert page.locator('.pv-item-edge').count() > 0
    page.screenshot(path=str(artifacts / 'item-preview.png'))
    open_fixture(page, 'entity/player/wide/steve', kind='skin')
    assert canvas_state(page) == image_state('entity/player/wide/steve')
    preview(page)
    assert page.locator('#pvW .pv-face').count() == 72
    page.screenshot(path=str(artifacts / 'skin-preview.png'))
    print('PASS: animation frames, transparent item edges, and the real Steve skin', flush=True)

    open_fixture(page, 'gui/title/minecraft')
    assert_native(page, 'gui/title/minecraft')
    page.locator('#edZoom').evaluate("e=>{e.value=4;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    scrolling = page.locator('#edArea').evaluate("e=>{e.scrollLeft=400;e.scrollTop=200;return {x:e.scrollLeft,y:e.scrollTop,w:e.scrollWidth,cw:e.clientWidth}}")
    assert scrolling['x'] > 0 and scrolling['y'] > 0 and scrolling['w'] > scrolling['cw']
    light = page.locator('#edArea').evaluate("e=>({width:getComputedStyle(e,'::-webkit-scrollbar').width,color:getComputedStyle(e,'::-webkit-scrollbar-thumb').backgroundColor,radius:getComputedStyle(e,'::-webkit-scrollbar-thumb').borderRadius})")
    assert light['width'] == '12px' and light['radius'] == '12px'
    page.evaluate("document.documentElement.setAttribute('data-theme','dark')")
    dark = page.locator('#edArea').evaluate("e=>getComputedStyle(e,'::-webkit-scrollbar-thumb').backgroundColor")
    assert light['color'] != dark
    page.screenshot(path=str(artifacts / 'custom-scrollbars.png'))
    page.locator('#edBack').click()
    page.locator('[data-go="library"]').click()
    page.locator('#q').fill('')
    page.locator('#libCat').select_option('block')
    page.screenshot(path=str(artifacts / 'texture-library.png'))
    print('PASS: wide GUI textures, canvas scrolling, and themed custom scrollbars', flush=True)
    context.close()

    mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=1)
    phone = mobile.new_page()
    start_app(phone, url, errors)
    open_fixture(phone, 'block/grass_block_top')
    assert phone.locator('#ed').evaluate('e=>e.scrollWidth') <= 390
    phone.locator('#edL').click()
    phone.locator('#edCat').select_option('gui')
    assert phone.locator('#edCount').inner_text() == '563 textures'
    preview(phone)
    assert not phone.locator('#ed').evaluate("e=>e.classList.contains('l-open')")
    assert phone.locator('#pvW .pv-face').count() == 6
    phone.screenshot(path=str(artifacts / 'mobile-preview.png'))
    mobile.close()
    assert not errors, 'Browser errors: ' + repr(errors)
    print('PASS: mobile layout, folder drawer, and 3D preview; no JavaScript errors', flush=True)

    local = browser.new_context(viewport={'width': 1440, 'height': 900})
    local_page = local.new_page()
    start_app(local_page, (ROOT / 'index.html').as_uri(), errors)
    open_fixture(local_page, 'block/stone')
    assert canvas_state(local_page) == image_state('block/stone')
    preview(local_page)
    assert local_page.locator('#pvW .pv-face').count() == 6
    assert not errors, 'Local file errors: ' + repr(errors)
    local.close()
    print('PASS: direct file:// opening and editable local Minecraft PNGs', flush=True)


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser-path')
    parser.add_argument('--artifacts', default='/tmp/cubeon-bench-browser-checks')
    args = parser.parse_args()
    artifacts = Path(args.artifacts); artifacts.mkdir(parents=True, exist_ok=True)
    candidates = [Path('/opt/google/chrome/chrome'), *Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome')]
    executable = args.browser_path or next((str(p) for p in candidates if p.exists()), None)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable, headless=True, ignore_default_args=['--hide-scrollbars'], args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-crashpad-for-testing'])
            try:
                run(browser, f'http://127.0.0.1:{server.server_port}/index.html', artifacts)
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close()
    print('Browser checks passed. Screenshots:', artifacts)


if __name__ == '__main__':
    main()
