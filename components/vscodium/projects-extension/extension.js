"use strict";

const childProcess = require("child_process");
const vscode = require("vscode");

function projectctlPath() {
  return vscode.workspace
    .getConfiguration("homelabProjects")
    .get("projectctlPath", "/run/current-system/sw/bin/projectctl");
}

function runProjectctl(argumentsList) {
  return new Promise((resolve, reject) => {
    childProcess.execFile(
      projectctlPath(),
      argumentsList,
      { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stderr.trim() || error.message));
          return;
        }
        resolve(stdout);
      },
    );
  });
}

async function openProject() {
  let payload;
  try {
    payload = JSON.parse(await runProjectctl(["list", "--json"]));
  } catch (error) {
    vscode.window.showErrorMessage(`Could not list projects: ${error.message}`);
    return;
  }

  const choices = payload.projects.map((project) => ({
    label: project.title,
    description: project.name,
    detail: `${project.root} · ${project.editor_preset}`,
    project,
  }));
  if (choices.length === 0) {
    vscode.window.showInformationMessage("No active projectctl projects were found.");
    return;
  }
  const selected = await vscode.window.showQuickPick(choices, {
    matchOnDescription: true,
    matchOnDetail: true,
    placeHolder: "Choose a project to open",
  });
  if (!selected) {
    return;
  }

  if (vscode.env.remoteName) {
    await vscode.commands.executeCommand(
      "vscode.openFolder",
      vscode.Uri.file(selected.project.root),
      { forceNewWindow: true },
    );
    return;
  }

  const command = projectctlPath();
  const child = childProcess.spawn(command, ["ide", selected.project.name], {
    detached: true,
    stdio: "ignore",
  });
  child.once("error", (error) => {
    vscode.window.showErrorMessage(`Could not open project: ${error.message}`);
  });
  child.unref();
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("homelabProjects.openProject", openProject),
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
