# -*- coding: utf-8 -*-
"""board.js と Deck の設定の送受信の試験（実ブラウザ・ヘッドレス）。

通知音の設定（ON/OFF・音種）は Deck だけが持つ。読み込みでは読むだけで、送るのは⚙を操作したときだけ。
✎ の時刻の上書きは、ブラウザに今日の記録があれば起動時にも送る。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
DOM を出せる Chrome も Edge も見つからなければ飛ばす。Chrome があれば Chrome で走る。別のブラウザで走らせるときは、環境変数 TB_TEST_BROWSER に
実行ファイルのパスを入れる（指したものが動かないときは飛ばさずに落ちる。Edge は Application フォルダの中の版のフォルダにある msedge.exe を指す）。
すべて一時フォルダで行い、Deck の受信は 18737 以降の臨時のポートだけを使う
（板の接続情報もそのポートを指すので、本番の 8737〜8746 へは送らない）。プロファイルも一時フォルダに作る。
"""

import datetime
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
import pathlib
import re

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "skill", "assets")

_DECK_COPY_DIR = tempfile.mkdtemp(prefix="tb-browser-test-mod-")
shutil.copyfile(os.path.join(ROOT, "deck", "deck_watcher.py"), os.path.join(_DECK_COPY_DIR, "deck_watcher.py"))
_spec = importlib.util.spec_from_file_location("deck_watcher_tb", os.path.join(_DECK_COPY_DIR, "deck_watcher.py"))
dw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dw)


def edge_candidates(app):
    """Edge の候補。版のフォルダの msedge.exe を新しい順に先に試し、最後に Application 直下。"""
    versions = []
    try:
        for name in os.listdir(app):
            if re.fullmatch(r"\d+(\.\d+)+", name):
                versions.append(name)
    except OSError:
        pass
    versions.sort(key=lambda v: [int(x) for x in v.split(".")], reverse=True)
    return [os.path.join(app, v, "msedge.exe") for v in versions] + [os.path.join(app, "msedge.exe")]


def dumps_dom(exe):
    """そのブラウザが --dump-dom で DOM を出せるか（Edge の Application 直下の msedge.exe は何も出さずに戻る）。"""
    d = tempfile.mkdtemp(prefix="tb-browser-probe-")
    try:
        probe = os.path.join(d, "probe.html")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("<!doctype html><title>probe</title>")
        r = subprocess.run([exe, "--headless=new", "--user-data-dir=" + os.path.join(d, "profile"), "--no-first-run",
                            "--no-default-browser-check", "--disable-extensions", "--dump-dom",
                            pathlib.Path(probe).as_uri()], capture_output=True, timeout=60)
        return b"</html>" in r.stdout
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(d, ignore_errors=True)


def find_browser():
    forced = os.environ.get("TB_TEST_BROWSER")
    if forced:
        return forced               # 無いパスなら試験は飛ばずに落ちる（別のブラウザで走ったと見誤らないように）
    candidates = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
    candidates += edge_candidates(r"C:\Program Files (x86)\Microsoft\Edge\Application")
    candidates += edge_candidates(r"C:\Program Files\Microsoft\Edge\Application")
    candidates += [p for p in (shutil.which("google-chrome"), shutil.which("chromium")) if p]
    for p in candidates:
        if os.path.exists(p) and dumps_dom(p):
            return p
    return None


BROWSER = find_browser()
TOKEN = "t-" + "0123456789" * 3
KEY = "23:59|試験"
PLAYED = []   # 試聴の記録（実際には鳴らさない）
POSTS = []    # Deck が受けた POST の経路
NO_DECK = "Deck から設定を読めないため"
NOT_TODAY = "今日のボードではないため"
FAILED = "Deck に届かなかった可能性があります"
NEW_DESC = "通知音の設定は Deck に保存され、どのブラウザで開いても同じです（Deck が動いていないときは変更できません）。それ以外の設定はこのブラウザに保存されます。"
OLD_DESC = "設定はこのブラウザに保存されます。"


def _fake_play(sound_type):
    PLAYED.append(sound_type)
    return True


dw.play_sound_async = _fake_play
_orig_post = dw._BoardMoveHandler.do_POST


def _record_post(handler):
    POSTS.append(urllib.parse.urlsplit(handler.path).path)
    _orig_post(handler)


dw._BoardMoveHandler.do_POST = _record_post


