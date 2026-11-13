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

    def put_legacy_early(self, title, due):
        """タイトル title の今日の側の行を、v1.8・Deck v2.12 までに先の日の行を前もって今日の側へ動かした形にする（サンドボックスの板だけ）。

        実施日を due（先の日）に戻し、一度移した印と元の実施日を外す。v1.9・v2.13 の move・D&D は先の日の行も今日の行にするので、
        この形はそれらの操作では作れない。"""
        self.put_legacy_due(title, due)
        lines = self.text().splitlines(keepends=True)
        _secs, items = be.layout(lines)
        s = [x for x in items if be._element_text("".join(lines[x["s"]:x["e"] + 1]), "task-title") == title][0]["s"]
        lines[s] = re.sub(r'\sdata-due-(?:moved|from)="[^"]*"', "", lines[s])
        self.write("".join(lines))

    def put_legacy_due(self, title, due, time=None):
        """タイトル title の行の data-due を due に書き換える（サンドボックスの板だけ）。

        v1.6 までの操作（今日の側で set-time してから「明日以降」へ戻す等）でできた、時刻の欄と実施日の時刻が違う行を作る。
        v1.7 の set-time・set-due・add・create は時刻の欄と実施日の時刻を同じ値にするので、この形はそれらの操作では作れない。time を渡すと、時刻の欄がその文字の行だけを見る。"""
        lines = self.text().splitlines(keepends=True)
        _secs, items = be.layout(lines)
        hits = [x for x in items if be._element_text("".join(lines[x["s"]:x["e"] + 1]), "task-title") == title
                and (time is None or (be._element_text("".join(lines[x["s"]:x["e"] + 1]), "time") or "").strip() == time)]
        self.assertEqual(len(hits), 1, hits)
        s = hits[0]["s"]
        new, n = re.subn(r'(\sdata-due=")[^"]*(")', lambda m: m.group(1) + due + m.group(2), lines[s], count=1)
        self.assertEqual(n, 1, lines[s])
        lines[s] = new
        self.write("".join(lines))

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
        rc, out = self.ed("move", "--item", "作業B", "--section", "明日以降", "--head", "--due", "none")
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


# 時刻の欄の中の svg・math の形と、ブラウザの読み方（v2.19 / board_edit.py v1.15。Chrome・Edge で確かめる＝tests/test_board_browser.py の
# test_time_field_foreign_matches_browser）。"close"＝ブラウザが外側の閉じタグで欄を閉じ、タイトルは欄の外（_time_screen_closed）、
# "reopen"＝閉じた後で書式の要素を開き直す（_time_reopened）、"keep"＝欄を閉じず、タイトルが欄の中に入る（_time_keeps_open）
TIME_FOREIGN_CASES = [
    ("<svg><span><desc>", "close"),          # span が svg を閉じ、desc は HTML の要素
    ("<math><span><mi>", "close"),
    ("<svg><p><desc>", "close"),
    ("<svg></p><desc>", "close"),            # </p> も svg を閉じる
    ("<math><b><mi>", "reopen"),             # b が math を閉じ、HTML の b が開き直される
    ('<svg><font color="red"><desc>', "reopen"),   # 属性のある font は svg を閉じる（HTML の font は書式の要素）
    ("<svg><font><desc>", "keep"),           # 属性の無い font は svg の要素のまま。desc は svg の境界
    ("<svg><textarea>", "close"),            # svg の中の textarea・style は svg の要素
    ("<svg><style>", "close"),
    ("<svg><foreignObject><span>x</svg>", "keep"),   # 境界の中の HTML から書いた </svg> は読み飛ばす
    ("<math><mi><span>x</math>", "keep"),
    ("<svg><foreignObject>x</svg>", "close"),        # 境界の直下の </svg> は svg を閉じる
    ("<svg>", "close"),                      # svg・math そのものが閉じていない形
    ("<svg><circle>", "close"),
    ("<svg><g>", "close"),
    ("<math>", "close"),
    ("<svg><desc>", "keep"),
    ("<svg><title>", "keep"),
    ("<math><annotation-xml>", "keep"),
    ('<math><annotation-xml encoding="text/html">', "keep"),
    ("<svg><foreignObject>y</foreignObject>", "close"),
    ("<svg><desc>y</desc></svg>", "close"),
    # 欄が div で、中の範囲の境界（table の td・object）が開いたまま。</div> は範囲の外の欄まで届かず、欄を閉じない（3つ目＝欄のタグ。v2.21 / board_edit.py v1.17）
    ("<table><tr><td>", "keep", "div"),
    ("<object>", "keep", "div"),
    # 欄が p で、中に開いたままの button がある。</p> は欄を閉じず、外側の </div> で閉じる（ボタンの範囲）。table の td なら </div> も届かない
    ("<button>a</p>", "close", "p"),
    ("<table><tr><td>a</p>", "keep", "p"),
]


def time_foreign_row(inner, title="T", tag="span"):
    return ('<div class="item"><div><%s class="time">9:00 %sx</div><p class="task-title">%s</p>'
            '<div class="chips"><span class="chip pending">未</span></div></div>' % (tag, inner, title))


# ------------------------------------------------------------------ T-P（Deck との写しの一致）

COPIED = ["_blank_comments", "_canon_section", "_scan_board", "_element_text", "_key_text", "_item_key", "_recalc_progress",
          "_toggle_class_token", "_normalize_item_block", "board_header_date_text", "parse_board_date",
          "_marker_counts", "_item_start_lines", "board_structure_ok", "_canon_label", "_remove_time_elements",
          "_div_balance", "hand_fingerprint", "parse_due_value", "_item_open_attr", "_item_due_pending", "_mark_due_moved",
          "_insert_status_chip", "_due_moved_shape", "_item_due_shapeable", "_valid_hm", "_later_due_shape",
          "_time_open_unclosed", "_time_screen_closed", "_time_close_at", "_implied_close",
          "_open_stack", "_time_range", "_time_text", "_time_reopened", "_time_inner_open", "_time_keeps_open", "_time_inner_stack", "_tag_walk", "_tag_walk_once", "_time_match_close", "_blank_markup", "_markup_free",
          "_sw_tag_end", "_sw_text_end", "_sw_is_board_js", "_sw_runs", "_sw_src_board_js", "_sw_board_js_in", "_sw_lost", "_swallow_open", "_sw_scan", "swallow_text", "migrate_board_js"]
COPIED_CONSTS = ["MARKER_START", "MARKER_END", "MOVABLE_SECTIONS", "CANON_SECTIONS", "WEEKDAY_JA", "_SECTION_LABEL_RE",
                 "_CLASS_TAG_RE", "_STRIP_TAGS_RE", "_CHIP_TOKEN_RE", "_CHIP_DONE_RE", "_ITEM_CLASS_RE",
                 "_ANY_CLASS_TAG_RE", "_HEADER_RE", "_TITLE_RE", "_UPD_TIME_RE", "_ITEM_OPEN_RE", "_TIME_OPEN_RE",
                 "_FOOTER_LINE_RE", "_DUE_VALUE_RE", "_SPAN_CLASS_RE", "_KEY_STOP_RE", "_ROW_PART_RE", "_TAG_TOKEN_RE", "_VOID_TAGS", "_P_CLOSERS",
                 "_FORMATTING_TAGS", "_KEEP_OPEN_TAGS", "_MATH_POINTS", "_SVG_POINTS", "_KEEP_OPEN_HTML", "_MARKUP_TAG_RE", "_BLANK_CACHE", "_HTML_SPECIAL", "_OWN_END_RULE", "_SCOPE_BOUNDS", "_WALK_CACHE", "_HEADINGS",
                 "_BOARD_JS_TAIL_RE", "_BOARD_CSS_LINK", "_BOARD_JS_HEAD", "_SWALLOW_TAGS", "_FOREIGN_BREAKOUT", "_SW_TAG_RE", "_SW_ATTR_NAME_RE", "_SW_UNQUOTED_RE", "_SW_SPACE", "_SW_SCRIPT_RE", "_SW_ROW_RE", "_SW_START_RE", "_SW_JS_TYPES", "_SW_SCRIPT_OPEN_RE", "_SW_SRC_RE"]
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
                                                                    "chip": "pending", "crit": False, "carried": None, "due": None, "due_moved": None,
                                                                    "due_from": None}])
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
        """崩れた板でも、崩れより後ろの行が only_now から抜けない。"""
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
        """戻す版が読めないときは、いまの板ではなく戻す版のことを言う。"""
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
        self.assertEqual(set(x), {"section", "time", "title", "note", "chip", "crit", "carried", "due", "due_moved", "due_from"})


