const state = {
  posts: [],
  selected: null,
  notebook: null,
  projects: [],
};

const elements = {
  body: document.querySelector("#posts-body"),
  count: document.querySelector("#post-count"),
  empty: document.querySelector("#empty-state"),
  placeholder: document.querySelector("#editor-placeholder"),
  form: document.querySelector("#post-form"),
  status: document.querySelector("#status"),
  publish: document.querySelector("#publish-button"),
  dialog: document.querySelector("#create-dialog"),
  createForm: document.querySelector("#create-form"),
  dialogTitle: document.querySelector("#dialog-title"),
  createSubmit: document.querySelector("#create-submit"),
  fileInput: document.querySelector("#notebook-input"),
  selectedFile: document.querySelector("#selected-file"),
  importProject: document.querySelector("#import-project-button"),
  projectDialog: document.querySelector("#project-dialog"),
  projectForm: document.querySelector("#project-form"),
  projectSelect: document.querySelector("#project-select"),
  projectDetail: document.querySelector("#project-detail"),
  projectSubmit: document.querySelector("#project-submit"),
  openSource: document.querySelector("#open-source"),
  viewPost: document.querySelector("#view-post"),
  removePost: document.querySelector("#remove-post"),
  logPanel: document.querySelector("#build-log-panel"),
  log: document.querySelector("#build-log"),
};

function setStatus(message, error = false) {
  elements.status.textContent = message;
  elements.status.classList.toggle("error", error);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if ((options.method || "GET") !== "GET") headers.set("X-Blog-Admin", "1");
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function renderPosts() {
  elements.body.replaceChildren();
  elements.count.textContent = String(state.posts.length);
  elements.empty.hidden = state.posts.length !== 0;

  for (const post of state.posts) {
    const row = document.createElement("tr");
    row.tabIndex = 0;
    row.classList.toggle("selected", state.selected?.id === post.id);
    row.innerHTML = `
      <td><div class="post-title"></div><div class="post-slug"></div></td>
      <td class="kind"></td>
      <td><span class="badge"></span></td>
      <td class="post-date"></td>
    `;
    row.querySelector(".post-title").textContent = post.title;
    row.querySelector(".post-slug").textContent = post.slug;
    row.querySelector(".kind").textContent = post.kind;
    const badge = row.querySelector(".badge");
    badge.textContent = post.draft ? "Draft" : "Published";
    badge.classList.add(post.draft ? "draft" : "published");
    row.querySelector(".post-date").textContent = post.date;
    const select = () => selectPost(post.id);
    row.addEventListener("click", select);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") select();
    });
    elements.body.append(row);
  }
}

function selectPost(id) {
  state.selected = state.posts.find((post) => post.id === id) || null;
  renderPosts();
  if (!state.selected) {
    elements.form.hidden = true;
    elements.placeholder.hidden = false;
    return;
  }
  const post = state.selected;
  elements.placeholder.hidden = true;
  elements.form.hidden = false;
  elements.form.elements.title.value = post.title;
  elements.form.elements.slug.value = post.slug;
  elements.form.elements.description.value = post.description;
  elements.form.elements.date.value = post.date;
  elements.form.elements.categories.value = post.categories.join(", ");
  elements.form.elements.draft.checked = post.draft;
  elements.openSource.href = post.editorUrl || "#";
  elements.openSource.hidden = !post.editorUrl;
  elements.viewPost.hidden = !post.postUrl;
  elements.removePost.textContent = post.origin === "project" ? "Remove project" : "Remove post";
}

async function loadPosts(selectedId = state.selected?.id) {
  const data = await api("/admin/api/posts");
  state.posts = data.posts;
  renderPosts();
  if (selectedId) selectPost(selectedId);
}

function openCreateDialog(notebook = null) {
  state.notebook = notebook;
  elements.createForm.reset();
  elements.dialogTitle.textContent = notebook ? "Import notebook" : "New post";
  elements.createSubmit.textContent = notebook ? "Import" : "Create";
  elements.selectedFile.hidden = !notebook;
  elements.selectedFile.textContent = notebook ? notebook.name : "";
  elements.dialog.showModal();
}

document.querySelector("#new-button").addEventListener("click", () => openCreateDialog());
document.querySelector("#import-button").addEventListener("click", () => elements.fileInput.click());
elements.fileInput.addEventListener("change", () => {
  const notebook = elements.fileInput.files[0];
  if (notebook) openCreateDialog(notebook);
  elements.fileInput.value = "";
});

function renderProjectOptions() {
  elements.projectSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a project";
  elements.projectSelect.append(placeholder);
  for (const project of state.projects) {
    const option = document.createElement("option");
    option.value = project.id;
    option.disabled = project.imported || project.notebookCount === 0;
    const suffix = project.imported
      ? "already imported"
      : `${project.notebookCount} notebook${project.notebookCount === 1 ? "" : "s"}`;
    option.textContent = `${project.title} (${suffix})`;
    elements.projectSelect.append(option);
  }
  elements.projectSelect.value = "";
  elements.projectDetail.hidden = true;
  elements.projectSubmit.disabled = true;
}

async function openProjectDialog() {
  try {
    setStatus("Loading projects...");
    const data = await api("/admin/api/projects");
    state.projects = data.projects;
    renderProjectOptions();
    elements.projectDialog.showModal();
    setStatus("Ready");
  } catch (error) {
    setStatus(error.message, true);
  }
}

