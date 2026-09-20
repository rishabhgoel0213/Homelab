"use strict";

const childProcess = require("child_process");
const vscode = require("vscode");

let outputChannel;

function configuration() {
  return vscode.workspace.getConfiguration("homelabProjects");
}

function projectctlPath() {
  return configuration().get(
    "projectctlPath",
    "/run/current-system/sw/bin/projectctl",
  );
}

function defaultSyncTarget() {
  return configuration().get("defaultSyncTarget", "macbook");
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

async function runProjectctlJson(argumentsList) {
  const output = await runProjectctl(argumentsList);
  try {
    return JSON.parse(output);
  } catch (error) {
    throw new Error(`projectctl returned invalid JSON: ${error.message}`);
  }
}

function projectItem(project) {
  return {
    label: project.title,
    description: project.name,
    detail: `${project.root} · ${project.status} · ${project.environment} · ${project.editor_preset}`,
    project,
  };
}

async function listProjects(includeArchived = false) {
  const argumentsList = ["list"];
  if (includeArchived) {
    argumentsList.push("--all");
  }
  argumentsList.push("--json");
  const payload = await runProjectctlJson(argumentsList);
  if (!Array.isArray(payload.projects)) {
    throw new Error("projectctl list response did not contain a projects array");
  }
  return payload.projects;
}

async function pickProject(options = {}) {
  const projects = (await listProjects(options.includeArchived)).filter(
    options.filter || (() => true),
  );
  if (projects.length === 0) {
    vscode.window.showInformationMessage(
      options.emptyMessage || "No matching projectctl projects were found.",
    );
    return undefined;
  }
  const selected = await vscode.window.showQuickPick(projects.map(projectItem), {
    matchOnDescription: true,
    matchOnDetail: true,
    placeHolder: options.placeHolder || "Choose a project",
  });
  return selected && selected.project;
}

async function promptText(prompt, options = {}) {
  return vscode.window.showInputBox({
    prompt,
    value: options.value,
    placeHolder: options.placeHolder,
    ignoreFocusOut: true,
    validateInput: (value) =>
      value.trim() ? undefined : options.emptyMessage || "A value is required.",
  });
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

function openProjectTerminal(title, argumentsList) {
  const terminal = vscode.window.createTerminal({ name: title });
  terminal.show(true);
  terminal.sendText(
    [projectctlPath(), ...argumentsList].map(shellQuote).join(" "),
    true,
  );
}

function showJson(title, payload) {
  outputChannel.clear();
  outputChannel.appendLine(title);
  outputChannel.appendLine("=".repeat(title.length));
  outputChannel.appendLine(JSON.stringify(payload, null, 2));
  outputChannel.show(true);
}

async function confirm(message, action) {
  const selected = await vscode.window.showWarningMessage(
    message,
    { modal: true },
    action,
  );
  return selected === action;
}

async function runWithProgress(title, operation) {
  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title,
      cancellable: false,
    },
    operation,
  );
}

async function openResolvedProject(project) {
  if (vscode.env.remoteName) {
    await vscode.commands.executeCommand(
      "vscode.openFolder",
      vscode.Uri.file(project.root),
      { forceNewWindow: true },
    );
    return;
  }

  const child = childProcess.spawn(projectctlPath(), ["ide", project.name], {
    detached: true,
    stdio: "ignore",
  });
  child.once("error", (error) => {
    vscode.window.showErrorMessage(`Could not open project: ${error.message}`);
  });
  child.unref();
}

async function openProject() {
  const project = await pickProject({
    placeHolder: "Choose a project to open",
  });
  if (project) {
    await openResolvedProject(project);
  }
}

async function createProject() {
  const name = await promptText("Project name or slug", {
    placeHolder: "linear-algebra",
  });
  if (!name) {
    return;
  }
  const title = await promptText("Project display title", { value: name });
  if (!title) {
    return;
  }
  const project = await runProjectctlJson([
    "create",
    name,
    "--title",
    title,
    "--json",
  ]);
  const selected = await vscode.window.showInformationMessage(
    `Created ${project.title} at ${project.root}.`,
    "Open Project",
  );
  if (selected === "Open Project") {
    await openResolvedProject(project);
  }
}

async function initializeProject() {
  const project = await pickProject({
    includeArchived: true,
    filter: (candidate) => !candidate.managed,
    placeHolder: "Choose an existing directory to initialize",
    emptyMessage: "Every discovered project is already managed.",
  });
  if (!project) {
    return;
  }
  const title = await promptText("Project display title", {
    value: project.title,
  });
  if (!title) {
    return;
  }
  const initialized = await runProjectctlJson([
    "init",
    project.name,
    "--title",
    title,
    "--json",
  ]);
  vscode.window.showInformationMessage(`Initialized ${initialized.title}.`);
}