# ------------------------------------------------------------------ create の退避と、消える行の確かめ

class TestCreateGuard(Sandbox):
    def spec_file(self, spec):
        p = os.path.join(self.dir, "s.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        return p

    def make_afternoon_row(self, title="午後の件"):
        self.ed("add", "--section", "今日中", "--title", title, "--time", "15:00")
        self.write(self.text().replace('<div class="time">15:00</div>', '<div class="time">午後</div>', 1))
        self.assertIn("午後", [i["time"] for i in self.status()["sections"][1]["items"] if i["title"] == title])

    def test_missing_rows_do_not_compare_non_hm_time(self):
        """時刻の欄が H:MM でない行（「午後」）は、spec に time なしで入れれば消える行に出ないが、時刻が消えるので
        --confirmed が無ければ書かずに dropped_times を返す。--confirmed を付ければ書き、書いた後の出力にも dropped_times を出す。"""
        self.create()
        self.make_afternoon_row()
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC)])
        self.assertEqual(rc, 1, out)
        self.assertEqual([r["title"] for r in out["missing"]], ["午後の件"])       # spec に無ければ消える行に出る
        self.assertEqual(out["dropped_times"], [])                                 # spec に無い行は missing の側だけ
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"].append({"section": "今日中", "title": "午後の件"})
        before = self.read()
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual(out["dropped_times"], [{"no": 1, "status_index": 5, "section": "今日中", "time": "午後", "new_time": None,
                                                 "title": "午後の件", "due": None}])
        self.assertIn("dropped_times", out["error"])
        self.assertIn("--confirmed", out["error"])
        self.assertUnchanged(before)
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])
        self.assertEqual([(r["title"], r["time"]) for r in out["dropped_times"]], [("午後の件", "午後")])
        self.assertNotIn("午後</div>", self.text())

    def test_non_hm_time_replaced_by_hm_is_same_row(self):
        """H:MM でない時刻を H:MM で spec に入れたら、同じ行とみなす（消える行に出ない）。ただし時刻が変わるので、
        --confirmed が無ければ書かずに dropped_times（new_time にその時刻）を返す。--confirmed を付ければ書き、書いた後も出す。"""
        self.create()
        self.make_afternoon_row()
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"].append({"section": "今日中", "title": "午後の件", "time": "13:30"})
        before = self.read()
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual(out["dropped_times"], [{"no": 1, "status_index": 5, "section": "今日中", "time": "午後", "new_time": "13:30",
                                                 "title": "午後の件", "due": None}])
        self.assertUnchanged(before)
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("午後", "13:30")])
        self.assertIn('<div class="time">13:30</div>', self.text())

    def test_non_hm_time_does_not_take_other_rows_pair(self):
        """同じタイトルの、時刻の無い行と「午後」の行があるとき、時刻の無い行は spec の時刻の無い行と、「午後」の行は残りの行と組になる。"""
        self.create()
        self.make_afternoon_row("同じ名前")                                       # 「午後」の行が先に並ぶ
        self.ed("add", "--section", "今日中", "--title", "同じ名前")
        self.assertEqual([i["time"] for i in self.status()["sections"][1]["items"] if i["title"] == "同じ名前"], ["午後", None])
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"] += [{"section": "今日中", "title": "同じ名前", "time": "13:30"}, {"section": "今日中", "title": "同じ名前"}]
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])                                       # 時刻の無い行は時刻の無い spec の行と組になる
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("午後", "13:30")])

    def test_non_hm_time_pairs_with_no_time_row_first(self):
        """板に「午後 X」が1行、spec に「X 13:30」と「X（時刻なし）」があれば、時刻の無い行と組になる（new_time は None）。"""
        self.create()
        self.make_afternoon_row("同じ名前")
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"] += [{"section": "今日中", "title": "同じ名前", "time": "13:30"}, {"section": "今日中", "title": "同じ名前"}]
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("午後", None)])

    def test_dropped_times_on_unreadable_date_board(self):
        """ヘッダの日付が読めない板でも、「午後」の行を時刻なしで spec に入れたら書かずに dropped_times を返し、--confirmed で書く。"""
        self.create()
        self.make_afternoon_row()
        self.write(self.text().replace(be.fmt_full_date(date.today()), "そのうち", 1))
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"].append({"section": "今日中", "title": "午後の件"})
        before = self.read()
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual(len(out["dropped_times"]), 1)
        self.assertUnchanged(before)
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2), "--confirmed"])
        self.assertEqual(rc, 0, out)

    def test_missing_and_dropped_together(self):
        """消える行と時刻が消える行が両方あれば、1回の拒否で両方を返す（ユーザーへの確かめを1回で済ませる）。"""
        self.create()
        self.make_afternoon_row()
        self.ed("add", "--section", "今日中", "--title", "他のセッションの行")
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"].append({"section": "今日中", "title": "午後の件"})
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 1, out)
        self.assertEqual([r["title"] for r in out["missing"]], ["他のセッションの行"])
        self.assertEqual([r["title"] for r in out["dropped_times"]], ["午後の件"])
        self.assertIn("dropped_times", out["error"])

    def test_dropped_times_reported_for_rolled_board(self):
        """Deck が引き継いだ板・前の日の板は確かめずに書くが、時刻が消えた行は出力の dropped_times に出す。板が無ければ空。"""
        self.create()
        self.make_afternoon_row()
        self.write(self.text().replace('<div class="board">', '<div class="board" data-tb-rolled="2026-10-28">', 1))
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"].append({"section": "今日中", "title": "午後の件"})
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 0, out)
        self.assertEqual([(r["title"], r["time"]) for r in out["dropped_times"]], [("午後の件", "午後")])
        os.remove(self.board)
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC)])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["dropped_times"], [])

    def test_missing_rows_do_not_compare_unreadable_due(self):
        """「明日以降」の行の data-due が読めない値（「そのうち」）なら、spec に同じ見出し・時刻・タイトルの行（due 無し）があれば消える行に出ない。"""
        self.create()
        self.ed("add", "--section", "明日以降", "--title", "そのうちの件", "--due", date.fromordinal(date.today().toordinal() + 3).isoformat())
        self.write(re.sub(r'data-due="[^"]*"(>\s*<div>\s*<p class="task-title">そのうちの件)', r'data-due="そのうち"\1', self.text(), count=1))
        self.assertIn('data-due="そのうち"', self.text())
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(SPEC)])
        self.assertEqual(rc, 1, out)
        self.assertEqual([r["title"] for r in out["missing"]], ["そのうちの件"])
        spec2 = json.loads(json.dumps(SPEC))
        spec2["items"].append({"section": "明日以降", "title": "そのうちの件"})
        rc, out = run(["create", "--board", self.board, "--spec", self.spec_file(spec2)])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])

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
                                           "title": "他のセッションの行", "chip": "pending", "note": "proj",
                                           "crit": False, "due": None, "due_moved": None, "due_from": None}])
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
        """退避の名前は書く段で排他的に決める。直前に同名のファイルが置かれても上書きしない。"""
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
        """いまの板が UTF-8 で読めないときの create は removed: null・removed_incomplete: true。"""
        self.create()
        self.write(self.read() + b"\xff")
        out = self.create(SPEC, "--confirmed")
        self.assertIsNone(out["removed"])
        self.assertTrue(out["removed_incomplete"])

    def test_create_replace_fails_after_backup(self):
        """退避の後に置き換えが失敗したら、退避・記録・一時ファイルを残さず、板も変えない。"""
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
        """読み直しで割り込みを見つけてやり直したら、1回目の退避を消し、2回目の退避は割り込んだ版を持つ。"""
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
        """UTF-8 として読めない板には、--confirmed が無ければ create も書かない。"""
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
        """一時ファイルへの書き込みが失敗したら、一時ファイルを残さない。"""
        with self.assertRaises(TypeError):
            be._write_tmp(self.dir, "bytes ではない")
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_history_xb_failure_removes_own_file(self):
        """os.link が使えず xb で書く経路で、書く途中に失敗したら、自分が作ったファイルだけを消す。"""
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


