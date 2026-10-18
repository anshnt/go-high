/* go-high chat widget: <script src="https://HOST/widget.js" data-key="WIDGET KEY" async></script>
   No framework. The bubble is drawn at once; the chat panel is built on the first click. The visitor token lives in this
   page's localStorage (every access is wrapped: private windows and blocked storage must not break the page). */
(function () {
  "use strict";
  var script = document.currentScript;
  var key = script && script.getAttribute("data-key");
  if (!key || window["gohigh-chat-" + key]) return;
  window["gohigh-chat-" + key] = 1;
  var api = new URL(script.src).origin + "/api/public/chat/" + encodeURIComponent(key);
  var slot = "gohigh-chat-" + key;
  var state = { token: null, seq: 0, open: false, timer: null, asked: false, busy: false };
  var el = {};

  function read() { try { return JSON.parse(localStorage.getItem(slot) || "{}") || {}; } catch (e) { return {}; } }
  function write(v) { try { localStorage.setItem(slot, JSON.stringify(v)); } catch (e) { /* not persisted */ } }
  function remember() { write({ token: state.token, asked: state.asked }); }

  function call(method, path, body, retry) {
    var headers = { "Content-Type": "application/json" };
    if (state.token) headers.Authorization = "Bearer " + state.token;
    return fetch(api + path, { method: method, headers: headers, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        if (r.status === 401 && retry !== false) { state.token = null; state.seq = 0; clear(); return session().then(function () { return call(method, path, body, false); }); }
        if (!r.ok) throw new Error(r.status);
        return r.json();
      });
  }

  function session() {
    return call("POST", "/session", null, false).then(function (s) {
      state.token = s.token; remember();
      if (s.greeting && !state.seq) add("agent", s.greeting, 0);
      if (s.title) el.title.textContent = s.title;
    });
  }

  function clear() { if (el.list) el.list.textContent = ""; }

  function add(from, text, seq) {
    var m = document.createElement("div");
    m.className = "gh-m gh-" + from;
    m.textContent = text;
    el.list.appendChild(m);
    el.list.scrollTop = el.list.scrollHeight;
    if (seq) state.seq = Math.max(state.seq, seq);
  }

  function poll() {
    clearTimeout(state.timer);
    if (!state.open) return;
    var next = function () { state.timer = setTimeout(poll, 3000); };
    if (!state.token) return next();
    call("GET", "/messages?after=" + state.seq).then(function (r) {
      r.data.forEach(function (m) { add(m.from, m.body, m.seq); });
    }).catch(function () { /* offline or rate limited: try again later */ }).then(next);
  }

  function send(e) {
    e.preventDefault();
    var text = el.input.value.trim();
    if (!text || state.busy) return;
    state.busy = true;
    var id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : undefined;
    call("POST", "/messages", { body: text, client_id: id, website: el.trap.value }).then(function () {
      el.input.value = "";
      if (!state.asked) { state.asked = true; remember(); el.ask.hidden = false; }
      poll();
    }).catch(function () { el.note.textContent = "Not sent, please try again."; })
      .then(function () { state.busy = false; });
  }

  function identify(e) {
    e.preventDefault();
    var v = el.ask.elements;
    call("POST", "/identify", { name: v.name.value, email: v.email.value, phone: v.phone.value, website: v.website.value })
      .then(function () { el.ask.hidden = true; el.note.textContent = "Thanks, we will reply here or by email."; })
      .catch(function () { el.note.textContent = "That did not work, check the email or phone number."; });
  }

  function field(name, label, type) {
    return '<input name="' + name + '" type="' + type + '" placeholder="' + label + '" aria-label="' + label + '" autocomplete="' + name + '">';
  }

  function build() {
    var st = document.createElement("style");
    st.textContent = "#gh-chat{position:fixed;right:16px;bottom:16px;z-index:2147483000;font:14px/1.4 system-ui,sans-serif;color:#1a1a1a}" +
      "#gh-chat *{box-sizing:border-box}#gh-chat button{font:inherit;cursor:pointer}" +
      "#gh-bubble{width:56px;height:56px;border-radius:28px;border:0;background:var(--gh,#2563eb);color:#fff;font-size:24px;box-shadow:0 4px 14px rgba(0,0,0,.25)}" +
      "#gh-panel{display:none;width:340px;max-width:calc(100vw - 32px);height:460px;max-height:calc(100vh - 100px);flex-direction:column;background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.3);overflow:hidden;margin-bottom:12px}" +
      "#gh-chat.gh-open #gh-panel{display:flex}#gh-chat.gh-open #gh-bubble{display:none}" +
      "#gh-head{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;background:var(--gh,#2563eb);color:#fff;font-weight:600}" +
      "#gh-head button{background:none;border:0;color:#fff;font-size:20px}" +
      "#gh-list{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:8px;background:#f6f7f9}" +
      ".gh-m{max-width:80%;padding:8px 11px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere}" +
      ".gh-visitor{align-self:flex-end;background:var(--gh,#2563eb);color:#fff}.gh-agent{align-self:flex-start;background:#fff;border:1px solid #e2e4e8}" +
      "#gh-note{padding:0 12px;min-height:18px;font-size:12px;color:#555}" +
      "#gh-ask{display:flex;flex-direction:column;gap:6px;padding:8px 12px;border-top:1px solid #e2e4e8}#gh-ask[hidden]{display:none}" +
      "#gh-chat input,#gh-chat textarea{font:inherit;padding:7px 9px;border:1px solid #c9ccd2;border-radius:8px;width:100%}" +
      "#gh-chat input[name=website]{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}" +
      "#gh-form{display:flex;gap:6px;padding:10px 12px;border-top:1px solid #e2e4e8}#gh-form textarea{resize:none;height:38px}" +
      "#gh-form button,#gh-ask button{border:0;border-radius:8px;background:var(--gh,#2563eb);color:#fff;padding:0 14px;min-height:36px}";
    document.head.appendChild(st);
    var color = script.getAttribute("data-color");
    var root = document.createElement("div");
    root.id = "gh-chat";
    if (color && /^#[0-9a-fA-F]{3,8}$/.test(color)) root.style.setProperty("--gh", color);
    root.innerHTML = '<div id="gh-panel" role="dialog" aria-label="Chat"><div id="gh-head"><span id="gh-title">Chat</span>' +
      '<button type="button" id="gh-close" aria-label="Close chat">×</button></div>' +
      '<div id="gh-list" role="log" aria-live="polite"></div><div id="gh-note" role="status"></div>' +
      '<form id="gh-ask" hidden><div>Leave your details so we can reach you:</div>' + field("name", "Your name", "text") +
      field("email", "Email", "email") + field("phone", "Phone", "tel") + field("website", "Website", "text") +
      '<button type="submit">Save</button></form>' +
      '<form id="gh-form"><textarea id="gh-input" placeholder="Write a message" aria-label="Message" maxlength="2000"></textarea>' +
      '<input name="website" tabindex="-1" autocomplete="off" aria-hidden="true" id="gh-trap"><button type="submit">Send</button></form></div>' +
      '<button type="button" id="gh-bubble" aria-label="Open chat">✉</button>';
    document.body.appendChild(root);
    el.root = root; el.list = root.querySelector("#gh-list"); el.input = root.querySelector("#gh-input");
    el.title = root.querySelector("#gh-title"); el.note = root.querySelector("#gh-note"); el.ask = root.querySelector("#gh-ask");
    el.trap = root.querySelector("#gh-trap");
    root.querySelector("#gh-form").addEventListener("submit", send);
    el.ask.addEventListener("submit", identify);
    el.input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) send(e); });
    root.querySelector("#gh-close").addEventListener("click", toggle);
    root.querySelector("#gh-bubble").addEventListener("click", toggle);
  }

  function toggle() {
    if (!el.root) {
      build();
      var saved = read();
      state.token = saved.token || null; state.asked = !!saved.asked;
      var ready = state.token ? Promise.resolve() : session();
      ready.then(function () { return call("GET", "/messages?after=0"); }).then(function (r) {
        r.data.forEach(function (m) { add(m.from, m.body, m.seq); });
        if (state.asked) el.ask.hidden = true;
      }).catch(function () { el.note.textContent = "Chat is not available right now."; });
    }
    state.open = !state.open;
    el.root.classList.toggle("gh-open", state.open);
    if (state.open) { el.input.focus(); poll(); }
  }

  function boot() {
    var bubble = document.createElement("button");
    bubble.type = "button"; bubble.setAttribute("aria-label", "Open chat"); bubble.id = "gh-first";
    bubble.style.cssText = "position:fixed;right:16px;bottom:16px;width:56px;height:56px;border-radius:28px;border:0;background:" +
      (/^#[0-9a-fA-F]{3,8}$/.test(script.getAttribute("data-color") || "") ? script.getAttribute("data-color") : "#2563eb") +
      ";color:#fff;font-size:24px;cursor:pointer;z-index:2147483000;box-shadow:0 4px 14px rgba(0,0,0,.25)";
    bubble.textContent = "✉";
    bubble.addEventListener("click", function () { bubble.remove(); toggle(); });
    document.body.appendChild(bubble);
  }

  if (document.body) boot(); else document.addEventListener("DOMContentLoaded", boot);
})();
