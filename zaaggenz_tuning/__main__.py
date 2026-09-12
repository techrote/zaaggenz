import argparse,json
from pathlib import Path
from .scala import load_scala_tuning
from .core import tuning_to_spec

def main():
    p=argparse.ArgumentParser(description='Inspect Scala tuning files without rendering audio')
    p.add_argument('scl',type=Path);p.add_argument('--kbm',type=Path);p.add_argument('--id',default='scala-import');p.add_argument('--json',action='store_true');a=p.parse_args()
    tuning=load_scala_tuning(a.scl.read_bytes(),a.kbm.read_bytes() if a.kbm else None,tuning_id=a.id)
    result={'spec':tuning_to_spec(tuning),'description':tuning.description,'provenance':tuning.provenance,
            'reference_key_frequency_hz':tuning.keyboard_frequency(tuning.keyboard.reference_key) if tuning.keyboard else None}
    print(json.dumps(result,indent=2,ensure_ascii=False) if a.json else f'{tuning.id}: {tuning.degrees_per_period} degrees, period {tuning.period_ratio:.9g}, reference {tuning.reference_hz:.9g} Hz')
if __name__=='__main__':main()
