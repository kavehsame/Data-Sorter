const fromBase64 = (value) => Uint8Array.fromBase64(value);
let pdfLibrary;

function moduleFrom(code) {
  return URL.createObjectURL(new Blob([fromBase64(code)], { type: "text/javascript" }));
}

async function loadPdfLibrary() {
  if (!pdfLibrary) {
    pdfLibrary = import(moduleFrom(VENDOR.pdf)).then((lib) => {
      const url = moduleFrom(VENDOR.pdfWorker);
      const port = new Worker(url, { name: "Local PDF preview" });
      URL.revokeObjectURL(url);
      return { lib, worker: new lib.PDFWorker({ port }) };
    });
  }
  return pdfLibrary;
}

class LocalPdfAssets {
  async fetch({ filename }) {
    if (!Object.hasOwn(VENDOR.pdfAssets, filename)) throw new Error("Missing bundled PDF resource " + filename);
    return fromBase64(VENDOR.pdfAssets[filename]);
  }
}

function decodeText(bytes) {
  if (bytes[0] === 255 && bytes[1] === 254) return new TextDecoder("utf-16le").decode(bytes);
  if (bytes[0] === 254 && bytes[1] === 255) return new TextDecoder("utf-16be").decode(bytes);
  try { return new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { return new TextDecoder("windows-1252").decode(bytes); }
}

async function wordText(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const data = fflate.unzipSync(bytes, { filter: ({ name, originalSize }) =>
    name === "word/document.xml" && originalSize <= 12_000_000 });
  if (!data["word/document.xml"]) throw new Error("The Word document has no readable text body.");
  const doc = new DOMParser().parseFromString(decodeText(data["word/document.xml"]), "application/xml");
  if (doc.querySelector("parsererror")) throw new Error("The Word document could not be read.");
  const ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
  const collect = (node) => {
    if (node.namespaceURI === ns) {
      if (node.localName === "t") return node.textContent;
      if (node.localName === "tab") return "\t";
      if (["br", "cr"].includes(node.localName)) return "\n";
    }
    return Array.from(node.children, collect).join("");
  };
  return Array.from(doc.getElementsByTagNameNS(ns, "p"), collect).filter(Boolean).join("\n\n") || "No text found.";
}

class Preview {
  constructor(viewport, surface, updateZoom) {
    Object.assign(this, { viewport, surface, updateZoom, zoom: 1, pages: [], pointers: new Map(), token: 0 });
    this.onScroll = () => this.schedulePages(30);
    viewport.addEventListener("scroll", this.onScroll, { passive: true });
    viewport.addEventListener("wheel", (event) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      this.setZoom(this.zoom * Math.exp(-event.deltaY * 0.012), this.point(event));
    }, { passive: false });
    viewport.addEventListener("gesturestart", (event) => { event.preventDefault(); this.gestureZoom = this.zoom; });
    viewport.addEventListener("gesturechange", (event) => {
      event.preventDefault();
      if (this.gestureZoom) this.setZoom(this.gestureZoom * event.scale, this.point(event));
    });
    viewport.addEventListener("gestureend", () => { this.gestureZoom = null; });
    viewport.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || (event.pointerType === "mouse" && !viewport.classList.contains("grabbable"))) return;
      event.preventDefault();
      this.pointers.set(event.pointerId, this.point(event));
      viewport.setPointerCapture(event.pointerId);
      viewport.classList.add("dragging");
    });
    viewport.addEventListener("pointermove", (event) => this.drag(event));
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
      viewport.addEventListener(type, (event) => {
        this.pointers.delete(event.pointerId);
        if (!this.pointers.size) viewport.classList.remove("dragging");
      });
    }
    new ResizeObserver(() => {
      if (!this.node && !this.pages.length) return;
      const anchor = this.anchor();
      this.layout();
      this.restoreAnchor(anchor);
      this.schedulePages(0);
    }).observe(viewport);
  }

  point(event) {
    const box = this.viewport.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  drag(event) {
    const last = this.pointers.get(event.pointerId);
    if (!last) return;
    const point = this.point(event);
    const other = Array.from(this.pointers).find(([id]) => id !== event.pointerId)?.[1];
    if (other && event.pointerType === "touch") {
      const distance = (p) => Math.hypot(p.x - other.x, p.y - other.y);
      if (distance(last) > 4) this.setZoom(this.zoom * distance(point) / distance(last),
        { x: (point.x + other.x) / 2, y: (point.y + other.y) / 2 });
    } else {
      this.viewport.scrollLeft += last.x - point.x;
      this.viewport.scrollTop += last.y - point.y;
    }
    this.pointers.set(event.pointerId, point);
  }

  anchor(point) {
    const view = this.viewport;
    point ||= { x: view.clientWidth / 2, y: view.clientHeight / 2 };
    const outer = view.getBoundingClientRect();
    const node = this.pages.find(({ box }) => box.getBoundingClientRect().bottom > outer.top + point.y)?.box ||
      this.pages.at(-1)?.box || this.node;
    if (!node) return null;
    const box = node.getBoundingClientRect();
    return { point, node, x: (outer.left + point.x - box.left) / (box.width || 1), y: (outer.top + point.y - box.top) / (box.height || 1) };
  }

  restoreAnchor(anchor) {
    if (!anchor) return;
    const { point, node, x, y } = anchor;
    const outer = this.viewport.getBoundingClientRect(), box = node.getBoundingClientRect();
    this.viewport.scrollLeft += box.left - outer.left + x * box.width - point.x;
    this.viewport.scrollTop += box.top - outer.top + y * box.height - point.y;
  }

  setZoom(value, point) {
    const zoom = Math.min(5, Math.max(1, value));
    if (zoom === this.zoom) return;
    const anchor = this.anchor(point);
    this.zoom = zoom;
    this.updateZoom(Math.round(zoom * 100));
    this.layout();
    this.restoreAnchor(anchor);
    if (zoom === 1) this.centre();
    this.schedulePages(115, true);
  }

  centre() {
    this.viewport.scrollLeft = (this.viewport.scrollWidth - this.viewport.clientWidth) / 2;
  }

  reset() {
    this.token += 1;
    clearTimeout(this.timer);
    for (const page of this.pages) page.render?.cancel();
    this.pages = [];
    this.task?.destroy().catch(() => {});
    this.task = null;
    if (this.dicomWorker) this.dicomWorker.terminate();
    this.cancelDicom?.();
    this.cancelDicom = null;
    this.dicomWorker = null;
    if (this.blob) URL.revokeObjectURL(this.blob);
    this.blob = null;
    this.node = null;
    this.zoomIdle = 0;
    this.pointers.clear();
    this.surface.replaceChildren();
    delete this.surface.dataset.image;
    this.viewport.classList.remove("grabbable", "dragging");
    this.viewport.scrollLeft = this.viewport.scrollTop = 0;
    return this.token;
  }

  message(text) {
    const node = document.createElement("p");
    node.className = "preview-message";
    node.textContent = text;
    this.surface.replaceChildren(node);
  }

  async show(session, entry) {
    const token = this.reset();
    this.message("Loading preview…");
    try {
      const file = await session.openFile(entry);
      if (this.token !== token) return;
      if (entry.ext === "pdf") { await this.showPdf(file, token); return; }
      let node;
      if (["jpg", "jpeg", "png"].includes(entry.ext)) {
        node = new Image();
        node.alt = entry.name;
        node.draggable = false;
        this.blob = URL.createObjectURL(file);
        node.src = this.blob;
        await node.decode();
      } else if (["dcm", "dicom"].includes(entry.ext)) {
        node = await this.showDicom(file, token);
      } else if (entry.ext === "docx") {
        node = this.documentText(await wordText(file));
      } else {
        const text = decodeText(new Uint8Array(await file.slice(0, 1_500_000).arrayBuffer()));
        node = entry.ext === "csv" ? this.csvTable(text, file.size > 1_500_000) : this.documentText(text.slice(0, 160_000));
        if (file.size > 1_500_000 || (entry.ext === "txt" && text.length > 160_000)) {
          node.append(document.createTextNode("\n\nPreview truncated."));
        }
      }
      if (this.token !== token || !node) return;
      this.node = node;
      if (node.matches("img, canvas")) {
        this.surface.dataset.image = "true";
        node.className = "image-preview";
      }
      this.surface.replaceChildren(node);
      this.layout();
      this.centre();
      if (this.surface.dataset.image) this.viewport.scrollTop = (this.viewport.scrollHeight - this.viewport.clientHeight) / 2;
    } catch (error) {
      if (this.token === token) {
        this.reset();
        this.message(absent(error) ? "The file could not be found in the selected folders." :
          "Preview unavailable. " + (error.message || "The file could not be opened."));
      }
    }
  }

  documentText(text) {
    const node = document.createElement("pre");
    node.className = "document";
    node.textContent = text || "Empty file.";
    return node;
  }

  csvTable(text, partial) {
    const rows = readCsv(text, 201, partial);
    if (!rows.length) return this.documentText("Empty CSV.");
    const node = document.createElement("div");
    node.className = "document";
    const table = document.createElement("table");
    const header = table.createTHead(), body = table.createTBody();
    rows.slice(0, 200).forEach((values, i) => {
      const row = (i === 0 ? header : body).insertRow();
      for (const value of values.slice(0, 40)) {
        const cell = document.createElement(i === 0 ? "th" : "td");
        if (i === 0) cell.scope = "col";
        cell.textContent = value.slice(0, 300);
        row.append(cell);
      }
    });
    node.append(table);
    if (rows.length > 200 || rows.some((row) => row.length > 40 || row.some((cell) => cell.length > 300))) {
      const truncation = document.createElement("p");
      truncation.textContent = "Preview truncated.";
      node.append(truncation);
    }
    return node;
  }

  async showDicom(file, token) {
    const bytes = await file.arrayBuffer();
    if (token !== this.token) return null;
    const url = URL.createObjectURL(new Blob([
      "(() => { const module = {exports:{}}; const require = (name) => {throw new Error('Unavailable module: ' + name);};\n",
      fromBase64(VENDOR.dicom), "\nself.daikon = module.exports; })();\n", fromBase64(VENDOR.dicomWorker),
    ], { type: "text/javascript" }));
    const worker = new Worker(url, { name: "Local DICOM preview" });
    URL.revokeObjectURL(url);
    this.dicomWorker = worker;
    return new Promise((resolve, reject) => {
      this.cancelDicom = () => resolve(null);
      worker.addEventListener("message", ({ data }) => {
        if (data.error) { reject(new Error(data.error)); return; }
        const canvas = document.createElement("canvas");
        canvas.width = data.width; canvas.height = data.height;
        canvas.getContext("2d").putImageData(new ImageData(data.pixels, data.width, data.height), 0, 0);
        resolve(canvas);
      }, { once: true });
      worker.addEventListener("error", (event) => reject(new Error(event.message || "The DICOM decoder stopped.")), { once: true });
      worker.postMessage(bytes, [bytes]);
    }).finally(() => {
      worker.terminate();
      if (this.dicomWorker === worker) { this.dicomWorker = null; this.cancelDicom = null; }
    });
  }

  async showPdf(file, token) {
    const [{ lib, worker }, data] = await Promise.all([loadPdfLibrary(), file.arrayBuffer()]);
    if (this.token !== token) return;
    this.task = lib.getDocument({
      data, worker, BinaryDataFactory: LocalPdfAssets, useWorkerFetch: false,
      cMapPacked: true, cMapUrl: "./", standardFontDataUrl: "./", wasmUrl: "./",
      useSystemFonts: false, isEvalSupported: false, enableXfa: false,
    });
    const pdf = await this.task.promise;
    if (this.token !== token) return;
    const first = await pdf.getPage(1);
    if (this.token !== token) return;
    const placeholders = document.createDocumentFragment();
    this.pages = Array.from({ length: pdf.numPages }, (_, index) => {
      const box = document.createElement("div");
      box.className = "pdf-page";
      box.setAttribute("aria-label", "Page " + (index + 1));
      const size = first.getViewport({ scale: 1 });
      placeholders.append(box);
      return { box, width: size.width, height: size.height, number: index + 1, pdf, page: index === 0 ? first : null };
    });
    this.surface.replaceChildren(placeholders);
    this.layout();
    this.centre();
    this.schedulePages(0);
    // Queue nearby pages first. Resolve the other pages' dimensions in small batches.
    for (let i = 1; i < this.pages.length && token === this.token; i += 12) {
      const batch = this.pages.slice(i, i + 12);
      await Promise.all(batch.map(async (item) => {
        item.page ||= await pdf.getPage(item.number);
        if (token !== this.token) return;
        if (item.width !== item.page.getViewport({ scale: 1 }).width || item.height !== item.page.getViewport({ scale: 1 }).height) {
          const anchor = this.anchor(), size = item.page.getViewport({ scale: 1 });
          item.width = size.width; item.height = size.height;
          this.layout();
          this.restoreAnchor(anchor);
        }
      }));
    }
  }

  layout() {
    const w = Math.max(32, this.viewport.clientWidth - 32), h = Math.max(32, this.viewport.clientHeight - 32);
    if (this.pages.length) {
      const fit = Math.min(w / this.pages[0].width, 1.55);
      for (const item of this.pages) {
        item.scale = Math.min(fit, w / item.width) * this.zoom;
        item.box.style.width = item.width * item.scale + "px";
        item.box.style.height = item.height * item.scale + "px";
      }
    } else if (this.node && this.surface.dataset.image) {
      const ratio = (this.node.naturalWidth || this.node.width) / (this.node.naturalHeight || this.node.height);
      const width = Math.min(w, h * ratio) * this.zoom;
      this.node.style.width = width + "px";
      this.node.style.height = width / ratio + "px";
    } else if (this.node) {
      this.node.style.fontSize = 13 * this.zoom + "px";
      this.node.style.setProperty("--doc-width", w * this.zoom + "px");
    }
    this.viewport.classList.toggle("grabbable", this.viewport.scrollWidth > this.viewport.clientWidth ||
      this.viewport.scrollHeight > this.viewport.clientHeight);
  }

  schedulePages(delay, zooming = false) {
    if (!this.pages.length) return;
    if (zooming) this.zoomIdle = performance.now() + delay;
    clearTimeout(this.timer);
    const token = this.token;
    this.timer = setTimeout(() => this.renderPages(token), Math.max(delay, (this.zoomIdle || 0) - performance.now()));
  }

  renderPages(token) {
    if (token !== this.token) return;
    const view = this.viewport.getBoundingClientRect();
    const near = [];
    for (const item of this.pages) {
      const box = item.box.getBoundingClientRect();
      const distance = Math.max(view.top - box.bottom, box.top - view.bottom, 0);
      if (distance < view.height * 0.65) near.push({ item, distance });
      if (distance > view.height * 2) {
        item.render?.cancel();
        item.box.replaceChildren();
        item.drawn = 0;
      }
    }
    near.sort((a, b) => a.distance - b.distance);
    let available = Math.max(0, 2 - this.pages.filter((item) => item.pending).length);
    for (const { item } of near) {
      const scale = Math.min(item.scale * window.devicePixelRatio, Math.sqrt(18_000_000 / (item.width * item.height)));
      if (Math.abs((item.drawn || 0) - scale) < 0.025 || item.pending) continue;
      if (available <= 0) break;
      available -= 1;
      this.drawPage(item, scale, token);
    }
  }

  async drawPage(item, scale, token) {
    item.pending = true;
    try {
      item.page ||= await item.pdf.getPage(item.number);
      if (token !== this.token) return;
      const viewport = item.page.getViewport({ scale });
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      item.render = item.page.render({ canvas, viewport });
      await item.render.promise;
      if (token === this.token) { item.box.replaceChildren(canvas); item.drawn = scale; }
    } catch (error) {
      if (token === this.token && error.name !== "RenderingCancelledException") {
        item.box.textContent = "Page " + item.number + " could not be rendered.";
        item.drawn = scale;
      }
    } finally {
      item.pending = false;
      item.render = null;
      if (token === this.token) this.schedulePages(20);
    }
  }
}