async function showProject() {
  const project = await pickProject({
    includeArchived: true,
    placeHolder: "Choose a project to inspect",
  });
  if (!project) {
    return;
  }
  showJson(
    `Project: ${project.title}`,
    await runProjectctlJson(["show", project.name, "--json"]),
  );
}

async function renameProject() {
  const project = await pickProject({
    includeArchived: true,
    filter: (candidate) => candidate.managed,
    placeHolder: "Choose a managed project to rename",
  });
  if (!project) {
    return;
  }
  const title = await promptText("New project display title", {
    value: project.title,
  });
  if (!title || title === project.title) {
    return;
  }
  const renamed = await runProjectctlJson([
    "rename",
    project.name,
    title,
    "--json",
  ]);
  vscode.window.showInformationMessage(`Renamed project to ${renamed.title}.`);
}

async function setProjectLifecycle(nextStatus) {
  const command = nextStatus === "archived" ? "archive" : "unarchive";
  const verb = nextStatus === "archived" ? "Archive" : "Reactivate";
  const project = await pickProject({
    includeArchived: true,
    filter: (candidate) =>
      candidate.managed && candidate.status !== nextStatus,
    placeHolder: `${verb} which project?`,
    emptyMessage: `No managed projects are available to ${verb.toLowerCase()}.`,
  });
  if (!project || !(await confirm(`${verb} ${project.title}?`, verb))) {
    return;
  }
  await runProjectctlJson([command, project.name, "--json"]);
  vscode.window.showInformationMessage(`${verb}d ${project.title}.`);
}

async function runCommand() {
  const project = await pickProject({
    placeHolder: "Run a command in which project?",
  });
  if (!project) {
    return;
  }
  const command = await promptText("Command to run in the project environment", {
    placeHolder: "python -V",
  });
  if (!command) {
    return;
  }
  openProjectTerminal(`Project: ${project.name}`, [
    "exec",
    project.name,
    "--",
    "/bin/sh",
    "-lc",
    command,
  ]);
}

async function openShell() {
  const project = await pickProject({
    filter: (candidate) => candidate.environment === "nix",
    placeHolder: "Open a Nix shell for which project?",
    emptyMessage: "No active projects have a Nix environment.",
  });
  if (project) {
    openProjectTerminal(`Shell: ${project.name}`, ["shell", project.name]);
  }
}

async function startSession() {
  const project = await pickProject({
    placeHolder: "Start an agent session in which project?",
  });
  if (!project) {
    return;
  }
  const payload = await runProjectctlJson(["harnesses", "--json"]);
  const harnesses = (payload.harnesses || []).filter(
    (harness) => harness.available,
  );
  const selected = await vscode.window.showQuickPick(
    harnesses.map((harness) => ({
      label: harness.name,
      description: harness.command.join(" "),
      harness,
    })),
    { placeHolder: "Choose an available agent harness" },
  );
  if (selected) {
    openProjectTerminal(`${selected.harness.name}: ${project.name}`, [
      "session",
      project.name,
      selected.harness.name,
    ]);
  }
}

async function environmentCommand(command, label) {
  const project = await pickProject({
    filter: (candidate) => candidate.environment === "nix",
    placeHolder: `${label} for which project?`,
    emptyMessage: "No active projects have a Nix environment.",
  });
  if (project) {
    openProjectTerminal(`${label}: ${project.name}`, [
      "env",
      command,
      project.name,
    ]);
  }
}

async function openJupyter() {
  const project = await pickProject({
    placeHolder: "Open which project in JupyterLab?",
  });
  if (!project) {
    return;
  }
  const payload = await runWithProgress("Preparing JupyterLab project", () =>
    runProjectctlJson(["jupyter", project.name, "--json"]),
  );
  await vscode.env.openExternal(vscode.Uri.parse(payload.url));
}

async function showSyncStatus() {
  const project = await pickProject({
    includeArchived: true,
    filter: (candidate) => candidate.managed,
    placeHolder: "Show synchronization status for which project?",
  });
  if (project) {
    showJson(
      `Synchronization: ${project.title}`,
      await runProjectctlJson(["sync", "status", project.name, "--json"]),
    );
  }
}

async function promptSyncTarget(prompt, value = defaultSyncTarget()) {
  return promptText(prompt, {
    value,
    placeHolder: "macbook",
    emptyMessage: "A synchronization target is required.",
  });
}

