"""Real Chromium acceptance for frozen material, blinded ABX playback, ratings, annotation and Compose independence."""
from __future__ import annotations
import argparse,json,sys,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from playwright.sync_api import sync_playwright,expect
from zaaggenz_listening.server import ListeningServer
from zaaggenz_timeline import TimelineDocument,default_document

SR=12000
def timeline(name,degree,gain):
    d=default_document(SR).to_dict();d['name']=name;d['end_beat']='2/1';d['notes']=[{'id':'n-0','beat':'0/1','duration_beats':'1/1','degree':degree,'detune_cents':0.,'gain_db':gain,'muted':False,'roll_density':0}];d['clips']=[];d['next_id']=1;return TimelineDocument(d).to_dict()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    project_a=a.out/'a.zgtimeline.json';project_b=a.out/'b.zgtimeline.json';project_a.write_text(json.dumps(timeline('A',0,-18)));project_b.write_text(json.dumps(timeline('B',4,-12)))
    server=ListeningServer(0,SR);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{server.server_port}/listen';errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required','--mute-audio','--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True);page.on('pageerror',lambda e:errors.append(str(e)));page.set_default_timeout(30000);page.goto(url)
            expect(page.locator('#status')).to_contain_text('optional');page.locator('#projects').set_input_files([project_a,project_b]);page.locator('#materialise').click();expect(page.locator('.stimulus')).to_have_count(2,timeout=90000);expect(page.locator('#create')).to_be_enabled()
            page.locator('#design').select_option('abx');page.locator('#seed').fill('77');page.locator('#create').click();expect(page.locator('#players button')).to_have_count(3);expect(page.locator('#instructions')).to_contain_text('Accuracy is recorded separately')
            public_tid=next(iter(server.listening._participant_to_trusted));trusted_tid=server.listening._participant_to_trusted[public_tid];truth=server.listening.trials[trusted_tid].to_dict()['abx_truth'];assert public_tid!=trusted_tid
            for i in range(3):
                page.locator('#players button').nth(i).click();page.wait_for_function("!document.getElementById('player').paused",timeout=15000);page.locator('#player').evaluate('(a)=>a.pause()')
            page.locator('#choice').select_option(truth)
            ranges=page.locator('[data-endpoint]');expect(ranges).to_have_count(2);ranges.nth(0).fill('65');ranges.nth(1).fill('45');page.locator('#confidence').fill('73');page.locator('#effort').fill('27')
            page.locator('#players button').nth(0).click();page.wait_for_timeout(100);page.locator('#player').evaluate('(a)=>a.pause()');page.locator('#response button').click();expect(page.locator('#status')).to_contain_text('Annotation added')
            page.locator('#submit').click();expect(page.locator('#status')).to_contain_text('Result stored')
            result=server.listening.results[trusted_tid][-1].to_dict();assert result['abx_correct'] is True;assert result['x_replay_count']==1;assert result['confidence']==73;assert result['effort']==27;assert set(result['ratings'])=={'liking','sound_quality'};assert 'abx_correct' not in result['ratings'];assert len(result['annotations'])==1
            with page.expect_download() as dl:page.locator('#export').click()
            bundle_path=a.out/'trial.json';dl.value.save_as(bundle_path);bundle=json.loads(bundle_path.read_text());assert bundle['format']=='zaaggenz-listening-participant-bundle';assert bundle['trial']['id']==public_tid;assert bundle['trial']['abx_truth'] is None;assert 'seed' not in bundle['trial'];assert bundle['results'][-1]['abx_correct'] is None;assert trusted_tid not in bundle_path.read_text();assert len(bundle['stimuli'])==2
            trusted=server.listening.export_bundle(public_tid);assert trusted['manifest']['id']==trusted_tid;assert trusted['manifest']['abx_truth']==truth;assert trusted['results'][-1]['abx_correct'] is True
            page.screenshot(path=a.out/'listening-abx.png',full_page=True);page.goto(f'http://127.0.0.1:{server.server_port}/timeline');expect(page.locator('#roll')).to_be_visible();assert not errors,errors;browser.close()
        report={'checks':'passed','design':'abx','participant_trial_id':public_tid,'trusted_trial_id_withheld_from_browser':True,'abx_correct':True,'participant_export_blind':True,'ratings_fields':sorted(result['ratings']),'confidence':result['confidence'],'effort':result['effort'],'x_replay_count':result['x_replay_count'],'annotation_count':len(result['annotations']),'compose_independent':True,'page_errors':errors}
        (a.out/'browser-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'checks':'passed','participant_trial_id':public_tid}))
    finally:
        server.shutdown();server.server_close();thread.join(3)
if __name__=='__main__':main()
