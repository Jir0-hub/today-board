# -*- coding: utf-8 -*-
"""構造の検査 K16（閉じていない textarea・script など、ブラウザがそれより後ろのページを飲み込む形＝_swallow_open）の試験。

board_edit.py v1.13（status・書く操作・restore）、Deck v2.17（崩れる前の版の退避・日付の切り替え）、guard.py v1.1（形の悪さ）を、
サンドボックスの板で確かめる。当たる形で画面から要素が消えることは tests/test_board_browser.py の TestSwallowInBrowser（Chrome）。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
"""
import os
import sys
import tempfile
import shutil
import unittest
from datetime import date, timedelta

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_board_edit as tbe  # noqa: E402  （Sandbox と run を借りる）

be = tbe.be
dw = tbe.dw
sys.path.insert(0, os.path.join(tbe.ROOT, "skill", "hooks"))
import guard as gd  # noqa: E402
import swallow_cases as sc  # noqa: E402

AFTER = '<div class="section-label">今日中</div>\n'


def _template():
    with open(os.path.join(tbe.ROOT, "skill", "assets", "board-template.html"), encoding="utf-8") as f:
        return f.read()


class TestSwallowOpen(unittest.TestCase):
    def test_cases(self):
        """当たる ⇔ 項目・見出し・行の部品・Deck の要素のどれかが画面から消える（swallow_cases.CASES。Chrome で確かめた形＝TestSwallowInBrowser）。"""
        t = sc.board(_template(), date.today())
        self.assertIsNone(be._swallow_open(sc.page(t, "n")))
        self.assertIsNone(be._swallow_open(_template()))
        for snip, want in sc.CASES:
            p = sc.page(t, snip)
            with self.subTest(snippet=snip):
                hit = be._swallow_open(p)
                self.assertEqual(hit is not None, want, hit)
                self.assertEqual(dw._swallow_open(p), hit)
                self.assertEqual(gd._swallow_open(p), hit)

    def test_cut_only(self):
        """形の中に行の部品を書いた形（swallow_cases.CUT_ONLY）は当たる（3つの写しで同じ）。"""
        t = sc.board(_template(), date.today())
        for snip in sc.CUT_ONLY + sc.CUT_MISS:
            with self.subTest(snippet=snip):
                p = sc.page(t, snip)
                hit = be._swallow_open(p)
                self.assertIsNotNone(hit)
                self.assertEqual(dw._swallow_open(p), hit)
                self.assertEqual(gd._swallow_open(p), hit)

    def test_no_cut_and_limit_not_k16(self):
        """swallow_cases.NO_CUT・CUT_LIMIT の形は K16 に当たらない（3つの写しで同じ）。"""
        t = sc.board(_template(), date.today())
        for snip in sc.NO_CUT + sc.CUT_LIMIT:
            with self.subTest(snippet=snip):
                p = sc.page(t, snip)
                self.assertIsNone(be._swallow_open(p))
                self.assertIsNone(dw._swallow_open(p))
                self.assertIsNone(gd._swallow_open(p))

    def test_nothing_lost(self):
        """後ろに項目・見出し・行の部品・Deck の要素が無ければ、閉じていなくても当てない（画面から消えるものが無い）。"""
        for t in ("<p>a</p>\n<textarea>\n", "<p>a</p><script>x", "<textarea>\n<p>b</p>", "<p>a</p><!-- x\n<footer>f</footer>",
                  '<script>a<script src="board.js"></script><p>b</p><script src="board.js"></script>', "<!-- a -->\n<!-- b -->",
                  "<template><p>x</p></template>"):
            with self.subTest(text=t):
                self.assertIsNone(be._swallow_open(t))
        # 自分の --> で閉じるコメントの中の行は、書き手が隠したもの（テンプレートの記入例のコメントなど）なので当てない
        self.assertIsNone(be._swallow_open('<!-- <div class="item">x</div> -->\n<div class="item">y</div>'))

    def test_lost_kinds(self):
        """消える要素があれば、どの形でも当てる。種類と名前は (位置, 種類, 名前) の後ろ2つ。"""
        row = '<div class="item"><p class="task-title">b</p></div>'
        for t, want in (("<textarea>\n" + row, ("element", "textarea")),
                        ("<textarea>a</textarea>" + row, None),
                        ("<textarea><div class='item'>x</div></textarea>", ("element", "textarea")),
                        ("<plaintext>\n" + row, ("element", "plaintext")),
                        ("<!-- x\n" + row + "<!-- y -->", ("comment", "")),
                        ("<!-- x\n" + row, ("comment", "")),
                        ("<!x\n" + row, ("comment", "")),
                        ("<svg><![CDATA[x\n" + row, ("cdata", "")),
                        ('<span title="x\n' + row + '"', ("tag", "span")),
                        ("<template>\n" + row, ("element", "template")),
                        ("<template>" + row + "</template>", ("element", "template")),
                        ("<script>\n" + row + '<script src="board.js"></script>', ("load", "script")),
                        ("<script>\n" + row + '<script src="x.js"></script>', ("element", "script"))):
            with self.subTest(text=t):
                hit = be._swallow_open(t)
                self.assertEqual(hit and hit[1:], want)
        # Deck の要素（DECK 領域の中の開きタグ）が消えるときも当てる
        t = "a\n<textarea>\n" + be.MARKER_START + '<span id="deck-key"></span>' + be.MARKER_END
        self.assertEqual(be._swallow_open(t)[1:], ("element", "textarea"))
        self.assertIsNone(be._swallow_open("a\n<textarea>\n" + be.MARKER_START + be.MARKER_END))

    def test_board_js_not_run(self):
        """画面から消える要素が無くても、実行されるはずの board.js の <script>（_sw_runs）が実行されない形は "load" で当てる（2026-11-10 ユーザー決定）。
        実行される board.js の <script> が別にあれば当てない。属性で実行されないもの（type が JavaScript でない・nomodule）は、実行されるはずのものに数えない。"""
        for t, want in (('<p>a</p><script src="board.js">', ("load", "script")),
                        ('<p>a</p><script src="board.js">x', ("load", "script")),
                        ('<script src="board.js"></script>', None),
                        ('<script src="board.js" async></script>', None),
                        ('<script src="board.js" type=" TEXT/JavaScript "></script>', None),
                        ('<template><script src="board.js"></script></template>', ("load", "script")),
                        ('<svg><script src="board.js"></script></svg>', ("load", "script")),
                        ('<svg><foreignObject><script src="board.js"></script></foreignObject></svg>', None),
                        ('<!-- <script src="board.js"></script> -->', ("load", "")),
                        ('<textarea><script src="board.js"></script></textarea>', ("load", "textarea")),
                        ('<script>a<script src="board.js"></script>', ("load", "script")),
                        ('<script>a<script src="board.js"></script><script src="board.js"></script>', None),
                        # 属性で実行されない board.js だけの板も当てる（候補は src が board.js を指す <script> すべて・2026-11-10 ユーザー決定）
                        ('<script src="board.js" type="text/plain"></script>', ("load", "script")),
                        ('<script src="board.js" nomodule></script>', ("load", "script")),
                        ('<script src="board.js" type="module"></script>', ("load", "script")),
                        ('<script src="board.js" type="text/javascript; charset=utf-8"></script>', ("load", "script")),
                        ('<script src="board.js" language="vbscript"></script>', ("load", "script")),
                        ('<script src="board.js" language="javascript"></script>', None),
                        ('<script src="board.js" type="" language="vbscript"></script>', None),
                        ('<script src="x.js" src="board.js"></script>', ("load", "script")),
                        ('<script src="board.js" src="x.js"></script>', None),
                        ('<script src="board.js" type="text/plain"></script><script src="board.js"></script>', None),
                        ("<div title=\"<script src='board.js'></script>\"></div>", ("load", "div")),
                        # > の無いまま文書が終わる閉じタグでは、要素は閉じない
                        ('<script src="board.js"></script', ("load", "script")),
                        ('<p>a</p>', None)):
            with self.subTest(text=t):
                hit = be._swallow_open(t)
                self.assertEqual(hit and hit[1:], want)
                self.assertEqual(dw._swallow_open(t), hit)
                self.assertEqual(gd._swallow_open(t), hit)

    def test_end_tag_without_gt_at_end(self):
        """> の無いまま文書が終わる閉じタグ（</textarea・</script）では要素は閉じない（閉じたと読むと、後ろの判定を誤る）。"""
        self.assertIsNone(be._sw_text_end("<textarea>x</textarea", 10, "textarea"))
        self.assertIsNone(be._sw_text_end("<script>x</script", 8, "script"))
        self.assertEqual(be._sw_text_end("<textarea>x</textarea>", 10, "textarea"), (22, False))
        t = '<textarea>\n<div class="item">x</div></textarea'
        self.assertEqual(be._swallow_open(t)[1:], ("element", "textarea"))

    def test_unclosed_script_in_board_is_load(self):
        """末尾で board.js を読む板では、閉じていない <script> は板の終わりの board.js の </script> で閉じ、項目と Deck の要素を消す＝"load"。"""
        t = sc.page(sc.board(_template(), date.today()), "<script>")
        hit = be._swallow_open(t)
        self.assertEqual(hit[1:], ("load", "script"))
        self.assertEqual(t.count("\n", 0, hit[0]), t.count("\n", 0, t.index('<p class="task-note"')))
        msg = [e["message"] for e in be.structure_errors(t) if e["code"] == "K16"][0]
        self.assertIn("ボードのスクリプト（board.js）の読み込みが実行されないので", msg)

    def test_k16_messages(self):
        """K16 の知らせの文を逐語で見る（board.js が動かない "load"／板の要素が消えて board.js は動く／板の要素が消えて board.js が動くか分からない、の3通り）。
        board_edit.py と guard.py の structure_errors が同じ文を返すことも見る。"""
        tmpl = _template()
        load = sc.page(sc.board(tmpl, date.today()), "<script>")
        ran = sc.page(sc.board(tmpl, date.today(), tail=False), "<textarea>")
        not_ran = sc.page(sc.board(tmpl, date.today()), "<textarea>")
        for t, kind, want in (
                (load, "load",
                 "ボードのスクリプトの読み込み（<script src=\"board.js\">）を実行させない <script>（31 行目）があります。"
                 "ボードのスクリプト（board.js）の読み込みが実行されないので、"
                 "ポップアップの通知・「ボードの点検」・「書き込み停止中」の知らせも画面に出ません。"),
                (ran, "element",
                 "後ろの行を文字として読む <textarea>（32 行目）があります。"
                 "ブラウザはそこに入る行・見出し・Deck の欄を要素として読まないので、それらが画面から消えます"
                 "（ボードのスクリプトは動くので、ふつうは画面の「ボードの点検」にも出ます）。"),
                (not_ran, "element",
                 "後ろの行を文字として読む <textarea>（31 行目）があります。"
                 "ブラウザはそこに入る行・見出し・Deck の欄を要素として読まないので、それらが画面から消えます。"
                 "ボードのスクリプト（board.js）を末尾で読む板では、その読み込みも飲み込まれてボードのスクリプトが動かないことがあり、"
                 "そのときはポップアップの通知・「ボードの点検」・「書き込み停止中」の知らせも画面に出ません。")):
            with self.subTest(kind=kind, want=want[:20]):
                self.assertEqual(be._swallow_open(t)[1], kind)
                msgs = [e["message"] for e in be.structure_errors(t) if e["code"] == "K16"]
                self.assertEqual(len(msgs), 1)
                self.assertIn(want, msgs)
                self.assertEqual([e["message"] for e in gd.structure_errors(t) if e["code"] == "K16"], msgs)

    def test_first_hit(self):
        """消える要素のある最初の形を返す（前の形が消すものが無ければ、後ろの形）。"""
        t = '<p>x<script>a<script src=board.js></script>\n\n<textarea>\n<div class="item">y</div>'
        hit = be._swallow_open(t)
        self.assertEqual(hit[1:], ("element", "textarea"))
        self.assertEqual(t.count("\n", 0, hit[0]) + 1, 3)
        self.assertEqual(dw._swallow_open(t), hit)
        self.assertEqual(gd._swallow_open(t), hit)

    def test_large_boards_not_slow(self):
        """約 2MB の板でも 2 秒未満（コメントごとに --> や --!> を文書の終わりまで探し直さず、開いていない要素の閉じタグで
        要素の並びを辿り直さない。修正前は、コメントだけの 2MB で 59 秒・--!> で閉じるコメントの 2MB で 72 秒・240KB で 14 秒・180KB で 28 秒の形があった）。"""
        import time
        n = 2000000

        def rep(s, tail=""):
            return (s * (n // len(s)))[:n - len(tail)] + tail
        boards = {"コメント": rep("<!-- a -->\n"), "--!> で閉じるコメント": rep("<!--a--!>", "-->"),
                  "開いていない閉じタグ": rep("<p>x</span>\n"),
                  "foreignObject の中の閉じタグ": "<span><svg><foreignObject>" + rep("<p>x</span>\n"),
                  "svg の中の開いていない閉じタグ": "<svg>" + rep("<g>x</h>\n"),
                  "入れ子の svg": "<svg>" + rep("<foreignObject><svg><g>x</h>\n"),
                  "深い g": "<svg>" + rep("<g>"), "属性の引用符": rep("<a b='x' c=\"y\" d=e>"),
                  "> の無いタグ": rep("<a b ", ">"), "script の中の board.js の文字": "<script>" + rep("<script src=board.js>", "</script>"),
                  # template の入れ子（修正前は 400KB で 79 秒・880KB で 87 秒）と、template を挟んだ外の閉じタグ
                  "template の入れ子": rep("<template>"), "template の入れ子を閉じる": "<template>" * 100000 + "</template>" * 100000,
                  "template の外の閉じタグ": "<div>" + "<template><span>" * 80000 + "</div>" * 80000}
        for name, t in boards.items():
            with self.subTest(board=name):
                t0 = time.process_time()   # 同時に動くブラウザの試験に左右されないよう、この処理の CPU 時間で測る
                be._swallow_open(t)
                self.assertLess(time.process_time() - t0, 2)

    def test_text(self):
        t = "a\n<!-- DECK:AUTO:START -->\n<textarea>\n<span id=\"deck-key\"></span><!-- DECK:AUTO:END -->\n"
        self.assertEqual(be.swallow_text(t, be._swallow_open(t)), "後ろの行を文字として読む <textarea>（3 行目・DECK 領域の中）")
        # 名前の無い "load" は、CDATA の中とコメント・宣言とで文を分ける
        for t, want in (('<svg><![CDATA[<script src="board.js"></script>]]></svg>', "svg・math の中の <![CDATA["),
                        ('<!-- <script src="board.js"></script> -->', "HTML のコメントか宣言")):
            hit = be._swallow_open(t)
            self.assertEqual(hit[1], "load")
            self.assertIn(want, be.swallow_text(t, hit))
            self.assertEqual(dw.swallow_text(t, hit), be.swallow_text(t, hit))
        t = 'a\n<plaintext>\n<p class="item">b\n'
        self.assertEqual(be.swallow_text(t, be._swallow_open(t)), "<plaintext>（閉じタグを持たない要素。後ろをすべて文字として読む）（2 行目）")
        t = 'a\n<div class="x\n<p class="item">b\n'
        self.assertIn("後ろの行を取り込むタグ <div（> が無いか", be.swallow_text(t, be._swallow_open(t)))


class TestK16BoardEdit(tbe.Sandbox):
    def status(self):
        rc, out = self.ed("status")
        self.assertEqual(rc, 0)
        return out

    def insert(self, snippet):
        t = self.text()
        self.assertIn(AFTER, t)
        self.write(t.replace(AFTER, AFTER + snippet + "\n", 1))

    def test_status_and_refuse(self):
        self.create()
        self.insert("<textarea>")
        st = self.status()
        k16 = [e for e in st["errors"] if e["code"] == "K16"]
        self.assertEqual(len(k16), 1, st["errors"])
        self.assertIn("後ろの行を文字として読む <textarea>", k16[0]["message"])
        self.assertIn("「ボードの点検」", k16[0]["message"])
        before = self.read()
        rc, out = self.ed("add", "--section", "今日中", "--title", "x")
        self.assertEqual(rc, 1)
        self.assertIn("restore", out["error"])
        self.assertIn("K16", [c["code"] for c in out["checks"]])
        self.assertEqual(self.read(), before)

    def test_closed_or_foreign_not_k16(self):
        self.create()
        self.insert("<textarea>a</textarea><svg><style>x</style></svg>")
        self.assertEqual([e for e in self.status()["errors"] if e["code"] == "K16"], [])

    def test_restore_skips_k16_versions(self):
        self.create()
        good = self.read()
        iso = date.today().isoformat()
        h = os.path.join(self.dir, "history")
        os.makedirs(h, exist_ok=True)
        broken = good.decode("utf-8").replace(AFTER, AFTER + "<script>\n", 1)
        with open(os.path.join(h, "board-%s-lastgood-120000.html" % iso), "wb") as f:
            f.write(broken.encode("utf-8"))
        with open(os.path.join(h, "board-%s-lastgood-110000.html" % iso), "wb") as f:
            f.write(good)
        st = self.status()
        self.assertEqual(st["restorable_today"], ["history/board-%s-lastgood-110000.html" % iso])
        rc, out = self.ed("restore", "--from", "history/board-%s-lastgood-120000.html" % iso, "--confirmed")
        self.assertEqual(rc, 1)
        self.assertIn("K16", [c["code"] for c in out["checks"]])
        self.assertEqual(self.read(), good)
        # いまの板に K16 があっても、形の正しい版へは戻せる
        self.write(broken)
        rc, out = self.ed("restore", "--from", "history/board-%s-lastgood-110000.html" % iso, "--confirmed")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status()["errors"], [])

    def test_k17_board_js_removed(self):
        """書く前の板にあった、実行される board.js の読み込みが、出来上がりで無いか実行されないなら K17 で書かない（2026-11-10 ユーザー決定）。
        板に board.js の読み込みがまるごと無いこと自体は K16 にしない（小さい板）。"""
        self.create()
        old = self.text()
        self.assertTrue(be._sw_scan(old)[1])
        codes = [e["code"] for e in be.run_checks("add", old, old.replace('<script src="board.js" defer></script>', ""), None)]
        self.assertIn("K17", codes)
        self.assertNotIn("K16", codes)
        # 属性で実行されない形へ変えた出来上がりは、K16（board.js が止まる形）で断る（K17 は重ねない）
        codes = [e["code"] for e in be.run_checks("add", old, old.replace('<script src="board.js" defer></script>',
                                                                       '<script src="board.js" type="text/plain"></script>'), None)]
        self.assertIn("K16", codes)
        self.assertNotIn("K17", codes)
        self.assertNotIn("K17", [e["code"] for e in be.run_checks("add", old, old, None)])
        tiny = "<p>a</p>"
        self.assertEqual(be.structure_errors(tiny) and [e for e in be.structure_errors(tiny) if e["code"] in ("K16", "K17")], [])

    def test_k15_not_on_k16_item(self):
        """時刻の欄の中で閉じていない textarea の行は K16 で知らせ、K15 には入れない（J-6）。ほかの行の K15 は残る。"""
        self.create()
        rows = ['<div class="item"><span class="time">9:00 <textarea>x</div><p class="task-title">中の textarea</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div>']
        self.insert(rows[0])
        st = self.status()
        self.assertIn("K16", [e["code"] for e in st["errors"]])
        self.assertFalse([w for w in st["warnings"] if w["code"] == "K15" and "中の textarea" in w["message"]])


class TestK16Deck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-swallow-test-")
        self.board = os.path.join(self.dir, "board.html")
        self.log_path = os.path.join(self.dir, "watcher.log")
        self._log = dw.LOG_PATH
        dw.LOG_PATH = self.log_path
        dw._lastgood.clear()
        p = os.path.join(self.dir, "spec.json")
        import json
        with open(p, "w", encoding="utf-8") as f:
            json.dump(tbe.SPEC, f, ensure_ascii=False)
        rc, out = tbe.run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 0, out)
        with open(self.board, "rb") as f:
            self.good = f.read()

    def tearDown(self):
        dw.LOG_PATH = self._log
        dw._lastgood.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def broken(self, snip="<textarea>"):
        return self.good.decode("utf-8").replace(AFTER, AFTER + snip + "\n", 1)

    def test_lastgood_saved_and_logged(self):
        text = self.good.decode("utf-8")
        self.assertIsNone(dw.track_structure(self.board, self.good, text))
        b = self.broken()
        rel = dw.track_structure(self.board, b.encode("utf-8"), b)
        self.assertTrue(rel and rel.startswith("history/"), rel)
        with open(os.path.join(self.dir, rel), "rb") as f:
            self.assertEqual(f.read(), self.good)
        with open(self.log_path, encoding="utf-8") as f:
            log = f.read()
        self.assertIn("後ろの行を文字として読む <textarea>", log)
        self.assertIn("画面から消えます（board.js は動き、ふつうは画面の「ボードの点検」に出ます）", log)
        self.assertEqual(dw.board_broken_reason(text), None)

    def test_lastgood_when_board_js_removed(self):
        """持っていた正しい版で実行される board.js の読み込みが、今の板で無くなったら、崩れとして退避する（v2.17）。"""
        text = self.good.decode("utf-8")
        self.assertIsNone(dw.track_structure(self.board, self.good, text))
        b = text.replace('<script src="board.js" defer></script>', "")
        rel = dw.track_structure(self.board, b.encode("utf-8"), b)
        self.assertTrue(rel and rel.startswith("history/"), rel)
        with open(self.log_path, encoding="utf-8") as f:
            self.assertIn("board.js の読み込み", f.read())

    def test_rollover_refused(self):
        b = self.broken("<style>")
        yesterday = date.today() - timedelta(days=1)
        b = b.replace(be.fmt_full_date(date.today()), be.fmt_full_date(yesterday))
        with self.assertRaises(dw.RolloverError) as cm:
            dw.roll_board_text(b, date.today(), "0:05")
        self.assertIn("後ろの行を文字として読む <style>", str(cm.exception))
        ok = self.good.decode("utf-8").replace(be.fmt_full_date(date.today()), be.fmt_full_date(yesterday))
        dw.roll_board_text(ok, date.today(), "0:05")     # 崩れの無い板は作れる


class TestK16Guard(unittest.TestCase):
    def test_shape_codes(self):
        with open(os.path.join(tbe.ROOT, "skill", "assets", "board-template.html"), encoding="utf-8") as f:
            tpl = f.read()
        t = tpl.replace("  <!-- DECK:AUTO:START -->", "<textarea>\n  <!-- DECK:AUTO:START --><span id=\"deck-key\"></span>", 1)
        self.assertIn("K16", gd.shape_codes(t))
        self.assertNotIn("K16", gd.shape_codes(tpl))
        self.assertIn("K16", gd.describe(None)[1])
        self.assertIn("K17", gd.describe(None)[1])
        t2 = tpl.replace('<script src="board.js" defer></script>', "")
        self.assertEqual(gd.shape_codes(t2) & {"K16", "K17"}, {"K17"})


if __name__ == "__main__":
    unittest.main()
