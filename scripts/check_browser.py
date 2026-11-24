"""Exercise the release in desktop Chrome using synthetic files and browser-owned folders."""

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import fitz
import numpy as np
import websocket
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, RLELossless, SecondaryCaptureImageStorage, generate_uid

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist"
MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def fixtures():
    pdf = fitz.open()
    for index in range(3):
        page = pdf.new_page(width=420, height=500)
        page.insert_text((36, 44), f"Data Sorter PDF test page {index + 1}", fontsize=22)
        page.draw_rect((36, 75, 320, 340), color=(0.08, 0.3, 0.2), width=4, fill=(0.88, 0.95, 0.9))
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Local Word preview</w:t></w:r></w:p></w:body></w:document>',
        )
    png = io.BytesIO()
    Image.new("RGB", (220, 160), "#469981").save(png, format="PNG")
    jpg = io.BytesIO()
    Image.new("RGB", (220, 160), "#353c90").save(jpg, format="JPEG")
    metadata = FileMetaDataset()
    metadata.TransferSyntaxUID = ExplicitVRLittleEndian
    metadata.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    metadata.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset(None, {}, file_meta=metadata, preamble=bytes(128))
    ds.Rows, ds.Columns, ds.SamplesPerPixel = 32, 32, 1
    ds.PhotometricInterpretation = "MONOCHROME1"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.PixelData = np.arange(-512, 512, dtype="<i2").tobytes()
    dcm = io.BytesIO()
    ds.save_as(dcm, enforce_file_format=True)
    ds.compress(RLELossless)
    compressed = io.BytesIO()
    ds.save_as(compressed, enforce_file_format=True)
    samples = {
        "01-image.png": png.getvalue(),
        "02-paper.pdf": pdf.tobytes(),
        "03-grid.csv": b'Name,Note\r\nAlpha,"line 1\nline 2"\r\n',
        "04-word.docx": docx.getvalue(),
        "05-dicom.dcm": dcm.getvalue(),
        "06-text.txt": b"Offline text review\n" * 250,
        "07-rle.dcm": compressed.getvalue(),
        "08-image.jpg": jpg.getvalue(),
    }
    samples.update({f"{i:02d}-sample.txt": b"Sorting test fixture" for i in range(9, 21)})
    return {name: encoded(data) for name, data in samples.items()}


