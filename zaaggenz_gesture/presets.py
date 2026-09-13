"""Original synthetic directionality fixture; no cultural or preference claim."""
from .model import DirectionalGesture,VERSION

def _trajectory(axis,unit,values,directions,interpolation='linear'):
    beats=('0/1','1/1','2/1','3/1','4/1')
    return {'axis':axis,'unit':unit,'interpolation':interpolation,
            'points':[{'beat':beat,'value':value} for beat,value in zip(beats,values)],
            'segments':[{'start_beat':'0/1','end_beat':'2/1','direction':directions[0]},
                        {'start_beat':'2/1','end_beat':'4/1','direction':directions[1]}]}

def rise_turn_return(*,source_family='locked-bloom-directional'):
    return DirectionalGesture({
      'format':'zaaggenz-directional-gesture','version':VERSION,'id':'synthetic-rise-turn-return',
      'description':'Four-beat synthetic gesture with rising intensity/brightness/pitch into a protected midpoint turn, then a directional return and fixed terminal landing.',
      'duration_beats':'4/1','source_family':source_family,'base_degree':0,'base_gain_db':-24.,
      'landing':{'beat':'7/2','duration_beats':'1/2','degree':0,'detune_cents':0.,'gain_db':-24.},
      'landmarks':[{'id':'entry','beat':'0/1','kind':'entry'},{'id':'turn','beat':'2/1','kind':'turn'},
                   {'id':'landing','beat':'7/2','kind':'landing'},{'id':'endpoint','beat':'4/1','kind':'endpoint'}],
      'trajectories':[
        _trajectory('onset_density','events/beat',[2,4,8,4,2],('rising','falling'),'step'),
        _trajectory('accent_db','dB',[0.,1.5,3.,1.,0.],('rising','falling')),
        _trajectory('duration_beats','beats',[.5,.375,.25,.375,.5],('falling','rising'),'step'),
        _trajectory('pitch_cents','cents',[0.,100.,300.,120.,0.],('rising','falling')),
        _trajectory('brightness_hz','Hz',[1600.,2500.,5200.,3000.,1800.],('rising','falling')),
        _trajectory('roughness_fraction','ratio',[.25,.4,.65,.5,.3],('rising','falling')),
        _trajectory('spectral_occupancy_fraction','ratio',[.35,.5,.8,.62,.4],('rising','falling')),
        _trajectory('spectral_width_fraction','ratio',[.3,.45,.85,.65,.38],('rising','falling'))]})
