import { createRequire } from "node:module";
import { resolve } from "node:path";

const addon = process.argv[2];
if (!addon) throw new Error("usage: iroh_smoke.ts LIBIROH_NODE");

// A N-API addon: the Android linker resolves it, then Rust's key code must run.
const load = createRequire(import.meta.url);
const iroh = load(resolve(addon));

const message = [1, 2, 3];
const key = iroh.SecretKey.generate();
const id = key.public().toString();
if (iroh.EndpointId.fromString(id).toString() !== id) {
  throw new Error(`iroh/EndpointId round trip failed for ${id}`);
}
// An always-accepting verify would pass the first call, so a foreign key must fail.
key.public().verify(message, key.sign(message));
const other = iroh.SecretKey.generate();
let rejected = false;
try {
  other.public().verify(message, key.sign(message));
} catch {
  rejected = true;
}
if (!rejected) throw new Error("iroh/EndpointId verified a signature from another key");
console.log(JSON.stringify({ load: true, key: true, sign: true }));
