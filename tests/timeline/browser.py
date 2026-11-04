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
            # Owner-approved ZG-022 sounds are ordinary Compose presets with
            # stable identity across the normal save/reopen path.
            expect(page.locator('#source-preset')).to_have_value('locked_bloom')
            page.locator('#source-preset').select_option('zaag.upper-chop');ready()
            expect(page.locator('#source-preset')).to_have_value('zaag.upper-chop')
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
            preset_saved=saved('upper-chop-preset.zgtimeline.json')
            preset_recipe=json.loads(preset_saved['project']['revisions'][-1]['recipe_json'])
            assert preset_recipe['source']['id']=='zaag.upper-chop'
            page.locator('#open').set_input_files(args.out/'upper-chop-preset.zgtimeline.json');ready()
            expect(page.locator('#source-preset')).to_have_value('zaag.upper-chop')
            page.locator('#source-preset').select_option('locked_bloom');ready()
            expect(page.locator('#source-preset')).to_have_value('locked_bloom')
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
            # MBR-003: actual Compose source-bound rack proposal, normal
            # validation/admission, numerical WAV, project/preset persistence
            # and restoration of the exact dry signal.
            dry_id=rendered('rack-original')
            dry_pcm=server.timeline.scheduler.result(dry_id).audio_bytes
            page.locator('#rack-meter-panel').evaluate('(e)=>e.open=true')
            expect(page.locator('#rack-meters')).to_contain_text('dry source path')
            page.locator('#rack-editor').get_by_role('button',name='Enable four-band rack').click();ready()
            lowmid=page.locator('#rack-editor .rack-band').nth(1)
            lowmid.get_by_role('button',name='Add gain').click();ready()
            gain_field=page.locator('#rack-editor .rack-band').nth(1).locator('.rack-stage input[type=number]').last
            gain_field.fill('9');gain_field.dispatch_event('change')
            # A pending authoritative rack proposal must invalidate playback
            # and prevent an old-revision render from racing its adoption.
            expect(page.locator('#render')).to_be_disabled()
            expect(page.locator('#rack-meters')).to_contain_text('No current completed render')
            ready()
            changed_id=rendered('rack-gain-nine')
            changed_pcm=server.timeline.scheduler.result(changed_id).audio_bytes
            assert changed_pcm!=dry_pcm,'editing gain must alter actual rendered PCM'
            # Measurements come exclusively from the accepted completed artifact,
            # not values in editable controls or a fabricated live meter.
            measured=server.timeline.status(changed_id)['artifact']
            rack_report=measured['scopes']['diagnostics']['rack']
            assert len(rack_report['bands'])==4
            lowmid_report=rack_report['bands'][1]
            assert lowmid_report['band']=='lowmid'
            assert lowmid_report['stages'][0]['executed']
            report_text=page.locator('#rack-meters').inner_text()
            assert measured['revision_id'] in report_text
            assert 'LOWMID' in report_text and 'post-band wet' in report_text
            assert 'zg.gain' in report_text and 'stage output' in report_text
            assert 'full phrase context' in report_text
            assert not any(a in report_text for a in ('NaN','undefined'))
            # Source-bound raw/dry A/B runs the real numerical engine without
            # mutating the current Compose project or export selection.
            before_monitor=server.timeline.session.current_identity()
            expect(page.locator('#prepare-dry')).to_be_enabled()
            page.locator('#prepare-dry').click()
            expect(page.locator('#hear-dry')).to_be_enabled(timeout=120000)
            assert server.timeline.session.current_identity()==before_monitor
            dry_job=page.locator('#hear-dry').get_attribute('data-job-id')
            assert dry_job and server.timeline.scheduler.result(dry_job).audio_bytes==dry_pcm
            assert server.timeline.scheduler.result(dry_job).audio_bytes!=changed_pcm
            page.locator('#hear-dry').click()
            expect(page.locator('#playback-revision')).to_contain_text('DRY MONITOR ONLY')
            expect(page.locator('#monitor-mode')).to_contain_text('Download processed WAV')
            expect(page.locator('#rack-meters')).to_contain_text('No current completed render')
            with page.expect_download() as ab_download:
                page.locator('#download').click()
            ab_path=args.out/'rack-ab-processed-export.wav'
            ab_download.value.save_as(ab_path)
            assert ab_path.read_bytes()==(args.out/'rack-gain-nine.wav').read_bytes(), (
                'dry monitoring must not replace the processed export')
            page.locator('#hear-processed').click()
            expect(page.locator('#playback-revision')).to_have_text(page.locator('#revision').inner_text())
            expect(page.locator('#rack-meters')).to_contain_text('LOWMID')
            assert server.timeline.session.current_identity()==before_monitor
            # Reset built-in parameters without replacing the stage identity or
            # overwriting the separately saved wet/bypass/source settings.
            stage_before=saved('rack-before-parameter-reset.zgtimeline.json')
            stage_before=json.loads(stage_before['project']['revisions'][-1]['recipe_json'])['rack']['bands'][1]['inserts'][0]
            page.locator('#rack-editor .rack-band').nth(1).get_by_role(
                'button',name='Reset parameters').click();ready()
            stage_reset=saved('rack-after-parameter-reset.zgtimeline.json')
            stage_reset=json.loads(stage_reset['project']['revisions'][-1]['recipe_json'])['rack']['bands'][1]['inserts'][0]
            assert stage_reset['id']==stage_before['id'] and stage_reset['params']['gain_db']==0
            assert stage_reset['wet']==stage_before['wet'] and stage_reset['bypass']==stage_before['bypass']
            reset_id=rendered('rack-gain-parameter-reset')
            assert server.timeline.scheduler.result(reset_id).audio_bytes!=changed_pcm
            gain_field=page.locator('#rack-editor .rack-band').nth(1).locator('.rack-stage input[type=number]').last
            gain_field.fill('9');gain_field.dispatch_event('change');ready()
            reapply_id=rendered('rack-gain-restored-after-reset')
            assert server.timeline.scheduler.result(reapply_id).audio_bytes==changed_pcm
            # Rack save is project-local, never a source/factory preset mutation.
            page.locator('#rack-editor').get_by_role('button',name='Save new preset').click();ready()
            rack_saved=saved('rack-processed.zgtimeline.json')
            assert 'rack' in json.loads(rack_saved['project']['revisions'][-1]['recipe_json'])
            page.get_by_label('Load saved preset').select_option('user.myrack')
            portable_path=args.out/'rack-exported.zgrack.json'
            with page.expect_download() as pending_preset:
                page.get_by_role('button',name='Export selected preset').click()
            pending_preset.value.save_as(portable_path)
            portable=json.loads(portable_path.read_text(encoding='utf-8'))
            assert portable['format']=='zaaggenz-rack-preset' and portable['version']=='1.0.0'
            assert portable['rack']==rack_saved['project']['rack_presets']['user.myrack']['rack']
            assert portable['rack_sha256']==rack_saved['project']['rack_presets']['user.myrack']['rack_sha256']
            assert 'user.myrack' in rack_saved['project']['rack_presets']
            page.locator('#open').set_input_files(args.out/'rack-processed.zgtimeline.json');ready()
            reload_id=rendered('rack-reopened')
            assert server.timeline.scheduler.result(reload_id).audio_bytes==changed_pcm
            # Two controls changed while the first backend proposal is blocked
            # must be serialized rather than silently dropping the second edit.
            # Saving/rendering old PCM is prohibited until both are admitted.
            gate=threading.Event();entered=threading.Event()
            propose=server.timeline.propose_rack_edit
            def held_proposal(*a,**kw):
                entered.set()
                if not gate.wait(10):
                    raise RuntimeError('bounded rack edit proposal gate expired')
                return propose(*a,**kw)
            with patch.object(server.timeline,'propose_rack_edit',held_proposal):
                wet=page.get_by_label('Rack wet')
                wet.fill('0.65');wet.dispatch_event('change')
                assert entered.wait(5),'rack edit did not enter the backend'
                page.get_by_label('Bypass rack').check()
                expect(page.locator('#render')).to_be_disabled()
                expect(page.locator('#save')).to_be_disabled()
                gate.set()
                page.wait_for_function(
                    "() => !document.querySelector('#render').disabled && !document.querySelector('#save').disabled",
                    timeout=30000)
            queued_saved=saved('rack-rapid-edits.zgtimeline.json')
            queued_recipe=json.loads(queued_saved['project']['revisions'][-1]['recipe_json'])['rack']
            assert queued_recipe['wet']==0.65
            assert queued_recipe['bypass'] is True
            # Both edits must be independently undoable against stable rack IDs.
            page.locator('#undo').click();ready()
            undo_recipe=json.loads(saved('rack-rapid-undo.zgtimeline.json')['project']['revisions'][-1]['recipe_json'])['rack']
            assert undo_recipe['wet']==0.65 and undo_recipe['bypass'] is False
            page.locator('#redo').click();ready()
            redo_recipe=json.loads(saved('rack-rapid-redo.zgtimeline.json')['project']['revisions'][-1]['recipe_json'])['rack']
            assert redo_recipe==queued_recipe
            # User preset edits are explicit; no source or factory preset mutation.
            page.get_by_label('Load saved preset').select_option('user.myrack')
            page.get_by_label('Preset name').fill('Renamed rack')
            page.get_by_role('button',name='Rename selected preset').click();ready()
            named=saved('rack-renamed-preset.zgtimeline.json')
            assert named['project']['rack_presets']['user.myrack']['name']=='Renamed rack'
            page.get_by_label('Bypass rack').uncheck();ready()
            lowmid=page.locator('#rack-editor .rack-band').nth(1)
            lowmid.get_by_role('button',name='Remove insert').click();ready()
            removed=saved('rack-removed-insert.zgtimeline.json')
            removed_recipe=json.loads(removed['project']['revisions'][-1]['recipe_json'])['rack']
            assert not removed_recipe['bands'][1]['inserts']
            page.get_by_label('Load saved preset').select_option('user.myrack')
            page.get_by_role('button',name='Replace selected preset').click();ready()
            replaced=saved('rack-replaced-preset.zgtimeline.json')
            assert replaced['project']['rack_presets']['user.myrack']['rack']==removed_recipe
            removed_id=rendered('rack-insert-removed')
            assert server.timeline.scheduler.result(removed_id).audio_bytes==dry_pcm
            page.screenshot(path=args.out/'compose-rack-four-band.png',full_page=True)
            page.locator('#rack-editor').get_by_role('button',name='Remove rack (dry)').click();ready()
            restored_id=rendered('rack-removed')
            assert server.timeline.scheduler.result(restored_id).audio_bytes==dry_pcm
            # Portable rack import into an otherwise dry project must not
            # change the active rack until explicitly recalled.
            page.locator('#open').set_input_files(args.out/'four-bar.zgtimeline.json');ready()
            expect(page.locator('#rack-editor')).to_contain_text('No rack is installed')
            page.get_by_label('Import rack preset file').set_input_files(portable_path);ready()
            fresh_with_preset=saved('rack-portable-import.zgtimeline.json')
            assert 'user.myrack' in fresh_with_preset['project']['rack_presets']
            assert 'rack' not in json.loads(fresh_with_preset['project']['revisions'][-1]['recipe_json'])
            page.get_by_label('Load saved preset').select_option('user.myrack')
            page.get_by_role('button',name='Load',exact=True).click();ready()
            portable_id=rendered('rack-portable-recall')
            assert server.timeline.scheduler.result(portable_id).audio_bytes==changed_pcm
            # Deletion requires user confirmation and only drops the saved
            # preset inventory. Never rewrite the active rack or factory source.
            page.get_by_label('Load saved preset').select_option('user.myrack')
            delete_button=page.get_by_role('button',name='Delete selected preset')
            page.once('dialog',lambda dialog:dialog.dismiss())
            delete_button.click()
            assert 'user.myrack' in saved('rack-preset-deletion-dismissed.zgtimeline.json')['project']['rack_presets']
            page.once('dialog',lambda dialog:dialog.accept())
            delete_button.click();ready()
            after_delete=saved('rack-preset-deleted.zgtimeline.json')
            assert 'user.myrack' not in after_delete['project']['rack_presets']
            assert json.loads(after_delete['project']['revisions'][-1]['recipe_json'])['rack']==portable['rack']
            post_delete_id=rendered('rack-after-preset-delete')
            assert server.timeline.scheduler.result(post_delete_id).audio_bytes==changed_pcm
            page.get_by_label('Import rack preset file').set_input_files(portable_path);ready()
            assert 'user.myrack' in saved('rack-preset-reimported.zgtimeline.json')['project']['rack_presets']
            # Restore the pre-rack document so the following legacy
            # four-bar revision identity/save-reopen regression stays intact.
            page.locator('#open').set_input_files(args.out/'four-bar.zgtimeline.json')
            expect(page.locator('#revision')).to_have_text(TimelineDocument(data4).revision_id)
            ready()
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
            page.locator('#open').set_input_files(args.out/'four-bar.zgtimeline.json')
            expect(page.locator('#revision')).to_have_text(TimelineDocument(data4).revision_id)
            ready()
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
                'scope':'real browser and numerical server; owner approval is separate recorded ZG-022 evidence'}
        (args.out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps({'checks':'passed','renders':len(evidence),'sample_rate_hz':args.sample_rate}))
    finally:
        server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':main()
