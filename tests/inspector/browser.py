from __future__ import annotations
import argparse,json,os,sys,threading,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from playwright.sync_api import sync_playwright,expect
from zaaggenz_inspector.server import InspectorServer
from zaaggenz_inspector import service as service_module

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    server=InspectorServer(0,args.sample_rate);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}';errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('ZAAGGENZ_CHROMIUM') or None,headless=True,args=['--autoplay-policy=no-user-gesture-required','--mute-audio','--no-sandbox'])
            page=browser.new_page(viewport={'width':1500,'height':1200});page.on('pageerror',lambda e:errors.append(str(e)));page.set_default_timeout(20000);page.goto(base+'/inspector')
            expect(page.locator('#status')).to_contain_text('Ready',timeout=60000);expect(page.locator('#pitch-table tr').first).to_be_visible();initial_snapshot=page.locator('#snapshot-id').inner_text();initial_working=page.locator('#working-revision').inner_text()
            # Labels remain distinct and visible, stage provenance is shown.
            headers=page.locator('#pitch-table').locator('xpath=preceding::thead[1]').inner_text();assert 'Requested' in headers and 'Estimated' in headers and 'Realised' in headers
            expect(page.locator('#stage-order')).to_contain_text('multi-comb-chordness')
            # Confidence masking is visual-only and zoom changes only the viewport.
            circles=page.locator('#timeline .component');assert circles.count()>0
            page.locator('#confidence').fill('0.95');page.locator('#confidence').dispatch_event('input');expect(page.locator('#timeline .component[data-masked="1"]').first).to_be_attached()
            page.locator('#zoom').fill('4');page.locator('#zoom').dispatch_event('input');expect(page.locator('#timeline')).to_have_attribute('data-zoom','4')
            # Linked A/B transport switches audio source; compensation is explicit.
            expect(page.locator('#audio')).to_have_attribute('src',lambda v:'/audio/A' in v)
            page.locator('#slot-b').click();expect(page.locator('#slot-b')).to_have_attribute('aria-pressed','true');expect(page.locator('#audio')).to_have_attribute('src',lambda v:'/audio/B' in v and 'compensated=0' in v)
            page.locator('#compensate').check();expect(page.locator('#audio')).to_have_attribute('src',lambda v:'compensated=1' in v)
            page.locator('#slot-a').click();expect(page.locator('#audio')).to_have_attribute('src',lambda v:'/audio/A' in v)
            # Freeze does not apply. Apply is explicit and undo restores the working sound.
            page.locator('#freeze').click();expect(page.locator('#status')).to_contain_text('frozen');assert page.locator('#working-revision').inner_text()==initial_working
            page.locator('#apply').click();expect(page.locator('#status')).to_contain_text('applied explicitly');applied=page.locator('#working-revision').inner_text();assert applied!=initial_working;expect(page.locator('#undo-depth')).to_have_text('1')
            page.locator('#undo').click();expect(page.locator('#working-revision')).to_have_text(initial_working);expect(page.locator('#undo-depth')).to_have_text('0')
            # A normal rerun can change analysis controls without changing the working sound.
            page.locator('#amount').fill('0.31');page.locator('#amount').dispatch_event('input');page.locator('#sonority').select_option('fourth');page.locator('#analyse').click();expect(page.locator('#status')).to_contain_text('published to inspector only',timeout=120000);assert page.locator('#snapshot-id').inner_text()!=initial_snapshot;expect(page.locator('#working-revision')).to_have_text(initial_working)
            # Force a genuinely pending analysis, rebind A behind it, and prove stale publication is rejected.
            release=threading.Event();original=service_module.build_analysis
            def delayed(*params,**kwargs):
                while not release.wait(.01):
                    checkpoint=kwargs.get('checkpoint')
                    if checkpoint:checkpoint()
                return original(*params,**kwargs)
            with patch.object(service_module,'build_analysis',delayed):
                with page.expect_response('**/api/inspector/analyse') as response:page.locator('#analyse').click()
                job=response.value.json()['job_id'];time.sleep(.05);new_source=server.inspector.replace_source_for_test(9);release.set();server.inspector.scheduler.wait(job,30)
                expect(page.locator('#status')).to_contain_text('Stale analysis rejected',timeout=30000);expect(page.locator('#apply')).to_be_disabled();expect(page.locator('#stale-warning')).to_be_visible();expect(page.locator('#source-revision')).to_have_text(new_source.revision_id[:12])
            page.screenshot(path=args.out/'inspector.png',full_page=True)
            # Core instrument remains the default/root route; Research is optional.
            page.goto(base+'/');expect(page.locator('body')).to_be_visible();assert '/inspector' in page.locator('body').inner_text() or page.locator('a[href="/inspector"]').count()==1
            assert not errors,errors;browser.close()
        report={'method':'zg023-browser-v1','sample_rate_hz':args.sample_rate,'checks':'passed','page_errors':errors,
                'policy':{'analysis_auto_apply':False,'stale_result_rejected':True,'compose_root_remains_available':True}}
        (args.out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps(report))
    finally:
        server.shutdown();server.server_close();thread.join(3)
if __name__=='__main__':main()
