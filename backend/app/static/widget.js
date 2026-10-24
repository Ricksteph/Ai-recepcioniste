/**
 * AI Receptionist — widget de chat embarquable (§15).
 * Usage : <script src="https://VOTRE-API/widget.js" data-slug="mon-entreprise" async></script>
 */
(function () {
  "use strict";
  var script = document.currentScript || document.querySelector("script[data-slug]");
  if (!script) return;
  var SLUG = script.getAttribute("data-slug");
  var API = (script.getAttribute("data-api") || script.src.replace(/\/widget\.js.*$/, ""));
  var STORAGE_KEY = "air_visitor_" + SLUG;
  var visitorId = localStorage.getItem(STORAGE_KEY);
  if (!visitorId) {
    visitorId = Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem(STORAGE_KEY, visitorId);
  }
  var conversationId = null;
  var open = false;

  var css = document.createElement("style");
  css.textContent =
    "#air-root{position:fixed;bottom:20px;right:20px;z-index:999999;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}" +
    "#air-bubble{width:58px;height:58px;border-radius:50%;background:#2563eb;color:#fff;border:none;font-size:26px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.25)}" +
    "#air-panel{display:none;position:fixed;bottom:92px;right:20px;width:360px;max-width:92vw;height:520px;max-height:75vh;background:#fff;border-radius:16px;box-shadow:0 16px 48px rgba(0,0,0,.28);overflow:hidden;flex-direction:column}" +
    "#air-panel.open{display:flex}" +
    "#air-header{background:#2563eb;color:#fff;padding:14px 16px;font-weight:600;font-size:15px}" +
    "#air-header small{display:block;font-weight:400;opacity:.85;font-size:12px;margin-top:2px}" +
    "#air-msgs{flex:1;overflow-y:auto;padding:14px;background:#f8fafc;display:flex;flex-direction:column;gap:8px}" +
    ".air-msg{max-width:85%;padding:9px 12px;border-radius:12px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-break:break-word}" +
    ".air-user{align-self:flex-end;background:#2563eb;color:#fff;border-bottom-right-radius:4px}" +
    ".air-bot{align-self:flex-start;background:#e2e8f0;color:#0f172a;border-bottom-left-radius:4px}" +
    ".air-typing{align-self:flex-start;color:#64748b;font-size:12px;padding:4px 8px}" +
    ".air-actions{display:flex;gap:6px;padding:8px 12px;background:#f8fafc;flex-wrap:wrap}" +
    ".air-chip{border:1px solid #cbd5e1;background:#fff;border-radius:999px;padding:4px 10px;font-size:12px;cursor:pointer;color:#334155}" +
    "#air-form{display:flex;border-top:1px solid #e2e8f0;background:#fff}" +
    "#air-input{flex:1;border:none;padding:12px 14px;font-size:14px;outline:none}" +
    "#air-send{border:none;background:none;color:#2563eb;font-weight:600;padding:0 16px;cursor:pointer}";
  document.head.appendChild(css);

  var root = document.createElement("div");
  root.id = "air-root";
  root.innerHTML =
    '<div id="air-panel">' +
    '<div id="air-header"><span id="air-title">Assistant</span><small id="air-sub">Je réponds en quelques instants</small></div>' +
    '<div id="air-msgs"></div>' +
    '<div class="air-actions" id="air-chips" style="display:none"></div>' +
    '<form id="air-form"><input id="air-input" placeholder="Écrivez votre message…" autocomplete="off" maxlength="2000"/><button id="air-send" type="submit">Envoyer</button></form>' +
    "</div>" +
    '<button id="air-bubble" title="Ouvrir le chat">💬</button>';
  document.body.appendChild(root);

  var msgs = root.querySelector("#air-msgs");
  var panel = root.querySelector("#air-panel");
  var form = root.querySelector("#air-form");
  var input = root.querySelector("#air-input");
  var chips = root.querySelector("#air-chips");

  function addMsg(text, who) {
    var el = document.createElement("div");
    el.className = "air-msg air-" + who;
    el.textContent = text;
    msgs.appendChild(el);
    msgs.scrollTop = msgs.scrollHeight;
    return el;
  }

  function setChips(list) {
    if (!list || !list.length) { chips.style.display = "none"; chips.innerHTML = ""; return; }
    chips.style.display = "flex";
    chips.innerHTML = "";
    list.forEach(function (c) {
      var b = document.createElement("button");
      b.className = "air-chip";
      b.type = "button";
      b.textContent = c;
      b.onclick = function () { send(c); };
      chips.appendChild(b);
    });
  }

  function send(text) {
    if (!text || !text.trim()) return;
    addMsg(text, "user");
    input.value = "";
    setChips([]);
    var typing = addMsg("…", "typing");
    fetch(API + "/public/" + SLUG + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation_id: conversationId, visitor_id: visitorId }),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        typing.remove();
        if (!res.ok) {
          addMsg(res.d && res.d.detail ? String(res.d.detail) : "Une erreur est survenue. Réessayez.", "bot");
          return;
        }
        conversationId = res.d.conversation_id;
        addMsg(res.d.reply, "bot");
        if (res.d.handoff) {
          root.querySelector("#air-sub").textContent = "Un conseiller prend le relais";
          setChips([]);
        } else {
          var follow = [];
          var lastAction = (res.d.actions || []).filter(function (a) { return a.tool === "check_availability" && a.status === "success"; })[0];
          if (lastAction && lastAction.result && lastAction.result.slots) {
            follow = lastAction.result.slots.slice(0, 4).map(function (s) {
              return s.starts_at.slice(0, 10) + " à " + s.starts_at.slice(11, 16);
            });
          }
          setChips(follow);
        }
      })
      .catch(function () { typing.remove(); addMsg("Connexion impossible au serveur.", "bot"); });
  }

  form.onsubmit = function (e) { e.preventDefault(); send(input.value); };
  root.querySelector("#air-bubble").onclick = function () {
    open = !open;
    panel.classList.toggle("open", open);
    if (open && !msgs.children.length) {
      fetch(API + "/public/" + SLUG + "/widget")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (cfg) {
          if (!cfg) return;
          root.querySelector("#air-title").textContent = cfg.agent_name + " — " + cfg.company;
          if (cfg.greeting) addMsg(cfg.greeting, "bot");
        })
        .catch(function () {});
      input.focus();
    }
  };
})();
