# -*- coding: utf-8 -*-
"""board.js の読み込みを head に defer で置く形（2026-11-10 ユーザー決定）と、末尾の形の板の移行（migrate_board_js・Deck v2.18 /
board_edit.py v1.14）、崩れた板の D&D を断る Deck の /board/move（409・Deck v2.18）の試験。ブラウザでの確かめは
tests/test_board_browser.py の TestSwallowInBrowser（⑦・D&D の停止）と TestMigratedBoard。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_board_edit as tbe  # noqa: E402
import swallow_cases as sc  # noqa: E402

be = tbe.be
dw = tbe.dw
sys.path.insert(0, os.path.join(tbe.ROOT, "skill", "hooks"))
import guard as gd  # noqa: E402

AFTER = '<div class="section-label">今日中</div>\n'


def _template():
    with open(os.path.join(tbe.ROOT, "skill", "assets", "board-template.html"), encoding="utf-8") as f:
        return f.read()


def to_tail(text):
    """head の形の板を、末尾の形（2026-11-10 以前のテンプレートの形）にする。"""
    nl = "\r\n" if "\r\n" in text else "\n"
    assert text.count(sc.HEAD_JS + nl) == 1
    return text.replace(sc.HEAD_JS + nl, "", 1).rstrip("\r\n") + nl + nl + sc.BOARD_JS + nl


class TestTemplate(unittest.TestCase):
    def test_head_defer(self):
        t = _template()
        self.assertEqual(t.count(sc.HEAD_JS), 1)
        self.assertNotIn(sc.BOARD_JS, t)
        self.assertLess(t.index('<link rel="stylesheet" href="board.css">'), t.index(sc.HEAD_JS))
        self.assertLess(t.index(sc.HEAD_JS), t.index('<div class="board">'))


class TestMigrate(unittest.TestCase):
    def test_tail_board_moves_to_head_form(self):
        """末尾の形の板は、テンプレートと同じ head の形になる（行・見出し・DECK 領域・ヘッダは変わらない）。2回目は移さない。"""
        today = date.today()
        head = sc.page(sc.board(_template(), today, tail=False), "n")
        tail = sc.page(sc.board(_template(), today, tail=True), "n")
        for t, want in ((tail, head), (tail.replace("\n", "\r\n"), head.replace("\n", "\r\n"))):
            with self.subTest(crlf="\r\n" in t):
                new = be.migrate_board_js(t)
                self.assertEqual(new, want)
                self.assertEqual(dw.migrate_board_js(t), new)
                self.assertEqual(be.hand_fingerprint(new), be.hand_fingerprint(t))
                self.assertEqual(be.deck_region(new), be.deck_region(t))
                self.assertEqual(be._sw_scan(new), (None, True))
                self.assertIsNone(be.migrate_board_js(new))

    def test_not_moved(self):
        """崩れた板・形の違う板は移さない。"""
        today = date.today()
        tail = sc.page(sc.board(_template(), today, tail=True), "n")
        for name, t in (("head の形", sc.page(sc.board(_template(), today, tail=False), "n")),
                        ("K16", sc.page(sc.board(_template(), today, tail=True), "<textarea>")),
                        ("K1", tail.replace('<div class="item flat" data-probe="i2"><div><p class="task-title" data-probe="ti2">B</p></div></div>',
                                            '<div class="item flat" data-probe="i2"><div><p class="task-title" data-probe="ti2">B</p></div>', 1)),
                        ("後ろに文字", tail + "<!-- x -->\n"),
                        ("board.css の読み込みが無い", tail.replace('<link rel="stylesheet" href="board.css">', "")),
                        ("属性付きの読み込み", tail.replace(sc.BOARD_JS, '<script src="board.js" async></script>')),
                        ("読み込みが無い", tail.replace(sc.BOARD_JS, ""))):
            with self.subTest(name):
                self.assertIsNone(be.migrate_board_js(t))
                self.assertIsNone(dw.migrate_board_js(t))


class TestBoardEditMigrates(tbe.Sandbox):
    def test_write_moves_and_checks_pass(self):
        """書く操作は末尾の形の板を移す。移した書き込みは K6・K7・K8・K17 に当たらない（K の検査を通って書けた）。"""
        self.create()
        head = self.text()
        self.assertIn(sc.HEAD_JS, head)
        self.write(to_tail(head))
        old = self.text()
        self.assertEqual([e["code"] for e in be.run_checks("add", old, be.migrate_board_js(old), None)
                          if e["code"] in ("K6", "K7", "K8", "K16", "K17")], [])
        rc, out = self.ed("add", "--section", "今日中", "--title", "足した行")
        self.assertEqual(rc, 0, out)
        self.assertIs(out.get("migrated"), True)     # 移した書き込みには migrated が付く（v1.14）
        rc, out2 = self.ed("set-chip", "--item", "足した行", "--chip", "active")
        self.assertEqual(rc, 0, out2)
        self.assertNotIn("migrated", out2)            # 移した後の板では付かない
        t = self.text()
        self.assertIn(sc.HEAD_JS, t)
        self.assertNotIn(sc.BOARD_JS, t)
        rc, st = self.ed("status")
        self.assertEqual(st["errors"], [])


class TestDeckMigratesAndMove(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-head-test-")
        self.board = os.path.join(self.dir, "board.html")
        self._log = dw.LOG_PATH
        dw.LOG_PATH = os.path.join(self.dir, "watcher.log")
        dw._lastgood.clear()
        dw._hand_fp.clear()
        p = os.path.join(self.dir, "spec.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(tbe.SPEC, f, ensure_ascii=False)
        rc, out = tbe.run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 0, out)

    def tearDown(self):
        dw.LOG_PATH = self._log
        dw._lastgood.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def text(self):
        with open(self.board, encoding="utf-8", newline="") as f:
            return f.read()

    def write(self, t):
        with open(self.board, "w", encoding="utf-8", newline="") as f:
            f.write(t)

    def test_inject_moves(self):
        """Deck の周回の書き直し（inject）は末尾の形の板を移す。行の指紋は変わらない。"""
        tail = to_tail(self.text())
        self.write(tail)
        self.assertEqual(dw.inject(self.board, "  <!-- x -->"), "written")
        t = self.text()
        self.assertIn(sc.HEAD_JS, t)
        self.assertNotIn(sc.BOARD_JS, t)
        self.assertEqual(dw.hand_fingerprint(t), dw.hand_fingerprint(tail))

    def test_rollover_moves(self):
        """日付の切り替えは末尾の形の板を移す。"""
        y = date.today() - timedelta(days=1)
        tail = to_tail(self.text()).replace(be.fmt_full_date(date.today()), be.fmt_full_date(y))
        new, _info = dw.roll_board_text(tail, date.today(), "0:05")
        self.assertIn(sc.HEAD_JS, new)
        self.assertNotIn(sc.BOARD_JS, new)

    def test_move_refused_on_broken_board(self):
        """崩れた板（K1・K16）では D&D の移動を書かずに 409 で断る（v2.18）。崩れていない板では書く。"""
        good = self.text()
        rc, st = tbe.run(["status", "--board", self.board])
        key = [it["key"] for s in st["sections"] for it in s["items"] if it["title"] == "作業B"][0]
        for name, t in (("K16", good.replace(AFTER, AFTER + "<textarea>\n", 1)),
                        ("K1", good.replace(AFTER, AFTER + tbe.NESTED, 1))):
            with self.subTest(name):
                self.write(t)
                self.assertEqual(dw.apply_move_to_board(self.board, key, "今日の予定", head=True), (409, dw.MOVE_BOARD_BROKEN))
                self.assertEqual(self.text(), t)
        self.write(good)
        code, _msg = dw.apply_move_to_board(self.board, key, "今日の予定", head=True)
        self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
