import assert from 'node:assert/strict';
import {VocalEditor,pcm16Wav} from '../../web/vocal/editor.mjs';
const edit={segments:[{segment_id:'vocal-000',approved:true,manual_offset_samples:0,pitch_mode:'estimate',manual_pitch_hz:null,manual_brightness_hz:null,token:'bu'}],source_disposition:'retained-session-local'};
const e=new VocalEditor(edit);e.patch('vocal-000',{manual_offset_samples:7});assert.equal(e.document.segments[0].manual_offset_samples,7);assert(e.undo());assert.equal(e.document.segments[0].manual_offset_samples,0);assert(e.redo());assert.equal(e.document.segments[0].manual_offset_samples,7);e.replace({...e.document,source_disposition:'discarded'},{resetHistory:true});assert.equal(e.document.source_disposition,'discarded');assert.equal(e.undo(),false);
const blob=pcm16Wav([new Float32Array([0,-1,1,.5])],48000);assert.equal(blob.type,'audio/wav');assert.equal(blob.size,52);console.log('vocal editor: history/reset and local PCM16 WAV encoding passed');
