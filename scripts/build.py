"""Build the self-contained page and its optional HTTPS offline cache."""

import base64
import hashlib
import json
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VENDOR = WEB / "vendor"
OUTPUT = ROOT / "dist"


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def key(path):
    return encoded(path.read_bytes())


def classic_pdf_worker(path):
    """Load the pinned PDF.js worker on HTTP and on opaque file origins."""
    content = path.read_text()
    export = "export{WorkerMessageHandler};"
    if not content.rstrip().endswith(export) or content.count("import.meta.url") != 2:
        raise ValueError("Check the PDF.js worker entry point before updating the bundled version.")
    content = content.rstrip().removesuffix(export).replace("import.meta.url", "self.location.href")
    notice = "// Modified by Data Sorter: load PDF.js as a classic worker, including on file URLs.\n"
    return encoded((notice + content).encode())


def build(output=OUTPUT):
    output = output.absolute()
    website = output / "website"
    if website.resolve() != website or not output.is_relative_to(ROOT):
        raise ValueError("Build outputs must remain in the project.")
    website.mkdir(parents=True, exist_ok=True)
    pdf = VENDOR / "pdfjs-dist"
    icon = "data:image/png;base64," + key(WEB / "data_sorter_icon.png")
    assets = {
        asset.name: key(asset)
        for folder in ("cmaps", "standard_fonts", "wasm", "iccs")
        for asset in sorted((pdf / folder).iterdir())
        if not asset.name.startswith("LICENSE")
    }
    vendor = dict(
        pdf=key(pdf / "build/pdf.min.mjs"),
        pdfWorker=classic_pdf_worker(pdf / "build/pdf.worker.min.mjs"),
        pdfAssets=assets,
        dicom=key(VENDOR / "daikon/release/current/daikon-min.js"),
        dicomWorker=key(WEB / "dicom_worker.js"),
    )
    icons = {
        svg.stem: svg.read_text().replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1).strip()
        for svg in sorted((VENDOR / "lucide-static/icons").glob("*.svg"))
    }
    boot = "\n".join(
        [
            "const VENDOR = " + json.dumps(vendor, separators=(",", ":")) + ";",
            "const ICONS = " + json.dumps({name: icons[name] for name in ("x", "check")}) + ";",
            (VENDOR / "fflate/umd/index.js").read_text(),
            ";(() => {",
            *((WEB / name).read_text("utf-8") for name in ("session.js", "preview.js", "app.js")),
            "})();",
        ]
    )
    if "</script" in boot.lower() or "\r" in boot:
        raise ValueError("The bundled script must stay valid inside an HTML script element.")
    licenses = "\n\n".join(
        str(asset.relative_to(VENDOR)) + "\n" + asset.read_text(errors="replace")
        for asset in sorted(VENDOR.rglob("*"))
        if asset.is_file() and asset.name.lower().startswith(("license", "notice"))
    )
    app_license = (ROOT / "LICENSE").read_text("utf-8")
    template = (WEB / "index.template.html").read_text("utf-8")
    context = {
        **icons,
        "ICON": icon,
        "STYLE": (WEB / "style.css").read_text("utf-8"),
        "BOOT": boot,
        "OFFLINE": "Local workspace",
        "LICENSES": escape(app_license + "\n\n" + licenses),
        "SCRIPT_HASH": "'sha256-" + encoded(hashlib.sha256(boot.encode()).digest()) + "'",
    }
    page = re.sub(r"@@([\w-]+)@@", lambda match: context[match[1]], template).encode()
    digest = hashlib.sha256(page).hexdigest()
    worker = (
        (WEB / "offline.template.js")
        .read_text("utf-8")
        .replace("@@VERSION@@", digest[:16])
        .replace("@@DIGEST@@", digest)
    )
    files = {
        website / "index.html": page,
        website / "offline.js": worker.encode(),
        website / "THIRD_PARTY_NOTICES.txt": licenses.encode(),
        website / "LICENSE": app_license.encode(),
        output / "Data Sorter.html": page,
    }
    for target, data in files.items():
        if target.resolve() != target:
            raise ValueError(f"Unexpected symbolic link at {target}.")
        target.write_bytes(data)
    print("Page size:", len(page), "bytes")
    print("Page SHA-256:", digest)


if __name__ == "__main__":
    build()
