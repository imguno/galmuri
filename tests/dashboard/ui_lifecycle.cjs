/* Execute the real UI with a deterministic delayed transport, without browser dependencies. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor() {
    this.value = ""; this.textContent = ""; this.hidden = false;
    this.children = []; this.handlers = {}; this.classList = {toggle() {}};
  }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  querySelector() { return new Element(); }
  querySelectorAll() { return []; }
  get options() { return this.children; }
}

(async () => {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  let releaseRead;
  const document = {getElementById: element, createElement: () => new Element(),
    createTextNode: text => ({textContent: text}), querySelectorAll: () => []};
  const response = result => ({json: async () => ({ok: true, result})});
  const context = vm.createContext({document, fetch: async (path, options = {}) => {
    if (path === "/auth/me") return response({authenticated: false});
    if (path === "/api/capabilities") return response({sample: {operations: ["read"]}});
    if (path === "/auth/logout") return response(null);
    const command = JSON.parse(options.body);
    if (command.operation === "read") return new Promise(resolve => { releaseRead = resolve; });
    if (command.operation === "documents") return response({items: [], total: 0});
    throw new Error("Unexpected request: " + path);
  }});
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
  await new Promise(resolve => setImmediate(resolve));
  vm.runInContext(`state.me = {authenticated: true, user_id: "private-user"};
    state.csrf = "csrf"; $("source").value = "sample";
    $("document-preview").hidden = false;
    $("document-content").value = "previous private body";
    $("documents").append(document.createTextNode("private filename"));`, context);
  const pendingRead = vm.runInContext("openDocument({key:'private',name:'Private',can_write:true})", context);
  // The current account logs out while its document request remains in flight.
  await element("logout").onclick();
  assert.equal(element("document-preview").hidden, true);
  assert.equal(element("document-content").value, "");
  assert.equal(element("documents").children.length, 0);
  // A response already authorized by the old session must not repopulate the new view.
  releaseRead(response({key: "private", text: "late private body", version: "v1"}));
  await assert.rejects(pendingRead, error => error.stale === true);
  assert.equal(element("document-preview").hidden, true);
  assert.equal(element("document-content").value, "");
  assert.equal(element("token-secret").textContent, "");
  process.stdout.write("UI logout clears private state and fences late document responses\n");
})().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; });
