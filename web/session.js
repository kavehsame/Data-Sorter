const EXTENSIONS = new Set(["jpg", "jpeg", "png", "dcm", "dicom", "pdf", "docx", "txt", "csv"]);
const RESULT_FILE = "data_sorter_results.csv";
const CSV_FIELDS = ("schema_version exported_at input_dir output_dir mode categories_json current_index total " +
  "image_index rel_path filename ext choice operation dest_rel_path original_path current_path dest_path").split(" ");
const extension = (name) => name.includes(".") ? name.split(".").pop().toLowerCase() : "";
const absent = (error) => error.name === "NotFoundError";
const fail = (message) => { throw new Error(message); };

function categoriesFrom(raw) {
  const names = new Set(), keys = new Set();
  if (!Array.isArray(raw) || !raw.length) fail("Add at least one category.");
  return raw.map((item) => {
    const name = String(item?.name ?? "").trim();
    const key = String(item?.key ?? "").trim().toLowerCase();
    const control = Array.from(name).some((char) => char.charCodeAt(0) < 32);
    if (!name || name === "." || name === ".." || /[/\\:*?"<>|]/.test(name) || control || name.endsWith(".")) {
      fail("Enter a valid folder name for each category.");
    }
    const folded = name.normalize("NFC").toLowerCase();
    if (names.has(folded)) fail("Category names must be unique.");
    if (!/^[\p{L}\p{N}\p{P}\p{S}]$/u.test(key) || keys.has(key)) fail("Use a different single character for each shortcut.");
    names.add(folded);
    keys.add(key);
    return { name, key };
  });
}

function readCsv(text, limit = Infinity, partial = false) {
  const rows = [];
  let row = [], value = "", quoted = false, closed = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char !== '"') value += char;
      else if (text[i + 1] === '"') { value += '"'; i += 1; }
      else { quoted = false; closed = true; }
      continue;
    }
    if (char === "," || char === "\r" || char === "\n") {
      row.push(value);
      value = "";
      closed = false;
      if (char === ",") continue;
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      rows.push(row);
      if (rows.length === limit) return rows;
      row = [];
    } else if (char === '"' && !value && !closed) {
      quoted = true;
    } else {
      if (closed || char === '"') fail("The CSV contains an invalid field.");
      value += char;
    }
  }
  if (partial) return rows;
  if (quoted) fail("The CSV contains an unfinished quoted field.");
  if (row.length || value || closed) rows.push([...row, value]);
  return rows;
}

function safePath(value) {
  const parts = String(value || "").replaceAll("\\", "/").split("/");
  if (parts.some((part) => !part || part === "." || part === ".." || part.includes(":") || part.includes("\0"))) {
    fail("The session CSV contains an unsafe relative path.");
  }
  return parts;
}

function readSession(text) {
  const [header, ...raw] = readCsv(text);
  if (!header || new Set(header).size !== header.length ||
      !["schema_version", "categories_json", "mode", "rel_path", "choice"].every((name) => header.includes(name))) {
    fail("Choose a Data Sorter session CSV.");
  }
  const rows = raw.filter((row) => row.some(Boolean)).map((row) => {
    if (row.length !== header.length) fail("A session CSV row has the wrong number of fields.");
    return Object.fromEntries(header.map((key, i) => [key, row[i]]));
  });
  const first = rows[0];
  if (!first || !rows.every((row) => row.schema_version === "1")) fail("The session CSV version is unsupported.");
  if (!["copy", "move"].includes(first.mode)) fail("The session CSV has an invalid file operation.");
  const categories = categoriesFrom(JSON.parse(first.categories_json));
  const seen = new Set(), destinations = new Set(), names = new Set(categories.map((entry) => entry.name));
  const entries = rows.toSorted((a, b) => Number(a.image_index) - Number(b.image_index)).map((row) => {
    const original = safePath(row.rel_path);
    const name = original.at(-1), ext = extension(name), choice = row.choice || "";
    if (seen.has(original.join("/")) || !EXTENSIONS.has(ext)) fail("The session CSV contains a duplicate or unsupported file.");
    seen.add(original.join("/"));
    if (choice && (!names.has(choice) || !["copy", "move"].includes(row.operation))) {
      fail("The session CSV contains an invalid sorting decision.");
    }
    const destination = choice ? safePath(row.dest_rel_path || choice + "/" + name) : null;
    if (destination && (destination.length !== 2 || destination[0] !== choice || destinations.has(destination.join("/")))) {
      fail("The session CSV contains an invalid or repeated output path.");
    }
    if (destination) destinations.add(destination.join("/"));
    return { original, name, ext, choice, destination, operation: choice ? row.operation : "" };
  });
  const index = Number.parseInt(first.current_index, 10) || 0;
  return { categories, entries, mode: first.mode, index: Math.max(0, Math.min(index, entries.length - 1)) };
}

