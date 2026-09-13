"""Original local mnemonic dictionaries; tokens deliberately have no universal meaning."""
from __future__ import annotations
from .model import MnemonicDictionary,DictionaryRegistry,VERSION


def _mapping(duration='1/2',accent=0.,degree=0,cents=0.,brightness=.35,roughness=.3,occupancy=.45,width=.4,density=2):
    return {'duration_beats':duration,'accent_db':float(accent),'degree_offset':int(degree),'detune_cents':float(cents),
            'brightness_fraction':float(brightness),'roughness_fraction':float(roughness),
            'spectral_occupancy_fraction':float(occupancy),'spectral_width_fraction':float(width),
            'density_per_beat':int(density)}


def _dictionary(identifier,description,entries,*,base_degree=0,base_gain_db=-24.,brightness=(1200.,7000.)):
    return MnemonicDictionary({'format':'zaaggenz-text-dictionary','version':VERSION,'id':identifier,'description':description,
        'base_degree':int(base_degree),'base_gain_db':float(base_gain_db),
        'brightness_range_hz':{'closed_hz':float(brightness[0]),'open_hz':float(brightness[1])},
        'return_mapping':_mapping('1/2',0.,0,0.,.3,.3,.45,.4,1),
        'entries':[{'token':token,'mapping':mapping} for token,mapping in entries]})


def starter_registry():
    soft=_dictionary('local-soft','Synthetic project-local mnemonic dictionary: compact low/mid motion. Token names are user mnemonics, not phonetic/acoustic universals.',[
        ('bu',_mapping('1/2',0.,0,0.,.28,.28,.42,.38,2)),
        ('budu',_mapping('1/2',1.,2,0.,.48,.38,.52,.48,4)),
        ('budubu',_mapping('1/4',2.,4,0.,.68,.48,.62,.58,8)),
        ('ta',_mapping('1/4',1.5,7,0.,.58,.42,.56,.52,4))])
    bright=_dictionary('local-bright','Synthetic alternative project-local dictionary using the same mnemonic tokens with intentionally different mappings.',[
        ('bu',_mapping('1/2',1.5,4,25.,.82,.52,.72,.68,4)),
        ('budu',_mapping('1/4',2.5,7,35.,.9,.62,.82,.78,8)),
        ('budubu',_mapping('1/4',3.,9,45.,.96,.72,.9,.86,12)),
        ('ta',_mapping('1/2',.5,2,-20.,.6,.35,.5,.46,2))],brightness=(1600.,9000.))
    return DictionaryRegistry([soft,bright])
