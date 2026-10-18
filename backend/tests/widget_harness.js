// Runs the chat widget against a live server with a tiny fake DOM, the way a customer's page would:
//   node widget_harness.js <origin> <widget key> [blocked]
// It prints one JSON line per step ({"step": "sent"}, ...) and waits for a line on stdin after "sent", so the test can
// reply as an agent. With "blocked", localStorage throws on every access (a private window): the widget must still work.
const vm = require("vm");
const readline = require("readline");

const [origin, key, mode] = process.argv.slice(2);
const registry = {};
const say = (o) => process.stdout.write(JSON.stringify(o) + "\n");

function el(tag) {
  const e = {
    tag, children: [], listeners: {}, attrs: {}, textContent: "", value: "", hidden: false, scrollTop: 0, scrollHeight: 0,
    style: { setProperty() {}, cssText: "" }, classList: { toggle() {} }, elements: {},
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    remove() { this.removed = true; }, focus() {},
    querySelector(selector) { return registry[selector] || (registry[selector] = el(selector)); },
    set innerHTML(v) { this.html = v; }, get innerHTML() { return this.html; },
  };
  return e;
}

async function main() {
  const source = await (await fetch(origin + "/widget.js")).text();
  const script = el("script");
  script.attrs = { "data-key": key, "data-color": "#112233" };
  script.src = origin + "/widget.js";
  const body = el("body");
  const storage = new Map();
  const sandbox = {
    document: { currentScript: script, body, head: el("head"), createElement: el, addEventListener() {} },
    window: {}, fetch, URL, crypto: globalThis.crypto, setTimeout, clearTimeout, JSON, Promise, Math, console,
  };
  Object.defineProperty(sandbox, "localStorage", mode === "blocked"
    ? { get() { throw new Error("SecurityError: storage is blocked"); } }
    : { value: { getItem: (k) => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, v) } });
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  say({ step: "loaded", bubble: body.children.length });

  const bubble = body.children[0];
  bubble.listeners.click[0]();  // the visitor opens the chat
  const list = registry["#gh-list"];
  const until = async (test, what) => {
    for (let i = 0; i < 100; i++) { if (test()) return; await new Promise((r) => setTimeout(r, 100)); }
    throw new Error("timed out waiting for " + what);
  };
  await until(() => list.children.length > 0, "the greeting");
  say({ step: "greeting", text: list.children[0].textContent, title: registry["#gh-title"].textContent });

  registry["#gh-input"].value = "hello from the widget";
  registry["#gh-form"].listeners.submit[0]({ preventDefault() {} });
  await until(() => list.children.some((c) => c.textContent === "hello from the widget"), "our message");
  say({ step: "sent", stored: [...storage.keys()].length, asked: registry["#gh-ask"].hidden === false });

  const lines = readline.createInterface({ input: process.stdin });
  await new Promise((resolve) => lines.once("line", resolve));
  await until(() => list.children.some((c) => c.textContent === "an agent replies"), "the agent's reply");
  say({ step: "replied", messages: list.children.map((c) => [c.className, c.textContent]) });
  const ask = registry["#gh-ask"].elements;
  Object.assign(ask, { name: { value: "Pat Smith" }, email: { value: "pat@example.com" }, phone: { value: "" },
                       website: { value: "" } });
  registry["#gh-ask"].listeners.submit[0]({ preventDefault() {} });
  await until(() => registry["#gh-note"].textContent.length > 0, "the identify answer");
  say({ step: "identified", note: registry["#gh-note"].textContent });
  process.exit(0);
}

main().catch((e) => { say({ step: "error", message: String(e && e.message || e) }); process.exit(1); });
