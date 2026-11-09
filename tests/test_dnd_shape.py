# -*- coding: utf-8 -*-
"""D&D の反映（Deck v2.10 の /board/move）が、board_edit.py の move・日付の切り替えと同じ形を作ることの試験。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
すべて一時フォルダの板で行う。受信サーバの試験は 18737 以降の臨時のポートだけを使う。
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse
import urllib.request
from datetime import date, timedelta

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))
import board_edit as be  # noqa: E402

_MOD = tempfile.mkdtemp(prefix="tb-dnd-mod-")
shutil.copyfile(os.path.join(ROOT, "deck", "deck_watcher.py"), os.path.join(_MOD, "deck_watcher.py"))
_spec = importlib.util.spec_from_file_location("deck_watcher_dnd", os.path.join(_MOD, "deck_watcher.py"))
dw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dw)

TODAY = date.today()
YEST = TODAY - timedelta(days=1)
TOKEN = "t-" + "0123456789" * 3


class _FixedDate(date):
    """試験の間の「今日」を固定する（0 時をまたいでも board_edit.py と Deck が同じ日を今日とみなす）。"""

    @classmethod
    def today(cls):
        return TODAY


_SAVED = {}


def setUpModule():
    _SAVED["be"], _SAVED["dw"] = be.date, dw.date
    be.date = _FixedDate
    dw.date = _FixedDate


def tearDownModule():
    be.date, dw.date = _SAVED["be"], _SAVED["dw"]
    shutil.rmtree(_MOD, ignore_errors=True)


def be_run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = be.main(argv)
    return rc, out.getvalue()


LATER_DUE = (TODAY + timedelta(days=3)).isoformat() + " 14:00"   # 「明日以降」へ戻す行に当てる実施日（v1.9・v2.13）


class DndShapeCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-dnd-")
        dw.LOG_PATH = os.path.join(self.dir, "watcher.log")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def make_board(self, name):
        """今日の予定・今日中・明日以降の板。「明日以降」に、時刻の欄を持つ前の日の行・実施日が今日で時刻のある行・実施日の無い行、
        今日中に、一度移した印の付いた行（明日以降へ戻す試験用）を置く。"""
        board = os.path.join(self.dir, name)
        sp = os.path.join(self.dir, name + ".spec.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
                {"section": "今日の予定", "time": "9:00", "title": "前の日の時刻つき"},
                {"section": "今日の予定", "time": "10:00", "title": "朝の会議"},
                {"section": "今日中", "title": "ふつう", "chip": "active"},
                {"section": "今日中", "title": "移した行", "due": YEST.isoformat(), "due_moved": TODAY.isoformat()},
                {"section": "明日以降", "title": "今日の時刻", "due": (TODAY + timedelta(days=1)).isoformat() + " 23:58"},
                {"section": "明日以降", "title": "日付だけ", "due": (TODAY + timedelta(days=1)).isoformat()},
                {"section": "明日以降", "title": "実施日なし"},
            ]}, f, ensure_ascii=False)
        self.assertEqual(be_run(["create", "--board", board, "--spec", sp])[0], 0)
        for argv in (["move", "--item", "9:00|前の日の時刻つき", "--section", "明日以降", "--due", "none"],   # 未定で戻す（時刻の欄は残る・v1.9）
                     ["set-due", "--item", "9:00|前の日の時刻つき", "--due", YEST.isoformat()],
                     ["set-due", "--item", "|今日の時刻", "--due", TODAY.isoformat() + " 23:58"],
                     ["set-due", "--item", "|日付だけ", "--due", TODAY.isoformat()]):
            self.assertEqual(be_run(argv[:1] + ["--board", board] + argv[1:])[0], 0, argv)
        return board

    def read(self, board):
        with open(board, encoding="utf-8") as f:
            return f.read()

    def block(self, text, title):
        lines = text.splitlines(keepends=True)
        _s, items, _d = dw._scan_board(lines)
        for s, e, name in items:
            b = "".join(lines[s:e + 1])
            if (dw._element_text(b, "task-title") or "") == title:
                return name, b.strip()
        return None, None

    def dnd(self, text, k, sec, due=None):
        # 今日の側から「明日以降」へは、board.js が利用者の決めた実施日を送る（v2.13）
        new, code, msg = dw.apply_board_move(text, k, sec, None, False, today=TODAY, due=due, set_due=due is not None)
        self.assertEqual(code, 200, msg)
        return new

    def move(self, board, k, sec, due=None):
        rc, out = be_run(["move", "--board", board, "--item", k, "--section", sec] + (["--due", due] if due else []))
        self.assertEqual(rc, 0, out)
        return self.read(board)

    CASES = [("9:00|前の日の時刻つき", "前の日の時刻つき", "今日の予定"), ("9:00|前の日の時刻つき", "前の日の時刻つき", "今日中"),
             ("|今日の時刻", "今日の時刻", "今日の予定"), ("|今日の時刻", "今日の時刻", "今日中"),
             ("|日付だけ", "日付だけ", "今日の予定"), ("|日付だけ", "日付だけ", "今日中"),
             ("|実施日なし", "実施日なし", "今日中"), ("|移した行", "移した行", "明日以降"), ("|ふつう", "ふつう", "今日の予定")]

    def test_same_block_as_move(self):
        """どの行き先でも、D&D で動かした行は move で動かした行と同じ形になる（位置は D&D が落とした位置・move が既定の位置）。"""
        for i, (k, title, sec) in enumerate(self.CASES):
            with self.subTest(item=title, to=sec):
                board = self.make_board("b%d.html" % i)   # 試験ごとに別の板（1件の失敗が次へ持ち越さないように）
                text = self.read(board)
                due = LATER_DUE if sec == "明日以降" else None
                after_dnd = self.dnd(text, k, sec, due)
                after_move = self.move(board, k, sec, due)
                n1, b1 = self.block(after_dnd, title)
                n2, b2 = self.block(after_move, title)
                self.assertEqual((n1, b1), (n2, b2))

    def test_alarms_follow_the_shape(self):
        """前の日の時刻は今日の側へ D&D しても鳴らさず、実施日が今日で時刻のある行は今日の予定へ D&D するとその時刻に鳴る。"""
        board = self.make_board("b.html")
        text = self.dnd(self.read(board), "9:00|前の日の時刻つき", "今日の予定")
        text = self.dnd(text, "|今日の時刻", "今日の予定")
        with open(board, "w", encoding="utf-8") as f:
            f.write(text)
        alarms = {a[3]: a[2] for a in dw.read_board_alarms(board)}
        self.assertNotIn("前の日の時刻つき", alarms)
        self.assertEqual(alarms.get("今日の時刻"), "23:58")
        _n, b = self.block(text, "前の日の時刻つき")
        self.assertNotIn("data-orig-time", b)                        # 行の時刻は data-due-from に残る（Deck v2.12）
        self.assertIn('data-due-from="%s 9:00"' % (TODAY - timedelta(days=1)).isoformat(), b)
        self.assertIn('class="item flat"', b)
        self.assertIn('data-due-moved="%s"' % TODAY.isoformat(), b)

    def test_dropped_position_is_kept(self):
        """位置は落とした位置のまま（head・before）。形だけを move と同じにする。"""
        board = self.make_board("b.html")
        text = self.read(board)
        new, code, _m = dw.apply_board_move(text, "|今日の時刻", "今日の予定", None, True, today=TODAY)
        self.assertEqual(code, 200)
        lines = new.splitlines(keepends=True)
        _s, items, _d = dw._scan_board(lines)
        plan = [dw._element_text("".join(lines[s:e + 1]), "task-title") for s, e, n in items if n == "今日の予定"]
        self.assertEqual(plan[0], "今日の時刻")    # 時刻の順（10:00 の後）ではなく、先頭へ落とした位置

    def test_rollover_uses_the_same_shape(self):
        """日付の切り替え（_move_due_block）も同じ形の関数を使い、行き先は時刻の欄の有無で決まる。"""
        board = self.make_board("b.html")
        text = self.read(board)
        for title, want in (("前の日の時刻つき", "今日中"), ("今日の時刻", "今日の予定"), ("日付だけ", "今日中")):
            _n, b = self.block(text, title)
            due = dw._item_due_pending(b, TODAY)
            shaped, to = dw._move_due_block(b, due, TODAY, "\n")
            self.assertEqual(to, want, title)
            self.assertEqual(shaped, dw._due_moved_shape(b, due, TODAY, "\n", True))

    def http_move(self, board, k, sec):
        server = None
        for cand in range(18737, 18837):
            server = dw.start_move_server(board, None, port=cand, token=TOKEN)
            if server is not None:
                port = cand
                break
        self.assertIsNotNone(server)
        try:
            url = "http://127.0.0.1:%d/board/move?board=%s&k=%s" % (
                port, urllib.parse.quote("file:" + urllib.request.pathname2url(board), safe=""), TOKEN)
            body = json.dumps({"k": k, "sec": sec, "before": None, "head": False}).encode("utf-8")
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with op.open(urllib.request.Request(url, data=body, method="POST"), timeout=10) as r:
                return r.status
        finally:
            server.shutdown()
            server.server_close()

    def test_two_time_fields_get_only_the_mark(self):
        """時刻の欄が2つある、実施日の来た行を /board/move で今日の側へ動かすと、印だけが付き、時刻の欄は2つのまま（move と同じ）。"""
        board = self.make_board("b.html")
        text = self.read(board)
        _n, b = self.block(text, "日付だけ")
        two = b.replace('<p class="task-title">', '<div class="time">8:00</div><div class="time">8:30</div><p class="task-title">', 1)
        with open(board, "w", encoding="utf-8") as f:
            f.write(text.replace(b, two, 1))
        self.assertEqual(self.http_move(board, dw._item_key(two), "今日中"), 200)
        name, after = self.block(self.read(board), "日付だけ")
        self.assertEqual(name, "今日中")
        self.assertIn('data-due-moved="%s"' % TODAY.isoformat(), after)
        self.assertEqual(after.count('class="time"'), 2)
        # 開始タグは印を足しただけ（flat・data-orig-time は変えない）、中身はそのまま
        self.assertEqual(after, two.replace(">", ' data-due-moved="%s">' % TODAY.isoformat(), 1))

    def test_invalid_calendar_due_is_not_shaped(self):
        """暦に無い実施日（2025-02-30）は読まない＝形も印も付けない（board.js と同じ）。"""
        board = self.make_board("b.html")
        text = self.read(board)
        _n, b = self.block(text, "実施日なし")
        self.assertNotIn("data-due", b)
        head, rest = b.split(">", 1)
        bad = head + ' data-due="2025-02-30">' + rest
        text = text.replace(b, bad, 1)
        new = self.dnd(text, "|実施日なし", "今日中")
        _n, after = self.block(new, "実施日なし")
        self.assertNotIn("data-due-moved", after)
        self.assertNotIn("chip pending", after)

    def test_unclosed_time_field_cannot_be_shaped(self):
        """中に行の部品のある時刻の欄（閉じタグの無い欄にタイトルが入る形）の行は形を作れない（_due_moved_shape が None＝D&D と move は印だけ）。
        board.js も印だけにする（tbTimeHasPart）。"""
        b = ('<div class="item" data-due="%s">\n  <div class="time">9:00\n  <div>\n    <p class="task-title">x</p>\n  </div>\n</div>\n'
             % YEST.isoformat())
        due = dw._item_due_pending(b, TODAY)
        self.assertIsNotNone(due)
        self.assertIsNone(dw._due_moved_shape(b, due, TODAY, "\n", True))

    def test_http_move_writes_the_shape(self):
        board = self.make_board("b.html")
        server = None
        for cand in range(18737, 18837):
            server = dw.start_move_server(board, None, port=cand, token=TOKEN)
            if server is not None:
                port = cand
                break
        self.assertIsNotNone(server)
        try:
            url = "http://127.0.0.1:%d/board/move?board=%s&k=%s" % (
                port, urllib.parse.quote("file:" + urllib.request.pathname2url(board), safe=""), TOKEN)
            body = json.dumps({"k": "9:00|前の日の時刻つき", "sec": "今日中", "before": None, "head": False}).encode("utf-8")
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with op.open(urllib.request.Request(url, data=body, method="POST"), timeout=10) as r:
                self.assertEqual(r.status, 200)
        finally:
            server.shutdown()
            server.server_close()
        name, b = self.block(self.read(board), "前の日の時刻つき")
        self.assertEqual(name, "今日中")
        self.assertNotIn('class="time"', b)
        self.assertNotIn("data-orig-time", b)
        self.assertIn('data-due-from="%s 9:00"' % (TODAY - timedelta(days=1)).isoformat(), b)
        self.assertEqual([a for a in dw.read_board_alarms(board) if a[3] == "前の日の時刻つき"], [])

    def test_http_move_without_due_keeps_the_row(self):
        """"due" の無い /board/move（v2.12 と同時の board.js）で今日の側の行を「明日以降」へ動かすと、行の形を変えない
        （印・実施日・元の実施日・時刻の欄がそのまま。v2.13）。"due" が文字列でも null でもない要求は 400 で、板を変えない。"""
        board = self.make_board("b.html")
        came = (TODAY - timedelta(days=2)).isoformat() + " 9:00"
        rc, out = be_run(["add", "--board", board, "--section", "今日の予定", "--title", "戻す", "--time", "11:00",
                          "--due", TODAY.isoformat() + " 11:00", "--due-moved", TODAY.isoformat(), "--due-from", came])
        self.assertEqual(rc, 0, out)
        _n, start = self.block(self.read(board), "戻す")
        head = start.split(">", 1)[0]
        self.assertIn('data-due-moved="%s"' % TODAY.isoformat(), head)
        self.assertIn('data-due-from="%s"' % came, head)
        server = None
        for cand in range(18837, 18937):
            server = dw.start_move_server(board, None, port=cand, token=TOKEN)
            if server is not None:
                port = cand
                break
        self.assertIsNotNone(server)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = "http://127.0.0.1:%d/board/move?board=%s&k=%s" % (
            port, urllib.parse.quote("file:" + urllib.request.pathname2url(board), safe=""), TOKEN)

        def post(payload):
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
            try:
                with op.open(req, timeout=10) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code
        try:
            before = self.read(board)
            self.assertEqual(post({"k": "11:00|戻す", "sec": "明日以降", "before": None, "head": False, "due": 5}), 400)
            self.assertEqual(self.read(board), before)
            self.assertEqual(post({"k": "11:00|戻す", "sec": "明日以降", "before": None, "head": False}), 200)
        finally:
            server.shutdown()
            server.server_close()
        name, b = self.block(self.read(board), "戻す")
        self.assertEqual(name, "明日以降")
        self.assertEqual(b, start)                     # 印・実施日・元の実施日・時刻の欄（11:00）とも変わらない
        self.assertIn('<div class="time">11:00</div>', b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
