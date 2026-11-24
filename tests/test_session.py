import json
import subprocess
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[1] / "web" / "session.js"
FILESYSTEM = """
let clock = 0;
class TestDirectory {
  constructor(name) {
    this.name = name;
    this.kind = "directory";
    this.children = new Map();
    this.blockDelete = false;
    this.corruptWrite = false;
  }
  async *values() { yield* this.children.values(); }
  async isSameEntry(other) { return this === other; }
  async getDirectoryHandle(name, { create } = {}) {
    if (create && !this.children.has(name)) this.children.set(name, new TestDirectory(name));
    return this.find(name, "directory");
  }
  async getFileHandle(name, { create } = {}) {
    if (create && !this.children.has(name)) {
      const directory = this;
      this.children.set(name, {
        kind: "file", name, data: new File([], name, { lastModified: ++clock }),
        async isSameEntry(other) { return this === other; },
        async getFile() { return this.data; },
        async createWritable() {
          const parts = [];
          return Object.assign(new WritableStream({
            write: (chunk) => parts.push(chunk),
            close: () => {
              this.data = new File(directory.corruptWrite ? ["corrupt"] : parts, name, { lastModified: ++clock });
            },
          }), {
            write(chunk) { parts.push(chunk); },
            close: () => { this.data = new File(parts, name, { lastModified: ++clock }); },
          });
        },
      });
    }
    return this.find(name, "file");
  }
  find(name, kind) {
    const child = this.children.get(name);
    if (!child) throw new DOMException("Missing resource", "NotFoundError");
    if (child.kind !== kind) throw new DOMException("Wrong resource type", "TypeMismatchError");
    return child;
  }
  async removeEntry(name) {
    if (this.blockDelete) throw new DOMException("Deletion denied", "NotAllowedError");
    if (!this.children.delete(name)) throw new DOMException("Missing resource", "NotFoundError");
  }
}
const categories = [{ name: "A", key: "a" }, { name: "B", key: "b" }];
async function setup(mode = "copy") {
  const input = new TestDirectory("input");
  const output = new TestDirectory("output");
  await writeFile(input, "draft.txt", "source content");
  const entries = await findEntries(input, output);
  const session = new SortSession(input, output, { entries, mode, index: 0, categories });
  return { session, input, output, entry: entries[0] };
}
async function content(folder, name) { return (await (await folder.getFileHandle(name)).getFile()).text(); }
"""


def run_js(body):
    code = "\n".join(
        [
            'const assert = require("node:assert/strict");',
            SESSION.read_text("utf-8"),
            FILESYSTEM,
            "(async () => {",
            body,
            "})().catch((error) => { console.error(error); process.exitCode = 1; });",
        ]
    )
    result = subprocess.run(
        ["node", "--input-type=commonjs"], input=code, text=True, capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("\ufeffa,b\r\n,2\r\n", [["a", "b"], ["", "2"]]),
        ('a,"b,b"\n"x\ny","""quoted"""', [["a", "b,b"], ["x\ny", '"quoted"']]),
        ("a,", [["a", ""]]),
        ('""\r', [[""]]),
        ("", []),
    ],
)
def test_csv_parsing(source, expected):
    run_js(f"assert.deepEqual(readCsv({json.dumps(source)}), {json.dumps(expected)});")


def test_preview_csv_keeps_only_complete_rows_when_truncated():
    run_js("""
      assert.deepEqual(readCsv('A,B\u005cn1,"partial', Infinity, true), [["A","B"]]);
      assert.deepEqual(readCsv('A,B\u005cn1,2\u005cn3,4', 2), [["A","B"],["1","2"]]);
    """)


@pytest.mark.parametrize("source", ['a,"incomplete', '"a"suffix', 'one"quote'])
def test_csv_malformed_fields_are_rejected(source):
    run_js(f"assert.throws(() => readCsv({json.dumps(source)}), /CSV/);")


@pytest.mark.parametrize(
    "path", ["../report.pdf", "nested/../report.pdf", "/report.pdf", "C:\\report.pdf", "a//report.pdf"]
)
def test_csv_paths_reject_traversal_absolute_and_empty_components(path):
    run_js(f"assert.throws(() => safePath({json.dumps(path)}), /unsafe relative path/);")


def test_category_names_are_checked_across_case_and_unicode_forms():
    run_js("""
      assert.throws(() => categoriesFrom([{name:'ABC',key:'a'}, {name:'abc',key:'b'}]), /unique/);
      assert.throws(() => categoriesFrom([{name:'ABC',key:'Z'}, {name:'DEF',key:'z'}]), /different/);
      assert.throws(() => categoriesFrom([{name:'a/b',key:'a'}]), /folder name/);
      assert.deepEqual(categoriesFrom([{name:' A ',key:'!'}]), [{name:'A',key:'!'}]);
    """)


def test_session_csv_round_trip_preserves_decisions_order_and_text():
    run_js("""
      const {session, input, output} = await setup();
      await writeFile(input, 'with "quotes",.txt', "second");
      session.entries = await findEntries(input, output);
      await session.choose("A");
      const csv = encodeSession(session);
      const restored = readSession(csv);
      assert.deepEqual(restored.entries, session.entries);
      assert.equal(restored.index, 1);
      assert.equal(restored.mode, 'copy');
      const preferences = new SortSession(input, output, restored);
      assert.deepEqual(preferences.history, []);
    """)


def test_desktop_csv_with_windows_paths():
    run_js("""
      const text = 'schema_version,categories_json,mode,rel_path,choice,operation,dest_rel_path,current_index,image_index\u005cn' +
        '1,"[{""name"":""A"",""key"":""a""}]",move,nested\\\\film.png,A,move,A\\\\film.png,0,0\u005cn';
      const restored = readSession(text);
      assert.deepEqual(restored.entries[0].original, ["nested","film.png"]);
      assert.deepEqual(restored.entries[0].destination, ["A","film.png"]);
    """)


