#!/usr/bin/env python3
"""Run file-based UI checks with Firefox, without a server or remote debugging."""

import argparse
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


SUITE = r"""
(async function(){
  const results={passed:[],errors:[],snapshots:{},viewport:[innerWidth,innerHeight]},expected=__EXPECTED__;
  const query=new URLSearchParams(location.search),mobile=query.has('mobile');
  const $=s=>document.querySelector(s),sleep=ms=>new Promise(ok=>setTimeout(ok,ms));
  window.addEventListener('error',e=>{if(e.message)results.errors.push(e.message)});
  window.addEventListener('unhandledrejection',e=>results.errors.push(String(e.reason)));
  function assert(value,message){if(!value)throw Error(message)}
  async function until(fn,message){for(let i=0;i<800;i++){if(fn())return;await sleep(10)}throw Error(message)}
  function click(s){assert($(s),'Missing '+s);$(s).click()}
  function choose(s,value){$(s).value=value;$(s).dispatchEvent(new Event('change',{bubbles:true}))}
  function state(){const cv=$('#ec'),pixels=cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data;let hash=2166136261;for(let i=0;i<pixels.length;i+=4)for(let j=0;j<4;j++){const b=j<3?Math.round(pixels[i+j]*pixels[i+3]/255):pixels[i+3];hash=Math.imul(hash^b,16777619)}return {w:cv.width,h:cv.height,hash:hash>>>0}}
  function native(id){
    const cv=$('#ec'),reference=expected[id],pixels=cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data,original=atob(reference.pixels);
    assert(cv.width===reference.w&&cv.height===reference.h,'PNG dimensions: '+id);
    for(let i=0;i<pixels.length;i+=4){
      const alpha=original.charCodeAt(i+3),tolerance=alpha===255?0:alpha?Math.ceil(255/alpha):255;
      assert(pixels[i+3]===alpha,'PNG alpha: '+id+' at '+i/4);
      for(let j=0;j<3;j++)assert(Math.abs(pixels[i+j]-original.charCodeAt(i+j))<=tolerance,'PNG color: '+id+' at '+i/4);
    }
  }
  async function ready(id){await until(()=>$('#edPath').textContent==='textures/'+id+'.png'&&$('#edArea').style.display!=='none','Texture did not open: '+id)}
  function fixture(id,type='pack',size=16){const now=Date.now(),p={id:'check'+now+Math.random(),name:id,type,size,pal:'meadow',texture:id,created:now,edited:now};window.CB.D.projects.unshift(p);return p}
  async function open(id,type='pack',size=16){const p=fixture(id,type,size);await window.Ed.open(p);await ready(id);return p}
  async function search(id){$('#edQ').value=id;$('#edQ').dispatchEvent(new Event('input',{bubbles:true}));click('#edRes [data-id="'+id+'"]');await ready(id)}
  async function preview(){click('#edTabs [data-id="preview"]');await until(()=>$('#pvW .pv-face')&&!$('#pvT').textContent.includes('Loading'),'Preview did not render');if($('#pvAuto').textContent.endsWith('on'))click('#pvAuto');click('#pvReset');await sleep(30)}
  function snapshot(name){
    const copy=document.documentElement.cloneNode(true),original=document.querySelectorAll('canvas'),clones=copy.querySelectorAll('canvas');
    const base=document.createElement('base');base.href=new URL('.',location.href).href;copy.querySelector('head').prepend(base);
    clones.forEach((c,i)=>{if(original[i].width&&original[i].height){c.style.backgroundImage='url("'+original[i].toDataURL()+'")';c.style.backgroundSize='100% 100%'}});
    copy.querySelectorAll('select').forEach((select,i)=>{const value=document.querySelectorAll('select')[i].value;for(const option of select.options)option.toggleAttribute('selected',option.value===value)});
    copy.querySelectorAll('input').forEach((input,i)=>{const source=document.querySelectorAll('input')[i];input.setAttribute('value',source.value);input.toggleAttribute('checked',source.checked)});
    copy.querySelectorAll('script').forEach(e=>e.remove());
    const style=document.createElement('style');style.textContent='*,*::before,*::after{animation:none!important;transition:none!important}';copy.querySelector('head').append(style);
    results.snapshots[name]='<!doctype html>\n'+copy.outerHTML;
  }
  function pass(s){results.passed.push(s);console.log('PASS: '+s)}
  try{
    assert(window.Ed&&window.MinecraftTextures,'App scripts did not initialize');
    await window.CB.ready;await window.enterApp({name:'Texture tester'});await until(()=>$('#app').classList.contains('on'),'App did not open');
    document.body.classList.add('calm');
    assert(window.MinecraftTextures.entries.length===3964,'Incomplete texture catalog');
    assert(window.MinecraftTextures.roots.length===15,'Missing Minecraft categories');
    if(mobile){
      await open('block/grass_block_top');
      assert(innerWidth<=410,'Mobile viewport was not applied: '+innerWidth);
      assert($('#ed').scrollWidth<=innerWidth,'Mobile toolbar overflows');
      click('#edL');choose('#edCat','gui');
      assert($('#edCount').textContent==='563 textures','Mobile folder count');
      await preview();assert(!$('#ed').classList.contains('l-open'),'Drawer obscures preview');
      assert(document.querySelectorAll('#pvW .pv-face').length===6,'Mobile cube faces');
      const area=$('#pvS').getBoundingClientRect();
      for(const face of document.querySelectorAll('#pvW .pv-face')){const box=face.getBoundingClientRect();assert(box.left>=area.left&&box.right<=area.right,'Mobile cube is clipped')}
      snapshot('mobile-preview');pass('mobile toolbar, folder drawer, and unclipped 3D preview');
      click('#edTabs [data-id="block/grass_block_top"]');await ready('block/grass_block_top');click('#edR');
      $('#edCol').scrollIntoView({block:'center'});click('#edCol');
      assert(!$('#colorChooser').hidden,'Mobile custom color chooser did not open');
      const chooser=$('#colorChooser').getBoundingClientRect();
      assert(chooser.left>=0&&chooser.right<=innerWidth&&chooser.top>=0&&chooser.bottom<=innerHeight,'Mobile color chooser is clipped');
      $('#colorHex').value='#1357BD';$('#colorHex').dispatchEvent(new Event('input',{bubbles:true}));
      assert($('#edHex').value==='#1357BD','Mobile custom HEX color');snapshot('mobile-color-chooser');
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert($('#colorChooser').hidden,'Mobile chooser Escape');
      click('#edDetails');assert(!$('#mpal')&&!$('#spal'),'Palette selection was not removed');
      const modal=$('#modal .mb').getBoundingClientRect();assert(modal.left>=0&&modal.right<=innerWidth&&modal.top>=0&&modal.bottom<=innerHeight,'Mobile pack details are clipped');
      snapshot('mobile-pack-details');click('#modal [data-x]');
      pass('mobile custom color chooser, exact HEX entry, and pack metadata dialog without palette selection');
    }else{
      click('[data-go="library"]');assert($('#libCount').textContent==='3,964 textures','Library texture count');
      choose('#libCat','entity');assert($('#libCount').textContent==='743 textures','Entity count');
      click('#libFolders [data-folder="entity/creeper"]');click('#lib-grid [data-texture="entity/creeper/creeper"]');click('#mcreate');
      await ready('entity/creeper/creeper');native('entity/creeper/creeper');
      const p=window.CB.D.projects[0];click('[data-a="rot"]');const rotated=state();
      assert(rotated.w===32&&rotated.h===64,'Non-square rotation dimensions');
      click('#edUndo');native('entity/creeper/creeper');click('#edRedo');assert(JSON.stringify(state())===JSON.stringify(rotated),'Non-square redo');
      window.Ed.close();await window.LocalStore.flush();const saved=(await window.LocalStore.loadState()).projects.find(x=>x.id===p.id);
      Object.assign(p,saved);await window.Ed.open(p);await ready('entity/creeper/creeper');assert(JSON.stringify(state())===JSON.stringify(rotated),'Saved rectangular pixels');
      click('[data-a="reset"]');await until(()=>$('#ec').width===64,'Reset dimensions');native('entity/creeper/creeper');
      pass('native library textures, rectangular rotation, undo/redo, and saved edits');

      choose('#edCat','');assert($('#edCount').textContent==='3,964 textures','All editor textures');
      choose('#edCat','entity');click('#edFolders [data-folder="entity/player"]');click('#edFolders [data-folder="entity/player/wide"]');
      await search('block/stone');native('block/stone');
      $('#edHex').value='#FF0000';$('#edHex').dispatchEvent(new Event('input',{bubbles:true}));
      const rect=$('#ec').getBoundingClientRect(),options={button:0,pointerId:1,bubbles:true,clientX:rect.left+rect.width/32,clientY:rect.top+rect.height/32};
      $('#ec').dispatchEvent(new PointerEvent('pointerdown',options));$('#ec').dispatchEvent(new PointerEvent('pointerup',options));
      assert(state().hash!==expected['block/stone'].hash,'Painting did not change pixels');
      click('#edUndo');native('block/stone');click('#edRedo');
      assert(Array.from($('#ec').getContext('2d').getImageData(0,0,1,1).data).join(',')==='255,0,0,255','Paint redo color');
      pass('nested folder navigation, global path search, painting, and undo/redo');

      await open('block/grass_block_top');native('block/grass_block_top');await preview();
      assert(document.querySelectorAll('#pvW .pv-face').length===6,'Cube must have six faces');
      assert($('.pv-face-top').dataset.texture==='textures/block/grass_block_top.png','Grass top texture');
      assert($('.pv-face-bottom').dataset.texture==='textures/block/dirt.png','Grass bottom texture');
      assert($('.pv-face-front').dataset.texture==='textures/block/grass_block_side.png','Grass side texture');
      for(const face of document.querySelectorAll('#pvW .pv-face')){assert(getComputedStyle(face).padding==='0px','Page layout padding leaked into 3D face');assert(face.getBoundingClientRect().width>1,'Invisible face')}
      snapshot('grass-preview');
      click('#edTabs [data-id="block/grass_block_top"]');await ready('block/grass_block_top');
      click('#faceBar [data-face="bottom"]');await ready('block/dirt');
      click('#faceBar [data-face="top"]');await ready('block/grass_block_top');
      await open('block/oak_log');await preview();
      assert($('.pv-face-top').dataset.texture==='textures/block/oak_log_top.png','Log ends');
      assert($('.pv-face-front').dataset.texture==='textures/block/oak_log.png','Log bark');snapshot('log-preview');
      const stage=$('#pvS'),r=stage.getBoundingClientRect(),before=$('#pvW').style.transform;
      stage.dispatchEvent(new PointerEvent('pointerdown',{button:0,pointerId:2,clientX:r.left+r.width/2,clientY:r.top+r.height/2}));
      stage.dispatchEvent(new PointerEvent('pointermove',{pointerId:2,clientX:r.left+r.width/2+80,clientY:r.top+r.height/2+30}));
      stage.dispatchEvent(new PointerEvent('pointerup',{pointerId:2}));
      assert($('#pvW').style.transform!==before,'Drag rotation');const dragged=$('#pvW').style.transform;
      stage.dispatchEvent(new WheelEvent('wheel',{deltaY:-100,cancelable:true}));assert($('#pvW').style.transform!==dragged,'Scroll zoom');
      click('#pvReset');assert($('#pvW').style.transform.includes('rotateX(-22deg) rotateY(-35deg)'),'Reset view');
      pass('cube face isolation, grass/log textures, face editing, rotation, zoom, and reset');

      await open('block/water_still');native('block/water_still');await preview();
      const water=$('.pv-face-front'),first=water.style.backgroundImage,img=new Image();img.src=first.slice(5,-2);await img.decode();
      assert(img.width===16&&img.height===16,'Animation strip stretched onto the cube');
      await until(()=>water.style.backgroundImage!==first,'Animation did not advance');
      await open('item/diamond_sword');native('item/diamond_sword');await preview();
      assert(document.querySelectorAll('.pv-item-edge').length>0,'Transparent item needs edge geometry');snapshot('item-preview');
      await open('entity/player/wide/steve','skin');native('entity/player/wide/steve');await preview();
      assert(document.querySelectorAll('#pvW .pv-face').length===72,'Skin body and overlay faces');snapshot('skin-preview');
      pass('full animation PNGs, cropped animated faces, transparent item edges, and real Steve skin');

      await open('gui/title/minecraft');native('gui/title/minecraft');$('#edZoom').value=4;$('#edZoom').dispatchEvent(new Event('input'));
      const area=$('#edArea');area.scrollLeft=400;area.scrollTop=200;
      assert(area.scrollLeft>0&&area.scrollTop>0,'Editor must scroll in both directions');
      document.documentElement.dataset.theme='light';const light=getComputedStyle(area).scrollbarColor;
      assert(getComputedStyle(area).scrollbarWidth==='thin','Custom Firefox scrollbar width');
      document.documentElement.dataset.theme='dark';assert(getComputedStyle(area).scrollbarColor!==light,'Scrollbar theme did not change');snapshot('custom-scrollbars');
      const tabs=fixture('block/stone');tabs.open=window.MinecraftTextures.entries.filter(e=>e.cat==='block').slice(0,20).map(e=>e.id);tabs.cur=tabs.open[0];await window.Ed.open(tabs);
      $('#edTabs').scrollLeft=300;assert($('#edTabs').scrollLeft>0,'Open texture tabs must scroll');
      window.Ed.close();click('[data-go="library"]');choose('#libCat','block');
      await Promise.all(Array.from(document.querySelectorAll('#lib-grid canvas')).map(c=>window.MinecraftTextures.load(c.dataset.texture)));
      await sleep(40);snapshot('texture-library');
      pass('native wide GUI textures, vertical/horizontal scrolling, themed scrollbars, and scrolling tabs');
    }
    assert(!results.errors.length,'JavaScript errors: '+results.errors.join('; '));
  }catch(error){results.failure=String(error)+'\n'+(error.stack||'');if($('#ec'))results.debugCanvas=$('#ec').toDataURL()}
  const a=document.createElement('a');a.download='firefox-results.json';a.href=URL.createObjectURL(new Blob([JSON.stringify(results)],{type:'application/json'}));document.body.append(a);a.click();
})();
"""


