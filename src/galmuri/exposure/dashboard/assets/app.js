"use strict";

const state = {me: {}, csrf: null, apps: {}, users: [], groups: [], offset: 0, total: 0,
  document: null, policy: null, activePanel: "explorer", epoch: 0, policyOffset: 0, policyTotal: 0};
const $ = id => document.getElementById(id);
const rows = result => Array.isArray(result) ? result : (result.items || []);
function notice(message = "") { $("notice").textContent = message; }
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function button(text, action) {
  const item = node("button", text);
  item.type = "button";
  item.addEventListener("click", () => run(action, item));
  return item;
}
async function run(action, control) {
  if (control) control.disabled = true;
  notice();
  try { await action(); } catch (error) { if (!error.stale) notice(error.message || "The request failed."); }
  finally { if (control) control.disabled = false; }
}
async function request(path, body) {
  const epoch = state.epoch;
  const options = {credentials: "same-origin", cache: "no-store", headers: {}};
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    if (state.csrf) options.headers["X-CSRF-Token"] = state.csrf;
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const value = await response.json();
  if (epoch !== state.epoch) { const error = new Error("Account changed"); error.stale = true; throw error; }
  if (!value.ok) throw new Error(value.error?.message || "The operation was refused.");
  return value.result;
}
const call = (operation, params = {}) => request("/dashboard/api", {operation, params});
function form(id, action) {
  $(id).addEventListener("submit", event => {
    event.preventDefault();
    run(action, $(id).querySelector("button"));
  });
}
function options(select, items, value, text) {
  const previous = select.value;
  select.replaceChildren(...items.map(item => {
    const option = node("option", text(item));
    option.value = value(item);
    return option;
  }));
  if ([...select.options].some(option => option.value === previous)) select.value = previous;
}
function cell(tr, text, detail) {
  const td = node("td", text);
  if (detail) td.append(node("small", detail));
  tr.append(td);
  return td;
}
function date(value) {
  return value ? new Date(Number(value) * 1000).toLocaleString() : "—";
}
async function refreshIdentity() {
  const previous = state.me.user_id;
  try { state.me = await request("/auth/me"); }
  catch (error) { if (error.stale) throw error; state.me = {authenticated: false}; }
  state.csrf = state.me.csrf;
  if (previous !== state.me.user_id || !state.me.authenticated) clearPrivateState();
  $("identity").textContent = state.me.authenticated ? (state.me.username || state.me.user_id) : "Public access";
  $("login-panel").hidden = !!state.me.authenticated;
  $("logout").hidden = !state.me.authenticated;
  document.querySelectorAll(".admin-only").forEach(item => { item.hidden = !state.me.administrator; });
  $("root-grant").hidden = !state.me.root;
  if (!state.me.root) $("new-root").checked = false;
  $("create-token").hidden = !state.me.authenticated;
  $("change-password").hidden = !state.me.authenticated;
  if (!state.me.authenticated) {
    $("token-list").replaceChildren();
    clearSecret();
  }
}
function clearPrivateState() {
  state.epoch += 1;
  state.document = null; state.policy = null; state.users = []; state.groups = []; state.offset = 0; state.total = 0;
  state.policyOffset = 0; state.policyTotal = 0;
  $("document-preview").hidden = true; $("document-content").value = "";
  $("document-title").textContent = ""; $("document-location").textContent = "";
  $("permission-editor").hidden = true;
  ["documents", "user-list", "members", "permission-list", "read-grants", "write-grants", "token-list", "group-select", "member-select"].forEach(id => $(id).replaceChildren());
  $("page-label").textContent = "";
  $("policy-page-label").textContent = "";
  $("operation-result").textContent = "";
  clearSecret();
}
async function refreshApps() {
  state.apps = await request("/api/capabilities");
  const names = Object.keys(state.apps);
  ["source", "permission-source", "operation-source"].forEach(id => {
    options($(id), names, name => name, name => name);
  });
}
async function loadDocuments() {
  if (!$("source").value) return;
  const result = await call("documents", {app: $("source").value,
    query: $("document-query").value, offset: state.offset, limit: 50});
  const items = rows(result);
  state.total = result.total ?? items.length;
  $("documents").replaceChildren(...items.map(item => {
    const tr = node("tr");
    cell(tr, item.name || item.key, item.uri || item.key);
    cell(tr, item.version);
    cell(tr).append(button("Open", () => openDocument(item)));
    return tr;
  }));
  $("documents-empty").hidden = items.length !== 0;
  $("page-label").textContent = `${state.offset + (items.length ? 1 : 0)}–${state.offset + items.length} of ${state.total}`;
  $("previous-page").disabled = state.offset === 0;
  $("next-page").disabled = state.offset + items.length >= state.total;
}
async function openDocument(summary) {
  const app = $("source").value;
  const result = await call("read", {app, document_key: summary.key});
  state.document = {app, key: summary.key, version: result.version, can_write: summary.can_write};
  $("document-title").textContent = summary.name || result.key;
  $("document-location").textContent = summary.uri || summary.key;
  $("document-content").value = result.text;
  $("document-content").readOnly = !summary.can_write;
  $("document-version").textContent = "Version: " + result.version;
  $("write-document").hidden = !summary.can_write;
  $("document-preview").hidden = false;
}
function clearSecret() {
  $("token-secret").textContent = "";
  $("token-secret-panel").hidden = true;
}
async function loadTokens() {
  if (!state.me.authenticated) return;
  const items = await call("tokens.list");
  $("token-list").replaceChildren(...items.map(item => {
    const tr = node("tr");
    cell(tr, item.name);
    cell(tr, item.scopes.join(", "), item.apps.join(", "));
    cell(tr, item.active ? "Active" : (item.revoked ? "Revoked" : "Expired / inactive"), date(item.expires_at));
    cell(tr).append(button("Revoke", async () => {
      await call("tokens.revoke", {token_id: item.id}); await loadTokens();
    }));
    return tr;
  }));
}
async function loadDirectory() {
  if (!state.me.administrator) return;
  [state.users, state.groups] = await Promise.all([call("users.list"), call("groups.list")]);
  $("user-list").replaceChildren(...state.users.map(user => {
    const tr = node("tr");
    cell(tr, user.username, user.id);
    cell(tr, user.root ? "Root" : (user.administrator ? "Administrator" : "Member"));
    cell(tr, user.enabled ? "Active" : "Disabled");
    const changeState = button(user.enabled ? "Disable" : "Enable", async () => {
      await call("users.enabled", {user_id: user.id, enabled: !user.enabled});
      await refreshIdentity(); await loadDirectory();
    });
    if (user.root && !state.me.root) { changeState.disabled = true; changeState.textContent = "Root protected"; }
    cell(tr).append(changeState);
    return tr;
  }));
  options($("group-select"), state.groups, item => item.id, item => item.name);
  options($("member-select"), state.users, item => item.id, item => item.username);
  await loadMembers();
}
async function loadMembers() {
  if (!$("group-select").value) { $("members").replaceChildren(); return; }
  const group_id = $("group-select").value;
  const items = await call("groups.members", {group_id});
  $("members").replaceChildren(...items.map(user => {
    const item = node("li");
    item.append(node("span", user.username), button("Remove", async () => {
      await call("groups.remove", {group_id, user_id: user.id}); await loadMembers();
    }));
    return item;
  }));
}
async function loadPermissions() {
  if (!$("permission-source").value) return;
  const result = await call("permission_inventory", {app: $("permission-source").value,
    offset: state.policyOffset, limit: 100});
  const items = rows(result);
  state.policyTotal = result.total ?? items.length;
  $("policy-page-label").textContent = `${state.policyOffset + (items.length ? 1 : 0)}–${state.policyOffset + items.length} of ${state.policyTotal}`;
  $("previous-policy-page").disabled = state.policyOffset === 0;
  $("next-policy-page").disabled = state.policyOffset + items.length >= state.policyTotal;
  $("permission-list").replaceChildren(...items.map(item => {
    const tr = node("tr");
    cell(tr, item.name || item.key, item.uri || item.key);
    cell(tr, item.readers.join(", ") || "Denied");
    cell(tr, item.writers.join(", ") || "Denied");
    cell(tr).append(button("Edit policy", () => editPermission(item)));
    return tr;
  }));
}
function grantChoices(container, selected) {
  const grants = [...state.users.map(user => ({value: "user:" + user.id, label: "User · " + user.username})),
    ...state.groups.map(group => ({value: "group:" + group.id, label: "Group · " + group.name}))];
  const known = new Set(grants.map(item => item.value));
  selected.filter(value => value !== "*" && !known.has(value)).forEach(value => {
    grants.push({value, label: "Existing grant · " + value});
  });
  container.replaceChildren(...grants.map(grant => {
    const label = node("label", undefined, "check"), input = node("input");
    input.type = "checkbox"; input.value = grant.value; input.checked = selected.includes(grant.value);
    label.append(input, document.createTextNode(grant.label));
    return label;
  }));
}
async function editPermission(item) {
  await loadDirectory();
  state.policy = {...item, app: $("permission-source").value};
  $("permission-title").textContent = item.name || item.key;
  $("public-read").checked = item.readers.includes("*");
  $("public-write").checked = item.writers.includes("*");
  grantChoices($("read-grants"), item.readers); grantChoices($("write-grants"), item.writers);
  $("permission-editor").hidden = false;
}
async function selectPanel(name) {
  state.activePanel = name;
  clearSecret();
  document.querySelectorAll(".panel").forEach(item => { item.hidden = item.id !== name; });
  document.querySelectorAll(".nav").forEach(item => item.classList.toggle("active", item.dataset.panel === name));
  if (name === "tokens") await loadTokens();
  if (name === "accounts") await loadDirectory();
  if (name === "permissions") await loadPermissions();
}
form("login", async () => {
  clearPrivateState();
  try { const result = await request("/auth/login", {username: $("username").value, password: $("password").value}); state.csrf = result.csrf; }
  finally { $("password").value = ""; }
  await refreshIdentity(); await refreshApps(); await loadDocuments();
});
$("logout").onclick = () => run(async () => {
  clearPrivateState();
  await request("/auth/logout", {}); await refreshIdentity(); await selectPanel("explorer"); await loadDocuments();
});
document.querySelectorAll(".nav").forEach(item => {
  item.onclick = () => run(() => selectPanel(item.dataset.panel), item);
});
$("source").onchange = () => run(async () => { state.offset = 0; $("document-preview").hidden = true; await loadDocuments(); });
form("filter-documents", async () => { state.offset = 0; await loadDocuments(); });
$("refresh-documents").onclick = () => run(loadDocuments);
$("previous-page").onclick = () => run(async () => { state.offset = Math.max(0, state.offset - 50); await loadDocuments(); });
$("next-page").onclick = () => run(async () => { state.offset += 50; await loadDocuments(); });
$("close-preview").onclick = () => { state.document = null; $("document-preview").hidden = true; $("document-content").value = ""; };
$("write-document").onclick = () => run(async () => {
  const item = state.document;
  await call("write", {app: item.app, document_key: item.key, content: $("document-content").value, expected_version: item.version});
  state.document = null; $("document-preview").hidden = true; await loadDocuments();
  notice("Source updated. The new document is queued for publication.");
}, $("write-document"));
form("create-token", async () => {
  const scopes = ["read", "write", "manage"].filter(scope => $("scope-" + scope).checked);
  const result = await call("tokens.create", {name: $("token-name").value, scopes,
    apps: $("token-apps").value.split(",").map(value => value.trim()).filter(Boolean), ttl: Number($("token-days").value) * 86400});
  clearSecret(); $("token-secret").textContent = result.token; $("token-secret-panel").hidden = false;
  await loadTokens();
});
$("dismiss-secret").onclick = clearSecret;
form("change-password", async () => {
  clearPrivateState();
  try { await call("password.change", {password: $("new-password").value}); }
  finally { $("new-password").value = ""; }
  await refreshIdentity(); await selectPanel("explorer"); notice("Password changed. Existing credentials were invalidated.");
});
form("create-user", async () => {
  try { await call("users.create", {username: $("new-username").value, password: $("initial-password").value, administrator: $("new-administrator").checked, root: $("new-root").checked}); }
  finally { $("initial-password").value = ""; }
  $("new-username").value = ""; await loadDirectory();
});
form("create-group", async () => { await call("groups.create", {name: $("group-name").value}); $("group-name").value = ""; await loadDirectory(); });
$("group-select").onchange = () => run(loadMembers);
$("add-member").onclick = () => run(async () => { await call("groups.add", {group_id: $("group-select").value, user_id: $("member-select").value}); await loadMembers(); });
$("refresh-permissions").onclick = () => run(loadPermissions);
$("permission-source").onchange = () => run(async () => { state.policyOffset = 0; $("permission-editor").hidden = true; await loadPermissions(); });
$("previous-policy-page").onclick = () => run(async () => { state.policyOffset = Math.max(0, state.policyOffset - 100); await loadPermissions(); });
$("next-policy-page").onclick = () => run(async () => { state.policyOffset += 100; await loadPermissions(); });
form("permission-editor", async () => {
  const selected = id => [...$(id).querySelectorAll("input:checked")].map(input => input.value);
  const policy = state.policy;
  await call("document_permissions", {app: policy.app, document_key: policy.key,
    expected_revision: policy.permissions_revision,
    readers: $("public-read").checked ? ["*"] : selected("read-grants"),
    writers: $("public-write").checked ? ["*"] : selected("write-grants")});
  $("permission-editor").hidden = true; await loadPermissions();
});
document.querySelectorAll("[data-operation]").forEach(item => {
  item.onclick = () => run(async () => {
    const result = await call(item.dataset.operation, {app: $("operation-source").value});
    $("operation-result").textContent = JSON.stringify(result, null, 2);
  }, item);
});
run(async () => { await refreshIdentity(); await refreshApps(); await loadDocuments(); });
