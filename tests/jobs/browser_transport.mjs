import assert from 'node:assert/strict';
import { RenderTransport } from '../../web/jobs_transport.mjs';
const r1='a'.repeat(64),r2='b'.repeat(64),q='c'.repeat(64),k='d'.repeat(64);
const t=new RenderTransport();
assert.throws(()=>t.begin('preview',r1),TypeError,'complete immutable identity is required at begin');
const g1=t.begin('preview',r1,q,k),g2=t.begin('preview',r2,q,k);
const message=(generation,revision,recipe=q,cacheKey=k,product='preview',waveform=[1],audio=[1,2])=>({
  state:'completed',accepted:true,generation,revision_id:revision,audio:new Uint8Array(audio),
  artifact:{revision_id:revision,recipe_sha256:recipe,cache_key:cacheKey,product,asset:{kind:'AudioAssetRef'},scopes:{waveform}}
});
assert.equal(t.accept('preview',message(g1,r1)),false,'late prior generation must be rejected');
for (const [name,bad] of [
  ['revision',message(g2,r1)],
  ['recipe',message(g2,r2,'e'.repeat(64))],
  ['cache',message(g2,r2,q,'f'.repeat(64))],
  ['product',message(g2,r2,q,k,'analysis')],
]) {
  assert.equal(t.accept('preview',bad),false,`${name} mismatch must be rejected`);
  assert.equal(t.current('preview'),null,`${name} mismatch must not create playable state`);
}
assert.equal(t.accept('preview',message(g2,r2)),true);
const current=t.current('preview');
assert.equal(current.revisionId,r2);assert.equal(current.recipeSha256,q);assert.equal(current.cacheKey,k);assert.equal(current.product,'preview');
assert.deepEqual(current.scopes,{waveform:[1]});
const poisoned=message(g2,r2,'e'.repeat(64),k,'preview',[9],[9]);
assert.equal(t.accept('preview',poisoned),false,'mismatch must not replace accepted audio/scopes');
assert.strictEqual(t.current('preview'),current);assert.deepEqual(t.current('preview').scopes,{waveform:[1]});assert.deepEqual([...t.current('preview').audio],[1,2]);
t.stop('preview');assert.equal(t.current('preview'),null);assert.equal(t.accept('preview',message(g2,r2)),false,'stop invalidates late decode/playback');
console.log(JSON.stringify({stale_rejected:true,complete_identity_bound:true,mismatch_not_playable:true,atomic_transport_snapshot:true,stop_invalidates:true}));
