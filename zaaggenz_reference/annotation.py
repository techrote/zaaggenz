from __future__ import annotations

class AnnotationError(ValueError):pass

def _r(c,m):
    if not c:raise AnnotationError(m)

def validate_annotation(d,asset_ids):
    _r(type(d)is dict and set(d)=={'version','segments','relations'},'invalid annotation root');_r(d['version']=='1.0.0','unsupported annotation version')
    segids=set()
    for s in d['segments']:
        req={'id','asset_id','start_sample','end_sample','section_function','label','confidence','source','meter_candidates','correspondence_group'}
        _r(type(s)is dict and set(s)==req,'invalid segment');_r(s['id'] not in segids,'duplicate segment');segids.add(s['id'])
        _r(s['asset_id'] in asset_ids,'unknown annotated asset');_r(type(s['start_sample'])is int and type(s['end_sample'])is int and 0<=s['start_sample']<s['end_sample'],'invalid segment span')
        _r(s['section_function'] in ('unknown','establish','build','drop','variation','break','return','outro'),'invalid section function')
        _r(type(s['confidence'])in (int,float) and 0<=s['confidence']<=1,'invalid confidence');_r(s['source'] in ('manual','automatic-suggestion'),'invalid annotation source')
        _r(s['correspondence_group'] is None or type(s['correspondence_group'])is str,'invalid correspondence group')
        _r(type(s['meter_candidates'])is list and len(s['meter_candidates'])<=8,'invalid metre candidates')
        total=0
        for m in s['meter_candidates']:
            _r(type(m)is dict and set(m)=={'numerator','denominator','pulse_divisor','confidence'},'invalid metre candidate');_r(m['numerator']>0 and m['denominator'] in (1,2,4,8,16,32) and m['pulse_divisor'] in (1,2,4,8),'invalid metre');_r(0<=m['confidence']<=1,'invalid metre confidence');total+=m['confidence']
        _r(total<=1.000001,'metre confidence mass > 1')
    relids=set()
    for x in d['relations']:
        _r(type(x)is dict and set(x)=={'id','left_segment','right_segment','relation','confidence','source'},'invalid relation');_r(x['id'] not in relids,'duplicate relation');relids.add(x['id'])
        _r(x['left_segment'] in segids and x['right_segment'] in segids and x['left_segment']!=x['right_segment'],'relation references invalid segments')
        _r(x['relation'] in ('corresponding','unrelated','uncertain'),'invalid relation');_r(0<=x['confidence']<=1,'invalid relation confidence');_r(x['source'] in ('manual','automatic-suggestion'),'invalid relation source')
    return d
