#!/usr/bin/env bun
// opencode-termux: stop OpenTUI from failing on tagged heap pointers.
//
// Bionic tags heap pointers in the top byte (TBI). On a real device
// `malloc(64)` returns e.g. 0xb400007a3a41e380, whose value is far above
// Number.MAX_SAFE_INTEGER, while the address itself is 0x7a3a41e380. OpenTUI
// converts the context pointer returned by `ot_context_create` to a JS number
// and throws "Pointer exceeds safe integer range", so the TUI dies on the first
// native call. CI never sees it: termux-docker has no tagged-address ABI.
//
// The tag is not part of the address, so dropping it is safe. bun:ffi takes
// numeric pointers only, which is why the value must stay a number.
//
//   bun scripts/patch-opentui-pointer.mjs <opencode-source-root> [--self-test]
//
// Exits non-zero when neither the original nor the patched function is found:
// a silent no-op here would ship a binary that cannot open the TUI.

import fs from "node:fs";
import path from "node:path";

const MARKER = "bionic tags heap pointers";
const FUNCTION_RE = /function toSafeNumberPointer\(pointer\) \{[\s\S]{0,600}?\n\}/;

const PATCHED = `function toSafeNumberPointer(pointer) {
  if (pointer < 0n) {
    throw new Error(POINTER_NEGATIVE);
  }
  if (pointer > BigInt(Number.MAX_SAFE_INTEGER)) {
    // opencode-termux: ${MARKER} in the top byte (TBI), and the tag is not
    // part of the address. Drop it instead of failing: bun:ffi accepts numeric
    // pointers only.
    const untagged = pointer & 0x00ffffffffffffffn;
    if (untagged >= 0x1000n && untagged <= BigInt(Number.MAX_SAFE_INTEGER)) {
      return Number(untagged);
    }
    throw new Error(POINTER_UNSAFE);
  }
  return Number(pointer);
}`;

const args = process.argv.slice(2);
const selfTest = args.includes("--self-test");
const root = args.find((arg) => !arg.startsWith("--"));

if (!root) {
  console.error("usage: patch-opentui-pointer.mjs <opencode-source-root> [--self-test]");
  process.exit(2);
}

// Bun hoists, nests, or keeps hardlinks in its `.bun` store, so walk the tree
// instead of assuming one location (tools/swap_native_assets.py does the same).
function opentuiPackages(dir, found = [], seen = new Set()) {
  let entries;
  try {
    if (!fs.statSync(dir).isDirectory()) return found;
    const key = fs.realpathSync(dir);
    if (seen.has(key)) return found;
    seen.add(key);
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    if (entry.name === ".git") continue;
    const full = path.join(dir, entry.name);
    let isDirectory;
    try {
      // Bun links packages, so symlinked directories must be followed.
      isDirectory = fs.statSync(full).isDirectory();
    } catch {
      continue;
    }
    if (!isDirectory) continue;
    if (entry.name === "@opentui") {
      const core = path.join(full, "core");
      if (fs.existsSync(path.join(core, "package.json"))) found.push(core);
      continue;
    }
    opentuiPackages(full, found, seen);
  }
  return found;
}

const packages = [...new Set(opentuiPackages(root).map((dir) => fs.realpathSync(dir)))];
if (packages.length === 0) {
  console.error(`patch-opentui-pointer: no @opentui/core under ${root}; run bun install first`);
  process.exit(1);
}

function javascriptFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "node_modules") out.push(...javascriptFiles(full));
    } else if (entry.name.endsWith(".js")) {
      out.push(full);
    }
  }
  return out;
}

const files = packages.flatMap((dir) => javascriptFiles(dir));
const withFunction = [...new Set(files)].filter((file) => {
  const text = fs.readFileSync(file, "utf8");
  return text.includes("POINTER_UNSAFE") && FUNCTION_RE.test(text);
});

if (withFunction.length === 0) {
  console.error(
    `patch-opentui-pointer: no toSafeNumberPointer in ${packages.length} @opentui/core (${files.length} JS files); OpenTUI changed`
  );
  process.exit(1);
}

let patched = 0;
for (const file of withFunction) {
  const before = fs.readFileSync(file, "utf8");
  if (before.includes(MARKER)) {
    console.log(`already patched: ${path.relative(root, file)}`);
    continue;
  }
  const match = before.match(FUNCTION_RE);
  if (!match?.[0].includes("POINTER_UNSAFE") || !match[0].includes("MAX_SAFE_INTEGER")) {
    console.error(`patch-opentui-pointer: unexpected shape in ${path.relative(root, file)}`);
    process.exit(1);
  }
  fs.writeFileSync(file, before.replace(FUNCTION_RE, PATCHED));
  patched += 1;
  console.log(`patched: ${path.relative(root, file)}`);
}

if (selfTest) {
  const source = fs.readFileSync(withFunction[0], "utf8");
  const body = source.match(FUNCTION_RE)?.[0];
  if (!body) {
    console.error("patch-opentui-pointer: self-test could not read the function back");
    process.exit(1);
  }
  const fn = new Function(`${body}\nreturn toSafeNumberPointer;`)();
  const cases = [
    [0xb400007a3a41e380n, 0x7a3a41e380, "tagged heap pointer"],
    [0x7f3c1a20n, 0x7f3c1a20, "plain pointer"],
  ];
  for (const [input, expected, label] of cases) {
    const actual = fn(input);
    if (actual !== expected) {
      console.error(`patch-opentui-pointer: self-test ${label}: ${actual} !== ${expected}`);
      process.exit(1);
    }
  }
  for (const [input, label] of [
    [0x0100000000000000n, "tag only, no address"],
    [-1n, "negative pointer"],
  ]) {
    let threw = false;
    try {
      fn(input);
    } catch {
      threw = true;
    }
    if (!threw) {
      console.error(`patch-opentui-pointer: self-test ${label} did not throw`);
      process.exit(1);
    }
  }
  console.log("self-test: ok");
}

console.log(`patch-opentui-pointer: ${patched} file(s) patched`);
