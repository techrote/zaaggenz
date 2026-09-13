// Authoring edits are snapshots. Audio and scientific contracts stay server-authoritative.
export const copy = value => structuredClone(value);
const gcd = (a,b) => b ? gcd(b,a%b) : a;
export function rational(value) {
  const s=String(value).trim();
  let n,d;
  if (/^-?\d+\/[1-9]\d*$/.test(s)) [n,d]=s.split('/').map(BigInt);
  else if (/^-?\d+(\.\d{1,9})?$/.test(s)) {
    const parts=s.split('.'); d=10n**BigInt(parts[1]?.length??0); n=BigInt(parts.join(''));
  } else throw Error('Use a beat number or fraction, such as 1.5 or 3/2.');
  if (d===0n) throw Error('A fraction cannot have a zero denominator.');
  const g=gcd(n<0n?-n:n,d); n/=g;d/=g;
  if (n>1000000000n||n< -1000000000n||d>1000000000n) throw Error('Beat fraction is too large.');
  return `${n}/${d}`;
}
export function value(s) { const [n,d]=rational(s).split('/').map(Number); return n/d; }
function calc(a,b,op) {
  const [an,ad]=rational(a).split('/').map(BigInt),[bn,bd]=rational(b).split('/').map(BigInt);
  return rational(op==='add'?`${an*bd+bn*ad}/${ad*bd}`:`${an*bn}/${ad*bd}`);
}
export const add=(a,b)=>calc(a,b,'add');
export function snap(a,grid) {
  const [n,d]=rational(a).split('/').map(BigInt),[gn,gd]=rational(grid).split('/').map(BigInt);
  if(n<0n||gn<=0n)throw Error('Onsets must be nonnegative and snap must be positive.');
  const top=n*gd,bottom=d*gn;
  const k=(2n*top+bottom)/(2n*bottom); // exact nonnegative nearest, ties upwards
  return rational(`${k*gn}/${gd}`);
}

export class Editor {
  constructor(data) {this.state=copy(data);this.past=[];this.future=[];}
  get document(){return copy(this.state);}
  commit(mutator) {
    const next=copy(this.state);mutator(next);
    if (JSON.stringify(next)===JSON.stringify(this.state))return;
    if (next.notes.length>256)throw Error('At most 256 note/rest objects.');
    if (next.notes.some(r=>value(r.beat)<0||value(r.duration_beats)<=0||value(add(r.beat,r.duration_beats))>value(next.end_beat)))
      throw Error('The edit puts an event outside the phrase. Extend the phrase first.');
    this.past.push(this.state);if(this.past.length>64)this.past.shift();
    this.state=next;this.future=[];
  }
  replace(data){this.commit(s=>{for(const k of Object.keys(s))delete s[k];Object.assign(s,copy(data));});}
  undo(){if(this.past.length){this.future.push(this.state);this.state=this.past.pop();}}
  redo(){if(this.future.length){this.past.push(this.state);this.state=this.future.pop();}}
  id(s,prefix='n'){
    const ids=new Set([...s.notes,...s.clips].map(r=>r.id));let id;
    do {if(s.next_id>=1000000)throw Error('Event identity counter exhausted.');id=`${prefix}-${s.next_id++}`;}while(ids.has(id));
    return id;
  }
  add(row,grid){let id;this.commit(s=>{id=this.id(s);s.notes.push({...copy(row),id,beat:snap(row.beat,grid),duration_beats:snap(row.duration_beats,grid)});});return id;}
  edit(id,row,grid){this.commit(s=>{const i=s.notes.findIndex(r=>r.id===id);if(i<0)throw Error('Select an event.');s.notes[i]={...copy(row),id,beat:snap(row.beat,grid),duration_beats:snap(row.duration_beats,grid)};});}
  duplicate(id,grid){let newid;this.commit(s=>{const row=s.notes.find(r=>r.id===id);if(!row)throw Error('Select an event.');newid=this.id(s);s.notes.push({...copy(row),id:newid,beat:snap(add(row.beat,row.duration_beats),grid)});});return newid;}
  remove(id){this.commit(s=>s.notes=s.notes.filter(r=>r.id!==id));}
  mute(id){this.commit(s=>{const row=s.notes.find(r=>r.id===id);if(!row)throw Error('Select an event.');row.muted=!row.muted;});}
  clip(name,start,end){let id;this.commit(s=>{id=this.id(s,'c');s.clips.push({id,name,start_beat:rational(start),end_beat:rational(end)});});return id;}
  duplicateClip(id){this.commit(s=>{const c=s.clips.find(c=>c.id===id);if(!c)throw Error('Select a clip.');
    const [n,d]=rational(c.start_beat).split('/');const span=add(c.end_beat,`-${n}/${d}`);
    if(value(add(c.end_beat,span))>value(s.end_beat))throw Error('Extend the phrase before duplicating this clip.');
    const rows=s.notes.filter(r=>value(r.beat)>=value(c.start_beat)&&value(add(r.beat,r.duration_beats))<=value(c.end_beat));
    for(const r of rows)s.notes.push({...copy(r),id:this.id(s),beat:add(r.beat,span)});
    s.clips.push({id:this.id(s,'c'),name:c.name+' copy',start_beat:c.end_beat,end_beat:add(c.end_beat,span)});
  });}
  example(bars){this.commit(s=>{s.end_beat=`${bars*4}/1`;s.notes=[];s.clips=[];
    for(let i=0;i<bars*8;i++)s.notes.push({id:this.id(s),beat:rational(`${i}/2`),duration_beats:'1/2',
      degree:i%8===6?null:[0,2,4,7,4,2,0,0][i%8],detune_cents:0,gain_db:-18,muted:false,roll_density:i%8===7?8:0});
    s.clips.push({id:this.id(s,'c'),name:'First four bars',start_beat:'0/1',end_beat:'16/1'});
  });}
}
