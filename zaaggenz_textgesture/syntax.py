"""Small non-executable scanner/parser for mnemonic gesture text."""
from __future__ import annotations
from fractions import Fraction
import math,re
from .model import TextGestureError,VERSION

MODIFIERS=('d','a','p','c','b','r','o','w','n')
MODIFIER_UNITS={'d':'beats','a':'dB','p':'scale-degrees','c':'cents','b':'opening-fraction','r':'roughness-fraction','o':'occupancy-fraction','w':'width-fraction','n':'events/beat'}
_TOKEN=re.compile(r'[a-z][a-z0-9-]{0,31}')
_KEY=re.compile(r'[a-z]')
_RATIONAL=re.compile(r'(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*|\.[0-9]{1,6})?\Z')
_NUMBER=re.compile(r'[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z')
_INTEGER=re.compile(r'[+-]?(?:0|[1-9][0-9]*)\Z')

class TextSyntaxError(TextGestureError):
    def __init__(self,text,index,message):
        self.offset=index;self.line=text.count('\n',0,index)+1;last=text.rfind('\n',0,index);self.column=index-(last if last>=0 else -1)
        self.message=message;super().__init__(f'line {self.line}, column {self.column}: {message}')

def _rat(value):return f'{value.numerator}/{value.denominator}'
def _duration(raw,text,index):
    if not _RATIONAL.fullmatch(raw):raise TextSyntaxError(text,index,'duration must be a nonnegative decimal or rational such as 1/2')
    try:value=Fraction(raw)
    except (ValueError,ZeroDivisionError) as exc:raise TextSyntaxError(text,index,'invalid duration') from exc
    if not 0<value<=4:raise TextSyntaxError(text,index,'duration must be in (0, 4] beats')
    if value.denominator>960:raise TextSyntaxError(text,index,'duration grid is finer than 1/960 beat')
    return _rat(value)
def _decimal(raw,text,index,lo,hi,name):
    if not _NUMBER.fullmatch(raw):raise TextSyntaxError(text,index,f'{name} must be an ordinary decimal number')
    value=float(raw)
    if not math.isfinite(value) or not lo<=value<=hi:raise TextSyntaxError(text,index,f'{name} must be in [{lo}, {hi}]')
    return value
def _integer(raw,text,index,lo,hi,name):
    if not _INTEGER.fullmatch(raw):raise TextSyntaxError(text,index,f'{name} must be an integer')
    value=int(raw)
    if not lo<=value<=hi:raise TextSyntaxError(text,index,f'{name} must be in [{lo}, {hi}]')
    return value

def _modifier_value(key,raw,text,index):
    if key=='d':return _duration(raw,text,index)
    if key=='a':return _decimal(raw,text,index,-24,24,'accent')
    if key=='p':return _integer(raw,text,index,-32,32,'pitch degrees')
    if key=='c':return _decimal(raw,text,index,-1200,1200,'pitch cents')
    if key in ('b','r','o','w'):return _decimal(raw,text,index,0,1,MODIFIER_UNITS[key])
    if key=='n':return _integer(raw,text,index,1,16,'density')
    raise TextSyntaxError(text,index,f'unknown modifier {key!r}; allowed: {", ".join(MODIFIERS)}')

def _span(text,start,end):
    line=text.count('\n',0,start)+1;last=text.rfind('\n',0,start);column=start-(last if last>=0 else -1)
    return {'start':start,'end':end,'line':line,'column':column}

