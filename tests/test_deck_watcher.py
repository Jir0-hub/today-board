# -*- coding: utf-8 -*-
"""deck/deck_watcher.py v2.6 の試験（T-D：書き込みの記録・読み直しの比較・os.replace の再試行・書けなかった D&D の応答）。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
すべて一時フォルダで行う。deck_watcher.py は一時フォルダへ写してから読み込む（watcher.log・sound.json を写しの側に出すため）。
受信サーバの試験は 18737 以降の臨時のポートだけを使う（本番の 8737〜8746 へは送らない）。
同時書き込みの試験（TestConcurrentProcess）は、別のフォルダに置いた Deck の写しを --board で一時フォルダの板に向けて
常駐で起動する。写しは 8737〜8746 のうち空いているものを取る（本番の Deck が 8737 を持っていれば 8738 以降）。
要求はその写しが watcher.log に書いたポートにだけ送り、止めるのもその写しのプロセスだけである。
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECK_SRC = os.path.join(ROOT, "deck", "deck_watcher.py")
BOARD_EDIT = os.path.join(ROOT, "skill", "scripts", "board_edit.py")
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))
import board_edit as be  # noqa: E402

_DECK_COPY_DIR = tempfile.mkdtemp(prefix="tb-deck-test-mod-")
shutil.copyfile(DECK_SRC, os.path.join(_DECK_COPY_DIR, "deck_watcher.py"))
_spec = importlib.util.spec_from_file_location("deck_watcher_t26", os.path.join(_DECK_COPY_DIR, "deck_watcher.py"))
dw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dw)
assert dw.SCRIPT_DIR == _DECK_COPY_DIR

SPEC = {
    "sections": ["今日の予定", "今日中", "明日以降"],
    "items": [
        {"section": "今日の予定", "time": "9:00", "title": "朝会"},
        {"section": "今日中", "title": "作業A", "chip": "active"},
        {"section": "今日中", "title": "作業B"},
        {"section": "明日以降", "title": "来週の件"},
    ],
}
HOLD = "import sys,time\nf=open(sys.argv[1],'rb')\nprint('ready',flush=True)\ntime.sleep(float(sys.argv[2]))\n"


def tearDownModule():
    shutil.rmtree(_DECK_COPY_DIR, ignore_errors=True)


def be_run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = be.main(argv)
    return rc, out.getvalue()


class DeckSandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-deck-test-")
        self.board = os.path.join(self.dir, "board.html")
        self.log_path = os.path.join(self.dir, "watcher.log")
        dw.LOG_PATH = self.log_path
        dw._HOOK_BEFORE_REREAD = None
        dw._hand_fp.clear()
        dw._lastgood.clear()
        dw._guard_unknown_logged.clear()
        dw._rollover.update({"day": None, "count": 0, "next_at": 0.0, "logged": set()})
        p = os.path.join(self.dir, "spec.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(SPEC, f, ensure_ascii=False)
        rc, out = be_run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 0, out)

    def tearDown(self):
        dw._HOOK_BEFORE_REREAD = None
        shutil.rmtree(self.dir, ignore_errors=True)

    # ---- 道具
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

    def guard_dir(self):
        return os.path.join(self.dir, ".guard")

    def records(self, writer=None):
        """(json のパス, 中身) の一覧（名前の順）。writer を渡せばその書き手のものだけ。"""
        adir = os.path.join(self.guard_dir(), "auth")
        out = []
        if os.path.isdir(adir):
            for n in sorted(os.listdir(adir)):
                if n.endswith(".json"):
                    with open(os.path.join(adir, n), encoding="utf-8") as f:
                        j = json.load(f)
                    if writer is None or j.get("writer") == writer:
                        out.append((os.path.join(adir, n), j))
        return out

    def logtext(self):
        try:
            with open(self.log_path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def tmp_left(self):
        return [n for n in os.listdir(self.dir) if n.endswith(".tmp")]

    def hold(self, sec):
        p = subprocess.Popen([sys.executable, "-I", "-c", HOLD, self.board, str(sec)], stdout=subprocess.PIPE)
        self.assertEqual(p.stdout.readline().strip(), b"ready")
        p.stdout.close()
        return p


# ------------------------------------------------------------------ 記録・format.json

class TestRecord(DeckSandbox):
    def test_move_writes_record_before_replace(self):
        old = self.read()
        old_fp = dw.hand_fingerprint(old.decode("utf-8"))
        seen = {}

        def hook(board_path, record):
            seen["record"] = record
            seen["board_at_hook"] = self.read()
            with open(record[0], encoding="utf-8") as f:
                seen["json"] = json.load(f)
            with open(record[1], "rb") as f:
                seen["body"] = f.read()
        dw._HOOK_BEFORE_REREAD = hook
        code, msg = dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True)
        self.assertEqual((code, msg), (200, "ok"))
        self.assertEqual(seen["board_at_hook"], old)                  # 置き換えの前に記録がある
        self.assertEqual(seen["body"], self.read())                   # 記録の本文＝置き換えた版
        j = seen["json"]
        self.assertEqual(j, {"v": 1, "fp": dw.hand_fingerprint(self.text()), "base_fp": old_fp,
                             "writer": "deck", "body": os.path.basename(seen["record"][1])})
        self.assertNotEqual(j["fp"], j["base_fp"])
        self.assertRegex(os.path.basename(seen["record"][0]), r"^\d{20}-%d\.json$" % os.getpid())
        self.assertEqual(len(self.records("deck")), 1)

    def test_normal_inject_writes_no_record(self):
        shutil.rmtree(self.guard_dir())
        self.assertEqual(dw.inject(self.board, "  <!-- x -->"), "written")
        self.assertEqual(dw.inject(self.board, "  <!-- y -->"), "written")
        self.assertFalse(os.path.exists(self.guard_dir()))             # 記録も format.json も作らない
        # 完了表示の整合（指紋に入らない）も記録しない
        t = self.text().replace('<p class="task-title">作業B</p>', '<p class="task-title strike">作業B</p>', 1)
        self.write(t)
        self.assertEqual(dw.inject(self.board, "  <!-- y -->"), "written")
        self.assertNotIn("strike\">作業B", self.text())
        self.assertFalse(os.path.exists(self.guard_dir()))

    def test_inject_restoring_markers_writes_record_when_fp_changes(self):
        # Deck の部分（見出し・カード）を書いてから目印だけを消す → 囲み直すと指紋が変わる
        self.assertEqual(dw.inject(self.board, dw.build_html([], time.time())), "written")
        t = self.text()
        lines = [ln for ln in t.splitlines(keepends=True)
                 if dw.MARKER_START not in ln and dw.MARKER_END not in ln]
        broken = "".join(lines)
        self.write(broken)
        n_before = len(self.records("deck"))
        self.assertEqual(dw.inject(self.board, dw.build_html([], time.time())), "written")
        recs = self.records("deck")
        self.assertEqual(len(recs), n_before + 1)
        j = recs[-1][1]
        self.assertEqual(j["base_fp"], dw.hand_fingerprint(broken))
        self.assertEqual(j["fp"], dw.hand_fingerprint(self.text()))
        self.assertNotEqual(j["fp"], j["base_fp"])

    def test_inject_footer_markers_no_record(self):
        # Deck の部分が無く、<footer> の前に空の目印を足すだけ → 指紋は変わらない
        t = self.text()
        lines = [ln for ln in t.splitlines(keepends=True)
                 if dw.MARKER_START not in ln and dw.MARKER_END not in ln]
        self.write("".join(lines))
        self.assertEqual(dw.inject(self.board, "  <!-- x -->"), "written")
        self.assertIn(dw.MARKER_START, self.text())
        self.assertEqual(self.records("deck"), [])

    def test_rollover_writes_record_before_replace(self):
        today = date.today()
        y = today - timedelta(days=1)
        t = self.text().replace(dw.fmt_full_date(today), dw.fmt_full_date(y), 1)
        self.assertIn(dw.fmt_full_date(y), t)
        self.write(t)
        seen = {}

        def hook(board_path, record):
            seen["board_at_hook"] = self.read()
            seen["record"] = record
        dw._HOOK_BEFORE_REREAD = hook
        r = dw.try_rollover(self.board, today=today, now=time.time(), assets_dir=None)
        self.assertEqual(r, "rolled")
        self.assertEqual(seen["board_at_hook"], t.encode("utf-8"))
        recs = self.records("deck")
        self.assertEqual(len(recs), 1)
        j = recs[0][1]
        self.assertEqual(j["base_fp"], dw.hand_fingerprint(t))
        self.assertEqual(j["fp"], dw.hand_fingerprint(self.text()))
        with open(os.path.join(self.guard_dir(), "auth", j["body"]), "rb") as f:
            self.assertEqual(f.read(), self.read())

    def test_format_json_created_when_absent_and_not_overwritten(self):
        shutil.rmtree(self.guard_dir())
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True)[0], 200)
        fpath = os.path.join(self.guard_dir(), "format.json")
        with open(fpath, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1})
        with open(fpath, "w", encoding="utf-8") as f:
            f.write('{"v": 1, "note": "keep"}')
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "今日中", head=True)[0], 200)
        with open(fpath, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1, "note": "keep"})
        self.assertEqual(len(self.records("deck")), 2)

    def test_unknown_format_version_writes_board_without_record(self):
        with open(os.path.join(self.guard_dir(), "format.json"), "w", encoding="utf-8") as f:
            f.write('{"v": 2}')
        old = self.read()
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True), (200, "ok"))
        self.assertNotEqual(self.read(), old)                           # 書き込み自体は止めない
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "今日中", head=True), (200, "ok"))
        self.assertEqual(self.records("deck"), [])
        self.assertEqual(self.logtext().count("format.json の版を知らないか読めないため（v=2）"), 1)   # 同じ版は1回だけ

    def test_unreadable_format_json_writes_board_without_record(self):
        fpath = os.path.join(self.guard_dir(), "format.json")
        with open(fpath, "wb") as f:
            f.write(b"{broken")
        old = self.read()
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True), (200, "ok"))
        self.assertNotEqual(self.read(), old)                           # D&D を止めない
        self.assertEqual(self.records("deck"), [])
        # 日付の切り替えも止めない
        today = date.today()
        y = today - timedelta(days=1)
        self.write(self.text().replace(dw.fmt_full_date(today), dw.fmt_full_date(y), 1))
        self.assertEqual(dw.try_rollover(self.board, today=today, now=time.time(), assets_dir=None), "rolled")
        self.assertEqual(self.records("deck"), [])
        with open(fpath, "rb") as f:
            self.assertEqual(f.read(), b"{broken")                      # 直さない・上書きしない
        self.assertEqual(self.logtext().count("format.json の版を知らないか読めないため（v=None）"), 1)

    def test_record_write_failure_blocks_write(self):
        shutil.rmtree(os.path.join(self.guard_dir(), "auth"))
        with open(os.path.join(self.guard_dir(), "auth"), "w") as f:   # auth がファイル＝記録を書けない
            f.write("x")
        old = self.read()
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True),
                         (500, dw.MOVE_WRITE_FAILED))
        self.assertEqual(self.read(), old)
        self.assertIn("書き込みの記録（.guard/auth/）を書けなかったため、board.html を書いていません", self.logtext())
        self.assertEqual(self.tmp_left(), [])

    def test_old_records_pruned_on_write(self):
        adir = os.path.join(self.guard_dir(), "auth")
        old_ns = time.time_ns() - 49 * 3600 * 10 ** 9
        base = "%020d-%d" % (old_ns, 99999)
        for ext in (".html", ".json"):
            with open(os.path.join(adir, base + ext), "w", encoding="utf-8") as f:
                f.write("{}" if ext == ".json" else "x")
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True)[0], 200)
        self.assertFalse(os.path.exists(os.path.join(adir, base + ".json")))
        self.assertFalse(os.path.exists(os.path.join(adir, base + ".html")))


# ------------------------------------------------------------------ 読み直しの比較

class TestReread(DeckSandbox):
    def other_writer(self, old, new):
        t = self.text()
        self.assertIn(old, t)
        self.write(t.replace(old, new, 1))

    def test_inject_skips_when_board_changed(self):
        self.assertEqual(dw.inject(self.board, "  <!-- x -->"), "written")

        def hook(board_path, record):
            self.other_writer("作業A</p>", "作業A改</p>")
        dw._HOOK_BEFORE_REREAD = hook
        self.assertEqual(dw.inject(self.board, "  <!-- y -->"), "conflict")
        t = self.text()
        self.assertIn("作業A改", t)                    # 割り込んだ書き込みを消していない
        self.assertIn("<!-- x -->", t)                 # Deck の書き込みは見送った
        self.assertNotIn("<!-- y -->", t)
        self.assertEqual(self.tmp_left(), [])
        self.assertIn("今回は書きませんでした", self.logtext())
        dw._HOOK_BEFORE_REREAD = None
        self.assertEqual(dw.inject(self.board, "  <!-- y -->"), "written")   # 次の周回で書ける
        self.assertIn("作業A改", self.text())

    def test_inject_conflict_removes_own_record(self):
        self.assertEqual(dw.inject(self.board, dw.build_html([], time.time())), "written")
        t = self.text()
        self.write("".join(ln for ln in t.splitlines(keepends=True)
                           if dw.MARKER_START not in ln and dw.MARKER_END not in ln))
        seen = []

        def hook(board_path, record):
            seen.append(record)
            self.other_writer("作業A</p>", "作業A改</p>")
        dw._HOOK_BEFORE_REREAD = hook
        self.assertEqual(dw.inject(self.board, dw.build_html([], time.time())), "conflict")
        self.assertIsNotNone(seen[0])                  # 指紋が変わるので記録を書いていた
        self.assertFalse(os.path.exists(seen[0][0]))   # それを消した（.json と .html）
        self.assertFalse(os.path.exists(seen[0][1]))
        self.assertEqual(self.records("deck"), [])

    def test_move_retries_after_other_writer(self):
        calls = []

        def hook(board_path, record):
            calls.append(record)
            if len(calls) == 1:
                self.other_writer("作業B</p>", "作業B改</p>")
        dw._HOOK_BEFORE_REREAD = hook
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True), (200, "ok"))
        self.assertEqual(len(calls), 2)
        self.assertFalse(os.path.exists(calls[0][0]))   # 1回目の記録は消した
        self.assertTrue(os.path.exists(calls[1][0]))
        t = self.text()
        self.assertIn("作業B改", t)                       # 割り込んだ書き込みを残したうえで
        self.assertLess(t.index("明日以降"), t.index("朝会"))   # 移動も反映した
        recs = self.records("deck")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0][1]["fp"], dw.hand_fingerprint(t))

    def test_move_gives_up(self):
        n = [0]

        def hook(board_path, record):
            n[0] += 1
            self.other_writer("</footer>", "</footer><!-- %d -->" % n[0])
        dw._HOOK_BEFORE_REREAD = hook
        self.assertEqual(dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True),
                         (409, dw.MOVE_WRITE_FAILED))
        self.assertEqual(n[0], dw.BOARD_REREAD_ATTEMPTS)
        self.assertEqual(self.records("deck"), [])
        self.assertIn("<!-- %d -->" % n[0], self.text())
        self.assertLess(self.text().index("朝会"), self.text().index("明日以降"))   # 移動は書いていない
        self.assertIn("%d 回試しても書けませんでした" % dw.BOARD_REREAD_ATTEMPTS, self.logtext())
        self.assertEqual(self.tmp_left(), [])

    def test_rollover_conflict_at_reread(self):
        today = date.today()
        y = today - timedelta(days=1)
        self.write(self.text().replace(dw.fmt_full_date(today), dw.fmt_full_date(y), 1))

        def hook(board_path, record):
            self.other_writer("作業B</p>", "作業B改</p>")
        dw._HOOK_BEFORE_REREAD = hook
        r = dw.try_rollover(self.board, today=today, now=time.time(), assets_dir=None)
        self.assertEqual(r, "conflict")
        self.assertIn(dw.fmt_full_date(y), self.text())
        self.assertIn("作業B改", self.text())
        self.assertEqual(self.records("deck"), [])
        self.assertIn("日付の切り替え: 書く直前に board.html が書き換えられたため中止しました", self.logtext())


# ------------------------------------------------------------------ os.replace の再試行・時間の上限・書けなかった D&D の応答

@unittest.skipUnless(sys.platform == "win32", "読み取り中の os.replace の失敗は Windows だけで起きる")
class TestReplaceRetry(DeckSandbox):
    def test_retry_while_reader_has_file_open(self):
        p = self.hold(0.5)
        try:
            r = dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True)
        finally:
            p.wait()
        self.assertEqual(r, (200, "ok"))
        self.assertGreaterEqual(dw._last_board_replace_tries[0], 2)   # 1回目は読み取り中で失敗し、やり直して通った
        self.assertEqual(len(self.records("deck")), 1)

    def test_inject_retry_while_reader_has_file_open(self):
        p = self.hold(0.5)
        try:
            r = dw.inject(self.board, "  <!-- x -->")
        finally:
            p.wait()
        self.assertEqual(r, "written")
        self.assertGreaterEqual(dw._last_board_replace_tries[0], 2)

    def test_retry_rereads_before_next_replace(self):
        """読み取りで開かれて置き換えを待つ間に、別の書き手が置き換えた版を消さない（待った後に読み直して比べる）。"""
        p = self.hold(0.3)

        def other():
            p.wait()                  # 読み手が閉じた直後に
            time.sleep(0.02)
            t = self.text().replace("作業A</p>", "作業A-他の書き手</p>", 1)
            tmp = self.board + ".o"
            with open(tmp, "wb") as f:
                f.write(t.encode("utf-8"))
            os.replace(tmp, self.board)
        th = threading.Thread(target=other)
        th.start()
        r = dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True)
        th.join()
        self.assertEqual(r, (200, "ok"))
        t = self.text()
        self.assertIn("作業A-他の書き手", t)                    # 別の書き手の版が残り
        self.assertLess(t.index("明日以降"), t.index("朝会"))   # そのうえに移動を当てた
        self.assertEqual(len(self.records("deck")), 1)
        self.assertEqual(self.tmp_left(), [])

    def test_inject_retry_does_not_overwrite_other_writer(self):
        p = self.hold(0.3)

        def other():
            p.wait()
            time.sleep(0.02)
            t = self.text().replace("作業A</p>", "作業A-他の書き手</p>", 1)
            tmp = self.board + ".o"
            with open(tmp, "wb") as f:
                f.write(t.encode("utf-8"))
            os.replace(tmp, self.board)
        th = threading.Thread(target=other)
        th.start()
        r = dw.inject(self.board, "  <!-- x -->")
        th.join()
        self.assertIn(r, ("conflict", "written"))
        self.assertIn("作業A-他の書き手", self.text())

    def test_deadline_stops_retries(self):
        old = self.read()
        p = self.hold(3)
        t0 = time.time()
        try:
            r = dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True,
                                       deadline=time.time() + dw.MOVE_DEADLINE_SEC)
            took = time.time() - t0
        finally:
            p.wait()
        self.assertEqual(r, (503, dw.MOVE_WRITE_FAILED))
        self.assertLess(took, dw.MOVE_DEADLINE_SEC + 0.3)
        time.sleep(0.5)
        self.assertEqual(self.read(), old)                     # 時間切れの後に書いていない
        self.assertEqual(self.records("deck"), [])
        self.assertEqual(self.tmp_left(), [])
        self.assertIn("秒以内に書けなかったため、書かずにやめました", self.logtext())

    def test_retries_exhausted(self):
        old = self.read()
        p = self.hold(3)
        try:
            r = dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True)
        finally:
            p.wait()
        self.assertEqual(r, (500, dw.MOVE_WRITE_FAILED))
        self.assertEqual(dw._last_board_replace_tries[0], dw.BOARD_REPLACE_RETRIES + 1)
        self.assertEqual(self.read(), old)
        self.assertEqual(self.records("deck"), [])        # 自分の記録は消す
        self.assertEqual(self.tmp_left(), [])
        self.assertIn("警告: board.html への書き込みに失敗", self.logtext())

    def test_lock_wait_counts_toward_deadline(self):
        held = threading.Event()
        release = threading.Event()

        def holder():
            with dw._BOARD_LOCK:
                held.set()
                release.wait(5)
        th = threading.Thread(target=holder)
        th.start()
        held.wait(5)
        old = self.read()
        t0 = time.time()
        r = dw.apply_move_to_board(self.board, "9:00|朝会", "明日以降", head=True, deadline=time.time() + 0.3)
        took = time.time() - t0
        release.set()
        th.join()
        self.assertEqual(r, (503, dw.MOVE_WRITE_FAILED))
        self.assertLess(took, 0.8)
        self.assertEqual(self.read(), old)
        self.assertIn("待っても終わらなかったため、書かずにやめました", self.logtext())

    def test_http_move_failure_is_not_200(self):
        token = "t-" + "0123456789" * 3
        server = None
        port = None
        for cand in range(18737, 18837):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", cand))
            except OSError:
                continue
            finally:
                s.close()
            server = dw.start_move_server(self.board, None, port=cand, token=token)
            if server is not None:
                port = cand
                break
        self.assertIsNotNone(server, "臨時のポートを取れない")
        try:
            url = "http://127.0.0.1:%d/board/move?board=%s&k=%s" % (
                port, urllib.parse.quote("file:" + urllib.request.pathname2url(self.board), safe=""), token)
            body = json.dumps({"k": "9:00|朝会", "sec": "明日以降", "before": None, "head": True}).encode("utf-8")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            old = self.read()
            p = self.hold(3)
            t0 = time.time()
            try:
                try:
                    with opener.open(urllib.request.Request(url, data=body, method="POST"), timeout=10) as res:
                        code, data = res.status, res.read()
                except urllib.error.HTTPError as e:
                    code, data = e.code, e.read()
                took = time.time() - t0
                time.sleep(0.5)
                after = self.read()
            finally:
                p.wait()
            # board.js が待つのをやめる 1.5 秒より前に、書かずに答える
            self.assertEqual(code, 503)
            self.assertLess(took, 1.5)
            self.assertEqual(json.loads(data.decode("utf-8")), {"ok": False, "error": dw.MOVE_WRITE_FAILED})
            self.assertEqual(after, old)
            time.sleep(0.5)
            self.assertEqual(self.read(), old)                 # 答えた後にも書いていない
            self.assertEqual(self.records("deck"), [])
            self.assertIn("移動受信: k='9:00|朝会' sec='明日以降' → 503 (%s)" % dw.MOVE_WRITE_FAILED, self.logtext())
            # 読み取りが終われば同じ要求は通る
            with opener.open(urllib.request.Request(url, data=body, method="POST"), timeout=10) as res:
                self.assertEqual(res.status, 200)
            self.assertEqual(len(self.records("deck")), 1)
        finally:
            server.shutdown()
            server.server_close()


# ------------------------------------------------------------------ 同時書き込み（別フォルダの Deck の写し）

class TestConcurrentProcess(unittest.TestCase):
    """常駐の Deck の写し（別フォルダ・--board でサンドボックス）・board_edit.py（別プロセス）・D&D の受信が
    同じ板へ並んで書く。①board_edit.py が書けたと答えた行が消えない ②板に現れた指紋は、どれも最初の板の指紋か
    記録（.guard/auth/）にある指紋（＝記録が置き換えの前に書かれている）③板の形が崩れない を確かめる。"""

    N = 8

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tb-deck-proc-")
        self.deck = os.path.join(self.tmp, "deckcopy")
        os.makedirs(self.deck)
        shutil.copyfile(DECK_SRC, os.path.join(self.deck, "deck_watcher.py"))
        self.bdir = os.path.join(self.tmp, "b")
        os.makedirs(self.bdir)
        self.board = os.path.join(self.bdir, "board.html")
        self.projects = os.path.join(self.tmp, "projects")
        os.makedirs(self.projects)
        p = os.path.join(self.tmp, "spec.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(SPEC, f, ensure_ascii=False)
        rc, out = be_run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 0, out)
        self.proc = None

    def tearDown(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait(timeout=10)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_for(self, pred, limit_sec, what):
        deadline = time.time() + limit_sec
        while time.time() < deadline:
            v = pred()
            if v:
                return v
            time.sleep(0.2)
        self.fail("TIMEOUT: " + what)

    def deck_log(self):
        try:
            with open(os.path.join(self.deck, "watcher.log"), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def test_three_writers(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-I", os.path.join(self.deck, "deck_watcher.py"), "--board", self.board,
             "--projects-dir", self.projects, "--state", os.path.join(self.tmp, "state.json")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        port = int(self.wait_for(lambda: (re.search(r"受信サーバ起動: http://127\.0\.0\.1:(\d+)/", self.deck_log())
                                          or [None, None])[1], 20, "写しの受信サーバが起動しない"))
        self.assertNotEqual(port, None)

        def key():
            with open(self.board, encoding="utf-8") as f:
                m = re.search(r'id="deck-key" hidden data-port="(\d+)" data-k="([^"]+)"', f.read())
            return m and m.group(2)
        token = self.wait_for(key, 20, "写しが接続情報を書かない")
        with open(self.board, "rb") as f:
            first_fp = dw.hand_fingerprint(f.read().decode("utf-8"))

        seen_fps = set()
        stop = threading.Event()

        def observe():
            while not stop.is_set():
                try:
                    with open(self.board, "rb") as f:
                        seen_fps.add(dw.hand_fingerprint(f.read().decode("utf-8")))
                except (OSError, UnicodeDecodeError):
                    pass
                time.sleep(0.01)

        added, add_rc = [], []

        def adder():
            for i in range(self.N):
                title = "並行%d" % i
                r = subprocess.run([sys.executable, "-I", BOARD_EDIT, "add", "--board", self.board,
                                    "--section", "今日中", "--title", title],
                                   capture_output=True, timeout=60)
                add_rc.append(r.returncode)
                if r.returncode == 0:
                    added.append(title)
                time.sleep(0.05)

        codes = []

        def mover():
            url = "http://127.0.0.1:%d/board/move?board=%s&k=%s" % (
                port, urllib.parse.quote("file:" + urllib.request.pathname2url(self.board), safe=""), token)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for i in range(self.N):
                sec = "明日以降" if i % 2 == 0 else "今日中"
                body = json.dumps({"k": "|作業A", "sec": sec, "before": None, "head": True}).encode("utf-8")
                try:
                    with opener.open(urllib.request.Request(url, data=body, method="POST"), timeout=10) as res:
                        codes.append(res.status)
                except urllib.error.HTTPError as e:
                    codes.append(e.code)
                time.sleep(0.05)

        threads = [threading.Thread(target=f) for f in (observe, adder, mover)]
        for t in threads:
            t.start()
        for t in threads[1:]:
            t.join(timeout=120)
        time.sleep(6)          # 写しの常駐が最後の変化を読んで書き直すのを待つ（POLL_SEC＝5秒）
        stop.set()
        threads[0].join(timeout=10)
        self.assertIsNone(self.proc.poll(), "写しの常駐が終わっている")

        with open(self.board, "rb") as f:
            final = f.read().decode("utf-8")
        recs = {}
        adir = os.path.join(self.bdir, ".guard", "auth")
        for n in os.listdir(adir):
            if n.endswith(".json"):
                with open(os.path.join(adir, n), encoding="utf-8") as f:
                    j = json.load(f)
                recs.setdefault(j["writer"], []).append(j)
        rec_fps = {j["fp"] for js in recs.values() for j in js}
        print("\n  同時書き込み: add の終了コード=%s・D&D の応答=%s・記録=%s・板に現れた指紋=%d"
              % (add_rc, codes, {k: len(v) for k, v in recs.items()}, len(seen_fps)), file=sys.stderr)
        for title in added:
            self.assertIn('<p class="task-title">%s</p>' % title, final, "書けたと答えた行が消えた: " + title)
        self.assertTrue(dw.board_structure_ok(final.splitlines(keepends=True)))
        self.assertTrue(set(codes) <= {200, 409, 500}, codes)
        self.assertIn(200, codes)
        self.assertGreaterEqual(len(recs.get("deck", [])), 1)
        self.assertGreaterEqual(len(recs.get("board_edit", [])), 1 + len(added))
        stray = seen_fps - rec_fps - {first_fp}
        self.assertEqual(stray, set(), "記録の無い指紋が板に現れた")
        self.assertEqual(dw.hand_fingerprint(final) in rec_fps | {first_fp}, True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
