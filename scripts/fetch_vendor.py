"""Retrieve pinned browser libraries and verify their npm integrity hashes."""

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path
from urllib.request import urlopen

VENDOR = Path(__file__).resolve().parent.parent / "web" / "vendor"
PACKAGES = {
    "pdfjs-dist": "6.5.438",
    "daikon": "1.2.46",
    "fflate": "0.8.3",
    "lucide-static": "1.79.0",
}
FONT_URL = (
    "https://github.com/liberationfonts/liberation-fonts/files/7261482/liberation-fonts-ttf-2.1.5.tar.gz"
)
FONT_SHA256 = "7191c669bf38899f73a2094ed00f7b800553364f90e2637010a69c0e268f25d0"
FONT_STYLES = ("Regular", "Italic", "Bold", "BoldItalic")


def wanted(name, path):
    if (
        name == "pdfjs-dist"
        and path.parent == Path("standard_fonts")
        and path.name.startswith(("LiberationSans-", "LICENSE_LIBERATION"))
    ):
        return False
    if path.name.lower().startswith(("license", "notice")):
        return True
    if name == "pdfjs-dist":
        return str(path) in {"build/pdf.min.mjs", "build/pdf.worker.min.mjs"} or (
            path.parts[0] in {"cmaps", "standard_fonts", "wasm", "iccs"}
            and path.suffix in {".bcmap", ".pfb", ".ttf", ".wasm", ".icc", ".js", ".mjs"}
        )
    if name == "daikon":
        return str(path) == "release/current/daikon-min.js"
    if name == "fflate":
        return str(path) == "umd/index.js"
    return (
        path.parts[0] == "icons"
        and path.suffix == ".svg"
        and path.stem
        in {
            "arrow-left",
            "arrow-right",
            "check",
            "chevrons-up-down",
            "circle-help",
            "download",
            "file",
            "file-image",
            "file-text",
            "folder-open",
            "folder-output",
            "hard-drive-download",
            "image",
            "list-filter",
            "lock-keyhole",
            "maximize",
            "minus",
            "plus",
            "rotate-ccw",
            "settings-2",
            "x",
            "scan-line",
            "upload",
        }
    )


def write_asset(target, data):
    if target.resolve() != target:
        raise ValueError(f"Unexpected symbolic link at {target}.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def fetch_fonts(vendor):
    with urlopen(FONT_URL, timeout=40) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != FONT_SHA256:
        raise ValueError("Integrity mismatch for Liberation Fonts 2.1.5.")
    standard = vendor / "pdfjs-dist" / "standard_fonts"
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for name in [*(f"LiberationSans-{style}.ttf" for style in FONT_STYLES), "LICENSE"]:
            source = tar.getmember(f"liberation-fonts-ttf-2.1.5/{name}")
            if not source.isfile():
                raise ValueError(f"Missing Liberation asset: {name}.")
            target = "LICENSE_LIBERATION" if name == "LICENSE" else name
            write_asset(standard / target, tar.extractfile(source).read())
    print("Liberation Fonts 2.1.5: 5 verified files")


def main():
    vendor = VENDOR
    if vendor.resolve() != vendor:
        raise ValueError("Vendor files must remain in the source folder.")
    for name, version in PACKAGES.items():
        with urlopen(f"https://registry.npmjs.org/{name}/{version}", timeout=30) as response:
            metadata = json.load(response)
        dist = metadata["dist"]
        with urlopen(dist["tarball"], timeout=40) as response:
            archive = response.read()
        digest = base64.b64encode(hashlib.sha512(archive).digest()).decode("ascii")
        if dist["integrity"] != f"sha512-{digest}":
            raise ValueError(f"Integrity mismatch for {name}.")
        count = 0
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for member in tar:
                relative = Path(member.name)
                if (
                    not member.isfile()
                    or relative.parts[0] != "package"
                    or ".." in relative.parts
                    or len(relative.parts) < 2
                ):
                    continue
                asset = Path(*relative.parts[1:])
                if not wanted(name, asset):
                    continue
                write_asset(vendor / name / asset, tar.extractfile(member).read())
                count += 1
        print(f"{name} {version}: {count} verified files")
    fetch_fonts(vendor)


if __name__ == "__main__":
    main()