# ------------------------------------------------------------------ T-B（閉じタグの無い時刻の欄・v1.10 / Deck v2.14）

# 閉じタグの無い時刻の欄の形（ブラウザは後ろの要素を欄の中に取り込む）。どれも鍵は「0:00|タイトル」（tests/test_board_browser.py の
# TestBrokenTimeKeys が board.js の鍵と同じであることを見る）。v2.13 までの Deck は、最初の </span> までの文字を時刻にしていた
BROKEN_SHAPES = {
    "補足つき": '<div class="item"><span class="time">0:00<div><p class="task-title">補足つき</p><p class="task-note">メモ</p>'
            '<div class="chips"><span class="chip pending">未</span></div></div></div>',
    "span題": '<div class="item"><span class="time">0:00<div><span class="task-title strike">span題</span>'
             '<div class="chips"><span class="chip pending">未</span></div></div></div>',
    "二つ": '<div class="item crit"><span class="time">0:00<div><p class="task-title">二つ</p>'
          '<div class="chips"><span class="chip pending">未</span><span class="chip crit">重要</span></div></div></div>',
    "崩れ": '<div class="item"><span class="time">0:00<div><p class="task-title">崩れ</p>'
          '<div class="chips"><span class="chip pending">未</span></div></div></div>',
    "複数行": '<div class="item"><span class="time">0:00\n  <div>\n    <p class="task-title">複数行</p>\n'
           '    <div class="chips"><span class="chip pending">未</span></div>\n  </div>\n</div>',
}
# 閉じタグは無いが、ブラウザが時刻の欄をタイトルやチップの手前で閉じる形（画面は正しい・⑥には出ない＝_time_screen_closed・v1.12）
SHOWN_CLOSED = {
    "p欄": '<div class="item">\n  <p class="time">9:00\n  <div>\n    <p class="task-title">p欄</p>\n'
          '    <div class="chips"><span class="chip pending">未</span></div>\n  </div>\n</div>',
    "内側で閉じる": '<div class="item"><div><span class="time">9:00</div><p class="task-title">内側で閉じる</p>'
              '<div class="chips"><span class="chip pending">未</span></div></div>',
    "欄の外に文字": '<div class="item"><div><span class="time">9:00</div>am <p class="task-title">欄の外に文字</p>'
              '<div class="chips"><span class="chip pending">未</span></div></div>',
}
# 同じく画面は正しい形のうち、v1.11 の close-time が "after"・"after"・"text" で断った形。値は (行, 行の鍵)
SHOWN_CLOSED_REFUSED_BEFORE = {
    "p欄にam": ('<div class="item"><p class="time">9:00 <b>am</b><div><p class="task-title">p欄にam</p>'
               '<div class="chips"><span class="chip pending">未</span></div></div></div>', "9:00 am|p欄にam"),
    "中の span": ('<div class="item"><div><span class="time">9:00 <span>am</div><p class="task-title">中の span</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div>', "9:00 am|中の span"),
    "空の欄": ('<div class="item"><div><span class="time">  </div><p class="task-title">空の欄</p>'
             '<div class="chips"><span class="chip pending">未</span></div></div>', "|空の欄"),
}


