"use strict";

const assert = require("assert");
const Module = require("module");

const handlers = new Map();
const execCalls = [];
const informationMessages = [];
const terminalLines = [];
const inputValues = [];
let openFolderCall;

const selectedProject = {
  title: "Example",
  name: "example",
  root: "/home/rishabh/Projects/example",
  status: "active",
  managed: true,
  environment: "nix",
  editor_preset: "general",
  sync_targets: [],
};

const outputChannel = {
  clear: () => {},
  appendLine: () => {},
  show: () => {},
  dispose: () => {},
};

const vscode = {
  ProgressLocation: { Notification: 15 },
  env: {
    remoteName: "ssh-remote",
    openExternal: async () => true,
  },
  workspace: {
    getConfiguration: () => ({
      get: (_name, fallback) => fallback,
    }),
  },
  window: {
    createOutputChannel: () => outputChannel,
    createTerminal: () => ({
      show: () => {},
      sendText: (line) => terminalLines.push(line),
    }),
    showErrorMessage: (message) => {
      throw new Error(message);
    },
    showInformationMessage: async (message) => {
      informationMessages.push(message);
      return undefined;
    },
    showInputBox: async () => inputValues.shift(),
    showQuickPick: async (choices) => choices[0],
    showWarningMessage: async (_message, _options, action) => action,
    withProgress: async (_options, operation) => operation(),
  },
  Uri: {
    file: (path) => ({ scheme: "file", path }),
    parse: (value) => ({ value }),
  },
  commands: {
    registerCommand: (name, handler) => {
      handlers.set(name, handler);
      return { dispose: () => {} };
    },
    executeCommand: async (...argumentsList) => {
      openFolderCall = argumentsList;
    },
  },
};

function responseFor(argumentsList) {
  if (argumentsList[0] === "list") {
    return { projects: [selectedProject] };
  }
  if (argumentsList[0] === "create") {
    return {
      ...selectedProject,
      name: "new-project",
      title: "New Project",
      root: "/home/rishabh/Projects/new-project",
    };
  }
  if (argumentsList[0] === "harnesses") {
    return {
      harnesses: [{ name: "codex", command: ["codex"], available: true }],
    };
  }
  return selectedProject;
}

const childProcess = {
  execFile: (_path, argumentsList, _options, callback) => {
    execCalls.push(argumentsList);
    callback(null, JSON.stringify(responseFor(argumentsList)), "");
  },
  spawn: () => {
    throw new Error("The local project launcher should not run in a remote extension host");
  },
};

const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  if (request === "vscode") {
    return vscode;
  }
  if (request === "child_process") {
    return childProcess;
  }
  return originalLoad.call(this, request, parent, isMain);
};

const expectedCommands = [
  "homelabProjects.openProject",
  "homelabProjects.createProject",
  "homelabProjects.initializeProject",
  "homelabProjects.showProject",
  "homelabProjects.renameProject",
  "homelabProjects.archiveProject",
  "homelabProjects.unarchiveProject",
  "homelabProjects.runCommand",
  "homelabProjects.openShell",
  "homelabProjects.startSession",
  "homelabProjects.checkEnvironment",
  "homelabProjects.lockEnvironment",
  "homelabProjects.openJupyter",
  "homelabProjects.showSyncStatus",
  "homelabProjects.enableSync",
  "homelabProjects.disableSync",
  "homelabProjects.deploySync",
  "homelabProjects.reconcileSync",
  "homelabProjects.showHarnesses",
  "homelabProjects.showCapabilities",
];

async function main() {
  const extension = require(process.env.PROJECTS_EXTENSION_PATH || "./extension");
  const context = { subscriptions: [] };
  extension.activate(context);

  assert.deepStrictEqual([...handlers.keys()], expectedCommands);

  await handlers.get("homelabProjects.openProject")();
  assert.deepStrictEqual(openFolderCall, [
    "vscode.openFolder",
    { scheme: "file", path: selectedProject.root },
    { forceNewWindow: true },
  ]);

  inputValues.push("new-project", "New Project");
  await handlers.get("homelabProjects.createProject")();
  assert.deepStrictEqual(execCalls.at(-1), [
    "create",
    "new-project",
    "--title",
    "New Project",
    "--json",
  ]);
  assert.match(informationMessages.at(-1), /^Created New Project/);

  inputValues.push("python -V");
  await handlers.get("homelabProjects.runCommand")();
  assert.match(
    terminalLines.at(-1),
    /projectctl' 'exec' 'example' '--' '\/bin\/sh' '-lc' 'python -V'$/,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
