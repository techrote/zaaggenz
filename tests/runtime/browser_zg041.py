"""Real Chromium acceptance for the explicit Compose/Research workspace boundary."""
from __future__ import annotations
import argparse,json,os,sys,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from playwright.sync_api import sync_playwright,expect
from zaaggenz_runtime import ZaaggenzServer


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    server=ZaaggenzServer(0,args.sample_rate);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}';errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('ZAAGGENZ_CHROMIUM') or None,headless=True,args=['--autoplay-policy=no-user-gesture-required','--mute-audio','--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)));page.set_default_timeout(30000)
            page.goto(base+'/timeline');expect(page.locator('#render')).to_be_enabled(timeout=60000)
            expect(page.locator('.eyebrow')).to_have_text('ZAAGGENZ / COMPOSE')
            self_initial=page.locator('#revision').inner_text()
            page.locator('#project-name').fill('ZG-041 workspace persistence')
            page.locator('#project-name').dispatch_event('change')
            page.wait_for_function("initial=>document.getElementById('revision').textContent!==initial && !document.getElementById('revision').textContent.includes('Validating')",self_initial)
            compose_revision=page.locator('#revision').inner_text();assert compose_revision!=self_initial
            session_before=server.session.snapshot();assert session_before['timeline_revision_id']==compose_revision

            page.locator('#research-workspace-link').click();page.wait_for_url('**/research')
            expect(page.locator('#research-workspace')).to_be_visible();expect(page.locator('.eyebrow')).to_have_text('ZAAGGENZ / RESEARCH')
            expect(page.locator('#research-timeline-revision')).to_have_text(compose_revision)
            assert page.locator('#render').count()==0
            assert server.session.snapshot()==session_before

            # Accepted research tools remain reachable from the explicit hub,
            # but merely entering Research does not acquire trusted authority or
            # mutate the authoritative Compose revision.
            page.locator('#research-inspector').click();page.wait_for_url('**/inspector');expect(page.locator('body')).to_be_visible();assert server.session.snapshot()==session_before
            page.goto(base+'/research');page.locator('#research-listening').click();page.wait_for_url('**/listen');expect(page.locator('body')).to_be_visible();assert server.session.snapshot()==session_before
            page.goto(base+'/research');page.locator('#research-vocal').click();page.wait_for_url('**/vocal');expect(page.locator('body')).to_be_visible();assert server.session.snapshot()==session_before

            page.goto(base+'/research');page.locator('#compose-workspace-link').click();page.wait_for_url('**/timeline');expect(page.locator('#render')).to_be_enabled(timeout=60000)
            expect(page.locator('#project-name')).to_have_value('ZG-041 workspace persistence')
            expect(page.locator('#revision')).to_have_text(compose_revision)
            assert server.session.snapshot()==session_before
            page.screenshot(path=args.out/'compose-after-research.png',full_page=True)
            assert not errors,errors;browser.close()
        report={'method':'zg041-compose-research-browser-v1','sample_rate_hz':args.sample_rate,'checks':'passed','page_errors':errors,
                'compose_revision':compose_revision,'research_revision':session_before['timeline_revision_id'],
                'routes':['/timeline','/research','/inspector','/listen','/vocal'],
                'invariants':['compose-default','research-get-no-mutation','sidecars-reachable','compose-state-survives-switch']}
        (args.out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps(report,sort_keys=True))
    finally:
        server.shutdown();server.server_close();thread.join(3)

if __name__=='__main__':main()
