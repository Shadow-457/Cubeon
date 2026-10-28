"""Optional Playwright checks; all HTTP/AI requests are intercepted offline.

Run with a Python that has Playwright and an installed Chromium. Set
CUBEON_TEST_CHROMIUM for an explicit browser executable. Not in mega smoke.
"""
import base64
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
import zlib

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon.webdoctor import doctor_url

def guide(log):
    return {'cause':'Heap exhausted <img src=x onerror=alert(1)>','confidence':'high',
            'evidence':[log.split('\n')[-1]],'steps':[
                {'action':'memory','title':'Raise memory','instruction':'Use the safe RAM slider.'},
                {'action':'retry','title':'Try once','instruction':'Compare the fresh log.'}],
            'verify':'Launch once','rollback':'Restore the previous value','source':'ai','model':'Kilo auto/free'}

def main():
    captures = ROOT / 'archive/ui-captures'
    captures.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        executable = os.environ.get('CUBEON_TEST_CHROMIUM')
        options = {'executable_path': executable} if executable else {}
        browser = p.chromium.launch(headless=True, **options)
        page = browser.new_page(viewport={'width':1440,'height':1050})
        errors, external, ai_calls = [], [], []
        ai_mode = ['ok']
        page.on('pageerror',lambda e: errors.append(str(e)))
        def route(request):
            url = request.request.url
            if not url.startswith('https://cubeon.test/'):
                external.append(url); request.abort(); return
            if urlsplit(url).path == '/api/doctor':
                body = request.request.post_data_json; ai_calls.append(body)
                assert 'model' not in body and 'messages' not in body
                if ai_mode[0] == 'fail': request.fulfill(status=503,body='{}',content_type='application/json')
                else: request.fulfill(body=json.dumps(guide(body['log'])),content_type='application/json')
                return
            path = urlsplit(url).path.lstrip('/')
            if path == 'doctor': path = 'doctor.html'
            file = ROOT / 'web' / path
            if file.is_file(): request.fulfill(path=str(file))
            else: request.fulfill(status=404,body='Not found')
        page.route('**/*',route)
        page.goto('https://cubeon.test/doctor')
        expect(page.locator('#doctor-empty')).to_be_visible()
        expect(page.locator('#log-text')).to_have_attribute('aria-describedby','file-note')
        expect(page.locator('.doc-ai-note')).to_contain_text('may retain and use')
        assert len(ai_calls)==0
        page.screenshot(path=str(captures/'doctor-empty-desktop.png'),full_page=True)
        url = doctor_url('password=hidden\njava.lang.OutOfMemoryError: Java heap space',version_label='Test pack',base_url='https://cubeon.test')
        page.goto(url)
        expect(page.locator('#result-cause')).to_contain_text('heap memory')
        assert '#' not in page.url
        assert 'hidden' not in page.locator('#log-text').input_value()
        assert len(ai_calls)==0, 'AI must not run automatically on a launcher handoff'
        expect(page.locator('.doc-slider')).to_be_visible()
        expect(page.locator('#guide-tabs button').first).to_be_visible()
        expect(page.locator('#guide-tabs button').first).to_contain_text('Allocated RAM')
        expect(page.locator('#guide-tabs button').first).to_have_attribute('aria-current','step')
        page.locator('.doc-evidence summary').click()
        expect(page.locator('#result-evidence')).to_contain_text('OutOfMemoryError')
        page.locator('.doc-evidence summary').click()
        page.locator('#step-next').click()
        expect(page.locator('#guide-step h3')).to_have_text('Launch once more')
        page.locator('#step-prev').click()
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(captures/'doctor-desktop.png'),full_page=True)
        print('PASS launcher handoff, immediate redaction, local guide and step navigation')

        page.locator('#log-file').set_input_files({'name':'crash.log','mimeType':'text/plain','buffer':b'GLFW error 65542: WGL: failed'})
        expect(page.locator('#result-cause')).to_contain_text('OpenGL')
        expect(page.locator('.doc-external-links a')).to_have_count(3)
        page.locator('#log-file').set_input_files({'name':'bad.zip','mimeType':'application/zip','buffer':b'bad'})
        expect(page.locator('#doctor-status')).to_contain_text('plain .log or .txt')
        page.locator('#log-file').set_input_files({'name':'huge.log','mimeType':'text/plain','buffer':b'x'*2100000})
        expect(page.locator('#doctor-status')).to_contain_text('over 2 MB')
        page.locator('#log-file').set_input_files({'name':'long.log','mimeType':'text/plain','buffer':b'x'*70000+b'\nUnrecognized VM option bogus'})
        expect(page.locator('#file-note')).to_contain_text('tail excerpt')
        expect(page.locator('#result-cause')).to_contain_text('launch option')
        print('PASS file types, size limits, truncation and graphics links')

        page.locator('#log-text').fill('java.lang.OutOfMemoryError: Java heap space')
        page.locator('#ai-check').click()
        expect(page.locator('#result-source')).to_contain_text('Kilo auto/free')
        assert len(ai_calls)==1
        expect(page.locator('#model-attempts .doc-attempt')).to_have_count(0)
        expect(page.locator('#result-cause img')).to_have_count(0)
        expect(page.locator('#result-cause')).to_contain_text('<img')
        with page.expect_download() as info: page.locator('#download-result').click()
        assert info.value.suggested_filename=='cubeon-doctor-guide.txt'
        print('PASS same-origin Kilo requests, text rendering and saved guide')

        ai_mode[0] = 'fail'
        page.locator('#ai-check').click()
        expect(page.locator('#doctor-status')).to_contain_text('local guide remains available')
        expect(page.locator('#result-source')).to_have_text('Local check')
        page.evaluate("""() => {
            const realFetch = window.fetch;
            window.fetch = (url,options) => url === '/api/doctor' ? new Promise(()=>{}) : realFetch(url,options);
        }""")
        page.locator('#ai-check').click()
        expect(page.locator('#cancel-check')).to_be_visible()
        page.locator('#cancel-check').click()
        expect(page.locator('#doctor-status')).to_contain_text('stopped')
        expect(page.locator('#ai-check')).to_be_enabled()
        page.locator('#ai-check').click()
        expect(page.locator('#model-attempts .doc-attempt')).to_have_count(1)
        page.locator('#log-text').fill('UnknownHostException: unreachable')
        page.locator('#local-check').click()
        expect(page.locator('#result-cause')).to_contain_text('could not be reached')
        expect(page.locator('#cancel-check')).to_be_hidden()
        page.locator('#clear-log').click()
        expect(page.locator('#doctor-empty')).to_be_visible()
        assert page.locator('#log-text').input_value()==''
        print('PASS AI outage fallback, cancellation, editing and clearing during a request')

        page.goto('https://cubeon.test/doctor#report=bad!')
        expect(page.locator('#doctor-status')).to_contain_text('could not be opened')
        assert '#' not in page.url
        bomb=base64.urlsafe_b64encode(zlib.compress(b'x'*350000)).decode().rstrip('=')
        page.goto('https://cubeon.test/doctor#report='+bomb)
        expect(page.locator('#doctor-status')).to_contain_text('could not be opened')
        page.set_viewport_size({'width':390,'height':844})
        page.locator('[data-example="mods"]').click()
        expect(page.locator('#result-cause')).to_contain_text('dependency')
        result_top = page.locator('#doctor-result').bounding_box()['y']
        assert 70 <= result_top < 180, 'A mobile diagnosis should scroll into view below the navbar'
        expect(page.locator('#guide-tabs button').nth(1)).to_contain_text('Check & repair')
        page.locator('#step-next').click()
        expect(page.locator('#guide-step')).to_contain_text('Check & repair')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(captures/'doctor-mobile.png'),full_page=True)
        for width in [320,768,1024]:
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
            expect(page.locator('#guide-tabs button').nth(1)).to_be_visible()
        page.emulate_media(color_scheme='light', reduced_motion='reduce')
        assert page.locator('#log-text').evaluate("el => getComputedStyle(el).color") == 'rgb(221, 246, 213)', 'Doctor should keep the restored site palette'
        assert not errors, errors
        assert not external, external
        print('PASS invalid fragments, decompression bounds, mobile layout and no browser exceptions')
        browser.close()

if __name__=='__main__': main()