class TestBrokenTimeKey(Sandbox):
    def put_rows(self, rows, nl="\n"):
        """今日中の見出しの直後に rows（HTML の行）を足す（サンドボックスの板だけ。board_edit.py では作れない形）。"""
        lines = self.text().splitlines(keepends=True)
        at = [i for i, ln in enumerate(lines) if 'class="section-label"' in ln and ">今日中<" in ln][0] + 1
        lines[at:at] = [r.replace("\n", nl) + nl for r in rows]
        self.write("".join(lines))

    def test_keys_same_in_deck_and_board_edit(self):
        """どの形でも、Deck と board_edit.py の鍵は「0:00|タイトル」で同じ（CR LF の板でも）。read_board_alarms の鍵も同じ。"""
        for nl in ("\n", "\r\n"):
            for title, row in BROKEN_SHAPES.items():
                block = row.replace("\n", nl) + nl
                with self.subTest(title=title, nl=repr(nl)):
                    self.assertEqual(dw._item_key(block), "0:00|" + title)
                    self.assertEqual(be._item_key(block), "0:00|" + title)
                    self.assertTrue(be._time_unclosed(block))
        self.create()
        self.put_rows(list(BROKEN_SHAPES.values()), nl="\r\n")
        alarms = [a[0] for a in dw.read_board_alarms(self.board) if a[3] in BROKEN_SHAPES]
        self.assertEqual(sorted(alarms), sorted("0:00|" + t for t in BROKEN_SHAPES))

    def test_wellformed_keys_unchanged(self):
        """閉じタグのある行の鍵は v2.13 までと同じ（時刻の欄の中に class を持つ要素が無く、欄の文字の後ろに空白の無い形）。"""
        rows = ['<div class="item"><div class="time">9:00</div><div><p class="task-title">朝会</p></div></div>',
                '<div class="item"><span class="time">9:00</span><div><p class="task-title">D&amp;D の件</p></div></div>',
                '<div class="item"><div class="time"><div>9:00</div></div><div><p class="task-title">入れ子</p></div></div>',
                '<div class="item flat"><div><p class="task-title">時刻なし</p></div></div>',
                '<div class="item"><div class="time">午後</div><div><p class="task-title">読めない</p></div></div>']
        for row in rows:
            old = ((be._element_text(row, "time") or "") + "|" + (be._element_text(row, "task-title") or "")).strip()
            self.assertEqual(be._item_key(row), old)
            self.assertEqual(dw._item_key(row), old)
            self.assertFalse(be._time_unclosed(row))
        # class の無い同じ名前の子が先に閉じる欄も、中に class を持つ要素があれば K15 に当たる（board.js の⑥も数える）。欄の閉じタグは
        # 入れ子を数えて決めるので、鍵の時刻は「9:00」（v2.20 / board_edit.py v1.16。v1.15 までは K15 に当たらず、鍵は「9」）
        row = '<div class="item"><span class="time"><span>9</span>:00 <span class="x">a</span></span><div><p class="task-title">T</p></div></div>'
        self.assertTrue(be._time_unclosed(row))
        self.assertEqual(be._item_key(row), "9:00|T")
        self.assertEqual(dw._item_key(row), "9:00|T")

    def test_time_field_markup_and_self_closing(self):
        """欄の閉じタグを数えるとき、コメントの中と属性の値の中の </span> は数えず、HTML の要素の <span/> は開きタグとして数える
        （ブラウザと同じ。v2.20 / board_edit.py v1.16）。鍵・K15・close-time・set-time と、Deck の写しが同じ結果になる。"""
        def row(inner):
            return '<div class="item"><span class="time">0:00 %s</span><div><p class="task-title">T</p></div></div>' % inner
        cases = [("<!-- </span> -->", "0:00|T", False), ('<span title="</span>">a</span>', "0:00 a|T", False),
                 ("<!-- <span class=\"x\"> -->", "0:00|T", False), ("<span/>x", "0:00 x|T", True),
                 # 閉じタグまでを文字として読む要素の中身と、svg・math の中の CDATA の中の </span> も数えない（文字は欄の文字に入る）
                 ("<script></span></script>", "0:00 </span>|T", False), ("<textarea></span></textarea>", "0:00 </span>|T", False),
                 ("<style></span></style>", "0:00 </span>|T", False), ("<title></span></title>", "0:00 </span>|T", False),
                 ("<svg><![CDATA[</span>]]></svg>", "0:00 </span>|T", False)]
        for inner, key, k15 in cases:
            with self.subTest(inner=inner):
                r = row(inner)
                self.assertEqual(be._item_key(r), key)
                self.assertEqual(dw._item_key(r), key)
                self.assertEqual(be._time_unclosed(r), k15)
                self.assertEqual(be._time_close_at(r), dw._time_close_at(r))
                if not k15:
                    out = "".join(be.block_set_time(r.splitlines(keepends=True), "\n", "11:00"))
                    self.assertEqual(be._item_key(out), "11:00|T")
                    self.assertNotIn("</span></span>", out)
        # <b/> は書式の要素として開き、閉じた後で開き直される（_time_reopened）
        r = '<div class="item"><div><span class="time">0:00 <b/>x</div><p class="task-title">T</p></div></div>'
        self.assertTrue(be._time_reopened(r, be._time_open_unclosed(r)))
        # svg の中の /> は閉じる（<svg><a/></svg> の a は開きタグに数えない）
        r = '<div class="item"><a class="time">0:00 <svg><a/></svg></a><div><p class="task-title">T</p></div></div>'
        self.assertFalse(be._time_unclosed(r))
        self.assertEqual(be._item_key(r), "0:00|T")

    def test_status_warns_and_close_time_repairs(self):
        """status は閉じタグの無い欄を K15 で知らせ、time は欄の文字だけを出す。close-time は閉じタグを補い、鍵も文言も変えない。"""
        self.create()
        self.put_rows(list(BROKEN_SHAPES.values()), nl="\r\n")
        st = self.status()
        k15 = [w for w in st["warnings"] if w["code"] == "K15"]
        self.assertEqual(len(k15), 1, st["warnings"])
        for title in BROKEN_SHAPES:
            self.assertIn("0:00|" + title, k15[0]["message"])
        its = {i["title"]: i for i in self.items()}
        for title in BROKEN_SHAPES:
            self.assertEqual((its[title]["time"], its[title]["key"]), ("0:00", "0:00|" + title))
        # set-time は閉じタグの無い欄を書き換えない（後ろのタイトルとチップまで消えるため。ブラウザが欄の中に入れた行でも、手前で閉じる行でも同じ）
        before = self.read()
        rc, out = self.ed("set-time", "--item", "0:00|崩れ", "--time", "9:00")
        self.assertNotEqual(rc, 0)
        self.assertIn("close-time", out["error"])
        self.assertUnchanged(before)
        for title in BROKEN_SHAPES:
            rc, out = self.ed("close-time", "--item", "0:00|" + title)
            self.assertEqual(rc, 0, out)
            self.assertTrue(out["changed"])
        text = self.text()
        self.assertEqual(be.structure_errors(text), [])
        st = self.status()
        self.assertEqual([w for w in st["warnings"] if w["code"] == "K15"], [])
        its2 = {i["title"]: i for i in self.items()}
        for title in BROKEN_SHAPES:
            a, b = dict(its[title]), dict(its2[title])
            a.pop("index"), b.pop("index")
            self.assertEqual(a, b)                    # 鍵・時刻・補足・チップ・重要は変わらない
        self.assertEqual(text.count('<span class="time">0:00</span>'), len(BROKEN_SHAPES))
        self.assertIn('<span class="time">0:00</span>\r\n  <div>', text)   # 複数行の行は時刻の文字の直後に補う
        # 直した後は、もう直すものが無い
        before = self.read()
        rc, out = self.ed("close-time", "--item", "0:00|崩れ")
        self.assertNotEqual(rc, 0)
        self.assertUnchanged(before)
        self.assertEqual(self.ed("set-time", "--item", "0:00|崩れ", "--time", "9:00")[0], 0)   # 閉じた欄は書き換えられる

    def test_unclosed_second_time_and_single_line(self):
        """時刻の欄が2つある行の2つ目が閉じていなくても K15 に出る（board.js の⑥と同じく項目ごとに1件）。div を挟まない形
        （v1.9 の set-time がタイトルを消した形）も set-time は断り、close-time は直す。"""
        self.create()
        self.put_rows(['<div class="item"><span class="time">9:00</span><span class="time">9:30<div><p class="task-title">二つの時刻</p>'
                       '<div class="chips"><span class="chip pending">未</span></div></div></div>',
                       '<div class="item"><span class="time">0:00 <span class="task-title">単一</span></div>'])
        k15 = [w for w in self.status()["warnings"] if w["code"] == "K15"]
        self.assertEqual(len(k15), 1)
        self.assertIn("9:00|二つの時刻", k15[0]["message"])
        self.assertIn("0:00|単一", k15[0]["message"])
        before = self.read()
        rc, out = self.ed("set-time", "--item", "単一", "--time", "9:00")
        self.assertNotEqual(rc, 0)
        self.assertUnchanged(before)
        self.assertEqual(self.ed("close-time", "--item", "単一")[0], 0)
        self.assertIn('<span class="time">0:00</span> <span class="task-title">単一</span>', self.text())
        self.assertEqual(self.ed("close-time", "--item", "二つの時刻")[0], 0)
        self.assertIn('<span class="time">9:30</span><div><p class="task-title">二つの時刻</p>', self.text())
        self.assertEqual([w for w in self.status()["warnings"] if w["code"] == "K15"], [])

    def test_screen_closed_shapes(self):
        """ブラウザが時刻の欄をタイトルやチップの手前で閉じる形（閉じタグは無いが画面は正しい・⑥には出ない）は、K15 を別の文で知らせ、
        set-time は断り、close-time はブラウザが閉じる位置に補う（v1.12。欄の外に文字がある形も直す。v1.11 は断って restore を案内した）。
        補った後は閉じていて、鍵・時刻・補足・チップは変わらず、set-time で書き換えられる。Deck の _time_close_at も同じ位置を返す。"""
        for title, row in SHOWN_CLOSED.items():
            with self.subTest(title=title):
                hit = be._time_open_unclosed(row)
                self.assertIsNotNone(hit)
                at = be._time_screen_closed(row, hit)
                self.assertIsNotNone(at)
                self.assertEqual(be._time_close_at(row), dw._time_close_at(row))
                pos = be._time_close_at(row)[0]
                self.assertEqual(row[pos:at].strip(), "")      # ブラウザが閉じる位置の手前の空白を除いた所
                self.assertLessEqual(pos, at)
                self.assertEqual(be._item_key(row), "9:00|" + title)
        for title, row in BROKEN_SHAPES.items():        # ブラウザが後ろの要素を欄に取り込む形は、これまでどおり時刻の文字の直後に補う
            with self.subTest(title=title):
                self.assertIsNone(be._time_screen_closed(row, be._time_open_unclosed(row)))
        self.create()
        self.put_rows(list(SHOWN_CLOSED.values()) + [BROKEN_SHAPES["崩れ"]])
        st = self.status()
        k15 = [w for w in st["warnings"] if w["code"] == "K15"]
        self.assertEqual(len(k15), 2, st["warnings"])
        self.assertIn("0:00|崩れ", k15[0]["message"])
        self.assertIn("ブラウザでは時刻の欄の中に", k15[0]["message"])
        for title in SHOWN_CLOSED:
            self.assertNotIn("9:00|" + title, k15[0]["message"])
            self.assertIn("9:00|" + title, k15[1]["message"])
        self.assertNotIn("0:00|崩れ", k15[1]["message"])
        self.assertIn("画面では正しく表示されます", k15[1]["message"])
        self.assertIn("close-time", k15[1]["message"])
        its = {i["title"]: i for i in self.items()}
        before = self.read()
        rc, out = self.ed("set-time", "--item", "9:00|内側で閉じる", "--time", "10:00")
        self.assertNotEqual(rc, 0)
        self.assertIn("close-time", out["error"])
        self.assertUnchanged(before)
        for title in SHOWN_CLOSED:
            rc, out = self.ed("close-time", "--item", "9:00|" + title)
            self.assertEqual(rc, 0, out)
            self.assertTrue(out["changed"])
        text = self.text()
        self.assertEqual(be.structure_errors(text), [])
        self.assertIn('<p class="time">9:00</p>\n  <div>', text)                 # p を閉じる div の手前（ブラウザが閉じる位置。その手前の空白を除く）
        self.assertIn('<span class="time">9:00</span></div><p class="task-title">内側で閉じる</p>', text)
        self.assertIn('<span class="time">9:00</span></div>am <p class="task-title">欄の外に文字</p>', text)
        k15 = [w for w in self.status()["warnings"] if w["code"] == "K15"]
        self.assertEqual(len(k15), 1)                   # 残るのは取り込む形の行だけ
        self.assertNotIn("9:00|", k15[0]["message"])
        its2 = {i["title"]: i for i in self.items()}
        for title in SHOWN_CLOSED:
            a, b = dict(its[title]), dict(its2[title])
            a.pop("index"), b.pop("index")
            self.assertEqual(a, b)
        self.assertEqual(self.ed("set-time", "--item", "9:00|内側で閉じる", "--time", "10:00")[0], 0)
        self.assertIn('<span class="time">10:00</span></div><p class="task-title">内側で閉じる</p>', self.text())

    def test_screen_closed_shapes_refused_before(self):
        """画面は正しい形のうち v1.11 の close-time が断った形（時刻の文字の後ろにタグで囲んだ文字・欄の中で閉じていない span・
        欄に時刻の文字が無い）も、v1.12 はブラウザが閉じる位置に補う（中で閉じていない span の閉じタグも足す）。鍵は変わらず、補った後は閉じている。"""
        for title, (row, key) in SHOWN_CLOSED_REFUSED_BEFORE.items():
            with self.subTest(title=title):
                hit = be._time_open_unclosed(row)
                self.assertIsNotNone(hit)
                self.assertIsNotNone(be._time_screen_closed(row, hit))
                self.assertEqual(be._time_close_at(row), dw._time_close_at(row))
                self.assertEqual(be._item_key(row), key)
        self.create()
        self.put_rows([r for r, _k in SHOWN_CLOSED_REFUSED_BEFORE.values()])
        k15 = [w for w in self.status()["warnings"] if w["code"] == "K15"]
        self.assertEqual(len(k15), 1)
        self.assertIn("画面では正しく表示されます", k15[0]["message"])
        its = {i["title"]: i for i in self.items()}
        for title, (_row, key) in SHOWN_CLOSED_REFUSED_BEFORE.items():
            rc, out = self.ed("close-time", "--item", key)
            self.assertEqual(rc, 0, out)
        text = self.text()
        self.assertEqual(be.structure_errors(text), [])
        self.assertIn('<p class="time">9:00 <b>am</b></p><div><p class="task-title">p欄にam</p>', text)
        self.assertIn('<span class="time">9:00 <span>am</span></span></div><p class="task-title">中の span</p>', text)
        self.assertIn('<span class="time"></span>  </div><p class="task-title">空の欄</p>', text)
        self.assertEqual([w for w in self.status()["warnings"] if w["code"] == "K15"], [])
        its2 = {i["title"]: i for i in self.items()}
        for title in SHOWN_CLOSED_REFUSED_BEFORE:
            a, b = dict(its[title]), dict(its2[title])
            a.pop("index"), b.pop("index")
            self.assertEqual(a, b)

    def test_formatting_time_shapes(self):
        """書式の要素（b など）の扱い。欄の中で閉じていない書式の要素がある行は、ブラウザが欄を閉じた後で
        開き直す（画面は正しくない）ので、_time_screen_closed は None・_time_reopened は真で、K15 は3つ目の文、close-time は "format" で断る。
        欄そのものが書式の要素の行（<b class="time">）は class="time" ごと開き直すので None で、従来の判定に戻り、close-time は時刻の文字の直後に補う。"""
        inner = ('<div class="item"><div><span class="time">9:00 <b>am</div><p class="task-title">中の書式</p>'
                 '<div class="chips"><span class="chip pending">未</span></div></div>')
        own = ('<div class="item"><div><b class="time">9:00</div><p class="task-title">欄が書式</p>'
               '<div class="chips"><span class="chip pending">未</span></div></div>')
        for row in (inner, own):
            self.assertIsNone(be._time_screen_closed(row, be._time_open_unclosed(row)))
            self.assertEqual(be._time_close_at(row), dw._time_close_at(row))
        self.assertTrue(be._time_reopened(inner, be._time_open_unclosed(inner)))
        self.assertFalse(be._time_reopened(own, be._time_open_unclosed(own)))
        self.assertEqual(be._time_close_at(inner), "format")
        self.assertEqual(dw._time_close_at(inner), "format")        # Deck の日付の切り替えは確かめられないので補わない（外す）
        self.assertEqual(be._time_close_at(inner, reopen=True), dw._time_close_at(inner, reopen=True))
        self.assertEqual(be._time_close_at(inner, reopen=True)[1], "</b></span>")
        self.assertIsInstance(be._time_close_at(own), tuple)
        self.create()
        self.put_rows([inner, own, SHOWN_CLOSED["内側で閉じる"], BROKEN_SHAPES["崩れ"]])
        k15 = [w["message"] for w in self.status()["warnings"] if w["code"] == "K15"]
        self.assertEqual(len(k15), 3, k15)
        by = {k: [m for m in k15 if k in m] for k in ("9:00 am|中の書式", "9:00|欄が書式", "9:00|内側で閉じる", "0:00|崩れ")}
        self.assertTrue(all(len(v) == 1 for v in by.values()), by)
        self.assertIn("画面では正しく表示されます", by["9:00|内側で閉じる"][0])      # close-time で直せる行だけがこの文
        self.assertNotIn("画面では正しく表示されます", by["9:00 am|中の書式"][0])
        self.assertIn("close-time --item <項目> --confirmed", by["9:00 am|中の書式"][0])   # 書式が外れるので確かめてから補う（v1.12）
        self.assertIs(by["9:00|欄が書式"][0], by["0:00|崩れ"][0])             # 欄が書式の要素の行は、取り込む形の行と同じ文
        before = self.read()
        rc, out = self.ed("close-time", "--item", "9:00 am|中の書式")
        self.assertNotEqual(rc, 0)
        self.assertIn("--confirmed", out["error"])
        self.assertUnchanged(before)
        keys = [i["key"] for i in self.items()]
        rc, out = self.ed("close-time", "--item", "9:00 am|中の書式", "--confirmed")
        self.assertEqual(rc, 0, out)
        self.assertIn('<span class="time">9:00 <b>am</b></span></div><p class="task-title">中の書式</p>', self.text())
        self.assertEqual([i["key"] for i in self.items()], keys)
        self.assertFalse([w for w in self.status()["warnings"] if w["code"] == "K15" and "9:00 am|中の書式" in w["message"]])
        rc, out = self.ed("close-time", "--item", "9:00|欄が書式")
        self.assertEqual(rc, 0, out)
        self.assertIn('<b class="time">9:00</b></div><p class="task-title">欄が書式</p>', self.text())
        self.assertEqual([i["key"] for i in self.items()], keys)

    def test_keep_open_tags_not_screen_closed(self):
        """欄の中で table・object・script など（_KEEP_OPEN_TAGS）が閉じていない行は、ブラウザが外側の閉じタグで欄を閉じず、タイトルやチップが
        欄に入るか文字として読まれるので、「画面では正しく」の側に入れない（_time_screen_closed は None・_time_reopened は偽＝K15 は取り込む形の行と
        同じ文）。3種類（スコープの境界・MathML/SVG の中の HTML・閉じタグまでを文字として読む要素）から選ぶ。"""
        openers = {"table": "<table>", "select": "<select>", "textarea": "<textarea>", "object": "<object>", "template": "<template>",
                   "mi": "<math><mi>", "foreignobject": "<svg><foreignObject>", "script": "<script>", "style": "<style>", "title": "<title>"}
        rows = {t: ('<div class="item"><div><span class="time">9:00 %sx</div><p class="task-title">中の %s</p>'
                    '<div class="chips"><span class="chip pending">未</span></div></div>' % (o, t)) for t, o in openers.items()}
        for t, row in rows.items():
            with self.subTest(tag=t):
                hit = be._time_open_unclosed(row)
                if t in be._SWALLOW_TAGS:
                    # 閉じていない textarea・script などは、後ろの行を文字として読む（タイトルは要素にならない＝K16）。欄の中に class を持つ
                    # 要素は無いので K15 には当たらない（v2.20 / board_edit.py v1.16。それまでは中身の文字のタグを数えて当てた。
                    # どちらの版でも status は K16 の行に K15 を出さない）
                    self.assertIsNone(hit)
                    self.assertEqual(dw._time_open_unclosed(row), None)
                    continue
                self.assertIsNotNone(hit)
                self.assertIsNone(be._time_screen_closed(row, hit))
                self.assertFalse(be._time_reopened(row, hit))
                self.assertEqual(be._time_close_at(row), dw._time_close_at(row))
        self.create()
        self.put_rows(list(rows.values()) + [BROKEN_SHAPES["崩れ"]])
        k15 = [w["message"] for w in self.status()["warnings"] if w["code"] == "K15"]
        self.assertEqual(len(k15), 1, k15)
        self.assertIn("ブラウザでは時刻の欄の中に", k15[0])

    def test_math_svg_points_only_inside(self):
        """MathML の mi など・SVG の foreignObject・desc は、math・svg の中にあるときだけ欄を閉じなくする（_time_keeps_open）。
        math・svg の外にそのまま書いたものはふつうの要素で、ブラウザは外側の閉じタグで欄を閉じる＝「画面では正しく」の側。title は名前だけで見る。"""
        def row(inner):
            return ('<div class="item"><div><span class="time">9:00 %sx</div><p class="task-title">T</p>'
                    '<div class="chips"><span class="chip pending">未</span></div></div>' % inner)
        for inner in ("<mi>", "<mo>", "<mtext>", "<annotation-xml>", "<foreignObject>", "<desc>", "<svg></svg><desc>"):
            with self.subTest(inner=inner):
                r = row(inner)
                self.assertIsNotNone(be._time_screen_closed(r, be._time_open_unclosed(r)))
                self.assertIsInstance(be._time_close_at(r), tuple)
                self.assertEqual(be._time_close_at(r), dw._time_close_at(r))
        self.assertIsNone(be._time_open_unclosed(row("<title>")))      # 閉じていない title は後ろを文字として読む（K16。上の試験）
        for inner in ("<math><mi>", "<math><mrow><mo>", "<math><annotation-xml>", "<svg><foreignObject>", "<svg><g><desc>", "<svg><title>"):
            with self.subTest(inner=inner):
                r = row(inner)
                self.assertIsNone(be._time_screen_closed(r, be._time_open_unclosed(r)))
                self.assertFalse(be._time_reopened(r, be._time_open_unclosed(r)))
        self.assertTrue(be._time_keeps_open(be._time_inner_stack("<math><mi>", 0, 10)))
        self.assertFalse(be._time_keeps_open(be._time_inner_stack("<mi>", 0, 4)))
        self.assertFalse(be._time_keeps_open(be._time_inner_stack("<mi><math>", 0, 10)))      # math が mi より内側なら数えない

    def test_time_field_foreign(self):
        """時刻の欄の中の svg・math を、ブラウザと同じ決まりで読む（_tag_walk・v2.19 / board_edit.py v1.15。TIME_FOREIGN_CASES）。
        抜ける HTML のタグの後ろの mi・desc と、svg の中の textarea・style は数えない（v1.14 までは数えた）。境界の中の HTML から書いた </svg> は
        読み飛ばす（v1.14 までは閉じた）。"close" の形は close-time が補え、Deck と同じ結果を返す。"""
        for inner, want, *tag in TIME_FOREIGN_CASES:
            with self.subTest(inner=inner):
                r = time_foreign_row(inner, "T", *tag)
                hit = be._time_open_unclosed(r)
                got = ("close" if be._time_screen_closed(r, hit) is not None else
                       "reopen" if be._time_reopened(r, hit) else "keep")
                self.assertEqual(got, want)
                self.assertEqual(be._time_close_at(r, reopen=True), dw._time_close_at(r, reopen=True))
                at = be._time_close_at(r)
                if want == "close":
                    self.assertIsInstance(at, tuple)
                    fixed = r[:at[0]] + at[1] + r[at[0]:]
                    self.assertIsNone(be._time_open_unclosed(fixed))
                    self.assertEqual(be._item_key(fixed), be._item_key(r))
                elif want == "reopen":
                    self.assertEqual(at, "format")
                else:
                    self.assertNotIsInstance(at, tuple)
        # 境界の中では、外側の閉じタグで欄を閉じない（_implied_close）
        r = time_foreign_row("<svg><foreignObject><span>x</svg>")
        m = be._TIME_OPEN_RE.search(r)
        self.assertIsNone(be._implied_close(r[:r.index("<p class")], m.end(), ["div"]))
        self.assertEqual(be._implied_close(r, m.end(), ["div"]), dw._implied_close(r, m.end(), ["div"]))

    def test_time_field_cdata_in_html_and_blocked_close(self):
        """svg の HTML として読む所の中の HTML の要素の直下の <![CDATA[ は偽のコメント（中身は鍵に入らない）。HTML として読む所の直下なら CDATA
        （中身は鍵に入る）。欄の閉じタグが HTML として読む所の中から書かれたもの・間に special の要素（p）があるものは欄を閉じず、K15 に当たる
        （ブラウザと同じ＝tests/test_board_browser.py の test_nested_same_name_time_fields。v2.21 / board_edit.py v1.17）。"""
        def row(inner):
            return ('<div class="item"><span class="time">0:00 %s<div><p class="task-title">T</p>'
                    '<div class="chips"><span class="chip pending">未</span></div></div></div>' % inner)
        cases = [('<svg><foreignObject><span><![CDATA[x]]>y</span></foreignObject></svg></span>', "0:00 y|T", False),
                 ('<svg><foreignObject><![CDATA[x]]></foreignObject></svg></span>', "0:00 x|T", False),
                 ('<svg><foreignObject></span></foreignObject></svg>', "0:00|T", True),
                 ('<p>x</span>', "0:00 x|T", True),
                 ('<div>x</span>', "0:00 x|T", True),
                 ('<span>x</span></span>', "0:00 x|T", False),
                 ('<svg><style></span></style></svg>x</span>', "0:00|T", False)]
        for inner, key, k15 in cases:
            with self.subTest(inner=inner):
                r = row(inner)
                self.assertEqual(be._item_key(r), key)
                self.assertEqual(dw._item_key(r), key)
                self.assertEqual(be._time_unclosed(r), k15)
                self.assertEqual(be._time_close_at(r), dw._time_close_at(r))

    def test_time_field_markup_not_slow(self):
        """コメント・閉じタグまでを文字として読む要素・CDATA が多い行でも、約 400KB で 1 秒未満（_blank_markup は --> と --!> を一度探した
        位置を持ち、同じ行は一度だけ作って使い回す。持つ前は、--!> の無い 480KB の形で 18 秒かかった）。"""
        import time
        forms = {"閉じたコメント": "<!-- </span> -->" * 30000, "閉じないコメント": "<!--" + "</span>" * 60000,
                 "script": "<script></span></script>" * 20000, "CDATA": "<svg>" + "<![CDATA[</span>]]>" * 20000}
        for name, inner in forms.items():
            r = time_foreign_row(inner)
            for mod in (be, dw):
                with self.subTest(form=name, mod=mod.__name__):
                    t0 = time.process_time()
                    mod._time_open_unclosed(r)
                    mod._time_close_at(r)
                    mod._time_close_at(r, reopen=True)
                    mod._item_key(r)
                    self.assertLess(time.process_time() - t0, 1)

    def test_time_field_foreign_not_slow(self):
        """時刻の欄の中が深く入れ子になった行でも、約 100KB で 1 秒未満（_tag_walk は区間ごとの名前の数で、閉じタグの名前が区間に無ければ
        並びを辿らない。区間ごとの数を持つ前は、境界の中の HTML の要素が深く入れ子になった 108KB の形で _time_close_at が 4 秒を超えた）。"""
        import time
        n = 8000
        forms = {"svg の中の深い g": "<svg>" + "<g>" * n,
                 "境界の中の HTML の入れ子": "<svg>" + "<foreignObject><span>" * (n // 2) + "</svg>" * (n // 2),
                 "書式の要素の入れ子": "<b>" * n, "span の開きと閉じ": "<span>" * (n // 2) + "</span>" * (n // 2),
                 "svg と desc の交互": "<svg><desc>" * (n // 2), "境界の中の外側の閉じタグ": "<svg><foreignObject>" + "</div></g></x>" * (n // 3)}
        for name, inner in forms.items():
            r = time_foreign_row(inner)
            for mod in (be, dw):
                with self.subTest(form=name, mod=mod.__name__):
                    t0 = time.process_time()   # 同時に動くブラウザの試験に左右されないよう、この処理の CPU 時間で測る
                    mod._time_close_at(r)
                    mod._time_close_at(r, reopen=True)
                    mod._item_key(r)
                    self.assertLess(time.process_time() - t0, 1)

    def test_inner_p_closed_by_p(self):
        """欄の中の p は、後ろの p を閉じる開きタグでブラウザが閉じるので、閉じタグを数えない。
        <span class="time">9:00 <p>a<p>b</div> には </p></span> を足す（</p></p></span> にすると空の p が増える）。"""
        row = ('<div class="item"><div><span class="time">9:00 <p>a<p>b</div><p class="task-title">中の p</p>'
               '<div class="chips"><span class="chip pending">未</span></div></div>')
        self.assertIsNotNone(be._time_screen_closed(row, be._time_open_unclosed(row)))
        at = be._time_close_at(row)
        self.assertEqual(at[1], "</p></span>")
        self.assertEqual(at, dw._time_close_at(row))
        self.assertEqual(be._time_inner_open(row, row.index("9:00"), at[0]), ["p"])

    def test_rollover_screen_closed_time(self):
        """今日の予定の未完了の行で、ブラウザが時刻の欄をタイトルの手前で閉じる形（閉じタグは無い）は、Deck の日付の切り替えが
        ブラウザの閉じる位置に閉じタグを補ってから引き継ぐ（v2.16）。タイトル・補足は残り、data-orig-time は欄の時刻。"""
        from datetime import timedelta
        self.create()
        text = self.text()
        self.assertEqual(text.count('<div class="time">9:00</div>'), 1)
        for shape in ('<div><span class="time">9:00</div>', '<p class="time">9:00'):
            with self.subTest(shape=shape):
                t = text.replace('<div class="time">9:00</div>', shape, 1)
                self.assertEqual(be.structure_errors(t), [])
                blk0 = [b for b in (("".join(t.splitlines(keepends=True)[s:e + 1]))
                                    for (s, e, n) in dw._scan_board(t.splitlines(keepends=True))[1]) if "朝会" in b][0]
                hit = dw._time_open_unclosed(blk0)
                self.assertIsNotNone(hit)
                self.assertIsNotNone(dw._time_screen_closed(blk0, hit))
                rolled, _info = dw.roll_board_text(t, date.today() + timedelta(days=1), "00:00")
                self.assertEqual(be.structure_errors(rolled), [])
                lines = rolled.splitlines(keepends=True)
                blk = [("".join(lines[s:e + 1]), n) for (s, e, n) in dw._scan_board(lines)[1]
                       if dw._element_text("".join(lines[s:e + 1]), "task-title") == "朝会"]
                self.assertEqual(len(blk), 1)
                self.assertEqual(blk[0][1], "今日中")
                self.assertNotIn('class="time"', blk[0][0])
                self.assertIn('data-orig-time="9:00"', blk[0][0])
                self.assertIn("毎朝", blk[0][0])

    def test_rollover_closes_unclosed_time(self):
        """今日の予定の未完了の行の時刻の欄が閉じていなくても、補える形なら Deck の日付の切り替えは閉じタグを補ってから引き継ぐ
        （v2.14。v2.13 までは RolloverError で止まった）。補えない形で、外すと行の部品が一緒に消える欄・終わりの決まらない欄は止める。"""
        from datetime import timedelta
        self.create()
        text = self.text()
        self.assertEqual(text.count('<div class="time">9:00</div>'), 1)
        ok = text.replace('<div class="time">9:00</div>', '<div class="time">9:00', 1).replace(
            '<div class="time">9:00', '<span class="time">9:00', 1)
        self.assertEqual(be.structure_errors(ok), [])
        rolled, info = dw.roll_board_text(ok, date.today() + timedelta(days=1), "00:00")
        self.assertEqual(be.structure_errors(rolled), [])
        lines = rolled.splitlines(keepends=True)
        blk = [("".join(lines[s:e + 1]), n) for (s, e, n) in dw._scan_board(lines)[1]
               if dw._element_text("".join(lines[s:e + 1]), "task-title") == "朝会"]
        self.assertEqual(len(blk), 1)
        self.assertEqual(blk[0][1], "今日中")
        self.assertNotIn('class="time"', blk[0][0])
        self.assertIn('data-orig-time="9:00"', blk[0][0])
        self.assertIn("毎朝", blk[0][0])                       # 補足も残る
        bad = text.replace('<div class="time">9:00</div>', '<span class="time">9:00 <b>am</b>', 1)
        with self.assertRaises(dw.RolloverError):
            dw.roll_board_text(bad, date.today() + timedelta(days=1), "00:00")
        # 閉じタグが項目の終わりに置かれた形（外すとタイトル・補足・チップが一緒に消える）は外さずに止める（v2.13 と v2.14 の最初の版は消した）
        wrap = self.wrap_at_item_end(text, "朝会")
        self.assertEqual(be.structure_errors(wrap), [])
        with self.assertRaises(dw.RolloverError):
            dw.roll_board_text(wrap, date.today() + timedelta(days=1), "00:00")
        # 閉じタグのある欄の中に class を持つ要素があるだけの形は、これまでどおり引き継ぐ（欄の文字は data-orig-time に残る）
        child = text.replace('<div class="time">9:00</div>', '<span class="time">9:00<span class="x">a</span></span>', 1)
        rolled, _info = dw.roll_board_text(child, date.today() + timedelta(days=1), "00:00")
        lines = rolled.splitlines(keepends=True)
        blk = ["".join(lines[s:e + 1]) for (s, e, n) in dw._scan_board(lines)[1]
               if dw._element_text("".join(lines[s:e + 1]), "task-title") == "朝会"]
        self.assertEqual(len(blk), 1)
        self.assertIn("毎朝", blk[0])
        self.assertIn('data-orig-time="9:00"', blk[0])      # 欄の時刻は鍵と同じ読み方（_time_text・v2.15。v2.14 までは「9:00a」）

    def test_rollover_part_child_and_stuck_later_row(self):
        """閉じタグのある欄でも、中に部品の class の要素（チップ）がある今日の予定の行は外さずに止める。実施日の来た「明日以降」の行で
        欄を外せない形は、切り替えを止めずにその場に残し、board_edit.py の K13 がその行を名指す（「次の切り替えで移ります」に当たらない）。"""
        from datetime import timedelta
        self.create()
        text = self.text()
        chip = text.replace('<div class="time">9:00</div>', '<span class="time">9:00<span class="chip">x</span></span>', 1)
        with self.assertRaises(dw.RolloverError):
            dw.roll_board_text(chip, date.today() + timedelta(days=1), "00:00")
        # 「明日以降」の行（実施日が今日）を、時刻の欄が項目の終わりで閉じる形にする
        rc, _out = self.ed("add", "--section", "明日以降", "--title", "移せない", "--due", (date.today() + timedelta(days=1)).isoformat())
        self.assertEqual(rc, 0)
        self.put_legacy_due("移せない", date.today().isoformat())
        lines = self.text().splitlines(keepends=True)
        for (s, e, _n) in dw._scan_board(lines)[1]:
            b = "".join(lines[s:e + 1])
            if dw._element_text(b, "task-title") == "移せない":
                b2 = b.replace('<p class="task-title">', '<span class="time">9:00<p class="task-title">', 1)
                k = b2.rstrip().rfind("</div>")
                self.write(self.text().replace(b, b2[:k] + "</span>" + b2[k:], 1))
                break
        st = self.status()
        k13 = [w for w in st["warnings"] if w["code"] == "K13"]
        self.assertEqual(len(k13), 1)
        self.assertIn("9:00|移せない", k13[0]["message"])
        self.assertIn("その場に残ります", k13[0]["message"])
        rolled, info = dw.roll_board_text(self.text(), date.today() + timedelta(days=1), "00:00")
        self.assertEqual(info["due_moved"], 0)
        lines = rolled.splitlines(keepends=True)
        left = [(n, "".join(lines[s:e + 1])) for (s, e, n) in dw._scan_board(lines)[1] if "移せない" in "".join(lines[s:e + 1])]
        self.assertEqual([n for n, _b in left], ["明日以降"])          # 文言を残したまま、その場に残る

    def test_time_text_reads_the_browser_range(self):
        """欄の時刻を読む所はすべて、鍵と同じ読み方（_time_text・v2.15）で、ブラウザが欄とみなす範囲だけを読む（Deck と board_edit.py で同じ）。
        ①閉じタグが無く、閉じる所までに class の要素が無い欄（v2.14 までの _element_text は最初の </span> までの「0:00未」を読み、
        実施日の時刻を使った＝画面の data-orig「0:00」と分かれた）②外側でも開いていない閉じタグ（</b>）はブラウザと同じく読み飛ばす
        ③p の欄は後ろの block 要素の手前で閉じる。"""
        from datetime import timedelta
        today = date.today()
        d = today.isoformat()
        one = ('<div class="item" data-due="%s 10:00"><div><p class="task-title">X</p><span class="time">0:00</div>'
               '<div class="chips"><span class="chip pending">未</span></div></div>\n' % d)
        stray = '<div class="item"><div><p class="task-title">Y</p></div><span class="time">9:00</b><span class="x">a</span></div>\n'
        para = '<div class="item"><p class="time">9:00<div><p class="task-title">Z</p></div></div>\n'
        for mod in (dw, be):
            with self.subTest(mod=mod.__name__):
                self.assertEqual((mod._element_text(one, "time"), mod._time_text(one)), ("0:00未", "0:00"))
                shaped = mod._due_moved_shape(one, mod.parse_due_value(d + " 10:00"), today, "\n", True)
                self.assertIn('<div class="time">0:00</div>', shaped)            # 画面（data-orig「0:00」）と同じ時刻
                self.assertIn('data-due="%s 0:00"' % d, shaped)
                self.assertIn('<span class="chip pending">未</span>', shaped)
                self.assertEqual(mod._item_key(stray), "9:00|Y")
                gone, n = mod._remove_time_elements(stray)
                self.assertEqual((n, "class=\"x\"" in gone), (1, False))         # x はブラウザでも欄の中（</b> を読み飛ばす）
                gone, n = mod._remove_time_elements(para)
                self.assertEqual(n, 1)
                self.assertIn('<p class="task-title">Z</p>', gone)                 # p の欄は <div> の手前で閉じる＝タイトルは欄の外
                self.assertEqual(mod._time_text(para), "9:00")
        # K14 も同じ読み方（時刻の欄「0:00」と実施日の時刻「10:00」が違う＝食い違い）
        self.assertEqual(be._later_time_conflict(one, "10:00"), "0:00")

    def wrap_at_item_end(self, text, title):
        """タイトル title の行の時刻の欄を、閉じタグを項目の最後の </div> の手前に置いた形にする（サンドボックスの板だけ）。"""
        text = text.replace('<div class="time">9:00</div>', '<span class="time">9:00', 1)
        lines = text.splitlines(keepends=True)
        for (s, e, _n) in dw._scan_board(lines)[1]:
            b = "".join(lines[s:e + 1])
            if dw._element_text(b, "task-title") == title:
                k = b.rstrip().rfind("</div>")
                return text.replace(b, b[:k] + "</span>" + b[k:], 1)
        self.fail(title)

    def test_time_removal_never_drops_task_text(self):
        """時刻の欄を外す経路（Deck の D&D の反映・board_edit.py の move・set-time --time none）は、外すとタイトル・補足・チップが
        一緒に消える欄を外さない（Deck は 400、board_edit.py は書かずに断る。v1.9・v2.13 は消した）。"""
        from datetime import timedelta
        self.create()
        wrap = self.wrap_at_item_end(self.text(), "朝会")
        self.write(wrap)
        k = [i["key"] for i in self.items() if i["title"] == "朝会"][0]
        tom = (date.today() + timedelta(days=1)).isoformat()
        new, code, _msg = dw.apply_board_move(wrap, k, "明日以降", today=date.today(), due=tom + " 10:00", set_due=True)
        self.assertEqual((new, code), (None, 400))
        before = self.read()
        for args in (("move", "--item", "朝会", "--section", "明日以降", "--due", tom + " 10:00"),
                     ("set-time", "--item", "朝会", "--time", "none")):
            rc, out = self.ed(*args)
            self.assertNotEqual(rc, 0, args)
            self.assertUnchanged(before)
        # class の書き方（空白・大文字・' の引用符・引用符なし）を問わず、欄の中の部品を見る（Deck と board_edit.py で同じ）
        for cls in ('class = "task-title"', 'CLASS="task-title"', "class='task-title'", "class=task-title"):
            row = '<div class="item"><span class="time">9:00 <p %s>A</p></span></div>\n' % cls
            for mod in (dw, be):
                with self.subTest(cls=cls, mod=mod.__name__):
                    self.assertEqual(mod._remove_time_elements(row), (row, 0))
        ok = ('<div class="item"><span class="time">9:00 <span class="chip-x">x</span><b data-class="item">y</b></span>'
              '<p class="task-title">A</p></div>\n')
        for mod in (dw, be):
            self.assertEqual(mod._remove_time_elements(ok)[1], 1)       # 欄の中の chip-x・data-class は部品ではない
        # class の値も大文字小文字を区別しない（ボードは互換モードで開かれ、ブラウザの class セレクタが区別しないため。class="Chip" も部品＝board.js の tbTimeHasPart と同じ）
        upper = '<div class="item"><span class="time">9:00 <span class="Chip">x</span></span><p class="task-title">A</p></div>\n'
        for mod in (dw, be):
            self.assertEqual(mod._remove_time_elements(upper), (upper, 0))

    def test_close_time_refuses_shapes_it_cannot_fix(self):
        """欄が div の行（後ろの項目も中に入る）・閉じタグの数が1つ足して合わない行は、書かずに断る。"""
        self.create()
        self.put_rows(['<div class="item"><span class="time">0:00<div><p class="task-title">入れ違い</p>'
                       '<div class="chips"><span class="chip pending">未</span></div></div></span></div>'])
        before = self.read()
        rc, out = self.ed("close-time", "--item", "入れ違い")
        self.assertNotEqual(rc, 0)
        self.assertIn("restore", out["error"])
        self.assertUnchanged(before)
        # 時刻の文字の後ろにタグで囲んだ文字がある形（補うと「am」が欄の外へ出て鍵が変わる）
        self.put_rows(['<div class="item"><span class="time">9:00 <b>am</b><div><p class="task-title">午前</p>'
                       '<div class="chips"><span class="chip pending">未</span></div></div></div>'])
        self.assertIn("9:00 am|午前", [i["key"] for i in self.items()])
        before = self.read()
        rc, out = self.ed("close-time", "--item", "午前")
        self.assertNotEqual(rc, 0)
        self.assertIn("restore", out["error"])
        self.assertUnchanged(before)
        text = self.text().replace('<div class="time">9:00</div>', '<div class="time">9:00', 1)
        self.write(text)
        before = self.read()
        rc, out = self.ed("close-time", "--item", "朝会")
        self.assertNotEqual(rc, 0)
        self.assertUnchanged(before)


if __name__ == "__main__":
    unittest.main()
