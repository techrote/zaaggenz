from __future__ import annotations
import argparse,hashlib,json,os,re,sys,threading,time,urllib.request
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from playwright.sync_api import sync_playwright,expect
from zaaggenz_inspector.server import InspectorServer
from zaaggenz_inspector import service as service_module
from zaaggenz_jobs import JobClass,RenderArtifact

def post_json(base,path,payload,token):
    req=urllib.request.Request(base+path,data=json.dumps(payload).encode(),method='POST',headers={'Content-Type':'application/json','X-Zaaggenz-Token':token})
    with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read())

def prepare_bound_render(server,base):
    with urllib.request.urlopen(base+'/api/timeline/bootstrap',timeout=10) as r:boot=json.loads(r.read())
    document=boot['document'];document['notes']=[{'id':'browser-source','beat':'0/1','duration_beats':'1/2','degree':0,'detune_cents':0.,'gain_db':0.,'muted':False,'roll_density':0}];document['next_id']=1
    render=post_json(base,'/api/timeline/render',{'document':document,'region':{'start_beat':'0/1','end_beat':'1/1'},'name':'Inspector browser source'},boot['token'])
    server.timeline.scheduler.wait(render['job_id'],30);artifact=server.timeline.scheduler.result(render['job_id'])
    bound=post_json(base,'/api/inspector/bind',{'job_id':render['job_id']},boot['token']);assert bound['source_binding']['content_sha256']==artifact.asset['content_sha256']
    return boot['token'],artifact

def replacement_artifact(artifact):
    revision=hashlib.sha256(b'browser-replacement-revision').hexdigest();recipe=hashlib.sha256(b'browser-replacement-recipe').hexdigest();cache=hashlib.sha256(b'browser-replacement-cache').hexdigest()
    return RenderArtifact(revision,recipe,artifact.product,cache,artifact.audio_bytes,artifact.asset,artifact.scopes)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    server=InspectorServer(0,args.sample_rate);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}';errors=[]
    try:
        token,artifact=prepare_bound_render(server,base)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('ZAAGGENZ_CHROMIUM') or None,headless=True,args=['--autoplay-policy=no-user-gesture-required','--mute-audio','--no-sandbox'])
            page=browser.new_page(viewport={'width':1500,'height':1200});page.on('pageerror',lambda e:errors.append(str(e)));page.set_default_timeout(20000);page.goto(base+'/inspector')
            expect(page.locator('#status')).to_contain_text('artifact bound',timeout=60000);expect(page.locator('#source-revision')).to_have_text(artifact.revision_id[:12]);expect(page.locator('#source-recipe')).to_have_text(artifact.recipe_sha256[:12]);expect(page.locator('#source-cache')).to_have_text(artifact.cache_key[:12]);expect(page.locator('#source-content')).to_have_text(artifact.asset['content_sha256'][:12])
            initial_working=page.locator('#working-revision').inner_text();expect(page.locator('#apply')).to_be_disabled();expect(page.locator('#slot-b')).to_be_disabled()
            page.locator('#analyse').click();expect(page.locator('#status')).to_contain_text('published to inspector only',timeout=120000);initial_snapshot=page.locator('#snapshot-id').inner_text()
            expect(page.locator('#pitch-table tr').first).to_be_visible();headers=page.locator('thead').inner_text();assert 'Requested' in headers and 'Estimated' in headers and 'Realised' in headers
            expect(page.locator('#stage-order')).to_contain_text('multi-comb-chordness');circles=page.locator('#timeline .component');assert circles.count()>0
            page.locator('#confidence').fill('0.95');page.locator('#confidence').dispatch_event('input');expect(page.locator('#timeline .component[data-masked="1"]').first).to_be_attached()
            page.locator('#zoom').fill('4');page.locator('#zoom').dispatch_event('input');expect(page.locator('#timeline')).to_have_attribute('data-zoom','4')
            expect(page.locator('#audio')).to_have_attribute('src',re.compile(r'/api/inspector/audio/A\?'))
            page.locator('#slot-b').click();expect(page.locator('#slot-b')).to_have_attribute('aria-pressed','true');expect(page.locator('#audio')).to_have_attribute('src',re.compile(r'/api/inspector/audio/B\?compensated=0'))
            page.locator('#compensate').check();expect(page.locator('#audio')).to_have_attribute('src',re.compile(r'compensated=1'))
            page.locator('#slot-a').click();expect(page.locator('#audio')).to_have_attribute('src',re.compile(r'/api/inspector/audio/A\?'))
            page.locator('#freeze').click();expect(page.locator('#status')).to_contain_text('frozen');assert page.locator('#working-revision').inner_text()==initial_working
            page.locator('#apply').click();expect(page.locator('#status')).to_contain_text('applied explicitly');applied=page.locator('#working-revision').inner_text();assert applied!=initial_working;expect(page.locator('#undo-depth')).to_have_text('1')
            page.locator('#undo').click();expect(page.locator('#working-revision')).to_have_text(initial_working);expect(page.locator('#undo-depth')).to_have_text('0')
            page.locator('#amount').fill('0.31');page.locator('#amount').dispatch_event('input');page.locator('#sonority').select_option('fourth');page.locator('#analyse').click();expect(page.locator('#status')).to_contain_text('published to inspector only',timeout=120000);assert page.locator('#snapshot-id').inner_text()!=initial_snapshot;expect(page.locator('#working-revision')).to_have_text(initial_working)
            release=threading.Event();original=service_module.build_analysis
            def delayed(*params,**kwargs):
                while not release.wait(.01):
                    checkpoint=kwargs.get('checkpoint')
                    if checkpoint:checkpoint()
                return original(*params,**kwargs)
            with patch.object(service_module,'build_analysis',delayed):
                with page.expect_response('**/api/inspector/analyse') as response:page.locator('#analyse').click()
                job=response.value.json()['job_id'];time.sleep(.05);new_artifact=replacement_artifact(artifact);replacement_job=server.timeline.scheduler.submit(JobClass.RENDER,new_artifact.revision_id,lambda ctx:new_artifact,estimated_memory_bytes=8*1024*1024);server.timeline.scheduler.wait(replacement_job,10);post_json(base,'/api/inspector/bind',{'job_id':replacement_job},token);release.set();server.inspector.scheduler.wait(job,30)
                expect(page.locator('#status')).to_contain_text('Stale analysis rejected',timeout=30000);expect(page.locator('#apply')).to_be_disabled();expect(page.locator('#snapshot-id')).to_have_text('—');expect(page.locator('#source-revision')).to_have_text(new_artifact.revision_id[:12]);expect(page.locator('#source-content')).to_have_text(new_artifact.asset['content_sha256'][:12])
            page.screenshot(path=args.out/'inspector.png',full_page=True)
            page.goto(base+'/');expect(page.locator('body')).to_be_visible();assert page.locator('a[href="/inspector"]').count()==1;assert page.locator('a[href="/timeline"]').count()==1
            assert not errors,errors;browser.close()
        report={'method':'zg023-browser-v2','sample_rate_hz':args.sample_rate,'checks':'passed','page_errors':errors,'bound_source':{'revision_id':artifact.revision_id,'recipe_sha256':artifact.recipe_sha256,'cache_key':artifact.cache_key,'content_sha256':artifact.asset['content_sha256']},'policy':{'analysis_auto_apply':False,'stale_result_rejected':True,'render_artifact_binding':True,'compose_root_remains_available':True}}
        (args.out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps(report))
    finally:
        server.shutdown();server.server_close();thread.join(3)
if __name__=='__main__':main()
