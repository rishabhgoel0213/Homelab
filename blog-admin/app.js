const state = {
  posts: [],
  selected: null,
  notebook: null,
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
  openSource: document.querySelector("#open-source"),
  viewPost: document.querySelector("#view-post"),
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
    row.classList.toggle("selected", state.selected?.slug === post.slug);
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
    const select = () => selectPost(post.slug);
    row.addEventListener("click", select);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") select();
    });
    elements.body.append(row);
  }
}

function selectPost(slug) {
  state.selected = state.posts.find((post) => post.slug === slug) || null;
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
  elements.viewPost.href = post.postUrl;
  elements.viewPost.hidden = !post.postUrl;
}

async function loadPosts(selectedSlug = state.selected?.slug) {
  const data = await api("/admin/api/posts");
  state.posts = data.posts;
  renderPosts();
  if (selectedSlug) selectPost(selectedSlug);
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
    await loadPosts(post.slug);
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
    const post = await api(`/admin/api/posts/${encodeURIComponent(state.selected.slug)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadPosts(post.slug);
    setStatus("Metadata saved");
  } catch (error) {
    setStatus(error.message, true);
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
