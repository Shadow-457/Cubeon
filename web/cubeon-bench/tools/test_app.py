#!/usr/bin/env python3
"""Browser workflows for editing, portable backups, Trash, and offline reloads."""
import argparse
import importlib.util
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bench_serve', ROOT / 'tools/serve.py')
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class Handler(serve.Handler):
    def log_message(self, *_):
        pass


def pixel(page, x=0, y=0):
    return page.locator('#ec').evaluate('(cv,p)=>Array.from(cv.getContext("2d").getImageData(p[0],p[1],1,1).data)', [x, y])


def draw(page, start, end=None, shift=False):
    page.locator('#ec').evaluate('''(cv,o)=>{
      const r=cv.getBoundingClientRect(), point=p=>({button:0,pointerId:17,bubbles:true,shiftKey:o.shift,
        clientX:r.left+(p[0]+.5)*r.width/cv.width,clientY:r.top+(p[1]+.5)*r.height/cv.height});
      cv.dispatchEvent(new PointerEvent('pointerdown',point(o.start)));
      if(o.end)cv.dispatchEvent(new PointerEvent('pointermove',point(o.end)));
      cv.dispatchEvent(new PointerEvent('pointerup',point(o.end||o.start)));
    }''', {'start': start, 'end': end, 'shift': shift})


def texture(page, identifier):
    page.locator('#edQ').fill(identifier)
    page.locator('#edRes button[data-id="' + identifier + '"]').click()
    page.wait_for_function('id=>document.querySelector("#edPath").textContent===id&&document.querySelector("#edArea").style.display!=="none"', arg='textures/' + identifier + '.png')


def choose_color(page, value):
    page.locator('#edCol').click()
    page.locator('#colorHex').fill(value)
    page.locator('#colorClose').click()


def choose_tool(page, name):
    button = page.locator('[data-t="' + name + '"]')
    if not button.is_visible():
        page.locator('#morePaintTools summary').click()
    button.click()


