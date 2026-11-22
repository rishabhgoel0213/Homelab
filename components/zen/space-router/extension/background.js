"use strict";

const ROUTER_BASE_URL = "https://zen-router.internal.therealrishabh.com";
const STARTUP_GRACE_MS = 4000;
const TITLE_DEBOUNCE_MS = 300;
const REQUEST_TIMEOUT_MS = 2500;
const MAX_HISTORY_ENTRIES = 25;

const DEFAULT_SETTINGS = {
  enabled: true,
  followActiveTab: true,
  minConfidence: 0.65,
  minShouldMove: 0.65,
  customCriteria: {},
  domainOverrides: {},
};

const extensionStartedAt = Date.now();
const pendingTabs = new Map();
const inFlightTabs = new Set();

let settings = { ...DEFAULT_SETTINGS };
let recentDecisions = [];

async function loadState() {
  try {
    const stored = await browser.storage.local.get([
      "settings",
      "recentDecisions",
    ]);
    if (stored.settings && typeof stored.settings === "object") {
      settings = {
        ...DEFAULT_SETTINGS,
        ...stored.settings,
        customCriteria: {
          ...(stored.settings.customCriteria || {}),
        },
        domainOverrides: {
          ...(stored.settings.domainOverrides || {}),
        },
      };
    }
    if (Array.isArray(stored.recentDecisions)) {
      recentDecisions = stored.recentDecisions.slice(0, MAX_HISTORY_ENTRIES);
    }
  } catch (err) {
    console.error("[ZenSpaceRouter] Failed to load state:", err);
  }
  updateBadge();
}

function updateBadge() {
  if (!settings.enabled) {
    browser.browserAction.setBadgeText({ text: "OFF" });
    browser.browserAction.setBadgeBackgroundColor({ color: "#6b7280" });
  } else {
    browser.browserAction.setBadgeText({ text: "" });
  }
}

async function saveSettings(patch) {
  settings = {
    ...settings,
    ...patch,
    customCriteria:
      patch.customCriteria !== undefined
        ? { ...patch.customCriteria }
        : settings.customCriteria,
    domainOverrides:
      patch.domainOverrides !== undefined
        ? { ...patch.domainOverrides }
        : settings.domainOverrides,
  };
  await browser.storage.local.set({ settings });
  updateBadge();
  return settings;
}

function recordDecision(entry) {
  recentDecisions.unshift({
    timestamp: Date.now(),
    ...entry,
  });
  if (recentDecisions.length > MAX_HISTORY_ENTRIES) {
    recentDecisions = recentDecisions.slice(0, MAX_HISTORY_ENTRIES);
  }
  browser.storage.local
    .set({ recentDecisions })
    .catch(err => console.error("[ZenSpaceRouter] Failed to save log:", err));
}

function normalizeHost(urlString) {
  try {
    const parsed = new URL(urlString);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    let host = parsed.hostname.toLowerCase();
    if (host.startsWith("www.")) {
      host = host.slice(4);
    }
    return host || null;
  } catch (_err) {
    return null;
  }
}

