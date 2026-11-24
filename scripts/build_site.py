"""Generate the GitHub Pages tree and its matching browser download."""

import hashlib
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from scripts.build import OUTPUT, ROOT, WEB, build

SITE = ROOT / "site"


def version():
    value = (SITE / "VERSION").read_text("utf-8").strip()
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value, re.ASCII):
        raise ValueError("site/VERSION must contain a release version such as 1.0.0.")
    return value


def write(path, data, output):
    if path.resolve() != path or not path.is_relative_to(output):
        raise ValueError("Site products must stay in the build folder.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build_site(output=OUTPUT):
    output = output.absolute()
    current_version = version()
    build(output)
    pages = output / "pages"
    release = output / "release"
    website = output / "website"
    app = (website / "index.html").read_bytes()

    for name in ("index.html", "offline.js", "LICENSE", "THIRD_PARTY_NOTICES.txt"):
        write(pages / "app" / name, (website / name).read_bytes(), output)

    bundle = release / "data-sorter-offline.zip"
    if bundle.resolve() != bundle or not bundle.is_relative_to(output):
        raise ValueError("Release ZIP must stay in the build folder.")
    release.mkdir(exist_ok=True)
    release_files = {
        "Data Sorter.html": app,
        "LICENSE": (website / "LICENSE").read_bytes(),
        "THIRD_PARTY_NOTICES.txt": (website / "THIRD_PARTY_NOTICES.txt").read_bytes(),
    }
    with ZipFile(bundle, "w", compression=ZIP_DEFLATED, compresslevel=9) as stream:
        for name, data in release_files.items():
            info = ZipInfo(name)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            stream.writestr(info, data, compresslevel=9)
    zipped = bundle.read_bytes()
    checksum = hashlib.sha256(zipped).hexdigest()
    write(release / "SHA256SUMS.txt", f"{checksum}  {bundle.name}\n".encode(), output)

    context = {
        "VERSION": current_version,
        "CACHE_MB": f"{len(app) / 1_000_000:.2f}",
        "ZIP_MB": f"{len(zipped) / 1_000_000:.2f}",
    }
    for name in ("index.html", "guide.html", "checks.html"):
        contents = (SITE / name).read_text("utf-8")
        page = re.sub(r"@@([A-Z_]+)@@", lambda marker: context[marker[1]], contents)
        write(pages / name, page.encode(), output)
    write(pages / "assets/site.css", (SITE / "site.css").read_bytes(), output)
    write(pages / "assets/icon.png", (WEB / "data_sorter_icon.png").read_bytes(), output)
    write(pages / ".nojekyll", b"", output)

    print(f"Built GitHub Pages and v{current_version} download ({len(zipped)} bytes).")


if __name__ == "__main__":
    build_site()