function encodeSession(session) {
  const { input, output, categories, mode, index, entries } = session;
  const line = (values) => values.map((value) => '"' + String(value ?? "").replaceAll('"', '""') + '"').join(",");
  const clock = new Date().toISOString();
  return [CSV_FIELDS.join(","), ...entries.map((entry, i) => {
    const original = entry.original.join("/");
    const destination = entry.destination?.join("/") || "";
    const inputPath = input.name + "/" + original;
    const outputPath = destination ? output.name + "/" + destination : "";
    return line(["1", clock, input.name, output.name, mode, JSON.stringify(categories), index, entries.length,
      i, original, entry.name, "." + entry.ext, entry.choice, entry.operation, destination,
      inputPath, entry.operation === "move" ? outputPath : inputPath, outputPath]);
  })].join("\r\n") + "\r\n";
}

async function findEntries(input, output) {
  const entries = [];
  async function walk(folder, path) {
    for await (const handle of folder.values()) {
      if (handle.kind === "directory") {
        if (!await handle.isSameEntry(output)) await walk(handle, [...path, handle.name]);
      } else {
        const ext = extension(handle.name);
        if (EXTENSIONS.has(ext)) {
          entries.push({ original: [...path, handle.name], name: handle.name, ext, choice: "", destination: null, operation: "" });
        }
      }
    }
  }
  await walk(input, []);
  entries.sort((a, b) => a.original.join("/").localeCompare(b.original.join("/"), "en", { sensitivity: "base" }));
  if (!entries.length) fail("No supported files were found in the input folder.");
  return entries;
}

async function directory(root, parts, create = false) {
  let current = root;
  for (const name of parts) current = await current.getDirectoryHandle(name, { create });
  return current;
}

async function fileLocation(root, parts, createDir = false) {
  return { dir: await directory(root, parts.slice(0, -1), createDir), name: parts.at(-1) };
}

async function existingLocation(root, parts) {
  try {
    return await fileLocation(root, parts);
  } catch (error) {
    if (absent(error)) return null;
    throw error;
  }
}

async function lookup({ dir, name }) {
  try {
    return await dir.getFileHandle(name);
  } catch (error) {
    if (absent(error)) return null;
    if (error.name === "TypeMismatchError") fail("A folder already uses the name " + name + ".");
    throw error;
  }
}

async function unusedName(dir, name) {
  const occupied = new Set();
  for await (const entry of dir.values()) occupied.add(entry.name.normalize("NFC").toLowerCase());
  const taken = (candidate) => occupied.has(candidate.normalize("NFC").toLowerCase());
  if (!taken(name)) return name;
  const dot = name.lastIndexOf(".");
  for (let i = 2; ; i += 1) {
    const candidate = name.slice(0, dot) + "_" + i + name.slice(dot);
    if (!taken(candidate)) return candidate;
  }
}

async function writeFile(dir, name, data, replace = false) {
  const previous = await lookup({ dir, name });
  if (previous && !replace) fail("A file already exists at " + name + ".");
  const handle = previous || await dir.getFileHandle(name, { create: true });
  let stream;
  try {
    stream = await handle.createWritable({ mode: "exclusive" });
    if (data instanceof Blob) await data.stream().pipeTo(stream);
    else { await stream.write(data); await stream.close(); }
  } catch (error) {
    if (stream && !stream.locked) await stream.abort().catch(() => {});
    if (!previous) {
      const current = await handle.getFile().catch(() => null);
      if (current?.size === 0) await dir.removeEntry(name).catch(() => {});
    }
    throw error;
  }
  return handle;
}

async function bytesEqual(a, b) {
  if (a.size !== b.size) return false;
  const block = 2 * 1024 * 1024;
  for (let offset = 0; offset < a.size; offset += block) {
    const [left, right] = await Promise.all([a, b].map(async (file) =>
      new Uint8Array(await file.slice(offset, offset + block).arrayBuffer())));
    if (left.some((value, index) => value !== right[index])) return false;
  }
  return true;
}

class SortSession {
  constructor(input, output, settings) {
    Object.assign(this, { input, output, history: [], ...settings });
  }

