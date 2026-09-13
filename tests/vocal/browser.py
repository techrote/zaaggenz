"""Real Chromium acceptance for optional capture/import/correction/discard without requiring recording permission."""
from __future__ import annotations
import argparse,json,sys,threading
from pathlib import Path
import numpy as np
from scipy.io import wavfile
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from playwright.sync_api import sync_playwright,expect
from zaaggenz_vocal.server import VocalServer

SR=12000
def fixture():
    z=lambda d:np.zeros(round(SR*d),np.float32)
    def tone(f,d):
        t=np.arange(round(SR*d))/SR;return (.30*np.sin(2*np.pi*f*t)).astype(np.float32)
    rng=np.random.default_rng(4)
    return np.concatenate([z(.10),tone(120,.32),z(.08),rng.normal(0,.20,round(SR*.25)).astype(np.float32),z(.08),tone(150,.32),z(.10)])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    wav=a.out/'capture.wav';wavfile.write(wav,SR,fixture())
    server=VocalServer(0,SR);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{server.server_port}/vocal';errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required','--mute-audio','--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True,permissions=[])
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.goto(url);page.set_default_timeout(30000)
            expect(page.locator('#record-state')).to_contain_text('Idle');expect(page.locator('#analyse')).to_be_disabled()
            page.locator('#file').set_input_files(wav);expect(page.locator('#analyse')).to_be_enabled();page.locator('#analyse').click();expect(page.locator('.segment')).to_have_count(3)
            middle=page.locator('.segment').nth(1);middle.locator('select').nth(1).select_option('manual');middle.locator('input[type=number]').nth(1).fill('136');middle.locator('input[type=number]').nth(1).dispatch_event('change')
            page.locator('#compile').click();expect(page.locator('#render')).to_be_enabled();expect(page.locator('#preview')).to_contain_text('"pitch_mode": "manual"')
            page.locator('#render').click();expect(page.locator('#status')).to_contain_text('Source-derived preview rendered',timeout=90000)
            page.locator('#discard').click();expect(page.locator('#status')).to_contain_text('Raw source discarded');expect(page.locator('#render')).to_be_enabled();expect(page.locator('#apply')).to_be_enabled()
            with page.expect_download() as dl:page.locator('#apply').click()
            export=a.out/'capture.zgtimeline.json';dl.value.save_as(export);doc=json.loads(export.read_text());assert len(doc['notes'])==3
            page.screenshot(path=a.out/'vocal-capture.png',full_page=True);assert not errors,errors;browser.close()
        (a.out/'browser-report.json').write_text(json.dumps({'checks':'passed','segments':3,'recording_permission_granted':False,'raw_source_discarded_before_export':True,'page_errors':errors},indent=2)+'\n')
        print(json.dumps({'checks':'passed','segments':3}))
    finally:
        server.shutdown();server.server_close();thread.join(3)
if __name__=='__main__':main()