elements.importProject.addEventListener("click", openProjectDialog);
elements.projectSelect.addEventListener("change", () => {
  const selected = state.projects.find((project) => project.id === elements.projectSelect.value);
  elements.projectSubmit.disabled = !selected || selected.imported || selected.notebookCount === 0;
  elements.projectDetail.hidden = !selected;
  if (selected) {
    elements.projectDetail.textContent = `${selected.root} · ${selected.environment} environment`;
  }
});

elements.projectForm.addEventListener("submit", async (event) => {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  const projectId = elements.projectSelect.value;
  if (!projectId) return;
  elements.projectSubmit.disabled = true;
  try {
    setStatus("Linking project...");
    const result = await api("/admin/api/import-project", {
      method: "POST",
      body: JSON.stringify({ project: projectId }),
    });
    elements.projectDialog.close();
    await loadPosts(result.posts[0]?.id);
    const count = result.posts.length;
    setStatus(`Imported ${count} notebook${count === 1 ? "" : "s"} as drafts`);
  } catch (error) {
    setStatus(error.message, true);
    elements.projectSubmit.disabled = false;
  }
});

elements.createForm.addEventListener("submit", async (event) => {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  if (!elements.createForm.reportValidity()) return;
  const form = new FormData(elements.createForm);
  const title = form.get("title");
  const slug = form.get("slug");
  try {
    setStatus(state.notebook ? "Importing notebook..." : "Creating post...");
    let post;
    if (state.notebook) {
      const upload = new FormData();
      upload.set("title", title);
      if (slug) upload.set("slug", slug);
      upload.set("notebook", state.notebook);
      post = await api("/admin/api/import", { method: "POST", body: upload });
    } else {
      post = await api("/admin/api/posts", {
        method: "POST",
        body: JSON.stringify({ title, slug, draft: true }),
      });
    }
    elements.dialog.close();
    await loadPosts(post.id);
    setStatus("Draft created");
  } catch (error) {
    setStatus(error.message, true);
  }
});

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(elements.form);
  const payload = {
    title: form.get("title"),
    description: form.get("description"),
    date: form.get("date"),
    categories: form.get("categories").split(",").map((item) => item.trim()).filter(Boolean),
    draft: elements.form.elements.draft.checked,
  };
  try {
    setStatus("Saving metadata...");
    const post = await api(`/admin/api/posts/${encodeURIComponent(state.selected.id)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadPosts(post.id);
    setStatus("Metadata saved");
  } catch (error) {
    setStatus(error.message, true);
  }
});

elements.removePost.addEventListener("click", async () => {
  if (!state.selected) return;
  const selected = state.selected;
  const project = selected.origin === "project";
  const prompt = project
    ? `Remove the linked project “${selected.projectTitle}” and all of its notebook drafts from the blog? The project files will not be deleted.`
    : `Permanently remove “${selected.title}” from the blog source?`;
  if (!window.confirm(prompt)) return;
  elements.removePost.disabled = true;
  try {
    setStatus(project ? "Removing project and rebuilding preview..." : "Removing post and rebuilding preview...");
    const result = await api(`/admin/api/posts/${encodeURIComponent(selected.id)}`, {
      method: "DELETE",
    });
    if (result.preview?.log) {
      elements.log.textContent = result.preview.log;
      elements.logPanel.hidden = false;
    }
    state.selected = null;
    await loadPosts();
    setStatus(project ? "Project removed; original files were preserved" : "Post removed");
  } catch (error) {
    setStatus(error.message, true);
    await loadPosts().catch(() => {});
  } finally {
    elements.removePost.disabled = false;
  }
});

elements.viewPost.addEventListener("click", async (event) => {
  event.preventDefault();
  if (!state.selected?.postUrl || elements.viewPost.dataset.busy) return;
  const postUrl = state.selected.postUrl;
  elements.viewPost.dataset.busy = "true";
  elements.viewPost.setAttribute("aria-disabled", "true");
  try {
    setStatus("Rendering preview...");
    const result = await api("/admin/api/preview", { method: "POST" });
    elements.log.textContent = result.log || "Preview completed without output.";
    elements.logPanel.hidden = false;
    window.location.assign(postUrl);
  } catch (error) {
    setStatus(error.message, true);
    const status = await api("/admin/api/status").catch(() => null);
    if (status?.log) {
      elements.log.textContent = status.log;
      elements.logPanel.hidden = false;
      elements.logPanel.open = true;
    }
  } finally {
    delete elements.viewPost.dataset.busy;
    elements.viewPost.removeAttribute("aria-disabled");
  }
});

elements.publish.addEventListener("click", async () => {
  elements.publish.disabled = true;
  try {
    setStatus("Rendering and publishing...");
    const result = await api("/admin/api/publish", { method: "POST" });
    elements.log.textContent = result.log || "Build completed without output.";
    elements.logPanel.hidden = false;
    setStatus("Published");
  } catch (error) {
    setStatus(error.message, true);
    const status = await api("/admin/api/status").catch(() => null);
    if (status?.log) {
      elements.log.textContent = status.log;
      elements.logPanel.hidden = false;
      elements.logPanel.open = true;
    }
  } finally {
    elements.publish.disabled = false;
  }
});

loadPosts().catch((error) => setStatus(error.message, true));
