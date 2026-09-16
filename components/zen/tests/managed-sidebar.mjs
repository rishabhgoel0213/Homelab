import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const compilerPath = process.env.ZEN_MANAGED_SIDEBAR_COMPILER;
assert.ok(compilerPath, "ZEN_MANAGED_SIDEBAR_COMPILER is required");
const { compileManagedSidebar } = await import(pathToFileURL(compilerPath));

if (process.env.ZEN_MANAGED_SIDEBAR_MANIFEST) {
  const generatedManifest = JSON.parse(
    await readFile(process.env.ZEN_MANAGED_SIDEBAR_MANIFEST, "utf8")
  );
  compileManagedSidebar(generatedManifest);
}

const manifest = {
  version: 1,
  modes: {
    containers: "merge",
    spaces: "authoritative",
    pins: "authoritative",
    folders: "authoritative",
    splits: "authoritative",
    routes: "authoritative",
  },
  pinRemoval: "demote",
  disableFirefoxSync: true,
  containers: {
    Work: {
      id: "unused-for-builtin",
      builtin: 1,
      name: "Work",
      icon: "briefcase",
      color: "blue",
      position: 0,
    },
  },
  spaces: {
    General: {
      id: "{space-general}",
      name: "General",
      icon: "home",
      container: null,
      theme: null,
      position: 0,
    },
    Work: {
      id: "{space-work}",
      name: "Work",
      icon: "briefcase",
      container: "Work",
      theme: { type: "gradient", gradientColors: [], opacity: 0.5, texture: 0 },
      position: 10,
    },
  },
  folders: {
    Projects: {
      id: "{folder-projects}",
      name: "Projects",
      space: "Work",
      parent: null,
      icon: null,
      live: null,
      position: 10,
    },
    Feed: {
      id: "{folder-feed}",
      name: "Feed",
      space: null,
      parent: "Projects",
      icon: null,
      live: {
        type: "rss",
        state: { url: "https://example.com/feed.xml", maxItems: 5 },
      },
      position: 20,
    },
  },
  pins: {
    Home: {
      id: "{pin-home}",
      title: "Home",
      url: "https://example.com",
      essential: true,
      container: null,
      space: null,
      folder: null,
      position: 0,
    },
    Repo: {
      id: "{pin-repo}",
      title: "Repo",
      url: "https://github.com/example/repo",
      essential: false,
      container: null,
      space: null,
      folder: "Projects",
      position: 30,
    },
    Docs: {
      id: "{pin-docs}",
      title: "Docs",
      url: "https://docs.example.com",
      essential: false,
      container: null,
      space: "Work",
      folder: null,
      position: 40,
    },
  },
  splits: {
    WorkPair: {
      id: "{split-work}",
      pins: ["Repo", "Docs"],
      gridType: "vsep",
      space: "Work",
      folder: "Projects",
      position: 30,
    },
  },
  routes: {
    Github: {
      id: "{route-github}",
      reference: "github.com",
      matchType: "contains",
      space: "Work",
      position: 0,
    },
  },
  defaultExternalSpace: "General",
};

const compiled = compileManagedSidebar(manifest);
assert.equal(compiled.pinRemoval, "demote");
assert.equal(compiled.disableFirefoxSync, true);
assert.deepEqual(compiled.routes, [
  {
    id: "{route-github}",
    reference: "github.com",
    matchType: "contains",
    openIn: "{space-work}",
  },
]);
assert.equal(compiled.defaultExternalRoute, "{space-general}");

const byId = new Map(compiled.records.map(record => [record.id, record.cleartext]));
assert.equal(byId.get("builtin-1").kind, "container");
assert.deepEqual(byId.get("{space-general}").data.children, []);
assert.deepEqual(byId.get("{space-general}").data.theme, {
  type: "gradient",
  gradientColors: [],
  opacity: 0.5,
  texture: 0,
});
assert.deepEqual(byId.get("{space-work}").data.theme, manifest.spaces.Work.theme);
const omittedTheme = structuredClone(manifest);
delete omittedTheme.spaces.General.theme;
assert.deepEqual(
  compileManagedSidebar(omittedTheme).records.find(
    record => record.id === "{space-general}"
  ).cleartext.data.theme,
  byId.get("{space-general}").data.theme
);
assert.deepEqual(byId.get("{space-work}").data.children, ["{folder-projects}"]);
assert.deepEqual(byId.get("{folder-projects}").data.children, [
  "{folder-feed}",
  "{split-work}",
]);
assert.equal(byId.get("{folder-feed}").data.live.type, "rss");
assert.equal(byId.get("{pin-repo}").data.folderId, "{folder-projects}");
assert.equal(byId.get("{pin-repo}").data.workspaceUuid, "{space-work}");
assert.equal(byId.get("{pin-repo}").data.containerGuid, "builtin-1");
assert.deepEqual(byId.get("{split-work}").data.tabs, ["{pin-repo}", "{pin-docs}"]);
assert.deepEqual(byId.get("layout").data.essentials, {
  default: ["{pin-home}"],
});

const cycle = structuredClone(manifest);
cycle.folders.Projects.parent = "Feed";
assert.throws(() => compileManagedSidebar(cycle), /folder parent cycle/);

const duplicate = structuredClone(manifest);
duplicate.pins.Home.id = "{space-general}";
assert.throws(() => compileManagedSidebar(duplicate), /used more than once/);

const essentialSplit = structuredClone(manifest);
essentialSplit.pins.Repo.essential = true;
assert.throws(() => compileManagedSidebar(essentialSplit), /cannot belong to a split/);

const duplicateRoute = structuredClone(manifest);
duplicateRoute.routes.Second = {
  ...duplicateRoute.routes.Github,
  reference: "example.com",
};
assert.throws(() => compileManagedSidebar(duplicateRoute), /route id.*used more than once/);

const invalidGrid = structuredClone(manifest);
invalidGrid.splits.WorkPair.gridType = "diagonal";
assert.throws(() => compileManagedSidebar(invalidGrid), /gridType is invalid/);

console.log("managed Zen sidebar compiler tests passed");
