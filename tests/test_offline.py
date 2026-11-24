import hashlib
import subprocess
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[1] / "web" / "offline.template.js"
MOCKS = """
const assert = require("node:assert/strict");
const listeners = new Map();
const cacheEntries = new Map();
const deleted = [];
const downloads = [];
let active = false, claimed = false;
const cachedResponse = new Response("<html>test</html>", {headers:{"content-type":"text/html"}});
const cacheMock = {
  async put(key, response) { cacheEntries.set(key, response); },
  async match(key) { return cacheEntries.get(key); },
};
const caches = {
  async open() { return cacheMock; },
  async keys() { return ["data-sorter:https://example.test/sorter/:old", "other-app"]; },
  async delete(key) { deleted.push(key); },
};
const self = {
  registration: {scope:"https://example.test/sorter/"},
  addEventListener(event, callback) { listeners.set(event, callback); },
  async skipWaiting() { active = true; },
  clients: {async claim() { claimed = true; }},
};
let response = cachedResponse;
const fetch = async (url, options) => { downloads.push({url, options}); return response; };
function trigger(type, args = {}) {
  let value;
  const setValue = (next) => { value = next; };
  listeners.get(type)({...args, waitUntil:setValue, respondWith:setValue});
  return value;
}
"""


def run_worker(body):
    digest = hashlib.sha256(b"<html>test</html>").hexdigest()
    worker = WORKER.read_text("utf-8").replace("@@VERSION@@", digest[:16]).replace("@@DIGEST@@", digest)
    program = f"{MOCKS}\n{worker}\n(async () => {{\n{body}\n}})().catch(e => {{console.error(e);process.exitCode=1;}});"
    result = subprocess.run(
        ["node", "--input-type=commonjs"], input=program, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_verifies_page_before_caching():
    run_worker("""
      await trigger("install");
      assert.equal(active, true);
      assert.equal(downloads[0].url, ENTRY);
      assert.equal(downloads[0].options.cache, "reload");
      assert.equal(cacheEntries.get(ENTRY), cachedResponse);
    """)


@pytest.mark.parametrize(
    "setup",
    [
        'response = new Response("wrong bytes", {headers:{"content-type":"text/html"}});',
        'response = new Response("<html>test</html>", {headers:{"content-type":"application/json"}});',
        'response = new Response("<html>test</html>", {status:404, headers:{"content-type":"text/html"}});',
    ],
)
def test_invalid_install_leaves_cache_unmodified(setup):
    run_worker(f"""
      {setup}
      await assert.rejects(trigger("install"));
      assert.equal(active, false);
      assert.equal(cacheEntries.size, 0);
    """)


def test_activation_only_deletes_this_app_old_cache():
    run_worker("""
      await trigger("activate");
      assert.deepEqual(deleted, ["data-sorter:https://example.test/sorter/:old"]);
      assert.equal(claimed, true);
    """)


def test_cache_serves_index_and_root_blocks_no_other_routes():
    run_worker("""
      await trigger("install");
      for (const url of [ENTRY, ROOT, ROOT + "?query=1"]) {
        assert.equal(await trigger("fetch", {request:{method:"GET",url}}), cachedResponse);
      }
      for (const [method,url] of [
        ["POST", ENTRY], ["GET", ROOT + "another.html"], ["GET", "https://other.test/sorter/index.html"],
      ]) {
        assert.equal(trigger("fetch", {request:{method,url}}), undefined);
      }
      assert.equal(downloads.length, 1);
    """)
