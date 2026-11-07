"""Image importer browser checks, invoked by test_app.py in isolated contexts."""
import io
import struct
import json
import zipfile
from PIL import Image


def fixture(image, name, kind='PNG', **options):
    out = io.BytesIO()
    image.save(out, format=kind, **options)
    return {'name': name, 'mimeType': 'image/' + {'PNG':'png','JPEG':'jpeg','WEBP':'webp'}[kind], 'buffer': out.getvalue()}


def run(browser, url, artifacts, pixel, texture):
    context = browser.new_context(viewport={'width':1440,'height':1000}, accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function('window.CB && window.Ed && window.ImageImporter')
    page.evaluate('async()=>{await CB.ready; CB.D.set.calm=true; await enterApp({name:"Image maker"})}')
    page.locator('#home-grid .first-project').click()
    page.locator('#mn').fill('Picture pack')
    page.locator('#mcreate').click()
    page.wait_for_function('document.querySelector("#edArea").style.display!=="none"')
    texture(page, 'block/stone')
    before = page.evaluate('JSON.stringify(CB.D.projects[0].edits)')
    original = pixel(page)
    stripes = Image.new('RGBA', (48,16), '#dd2233')
    stripes.paste('#22bb44', (16,0,32,16))
    stripes.paste('#2244dd', (32,0,48,16))
    source = fixture(stripes, 'three-colors.png')

    def output(x=0,y=0):
        return page.locator('#importOutput').evaluate('(cv,p)=>Array.from(cv.getContext("2d").getImageData(p[0],p[1],1,1).data)',[x,y])

    def load(file):
        page.locator('#importFile').set_input_files(file)
        page.wait_for_function('!document.querySelector("#importApply").disabled && !document.querySelector("#imageImport").hasAttribute("aria-busy")')

    def apply():
        page.locator('#importApply').click()
        page.wait_for_function('!document.querySelector("#imageImport")')
        page.evaluate('async()=>{await CB.save();await LocalStore.flush()}')

    page.locator('#canvasImport').click()
    assert page.locator('#importApply').is_disabled()
    assert page.locator('#importDestination').inner_text() == 'Stone'
    page.screenshot(path=str(artifacts/'import-empty.png'))
    load(source)
    assert output(8,8) == [34,187,68,255] and pixel(page) == original
    page.locator('#importZoom').fill('200')
    page.wait_for_function('document.querySelector("#importZoomValue").value==="200%"')
    page.locator('#importSourceCanvas').focus()
    page.keyboard.press('Shift+ArrowRight')
    page.keyboard.press('Shift+ArrowRight')
    page.wait_for_function('Array.from(document.querySelector("#importOutput").getContext("2d").getImageData(8,8,1,1).data).join() === "34,68,221,255"')
    page.locator('#importReset').click()
    page.wait_for_function('document.querySelector("#importZoomValue").value==="100%"')
    box = page.locator('#importSourceCanvas').bounding_box()
    page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
    page.mouse.down()
    page.mouse.move(box['x']+box['width']*.85,box['y']+box['height']/2,steps=10)
    page.mouse.up()
    assert output(8,8) == [34,68,221,255]
    page.locator('#importReset').click()
    page.locator('[data-fit="contain"]').click()
    page.wait_for_function('document.querySelector("#importZoomRow").hidden')
    assert output(0,0)[3] == 0 and output(8,8) == [34,187,68,255]
    page.locator('.import-details summary').click()
    page.locator('#importBackground').select_option('solid')
    page.locator('#importColor').fill('#112233')
    page.wait_for_function('Array.from(document.querySelector("#importOutput").getContext("2d").getImageData(0,0,1,1).data).join()==="17,34,51,255"')
    page.locator('#importGrid').check()
    assert page.locator('#importPreview').evaluate('e=>e.classList.contains("show-grid")')
    page.screenshot(path=str(artifacts/'import-fit-transparency.png'))
    page.locator('#importCancel').click()
    assert pixel(page) == original and page.evaluate('JSON.stringify(CB.D.projects[0].edits)') == before
    assert page.locator('#editedToday').inner_text() == '0 textures edited today'
    assert page.evaluate('document.activeElement.id') == 'canvasImport'

    page.locator('#ec').focus()
    page.keyboard.press('Control+Shift+i')
    assert page.locator('#imageImport').is_visible()
    load(source)
    page.locator('#importResolution').select_option('source')
    page.wait_for_function('document.querySelector("#importOutput").width===48 && document.querySelector("#importOutput").height===16')
    assert output(0,0) == [221,34,51,255] and output(47,0) == [34,68,221,255]
    page.locator('#importFlip').click()
    page.wait_for_function('Array.from(document.querySelector("#importOutput").getContext("2d").getImageData(0,0,1,1).data).join()==="34,68,221,255"')
    page.locator('#importRotate').click()
    page.wait_for_function('document.querySelector("#importOutput").width===16 && document.querySelector("#importOutput").height===48')
    load(source)
    page.locator('#importResolution').select_option('32')
    page.wait_for_function('document.querySelector("#importOutput").width===32')
    expected = output(0,0)
    apply()
    assert pixel(page) == expected and page.locator('#ec').evaluate('cv=>cv.width===32 && cv.height===32')
    assert page.locator('#editedToday').inner_text() == '1 texture edited today'
    page.locator('#edUndo').click()
    assert pixel(page) == original and page.locator('#ec').evaluate('cv=>cv.width===16')
    page.locator('#edRedo').click()
    assert pixel(page) == expected and page.locator('#ec').evaluate('cv=>cv.width===32')
    with page.expect_download() as event:
        page.evaluate('Ed.exportPNG()')
    exported = artifacts/'image-import-texture.png'
    event.value.save_as(exported)
    with Image.open(exported) as image:
        assert image.size == (32,32) and list(image.convert('RGBA').getpixel((0,0))) == expected

    # Exact alpha preservation, plus actual JPEG and lossless WebP decoding.
    page.locator('#canvasImport').click()
    load(fixture(Image.new('RGBA',(8,8),(255,0,0,128)), 'half-transparent.png'))
    assert output(8,8) == [255,0,0,128]
    apply()
    assert pixel(page) == [255,0,0,128]
    page.locator('#edUndo').click()
    page.locator('#canvasImport').click()
    load(fixture(Image.new('RGB',(120,80),'#345678'), 'photo.jpg','JPEG'))
    assert page.locator('#importSampling').input_value() == 'smooth'
    page.screenshot(path=str(artifacts/'import-photo.png'))
    load(fixture(Image.new('RGBA',(16,16),'#2255dd'),'pixel.webp','WEBP',lossless=True))
    assert output(0,0) == [34,85,221,255]
    page.keyboard.press('Escape')
    assert pixel(page) == expected

    # File validation is inline; failed/oversized inputs never touch the project.
    page.locator('#canvasImport').click()
    load_before = page.evaluate('JSON.stringify(CB.D.projects[0].edits)')
    page.locator('#importFile').set_input_files({'name':'fake.png','mimeType':'image/png','buffer':b'<svg>not a raster image</svg>'})
    page.wait_for_function('document.querySelector("#importFeedback").classList.contains("error")')
    assert page.locator('#importApply').is_disabled()
    huge = b'\x89PNG\r\n\x1a\n' + struct.pack('>I',13) + b'IHDR' + struct.pack('>II',100000,100000) + b'\x08\x06\x00\x00\x00' + b'\x00'*4
    page.locator('#importFile').set_input_files({'name':'too-large.png','mimeType':'image/png','buffer':huge})
    page.wait_for_function('document.querySelector("#importFeedback").textContent.includes("16 million")')
    assert page.locator('#importApply').is_disabled()
    assert page.evaluate('JSON.stringify(CB.D.projects[0].edits)') == load_before
    load(source)
    page.keyboard.press('Escape')

    # Dropping on the editor previews an image; it does not create a skin project.
    def transfer(file, target='#ec', kind='drop'):
        page.locator(target).evaluate('''(el,o)=>{
          const dt=new DataTransfer();dt.items.add(new File([new Uint8Array(o.bytes)],o.name,{type:o.type}));
          el.dispatchEvent(o.kind==='paste'?new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}):new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));
        }''', {'name':file['name'],'type':file['mimeType'],'bytes':list(file['buffer']),'kind':kind})
    transfer(source)
    page.wait_for_function('document.querySelector("#importApply")&&!document.querySelector("#importApply").disabled')
    assert page.evaluate('CB.D.projects.length') == 1
    transfer(fixture(Image.new('RGBA',(16,16),'#2255dd'),'pasted.png'), '#imageImport','paste')
    page.wait_for_function('document.querySelector("#importFileName").textContent==="pasted.png" && !document.querySelector("#importApply").disabled')
    assert output(0,0) == [34,85,221,255]
    assert page.locator('#dropZone').is_hidden()
    page.keyboard.press('Escape')
    transfer(source,kind='paste')
    page.wait_for_function('document.querySelector("#importApply")&&!document.querySelector("#importApply").disabled')
    page.keyboard.press('Escape')

    page.locator('#canvasAnimate').click()
    page.locator('#animFrames [data-frame="1"]').click()
    page.locator('#animSeconds').fill('0.35')
    page.locator('#animSeconds').press('Tab')
    sheet_before = page.evaluate('JSON.stringify(CB.D.projects[0].edits["block/stone"])')
    animation_before = page.evaluate('JSON.stringify(CB.D.projects[0].animations["block/stone"])')
    blue = fixture(Image.new('RGBA',(16,16),'#2255dd'),'frame.png')
    page.locator('#canvasImport').click()
    load(blue)
    assert page.locator('#importScope').input_value() == 'frame'
    assert page.locator('#importResolution').is_disabled()
    assert page.locator('#importOutput').evaluate('e=>e.width===32&&e.height===32')
    apply()
    assert pixel(page) == [34,85,221,255]
    assert page.evaluate('JSON.stringify(CB.D.projects[0].animations["block/stone"])') == animation_before
    raw = page.evaluate('Array.from(TextureCodec.decode(CB.D.projects[0].edits["block/stone"],CB.D.projects[0]).data.slice(0,4))')
    assert raw == expected, 'The unselected frame was changed'
    page.locator('#edUndo').click()
    assert page.evaluate('JSON.stringify(CB.D.projects[0].edits["block/stone"])') == sheet_before
    sheet = Image.new('RGBA',(32,64),'#aa2233');sheet.paste('#2255dd',(0,32,32,64))
    page.locator('#canvasImport').click()
    load(fixture(sheet,'two-frame-sheet.png'))
    page.locator('#importScope').select_option('sheet')
    page.wait_for_function('document.querySelector("#importOutput").height===64')
    apply()
    assert pixel(page) == [34,85,221,255]
    assert page.evaluate('Array.from(TextureCodec.decode(CB.D.projects[0].edits["block/stone"],CB.D.projects[0]).data.slice(0,4))') == [170,34,51,255]
    assert page.evaluate('JSON.stringify(CB.D.projects[0].animations["block/stone"])') == animation_before
    with page.expect_download() as event:
        page.evaluate('ResourcePacks.exportProject(CB.D.projects[0])')
    pack_path=artifacts/'image-import-pack.zip'
    event.value.save_as(pack_path)
    with zipfile.ZipFile(pack_path) as pack:
        with Image.open(io.BytesIO(pack.read('assets/minecraft/textures/block/stone.png'))) as png:
            assert png.size==(32,64)
            assert list(png.convert('RGBA').getpixel((0,0)))==[170,34,51,255]
            assert list(png.convert('RGBA').getpixel((0,32)))==[34,85,221,255]
        assert json.loads(pack.read('assets/minecraft/textures/block/stone.png.mcmeta'))['animation']==json.loads(animation_before)
    page.locator('#edUndo').click()
    assert page.evaluate('JSON.stringify(CB.D.projects[0].edits["block/stone"])') == sheet_before

    # Dark/mobile rendering, grid alignment, offline imports, and saved reload.
    page.wait_for_function('navigator.serviceWorker.controller && document.querySelector("#connectionBadge").dataset.ready==="true"')
    context.set_offline(True)
    page.locator('#canvasImport').click()
    load(source)
    page.evaluate('document.documentElement.dataset.theme="dark"')
    page.screenshot(path=str(artifacts/'import-dark.png'))
    page.set_viewport_size({'width':390,'height':844})
    page.locator('#importGrid').check()
    page.screenshot(path=str(artifacts/'import-mobile-dark.png'))
    assert page.locator('#imageImport').evaluate('e=>e.scrollWidth<=e.clientWidth')
    checker = page.locator('#imageImport').evaluate('e=>getComputedStyle(e).getPropertyValue("--import-check-b").trim()')
    assert checker == '#3f4741'
    page.locator('#importCancel').click()
    page.evaluate('async()=>{await CB.save();await LocalStore.flush()}')
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('window.ImageImporter && window.Ed')
    page.evaluate('async()=>{await CB.ready;await Ed.open(CB.D.projects[0])}')
    page.wait_for_function('document.querySelector("#edArea").style.display!=="none"')
    assert pixel(page) == expected
    assert page.evaluate('JSON.stringify(CB.D.projects[0].animations["block/stone"])') == animation_before
    # Failed persistence keeps the visible edit and gives honest retry feedback.
    page.locator('#canvasImport').click()
    load(blue)
    page.evaluate('()=>{window.importRealSave=LocalStore.saveState;LocalStore.saveState=()=>Promise.reject(new Error("Import save failure"))}')
    page.locator('#importApply').click()
    page.wait_for_function('document.querySelector("#toast").textContent.includes("could not be saved")')
    assert pixel(page)==[34,85,221,255]
    page.evaluate('()=>{LocalStore.saveState=window.importRealSave}')
    page.locator('#edUndo').click()
    page.evaluate('async()=>{await CB.save();await LocalStore.flush()}')
    assert pixel(page)==expected
    # Natural Minecraft tint is a separate view; imports save source RGBA.
    texture(page,'block/grass_block_top')
    page.locator('#canvasImport').click()
    load(source)
    assert page.locator('#importTint').is_checked()
    assert output(8,8)==[34,187,68,255]
    tinted=page.locator('#importTintOutput').evaluate('e=>Array.from(e.getContext("2d").getImageData(8,8,1,1).data)')
    assert tinted==[19,139,24,255]
    page.locator('#importTint').uncheck()
    page.wait_for_function('document.querySelector("#importTintOutput").hidden')
    assert output(8,8)==[34,187,68,255]
    apply()
    assert pixel(page)==[34,187,68,255]
    with page.expect_download() as event:
        page.evaluate('Ed.exportPNG()')
    grass_path=artifacts/'image-import-grass.png'
    event.value.save_as(grass_path)
    with Image.open(grass_path) as grass:
        assert list(grass.convert('RGBA').getpixel((8,8)))==[34,187,68,255]
    assert not errors, errors
    context.close()
    print('PASS: image import preview/crop/pointer/keyboard, fit/size/orientation/alpha, PNG/JPEG/WebP, cancel/apply/Undo/redo/export, validation/recovery, drag/drop/paste, frame/sheet integrity, dark/mobile and offline saved reload',flush=True)
