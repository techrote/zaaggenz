from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import unittest

import numpy as np

from zaaggenz_components import analyse_components
from zaaggenz_jobs import JobError,JobScheduler,SchedulerLimits
from zaaggenz_jobs.memory import authoritative_memory_reservation
from zaaggenz_spectral import (ChordnessRequest,CombTemplate,LatticeVoice,NonlinearStageSpec,
                               PlacementRequest,SpectralRetuneRequest,
                               estimate_chordness_memory_bytes,estimate_placement_memory_bytes,
                               estimate_retune_memory_bytes,submit_chordness_job,
                               submit_placement_family_job,submit_placement_job,submit_retune_job)
from zaaggenz_tuning import (AdaptiveTuningRequest,AdaptiveVoice,AdaptiveWeights,
                             fixture_pack,harmonic_spectrum,submit_adaptive_tuning_job,
                             submit_dissonance_map_job,tuning_to_spec)

SR=12000
REVISION='d'*64
MIB=1024*1024


class RecordingScheduler:
    def __init__(self):self.calls=[]
    def submit(self,job_class,revision_id,executor,*,estimated_memory_bytes,**kwargs):
        self.calls.append((job_class,revision_id,executor,estimated_memory_bytes,kwargs))
        return 'captured'


def tone(frames):
    t=np.arange(frames,dtype=np.float64)/SR
    return (.3*np.cos(2*np.pi*445.*t+.17)).astype(np.float32)


def spectral_request():
    return SpectralRetuneRequest(tuning_spec=tuning_to_spec(fixture_pack()['12tet-a440']),
                                 voices=(LatticeVoice(0,(1.,),'a440'),),amount=0.,
                                 min_hz=100.,max_hz=1200.,max_displacement_cents=180.,
                                 max_correction_slew_cents_per_second=1200.)


def adaptive_request():
    root=AdaptiveVoice('root',0.,harmonic_spectrum('root-spectrum',220.,partials=4),'root',False)
    upper=AdaptiveVoice('upper',705.,harmonic_spectrum('upper-spectrum',330.,partials=4),'voice',False)
    return AdaptiveTuningRequest((root,upper),(0.,498.,702.,1200.),'root',desired_tension=0.,root_lock=True,
        max_total_drift_cents=30.,max_step_cents=12.,search_step_cents=1.,min_separation_cents=20.,
        weights=AdaptiveWeights(tension=12.,voice_leading=.02,drift=.02,candidate_proximity=.1))


class WrapperMemoryAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.small=analyse_components(tone(1200),SR)
        cls.large=analyse_components(tone(3600),SR)
        cls.spectral=spectral_request()
        cls.chordness=ChordnessRequest((CombTemplate('a',(440.,)),),mode='off')

    def test_shared_policy_rejects_every_under_declaration_shape(self):
        minimum=4096
        self.assertEqual(authoritative_memory_reservation(minimum),minimum)
        self.assertEqual(authoritative_memory_reservation(minimum,minimum),minimum)
        self.assertEqual(authoritative_memory_reservation(minimum,minimum+1),minimum+1)
        for value in (minimum-1,0,-1,True,False,1.5,float('nan'),float('inf'),-float('inf'),'4096'):
            with self.subTest(value=value),self.assertRaises(JobError):
                authoritative_memory_reservation(minimum,value)

    def test_retune_and_chordness_authoritative_floors_and_extra_reservation(self):
        cases=((submit_retune_job,estimate_retune_memory_bytes(self.small),self.spectral),
               (submit_chordness_job,estimate_chordness_memory_bytes(self.small),self.chordness))
        for submit,minimum,request in cases:
            with self.subTest(submit=submit.__name__):
                scheduler=RecordingScheduler()
                submit(scheduler,REVISION,self.small,request)
                self.assertEqual(scheduler.calls[-1][3],minimum)
                submit(scheduler,REVISION,self.small,request,estimated_memory_bytes=minimum)
                self.assertEqual(scheduler.calls[-1][3],minimum)
                submit(scheduler,REVISION,self.small,request,estimated_memory_bytes=minimum+MIB)
                self.assertEqual(scheduler.calls[-1][3],minimum+MIB)
                before=len(scheduler.calls)
                with self.assertRaises(JobError):
                    submit(scheduler,REVISION,self.small,request,estimated_memory_bytes=minimum-1)
                self.assertEqual(len(scheduler.calls),before)
                for invalid in (0,-1,True,1.25,float('nan'),float('inf')):
                    with self.assertRaises(JobError):
                        submit(scheduler,REVISION,self.small,request,estimated_memory_bytes=invalid)
                self.assertEqual(len(scheduler.calls),before)

    def test_spectral_estimates_are_monotonic_and_exceed_resident_analysis_bytes(self):
        def resident(analysis):
            return sum(np.asarray(x).nbytes for x in (analysis.source,analysis.sinusoidal,
                analysis.transient,analysis.residual,analysis.transient_mask))
        self.assertGreater(estimate_retune_memory_bytes(self.small),resident(self.small))
        self.assertGreater(estimate_chordness_memory_bytes(self.small),resident(self.small))
        self.assertGreater(estimate_retune_memory_bytes(self.large),estimate_retune_memory_bytes(self.small))
        self.assertGreater(estimate_chordness_memory_bytes(self.large),estimate_chordness_memory_bytes(self.small))

    def test_placement_single_and_family_cannot_understate(self):
        source=np.zeros((512,2),dtype=np.float32);a=NonlinearStageSpec();b=NonlinearStageSpec('hard_clip')
        request=PlacementRequest(self.spectral,'inter',a,b)
        for submit,minimum,args in (
            (submit_placement_job,estimate_placement_memory_bytes(source,1),(source,SR,request)),
            (submit_placement_family_job,estimate_placement_memory_bytes(source,3),(source,SR,self.spectral,a,b))):
            scheduler=RecordingScheduler();submit(scheduler,REVISION,*args)
            self.assertEqual(scheduler.calls[-1][3],minimum)
            submit(scheduler,REVISION,*args,estimated_memory_bytes=minimum+1)
            self.assertEqual(scheduler.calls[-1][3],minimum+1)
            before=len(scheduler.calls)
            with self.assertRaises(JobError):submit(scheduler,REVISION,*args,estimated_memory_bytes=minimum-1)
            self.assertEqual(len(scheduler.calls),before)

    def test_tuning_wrappers_retain_eight_mib_floor(self):
        request=adaptive_request();a=harmonic_spectrum('a',220.,partials=4);b=harmonic_spectrum('b',330.,partials=4)
        for submit,args in ((submit_adaptive_tuning_job,(request,)),(submit_dissonance_map_job,(a,b))):
            scheduler=RecordingScheduler();submit(scheduler,REVISION,*args)
            self.assertEqual(scheduler.calls[-1][3],8*MIB)
            submit(scheduler,REVISION,*args,estimated_memory_bytes=9*MIB)
            self.assertEqual(scheduler.calls[-1][3],9*MIB)
            before=len(scheduler.calls)
            with self.assertRaises(JobError):submit(scheduler,REVISION,*args,estimated_memory_bytes=8*MIB-1)
            self.assertEqual(len(scheduler.calls),before)

    def test_forged_spectral_estimates_cannot_bypass_scheduler_admission(self):
        retune=estimate_retune_memory_bytes(self.small);chord=estimate_chordness_memory_bytes(self.small)
        budget=min(retune,chord)-1
        limits=SchedulerLimits(interactive_workers=1,background_workers=1,max_queued_jobs=8,
            max_background_queued_jobs=8,max_history_jobs=32,max_memory_bytes=budget,
            interactive_memory_reserve_bytes=max(1,budget//4),max_job_memory_bytes=budget,
            max_preview_memory_bytes=max(1,budget//8),preview_cache_bytes=4096,
            preview_cache_entries=2,numeric_threads=1)
        scheduler=JobScheduler(limits,apply_numeric_limit=False)
        try:
            with self.assertRaises(JobError):submit_retune_job(scheduler,REVISION,self.small,self.spectral)
            with self.assertRaises(JobError):submit_chordness_job(scheduler,REVISION,self.small,self.chordness)
            for _ in range(3):
                with self.assertRaises(JobError):submit_retune_job(scheduler,REVISION,self.small,self.spectral,estimated_memory_bytes=1)
                with self.assertRaises(JobError):submit_chordness_job(scheduler,REVISION,self.small,self.chordness,estimated_memory_bytes=1)
            self.assertEqual(scheduler._records,{})
        finally:scheduler.shutdown(cancel=True)

    def test_concurrent_retune_and_chordness_underdeclarations_never_reach_shared_scheduler(self):
        retune=estimate_retune_memory_bytes(self.small);chord=estimate_chordness_memory_bytes(self.small)
        budget=min(retune,chord)-1
        limits=SchedulerLimits(interactive_workers=1,background_workers=1,max_queued_jobs=16,
            max_background_queued_jobs=16,max_history_jobs=32,max_memory_bytes=budget,
            interactive_memory_reserve_bytes=max(1,budget//4),max_job_memory_bytes=budget,
            max_preview_memory_bytes=max(1,budget//8),preview_cache_bytes=4096,
            preview_cache_entries=2,numeric_threads=1)
        scheduler=JobScheduler(limits,apply_numeric_limit=False)
        def forged(kind):
            try:
                if kind=='retune':
                    submit_retune_job(scheduler,REVISION,self.small,self.spectral,estimated_memory_bytes=1)
                else:
                    submit_chordness_job(scheduler,REVISION,self.small,self.chordness,estimated_memory_bytes=1)
            except JobError:
                return 'rejected'
            return 'admitted'
        try:
            kinds=('retune','chordness')*8
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(forged,kinds))
            self.assertEqual(results,['rejected']*len(kinds))
            self.assertEqual(scheduler._records,{})
        finally:scheduler.shutdown(cancel=True)

    def test_background_floor_meets_and_one_byte_over_lane_uses_scheduler_100_rule(self):
        limits=SchedulerLimits(interactive_workers=1,background_workers=1,max_queued_jobs=8,
            max_background_queued_jobs=8,max_history_jobs=32,max_memory_bytes=10*MIB,
            interactive_memory_reserve_bytes=2*MIB,max_job_memory_bytes=9*MIB,
            max_preview_memory_bytes=2*MIB,preview_cache_bytes=4096,
            preview_cache_entries=2,numeric_threads=1)
        scheduler=JobScheduler(limits,apply_numeric_limit=False)
        try:
            job=submit_adaptive_tuning_job(scheduler,REVISION,adaptive_request())
            self.assertEqual(scheduler.snapshot(job).estimated_memory_bytes,8*MIB)
            self.assertEqual(scheduler.wait(job,5).state,'completed')
            before=len(scheduler._records)
            with self.assertRaisesRegex(JobError,'permanent background lane capacity'):
                submit_adaptive_tuning_job(scheduler,REVISION,adaptive_request(),estimated_memory_bytes=8*MIB+1)
            self.assertEqual(len(scheduler._records),before)
        finally:scheduler.shutdown(cancel=True)


if __name__=='__main__':unittest.main(verbosity=2)
