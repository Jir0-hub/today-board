# -*- coding: utf-8 -*-
"""board_edit.py v1.2 の deck-snap / deck-wait の試験（Deck を起動し直す前後の確かめ）。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
すべて一時フォルダの板と watcher.log で行う。Deck は起動しない（板と watcher.log を試験が書いて、Deck の書き込みを模す）。
待ちの間隔と上限は引数で短くする。
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))
import board_edit as be  # noqa: E402

K_OLD = "OLDTOKEN" + "a" * 35
K_NEW = "NEWTOKEN" + "b" * 35
V_OLD = "OLDVIEW" + "c" * 36
V_NEW = "NEWVIEW" + "d" * 36
WAIT_WATCHDOG_SEC = 15   # 実時間の試験の待ちは長くても数秒。これを超えたら上限が効いていない


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = be.main(argv)
    return rc, json.loads(out.getvalue())


def span(port, k, view):
    return '<span id="deck-key" hidden data-port="%d" data-k="%s" data-view="%s"></span>' % (port, k, view)


class DeckWaitCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-deck-wait-")
        self.board = os.path.join(self.dir, "board.html")
        os.makedirs(os.path.join(self.dir, "deck"))
        self.log = os.path.join(self.dir, "deck", "watcher.log")
        self.threads = []

    def tearDown(self):
        for t in self.threads:
            t.join(timeout=10)
        shutil.rmtree(self.dir, ignore_errors=True)

    def write_board(self, inside="", outside="", same_line=False):
        mid = "" if same_line else "\n"
        body = ("<!doctype html>\n<div class=\"board\">\n%s\n  <!-- DECK:AUTO:START -->%s%s%s<!-- DECK:AUTO:END -->\n<footer></footer></div>\n"
                % (outside, mid, inside, mid))
        tmp = self.board + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        # Deck と board_edit.py と同じく、置き換えで書く（読みかけの板を読ませない）。Windows では、deck-wait が板を開いている
        # 瞬間の置き換えは PermissionError になるので、少し待って置き換え直す（見張りの側の読み方は変えない）
        for _ in range(100):
            try:
                os.replace(tmp, self.board)
                return
            except PermissionError:
                time.sleep(0.01)
        os.replace(tmp, self.board)

    def write_log(self, *lines, at=None):
        t = (at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log, "a", encoding="utf-8") as f:
            for ln in lines:
                f.write("%s %s\n" % (t, ln))

    def later(self, sec, fn):
        t = threading.Timer(sec, fn)
        t.start()
        self.threads.append(t)

    def snap(self):
        rc, out = run(["deck-snap", "--board", self.board])
        self.assertEqual(rc, 0)
        return out

    def wait(self, snap, url=None, limit="0.6", extra="0.6", more=()):
        argv = ["deck-wait", "--board", self.board, "--prev-k-fp", snap["prev_k_fp"], "--since", snap["since"],
                "--interval", "0.05", "--limit", limit, "--extra", extra]
        if url:
            argv += ["--url", url]
        argv += list(more)
        # 見張り: 別スレッドで回し、打ち切り付きで待つ（上限の不具合が、試験の固まりではなく失敗として出る）。
        # 標準出力を差し替えずに済むよう、main ではなく引数を読んだ後の op_deck_wait を呼ぶ（main の deck-wait はこれを出すだけ）
        a = be.build_parser().parse_args(argv)
        box = {}

        def target():
            try:
                box["out"] = be.op_deck_wait(os.path.abspath(a.board), a)
            except BaseException as e:   # noqa: BLE001 — 主のスレッドで出し直す
                box["err"] = e

        t0 = time.time()
        th = threading.Thread(target=target, daemon=True)
        th.start()
        th.join(timeout=WAIT_WATCHDOG_SEC)
        if th.is_alive():
            self.fail("deck-wait が %d 秒たっても終わらない（上限が効いていない）" % WAIT_WATCHDOG_SEC)
        if "err" in box:
            raise box["err"]
        out = dict(box["out"])
        out["_took"] = time.time() - t0
        return out

    def assert_no_secret(self, out):
        text = json.dumps(out)
        for secret in (K_OLD, K_NEW, V_OLD, V_NEW):
            self.assertNotIn(secret, text)

    # ---- deck-snap
    def test_snap_reads_only_between_markers_and_hides_secrets(self):
        self.write_board(inside=span(8738, K_NEW, V_NEW), outside=span(8737, K_OLD, V_OLD))
        out = self.snap()
        self.assertEqual(out["deck_key"]["port"], 8738)
        self.assertEqual(out["prev_k_fp"], be._fp(K_NEW))
        self.assert_no_secret(out)

    def test_snap_markers_must_be_proper(self):
        for kw in (dict(same_line=True),):
            self.write_board(inside=span(8738, K_NEW, V_NEW), **kw)
            self.assertEqual(self.snap()["prev_k_fp"], "none")
        # END が欠けている・順序が逆
        with open(self.board, "w", encoding="utf-8") as f:
            f.write("<!-- DECK:AUTO:START -->\n%s\n" % span(8738, K_NEW, V_NEW))
        self.assertEqual(self.snap()["deck_key"]["markers"], "count")
        with open(self.board, "w", encoding="utf-8") as f:
            f.write("<!-- DECK:AUTO:END -->\n%s\n<!-- DECK:AUTO:START -->\n" % span(8738, K_NEW, V_NEW))
        self.assertEqual(self.snap()["deck_key"]["markers"], "order")
        # カードの文に入った同じ文字列（Deck は < を &lt; にして書く）は目印に数えない
        self.write_board(inside=span(8738, K_NEW, V_NEW) + "\n<p>&lt;!-- DECK:AUTO:START --&gt;</p>")
        self.assertEqual(self.snap()["prev_k_fp"], be._fp(K_NEW))

    # ---- 替わった
    def test_changed_same_url(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.later(0.2, lambda: self.write_board(inside=span(8737, K_NEW, V_OLD)))
        out = self.wait(s, url="http://127.0.0.1:8737/?v=" + V_OLD)
        self.assertEqual(out["result"], "same-url")
        self.assertLess(out["_took"], 0.6)
        self.assert_no_secret(out)

    def test_changed_port_opens_new_url(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.later(0.2, lambda: self.write_board(inside=span(8738, K_NEW, V_NEW)))
        out = self.wait(s, url="http://127.0.0.1:8737/?v=" + V_OLD)
        self.assertEqual(out["result"], "open-new-url")
        self.assertTrue(out["port_changed"])
        self.assertTrue(out["view_changed"])
        self.assertNotIn("url", out)
        self.assert_no_secret(out)

    def test_changed_view_same_port_opens_new_url_and_prints_when_asked(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.later(0.2, lambda: self.write_board(inside=span(8737, K_NEW, V_NEW)))
        out = self.wait(s, url="http://127.0.0.1:8737/?v=" + V_OLD, more=["--print-url"])
        self.assertEqual(out["result"], "open-new-url")
        self.assertFalse(out["port_changed"])
        self.assertEqual(out["url"], "http://127.0.0.1:8737/?v=" + V_NEW)

    def test_appears_when_there_was_none(self):
        self.write_board()
        s = self.snap()
        self.assertEqual(s["prev_k_fp"], "none")
        self.later(0.2, lambda: self.write_board(inside=span(8739, K_NEW, V_NEW)))
        out = self.wait(s, url="http://127.0.0.1:8737/?v=" + V_OLD)
        self.assertEqual(out["result"], "open-new-url")

    def test_disappears_is_no_key(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.later(0.2, lambda: self.write_board(inside="<div>cards</div>"))
        self.assertEqual(self.wait(s)["result"], "no-key")

    def test_old_key_outside_markers_does_not_count_as_change(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.later(0.1, lambda: self.write_board(inside=span(8737, K_OLD, V_OLD), outside=span(8740, K_NEW, V_NEW)))
        self.assertEqual(self.wait(s)["result"], "not-started")

    # ---- 替わらない: watcher.log の読み分け
    def test_duplicate_returns_early(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.later(0.1, lambda: self.write_log("多重起動を検出したため終了します（board=x / lock=y）: 稼働中の1本目 → z"))
        out = self.wait(s, limit="5")
        self.assertEqual(out["result"], "duplicate")
        self.assertLess(out["_took"], 2)     # 上限（5 秒）を待たない

    def test_no_port(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)",
                       "警告: 受信ポート 8737〜8746 をすべてバインドできません（…）")
        self.assertEqual(self.wait(s)["result"], "no-port")

    def test_no_marker(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)",
                       "警告: board.html に DECK:AUTO マーカーが見つかりません（挿入は行いません）")
        self.assertEqual(self.wait(s)["result"], "no-marker")

    def test_collecting_extends_once_then_not_written_yet(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)")
        out = self.wait(s, limit="0.4", extra="0.4")
        self.assertEqual(out["result"], "not-written-yet")
        self.assertTrue(out["extended"])
        self.assertGreaterEqual(out["_took"], 0.75)
        self.assertLess(out["_took"], 2.0)    # 上限（0.4＋0.4）で必ず終わる

    def test_collecting_then_written_during_extension(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)")
        self.later(0.6, lambda: self.write_board(inside=span(8737, K_NEW, V_OLD)))
        out = self.wait(s, url="http://127.0.0.1:8737/?v=" + V_OLD, limit="0.4", extra="1.0")
        self.assertEqual(out["result"], "same-url")
        self.assertTrue(out["extended"])

    def test_regenerated_but_unchanged_is_unknown(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)", "再生成: セッション 3 件を board.html に反映")
        self.assertEqual(self.wait(s)["result"], "unknown")

    def test_nothing_is_not_started(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        out = self.wait(s, limit="0.3")
        self.assertEqual(out["result"], "not-started")
        self.assertLess(out["_took"], 1.5)

    def test_lines_before_since_are_ignored(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        self.write_log("多重起動を検出したため終了します", "受信ポート 8737〜8746 をすべてバインドできません",
                       at=datetime.now() - timedelta(minutes=5))
        s = self.snap()
        self.assertEqual(self.wait(s, limit="0.3")["result"], "not-started")

    def test_missing_board_is_not_a_change(self):
        """板が読めない周回（置き換えの最中など）は、消えたとはみなさない。"""
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        os.remove(self.board)
        self.later(0.2, lambda: self.write_board(inside=span(8737, K_NEW, V_OLD)))
        self.assertEqual(self.wait(s, url="http://127.0.0.1:8737/?v=" + V_OLD)["result"], "same-url")

    def test_bad_arguments(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        rc, out = run(["deck-wait", "--board", self.board, "--prev-k-fp", "none", "--since", "きのう"])
        self.assertEqual(rc, 1)
        self.assertFalse(out["ok"])
        rc, out = run(["deck-wait", "--board", self.board, "--since", "2026-11-04 10:00:00"])
        self.assertEqual(rc, 1)


    # ---- 目印の崩れ
    def test_markers_broken_after_snap_is_board_markers(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.later(0.1, lambda: self.write_board(inside=span(8737, K_OLD, V_OLD) + "\n<!-- DECK:AUTO:START -->"))
        out = self.wait(s)
        self.assertEqual(out["result"], "board-markers")
        self.assertEqual(out["deck_key"]["markers"], "count")

    def test_two_pairs_of_markers_is_board_markers(self):
        with open(self.board, "w", encoding="utf-8") as f:
            f.write("<!-- DECK:AUTO:START -->\n%s\n<!-- DECK:AUTO:END -->\n<!-- DECK:AUTO:START -->\n%s\n<!-- DECK:AUTO:END -->\n"
                    % (span(8737, K_OLD, V_OLD), span(8738, K_NEW, V_NEW)))
        s = self.snap()
        self.assertEqual(s["prev_k_fp"], "none")
        self.assertEqual(s["deck_key"]["markers"], "count")
        self.assertEqual(self.wait(s)["result"], "board-markers")

    # ---- 引数の検査
    def test_argument_shapes(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        base = ["deck-wait", "--board", self.board, "--since", s["since"], "--interval", "0.05", "--limit", "0.2", "--extra", "0"]
        for fp in ("abc", "X" * 16, be._fp(K_OLD) + "0", "NONE"):
            rc, out = run(base + ["--prev-k-fp", fp])
            self.assertEqual(rc, 1, fp)
        ok = base + ["--prev-k-fp", s["prev_k_fp"]]
        for url in ("http://127.0.0.1:abc/?v=x", "http://127.0.0.1:70000/?v=x"):
            rc, out = run(ok + ["--url", url])
            self.assertEqual(rc, 1, url)
            self.assertIn("--url", out["error"])
        # 秒の数は、差し込んだ時計で呼ぶ（検査が外れても、試験が固まらずに失敗する）
        for name in ("limit", "interval", "extra"):
            for bad in ("inf", "nan", "-inf", "x"):
                vals = dict(interval="0.05", limit="0.2", extra="0")
                vals[name] = bad
                ns = argparse.Namespace(prev_k_fp=s["prev_k_fp"], since=s["since"], log=None, url=None, print_url=False, **vals)
                ft = FakeTime(limit_calls=1000)
                with self.assertRaises(be.OpError, msg=(name, bad)):
                    be.op_deck_wait(self.board, ns, sleep=ft.sleep, clock=ft.clock)

    def test_url_without_port_is_written(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.later(0.1, lambda: self.write_board(inside=span(8737, K_NEW, V_OLD)))
        out = self.wait(s, url="http://127.0.0.1/?v=" + V_OLD, more=["--print-url"])
        self.assertEqual(out["result"], "written")
        self.assertEqual(out["url"], "http://127.0.0.1:8737/?v=" + V_OLD)

    def test_bad_data_port_is_not_present(self):
        for port in ("０８７３７", "70000", "0", "87a7"):
            with open(self.board, "w", encoding="utf-8") as f:
                f.write('<!-- DECK:AUTO:START -->\n<span id="deck-key" hidden data-port="%s" data-k="%s" data-view="%s"></span>\n'
                        '<!-- DECK:AUTO:END -->\n' % (port, K_OLD, V_OLD))
            self.assertFalse(self.snap()["deck_key"]["present"], port)

    # ---- 「再生成」の照合（書けた行だけを数える）
    def test_failed_regenerate_line_is_still_collecting(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)", "エラー（継続）: 再生成の途中で読めませんでした")
        self.assertEqual(self.wait(s, limit="0.2", extra="0.2")["result"], "not-written-yet")

    def test_deck_real_failed_write_line_is_not_regenerated(self):
        """Deck が書けなかったときの実物の文言（deck_watcher.py の「再生成: 書く直前に…」）は、書けた印に数えない。"""
        line = "再生成: 書く直前に board.html が別の書き手に書き換えられたため、今回は書きませんでした（次の周回で読み直します）"
        with open(os.path.join(ROOT, "deck", "deck_watcher.py"), encoding="utf-8") as f:
            self.assertIn(line, f.read())      # 文言が Deck の実物であることを確かめる
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)", line)
        out = self.wait(s, limit="0.2", extra="0.2")
        self.assertEqual(out["result"], "not-written-yet")
        self.assertTrue(out["extended"])
        self.assertTrue(any("再生成: 書く直前に" in ln for ln in out["log"]))     # 数えないが log には入る
        self.assertEqual(out["skipped_writes"], 1)

    def test_failed_write_line_is_logged_with_other_results(self):
        """書けなかった行は、result が written のときも log に入る。"""
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)",
                       "再生成: 書く直前に board.html が別の書き手に書き換えられたため、今回は書きませんでした（次の周回で読み直します）")
        self.later(0.1, lambda: self.write_board(inside=span(8737, K_NEW, V_OLD)))
        out = self.wait(s)
        self.assertEqual(out["result"], "written")
        self.assertTrue(any("再生成: 書く直前に" in ln for ln in out["log"]))
        self.assertEqual(out["skipped_writes"], 1)

    def test_many_failed_write_lines_do_not_push_out_start_lines(self):
        """書けなかった行が続いても、起動の手がかりの行（受信サーバ起動・常駐モード開始）は log に残り、書けなかった行は最後の1行と数だけ。"""
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        skipped = "再生成: 書く直前に board.html が別の書き手に書き換えられたため、今回は書きませんでした（次の周回で読み直します）"
        self.write_log("受信サーバ起動: 127.0.0.1:8737", "起動: 常駐モード開始 (projects=p, board=b)", *([skipped] * 15))
        out = self.wait(s, limit="0.2", extra="0.2")
        self.assertEqual(out["result"], "not-written-yet")
        self.assertTrue(any("受信サーバ起動" in ln for ln in out["log"]))
        self.assertTrue(any("常駐モード開始" in ln for ln in out["log"]))
        self.assertEqual(sum("再生成: 書く直前に" in ln for ln in out["log"]), 1)
        self.assertEqual(out["skipped_writes"], 15)
        self.assertEqual(out["log"][-1].split(" ", 2)[2], skipped)            # 元の順（書けなかった行が最後）

    def test_unknown_includes_the_regenerate_line(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)", "再生成: セッション 3 件を board.html に反映")
        out = self.wait(s, limit="0.2")
        self.assertEqual(out["result"], "unknown")
        self.assertTrue(any("再生成: セッション" in ln for ln in out["log"]))
        self.assertEqual(out["skipped_writes"], 0)                              # 書けなかった行が無ければ 0

    def test_many_regenerate_lines_do_not_push_out_start_lines(self):
        """unknown で「再生成: セッション」の行が続いても、起動の手がかりの行は log に残り、「再生成」の行は最後の1行だけ。"""
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        regen = ["再生成: セッション %d 件を board.html に反映" % n for n in range(1, 16)]
        self.write_log("受信サーバ起動: 127.0.0.1:8737", "起動: 常駐モード開始 (projects=p, board=b)", *regen)
        out = self.wait(s, limit="0.2")
        self.assertEqual(out["result"], "unknown")
        self.assertTrue(any("受信サーバ起動" in ln for ln in out["log"]))
        self.assertTrue(any("常駐モード開始" in ln for ln in out["log"]))
        self.assertEqual([ln.split(" ", 2)[2] for ln in out["log"] if "再生成: セッション" in ln], [regen[-1]])
        self.assertEqual(out["log"][-1].split(" ", 2)[2], regen[-1])             # 元の順

    def test_regenerate_line_is_not_logged_unless_unknown(self):
        """unknown 以外の result では、「再生成: セッション」の行は log に入れない（起動の手がかりではないため）。"""
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)", "再生成: セッション 3 件を board.html に反映")
        self.later(0.1, lambda: self.write_board(inside=span(8737, K_NEW, V_OLD)))
        out = self.wait(s)
        self.assertEqual(out["result"], "written")
        self.assertTrue(any("常駐モード開始" in ln for ln in out["log"]))
        self.assertFalse(any("再生成: セッション" in ln for ln in out["log"]))

    def test_last_line_of_each_clue_is_kept(self):
        """起動の手がかりの行が 10 行を超えても、手がかりの文言ごとの最後の1行は log に残る（「常駐モード開始」を押し出さない）。"""
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)",
                       *["受信サーバ起動: 127.0.0.1:%d" % (8737 + n) for n in range(12)])
        out = self.wait(s, limit="0.2", extra="0.2")
        self.assertEqual(out["result"], "not-written-yet")
        self.assertTrue(any("常駐モード開始" in ln for ln in out["log"]))
        self.assertTrue(any("8748" in ln for ln in out["log"]))


class FakeTime:
    """clock と sleep を差し込む。待ちの不具合が試験の固まりではなく失敗として出るよう、sleep の回数に上限を付ける。"""

    def __init__(self, limit_calls=10000):
        self.t = 0.0
        self.calls = 0
        self.limit_calls = limit_calls

    def clock(self):
        return self.t

    def sleep(self, sec):
        self.calls += 1
        if self.calls > self.limit_calls:
            raise AssertionError("待ちが終わらない（sleep が %d 回を超えた）" % self.limit_calls)
        self.t += sec


class DeckWaitClockCase(unittest.TestCase):
    """deck-wait の待ちの上限を、差し込んだ時計で確かめる（実時間は使わない）。道具は DeckWaitCase のものを借りる。"""

    setUp = DeckWaitCase.setUp
    tearDown = DeckWaitCase.tearDown
    write_board = DeckWaitCase.write_board
    write_log = DeckWaitCase.write_log
    snap = DeckWaitCase.snap

    def call(self, snap, interval, limit, extra):
        ns = argparse.Namespace(prev_k_fp=snap["prev_k_fp"], since=snap["since"], log=None, url=None, print_url=False,
                                interval=str(interval), limit=str(limit), extra=str(extra))
        ft = FakeTime()
        out = be.op_deck_wait(self.board, ns, sleep=ft.sleep, clock=ft.clock)
        return out, ft

    def test_total_wait_never_exceeds_limit_plus_extra(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("起動: 常駐モード開始 (projects=p, board=b)")
        out, ft = self.call(s, interval=7, limit=60, extra=60)
        self.assertEqual(out["result"], "not-written-yet")
        self.assertTrue(out["extended"])
        self.assertLessEqual(ft.t, 120.0 + 1e-9)
        self.assertGreaterEqual(ft.t, 120.0 - 1e-9)

    def test_not_started_ends_at_limit(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        out, ft = self.call(s, interval=2, limit=60, extra=60)
        self.assertEqual(out["result"], "not-started")
        self.assertFalse(out["extended"])
        self.assertLessEqual(ft.t, 60.0 + 1e-9)

    def test_no_port_ends_at_limit(self):
        self.write_board(inside=span(8737, K_OLD, V_OLD))
        s = self.snap()
        self.write_log("警告: 受信ポート 8737〜8746 をすべてバインドできません（…）")
        out, ft = self.call(s, interval=2, limit=60, extra=60)
        self.assertEqual(out["result"], "no-port")
        self.assertLessEqual(ft.t, 60.0 + 1e-9)


class DeckLogWordsCase(unittest.TestCase):
    """board_edit.py が読み分けに使う watcher.log の文言は、deck/deck_watcher.py が書く文言の写し。Deck のソースに実在することを確かめる。"""

    def test_words_exist_in_deck_source(self):
        with open(os.path.join(ROOT, "deck", "deck_watcher.py"), encoding="utf-8") as f:
            src = f.read()
        words = [w for _k, w in be.DECK_LOG_KINDS] + [be.DECK_LOG_STARTED, be.DECK_LOG_REGEN, be.DECK_LOG_SERVER]
        for w in words:
            self.assertIn(w, src, w)


if __name__ == "__main__":
    unittest.main(verbosity=2)