def click(selector, ms=800):
    return ("<script>setTimeout(function(){document.querySelector(\"%s\").click();},%d);</script>" % (selector, ms))


# 別のブラウザが Deck の設定を変える（ページの表示は変わらない）
def other_browser_sets(enabled, stype, ms=600):
    return ("<script>setTimeout(function(){var k=document.getElementById('deck-key');"
            "var u='http://127.0.0.1:'+k.dataset.port+'/sound/config?board='+"
            "encodeURIComponent(location.href.split('#')[0])+'&k='+k.dataset.k;"
            "fetch(u,{method:'POST',body:JSON.stringify({enabled:%s,type:'%s',test:false})});},%d);</script>"
            % ("true" if enabled else "false", stype, ms))


def tearDownModule():
    dw._BoardMoveHandler.do_POST = _orig_post
    shutil.rmtree(_DECK_COPY_DIR, ignore_errors=True)


@unittest.skipUnless(BROWSER, "DOM を出せる Chrome / Edge が見つからない")
class BrowserCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-browser-test-")
        dw.LOG_PATH = os.path.join(self.dir, "watcher.log")
        self.board = os.path.join(self.dir, "board.html")
        self.sound = os.path.join(self.dir, "sound.json")
        self.profile = os.path.join(self.dir, "profile")
        self.server = None
        self.port = None
        del PLAYED[:]
        del POSTS[:]
        for f in ("board.js", "board.css", "cat.png"):
            shutil.copy2(os.path.join(ASSETS, f), self.dir)

    def tearDown(self):
        self.stop_deck()
        shutil.rmtree(self.dir, ignore_errors=True)

    # ---- 道具
    def free_port(self):
        for cand in range(18737, 18837):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", cand))
                return cand
            except OSError:
                continue
            finally:
                s.close()
        self.fail("臨時のポートを取れない")

    def start_deck(self, enabled=True, stype="chime", ovr=None):
        today = datetime.date.today().strftime("%Y-%m-%d")
        with open(self.sound, "w", encoding="utf-8") as f:
            json.dump({"enabled": enabled, "type": stype, "ovr_date": today,
                       "ovr": {KEY: "23:30"} if ovr is None else ovr}, f, ensure_ascii=False)
        self.port = self.free_port()
        self.server = dw.start_move_server(self.board, dw.SoundStore(self.sound), port=self.port, token=TOKEN)
        self.assertIsNotNone(self.server)

    def stop_deck(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def sound_bytes(self):
        with open(self.sound, "rb") as f:
            return f.read()

    def state(self):
        with open(self.sound, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("enabled"), d.get("type"), d.get("ovr")

    def write_board(self, port=None, extra="", date=None, key=True):
        today = datetime.date.today()
        port = self.port if port is None else port
        date = today.strftime("%Y-%m-%d") if date is None else date
        deck_key = '<span id="deck-key" hidden data-port="%d" data-k="%s"></span>' % (port, TOKEN) if key else ""
        html = ('<!doctype html><meta charset="utf-8"><title>%d/%d 試験</title><link rel="stylesheet" href="board.css">'
                '<div class="board"><header><h1>きょうのボード</h1><span class="date">%s</span></header>'
                '<div class="updated"><span id="upd-time">00:00</span><button id="settings-btn"></button></div>'
                '<div id="settings-panel" hidden><button id="popup-toggle"></button><button id="sound-toggle"></button>'
                '<button data-sound="std"></button><button data-sound="chime"></button>'
                '<button data-sound="pip"></button><button data-sound="bell"></button><button id="sound-test"></button></div>'
                '<div class="progress"><span>0 / 1 完了</span></div>'
                '<div class="section-label">今日の予定</div>'
                '<div class="item"><div class="time">23:59</div><div><p class="task-title">試験</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div></div>'
                '<!-- DECK:AUTO:START -->%s<!-- DECK:AUTO:END -->'
                '<footer></footer></div><div id="toast-area"></div><script src="board.js"></script>%s'
                % (today.month, today.day, date, deck_key, extra))
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(html)

    def write_real_board(self, old_desc=False, extra=""):
        """実物の board-template.html から今日の板を作る（発行済みの古い説明文の板も作れる）。"""
        today = datetime.date.today()
        with open(os.path.join(ASSETS, "board-template.html"), encoding="utf-8") as f:
            t = f.read()
        self.assertIn(NEW_DESC, t)
        if old_desc:
            t = t.replace(NEW_DESC, OLD_DESC)
        for k, v in {"{{TITLE_DATE}}": "%d/%d" % (today.month, today.day), "{{FULL_DATE}}": today.strftime("%Y-%m-%d"),
                     "{{UPDATED_AT}}": "00:00", "{{DONE}}": "0", "{{TOTAL}}": "1", "{{PERCENT}}": "0"}.items():
            t = t.replace(k, v)
        t = re.sub(r"<!-- \{\{SECTIONS\}\}.*?-->", '<div class="section-label">今日の予定</div>', t, flags=re.S)
        t = t.replace("<!-- DECK:AUTO:START -->", '<!-- DECK:AUTO:START --><span id="deck-key" hidden data-port="%d" data-k="%s"></span>'
                      % (self.port, TOKEN))
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t + extra)

    def open_page(self, path, budget=2500):
        """プロファイルを保ったままページを開き、読み込み後の DOM を返す。
        ブラウザが起動しない・board.js が動かないと、ここで落とす（何も起きないことを確かめる試験が素通りしないように）。"""
        r = subprocess.run([BROWSER, "--headless=new", "--user-data-dir=" + self.profile, "--no-first-run",
                            "--no-default-browser-check", "--disable-extensions", "--disable-sync",
                            "--disable-background-networking", "--disable-component-update",
                            "--virtual-time-budget=%d" % budget, "--dump-dom", pathlib.Path(path).as_uri()],
                           capture_output=True, timeout=90)
        dom = r.stdout.decode("utf-8", "replace")
        self.assertIn("</html>", dom, "ブラウザが DOM を返さない: rc=%s" % r.returncode)
        if path == self.board:
            self.assertIn(self.toggle_text(dom), ("ON", "OFF", "—"), "board.js が動いていない")
        return dom

    def seed(self, values):
        """board.html と同じ file: の localStorage へ値を入れる（ふだんのプロファイル相当）。"""
        p = os.path.join(self.dir, "seed.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write("<script>var v=%s;for(var k in v)localStorage.setItem(k,v[k]);"
                    "document.title='seeded '+Object.keys(v).length;</script>" % json.dumps(values))
        self.assertIn("seeded", self.open_page(p))

    def toggle_text(self, dom):
        m = re.search(r'id="sound-toggle"[^>]*>([^<]*)<', dom)
        return m.group(1) if m else None

    def active_type(self, dom):
        m = re.search(r'<button[^>]*data-sound="(\w+)"[^>]*class="[^"]*active|<button[^>]*class="[^"]*active[^"]*"[^>]*data-sound="(\w+)"', dom)
        return (m.group(1) or m.group(2)) if m else None

    def operable(self, dom):
        """通知音の3種のボタンがそろって押せるか。そろっていなければ試験を落とす。"""
        tags = re.findall(r'<button[^>]*(?:id="sound-toggle"|id="sound-test"|data-sound="\w+")[^>]*>', dom)
        self.assertEqual(len(tags), 6)
        flags = set("disabled" in t for t in tags)
        self.assertEqual(len(flags), 1, tags)
        return flags == {False}

    def note(self, dom):
        m = re.search(r'<div id="sound-note"[^>]*>(.*?)</div>', dom)
        self.assertIsNotNone(m, "知らせの要素が無い")
        tag = re.search(r'<div id="sound-note"[^>]*>', dom).group(0)
        return "" if "hidden" in tag else m.group(1)

    def sound_posts(self):
        return POSTS.count("/sound/config")

    def fail_get_after(self, n):
        """GET /sound/config を、最初の n 回だけ通して以後は 500 にする。"""
        orig = dw._BoardMoveHandler.do_GET
        count = [0]

        def do_get(handler):
            if handler.path.startswith("/sound/config"):
                count[0] += 1
                if count[0] > n:
                    handler._send(500, b'{"ok": false}')
                    return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def fail_get_first(self, n):
        """GET /sound/config を、最初の n 回だけ 500 にする（応答が戻る場合）。"""
        orig = dw._BoardMoveHandler.do_GET
        count = [0]

        def do_get(handler):
            if handler.path.startswith("/sound/config"):
                count[0] += 1
                if count[0] <= n:
                    handler._send(500, b'{"ok": false}')
                    return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def fail_notifications_after(self, n):
        """GET /notifications を、最初の n 回だけ通して以後は 500 にする（開いた後に Deck が応答しなくなる場合）。"""
        orig = dw._BoardMoveHandler.do_GET
        count = [0]

        def do_get(handler):
            if handler.path.startswith("/notifications"):
                count[0] += 1
                if count[0] > n:
                    handler._send(500, b'{"ok": false}')
                    return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def reply_get_sound(self, body):
        """GET /sound/config の応答を置き換える（形が崩れた場合）。"""
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/sound/config"):
                handler._send(200, body)
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def reply_post_sound(self, code, body):
        """POST /sound/config に保存せずこの応答を返す。"""
        orig = dw._BoardMoveHandler.do_POST

        def do_post(handler):
            if handler.path.startswith("/sound/config"):
                POSTS.append("/sound/config")
                length = int(handler.headers.get("Content-Length") or 0)
                handler.rfile.read(length)
                handler._send(code, body)
                return
            orig(handler)

        dw._BoardMoveHandler.do_POST = do_post
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_POST", orig)

    def fail_post_sound(self):
        self.reply_post_sound(500, b'{"ok": false}')

    def save_then_fail_post_sound(self):
        """Deck は保存したのに、応答が失敗に見える場合。"""
        orig = dw._BoardMoveHandler.do_POST
        send = dw._BoardMoveHandler._send

        def do_post(handler):
            if handler.path.startswith("/sound/config"):
                handler._send = lambda code, body=b"", *a, **k: send(handler, 500, b'{"ok": false}')
            orig(handler)

        dw._BoardMoveHandler.do_POST = do_post
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_POST", orig)


class TestSoundOpenOnly(BrowserCase):
    """開くだけでは送らない"""

    def assert_open_sends_nothing(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board()
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.toggle_text(dom), "ON")
        self.assertEqual(self.active_type(dom), "chime")
        self.assertTrue(self.operable(dom))
        self.assertEqual(self.note(dom), "")
        return dom

    def test_empty_storage(self):
        self.assert_open_sends_nothing()

    def test_old_values_are_not_sent_and_are_removed(self):
        self.seed({"tb:sound": "0", "tb:soundType": "bell", "tb:soundFromDeck": "0"})
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra="<script>document.documentElement.setAttribute('data-test','keys='+[localStorage.getItem('tb:sound'),"
                               "localStorage.getItem('tb:soundType'),localStorage.getItem('tb:soundFromDeck')].join());</script>")
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.toggle_text(dom), "ON")
        self.assertEqual(self.active_type(dom), "chime")
        self.assertIn('data-test="keys=,,"', dom)

    def test_type_only_old_value(self):
        self.seed({"tb:soundType": "bell"})
        self.assert_open_sends_nothing()

    def test_sound_only_old_value(self):
        self.seed({"tb:sound": "0"})
        self.assert_open_sends_nothing()

    def test_other_settings_stay_in_browser(self):
        self.seed({"tb:popup": "0"})
        self.start_deck()
        self.write_board(extra="<script>document.documentElement.setAttribute('data-test','popup='+localStorage.getItem('tb:popup'));</script>")
        self.assertIn('data-test="popup=0"', self.open_page(self.board))

    def test_values_made_on_another_board_do_not_reach(self):
        self.start_deck(enabled=False, stype="std")
        self.write_board(extra=click("#sound-toggle"))
        self.open_page(self.board)
        self.assertEqual(self.state()[:2], (True, "std"))
        self.stop_deck()
        # 同じプロファイルで別のフォルダのボード（本番相当）を開く
        d2 = os.path.join(self.dir, "other")
        os.makedirs(d2)
        for f in ("board.js", "board.css", "cat.png"):
            shutil.copy2(os.path.join(ASSETS, f), d2)
        self.board = os.path.join(d2, "board.html")
        self.sound = os.path.join(d2, "sound.json")
        del POSTS[:]
        self.start_deck(enabled=False, stype="chime")
        self.write_board()
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.toggle_text(dom), "OFF")


