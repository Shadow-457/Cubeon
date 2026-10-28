"""Optional offline Playwright checks for Doctor upload and Markdown instructions.

Use an installed Chromium and Python with Playwright. All HTTP/AI is intercepted.
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
    return {'cause':'Heap exhausted <img src=x onerror=alert(1)>', 'confidence':'high',
            'evidence':[log.split('\n')[-1]], 'steps':[
                {'action':'memory','title':'Raise memory',
                 'instruction':'Open **Settings → Performance → Memory**. Raise **Allocated RAM** within the safe range.\n\nKeep `options.txt` unchanged. <img src=x onerror=alert(1)>'},
                {'action':'retry','title':'Try once','instruction':'Launch the same instance and compare the fresh log.'}],
            'verify':'Launch once','rollback':'Restore the previous value','source':'ai','model':'Kilo auto/free'}


def main():
    captures = ROOT / 'archive/ui-captures'
    captures.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        executable = os.environ.get('CUBEON_TEST_CHROMIUM')
        browser = p.chromium.launch(headless=True, **({'executable_path':executable} if executable else {}))
        page = browser.new_page(viewport={'width':1440,'height':1050})
        errors, external, ai_calls = [], [], []
        ai_mode = ['fail']
        page.on('pageerror',lambda e: errors.append(str(e)))

        def route(request):
            url = request.request.url
            if not url.startswith('https://cubeon.test/'):
                external.append(url); request.abort(); return
            if urlsplit(url).path == '/api/doctor':
                body = request.request.post_data_json; ai_calls.append(body)
                assert 'model' not in body and 'messages' not in body
                if ai_mode[0] == 'fail': request.fulfill(status=503,body='{}',content_type='application/json')
                elif ai_mode[0] == 'visitor_limit': request.fulfill(status=429,body=json.dumps({'error':'rate_limited','scope':'visitor','retry_after':61}),content_type='application/json')
                elif ai_mode[0] == 'provider_limit': request.fulfill(status=429,body=json.dumps({'error':'rate_limited','provider':'groq'}),content_type='application/json')
                elif ai_mode[0].startswith('ai_'): request.fulfill(status=503,body=json.dumps({'error':ai_mode[0]}),content_type='application/json')
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
        expect(page.locator('#log-text')).to_be_hidden()
        expect(page.locator('#ai-privacy')).to_contain_text('Uploading starts AI analysis')
        expect(page.locator('.cookie-note')).to_have_count(0)
        assert not ai_calls
        page.screenshot(path=str(captures/'doctor-empty-desktop.png'),full_page=True)

        url = doctor_url('password=hidden\njava.lang.OutOfMemoryError: Java heap space',version_label='Test pack',base_url='https://cubeon.test')
        page.goto(url)
        expect(page.locator('#result-cause')).to_contain_text('heap memory')
        assert '#' not in page.url and 'hidden' not in page.locator('#log-text').input_value()
        assert not ai_calls, 'A launcher handoff stays local until Analyze is clicked'
        expect(page.locator('#guide-steps > li')).to_have_count(2)
        expect(page.locator('#guide-steps strong').first).to_contain_text('Settings')
        expect(page.locator('.doc-mock')).to_have_count(0)
        page.locator('.doc-evidence summary').click()
        expect(page.locator('#result-evidence')).to_contain_text('OutOfMemoryError')
        page.locator('.doc-evidence summary').click()
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(captures/'doctor-desktop.png'),full_page=True)
        print('PASS launcher redaction, no automatic sharing, all Markdown steps and error evidence')

        page.locator('#log-file').set_input_files({'name':'crash.log','mimeType':'text/plain','buffer':b'password=hidden\nGLFW error 65542: WGL: failed'})
        expect(page.locator('#doctor-status')).to_contain_text('AI is unavailable')
        assert len(ai_calls)==1, 'File upload must analyze automatically'
        assert 'hidden' not in ai_calls[-1]['log'], 'An uploaded log must be redacted before sharing'
        expect(page.locator('#result-cause')).to_contain_text('OpenGL')
        expect(page.locator('.doc-external-links a')).to_have_count(3)
        expect(page.locator('#file-note')).to_contain_text('crash.log')
        page.locator('#log-file').set_input_files({'name':'bad.zip','mimeType':'application/zip','buffer':b'bad'})
        expect(page.locator('#doctor-status')).to_contain_text('plain .log or .txt')
        page.locator('#log-file').set_input_files({'name':'huge.log','mimeType':'text/plain','buffer':b'x'*2100000})
        expect(page.locator('#doctor-status')).to_contain_text('over 2 MB')
        assert len(ai_calls)==1, 'Invalid uploads must not call AI'
        page.locator('#log-file').set_input_files({'name':'long.log','mimeType':'text/plain','buffer':b'x'*70000+b'\nUnrecognized VM option bogus'})
        expect(page.locator('#doctor-status')).to_contain_text('AI is unavailable')
        expect(page.locator('#file-note')).to_contain_text('tail excerpt')
        expect(page.locator('#guide-steps')).to_contain_text('bogus')
        assert len(ai_calls[-1]['log'])<=64000
        print('PASS automatic upload analysis, local fallback, size/type bounds and precise flags')

        for reason, message in [('ai_not_configured','not configured on this server'),
                                ('ai_credentials_invalid','rejected the server’s API key'),
                                ('ai_quota_exhausted','credits or quota'),
                                ('ai_timeout','time limit'),
                                ('ai_bad_response','reliable repair instructions')]:
            ai_mode[0]=reason
            page.locator('#ai-check').click()
            expect(page.locator('#doctor-status')).to_contain_text(message)
            expect(page.locator('#doctor-status')).to_contain_text('On-device instructions')
            expect(page.locator('#result-source')).to_have_text('On-device check')
        print('PASS distinct configuration, credential, quota, timeout and invalid-response messages')

        for mode,message in [('visitor_limit','3 AI requests'),('ai_busy','AI is busy'),('provider_limit','AI is busy')]:
            ai_mode[0]=mode
            page.locator('#ai-check').click()
            expect(page.locator('#doctor-status')).to_contain_text(message)
            expect(page.locator('#result-source')).to_have_text('On-device check')
            expect(page.locator('#guide-steps')).to_contain_text('bogus')
            if mode=='visitor_limit': expect(page.locator('#doctor-status')).to_contain_text('2 minutes')
            else: expect(page.locator('#doctor-status')).not_to_contain_text('3 AI requests')
        print('PASS visitor rolling quota, accurate wait and separate capacity/provider limits with local guide retained')

        ai_mode[0]='ok'
        page.locator('#log-text').fill('java.lang.OutOfMemoryError: Java heap space')
        page.locator('#ai-check').click()
        expect(page.locator('#result-source')).to_have_text('AI analysis')
        expect(page.locator('#guide-steps > li')).to_have_count(2)
        expect(page.locator('#guide-steps code')).to_have_text('options.txt')
        expect(page.locator('#guide-steps img')).to_have_count(0)
        expect(page.locator('#result-cause img')).to_have_count(0)
        expect(page.locator('#result-cause')).to_contain_text('<img')
        with page.expect_download() as info: page.locator('#download-result').click()
        download=info.value
        assert download.suggested_filename=='cubeon-doctor-guide.md'
        content=Path(download.path()).read_text()
        assert '## How to fix it' in content and '1. **Raise memory**' in content
        print('PASS Markdown bold/code, safe HTML handling, all steps and Markdown download')

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
        page.locator('#log-text').fill('UnknownHostException: unreachable')
        page.locator('#local-check').click()
        expect(page.locator('#result-cause')).to_contain_text('could not be reached')
        expect(page.locator('#cancel-check')).to_be_hidden()
        page.locator('#clear-log').click()
        expect(page.locator('#doctor-empty')).to_be_visible()
        assert page.locator('#log-text').input_value()==''
        expect(page.locator('#log-text')).to_be_hidden()
        print('PASS cancellation, editing during analysis and clearing')

        page.locator('#log-editor summary').click()
        page.locator('#log-text').fill("[main/INFO]: Loading innocentmod 1.0\nMixin apply for mod iris failed iris.mixins.json:GameRendererMixin\nCaused by: NoSuchMethodError: net.minecraft.GameRenderer.render()")
        page.locator('#local-check').click()
        expect(page.locator('#result-cause')).to_contain_text('iris')
        expect(page.locator('#guide-steps')).to_contain_text('Switch off iris')
        expect(page.locator('#guide-steps')).to_contain_text('re-enable')
        expect(page.locator('#guide-steps')).not_to_contain_text('innocentmod')
        expect(page.locator('#guide-steps strong')).to_contain_text(['Settings', 'Mods', 'iris', 'Play'])
        page.locator('#log-text').fill('MixinApplyError: mixins.widgets.json:ExampleMixin')
        page.locator('#local-check').click()
        expect(page.locator('#guide-steps')).to_contain_text('no confirmed mod to disable')
        expect(page.locator('#guide-steps code')).to_have_text('mixins.widgets.json')
        print('PASS on-device named mod switch instructions and ambiguous mixin ownership')

        page.goto('https://cubeon.test/doctor#report=bad!')
        expect(page.locator('#doctor-status')).to_contain_text('could not be opened')
        assert '#' not in page.url
        bomb=base64.urlsafe_b64encode(zlib.compress(b'x'*350000)).decode().rstrip('=')
        page.goto('https://cubeon.test/doctor#report='+bomb)
        expect(page.locator('#doctor-status')).to_contain_text('could not be opened')
        page.set_viewport_size({'width':390,'height':844})
        page.locator('[data-example="mods"]').click()
        expect(page.locator('#result-cause')).to_contain_text('Example Mod')
        expect(page.locator('#guide-steps')).to_contain_text('fabric-api')
        expect(page.locator('#guide-steps')).to_contain_text('Check & repair')
        result_top=page.locator('#doctor-result').bounding_box()['y']
        assert 70<=result_top<180, 'The diagnosis should scroll into view below the navbar'
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(captures/'doctor-mobile.png'),full_page=True)
        for width in [320,768,1024]:
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        page.emulate_media(color_scheme='light',reduced_motion='reduce')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        assert not external,external
        print('PASS corrupt reports, decompression limits, specific mod names and responsive default theme')
        browser.close()

if __name__=='__main__': main()
