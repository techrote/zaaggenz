// Independent Node reference for zg-c14n-v1. Not JCS and not a schema validator.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

function exactNumber(x) {
  if (!Number.isFinite(x) || (Number.isInteger(x) && !Number.isSafeInteger(x)))
    throw new Error('Nonfinite or unsafe number');
  if (x === 0) return ['number', '0', '1'];
  const b = new ArrayBuffer(8), view = new DataView(b);
  view.setFloat64(0, x, false);
  const bits = view.getBigUint64(0, false);
  const exp = Number((bits >> 52n) & 2047n);
  let n = bits & ((1n << 52n) - 1n);
  const power = exp === 0 ? -1074 : exp - 1023 - 52;
  if (exp !== 0) n += 1n << 52n;
  let d = 1n;
  if (power >= 0) n <<= BigInt(power); else d <<= BigInt(-power);
  while (d > 1n && n % 2n === 0n) { n >>= 1n; d >>= 1n; }
  if ((bits >> 63n) !== 0n) n = -n;
  return ['number', n.toString(), d.toString()];
}

export function digest(value) {
  let count = 0;
  const active = new Set();
  function tag(x, depth = 0) {
    if (++count > 100000 || depth > 32) throw new Error('Resource bound');
    if (x === null) return ['null'];
    if (typeof x === 'boolean') return ['bool', x];
    if (typeof x === 'number') return exactNumber(x);
    if (typeof x === 'string') {
      if (Array.from(x).length > 65536 || Array.from(x).some(c => {
        const p = c.codePointAt(0); return p >= 0xd800 && p <= 0xdfff;
      })) throw new Error('Invalid string');
      return ['string', x];
    }
    if (typeof x !== 'object' || active.has(x)) throw new Error('Non-JSON or cyclic input');
    active.add(x);
    let result;
    if (Array.isArray(x)) result = ['array', x.map(v => tag(v, depth + 1))];
    else {
      if (Object.getPrototypeOf(x) !== Object.prototype) throw new Error('Non-JSON object');
      const keys = Object.keys(x).sort((a,b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
      result = ['object', keys.map(k => { tag(k, depth + 1); return [k, tag(x[k], depth + 1)]; })];
    }
    active.delete(x);
    return result;
  }
  const tagged = tag(value);
  if (Buffer.byteLength(JSON.stringify(value)) > 2000000) throw new Error('Byte bound');
  return createHash('sha256').update('zaaggenz.contract.c14n-v1\0').update(JSON.stringify(tagged)).digest('hex');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const lines = readFileSync(0, 'utf8').trim().split('\n');
  for (const line of lines) console.log(digest(JSON.parse(line)));
}
