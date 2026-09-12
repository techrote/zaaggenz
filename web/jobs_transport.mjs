// Browser-side stale-result gate. Audio/scopes/revision publish as one immutable snapshot.
export class RenderTransport {
  constructor() { this.channels = new Map(); }
  begin(channel, revisionId) {
    const old = this.channels.get(channel);
    const generation = (old?.generation ?? 0) + 1;
    this.channels.set(channel, { generation, revisionId, current: null });
    return generation;
  }
  stop(channel) {
    const old = this.channels.get(channel);
    const generation = (old?.generation ?? 0) + 1;
    this.channels.set(channel, { generation, revisionId: null, current: null });
    return generation;
  }
  accept(channel, message) {
    const state = this.channels.get(channel);
    if (!state || message.accepted !== true || message.state !== 'completed') return false;
    if (message.generation !== state.generation || message.revision_id !== state.revisionId) return false;
    const a = message.artifact;
    if (!a || a.revision_id !== state.revisionId || !a.asset || !a.scopes) return false;
    // Replace transport-visible state atomically: no audio from one revision with scopes from another.
    state.current = Object.freeze({
      generation: state.generation,
      revisionId: state.revisionId,
      audio: message.audio,
      asset: structuredClone(a.asset),
      scopes: structuredClone(a.scopes),
      recipeSha256: a.recipe_sha256,
      cacheKey: a.cache_key,
      product: a.product,
    });
    return true;
  }
  current(channel) { return this.channels.get(channel)?.current ?? null; }
}