  async openFile(entry) {
    const moved = entry.operation === "move";
    try {
      const { dir, name } = await fileLocation(moved ? this.output : this.input, moved ? entry.destination : entry.original);
      return await (await dir.getFileHandle(name)).getFile();
    } catch (error) {
      if (!absent(error) || entry.operation !== "copy") throw error;
      const { dir, name } = await fileLocation(this.output, entry.destination);
      return (await dir.getFileHandle(name)).getFile();
    }
  }

  async change(entry, desired) {
    const old = entry.destination ? await existingLocation(this.output, entry.destination) : null;
    const oldHandle = old ? await lookup(old) : null;
    if (entry.operation === "move" && !oldHandle) fail("The moved file is missing from the output folder.");
    const original = entry.operation === "move" && desired.operation !== "move" ?
      await fileLocation(this.input, entry.original, true) : await existingLocation(this.input, entry.original);
    const originalHandle = original ? await lookup(original) : null;
    if (entry.operation === "move" && originalHandle) fail("A file already exists in the original location.");
    if (entry.operation !== "move" && !originalHandle) fail("The original file is missing from the input folder.");
    const sourceHandle = entry.operation === "move" ? oldHandle : originalHandle;
    const data = await sourceHandle.getFile();
    const oldData = oldHandle ? await oldHandle.getFile() : null;
    if (oldData && entry.operation === "copy" && !await bytesEqual(data, oldData)) {
      fail("The existing sorted copy differs from the original.");
    }
    const writes = [];
    let oldCopyRemoved = false;
    try {
      if (entry.operation === "move" && desired.operation !== "move") {
        await this.stageFile(original, data, writes);
      }
      if (desired.destination) {
        const target = await fileLocation(this.output, desired.destination, true);
        await this.stageFile(target, data, writes);
      }
      if (entry.operation === "move" || desired.operation === "move") {
        for (const { snapshot } of writes) {
          if (!await bytesEqual(data, snapshot)) fail("The destination failed verification. The source was retained.");
        }
      }
      if (desired.operation === "move" && entry.operation !== "move") {
        if (oldHandle) {
          await this.removeChecked(old, oldHandle, oldData);
          oldCopyRemoved = true;
        }
        await this.removeChecked(original, originalHandle, data);
      } else if (oldHandle) {
        await this.removeChecked(old, oldHandle, oldData);
      }
    } catch (error) {
      // A verified new file supplies the rollback bytes after the old copy has been removed.
      if (oldCopyRemoved) {
        try {
          await writeFile(old.dir, old.name, await writes.at(-1).handle.getFile());
        } catch {
          fail(error.message + " The previous copy could not be restored. The new file was retained.");
        }
      }
      let remains = false;
      for (const written of writes.toReversed()) {
        try {
          await this.removeChecked(written, written.handle, written.snapshot);
        } catch { remains = true; }
      }
      if (remains) fail(error.message + " A new copy could not be removed. Check both selected folders.");
      throw error;
    }
    Object.assign(entry, desired);
  }

  async stageFile(place, data, writes) {
    const handle = await writeFile(place.dir, place.name, data);
    const record = { ...place, handle, snapshot: null };
    writes.push(record);
    record.snapshot = await handle.getFile();
  }

  async removeChecked(place, handle, snapshot) {
    const current = await lookup(place);
    if (!current || !await current.isSameEntry(handle)) fail("The file changed during sorting.");
    const file = await current.getFile();
    if (!snapshot || file.size !== snapshot.size || file.lastModified !== snapshot.lastModified) fail("The file changed during sorting.");
    await place.dir.removeEntry(place.name);
  }

  async choose(choice) {
    const entry = this.entries[this.index];
    if (entry.choice !== choice || entry.operation !== this.mode) {
      const dir = await directory(this.output, [choice], true);
      const name = await unusedName(dir, entry.name);
      const before = { choice: entry.choice, destination: entry.destination, operation: entry.operation };
      await this.change(entry, { choice, destination: [choice, name], operation: this.mode });
      this.history.push({ index: this.index, before });
    }
    this.index = Math.min(this.index + 1, this.entries.length - 1);
  }

  async undo() {
    const record = this.history.at(-1);
    if (!record) return;
    await this.change(this.entries[record.index], record.before);
    this.history.pop();
    this.index = record.index;
  }

  async saveCsv() {
    await writeFile(this.output, RESULT_FILE, encodeSession(this), true);
  }
}
