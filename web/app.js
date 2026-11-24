const $ = (id) => document.getElementById(id);
const button = (tag, text, className = "") => {
  const node = document.createElement(tag);
  if (tag === "button") node.type = "button";
  node.className = className;
  node.textContent = text;
  return node;
};
const keys = "1234567890abcdefghijklmnopqrstuvwxyz";
const defaults = [{ name: "Category A", key: "1" }, { name: "Category B", key: "2" }, { name: "Category C", key: "3" }];
const viewer = new Preview($("viewport"), $("surface"), (value) => {
  $("zoom").value = value;
  $("zoomLabel").value = value + "%";
});
let session, input, output, imported, busy = false, toastTimer, scrollFrame;

function note(message, error = false) {
  if (!$("setup").hidden) {
    $("setupStatus").hidden = !message;
    $("setupStatus").textContent = message;
  } else {
    $("toast").hidden = !message;
    $("toast").textContent = message;
    clearTimeout(toastTimer);
    if (!error) toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3900);
  }
}

async function run(action, write = false) {
  if (busy) return;
  busy = true;
  note("");
  updateControls();
  try {
    if (write && location.protocol !== "file:" && navigator.locks) {
      await navigator.locks.request("data-sorter-local-writes", action);
    }
    else await action();
  } catch (error) {
    if (error.name !== "AbortError") note(error.message || "The operation could not be completed.", true);
  } finally {
    busy = false;
    updateControls();
  }
}

function updateControls() {
  const reviewing = Boolean(session && !$("workspace").hidden);
  $("export").disabled = busy || !reviewing;
  $("configure").hidden = !reviewing;
  $("configure").disabled = busy;
  $("prev").disabled = busy || !reviewing || session.index === 0;
  $("next").disabled = busy || !reviewing || session.index === session.entries.length - 1;
  $("undo").disabled = busy || !reviewing || !session.history.length;
  $("start").disabled = busy || !window.showDirectoryPicker;
  $("back").disabled = busy;
  $("input").disabled = $("output").disabled = busy || !window.showDirectoryPicker;
  $("import").disabled = $("clearImport").disabled = busy;
  $("clearImport").hidden = !imported;
  $("add").disabled = busy || Boolean(imported);
  document.querySelectorAll("#categoryRows :is(button,input), .mode input").forEach((item) => {
    item.disabled = busy || Boolean(imported);
  });
  $("actions").querySelectorAll("button").forEach((item) => { item.disabled = busy; });
}

function addCategory({ name = "", key = "" } = {}) {
  const row = button("div", "", "category-row");
  const label = document.createElement("input"), shortcut = document.createElement("input");
  label.setAttribute("aria-label", "Category name");
  label.placeholder = "Category name";
  label.value = name;
  shortcut.setAttribute("aria-label", "Category shortcut");
  shortcut.maxLength = 2;
  shortcut.autocomplete = "off";
  const used = new Set(Array.from($("categoryRows").querySelectorAll("input:nth-child(2)"), (node) => node.value));
  shortcut.value = key || Array.from(keys).find((item) => !used.has(item)) || "";
  const remove = button("button", "", "icon");
  remove.innerHTML = ICONS.x;
  remove.title = "Remove category";
  remove.setAttribute("aria-label", remove.title);
  remove.addEventListener("click", () => {
    if (busy) return;
    row.remove();
    if (!$("categoryRows").children.length) addCategory();
  });
  row.append(label, shortcut, remove);
  $("categoryRows").append(row);
}

