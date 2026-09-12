"""Synthetic design sensitivity. NO real participants, outcomes or effect claims.
D_li = effect + listener slope + item slope + residual, in contrast units.
"""
from __future__ import annotations
import math
import numpy as np
from scipy import stats
from common import METHOD, SEED, table, dump


def run_statistics(out,replicates=2000):
    rng=np.random.default_rng(SEED+29); rows=[]
    # 0.35/0.45/1.0 are explicit planning assumptions, not literature estimates.
    su,sv,se=.35,.45,1.
    for n in (12,24,48,96):
        for items in (4,12,24,48):
            means=[]; naive=[]; crossed=[]; tcritical=[]
            for start in range(0,replicates,100):
                k=min(100,replicates-start)
                d=(rng.normal(0,su,(k,n,1))+rng.normal(0,sv,(k,1,items))+
                   rng.normal(0,se,(k,n,items)))
                g=d.mean(axis=(1,2)); r=d.mean(axis=2); c=d.mean(axis=1)
                e=d-r[:,:,None]-c[:,None,:]+g[:,None,None]
                mse=np.sum(e*e,axis=(1,2))/((n-1)*(items-1))
                msr=items*np.var(r,axis=1,ddof=1); msc=n*np.var(c,axis=1,ddof=1)
                # Two-way method-of-moments approximation, not a mixed-model fit.
                v1=np.maximum((msr-mse)/items,0)/n
                v2=np.maximum((msc-mse)/n,0)/items
                means.extend(g); naive.extend(np.std(r,axis=1,ddof=1)/np.sqrt(n))
                v3=mse/(n*items); vm=v1+v2+v3
                crossed.extend(np.sqrt(vm))
                # Satterthwaite-style approximation retained as an explicitly
                # approximate refinement; comparison to oracle stays in outputs.
                df=vm**2/np.maximum(v1**2/(n-1)+v2**2/(items-1)+v3**2/((n-1)*(items-1)),1e-30)
                tcritical.extend(stats.t.ppf(.975,np.maximum(df,1)))
            mean=np.array(means); naive=np.array(naive); cross=np.array(crossed)
            oracle=math.sqrt(su**2/n+sv**2/items+se**2/(n*items))
            for effect in (0.,.2,.4):
                for model,sem,crit in [('listener_only',naive,1.95996398454),('crossed_mom_normal',cross,1.95996398454),('crossed_mom_t_approx',cross,np.array(tcritical)),('known_variance_oracle',oracle,1.95996398454)]:
                    rejection=float(np.mean(abs(mean+effect)>crit*sem))
                    coverage=float(np.mean(abs(mean)<=crit*sem))
                    rows.append(dict(listeners=n,items=items,effect=effect,method=model,
                        replicates=replicates,rejection_probability=rejection,
                        rejection_mcse=math.sqrt(rejection*(1-rejection)/replicates),
                        coverage_95=coverage,mean_se=float(np.mean(sem))))
    table(out/'design_sensitivity.csv',rows)
    dump(out/'design_assumptions.json',{'method':METHOD,'synthetic_only':True,
       'model':'D_li = effect + listener_i + item_j + residual_ij',
       'listener_sd':su,'item_sd':sv,'contrast_residual_sd':se,
       'replicates_per_design':replicates,'seeds':SEED+29,
       'null_total_designs':16,'effect_values':[0,.2,.4],
       'warning':'Normal intervals and moment variance estimates are exploratory approximations. Small item samples can under-cover. No sample size prescribed; pilot, ordinal outcomes, order, familiarity and missingness still needed.'})
    return rows


def run_job_model(out):
    # Deterministic single-worker CPU simulation. Does not measure web/audio latency.
    jobs=[('analysis',0,2500,3),('preview-a',100,40,0),('preview-b',500,40,0),('preview-c',1000,40,0)]
    result={}
    for quantum in (2500,50):
        remaining={j[0]:j[2] for j in jobs}; t=0; ended={}; log=[]
        while remaining:
            available=[j for j in jobs if j[0] in remaining and j[1]<=t]
            if not available: t=min(j[1] for j in jobs if j[0] in remaining);continue
            j=min(available,key=lambda j:(j[3],j[1]))
            used=min(quantum,remaining[j[0]])
            log.append([j[0],t,t+used]); t+=used; remaining[j[0]]-=used
            if remaining[j[0]]==0: ended[j[0]]=t;del remaining[j[0]]
        result[str(quantum)]={'quantum_ms':quantum,'preview_response_ms':{j[0]:ended[j[0]]-j[1] for j in jobs if j[3]==0},'makespan_ms':t,'dispatches':len(log)}
    # Exhaustive completions: revision-aware publication should always choose newest.
    from itertools import permutations
    wrong=0; keyed_wrong=0
    for order in permutations(range(4)):
        naive=order[-1]; keyed=None
        for rev in order:
            if rev==3: keyed=rev
        wrong+=naive!=3;keyed_wrong+=keyed!=3
    dump(out/'job_policy_model.json',{'method':METHOD,'schedules':result,
        'out_of_order_cases':24,'naive_stale_publications':wrong,'revision_checked_stale_publications':keyed_wrong,
        'limitations':'Pure deterministic model; cooperative 50-ms quantum is an assumption, not achieved API latency. No production thread/cancel implementation.'})
    return result


def main(out):
    return {'rows':len(run_statistics(out)),'job_policy':run_job_model(out)}