class TestSoundOperate(BrowserCase):
    """⚙の操作で1回だけ送る"""

    def test_toggle_sends_once_and_keeps_type(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle"))
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 1)
        self.assertEqual(self.state()[:2], (False, "chime"))
        self.assertEqual(self.toggle_text(dom), "OFF")
        self.assertEqual(PLAYED, [])
        # 読み込み直しても送らない
        del POSTS[:]
        self.write_board()
        self.assertEqual(self.toggle_text(self.open_page(self.board)), "OFF")
        self.assertEqual(self.sound_posts(), 0)

    def test_type_sends_once_and_keeps_enabled_and_previews(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("[data-sound=pip]"))
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 1)
        self.assertEqual(self.state()[:2], (True, "pip"))
        self.assertEqual(PLAYED, ["pip"])
        self.assertEqual(self.active_type(dom), "pip")

    def test_click_before_first_response_does_nothing(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra="<script>document.getElementById('sound-test').click();"
                               "document.querySelector('[data-sound=std]').click();"
                               "document.getElementById('sound-toggle').click();</script>")
        before = self.sound_bytes()
        self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)

    def test_double_click_sends_once(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra="<script>setTimeout(function(){var b=document.getElementById('sound-toggle');b.click();b.click();},800);</script>")
        self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 1)
        self.assertEqual(self.state()[:2], (False, "chime"))

    # 試聴
    def test_preview_keeps_settings(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-test"))
        dom = self.open_page(self.board)
        self.assertEqual(self.state()[:2], (True, "chime"))
        self.assertEqual(PLAYED, ["chime"])
        self.assertEqual(self.toggle_text(dom), "ON")

    def test_current_type_button_keeps_settings_and_previews(self):
        self.start_deck(enabled=False, stype="chime")
        self.write_board(extra=click("[data-sound=chime]"))
        self.open_page(self.board)
        self.assertEqual(self.state()[:2], (False, "chime"))
        self.assertEqual(PLAYED, ["chime"])

    # 別のブラウザの変更を上書きしない
    def test_preview_keeps_other_browser_change(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=other_browser_sets(False, "pip") + click("#sound-test", 1000))
        dom = self.open_page(self.board)
        self.assertEqual(self.state()[:2], (False, "pip"))
        self.assertEqual(PLAYED, ["pip"])
        self.assertEqual(self.toggle_text(dom), "OFF")
        self.assertEqual(self.active_type(dom), "pip")

    def test_type_keeps_other_browser_enabled(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=other_browser_sets(False, "pip") + click("[data-sound=bell]", 1000))
        self.open_page(self.board)
        self.assertEqual(self.state()[:2], (False, "bell"))

    def test_toggle_keeps_other_browser_type(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=other_browser_sets(True, "pip") + click("#sound-toggle", 1000))
        self.open_page(self.board)
        self.assertEqual(self.state()[:2], (False, "pip"))

    def test_toggle_to_value_already_set_elsewhere_does_not_send(self):
        # 見えている ON を OFF にする操作。別のブラウザが先に OFF にしていれば、ON に戻さず何も送らない
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=other_browser_sets(False, "chime") + click("#sound-toggle", 1000))
        dom = self.open_page(self.board)
        self.assertEqual(self.state()[:2], (False, "chime"))
        self.assertEqual(self.sound_posts(), 1)                 # 別のブラウザの1回だけ
        self.assertEqual(self.toggle_text(dom), "OFF")

    # 失敗
    def test_read_fails_at_operation_sends_nothing(self):
        self.fail_get_after(1)
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle"))
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.toggle_text(dom), "—")
        self.assertFalse(self.operable(dom))
        self.assertIn(NO_DECK, self.note(dom))

    def test_post_fails_keeps_display_and_tells(self):
        self.fail_post_sound()
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle"))
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.toggle_text(dom), "ON")
        self.assertIn(FAILED, self.note(dom))
        self.assertTrue(self.operable(dom))