class _Parser:
    def __init__(self,text):
        if type(text)is not str:raise TextGestureError('text must be UTF-8 string data')
        if len(text)>65536:raise TextGestureError('text exceeds 65,536 characters')
        if any(ord(ch)<32 and ch not in '\n\r\t' for ch in text):raise TextGestureError('text contains unsupported control characters')
        self.text=text;self.i=0
    def ws(self):
        while self.i<len(self.text) and self.text[self.i].isspace():self.i+=1
    def mods(self):
        self.ws()
        if self.i>=len(self.text) or self.text[self.i]!='[':return {}
        self.i+=1;values={}
        while True:
            self.ws()
            if self.i>=len(self.text):raise TextSyntaxError(self.text,self.i,'unterminated modifier list')
            if self.text[self.i]==']':self.i+=1;return values
            key_start=self.i;m=_KEY.match(self.text,self.i)
            if not m:raise TextSyntaxError(self.text,self.i,'expected one-letter modifier key')
            key=m.group(0);self.i=m.end();self.ws()
            if self.i>=len(self.text) or self.text[self.i]!='=':raise TextSyntaxError(self.text,self.i,"expected '=' after modifier key")
            self.i+=1;self.ws();value_start=self.i
            while self.i<len(self.text) and self.text[self.i] not in ',]':self.i+=1
            raw=self.text[value_start:self.i].strip()
            if not raw:raise TextSyntaxError(self.text,value_start,'modifier value is empty')
            if key in values:raise TextSyntaxError(self.text,key_start,f'duplicate modifier {key!r}')
            values[key]=_modifier_value(key,raw,self.text,value_start)
            if self.i>=len(self.text):raise TextSyntaxError(self.text,self.i,'unterminated modifier list')
            if self.text[self.i]==',':self.i+=1;continue
            self.i+=1;return values
    def parse(self):
        items=[];token_count=0;return_seen=False;group_has_event=False
        self.ws()
        while self.i<len(self.text):
            start=self.i;ch=self.text[self.i]
            if return_seen:raise TextSyntaxError(self.text,self.i,'nothing may follow the terminal @return marker')
            if ch=='|':
                if not group_has_event:raise TextSyntaxError(self.text,self.i,'group separator requires an event before it')
                self.i+=1;items.append({'kind':'group','span':_span(self.text,start,self.i)});group_has_event=False
            elif ch=='~':
                if not items or items[-1]['kind'] not in ('token','hold'):raise TextSyntaxError(self.text,self.i,'hold must follow a syllable or another hold')
                self.i+=1;value_start=self.i
                while self.i<len(self.text) and not self.text[self.i].isspace() and self.text[self.i] not in '|[]':self.i+=1
                raw=self.text[value_start:self.i]
                duration=_duration(raw,self.text,value_start);items.append({'kind':'hold','duration_beats':duration,'span':_span(self.text,start,self.i)})
            elif self.text.startswith('@return',self.i):
                if not group_has_event:raise TextSyntaxError(self.text,self.i,'@return requires at least one event in its group')
                self.i+=7;mods=self.mods();items.append({'kind':'return','modifiers':mods,'span':_span(self.text,start,self.i)});return_seen=True
            else:
                match=_TOKEN.match(self.text,self.i)
                if not match:raise TextSyntaxError(self.text,self.i,f'unexpected character {ch!r}')
                token=match.group(0);self.i=match.end();mods=self.mods();items.append({'kind':'token','token':token,'modifiers':mods,'span':_span(self.text,start,self.i)});token_count+=1;group_has_event=True
                if token_count>128:raise TextSyntaxError(self.text,start,'at most 128 syllable events are allowed')
            self.ws()
        if not items:raise TextSyntaxError(self.text,0,'text gesture is empty')
        if items[-1]['kind']!='return':raise TextSyntaxError(self.text,len(self.text),'text gesture requires a terminal @return marker')
        groups=1+sum(item['kind']=='group' for item in items)
        return {'format':'zaaggenz-text-ast','version':VERSION,'items':items,'group_count':groups,'modifier_units':dict(MODIFIER_UNITS)}

def parse_text(text):return _Parser(text).parse()

def _num(value):
    if isinstance(value,int):return str(value)
    if isinstance(value,float):
        if value==0:return '0'
        return format(value,'.12g')
    return str(value)
def _format_mods(mods):
    if not mods:return ''
    values=[]
    for key in MODIFIERS:
        if key in mods:values.append(f'{key}={_num(mods[key])}')
    return '['+','.join(values)+']'
def format_text(ast):
    if type(ast)is not dict or ast.get('format')!='zaaggenz-text-ast' or ast.get('version')!=VERSION:raise TextGestureError('valid text AST required')
    parts=[]
    for item in ast['items']:
        if item['kind']=='token':parts.append(item['token']+_format_mods(item['modifiers']))
        elif item['kind']=='hold':parts.append('~'+item['duration_beats'])
        elif item['kind']=='group':parts.append('|')
        elif item['kind']=='return':parts.append('@return'+_format_mods(item['modifiers']))
        else:raise TextGestureError('unknown AST item kind')
    return ' '.join(parts)

def semantic_ast(ast):
    """Drop source spans while retaining timing, units, grouping and return landmarks."""
    return {'format':ast['format'],'version':ast['version'],'group_count':ast['group_count'],'modifier_units':ast['modifier_units'],
            'items':[{k:v for k,v in item.items() if k!='span'} for item in ast['items']]}
