import base64
import hashlib
import re
from pathlib import Path

import pytest

from scripts import build, fetch_vendor


@pytest.fixture(scope="module")
def distribution(tmp_path_factory):
    site = tmp_path_factory.mktemp("release")
    build.build(site)
    return site


def test_standalone_and_site_are_identical_and_cache_is_versioned(distribution):
    standalone = (distribution / "Data Sorter.html").read_bytes()
    site = distribution / "website"
    assert standalone == (site / "index.html").read_bytes()
    digest = hashlib.sha256(standalone).hexdigest()
    worker = (site / "offline.js").read_text("utf-8")
    assert f'"{digest}"' in worker
    assert f'"{digest[:16]}"' in worker
    assert b"@@" not in standalone[:500]


def test_html_content_security_policy_hash_and_licences(distribution):
    page = (distribution / "Data Sorter.html").read_text("utf-8")
    inline_js = re.search(r"<script>(.*?)</script>", page, re.DOTALL).group(1)
    digest = base64.b64encode(hashlib.sha256(inline_js.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in page
    assert "connect-src 'none'" in page
    assert "default-src 'none'" in page
    assert "form-action 'none'" in page
    assert "MIT License" in (distribution / "website" / "LICENSE").read_text("utf-8")
    assert "SIL OPEN FONT LICENSE" in page
    assert "Apache License" in page
    assert "https://cdn." not in page[:2000]


def test_build_is_reproducible(distribution, tmp_path):
    build.build(tmp_path)
    assert (tmp_path / "Data Sorter.html").read_bytes() == (distribution / "Data Sorter.html").read_bytes()
    assert (tmp_path / "website/offline.js").read_bytes() == (
        distribution / "website/offline.js"
    ).read_bytes()


def test_output_must_stay_within_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path / "repo")
    with pytest.raises(ValueError, match="remain in the project"):
        build.build(tmp_path / "outside")


def test_worker_transformation_rejects_incompatible_entry_point(tmp_path):
    source = tmp_path / "worker.mjs"
    source.write_text("export const value = 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="worker entry point"):
        build.classic_pdf_worker(source)


def test_worker_transformation_preserves_worker_handler():
    worker = build.VENDOR / "pdfjs-dist/build/pdf.worker.min.mjs"
    code = base64.b64decode(build.classic_pdf_worker(worker)).decode()
    assert "Modified by Data Sorter" in code
    assert "import.meta.url" not in code
    assert "export{WorkerMessageHandler}" not in code
    assert "this.initializeFromPort(self)" in code


def test_vendor_selection_excludes_superseded_fonts():
    assert not fetch_vendor.wanted("pdfjs-dist", Path("standard_fonts/LiberationSans-Regular.ttf"))
    assert not fetch_vendor.wanted("pdfjs-dist", Path("standard_fonts/LICENSE_LIBERATION"))
    assert fetch_vendor.wanted("pdfjs-dist", Path("standard_fonts/FoxitFixed.pfb"))


def test_vendor_writer_rejects_symbolic_links(tmp_path):
    other = tmp_path / "original"
    other.write_bytes(b"existing")
    link = tmp_path / "link"
    link.symlink_to(other)
    with pytest.raises(ValueError, match="symbolic link"):
        fetch_vendor.write_asset(link, b"replace")
    assert other.read_bytes() == b"existing"