class Browser:
    def __init__(self, endpoint):
        self.ws = websocket.create_connection(endpoint, suppress_origin=True, timeout=14)
        self.number = 0
        self.errors = []
        self.command("Runtime.enable")
        self.command("Log.enable")
        self.command("Page.enable")
        self.command("Network.enable")

    def command(self, method, **params):
        self.number += 1
        self.ws.send(json.dumps({"id": self.number, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("method") == "Runtime.exceptionThrown" or (
                message.get("method") == "Log.entryAdded" and message["params"]["entry"]["level"] == "error"
            ):
                self.errors.append(message["params"])
            if message.get("id") == self.number:
                if "error" in message:
                    raise AssertionError(message["error"])
                return message.get("result", {})

    def js(self, expression):
        result = self.command(
            "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
        )
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            raise AssertionError(detail.get("exception", {}).get("description", detail["text"]))
        return result["result"].get("value")

    def expect(self, expression, label):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                if self.js(expression):
                    print("PASS", label, flush=True)
                    return
            except AssertionError as error:
                if "context" not in str(error).lower():
                    raise
            time.sleep(0.075)
        raise AssertionError(
            label
            + " timed out: "
            + str(
                self.js(
                    "({setup: document.querySelector('#setupStatus')?.textContent, preview: document.querySelector('#surface')?.textContent, offline: document.querySelector('#offline')?.textContent, script: document.querySelector('script')?.textContent.length, picker: typeof showDirectoryPicker})"
                )
            )
            + "\n"
            + json.dumps(self.errors, indent=2)
        )

    def click(self, name):
        self.js(f"document.getElementById({json.dumps(name)}).click()")


def prepare_folders(browser, entries, portable=False):
    if portable:
        # Chrome restricts origin-private storage for file URLs. Use in-memory
        # handles here to exercise the same UI and workers in the portable page.
        browser.js("""
        class TestDirectory {
          constructor(name) { this.name = name; this.kind = 'directory'; this.children = new Map(); }
          async *values() { yield* this.children.values(); }
          async isSameEntry(other) { return other === this; }
          async resolve() { return null; }
          async getFileHandle(name, {create} = {}) {
            if (!this.children.has(name) && create) {
              const file = {
                name, kind:'file', data:new File([], name),
                async getFile() { return this.data; },
                async createWritable() {
                  const parts = [];
                  return new WritableStream({write: part => parts.push(part), close: () => {
                    this.data = new File(parts, name);
                  }});
                }
              };
              this.children.set(name, file);
            }
            if (!this.children.has(name)) throw new DOMException('Missing file', 'NotFoundError');
            return this.children.get(name);
          }
          async getDirectoryHandle(name, {create} = {}) {
            if (!this.children.has(name) && create) this.children.set(name, new TestDirectory(name));
            if (!this.children.has(name)) throw new DOMException('Missing directory', 'NotFoundError');
            return this.children.get(name);
          }
        }
        window.qaRoot = new TestDirectory('qa-root');
        """)
    browser.js(
        """
    (async () => {
        const root = window.qaRoot || await navigator.storage.getDirectory();
        window.qaIn = await root.getDirectoryHandle('qa-input', {create: true});
        window.qaOut = await root.getDirectoryHandle('qa-output', {create: true});
        window.showDirectoryPicker = async ({id}) => id.endsWith('input') ? qaIn : qaOut;
        for (const [name, data] of Object.entries(SAMPLES)) {
            const handle = await qaIn.getFileHandle(name, {create: true});
            const writable = await handle.createWritable();
            await new Blob([Uint8Array.fromBase64(data)]).stream().pipeTo(writable);
        }
        window.qaExists = async (root, name, folder) => {
            try {
                const dir = folder ? await root.getDirectoryHandle(folder) : root;
                return Boolean(await dir.getFileHandle(name));
            } catch (error) { if (error.name === 'NotFoundError') return false; throw error; }
        };
        window.qaButton = (index) => document.querySelectorAll('#actions button')[index];
    })()
    """.replace("SAMPLES", json.dumps(entries))
    )


def browse_and_start(browser, mode="copy"):
    browser.js(f'document.querySelector("[value={mode}]").click()')
    browser.click("input")
    browser.expect(
        "document.getElementById('inputName').textContent === 'qa-input'", "input handle selected"
    )
    browser.click("output")
    browser.expect(
        "document.getElementById('outputName').textContent === 'qa-output'", "output handle selected"
    )
    browser.click("start")
    browser.expect("!document.getElementById('workspace').hidden", "review session opened")


def check_release(browser, url, stop_server, screenshot):
    browser.command("Page.navigate", url=url)
    browser.expect(
        "window.showDirectoryPicker && document.querySelectorAll('.category-row').length === 3",
        "release starts in Chrome",
    )
    browser.expect(
        "document.getElementById('offline').textContent === 'Offline ready'", "page cached and controlled"
    )
    stop_server()
    browser.command(
        "Network.emulateNetworkConditions",
        offline=True,
        latency=0,
        downloadThroughput=-1,
        uploadThroughput=-1,
    )
    browser.command("Page.reload")
    browser.expect(
        "document.getElementById('offline')?.textContent === 'Offline ready' && document.querySelectorAll('.category-row').length === 3",
        "offline reload starts",
    )
    prepare_folders(browser, fixtures())
    browse_and_start(browser)
    browser.expect("document.querySelector('.image-preview')?.naturalWidth === 220", "PNG preview")
    browser.js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key:'1', bubbles:true}))")
    browser.expect("qaExists(qaOut, '01-image.png', 'Category A')", "keyboard copy writes category file")
    browser.expect("qaExists(qaIn, '01-image.png')", "copy retains source")
    browser.expect("document.querySelector('.pdf-page canvas')?.width > 100", "PDF renders offline")
    width = browser.js("document.querySelector('.pdf-page canvas').width")
    browser.js(
        "document.getElementById('zoom').value = '245'; document.getElementById('zoom').dispatchEvent(new Event('input'))"
    )
    browser.expect(
        f"document.querySelector('.pdf-page canvas')?.width > {width * 1.8}",
        "PDF rerasterises at higher resolution",
    )
    browser.expect(
        "(() => { const v=document.querySelector('#viewport'), p=document.querySelector('.pdf-page'); return Math.abs((p.getBoundingClientRect().left + p.getBoundingClientRect().right) / 2 - (v.getBoundingClientRect().left + v.clientWidth / 2)) < 3 })()",
        "PDF zoom stays centred",
    )
    position = browser.js("""(() => {
        const v = document.querySelector('#viewport'), r = v.getBoundingClientRect();
        return {x: r.left + v.clientWidth/2, y: r.top + v.clientHeight/2, left: v.scrollLeft, top: v.scrollTop};
    })()""")
    x, y = position["x"], position["y"]
    browser.command(
        "Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", buttons=1, clickCount=1
    )
    browser.command(
        "Input.dispatchMouseEvent", type="mouseMoved", x=x - 85, y=y - 95, button="left", buttons=1
    )
    browser.command(
        "Input.dispatchMouseEvent",
        type="mouseReleased",
        x=x - 85,
        y=y - 95,
        button="left",
        buttons=0,
        clickCount=1,
    )
    browser.expect(
        f"(() => {{const v=document.querySelector('#viewport');return v.scrollTop>{position['top'] + 65} && v.scrollLeft>{position['left'] + 60}}})()",
        "drag pans PDF on both axes",
    )
    browser.command(
        "Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=-24, modifiers=2
    )
    browser.expect(
        "document.getElementById('zoom').valueAsNumber > 245", "trackpad-style wheel zoom updates slider"
    )
    browser.js(
        "document.getElementById('viewport').scrollTop = document.getElementById('viewport').scrollHeight"
    )
    browser.expect(
        "document.querySelector('.pdf-page:last-child canvas')?.width > 100",
        "last PDF page renders on scroll",
    )
    browser.click("fit")
    browser.js("document.getElementById('viewport').scrollTop = 0")
    browser.expect(
        "document.querySelector('.pdf-page canvas')?.width > 100", "first PDF page redraws when revisited"
    )
    result = browser.command("Page.captureScreenshot", format="png")
    screenshot.write_bytes(base64.b64decode(result["data"]))
    for ext, expression in [
        ("CSV", "document.querySelector('td')?.textContent === 'Alpha'"),
        ("DOCX", "document.querySelector('pre.document')?.textContent === 'Local Word preview'"),
        ("DICOM", "document.querySelector('canvas.image-preview')?.width === 32"),
        ("TXT", "document.querySelector('pre.document')?.textContent.startsWith('Offline text review')"),
        ("RLE DICOM", "document.querySelector('canvas.image-preview')?.width === 32"),
        ("JPEG", "document.querySelector('.image-preview')?.naturalWidth === 220"),
    ]:
        browser.click("next")
        browser.expect(expression, ext + " preview")
    browser.click("undo")
    browser.expect(
        "document.getElementById('currentTitle').textContent === '01-image.png'",
        "undo returns to changed file",
    )
    browser.expect(
        "qaExists(qaOut, '01-image.png', 'Category A').then(exists => !exists)", "undo removes sorted copy"
    )
    browser.js("qaButton(0).click()")
    browser.expect("!document.getElementById('export').disabled", "choice complete")
    browser.click("export")
    browser.expect("qaExists(qaOut, 'data_sorter_results.csv')", "CSV exported to output root")
    browser.click("configure")
    browser.js("""
    (async () => {
      const handle = await qaOut.getFileHandle('data_sorter_results.csv');
      const transfer = new DataTransfer();
      transfer.items.add(await handle.getFile());
      const input = document.getElementById('importFile');
      input.files = transfer.files;
      input.dispatchEvent(new Event('change'));
    })()
    """)
    browser.expect(
        "document.getElementById('start').textContent.includes('Restore session')", "CSV can be imported"
    )
    browser.click("start")
    browser.expect(
        "document.getElementById('progressText').textContent === '1 of 20 sorted' && document.getElementById('currentTitle').textContent === '02-paper.pdf'",
        "CSV restores decision and position",
    )
    browser.click("undecided")
    browser.expect(
        "document.querySelectorAll('.file-row').length === 19", "undecided filter excludes sorted file"
    )
    browser.js("document.querySelectorAll('.file-row')[13].click()")
    browser.expect("document.getElementById('fileList').scrollTop > 100", "file queue auto-scrolls")
    browser.expect(
        "(() => { const list = document.getElementById('fileList'), rows = Array.from(list.querySelectorAll('.file-row')), start = rows.findIndex(r => r.getAttribute('aria-current') === 'true'), bounds = list.getBoundingClientRect(); return start >= 0 && rows.slice(start,start+4).every(r=>{const b=r.getBoundingClientRect(); return b.top>=bounds.top && b.bottom<=bounds.bottom}) })()",
        "four pending files visible",
    )
    browser.click("configure")
    browser.js("document.querySelector('[value=move]').click()")
    browser.click("start")
    browser.expect(
        "document.getElementById('modeBadge').textContent === 'Move' && !document.getElementById('workspace').hidden",
        "move session opened",
    )
    browser.js("qaButton(1).click()")
    browser.expect(
        "(async () => await qaExists(qaOut, '01-image.png', 'Category B') && !await qaExists(qaIn, '01-image.png'))()",
        "move writes destination and removes source",
    )
    browser.click("undo")
    browser.expect("qaExists(qaIn, '01-image.png')", "move undo restores source")
    browser.expect(
        "qaExists(qaOut, '01-image.png', 'Category B').then(exists => !exists)",
        "move undo removes destination",
    )
    browser.command(
        "Emulation.setDeviceMetricsOverride", width=390, height=750, deviceScaleFactor=1, mobile=False
    )
    browser.expect(
        "document.querySelector('#viewport').clientWidth > 180 && document.body.scrollWidth === innerWidth",
        "narrow viewport keeps workspace readable",
    )
    browser.command("Emulation.clearDeviceMetricsOverride")


