const get = (id) => document.getElementById(id);
const states = { draft: "Draft", review: "In Product review", approved: "Approved" };
const labels = { created: "Created", edit: "Edited", submit: "Submitted for review",
  return: "Requested changes", approve: "Approved", reopen: "Reopened" };
let current = null;
let busy = false;

async function request(path, payload) {
  const options = payload ? {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)} : {};
  const response = await fetch("/api/releases" + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

function node(tag, text) {
  const item = document.createElement(tag);
  item.textContent = text;
  return item;
}

async function operate(task) {
  if (busy) return;
  busy = true;
  get("notice").textContent = "";
  try {
    await task();
  } catch (error) {
    get("notice").textContent = error.message;
  } finally {
    busy = false;
  }
}

async function refreshList() {
  const notes = await request("");
  const list = get("notes");
  list.replaceChildren();
  if (!notes.length) list.append(node("li", "No release notes yet."));
  for (const note of notes) {
    const row = node("li", "");
    const button = node("button", note.title + " · " + states[note.state]);
    if (current?.id === note.id) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => operate(() => openNote(note.id)));
    row.append(button);
    list.append(row);
  }
}

function draftFields(note) {
  for (const key of ["title", "project", "body"]) {
    get("draft-" + key).value = note?.[key] ?? "";
  }
}

function showDraft() {
  current = null;
  get("summary").hidden = get("workflow").hidden = true;
  get("editor").hidden = get("sample").hidden = false;
  get("editor-title").textContent = "New draft";
  draftFields(null);
}

function addAction(label, action, primary = false) {
  const button = node("button", label);
  if (primary) button.className = "primary";
  button.addEventListener("click", () => operate(async () => {
    const updated = await request("/" + current.id, {
      action, version: current.version, note: get("reason").value,
    });
    await openNote(updated.id);
  }));
  get("actions").append(button);
  return button;
}

async function openNote(id) {
  current = await request("/" + id);
  const draft = current.state === "draft";
  get("summary").hidden = get("workflow").hidden = false;
  get("editor").hidden = !draft;
  get("sample").hidden = true;
  get("editor-title").textContent = "Edit draft";
  get("state").textContent = states[current.state] + " · Revision " + current.version;
  for (const key of ["title", "project", "body"]) get(key).textContent = current[key];
  draftFields(current);
  get("reason").value = "";
  get("reason-label").hidden = draft;
  get("actions").replaceChildren();
  if (draft) {
    const submit = addAction("Submit for review", "submit", true);
    submit.id = "submit-review";
  } else if (current.state === "review") {
    addAction("Approve", "approve", true);
    addAction("Request changes", "return");
  } else {
    const download = node("a", "Download client update");
    download.href = "/api/releases/" + current.id + "/export";
    get("actions").append(download);
    addAction("Reopen draft", "reopen");
  }
  const history = get("history");
  history.replaceChildren();
  for (const event of current.history) {
    const date = new Date(event.happened).toLocaleString();
    const row = node("li", [labels[event.action], event.actor, date].join(" · "));
    if (event.note) row.append(node("p", event.note));
    history.append(row);
  }
  await refreshList();
}

get("new").addEventListener("click", () => operate(async () => {
  showDraft();
  await refreshList();
  get("draft-title").focus();
}));
get("sample").addEventListener("click", () => draftFields({
  title: "Simpler appointment rescheduling",
  project: "Harbor Studio",
  body: "Clients can move an upcoming appointment from their account. The confirmation now shows the new time and sends an updated calendar invitation.",
}));
get("editor").addEventListener("input", () => {
  const submit = get("submit-review");
  if (submit) {
    submit.disabled = ["title", "project", "body"].some(
      (key) => get("draft-" + key).value !== current[key]
    );
  }
});
get("editor").addEventListener("submit", (event) => {
  event.preventDefault();
  operate(async () => {
    const data = Object.fromEntries(["title", "project", "body"].map((key) => [key, get("draft-" + key).value]));
    if (current) Object.assign(data, {action: "edit", version: current.version});
    const saved = await request(current ? "/" + current.id : "", data);
    await openNote(saved.id);
    get("notice").textContent = "Draft saved.";
  });
});
showDraft();
operate(refreshList);