def run(browser, url, artifacts):
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
    context.route('https://fonts.googleapis.com/**', lambda route: route.fulfill(status=200, content_type='text/css', body=''))
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url, wait_until='domcontentloaded', timeout=15000)
    page.wait_for_function('window.CB && window.Ed && window.Workspace')
    page.evaluate('async()=>{await CB.ready;CB.D.set.calm=true;await enterApp({name:"Builder"})}')
    page.locator('#app.on').wait_for()
    page.wait_for_function('navigator.serviceWorker.controller && document.querySelector("#connectionBadge").dataset.ready==="true"', timeout=30000)
    page.screenshot(path=str(artifacts / 'before-home.png'))
    assert page.locator('#home-grid .first-project').count()==1
    assert page.locator('#home-grid .pc.add').count()==0
    assert page.locator('#home-lib').count()==0
    page.locator('#home-grid .first-project').click()
    page.locator('#mn').fill('Workshop pack')
    page.locator('#mcreate').click()
    page.wait_for_function('document.querySelector("#edArea").style.display!=="none" && document.querySelector("#edName").textContent==="Workshop pack"')
    pack_id = page.evaluate('CB.D.projects[0].id')
    page.wait_for_function('document.querySelector("#ec").getBoundingClientRect().height <= document.querySelector("#edArea").clientHeight-64')
    page.screenshot(path=str(artifacts / 'before-editor.png'))
    assert not page.locator('#et').is_hidden()
    raw = pixel(page)
    assert page.locator('#ec').bounding_box()['width'] >= 400
    assert page.locator('#canvasAnimate').is_visible()
    assert page.locator('#edTools .tb:visible').count() == 4
    assert page.locator('#edHex').is_hidden() and page.locator('#brushCustom').is_hidden()
    assert page.locator('#canvasPan').is_hidden() and page.locator('#canvasGrid').is_hidden()
    page.keyboard.press('l')
    assert page.locator('[data-t="line"]').is_visible() and page.locator('#canvasToolName').inner_text() == 'Line'
    page.keyboard.press('b')
    assert page.locator('#edTools .tb:visible').count() == 4
    fit_zoom = page.locator('#canvasZoomValue').inner_text()
    page.locator('#canvasZoomOut').click()
    assert page.locator('#canvasZoomValue').inner_text() != fit_zoom and pixel(page) == raw
    page.locator('#viewOptions summary').click()
    page.locator('#edZoom').evaluate('e=>{e.value=48;e.dispatchEvent(new Event("input"))}')
    page.locator('#canvasPan').click()
    bounds = page.locator('#edArea').bounding_box()
    page.mouse.move(bounds['x']+bounds['width']/2, bounds['y']+bounds['height']/2)
    page.mouse.down()
    page.mouse.move(bounds['x']+bounds['width']/2, bounds['y']+bounds['height']/2-100, steps=10)
    page.mouse.up()
    assert page.locator('#edArea').evaluate('e=>e.scrollTop') > 50
    assert pixel(page) == raw and not page.locator('#edArea').evaluate('e=>e.classList.contains("is-panning")')
    page.locator('#canvasPan').click()
    page.locator('#edFit').click()
    assert page.locator('#canvasZoomValue').inner_text() == fit_zoom
    page.locator('#canvasGrid').click()
    assert page.locator('#edWrap').evaluate('e=>e.classList.contains("nogrid")') and pixel(page) == raw
    page.locator('#canvasGrid').click()
    page.locator('#viewOptions summary').click()
    print('PASS: four default tools, advanced keyboard access, simple zoom/Fit, opt-in grid/pan and pixel-safe navigation', flush=True)
    page.locator('#canvasHelp').click()
    assert 'Create animation' in page.locator('#appDialog').inner_text()
    page.locator('#appDialogAccept').click()
    assert page.evaluate('document.activeElement===document.querySelector("#canvasHelp")')
    tinted = page.locator('#et').evaluate('cv=>Array.from(cv.getContext("2d").getImageData(0,0,1,1).data)')
    assert raw[0] == raw[1] == raw[2] and tinted[0] != tinted[2]
    page.locator('#tintToggle').click()
    assert page.locator('#et').is_hidden() and pixel(page) == raw
    page.locator('#tintToggle').click()
    assert not page.locator('#et').is_hidden() and pixel(page) == raw
    assert page.locator('#editedToday').inner_text() == '0 textures edited today'
    handle = page.locator('#resize-left').bounding_box()
    assert handle['width']==8,handle
    before_width = page.locator('#edLeft').evaluate('e=>e.getBoundingClientRect().width')
    page.mouse.move(handle['x']+4, handle['y']+100)
    page.mouse.down()
    page.mouse.move(handle['x']+68, handle['y']+100)
    page.mouse.up()
    assert page.locator('#edLeft').evaluate('e=>e.getBoundingClientRect().width') > before_width + 40
    left_width = page.locator('#edLeft').evaluate('e=>e.getBoundingClientRect().width')
    page.mouse.move(handle['x']+120, handle['y']+100)
    assert page.locator('#edLeft').evaluate('e=>e.getBoundingClientRect().width') == left_width
    assert not page.locator('#ed').evaluate('e=>e.classList.contains("resizing")')
    page.locator('#resize-right').focus()
    page.keyboard.press('ArrowLeft')
    assert page.evaluate('CB.D.set.editorRight') == 304
    handle = page.locator('#resize-right').bounding_box()
    assert handle['width'] == 8, handle
    page.mouse.move(handle['x']+4, handle['y']+100)
    page.mouse.down()
    page.mouse.move(handle['x']-60, handle['y']+100, steps=12)
    page.mouse.up()
    assert page.locator('#edRight').evaluate('e=>e.getBoundingClientRect().width') == 368
    assert page.locator('#edLeft').evaluate('e=>e.getBoundingClientRect().width') == left_width
    assert page.evaluate('CB.D.set.editorRight') == 368
    page.locator('#resize-left').focus()
    for _ in range(12):
        page.keyboard.press('ArrowRight')
    page.locator('#resize-right').focus()
    for _ in range(12):
        page.keyboard.press('ArrowLeft')
    assert page.evaluate('CB.D.set.editorLeft === 460 && CB.D.set.editorRight === 460')
    page.locator('#edBack').click()
    page.set_viewport_size({'width': 950, 'height': 900})
    page.evaluate('id=>Ed.open(CB.find(id))', pack_id)
    page.wait_for_function('document.querySelector("#edArea").style.display!=="none"')
    assert page.locator('#edC').evaluate('e=>e.getBoundingClientRect().width') >= 320
    assert page.locator('#edLeft').evaluate('e=>e.getBoundingClientRect().width') >= 180
    assert page.locator('#edRight').evaluate('e=>e.getBoundingClientRect().width') >= 248
    handle = page.locator('#resize-left').bounding_box()
    page.mouse.move(handle['x']+4, handle['y']+100)
    page.mouse.down()
    page.mouse.move(handle['x']+200, handle['y']+100, steps=12)
    page.mouse.up()
    assert page.locator('#edC').evaluate('e=>e.getBoundingClientRect().width') >= 320
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.locator('#resize-left').dblclick()
    page.locator('#resize-right').dblclick()
    print('PASS: natural colors preserve pixels; independent 8px sidebar handles stop on release, persist widths, and protect the canvas at 950px', flush=True)
    texture(page, 'block/stone')
    original = pixel(page, 0, 0)
    original_outside = pixel(page, 8, 8)
    choose_tool(page, 'select')
    draw(page, [0, 0], [3, 3])
    assert page.locator('#eo').evaluate('cv=>cv.getContext("2d").getImageData(0,0,cv.width,cv.height).data.some(v=>v!==0)')
    choose_color(page, '#CC2277')
    choose_tool(page, 'fill')
    assert page.locator('#canvasToolName').inner_text() == 'Fill'
    assert 'connected pixels' in page.locator('#canvasToolHint').inner_text()
    draw(page, [0, 0])
    assert pixel(page) == [204, 34, 119, 255]
    assert pixel(page, 8, 8) == original_outside
    page.keyboard.press('Control+c')
    page.keyboard.press('Delete')
    assert pixel(page) == [0, 0, 0, 0]
    page.locator('#edUndo').click()
    assert pixel(page) == [204, 34, 119, 255]
    page.keyboard.press('Delete')
    page.keyboard.press('Control+v')
    assert pixel(page) == [204, 34, 119, 255]
    page.keyboard.press('Escape')
    choose_tool(page, 'ellipse')
    choose_color(page, '#1278AB')
    draw(page, [4, 4], [10, 10], shift=True)
    assert pixel(page, 7, 7) == [18, 120, 171, 255]
    page.locator('#brushOptions summary').click()
    page.locator('#brushCustom').fill('8')
    choose_tool(page, 'pencil')
    draw(page, [8, 8])
    assert pixel(page, 5, 5) == [18, 120, 171, 255]
    assert original != pixel(page)
    assert page.locator('#editedToday').inner_text() == '1 texture edited today'
    assert page.locator('#texturePalette [data-texture-color="#cc2277"]').count() == 1
    page.locator('#texturePalette [data-texture-color="#cc2277"]').click()
    assert page.locator('#edHex').input_value() == '#CC2277'
    print('PASS: selection confines fill, copy/clear/paste, undo, filled ellipse, custom brush', flush=True)

    # Real native PNG download and replacement, including undoable dimensions.
    with page.expect_download() as download:
        page.locator('#edContext').click()
        page.locator('#textureExport').click()
    png_path = artifacts / 'edited-stone.png'
    download.value.save_as(png_path)
    page.locator('#texturePicker').set_input_files(str(png_path))
    page.locator('#importApply').click()
    page.wait_for_function('document.querySelector("#toast").textContent.includes("Texture replaced")')
    encoded = page.evaluate('CB.find(' + json.dumps(pack_id) + ').edits["block/stone"]')
    assert encoded['w'] == 16 and encoded['h'] == 16
    print('PASS: native texture PNG download and replacement', flush=True)

    # Skin file import is a complete project and stays byte-compatible on export.
    skin_bytes = page.evaluate('''async()=>{
      const cv=document.createElement('canvas');cv.width=cv.height=64;
      const ctx=cv.getContext('2d');ctx.fillStyle='#4488BB';ctx.fillRect(0,0,64,64);
      return Array.from(new Uint8Array(await (await new Promise(ok=>cv.toBlob(ok))).arrayBuffer()));
    }''')
    page.locator('#packImport').set_input_files({'name': 'studio-skin.png', 'mimeType': 'image/png', 'buffer': bytes(skin_bytes)})
    page.wait_for_function('document.querySelector("#edName").textContent==="studio-skin" && document.querySelector("#ec").width===64')
    assert pixel(page) == [68, 136, 187, 255]
    with page.expect_download() as skin_download:
        page.locator('#edExport').click()
    skin_download.value.save_as(artifacts / 'studio-skin.png')
    print('PASS: skin PNG import, editing project, and real download', flush=True)

    # Keep original pack binary files and shared asset IDs through backup/Trash.
    page.evaluate('''async()=>{
      const files={'pack.mcmeta':new TextEncoder().encode(JSON.stringify({pack:{pack_format:34,description:'Fixture'}})),
        'extras/data.bin':new Uint8Array([0,255,42,19])};
      await LocalStore.putFiles('fixtureasset',files);
      const p={id:'pfixtureasset',assetId:'fixtureasset',name:'Imported fixture',type:'pack',size:16,pal:'meadow',
        textures:[],packMeta:{pack:{pack_format:34,description:'Fixture'}},minecraftVersion:'imported',
        created:Date.now(),edited:Date.now(),edits:{}};CB.D.projects.push(p);await CB.save();
      Workspace.removeProject(p.id);await LocalStore.flush();
    }''')
    page.locator('#edBack').click()
    page.locator('[data-go="projects"]').first.click()
    page.locator('#pj-grid [data-id="' + pack_id + '"] .dots').click()
    page.locator('#pop [data-a="fav"]').click()
    page.locator('#ft [data-v="favorite"]').click()
    assert page.locator('#pj-grid .pc[data-id]').count() == 1
    page.locator('#ft [data-v="all"]').click()
    page.locator('#pj-grid [data-id="' + pack_id + '"] .dots').click()
    page.locator('#pop [data-a="del"]').click()
    assert page.evaluate('CB.find(' + json.dumps(pack_id) + ')===undefined')
    page.locator('[data-go="settings"]').first.click()
    page.locator('[data-settings="trash"]').click()
    assert '2 projects' in page.locator('#trashCount').inner_text()
    page.locator('[data-restore="' + pack_id + '"]').click()
    assert page.evaluate('!!CB.find(' + json.dumps(pack_id) + ')')
    print('PASS: project favorites, recoverable Trash, and restoration', flush=True)

    with page.expect_download() as backup_download:
        page.locator('[data-settings="backups"]').click()
        page.locator('#backupWorkspace').click()
    backup_path = artifacts / 'workspace.cubeon.zip'
    backup_download.value.save_as(backup_path)
    import zipfile
    with zipfile.ZipFile(backup_path) as backup:
        assert backup.testzip() is None
        manifest = json.loads(backup.read('cubeon-workspace.json'))
        assert manifest['state']['trash'][0]['name'] == 'Imported fixture'
        assert backup.read('packs/0/extras/data.bin') == bytes([0, 255, 42, 19])
    before = page.evaluate('CB.D.projects.length')
    page.locator('#workspaceImport').set_input_files(str(backup_path))
    page.locator('#appDialogAccept').click()
    page.wait_for_function('n=>CB.D.projects.length===n*2', arg=before)
    assert page.evaluate('new Set(CB.D.projects.concat(CB.D.trash).map(p=>p.id)).size===CB.D.projects.length+CB.D.trash.length')
    assert page.evaluate('''async()=>{
      const p=CB.D.trash.find(p=>p.name==='Imported fixture'&&p.assetId!=='fixtureasset');
      return Array.from((await LocalStore.getFiles(p.assetId))['extras/data.bin']);
    }''') == [0, 255, 42, 19]
    print('PASS: real workspace ZIP, independent archive validation, merge restore, binary files, unique IDs', flush=True)

    # Invalid backups must leave data unchanged; atomic storage failure keeps D unchanged.
    before_ids = page.evaluate('CB.D.projects.map(p=>p.id)')
    failures = page.evaluate('''async()=>{
      const blob=await Workspace.buildBackup(),b=await Workspace.inspectBackup(blob);
      const commit=LocalStore.commitWorkspace;LocalStore.commitWorkspace=async()=>{throw Error('simulated storage full')};
      let failed=false;try{await Workspace.restoreBackup(b,false)}catch(e){failed=e.message==='simulated storage full'}finally{LocalStore.commitWorkspace=commit}
      const files=fflate.unzipSync(new Uint8Array(await blob.arrayBuffer()));
      const data=JSON.parse(new TextDecoder().decode(files['cubeon-workspace.json']));
      data.state.projects[0].id='p"><img src=x onerror=alert(1)>';
      files['cubeon-workspace.json']=new TextEncoder().encode(JSON.stringify(data));
      let invalid=false;try{await Workspace.inspectBackup(await BenchArchive.write(files))}catch(e){invalid=true}
      return {failed,invalid};
    }''')
    assert failures == {'failed': True, 'invalid': True}
    assert before_ids == page.evaluate('CB.D.projects.map(p=>p.id)')
    print('PASS: failed restores and invalid backups preserve current projects', flush=True)

    page.keyboard.press('Control+k')
    page.locator('#commandSearch').fill('Workshop pack')
    page.locator('#commandResults button').first.click()
    page.wait_for_function('document.querySelector("#ed").classList.contains("show")')
    page.locator('#edBack').click()
    page.keyboard.press('F1')
    assert 'Copy / cut / paste' in page.locator('#appDialogContent').inner_text()
    page.locator('#appDialogAccept').click()
    page.screenshot(path=str(artifacts / 'desktop-projects.png'))
    print('PASS: keyboard quick actions, project search, help dialog, and focus return', flush=True)

    # Restart the app while completely offline and open a texture never requested.
    page.evaluate('async()=>{await CB.save();await LocalStore.flush()}')
    context.set_offline(True)
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('window.CB && window.Ed && document.querySelector("#app").classList.contains("on")')
    assert page.evaluate('CB.D.projects.length') == before * 2
    page.evaluate('async id=>{await CB.ready;await Ed.open(CB.find(id))}', pack_id)
    texture(page, 'block/stone')
    assert pixel(page) == [204, 34, 119, 255]
    texture(page, 'item/wooden_hoe')
    assert page.locator('#ec').evaluate('cv=>cv.width') == 16
    choose_color(page, '#33EE77')
    choose_tool(page, 'pencil')
    draw(page, [0, 0])
    assert pixel(page) == [51, 238, 119, 255]
    with page.expect_download() as offline_download:
        page.locator('#edExport').click()
    offline_download.value.save_as(artifacts / 'offline-pack.zip')
    with zipfile.ZipFile(artifacts / 'offline-pack.zip') as backup:
        assert 'assets/minecraft/textures/item/wooden_hoe.png' in backup.namelist()
        assert backup.testzip() is None
    page.screenshot(path=str(artifacts / 'offline-editor.png'))
    print('PASS: offline page reload, reopened edits, unvisited vanilla texture, painting, playable pack download', flush=True)
    context.set_offline(False)
    # 3D preview stays pinned when the open-texture list overflows.
    for identifier in ['block/dirt','block/oak_log','block/diamond_ore','block/andesite','block/granite','block/sand','block/gravel','block/coal_ore','block/iron_ore','block/gold_ore','block/copper_ore','block/emerald_ore','block/netherrack','block/soul_sand','block/obsidian']:
        texture(page, identifier)
    page.locator('#textureTabs').evaluate('e=>e.scrollLeft=e.scrollWidth')
    preview_box=page.locator('#edTabs [data-id="preview"]').bounding_box()
    assert preview_box['x']+preview_box['width']<=1440
    assert page.locator('#textureTabs').evaluate('e=>e.scrollWidth>e.clientWidth')
    assert page.locator('#editedToday').inner_text() == '2 textures edited today'
    page.evaluate('()=>document.documentElement.setAttribute("data-theme","dark")')
    page.wait_for_function('getComputedStyle(document.querySelector("#edWrap")).backgroundColor==="rgb(32, 38, 33)"')
    page.screenshot(path=str(artifacts / 'dark-editor.png'))
    print('PASS: pinned 3D preview with overflowing tabs, unique daily texture count, dark transparency checkerboard', flush=True)
    page.locator('#edBack').click()
    page.locator('[data-go="settings"]').first.click()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.locator('[data-settings="profile"]').click()
    page.screenshot(path=str(artifacts / 'mobile-settings.png'))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate('Array.from(document.querySelectorAll("body *")).filter(e=>e.getBoundingClientRect().right>innerWidth+1&&getComputedStyle(e).display!=="none").slice(0,20).map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().width,e.getBoundingClientRect().right])')
    page.locator('[data-settings="backups"]').click()
    page.locator('#restoreWorkspace').scroll_into_view_if_needed()
    page.locator('#workspaceImport').set_input_files(str(backup_path))
    page.locator('#appDialog').wait_for()
    box = page.locator('#appDialog').bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 390
    page.screenshot(path=str(artifacts / 'mobile-restore.png'))
    page.locator('#appDialogCancel').click()
    print('PASS: mobile settings and backup review fit a 390px viewport', flush=True)
    if page.locator('#workspaceTaskClose').is_visible():
        page.locator('#workspaceTaskClose').click()
    page.evaluate('CB.newProject({type:"pack",texture:"block/stone"})')
    page.locator('#mn').fill('Animation basics')
    page.locator('#mcreate').click()
    page.wait_for_function('document.querySelector("#edName").textContent==="Animation basics" && document.querySelector("#edArea").style.display!=="none" && document.querySelector("#edPath").textContent!==""')
    assert page.locator('#edFit').is_visible() and page.locator('#canvasAnimate').is_visible()
    source = pixel(page)
    page.locator('#canvasAnimate').click()
    page.wait_for_function('document.querySelectorAll("#animFrames .anim-row").length===2')
    assert page.locator('#edFrames').is_visible()
    assert page.locator('#animPlay').is_visible() and page.locator('#animSeconds').is_visible()
    assert page.locator('#animTime').is_hidden() and page.locator('#animRemove').is_hidden()
    page.locator('#animSeconds').fill('0.25')
    page.locator('#animSeconds').press('Tab')
    assert page.locator('#animTime').input_value() == '5'
    page.locator('#animSeconds').fill('0.12')
    page.locator('#animSeconds').press('Tab')
    assert page.locator('#animSeconds').input_value() == '0.1' and page.locator('#animTime').input_value() == '2'
    page.locator('#edUndo').click()
    assert page.locator('#animSeconds').input_value() == '0.25'
    page.locator('#animSeconds').fill('0')
    page.locator('#animSeconds').press('Tab')
    assert page.locator('#animSeconds').input_value() == '0.25' and page.locator('#animTime').input_value() == '5'
    page.locator('#animFrames [data-frame="1"]').click()
    assert page.locator('#edFrames').is_hidden()
    assert page.locator('#canvasDocumentMeta').inner_text() == 'Editing frame 2 of 2'
    assert pixel(page) == source
    page.locator('#edFramesToggle').click()
    page.locator('[data-anim-action="add"]').click()
    assert page.locator('#animFrames .anim-row').count() == 3
    page.locator('#edFramesClose').click()
    page.locator('#edUndo').click()
    page.locator('#edFramesToggle').click()
    assert page.locator('#animFrames .anim-row').count() == 2
    page.locator('#animPlay').click()
    page.wait_for_function('document.querySelector("#edAnimation").dataset.playingFrame==="1"')
    assert pixel(page) == source
    page.locator('#animPlay').click()
    page.screenshot(path=str(artifacts / 'mobile-animation-basics.png'))
    print('PASS: mobile Create animation, seconds-to-ticks timing, select-and-paint drawer, add-frame undo and pixel-safe playback', flush=True)
    assert not errors, errors
    context.close()


