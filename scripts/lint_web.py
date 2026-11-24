"""Check JavaScript syntax and lint the concatenated application source."""

import hashlib
import io
import os
import platform
import subprocess
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.95.0"
OXCLINT_ARCHIVES = {
    ("Darwin", "arm64"): (
        "aarch64-apple-darwin",
        "a08b6a75a95ef77ee6d7bd9e74f903539fb78e856ce58f4f39b6ea2353a4599f",
    ),
    ("Darwin", "x86_64"): (
        "x86_64-apple-darwin",
        "1863cd8fca56e958fc5ecdc3468b4f30562e0bd677701b3b0a2922b4305986e8",
    ),
    ("Linux", "x86_64"): (
        "x86_64-unknown-linux-gnu",
        "180d51ffd469995f394ba379a4b6f73c55ddb98443df442e3e456951d874a5f1",
    ),
    ("Linux", "aarch64"): (
        "aarch64-unknown-linux-gnu",
        "8cb1fa1ac7ab4a6caae3003ffa1d6b2cf1b939fda977dddc971234ee6fccb8c7",
    ),
}


def get_oxlint(checks):
    external = os.environ.get("OXLINT_BIN")
    if external:
        return Path(external).resolve(strict=True)
    platform_key = (platform.system(), platform.machine())
    if platform_key not in OXCLINT_ARCHIVES:
        raise RuntimeError("Set OXLINT_BIN to a compatible Oxlint executable.")
    target, checksum = OXCLINT_ARCHIVES[platform_key]
    binary = checks / f"oxlint-{VERSION}-{target}"
    if binary.resolve() != binary:
        raise ValueError("Oxlint must stay inside the check folder.")
    if not binary.is_file():
        url = (
            f"https://github.com/oxc-project/oxc/releases/download/oxlint_v{VERSION}/oxlint-{target}.tar.gz"
        )
        with urlopen(url, timeout=30) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != checksum:
            raise ValueError("Oxlint archive integrity check failed.")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            names = {"oxlint", f"oxlint-{target}"}
            binary_member = next(
                (item for item in archive if item.isfile() and Path(item.name).name in names), None
            )
            if binary_member is None:
                raise ValueError("No Oxlint executable found in the verified archive.")
            binary.write_bytes(archive.extractfile(binary_member).read())
        binary.chmod(0o755)
    return binary


def main():
    checks = ROOT / ".checks"
    if checks.resolve() != checks:
        raise ValueError("Check files must stay inside the repository.")
    checks.mkdir(exist_ok=True)
    web = ROOT / "web"
    app_names = ("session.js", "preview.js", "app.js")
    workers = [web / "dicom_worker.js", web / "offline.template.js"]
    with TemporaryDirectory(dir=checks) as temporary:
        source = Path(temporary) / "app.js"
        app = "\n".join((web / name).read_text("utf-8") for name in app_names)
        source.write_text("(() => {\n" + app + "\n})();\n", encoding="utf-8")
        files = [source, *workers]
        for path in files:
            subprocess.run(["node", "--check", path], check=True, cwd=ROOT)
        linter = get_oxlint(checks)
        subprocess.run([linter, "--version"], check=True, cwd=ROOT)
        subprocess.run(
            [linter, "--no-ignore", "--deny-warnings", "-c", ROOT / ".oxlintrc.json", *files],
            check=True,
            cwd=ROOT,
        )


if __name__ == "__main__":
    main()