def test_scan_skips_output_and_unsupported_files():
    run_js("""
      const {input} = await setup();
      const nested = await input.getDirectoryHandle('nested', {create:true});
      const output = await nested.getDirectoryHandle('output', {create:true});
      await writeFile(nested, 'film.PNG', 'image');
      await writeFile(input, 'unsupported.exe', 'unsupported');
      await writeFile(output, 'existing.pdf', 'sorted');
      const entries = await findEntries(input, output);
      assert.deepEqual(entries.map(e => e.original), [['draft.txt'], ['nested','film.PNG']]);
    """)


def test_copy_collision_and_undo_preserve_existing_bytes():
    run_js("""
      const {session, input, output, entry} = await setup();
      const category = await directory(output, ["A"], true);
      await writeFile(category, 'draft.txt', 'pre-existing');
      await session.choose('A');
      assert.deepEqual(entry.destination, ['A','draft_2.txt']);
      assert.equal(await content(category, 'draft_2.txt'), 'source content');
      await session.undo();
      assert.equal(await content(input, 'draft.txt'), 'source content');
      assert.equal(await content(category, 'draft.txt'), 'pre-existing');
      assert.equal(await lookup({dir:category, name:'draft_2.txt'}), null);
    """)


def test_move_reclassification_and_two_undos():
    run_js("""
      const {session, input, output, entry} = await setup('move');
      await session.choose('A');
      assert.equal(await lookup({dir:input, name:'draft.txt'}), null);
      await session.choose('B');
      const a = await directory(output, ['A']), b = await directory(output, ['B']);
      assert.equal(await lookup({dir:a, name:'draft.txt'}), null);
      assert.equal(await (await session.openFile(entry)).text(), 'source content');
      await session.undo();
      assert.equal(await lookup({dir:b, name:'draft.txt'}), null);
      assert.equal(await content(a, 'draft.txt'), 'source content');
      await session.undo();
      assert.equal(await content(input, 'draft.txt'), 'source content');
      assert.equal(entry.choice, '');
    """)


def test_copy_to_move_and_undo_removes_superseded_copy():
    run_js("""
      const {session, input, output, entry} = await setup();
      await session.choose('A');
      session.mode = 'move';
      await session.choose('B');
      const a = await directory(output, ['A']), b = await directory(output, ['B']);
      assert.equal(await lookup({dir:input, name:'draft.txt'}), null);
      assert.equal(await lookup({dir:a, name:'draft.txt'}), null);
      assert.equal(await content(b, 'draft.txt'), 'source content');
      await session.undo();
      assert.equal(entry.operation, 'copy');
      assert.equal(await content(a, 'draft.txt'), 'source content');
      assert.equal(await content(input, 'draft.txt'), 'source content');
      assert.equal(await lookup({dir:b, name:'draft.txt'}), null);
    """)


def test_move_to_copy_restore_and_undo():
    run_js("""
      const {session, input, output, entry} = await setup('move');
      await session.choose('A');
      session.mode = 'copy';
      await session.choose('B');
      assert.equal(await content(input, 'draft.txt'), 'source content');
      assert.equal(entry.operation, 'copy');
      await session.undo();
      assert.equal(await lookup({dir:input, name:'draft.txt'}), null);
      assert.equal(await content(await directory(output, ['A']), 'draft.txt'), 'source content');
      assert.equal(entry.operation, 'move');
    """)


def test_failed_copy_to_move_restores_previous_copy_and_history():
    run_js("""
      const {session, input, output, entry} = await setup();
      await session.choose('A');
      session.mode = 'move';
      input.blockDelete = true;
      await assert.rejects(session.choose('B'), /Deletion denied/);
      const a = await directory(output, ['A']), b = await directory(output, ['B']);
      assert.equal(await content(a, 'draft.txt'), 'source content');
      assert.equal(await content(input, 'draft.txt'), 'source content');
      assert.equal(await lookup({dir:b, name:'draft.txt'}), null);
      assert.equal(entry.operation, 'copy');
      assert.equal(session.history.length, 1);
    """)


def test_failed_move_verification_preserves_source():
    run_js("""
      const {session, input, output, entry} = await setup('move');
      const a = await directory(output, ['A'], true);
      a.corruptWrite = true;
      await assert.rejects(session.choose('A'), /failed verification/);
      assert.equal(await content(input, 'draft.txt'), 'source content');
      assert.equal(await lookup({dir:a, name:'draft.txt'}), null);
      assert.equal(entry.operation, '');
      assert.deepEqual(session.history, []);
    """)


def test_undo_refuses_to_overwrite_a_replacement_source():
    run_js("""
      const {session, input, output, entry} = await setup('move');
      await session.choose('A');
      await writeFile(input, 'draft.txt', 'replacement');
      await assert.rejects(session.undo(), /already exists/);
      assert.equal(await content(input, 'draft.txt'), 'replacement');
      assert.equal(await content(await directory(output, ['A']), 'draft.txt'), 'source content');
      assert.equal(entry.operation, 'move');
      assert.equal(session.history.length, 1);
    """)


def test_undo_preserves_an_edited_destination():
    run_js("""
      const {session, output, entry} = await setup();
      await session.choose('A');
      const a = await directory(output, ['A']);
      await writeFile(a, 'draft.txt', 'external edit', true);
      await assert.rejects(session.undo(), /differs from the original/);
      assert.equal(await content(a, 'draft.txt'), 'external edit');
      assert.equal(entry.choice, 'A');
    """)
