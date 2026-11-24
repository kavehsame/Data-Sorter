import hashlib
from html.parser import HTMLParser
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest

from scripts.build_site import build_site, version


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.links.extend(value for name, value in attrs if name in {"href", "src"} and value)


@pytest.fixture(scope="module")
def site_output(tmp_path_factory):
    output = tmp_path_factory.mktemp("pages")
    build_site(output)
    return output


def test_site_links_work_at_a_github_project_subpath(site_output):
    pages = site_output / "pages"
    for name in ("index.html", "guide.html", "checks.html"):
        parser = LinkParser()
        text = (pages / name).read_text("utf-8")
        parser.feed(text)
        for link in parser.links:
            url = urlsplit(link)
            if url.scheme or not url.path:
                continue
            assert not url.path.startswith("/")
            candidate = pages / url.path
            if candidate.is_dir():
                candidate /= "index.html"
            assert candidate.is_file(), link
        assert "@@" not in text
    overview = (pages / "index.html").read_text("utf-8")
    assert f"Version {version()}" in overview
    assert 'href="app/"' in overview
    assert "releases/latest/download/data-sorter-offline.zip" in overview
    assert (pages / "index.html").stat().st_size < 10_000


def test_hosted_and_downloadable_app_match(site_output):
    pages = site_output / "pages"
    release = site_output / "release"
    app = (pages / "app/index.html").read_bytes()
    asset = release / "data-sorter-offline.zip"
    with ZipFile(asset) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"Data Sorter.html", "LICENSE", "THIRD_PARTY_NOTICES.txt"}
        assert archive.read("Data Sorter.html") == app
    worker = (pages / "app/offline.js").read_text("utf-8")
    assert hashlib.sha256(app).hexdigest() in worker
    assert hashlib.sha256(asset.read_bytes()).hexdigest() in (release / "SHA256SUMS.txt").read_text()
    assert f"{len(app) / 1_000_000:.2f} MB" in (pages / "index.html").read_text("utf-8")