async function enableSync() {
  const project = await pickProject({
    filter: (candidate) => candidate.managed,
    placeHolder: "Enable synchronization for which project?",
  });
  if (!project) {
    return;
  }
  const target = await promptSyncTarget("Synchronization target");
  if (!target) {
    return;
  }
  const payload = await runProjectctlJson([
    "sync",
    "enable",
    project.name,
    "--target",
    target,
    "--json",
  ]);
  vscode.window.showInformationMessage(
    payload.changed
      ? `Enabled ${target} synchronization for ${project.title}. Deploy sync to apply it.`
      : `${project.title} already targets ${target}.`,
  );
}

async function disableSync() {
  const project = await pickProject({
    includeArchived: true,
    filter: (candidate) =>
      candidate.managed && candidate.sync_targets.length > 0,
    placeHolder: "Disable synchronization for which project?",
    emptyMessage: "No managed projects currently declare synchronization targets.",
  });
  if (!project) {
    return;
  }
  const selected = await vscode.window.showQuickPick(project.sync_targets, {
    placeHolder: "Choose a synchronization target to remove",
  });
  if (
    !selected ||
    !(await confirm(
      `Stop synchronizing ${project.title} with ${selected}? Files will be preserved.`,
      "Disable Sync",
    ))
  ) {
    return;
  }
  await runProjectctlJson([
    "sync",
    "disable",
    project.name,
    "--target",
    selected,
    "--json",
  ]);
  vscode.window.showInformationMessage(
    `Disabled ${selected} synchronization for ${project.title}. Deploy sync to apply it.`,
  );
}

async function deploySync() {
  const target = await promptSyncTarget("Deploy synchronization target");
  if (
    !target ||
    !(await confirm(
      `Reconcile project synchronization on ${target} and this server?`,
      "Deploy Sync",
    ))
  ) {
    return;
  }
  const payload = await runWithProgress(
    `Deploying project synchronization to ${target}`,
    () => runProjectctlJson(["sync", "deploy", target, "--json"]),
  );
  showJson(`Synchronization deployment: ${target}`, payload);
}

async function reconcileSync() {
  if (
    !(await confirm(
      "Reconcile every declared project synchronization folder on this server?",
      "Reconcile Sync",
    ))
  ) {
    return;
  }
  const payload = await runWithProgress(
    "Reconciling project synchronization",
    () => runProjectctlJson(["sync", "reconcile", "--json"]),
  );
  showJson("Synchronization reconciliation", payload);
}

async function showHarnesses() {
  showJson(
    "Project agent harnesses",
    await runProjectctlJson(["harnesses", "--json"]),
  );
}

async function showCapabilities() {
  showJson(
    "projectctl capabilities",
    await runProjectctlJson(["capabilities", "--json"]),
  );
}

function register(context, command, handler) {
  context.subscriptions.push(
    vscode.commands.registerCommand(command, async () => {
      try {
        await handler();
      } catch (error) {
        vscode.window.showErrorMessage(
          `${command.replace("homelabProjects.", "Projects: ")} failed: ${error.message}`,
        );
      }
    }),
  );
}

function activate(context) {
  outputChannel = vscode.window.createOutputChannel("Homelab Projects");
  context.subscriptions.push(outputChannel);

  register(context, "homelabProjects.openProject", openProject);
  register(context, "homelabProjects.createProject", createProject);
  register(context, "homelabProjects.initializeProject", initializeProject);
  register(context, "homelabProjects.showProject", showProject);
  register(context, "homelabProjects.renameProject", renameProject);
  register(context, "homelabProjects.archiveProject", () =>
    setProjectLifecycle("archived"),
  );
  register(context, "homelabProjects.unarchiveProject", () =>
    setProjectLifecycle("active"),
  );
  register(context, "homelabProjects.runCommand", runCommand);
  register(context, "homelabProjects.openShell", openShell);
  register(context, "homelabProjects.startSession", startSession);
  register(context, "homelabProjects.checkEnvironment", () =>
    environmentCommand("check", "Check environment"),
  );
  register(context, "homelabProjects.lockEnvironment", () =>
    environmentCommand("lock", "Update environment lock"),
  );
  register(context, "homelabProjects.openJupyter", openJupyter);
  register(context, "homelabProjects.showSyncStatus", showSyncStatus);
  register(context, "homelabProjects.enableSync", enableSync);
  register(context, "homelabProjects.disableSync", disableSync);
  register(context, "homelabProjects.deploySync", deploySync);
  register(context, "homelabProjects.reconcileSync", reconcileSync);
  register(context, "homelabProjects.showHarnesses", showHarnesses);
  register(context, "homelabProjects.showCapabilities", showCapabilities);
}

function deactivate() {}

module.exports = { activate, deactivate };
