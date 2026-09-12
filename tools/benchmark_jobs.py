"""Measured local scheduler/preview benchmark. Values describe only the executing host."""
from __future__ import annotations
import argparse,hashlib,json,platform,sys,threading,time
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'app')]
from zaaggenz_jobs import *

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--baseline',action='store_true');a=p.parse_args()
    limits=SchedulerLimits();s=JobScheduler(limits);revision='a'*64;recipe='b'*64;key='c'*64
    def make_artifact(payload):
        asset=dict(kind='AudioAssetRef',version='1.0.0',content_sha256=hashlib.sha256(payload).hexdigest(),identity_domain='pcm-f32le-interleaved-v1',sample_rate_hz=48000,channels=1,channel_layout='mono',frame_count=len(payload)//4,level_domain='source',sample_policy='unclamped_float')
        return RenderArtifact(revision,recipe,'preview',key,payload,asset,{'benchmark':True})
    if a.baseline:
        import numpy as np
        from uptempo_harmony.synth import PRESETS,synthesize_one
        params=replace(PRESETS['locked_bloom'],sr=48000,beats=1)
        def preview(ctx):
            ctx.check_cancelled();audio,_=synthesize_one(params,duration_s=.35);ctx.check_cancelled();return make_artifact(np.asarray(audio,dtype='<f4').tobytes())
    else:preview=lambda ctx:make_artifact(b'\0'*48000)
    c=RenderCoordinator(s)
    t0=time.perf_counter();ticket=c.request_preview('bench',revision,recipe,key,preview,estimated_memory_bytes=32*1024*1024)
    while True:
        r=c.poll(ticket)
        if r['state']=='completed':break
        time.sleep(.001)
    cold=(time.perf_counter()-t0)*1000
    t0=time.perf_counter();warm=c.request_preview('bench',revision,recipe,key,preview,estimated_memory_bytes=32*1024*1024);r=c.poll(warm);warm_ms=(time.perf_counter()-t0)*1000
    release=threading.Event();started=[threading.Event(),threading.Event()]
    def bg(i):
        def run(ctx):started[i].set();release.wait(2);ctx.check_cancelled();return i
        return run
    jobs=[s.submit(JobClass.ANALYSIS,revision,bg(i),estimated_memory_bytes=128*1024*1024) for i in range(2)]
    for e in started:e.wait(2)
    t0=time.perf_counter();starve=s.submit(JobClass.PREVIEW,revision,preview,estimated_memory_bytes=32*1024*1024)
    s.wait(starve,5);preview_while_background_ms=(time.perf_counter()-t0)*1000;release.set()
    cancel_started=threading.Event()
    def cancellable(ctx):
        cancel_started.set()
        while True:ctx.check_cancelled();time.sleep(.001)
    j=s.submit(JobClass.RENDER,revision,cancellable,estimated_memory_bytes=1);cancel_started.wait(2);t0=time.perf_counter();s.cancel(j);s.wait(j,2);cancel_ms=(time.perf_counter()-t0)*1000
    c.close()
    report=dict(scope='measured on this host only',platform=platform.platform(),python=sys.version,
                baseline_preview=a.baseline,cold_preview_ms=cold,warm_cache_ms=warm_ms,
                preview_while_two_background_jobs_ms=preview_while_background_ms,cooperative_cancel_ms=cancel_ms,
                limits=limits.__dict__)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
