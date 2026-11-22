/* global ExtensionAPI, ChromeUtils, Services */
"use strict";

function getZenSpaceRoutingManager() {
  try {
    const mod = ChromeUtils.importESModule(
      "resource:///modules/zen/spacerouting/ZenSpaceRoutingManager.sys.mjs"
    );
    return mod?.gZenSpaceRoutingManager ?? null;
  } catch (_err) {
    return null;
  }
}

function resolveBrowserWindow(extension, context, windowId) {
  if (typeof windowId === "number") {
    try {
      const wrapped = extension.windowManager.get(windowId, context);
      if (wrapped?.window) {
        return wrapped.window;
      }
    } catch (_err) {
      // Fall through to most recent browser window.
    }
  }
  return Services.wm.getMostRecentWindow("navigator:browser");
}

function resolveNativeTab(extension, tabId) {
  try {
    const wrapped = extension.tabManager.get(tabId, null);
    if (wrapped?.nativeTab) {
      return wrapped.nativeTab;
    }
  } catch (_err) {
    // Fall through to global tabTracker if available.
  }
  if (typeof globalThis.tabTracker?.getTab === "function") {
    return globalThis.tabTracker.getTab(tabId, null);
  }
  return null;
}

this.zenSpaces = class extends ExtensionAPI {
  getAPI(context) {
    const { extension } = context;

    return {
      zenSpaces: {
        async getSpaces(windowId) {
          const win = resolveBrowserWindow(extension, context, windowId);
          const zw = win?.gZenWorkspaces;
          if (!zw || typeof zw.getWorkspaces !== "function") {
            return [];
          }
          const activeId = zw.activeWorkspace || "";
          const rawSpaces = zw.getWorkspaces() || [];
          return rawSpaces
            .filter(space => space && space.uuid && space.name)
            .map(space => ({
              uuid: String(space.uuid),
              name: String(space.name),
              isActive: String(space.uuid) === String(activeId),
            }));
        },

        async getTabContext(tabId, url) {
          const tab = resolveNativeTab(extension, tabId);
          if (!tab || !tab.isConnected) {
            return { found: false };
          }
          const win = tab.ownerGlobal;
          const zw = win?.gZenWorkspaces;
          const workspaceId =
            tab.getAttribute("zen-workspace-id") || zw?.activeWorkspace || "";

          let hasManualZenRoute = false;
          if (typeof url === "string" && url.length > 0) {
            const routingManager = getZenSpaceRoutingManager();
            if (routingManager && typeof routingManager.routeUri === "function") {
              try {
                const manualRoute = routingManager.routeUri(url, {
                  fromExternal: false,
                });
                hasManualZenRoute =
                  Boolean(manualRoute) && manualRoute !== "most-recent-space";
              } catch (_err) {
                hasManualZenRoute = false;
              }
            }
          }

          return {
            found: true,
            workspaceId: String(workspaceId),
            isPinned: Boolean(tab.pinned),
            isEssential: tab.hasAttribute("zen-essential"),
            isEmpty: tab.hasAttribute("zen-empty-tab"),
            isGlance:
              tab.hasAttribute("zen-glance-tab") || tab.hasAttribute("glance-id"),
            isSplit: Boolean(tab.group?.hasAttribute("split-view-group")),
            isSelected: Boolean(tab.selected),
            hasManualZenRoute,
          };
        },

        async moveTabToSpace(tabId, targetWorkspaceId, followIfSelected = true) {
          const tab = resolveNativeTab(extension, tabId);
          if (!tab || !tab.isConnected) {
            return { moved: false, reason: "tab_not_found" };
          }

          const win = tab.ownerGlobal;
          const zw = win?.gZenWorkspaces;
          const gBrowser = win?.gBrowser;
          if (!zw || !gBrowser || typeof zw.moveTabToWorkspace !== "function") {
            return { moved: false, reason: "zen_workspaces_unavailable" };
          }

          if (
            tab.pinned ||
            tab.hasAttribute("zen-essential") ||
            tab.hasAttribute("zen-empty-tab") ||
            tab.hasAttribute("zen-glance-tab") ||
            tab.hasAttribute("glance-id") ||
            tab.group?.hasAttribute("split-view-group")
          ) {
            return { moved: false, reason: "special_tab" };
          }

          const currentWorkspaceId =
            tab.getAttribute("zen-workspace-id") || zw.activeWorkspace || "";
          if (currentWorkspaceId === targetWorkspaceId) {
            return {
              moved: false,
              reason: "already_in_space",
              workspaceId: currentWorkspaceId,
            };
          }

          const targetWorkspace =
            typeof zw.getWorkspaceFromId === "function"
              ? zw.getWorkspaceFromId(targetWorkspaceId)
              : (zw.getWorkspaces?.() || []).find(
                  ws => ws.uuid === targetWorkspaceId
                );
          if (!targetWorkspace) {
            return { moved: false, reason: "workspace_not_found" };
          }

          const wasSelected = Boolean(tab.selected);

          // Mirror Zen's own ZenSpaceRoutingNavigation handoff so moving the
          // selected tab leaves a valid tab selected in the origin Space.
          if (
            wasSelected &&
            tab.owner &&
            tab.owner.isConnected &&
            tab.owner.getAttribute("zen-workspace-id") === currentWorkspaceId
          ) {
            gBrowser.selectedTab = tab.owner;
          }

          zw.moveTabToWorkspace(tab, targetWorkspaceId);

          if (wasSelected && followIfSelected) {
            if (zw.lastSelectedWorkspaceTabs) {
              zw.lastSelectedWorkspaceTabs[targetWorkspaceId] = tab;
            }
            if (typeof zw.changeWorkspace === "function") {
              await zw.changeWorkspace(targetWorkspace);
            } else if (typeof zw.changeWorkspaceWithID === "function") {
              await zw.changeWorkspaceWithID(targetWorkspaceId);
            }
            if (tab.isConnected) {
              gBrowser.selectedTab = tab;
            }
          } else if (wasSelected && !followIfSelected) {
            const remaining = Array.from(zw.allStoredTabs || []).find(
              candidate =>
                candidate !== tab &&
                candidate.isConnected &&
                candidate.getAttribute("zen-workspace-id") === currentWorkspaceId &&
                !candidate.hasAttribute("zen-empty-tab") &&
                !candidate.hasAttribute("zen-essential")
            );
            if (remaining) {
              gBrowser.selectedTab = remaining;
            } else if (typeof zw.selectEmptyTab === "function") {
              zw.selectEmptyTab();
            }
          }

          return {
            moved: true,
            reason: "moved",
            workspaceId: targetWorkspaceId,
          };
        },
      },
    };
  }
};
