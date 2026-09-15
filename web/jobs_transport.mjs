// Browser-side stale-result gate. Audio/scopes/request identity publish as one immutable snapshot.
export class RenderTransport {
  constructor() { this.channels = new Map(); }
  begin(channel, revisionId, recipeSha256, cacheKey, product = 'preview') {
    for (const [name, value] of Object.entries({revisionId, recipeSha256, cacheKey, product})) {
      if (typeof value !== 'string' || value.length === 0) throw new TypeError(`${name} is required`);
    }
    const old = this.channels.get(channel);
    const generation = (old?.generation ?? 0) + 1;
    this.channels.set(channel, { generation, revisionId, recipeSha256, cacheKey, product, current: null });
    return generation;
  }
  stop(channel) {
    const old = this.channels.get(channel);
    const generation = (old?.generation ?? 0) + 1;
    this.channels.set(channel, { generation, revisionId: null, recipeSha256: null, cacheKey: null, product: null, current: null });
    return generation;
  }
  accept(channel, message) {
    const state = this.channels.get(channel);
    if (!state || message.accepted !== true || message.state !== 'completed') return false;
    if (message.generation !== state.generation || message.revision_id !== state.revisionId) return false;
    const a = message.artifact;
    if (!a || !a.asset || !a.scopes) return false;
    if (a.revision_id !== state.revisionId || a.recipe_sha256 !== state.recipeSha256 ||
        a.cache_key !== state.cacheKey || a.product !== state.product) return false;
    // Replace transport-visible state atomically only after the complete request identity agrees.
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