def run_logout(browser, url, artifacts):
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function('window.CB && window.Ed')
    page.evaluate('async()=>{await CB.ready;CB.D.set.calm=true;await enterApp({name:"Builder"})}')
    page.locator('#app.on').wait_for()
    page.wait_for_function('navigator.serviceWorker.controller && document.querySelector("#connectionBadge").dataset.ready==="true"', timeout=30000)
    page.locator('#home-grid .first-project').click()
    page.locator('#mn').fill('Keep after logout')
    page.locator('#mcreate').click()
    page.wait_for_function('document.querySelector("#ed").classList.contains("show") && document.querySelector("#edArea").style.display!=="none" && document.querySelector("#edName").textContent==="Keep after logout" && document.querySelector("#edPath").textContent!==""')
    choose_color(page, '#CC2277')
    draw(page, [0, 0])
    assert pixel(page) == [204, 34, 119, 255]
    page.locator('#edBack').click()
    page.locator('[data-go="settings"]').first.click()
    for section in ['profile', 'appearance', 'editor', 'workspace', 'offline', 'backups', 'trash']:
        page.locator('[data-settings="' + section + '"]').click()
        assert page.get_by_role('button', name='Log out', exact=True).is_visible()
    page.locator('[data-settings="profile"]').click()
    page.screenshot(path=str(artifacts / 'settings-logout.png'))
    snapshot = page.evaluate('''async()=>{
      const saved=CB.save();await LocalStore.flush();await saved;
      return JSON.parse(JSON.stringify({projects:CB.D.projects,trash:CB.D.trash,
        profile:CB.D.profile,set:CB.D.set,textureActivity:CB.D.textureActivity}));
    }''')
    # A failed save keeps the session open and allows retrying.
    page.evaluate('()=>{window.realSaveState=LocalStore.saveState;LocalStore.saveState=()=>Promise.reject(new Error("Test save failure"))}')
    page.locator('#lo').click()
    page.wait_for_function('document.querySelector("#toast").textContent.includes("could not be saved")')
    assert page.locator('#app.on').is_visible() and page.evaluate('CB.D.signedIn')
    assert page.locator('#lo').is_enabled() and page.locator('#lo').inner_text() == 'Log out'
    page.evaluate('()=>{LocalStore.saveState=realSaveState}')
    # Leaving waits for the save promise, even if storage is slow.
    page.evaluate('''()=>{LocalStore.saveState=state=>realSaveState(state).then(ok=>new Promise(resolve=>{
      window.finishLogoutSave=()=>{LocalStore.saveState=realSaveState;resolve(ok)};
    }))}''')
    page.locator('#lo').click()
    page.wait_for_function('typeof window.finishLogoutSave==="function"')
    assert page.locator('#app.on').is_visible() and page.locator('#lo').is_disabled()
    assert page.locator('#lo').inner_text() == 'Saving…'
    page.evaluate('finishLogoutSave()')
    page.wait_for_function('!document.querySelector("#app").classList.contains("on")')
    page.wait_for_function('document.activeElement===document.querySelector("#guest")')
    context.set_offline(True)
    page.reload(wait_until='domcontentloaded')
    page.evaluate('async()=>{await CB.ready}')
    assert not page.locator('#app').is_visible() and not page.evaluate('CB.D.signedIn')
    assert page.evaluate('({projects:CB.D.projects,trash:CB.D.trash,profile:CB.D.profile,set:CB.D.set,textureActivity:CB.D.textureActivity})') == snapshot
    # The returning welcome button opens the preserved workspace without onboarding.
    page.locator('#guest').click()
    page.locator('#app.on').wait_for()
    page.locator('#usr').click()
    assert page.locator('#pop').get_by_role('button', name='Log out', exact=True).is_visible()
    page.screenshot(path=str(artifacts / 'profile-logout.png'))
    page.locator('#pop').get_by_role('button', name='Log out', exact=True).click()
    page.wait_for_function('!document.querySelector("#app").classList.contains("on")')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.locator('#guest').click()
    page.locator('#app.on').wait_for()
    page.locator('[data-go="settings"]').first.click()
    assert page.locator('#lo').is_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(artifacts / 'mobile-settings-logout.png'))
    page.locator('#avb').click()
    page.locator('#pop').get_by_role('button', name='Log out', exact=True).click()
    page.wait_for_function('!document.querySelector("#app").classList.contains("on")')
    page.reload(wait_until='domcontentloaded')
    page.evaluate('async()=>{await CB.ready}')
    assert not page.locator('#app').is_visible() and not page.evaluate('CB.D.signedIn')
    assert page.evaluate('CB.D.projects') == snapshot['projects']
    assert not errors, errors
    context.close()
    print('PASS: visible Settings/profile logout on desktop/mobile, pending-save wait, failure retry, offline reload stays logged out and preserves edits/preferences', flush=True)