class TestSoundReplies(BrowserCase):
    """応答の形・失敗の知らせ・読み直し"""

    def test_post_reply_without_fields_shows_sent_values(self):
        self.reply_post_sound(200, b'{"ok": true}')
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle"))
        dom = self.open_page(self.board)
        self.assertEqual(self.toggle_text(dom), "OFF")
        self.assertEqual(self.active_type(dom), "chime")
        self.assertEqual(self.note(dom), "")

    def test_post_reply_with_broken_fields_shows_sent_values(self):
        self.reply_post_sound(200, b'{"ok": true, "enabled": "x", "type": 1}')
        self.start_deck(enabled=False, stype="chime")
        self.write_board(extra=click("[data-sound=pip]"))
        dom = self.open_page(self.board)
        self.assertEqual(self.toggle_text(dom), "OFF")            # "x" を真として ON にしない
        self.assertEqual(self.active_type(dom), "pip")

    def test_post_reply_not_json_tells(self):
        self.reply_post_sound(200, b'not json')
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle"))
        self.assertIn(FAILED, self.note(self.open_page(self.board)))

    def test_get_reply_broken_is_unreadable(self):
        for body in (b'{"ok": true}', b'{"ok": true, "enabled": "x", "type": "std"}', b'{"ok": true, "enabled": true, "type": 1}', b"not json"):
            self.reply_get_sound(body)
            self.start_deck(enabled=True, stype="chime")
            self.write_board()
            dom = self.open_page(self.board)
            self.assertEqual(self.toggle_text(dom), "—", body)
            self.assertFalse(self.operable(dom), body)
            self.assertIn(NO_DECK, self.note(dom), body)
            self.stop_deck()

    def test_failure_rereads_and_keeps_notice(self):
        # 応答は失敗でも Deck は保存していた場合、読み直しで実際の値を映し、知らせは残す
        self.save_then_fail_post_sound()
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle"))
        dom = self.open_page(self.board)
        self.assertEqual(self.state()[:2], (False, "chime"))
        self.assertEqual(self.toggle_text(dom), "OFF")
        self.assertIn(FAILED, self.note(dom))

    def test_notice_cleared_by_later_read(self):
        self.fail_post_sound()
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle") + click("#settings-btn", 1400))
        self.assertEqual(self.note(self.open_page(self.board)), "")

    def test_opening_settings_rereads(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=other_browser_sets(False, "pip") + click("#settings-btn", 1000))
        dom = self.open_page(self.board)
        self.assertEqual(self.toggle_text(dom), "OFF")
        self.assertEqual(self.active_type(dom), "pip")

    def test_closing_settings_does_not_reread(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#settings-btn", 300) + other_browser_sets(False, "pip") + click("#settings-btn", 1000))
        self.assertEqual(self.toggle_text(self.open_page(self.board)), "ON")


class TestSettingsPanelOnRealTemplate(BrowserCase):
    """実物のテンプレートから作った板の⚙（順序の基準は docs/images/tb-dark-settings.png）"""

    ROWS = ["テーマ", "時刻トリガーのポップアップ通知", "ポップアップの消え方", "時刻トリガーの通知音", "通知音の種類",
            "強調色（重要タスク）", "× で隠したセッションの記録", "済タスクを隠す", "× で隠した済タスク", "セクション表示順"]

    def panel(self, dom):
        m = re.search(r'<div id="settings-panel".*?(?=<div class="progress">)', dom, re.S)
        self.assertIsNotNone(m)
        return m.group(0)

    def test_row_order_and_note_position(self):
        self.start_deck()
        self.write_real_board()
        p = self.panel(self.open_page(self.board))
        at = [p.index("<span>%s" % r) for r in self.ROWS]
        self.assertEqual(at, sorted(at), "行の順序が崩れた")
        desc = p.index('<div class="set-note">')
        self.assertGreater(desc, at[-1], "説明文が末尾にない")
        self.assertEqual(p.count('id="sound-note"'), 1)
        # #sound-note の直前は通知音の種類の行、直後は強調色の行
        note = p.index('<div id="sound-note"')
        self.assertLess(at[4], note)
        self.assertLess(note, at[5])
        self.assertTrue(re.search(r'id="sound-test"[^>]*>[^<]*</button></span></div><div id="sound-note"', p), "通知音の種類の行の直後にない")

    def test_notice_shows_between_rows_when_unreadable(self):
        self.port = self.free_port()
        self.write_real_board()
        p = self.panel(self.open_page(self.board))
        self.assertIn(NO_DECK, p)
        self.assertLess(p.index(NO_DECK), p.index("<span>強調色"))

    def test_old_description_is_rewritten_on_display(self):
        self.start_deck()
        self.write_real_board(old_desc=True)
        dom = self.open_page(self.board)
        self.assertEqual(dom.count(NEW_DESC), 1)
        self.assertEqual(dom.count("それ以外の設定は"), 1)
        with open(self.board, encoding="utf-8") as f:
            self.assertNotIn(NEW_DESC, f.read())                  # 正本は変えない

    def test_new_description_is_left_alone(self):
        self.start_deck()
        self.write_real_board()
        dom = self.open_page(self.board)
        self.assertEqual(dom.count(NEW_DESC), 1)
        self.assertEqual(dom.count("通知音の設定は Deck に保存され"), 1)


class TestSoundUnavailable(BrowserCase):
    """Deck が応答しないとき"""

    def test_deck_stops_after_page_opened(self):
        self.fail_notifications_after(1)
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle", 3800))
        before = self.sound_bytes()
        dom = self.open_page(self.board, budget=5000)
        self.assert_unavailable(dom)
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)

    def assert_unavailable(self, dom):
        self.assertEqual(self.toggle_text(dom), "—")
        self.assertIsNone(self.active_type(dom))
        self.assertFalse(self.operable(dom))
        self.assertIn(NO_DECK, self.note(dom))

    def test_deck_not_answering(self):
        self.write_board(port=self.free_port())
        self.assert_unavailable(self.open_page(self.board))

    def test_no_connection_info(self):
        self.write_board(key=False)
        self.assert_unavailable(self.open_page(self.board))

    def test_old_value_is_not_shown(self):
        self.seed({"tb:sound": "1", "tb:soundType": "bell"})
        self.write_board(port=self.free_port())
        self.assert_unavailable(self.open_page(self.board))

    def test_click_while_unavailable_does_nothing(self):
        self.write_board(port=self.free_port(), extra=click("#sound-toggle") + click("#sound-test", 900))
        self.assert_unavailable(self.open_page(self.board))

    def test_operable_after_response_returns(self):
        # 最初の読み込みが失敗しても、Deck の応答があれば読み直し、操作できるようになる
        self.fail_get_first(1)
        self.start_deck(enabled=True, stype="chime")
        self.write_board(extra=click("#sound-toggle", 3800))
        dom = self.open_page(self.board, budget=5000)
        self.assertEqual(self.sound_posts(), 1)
        self.assertEqual(self.state()[:2], (False, "chime"))
        self.assertEqual(self.toggle_text(dom), "OFF")
        self.assertEqual(self.note(dom), "")


