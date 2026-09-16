import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createContext, SourceTextModule, SyntheticModule } from "node:vm";

const source = await readFile(process.env.ZEN_SPACES_SYNC_APPLIER, "utf8");

async function deletion({ managed = false, accept = false, last = false } = {}) {
  let spaces = [{ uuid: "remove", name: "Undeclared" }];
  if (!last) spaces.push({ uuid: "keep", name: "General" });
  let prompts = 0;
  let animations = 0;
  const window = {
    browsingContext: {},
    document: {
      getElementById: () => null,
      l10n: { formatValues: async () => ["Delete synced Space?", "Confirm"] },
    },
    gBrowser: { isTab: () => false },
    gZenWorkspaces: {
      promiseInitialized: Promise.resolve(),
      getWorkspaces: () => spaces,
      getWorkspaceFromId: id => spaces.find(space => space.uuid === id),
      removeWorkspace: async id => { spaces = spaces.filter(space => space.uuid !== id); },
    },
    gZenStartup: { playWindowSweepAnimation: () => animations++ },
  };
  const context = createContext({
    console,
    Services: {
      prefs: { getBoolPref: () => false, setBoolPref() {} },
      prompt: {
        asyncConfirmEx: async () => {
          prompts++;
          return new Map([["buttonNumClicked", accept ? 0 : 1]]);
        },
      },
    },
    ChromeUtils: {
      defineESModuleGetters: target => Object.assign(target, {
        ZenWindowSync: { firstSyncedWindow: window },
        SessionSaver: { runDelayed() {} },
      }),
    },
  });
  const model = new SyntheticModule([
    "canonicalJSON", "LAYOUT_RECORD_ID", "RECORD_KINDS", "syncableIconUrl", "ZenSpacesSyncModel",
  ], function () {
    this.setExport("canonicalJSON", JSON.stringify);
    this.setExport("LAYOUT_RECORD_ID", "layout");
    this.setExport("RECORD_KINDS", {});
    this.setExport("syncableIconUrl", value => value);
    this.setExport("ZenSpacesSyncModel", {
      contextIdForGuid: () => null, invalidate() {}, noteApplied() {},
    });
  }, { context });
  const module = new SourceTextModule(source, { context });
  await module.link(() => model);
  await module.evaluate();
  const failed = await module.namespace.ZenSpacesSyncApplier.applyBatch(
    [{ id: "remove", deleted: true }],
    managed ? { source: "managed" } : undefined
  );
  assert.equal(failed.length, 0);
  return { prompts, animations, spaces: spaces.length };
}

assert.deepEqual(await deletion(), { prompts: 1, animations: 1, spaces: 2 });
assert.deepEqual(await deletion({ accept: true }), { prompts: 1, animations: 1, spaces: 1 });
assert.deepEqual(await deletion({ managed: true }), { prompts: 0, animations: 0, spaces: 1 });
assert.deepEqual(await deletion({ managed: true, last: true }), { prompts: 0, animations: 0, spaces: 1 });
console.log("Managed deletion is silent; remote Sync confirmation and last-Space protection remain intact.");
