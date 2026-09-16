from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_components.model import ComponentTrackerSpec
from zaaggenz_components.tracker import _detector_status,_track_bundle

class ReanchoredContractTests(unittest.TestCase):
    def test_reanchored_history_is_preserve_only_under_frozen_partial_contract(self):
        source=np.zeros((4096,1),dtype=np.float32);zero=np.zeros_like(source);mask=np.zeros(len(source),dtype=np.float32);spec=ComponentTrackerSpec()
        rows=[]
        for i,anchor in enumerate((1024,1280,1536)):
            rows.append(dict(frame=i,anchor=anchor,start=anchor-256,end=anchor+256,frequency_hz=440.,amplitudes=(.5,),phases=(0.,),confidence=1.,ambiguous=False,condition=1.))
        tracks=[dict(serial=1,rows=rows,missed=0,ambiguous=False,had_gap=True,last_frame=2)]
        stft_spec=type('S',(),{'window_samples':512,'hop_samples':128,'fft_samples':2048})()
        result=type('R',(),{'spec':stft_spec})();detector=_detector_status('test-fixture-v1',True)
        bundle,transform_frames,ambiguous_tracks=_track_bundle(source,12000,tracks,spec,result,mask,zero,zero,detector)
        d=bundle.to_dict();self.assertEqual(d['tracks'][0]['continuity'],'reanchored');self.assertEqual(transform_frames,0);self.assertEqual(ambiguous_tracks,0)
        self.assertTrue(all(frame['action']=='preserve' for frame in d['tracks'][0]['frames']))

if __name__=='__main__':unittest.main(verbosity=2)
