(function () {
  "use strict";

  var STORAGE_KEY = "airwise.profile";
  var GEO_TIMEOUT_MS = 10000;
  var FALLBACK_CITY = "My location";

  var YES_NO = [["yes", "Yes"], ["no", "No"]];
  var FIELDS = [
    { name: "kids", label: "Children present", type: "bool", options: YES_NO },
    { name: "elderly", label: "Elderly person present", type: "bool", options: YES_NO },
    { name: "respiratory", label: "Respiratory condition present", type: "bool", options: YES_NO },
    { name: "commute", label: "Commute mode", type: "enum", options: [
      ["car", "Car"], ["two_wheeler", "Two-wheeler"], ["bus_metro", "Bus or metro"],
      ["walk_cycle", "Walk or cycle"], ["work_from_home", "Work from home"]] },
    { name: "cooking_fuel", label: "Cooking fuel", type: "enum", options: [
      ["lpg", "LPG"], ["png", "PNG (piped gas)"], ["induction", "Induction"], ["biomass", "Biomass (wood, dung, crop waste)"]] },
    { name: "heating", label: "Heating type", type: "enum", options: [
      ["none", "None"], ["electric", "Electric"], ["biomass_burning", "Burning biomass or coal"]] },
    { name: "has_purifier", label: "Own an air purifier", type: "bool", options: YES_NO },
    { name: "ventilation", label: "Window ventilation habit", type: "enum", options: [
      ["open_often", "Windows open often"], ["sometimes", "Sometimes open"], ["mostly_closed", "Mostly closed"]] }
  ];

  var ERROR_MESSAGES = {
    validation_error: "Some details were not accepted. Please fix the fields listed below.",
    payload_too_large: "The request was too large. Please shorten your input and try again.",
    rate_limited: "Too many requests. Please wait before trying again.",
    city_not_found: "We could not find that city in India. Check the spelling or try a nearby larger city.",
    lookup_unavailable: "The location lookup service is not responding. Please try again in a moment.",
    server_error: "Something went wrong on our side. Please try again later."
  };

  var state = { coords: null, plan: null, reading: null, profile: null };

  // The only element factory in this page. Text is always set via textContent.
  function el(tag, text, cls) {
    var node = document.createElement(tag);
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    if (cls) { node.className = cls; }
    return node;
  }

  function byId(id) { return document.getElementById(id); }
  function clearNode(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }

  // ---------- Form construction ----------
  function buildForm() {
    var host = byId("fields");
    FIELDS.forEach(function (f) {
      var wrap = el("div");
      var label = el("label", f.label);
      label.htmlFor = "f-" + f.name;
      var select = el("select");
      select.id = "f-" + f.name;
      select.name = f.name;
      select.required = true;
      var blank = el("option", "Select...");
      blank.value = "";
      select.appendChild(blank);
      f.options.forEach(function (o) {
        var opt = el("option", o[1]);
        opt.value = o[0];
        select.appendChild(opt);
      });
      wrap.appendChild(label);
      wrap.appendChild(select);
      host.appendChild(wrap);
    });
  }

  function readProfile() {
    var p = { city: byId("city").value.trim() };
    FIELDS.forEach(function (f) {
      var v = byId("f-" + f.name).value;
      if (f.type === "bool") { p[f.name] = v === "yes" ? true : (v === "no" ? false : null); }
      else { p[f.name] = v; }
    });
    return p;
  }

  function fillForm(p) {
    byId("city").value = p.city;
    FIELDS.forEach(function (f) {
      var v = p[f.name];
      byId("f-" + f.name).value = f.type === "bool" ? (v ? "yes" : "no") : v;
    });
  }

  function resetForm() {
    byId("city").value = "";
    FIELDS.forEach(function (f) { byId("f-" + f.name).value = ""; });
  }

  // ---------- Validation (mirrors the server rules) ----------
  function isValidProfile(p) {
    if (!p || typeof p !== "object" || Array.isArray(p)) { return false; }
    var keys = Object.keys(p);
    if (keys.length !== FIELDS.length + 1) { return false; }
    if (typeof p.city !== "string") { return false; }
    var city = p.city.trim();
    if (city.length < 1 || city.length > 100) { return false; }
    return FIELDS.every(function (f) {
      if (!Object.prototype.hasOwnProperty.call(p, f.name)) { return false; }
      var v = p[f.name];
      if (f.type === "bool") { return typeof v === "boolean"; }
      return typeof v === "string" && f.options.some(function (o) { return o[0] === v; });
    });
  }

  function invalidFieldLabels(p) {
    var bad = [];
    var city = typeof p.city === "string" ? p.city.trim() : "";
    if (city.length < 1 || city.length > 100) { bad.push("City"); }
    FIELDS.forEach(function (f) {
      var v = p[f.name];
      var ok = f.type === "bool" ? typeof v === "boolean"
        : (typeof v === "string" && f.options.some(function (o) { return o[0] === v; }));
      if (!ok) { bad.push(f.label); }
    });
    return bad;
  }

  // ---------- localStorage (every access guarded) ----------
  function saveProfile(p) {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(p)); } catch (e) { /* not blocking */ }
  }

  function removeSaved() {
    try { window.localStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }
  }

  function loadSaved() {
    var raw = null;
    try { raw = window.localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
    if (raw === null) { return null; }
    var parsed = null;
    try { parsed = JSON.parse(raw); } catch (e) { parsed = null; }
    if (!isValidProfile(parsed)) { removeSaved(); return null; }
    return parsed;
  }

  // ---------- Status helpers ----------
  function setStatus(node, message, opts) {
    opts = opts || {};
    clearNode(node);
    node.className = "status" + (opts.error ? " error" : "") + (opts.loading ? " loading" : "");
    if (message) { node.appendChild(el("span", message)); }
    if (opts.list && opts.list.length) {
      var ul = el("ul");
      opts.list.forEach(function (item) { ul.appendChild(el("li", item)); });
      node.appendChild(ul);
    }
  }

  // ---------- API ----------
  function describeError(status, body, retryAfter) {
    var err = body && body.error ? body.error : {};
    var code = err.code || (status === 429 ? "rate_limited" : (status === 413 ? "payload_too_large" : "server_error"));
    var message = ERROR_MESSAGES[code] || ERROR_MESSAGES.server_error;
    var list = [];
    if (code === "validation_error" && Array.isArray(err.fields)) {
      list = err.fields.map(function (x) { return String(x); });
    }
    if (code === "rate_limited") {
      var secs = parseInt(retryAfter, 10);
      if (isFinite(secs) && secs > 0) {
        message = "Too many requests. Please try again in " + secs + (secs === 1 ? " second." : " seconds.");
      }
    }
    return { message: message, list: list };
  }

  function callApi(path, options) {
    return fetch(path, options).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (body) {
        if (!res.ok) {
          var d = describeError(res.status, body, res.headers.get("Retry-After"));
          var e = new Error(d.message);
          e.detail = d;
          throw e;
        }
        return body;
      });
    }, function () {
      var e = new Error("Could not reach AirWise. Check your connection and try again.");
      e.detail = { message: e.message, list: [] };
      throw e;
    });
  }

  function postPlan(profile, coords) {
    var payload = { profile: profile };
    if (coords) { payload.latitude = coords.latitude; payload.longitude = coords.longitude; }
    return callApi("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  }

  function publish(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail: detail }));
  }

  // ---------- Generate ----------
  function onGenerate(ev) {
    ev.preventDefault();
    var status = byId("status");
    var btn = byId("generate-btn");
    var profile = readProfile();
    if (state.coords && profile.city === "") {
      profile.city = FALLBACK_CITY;
      byId("city").value = FALLBACK_CITY;
    }
    if (!isValidProfile(profile)) {
      setStatus(status, "Please complete these fields:", { error: true, list: invalidFieldLabels(profile) });
      return;
    }
    btn.disabled = true;
    setStatus(status, "Generating your plan...", { loading: true });
    postPlan(profile, state.coords).then(function (data) {
      saveProfile(profile);
      state.plan = data.plan;
      state.reading = data.reading;
      state.profile = profile;
      setStatus(status, "");
      publish("airwise:plan", data);
    }, function (e) {
      setStatus(status, e.detail.message, { error: true, list: e.detail.list });
    }).then(function () { btn.disabled = false; });
  }

  function onClear() {
    removeSaved();
    resetForm();
    state.coords = null;
    setStatus(byId("status"), "Saved profile cleared.");
    setStatus(byId("geo-status"), "");
  }

  // ---------- Geolocation ----------
  function onUseLocation() {
    var btn = byId("geo-btn");
    var status = byId("geo-status");
    var NO_LOCATION = "We could not get your location. Please enter a city name instead.";
    if (!navigator.geolocation) {
      setStatus(status, NO_LOCATION, { error: true });
      return;
    }
    var settled = false;
    var timer = null;
    btn.disabled = true;
    setStatus(status, "Finding your location...", { loading: true });

    function finish() { settled = true; clearTimeout(timer); btn.disabled = false; }

    timer = setTimeout(function () {
      if (settled) { return; }
      finish();
      setStatus(status, NO_LOCATION, { error: true });
    }, GEO_TIMEOUT_MS);

    navigator.geolocation.getCurrentPosition(function (pos) {
      if (settled) { return; }
      var coords = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
      if (byId("city").value.trim() === "") { byId("city").value = FALLBACK_CITY; }
      setStatus(status, "Looking up air quality for your location...", { loading: true });
      var q = "/api/aqi?lat=" + encodeURIComponent(coords.latitude) + "&lon=" + encodeURIComponent(coords.longitude);
      callApi(q, { method: "GET" }).then(function (reading) {
        state.coords = coords;
        state.reading = reading;
        setStatus(status, "Using your location. Complete the profile and choose Generate plan.");
        publish("airwise:reading", reading);
      }, function (e) {
        setStatus(status, e.detail.message, { error: true, list: e.detail.list });
      }).then(function () { finish(); });
    }, function () {
      if (settled) { return; }
      finish();
      setStatus(status, NO_LOCATION, { error: true });
    }, { timeout: GEO_TIMEOUT_MS });
  }

  // ---------- Result rendering (text only, via el()) ----------
  var GRAP_LABEL = "indicative, not an official declaration";
  var ESTIMATED_NOTICE = "This is an estimated typical winter value, not live data.";
  var FALLBACK_NOTICE = "This plan is rule-based and not AI-personalized.";
  var NO_ACTIONS = "No further actions apply.";
  var SLOTS = [["morning", "Morning"], ["commute", "Commute"], ["midday", "Midday"], ["evening", "Evening"]];

  function pct(n) { return String(Math.round(Number(n) * 10) / 10); }

  function renderAqiCard(reading) {
    var card = el("div", null, "card aqi");
    card.appendChild(el("h2", "Air quality in " + reading.location_name));
    var line = el("p", null, "aqi-line");
    line.appendChild(el("span", reading.aqi, "aqi-value"));
    line.appendChild(el("span", " AQI \u2013 " + reading.band, "aqi-band"));
    card.appendChild(line);
    var grap = el("p", null, "grap");
    var stage = reading.grap_stage === "none" ? "GRAP stage: none" : "GRAP stage: " + reading.grap_stage;
    grap.appendChild(el("span", stage));
    grap.appendChild(el("span", " (" + GRAP_LABEL + ")", "muted"));
    card.appendChild(grap);
    return card;
  }

  function renderItem(item) {
    var li = el("li");
    li.appendChild(el("div", item.text, "item-text"));
    li.appendChild(el("div", "Why it matters: " + item.why_it_matters, "why"));
    return li;
  }

  function renderItemList(title, items) {
    var box = el("div", null, "block");
    box.appendChild(el("h3", title));
    var ul = el("ul");
    items.forEach(function (it) { ul.appendChild(renderItem(it)); });
    box.appendChild(ul);
    return box;
  }

  function renderImpact(rows) {
    var box = el("div", null, "block");
    box.appendChild(el("h3", "Impact table"));
    if (!rows.length) {
      box.appendChild(el("p", NO_ACTIONS, "no-actions"));
      return box;
    }
    var wrap = el("div", null, "table-wrap");
    var table = el("table");
    var head = el("tr");
    ["Action", "Exposure reduction (approx.)", "CO2 saved (approx.)", "Basis", "Source"].forEach(function (h) {
      head.appendChild(el("th", h));
    });
    var thead = el("thead");
    thead.appendChild(head);
    table.appendChild(thead);
    var tbody = el("tbody");
    rows.forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", r.action));
      tr.appendChild(el("td", "\u2248 " + pct(r.exposure_reduction_pct) + "%"));
      tr.appendChild(el("td", "\u2248 " + pct(r.co2_kg_per_day) + " kg/day"));
      tr.appendChild(el("td", r.basis));
      tr.appendChild(el("td", r.source_note));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    box.appendChild(wrap);
    return box;
  }

  function renderResult(reading, plan) {
    var host = byId("result");
    clearNode(host);
    if (reading) {
      host.appendChild(renderAqiCard(reading));
      if (reading.source === "estimated" || (plan && plan.estimated)) {
        host.appendChild(el("div", ESTIMATED_NOTICE, "notice"));
      }
    }
    if (plan) {
      if (plan.fallback) { host.appendChild(el("div", FALLBACK_NOTICE, "notice")); }
      var score = el("div", null, "card score");
      score.appendChild(el("h2", "Exposure score"));
      score.appendChild(el("p", "\u2248 " + pct(plan.exposure_score) + "% estimated exposure reduction (approximate)"));
      host.appendChild(score);
      var routine = el("div", null, "card");
      routine.appendChild(el("h2", "Daily routine"));
      SLOTS.forEach(function (s) { routine.appendChild(renderItemList(s[1], plan.routine[s[0]])); });
      host.appendChild(routine);
      var more = el("div", null, "card");
      more.appendChild(renderItemList("Indoor hacks", plan.indoor_hacks));
      more.appendChild(renderItemList("Sustainable swaps", plan.swaps));
      if (plan.vulnerable_note) {
        var vn = el("div", null, "block");
        vn.appendChild(el("h3", "Vulnerable members"));
        vn.appendChild(el("p", plan.vulnerable_note));
        more.appendChild(vn);
      }
      host.appendChild(more);
      var impact = el("div", null, "card");
      impact.appendChild(renderImpact(plan.impact_table));
      host.appendChild(impact);
    }
    host.hidden = false;
  }

  document.addEventListener("airwise:plan", function (ev) {
    renderResult(ev.detail.reading, ev.detail.plan);
  });
  document.addEventListener("airwise:reading", function (ev) {
    if (!state.plan) { renderResult(ev.detail, null); }
  });

  // ---------- Chat ----------
  var STARTERS = [
    "What should I do first today?",
    "Which action reduces my exposure the most?",
    "How can I keep my home air cleaner?",
    "Is it a good day to go outside?"
  ];
  var MAX_HISTORY = 10;
  var MAX_MESSAGE = 500;
  var CHAT_FAILURE = "Sorry, I could not answer that right now. Please try again.";

  // Chat state lives in JS variables only (plan, reading, profile are in `state`).
  var history = [];
  var chatBusy = false;

  function addBubble(role, text, failed) {
    var list = byId("chat-history");
    var li = el("li", text, "bubble " + role + (failed ? " failed" : ""));
    list.appendChild(li);
    list.scrollTop = list.scrollHeight;
  }

  function sendChat(message) {
    message = String(message).trim();
    if (chatBusy || !state.plan || message === "" || message.length > MAX_MESSAGE) { return; }
    var input = byId("chat-input");
    var send = byId("chat-send");
    byId("starters").hidden = true;
    addBubble("user", message, false);
    input.value = "";
    chatBusy = true;
    send.disabled = true;
    var payload = {
      message: message,
      history: history.slice(-MAX_HISTORY),
      plan: state.plan,
      reading: state.reading,
      profile: state.profile
    };
    callApi("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (data) {
      var failed = !data || data.failed === true || typeof data.reply !== "string" || data.reply === "";
      var text = failed ? ((data && data.reply) || CHAT_FAILURE) : data.reply;
      addBubble("assistant", text, failed);
      history.push({ role: "user", content: message });
      history.push({ role: "assistant", content: text });
      history = history.slice(-MAX_HISTORY);
    }, function (e) {
      addBubble("assistant", e.detail && e.detail.message ? e.detail.message : CHAT_FAILURE, true);
    }).then(function () {
      chatBusy = false;
      send.disabled = false;
    });
  }

  function buildChat() {
    var host = byId("starters");
    STARTERS.forEach(function (q) {
      var b = el("button", q, "secondary");
      b.type = "button";
      b.addEventListener("click", function () { sendChat(q); });
      host.appendChild(b);
    });
    byId("chat-form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      sendChat(byId("chat-input").value);
    });
  }

  document.addEventListener("airwise:plan", function () {
    history = [];
    clearNode(byId("chat-history"));
    byId("starters").hidden = false;
    byId("chat").hidden = false;
  });

  // ---------- Init ----------
  function init() {
    buildForm();
    buildChat();
    var saved = loadSaved();
    if (saved) { fillForm(saved); }
    byId("profile-form").addEventListener("submit", onGenerate);
    byId("clear-btn").addEventListener("click", onClear);
    byId("geo-btn").addEventListener("click", onUseLocation);
    byId("city").addEventListener("input", function () {
      if (byId("city").value.trim() !== FALLBACK_CITY) { state.coords = null; }
    });
  }

  window.AirWise = { el: el, state: state, isValidProfile: isValidProfile, setStatus: setStatus };
  init();
})();