function isInformativeTitle(title, urlString) {
  if (!title || typeof title !== "string") {
    return false;
  }
  const trimmed = title.trim();
  if (!trimmed || trimmed === "New Tab" || trimmed === "Connecting…") {
    return false;
  }
  const strippedUrl = urlString.replace(/^https?:\/\//i, "").replace(/\/$/, "");
  if (trimmed === urlString || trimmed === strippedUrl) {
    return false;
  }
  return true;
}

function findDomainOverride(host) {
  const overrides = settings.domainOverrides || {};
  if (overrides[host]) {
    return overrides[host];
  }
  const parts = host.split(".");
  for (let i = 1; i < parts.length - 1; i++) {
    const suffix = parts.slice(i).join(".");
    if (overrides[suffix]) {
      return overrides[suffix];
    }
  }
  return null;
}

async function fetchRouteDecision(payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const resp = await fetch(`${ROUTER_BASE_URL}/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

async function fetchHealth() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1500);
  try {
    const resp = await fetch(`${ROUTER_BASE_URL}/health`, {
      method: "GET",
      signal: controller.signal,
    });
    if (!resp.ok) {
      return { ok: false, error: `HTTP ${resp.status}` };
    }
    return await resp.json();
  } catch (err) {
    return { ok: false, error: err?.name || "unreachable" };
  } finally {
    clearTimeout(timer);
  }
}

async function routeTab(tabId, { manual = false, openerUrl = "" } = {}) {
  if (inFlightTabs.has(tabId)) {
    return { action: "stay", reason: "in_flight" };
  }
  inFlightTabs.add(tabId);

  try {
    const tab = await browser.tabs.get(tabId);
    if (!tab || !tab.url) {
      return { action: "stay", reason: "missing_tab" };
    }

    const host = normalizeHost(tab.url);
    if (!host) {
      return { action: "stay", reason: "non_http_scheme" };
    }

    const tabCtx = await browser.zenSpaces.getTabContext(tabId, tab.url);
    if (!tabCtx || !tabCtx.found) {
      return { action: "stay", reason: "tab_gone" };
    }
    if (
      !manual &&
      (tabCtx.isPinned ||
        tabCtx.isEssential ||
        tabCtx.isEmpty ||
        tabCtx.isGlance ||
        tabCtx.isSplit ||
        tabCtx.hasManualZenRoute)
    ) {
      return { action: "stay", reason: "skipped_special_or_manual_route" };
    }

    const spaces = await browser.zenSpaces.getSpaces(tab.windowId);
    if (!Array.isArray(spaces) || spaces.length < 2) {
      return { action: "stay", reason: "insufficient_spaces" };
    }

    const currentSpace = spaces.find(s => s.uuid === tabCtx.workspaceId);
    const currentSpaceName = currentSpace?.name || "";

    // Fast path: explicit user domain override.
    const overrideSpaceName = findDomainOverride(host);
    if (overrideSpaceName) {
      const targetSpace = spaces.find(s => s.name === overrideSpaceName);
      if (targetSpace) {
        if (targetSpace.uuid === tabCtx.workspaceId) {
          const result = {
            action: "stay",
            reason: "already_in_space",
            source: "override",
            targetSpaceId: targetSpace.uuid,
            targetSpaceName: targetSpace.name,
            confidence: 1,
            shouldMove: 1,
            latencyMs: 0,
          };
          recordDecision({
            url: tab.url,
            host,
            title: tab.title || host,
            fromSpace: currentSpaceName,
            ...result,
          });
          return result;
        }

        const moveRes = await browser.zenSpaces.moveTabToSpace(
          tabId,
          targetSpace.uuid,
          settings.followActiveTab
        );
        const result = {
          action: moveRes?.moved ? "move" : "stay",
          reason: moveRes?.moved ? "override_routed" : moveRes?.reason || "noop",
          source: "override",
          targetSpaceId: targetSpace.uuid,
          targetSpaceName: targetSpace.name,
          confidence: 1,
          shouldMove: 1,
          latencyMs: 0,
        };
        recordDecision({
          url: tab.url,
          host,
          title: tab.title || host,
          fromSpace: currentSpaceName,
          ...result,
        });
        return result;
      }
    }

    let decision;
    try {
      decision = await fetchRouteDecision({
        url: tab.url,
        title: tab.title || "",
        openerUrl,
        currentSpaceId: tabCtx.workspaceId,
        currentSpaceName,
        spaces: spaces.map(s => ({ uuid: s.uuid, name: s.name })),
        customCriteria: settings.customCriteria,
        minConfidence: settings.minConfidence,
        minShouldMove: settings.minShouldMove,
        bypassCache: manual,
      });
    } catch (err) {
      const errorResult = {
        action: "stay",
        reason: "router_unreachable",
        source: "error",
        targetSpaceId: null,
        targetSpaceName: null,
        confidence: 0,
        shouldMove: 0,
        latencyMs: 0,
        error: err?.name || "fetch_error",
      };
      recordDecision({
        url: tab.url,
        host,
        title: tab.title || host,
        fromSpace: currentSpaceName,
        ...errorResult,
      });
      return errorResult;
    }

    if (decision.action === "move" && decision.targetSpaceId) {
      const moveRes = await browser.zenSpaces.moveTabToSpace(
        tabId,
        decision.targetSpaceId,
        settings.followActiveTab
      );
      if (!moveRes?.moved) {
        decision = {
          ...decision,
          action: "stay",
          reason: moveRes?.reason || "move_skipped",
        };
      }
    }

    recordDecision({
      url: tab.url,
      host,
      title: tab.title || host,
      fromSpace: currentSpaceName,
      ...decision,
    });
    return decision;
  } catch (err) {
    console.error("[ZenSpaceRouter] routeTab error:", err);
    return { action: "stay", reason: "internal_error" };
  } finally {
    inFlightTabs.delete(tabId);
  }
}

function clearPendingTimer(entry) {
  if (entry?.timer) {
    clearTimeout(entry.timer);
    entry.timer = null;
  }
}

function scheduleRoutingForPendingTab(tabId, entry, immediate) {
  clearPendingTimer(entry);
  const run = () => {
    const latest = pendingTabs.get(tabId);
    if (!latest || latest.routed) {
      return;
    }
    latest.routed = true;
    pendingTabs.delete(tabId);
    routeTab(tabId, { manual: false, openerUrl: latest.openerUrl });
  };

  if (immediate) {
    run();
  } else {
    entry.timer = setTimeout(run, TITLE_DEBOUNCE_MS);
  }
}

browser.tabs.onCreated.addListener(async tab => {
  if (!settings.enabled) {
    return;
  }
  if (Date.now() - extensionStartedAt < STARTUP_GRACE_MS) {
    return;
  }
  if (tab.pinned) {
    return;
  }

  let openerUrl = "";
  if (typeof tab.openerTabId === "number") {
    try {
      const opener = await browser.tabs.get(tab.openerTabId);
      openerUrl = opener?.url || "";
    } catch (_err) {
      openerUrl = "";
    }
  }

  const entry = {
    createdAt: Date.now(),
    openerUrl,
    routed: false,
    timer: null,
  };
  pendingTabs.set(tab.id, entry);

  // If the tab already has a routable HTTP(S) URL at creation (e.g., external link
  // or middle-click), arm the short debounce timer right away.
  if (tab.url && normalizeHost(tab.url)) {
    const hasTitle = isInformativeTitle(tab.title, tab.url);
    scheduleRoutingForPendingTab(tab.id, entry, hasTitle || tab.status === "complete");
  }
});

browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!settings.enabled) {
    return;
  }
  const entry = pendingTabs.get(tabId);
  if (!entry || entry.routed) {
    return;
  }

  const url = changeInfo.url || tab.url;
  if (!url || !normalizeHost(url)) {
    return;
  }

  const title = changeInfo.title || tab.title || "";
  const hasGoodTitle = isInformativeTitle(title, url);
  const isComplete = changeInfo.status === "complete" || tab.status === "complete";

  if (hasGoodTitle || isComplete) {
    scheduleRoutingForPendingTab(tabId, entry, true);
  } else if (!entry.timer) {
    scheduleRoutingForPendingTab(tabId, entry, false);
  }
});

browser.tabs.onRemoved.addListener(tabId => {
  const entry = pendingTabs.get(tabId);
  if (entry) {
    clearPendingTimer(entry);
    pendingTabs.delete(tabId);
  }
});

browser.runtime.onMessage.addListener(async message => {
  if (!message || typeof message.type !== "string") {
    return undefined;
  }

  switch (message.type) {
    case "getState": {
      const [spaces, health, activeTabs] = await Promise.all([
        browser.zenSpaces.getSpaces().catch(() => []),
        fetchHealth(),
        browser.tabs.query({ active: true, currentWindow: true }).catch(() => []),
      ]);
      const activeTab = activeTabs[0] || null;
      return {
        settings,
        spaces,
        health,
        recentDecisions,
        activeTab: activeTab
          ? {
              id: activeTab.id,
              url: activeTab.url || "",
              title: activeTab.title || "",
              host: normalizeHost(activeTab.url || ""),
            }
          : null,
      };
    }

    case "updateSettings":
      return { settings: await saveSettings(message.patch || {}) };

    case "routeActiveTab": {
      const activeTabs = await browser.tabs.query({
        active: true,
        currentWindow: true,
      });
      const activeTab = activeTabs[0];
      if (!activeTab) {
        return { action: "stay", reason: "no_active_tab" };
      }
      return routeTab(activeTab.id, { manual: true });
    }

    case "clearServerCache": {
      const resp = await fetch(`${ROUTER_BASE_URL}/cache`, {
        method: "DELETE",
      });
      return resp.ok ? await resp.json() : { ok: false };
    }

    case "clearHistory": {
      recentDecisions = [];
      await browser.storage.local.set({ recentDecisions });
      return { ok: true };
    }

    default:
      return undefined;
  }
});

loadState();
