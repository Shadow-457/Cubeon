#!/usr/bin/env python3
"""Capture real editor assets and verify the Three.js landing page in isolation."""
import argparse
import importlib.util
import io
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bench_serve', ROOT / 'tools/serve.py')
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class Handler(serve.Handler):
    def log_message(self, *_):
        pass


def capture_editor(browser, url):
    assets = ROOT / 'landing-assets'
    assets.mkdir(exist_ok=True)
    context = browser.new_context(viewport={'width':1440,'height':900},color_scheme='light')
    page = context.new_page()
    page.goto(url + 'workspace.html', wait_until='domcontentloaded')
    page.wait_for_function('window.CB && window.Ed')
    page.evaluate('async()=>{await CB.ready;CB.D.set.calm=true;await enterApp({name:"Pixel maker"})}')
    page.locator('#home-grid .first-project').click()
    page.locator('#mn').fill('A little greener')
    page.locator('#mcreate').click()
    page.wait_for_function('document.querySelector("#edName").textContent==="A little greener" && document.querySelector("#edArea").style.display!=="none"')

    def save(name):
        page.evaluate('document.querySelectorAll("#toast,#packTask,#workspaceTask").forEach(e=>e.style.visibility="hidden")')
        png = page.screenshot()
        Image.open(io.BytesIO(png)).save(assets / ('editor-' + name + '.webp'), 'WEBP', quality=91, method=6)
        page.evaluate('document.documentElement.dataset.theme="dark"')
        Image.open(io.BytesIO(page.screenshot())).save(assets / ('editor-' + name + '-dark.webp'), 'WEBP', quality=91, method=6)
        page.evaluate('document.documentElement.dataset.theme="light"')

    save('draw')
    page.locator('#canvasAnimate').click()
    page.locator('[data-anim-action="add"]').click()
    page.locator('#animFrames [data-frame="1"]').click()
    page.locator('#animSeconds').fill('0.2')
    page.locator('#animSeconds').press('Tab')
    save('animate')
    page.locator('#edTabs [data-id="preview"]').click()
    page.wait_for_function('document.querySelector("#pvW .pv-face") && !document.querySelector("#pvT").textContent.includes("Loading")')
    save('preview')
    context.close()
    print('Captured actual Draw, Animate, and Preview assets:', assets, flush=True)


