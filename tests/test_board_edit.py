# -*- coding: utf-8 -*-
"""skill/scripts/board_edit.py の試験（T-O 操作・T-K 検査・T-P Deck との写しの一致・T-R restore・T-W 書き込み・T-E 往復と、.guard/ の記録）。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
すべて一時フォルダのサンドボックスで行う。本番の ~/.claude/today-board/ には触れない
（各試験は --board で一時フォルダの board.html を指し、念のため HOME / USERPROFILE も一時フォルダへ向ける）。
"""

import ast
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import date

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skill", "scripts", "board_edit.py")
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "deck"))
import board_edit as be  # noqa: E402
import deck_watcher as dw  # noqa: E402

SPEC = {
    "sections": ["今日の予定", "今日中", "ルーチンタスク", "明日以降"],
    "items": [
        {"section": "今日の予定", "time": "9:00", "title": "朝会", "note": "毎朝"},
        {"section": "今日の予定", "time": "16:00", "title": "判断する", "crit": True},
        {"section": "今日中", "title": "作業A", "chip": "active"},
        {"section": "今日中", "title": "作業B"},
        {"section": "ルーチンタスク", "title": "ログを更新する"},
        {"section": "明日以降", "title": "来週の件"},
    ],
}


def run(argv):
    """board_edit.main を同じプロセスで走らせる。(終了コード, 出力の JSON)"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = be.main(argv)
    text = out.getvalue()
    return rc, (json.loads(text) if text.strip().startswith("{") else text)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-edit-test-")
        self.board = os.path.join(self.dir, "board.html")
        self._env = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        os.environ["HOME"] = os.environ["USERPROFILE"] = self.dir
        self.hook = be._HOOK_BEFORE_REREAD
        self.ops = dict(be.ITEM_OPS)

    def tearDown(self):
        be._HOOK_BEFORE_REREAD = self.hook
        be.ITEM_OPS.clear()
        be.ITEM_OPS.update(self.ops)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)

    def create(self, spec=SPEC, *extra):
        p = os.path.join(self.dir, "spec.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        rc, out = run(["create", "--board", self.board, "--spec", p] + list(extra))
        self.assertEqual(rc, 0, out)
        return out

    def write_spec(self, spec):
        p = os.path.join(self.dir, "spec-x.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        return p

    def ed(self, *args):
        return run([args[0], "--board", self.board] + list(args[1:]))

    def read(self):
        with open(self.board, "rb") as f:
            return f.read()

    def text(self):
        return self.read().decode("utf-8")

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        with open(self.board, "wb") as f:
            f.write(data)

    def status(self):
        rc, out = self.ed("status")
        self.assertEqual(rc, 0)
        return out

    def items(self):
        st = self.status()
        return [it for s in st["sections"] for it in s["items"]]

    def records(self):
        adir = os.path.join(self.dir, ".guard", "auth")
        return sorted(os.listdir(adir)) if os.path.isdir(adir) else []

    def assertUnchanged(self, before):
        self.assertEqual(self.read(), before)


# ------------------------------------------------------------------ T-O（操作）

class TestOps(Sandbox):
    def test_create_defaults(self):
        out = self.create()
        self.assertTrue(out["changed"])
        t = self.text()
        self.assertIn("<title>%s きょうのボード</title>" % be.fmt_title_date(date.today()), t)
        self.assertIn('<span class="date">%s</span>' % be.fmt_full_date(date.today()), t)
        self.assertNotRegex(t, r"\{\{")
        its = {i["title"]: i for i in self.items()}
        self.assertEqual(its["来週の件"]["chip"], "none")      # 明日以降はチップ無し
        self.assertEqual(its["作業B"]["chip"], "pending")      # それ以外は未
        self.assertEqual(its["作業A"]["chip"], "active")
        self.assertTrue(its["判断する"]["crit"])
        self.assertEqual(out["progress"], {"done": 0, "total": 4, "percent": 0})
        for a in be.ASSET_NAMES:
            self.assertTrue(os.path.isfile(os.path.join(self.dir, a)))
        self.assertEqual(be.structure_errors(t), [])

    def test_create_chip_none_and_rejections(self):
        spec = {"items": [{"section": "今日中", "title": "x", "chip": "none"}]}
        self.create(spec)
        self.assertEqual(self.items()[0]["chip"], "none")
        before = self.read()
        p = os.path.join(self.dir, "s2.json")
        for bad in (
            {"items": [{"section": "本日中", "title": "a"}]},
            {"items": [{"section": "今日中", "title": "a", "time": "9時"}]},
            {"items": [{"section": "今日中", "title": "a", "chip": "zzz"}]},
            {"items": [{"section": "今日中", "title": "a", "colour": "red"}]},
            {"items": [{"section": "監視ねこ", "title": "a"}]},
        ):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(bad, f, ensure_ascii=False)
            rc, out = run(["create", "--board", self.board, "--spec", p])
            self.assertEqual(rc, 1, bad)
            self.assertFalse(out["ok"])
            self.assertUnchanged(before)

    def test_create_keeps_deck_region(self):
        self.create()
        t = self.text().replace("<!-- DECK:AUTO:START -->\n",
                                '<!-- DECK:AUTO:START -->\n<span id="deck-key" hidden data-port="8737"></span>\n')
        self.write(t)
        self.create()
        self.assertIn('<span id="deck-key" hidden data-port="8737"></span>', self.text())

    def test_add_default_chip_and_count(self):
        self.create()
        n = len(self.items())
        rc, out = self.ed("add", "--section", "明日以降", "--title", "あさって")
        self.assertEqual(rc, 0, out)
        rc, out = self.ed("add", "--section", "今日中", "--title", "飛び込み", "--note", "proj", "--chip", "active")
        self.assertEqual(rc, 0, out)
        its = self.items()
        self.assertEqual(len(its), n + 2)
        d = {i["title"]: i for i in its}
        self.assertEqual(d["あさって"]["chip"], "none")
        self.assertEqual(d["飛び込み"]["chip"], "active")
        self.assertEqual(d["飛び込み"]["section"], "今日中")
        # 見出しの末尾に入る
        names = [i["title"] for i in its if i["section"] == "今日中"]
        self.assertEqual(names[-1], "飛び込み")

    def test_add_positions_and_time(self):
        self.create()
        self.ed("add", "--section", "今日中", "--title", "先頭", "--head")
        self.ed("add", "--section", "今日中", "--title", "Aの次", "--after", "作業A", "--time", "13:05")
        names = [i["title"] for i in self.items() if i["section"] == "今日中"]
        self.assertEqual(names, ["先頭", "作業A", "Aの次", "作業B"])
        d = {i["title"]: i for i in self.items()}
        self.assertEqual(d["Aの次"]["time"], "13:05")
        rc, out = self.ed("add", "--section", "今日中", "--title", "x", "--after", "朝会")
        self.assertEqual(rc, 1)   # --after の項目が別の見出し

    def test_add_section_missing_and_create_section(self):
        self.create()
        before = self.read()
        rc, out = self.ed("add", "--section", "プロジェクトX", "--title", "t")
        self.assertEqual(rc, 1)
        self.assertIn("--create-section", out["error"])
        self.assertUnchanged(before)
        rc, out = self.ed("add", "--section", "プロジェクトX", "--create-section", "--title", "t")
        self.assertEqual(rc, 0, out)
        labels = [s["name"] for s in self.status()["sections"]]
        self.assertEqual(labels, ["今日の予定", "今日中", "プロジェクトX", "ルーチンタスク", "明日以降"])

    def test_set_chip_all_values(self):
        self.create()
        for chip, label in (("done", "済"), ("hold", "保留"), ("wait", "条件待ち"), ("active", "進行中"), ("pending", "未")):
            rc, out = self.ed("set-chip", "--item", "作業B", "--chip", chip)
            self.assertEqual(rc, 0, out)
            self.assertEqual({i["title"]: i for i in self.items()}["作業B"]["chip"], chip)
            self.assertIn('>%s</span>' % label, self.text())
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "none")
        self.assertEqual(rc, 0)
        self.assertEqual({i["title"]: i for i in self.items()}["作業B"]["chip"], "none")
        blk = re.search(r'<div class="item flat">\s*<div>\s*<p class="task-title">作業B</p>.*?\n  </div>', self.text(), re.S).group(0)
        self.assertNotIn("chips", blk)
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0)
        self.assertIn('<div class="chips"><span class="chip done">済</span></div>', self.text())

    def test_set_chip_done_normalizes_only_target(self):
        self.create()
        self.ed("set-chip", "--item", "作業A", "--chip", "done")
        t = self.text()
        self.assertIn('<p class="task-title strike">作業A</p>', t)
        self.assertIn('class="item flat done-item"', t)
        self.ed("set-chip", "--item", "作業A", "--chip", "hold")
        t = self.text()
        self.assertIn('<p class="task-title">作業A</p>', t)
        self.assertNotIn("done-item", t)

    def test_edit(self):
        self.create()
        rc, out = self.ed("edit", "--item", "9:00|朝会", "--title", "朝会（延長）", "--note", "")
        self.assertEqual(rc, 0, out)
        d = {i["key"]: i for i in self.items()}
        self.assertIn("9:00|朝会（延長）", d)
        self.assertIsNone(d["9:00|朝会（延長）"]["note"])
        rc, out = self.ed("edit", "--item", "作業B", "--note", "補足を足す")
        self.assertEqual(rc, 0)
        self.assertEqual({i["title"]: i for i in self.items()}["作業B"]["note"], "補足を足す")
        rc, out = self.ed("edit", "--item", "作業B")
        self.assertEqual(rc, 1)

    def test_set_crit_both_class_and_chip(self):
        self.create()
        self.ed("set-crit", "--item", "16:00|判断する", "off")
        t = self.text()
        self.assertNotIn('<span class="chip crit">', t)
        self.assertNotIn("item crit", t)
        self.ed("set-crit", "--item", "作業B", "on")
        t = self.text()
        self.assertIn('class="item flat crit"', t)
        self.assertIn('<span class="chip crit">重要タスク</span><span class="chip pending">未</span>', t)
        self.assertTrue({i["title"]: i for i in self.items()}["作業B"]["crit"])

    def test_set_time(self):
        self.create()
        self.ed("set-time", "--item", "作業B", "--time", "14:00")
        d = {i["title"]: i for i in self.items()}
        self.assertEqual(d["作業B"]["time"], "14:00")
        self.assertIn('<div class="item">\n    <div class="time">14:00</div>', self.text())
        self.ed("set-time", "--item", "14:00|作業B", "--time", "none")
        d = {i["title"]: i for i in self.items()}
        self.assertIsNone(d["作業B"]["time"])
        rc, out = self.ed("set-time", "--item", "作業B", "--time", "25:00")
        self.assertEqual(rc, 1)

    def test_move(self):
        self.create()
        rc, out = self.ed("move", "--item", "作業B", "--section", "今日の予定", "--before", "16:00|判断する")
        self.assertEqual(rc, 0, out)
        names = [i["title"] for i in self.items() if i["section"] == "今日の予定"]
        self.assertEqual(names, ["朝会", "作業B", "判断する"])
        rc, out = self.ed("move", "--item", "作業B", "--section", "明日以降", "--head")
        self.assertEqual(rc, 0)
        self.assertEqual([i["title"] for i in self.items() if i["section"] == "明日以降"], ["作業B", "来週の件"])
        before = self.read()
        for args in (("--item", "ログを更新する", "--section", "今日中"),          # ルーチンタスクは動かせない
                     ("--item", "作業A", "--section", "ルーチンタスク"),          # 行き先が対象外
                     ("--item", "作業A", "--section", "今日中", "--before", "朝会")):  # before が行き先に無い
            rc, out = self.ed("move", *args)
            self.assertEqual(rc, 1, args)
            self.assertUnchanged(before)

    def test_move_before_duplicate_content(self):
        self.create()
        self.ed("add", "--section", "今日の予定", "--title", "同じ")
        self.ed("add", "--section", "今日の予定", "--title", "区切り")
        self.ed("add", "--section", "今日の予定", "--title", "同じ")
        idx = [i["index"] for i in self.items() if i["title"] == "同じ"]
        rc, out = self.ed("move", "--item", "作業B", "--section", "今日の予定", "--before", str(idx[1]))
        self.assertEqual(rc, 0, out)
        names = [i["title"] for i in self.items() if i["section"] == "今日の予定"]
        self.assertEqual(names, ["朝会", "判断する", "同じ", "区切り", "作業B", "同じ"])

    def test_remove_needs_confirmed(self):
        self.create()
        before = self.read()
        rc, out = self.ed("remove", "--item", "作業B")
        self.assertEqual(rc, 0)
        self.assertFalse(out["changed"])
        self.assertTrue(out["would_remove"])
        self.assertUnchanged(before)
        n = len(self.items())
        rc, out = self.ed("remove", "--item", "作業B", "--confirmed")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.items()), n - 1)

    def test_item_zero_or_many(self):
        self.create()
        self.ed("add", "--section", "今日中", "--title", "作業A")   # 同じタイトルが2件
        before = self.read()
        rc, out = self.ed("set-chip", "--item", "存在しない", "--chip", "done")
        self.assertEqual(rc, 1)
        self.assertIn("candidates", out)
        rc, out = self.ed("set-chip", "--item", "作業A", "--chip", "done")
        self.assertEqual(rc, 1)
        self.assertEqual(len(out["candidates"]), 2)
        self.assertUnchanged(before)
        idx = out["candidates"][1]["index"]
        rc, out = self.ed("set-chip", "--item", str(idx), "--chip", "done")
        self.assertEqual(rc, 0, out)

    def test_status(self):
        self.create()
        with open(os.path.join(self.dir, "state.json"), "w", encoding="utf-8") as f:
            json.dump({"date": date.today().isoformat(), "mode": "local"}, f)
        st = self.status()
        self.assertTrue(st["live"])
        self.assertEqual(st["suggest"], "update")
        self.assertEqual(st["errors"], [])
        self.assertEqual(st["board_date"], date.today().isoformat())
        os.remove(self.board)
        st = self.status()
        self.assertFalse(st["exists"])
        self.assertEqual(st["suggest"], "create")

    def test_status_unreadable_board(self):
        self.create()
        os.makedirs(os.path.join(self.dir, "history"))
        open(os.path.join(self.dir, "history", "board-%s-lastgood-120000.html" % date.today().isoformat()), "wb").close()
        self.write(self.read() + b"\xff\xfe")
        st = self.status()
        self.assertTrue(st["exists"])
        self.assertEqual([e["code"] for e in st["errors"]], ["UTF8"])
        self.assertEqual(len(st["restorable"]), 1)
        rc, out = self.ed("restore", "--from", st["restorable"][0])
        self.assertEqual(rc, 1)
        self.assertIn("restore でも戻せません", out["error"])

    def test_status_suggest_rolled(self):
        self.create()
        with open(os.path.join(self.dir, "state.json"), "w", encoding="utf-8") as f:
            json.dump({"date": date.today().isoformat(), "mode": "local"}, f)
        self.write(self.text().replace('<div class="board">', '<div class="board" data-tb-rolled="2026-10-28">', 1))
        st = self.status()
        self.assertEqual(st["suggest"], "update")
        self.assertEqual(st["suggest_if_planning"], "create")

    def test_argument_errors_are_json(self):
        self.create()
        rc, out = self.ed("add", "--bogus")
        self.assertEqual(rc, 1)
        self.assertFalse(out["ok"])
        self.assertIn("引数が正しくありません", out["error"])
        rc, out = self.ed("add", "--section", "今日中")
        self.assertEqual(rc, 1)
        self.assertIn("--title", out["error"])
        p = os.path.join(self.dir, "t.json")
        for bad in ({"items": [{"section": "今日中", "title": 123}]}, {"items": [{"section": "今日中", "title": "a", "crit": "yes"}]},
                    {"sections": [1], "items": []}):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(bad, f)
            rc, out = run(["create", "--board", self.board, "--spec", p])
            self.assertEqual(rc, 1, bad)

    def test_read_retry_on_permission_error(self):
        self.create()
        real = open
        n = [0]

        def fake(path, *args, **kw):
            if str(path) == self.board and n[0] < 2:
                n[0] += 1
                raise PermissionError(13, "busy")
            return real(path, *args, **kw)
        be.open = fake
        try:
            rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        finally:
            del be.open
        self.assertEqual(rc, 0, out)
        self.assertEqual(n[0], 2)

    def test_remove_confirmed_rejects_number(self):
        self.create()
        before = self.read()
        rc, out = self.ed("remove", "--item", "4", "--confirmed")
        self.assertEqual(rc, 1)
        self.assertUnchanged(before)

    def test_section_with_entity(self):
        self.create()
        rc, out = self.ed("add", "--section", "A&B", "--create-section", "--title", "x")
        self.assertEqual(rc, 0, out)
        self.assertIn('<div class="section-label">A&amp;B</div>', self.text())
        rc, out = self.ed("add", "--section", "A&B", "--title", "y")
        self.assertEqual(rc, 0, out)
        self.assertEqual([s["name"] for s in self.status()["sections"] if s["name"] == "A&B"], ["A&B"])

    def test_ops_file(self):
        self.create()
        ops_dir = os.path.join(self.dir, "ops")
        os.makedirs(ops_dir)
        p = os.path.join(ops_dir, "a.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"op": "add", "board": self.board, "section": "今日中", "title": "-で始まる & 記号 \"引用\"",
                       "create_section": False}, f, ensure_ascii=False)
        rc, out = run(["--ops", p])
        self.assertEqual(rc, 0, out)
        self.assertIn("-で始まる & 記号 \"引用\"", [i["title"] for i in self.items()])
        self.assertFalse(os.path.exists(p))   # ops/ の中のファイルは成功したら消す
        p2 = os.path.join(ops_dir, "b.json")
        with open(p2, "w", encoding="utf-8") as f:
            json.dump({"op": "set-crit", "board": self.board, "item": "作業B", "value": "on"}, f, ensure_ascii=False)
        rc, out = run(["--ops", p2])
        self.assertEqual(rc, 0, out)
        self.assertTrue({i["title"]: i for i in self.items()}["作業B"]["crit"])

    def test_ops_and_spec_with_tilde(self):
        # PowerShell は ~ を展開せずにネイティブのプログラムへ渡す。--ops と --spec の ~ は board_edit.py が展開する
        # （HOME / USERPROFILE は Sandbox がこの試験の一時フォルダへ向けている）
        ops_dir = os.path.join(self.dir, "ops")
        os.makedirs(ops_dir)
        sp = os.path.join(ops_dir, "s.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(SPEC, f, ensure_ascii=False)
        rc, out = run(["create", "--board", self.board, "--spec", "~/ops/s.json"])
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(sp))   # 展開した後のパスで ops/ の中と分かり、成功したら消す
        p = os.path.join(ops_dir, "a.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"op": "add", "board": self.board, "section": "今日中", "title": "チルダで渡した行"}, f, ensure_ascii=False)
        rc, out = run(["--ops", "~/ops/a.json"])
        self.assertEqual(rc, 0, out)
        self.assertIn("チルダで渡した行", [i["title"] for i in self.items()])
        self.assertFalse(os.path.exists(p))
        p2 = os.path.join(ops_dir, "b.json")
        with open(p2, "w", encoding="utf-8") as f:
            json.dump({"op": "create", "board": self.board, "spec": "~/ops/s2.json"}, f, ensure_ascii=False)
        with open(os.path.join(ops_dir, "s2.json"), "w", encoding="utf-8") as f:
            json.dump(SPEC, f, ensure_ascii=False)
        rc, out = run(["--ops", "~/ops/b.json", "--confirmed"])
        self.assertEqual(rc, 0, out)

    def test_note_equals_empty_clears_note(self):
        # PowerShell 5.1 は空の引数 "" を落とすので、補足を消すときは --note= と書く
        self.create()
        rc, out = self.ed("edit", "--item", "9:00|朝会", "--note=")
        self.assertEqual(rc, 0, out)
        self.assertIsNone({i["title"]: i for i in self.items()}["朝会"]["note"])

    def test_duplicate_untimed_titles_detour(self):
        # 同じタイトルで時刻の無い行が2つあると、remove --confirmed では1つに絞れない（番号は受けない）。
        # SKILL.md の回り道: 番号で一意な仮のタイトルに edit してから、そのタイトルで remove --confirmed
        self.create()
        for _ in range(2):
            rc, out = self.ed("add", "--section", "今日中", "--title", "重複")
            self.assertEqual(rc, 0, out)
        rc, out = self.ed("remove", "--item", "|重複", "--confirmed")
        self.assertEqual(rc, 1)
        self.assertIn("SKILL.md「ボードの書き方」の remove の回り道", out.get("error", ""))
        idx = [i["index"] for i in self.items() if i["title"] == "重複"]
        self.assertEqual(len(idx), 2)
        rc, out = self.ed("edit", "--item", str(idx[1]), "--title", "重複（消す）")
        self.assertEqual(rc, 0, out)
        rc, out = self.ed("remove", "--item", "|重複（消す）")
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.get("would_remove"))
        rc, out = self.ed("remove", "--item", "|重複（消す）", "--confirmed")
        self.assertEqual(rc, 0, out)
        self.assertEqual([i["title"] for i in self.items()].count("重複"), 1)
        self.assertNotIn("重複（消す）", [i["title"] for i in self.items()])

    def test_cli_subprocess_and_version(self):
        env = dict(os.environ, PYTHONUTF8="1", HOME=self.dir, USERPROFILE=self.dir)
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--version"], capture_output=True, env=env)
        self.assertEqual(r.stdout.decode().strip(), be.VERSION)
        self.create()
        r = subprocess.run([sys.executable, "-I", SCRIPT, "set-chip", "--board", self.board, "--item", "作業B", "--chip", "zzz"],
                           capture_output=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("チップ「zzz」", r.stderr.decode("utf-8"))
        self.assertFalse(json.loads(r.stdout.decode("utf-8"))["ok"])


# ------------------------------------------------------------------ T-K（検査）

NESTED = """  <div class="item flat">
    <div>
      <p class="task-title">外</p>
  <div class="item flat">
    <div>
      <p class="task-title">中</p>
    </div>
  </div>
    </div>
  </div>