def run_animation_frames(browser, url, artifacts):
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True, has_touch=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function('window.CB && window.Ed && window.Workspace')
    page.evaluate('async()=>{await CB.ready;CB.D.set.calm=true;await enterApp({name:"Animator"})}')
    fixture = page.evaluate('''async()=>{
      const cv=document.createElement('canvas');cv.width=16;cv.height=64;
      const ctx=cv.getContext('2d');
      ['#DD2233','#22AA44','#2233DD','#BB66CC'].forEach((color,i)=>{ctx.fillStyle=color;ctx.fillRect(0,i*16,16,16)});
      const png=new Uint8Array(await (await new Promise(ok=>cv.toBlob(ok))).arrayBuffer());
      const files={'pack.mcmeta':new TextEncoder().encode(JSON.stringify({pack:{pack_format:34,description:'Animation fixture'}})),
        'assets/minecraft/textures/block/stone.png':png,
        'assets/minecraft/textures/block/stone.png.mcmeta':new TextEncoder().encode(JSON.stringify({texture:{blur:false},animation:{frametime:2,frames:[0,{index:2,time:5},1,{index:0,time:3}]}}))};
      return {zip:Array.from(new Uint8Array(await (await BenchArchive.write(files)).arrayBuffer())),png:Array.from(png),
        pixels:TextureCodec.encode(ctx.getImageData(0,0,16,64)).pixels};
    }''')
    page.locator('#packImport').set_input_files({'name': 'Frame studio.zip', 'mimeType': 'application/zip', 'buffer': bytes(fixture['zip'])})
    page.wait_for_function('document.querySelectorAll("#animFrames .anim-row").length===4')
    project_id = page.evaluate('CB.D.projects[0].id')
    assert page.locator('#edFrames #animPreview').is_visible()
    assert page.locator('#edRight #edAnimation').count() == 0
    assert page.locator('#canvasDocumentMeta').inner_text() == 'Editing frame 1 of 4'
    assert page.locator('#animTime').is_hidden() and page.locator('#animAllTime').is_hidden()
    page.screenshot(path=str(artifacts / 'simple-animation.png'))
    assert pixel(page) == [221, 34, 51, 255]
    rail = page.locator('#edFrames').bounding_box()
    tools = page.locator('#edRight').bounding_box()
    canvas = page.locator('#edC').bounding_box()
    assert rail['x'] == canvas['x'] + canvas['width'] and rail['x'] + rail['width'] == tools['x']
    assert tools['x'] + tools['width'] == 1440
    assert page.locator('#edC').evaluate('e=>e.getBoundingClientRect().width') >= 320
    # The desktop close button releases the panel's space without changing data.
    page.locator('#edFramesClose').click()
    assert page.locator('#edFrames').is_hidden()
    assert page.locator('#edFramesToggle').get_attribute('aria-expanded') == 'false'
    assert page.locator('#edC').evaluate('e=>e.getBoundingClientRect().width') == canvas['width'] + rail['width']
    assert pixel(page) == [221, 34, 51, 255]
    page.locator('#edBack').click()
    page.evaluate('id=>Ed.open(CB.find(id))', project_id)
    page.wait_for_function('document.querySelector("#edArea").style.display!=="none"')
    assert page.locator('#edFrames').is_hidden()
    page.locator('#edFramesToggle').click()
    assert page.locator('#edFramesToggle').get_attribute('aria-expanded') == 'true'
    assert page.locator('#edFrames').is_visible()
    # Tools stay at the right edge; its divider resizes only that sidebar.
    tools = page.locator('#edRight').bounding_box()
    handle = page.locator('#resize-right').bounding_box()
    assert handle['x'] + 4 == tools['x']
    page.mouse.move(handle['x']+4, handle['y']+100)
    page.mouse.down()
    page.mouse.move(handle['x']-28, handle['y']+100, steps=8)
    page.mouse.up()
    assert page.locator('#edRight').evaluate('e=>e.getBoundingClientRect().width') == tools['width'] + 32
    assert page.locator('#edFrames').evaluate('e=>e.getBoundingClientRect().width') == 224
    page.locator('#resize-right').dblclick()
    # Exercise real motion, including reversing a close before it finishes.
    motion = page.evaluate('''async()=>{
      CB.D.set.calm=false;CB.renderAll();
      const rail=document.querySelector('#edFrames'), grid=document.querySelector('.edmn');
      const delay=ms=>new Promise(ok=>setTimeout(ok,ms));
      document.querySelector('#edFramesClose').click();
      await delay(70);
      const middle={width:parseFloat(getComputedStyle(grid).getPropertyValue('--frames-width')),
        hidden:rail.hidden,inert:rail.inert,animations:rail.getAnimations().length,
        gridClass:document.querySelector('#ed').className,transition:getComputedStyle(grid).transitionDuration};
      document.querySelector('#edFramesToggle').click();
      await delay(360);
      const reopened=!rail.hidden&&!rail.inert&&document.querySelector('#edFramesToggle').getAttribute('aria-expanded')==='true';
      document.querySelector('#edFramesClose').click();await delay(40);
      CB.D.set.calm=true;CB.renderAll();
      const cancelled=rail.hidden&&rail.getAnimations().length===0;
      document.querySelector('#edFramesToggle').click();
      return {middle,reopened,cancelled};
    }''')
    assert 0 < motion['middle']['width'] < 224, motion
    assert not motion['middle']['hidden'] and motion['middle']['inert'] and motion['middle']['animations'] > 0, motion
    assert motion['reopened'] and motion['cancelled'], motion
    page.emulate_media(reduced_motion='reduce')
    page.evaluate('()=>{CB.D.set.calm=false;CB.renderAll();document.querySelector("#edFramesClose").click()}')
    assert page.locator('#edFrames').is_hidden()
    assert page.evaluate('Motion.reduced()')
    page.locator('#edFramesToggle').click()
    assert page.locator('#edFrames').evaluate('e=>e.getAnimations().length') == 0
    page.emulate_media(reduced_motion='no-preference')
    page.evaluate('()=>{CB.D.set.calm=false;CB.renderAll()}')
    assert page.locator('#animFrames [data-frame="1"] small').inner_text() == '0.25 s'
    assert page.locator('#animFrames [data-frame="1"] canvas').evaluate('cv=>Array.from(cv.getContext("2d").getImageData(32,32,1,1).data)') == [34, 51, 221, 255]
    page.locator('#animFrames [data-frame="1"]').click()
    assert page.locator('#canvasDocumentMeta').inner_text() == 'Editing frame 2 of 4'
    assert page.locator('#animSeconds').input_value() == '0.25'
    handle = page.locator('#animFrames .anim-drag[data-step="1"]').bounding_box()
    target = page.locator('#animFrames .anim-drag[data-step="3"]').bounding_box()
    page.mouse.move(handle['x'] + handle['width']/2, handle['y'] + handle['height']/2)
    page.mouse.down()
    page.mouse.move(target['x'] + target['width']/2, target['y'] + target['height']/2, steps=15)
    page.mouse.up()
    assert page.locator('#animFrames').evaluate('e=>Array.from(e.querySelectorAll(".anim-row")).some(row=>row.getAnimations().length>0)')
    page.wait_for_function('Array.from(document.querySelectorAll("#animFrames .anim-row")).every(row=>row.getAnimations().length===0)')
    page.evaluate('()=>{CB.D.set.calm=true;CB.renderAll()}')
    expected = [0, 1, {'index': 0, 'time': 3}, {'index': 2, 'time': 5}]
    assert page.evaluate('id=>CB.find(id).animations["block/stone"].frames', project_id) == expected
    assert pixel(page) == [34, 51, 221, 255]
    assert page.evaluate('id=>CB.find(id).edits["block/stone"].pixels', project_id) == fixture['pixels']
    assert not page.locator('#animFrames').evaluate('e=>e.classList.contains("is-reordering")')
    page.locator('#edUndo').click()
    assert page.locator('#animFrames [data-frame="1"] small').inner_text() == '0.25 s'
    assert pixel(page) == [34, 51, 221, 255]
    page.locator('#edRedo').click()
    page.locator('#animFrames .anim-drag[data-step="3"]').focus()
    page.keyboard.press('Alt+ArrowUp')
    assert page.locator('#animFrames [data-frame="2"]').get_attribute('aria-pressed') == 'true'
    page.locator('.animation-options summary').click()
    page.locator('#animTime').fill('7')
    page.locator('#animTime').press('Tab')
    assert page.locator('#animFrames [data-frame="2"] small').inner_text() == '0.35 s'
    # Cancelled drags leave the sequence untouched.
    before_cancel = page.evaluate('id=>CB.find(id).animations["block/stone"].frames', project_id)
    handle = page.locator('#animFrames .anim-drag[data-step="2"]').bounding_box()
    page.mouse.move(handle['x']+12, handle['y']+28)
    page.mouse.down()
    page.mouse.move(handle['x']+12, handle['y']-100, steps=8)
    page.locator('#animFrames').dispatch_event('pointercancel')
    page.mouse.up()
    assert page.evaluate('id=>CB.find(id).animations["block/stone"].frames', project_id) == before_cancel
    page.evaluate('()=>document.documentElement.setAttribute("data-theme","dark")')
    page.screenshot(path=str(artifacts / 'animation-frame-rail.png'))
    with page.expect_download() as download:
        page.locator('#edExport').click()
    export_path = artifacts / 'animation-frames.zip'
    download.value.save_as(export_path)
    import io
    import zipfile
    from PIL import Image
    with zipfile.ZipFile(export_path) as archive:
        metadata = json.loads(archive.read('assets/minecraft/textures/block/stone.png.mcmeta'))
        assert metadata['animation']['frames'] == before_cancel
        assert metadata['texture'] == {'blur': False}
        with Image.open(io.BytesIO(archive.read('assets/minecraft/textures/block/stone.png'))) as exported, Image.open(io.BytesIO(bytes(fixture['png']))) as source:
            assert exported.size == source.size and exported.convert('RGBA').tobytes() == source.convert('RGBA').tobytes()
    page.locator('#edBack').click()
    page.evaluate('id=>Ed.open(CB.find(id))', project_id)
    page.wait_for_function('document.querySelector("#edArea").style.display!=="none"')
    assert page.locator('#animFrames [data-frame="2"] small').inner_text() == '0.35 s'
    assert pixel(page) == [34, 51, 221, 255]
    page.set_viewport_size({'width': 1101, 'height': 900})
    assert page.locator('#edC').evaluate('e=>e.getBoundingClientRect().width') >= 320
    page.locator('#edFramesToggle').click()
    assert page.locator('#edFrames').is_hidden()
    page.locator('#edFramesToggle').click()
    page.set_viewport_size({'width': 950, 'height': 900})
    page.locator('#edFramesToggle').click()
    rail = page.locator('#edFrames').bounding_box()
    tools = page.locator('#edRight').bounding_box()
    assert rail['x'] + rail['width'] == tools['x']
    page.locator('#edFramesClose').click()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.locator('#edFramesToggle').click()
    rail = page.locator('#edFrames').bounding_box()
    assert rail['x'] >= 0 and rail['x'] + rail['width'] <= 390
    assert page.locator('#ed').evaluate('e=>e.scrollWidth') <= 390
    page.screenshot(path=str(artifacts / 'mobile-animation-frames.png'))
    page.locator('#edFramesClose').click()
    assert not page.locator('#ed').evaluate('e=>e.classList.contains("frames-open")')
    page.locator('#edFramesToggle').click()
    page.locator('.animation-options summary').click()
    page.locator('#animToggle').click()
    assert page.locator('#edFrames').is_hidden()
    assert page.locator('#ec').evaluate('e=>e.width===16&&e.height===16')
    disabled = page.evaluate('''async id=>{
      const bytes=new Uint8Array(await (await ResourcePacks.buildZip(CB.find(id))).arrayBuffer());
      const files=await BenchArchive.read(bytes);
      return JSON.parse(new TextDecoder().decode(files['assets/minecraft/textures/block/stone.png.mcmeta']));
    }''', project_id)
    assert disabled == {'texture': {'blur': False}}
    assert not errors, errors
    context.close()
    print('PASS: frames left of tools, desktop close/reopen and persisted preference, correct divider, thumbnails/reorder/timing/undo/export, narrow and mobile drawers', flush=True)
    print('PASS: animated panel/canvas transition, rapid reversal, gliding frame reorder, and immediate cancellation for app/system reduced motion', flush=True)