def run(browser, url, artifacts):
    context = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    page = context.new_page()
    errors, requests = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: requests.append(r.url))
    page.goto(url + 'landing.html', wait_until='networkidle')
    page.wait_for_function('document.querySelector("#heroScene").dataset.renderer==="three"', timeout=30000)
    assert page.locator('h1').inner_text() == 'Edit textures.\nBuild your pack.'
    assert page.locator('#heroScene').evaluate('e=>e.width>500 && e.height>500')
    assert page.locator('body').evaluate('e=>e.scrollWidth<=innerWidth')
    page.screenshot(path=str(artifacts / 'landing-desktop.png'))
    before = page.locator('#heroScene').screenshot()
    page.locator('[data-palette="ember"]').click()
    page.wait_for_function('document.querySelector("#heroArt").dataset.palette==="ember"')
    after = page.locator('#heroScene').screenshot()
    assert before != after, 'Palette did not change the rendered sculpture'
    page.locator('#landingTheme').click()
    assert page.locator('html').get_attribute('data-theme') == 'dark'
    assert page.locator('#panel-draw img').get_attribute('src').endswith('-dark.webp')
    page.screenshot(path=str(artifacts / 'landing-dark.png'))
    page.locator('#landingTheme').click()
    page.locator('#heroScene').focus()
    page.keyboard.press('ArrowRight')
    assert page.locator('#heroScene').screenshot() != after
    page.locator('#scenePause').click()
    assert page.locator('#scenePause').get_attribute('aria-pressed') == 'true'
    page.locator('[data-palette="meadow"]').click()
    page.locator('#workspace').scroll_into_view_if_needed()
    page.locator('#tab-animate').click()
    page.wait_for_function('Array.from(document.querySelectorAll("#panel-animate img")).every(i=>i.complete&&i.naturalWidth>0)')
    assert page.locator('#panel-animate').is_visible()
    page.keyboard.press('ArrowRight')
    assert page.locator('#panel-preview').is_visible()
    page.screenshot(path=str(artifacts / 'landing-workspace.png'))
    page.locator('#questions details').nth(2).locator('summary').click()
    assert page.locator('#questions details').nth(2).get_attribute('open') is not None
    page.screenshot(path=str(artifacts / 'landing-full.png'), full_page=True)
    assert all(r.startswith(url.rsplit('/cubeon-bench/',1)[0]) or r.startswith('data:') for r in requests), requests
    # The landing page and editor retain separate, cached navigation entries.
    page.wait_for_function('navigator.serviceWorker.controller', timeout=30000)
    context.set_offline(True)
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('document.querySelector("#heroScene").dataset.renderer==="three"')
    assert page.locator('h1').inner_text().startswith('Edit textures.')
    page.locator('a[href="workspace"]').first.click()
    page.wait_for_function('window.CB && window.Ed')
    assert page.locator('#guest').is_visible()
    context.set_offline(False)
    context.close()

    phone = browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,reduced_motion='reduce')
    mobile = phone.new_page()
    mobile.on('pageerror', lambda e: errors.append(str(e)))
    mobile.goto(url + 'landing.html', wait_until='networkidle')
    mobile.wait_for_function('document.querySelector("#heroScene").dataset.renderer==="three"')
    assert mobile.locator('body').evaluate('e=>e.scrollWidth<=innerWidth')
    mobile.screenshot(path=str(artifacts / 'landing-mobile.png'))
    mobile.screenshot(path=str(artifacts / 'landing-mobile-full.png'),full_page=True)
    mobile.locator('#tab-animate').scroll_into_view_if_needed()
    mobile.locator('#tab-animate').click()
    assert mobile.locator('#panel-animate').is_visible()
    phone.close()

    fallback = browser.new_context(viewport={'width':1440,'height':900},java_script_enabled=False)
    static = fallback.new_page()
    static.goto(url + 'landing.html', wait_until='networkidle')
    assert static.locator('h1').is_visible() and static.locator('.scene-fallback').is_visible()
    fallback.close()
    # Motion follows the scroll in both directions, rather than a timed slideshow.
    motion = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='no-preference')
    story = motion.new_page()
    story.on('pageerror',lambda e: errors.append(str(e)))
    story.goto(url + 'landing.html',wait_until='networkidle')
    story.wait_for_function('document.querySelector("#heroScene").dataset.renderer==="three"')
    story.screenshot(path=str(artifacts / 'scroll-draw.png'))
    for progress, stage, name in [(0.5,'1','animate'),(.95,'2','flower'),(.1,'0','reverse')]:
        story.evaluate('(p)=>{const host=document.querySelector("#heroScroll");document.documentElement.style.scrollBehavior="auto";scrollTo(0,host.offsetTop+p*(host.offsetHeight-innerHeight))}',progress)
        story.wait_for_function('stage=>document.querySelector("#heroScene").dataset.stage===stage',arg=stage)
        story.wait_for_function('p=>Math.abs(Number(document.querySelector("#heroScene").dataset.progress)-p)<.015',arg=progress)
        story.wait_for_function('document.querySelector(".hero-description").getAnimations().every(a=>a.playState==="finished")')
        story.screenshot(path=str(artifacts / ('scroll-' + name + '.png')))
    story.evaluate('()=>{const r=document.querySelector(".feature").getBoundingClientRect();scrollTo(0,scrollY+r.top-innerHeight*.85)}')
    story.wait_for_timeout(250)
    first = story.locator('.texture-tiles').evaluate('e=>getComputedStyle(e).transform')
    story.evaluate('scrollBy(0,450)')
    story.wait_for_timeout(250)
    assert story.locator('.texture-tiles').evaluate('e=>getComputedStyle(e).transform') != first
    story.wait_for_function('getComputedStyle(document.querySelector(".feature")).opacity>.99')
    story.screenshot(path=str(artifacts / 'scroll-features.png'))
    story.locator('.local-section').scroll_into_view_if_needed()
    story.screenshot(path=str(artifacts / 'scroll-local.png'))
    story.evaluate('document.querySelector("#landingTheme").click()')
    story.reload(wait_until='networkidle')
    assert story.locator('html').get_attribute('data-theme') == 'dark'
    story.locator('#workspace').scroll_into_view_if_needed()
    story.locator('#tab-animate').click()
    story.wait_for_function('document.querySelector("#panel-animate img").complete && document.querySelector("#panel-animate img").naturalWidth>0')
    story.wait_for_function('getComputedStyle(document.querySelector(".workspace-demo")).opacity>.99 && document.querySelector("#panel-animate").getAnimations().length===0')
    story.screenshot(path=str(artifacts / 'dark-workspace.png'))
    for element in story.locator('.reveal').all():
        element.scroll_into_view_if_needed()
    story.wait_for_function('Array.from(document.querySelectorAll(".reveal")).every(e=>e.classList.contains("visible"))')
    story.wait_for_timeout(850)
    story.screenshot(path=str(artifacts / 'dark-full.png'),full_page=True)
    motion.close()
    assert not errors, errors
    print('PASS: Three.js scroll painting/frame fan/3D flower and reverse playback, full-page feature motion, persistent dark theme/editor images, recolor/rotation/pause, accessible tabs/FAQ, mobile/reduced motion, local assets, offline landing/editor navigation and no-JS fallback', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture-editor', action='store_true')
    parser.add_argument('--artifacts',default='/tmp/cubeon-bench-landing')
    args = parser.parse_args()
    artifacts = Path(args.artifacts);artifacts.mkdir(parents=True,exist_ok=True)
    candidates = [*Path.home().glob('.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'),Path('/opt/google/chrome/chrome')]
    executable = next(str(p) for p in candidates if p.exists())
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable,headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--disable-crashpad-for-testing','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
            try:
                url = f'http://127.0.0.1:{server.server_port}/cubeon-bench/'
                if args.capture_editor: capture_editor(browser,url)
                run(browser,url,artifacts)
            finally:
                browser.close()
    finally:
        server.shutdown();server.server_close()


if __name__ == '__main__':
    main()
