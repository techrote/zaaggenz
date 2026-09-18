from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import argparse,json,os,sys,threading,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from playwright.sync_api import sync_playwright,expect
from zaaggenz_runtime import ZaaggenzServer


def get_json(base,path):
    with urllib.request.urlopen(base+path,timeout=30) as r:return json.loads(r.read())

def post_json(base,path,payload,token):
    req=urllib.request.Request(base+path,data=json.dumps(payload).encode(),method='POST',headers={'Content-Type':'application/json','X-Zaaggenz-Token':token})
    with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read())

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    server=ZaaggenzServer(0,args.sample_rate);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}';errors=[]
    try:
        runtime=get_json(base,'/api/runtime/bootstrap');token=runtime['token'];timeline=get_json(base,'/api/timeline/bootstrap');document=timeline['document']
        document['name']='Unified runtime browser';document['end_beat']='2/1';document['notes']=[{'id':'browser-runtime','beat':'0/1','duration_beats':'1/2','degree':0,'detune_cents':0.,'gain_db':-12.,'muted':False,'roll_density':0}];document['clips']=[];document['next_id']=1
        render=post_json(base,'/api/timeline/render',{'document':document,'region':{'start_beat':'0/1','end_beat':'1/1'},'name':'Unified browser source'},token);server.scheduler.wait(render['job_id'],30);artifact=server.timeline.artifact(render['job_id'])
        stimulus=post_json(base,'/api/listening/freeze',{'job_id':render['job_id'],'name':'Unified exact source','start_frame':0,'end_frame':None},token)
        bound=post_json(base,'/api/inspector/bind',{'job_id':render['job_id']},token)
        assert stimulus['source_asset']['content_sha256']==artifact.asset['content_sha256'];assert bound['source_binding']['content_sha256']==artifact.asset['content_sha256']
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('ZAAGGENZ_CHROMIUM') or None,headless=True,args=['--autoplay-policy=no-user-gesture-required','--mute-audio','--no-sandbox'])
            page=browser.new_page(viewport={'width':1500,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)));page.set_default_timeout(30000)
            page.goto(base+'/');expect(page.locator('#zaaggenz-workspaces')).to_be_visible();
            for href in ('/timeline','/listen','/inspector','/vocal'):assert page.locator(f'a[href="{href}"]').count()==1
            page.goto(base+'/timeline');expect(page.locator('body')).to_be_visible()
            loaded_release=page.evaluate("()=>window.__ZAAGGENZ_WEB_RELEASE__")
            assert loaded_release['release_id']==runtime['web_releases']['timeline']['release_id']
            assert loaded_release['api_version']==runtime['api_version']

            # Keep the page alive while the backend's release identity changes.
            # The already-loaded entry module remains bound to the old identity,
            # so its next state-changing fetch must fail closed. A reload then
            # obtains newly fingerprinted HTML/JS and succeeds on the same origin.
            old_release=server.web_releases['timeline'];new_id=('0' if old_release.release_id[0]!='0' else '1')+old_release.release_id[1:]
            server.web_releases['timeline']=replace(old_release,release_id=new_id)
            stale=page.evaluate("""async ({document,token})=>{const r=await fetch('/api/timeline/validate',{method:'POST',headers:{'Content-Type':'application/json','X-Zaaggenz-Token':token},body:JSON.stringify({document})});return {status:r.status,body:await r.json()};}""",{'document':document,'token':token})
            assert stale['status']==409,stale;assert 'reload' in stale['body']['error'].lower()
            page.reload();expect(page.locator('body')).to_be_visible();reloaded_release=page.evaluate("()=>window.__ZAAGGENZ_WEB_RELEASE__")
            assert reloaded_release['release_id']==new_id
            recovered=page.evaluate("""async ({document,token})=>{const r=await fetch('/api/timeline/validate',{method:'POST',headers:{'Content-Type':'application/json','X-Zaaggenz-Token':token},body:JSON.stringify({document})});return {status:r.status,body:await r.json()};}""",{'document':document,'token':token})
            assert recovered['status']==200,recovered

            page.goto(base+'/listen');expect(page.locator('body')).to_be_visible()
            participant=page.evaluate("async()=>await (await fetch('/api/listening/bootstrap')).json()");assert participant['token']==token;assert 'trusted_token' not in participant;assert participant['capability']['role']=='participant';assert participant['web_release']['release_id']==runtime['web_releases']['listening']['release_id']
            page.goto(base+'/inspector');expect(page.locator('#source-revision')).to_have_text(artifact.revision_id[:12],timeout=60000);expect(page.locator('#source-content')).to_have_text(artifact.asset['content_sha256'][:12])
            page.goto(base+'/vocal');expect(page.locator('body')).to_be_visible();vocal=page.evaluate("async()=>await (await fetch('/api/vocal/bootstrap')).json()");assert vocal['source_session']['timeline_revision_id']==artifact.revision_id;assert 'proposal-only' in vocal['application_policy']
            edited=deepcopy(document);edited['name']='Browser authoritative edit';edited['notes'][0]['degree']=4;validated=post_json(base,'/api/timeline/validate',{'document':edited},token);assert validated['revision_id']!=artifact.revision_id
            page.goto(base+'/inspector');state=page.evaluate("async()=>await (await fetch('/api/inspector/state')).json()");assert state['source_stale'] is True;assert state['authoritative_revision_id']==validated['revision_id']
            current=page.evaluate("async()=>await (await fetch('/api/timeline/bootstrap')).json()");assert current['session']['timeline_revision_id']==validated['revision_id'];assert current['document']['name']=='Browser authoritative edit'
            page.goto(base+'/');page.screenshot(path=args.out/'unified-runtime.png',full_page=True);assert not errors,errors;browser.close()
        report={'method':'zg041-unified-runtime-browser-v2','sample_rate_hz':args.sample_rate,'checks':'passed','page_errors':errors,
                'routes':['/','/timeline','/listen','/inspector','/vocal'],'shared_artifact':{'revision_id':artifact.revision_id,'recipe_sha256':artifact.recipe_sha256,'cache_key':artifact.cache_key,'content_sha256':artifact.asset['content_sha256']},
                'web_release':{'stale_running_frontend_status':409,'old_release_id':old_release.release_id,'replacement_release_id':new_id,'reload_recovered':True},
                'authoritative_edit_revision':validated['revision_id'],'participant_trusted_boundary':'separate','vocal_application_policy':'proposal-only'}
        (args.out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps(report,sort_keys=True))
    finally:
        server.shutdown();server.server_close();thread.join(3)
if __name__=='__main__':main()
