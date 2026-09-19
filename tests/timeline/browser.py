"""Real Chromium UI + real numerical server; writes generated evidence, never reference audio."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from playwright.sync_api import sync_playwright, expect
from zaaggenz_timeline.server import TimelineServer
from zaaggenz_timeline.model import TimelineDocument
from zaaggenz_timeline import service as service_module


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--sample-rate',type=int,default=48000)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    server=TimelineServer(0,args.sample_rate)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/timeline'
    errors=[];evidence=[]
    try:
        with sync_playwright() as p:
            executable=os.environ.get('ZAAGGENZ_CHROMIUM')
            browser=p.chromium.launch(executable_path=executable or None,headless=True,
                                      args=['--autoplay-policy=no-user-gesture-required','--mute-audio','--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1100},accept_downloads=True)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.set_default_timeout(15000)
            page.goto(url)
            def ready():
                try:
                    expect(page.locator('#render')).to_be_enabled(timeout=30000)
                except Exception:
                    print('Browser status:',page.locator('#status').inner_text(),errors,flush=True)
                    page.screenshot(path=args.out/'failure.png',full_page=True)
                    raise
            ready()
            def saved(name):
                ready()
                with page.expect_download() as download:page.locator('#save').click()
                path=args.out/name;download.value.save_as(path)
                return json.loads(path.read_text(encoding='utf-8'))
            def rendered(name,region=False):
                ready();page.locator('#output-name').fill(name)
                page.locator('#render-region' if region else '#render').click()
                expect(page.locator('#play')).to_be_enabled(timeout=120000)
                expect(page.locator('#playback-revision')).to_have_text(page.locator('#revision').inner_text())
                assert page.locator('#waveform').get_attribute('data-revision')==page.locator('#revision').inner_text()
                page.locator('#play').click()
                page.wait_for_function("!document.getElementById('audio').paused")
                page.locator('#audio').evaluate('(a)=>a.pause()')
                with page.expect_download() as download:page.locator('#download').click()
                path=args.out/(name+'.wav');download.value.save_as(path)
                job=page.locator('#outputs').input_value()
                artifact=server.timeline.status(job)['artifact']
                evidence.append({'name':name,'revision_id':artifact['revision_id'],'artifact':artifact,
                                 'wav_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
                return job
            # Principal editing: rational snap, notes, rests, rolls, move, resize, mute.
            page.locator('#snap').select_option('1/12')
            page.locator('#beat').fill('1/3');page.locator('#duration').fill('1/2');page.locator('#degree').fill('4')
            page.locator('#add').click();ready()
            expect(page.locator('#roll .note')).to_have_count(1)
            page.locator('#duplicate').click();ready();expect(page.locator('#roll .note')).to_have_count(2)
            twice=saved('two-events.zgtimeline.json')
            page.locator('#undo').click();ready();expect(page.locator('#roll .note')).to_have_count(1)
            page.locator('#redo').click();ready();assert saved('two-events-redone.zgtimeline.json')==twice
            page.locator('#event-list button').nth(1).click()
            page.locator('#beat').fill('2');page.locator('#duration').fill('1');page.locator('#density').select_option('8')
            page.locator('#apply').click();ready();page.locator('#mute').click();ready()
            assert saved('muted.zgtimeline.json')['notes'][1]['muted'] is True
            page.locator('#mute').click();ready()
            page.locator('#rest').check();page.locator('#beat').fill('4');page.locator('#add').click();ready()
            assert saved('with-rest.zgtimeline.json')['notes'][-1]['degree'] is None
            # Mouse moving and resizing use the real SVG geometry.
            rect=page.locator('#roll .note').first;box=rect.bounding_box();assert box
            page.mouse.move(box['x']+5,box['y']+5);page.mouse.down();page.mouse.move(box['x']+35,box['y']+5);page.mouse.up();ready()
            moved=saved('mouse-moved.zgtimeline.json');assert moved['notes'][0]['beat']!='1/3'
            box=page.locator('#roll .note').first.bounding_box()
            page.keyboard.down('Shift');page.mouse.move(box['x']+5,box['y']+5);page.mouse.down();page.mouse.move(box['x']+35,box['y']+5);page.mouse.up();page.keyboard.up('Shift');ready()
            assert saved('mouse-resized.zgtimeline.json')['notes'][0]['duration_beats']!='1/2'
            # Four-bar render and saved project reopening without manual file editing.
            page.locator('#example4').click();ready()
            data4=saved('four-bar.zgtimeline.json');assert len(data4['notes'])==32
            full_job=rendered('four-bar-full')
            first_revision=page.locator('#revision').inner_text()
            page.locator('#region-start').fill('1/4');page.locator('#region-end').fill('4')
            page.locator('#clip-name').fill('Crossing selection');page.locator('#add-clip').click();ready()
            region_job=rendered('four-bar-region',True)
            region=server.timeline.scheduler.result(region_job);full=server.timeline.scheduler.result(full_job)
            lo=round(args.sample_rate*.3*.25);hi=round(args.sample_rate*.3*4)
            assert region.audio_bytes==full.audio_bytes[lo*4:hi*4]
            # Editing clears native playback/scopes; selecting a named output restores its revision.
            page.locator('#master').fill('-3');page.locator('#master').dispatch_event('change');ready()
            expect(page.locator('#play')).to_be_disabled();assert not page.locator('#audio').get_attribute('src')
            assert page.locator('#waveform').get_attribute('data-revision')==''
            page.locator('#outputs').select_option(full_job);ready()
            expect(page.locator('#playback-revision')).to_have_text(first_revision)
            page.locator('#stop').click();expect(page.locator('#play')).to_be_disabled()
            page.locator('#master').fill('-9');page.locator('#master').dispatch_event('change');ready()
            page.locator('#open').set_input_files(args.out/'four-bar.zgtimeline.json');ready()
            expect(page.locator('#revision')).to_have_text(first_revision)
            second_full=rendered('four-bar-reopened')
            assert server.timeline.scheduler.result(full_job).audio_bytes==server.timeline.scheduler.result(second_full).audio_bytes
            # Sixteen bars, including source-sliced rolls, named clips and visible scopes.
            page.locator('#example16').click();ready()
            data16=saved('sixteen-bar.zgtimeline.json');assert len(data16['notes'])==128
            rendered('sixteen-bar-full')
            page.screenshot(path=args.out/'timeline-sixteen-bars.png',full_page=True)
            # A real pending numerical job cannot publish after a user edit.
            release=threading.Event();original=service_module.region_executor
            def delayed(*params):
                execute=original(*params)
                def run(ctx):
                    while not release.wait(.01):ctx.check_cancelled()
                    return execute(ctx)
                return run
            with patch.object(service_module,'region_executor',delayed):
                ready()
                with page.expect_response('**/api/timeline/render') as response:page.locator('#render').click()
                pending=response.value.json()['job_id']
                page.locator('#master').fill('-6');page.locator('#master').dispatch_event('change');ready()
                expect(page.locator('#play')).to_be_disabled()
                # Pump browser events so its cancellation request reaches the server.
                page.wait_for_timeout(150);release.set()
                state=server.timeline.scheduler.wait(pending,10).state
                assert state=='cancelled',state
                page.wait_for_timeout(150);expect(page.locator('#play')).to_be_disabled()
                assert page.locator('#waveform').get_attribute('data-revision')==''
            # Legacy controls remain accessible, not replaced by this optional authoring view.
            # ZG-041 adds a second explicit workspace link; target the recovered
            # full-instrument link rather than relying on legacy-link cardinality.
            page.locator('a.legacy[href="/"]').click();expect(page.locator('a[href="/timeline"]')).to_be_visible()
            assert not errors,errors
            browser.close()
        report={'method':'zg009-browser-v1','sample_rate_hz':args.sample_rate,'browser':'Chromium',
                'checks':'passed','page_errors':errors,'examples':evidence,
                'scope':'real browser and numerical server; no owner listening approval implied'}
        (args.out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps({'checks':'passed','renders':len(evidence),'sample_rate_hz':args.sample_rate}))
    finally:
        server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':main()
