export const clone=x=>structuredClone(x);
export class VocalEditor{
  constructor(edit){this.state=clone(edit);this.past=[];this.future=[];}
  get document(){return clone(this.state);}
  patch(segmentId,changes){const next=clone(this.state),row=next.segments.find(x=>x.segment_id===segmentId);if(!row)throw Error('Unknown capture segment.');Object.assign(row,changes);this.past.push(this.state);if(this.past.length>64)this.past.shift();this.state=next;this.future=[];}
  replace(edit,{resetHistory=false}={}){if(resetHistory){this.state=clone(edit);this.past=[];this.future=[];return;}this.past.push(this.state);this.state=clone(edit);this.future=[];}
  undo(){if(this.past.length){this.future.push(this.state);this.state=this.past.pop();return true;}return false;}
  redo(){if(this.future.length){this.past.push(this.state);this.state=this.future.pop();return true;}return false;}
}
export function pcm16Wav(chunks,sampleRate){
  const n=chunks.reduce((a,c)=>a+c.length,0),buffer=new ArrayBuffer(44+n*2),v=new DataView(buffer);let o=0;
  const str=s=>{for(let i=0;i<s.length;i++)v.setUint8(o++,s.charCodeAt(i));};str('RIFF');v.setUint32(o,36+n*2,true);o+=4;str('WAVEfmt ');v.setUint32(o,16,true);o+=4;v.setUint16(o,1,true);o+=2;v.setUint16(o,1,true);o+=2;v.setUint32(o,sampleRate,true);o+=4;v.setUint32(o,sampleRate*2,true);o+=4;v.setUint16(o,2,true);o+=2;v.setUint16(o,16,true);o+=2;str('data');v.setUint32(o,n*2,true);o+=4;
  for(const chunk of chunks)for(const sample of chunk){const x=Math.max(-1,Math.min(1,sample));v.setInt16(o,x<0?x*32768:x*32767,true);o+=2;}return new Blob([buffer],{type:'audio/wav'});
}