def main():
    work = ROOT / ".checks"
    if work.resolve() != work:
        raise ValueError("Browser checks must remain inside the project.")
    work.mkdir(exist_ok=True)
    chrome_bin = os.environ.get("CHROME_BIN") or shutil.which("google-chrome") or str(MAC_CHROME)
    if not Path(chrome_bin).is_file():
        raise FileNotFoundError("Set CHROME_BIN to the Chrome executable.")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=OUT / "website")
    )

    def stop_server():
        server.shutdown()
        server.server_close()

    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="chrome-", dir=work) as profile:
            env = {**os.environ, "TMPDIR": profile}
            with subprocess.Popen(
                [
                    chrome_bin,
                    "--headless",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-breakpad",
                    "--disable-crash-reporter",
                    "--remote-debugging-port=0",
                    "--window-size=1380,870",
                    f"--user-data-dir={profile}",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            ) as chrome:
                try:
                    port_file = Path(profile, "DevToolsActivePort")
                    for _ in range(150):
                        if port_file.exists():
                            break
                        time.sleep(0.1)
                    port = port_file.read_text().splitlines()[0]
                    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                        page = json.load(response)[0]
                    browser = Browser(page["webSocketDebuggerUrl"])
                    check_release(
                        browser,
                        f"http://127.0.0.1:{server.server_port}/",
                        stop_server,
                        work / "preview.png",
                    )
                    browser.command("Page.navigate", url=(OUT / "Data Sorter.html").as_uri())
                    browser.expect(
                        "location.protocol === 'file:' && window.showDirectoryPicker && document.querySelectorAll('.category-row').length === 3",
                        "standalone HTML opens offline with folder picker API",
                    )
                    samples = fixtures()
                    prepare_folders(
                        browser,
                        {name: samples[name] for name in ("01-image.png", "02-paper.pdf")},
                        portable=True,
                    )
                    browse_and_start(browser)
                    browser.expect(
                        "document.querySelector('.image-preview')?.naturalWidth === 220",
                        "standalone PNG preview",
                    )
                    browser.js("qaButton(0).click()")
                    browser.expect(
                        "qaExists(qaOut, '01-image.png', 'Category A')",
                        "standalone copy writes destination",
                    )
                    browser.expect(
                        "document.querySelector('.pdf-page canvas')?.width > 100",
                        "standalone PDF renders offline",
                    )
                    if browser.errors:
                        raise AssertionError(json.dumps(browser.errors, indent=2))
                finally:
                    chrome.terminate()
                    chrome.wait(12)
    finally:
        stop_server()


if __name__ == "__main__":
    main()