function showCategories(categories) {
  $("categoryRows").replaceChildren();
  categories.forEach(addCategory);
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function setMode(mode) {
  document.querySelector('input[name="mode"][value="' + mode + '"]').checked = true;
}

function renderFolders() {
  $("inputName").textContent = input?.name || "No folder selected";
  $("outputName").textContent = output?.name || "No folder selected";
}

function browse(kind) {
  return run(async () => {
    const mode = kind === "input" && (imported?.mode || selectedMode()) === "copy" ? "read" : "readwrite";
    const handle = await window.showDirectoryPicker({ id: "data-sorter-" + kind, mode });
    const other = kind === "input" ? output : input;
    if (other && await handle.isSameEntry(other)) fail("Choose different input and output folders.");
    if (kind === "input") input = handle;
    else output = handle;
    renderFolders();
  });
}

function start() {
  return run(async () => {
    if (!input || !output) fail("Select the input and output folders.");
    const source = input, target = output;
    const mode = imported?.mode || selectedMode();
    const needsWrite = mode === "move" || imported?.entries.some((entry) => entry.operation === "move");
    // Permission prompts require activation from the Start button.
    if (needsWrite && await source.requestPermission({ mode: "readwrite" }) !== "granted") {
      fail("Allow input folder write access to use Move.");
    }
    if (await source.isSameEntry(target) || await target.resolve(source)) {
      fail("Choose an output folder that does not contain the input folder.");
    }
    const raw = Array.from($("categoryRows").children, (row) => ({
      name: row.children[0].value, key: row.children[1].value,
    }));
    const settings = imported || { categories: categoriesFrom(raw), mode, entries: await findEntries(source, target), index: 0 };
    if (imported) {
      const outputWithinInput = await source.resolve(target);
      if (outputWithinInput && settings.entries.some(({ original }) =>
        original.length > outputWithinInput.length && outputWithinInput.every((part, i) => original[i] === part))) {
        fail("The session lists input files inside the selected output folder.");
      }
    }
    for (const category of settings.categories) await directory(target, [category.name], true);
    session = new SortSession(source, target, settings);
    const restored = Boolean(imported);
    imported = null;
    $("undecided").checked = false;
    $("fileList").scrollTop = 0;
    showReview(true);
    if (restored) note("Session restored.");
  });
}

function showReview(reload) {
  $("setup").hidden = true;
  $("workspace").hidden = false;
  render(reload);
}

function configure() {
  if (busy) return;
  if (session) {
    input = session.input;
    output = session.output;
    imported = null;
    setMode(session.mode);
    showCategories(session.categories);
    renderFolders();
  }
  $("setup").hidden = false;
  $("workspace").hidden = true;
  $("start").firstChild.textContent = "Start new session ";
  $("back").hidden = !session;
  $("modeBadge").hidden = true;
  $("sessionName").textContent = "Session settings";
  $("progressText").textContent = "Session paused";
  note("");
  updateControls();
}

function render(reload) {
  const { entries, categories, index, mode } = session;
  const entry = entries[index], counts = new Map(categories.map(({ name }) => [name, 0]));
  let chosen = 0;
  for (const file of entries) {
    if (!file.choice) continue;
    chosen += 1;
    counts.set(file.choice, counts.get(file.choice) + 1);
  }
  $("sessionName").textContent = session.input.name;
  $("sessionName").title = session.input.name;
  $("modeBadge").textContent = mode === "move" ? "Move" : "Copy";
  $("modeBadge").hidden = false;
  $("progress").max = entries.length;
  $("progress").value = chosen;
  $("progressText").textContent = chosen + " of " + entries.length + " sorted";
  $("remaining").textContent = (entries.length - chosen) + " left";
  $("fileType").textContent = ({ jpeg: "JPG", dcm: "DICOM" })[entry.ext] || entry.ext.toUpperCase();
  $("currentTitle").textContent = entry.name;
  $("currentTitle").title = entry.name;
  $("currentPosition").textContent = "File " + (index + 1) + " of " + entries.length;
  $("currentPath").textContent = entry.original.join(" / ");
  $("currentPath").title = entry.original.join("/");
  $("currentChoice").textContent = entry.choice || "Undecided";
  $("currentChoice").classList.toggle("chosen", Boolean(entry.choice));
  $("footerStatus").textContent = session.output.name;
  renderFiles();
  $("actions").replaceChildren(...categories.map(({ name, key }) => {
    const decision = button("button", "", "decision");
    decision.setAttribute("aria-pressed", String(entry.choice === name));
    decision.setAttribute("aria-keyshortcuts", key);
    decision.append(button("kbd", key), button("span", name), button("span", counts.get(name), "count"));
    decision.addEventListener("click", () => choose(name));
    return decision;
  }));
  updateControls();
  if (reload) viewer.show(session, entry);
}

function renderFiles() {
  const list = $("fileList");
  const fragment = document.createDocumentFragment();
  const visible = [];
  session.entries.forEach((entry, index) => {
    if ($("undecided").checked && entry.choice) return;
    const row = button("button", "", "file-row");
    row.setAttribute("aria-current", String(index === session.index));
    row.title = entry.original.join("/");
    const title = button("span", "", "row-text");
    title.append(button("span", entry.name), button("small", entry.choice || "Undecided"));
    const mark = button("span", "", "row-result");
    if (entry.choice) mark.innerHTML = ICONS.check;
    row.append(button("span", index + 1, "row-num"), title, mark);
    row.addEventListener("click", () => navigate(index));
    visible.push({ index, entry, row });
    fragment.append(row);
  });
  if (!visible.length) fragment.append(button("p", "No undecided files.", "empty-list"));
  list.replaceChildren(fragment);
  cancelAnimationFrame(scrollFrame);
  scrollFrame = requestAnimationFrame(() => {
    const undecided = visible.filter(({ entry, index }) => !entry.choice && index >= session.index);
    const active = visible.find(({ index }) => index === session.index);
    const first = active || undecided[0] || visible.at(-1);
    const fourth = undecided[Math.min(3, undecided.length - 1)] || first;
    if (!first || !list.clientHeight) return;
    const margin = 6, origin = list.getBoundingClientRect().top;
    const top = first.row.getBoundingClientRect().top - origin;
    const bottom = fourth.row.getBoundingClientRect().bottom - origin;
    if (bottom - top > list.clientHeight - 2 * margin || top < margin) list.scrollTop += top - margin;
    else if (bottom > list.clientHeight - margin) list.scrollTop += bottom - (list.clientHeight - margin);
  });
}

function navigate(index) {
  if (busy || !session || index < 0 || index >= session.entries.length || index === session.index) return;
  session.index = index;
  render(true);
}

function choose(name) {
  return run(async () => {
    const previous = session.index;
    const entry = session.entries[previous];
    const sourceMayMove = session.mode === "move" && (entry.operation !== "move" || entry.choice !== name);
    await session.choose(name);
    render(session.index !== previous || sourceMayMove);
  }, true);
}

function undo() {
  return run(async () => { await session.undo(); render(true); }, true);
}

function showShortcuts() {
  const builtIn = [["Previous file", "←"], ["Next file", "→"], ["Undo decision", "Ctrl/⌘ Z"]];
  const categories = session?.categories || defaults;
  $("shortcutList").replaceChildren(...[...builtIn, ...categories.map(({ name, key }) => [name, key])]
    .flatMap(([name, key]) => {
      const value = button("dd", "");
      value.append(button("kbd", key));
      return [button("dt", name), value];
    }));
  $("shortcuts").showModal();
}

$("input").addEventListener("click", () => browse("input"));
$("output").addEventListener("click", () => browse("output"));
$("add").addEventListener("click", () => { addCategory(); $("categoryRows").lastElementChild.firstElementChild.focus(); });
$("setupForm").addEventListener("submit", (event) => { event.preventDefault(); start(); });
$("back").addEventListener("click", () => {
  input = session.input; output = session.output; imported = null;
  showReview(true);
});
$("configure").addEventListener("click", configure);
$("import").addEventListener("click", () => $("importFile").click());
$("clearImport").addEventListener("click", () => {
  imported = null;
  $("start").firstChild.textContent = session ? "Start new session " : "Start sorting ";
  note("");
  updateControls();
});
$("importFile").addEventListener("change", () => run(async () => {
  const file = $("importFile").files[0];
  $("importFile").value = "";
  if (!file) return;
  imported = readSession(await file.text());
  showCategories(imported.categories);
  setMode(imported.mode);
  $("start").firstChild.textContent = "Restore session ";
  note("Session loaded. Select the original folders or their new locations.");
}));
$("export").addEventListener("click", () => run(async () => {
  await session.saveCsv();
  note("Saved " + RESULT_FILE + " in " + session.output.name + ".");
}, true));
$("undecided").addEventListener("change", renderFiles);
$("prev").addEventListener("click", () => navigate(session.index - 1));
$("next").addEventListener("click", () => navigate(session.index + 1));
$("undo").addEventListener("click", undo);
$("zoom").addEventListener("input", (event) => viewer.setZoom(event.target.valueAsNumber / 100));
$("minus").addEventListener("click", () => viewer.setZoom(viewer.zoom - 0.1));
$("plus").addEventListener("click", () => viewer.setZoom(viewer.zoom + 0.1));
$("fit").addEventListener("click", () => viewer.setZoom(1));
$("help").addEventListener("click", showShortcuts);
$("closeHelp").addEventListener("click", () => $("shortcuts").close());
document.addEventListener("keydown", (event) => {
  if (!session || busy || !$("setup").hidden || $("shortcuts").open ||
      event.target.closest?.("input, textarea, select, [contenteditable]") || event.repeat) return;
  const key = event.key.toLowerCase();
  if ((event.metaKey || event.ctrlKey) && key === "z") { event.preventDefault(); undo(); return; }
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (key === "arrowleft" || key === "arrowright") {
    event.preventDefault();
    navigate(session.index + (key === "arrowleft" ? -1 : 1));
  } else {
    const category = session.categories.find(({ key: shortcut }) => shortcut === key);
    if (category) { event.preventDefault(); choose(category.name); }
  }
});

showCategories(defaults);
updateControls();
if (!window.showDirectoryPicker) note("Open Data Sorter in desktop Chrome or Edge for local folder access.", true);

if (location.protocol !== "file:") {
  $("portableLink").hidden = false;
  if ("serviceWorker" in navigator && window.isSecureContext) {
    const ready = () => { $("offline").textContent = "Offline ready"; };
    const cacheFailed = () => {
      if (navigator.serviceWorker.controller) return;
      $("offline").textContent = "Local workspace";
      $("footerStatus").textContent = "Download an offline copy for use without a connection.";
    };
    if (navigator.serviceWorker.controller) ready();
    navigator.serviceWorker.addEventListener("controllerchange", ready);
    navigator.serviceWorker.register("./offline.js").then((registration) => {
      const installing = registration.installing;
      installing?.addEventListener("statechange", () => {
        if (installing.state === "redundant") cacheFailed();
      });
    }).catch(cacheFailed);
  } else $("offline").textContent = "Local only";
}
