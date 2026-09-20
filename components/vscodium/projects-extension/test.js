"use strict";

const assert = require("assert");
const Module = require("module");

let commandHandler;
let openFolderCall;

const selectedProject = {
  title: "Example",
  name: "example",
  root: "/home/rishabh/Projects/example",
  editor_preset: "general",
};

const vscode = {
  env: { remoteName: "ssh-remote" },
  workspace: {
    getConfiguration: () => ({
      get: (_name, fallback) => fallback,
    }),
    workspaceFolders: [
      {
        uri: {
          scheme: "file",
          path: "/home/rishabh/Projects",
        },
      },
    ],
  },
  window: {
    showErrorMessage: (message) => {
      throw new Error(message);
    },
    showInformationMessage: () => {},
    showQuickPick: async (choices) => choices[0],
  },
  Uri: {
    file: (path) => ({ scheme: "file", path }),
  },
  commands: {
    registerCommand: (_name, handler) => {
      commandHandler = handler;
      return { dispose: () => {} };
    },
    executeCommand: async (...argumentsList) => {
      openFolderCall = argumentsList;
    },
  },
};

const childProcess = {
  execFile: (_path, _argumentsList, _options, callback) => {
    callback(null, JSON.stringify({ projects: [selectedProject] }), "");
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

async function main() {
  const extension = require(process.env.PROJECTS_EXTENSION_PATH || "./extension");
  const context = { subscriptions: [] };
  extension.activate(context);

  assert.strictEqual(typeof commandHandler, "function");
  await commandHandler();

  assert.deepStrictEqual(openFolderCall, [
    "vscode.openFolder",
    {
      scheme: "file",
      path: selectedProject.root,
    },
    { forceNewWindow: true },
  ]);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