def run_keyboard(browser, url, artifacts):
    context = browser.new_context(viewport={'width':1440,'height':900})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function('window.CB && window.Ed')
    page.evaluate('async()=>{await CB.ready;CB.D.set.calm=true;await enterApp({name:"Keyboard artist"})}')
    page.locator('#home-grid .first-project').click()
    page.locator('#mn').fill('Keyboard studio')
    page.locator('#mcreate').click()
    page.wait_for_function('document.querySelector("#edName").textContent==="Keyboard studio" && document.querySelector("#edArea").style.display!=="none"')
    page.locator('#ec').focus()
    page.keyboard.press('Shift+a')
    page.locator('#animFrames [data-frame="1"]').click()
    page.locator('#animSeconds').fill('0.35')
    page.locator('#animSeconds').press('Tab')
    assert page.locator('#animFrames [data-frame="1"] small').inner_text() == '0.35 s'
    choose_color(page, '#2233DD')
    draw(page, [0,0])
    choose_tool(page, 'eraser')
    draw(page, [1,1])
    choose_tool(page, 'pencil')
    copied = page.locator('#ec').evaluate('cv=>Array.from(cv.getContext("2d").getImageData(0,0,cv.width,cv.height).data)')
    page.locator('#animFrames [data-frame="1"]').click()
    page.keyboard.press('Meta+c')
    page.keyboard.press('Control+d')
    assert page.locator('#animFrames [data-frame]').count() == 3
    assert page.locator('#animSeconds').input_value() == '0.35'
    assert page.locator('#ec').evaluate('cv=>Array.from(cv.getContext("2d").getImageData(0,0,cv.width,cv.height).data)') == copied
    # Delete is one metadata/pixel undo, then paste uses a detached clipboard.
    page.keyboard.press('Delete')
    assert page.locator('#animFrames [data-frame]').count() == 2
    page.keyboard.press('Control+z')
    assert page.locator('#animFrames [data-frame]').count() == 3
    page.keyboard.press('Control+v')
    assert page.locator('#animFrames [data-frame]').count() == 4
    assert page.locator('#animSeconds').input_value() == '0.35'
    choose_color(page, '#FFAA22')
    draw(page, [0,0])
    assert page.evaluate('document.activeElement.id') == 'ec'
    page.locator('#animFrames [data-frame="1"]').click()
    assert pixel(page) == [34,51,221,255], 'A pasted frame shared source pixels'
    page.keyboard.press('Control+x')
    assert page.locator('#animFrames [data-frame]').count() == 3
    page.keyboard.press('Control+v')
    assert page.locator('#animFrames [data-frame]').count() == 4 and pixel(page) == [34,51,221,255]
    page.keyboard.press('Home')
    assert page.locator('#animFrames [data-frame="0"]').get_attribute('aria-pressed') == 'true'
    page.keyboard.press('End')
    assert page.locator('#animFrames [data-frame="3"]').get_attribute('aria-pressed') == 'true'
    page.keyboard.press('Alt+ArrowUp')
    assert page.locator('#animFrames [data-frame="2"]').get_attribute('aria-pressed') == 'true'
    count = page.locator('#animFrames [data-frame]').count()
    page.locator('#animSeconds').focus()
    page.keyboard.press('Control+a')
    page.keyboard.press('Delete')
    assert page.locator('#animFrames [data-frame]').count() == count
    page.locator('#animSeconds').fill('0.35')
    page.locator('#animSeconds').press('Tab')
    page.locator('#ec').focus()
    page.keyboard.press('PageDown')
    page.keyboard.press('Shift+Space')
    assert page.locator('#animPlay').get_attribute('aria-pressed') == 'true'
    page.keyboard.press('Shift+Space')
    assert page.locator('#animPlay').get_attribute('aria-pressed') == 'false'
    page.keyboard.press('h')
    assert page.locator('#canvasPan').get_attribute('aria-pressed') == 'true'
    page.keyboard.press('h')
    page.keyboard.down('Space')
    assert page.locator('#canvasPan').get_attribute('aria-pressed') == 'true'
    page.keyboard.up('Space')
    assert page.locator('#canvasPan').get_attribute('aria-pressed') == 'false'
    page.keyboard.press('Shift+g')
    assert page.locator('#canvasGrid').get_attribute('aria-pressed') == 'false'
    page.keyboard.press('f')
    page.keyboard.press('c')
    assert page.locator('#colorChooser').is_visible()
    page.keyboard.press('Escape')
    page.locator('#ec').focus()
    page.keyboard.press('p')
    page.wait_for_function('document.querySelector("#pvW .pv-face") && !document.querySelector("#pvT").textContent.includes("Loading")')
    transform = page.locator('#pvW').get_attribute('style')
    page.keyboard.press('ArrowLeft')
    assert page.locator('#pvW').get_attribute('style') != transform
    page.keyboard.press('p')
    page.wait_for_function('document.querySelector("#edArea").style.display!=="none"')
    page.locator('#ec').focus()
    page.keyboard.press('Control+f')
    assert page.evaluate('document.activeElement.id') == 'edQ'
    page.locator('#ec').focus()
    page.keyboard.press('F1')
    page.locator('#shortcutSearch').fill('frame')
    assert page.locator('.shortcut-row:visible').count() >= 8
    assert page.locator('.shortcut-row:visible').filter(has_text='Save now').count() == 0
    page.screenshot(path=str(artifacts / 'keyboard-shortcuts.png'))
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(artifacts / 'mobile-keyboard-shortcuts.png'))
    assert page.locator('#appDialog').evaluate('e=>e.scrollWidth<=e.clientWidth')
    page.locator('#appDialogAccept').click()
    assert page.evaluate('document.activeElement.id') == 'ec'
    assert not errors, errors
    context.close()
    print('PASS: frame copy/cut/paste/duplicate/delete with timing and independent pixels, Undo, keyboard navigation, input guards, canvas tools, 3D controls, searchable shortcuts and focus return', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-path')
    parser.add_argument('--url')
    parser.add_argument('--logout-only', action='store_true', help='Run the session/save/logout regression only')
    parser.add_argument('--image-import-only', action='store_true', help='Run the image importer workflow only')
    parser.add_argument('--artifacts', default='/tmp/cubeon-bench-app-checks')
    args = parser.parse_args()
    artifacts = Path(args.artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    candidates = [*Path.home().glob('.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'), *Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'), Path('/opt/google/chrome/chrome')]
    executable = args.browser_path or next((str(path) for path in candidates if path.exists()), None)
    server = None
    if not args.url:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable, headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-crashpad-for-testing'])
            try:
                url = args.url or f'http://127.0.0.1:{server.server_port}/cubeon-bench/workspace.html'
                from image_import_checks import run as run_image_import
                if args.image_import_only:
                    run_image_import(browser, url, artifacts, pixel, texture)
                elif not args.logout_only:
                    run(browser, url, artifacts)
                    run_animation_frames(browser, url, artifacts)
                    run_keyboard(browser, url, artifacts)
                    run_image_import(browser, url, artifacts, pixel, texture)
                if not args.image_import_only:
                    run_logout(browser, url, artifacts)
            finally:
                browser.close()
    finally:
        if server:
            server.shutdown()
            server.server_close()
    print('Image importer passed. Artifacts:' if args.image_import_only else 'Logout workflow passed. Artifacts:' if args.logout_only else 'Complete app workflows passed. Artifacts:', artifacts)


if __name__ == '__main__':
    main()