def run(mobile, artifacts, workflow=False):
    textures = ['entity/creeper/creeper', 'block/stone', 'block/grass_block_top', 'block/water_still', 'item/diamond_sword', 'entity/player/wide/steve', 'gui/title/minecraft']
    expected = {}
    for name in textures:
        with Image.open(ROOT / 'textures' / (name + '.png')) as im:
            data = im.convert('RGBA').tobytes()
            value = 2166136261
            for byte in data:
                value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
            expected[name] = {'w': im.width, 'h': im.height, 'hash': value,
                              'pixels': base64.b64encode(data).decode('ascii')}
    script = (ROOT / 'tools/workflow-checks.js').read_text() if workflow else SUITE.replace('__EXPECTED__', json.dumps(expected))
    html = (ROOT / 'index.html').read_text()
    html = '\n'.join(line for line in html.splitlines() if 'fonts.googleapis.com' not in line)
    html = html.replace('</body>', '<script>' + script + '</script></body>')
    with tempfile.NamedTemporaryFile(mode='w', prefix='.firefox-check-', suffix='.html', dir=ROOT, delete=False) as document:
        document.write(html)
        harness = Path(document.name)
    frame = harness.with_name(harness.stem + '-frame.html')
    target = harness
    if mobile:
        # Firefox desktop windows have a minimum width; an iframe supplies a real 390px viewport.
        frame.write_text(f'<!doctype html><html><body style="margin:0"><iframe src="{harness.name}?mobile=1" width="390" height="844" style="border:0;display:block"></iframe></body></html>')
        target = frame
    try:
        with tempfile.TemporaryDirectory(prefix='cubeon-bench-firefox-') as temporary:
            work = Path(temporary); profile = work / 'profile'; profile.mkdir()
            prefs = {
                'browser.download.folderList': 2, 'browser.download.dir': str(work),
                'browser.download.useDownloadDir': True, 'browser.download.alwaysOpenPanel': False,
                'browser.helperApps.neverAsk.saveToDisk': 'application/json,application/zip,image/png',
                'browser.download.start_downloads_in_tmp_dir': False,
                'browser.shell.checkDefaultBrowser': False, 'browser.aboutConfig.showWarning': False,
                'datareporting.policy.dataSubmissionEnabled': False, 'toolkit.telemetry.reportingpolicy.firstRun': False,
                'devtools.console.stdout.content': True,
                'dom.allow_scripts_to_close_windows': True,
            }
            (profile / 'user.js').write_text('\n'.join(f'user_pref({json.dumps(k)}, {json.dumps(v)});' for k, v in prefs.items()))
            def execute(url, report_name, label):
                command = ['firefox', '--headless', '--no-remote', '--profile', str(profile), '--width', '500' if mobile else '1440', '--height', '960' if mobile else '1080', url]
                log_path = artifacts / (label + '-firefox.log')
                with log_path.open('w') as log:
                    process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True, env={**os.environ, 'MOZ_CRASHREPORTER_DISABLE': '1', 'GSETTINGS_BACKEND': 'memory'})
                    try:
                        output = work / report_name
                        deadline = time.monotonic() + 55
                        result = None
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                raise RuntimeError(f'Firefox exited before reporting results: {log_path}')
                            if output.exists():
                                try:
                                    result = json.loads(output.read_text())
                                    break
                                except (json.JSONDecodeError, OSError):
                                    pass
                            time.sleep(.1)
                        if result is None:
                            raise RuntimeError(f'Firefox did not report results: {log_path}')
                    finally:
                        if workflow and process.poll() is None:
                            try:
                                process.wait(timeout=8)
                            except subprocess.TimeoutExpired:
                                pass
                        if process.poll() is None:
                            process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL); process.wait()
                snapshots = result.pop('snapshots')
                for name, snapshot in snapshots.items():
                    (artifacts / (name + '.html')).write_text(snapshot)
                (artifacts / (label + '-results.json')).write_text(json.dumps(result, indent=2))
                for passed in result['passed']:
                    print('PASS:', passed, flush=True)
                print('Viewport:', result['viewport'], flush=True)
                if result.get('failure') or result['errors']:
                    raise AssertionError(result.get('failure') or result['errors'])

            execute(target.as_uri(), 'firefox-results.json', 'workflow' if workflow else 'mobile' if mobile else 'desktop')
            if workflow:
                downloads = list(work.glob('*.zip'))
                if not downloads:
                    raise AssertionError('The native export button did not download a ZIP.')
                for path in downloads:
                    with zipfile.ZipFile(path) as archive:
                        assert 'pack.mcmeta' in archive.namelist()
                        assert json.loads(archive.read('pack.mcmeta'))['pack']['pack_format'] == 34
                        assert archive.testzip() is None
                    (artifacts / path.name).write_bytes(path.read_bytes())
                print('PASS: native ZIP download and independent archive validation', flush=True)
                # Keep the exact same file URL; file origins can include the query string.
                harness.write_text(html.replace('<script>' + script + '</script>', '<script>window.CB_WORKFLOW_REOPEN=true;</script><script>' + script + '</script>'))
                execute(harness.as_uri(), 'firefox-reopen.json', 'workflow-reopen')
    finally:
        harness.unlink(missing_ok=True)
        frame.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mobile', action='store_true')
    parser.add_argument('--workflow', action='store_true')
    parser.add_argument('--artifacts', default='/tmp/cubeon-bench-browser-checks')
    args = parser.parse_args()
    artifacts = Path(args.artifacts); artifacts.mkdir(parents=True, exist_ok=True)
    if args.mobile and args.workflow:
        parser.error('--mobile and --workflow must be run separately')
    run(args.mobile, artifacts, args.workflow)


if __name__ == '__main__':
    main()
