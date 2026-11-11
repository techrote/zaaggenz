"""Real Chromium UI + real numerical server; writes generated evidence, never reference audio."""
from __future__ import annotations
import argparse
import hashlib
import json
import numpy as np
from fractions import Fraction
import os
import time
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
            def ready(timeout=30000):
                try:
                    expect(page.locator('#render')).to_be_enabled(timeout=timeout)
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
                expect(page.locator('#playback-revision')).to_have_text(page.locator('#revision').text_content().strip())
                assert page.locator('#waveform').get_attribute('data-revision')==page.locator('#revision').text_content().strip()
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
            # Deliberately hold old /validate *inside the real backend*.
            # Render a newer ordinary Compose revision before releasing it;
            # the old response must fail closed without revoking new PCM.
            held_validation_entered = threading.Event()
            release_held_validation = threading.Event()
            compile_before_hold = service_module.compile_recipe

            def held_old_validation(document):
                if document.to_dict()['name'] == 'Held old Compose validation':
                    held_validation_entered.set()
                    if not release_held_validation.wait(60):
                        raise RuntimeError('stale validation test gate expired')
                return compile_before_hold(document)

            try:
                with patch.object(service_module, 'compile_recipe', held_old_validation):
                    project_name = page.locator('#project-name')
                    project_name.fill('Held old Compose validation')
                    # Native blur triggers exactly one DOM change; synthetic
                    # dispatch while still focused can trigger another when
                    # Save later receives focus, invalidating its own click.
                    project_name.press('Tab')
                    assert held_validation_entered.wait(10), (
                        'the old authoritative validation did not enter real backend')
                    expect(page.locator('#render')).to_be_disabled()
                    project_name.fill('Newer Compose validation')
                    project_name.press('Tab')
                    ready()
                    expect(page.locator('#save')).to_be_enabled()
                    newer_project = saved('rack-validation-newer-revision.zgtimeline.json')
                    newer_revision = TimelineDocument(newer_project).revision_id
                    newer_job = rendered('rack-validation-newer-numerical')
                    newer_pcm = server.timeline.scheduler.result(newer_job).audio_bytes
                    assert len(newer_pcm) > 0
                    with page.expect_response(
                        lambda response: response.url.endswith('/api/timeline/validate')
                            and response.status == 400, timeout=15000) as stale:
                        release_held_validation.set()
                    assert 'superseded' in stale.value.json()['error']
                    assert server.timeline.session.current_identity()[1] == newer_revision
                    assert server.timeline.status(newer_job)['accepted']
                    assert server.timeline.scheduler.result(newer_job).audio_bytes == newer_pcm
                    expect(page.locator('#revision')).to_have_text(newer_revision)
            finally:
                release_held_validation.set()
            # Hold an older real /render POST before its session commit, then
            # validate and numerically render a newer edit. The old response
            # must fail closed server-side, not merely be ignored by Chromium.
            held_render_entered = threading.Event()
            release_held_render = threading.Event()
            old_render_revision = newer_revision
            original_region_executor = service_module.region_executor

            def held_old_render(recipe, revision, region):
                if revision == old_render_revision:
                    held_render_entered.set()
                    if not release_held_render.wait(60):
                        raise RuntimeError('stale authoritative render gate expired')
                return original_region_executor(recipe, revision, region)

            try:
                with patch.object(service_module, 'region_executor', held_old_render):
                    with page.expect_response(
                        lambda response: response.url.endswith('/api/timeline/render')
                            and response.status == 400, timeout=15000) as rejected:
                        page.locator('#render').click()
                        assert held_render_entered.wait(10), (
                            'old render did not enter threaded backend before commit')
                        project_name = page.locator('#project-name')
                        project_name.fill('Winner after stale render')
                        project_name.press('Tab')
                        ready()
                        winning_doc = saved('rack-stale-render-winner.zgtimeline.json')
                        winning_revision = TimelineDocument(winning_doc).revision_id
                        winning_job = rendered('rack-stale-render-winner-numerical')
                        winning_pcm = server.timeline.scheduler.result(winning_job).audio_bytes
                        winning_identity = server.timeline.session.current_identity()
                        assert len(winning_pcm) > 0
                        release_held_render.set()
                    assert 'superseded' in rejected.value.json()['error']
                assert server.timeline.session.current_identity() == winning_identity
                assert winning_identity[1] == winning_revision
                assert server.timeline.status(winning_job)['accepted']
                assert server.timeline.scheduler.result(winning_job).audio_bytes == winning_pcm
                expect(page.locator('#revision')).to_have_text(winning_revision)
            finally:
                release_held_render.set()
            # Restore the frozen example before the existing dry/rack oracles.
            page.locator('#open').set_input_files(args.out/'four-bar.zgtimeline.json')
            ready()
            dry_id=rendered('rack-original')
            dry_pcm=server.timeline.scheduler.result(dry_id).audio_bytes
            page.locator('#rack-meter-panel').evaluate('(e)=>e.open=true')
            expect(page.locator('#rack-meters')).to_contain_text('dry source path')
            # A delayed source preset proposal must never overwrite a newer
            # four-band rack installation. It cannot silently roll the single
            # RuntimeSession back after the rack has been validated either.
            # The source proposal is held at the actual threaded HTTP service
            # while the normal Chromium UI enables a real rack.
            race_before=saved('rack-preset-race-before.zgtimeline.json')
            entered=threading.Event();release_preset=threading.Event()
            original_proposal=server.timeline.propose_source_preset
            def held_source_proposal(*params):
                entered.set()
                if not release_preset.wait(20):
                    raise RuntimeError('source preset proposal release timed out')
                return original_proposal(*params)
            with patch.object(server.timeline,'propose_source_preset',held_source_proposal):
                try:
                    with page.expect_response('**/api/timeline/preset-proposal') as response:
                        page.locator('#source-preset').select_option('zaag.upper-chop')
                        assert entered.wait(10),'source preset proposal did not reach the server'
                        page.locator('#rack-editor').get_by_role(
                            'button',name='Enable four-band rack').click()
                        ready()
                        release_preset.set()
                    assert response.value.status==200
                    expect(page.locator('#source-preset')).to_be_enabled(timeout=10000)
                finally:
                    release_preset.set()
            ready()
            race_after=saved('rack-preset-race-stale-rejected.zgtimeline.json')
            assert race_after['notes']==race_before['notes']
            assert race_after['master_gain_db']==race_before['master_gain_db']
            race_recipe=json.loads(race_after['project']['revisions'][-1]['recipe_json'])
            assert race_recipe['source']['id']=='locked_bloom'
            assert len(race_recipe['rack']['bands'])==4
            expect(page.locator('#source-preset')).to_have_value('locked_bloom')
            assert server.timeline.session.current_identity()[1]==TimelineDocument(race_after).revision_id
            race_job=rendered('rack-preset-race-preserved-rack')
            assert server.timeline.scheduler.result(race_job).audio_bytes==dry_pcm
            # A server-validated redraw must not throw keyboard users back to
            # the document root or lose the focused editable rack control.
            # These are real DOM/async proposal transitions, not mock state.
            # Preset form drafts must not be thrown away by the async redraw
            # after an unrelated accepted rack edit on the same source.
            page.locator('#rack-editor').get_by_label('Preset name').fill('Uncommitted draft')
            page.locator('#rack-editor').get_by_label('Preset ID',exact=False).fill('user.uncommitted')
            wet_focus=page.locator('#rack-editor').get_by_label('Rack wet')
            wet_focus.fill('0.8');wet_focus.dispatch_event('change');ready()
            expect(page.locator('#rack-editor').get_by_label('Rack wet')).to_be_focused()
            expect(page.locator('#rack-editor').get_by_label('Rack wet')).to_have_value('0.8')
            expect(page.locator('#rack-editor').get_by_label('Preset name')).to_have_value('Uncommitted draft')
            expect(page.locator('#rack-editor').get_by_label('Preset ID',exact=False)).to_have_value('user.uncommitted')
            wet_focus=page.locator('#rack-editor').get_by_label('Rack wet')
            wet_focus.fill('1');wet_focus.dispatch_event('change');ready()
            expect(page.locator('#rack-editor').get_by_label('Rack wet')).to_be_focused()
            # A new root project may reuse a visible control's stable key.
            # Redrawing it must not steal keyboard focus or carry an unsaved
            # preset draft across source ancestry. Exercise the shipped
            # module in real Chromium without mutating the server session.
            focus_context = page.evaluate("""async () => {
                const entry = document.querySelector('script[type="module"]');
                const release = new URL(entry.src).search;
                const {renderRack} = await import('/timeline/rack-ui.mjs' + release);
                const host = document.createElement('div');
                document.body.append(host);
                try {
                    const a = {present:false, presets:[], working_context:'root-A'};
                    renderRack(host, a, () => {});
                    const field = host.querySelector('[data-preset-field="name"]');
                    field.value = 'unsaved name from A';
                    field.focus();
                    renderRack(host, a, () => {});
                    const same = host.querySelector('[data-preset-field="name"]');
                    const kept = document.activeElement === same &&
                        same.value === 'unsaved name from A';
                    renderRack(host, {...a, working_context:'root-B'}, () => {});
                    const other = host.querySelector('[data-preset-field="name"]');
                    return {kept, leakedDraft:other.value === 'unsaved name from A',
                            stoleFocus:document.activeElement === other};
                } finally {host.remove();}
            }""")
            assert focus_context == {
                'kept': True, 'leakedDraft': False, 'stoleFocus': False,
            }, focus_context
            # Crossover UI admission mirrors the exact DSP contract: strictly
            # increasing neighbors and a strict 0.49*Fs high ceiling. Rejected
            # controls cannot publish a new revision or silently clamp values.
            crossover_before=saved('rack-crossovers-before.zgtimeline.json')
            crossover_identity=server.timeline.session.current_identity()
            initial_crossovers=json.loads(
                crossover_before['project']['revisions'][-1]['recipe_json'])['rack']['crossovers']['frequencies_hz']
            mid=page.locator('#rack-editor').get_by_label('Crossover 2',exact=False)
            high=page.locator('#rack-editor').get_by_label('Crossover 3',exact=False)
            high.fill(str(int(0.49*args.sample_rate)))
            high.dispatch_event('change')
            assert high.evaluate('(e)=>e.validity.customError')
            assert 'must be less than' in high.evaluate('(e)=>e.validationMessage')
            assert saved('rack-crossover-ceiling-rejected.zgtimeline.json')==crossover_before
            assert server.timeline.session.current_identity()==crossover_identity
            mid.fill(str(initial_crossovers[2]));mid.dispatch_event('change')
            assert mid.evaluate('(e)=>e.validity.customError')
            assert 'must be less than' in mid.evaluate('(e)=>e.validationMessage')
            assert saved('rack-crossover-order-rejected.zgtimeline.json')==crossover_before
            assert server.timeline.session.current_identity()==crossover_identity
            # HTML number inputs are not required by default. An empty or
            # out-of-bounds sonic value must explain which control is invalid
            # and must never dispatch a detached rack proposal or mutate the
            # canonical RuntimeSession. The browser is the real Chromium UI.
            rack_wet=page.locator('#rack-editor').get_by_label('Rack wet',exact=False)
            rack_wet.fill('');rack_wet.dispatch_event('change')
            assert rack_wet.evaluate('(e)=>e.validity.customError')
            assert 'Rack wet requires a finite numeric value' in rack_wet.evaluate('(e)=>e.validationMessage')
            assert server.timeline.session.current_identity()==crossover_identity
            assert saved('rack-blank-wet-rejected.zgtimeline.json')==crossover_before
            rack_wet.fill('1.1');rack_wet.dispatch_event('change')
            assert rack_wet.evaluate('(e)=>e.validity.customError')
            assert 'Rack wet must be at most 1' in rack_wet.evaluate('(e)=>e.validationMessage')
            assert server.timeline.session.current_identity()==crossover_identity
            assert saved('rack-overflow-wet-rejected.zgtimeline.json')==crossover_before
            mid=page.locator('#rack-editor').get_by_label('Crossover 2',exact=False)
            mid.fill('650');mid.dispatch_event('change');ready()
            changed_crossovers=saved('rack-crossover-valid.zgtimeline.json')
            assert json.loads(changed_crossovers['project']['revisions'][-1]['recipe_json'])['rack']['crossovers']['frequencies_hz'][1]==650
            assert changed_crossovers!=crossover_before
            # Restore the initial numerical routing before the established
            # dry-versus-processed PCM and persistence acceptance sequence.
            mid=page.locator('#rack-editor').get_by_label('Crossover 2',exact=False)
            mid.fill(str(initial_crossovers[1]));mid.dispatch_event('change');ready()
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
            processed_peak=measured['scopes']['diagnostics']['master_peak']
            dry_peak=server.timeline.status(dry_job)['artifact']['scopes']['diagnostics']['master_peak']
            assert processed_peak>0 and dry_peak>0
            expect(page.locator('#peak-match')).to_be_enabled()
            page.locator('#peak-match').check()
            processed_volume=min(processed_peak,dry_peak)/processed_peak
            assert abs(page.locator('#audio').evaluate('(e)=>e.volume')-processed_volume)<1e-6
            page.locator('#hear-dry').click()
            dry_volume=min(processed_peak,dry_peak)/dry_peak
            assert abs(page.locator('#audio').evaluate('(e)=>e.volume')-dry_volume)<1e-6
            expect(page.locator('#peak-match-status')).to_contain_text('attenuation only')
            page.locator('#peak-match').uncheck()
            assert page.locator('#audio').evaluate('(e)=>e.volume')==1
            page.locator('#peak-match').check()
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
            expect(page.locator('#playback-revision')).to_have_text(page.locator('#revision').text_content().strip())
            expect(page.locator('#rack-meters')).to_contain_text('LOWMID')
            assert abs(page.locator('#audio').evaluate('(e)=>e.volume')-processed_volume)<1e-6
            assert server.timeline.session.current_identity()==before_monitor
            # Post-master band solo/mute is a separate numerical listening job:
            # the full processed output remains the sole downloadable artifact.
            expect(page.locator('#prepare-band')).to_be_enabled()
            page.locator('#monitor-band').select_option('lowmid')
            page.locator('#monitor-action').select_option('solo')
            page.locator('#prepare-band').click()
            expect(page.locator('#hear-band')).to_be_enabled(timeout=120000)
            band_job=page.locator('#hear-band').get_attribute('data-job-id')
            assert band_job
            band_artifact=server.timeline.status(band_job)['artifact']
            assert band_artifact['scopes']['diagnostics']['monitor']['band']=='lowmid'
            assert band_artifact['scopes']['diagnostics']['monitor']['mode']=='solo'
            assert server.timeline.scheduler.result(band_job).audio_bytes!=changed_pcm
            page.locator('#hear-band').click()
            expect(page.locator('#playback-revision')).to_contain_text('BAND LOWMID SOLO MONITOR ONLY')
            expect(page.locator('#monitor-mode')).to_contain_text('not the pre-rack band stem')
            expect(page.locator('#peak-match')).to_be_disabled()
            expect(page.locator('#rack-meters')).to_contain_text('No current completed render')
            with page.expect_download() as monitor_download:
                page.locator('#download').click()
            monitor_path=args.out/'rack-band-monitor-processed-export.wav'
            monitor_download.value.save_as(monitor_path)
            assert monitor_path.read_bytes()==(args.out/'rack-gain-nine.wav').read_bytes()
            assert server.timeline.session.current_identity()==before_monitor
            # Changing the monitoring choice revokes the old object URL and
            # restores authoritative processed playback, rather than leaving
            # an old band audition under the newly selected mode. Even an
            # A→B→A reversal must not resurrect a stale monitoring result.
            page.locator('#monitor-action').select_option('mute')
            expect(page.locator('#hear-band')).to_be_disabled()
            expect(page.locator('#audio')).to_have_attribute('data-monitor-kind', 'processed')
            expect(page.locator('#playback-revision')).to_have_text(page.locator('#revision').text_content().strip())
            page.locator('#monitor-action').select_option('solo')
            expect(page.locator('#hear-band')).to_be_disabled()
            expect(page.locator('#prepare-band')).to_be_enabled()
            page.locator('#monitor-action').select_option('mute')
            expect(page.locator('#hear-band')).to_be_disabled()
            page.locator('#prepare-band').click()
            expect(page.locator('#hear-band')).to_be_enabled(timeout=120000)
            mute_job=page.locator('#hear-band').get_attribute('data-job-id')
            assert mute_job!=band_job
            assert server.timeline.status(mute_job)['artifact']['scopes']['diagnostics']['monitor']['mode']=='mute'
            page.locator('#hear-processed').click()
            expect(page.locator('#playback-revision')).to_have_text(page.locator('#revision').text_content().strip())
            expect(page.locator('#rack-meters')).to_contain_text('LOWMID')
            # Reset built-in parameters without replacing the stage identity or
            # overwriting the separately saved wet/bypass/source settings.
            stage_before=saved('rack-before-parameter-reset.zgtimeline.json')
            stage_before=json.loads(stage_before['project']['revisions'][-1]['recipe_json'])['rack']['bands'][1]['inserts'][0]
            page.locator('#rack-editor .rack-band').nth(1).get_by_role(
                'button',name='Reset parameters').click();ready()
            expect(page.locator('#peak-match')).to_be_disabled()
            assert page.locator('#audio').evaluate('(e)=>e.volume')==1
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
            # The draft-continuity exercise above deliberately changed the
            # form fields. Restore the established preset fixture identity
            # before running the separate portable import/export oracle.
            page.locator('#rack-editor').get_by_label('Preset name').fill('My rack')
            page.locator('#rack-editor').get_by_label('Preset ID',exact=False).fill('user.myrack')
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
            # The same four-bar spectral request can fit the 256 MiB full-
            # context budget at 12 kHz (ZG-041 browser lane), but exceed it at
            # 48 kHz (ZG-009 browser lane). Query a *detached* authoritative
            # backend proposal before the UI edit to establish the correct
            # admission result at this rate. Neither branch may mutate the
            # working Project on an unsuccessful proposal.
            page.locator('#rack-editor').get_by_role('button',name='Remove rack (dry)').click();ready()
            page.locator('#rack-editor').get_by_role('button',name='Enable four-band rack').click();ready()
            budget_before=saved('rack-spectral-budget-before.zgtimeline.json')
            before_revision=page.locator('#revision').text_content().strip()
            before_identity=server.timeline.session.current_identity()
            band_id=json.loads(budget_before['project']['revisions'][-1]['recipe_json'])[
                'rack']['bands'][1]['id']
            budget_action={'kind':'add','band':band_id,'type_id':'zg.spectral'}
            try:
                proposed=server.timeline.propose_rack_edit(budget_before,budget_action)
            except Exception as error:
                assert 'rack full-context memory estimate exceeds working-memory bound' in str(error),str(error)
                proposed=None
            assert server.timeline.session.current_identity()==before_identity, (
                'Detached rack proposal changed authoritative session')
            page.locator('#rack-editor .rack-band').nth(1).get_by_role(
                'button',name='Add spectral').click();ready()
            if proposed is None:
                expect(page.locator('#status')).to_contain_text(
                    'rack full-context memory estimate exceeds working-memory bound')
                expect(page.locator('#status')).to_contain_text('Shorten the phrase')
                expect(page.locator('#revision')).to_have_text(before_revision)
                assert saved('rack-spectral-budget-rejected.zgtimeline.json')==budget_before
            else:
                expect(page.locator('#revision')).to_have_text(proposed['revision_id'])
                admitted=saved('rack-spectral-budget-admitted.zgtimeline.json')
                assert admitted==proposed['document']
                admitted_stages=json.loads(admitted['project']['revisions'][-1][
                    'recipe_json'])['rack']['bands'][1]['inserts']
                assert sum(stage['type_id']=='zg.spectral' for stage in admitted_stages)==1
                assert proposed['estimated_memory_bytes'] <= (
                    server.timeline.scheduler.limits.max_job_memory_bytes)

            # Exercise actual source-bound spectral DSP on a smaller accepted
            # timeline, without bypassing the 256 MiB full-context cap. Preserve
            # the original source Project and two first-bar notes and import the
            # fully validated fixture through ordinary Compose, not a mock.
            first_bar=[n for n in data4['notes']
                       if Fraction(n['beat'])+Fraction(n['duration_beats'])<=4]
            assert len(first_bar)>=2, 'four-bar fixture must contain first-bar notes'
            short_doc=TimelineDocument({**data4,
                'name':'One-bar internal spectral qualification',
                'end_beat':'4/1', 'notes':first_bar[:2], 'clips':[]})
            short_path=args.out/'one-bar-spectral-fixture.zgtimeline.json'
            short_path.write_text(json.dumps(short_doc.to_dict(),sort_keys=True)+'\n',encoding='utf-8')
            page.locator('#open').set_input_files(short_path)
            expect(page.locator('#revision')).to_have_text(short_doc.revision_id)
            ready()
            one_bar_dry_job=rendered('rack-one-bar-dry-reference')
            one_bar_dry_pcm=server.timeline.scheduler.result(one_bar_dry_job).audio_bytes
            # Real spectral request authoring uses the accepted source tuning,
            # executes the existing band-selective DSP and saves its exact
            # nested target/selection contract. No new audio backend or mock.
            page.locator('#rack-editor').get_by_role('button',name='Enable four-band rack').click();ready()
            # The ordinary Compose UI must actually CREATE a source-bound
            # Chordness request from manually entered comb teeth. A preloaded
            # JSON-only Chordness project is not an editable instrument.
            lowmid=page.locator('#rack-editor .rack-band').nth(1)
            chord_form=lowmid.locator('.rack-chordness-create')
            chord_form.evaluate('(e)=>e.open=true')
            teeth=chord_form.get_by_label('Manual comb teeth (Hz, comma-separated)')
            initial_chord_doc=saved('rack-chordness-before.zgtimeline.json')
            initial_chord_identity=server.timeline.session.current_identity()
            teeth.fill('110, 110')
            chord_form.get_by_role('button',name='Add manual Chordness (off)').click()
            assert teeth.evaluate('(e)=>e.validity.customError')
            assert 'strictly increasing' in teeth.evaluate('(e)=>e.validationMessage')
            assert server.timeline.session.current_identity()==initial_chord_identity
            assert saved('rack-chordness-invalid.zgtimeline.json')==initial_chord_doc
            teeth.fill('110, 220, 330')
            chord_form.get_by_label('Manual comb label').fill('Musical upper comb')
            chord_form.get_by_role('button',name='Add manual Chordness (off)').click();ready()
            chord_document=saved('rack-chordness-created.zgtimeline.json')
            chord_rack=json.loads(chord_document['project']['revisions'][-1]['recipe_json'])['rack']
            chord_stage=chord_rack['bands'][1]['inserts'][0]
            assert chord_stage['params']['kind']=='ChordnessRequest'
            assert chord_stage['params']['mode']=='off'
            assert chord_stage['params']['templates'][0]['teeth_hz']==[110.,220.,330.]
            assert chord_stage['params']['templates'][0]['label']=='Musical upper comb'
            assert chord_stage['params']['selected_template_ids']==['user.manual']
            assert chord_document['project']['revisions'][0]==short_doc.to_dict()['project']['revisions'][0]
            chord_panel=lowmid.locator('.rack-stage').filter(
                has=page.locator('.rack-stage-id',has_text=chord_stage['id']))
            expect(chord_panel).to_have_count(1)
            chord_panel.locator('.rack-spectral').evaluate('(e)=>e.open=true')
            # The requested mode is a specifically named, accessible select;
            # do not infer identity from a generic select ordinal or from the
            # separate selection_mode policy field.

            # A second manual comb is created and edited from this same
            # ordinary Compose session; it is not an imported JSON-only stub.
            new_teeth=chord_panel.get_by_label(
                'New Chordness template teeth (Hz, comma-separated)')
            new_teeth.fill('110, 110')
            chord_panel.get_by_role(
                'button',name='Add Chordness template (unselected)').click()
            assert new_teeth.evaluate('(e)=>e.validity.customError')
            new_teeth.fill('150, 300, 450')
            chord_panel.get_by_label('New Chordness template label').fill('Second comb')
            chord_panel.get_by_role(
                'button',name='Add Chordness template (unselected)').click();ready()
            multi=saved('rack-chordness-two-templates.zgtimeline.json')
            params=json.loads(multi['project']['revisions'][-1]['recipe_json'])[
                'rack']['bands'][1]['inserts'][0]['params']
            assert len(params['templates'])==2
            assert params['templates'][1]['id']=='user.manual.2'
            assert params['templates'][1]['teeth_hz']==[150.,300.,450.]
            assert params['selected_template_ids']==['user.manual']
            # Changing this template is an intentional saved sonic edit.
            edited_teeth=chord_panel.get_by_label(
                'Template user.manual.2 teeth (Hz, comma-separated)')
            edited_teeth.fill('165, 330, 495')
            edited_teeth.press('Tab');ready()
            changed=saved('rack-chordness-edited-template.zgtimeline.json')
            params=json.loads(changed['project']['revisions'][-1]['recipe_json'])[
                'rack']['bands'][1]['inserts'][0]['params']
            assert params['templates'][1]['teeth_hz']==[165.,330.,495.]
            cap=chord_panel.get_by_label('max selected templates',exact=False)
            cap.fill('2');cap.press('Tab');ready()
            chord_panel.get_by_label('Select template Second comb (user.manual.2)').check();ready()
            # Original 48-kHz one-bar dry-source PCM was independently exercised
            # with the accepted saved-rack executor: targeting 140/280/420 Hz
            # in lowmid gives active spectral frames in both orderings and
            # 1.53e-3 RMS order-difference without hidden normalization.
            # Select that genuinely transformable pocket instead of highmid,
            # where original tracker evidence is almost entirely abstentions.
            # This is still an
            # ordinary source-bound UI edit, not a fabricated server request.
            high_teeth=chord_panel.get_by_label(
                'Template user.manual.2 teeth (Hz, comma-separated)')
            high_teeth.fill('140, 280, 420')
            high_teeth.press('Tab');ready()
            chord_panel.get_by_label(
                'Select template Musical upper comb (user.manual)').uncheck();ready()
            for label,value in (('min confidence · ratio','0'),
                                ('max gain db · dB','18'),
                                ('max gain slew db per second · dB/s','120')):
                field=chord_panel.get_by_label(label)
                field.fill(value);field.dispatch_event('change');ready()
            chord_panel.get_by_label('preserve ambiguous').uncheck();ready()
            chord_panel.get_by_role('combobox',name='mode',exact=True).select_option('reweight');ready()
            activated=saved('rack-chordness-active.zgtimeline.json')
            activated_rack=json.loads(activated['project']['revisions'][-1]['recipe_json'])['rack']
            assert activated_rack['bands'][1]['inserts'][0]['params']['mode']=='reweight'
            chord_job=rendered('rack-chordness-reweight')
            chord_audio=server.timeline.scheduler.result(chord_job).audio_bytes
            assert len(chord_audio)>44
            chord_report=server.timeline.status(chord_job)['artifact']['scopes']['diagnostics']['rack']
            assert any(stage['type_id']=='zg.spectral' and stage['executed']
                       for row in chord_report['bands'] for stage in row['stages'])
            chord_processor=next(stage['processor'] for stage in chord_report['bands'][1]['stages']
                                 if stage['type_id']=='zg.spectral')
            assert chord_processor['diagnostics']['changed_frames']>0, (
                'The lowmid Chordness fixture is an inactive/abstained spectral transform: '
                +repr(chord_processor['diagnostics']))
            assert chord_audio!=one_bar_dry_pcm, (
                'Active Chordness must change numerical Compose PCM, not only metadata')
            page.locator('#open').set_input_files(args.out/'rack-chordness-active.zgtimeline.json');ready()
            chord_reloaded=rendered('rack-chordness-reopened')
            assert server.timeline.scheduler.result(chord_reloaded).audio_bytes==chord_audio
            # MBR-003 independent-review closure: an actual user-authored
            # noncommuting spectral/compressor chain in the normal Compose UI.
            # The immediately preceding numerical spectral render must already
            # show changed component frames and PCM against a matched dry source.
            # Add the compressor through the browser, not through a preloaded
            # RackRecipe, and use one stable stage identity for both orders.
            lowmid=page.locator('#rack-editor .rack-band').nth(1)
            lowmid.get_by_role('button',name='Add compression').click();ready()
            added=saved('rack-order-with-compressor.zgtimeline.json')
            added_stages=json.loads(added['project']['revisions'][-1]['recipe_json'])[
                'rack']['bands'][1]['inserts']
            assert [stage['type_id'] for stage in added_stages]==[
                'zg.spectral','zg.compression'], added_stages
            compressor_id=added_stages[1]['id']
            compression_panel=lowmid.locator('.rack-stage').filter(
                has=page.locator('.rack-stage-id',has_text=compressor_id))
            expect(compression_panel).to_have_count(1)
            for label,value in (('threshold db · dBFS','-40'),
                                ('ratio · ratio','8'),
                                ('attack ms · ms','0.1'),
                                ('release ms · ms','35')):
                field=compression_panel.get_by_label(label)
                field.fill(value);field.dispatch_event('change');ready()
            order_a_doc=saved('rack-order-spectral-then-compression.zgtimeline.json')
            order_a=json.loads(order_a_doc['project']['revisions'][-1]['recipe_json'])[
                'rack']['bands'][1]['inserts']
            assert [stage['id'] for stage in order_a]==[chord_stage['id'],compressor_id]
            order_a_job=rendered('rack-order-spectral-then-compression')
            order_a_audio=server.timeline.scheduler.result(order_a_job).audio_bytes
            order_a_status=server.timeline.status(order_a_job)['artifact']
            order_a_report=order_a_status['scopes']['diagnostics']['rack']
            assert order_a_report['normalization']=='none'
            assert order_a_report['bands'][1]['order']==[chord_stage['id'],compressor_id]
            # The move button must operate the compressor's *existing ID*.
            # An old completed result is revoked on the intervening edit.
            compression_panel.get_by_role('button',name='Move up').click()
            expect(page.locator('#play')).to_be_disabled()
            ready()
            order_b_doc=saved('rack-order-compression-then-spectral.zgtimeline.json')
            order_b=json.loads(order_b_doc['project']['revisions'][-1]['recipe_json'])[
                'rack']['bands'][1]['inserts']
            assert [stage['id'] for stage in order_b]==[compressor_id,chord_stage['id']]
            assert {stage['id']:stage for stage in order_a}=={
                stage['id']:stage for stage in order_b}, (
                'The UI reorder changed stable identities, stage parameters or bypass policy')
            order_b_job=rendered('rack-order-compression-then-spectral')
            order_b_audio=server.timeline.scheduler.result(order_b_job).audio_bytes
            order_b_status=server.timeline.status(order_b_job)['artifact']
            order_b_report=order_b_status['scopes']['diagnostics']['rack']
            assert order_b_report['normalization']=='none'
            assert order_b_report['bands'][1]['order']==[compressor_id,chord_stage['id']]
            # An actually active transform, not a no-op spectral request or a
            # makeup-only compressor, is required in *both* orders.
            measured_order=[]
            for report in (order_a_report,order_b_report):
                rows=report['bands'][1]['stages']
                assert all(row['executed'] for row in rows),rows
                spectrum=next(row['processor']['diagnostics']
                              for row in rows if row['type_id']=='zg.spectral')
                dynamics=next(row['processor']['diagnostics']
                              for row in rows if row['type_id']=='zg.compression')
                assert spectrum['changed_frames']>0, (
                    'No numerical spectral action in a claimed noncommuting order: '
                    +repr(spectrum))
                assert dynamics['max_gain_reduction_db']>0, (
                    'No actual gain reduction in a claimed noncommuting order: '
                    +repr(dynamics))
                measured_order.append({
                    'spectral_changed_frames':spectrum['changed_frames'],
                    'compressor_max_gain_reduction_db':dynamics['max_gain_reduction_db']})
            # RenderArtifact.audio_bytes is *raw little-endian float32 PCM*.
            # The separately downloaded .wav is the user-facing container.
            # Compare the actual sample stream, never RIFF headers or revisions.
            # A superseded job is deliberately revoked from the live status
            # API after the UI reorder. Use the immutable artifact snapshots
            # captured while each revision was current; never re-read stale
            # job status and mistake its absence for a render failure.
            assert order_a_status['asset']['sample_rate_hz']==args.sample_rate
            assert order_b_status['asset']['sample_rate_hz']==args.sample_rate
            assert len(order_a_audio)==len(order_b_audio) and len(order_a_audio)%4==0
            samples_a=np.frombuffer(order_a_audio,dtype='<f4')
            samples_b=np.frombuffer(order_b_audio,dtype='<f4')
            assert np.isfinite(samples_a).all() and np.isfinite(samples_b).all()
            diff=samples_a.astype(np.float64)-samples_b.astype(np.float64)
            difference_rms=float(np.sqrt(np.mean(diff*diff)))
            assert difference_rms>1e-5, (
                'Spectral/compressor order must change PCM measurably on this '
                'prequalified source: RMS difference='+repr(difference_rms))
            (args.out/'rack-order-numerical-evidence.json').write_text(json.dumps({
                'source':'one-bar ordinary Compose saved project',
                'sample_rate_hz':args.sample_rate,
                'stage_ids':[chord_stage['id'],compressor_id],
                'stage_order_a':[stage['id'] for stage in order_a],
                'stage_order_b':[stage['id'] for stage in order_b],
                'stage_activity':measured_order,
                'pcm_difference_rms_full_scale':difference_rms,
                'normalization':'none',
                'raw_pcm_sha256_a':hashlib.sha256(order_a_audio).hexdigest(),
                'raw_pcm_sha256_b':hashlib.sha256(order_b_audio).hexdigest(),
            },sort_keys=True,indent=2)+'\n',encoding='utf-8')
            # Reopen both exact authored revisions and demand byte-identical
            # processed WAVs, not a cached monitor result. Bypassing the
            # complete chain must reproduce the one-bar no-rack PCM exactly.
            page.locator('#open').set_input_files(
                args.out/'rack-order-spectral-then-compression.zgtimeline.json');ready()
            reopened_a=rendered('rack-order-spectral-then-compression-reopened')
            assert server.timeline.scheduler.result(reopened_a).audio_bytes==order_a_audio
            page.locator('#open').set_input_files(
                args.out/'rack-order-compression-then-spectral.zgtimeline.json');ready()
            reopened_b=rendered('rack-order-compression-then-spectral-reopened')
            assert server.timeline.scheduler.result(reopened_b).audio_bytes==order_b_audio
            page.get_by_label('Bypass rack').check();ready()
            bypassed_job=rendered('rack-order-full-bypass')
            assert server.timeline.scheduler.result(bypassed_job).audio_bytes==one_bar_dry_pcm, (
                'Full rack bypass is not byte-identical to the matched dry Compose source')
            page.get_by_label('Bypass rack').uncheck();ready()
            # Return to one Chordness insert, so the original subsequent
            # spectral-retune and legacy timeline regressions are unchanged.
            lowmid=page.locator('#rack-editor .rack-band').nth(1)
            compression_panel=lowmid.locator('.rack-stage').filter(
                has=page.locator('.rack-stage-id',has_text=compressor_id))
            compression_panel.get_by_role('button',name='Remove insert').click();ready()
            lowmid=page.locator('#rack-editor .rack-band').nth(1)
            lowmid.get_by_role('button',name='Remove insert').click();ready()
            assert not json.loads(saved('rack-chordness-removed.zgtimeline.json')[
                'project']['revisions'][-1]['recipe_json'])['rack']['bands'][1]['inserts']
            # Restore the empty band before exercising the separately owned
            # multivoice, scheduled retune acceptance below.
            lowmid=page.locator('#rack-editor .rack-band').nth(1)
            lowmid.get_by_role('button',name='Add spectral').click();ready()
            # Read the authoritative saved revision before querying the DOM.
            # The visual stage position is not a stable identity: other inserts
            # can survive preset recall or be reordered independently.
            installed=saved('rack-spectral-installed.zgtimeline.json')
            installed_rack=json.loads(installed['project']['revisions'][-1]['recipe_json'])['rack']
            installed_stages=installed_rack['bands'][1]['inserts']
            spectral_matches=[s for s in installed_stages if s['type_id']=='zg.spectral']
            assert len(spectral_matches)==1, (
                'Add spectral did not install exactly one validated request: '+
                page.locator('#status').inner_text()+'; stages='+repr(installed_stages))
            spectral_id=spectral_matches[0]['id']
            assert spectral_matches[0]['params']['kind']=='SpectralRetuneRequest'
            spectral_stage=lowmid.locator('.rack-stage').filter(
                has=page.locator('.rack-stage-id',has_text=spectral_id))
            expect(spectral_stage).to_have_count(1)
            expect(spectral_stage.locator('.rack-spectral')).to_contain_text('Internal spectral retune')
            spectral_stage.locator('.rack-spectral').evaluate('(e)=>e.open=true')
            expect(lowmid).to_have_attribute('aria-label','lowmid processing band')
            expect(spectral_stage).to_have_attribute(
                'aria-label','lowmid zg.spectral '+spectral_id)
            # Contract uses an exclusive 0-Hz bound. The UI must reject zero
            # before sending an invalid backend proposal or changing revision.
            before_invalid=page.locator('#revision').text_content().strip()
            min_hz=spectral_stage.get_by_label('min hz · Hz')
            min_hz.fill('0');min_hz.dispatch_event('change')
            assert min_hz.evaluate('(e)=>e.validity.customError')
            expect(page.locator('#revision')).to_have_text(before_invalid)
            min_hz.fill('30')
            amount=spectral_stage.get_by_label('amount · ratio')
            amount.fill('0.7');amount.dispatch_event('change');ready()
            expect(spectral_stage.locator('.rack-spectral')).to_have_attribute('open','')
            degree=spectral_stage.get_by_label('Primary target degree')
            degree.fill('7');degree.dispatch_event('change');ready()
            # Explicit second voice construction uses the same saved tuning,
            # true request validation and numerical DSP, not a separate
            # simulated monitor or unsaved local-only target.
            add_degree=spectral_stage.get_by_label('Additional target degree')
            add_voice=spectral_stage.get_by_role('button',name='Add retune voice')
            before_add_revision=page.locator('#revision').text_content().strip()
            before_add_identity=server.timeline.session.current_identity()
            for bad,reason in (('', 'requires a whole number'),
                               ('4097', 'must be between -4096 and 4096')):
                add_degree.fill(bad)
                add_voice.click()
                assert add_degree.evaluate('(e)=>e.validity.customError')
                assert reason in add_degree.evaluate('(e)=>e.validationMessage')
                assert server.timeline.session.current_identity()==before_add_identity
                expect(page.locator('#revision')).to_have_text(before_add_revision)
            add_degree.fill('11')
            # Two synchronous clicks originate from the SAME displayed voice
            # snapshot. The first is applied through the serial edit queue;
            # the second must fail stale-snapshot admission, not append a
            # duplicate voice using a new primary target under old intent.
            add_voice.evaluate('(button) => {button.click(); button.click();}')
            ready()
            assert spectral_stage.locator('.rack-target-voice').count()==2
            second=spectral_stage.get_by_role('group',name='Retune target voice 2')
            ratios=second.get_by_label('Voice 2 partial ratios (comma-separated)')
            ratios.fill('1, 1.5, 3');ratios.dispatch_event('change');ready()
            # Specialist text edits must retain keyboard focus across the
            # actual authoritative async redraw, just like numeric controls.
            expect(second.get_by_label('Voice 2 partial ratios (comma-separated)')).to_be_focused()
            voice_label=second.get_by_label('Voice 2 label')
            voice_label.fill('Upper interval')
            voice_label.dispatch_event('change');ready()
            expect(second.get_by_label('Voice 2 label')).to_be_focused()
            expect(second.get_by_label('Voice 2 label')).to_have_value('Upper interval')
            before_invalid_ratio=page.locator('#revision').text_content().strip()
            ratios=second.get_by_label('Voice 2 partial ratios (comma-separated)')
            ratios.fill('1, 1');ratios.dispatch_event('change')
            assert ratios.evaluate('(e)=>e.validity.customError')
            expect(page.locator('#revision')).to_have_text(before_invalid_ratio)
            ratios.fill('1, 1.5, 3')
            # Unsubmitted specialist add forms are local authoring drafts.
            # A separate validated voice edit must not discard their values.
            spectral_stage.get_by_label('Additional target degree').fill('13')
            spectral_stage.get_by_label('Additional voice label').fill('Future voice')
            spectral_stage.get_by_label('New segment start sample').fill('1800')
            spectral_stage.get_by_label('New segment label').fill('Future segment')
            second.get_by_label('Voice 2 degree').fill('12')
            second.get_by_label('Voice 2 degree').dispatch_event('change');ready()
            expect(spectral_stage.get_by_label('Additional target degree')).to_have_value('13')
            expect(spectral_stage.get_by_label('Additional voice label')).to_have_value('Future voice')
            expect(spectral_stage.get_by_label('New segment start sample')).to_have_value('1800')
            expect(spectral_stage.get_by_label('New segment label')).to_have_value('Future segment')
            # Explicit sample-time retune change-point: the first segment
            # inherits the validated voices, then a numerical degree edit
            # changes only its scheduled lattice, not the source or export route.
            segment_start=spectral_stage.get_by_label('New segment start sample')
            add_segment=spectral_stage.get_by_role('button',name='Add retune segment')
            before_segment_revision=page.locator('#revision').text_content().strip()
            before_segment_identity=server.timeline.session.current_identity()
            for bad,reason in (('', 'requires a whole number'),
                               ('0', 'must be between 1 and 691200000')):
                segment_start.fill(bad)
                add_segment.click()
                assert segment_start.evaluate('(e)=>e.validity.customError')
                assert reason in segment_start.evaluate('(e)=>e.validationMessage')
                assert server.timeline.session.current_identity()==before_segment_identity
                expect(page.locator('#revision')).to_have_text(before_segment_revision)
            segment_start.fill('1200')
            add_segment.click();ready()
            # Consumed segment drafts are not re-used after a structural add;
            # the new default is derived from the new accepted target chain.
            expect(spectral_stage.get_by_label('New segment label')).to_have_value('Target change')
            assert spectral_stage.get_by_label('New segment start sample').input_value() != '1200'
            # A second scheduled change must be strictly later than the saved
            # first start. The UI now exposes the actual predecessor-dependent
            # bound and rejects duplicate/backward starts before a proposal.
            first_segment_source=saved('rack-first-segment-source.zgtimeline.json')
            first_segment_revision=page.locator('#revision').text_content().strip()
            first_segment_identity=server.timeline.session.current_identity()
            following_start=spectral_stage.get_by_label('New segment start sample')
            assert following_start.get_attribute('min')=='1201'
            for invalid_start in ('1200','1199'):
                following_start.fill(invalid_start)
                spectral_stage.get_by_role('button',name='Add retune segment').click()
                assert following_start.evaluate('(e)=>e.validity.customError')
                assert 'must be between 1201 and 691200000' in following_start.evaluate(
                    '(e)=>e.validationMessage')
                assert server.timeline.session.current_identity()==first_segment_identity
                expect(page.locator('#revision')).to_have_text(first_segment_revision)
            assert saved('rack-duplicate-segment-rejected.zgtimeline.json')==first_segment_source
            following_start.fill('1800')  # restore an admissible, unsubmitted draft
            segment=spectral_stage.get_by_role('group',name='Retune target segment 1')
            segment.get_by_label('Segment 1 voice 1 degree').fill('9')
            segment.get_by_label('Segment 1 voice 1 degree').dispatch_event('change');ready()
            segment_label=segment.get_by_label('Segment 1 label')
            segment_label.fill('Shifted upper voice')
            segment_label.dispatch_event('change');ready()
            expect(segment.get_by_label('Segment 1 label')).to_be_focused()
            before_bad_segment=page.locator('#revision').text_content().strip()
            segment_start_existing=segment.get_by_label('Segment 1 start sample')
            segment_start_existing.fill('0')
            segment_start_existing.dispatch_event('change')
            expect(page.locator('#revision')).to_have_text(before_bad_segment)
            assert segment_start_existing.evaluate('(e)=>!e.validity.valid')
            # Explicitly commit the restored, already-saved start before
            # touching another numeric field. Otherwise focusing the next
            # control can fire an implicit blur/change for this input while a
            # different rack proposal is being submitted. That races the
            # authoritative edit queue on slower Windows Chromium.
            segment_start_existing.fill('1200')
            segment_start_existing.dispatch_event('change');ready()
            expect(page.locator('#revision')).to_have_text(before_bad_segment)
            # The authored target must act on real lowmid components, not
            # merely pass source/schedule serialization. Use declared bounded
            # DSP controls; any processor abstention below must fail closed.
            for label,value in (
                ('min confidence · ratio','0'),
                ('max displacement cents · cents','2400'),
                ('max correction slew cents per second · cents/s','20000'),
            ):
                field=spectral_stage.get_by_label(label)
                start=time.monotonic()
                field.fill(value);field.dispatch_event('change')
                # A real Windows spectral proposal can remain admission-
                # disabled beyond the ordinary 30 s UI smoke bound. The
                # original failure screenshot showed a validated, enabled
                # Render button immediately after the timeout. Wait for
                # genuine authoritative readiness, never force enablement.
                ready(timeout=120000)
                print('Spectral control accepted:',label,
                      'elapsed_seconds:',round(time.monotonic()-start,3),flush=True)
            spectral_stage.get_by_label('preserve ambiguous').uncheck();ready()
            spectral_doc=saved('rack-spectral-source-bound.zgtimeline.json')
            spectral_rack=json.loads(spectral_doc['project']['revisions'][-1]['recipe_json'])['rack']
            spectral_params=next(s['params'] for s in spectral_rack['bands'][1]['inserts']
                                 if s['id']==spectral_id)
            assert spectral_params['kind']=='SpectralRetuneRequest'
            assert spectral_params['amount']==0.7
            assert spectral_params['voices'][0]['degree']==7
            assert len(spectral_params['voices'])==2
            assert spectral_params['voices'][1]['degree']==12
            assert spectral_params['voices'][1]['label']=='Upper interval'
            assert spectral_params['voices'][1]['partial_ratios']==[1.0,1.5,3.0]
            assert len(spectral_params['segments'])==1
            assert spectral_params['segments'][0]['start_sample']==1200
            assert spectral_params['segments'][0]['label']=='Shifted upper voice'
            assert spectral_params['segments'][0]['voices'][0]['degree']==9
            assert spectral_params['segments'][0]['voices'][1]['degree']==12
            assert spectral_params['tuning_spec']==json.loads(
                spectral_doc['project']['revisions'][0]['recipe_json'])['tuning']
            def retune_activity(job):
                artifact=server.timeline.status(job)['artifact']
                rack_report=artifact['scopes']['diagnostics']['rack']
                assert rack_report['normalization']=='none',rack_report
                stage=next((row for row in rack_report['bands'][1]['stages']
                            if row['type_id']=='zg.spectral'),None)
                assert stage is not None and stage['executed'],rack_report
                processor=stage['processor']
                diag=processor['diagnostics']
                assert diag['target_segments']==2,diag
                assert diag['changed_frames']>0 and not diag['identity_path'] and (
                    diag['max_abs_correction_cents']>1e-6),(
                    'Retune fixture abstained; do not report a successful sonic edit: '
                    +repr(processor))
                return processor

            spectral_job=rendered('rack-spectral-retune')
            spectral_wav=server.timeline.scheduler.result(spectral_job).audio_bytes
            assert len(spectral_wav)==len(one_bar_dry_pcm)>44
            spectral_activity=retune_activity(spectral_job)
            assert spectral_wav!=one_bar_dry_pcm,(
                'Activated retune left actual PCM dry despite nonzero stage diagnostics')
            # A second, genuine scheduled lattice through the normal UI:
            # retain 1200 source samples as the target change-point, stage ID,
            # source ancestry and all processor controls, edit both voices.
            root=spectral_doc['project']['revisions'][0]
            old_stage=next(s for s in spectral_rack['bands'][1]['inserts']
                           if s['id']==spectral_id)
            segment=spectral_stage.get_by_role('group',name='Retune target segment 1')
            for voice_no,degree_value in ((1,'-5'),(2,'-1')):
                field=segment.get_by_label('Segment 1 voice '+str(voice_no)+' degree')
                field.fill(degree_value);field.dispatch_event('change');ready()
            alternative=saved('rack-retune-alternative-scheduled-target.zgtimeline.json')
            assert alternative['project']['revisions'][0]==root
            alternative_rack=json.loads(alternative['project']['revisions'][-1][
                'recipe_json'])['rack']
            new_stage=next(s for s in alternative_rack['bands'][1]['inserts']
                           if s['id']==spectral_id)
            assert [v['degree'] for v in new_stage['params']['segments'][0]['voices']]==[-5,-1]
            assert new_stage['params']['segments'][0]['start_sample']==1200
            assert {k:v for k,v in old_stage.items() if k!='params'}=={
                k:v for k,v in new_stage.items() if k!='params'}
            assert {k:v for k,v in old_stage['params'].items() if k!='segments'}=={
                k:v for k,v in new_stage['params'].items() if k!='segments'}
            assert [s for s in spectral_rack['bands'][1]['inserts'] if s['id']!=spectral_id]==[
                s for s in alternative_rack['bands'][1]['inserts'] if s['id']!=spectral_id]
            alternative_job=rendered('rack-retune-alternative-scheduled-target')
            alternative_pcm=server.timeline.scheduler.result(alternative_job).audio_bytes
            alternative_activity=retune_activity(alternative_job)
            assert len(alternative_pcm)==len(spectral_wav)
            before=np.frombuffer(spectral_wav,dtype='<f4')
            after=np.frombuffer(alternative_pcm,dtype='<f4')
            assert np.isfinite(before).all() and np.isfinite(after).all()
            delta=before.astype(np.float64)-after.astype(np.float64)
            difference_rms=float(np.sqrt(np.mean(delta*delta)))
            post_change_rms=float(np.sqrt(np.mean(delta[1200:]*delta[1200:])))
            assert difference_rms>1e-5 and post_change_rms>1e-5,(
                'Scheduled target did not change numerical PCM after 1200 samples: '+
                repr((difference_rms,post_change_rms,spectral_activity,alternative_activity)))
            # The spectral-only bypass is the exact original dry path.
            spectral_stage.get_by_label('Bypass insert').check();ready()
            bypass_job=rendered('rack-spectral-retune-insert-bypass')
            bypass_pcm=server.timeline.scheduler.result(bypass_job).audio_bytes
            assert bypass_pcm==one_bar_dry_pcm,(
                'Stage bypass changed original dry source samples')
            page.locator('#open').set_input_files(
                args.out/'rack-spectral-source-bound.zgtimeline.json');ready()
            reopen_id=rendered('rack-spectral-reopened')
            reopen_pcm=server.timeline.scheduler.result(reopen_id).audio_bytes
            assert reopen_pcm==spectral_wav
            (args.out/'rack-retune-numerical-evidence.json').write_text(json.dumps({
                'source_root_id':root['id'],
                'source_id':json.loads(root['recipe_json'])['source']['id'],
                'sample_rate_hz':args.sample_rate,'change_sample':1200,
                'insert_id':spectral_id,'target_degrees_a':[9,12],
                'target_degrees_b':[-5,-1],
                'stage_activity_a':spectral_activity,
                'stage_activity_b':alternative_activity,
                'target_difference_rms_full_scale':difference_rms,
                'post_change_difference_rms_full_scale':post_change_rms,
                'pcm_sha256_a':hashlib.sha256(spectral_wav).hexdigest(),
                'pcm_sha256_b':hashlib.sha256(alternative_pcm).hexdigest(),
                'pcm_sha256_dry':hashlib.sha256(one_bar_dry_pcm).hexdigest(),
                'pcm_sha256_bypass':hashlib.sha256(bypass_pcm).hexdigest(),
                'pcm_sha256_reopen':hashlib.sha256(reopen_pcm).hexdigest(),
                'normalization':'none','evidence_class':'real Chromium and numerical PCM, not listening',
            },sort_keys=True,indent=2)+'\n',encoding='utf-8')
            # Restore the pre-rack document so the following legacy
            # four-bar revision identity/save-reopen regression stays intact.
            page.locator('#open').set_input_files(args.out/'four-bar.zgtimeline.json')
            expect(page.locator('#revision')).to_have_text(TimelineDocument(data4).revision_id)
            ready()
            full_job=rendered('four-bar-full')
            first_revision=page.locator('#revision').text_content().strip()
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
            stopped_download=page.locator('#download').get_attribute('href')
            page.locator('#stop').click();expect(page.locator('#play')).to_be_enabled()
            page.wait_for_function("document.getElementById('audio').paused && document.getElementById('audio').currentTime === 0")
            assert page.locator('#download').get_attribute('href')==stopped_download
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
