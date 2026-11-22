"use strict";

let currentState = null;

function setStatus(text) {
  document.getElementById("action-status").textContent = text;
}

function renderHealth(health) {
  const pill = document.getElementById("health-pill");
  if (health && health.ok) {
    pill.textContent = `Jev ready (${health.model || "jev-latest"} · ${health.cacheEntries ?? 0} cached)`;
    pill.className = "pill pill-ok";
  } else {
    pill.textContent = `Router offline (${health?.error || "unreachable"})`;
    pill.className = "pill pill-err";
  }
}

function renderPinSection(state) {
  const section = document.getElementById("pin-section");
  const host = state.activeTab?.host;
  if (!host || !state.spaces.length) {
    section.hidden = true;
    return;
  }

  section.hidden = false;
  document.getElementById("active-host").textContent = host;

  const select = document.getElementById("pin-space-select");
  select.textContent = "";

  const autoOpt = document.createElement("option");
  autoOpt.value = "";
  autoOpt.textContent = "Auto (use Jev)";
  select.appendChild(autoOpt);

  for (const space of state.spaces) {
    const opt = document.createElement("option");
    opt.value = space.name;
    opt.textContent = `Always → ${space.name}`;
    select.appendChild(opt);
  }

  select.value = state.settings.domainOverrides?.[host] || "";
}

function renderHistory(items) {
  const list = document.getElementById("history-list");
  list.textContent = "";

  if (!items || !items.length) {
    const empty = document.createElement("li");
    empty.className = "history-item";
    empty.textContent = "No routing decisions yet.";
    list.appendChild(empty);
    return;
  }

  for (const item of items.slice(0, 12)) {
    const li = document.createElement("li");
    li.className = "history-item";

    const top = document.createElement("div");
    top.className = "history-top";

    const title = document.createElement("span");
    title.className = "history-title";
    title.textContent = item.title || item.host || item.url;
    title.title = item.url || "";

    const action = document.createElement("span");
    if (item.action === "move") {
      action.className = "badge-move";
      action.textContent = `→ ${item.targetSpaceName}`;
    } else {
      action.className = "badge-stay";
      action.textContent = item.targetSpaceName
        ? `stay (${item.targetSpaceName})`
        : "stay";
    }

    top.appendChild(title);
    top.appendChild(action);

    const meta = document.createElement("div");
    meta.className = "history-meta";
    const confPct = Math.round((item.confidence || 0) * 100);
    const left = document.createElement("span");
    left.textContent = `${item.source || "?"} · ${item.reason || ""}`;
    const right = document.createElement("span");
    right.textContent = `${confPct}% · ${Math.round(item.latencyMs || 0)}ms`;

    meta.appendChild(left);
    meta.appendChild(right);

    li.appendChild(top);
    li.appendChild(meta);
    list.appendChild(li);
  }
}

function renderCriteria(state) {
  document.getElementById("input-min-confidence").value = String(
    state.settings.minConfidence ?? 0.65
  );
  document.getElementById("input-min-should-move").value = String(
    state.settings.minShouldMove ?? 0.65
  );

  const container = document.getElementById("criteria-container");
  container.textContent = "";
  const defaults = state.health?.defaultCriteria || {};

  for (const space of state.spaces) {
    const wrapper = document.createElement("label");
    wrapper.className = "criteria-item";

    const label = document.createElement("span");
    label.textContent = space.name;

    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.dataset.spaceName = space.name;
    textarea.placeholder =
      defaults[space.name] || `Tabs belonging to ${space.name}`;
    textarea.value = state.settings.customCriteria?.[space.name] || "";

    wrapper.appendChild(label);
    wrapper.appendChild(textarea);
    container.appendChild(wrapper);
  }
}

async function refresh() {
  currentState = await browser.runtime.sendMessage({ type: "getState" });
  document.getElementById("toggle-enabled").checked = Boolean(
    currentState.settings.enabled
  );
  document.getElementById("toggle-follow").checked = Boolean(
    currentState.settings.followActiveTab
  );
  renderHealth(currentState.health);
  renderPinSection(currentState);
  renderHistory(currentState.recentDecisions);
  renderCriteria(currentState);
}

document
  .getElementById("toggle-enabled")
  .addEventListener("change", async event => {
    await browser.runtime.sendMessage({
      type: "updateSettings",
      patch: { enabled: event.target.checked },
    });
    setStatus(event.target.checked ? "Auto-routing enabled." : "Auto-routing paused.");
  });

document
  .getElementById("toggle-follow")
  .addEventListener("change", async event => {
    await browser.runtime.sendMessage({
      type: "updateSettings",
      patch: { followActiveTab: event.target.checked },
    });
  });

document.getElementById("btn-route-now").addEventListener("click", async () => {
  setStatus("Routing current tab with Jev…");
  const res = await browser.runtime.sendMessage({ type: "routeActiveTab" });
  if (res?.action === "move") {
    setStatus(
      `Moved to ${res.targetSpaceName} (${Math.round((res.confidence || 0) * 100)}%, ${Math.round(res.latencyMs || 0)}ms).`
    );
  } else {
    setStatus(
      `Stayed (${res?.reason || "unchanged"}${res?.targetSpaceName ? `, top: ${res.targetSpaceName}` : ""}).`
    );
  }
  await refresh();
});

document
  .getElementById("btn-clear-cache")
  .addEventListener("click", async () => {
    const res = await browser.runtime.sendMessage({ type: "clearServerCache" });
    setStatus(
      res?.ok ? `Cleared ${res.cleared ?? 0} cached entries.` : "Failed to clear cache."
    );
    await refresh();
  });

document.getElementById("btn-pin-host").addEventListener("click", async () => {
  const host = currentState?.activeTab?.host;
  if (!host) {
    return;
  }
  const value = document.getElementById("pin-space-select").value;
  const overrides = { ...(currentState.settings.domainOverrides || {}) };
  if (value) {
    overrides[host] = value;
  } else {
    delete overrides[host];
  }
  await browser.runtime.sendMessage({
    type: "updateSettings",
    patch: { domainOverrides: overrides },
  });
  setStatus(value ? `Pinned ${host} → ${value}.` : `Cleared pin for ${host}.`);
  await refresh();
});

document
  .getElementById("btn-clear-history")
  .addEventListener("click", async () => {
    await browser.runtime.sendMessage({ type: "clearHistory" });
    await refresh();
  });

document
  .getElementById("btn-save-criteria")
  .addEventListener("click", async () => {
    const customCriteria = {};
    for (const el of document.querySelectorAll("textarea[data-space-name]")) {
      const val = el.value.trim();
      if (val) {
        customCriteria[el.dataset.spaceName] = val;
      }
    }
    const minConfidence = parseFloat(
      document.getElementById("input-min-confidence").value
    );
    const minShouldMove = parseFloat(
      document.getElementById("input-min-should-move").value
    );
    await browser.runtime.sendMessage({
      type: "updateSettings",
      patch: {
        customCriteria,
        minConfidence: Number.isFinite(minConfidence) ? minConfidence : 0.65,
        minShouldMove: Number.isFinite(minShouldMove) ? minShouldMove : 0.65,
      },
    });
    setStatus("Saved Space criteria and thresholds.");
    await refresh();
  });

refresh();