class TestSoundNotToday(BrowserCase):
    """今日でない板"""

    def test_shows_deck_value_and_cannot_operate(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(date="2026-01-01（木）", extra=click("#sound-toggle") + click("#sound-test", 900))
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(PLAYED, [])
        self.assertEqual(self.toggle_text(dom), "ON")
        self.assertEqual(self.active_type(dom), "chime")
        self.assertFalse(self.operable(dom))
        self.assertIn(NOT_TODAY, self.note(dom))
        # 同じプロファイルで今日の板を開いても、何も届かない
        self.write_board()
        dom = self.open_page(self.board)
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.toggle_text(dom), "ON")

    def test_no_deck(self):
        self.write_board(port=self.free_port(), date="2026-01-01（木）")
        dom = self.open_page(self.board)
        self.assertEqual(self.toggle_text(dom), "—")
        self.assertFalse(self.operable(dom))
        self.assertIn(NOT_TODAY, self.note(dom))


class TestTimeOverrides(BrowserCase):
    """✎ の時刻の上書き"""

    def test_not_sent_without_record(self):
        self.start_deck()
        self.write_board()
        self.open_page(self.board)
        self.assertEqual(self.state()[2], {KEY: "23:30"})

    def test_empty_record_clears(self):
        # 上書きを全部外したブラウザ（`ovr:<日付>` が {} で残る）は空の地図を送り、Deck も元の時刻へ戻る
        today = datetime.date.today().strftime("%Y-%m-%d")
        self.seed({"tb:ovr:" + today: "{}"})
        self.start_deck()
        self.write_board()
        self.open_page(self.board)
        self.assertEqual(self.state()[2], {})

    def test_removal_leaves_empty_record(self):
        # ✎ で元の時刻へ戻すと記録が {} で残ることを、実物の処理で確かめる（上の試験の前提）
        today = datetime.date.today().strftime("%Y-%m-%d")
        self.seed({"tb:ovr:" + today: json.dumps({KEY: "23:30"}, ensure_ascii=False)})
        self.start_deck()
        back = ("<script>setTimeout(function(){var t=document.querySelector('.item .time');t.click();"
                "var i=t.querySelector('input');i.value='23:59';i.dispatchEvent(new Event('blur'));},800);</script>")
        self.write_board(extra=back)
        self.open_page(self.board)
        self.assertEqual(self.state()[2], {})
        # Deck に上書きが残っていても、次の読み込みで空の地図が届く（記録が消えていれば届かない）
        self.stop_deck()
        self.start_deck()
        self.write_board()
        self.open_page(self.board)
        self.assertEqual(self.state()[2], {})


if __name__ == "__main__":
    unittest.main()
