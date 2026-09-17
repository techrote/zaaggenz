import hashlib,json,math,subprocess,sys,tempfile,unittest,warnings
from pathlib import Path
from unittest import mock
import numpy as np
from zaaggenz_reference import load_registry,load_locators,resolve_assets,descriptor_pcm,compare_planning,validate_annotation
import zaaggenz_reference.analysis as analysis
from zaaggenz_reference.annotation import AnnotationError
from zaaggenz_reference.__main__ import _strict_json_dumps

ROOT=Path(__file__).resolve().parents[2]
REG=ROOT/'references/private_registry_v1.json'


def assert_finite_scalars(testcase,value):
    if isinstance(value,dict):
        for item in value.values():assert_finite_scalars(testcase,item)
    elif isinstance(value,(list,tuple)):
        for item in value:assert_finite_scalars(testcase,item)
    elif isinstance(value,float):
        testcase.assertTrue(math.isfinite(value),value)


class RegistryTests(unittest.TestCase):
    def test_registered_identities_and_rights(self):
        r=load_registry(REG);self.assertEqual(len(r['assets']),6);self.assertEqual(len({a['sha256'] for a in r['assets']}),6)
        self.assertTrue(all(a['rights']['redistribution']=='not-authorized-in-repository' for a in r['assets']))
    def test_empty_locators_report_missing(self):
        r=load_registry(REG);l=load_locators(ROOT/'references/locator-example.json');rows=resolve_assets(r,l);self.assertTrue(all(x['status']=='missing' for x in rows))
    def test_hash_mismatch_not_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x';p.write_bytes(b'wrong')
            reg={'assets':[{'id':'a','sha256':'0'*64,'bytes':5}]};loc={'paths':{'a':str(p)}}
            self.assertEqual(resolve_assets(reg,loc)[0]['status'],'identity-mismatch')
    def test_cli_report_omits_local_paths_and_is_strict_json(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'r.json';cp=subprocess.run([sys.executable,'-m','zaaggenz_reference','--locators',str(ROOT/'references/locator-example.json'),'--out',str(out)],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(cp.returncode,2);text=out.read_text();self.assertNotIn('"path"',text)
            report=json.loads(text,parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
            self.assertFalse(report['source_paths_included'])
    def test_strict_json_serializer_rejects_nonfinite_numbers(self):
        for value in (float('nan'),float('inf'),float('-inf')):
            with self.assertRaises(ValueError):_strict_json_dumps({'evidence':value})


class DescriptorTests(unittest.TestCase):
    def _assert_unknown_correlation(self,x,reason):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('error',RuntimeWarning)
            d=descriptor_pcm(x,24000)
        self.assertEqual(caught,[])
        self.assertIsNone(d['stereo_correlation'])
        self.assertEqual(d['stereo_correlation_evidence'],{'status':'unknown','reason':reason})
        self.assertTrue(math.isfinite(d['side_mid_energy_ratio']))
        assert_finite_scalars(self,d)
        encoded=_strict_json_dumps(d,sort_keys=True)
        json.loads(encoded,parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
        return d
    def test_both_silent_stereo_correlation_is_explicit_unknown(self):
        self._assert_unknown_correlation(np.zeros((24000,2)),'both-channels-zero-variance')
    def test_silent_left_active_right_is_explicit_unknown(self):
        t=np.arange(24000)/24000;active=np.sin(2*np.pi*997*t)
        self._assert_unknown_correlation(np.column_stack((np.zeros(24000),active)),'left-channel-zero-variance')
    def test_active_left_silent_right_is_explicit_unknown(self):
        t=np.arange(24000)/24000;active=np.sin(2*np.pi*997*t)
        self._assert_unknown_correlation(np.column_stack((active,np.zeros(24000))),'right-channel-zero-variance')
    def test_constant_nonzero_channels_are_explicit_unknown(self):
        x=np.column_stack((np.full(24000,.25),np.full(24000,-.5)))
        self._assert_unknown_correlation(x,'both-channels-zero-variance')
    def test_identical_active_stereo_correlation_control(self):
        t=np.arange(24000)/24000;active=np.sin(2*np.pi*997*t);d=descriptor_pcm(np.column_stack((active,active)),24000)
        self.assertAlmostEqual(d['stereo_correlation'],1.0,places=12);self.assertEqual(d['stereo_correlation_evidence']['status'],'observed')
    def test_unclamped_stereo_antiphase_control(self):
        sr=24000;t=np.arange(sr)/sr;l=1.5*np.sin(2*np.pi*997*t);x=np.column_stack((l,-l));d=descriptor_pcm(x,sr)
        self.assertGreater(d['sample_peak'],1.49);self.assertGreater(d['samples_abs_ge_1_fraction'],0);self.assertLess(d['stereo_correlation'],-.999999);self.assertEqual(d['stereo_correlation_evidence']['status'],'observed')
    def test_self_planning_comparison(self):
        e=load_registry(REG)['assets'][0]['planning'];o={'decoded_duration_s':e['decoded_24k_duration_s'],'sample_peak':e['sample_peak_24k'],'loudness':{'integrated_lufs':e['integrated_lufs'],'true_peak_dbtp':e['true_peak_dbtp']},'energetic_medians':e['energetic_medians']}
        self.assertTrue(compare_planning(o,e)['pass'])
    def test_requested_planning_correlation_unknown_fails_honestly(self):
        e=load_registry(REG)['assets'][0]['planning'].copy();e['stereo_correlation']=.5
        o={'decoded_duration_s':e['decoded_24k_duration_s'],'sample_peak':e['sample_peak_24k'],'loudness':{'integrated_lufs':e['integrated_lufs'],'true_peak_dbtp':e['true_peak_dbtp']},'energetic_medians':e['energetic_medians'],'stereo_correlation':None,'stereo_correlation_evidence':{'status':'unknown','reason':'left-channel-zero-variance'}}
        result=compare_planning(o,e);check=result['checks']['stereo_correlation']
        self.assertFalse(result['pass']);self.assertFalse(check['pass']);self.assertEqual(check['status'],'unavailable');self.assertEqual(check['evidence']['reason'],'left-channel-zero-variance');self.assertIsNone(check['delta'])
    def test_nonfinite_rejected(self):
        x=np.zeros((24000,2));x[0,0]=np.nan
        with self.assertRaises(ValueError):descriptor_pcm(x,24000)


class StreamingReferenceTests(unittest.TestCase):
    def _active_pcm(self,seconds=2.25,sr=24000):
        n=int(seconds*sr);t=np.arange(n)/sr
        left=1.25*np.sin(2*np.pi*997*t)+.1*np.sin(2*np.pi*83*t)
        right=.8*np.sin(2*np.pi*997*t+.3)-.05*np.sin(2*np.pi*1400*t)
        return np.column_stack((left,right)).astype('<f4')
    def _stream_descriptor(self,pcm,sr=24000):
        with tempfile.TemporaryFile(mode='w+b') as spool:
            spool.write(pcm.astype('<f4',copy=False).tobytes())
            return analysis._descriptor_spooled_stereo(spool,sr,len(pcm))
    def _assert_equivalent(self,streamed,direct):
        self.assertEqual(streamed['method'],direct['method']);self.assertEqual(streamed['analysis_sr'],direct['analysis_sr'])
        self.assertEqual(streamed['complete_windows'],direct['complete_windows']);self.assertEqual(streamed['energetic_window_count'],direct['energetic_window_count'])
        self.assertEqual(streamed['sample_peak'],direct['sample_peak']);self.assertEqual(streamed['samples_abs_ge_1_fraction'],direct['samples_abs_ge_1_fraction'])
        self.assertEqual(streamed['stereo_correlation_evidence'],direct['stereo_correlation_evidence'])
        if direct['stereo_correlation'] is None:self.assertIsNone(streamed['stereo_correlation'])
        else:self.assertAlmostEqual(streamed['stereo_correlation'],direct['stereo_correlation'],places=12)
        self.assertAlmostEqual(streamed['side_mid_energy_ratio'],direct['side_mid_energy_ratio'],places=12)
        self.assertEqual(streamed['timeline'],direct['timeline']);self.assertEqual(streamed['energetic_medians'],direct['energetic_medians'])
    def test_streamed_descriptor_matches_v1_with_final_partial_second(self):
        pcm=self._active_pcm();pcm[-1]=[1.75,-1.5]
        streamed=self._stream_descriptor(pcm);direct=descriptor_pcm(pcm,24000)
        self._assert_equivalent(streamed,direct)
        self.assertEqual(streamed['complete_windows'],2);self.assertEqual(streamed['sample_peak'],1.75)
        self.assertEqual([row['start_s'] for row in streamed['timeline']],[0.0,1.0])
    def test_streamed_silence_preserves_unknown_correlation(self):
        pcm=np.zeros((24000*3+17,2),dtype='<f4');streamed=self._stream_descriptor(pcm);direct=descriptor_pcm(pcm,24000)
        self._assert_equivalent(streamed,direct);self.assertEqual(streamed['stereo_correlation_evidence']['reason'],'both-channels-zero-variance')
        self.assertEqual(streamed['complete_windows'],3)
    def test_exact_one_second_minimum_and_just_below(self):
        exact=np.zeros((24000,2),dtype='<f4');self.assertEqual(self._stream_descriptor(exact)['complete_windows'],1)
        below=np.zeros((23999,2),dtype='<f4')
        with self.assertRaisesRegex(ValueError,'at least one second'):self._stream_descriptor(below)
    def test_near_limit_iterator_never_reads_more_than_one_second(self):
        class VirtualSpool:
            def __init__(self):self.position=0;self.max_read=0
            def seek(self,position):self.position=position
            def read(self,count):self.max_read=max(self.max_read,count);self.position+=count;return b'\0'*count
        sr=24000;bound=analysis.reference_analysis_resource_bound(sr);spool=VirtualSpool();frames=0;chunks=0
        for pcm in analysis._iter_spooled_stereo_chunks(spool,sr,bound['max_decoded_frames']):
            frames+=len(pcm);chunks+=1
        self.assertEqual(frames,43_200_000);self.assertEqual(chunks,1800);self.assertEqual(spool.max_read,192_000)
        self.assertEqual(bound['max_decoded_spool_bytes'],345_600_000);self.assertEqual(bound['max_chunk_f64_bytes'],384_000);self.assertEqual(bound['max_timeline_rows'],1800)
    def test_decoded_size_bound_exact_limit_plus_one_and_alignment(self):
        bound=analysis.reference_analysis_resource_bound(24000)
        self.assertEqual(analysis._decoded_frame_count(bound['max_decoded_spool_bytes'],24000),bound['max_decoded_frames'])
        with self.assertRaisesRegex(ValueError,'30-minute'):analysis._decoded_frame_count(bound['max_decoded_spool_bytes']+8,24000)
        with self.assertRaisesRegex(ValueError,'byte count mismatch'):analysis._decoded_frame_count(9,24000)
    def test_spool_truncation_fails_closed(self):
        class ShortSpool:
            def seek(self,position):pass
            def read(self,count):return b'\0'*max(0,count-8)
        with self.assertRaisesRegex(ValueError,'truncated'):
            next(analysis._iter_spooled_stereo_chunks(ShortSpool(),24000,24000))
    def test_decoder_writes_to_bounded_tempfile_and_keeps_f32_stereo_policy(self):
        pcm=self._active_pcm(1.25);seen={}
        def fake_run(args,stdout=None,stderr=None,timeout=None,**kwargs):
            seen['args']=args;seen['stdout']=stdout;seen['stderr']=stderr;seen['timeout']=timeout
            stdout.write(pcm.tobytes());return subprocess.CompletedProcess(args,0)
        with mock.patch.object(analysis.subprocess,'run',side_effect=fake_run):
            streamed,frames=analysis._decode_spooled(Path('private-reference.flac'),24000)
        self.assertEqual(frames,len(pcm));self._assert_equivalent(streamed,descriptor_pcm(pcm,24000))
        self.assertIsNot(seen['stdout'],subprocess.PIPE);self.assertTrue(hasattr(seen['stdout'],'fileno'))
        command=seen['args'];self.assertEqual(command[command.index('-ar')+1],'24000');self.assertEqual(command[command.index('-ac')+1],'2')
        self.assertEqual(command[command.index('-c:a')+1],'pcm_f32le');self.assertEqual(command[command.index('-f')+1],'f32le');self.assertEqual(command[-1],'pipe:1')
    def test_decoder_failure_never_reaches_descriptor(self):
        def fake_run(args,stdout=None,stderr=None,timeout=None,**kwargs):
            stderr.write(b'bad private input');return subprocess.CompletedProcess(args,1)
        with mock.patch.object(analysis.subprocess,'run',side_effect=fake_run),mock.patch.object(analysis,'_descriptor_spooled_stereo') as descriptor:
            with self.assertRaisesRegex(RuntimeError,'ffmpeg decode failed: bad private input'):analysis._decode_spooled(Path('bad.flac'),24000)
            descriptor.assert_not_called()
    def test_misaligned_decoder_output_never_reaches_descriptor(self):
        def fake_run(args,stdout=None,stderr=None,timeout=None,**kwargs):
            stdout.write(b'123456789');return subprocess.CompletedProcess(args,0)
        with mock.patch.object(analysis.subprocess,'run',side_effect=fake_run),mock.patch.object(analysis,'_descriptor_spooled_stereo') as descriptor:
            with self.assertRaisesRegex(ValueError,'byte count mismatch'):analysis._decode_spooled(Path('bad.flac'),24000)
            descriptor.assert_not_called()
    def test_metadata_duration_bound_precedes_decode_and_boundary_is_inclusive(self):
        stream={'sample_rate':'44100','channels':1,'codec_name':'flac'};descriptor={'method':analysis.METHOD,'sample_peak':0.0}
        loudness={'integrated_lufs':-20.0,'loudness_range_lu':2.0,'true_peak_dbtp':-1.0}
        for duration in (1799.999,1800.0):
            with self.subTest(duration=duration),mock.patch.object(analysis,'_ffprobe',return_value=({'format':{'duration':str(duration)}},stream)),mock.patch.object(analysis,'_decode_spooled',return_value=(descriptor.copy(),24000)) as decode,mock.patch.object(analysis,'_loudness',return_value=loudness),mock.patch.object(analysis.subprocess,'check_output',return_value='ffmpeg version test\n'):
                result=analysis.analyse_file(Path('private.flac'));decode.assert_called_once_with(Path('private.flac'),24000)
                self.assertEqual(result['native_sample_rate'],44100);self.assertEqual(result['native_channels'],1);self.assertEqual(result['codec'],'flac');self.assertEqual(result['loudness'],loudness)
        with mock.patch.object(analysis,'_ffprobe',return_value=({'format':{'duration':'1800.000001'}},stream)),mock.patch.object(analysis,'_decode_spooled') as decode:
            with self.assertRaisesRegex(ValueError,'30-minute'):analysis.analyse_file(Path('private.flac'))
            decode.assert_not_called()


class AnnotationTests(unittest.TestCase):
    def test_automatic_candidates_validate_as_uncertain(self):
        d=json.loads((ROOT/'references/paired_suggestions_v1.json').read_text());validate_annotation(d,{'activation','zaagtivation'});self.assertTrue(all(r['relation']=='uncertain' and r['confidence']==0 for r in d['relations']))
    def test_ambiguous_meter_and_unrelated_sections_supported(self):
        seg=lambda i,a:{'id':i,'asset_id':a,'start_sample':0,'end_sample':48000,'section_function':'unknown','label':'x','confidence':.5,'source':'manual','meter_candidates':[{'numerator':4,'denominator':4,'pulse_divisor':1,'confidence':.5},{'numerator':4,'denominator':4,'pulse_divisor':2,'confidence':.4}],'correspondence_group':None}
        d={'version':'1.0.0','segments':[seg('a','activation'),seg('b','zaagtivation')],'relations':[{'id':'r','left_segment':'a','right_segment':'b','relation':'unrelated','confidence':.9,'source':'manual'}]};validate_annotation(d,{'activation','zaagtivation'})
    def test_bad_meter_confidence(self):
        d=json.loads((ROOT/'references/paired_suggestions_v1.json').read_text());d['segments'][0]['meter_candidates']=[{'numerator':4,'denominator':4,'pulse_divisor':1,'confidence':.7},{'numerator':3,'denominator':4,'pulse_divisor':1,'confidence':.7}]
        with self.assertRaises(AnnotationError):validate_annotation(d,{'activation','zaagtivation'})


class SafetyTests(unittest.TestCase):
    def test_repository_safety_scanner(self):
        cp=subprocess.run([sys.executable,'tools/check_reference_safety.py'],cwd=ROOT,capture_output=True,text=True);self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
    def test_holdout_inventory(self):
        d=json.loads((ROOT/'references/holdout_families_v1.json').read_text());self.assertGreaterEqual(sum(x['role']=='holdout' for x in d['families']),2)


if __name__=='__main__':unittest.main(verbosity=2)