"""


class TestChecks(Sandbox):
    def insert_raw(self, snippet, after='<div class="section-label">今日中</div>\n'):
        t = self.text()
        self.assertIn(after, t)
        self.write(t.replace(after, after + snippet, 1))

    def test_k1_broken_board_refused_except_status_restore_create(self):
        self.create()
        t = self.text()
        # 閉じタグを1つ落とす（入れ子＝K1）
        t = t.replace('      <p class="task-title">作業A</p>\n      <div class="chips"><span class="chip active">進行中</span></div>\n    </div>\n  </div>\n',
                      '      <p class="task-title">作業A</p>\n      <div class="chips"><span class="chip active">進行中</span></div>\n    </div>\n', 1)
        self.write(t)
        st = self.status()
        self.assertIn("K1", [e["code"] for e in st["errors"]])
        before = self.read()
        rc, out = self.ed("add", "--section", "今日中", "--title", "x")
        self.assertEqual(rc, 1)
        self.assertIn("restore", out["error"])
        self.assertIn("K1", [c["code"] for c in out["checks"]])
        self.assertUnchanged(before)
        rc, out = run(["create", "--board", self.board, "--spec", self.write_spec(SPEC)])
        self.assertEqual(rc, 1)                 # 崩れた板は消える行を確かめきれないので、確かめなしでは作らない
        self.assertTrue(out["missing_incomplete"])
        self.assertIn("restore では戻せません", out["error"])
        self.create(SPEC, "--confirmed")        # --confirmed なら崩れた板の上でも作れる
        self.assertEqual(self.status()["errors"], [])

    def test_k1_nested_sample(self):
        self.create()
        self.insert_raw(NESTED)
        self.assertIn("K1", [e["code"] for e in self.status()["errors"]])

    def test_k2_extra_close(self):
        self.create()
        self.insert_raw("  </div>\n", after="  <!-- DECK:AUTO:END -->\n")
        codes = [e["code"] for e in self.status()["errors"]]
        self.assertIn("K2", codes)
        rc, _ = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 1)

    def test_k3_markers(self):
        self.create()
        self.write(self.text().replace("  <!-- DECK:AUTO:END -->\n", "", 1))
        self.assertIn("K3", [e["code"] for e in self.status()["errors"]])
        rc, _ = self.ed("add", "--section", "今日中", "--title", "x")
        self.assertEqual(rc, 1)

    def test_k4_header_date(self):
        self.create()
        good = be.fmt_full_date(date.today())
        for bad in (date.today().strftime("%m/%d") + "（木）", good[:-3] + "（%s）" % ("月" if good[-2] != "月" else "火")):
            self.write(self.text().replace(good, bad, 1))
            before = self.read()
            rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
            self.assertEqual(rc, 1, bad)
            self.assertIn("K4", [c["code"] for c in out["checks"]])
            self.assertUnchanged(before)
            self.write(self.text().replace(bad, good, 1))

    def test_k4_old_date_is_kept(self):
        self.create()
        d = date(2026, 10, 25)
        self.write(self.text().replace(be.fmt_full_date(date.today()), be.fmt_full_date(d), 1))
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0, out)   # 元の日付のまま（今日でなくてもよい）
        self.assertIn(be.fmt_full_date(d), self.text())

    def test_k5_placeholder(self):
        self.create()
        self.write(self.text().replace('<span class="date">', '<span class="date" data-x="{{FOO}}">', 1))
        before = self.read()
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 1)
        self.assertIn("K5", [c["code"] for c in out["checks"]])
        self.assertUnchanged(before)
        # 項目の文言の {{…}} は K5 に当たらない
        self.write(self.text().replace(' data-x="{{FOO}}"', "", 1))
        rc, out = self.ed("add", "--section", "今日中", "--title", "{{TITLE_DATE}} を直す")
        self.assertEqual(rc, 0, out)

    def _buggy(self, fn):
        def op(text, nl, a):
            r = self.ops["set-chip"](text, nl, a)
            r.text = fn(r.text)
            return r
        be.ITEM_OPS["set-chip"] = op

    def test_k6_k7_k8_script_bugs_are_caught(self):
        self.create()
        before = self.read()
        recs = self.records()
        cases = {
            "K6": lambda t: t.replace("<!-- DECK:AUTO:START -->\n", "<!-- DECK:AUTO:START -->\n<p>x</p>\n", 1),
            "K7": lambda t: t.replace(">ログを更新する<", ">ログを更新しない<", 1),
            "K8": lambda t: t.replace('<div class="section-label">明日以降</div>\n',
                                      '<div class="section-label">明日以降</div>\n' + "".join(be.build_item("  ", "\n", "増えた")), 1),
        }
        for code, fn in cases.items():
            self._buggy(fn)
            rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
            self.assertEqual(rc, 1, code)
            self.assertIn(code, [c["code"] for c in out["checks"]])
            self.assertUnchanged(before)
            self.assertEqual(self.records(), recs)

    def test_k7_untouched_done_mismatch_is_left(self):
        self.create()
        # 作業A を「済チップあり・done-item なし」の不整合にしておく（Deck が整える前の形）
        self.write(self.text().replace('<span class="chip active">進行中</span>', '<span class="chip done">済</span>', 1))
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0, out)
        t = self.text()
        self.assertIn('<p class="task-title">作業A</p>', t)          # 触っていない項目は整えない
        self.assertIn('<p class="task-title strike">作業B</p>', t)   # 触った項目は整える

    def test_k9_missing_upd_time(self):
        self.create()
        self.write(re.sub(r'<span id="upd-time">[^<]*</span>', "", self.text(), count=1))
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 1)
        self.assertIn("K9", [c["code"] for c in out["checks"]])

    def test_header_auto(self):
        self.create()
        self.write(re.sub(r'(<span id="upd-time">)[^<]*', r"\g<1>1:23", self.text(), count=1))
        self.ed("set-chip", "--item", "作業B", "--chip", "done")
        t = self.text()
        self.assertRegex(t, r'<span id="upd-time">\d\d:\d\d</span>')
        self.assertNotIn('<span id="upd-time">1:23</span>', t)
        self.assertIn("1 / 4 完了", t)
        self.assertIn("width:25%", t)

    def test_k11_k12_warn_but_write(self):
        self.create()
        rc, out = self.ed("add", "--section", "本日中", "--create-section", "--title", "x")
        self.assertEqual(rc, 0)
        self.assertIn("K11", [w["code"] for w in out["warnings"]])
        self.write(self.text().replace('<div class="time">9:00</div>', '<div class="time">9時</div>', 1))
        rc, out = self.ed("set-chip", "--item", "作業A", "--chip", "done")
        self.assertEqual(rc, 0)
        self.assertIn("K12", [w["code"] for w in out["warnings"]])


class TestImportantTasks(Sandbox):
    """重要タスク（crit）に件数の上限は無い。古い表示名のチップが残った板もクラスで読む。"""
    OLD = '<span class="chip crit">判断ゲート</span>'
    NEW = '<span class="chip crit">重要タスク</span>'

    def old_board(self):
        """今日の板のチップを古い表示名にする（すでに作ったボードと同じ形）。"""
        self.create()
        self.write(self.text().replace(self.NEW, self.OLD))
        self.assertIn(self.OLD, self.text())

    def test_create_accepts_many_crit(self):
        spec = {"items": [
            {"section": "今日の予定", "time": "9:00", "title": "a", "crit": True},
            {"section": "今日の予定", "time": "10:00", "title": "b", "crit": True},
            {"section": "今日中", "title": "c", "crit": True},
        ]}
        out = self.create(spec)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(self.text().count(self.NEW), 3)
        self.assertEqual([i["crit"] for i in self.items()], [True, True, True])

    def test_set_crit_on_many_no_warning(self):
        self.create()  # SPEC の「判断する」が1件
        for title in ("作業A", "作業B"):
            rc, out = self.ed("set-crit", "--item", title, "on")
            self.assertEqual(rc, 0)
            self.assertEqual(out["warnings"], [])
        self.assertEqual(self.status().get("warnings", []), [])
        self.assertEqual(sum(1 for i in self.items() if i["crit"]), 3)

    def test_old_chip_status_and_ops(self):
        self.old_board()
        self.assertEqual(self.status().get("warnings", []), [])
        its = {i["title"]: i for i in self.items()}
        self.assertTrue(its["判断する"]["crit"])
        self.assertEqual(its["判断する"]["chip"], "pending")
        # 別の行への操作では古いチップに触らない
        self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertIn(self.OLD, self.text())
        # その行のチップを替えても古いチップは残り、crit のまま
        self.ed("set-chip", "--item", "16:00|判断する", "--chip", "done")
        t = self.text()
        self.assertIn(self.OLD + '<span class="chip done">済</span>', t)
        self.assertTrue({i["title"]: i for i in self.items()}["判断する"]["crit"])

    def test_old_chip_set_crit(self):
        self.old_board()
        # on にし直すと新しい表示名へ置き換わり、チップは増えない
        self.ed("set-crit", "--item", "16:00|判断する", "on")
        t = self.text()
        self.assertNotIn(self.OLD, t)
        self.assertEqual(t.count(self.NEW), 1)
        self.write(t.replace(self.NEW, self.OLD))
        # off は古いチップも class も外す
        self.ed("set-crit", "--item", "16:00|判断する", "off")
        t = self.text()
        self.assertNotIn(self.OLD, t)
        self.assertNotIn("item crit", t)

    def test_old_chip_deck_reads_same(self):
        """Deck の走査・形の判定・手書き部分の指紋の入力は、チップの文字で変わらない（クラスで見ている）。"""
        self.create()
        new = self.text().splitlines(keepends=True)
        old = self.text().replace(self.NEW, self.OLD).splitlines(keepends=True)
        self.assertNotEqual(new, old)
        self.assertTrue(dw.board_structure_ok(old))
        sec_new, its_new, deck_new = dw._scan_board(new)
        sec_old, its_old, deck_old = dw._scan_board(old)
        self.assertEqual(sec_old, sec_new)
        self.assertEqual(deck_old, deck_new)
        self.assertEqual(len(its_old), len(its_new))
        a, b = list(new), list(old)
        dw._recalc_progress(a)
        dw._recalc_progress(b)
        self.assertEqual("".join(b), "".join(a).replace(self.NEW, self.OLD))

    def test_old_chip_rollover_keeps_row(self):
        """日付の切り替えは古いチップの行もそのまま引き継ぐ（文字を見ていない）。"""
        self.create()
        text = self.text().replace(self.NEW, self.OLD)
        text = re.sub(r'(<span class="date">)[^<]*', r"\g<1>2020-01-01（水）", text, count=1)
        rolled, _info = dw.roll_board_text(text, date(2020, 1, 2), "09:00")
        self.assertIn(self.OLD, rolled)
        self.assertRegex(rolled, r'class="item[^"]*crit')


# ------------------------------------------------------------------ T-P（Deck との写しの一致）

COPIED = ["_blank_comments", "_canon_section", "_scan_board", "_element_text", "_item_key", "_recalc_progress",
          "_toggle_class_token", "_normalize_item_block", "board_header_date_text", "parse_board_date",
          "_marker_counts", "_item_start_lines", "board_structure_ok", "_canon_label", "_remove_time_elements",
          "_div_balance", "hand_fingerprint"]
COPIED_CONSTS = ["MARKER_START", "MARKER_END", "MOVABLE_SECTIONS", "CANON_SECTIONS", "WEEKDAY_JA", "_SECTION_LABEL_RE",
                 "_CLASS_TAG_RE", "_STRIP_TAGS_RE", "_CHIP_TOKEN_RE", "_CHIP_DONE_RE", "_ITEM_CLASS_RE",
                 "_ANY_CLASS_TAG_RE", "_HEADER_RE", "_TITLE_RE", "_UPD_TIME_RE", "_ITEM_OPEN_RE", "_TIME_OPEN_RE",
                 "_FOOTER_LINE_RE"]
# 書き込みの記録（.guard/）の節。Deck v2.6 が board_edit.py から写したもの
GUARD_COPIED = ["_guard_atomic_write", "guard_format_ok", "guard_write_record", "guard_remove_record",
                "guard_prune_records"]
GUARD_COPIED_CONSTS = ["GUARD_DIRNAME", "GUARD_FORMAT_V", "GUARD_RECORD_MAX_AGE_SEC", "_guard_last_ns"]


def _sources(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    lines = src.splitlines()
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = "\n".join(lines[node.lineno - 1:node.end_lineno])
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = "\n".join(lines[node.lineno - 1:node.end_lineno])
    return out


class TestDeckCopy(Sandbox):
    def test_source_identical(self):
        a = _sources(SCRIPT)
        b = _sources(os.path.join(ROOT, "deck", "deck_watcher.py"))
        for name in COPIED + COPIED_CONSTS + GUARD_COPIED + GUARD_COPIED_CONSTS:
            self.assertIsNotNone(a.get(name), name)
            self.assertEqual(a.get(name), b.get(name), name)

    def test_guard_record_same_form(self):
        """board_edit と Deck の記録は、同じ名前の形・同じ中身（writer を除く）で、互いの掃除で消える。"""
        self.create()
        body = self.read()
        fp = be.hand_fingerprint(self.text())
        r1 = be.guard_write_record(self.board, body, fp, "base", "board_edit")
        r2 = dw.guard_write_record(self.board, body, fp, "base", "deck")
        for r in (r1, r2):
            self.assertRegex(os.path.basename(r[0]), r"^\d{20}-%d\.json$" % os.getpid())
            self.assertEqual(os.path.basename(r[1]), os.path.basename(r[0])[:-5] + ".html")
            with open(r[1], "rb") as f:
                self.assertEqual(f.read(), body)
        with open(r1[0], encoding="utf-8") as f:
            j1 = json.load(f)
        with open(r2[0], encoding="utf-8") as f:
            j2 = json.load(f)
        self.assertEqual(sorted(j1), sorted(j2))
        self.assertEqual((j1["writer"], j2["writer"]), ("board_edit", "deck"))
        for k in ("v", "fp", "base_fp"):
            self.assertEqual(j1[k], j2[k], k)
        self.assertNotEqual(r1[0], r2[0])
        with open(os.path.join(self.dir, ".guard", "format.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1})
        # Deck の掃除は board_edit の記録も、board_edit の掃除は Deck の記録も消す（同じ規則）
        later = time.time_ns() + 49 * 3600 * 10 ** 9
        n = len([x for x in self.records() if x.endswith(".json")])
        self.assertGreaterEqual(n, 3)          # create の記録・r1・r2
        self.assertEqual(dw.guard_prune_records(self.board, now_ns=later), n)
        self.assertEqual(self.records(), [])

    def boards(self):
        self.create()
        good = self.text()
        variants = [good, good.replace("\n", "\r\n"), good.replace("<span class=\"chip active\">進行中</span>",
                                                                   "<span class=\"chip done\">済</span>")]
        variants.append(good.replace('<div class="section-label">今日中</div>\n', '<div class="section-label">今日中</div>\n' + NESTED))
        variants.append(good.replace("  <!-- DECK:AUTO:END -->\n", ""))
        variants.append(good.replace("<!-- DECK:AUTO:START -->\n", "<!-- DECK:AUTO:START -->\n" + "".join(
            be.build_item("  ", "\n", "セッション", chip="active")).replace('class="item flat"', 'class="item flat" data-sid="x"')))
        return variants

    def test_behaviour_matches(self):
        today = date.today()
        for t in self.boards():
            lines = t.splitlines(keepends=True)
            self.assertEqual(be.hand_fingerprint(t), dw.hand_fingerprint(t))
            self.assertEqual(be.board_structure_ok(lines), dw.board_structure_ok(lines))
            self.assertEqual(be._div_balance(t), dw._div_balance(t))
            self.assertEqual(be._scan_board(lines), dw._scan_board(lines))
            self.assertEqual(be.parse_board_date(be.board_header_date_text(t), today),
                             dw.parse_board_date(dw.board_header_date_text(t), today))
            l1, l2 = list(lines), list(lines)
            be._recalc_progress(l1)
            dw._recalc_progress(l2)
            self.assertEqual(l1, l2)

    def test_written_board_is_deck_normal(self):
        """board_edit が書いた板は、Deck の inject で手書き部分が変わらない（指紋・進捗が同じ）。"""
        self.create()
        self.ed("set-chip", "--item", "作業A", "--chip", "done")
        t = self.text()
        self.assertIsNone(dw.normalize_done_marks(t))
        lines = t.splitlines(keepends=True)
        l2 = list(lines)
        dw._recalc_progress(l2)
        self.assertEqual(lines, l2)


# ------------------------------------------------------------------ T-R（restore）

class TestRestore(Sandbox):
    def hist(self, name, data):
        h = os.path.join(self.dir, "history")
        os.makedirs(h, exist_ok=True)
        with open(os.path.join(h, name), "wb") as f:
            f.write(data)
        return "history/" + name

    def setUp(self):
        Sandbox.setUp(self)
        self.create()
        self.good = self.read()
        self.ed("add", "--section", "今日中", "--title", "後から足した行")
        self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.iso = date.today().isoformat()

    def test_accepts_three_forms(self):
        for kind in ("lastgood", "before-interrupt", "before-tool", "before-create"):
            for suffix in ("", "-2"):
                name = self.hist("board-%s-%s-120000%s.html" % (self.iso, kind, suffix), self.good)
                cur = self.read()
                rc, out = self.ed("restore", "--from", name)
                self.assertEqual(rc, 0, out)
                self.assertFalse(out["changed"])
                self.assertIn("後から足した行", [x["title"] for x in out["diff"]["only_now"]])
                if kind == "lastgood" and not suffix:   # 1回目だけ、作業B のチップの違いも差に出る
                    self.assertEqual(out["diff"]["only_restore"], [{"section": "今日中", "time": None, "title": "作業B", "note": None,
                                                                    "chip": "pending", "crit": False, "carried": None}])
                self.assertUnchanged(cur)
                rc, out = self.ed("restore", "--from", name, "--confirmed")
                self.assertEqual(rc, 0, out)
                self.assertTrue(out["changed"])
                self.assertNotIn("後から足した行", self.text())
                saved = os.path.join(self.dir, out["saved"])
                with open(saved, "rb") as f:
                    self.assertEqual(f.read(), cur)    # 戻す前の版を before-restore に残す
                self.assertRegex(out["saved"], r"^history/board-%s-before-restore-\d{6}(-\d+)?\.html$" % self.iso)
                self.ed("add", "--section", "今日中", "--title", "後から足した行")

    def test_rejects(self):
        cur = self.read()
        bad_names = ["board-%s.html" % self.iso, "board-%s-foreign-120000.html" % self.iso,
                     "board-%s-before-restore-120000.html" % self.iso, "board-%s-lastgood-1200.html" % self.iso,
                     "other.html"]
        for n in bad_names:
            rel = self.hist(n, self.good)
            rc, out = self.ed("restore", "--from", rel, "--confirmed")
            self.assertEqual(rc, 1, n)
            self.assertUnchanged(cur)
        # history/ の外
        outside = os.path.join(self.dir, "board-%s-lastgood-120000.html" % self.iso)
        with open(outside, "wb") as f:
            f.write(self.good)
        rc, out = self.ed("restore", "--from", outside, "--confirmed")
        self.assertEqual(rc, 1)
        # 日付が違う版
        other = self.good.decode("utf-8").replace(be.fmt_full_date(date.today()), be.fmt_full_date(date(2026, 1, 5)))
        rel = self.hist("board-%s-lastgood-130000.html" % self.iso, other.encode("utf-8"))
        rc, out = self.ed("restore", "--from", rel, "--confirmed")
        self.assertEqual(rc, 1)
        # 崩れた版（K1）・未置換（K5）
        broken = self.good.decode("utf-8").replace('<div class="section-label">今日中</div>\n',
                                                   '<div class="section-label">今日中</div>\n' + NESTED)
        rel = self.hist("board-%s-lastgood-140000.html" % self.iso, broken.encode("utf-8"))
        rc, out = self.ed("restore", "--from", rel, "--confirmed")
        self.assertEqual(rc, 1)
        self.assertIn("K1", [c["code"] for c in out["checks"]])
        ph = self.good.decode("utf-8").replace("<title>", "<title>{{TITLE_DATE}}", 1)
        rel = self.hist("board-%s-before-tool-150000.html" % self.iso, ph.encode("utf-8"))
        rc, out = self.ed("restore", "--from", rel, "--confirmed")
        self.assertEqual(rc, 1)
        self.assertUnchanged(cur)
        self.assertNotIn(os.path.basename(outside), [os.path.basename(x) for x in self.status()["restorable"]])

    def test_restore_diff_from_broken_board(self):
        """崩れた板でも、崩れより後ろの行が only_now から抜けない（M1）。"""
        rel = self.hist("board-%s-lastgood-120000.html" % self.iso, self.good)
        self.write(self.text().replace('<div class="section-label">今日中</div>\n',
                                       '<div class="section-label">今日中</div>\n' + NESTED))
        rc, out = self.ed("restore", "--from", rel)
        self.assertEqual(rc, 0, out)
        titles = [x["title"] for x in out["diff"]["only_now"]]
        self.assertIn("後から足した行", titles)    # 崩れより後ろの行
        self.assertIn("中", titles)
        self.assertTrue(out["diff"]["only_now_incomplete"])
        self.assertIn("only_now_incomplete", out["message"])

    def test_restore_onto_broken_board(self):
        rel = self.hist("board-%s-lastgood-120000.html" % self.iso, self.good)
        self.write(self.text().replace('<div class="section-label">今日中</div>\n',
                                       '<div class="section-label">今日中</div>\n' + NESTED))
        rc, out = self.ed("restore", "--from", rel, "--confirmed")
        self.assertEqual(rc, 0, out)
        self.assertTrue(out["diff"]["now_broken"])
        self.assertEqual(self.status()["errors"], [])
        self.assertIn(rel, self.status()["restorable"])

    def test_restore_source_not_utf8(self):
        """戻す版が読めないときは、いまの板ではなく戻す版のことを言う（N2）。"""
        good = self.hist("board-%s-lastgood-110000.html" % self.iso, self.good)
        rel = self.hist("board-%s-lastgood-120000.html" % self.iso, self.good + b"\xff")
        cur = self.read()
        rc, out = self.ed("restore", "--from", rel)
        self.assertEqual(rc, 1)
        self.assertIn("（戻す版）を UTF-8 として読めない", out["error"])
        self.assertNotIn("いまの", out["error"])
        self.assertEqual(out["candidates"], [good])
        self.assertUnchanged(cur)

    def test_restorable_today(self):
        """status の restorable_today は、いまの板と日付が同じで形の正しい、戻せる版だけ（R-c）。"""
        ok = self.hist("board-%s-lastgood-110000.html" % self.iso, self.good)
        other = self.good.decode("utf-8").replace(be.fmt_full_date(date.today()), be.fmt_full_date(date(2026, 1, 5)))
        self.hist("board-2026-01-05-before-create-110000.html", other.encode("utf-8"))
        broken = self.good.decode("utf-8").replace('<div class="section-label">今日中</div>\n',
                                                   '<div class="section-label">今日中</div>\n' + NESTED)
        self.hist("board-%s-lastgood-120000.html" % self.iso, broken.encode("utf-8"))
        self.hist("board-%s-lastgood-130000.html" % self.iso, self.good + b"\xff")
        st = self.status()
        self.assertEqual(len(st["restorable"]), 4)
        self.assertEqual(st["restorable_today"], [ok])

    def test_restore_good_board_is_complete(self):
        rel = self.hist("board-%s-lastgood-120000.html" % self.iso, self.good)
        rc, out = self.ed("restore", "--from", rel)
        self.assertFalse(out["diff"]["only_now_incomplete"])
        x = [e for e in out["diff"]["only_now"] if e["title"] == "後から足した行"][0]
        self.assertEqual(set(x), {"section", "time", "title", "note", "chip", "crit", "carried"})


# ------------------------------------------------------------------ create の退避と、消える行の確かめ

class TestCreateGuard(Sandbox):
    def spec_file(self, spec):
        p = os.path.join(self.dir, "s.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        return p

    def test_backup_before_create(self):
        self.create()
        self.write(re.sub(r'(<span id="upd-time">)[^<]*', r"\g<1>1:23", self.text(), count=1))
        before = self.read()
        out = self.create()
        self.assertRegex(out["saved"], r"^history/board-%s-before-create-\d{6}(-\d+)?\.html$" % date.today().isoformat())
        with open(os.path.join(self.dir, out["saved"]), "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertIn(out["saved"], self.status()["restorable"])

    def test_missing_rows_need_confirmed(self):
        self.create()
        self.ed("add", "--section", "今日中", "--title", "他のセッションの行", "--note", "proj")
        before = self.read()
        p = self.spec_file(SPEC)
        rc, out = run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 1)
        self.assertEqual(out["missing"], [{"no": 1, "status_index": 5, "section": "今日中", "time": None,
                                           "title": "他のセッションの行", "chip": "pending", "note": "proj"}])
        self.assertFalse(out["missing_incomplete"])
        self.assertNotIn("missing_incomplete）", out["error"])
        self.assertIn("まだ作り直していません", out["error"])
        self.assertUnchanged(before)
        self.assertEqual(self.status()["restorable"], [])   # 拒否したときは退避も書かない
        # spec に足せば通る
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"].append({"section": "今日中", "title": "他のセッションの行", "note": "proj"})
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 0, out)
        # 足さずに --confirmed でも通る（退避は残る）
        self.ed("add", "--section", "今日中", "--title", "もう1行")
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("もう1行", self.text())
        self.assertEqual([r["title"] for r in out["removed"]], ["他のセッションの行", "もう1行"])   # 書いた時点で spec に無かった行
        self.assertEqual([r["no"] for r in out["removed"]], [1, 2])
        self.assertFalse(out["removed_incomplete"])
        with open(os.path.join(self.dir, out["saved"]), encoding="utf-8") as f:
            self.assertIn("もう1行", f.read())

    def test_no_confirm_for_old_or_rolled_board(self):
        self.create()
        self.ed("add", "--section", "今日中", "--title", "昨日の行")
        t = self.text()
        self.write(t.replace(be.fmt_full_date(date.today()), be.fmt_full_date(date(2026, 1, 5)), 1))
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC)])
        self.assertEqual(rc, 0, out)               # 昨日以前の板は確かめない
        self.assertIn("board-2026-01-05-before-create-", out["saved"])
        self.ed("add", "--section", "今日中", "--title", "引き継いだ行")
        self.write(self.text().replace('<div class="board">', '<div class="board" data-tb-rolled="2026-10-28">', 1))
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC)])
        self.assertEqual(rc, 0, out)               # Deck が引き継いだ板は確かめない

    def test_unreadable_date_needs_confirmed(self):
        """ヘッダの日付が読めない板に手書きの行があるときも、確かめなしでは作らない（R-d）。"""
        self.create()
        self.ed("add", "--section", "今日中", "--title", "読めない日の行")
        self.write(self.text().replace(be.fmt_full_date(date.today()), "そのうち", 1))
        before = self.read()
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC)])
        self.assertEqual(rc, 1)
        self.assertEqual([r["title"] for r in out["missing"]], ["読めない日の行"])
        self.assertUnchanged(before)
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC), "--confirmed"])
        self.assertEqual(rc, 0, out)

    def test_backup_failure_refuses(self):
        """history/ へ退避できなければ板を書かない（R-a・R-b）。"""
        self.create()
        self.ed("add", "--section", "今日中", "--title", "x")
        with open(os.path.join(self.dir, "history"), "w") as f:
            f.write("history をファイルにして、退避を失敗させる")
        before = self.read()
        recs = self.records()
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"].append({"section": "今日中", "title": "x"})
        spec2["items"].append({"section": "今日中", "title": "新しい行"})
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 1, out)
        self.assertIn("退避できなかった", out["error"])
        self.assertUnchanged(before)
        self.assertEqual(self.records(), recs)

    def test_backup_name_taken_just_before_write(self):
        """退避の名前は書く段で排他的に決める。直前に同名のファイルが置かれても上書きしない（N3）。"""
        self.create()
        self.write(re.sub(r'(<span id="upd-time">)[^<]*', r"\g<1>1:23", self.text(), count=1))
        planted = {}

        def hook(extra):
            stem = extra[0][0]
            h = os.path.join(self.dir, "history")
            os.makedirs(h, exist_ok=True)
            p = os.path.join(h, stem + ".html")
            with open(p, "wb") as f:
                f.write(b"other writer")
            planted["path"] = p
            planted["name"] = "history/" + stem + ".html"
        be._HOOK_BEFORE_EXTRA = hook
        try:
            out = self.create()
        finally:
            be._HOOK_BEFORE_EXTRA = None
        with open(planted["path"], "rb") as f:
            self.assertEqual(f.read(), b"other writer")          # ①置かれたファイルは変わらない
        self.assertNotEqual(out["saved"], planted["name"])         # ②saved は別の名前
        self.assertRegex(out["saved"], r"-2\.html$")
        self.assertTrue(os.path.isfile(os.path.join(self.dir, out["saved"])))
        self.assertEqual([n for n in os.listdir(os.path.join(self.dir, "history")) if n.endswith(".tmp")], [])

    def test_restore_backup_name_taken_just_before_write(self):
        self.create()
        good = self.read()
        self.ed("add", "--section", "今日中", "--title", "後で足した")
        h = os.path.join(self.dir, "history")
        os.makedirs(h, exist_ok=True)
        name = "board-%s-lastgood-120000.html" % date.today().isoformat()
        with open(os.path.join(h, name), "wb") as f:
            f.write(good)
        planted = {}

        def hook(extra):
            p = os.path.join(h, extra[0][0] + ".html")
            with open(p, "wb") as f:
                f.write(b"other writer")
            planted["p"] = p
        be._HOOK_BEFORE_EXTRA = hook
        try:
            rc, out = self.ed("restore", "--from", "history/" + name, "--confirmed")
        finally:
            be._HOOK_BEFORE_EXTRA = None
        self.assertEqual(rc, 0, out)
        with open(planted["p"], "rb") as f:
            self.assertEqual(f.read(), b"other writer")
        self.assertNotEqual(os.path.join(self.dir, out["saved"]), planted["p"])
        with open(os.path.join(self.dir, out["saved"]), encoding="utf-8") as f:
            self.assertIn("後で足した", f.read())

    def test_unreadable_board_removed_is_null(self):
        """いまの板が UTF-8 で読めないときの create は removed: null・removed_incomplete: true（R2）。"""
        self.create()
        self.write(self.read() + b"\xff")
        out = self.create(SPEC, "--confirmed")
        self.assertIsNone(out["removed"])
        self.assertTrue(out["removed_incomplete"])

    def test_create_replace_fails_after_backup(self):
        """退避の後に置き換えが失敗したら、退避・記録・一時ファイルを残さず、板も変えない（W1）。"""
        self.create()
        self.ed("add", "--section", "今日中", "--title", "大事")
        before = self.read()
        hist = sorted(os.listdir(os.path.join(self.dir, "history"))) if os.path.isdir(os.path.join(self.dir, "history")) else []
        recs = self.records()
        p = subprocess.Popen([sys.executable, "-I", "-c", HOLD, self.board, "4"], stdout=subprocess.PIPE)
        self.assertEqual(p.stdout.readline().strip(), b"ready")
        p.stdout.close()
        try:
            rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC), "--confirmed"])
        finally:
            p.wait()
        self.assertEqual(rc, 1, out)
        self.assertUnchanged(before)
        h = os.path.join(self.dir, "history")
        self.assertEqual(sorted(os.listdir(h)) if os.path.isdir(h) else [], hist)
        self.assertEqual(self.records(), recs)
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_create_retry_after_intruder(self):
        """読み直しで割り込みを見つけてやり直したら、1回目の退避を消し、2回目の退避は割り込んだ版を持つ（W2）。"""
        self.create()
        self.ed("add", "--section", "今日中", "--title", "大事")
        calls = []

        def hook(attempt, record):
            calls.append(sorted(os.listdir(os.path.join(self.dir, "history"))))
            if attempt == 0:
                self.write(self.text().replace("作業B", "作業B改", 1))
        be._HOOK_BEFORE_REREAD = hook
        try:
            rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC), "--confirmed"])
        finally:
            be._HOOK_BEFORE_REREAD = None
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sorted(os.listdir(os.path.join(self.dir, "history"))), ["/".join(out["saved"].split("/")[1:])])
        with open(os.path.join(self.dir, out["saved"]), encoding="utf-8") as f:
            self.assertIn("作業B改", f.read())
        self.assertEqual(sorted(r["title"] for r in out["removed"]), ["作業B改", "大事"])

    def test_create_on_unreadable_board_needs_confirmed(self):
        """UTF-8 として読めない板には、--confirmed が無ければ create も書かない（P3）。"""
        self.create()
        self.write(self.read() + b"\xff")
        before = self.read()
        recs = self.records()
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC)])
        self.assertEqual(rc, 1)
        self.assertEqual(out["error"], "board.html を UTF-8 として読めません。何も書いていません。この板は restore でも戻せません（restore もいまの板を読むため）。ボードを書かずに、この出力をユーザーに見せて、どうするかを確かめてください。")
        self.assertEqual(out["missing"], [])
        self.assertTrue(out["missing_incomplete"])
        self.assertUnchanged(before)
        self.assertEqual(self.records(), recs)
        self.assertFalse(os.path.isdir(os.path.join(self.dir, "history")))

    def test_write_tmp_failure_leaves_no_tmp(self):
        """一時ファイルへの書き込みが失敗したら、一時ファイルを残さない（P1）。"""
        with self.assertRaises(TypeError):
            be._write_tmp(self.dir, "bytes ではない")
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_history_xb_failure_removes_own_file(self):
        """os.link が使えず xb で書く経路で、書く途中に失敗したら、自分が作ったファイルだけを消す（P2）。"""
        h = os.path.join(self.dir, "history")
        os.makedirs(h)
        other = os.path.join(h, "board-x.html")
        with open(other, "wb") as f:
            f.write(b"other writer")
        real_open = open

        class Failing(object):
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.f.close()

            def write(self, data):
                raise OSError(28, "disk full")

        def fake_open(path, mode="r", *args, **kw):
            f = real_open(path, mode, *args, **kw)
            return Failing(f) if mode == "xb" else f

        def no_link(src, dst):
            raise OSError(1, "link not supported")
        be.open = fake_open
        saved_link = be.os.link
        be.os.link = no_link
        try:
            with self.assertRaises(OSError):
                be.create_history_file(self.board, "board-x", b"data")
        finally:
            del be.open
            be.os.link = saved_link
        self.assertEqual(sorted(os.listdir(h)), ["board-x.html"])       # 自分の -2 は消え、他の書き手のものは残る
        with open(other, "rb") as f:
            self.assertEqual(f.read(), b"other writer")

    def test_create_on_unreadable_board_backs_up(self):
        self.create()
        self.write(self.read() + b"\xff")
        raw = self.read()
        out = self.create(SPEC, "--confirmed")
        with open(os.path.join(self.dir, out["saved"]), "rb") as f:
            self.assertEqual(f.read(), raw)


# ------------------------------------------------------------------ T-W（書き込み）

HOLD = "import sys,time\nf=open(sys.argv[1],'rb')\nprint('ready',flush=True)\ntime.sleep(float(sys.argv[2]))\n"


class TestWrite(Sandbox):
    def hold(self, sec):
        p = subprocess.Popen([sys.executable, "-I", "-c", HOLD, self.board, str(sec)], stdout=subprocess.PIPE)
        self.assertEqual(p.stdout.readline().strip(), b"ready")
        p.stdout.close()
        return p

    def test_retry_while_reader_has_file_open(self):
        self.create()
        p = self.hold(0.5)
        try:
            rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        finally:
            p.wait()
        self.assertEqual(rc, 0, out)
        self.assertGreaterEqual(be._last_replace_tries[0], 2)   # 1回目は読み取り中で失敗し、やり直して通った
        self.assertEqual({i["title"]: i for i in self.items()}["作業B"]["chip"], "done")

    def test_retries_exhausted(self):
        self.create()
        before = self.read()
        recs = self.records()
        p = self.hold(3)
        try:
            rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        finally:
            p.wait()
        if sys.platform != "win32":
            self.skipTest("読み取り中の os.replace の失敗は Windows だけで起きる")
        self.assertEqual(rc, 1, out)
        self.assertEqual(be._last_replace_tries[0], be.REPLACE_RETRIES + 1)
        self.assertUnchanged(before)
        self.assertEqual(self.records(), recs)   # 自分の記録は消す
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_retry_rereads_before_next_replace(self):
        """読み取りで開かれて置き換えを待つ間に、別の書き手が置き換えた版を消さない（待った後に読み直して比べる）。"""
        self.create()
        p = self.hold(0.3)

        def other():
            p.wait()                  # 読み手が閉じた直後に
            time.sleep(0.02)
            self.write(self.text().replace("<p class=\"task-title\">作業A</p>", "<p class=\"task-title\">作業A-他の書き手</p>", 1))
        th = threading.Thread(target=other)
        th.start()
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        th.join()
        self.assertEqual(rc, 0, out)
        t = self.text()
        self.assertIn("作業A-他の書き手", t)                       # 別の書き手の版が残り
        self.assertIn('<p class="task-title strike">作業B</p>', t)  # そのうえに書いた
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_record_before_replace(self):
        self.create()
        seen = {}

        def hook(attempt, record):
            seen["record"] = record
            seen["board_has_new"] = "作業B</p>\n      <div class=\"chips\"><span class=\"chip done\">" in self.text()
            with open(record[0], encoding="utf-8") as f:
                seen["json"] = json.load(f)
            with open(record[1], "rb") as f:
                seen["body"] = f.read()
        be._HOOK_BEFORE_REREAD = hook
        old_fp = be.hand_fingerprint(self.text())
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0, out)
        self.assertFalse(seen["board_has_new"])                     # 置き換えの前に
        self.assertEqual(seen["body"], self.read())                 # 記録の本文＝置き換えた版
        j = seen["json"]
        self.assertEqual(j["v"], 1)
        self.assertEqual(j["writer"], "board_edit")
        self.assertEqual(j["base_fp"], old_fp)
        self.assertEqual(j["fp"], be.hand_fingerprint(self.text()))
        self.assertEqual(j["body"], os.path.basename(seen["record"][1]))
        self.assertRegex(os.path.basename(seen["record"][0]), r"^\d{20}-\d+\.json$")

    def test_reread_detects_other_writer_and_retries(self):
        self.create()
        calls = []

        def hook(attempt, record):
            calls.append(record)
            if attempt == 0:   # 他の書き手が割り込んだ（別の行を足した）
                t = self.text().replace("<p class=\"task-title\">作業A</p>", "<p class=\"task-title\">作業A改</p>", 1)
                self.write(t)
        be._HOOK_BEFORE_REREAD = hook
        n_before = len(self.records())
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(calls), 2)
        self.assertFalse(os.path.exists(calls[0][0]))     # 1回目の記録は消した
        self.assertFalse(os.path.exists(calls[0][1]))
        self.assertTrue(os.path.exists(calls[1][0]))
        self.assertEqual(len(self.records()), n_before + 2)
        t = self.text()
        self.assertIn("作業A改", t)                          # 割り込んだ書き込みを消していない
        self.assertIn('<p class="task-title strike">作業B</p>', t)

    def test_reread_gives_up(self):
        self.create()
        n = [0]

        def hook(attempt, record):
            n[0] += 1
            self.write(self.text().replace("</footer>", "</footer><!-- %d -->" % n[0], 1))
        be._HOOK_BEFORE_REREAD = hook
        recs = self.records()
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 1)
        self.assertEqual(n[0], be.REREAD_ATTEMPTS)
        self.assertEqual(self.records(), recs)

    def test_no_record_when_fingerprint_unchanged(self):
        self.create()
        recs = self.records()
        rc, out = self.ed("set-chip", "--item", "作業A", "--chip", "active")   # 同じチップ＝本文は #upd-time だけ変わる
        self.assertEqual(rc, 0)
        self.assertEqual(self.records(), recs)


# ------------------------------------------------------------------ T-E（往復）

class TestEncoding(Sandbox):
    def test_bom_crlf_roundtrip(self):
        self.create()
        raw = b"\xef\xbb\xbf" + self.read().replace(b"\n", b"\r\n")
        self.write(raw)
        title = "日本語 & <tag> \"q\" 'a'"
        rc, out = self.ed("add", "--section", "今日中", "--title", title, "--note", "a<b>&c")
        self.assertEqual(rc, 0, out)
        new = self.read()
        self.assertTrue(new.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(new.count(b"\n"), new.count(b"\r\n"))
        d = {i["title"]: i for i in self.items()}
        self.assertEqual(d[title]["note"], "a<b>&c")
        self.assertIn("日本語 &amp; &lt;tag&gt;", new.decode("utf-8-sig"))

    def test_lf_kept(self):
        self.create()
        rc, _ = self.ed("add", "--section", "今日中", "--title", "x")
        self.assertNotIn(b"\r\n", self.read())

    def test_not_utf8(self):
        self.create()
        self.write(self.read() + b"\xff\xfe")
        before = self.read()
        rc, out = self.ed("add", "--section", "今日中", "--title", "x")
        self.assertEqual(rc, 1)
        self.assertUnchanged(before)

    def test_newline_in_title_rejected(self):
        self.create()
        rc, out = self.ed("add", "--section", "今日中", "--title", "a\nb")
        self.assertEqual(rc, 1)


# ------------------------------------------------------------------ .guard/ の形式

class TestGuardRecords(Sandbox):
    def test_format_created_only_when_absent(self):
        self.create()
        fmt = os.path.join(self.dir, ".guard", "format.json")
        with open(fmt, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1})
        with open(fmt, "w", encoding="utf-8") as f:
            json.dump({"v": 2}, f)
        recs = self.records()
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0, out)
        self.assertIn("guard", [w["code"] for w in out["warnings"]])
        self.assertEqual(self.records(), recs)   # 知らない版では記録を書かない
        with open(fmt, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 2})   # 上書きしない

    def test_format_unreadable_writes_without_record(self):
        """format.json が読めない（壊れている）ときは「知らない版」と同じ: 記録を書かずに板を書き、guard の警告を返す。"""
        self.create()
        fmt = os.path.join(self.dir, ".guard", "format.json")
        with open(fmt, "wb") as f:
            f.write(b"{broken")
        recs = self.records()
        rc, out = self.ed("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0, out)
        self.assertIn("guard", [w["code"] for w in out["warnings"]])
        self.assertEqual({i["title"]: i for i in self.items()}["作業B"]["chip"], "done")
        self.assertEqual(self.records(), recs)
        with open(fmt, "rb") as f:
            self.assertEqual(f.read(), b"{broken")      # 直さない・上書きしない

    def test_record_pairs_and_prune(self):
        self.create()
        self.ed("set-chip", "--item", "作業B", "--chip", "done")
        recs = self.records()
        self.assertEqual(len(recs) % 2, 0)
        stems = {r.rsplit(".", 1)[0] for r in recs}
        self.assertEqual(len(stems) * 2, len(recs))
        adir = os.path.join(self.dir, ".guard", "auth")
        old = "%020d-1" % (time.time_ns() - 49 * 3600 * 10 ** 9)
        for ext in (".html", ".json"):
            open(os.path.join(adir, old + ext), "w").close()
        orphan = "%020d-2.html" % (time.time_ns() - 50 * 3600 * 10 ** 9)
        open(os.path.join(adir, orphan), "w").close()
        self.assertEqual(be.guard_prune_records(self.board), 1)
        self.assertEqual(sorted(os.listdir(adir)), recs)

    def test_create_on_missing_board_records_null_base(self):
        self.create()
        adir = os.path.join(self.dir, ".guard", "auth")
        js = [n for n in os.listdir(adir) if n.endswith(".json")]
        self.assertEqual(len(js), 1)
        with open(os.path.join(adir, js[0]), encoding="utf-8") as f:
            self.assertIsNone(json.load(f)["base_fp"])


if __name__ == "__main__":
    unittest.main()
