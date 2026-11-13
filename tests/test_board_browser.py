# -*- coding: utf-8 -*-
"""board.js と Deck の設定の送受信の試験（実ブラウザ・ヘッドレス）。

通知音の設定（ON/OFF・音種）と ✎ の時刻の上書きは Deck だけが持つ。読み込みでは読むだけで、送るのは操作したときだけ。
実施日（data-due）のチップの表示も見る。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
DOM を出せる Chrome も Edge も見つからなければ飛ばす。Chrome があれば Chrome で走る。別のブラウザで走らせるときは、環境変数 TB_TEST_BROWSER に
実行ファイルのパスを入れる（指したものが動かないときは飛ばさずに落ちる）。
Edge は、互換モードの下で起こされたと見ると自分を起こし直し、起こし直した側は標準出力を引き継がないので、
--dump-dom が何も出さずに戻る（実行ファイルの互換性の設定〔HIGHDPIAWARE 等〕や、親から継いだ環境変数 __COMPAT_LAYER で起きる）。
そのため Edge には --edge-skip-compat-layer-relaunch を足して起こす（browser_cmd）。
確かめた条件: Edge 157.0.4341.42。HKCU の AppCompatFlags の Layers に msedge.exe の HIGHDPIAWARE があり、親から継いだ環境変数
__COMPAT_LAYER がある環境で、Application フォルダ直下の msedge.exe を新しい一時プロファイルで指定なし・ありの4回ずつ（指定なしは4回とも
--dump-dom の出力が0バイト、指定ありは4回とも DOM が出た）、版のフォルダの msedge.exe を1回ずつ（同じ結果）起こした（2026-11-11）。ほかの版・設定の無い環境では確かめていない。
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
import time
import unittest
import urllib.parse
import pathlib
import re
from html import unescape as html_unescape

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


def browser_cmd(exe, profile, *args):
    """ヘッドレスで起こすコマンド。Edge には、互換モードを抜けるための起こし直しをさせない指定を足す
    （起こし直すと --dump-dom の出力が試験に届かない。モジュールの docstring）。"""
    cmd = [exe, "--headless=new", "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
           "--disable-extensions"]
    if os.path.basename(exe).lower() == "msedge.exe":
        cmd.append("--edge-skip-compat-layer-relaunch")
    return cmd + list(args)


def dumps_dom(exe):
    """そのブラウザが --dump-dom で DOM を出せるか。"""
    d = tempfile.mkdtemp(prefix="tb-browser-probe-")
    try:
        probe = os.path.join(d, "probe.html")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("<!doctype html><title>probe</title>")
        r = subprocess.run(browser_cmd(exe, os.path.join(d, "profile"), "--dump-dom", pathlib.Path(probe).as_uri()),
                           capture_output=True, timeout=60)
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
VIEW = "v" * 43   # ボードの表示の鍵（Deck v2.9）
KEY = "23:59|試験"
PLAYED = []   # 試聴の記録（実際には鳴らさない）
POSTS = []    # Deck が受けた POST の経路
NO_DECK = "Deck から設定を読めないため"
NOT_TODAY = "今日のボードではないため"
FAILED = "Deck に届かなかった可能性があります"
NEW_DESC = "通知音は Deck（監視ねこ）が鳴らします（Windows のみ・既定は OFF）。タスクの時刻はクリックで変更できます（「明日以降」の行を除く）（変更した時刻には ✎ が付きます。Claude 側の記録も直すときはチャットで伝えてください）。通知音の設定と時刻の変更は Deck に保存されます。Deck が止まっている間は音が鳴らず、どちらも変更できません。ほかの設定はブラウザ毎に保存されます。"
# 「明日以降」の行を除く旨を足す前の版（2026-11-02〜11-05 のテンプレ）
PREV_DESC = "通知音は Deck（監視ねこ）が鳴らします（Windows のみ・既定は OFF）。タスクの時刻はクリックで変更できます（変更した時刻には ✎ が付きます。Claude 側の記録も直すときはチャットで伝えてください）。通知音の設定と時刻の変更は Deck に保存されます。Deck が止まっている間は音が鳴らず、どちらも変更できません。ほかの設定はブラウザ毎に保存されます。"
# 過去に配った版の説明文。OLDEST_DESC＝「通知音は同梱の」を含む最初の版、LATEST_OLD_DESC＝短くする直前の版
OLDEST_DESC = "通知音は同梱の Deck（監視ねこ）が鳴らします（既定は OFF。上の「時刻トリガーの通知音」を ON にしてください）。Deck が停止しているときは音が出ません（そのときは監視ねこの欄に「停止」と表示されます）。ポップアップは Deck 停止中でも出ますが、Deck 稼働中なら未確認のまま残り、リロードしても復元されます。タスクの時刻はクリックで手動変更できます（✎印・この画面内のみの変更ですが、Deck 稼働中は通知が新しい時刻で出ます。Claude側の記録も直す場合はチャットで伝えてください）。設定はこのブラウザに保存されます。"
LATEST_OLD_DESC = "通知音は同梱の Deck（監視ねこ）が鳴らします（Windows のみ。既定は OFF。上の「時刻トリガーの通知音」を ON にしてください）。Deck が停止しているときは音が出ません（そのときは監視ねこの欄に「停止」と表示されます。接続情報の無い板では「不明」）。ポップアップは Deck 停止中でも出ますが、Deck 稼働中なら未確認のまま残り、リロードしても復元されます。タスクの時刻はクリックで手動変更できます（✎印。変更は Deck に保存され、どのブラウザで開いても同じで、通知音とポップアップは新しい時刻で出ます。Deck から読めないときや今日のボードでないときは変更できません（表示は、開いた後に読めていればその時刻、読めていなければ元の時刻です）。ボードのファイルの時刻は変わらないので、Claude側の記録も直す場合はチャットで伝えてください）。通知音の設定は Deck に保存され、どのブラウザで開いても同じです（Deck が動いていないときは変更できません）。それ以外の設定はこのブラウザに保存されます。"
# 最初の版だけは「通知音は同梱の」を含まないので、置き換えない
V1_DESC = "通知音はブラウザの自動再生制限のため、ページを一度クリックすると有効になります。タスクの時刻はクリックで手動変更できます（✎印・この画面内のみの変更。Claude側の記録も直す場合はチャットで伝えてください）。設定はこのブラウザに保存されます。"


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
        self.injected = {}   # 注入の道具が実際に応答を差し替えた（遅らせた）回数。道具の名前ごと
        self.passed = {}     # 注入の道具が数えた、自分のボードの要求の回数（差し替えたものを含む。道具が書くものだけ）
        del PLAYED[:]
        del POSTS[:]
        for f in ("board.js", "board.css", "cat.png"):
            shutil.copy2(os.path.join(ASSETS, f), self.dir)

    def tearDown(self):
        self.stop_deck()
        shutil.rmtree(self.dir, ignore_errors=True)

    # ---- 道具
    # 臨時のポートは、取った時点から試験の終わりまで手放さない。空いているかを確かめてから閉じて後で使う形だと、
    # 同時に走る別の試験一式（別のプロセス）が間に同じポートを取り、Deck を起こせずに落ちる
    # （2026-11-04 に試験一式を2本同時に走らせて、start_deck の assertIsNotNone が3件落ちた）。
    def free_port(self):
        """Deck の居ないポート。受け付けないソケットで押さえておく（つなぐと断られる）。試験の終わりに放す。"""
        for cand in range(18737, 18837):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", cand))
            except OSError:
                s.close()
                continue
            self.addCleanup(s.close)
            return cand
        self.fail("臨時のポートを取れない")

    def start_deck(self, enabled=True, stype="chime", ovr=None, pending=None):
        """pending を渡すと、今日の未確認の通知として sound.json に積んでから起こす（本物の SoundStore が読み、確認で外す）。"""
        today = datetime.date.today().strftime("%Y-%m-%d")
        data = {"enabled": enabled, "type": stype, "ovr_date": today,
                "ovr": {KEY: "23:30"} if ovr is None else ovr}
        if pending is not None:
            data["pending_date"] = today
            data["pending"] = pending
        with open(self.sound, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        # 確かめずに受信のソケットそのもので取りにいき、取れなければ次へ（取れたソケットがそのまま押さえになる）
        for cand in range(18737, 18837):
            self.server = dw.start_move_server(self.board, dw.SoundStore(self.sound), port=cand, token=TOKEN,
                                               view_key=VIEW)
            if self.server is not None:
                self.port = cand
                return
        self.fail("臨時のポートを取れない")

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

    def pending_keys(self):
        """sound.json に残っている未確認の通知の鍵（本物の SoundStore が書いた順）。"""
        with open(self.sound, encoding="utf-8") as f:
            d = json.load(f)
        return [p.get("key") for p in d.get("pending", [])]

    def spy_ack(self):
        """本物の SoundStore.ack をそのまま呼び、渡された鍵だけを記録する（未確認から外すのは本物の ack）。"""
        acked = []
        orig = dw.SoundStore.ack

        def spy(store, keys):
            acked.extend(keys)
            return orig(store, keys)
        dw.SoundStore.ack = spy
        self.addCleanup(setattr, dw.SoundStore, "ack", orig)
        return acked

    def write_board(self, port=None, extra="", date=None, key=True, time="23:59", rows=""):
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
                '<div class="item"><div class="time">%s</div><div><p class="task-title">試験</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div></div>%s'
                '<!-- DECK:AUTO:START -->%s<!-- DECK:AUTO:END -->'
                '<footer></footer></div><div id="toast-area"></div><script src="board.js"></script>%s'
                % (today.month, today.day, date, time, rows, deck_key, extra))
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(html)

    def write_real_board(self, desc=None, extra=""):
        """実物の board-template.html から今日の板を作る（desc で説明文を差し替えると、発行済みの古い板も作れる）。"""
        today = datetime.date.today()
        with open(os.path.join(ASSETS, "board-template.html"), encoding="utf-8") as f:
            t = f.read()
        self.assertIn(NEW_DESC, t)
        if desc is not None:
            t = t.replace(NEW_DESC, desc)
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
        ブラウザが起動しない・board.js が動かないと、ここで落とす（何も起きないことを確かめる試験が素通りしないように）。
        path に http: の URL を渡すと、その URL を開く（Deck が配った板・v2.9）。"""
        url = path if path.startswith("http:") else pathlib.Path(path).as_uri()
        r = subprocess.run(browser_cmd(BROWSER, self.profile, "--disable-sync", "--disable-background-networking",
                                       "--disable-component-update", "--virtual-time-budget=%d" % budget,
                                       "--dump-dom", url),
                           capture_output=True, timeout=90)
        dom = r.stdout.decode("utf-8", "replace")
        self.assertIn("</html>", dom, "ブラウザが DOM を返さない: rc=%s" % r.returncode)
        if path == self.board or path.startswith("http:"):
            self.assertIn(self.toggle_text(dom), ("ON", "OFF", "—"), "board.js が動いていない")
        return dom

    def served_url(self, page="/"):
        return "http://127.0.0.1:%d%s?v=%s" % (self.port, page, VIEW)

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

    def is_mine(self, handler):
        """この試験のボード（self.board。配った板なら http://127.0.0.1:<この Deck のポート>/）を申告した要求か。
        要求を数えて応答を差し替える道具は、これに当たる要求だけを数える。ほかの要求（別のプロセスからのもの等）は
        元の do_GET に流して照合で断らせる（数えがずれないように）。
        数えを絞るためだけの判定で、Deck の照合（Origin・トークン・ホストの大文字小文字の扱いなど）を写したものではない
        ——通るかどうかは、差し替えなかった要求について元の do_GET が決める。"""
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
        v = (q.get("board") or [None])[0]
        if not v:
            return False
        if self.port is not None and v in ("http://127.0.0.1:%d/" % self.port, "http://127.0.0.1:%d/board.html" % self.port):
            return True
        p = dw.board_path_from_url(v)
        return p is not None and dw.same_board(p, self.board)

    def inject(self, name):
        self.injected[name] = self.injected.get(name, 0) + 1

    def fail_get_after(self, n):
        """GET /sound/config を、最初の n 回だけ通して以後は 500 にする。"""
        orig = dw._BoardMoveHandler.do_GET
        count = [0]

        def do_get(handler):
            if handler.path.startswith("/sound/config") and self.is_mine(handler):
                count[0] += 1
                if count[0] > n:
                    self.inject("fail_get_after")
                    handler._send(500, b'{"ok": false}')
                    return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def fail_get_first(self, n):
        """GET /sound/config を、最初の n 回だけ 500 にする（応答が戻る場合）。
        自分のボードの要求の回数（差し替えたものを含む）を self.passed["fail_get_first"] に数える。"""
        orig = dw._BoardMoveHandler.do_GET
        count = [0]

        def do_get(handler):
            if handler.path.startswith("/sound/config") and self.is_mine(handler):
                count[0] += 1
                self.passed["fail_get_first"] = count[0]
                if count[0] <= n:
                    self.inject("fail_get_first")
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
            if handler.path.startswith("/notifications") and self.is_mine(handler):
                count[0] += 1
                if count[0] > n:
                    self.inject("fail_notifications_after")
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

    def test_old_description_is_replaced_whole_on_display(self):
        self.start_deck()
        for old in (OLDEST_DESC, LATEST_OLD_DESC, PREV_DESC):
            with self.subTest(old=old[:40]):
                self.write_real_board(desc=old)
                p = self.panel(self.open_page(self.board))
                self.assertEqual(p.count(NEW_DESC), 1)            # 丸ごと1回だけ
                self.assertEqual(p.count('<div class="set-note">'), 1)
                self.assertNotIn("通知音は同梱の", p)
                self.assertNotIn("未確認のまま", p)
                self.assertNotIn("この画面内のみ", p)
                self.assertNotIn("それ以外の設定は", p)
                with open(self.board, encoding="utf-8") as f:
                    t = f.read()
                self.assertIn(old, t)                             # 正本は変えない
                self.assertNotIn(NEW_DESC, t)

    def test_new_description_is_left_alone(self):
        self.start_deck()
        self.write_real_board()
        p = self.panel(self.open_page(self.board))
        self.assertEqual(p.count(NEW_DESC), 1)
        self.assertEqual(p.count('<div class="set-note">'), 1)

    def test_other_description_is_left_alone(self):
        self.start_deck()
        for other in ("利用者が書いた説明です。設定はこのブラウザに保存されます。", V1_DESC):
            with self.subTest(other=other[:40]):
                self.write_real_board(desc=other)
                p = self.panel(self.open_page(self.board))
                self.assertEqual(p.count(other), 1)
                self.assertNotIn(NEW_DESC, p)


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
        self.assertEqual(self.injected.get("fail_get_first"), 1)    # 最初の読み込みを差し替えた
        # 失敗の応答を本当に返した: 1回目が失敗したので、Deck の応答の後の読み直しと、操作の直前の読み直しが続き、
        # 要求は n+2＝3 回以上になる（1回目が通っていれば、読み直しは操作の直前の1回だけで、2 回になる）
        self.assertGreaterEqual(self.passed.get("fail_get_first", 0), 3)
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


def edit_time(value, ms=800):
    """✎ を操作する（時刻の欄を押し、入力欄が開けば値を入れて離れる。開かなければ印を残す）。"""
    return ("<script>setTimeout(function(){var t=document.querySelector('.item .time');t.click();"
            "var i=t.querySelector('input');if(!i){document.documentElement.setAttribute('data-noinput','1');return;}"
            "i.value='%s';i.dispatchEvent(new Event('blur'));},%d);</script>" % (value, ms))


def minutes_ago(n):
    """n 分前の H:MM。日付をまたぐときは None（その試験は飛ばす）。"""
    now = datetime.datetime.now()
    then = now - datetime.timedelta(minutes=n)
    return None if then.date() != now.date() else "%d:%02d" % (then.hour, then.minute)


class TimeCase(BrowserCase):
    def time_tag(self, dom):
        m = re.search(r'<div[^>]*class="time[^"]*"[^>]*>[^<]*</div>', dom)
        self.assertIsNotNone(m, "時刻の欄が無い")
        return m.group(0)

    def time_text(self, dom):
        return re.sub(r"<[^>]+>", "", self.time_tag(dom))

    def locked(self, dom):
        return "time-locked" in self.time_tag(dom)

    def time_posts(self):
        return POSTS.count("/board/times")

    def patch_get_times(self, fn):
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/board/times") and self.is_mine(handler) and fn(handler):
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def fail_get_times_after(self, n):
        count = [0]

        def fn(handler):
            count[0] += 1
            if count[0] > n:
                handler._send(500, b'{"ok": false}')
                return True
            return False

        self.patch_get_times(fn)

    def delay_get_times(self, sec):
        def fn(handler):
            self.inject("delay_get_times")
            time.sleep(sec)
            return False

        self.patch_get_times(fn)


class TestTimeOpenOnly(TimeCase):
    """✎ : 開くだけでは送らない"""

    def test_opening_sends_nothing_and_shows_deck_value(self):
        self.start_deck()
        self.write_board()
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.time_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.time_text(dom), "23:30")
        self.assertIn("overridden", self.time_tag(dom))
        self.assertFalse(self.locked(dom))

    def test_old_record_is_not_sent_and_is_removed(self):
        today = datetime.date.today().strftime("%Y-%m-%d")
        self.seed({"tb:ovr:" + today: json.dumps({KEY: "1:00"}), "tb:ovr:2020-01-01（水）": "{}", "tb:popup": "0"})
        self.start_deck()
        self.write_board(extra="<script>document.documentElement.setAttribute('data-test',[localStorage.getItem('tb:ovr:%s'),"
                               "localStorage.getItem('tb:ovr:2020-01-01（水）'),localStorage.getItem('tb:popup')].join());</script>" % today)
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.time_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.time_text(dom), "23:30")     # 古い記録は Deck の値に勝たない
        self.assertIn('data-test=",,0"', dom)

    def test_value_on_another_board_does_not_reach(self):
        self.start_deck(ovr={})
        self.write_board(extra=edit_time("22:00"))
        self.open_page(self.board)
        self.assertEqual(self.state()[2], {KEY: "22:00"})
        self.stop_deck()
        d2 = os.path.join(self.dir, "other")
        os.makedirs(d2)
        for f in ("board.js", "board.css", "cat.png"):
            shutil.copy2(os.path.join(ASSETS, f), d2)
        self.board = os.path.join(d2, "board.html")
        self.sound = os.path.join(d2, "sound.json")
        del POSTS[:]
        self.start_deck(ovr={})
        self.write_board()
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        self.assertEqual(self.time_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.time_text(dom), "23:59")


class TestTimeOperate(TimeCase):
    """✎ : 操作で1回だけ送る"""

    def test_edit_sends_once(self):
        self.start_deck(ovr={})
        self.write_board(extra=edit_time("22:00"))
        dom = self.open_page(self.board)
        self.assertEqual(self.time_posts(), 1)
        self.assertEqual(self.state()[2], {KEY: "22:00"})
        self.assertEqual(self.time_text(dom), "22:00")
        self.assertIn("overridden", self.time_tag(dom))

    def test_keeps_other_browser_value(self):
        other = "9:00|別のタスク"
        self.start_deck(ovr={other: "9:30"})
        post = ("<script>setTimeout(function(){var k=document.getElementById('deck-key');"
                "fetch('http://127.0.0.1:'+k.dataset.port+'/board/times?board='+encodeURIComponent(location.href.split('#')[0])+'&k='+k.dataset.k,"
                "{method:'POST',body:JSON.stringify({ovr:{'9:00|別のタスク':'9:45'}})});},500);</script>")
        self.write_board(extra=post + edit_time("22:00", 1000))
        self.open_page(self.board)
        self.assertEqual(self.state()[2], {other: "9:45", KEY: "22:00"})   # 開いたときの値（9:30）でなく、操作の直前の値に足す

    def test_back_to_original_sends_empty_map(self):
        self.start_deck()
        self.write_board(extra=edit_time("23:59"))
        dom = self.open_page(self.board)
        self.assertEqual(self.time_posts(), 1)
        self.assertEqual(self.state()[2], {})
        self.assertEqual(self.time_text(dom), "23:59")
        self.assertNotIn("overridden", self.time_tag(dom))

    def test_unchanged_value_sends_nothing(self):
        self.start_deck()
        self.write_board(extra=edit_time("23:30"))
        self.open_page(self.board)
        self.assertEqual(self.time_posts(), 0)

    def test_read_fails_at_operation_sends_nothing(self):
        self.start_deck()
        self.fail_get_times_after(1)
        self.write_board(extra=edit_time("22:00"))
        dom = self.open_page(self.board)
        self.assertEqual(self.time_posts(), 0)
        self.assertEqual(self.state()[2], {KEY: "23:30"})
        self.assertIn("送っていません", dom)
        self.assertEqual(self.time_text(dom), "23:30")   # 最後に読めた時刻のまま、操作だけできなくなる
        self.assertTrue(self.locked(dom))

    def test_post_fails_then_rereads_saved_value(self):
        # Deck は保存したのに応答が失敗に見える場合、読み直して Deck の値を映す
        self.start_deck()
        orig = dw._BoardMoveHandler.do_POST
        send = dw._BoardMoveHandler._send

        def do_post(handler):
            if handler.path.startswith("/board/times"):
                handler._send = lambda code, body=b"", *a, **k: send(handler, 500, b'{"ok": false}')
            orig(handler)

        dw._BoardMoveHandler.do_POST = do_post
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_POST", orig)
        self.write_board(extra=edit_time("22:00"))
        dom = self.open_page(self.board)
        self.assertEqual(self.state()[2], {KEY: "22:00"})
        self.assertIn("Deck に届かなかった可能性があります", dom)
        self.assertEqual(self.time_text(dom), "22:00")

    def test_periodic_reread_shows_other_browser_change(self):
        self.start_deck()
        post = ("<script>setTimeout(function(){var k=document.getElementById('deck-key');"
                "fetch('http://127.0.0.1:'+k.dataset.port+'/board/times?board='+encodeURIComponent(location.href.split('#')[0])+'&k='+k.dataset.k,"
                "{method:'POST',body:JSON.stringify({ovr:{'23:59|試験':'21:00'}})});},1000);</script>")
        self.write_board(extra=post)
        dom = self.open_page(self.board, budget=32000)
        self.assertEqual(self.time_text(dom), "21:00")

    def test_read_started_before_operation_is_not_applied(self):
        # 30 秒ごとの読み直しの結果が、操作の後に遅れて届いても、古い地図で表示を戻さない
        self.start_deck(ovr={})
        slow = ("<script>setTimeout(function(){var f=window.fetch,used=false;window.fetch=function(u,o){"
                "if(!used&&String(u).indexOf('/board/times')>=0&&!(o&&o.method==='POST')){used=true;"
                "return new Promise(function(res){setTimeout(function(){res(new Response(JSON.stringify({ok:true,ovr:{'23:59|試験':'1:11'}})));},400);});}"
                "return f.apply(this,arguments);};},29900);</script>")
        self.write_board(extra=slow + edit_time("22:00", 30050))
        dom = self.open_page(self.board, budget=32000)
        self.assertEqual(self.state()[2], {KEY: "22:00"})
        self.assertEqual(self.time_text(dom), "22:00")

    def test_post_fails_tells_and_keeps_value(self):
        self.start_deck()
        orig = dw._BoardMoveHandler.do_POST

        def do_post(handler):
            if handler.path.startswith("/board/times"):
                POSTS.append("/board/times")
                handler.rfile.read(int(handler.headers.get("Content-Length") or 0))
                handler._send(500, b'{"ok": false}')
                return
            orig(handler)

        dw._BoardMoveHandler.do_POST = do_post
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_POST", orig)
        self.write_board(extra=edit_time("22:00"))
        dom = self.open_page(self.board)
        self.assertEqual(self.time_posts(), 1)
        self.assertEqual(self.state()[2], {KEY: "23:30"})
        self.assertIn("Deck に届かなかった可能性があります", dom)
        self.assertEqual(self.time_text(dom), "23:30")

    def test_click_before_first_response_does_nothing(self):
        self.start_deck()
        # board.js の直後に同期で押す＝最初の応答より必ず前
        self.write_board(extra=re.sub(r"setTimeout\(function\(\)\{|\},\d+\);(?=</script>)", "", edit_time("22:00"))
                         .replace("<script>", "<script>(function(){").replace("</script>", "})();</script>"))
        dom = self.open_page(self.board)
        self.assertIn('data-noinput="1"', dom)
        self.assertEqual(self.time_posts(), 0)
        self.assertEqual(self.time_text(dom), "23:30")
        self.assertNotIn("Deck から読めない", dom)     # 待っているだけなので知らせない


class TestTimeUnavailable(TimeCase):
    """✎ : Deck が読めないときは操作できず、元の時刻を表示する"""

    def assert_locked(self, dom, text="Deck から読めないため"):
        self.assertIn('data-noinput="1"', dom)
        self.assertTrue(self.locked(dom))
        self.assertEqual(self.time_text(dom), "23:59")
        self.assertIn(text, dom)
        self.assertEqual(self.time_posts(), 0)

    def test_deck_not_answering(self):
        self.write_board(port=self.free_port(), extra=edit_time("22:00"))
        self.assert_locked(self.open_page(self.board))

    def test_no_connection_info(self):
        self.write_board(port=1, key=False, extra=edit_time("22:00"))
        self.assert_locked(self.open_page(self.board))

    def test_not_today_board_does_not_read_or_send(self):
        self.seed({"tb:ovr:2020-01-01": json.dumps({KEY: "1:00"})})
        self.start_deck()
        self.write_board(date="2020-01-01", extra=edit_time("22:00"))
        before = self.sound_bytes()
        self.assert_locked(self.open_page(self.board), "今日のボードではないため、時刻は変更できません")
        self.assertEqual(self.sound_bytes(), before)

    def test_copy_of_board(self):
        self.start_deck()
        self.write_board()
        before = self.sound_bytes()
        real = self.board
        d2 = os.path.join(self.dir, "copy")
        os.makedirs(d2)
        for f in ("board.js", "board.css", "cat.png"):
            shutil.copy2(os.path.join(ASSETS, f), d2)
        self.board = os.path.join(d2, "board.html")
        self.write_board(extra=edit_time("22:00"))
        self.assert_locked(self.open_page(self.board))
        self.assertEqual(self.sound_bytes(), before)
        self.board = real

    def test_deck_stops_after_page_opened(self):
        self.start_deck()
        self.fail_notifications_after(1)
        self.write_board()
        dom = self.open_page(self.board, budget=8000)
        self.assertEqual(self.time_text(dom), "23:30")   # 最後に読めた時刻で続ける
        self.assertTrue(self.locked(dom))
        self.assertIn("overridden", self.time_tag(dom))

    def test_edit_then_deck_unreadable_keeps_edited_time(self):
        # ✎ で変えた後に読めなくなっても、変更の前の時刻へ戻らない
        self.start_deck(ovr={})
        self.fail_notifications_after(1)
        self.write_board(extra=edit_time("22:00"))
        dom = self.open_page(self.board, budget=8000)
        self.assertEqual(self.state()[2], {KEY: "22:00"})
        self.assertEqual(self.time_text(dom), "22:00")
        self.assertTrue(self.locked(dom))

    def test_value_read_at_operation_survives_unreadable(self):
        # 操作の直前の読みで別のブラウザの値を拾う（同じ値なので送らない）→ 読めなくなっても、その値で続ける
        self.start_deck(ovr={})
        self.fail_notifications_after(1)
        post = ("<script>setTimeout(function(){var k=document.getElementById('deck-key');"
                "fetch('http://127.0.0.1:'+k.dataset.port+'/board/times?board='+encodeURIComponent(location.href.split('#')[0])+'&k='+k.dataset.k,"
                "{method:'POST',body:JSON.stringify({ovr:{'23:59|試験':'21:00'}})});},500);</script>")
        self.write_board(extra=post + edit_time("21:00", 1000))
        dom = self.open_page(self.board, budget=8000)
        self.assertEqual(self.time_posts(), 1)    # 送ったのは別のブラウザの役の1回だけ
        self.assertEqual(self.time_text(dom), "21:00")
        self.assertTrue(self.locked(dom))

    def test_read_fails_is_locked(self):
        self.start_deck()
        self.fail_get_times_after(0)
        self.write_board()
        dom = self.open_page(self.board)
        self.assertTrue(self.locked(dom))
        self.assertEqual(self.time_text(dom), "23:59")

    def test_operable_after_read_returns(self):
        self.start_deck()
        count = [0]

        def fn(handler):
            count[0] += 1
            if count[0] == 1:
                handler._send(500, b'{"ok": false}')
                return True
            return False

        self.patch_get_times(fn)
        self.write_board()
        dom = self.open_page(self.board, budget=8000)
        self.assertGreaterEqual(count[0], 2)    # 1回目が失敗し、読み直しが届いた
        self.assertFalse(self.locked(dom))
        self.assertEqual(self.time_text(dom), "23:30")


class TestTimeAlarm(TimeCase):
    """応答の前に元の時刻で通知を出さない。応答の後に判定し直す。Deck が無ければ元の時刻で出す"""

    def test_no_false_popup_before_response(self):
        t = minutes_ago(1)
        if t is None:
            self.skipTest("日付をまたぐ")
        self.start_deck(ovr={t + "|試験": "23:58"})
        self.delay_get_times(1.0)
        self.write_board(time=t)
        dom = self.open_page(self.board, budget=4000)
        self.assertGreaterEqual(self.injected.get("delay_get_times", 0), 1)   # 応答を本当に遅らせた
        self.assertEqual(self.time_text(dom), "23:58")
        self.assertNotIn("⏰", dom)

    def test_popup_at_overridden_time_after_response(self):
        t = minutes_ago(1)
        if t is None:
            self.skipTest("日付をまたぐ")
        self.start_deck(ovr={KEY: t})
        self.delay_get_times(0.5)
        self.write_board()
        dom = self.open_page(self.board, budget=4000)
        self.assertGreaterEqual(self.injected.get("delay_get_times", 0), 1)   # 応答を本当に遅らせた
        self.assertIn("⏰ %s 試験" % t, dom)

    def test_read_failure_keeps_last_map_for_alarm(self):
        # 開いた後に読めなくなっても、元の時刻のポップアップを出さない（30 秒ごとの判定まで待つ）
        t = minutes_ago(1)
        if t is None:
            self.skipTest("日付をまたぐ")
        self.start_deck(ovr={t + "|試験": "23:58"})
        self.fail_notifications_after(1)
        self.fail_get_times_after(1)
        self.write_board(time=t)
        dom = self.open_page(self.board, budget=32000)
        self.assertEqual(self.time_text(dom), "23:58")
        self.assertTrue(self.locked(dom))
        self.assertNotIn("⏰", dom)

    def test_later_section_row_has_no_popup_or_chips(self):
        t = minutes_ago(1)
        if t is None:
            self.skipTest("日付をまたぐ")
        self.start_deck(ovr={})
        rows = ('<div class="section-label">明日以降</div><div class="item"><div class="time">%s</div><div><p class="task-title">先の行</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div></div>' % t)
        self.write_board(rows=rows)
        dom = self.open_page(self.board)
        self.assertNotIn("⏰", dom)
        self.assertNotRegex(dom, r"先の行</p><div class=\"chips\">.*?時刻超過.*?</div></div></div><!-- DECK")
        self.assertNotRegex(dom, r'class="item[^"]*next-up[^"]*"[^>]*><div class="time[^"]*"[^>]*>%s' % t)

    def test_row_outside_later_section_still_popups(self):
        t = minutes_ago(1)
        if t is None:
            self.skipTest("日付をまたぐ")
        self.start_deck(ovr={})
        self.write_board(time=t)
        dom = self.open_page(self.board)
        self.assertIn("⏰ %s 試験" % t, dom)
        self.assertIn("時刻超過", dom)

    def test_popup_with_no_deck_uses_original_time(self):
        t = minutes_ago(1)
        if t is None:
            self.skipTest("日付をまたぐ")
        self.write_board(port=1, key=False, time=t)
        dom = self.open_page(self.board)
        self.assertIn("⏰ %s 試験" % t, dom)

    def test_popup_with_deck_not_answering_uses_original_time(self):
        t = minutes_ago(1)
        if t is None:
            self.skipTest("日付をまたぐ")
        self.write_board(port=self.free_port(), time=t)
        dom = self.open_page(self.board)
        self.assertIn("⏰ %s 試験" % t, dom)


class TestDueChips(BrowserCase):
    """実施日のチップ"""

    @staticmethod
    def later(title, attrs):
        return '<div class="item flat" %s><div><p class="task-title">%s</p></div></div>' % (attrs, title)

    def rows(self, today_side="", later=""):
        return '<div class="section-label">今日中</div>%s<div class="section-label">明日以降</div>%s' % (today_side, later)

    def test_chips(self):
        self.start_deck()
        today = datetime.date.today()
        fut = today + datetime.timedelta(days=3)
        past = today - datetime.timedelta(days=2)
        md = lambda d: "%d/%d" % (d.month, d.day)
        rows = self.rows(
            today_side='<div class="item flat" data-due="%s" data-due-moved="%s"><div><p class="task-title">移した</p>'
                       '<div class="chips"><span class="chip pending">未</span></div></div></div>' % (past.isoformat() + " 22:05", today.isoformat())
                       # v2.11 で移した行: 実施日は今日、元の実施日は data-due-from。チップは元の実施日から出す
                       + '<div class="item flat" data-due="%s" data-due-moved="%s" data-due-from="%s 21:10"><div><p class="task-title">今日にした</p>'
                       '<div class="chips"><span class="chip pending">未</span></div></div></div>' % (today.isoformat(), past.isoformat(), past.isoformat())
                       # 元の実施日のある行は、そのチップだけを出す（引き継ぎのチップは出さない＝「↪」は1行に1つ・v2.12）
                       + '<div class="item flat" data-due="%s" data-due-moved="%s" data-due-from="%s 20:00" data-carried-from="%s"><div><p class="task-title">重なる</p>'
                       '<div class="chips"><span class="chip pending">未</span></div></div></div>' % (today.isoformat(), past.isoformat(), past.isoformat(), past.isoformat()),
            later=self.later("先", 'data-due="%s 22:05"' % fut.isoformat())
            + self.later("先日付だけ", 'data-due="%s"' % fut.isoformat())
            + self.later("過ぎた", 'data-due="%s" data-due-moved="%s"' % (past.isoformat(), past.isoformat()))
            + self.later("読めない", 'data-due="いつか"')
            + self.later("無し", ""))
        self.write_board(rows=rows)
        dom = self.open_page(self.board)
        self.assertRegex(dom, r'先</p><div class="chips"><span class="chip pending js-auto">%s 22:05</span>' % md(fut))
        self.assertRegex(dom, r'先日付だけ</p><div class="chips"><span class="chip pending js-auto">%s</span>' % md(fut))
        self.assertRegex(dom, r'過ぎた</p><div class="chips"><span class="chip hold js-auto">%s を過ぎました</span>' % md(past))
        self.assertIn("↪ %s 22:05 の予定" % md(past), dom)
        self.assertRegex(dom, r'今日にした</p><div class="chips"><span class="chip pending">未</span><span class="chip pending js-auto">↪ %s 21:10 の予定から</span>' % md(past))
        self.assertNotIn("%s の予定" % md(today), dom)                      # 実施日（今日）からはチップを出さない
        self.assertRegex(dom, r'重なる</p><div class="chips"><span class="chip pending">未</span>'
                              r'<span class="chip pending js-auto">↪ %s 20:00 の予定から</span></div>' % md(past))
        self.assertNotIn("↪ %sから" % md(past), dom)
        self.assertNotRegex(dom, r'読めない</p><div class="chips"><span')
        self.assertNotRegex(dom, r'無し</p><div class="chips"><span')

    def test_out_of_range_time_is_unreadable(self):
        """時刻の欄が範囲外（25:00）なら「時刻を読めない」を付ける（board.js の parseHM。Deck の read_board_alarms・K12 と同じ）。"""
        self.start_deck()
        rows = ('<div class="section-label">今日の予定</div>'
                '<div class="item"><div class="time">25:00</div><div><p class="task-title">範囲外</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div></div>'
                '<div class="item"><div class="time">23:59</div><div><p class="task-title">範囲内</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div></div>'
                '<div class="section-label">明日以降</div>')
        self.write_board(rows=rows)
        dom = self.open_page(self.board)
        self.assertRegex(dom, r'範囲外</p><div class="chips"><span class="chip pending">未</span><span class="chip hold js-auto">時刻を読めない</span>')
        self.assertNotRegex(dom, r'範囲内</p><div class="chips"><span class="chip pending">未</span><span class="chip hold js-auto">時刻を読めない')

    def test_today_due_is_not_past_and_done_row_has_no_past_notice(self):
        self.start_deck()
        today = datetime.date.today()
        past = today - datetime.timedelta(days=2)
        md = lambda d: "%d/%d" % (d.month, d.day)
        rows = self.rows(later=self.later("当日", 'data-due="%s"' % today.isoformat())
                         + '<div class="item flat" data-due="%s"><div><p class="task-title">済んだ</p>'
                           '<div class="chips"><span class="chip done">済</span></div></div></div>' % past.isoformat())
        self.write_board(rows=rows)
        dom = self.open_page(self.board)
        self.assertRegex(dom, r'当日</p><div class="chips"><span class="chip pending js-auto">%s</span>' % md(today))
        self.assertNotIn("を過ぎました", dom)
        self.assertIn(md(past), dom)

    def test_not_shown_twice_with_carried(self):
        self.start_deck()
        d = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        rows = self.rows(today_side='<div class="item flat" data-due="%s 22:05" data-carried-from="%s" data-orig-time="22:05"><div><p class="task-title">残り</p>'
                                    '<div class="chips"><span class="chip pending">未</span></div></div></div>' % (d, d))
        self.write_board(rows=rows)
        dom = self.open_page(self.board)
        self.assertIn("22:05 の予定から", dom)
        self.assertNotRegex(dom, r"22:05 の予定<")

    def test_early_moved_row_carried_next_day_has_no_other_days_time(self):
        """先の日（+2 の 9:00）の行を前もって今日中へ動かし、翌日に引き継いだ行の引き継ぎのチップに、+2 の時刻を出さない（Deck v2.12）。
        前もって動かした行は今日の行になり、元の予定（+2 の 9:00）のチップ「↪ … の予定から」が出て、引き継ぎのチップは出ない（v2.13）。
        行は Deck の関数で作る（D&D・move の形 → 日付の切り替えの引き継ぎ）"""
        self.start_deck()
        d = datetime.date.today()
        yest, fut = d - datetime.timedelta(days=1), d + datetime.timedelta(days=1)
        md = lambda x: "%d/%d" % (x.month, x.day)
        later = ('<div class="item flat" data-due="%s 9:00"><div class="time">9:00</div><div><p class="task-title">前倒し</p>'
                 '<div class="chips"><span class="chip pending">未</span></div></div></div>' % fut.isoformat())
        shaped = dw._due_moved_shape(later, dw.parse_due_value(fut.isoformat() + " 9:00"), yest, "\n", False)
        self.assertNotIn("data-orig-time", shaped)          # v2.12 の D&D・move は残さない
        # v2.11 までの D&D・v1.7 までの move が残した data-orig-time（実施日の時刻）を持つ行も、引き継ぐときに外れる
        self.assertIn('data-due-from="%s 9:00"' % fut.isoformat(), shaped)
        legacy = shaped.replace('data-due="%s"' % yest.isoformat(), 'data-due="%s" data-orig-time="9:00"' % yest.isoformat(), 1)
        self.assertIn('data-orig-time="9:00"', legacy)
        for title, blk in (("前倒し", shaped), ("前倒し旧", legacy.replace("前倒し</p>", "前倒し旧</p>", 1))):
            carried = dw._carry_due_today(dw._set_item_open_tag(blk, carried_from=yest.isoformat()), d)
            self.write_board(rows=self.rows(today_side=carried))
            dom = self.open_page(self.board)
            self.assertRegex(dom, r'%s</p><div class="chips"><span class="chip pending">未</span>'
                                  r'<span class="chip pending js-auto">↪ %s 9:00 の予定から</span></div>' % (title, md(fut)))
            self.assertNotIn("%s 9:00 の予定から" % md(yest), dom)

    def test_rolled_notice_uses_recorded_counts(self):
        """「引き継いだボード」の件数は、Deck v2.12 が .board に書いた数を出す（行の印からは数えない）"""
        self.start_deck()
        d = datetime.date.today()
        today, yest = d.isoformat(), (d - datetime.timedelta(days=1)).isoformat()
        # 切り替えの後に add が今日の印を足した行（Deck は移していない）と、data-carried-from の残ったまま移した行
        rows = self.rows(today_side='<div class="item flat" data-due="%s" data-due-moved="%s"><div><p class="task-title">足した</p>'
                                    '<div class="chips"><span class="chip pending">未</span></div></div></div>' % (today, today)
                         + '<div class="item flat" data-due="%s" data-due-moved="%s" data-due-from="%s" data-carried-from="%s">'
                           '<div><p class="task-title">移した</p><div class="chips"><span class="chip pending">未</span></div></div></div>'
                           % (today, today, yest, yest))
        # 数でない値（"x"）の板は、これまでどおり行の印から数える（引き継いだ行 1件・印だけの行 1件）
        for counts, want, unwanted in ((("4", "1"), ("終わっていないタスク4件", "実施日が来た予定 1件"), ("実施日が来た予定 2件",)),
                                       (("0", "0"), ("終わっていないタスクを引き継いで",), ("実施日が来た予定",)),
                                       (("x", "x"), ("終わっていないタスク1件", "実施日が来た予定 1件"), ("NaN",))):
            self.write_board(rows=rows)
            with open(self.board, encoding="utf-8") as f:
                t = f.read()
            with open(self.board, "w", encoding="utf-8") as f:
                f.write(t.replace('<div class="board">', '<div class="board" data-tb-rolled="%s" data-tb-rolled-carried="%s" '
                                  'data-tb-rolled-due="%s">' % (yest, counts[0], counts[1])))
            dom = self.open_page(self.board)
            for w in want:
                self.assertIn(w, dom, counts)
            for u in unwanted:
                self.assertNotIn(u, dom, counts)

    def test_rolled_notice_counts_moved_rows(self):
        self.start_deck()
        today = datetime.date.today().isoformat()
        rows = self.rows(today_side='<div class="item flat" data-due="%s" data-due-moved="%s"><div><p class="task-title">移した</p>'
                                    '<div class="chips"><span class="chip pending">未</span></div></div></div>' % (today, today))
        self.write_board(rows=rows)
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<div class="board">', '<div class="board" data-tb-rolled="%s">' % today))
        self.assertIn("実施日が来た予定 1件", self.open_page(self.board))

    def test_rolled_notice_does_not_count_carried_rows(self):
        """先の日の行を前もって今日の側へ動かし（印なし）、実施日を過ぎてから引き継いだ行は、Deck v2.11 の _carry_due_today が
        今日の印を付けるが、「実施日が来た予定」の件数には数えない（引き継いだ行＝data-carried-from）。"""
        self.start_deck()
        d = datetime.date.today()
        today, yest = d.isoformat(), (d - datetime.timedelta(days=1)).isoformat()
        early = ('<div class="item flat" data-due="%s 9:00"><div><p class="task-title">前倒し</p>'
                 '<div class="chips"><span class="chip pending">未</span></div></div></div>' % yest)
        carried = dw._carry_due_today(dw._set_item_open_tag(early, carried_from=yest), d)
        self.assertIn('data-due-moved="%s"' % today, carried)       # 前提: 引き継いだ行にも今日の印が付く
        self.assertIn('data-carried-from="%s"' % yest, carried)
        rows = self.rows(today_side='<div class="item flat" data-due="%s" data-due-moved="%s"><div><p class="task-title">移した</p>'
                                    '<div class="chips"><span class="chip pending">未</span></div></div></div>' % (today, today) + carried)
        self.write_board(rows=rows)
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<div class="board">', '<div class="board" data-tb-rolled="%s">' % yest))
        dom = self.open_page(self.board)
        self.assertIn("実施日が来た予定 1件", dom)
        self.assertNotIn("実施日が来た予定 2件", dom)


WATCH = '<div class="section-label">監視ねこ</div><div class="section-label">明日以降</div>'


class TestServedBoard(BrowserCase):
    """Deck が配った板（http://127.0.0.1:<ポート>/?v=<表示の鍵>・Deck v2.9）。file: で開いた板と同じく、通知音の設定・
    ✎ の時刻・通知の取得と確認・D&D の反映・Deck の生死表示が動き、今日でない板の知らせは Deck の板を開いたページの文面になる。"""

    def test_served_board_deck_stops_after_page_opened(self):
        """配った板でも、開いた後に Deck が応答しなくなると ⚙ の通知音は「—」になる（注入は配った板の申告にも効く）。"""
        self.fail_notifications_after(1)
        self.start_deck(enabled=True, stype="chime")
        self.write_board(rows=WATCH)
        dom = self.open_page(self.served_url(), budget=5000)
        self.assertGreaterEqual(self.injected.get("fail_notifications_after", 0), 1)
        self.assertEqual(self.toggle_text(dom), "—")
        self.assertFalse(self.operable(dom))

    def test_reads_and_operates_sound(self):
        self.start_deck(enabled=False, stype="std")
        self.write_board(rows=WATCH, extra=click("#sound-toggle"))
        dom = self.open_page(self.served_url())
        self.assertEqual(self.sound_posts(), 1)
        self.assertEqual(self.state()[:2], (True, "std"))
        self.assertIn('id="deck-status-row"', dom)
        self.assertRegex(dom, r'id="deck-status-row".*?<span class="chip active">稼働</span>')

    def test_opening_sends_nothing(self):
        self.start_deck(enabled=True, stype="chime")
        self.write_board(rows=WATCH)
        before = self.sound_bytes()
        dom = self.open_page(self.served_url("/board.html"))
        self.assertEqual(self.sound_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual((self.toggle_text(dom), self.active_type(dom)), ("ON", "chime"))
        self.assertTrue(self.operable(dom))

    def test_move_reaches_board(self):
        """D&D の反映（POST /board/move）が、配った板から同じオリジンの要求として届いて board.html に入る。
        板は board_edit.py の create で作る（Deck の走査は行単位なので、1行の板では項目を見つけられない）。"""
        self.start_deck()
        spec = os.path.join(self.dir, "spec.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"sections": ["今日の予定", "今日中", "明日以降"],
                       "items": [{"section": "今日の予定", "time": "23:59", "title": "試験"},
                                 {"section": "明日以降", "title": "来週"}]}, f, ensure_ascii=False)
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "skill", "scripts", "board_edit.py"), "create",
                            "--board", self.board, "--spec", spec], capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        t = t.replace("<!-- DECK:AUTO:START -->", '<!-- DECK:AUTO:START -->\n<span id="deck-key" hidden data-port="%d" data-k="%s"></span>'
                      % (self.port, TOKEN), 1)
        t += ("<script>setTimeout(function(){deckFetch('/board/move',{method:'POST',"
              "body:JSON.stringify({k:'23:59|試験',sec:'明日以降',before:null,head:true})}).then(function(r){"
              "document.documentElement.setAttribute('data-mv',String(r.status));});},800);</script>\n")
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t)
        dom = self.open_page(self.served_url())
        self.assertIn('data-mv="200"', dom)
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        self.assertGreater(t.index("試験"), t.index('<div class="section-label">明日以降</div>'))

    def test_time_edit_reaches_deck(self):
        """✎ の時刻の変更（POST /board/times）が、配った板から届いて Deck に保存され、画面の時刻も変わる。"""
        self.start_deck(ovr={})
        self.write_board(rows=WATCH, extra=edit_time("22:00"))
        dom = self.open_page(self.served_url())
        self.assertEqual(POSTS.count("/board/times"), 1)
        self.assertEqual(self.state()[2], {KEY: "22:00"})
        m = re.search(r'<div[^>]*class="time[^"]*"[^>]*>([^<]*)</div>', dom)
        self.assertIsNotNone(m, "時刻の欄が無い")
        self.assertEqual(m.group(1), "22:00")
        self.assertIn("overridden", m.group(0))

    def test_opening_shows_deck_time(self):
        """配った板を開くと、Deck が持つ ✎ の時刻を読んで出す（開くだけでは送らない）。"""
        self.start_deck()
        self.write_board(rows=WATCH)
        before = self.sound_bytes()
        dom = self.open_page(self.served_url())
        self.assertEqual(POSTS.count("/board/times"), 0)
        self.assertEqual(self.sound_bytes(), before)
        m = re.search(r'<div[^>]*class="time[^"]*"[^>]*>([^<]*)</div>', dom)
        self.assertIsNotNone(m, "時刻の欄が無い")
        self.assertEqual(m.group(1), "23:30")

    def test_notification_ack_reaches_deck(self):
        """Deck の未確認の通知が配った板に出て、閉じると確認（POST /notifications/ack）が Deck に届き、sound.json の未確認から外れる。"""
        acked = self.spy_ack()
        item = {"key": KEY, "time": "23:59", "title": "試験", "at": "00:00:01"}
        self.start_deck(pending=[item])
        self.assertEqual(self.pending_keys(), [KEY])
        self.write_board(rows=WATCH, extra=(
            "<script>setTimeout(function(){var t=document.querySelector('#toast-area .toast');"
            "document.documentElement.setAttribute('data-t',t?t.textContent:'none');if(t)t.click();"
            "setTimeout(function(){document.documentElement.setAttribute('data-after',"
            "String(document.querySelectorAll('#toast-area .toast').length));},4000);},2500);</script>"))
        dom = self.open_page(self.served_url(), budget=9000)
        m = re.search(r'data-t="([^"]*)"', dom)
        self.assertIsNotNone(m)
        self.assertIn("試験", m.group(1))                    # 未確認の通知が出た
        self.assertEqual(POSTS.count("/notifications/ack"), 1)
        self.assertEqual(acked, [KEY])                       # 閉じた通知の確認が Deck に届いた
        self.assertEqual(self.pending_keys(), [])            # 本物の SoundStore が未確認から外して保存した
        self.assertIn('data-after="0"', dom)                 # 確認の後は出し直さない

    def test_not_today_notice_uses_local_text(self):
        self.start_deck()
        fut = (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        self.write_board(rows=WATCH, date=fut)
        dom = self.open_page(self.served_url())
        self.assertIn("書き込み停止中", dom)
        self.assertIn("今日のボードと確かめられないため", dom)

    def test_other_port_in_key_is_not_local(self):
        """Deck が配ったページでも、接続情報のポートが配った Deck と違えば Deck の板を開いたページとみなさない。"""
        self.start_deck()
        other = self.free_port()
        while other == self.port:
            other += 1
        fut = (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        self.write_board(port=other, rows=WATCH, date=fut)
        dom = self.open_page(self.served_url())
        self.assertIn("書き込み停止中", dom)
        self.assertNotIn("今日のボードと確かめられないため", dom)

    def test_missing_markers_are_checked(self):
        self.start_deck()
        self.write_board(rows=WATCH)
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace("<!-- DECK:AUTO:END -->", ""))
        dom = self.open_page(self.served_url())
        self.assertIn("DECK:AUTO の目印）がそろっていません", dom)

    def reload_probe(self):
        return ("<script>var n=+(sessionStorage.getItem('loads')||0)+1;sessionStorage.setItem('loads',String(n));"
                "document.documentElement.setAttribute('data-loads',String(n));"
                "if(n===1)setTimeout(function(){tbReload();},300);</script>")

    def test_reload_waits_for_deck(self):
        self.start_deck()
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/ping"):
                handler._send(500, b"down")
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)
        self.write_board(rows=WATCH, extra=self.reload_probe())
        dom = self.open_page(self.served_url(), budget=4000)
        self.assertIn('data-loads="1"', dom)       # Deck が答えないので読み直さない（エラーの画面にしない）

    def test_reload_when_deck_answers(self):
        self.start_deck()
        self.write_board(rows=WATCH, extra=self.reload_probe())
        dom = self.open_page(self.served_url(), budget=4000)
        self.assertIn('data-loads="2"', dom)

    def ping_replies(self, make_body):
        """/ping の応答を置き換える（ポートを先に取った別のプログラムを模す）。make_body(乱数) が本文を返す。"""
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/ping"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
                handler._send(200, make_body((q.get("n") or [""])[0]).encode("ascii"), "text/plain; charset=utf-8")
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def test_no_reload_to_impostor_without_proof(self):
        """固定の文字列 deck-board-mover だけを返す相手には、読み直しで鍵を送らない。"""
        self.start_deck()
        self.ping_replies(lambda n: "deck-board-mover")
        self.write_board(rows=WATCH, extra=self.reload_probe())
        self.assertIn('data-loads="1"', self.open_page(self.served_url(), budget=4000))

    def test_no_reload_with_proof_for_other_port(self):
        """別のポートの本物の Deck へ中継して得た証し（そのポートの値）では読み直さない。"""
        self.start_deck()
        self.ping_replies(lambda n: "deck-board-mover " + dw.ping_proof(VIEW, self.port + 1, n))
        self.write_board(rows=WATCH, extra=self.reload_probe())
        self.assertIn('data-loads="1"', self.open_page(self.served_url(), budget=4000))

    def before_board_js(self, script):
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        self.assertEqual(t.count('<script src="board.js"></script>'), 1)
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<script src="board.js"></script>', '<script>%s</script><script src="board.js"></script>' % script))

    def test_no_reload_without_crypto_subtle(self):
        """証しを作れない（crypto.subtle が無い）ブラウザでは、Deck が本物でも読み直さない（fail-closed）。"""
        self.start_deck()
        self.write_board(rows=WATCH, extra=self.reload_probe())
        self.before_board_js("Object.defineProperty(window.crypto,'subtle',{value:undefined,configurable:true});"
                             "document.documentElement.setAttribute('data-nosubtle',String(!window.crypto.subtle));")
        dom = self.open_page(self.served_url(), budget=4000)
        self.assertIn('data-nosubtle="true"', dom)
        self.assertIn('data-loads="1"', dom)

    def test_url_with_key_is_checked_even_if_port_differs(self):
        """接続情報のポートが配り元と違う（TB_SERVED が偽の）ページでも、URL に ?v= があれば確かめてから読み直す。"""
        self.start_deck()
        self.ping_replies(lambda n: "deck-board-mover")
        other = self.free_port()
        while other == self.port:
            other += 1
        self.write_board(port=other, rows=WATCH, extra=self.reload_probe())
        self.assertIn('data-loads="1"', self.open_page(self.served_url(), budget=4000))

    def test_manual_reload_checks_deck_and_tells(self):
        self.start_deck()
        self.ping_replies(lambda n: "deck-board-mover")
        self.write_board(rows=WATCH, extra="<script>var n=+(sessionStorage.getItem('loads')||0)+1;"
                         "sessionStorage.setItem('loads',String(n));document.documentElement.setAttribute('data-loads',String(n));"
                         "</script>" + click("#reload-btn", 300))
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<button id="settings-btn"></button>', '<button id="settings-btn"></button><button id="reload-btn"></button>'))
        dom = self.open_page(self.served_url(), budget=4000)
        self.assertIn('data-loads="1"', dom)
        self.assertIn("応答を確かめられないため、読み直しませんでした", dom)


    # ---- 受信ポートで Deck 以外のもの（別のユーザーの Deck など）が答えたとき（配った板は同じオリジンなので CORS は関わらない）
    def answer_notifications(self, code, body, cors):
        """/notifications と /ping の応答を置き換える。cors=False なら CORS の許可を付けない（Deck 以外のものの応答を模す）。"""
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/notifications") or handler.path.startswith("/ping"):
                b = b"deck-board-mover" if handler.path.startswith("/ping") else body
                c = 200 if handler.path.startswith("/ping") else code
                if cors:
                    handler._send(c, b)
                else:
                    handler.send_response(c)
                    handler.send_header("Content-Type", "text/plain")
                    handler.send_header("Content-Length", str(len(b)))
                    handler.end_headers()
                    handler.wfile.write(b)
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def status_chip(self, dom):
        m = re.search(r'id="deck-status-row".*?<span class="chip [^"]*">([^<]*)</span>', dom)
        return m.group(1) if m else None

    def load_counter(self):
        return ("<script>var n=+(sessionStorage.getItem('loads')||0)+1;sessionStorage.setItem('loads',String(n));"
                "document.documentElement.setAttribute('data-loads',String(n));</script>")

    def test_other_answerer_without_cors_is_unknown(self):
        """目印の無い 200（CORS の許可なし）は「不明」。file: の板と違って fetch は失敗しない（「停止」にならない）。"""
        self.start_deck()
        self.answer_notifications(200, b"hello", cors=False)
        self.write_board(rows=WATCH)
        self.assertEqual(self.status_chip(self.open_page(self.served_url())), "不明")

    def test_other_answerer_404_is_unknown(self):
        self.start_deck()
        self.answer_notifications(404, b"not found", cors=False)
        self.write_board(rows=WATCH)
        self.assertEqual(self.status_chip(self.open_page(self.served_url())), "不明")

    def test_other_deck_token_mismatch_is_stale_and_no_reload(self):
        """別のユーザーの Deck が 403 token mismatch を返すと「古い」。読み直しは証しが合わないので起きない。
        文面は配った板のもの（file: の板の「数秒〜1分ほどで戻ります」は出さない）。"""
        self.start_deck()
        self.answer_notifications(403, b'{"ok": false, "error": "token mismatch"}', cors=True)
        self.write_board(rows=WATCH, extra=self.load_counter())
        dom = self.open_page(self.served_url(), budget=9000)
        self.assertEqual(self.status_chip(dom), "古い")
        self.assertIn('data-loads="1"', dom)
        self.assertIn("このボードを配った Deck と確かめてから読み直して戻ります", dom)
        self.assertIn("新しい URL を開き直してください", dom)
        self.assertNotIn("数秒〜1分ほどで戻ります", dom)

    def test_ok_without_marker_is_unknown(self):
        """JSON として読める 200 でも、目印（"deck":"today-board"）が無ければ「不明」。"""
        self.start_deck()
        self.answer_notifications(200, b'{"ok": true}', cors=True)
        self.write_board(rows=WATCH)
        self.assertEqual(self.status_chip(self.open_page(self.served_url())), "不明")


class TestFileBoardReload(BrowserCase):
    """file: で開いた板の読み直し（証しを確かめずに読み直す）"""

    def test_file_board_reloads(self):
        self.start_deck()
        self.write_board(extra="<script>var n=+(sessionStorage.getItem('loads')||0)+1;sessionStorage.setItem('loads',String(n));"
                               "document.documentElement.setAttribute('data-loads',String(n));"
                               "if(n===1)setTimeout(function(){tbReload();},300);</script>")
        self.assertIn('data-loads="2"', self.open_page(self.board, budget=4000))


    def test_file_board_stale_text_is_unchanged(self):
        """file: の板の「古い」は従来の文面のまま（Deck を再起動した直後なら読み直しで戻る）。"""
        self.start_deck()
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/notifications"):
                handler._send(403, b'{"ok": false, "error": "token mismatch"}')
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)
        self.write_board(rows=WATCH)
        dom = self.open_page(self.board, budget=3000)
        self.assertIn("数秒〜1分ほどで戻ります", dom)
        self.assertNotIn("このボードを配った Deck と確かめ", dom)



class TestServedStaleAndReloadLoop(BrowserCase):
    """配った板の「古い」の出し分け（今日でない板・行き詰まり）と、自動の読み直しの確かめを1本にまとめる仕組み。
    確かめ直しの間隔はページの中から TB_RELOAD_RETRY_MS を短くして試す。"""

    def setUp(self):
        super().setUp()
        self.pings = []

    def ping_replies(self, make_body):
        """/ping の応答を置き換え、受けた回数を数える。make_body(乱数, 何回目) が本文を返す。"""
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/ping"):
                self.pings.append(time.time())
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
                body = make_body((q.get("n") or [""])[0], len(self.pings))
                handler._send(200, body.encode("ascii"), "text/plain; charset=utf-8")
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def token_mismatch(self):
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/notifications"):
                handler._send(403, b'{"ok": false, "error": "token mismatch"}')
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)

    def before_board_js(self, script):
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        self.assertEqual(t.count('<script src="board.js"></script>'), 1)
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<script src="board.js"></script>', '<script>%s</script><script src="board.js"></script>' % script))

    def counter(self, then=""):
        return ("<script>var n=+(sessionStorage.getItem('loads')||0)+1;sessionStorage.setItem('loads',String(n));"
                "document.documentElement.setAttribute('data-loads',String(n));if(n===1){%s}</script>" % then)

    # ---- B: 「古い」の出し分け
    def test_not_today_stale_text(self):
        self.start_deck()
        self.token_mismatch()
        fut = (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        self.write_board(rows=WATCH, date=fut)
        dom = self.open_page(self.served_url(), budget=3000)
        self.assertIn("今日のボードではないので、Deck の再起動に合わせた読み直しはしません", dom)
        self.assertIn("このボードを配った Deck と確かめてから行います", dom)
        self.assertNotIn("読み直そうとしても新しくなりません", dom)

    def test_stuck_stale_text(self):
        self.start_deck()
        self.token_mismatch()
        self.write_board(rows=WATCH)
        self.before_board_js("sessionStorage.setItem('tbDeckReload:staleKey','%s');"
                             "sessionStorage.setItem('tbDeckReload:staleCount','2');" % TOKEN)
        dom = self.open_page(self.served_url(), budget=9000)
        self.assertIn("読み直そうとしても新しくなりません", dom)
        self.assertIn("Deck が board.html に書き込めていません", dom)
        self.assertNotIn("今日のボードではないので", dom)
        self.assertIn("Deck の再起動に合わせた読み直しは、これ以上新しくは始めません", dom)
        self.assertIn("15 秒ごとに確かめ直し", dom)
        self.assertNotIn("読み直しは止めました", dom)

    def test_stuck_then_proof_matches_reloads(self):
        """行き詰まった（DECK_STALE_STUCK）後も、待っている読み直しは確かめ直しを続け、証しが合えば読み直す。
        行き詰まりは自然な流れで起こす: 同じトークンで1回読み直した記録を置き、token mismatch を返し続ける。"""
        self.start_deck()
        self.token_mismatch()
        self.ping_replies(lambda n, i: "deck-board-mover" if i <= 4 else "deck-board-mover " + dw.ping_proof(VIEW, self.port, n))
        self.write_board(rows=WATCH, extra=(
            "<script>var n=+(sessionStorage.getItem('loads')||0)+1;sessionStorage.setItem('loads',String(n));"
            "document.documentElement.setAttribute('data-loads',String(n));"
            "document.documentElement.setAttribute('data-stuck-seen',sessionStorage.getItem('stuckSeen')||'0');"
            "if(n===1){TB_RELOAD_RETRY_MS=2000;setInterval(function(){if(DECK_STALE_STUCK)sessionStorage.setItem('stuckSeen','1');},200);}"
            "</script>"))
        self.before_board_js("sessionStorage.setItem('tbDeckReload:staleKey','%s');"
                             "sessionStorage.setItem('tbDeckReload:staleCount','1');" % TOKEN)
        dom = self.open_page(self.served_url(), budget=25000)
        self.assertIn('data-loads="2"', dom)
        self.assertIn('data-stuck-seen="1"', dom)       # 読み直す前に行き詰まりの状態になっていた

    def test_stuck_starts_no_new_reload(self):
        """行き詰まったら、Deck の再起動に合わせた読み直しを新しく始めない。
        証しは合うのに Deck が board.html を書き直さない＝トークンが古いまま token mismatch を返し続ける。
        読み直しは 60 秒に1回までで、同じトークンのまま2回読み直したら行き詰まる＝読み込みは3回で止まる。"""
        self.start_deck()
        self.token_mismatch()
        self.write_board(rows=WATCH, extra=self.counter())
        dom = self.open_page(self.served_url(), budget=200000)
        self.assertIn('data-loads="3"', dom)
        self.assertIn("読み直そうとしても新しくなりません", dom)

    # ---- 確かめを1本にまとめる
    def test_auto_reload_checks_once_per_interval(self):
        """自動の読み直しを何度呼んでも、確かめの /ping は間隔ごとに1回。"""
        self.start_deck()
        self.ping_replies(lambda n, i: "deck-board-mover")
        self.write_board(rows=WATCH, extra=self.counter(
            "TB_RELOAD_RETRY_MS=1000;setTimeout(function(){for(var i=0;i<10;i++)tbReload();},300);"
            "setTimeout(function(){for(var i=0;i<10;i++)tbReload();},700);"))
        dom = self.open_page(self.served_url(), budget=3500)
        self.assertIn('data-loads="1"', dom)
        self.assertGreaterEqual(len(self.pings), 2)
        self.assertLessEqual(len(self.pings), 5, len(self.pings))

    def test_manual_reload_checks_while_waiting(self):
        """自動の確かめ直しを待っている間でも、手の読み直しは確かめて知らせを出す。"""
        self.start_deck()
        self.ping_replies(lambda n, i: "deck-board-mover")
        self.write_board(rows=WATCH, extra=self.counter(
            "TB_RELOAD_RETRY_MS=60000;setTimeout(function(){tbReload();},300);"
            "setTimeout(function(){tbReload(true);},900);"))
        dom = self.open_page(self.served_url(), budget=3000)
        self.assertIn('data-loads="1"', dom)
        self.assertEqual(len(self.pings), 2)
        self.assertIn("応答を確かめられないため、読み直しませんでした", dom)

    def test_loop_reloads_when_proof_matches_later(self):
        """確かめ直しの途中で証しが合えば読み直す。"""
        self.start_deck()
        self.ping_replies(lambda n, i: "deck-board-mover" if i <= 2 else "deck-board-mover " + dw.ping_proof(VIEW, self.port, n))
        self.write_board(rows=WATCH, extra=self.counter("TB_RELOAD_RETRY_MS=500;setTimeout(function(){tbReload();},300);"))
        dom = self.open_page(self.served_url(), budget=4000)
        self.assertIn('data-loads="2"', dom)

    # ---- 決着しない確かめ
    def test_hanging_ping_without_abort_controller_gives_up(self):
        """AbortController が無く /ping の fetch が決着しなくても、上限の後に確かめられなかったことにする
        （手の読み直しは知らせる）。決着しない fetch はページの中で /ping だけを差し替えて作る。"""
        self.start_deck()
        self.write_board(rows=WATCH, extra=self.counter("TB_VERIFY_LIMIT_MS=800;setTimeout(function(){tbReload(true);},300);"))
        self.before_board_js("window.AbortController=undefined;var tbOrigFetch=window.fetch;"
                             "window.fetch=function(u){if(String(u).indexOf('/ping')===0)return new Promise(function(){});"
                             "return tbOrigFetch.apply(this,arguments);};")
        dom = self.open_page(self.served_url(), budget=3000)
        self.assertIn('data-loads="1"', dom)
        self.assertIn("応答を確かめられないため、読み直しませんでした", dom)


DND_TITLES = ["前の日の時刻つき", "時刻つき今日", "今日の時刻", "朝9時", "暦に無い", "時刻2つ", "入れ子div", "入れ子span",
              "印あり今日", "先の日", "ゼロ付き", "範囲外", "先の日付だけ", "元あり", "先のゼロ"]
DND_MOVES = [("前の日の時刻つき", "今日中"), ("時刻つき今日", "今日中"), ("今日の時刻", "今日の予定"), ("朝9時", "今日の予定"),
             ("暦に無い", "今日中"), ("時刻2つ", "今日中"), ("入れ子div", "今日中"), ("入れ子span", "今日中"),
             ("印あり今日", "今日の予定"), ("先の日", "今日の予定"), ("ゼロ付き", "今日の予定"), ("範囲外", "今日の予定"),
             ("先の日付だけ", "今日中"), ("元あり", "今日中"), ("先のゼロ", "今日中")]
# 画面で D&D を起こす（dragstart → 見出しへ drop → dragend）。行の形を JSON で html 要素の data-shape に書く
DND_JS = ("<script>function tbItem(title){return Array.prototype.slice.call(document.querySelectorAll('.item')).filter(function(i){"
          "var t=i.querySelector('.task-title');return t&&t.textContent===title;})[0];}"
          "function tbDnd(title, sec){var src=tbItem(title);"
          "var dt=new DataTransfer();src.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));"
          "var tgt=document.querySelector('.section-label[data-sec=\"'+sec+'\"]');"
          "tgt.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));"
          "src.dispatchEvent(new DragEvent('dragend',{bubbles:true}));}"
          "function tbShape(){var out={};%s.forEach(function(title){var it=tbItem(title);if(!it)return;"
          "var s=it.previousElementSibling;while(s&&!s.classList.contains('section-label'))s=s.previousElementSibling;"
          "out[title]={sec:s?s.textContent.trim():null,times:Array.prototype.map.call(it.querySelectorAll('.time'),function(t){"
          "return (t.getAttribute('data-orig')||t.textContent).trim();}),flat:it.classList.contains('flat'),"
          "orig:it.getAttribute('data-orig-time'),moved:it.getAttribute('data-due-moved'),due:it.getAttribute('data-due'),"
          "from:it.getAttribute('data-due-from'),"
          "pending:Array.prototype.filter.call(it.querySelectorAll('span.chip.pending'),function(c){return c.textContent==='未';}).length,"
          "chipsLast:!!(it.querySelector('.chips')&&it.querySelector('.chips').parentNode===it.lastElementChild)};});"
          "document.documentElement.setAttribute('data-shape',JSON.stringify(out));}"
          "var n=+(sessionStorage.getItem('loads')||0)+1;sessionStorage.setItem('loads',String(n));"
          "document.documentElement.setAttribute('data-loads',String(n));"
          "setTimeout(function(){document.documentElement.setAttribute('data-bound',['入れ子div','入れ子span'].map(function(t){"
          "var it=tbItem(t),el=it&&it.querySelector('.time');return t+'='+(el?el.getAttribute('data-orig'):'');}).join(','));},500);"
          "if(n===1){setTimeout(function(){%s},800);}setTimeout(tbShape,%d);%s</script>")


class TestDndDueShape(BrowserCase):
    """ボードの D&D で、実施日のある「明日以降」の行を今日の側へ動かすと、画面の行も Deck（board.html）と同じ形になる（Deck v2.10。
    印のある行・実施日の前の行も＝v2.11）。
    Deck に届かず localStorage に残した移動を、読み込みで再び当てるときも同じ形にする。"""

    def setUp(self):
        super().setUp()
        now = datetime.datetime.now()
        if now.hour == 23 and now.minute >= 50:
            self.skipTest("0 時をまたぐと「今日」がずれる")

    def make(self, port, after_load="", shape_at=2500, moves=DND_MOVES):
        today = datetime.date.today()
        yest = today - datetime.timedelta(days=1)
        tom = today + datetime.timedelta(days=1)
        spec = os.path.join(self.dir, "spec.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"sections": ["今日の予定", "今日中", "明日以降"],
                       "items": [{"section": "今日の予定", "time": "9:00", "title": "前の日の時刻つき"},
                                 # 時刻の欄（10:00）と実施日の時刻（23:57）が違う行は board_edit.py v1.7 の操作では作れない
                                 # （v1.6 までにできた行）。今日の側の行を move で「明日以降」へ戻した後に data-due を手で書き換える
                                 {"section": "今日の予定", "time": "10:00", "title": "時刻つき今日",
                                  "due": today.isoformat() + " 23:57", "due_moved": None},
                                 {"section": "今日中", "title": "ふつう"},
                                 {"section": "明日以降", "title": "今日の時刻", "due": tom.isoformat() + " 23:58"},
                                 {"section": "明日以降", "title": "朝9時", "due": tom.isoformat()},
                                 {"section": "明日以降", "title": "暦に無い"},
                                 {"section": "明日以降", "title": "時刻2つ", "due": tom.isoformat()},
                                 {"section": "明日以降", "title": "入れ子div", "due": tom.isoformat()},
                                 {"section": "明日以降", "title": "入れ子span", "due": tom.isoformat()},
                                 # 一度移した印のある行・実施日の前の行も同じ形にする（Deck v2.11）
                                 {"section": "明日以降", "title": "印あり今日", "due": today.isoformat() + " 23:56",
                                  "due_moved": yest.isoformat()},
                                 {"section": "明日以降", "title": "先の日", "due": tom.isoformat() + " 9:00"},
                                 # 時刻の欄の 09:00 は 9:00 に直して使い、範囲外の 25:00 は使わない（Deck の _valid_hm）
                                 {"section": "明日以降", "title": "ゼロ付き", "due": today.isoformat(), "due_moved": yest.isoformat()},
                                 {"section": "明日以降", "title": "範囲外", "due": today.isoformat() + " 23:55",
                                  "due_moved": yest.isoformat()},
                                 # 先の日の日付だけの実施日と時刻の欄（v1.6 までの set-time でできた形）。外した時刻を実施日に入れる
                                 {"section": "明日以降", "title": "先の日付だけ", "due": tom.isoformat()},
                                 # 旧版で一度移して戻した行（印と元の実施日あり）。元の実施日は変えない
                                 {"section": "明日以降", "title": "元あり", "due": yest.isoformat(), "due_moved": yest.isoformat(),
                                  "due_from": (yest - datetime.timedelta(days=2)).isoformat() + " 8:00"},
                                 # 先の日の 09:00 の実施日（board_edit.py は書かない形。手で作る）。時刻が同じでも 9:00 の形に書き直す（Deck と同じ）
                                 {"section": "明日以降", "title": "先のゼロ", "due": tom.isoformat() + " 9:00"}]}, f, ensure_ascii=False)
        be = [sys.executable, "-I", os.path.join(ROOT, "skill", "scripts", "board_edit.py")]
        for argv in (["create", "--board", self.board, "--spec", spec],
                     ["move", "--board", self.board, "--item", "9:00|前の日の時刻つき", "--section", "明日以降", "--due", "none"],
                     ["set-due", "--board", self.board, "--item", "9:00|前の日の時刻つき", "--due", yest.isoformat()],
                     ["move", "--board", self.board, "--item", "10:00|時刻つき今日", "--section", "明日以降", "--due", "none"],
                     ["set-due", "--board", self.board, "--item", "|今日の時刻", "--due", today.isoformat() + " 23:58"],
                     ["set-due", "--board", self.board, "--item", "|朝9時", "--due", today.isoformat() + " 9:05"],
                     ["set-due", "--board", self.board, "--item", "|時刻2つ", "--due", yest.isoformat()],
                     ["set-due", "--board", self.board, "--item", "|入れ子div", "--due", yest.isoformat()],
                     ["set-due", "--board", self.board, "--item", "|入れ子span", "--due", yest.isoformat()]):
            r = subprocess.run(be + argv, capture_output=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        # 0X:MM の実施日・暦に無い実施日・時刻の欄が2つの行は、board_edit.py が書かない形なので手で作る
        t = t.replace('data-due="%s 9:05"' % today.isoformat(), 'data-due="%s 09:05"' % today.isoformat(), 1)
        t, kz = re.subn(r'data-due="%s 9:00"(>\s*<div>\s*<p class="task-title">先のゼロ</p>)' % tom.isoformat(),
                        r'data-due="%s 09:00"\1' % tom.isoformat(), t, count=1)
        self.assertEqual(kz, 1)
        # 「時刻つき今日」は未定（--due none）で戻したので、実施日を手で付ける（時刻の欄 10:00 と違う今日の 23:57＝v1.6 までにできた形）
        t, kt = re.subn(r'(<div class="item[^"]*")(>\s*<div class="time">10:00</div>\s*<div>\s*<p class="task-title">時刻つき今日</p>)',
                        r'\1 data-due="%s 23:57"\2' % today.isoformat(), t, count=1)
        self.assertEqual(kt, 1)
        t = re.sub(r'(<div class="item[^"]*")(>\s*<div>\s*<p class="task-title">暦に無い</p>)', r'\1 data-due="2025-02-30"\2', t, count=1)
        t = t.replace('<p class="task-title">時刻2つ</p>', '<div class="time">8:00</div><div class="time">8:30</div><p class="task-title">時刻2つ</p>', 1)
        for title, tm in (("ゼロ付き", "09:00"), ("範囲外", "25:00"), ("先の日付だけ", "10:00")):
            t, k = re.subn(r'(<div class="item[^"]*"[^>]*>)(\s*<div>\s*<p class="task-title">%s</p>)' % title,
                           r'\1<div class="time">%s</div>\2' % tm, t, count=1)
            self.assertEqual(k, 1, title)
        # 正しい形の入れ子の時刻の欄（Deck の _TIME_OPEN_RE の前のコメントが挙げる形）
        t, nd = re.subn(r'(<div class="item[^"]*"[^>]*>)(\s*<div>\s*<p class="task-title">入れ子div</p>)',
                        r'\1<div class="time"><div>7:00</div></div>\2', t, count=1)
        t, ns = re.subn(r'(<div class="item[^"]*"[^>]*>)(\s*<div>\s*<p class="task-title">入れ子span</p>)',
                        r'\1<span class="time">7:30</span>\2', t, count=1)
        self.assertEqual((nd, ns), (1, 1))
        t = t.replace("<!-- DECK:AUTO:START -->", '<!-- DECK:AUTO:START -->\n<span id="deck-key" hidden data-port="%d" data-k="%s"></span>'
                      % (port, TOKEN), 1)
        calls = "".join("tbDnd(%s,%s);" % (json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False)) for a, b in moves)
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t + DND_JS % (json.dumps(DND_TITLES, ensure_ascii=False), calls, shape_at, after_load) + "\n")

    def dom_shape(self, dom):
        m = re.search(r'data-shape="([^"]*)"', dom)
        self.assertIsNotNone(m, "画面の形を取れない")
        return json.loads(html_unescape(m.group(1)))

    def file_shape(self):
        with open(self.board, encoding="utf-8") as f:
            text = f.read()
        lines = text.splitlines(keepends=True)
        _s, items, _d = dw._scan_board(lines)
        out = {}
        for s_, e, name in items:
            b = "".join(lines[s_:e + 1])
            title = dw._element_text(b, "task-title")
            if title not in DND_TITLES:
                continue
            head = b.split(">", 1)[0]
            out[title] = {"sec": name, "times": re.findall(r'<div class="time">([^<]*)</div>', b),
                          "flat": " flat" in re.search(r'class="([^"]*)"', head).group(1).join("  "),
                          "orig": (re.search(r'data-orig-time="([^"]*)"', head) or [None, None])[1],
                          "moved": (re.search(r'data-due-moved="([^"]*)"', head) or [None, None])[1],
                          "due": (re.search(r'\sdata-due="([^"]*)"', head) or [None, None])[1],
                          "from": (re.search(r'\sdata-due-from="([^"]*)"', head) or [None, None])[1],
                          "pending": len(re.findall(r'<span class="chip pending">未</span>', b))}
        return out

    def expected(self):
        d = datetime.date.today()
        today = d.isoformat()
        yest = (d - datetime.timedelta(days=1)).isoformat()
        tom = (d + datetime.timedelta(days=1)).isoformat()
        # 実施日が今日以前の行は、実施日を今日にし（時刻の欄を付けるならその時刻を含め、付けないなら日付だけ）、元の実施日を from に残す（v2.11）。
        # from の時刻は行の時刻（時刻の欄が H:MM ならそれ、無ければ実施日の時刻）。外した時刻の欄は orig（data-orig-time）に残さない（v2.12）
        return {
            "前の日の時刻つき": dict(sec="今日中", times=[], flat=True, orig=None, moved=today, pending=1, due=today, **{"from": yest + " 9:00"}),
            # 実施日が今日・時刻ありでも今日中へは鳴らさない（時刻を付けないので実施日は日付だけ）
            "時刻つき今日": dict(sec="今日中", times=[], flat=True, orig=None, moved=today, pending=1, due=today, **{"from": today + " 10:00"}),
            "今日の時刻": dict(sec="今日の予定", times=["23:58"], flat=False, orig=None, moved=today, pending=1, due=today + " 23:58",
                          **{"from": today + " 23:58"}),   # 今日の時刻で今日の予定へ（未を足す）
            "朝9時": dict(sec="今日の予定", times=["9:05"], flat=False, orig=None, moved=today, pending=1, due=today + " 9:05",
                        **{"from": today + " 9:05"}),           # 09:05 の形の実施日も読む（今日の実施日・元の実施日は 9:05 の形で書く）
            "暦に無い": dict(sec="今日中", times=[], flat=True, orig=None, moved=None, pending=0, due="2025-02-30", **{"from": None}),   # 読まない
            "時刻2つ": dict(sec="今日中", times=["8:00", "8:30"], flat=True, orig=None, moved=today, pending=0, due=yest, **{"from": None}),    # 印だけ
            "入れ子div": dict(sec="今日中", times=[], flat=True, orig=None, moved=today, pending=1, due=today, **{"from": yest + " 7:00"}),   # 正しい形の入れ子
            "入れ子span": dict(sec="今日中", times=[], flat=True, orig=None, moved=today, pending=1, due=today, **{"from": yest + " 7:30"}),
            "印あり今日": dict(sec="今日の予定", times=["23:56"], flat=False, orig=None, moved=yest, pending=1, due=today + " 23:56",
                          **{"from": today + " 23:56"}),  # 印は変えない
            "先の日": dict(sec="今日の予定", times=[], flat=True, orig=None, moved=today, pending=1, due=today, **{"from": tom + " 9:00"}),   # 今日の行になる・時刻は付けない（v2.13）
            "ゼロ付き": dict(sec="今日の予定", times=["9:00"], flat=False, orig=None, moved=yest, pending=1, due=today + " 9:00",
                         **{"from": today + " 9:00"}),   # 時刻の欄の 09:00 を 9:00 にして使う
            "範囲外": dict(sec="今日の予定", times=["23:55"], flat=False, orig=None, moved=yest, pending=1, due=today + " 23:55",
                        **{"from": today + " 23:55"}),   # 範囲外の時刻の欄は使わない
            "先の日付だけ": dict(sec="今日中", times=[], flat=True, orig=None, moved=today, pending=1, due=today,
                           **{"from": tom + " 10:00"}),   # 外した時刻の欄の時刻を元の予定に入れる（v2.13）
            "元あり": dict(sec="今日中", times=[], flat=True, orig=None, moved=yest, pending=1, due=today,
                         **{"from": (d - datetime.timedelta(days=3)).isoformat() + " 8:00"}),   # 印も元の実施日も変えない
            "先のゼロ": dict(sec="今日中", times=[], flat=True, orig=None, moved=today, pending=1, due=today,
                          **{"from": tom + " 9:00"}),   # 09:00 の実施日は 9:00 の形で元の予定に書く（画面と board.html が同じ）
        }

    def check(self, shape, label, with_chips_pos=False):
        for title, want in self.expected().items():
            got = dict(shape[title])
            got.pop("chipsLast", None)
            self.assertEqual(got, want, (label, title))

    def test_dom_and_file_with_deck(self):
        self.start_deck()
        self.make(self.port)
        dom = self.open_page(self.board, budget=3500)
        shape = self.dom_shape(dom)
        self.check(shape, "画面")
        self.check(self.file_shape(), "board.html")
        # 未の置き場（chips 欄が行の最後の div の中）も Deck と同じ
        for title in ("前の日の時刻つき", "時刻つき今日", "今日の時刻", "朝9時", "入れ子div", "入れ子span"):
            self.assertTrue(shape[title]["chipsLast"], title)
        # 正しい形の入れ子の時刻の欄にも ✎ が結ばれていた（読み込みの後・D&D の前に data-orig が付いた）
        self.assertIn('data-bound="入れ子div=7:00,入れ子span=7:30"', dom)

    def test_dom_after_replay_without_deck(self):
        """Deck が居ない（接続情報のポートに誰も居ない）と localStorage に残り、読み直した後の再適用でも同じ形になる。"""
        port = self.free_port()
        self.make(port, after_load="if(n===1)setTimeout(function(){location.reload();},2000);", shape_at=1500)
        with open(self.board, encoding="utf-8") as f:
            before = f.read()
        dom = self.open_page(self.board, budget=6000)
        self.assertIn('data-loads="2"', dom)
        self.check(self.dom_shape(dom), "再適用の後の画面")
        with open(self.board, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)     # Deck が居ないので board.html は変わらない

    def test_added_time_field_is_editable_without_reload(self):
        """D&D で足した時刻の欄も、読み直しを待たずに ✎（クリックで入力欄）が開く。"""
        self.start_deck()
        self.make(self.port, moves=[("今日の時刻", "今日の予定")],
                  after_load="setTimeout(function(){tbItem('今日の時刻').querySelector('.time').click();},1800);")
        dom = self.open_page(self.board, budget=3500)
        m = re.search(r'<div class="time[^"]*"[^>]*>(<input[^>]*>)</div>\s*<div>\s*<p class="task-title">今日の時刻</p>', dom)
        self.assertIsNotNone(m, "✎ の入力欄が開かない")

    def test_unclosed_time_field_gets_only_the_mark(self):
        """中に行の部品のある時刻の欄（閉じタグの無い欄に、ブラウザが後ろの要素を取り込んだ形）は、画面でも印だけ（Deck は形を作れない）。"""
        today = datetime.date.today()
        yest = (today - datetime.timedelta(days=1)).isoformat()
        rows = ('<div class="section-label">今日中</div><div class="item flat"><div><p class="task-title">ふつう</p></div></div>'
                '<div class="section-label">明日以降</div>'
                '<div class="item flat" data-due="%s"><div class="time">9:00<div><p class="task-title">閉じない</p></div></div>' % yest)
        self.write_board(key=False, rows=rows, extra=(
            "<script>setTimeout(function(){var it=Array.prototype.slice.call(document.querySelectorAll('.item')).filter(function(i){"
            "var t=i.querySelector('.task-title');return t&&t.textContent==='閉じない';})[0];var dt=new DataTransfer();"
            "it.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));"
            "document.querySelector('.section-label[data-sec=\"今日中\"]').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));"
            "it.dispatchEvent(new DragEvent('dragend',{bubbles:true}));"
            "document.documentElement.setAttribute('data-r',[it.getAttribute('data-due-moved'),it.querySelectorAll('.time').length,"
            "it.classList.contains('flat'),it.querySelectorAll('span.chip.pending').length,"
            "it.querySelector('.time').hasAttribute('data-orig')].join(','));},800);</script>"))
        dom = self.open_page(self.board, budget=2500)
        # 印だけ・時刻の欄は1つのまま・flat のまま・未を足さない・✎ を結ばない（data-orig が付かない）
        self.assertIn('data-r="%s,1,true,0,false"' % today.isoformat(), dom)

    def dnd_one(self, rows, title, report):
        """Deck の居ない板で、title の行を「今日中」へ D&D し、report（JS の式。it が行）の値を html 要素の data-r に書く。"""
        self.write_board(key=False, rows=rows, extra=(
            "<script>setTimeout(function(){var it=Array.prototype.slice.call(document.querySelectorAll('.item')).filter(function(i){"
            "var t=i.querySelector('.task-title');return t&&t.textContent===%s;})[0];var before=%s;var dt=new DataTransfer();"
            "it.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));"
            "document.querySelector('.section-label[data-sec=\"今日中\"]').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));"
            "it.dispatchEvent(new DragEvent('dragend',{bubbles:true}));"
            "document.documentElement.setAttribute('data-r',before+'/'+(%s));},800);</script>"
            % (json.dumps(title, ensure_ascii=False), report, report)))
        dom = self.open_page(self.board, budget=2500)
        m = re.search(r'data-r="([^"]*)"', dom)
        self.assertIsNotNone(m, "結果を取れない")
        return html_unescape(m.group(1)).split("/")

    def test_time_inside_time_gets_only_the_mark(self):
        """時刻の欄の中に時刻の欄がある形は、Deck と同じく時刻の欄2つと数えて印だけを付ける。外側の欄には ✎ を結ばない。"""
        today = datetime.date.today()
        yest = (today - datetime.timedelta(days=1)).isoformat()
        item = ('<div class="item flat" data-due="%s"><div class="time"><span class="time">9:00</span></div>'
                '<div><p class="task-title">二重</p></div></div>' % yest)
        rows = ('<div class="section-label">今日中</div><div class="item flat"><div><p class="task-title">ふつう</p></div></div>'
                '<div class="section-label">明日以降</div>' + item)
        report = ("[it.getAttribute('data-due-moved'),it.querySelectorAll('.time').length,it.classList.contains('flat'),"
                  "it.querySelectorAll('span.chip.pending').length,(function(t){return t?t.hasAttribute('data-orig'):'none';})(it.querySelector('.time'))].join(',')")
        before, after = self.dnd_one(rows, "二重", report)
        self.assertEqual(before, ",2,true,0,false")                   # 読み込みの後も外側の欄に ✎ は結ばれていない
        self.assertEqual(after, "%s,2,true,0,false" % today.isoformat())  # 印だけ
        self.assertIsNone(dw._due_moved_shape(item, dw.parse_due_value(yest), today, "\n", False))   # Deck も形を作らない

    def test_chips_field_is_matched_like_deck(self):
        """「未」の置き場の chips 欄は、Deck と同じく開始タグの最初の属性が class="chips" の div に限る
        （<div id=… class="chips"> は chips 欄と見ず、行の最後の div の末尾に chips 欄ごと足す）。"""
        today = datetime.date.today()
        yest = (today - datetime.timedelta(days=1)).isoformat()
        item = ('<div class="item flat" data-due="%s"><div><p class="task-title">属性の順</p>'
                '<div id="c1" class="chips"><span class="chip plan">計画</span></div></div></div>' % yest)
        rows = ('<div class="section-label">今日中</div><div class="item flat"><div><p class="task-title">ふつう</p></div></div>'
                '<div class="section-label">明日以降</div>' + item)
        report = ("[it.querySelectorAll('span.chip.pending').length,it.querySelector('#c1').querySelectorAll('span.chip.pending').length,"
                  "it.querySelectorAll('div.chips').length].join(',')")
        _before, after = self.dnd_one(rows, "属性の順", report)
        shaped = dw._due_moved_shape(item, dw.parse_due_value(yest), today, "\n", False)
        self.assertIsNotNone(shaped)
        c1 = re.search(r'<div id="c1" class="chips">(.*?)</div>', shaped).group(1)
        deck = "%d,%d,%d" % (shaped.count('<span class="chip pending">未</span>'), c1.count("chip pending"),
                             len(re.findall(r'<div[^>]*class="chips"', shaped)))
        self.assertEqual(deck, "1,0,2")
        self.assertEqual(after, deck)
        # class が最初の属性なら、その chips 欄の末尾に足す（Deck も同じ）
        item2 = item.replace('<div id="c1" class="chips">', '<div class="chips" id="c1">')
        shaped2 = dw._due_moved_shape(item2, dw.parse_due_value(yest), today, "\n", False)
        self.assertIn('<div class="chips" id="c1"><span class="chip plan">計画</span><span class="chip pending">未</span></div>', shaped2)
        _before, after2 = self.dnd_one(rows.replace(item, item2), "属性の順", report)
        self.assertEqual(after2, "1,1,1")


class TestLaterDueAsk(BrowserCase):
    """今日の予定・今日中の行を「明日以降」へ D&D すると、実施日（日付・時刻は任意）か未定を聞いてから動かす（2026-11-06 ユーザー決定・
    Deck v2.13）。決めた値は Deck の D&D の反映（"due"）と localStorage の再適用に渡り、Deck の _later_due_shape と同じ形になる。
    やめたら動かさない。「明日以降」の中での並べ替えは聞かない。"""

    def setUp(self):
        super().setUp()
        now = datetime.datetime.now()
        if now.hour == 23 and now.minute >= 50:
            self.skipTest("0 時をまたぐと「今日」がずれる")
        d = datetime.date.today()
        self.today = d.isoformat()
        self.plus = lambda n: (d + datetime.timedelta(days=n)).isoformat()

    def rows(self, extra=""):
        # Deck は行ごとに板を読むので、見出しと項目は行を分けて書く。extra は今日中の末尾に足す行
        return ('\n<div class="section-label">今日中</div>\n'
                '<div class="item flat" data-due="%s" data-due-moved="%s" data-due-from="%s 10:00"><div><p class="task-title">前倒し</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div></div>\n'
                '<div class="item"><div class="time">15:00</div><div><p class="task-title">会議</p>'
                '<div class="chips"><span class="chip pending">未</span></div></div></div>\n%s'
                '<div class="section-label">明日以降</div>\n'
                '<div class="item flat"><div><p class="task-title">いつか</p></div></div>\n'
                '<div class="item flat"><div><p class="task-title">そのうち</p></div></div>\n' % (self.today, self.today, self.plus(3), extra))

    SCRIPT = ("<script>function tbItem(title){return Array.prototype.slice.call(document.querySelectorAll('.item')).filter(function(i){"
              "var t=i.querySelector('.task-title');return t&&t.textContent===title;})[0];}"
              "function tbDnd(title, sec){var src=tbItem(title);"
              "var dt=new DataTransfer();src.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));"
              "var tgt=document.querySelector('.section-label[data-sec=\"'+sec+'\"]');"
              "tgt.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));"
              "src.dispatchEvent(new DragEvent('dragend',{bubbles:true}));}"
              "function tbRow(title){var it=tbItem(title);var s=it.previousElementSibling;"
              "while(s&&!s.classList.contains('section-label'))s=s.previousElementSibling;"
              "return [s?s.textContent.trim():'',it.getAttribute('data-due'),it.getAttribute('data-due-moved'),it.getAttribute('data-due-from'),"
              "Array.prototype.map.call(it.querySelectorAll('.time'),function(t){return t.textContent.trim();}).join('+'),"
              "it.classList.contains('flat')].join(',');}"
              "function tbDlg(){var g=document.querySelector('dialog.later-due');if(!g)return 'none';"
              "var i=g.querySelectorAll('input');return [g.open,i[0].value,i[0].min,i[1].value,g.textContent.indexOf('を明日以降へ')>=0].join(',');}"
              "var n=+(sessionStorage.getItem('loads')||0)+1;sessionStorage.setItem('loads',String(n));"
              "document.documentElement.setAttribute('data-loads',String(n));%s</script>")

    def page(self, body, key=True, budget=4000, port=None):
        self.write_board(key=key, port=port, rows=self.rows(), extra=self.SCRIPT % body)
        return self.open_page(self.board, budget=budget)

    def attr(self, dom, name):
        m = re.search(r'%s="([^"]*)"' % name, dom)
        self.assertIsNotNone(m, name)
        return html_unescape(m.group(1))

    def wait_file_row(self, title, section, limit=10.0):
        """Deck が書き終えるまで（行が section に現れるまで）最長 limit 秒待って file_row を返す。
        ページの DOM を出し終えた時点で、Deck がまだ移動を書いている途中のことがある（並べて走らせたときに1回落ちた）。"""
        end = time.time() + limit
        while True:
            r = self.file_row(title)
            if (r and r[0] == section) or time.time() >= end:
                return r
            time.sleep(0.1)

    def file_row(self, title):
        """board.html（Deck が書いた）の行の (見出し, data-due, data-due-moved, data-due-from, 時刻の欄の文字の並び)。"""
        with open(self.board, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r'(<div class="item[^"]*"[^>]*>)((?:(?!<div class="item).)*?<p class="task-title">%s</p>)' % re.escape(title), text, re.S)
        if not m:
            return None
        head, body = m.group(1), m.group(2)
        secs = re.findall(r'<div class="section-label">([^<]*)</div>', text[:m.start()])
        get = lambda a: (re.search(r'\s%s="([^"]*)"' % a, head) or [None, None])[1]
        return (secs[-1] if secs else None), get("data-due"), get("data-due-moved"), get("data-due-from"), re.findall(r'class="time">([^<]*)<', body)

    def test_prefill_then_decide_with_deck(self):
        """元の予定（明日以後）を初めから入れておき、決めた日付（時刻なし）で動かす。Deck も同じ形に書く。"""
        self.start_deck()
        dom = self.page("setTimeout(function(){tbDnd('前倒し','明日以降');"
                        "document.documentElement.setAttribute('data-moved',tbRow('前倒し'));"
                        "document.documentElement.setAttribute('data-dlg',tbDlg());"
                        "var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');"
                        "i[0].value='%s';i[1].value='';g.querySelector('.later-due-ok').click();"
                        "document.documentElement.setAttribute('data-after',tbRow('前倒し')+'|'+tbDlg());},800);" % self.plus(4))
        self.assertEqual(self.attr(dom, "data-moved").split(",")[0], "今日中")          # 決めるまでは動かさない
        self.assertEqual(self.attr(dom, "data-dlg"), "true,%s,%s,10:00,true" % (self.plus(3), self.plus(1)))
        self.assertEqual(self.attr(dom, "data-after"), "明日以降,%s,,,,true|none" % self.plus(4))
        self.assertEqual(self.file_row("前倒し"), ("明日以降", self.plus(4), None, None, []))

    def test_time_field_follows_the_decided_time_and_undecided_keeps_it(self):
        """時刻の欄のある行は、決めた時刻にそろう（Deck も同じ）。未定は実施日を外し、時刻の欄は変えない。"""
        self.start_deck()
        dom = self.page("setTimeout(function(){tbDnd('会議','明日以降');"
                        "document.documentElement.setAttribute('data-dlg',tbDlg());"
                        "var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');"
                        "i[0].value='%s';i[1].value='09:30';g.querySelector('.later-due-ok').click();"
                        "document.documentElement.setAttribute('data-after',tbRow('会議'));},800);" % self.plus(2))
        self.assertEqual(self.attr(dom, "data-dlg"), "true,,%s,15:00,true" % self.plus(1))   # 元の予定が無ければ日付は空・時刻は時刻の欄
        self.assertEqual(self.attr(dom, "data-after"), "明日以降,%s 9:30,,,9:30,false" % self.plus(2))
        self.assertEqual(self.file_row("会議"), ("明日以降", self.plus(2) + " 9:30", None, None, ["9:30"]))
        dom = self.page("setTimeout(function(){tbDnd('前倒し','明日以降');"
                        "document.querySelector('dialog.later-due .later-due-none').click();"
                        "document.documentElement.setAttribute('data-after',tbRow('前倒し'));},800);")
        self.assertEqual(self.attr(dom, "data-after"), "明日以降,,,,,true")
        self.assertEqual(self.file_row("前倒し"), ("明日以降", None, None, None, []))

    def test_cancel_and_bad_date_do_not_move(self):
        """やめる（と Esc）なら動かさず、Deck にも送らない。今日以前の日付では決められない。並べ替えでは聞かない。"""
        self.start_deck()
        dom = self.page("setTimeout(function(){tbDnd('会議','明日以降');"
                        "var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');"
                        "i[0].value='%s';g.querySelector('.later-due-ok').click();"
                        "document.documentElement.setAttribute('data-bad',tbDlg()+'|'+g.querySelector('.later-due-msg').textContent);"
                        "g.querySelector('.later-due-cancel').click();"
                        "document.documentElement.setAttribute('data-c1',tbRow('会議')+'|'+tbDlg());"
                        "tbDnd('会議','明日以降');document.querySelector('dialog.later-due').dispatchEvent(new Event('cancel',{cancelable:true}));"
                        "document.documentElement.setAttribute('data-c2',tbRow('会議')+'|'+tbDlg());"
                        "tbDnd('そのうち','明日以降');"
                        "document.documentElement.setAttribute('data-c3',tbDlg());},800);" % self.today)
        self.assertTrue(self.attr(dom, "data-bad").startswith("true,%s," % self.today))
        self.assertIn("明日以後の日付を入れてください", self.attr(dom, "data-bad"))
        self.assertEqual(self.attr(dom, "data-c1"), "今日中,,,,15:00,false|none")
        self.assertEqual(self.attr(dom, "data-c2"), "今日中,,,,15:00,false|none")
        self.assertEqual(self.attr(dom, "data-c3"), "none")
        self.assertEqual(self.file_row("会議"), ("今日中", None, None, None, ["15:00"]))

    def test_replayed_without_deck(self):
        """Deck が居ないと localStorage に残り、読み直した後の再適用でも決めた実施日の形になる。"""
        port = self.free_port()
        dom = self.page("if(n===1){setTimeout(function(){tbDnd('会議','明日以降');"
                        "var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');"
                        "i[0].value='%s';i[1].value='';g.querySelector('.later-due-ok').click();},800);"
                        "setTimeout(function(){location.reload();},2200);}"
                        "else setTimeout(function(){document.documentElement.setAttribute('data-after',tbRow('会議'));},800);" % self.plus(5),
                        port=port, budget=6000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertEqual(self.attr(dom, "data-after"), "明日以降,%s,,,,true" % self.plus(5))
        self.assertEqual(self.file_row("会議"), ("今日中", None, None, None, ["15:00"]))   # Deck が居ないので board.html は変わらない

    # 閉じタグの無い時刻の欄（ブラウザは後ろの要素を中に取り込む）。Deck の key（欄そのものの文字・v2.14）と board.js の key は「0:00|崩れ」。
    # 時刻は 0:00＝いつ走らせても過ぎている（board.js が足す「時刻超過」のチップが欄の中に入る側。時計に左右されない）
    BROKEN = ('<div class="item"><span class="time">0:00<div><p class="task-title">崩れ</p>'
              '<div class="chips"><span class="chip pending">未</span></div></div></div>\n')

    def test_auto_reload_waits_while_asking(self):
        """実施日を聞いている間は、自動の読み直し（5分ごと・日付・Deck の再起動・知らせ。どれも tbReload を通る）を延ばし、入れた値を消さない。
        閉じたら読み直し、閉じた直後の移動の保存は途中で切らない（Deck への要求が答えを待つ間も延ばす）。"""
        self.start_deck()
        # 開いたまま、5分ごとの読み直し（board.js の先頭の 300000 ミリ秒）と Deck の再起動に合わせた読み直しを走らせる
        dom = self.page("if(n===1){setTimeout(function(){tbDnd('会議','明日以降');"
                        "var g=document.querySelector('dialog.later-due');g.querySelectorAll('input')[0].value='%s';"
                        "deckReloadOnce('test',0);tbReload();},800);"
                        "setTimeout(function(){document.documentElement.setAttribute('data-held',tbDlg());},305000);}" % self.plus(2),
                        budget=306000)
        self.assertEqual(self.attr(dom, "data-loads"), "1")
        self.assertEqual(self.attr(dom, "data-held"), "true,%s,%s,15:00,true" % (self.plus(2), self.plus(1)))
        self.assertEqual(self.file_row("会議"), ("今日中", None, None, None, ["15:00"]))
        # 閉じたら読み直す。閉じた直後に送った移動は Deck が書いている
        self.stop_deck()
        self.start_deck()
        dom = self.page("if(n===1){setTimeout(function(){tbDnd('会議','明日以降');tbReload();},800);"
                        "setTimeout(function(){var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');"
                        "i[0].value='%s';i[1].value='';g.querySelector('.later-due-ok').click();},2000);}"
                        "else setTimeout(function(){document.documentElement.setAttribute('data-after',tbRow('会議'));},800);" % self.plus(2),
                        budget=8000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertEqual(self.file_row("会議"), ("明日以降", self.plus(2), None, None, []))
        self.assertEqual(self.attr(dom, "data-after"), "明日以降,%s,,,,true" % self.plus(2))

    def test_auto_reload_waits_for_the_answer(self):
        """閉じた直後に送った移動の答えを待ってから読み直す（答えが失敗なら localStorage に残し、読み直した後も移動が残る）。
        答えを待たずに読み直すと、失敗を受け取れずに移動が消える。ヘッドレスの仮想時間は答えを待つ間は進まないので、この試験は
        数えを外しても通る（数えそのものは test_auto_reload_waits_while_request_pending が見る）。"""
        self.start_deck()
        orig = dw._BoardMoveHandler.do_POST

        def slow_fail(handler):
            if handler.path.startswith("/board/move"):
                handler.rfile.read(int(handler.headers.get("Content-Length") or 0))
                time.sleep(1.2)
                handler._send(500, b'{"ok": false}')
                return
            orig(handler)

        dw._BoardMoveHandler.do_POST = slow_fail
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_POST", orig)
        dom = self.page("if(n===1){setTimeout(function(){tbDnd('会議','明日以降');tbReload();},800);"
                        "setTimeout(function(){var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');"
                        "i[0].value='%s';i[1].value='';g.querySelector('.later-due-ok').click();},1700);}"
                        "else setTimeout(function(){document.documentElement.setAttribute('data-after',tbRow('会議'));},800);" % self.plus(2),
                        budget=8000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertEqual(self.attr(dom, "data-after"), "明日以降,%s,,,,true" % self.plus(2))
        self.assertEqual(self.file_row("会議"), ("今日中", None, None, None, ["15:00"]))

    def test_auto_reload_waits_while_request_pending(self):
        """Deck への要求（deckFetch）は答えを受けるまで数え、その間は自動の読み直しを延ばす。手で押した読み直しは長くは待たない。
        （ヘッドレスの仮想時間は要求の答えを待つ間は進まないので、数えたものを直に見る）"""
        self.start_deck()
        dom = self.page("if(n===1){setTimeout(function(){var c0=tbDeckInFlight;var p=deckFetch('/notifications');var c1=tbDeckInFlight;"
                        "p.then(function(){sessionStorage.setItem('count',[c0,c1,tbDeckInFlight].join(','));"
                        "tbDeckInFlight++;tbReload();"
                        "setTimeout(function(){sessionStorage.setItem('held',document.documentElement.getAttribute('data-loads'));"
                        "tbDeckInFlight--;},3000);});},800);}"
                        "else document.documentElement.setAttribute('data-held',sessionStorage.getItem('count')+'|'+sessionStorage.getItem('held'));",
                        budget=8000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertEqual(self.attr(dom, "data-held"), "0,1,0|1")   # 3 秒間は読み直さず、数えが 0 に戻ってから読み直した
        # 手で押した読み直しは、答えを待つ要求が残っていても TB_HOLD_MANUAL_MS で読み直す
        self.stop_deck()
        self.start_deck()
        dom = self.page("if(n===1){setTimeout(function(){tbDeckInFlight++;tbReload(true);},800);}", budget=5000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")

    def test_reload_recheck_after_verify(self):
        """配った板で、確かめ（/ping）を待つ間に入力欄が開いたら、確かめが済んでも読み直さない。"""
        self.start_deck()
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){tbReload();tbDnd('会議','明日以降');},800);"
            "setTimeout(function(){document.documentElement.setAttribute('data-held',tbDlg());},4000);}"))
        dom = self.open_page(self.served_url(), budget=5000)
        self.assertEqual(self.attr(dom, "data-loads"), "1")
        self.assertTrue(self.attr(dom, "data-held").startswith("true,"))

    # Date を差し替え、tbShift(ミリ秒) で時計を進められるようにする（読み直すと元に戻る）
    DATE_STUB = ("<script>(function(){var R=Date,off=0;function F(){if(!(this instanceof F))return R();"
                 "if(arguments.length===0)return new R(R.now()+off);"
                 "return new (Function.prototype.bind.apply(R,[null].concat([].slice.call(arguments))))();}"
                 "F.now=function(){return R.now()+off;};F.prototype=R.prototype;F.UTC=R.UTC;F.parse=R.parse;"
                 "window.Date=F;window.tbShift=function(ms){off=ms;};})();</script>")
    DAY_MSG = "日付が変わったので、ボードを読み直しました。もう一度操作してください"

    def day_page(self, first, budget=6000):
        """1回目の読み込みで first を走らせ（その中で tbShift で日付を進める）、2回目の読み込みで行と知らせを書く。"""
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){%s},1500);}"
            "else setTimeout(function(){var t=document.querySelector('.tb-day-changed');"
            "document.documentElement.setAttribute('data-after',tbRow('会議')+'|'+tbRow('いつか')+'|'+(t?t.textContent:'none'));},800);"
            % first))
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<script src="board.js"></script>', self.DATE_STUB + '<script src="board.js"></script>', 1))
        return self.open_page(self.board, budget=budget)

    STOP_MSG = "日付が変わったので、この操作は保存していません。ボードを読み直します"

    def stub_date(self):
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<script src="board.js"></script>', self.DATE_STUB + '<script src="board.js"></script>', 1))

    def test_day_change_unverified_tells_at_once_and_keeps_row(self):
        """配った板で Deck を確かめられない（読み直しが待つ）間に日付が変わって D&D すると、行は元の位置のまま動かさず、その場で
        保存していないことを知らせる。読み直さなかったので、読み直した後の知らせの印は残さない。"""
        self.start_deck()
        orig = dw._BoardMoveHandler.do_GET

        def do_get(handler):
            if handler.path.startswith("/ping"):
                handler._send(200, b"deck-board-mover", "text/plain; charset=utf-8")   # 証しを返さない＝確かめられない
                return
            orig(handler)

        dw._BoardMoveHandler.do_GET = do_get
        self.addCleanup(setattr, dw._BoardMoveHandler, "do_GET", orig)
        del POSTS[:]
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "setTimeout(function(){tbShift(86400000);tbDnd('いつか','今日中');"
            "document.documentElement.setAttribute('data-now',tbRow('いつか'));},1000);"
            "setTimeout(function(){var ts=Array.prototype.map.call(document.querySelectorAll('#toast-area .toast'),function(e){return e.textContent;}).join('/');"
            "document.documentElement.setAttribute('data-q',tbRow('いつか')+'|'+ts+'|'+sessionStorage.getItem('tbDayNotice'));},20000);"))
        self.stub_date()
        dom = self.open_page(self.served_url(), budget=22000)
        self.assertEqual(self.attr(dom, "data-loads"), "1")
        self.assertEqual(self.attr(dom, "data-now").split(",")[0], "明日以降")     # 落とした直後も動いていない
        q = self.attr(dom, "data-q").split("|")
        self.assertEqual(q[0].split(",")[0], "明日以降")
        self.assertEqual(q[1], self.STOP_MSG)                                      # 1件だけ
        self.assertEqual(q[2], "null")
        self.assertNotIn("/board/move", POSTS)
        self.assertEqual(self.file_row("いつか")[0], "明日以降")

    # DATE_STUB と同じだが、tbShift で進めた時計を sessionStorage に残し、読み直した後も進めたままにする
    # （読み直した後の板が今日のものでない＝前の日の板のまま、を作る）
    DATE_STUB_KEEP = ("<script>(function(){var R=Date,off=+(sessionStorage.getItem('tbOff')||0);function F(){if(!(this instanceof F))return R();"
                      "if(arguments.length===0)return new R(R.now()+off);"
                      "return new (Function.prototype.bind.apply(R,[null].concat([].slice.call(arguments))))();}"
                      "F.now=function(){return R.now()+off;};F.prototype=R.prototype;F.UTC=R.UTC;F.parse=R.parse;"
                      "window.Date=F;window.tbShift=function(ms){off=ms;sessionStorage.setItem('tbOff',String(ms));};})();</script>")
    UNSAVED = "日付が変わったので、前の画面での操作は保存していません。"

    def stale_after_reload(self, budget, deck):
        """1回目の読み込みで日付を進めて D&D し、読み直した後も前の日の板のまま（Deck は今日の板を作らない）にする。
        最後の読み込みで、トースト・知らせの本文・直し方の欄・読み込みの回数を書く。"""
        port = None
        if deck:
            self.start_deck()
        else:
            port = self.free_port()   # 誰も受けていないポート＝Deck が止まっている
        self.write_board(port=port, rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){tbShift(86400000);tbDnd('いつか','今日中');},1500);}"
            "else setTimeout(function(){var e=document.getElementById('tb-board-notice');var f=e&&e.querySelector('.tb-notice-fix');"
            "document.documentElement.setAttribute('data-q',[" + self.TOASTS_JS + ",e&&!e.hidden?e.textContent:'none',f?f.textContent:'none',"
            "String(sessionStorage.getItem('tbDayNotice'))].join('|'));},3000);"))
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<script src="board.js"></script>', self.DATE_STUB_KEEP + '<script src="board.js"></script>', 1))
        dom = self.open_page(self.board, budget=budget)
        return dom, self.attr(dom, "data-q").split("|")

    def test_day_change_to_stale_board_asks_for_today_board(self):
        """読み直した後の板が今日のものでない（Deck が止まっている）ときは「もう一度操作してください」を出さない（操作しても保存されない）。
        代わりに「書き込み停止中」の知らせの頭に、保存していないことを足し、直し方の欄が「今日のボードを作って」と頼むよう案内する（トーストは出さない）。"""
        dom, q = self.stale_after_reload(8000, deck=False)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        toasts, notice, fix, mark = q
        self.assertNotIn(self.DAY_MSG, toasts)
        self.assertNotIn(self.UNSAVED, toasts)                      # トーストと知らせの二重には出さない
        self.assertIn("書き込み停止中", notice)
        self.assertIn(" — " + self.UNSAVED + "このボードは", notice)  # 知らせの本文の頭
        self.assertEqual(notice.count(self.UNSAVED), 1)
        self.assertIn("今日のボードを作って", fix)
        self.assertEqual(mark, "null")
        self.assertEqual(self.file_row("いつか")[0], "明日以降")

    def test_day_change_to_stale_board_waits_out_grace(self):
        """Deck が動いていて前の日の板のままのとき、知らせは読み込みから 90 秒待つ（60 秒で1回読み直す）。保存していないことの知らせは
        その読み直しの先へ持ち越し、待ち終えた後の知らせの頭に出す。"""
        dom, q = self.stale_after_reload(75000, deck=True)
        self.assertEqual(self.attr(dom, "data-loads"), "3")
        toasts, notice, fix, mark = q
        self.assertNotIn(self.DAY_MSG, toasts)
        self.assertIn(" — " + self.UNSAVED + "このボードは", notice)
        self.assertIn("今日のボードを作って", fix)
        self.assertEqual(mark, "null")

    def test_day_notice_once(self):
        """読み直した後の知らせは1回だけ出る（もう一度読み直すと出ない）。"""
        self.start_deck()
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){tbShift(86400000);tbDnd('いつか','今日中');},1500);}"
            "else if(n===2){setTimeout(function(){var t=document.querySelector('.tb-day-changed');"
            "sessionStorage.setItem('t2',t?t.textContent:'none');location.reload();},800);}"
            "else setTimeout(function(){document.documentElement.setAttribute('data-q',sessionStorage.getItem('t2')+'|'"
            "+(document.querySelector('.tb-day-changed')?'1':'0'));},800);"))
        self.stub_date()
        dom = self.open_page(self.board, budget=8000)
        self.assertEqual(self.attr(dom, "data-loads"), "3")
        self.assertEqual(self.attr(dom, "data-q"), self.DAY_MSG + "|0")

    def test_day_change_ack_is_sent_after_reload_and_not_shown_again(self):
        """日付が変わった後に通知を閉じると、その場では確認を送らずに読み直し、読み直した後のページが確認を送る（閉じた通知を出し直さない）。"""
        acked = self.spy_ack()
        item = {"key": "15:00|会議", "time": "15:00", "title": "会議", "at": "00:00:01"}
        self.start_deck(pending=[item])
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){var t=document.querySelector('#toast-area .toast');"
            "sessionStorage.setItem('t1',t?t.textContent:'none');tbShift(86400000);if(t)t.click();},5000);}"
            "else setTimeout(function(){var ts=Array.prototype.map.call(document.querySelectorAll('#toast-area .toast'),function(e){return e.textContent;}).join('/');"
            "document.documentElement.setAttribute('data-q',sessionStorage.getItem('t1')+'|'+ts);},5000);"))
        self.stub_date()
        dom = self.open_page(self.board, budget=14000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")       # その場では送らずに読み直した
        t1, shown = self.attr(dom, "data-q").split("|", 1)
        self.assertIn("会議", t1)                                  # 前のページでは出ていた
        self.assertNotIn("会議", shown)                            # 読み直した後には出ない
        self.assertEqual(acked, ["15:00|会議"])                    # 読み直した後のページが1回だけ送った
        self.assertEqual(self.pending_keys(), [])                  # 本物の SoundStore が未確認から外した

    def fake_notifications(self, pending):
        """Deck の未確認の通知を pending(呼ばれた回数) で返し、確認された鍵を返すリストに積む。

        SoundStore を差し替える道具。未確認の通知が答えの回ごとに現れたり消えたりする並びは、本物の SoundStore を
        差し替えずには作れないので、その並びが要る試験（test_carried_ack_applies_to_first_answer_only）だけに使う。
        確認が本物の SoundStore に届いて sound.json から外れることは、spy_ack と pending_keys を使う試験で見る。"""
        calls, acked = [], []
        o_p, o_a = dw.SoundStore.pending, dw.SoundStore.ack

        def fake(s):
            calls.append(1)
            return pending(len(calls))
        dw.SoundStore.pending = fake
        dw.SoundStore.ack = lambda s, keys: (acked.extend(keys), len(keys))[1]
        self.addCleanup(setattr, dw.SoundStore, "pending", o_p)
        self.addCleanup(setattr, dw.SoundStore, "ack", o_a)
        return acked

    TOASTS_JS = ("Array.prototype.map.call(document.querySelectorAll('#toast-area .toast'),function(e){return e.textContent;}).join('/')")

    def test_carried_ack_applies_to_first_answer_only(self):
        """持ち越した鍵は、読み直した後の最初の答えにだけ当てる。後から来た同じ鍵の通知（毎日のルーチンなど）は出し、確認もしない。"""
        item = {"key": "15:00|会議", "time": "15:00", "title": "会議", "at": "00:00:01"}
        # 1〜2回目（前のページ）と6回目以後に通知がある。3〜5回目（読み直した後の最初の答えを含む）には無い
        acked = self.fake_notifications(lambda n: [dict(item)] if (n <= 2 or n >= 6) else [])
        self.start_deck()
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){var t=document.querySelector('#toast-area .toast');"
            "sessionStorage.setItem('t1',t?t.textContent:'none');tbShift(86400000);if(t)t.click();},4000);}"
            "else setTimeout(function(){document.documentElement.setAttribute('data-q',sessionStorage.getItem('t1')+'|'+" + self.TOASTS_JS + ");},20000);"))
        self.stub_date()
        dom = self.open_page(self.board, budget=26000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        t1, shown = self.attr(dom, "data-q").split("|", 1)
        self.assertIn("会議", t1)
        self.assertIn("⏰ 15:00 会議", shown)     # 後から来た同じ鍵の通知は出る
        self.assertEqual(acked, [])               # 最初の答えに無かった鍵は、持ち越しから確認しない

    def test_carried_ack_is_for_the_same_board_only(self):
        """持ち越した鍵は、同じ板（このページの板の URL）にだけ当てる。別の板の鍵なら、その板の通知は出す。"""
        item = {"key": "15:00|会議", "time": "15:00", "title": "会議", "at": "00:00:01"}
        acked = self.spy_ack()
        self.start_deck(pending=[item])
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){sessionStorage.setItem('tbAckLater',JSON.stringify({board:'file:///C:/other/board.html',closed:{'15:00|会議':Date.now()}}));"
            "location.reload();},500);}"
            "else setTimeout(function(){document.documentElement.setAttribute('data-q'," + self.TOASTS_JS + ");},4000);"))
        dom = self.open_page(self.board, budget=8000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertIn("⏰ 15:00 会議", self.attr(dom, "data-q"))
        self.assertEqual(acked, [])
        self.assertEqual(self.pending_keys(), ["15:00|会議"])

    def test_carried_ack_skips_notice_added_after_close(self):
        """持ち越した鍵は、Deck がその通知を積んだ時刻（at）が閉じた時刻より前の項目にだけ当てる。閉じた後に積まれた同じ鍵の通知
        （ほぼ同時に鳴った今日の通知）は出し、確認しない。at は秒までなので、閉じたのと同じ秒に積まれた通知も後とみなして出す。
        at の無い項目にも当てない。閉じたより前に積まれた項目は従来どおり出さずに確認する（閉じた時刻は今日の 12:00:00.5 に固定）。"""
        items = [{"key": "09:00|朝会", "time": "09:00", "title": "朝会", "at": "11:59:59"},   # 閉じたより前
                 {"key": "10:00|点検", "time": "10:00", "title": "点検", "at": "12:00:00"},   # 閉じたのと同じ秒
                 {"key": "15:00|会議", "time": "15:00", "title": "会議", "at": "12:30:00"},   # 閉じた後
                 {"key": "16:00|日報", "time": "16:00", "title": "日報"}]                      # at が無い
        acked = self.spy_ack()
        self.start_deck(pending=items)
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){var d=new Date(),c={};"
            "c['09:00|朝会']=c['10:00|点検']=c['15:00|会議']=c['16:00|日報']=new Date(d.getFullYear(),d.getMonth(),d.getDate(),12,0,0).getTime()+500;"
            "sessionStorage.setItem('tbAckLater',JSON.stringify({board:DECK_BOARD,closed:c}));location.reload();},500);}"
            "else setTimeout(function(){document.documentElement.setAttribute('data-q'," + self.TOASTS_JS + ");},4000);"))
        dom = self.open_page(self.board, budget=8000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        shown = self.attr(dom, "data-q")
        self.assertIn("⏰ 15:00 会議", shown)      # 閉じた後に積まれた通知は出る
        self.assertIn("⏰ 10:00 点検", shown)      # 閉じたのと同じ秒に積まれた通知も出る
        self.assertIn("⏰ 16:00 日報", shown)      # at の無い通知も出る
        self.assertNotIn("朝会", shown)            # 閉じたより前に積まれた通知は出さない
        self.assertEqual(acked, ["09:00|朝会"])    # 確認として送るのは閉じたより前の分だけ
        self.assertEqual(self.pending_keys(), ["10:00|点検", "15:00|会議", "16:00|日報"])   # 本物の SoundStore が外したのもその分だけ

    def test_inflight_count_drops_once(self):
        """答えが 1.5 秒の打ち切りの直後に来ても、数えは一度だけ減らす（負にならない）。打ち切りの時計が先に減らし、答えでもう一度減らさない。"""
        self.start_deck()
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "setTimeout(function(){var c0=tbDeckInFlight;deckFetch('/x-test');"
            "setTimeout(function(){document.documentElement.setAttribute('data-c',c0+','+tbDeckInFlight);},3000);},1000);"))
        fake = ("<script>window.fetch=function(u){if(String(u).indexOf('/x-test')>=0)return new Promise(function(r){"
                "setTimeout(function(){r(new Response('{}'));},1600);});return Promise.reject(new Error('off'));};</script>")
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<script src="board.js"></script>', fake + '<script src="board.js"></script>', 1))
        dom = self.open_page(self.board, budget=6000)
        self.assertEqual(self.attr(dom, "data-c"), "0,0")

    def test_day_change_while_asking_on_stale_board_keeps_local(self):
        """今日でない板（読み込んだときに発行済みボード判定が偽）で入力欄を開いたまま日付が変わっても、「この日にする」「未定にする」は
        ほかの操作と同じく localStorage に残す（日付が変わったときの例外は、今日のボードとして読み込んだページだけ）。Deck へは送らない。"""
        self.start_deck()
        yday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        for act, due in (("i[0].value='%s';i[1].value='';g.querySelector('.later-due-ok').click();" % self.plus(3), self.plus(3)),
                         ("g.querySelector('.later-due-none').click();", "")):
            with self.subTest(act=act[-30:]):
                del POSTS[:]
                self.write_board(date=yday, rows=self.rows(), extra=self.SCRIPT % (
                    "if(n===1){setTimeout(function(){tbDnd('会議','明日以降');tbShift(86400000);"
                    "var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');" + act +
                    "document.documentElement.setAttribute('data-now',tbRow('会議')+'|'+" + self.TOASTS_JS + ");"
                    "sessionStorage.setItem('now',document.documentElement.getAttribute('data-now'));"
                    "setTimeout(function(){location.reload();},500);},1500);}"
                    "else setTimeout(function(){document.documentElement.setAttribute('data-q',sessionStorage.getItem('now')+'|'+tbRow('会議')+'|'"
                    "+" + self.TOASTS_JS + ");},800);"))
                self.stub_date()
                dom = self.open_page(self.board, budget=6000)
                self.assertEqual(self.attr(dom, "data-loads"), "2")
                q = self.attr(dom, "data-q").split("|")
                self.assertEqual(q[0].split(",")[:2], ["明日以降", due])      # その場で動いた
                self.assertNotIn(self.STOP_MSG, q[1])                         # 日付が変わったとして止めない
                self.assertEqual(q[2].split(",")[:2], ["明日以降", due])      # 読み直した後も localStorage から当たる
                self.assertNotIn(self.DAY_MSG, q[3])
                self.assertNotIn("/board/move", POSTS)
                self.assertEqual(self.file_row("会議"), ("今日中", None, None, None, ["15:00"]))
                shutil.rmtree(self.profile, ignore_errors=True)   # 次の subTest のために localStorage を消す

    def test_day_change_while_asking_does_not_write(self):
        """入力欄を開いたまま日付が変わると、「この日にする」「未定にする」で Deck へ送らず、localStorage にも残さず、読み直して知らせる
        （日付が変わった直後の読み直しは入力欄を閉じるまで延びるので、昨日の板の判定のまま書かないため）。"""
        self.start_deck()
        for act in ("i[0].value='%s';i[1].value='';g.querySelector('.later-due-ok').click();" % self.plus(3),
                    "g.querySelector('.later-due-none').click();"):
            with self.subTest(act=act[-30:]):
                del POSTS[:]
                dom = self.day_page("tbDnd('会議','明日以降');tbShift(86400000);tbReload();"
                                    "var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');" + act)
                self.assertEqual(self.attr(dom, "data-loads"), "2")
                after = self.attr(dom, "data-after").split("|")
                self.assertEqual(after[0].split(",")[0], "今日中")          # localStorage にも残っていない
                self.assertEqual(after[2], self.DAY_MSG)
                self.assertNotIn("/board/move", POSTS)
                self.assertEqual(self.file_row("会議"), ("今日中", None, None, None, ["15:00"]))

    def test_day_change_before_plain_move_does_not_write(self):
        """日付が変わった後の D&D（入力欄の出ない移動）も送らず、localStorage にも残さない。"""
        self.start_deck()
        dom = self.day_page("tbShift(86400000);tbDnd('いつか','今日中');")
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        after = self.attr(dom, "data-after").split("|")
        self.assertEqual(after[1].split(",")[0], "明日以降")
        self.assertEqual(after[2], self.DAY_MSG)
        self.assertNotIn("/board/move", POSTS)

    def test_day_change_while_editing_time_does_not_write(self):
        """✎ の入力欄を開いたまま日付が変わると、確定しても Deck へ送らず、読み直して知らせる。"""
        self.start_deck()
        before = self.sound_bytes()
        dom = self.day_page("var te=tbItem('会議').querySelector('.time');te.click();var inp=te.querySelector('input');"
                            "inp.value='16:45';tbShift(86400000);"
                            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertEqual(self.attr(dom, "data-after").split("|")[2], self.DAY_MSG)
        self.assertNotIn("/board/times", POSTS)
        self.assertEqual(self.sound_bytes(), before)

    def test_day_change_before_sound_setting_does_not_write(self):
        """日付が変わった後の通知音の設定も送らない。"""
        self.start_deck(enabled=False)
        before = self.sound_bytes()
        dom = self.day_page("tbShift(86400000);document.getElementById('sound-toggle').click();")
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertEqual(self.attr(dom, "data-after").split("|")[2], self.DAY_MSG)
        self.assertNotIn("/sound/config", POSTS)
        self.assertEqual(self.sound_bytes(), before)

    # 1回目の読み込みで、トーストと通知音の欄の知らせ（#sound-note）を出たものから順に sessionStorage の 'seen' へ積み、
    # PATH を読む（GET）答えが返った時点で日付を進める（＝読む→送るの途中で日付が変わる）。2回目の読み込みで seen と読み直した後の知らせを書く
    MID_DAY_JS = (
        "if(n===1){var seen=[];function rec(){var a=Array.prototype.map.call(document.querySelectorAll('#toast-area .toast'),"
        "function(e){return e.textContent;});var s=document.getElementById('sound-note');"
        "if(s&&!s.hidden&&s.textContent)a.push('note:'+s.textContent);"
        "a.forEach(function(x){if(seen.indexOf(x)<0)seen.push(x);});sessionStorage.setItem('seen',JSON.stringify(seen));}"
        "new MutationObserver(rec).observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true});"
        "var of=window.fetch;window.fetch=function(u,o){var p=of.apply(this,arguments);"
        "if(window.tbShiftOnRead&&String(u).indexOf('%s')>=0&&!(o&&o.method==='POST')){window.tbShiftOnRead=false;"
        "return p.then(function(r){tbShift(86400000);return r;});}return p;};"
        "setTimeout(function(){%s},1500);}"
        "else setTimeout(function(){var t=document.querySelector('.tb-day-changed');"
        "document.documentElement.setAttribute('data-q',sessionStorage.getItem('seen')+'|'+(t?t.textContent:'none'));},800);")

    def mid_day_page(self, path, op):
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (self.MID_DAY_JS % (path, op)))
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        t = t.replace('<button id="sound-test"></button>', '<button id="sound-test"></button><p id="sound-note" hidden></p>', 1)
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<script src="board.js"></script>', self.DATE_STUB + '<script src="board.js"></script>', 1))
        dom = self.open_page(self.board, budget=8000)
        seen, after = self.attr(dom, "data-q").split("|")
        return dom, json.loads(seen), after

    def test_day_change_during_time_read_tells_once(self):
        """✎ の確定で、読む→送るの途中（読んだ答えが返った時点）で日付が変わると、送らずに読み直し、知らせはその場の1件だけ
        （deckPost が止めたのを「Deck に届かなかった」と取り違えて2件目を出さない・2026-11-06）。読み直した後の知らせも1件。"""
        self.start_deck()
        before = self.sound_bytes()
        del POSTS[:]
        dom, seen, after = self.mid_day_page(
            "/board/times",
            "var te=tbItem('会議').querySelector('.time');te.click();var inp=te.querySelector('input');inp.value='16:45';"
            "window.tbShiftOnRead=true;inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertEqual(seen, [self.STOP_MSG])          # 「Deck に届かなかった可能性があります」を出さない
        self.assertEqual(after, self.DAY_MSG)
        self.assertNotIn("/board/times", POSTS)
        self.assertEqual(self.sound_bytes(), before)

    def test_day_change_during_sound_read_tells_once(self):
        """通知音の設定でも、読む→送るの途中で日付が変わると、送らずに読み直し、知らせはその場の1件だけ（通知音の欄に
        「Deck に届かなかった可能性があります」を出さない）。読み直した後の知らせも1件。"""
        self.start_deck(enabled=False)
        before = self.sound_bytes()
        del POSTS[:]
        dom, seen, after = self.mid_day_page(
            "/sound/config", "window.tbShiftOnRead=true;document.getElementById('sound-toggle').click();")
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        self.assertEqual(seen, [self.STOP_MSG])
        self.assertEqual(after, self.DAY_MSG)
        self.assertNotIn("/sound/config", POSTS)
        self.assertEqual(self.sound_bytes(), before)

    def test_same_day_still_writes(self):
        """日付が変わっていなければ、従来どおり送る（day_page の負の対照）。"""
        self.start_deck()
        dom = self.day_page("tbDnd('いつか','今日中');")
        self.assertEqual(self.attr(dom, "data-loads"), "1")
        self.assertIn("/board/move", POSTS)
        self.assertEqual(self.file_row("いつか")[0], "今日中")

    def test_hung_request_without_abortcontroller_stops_holding(self):
        """AbortController の無いブラウザで要求が戻らなくても、1.5 秒で数えから外し、読み直しを延ばし続けない。"""
        self.start_deck()
        self.write_board(rows=self.rows(), extra=self.SCRIPT % (
            "if(n===1){setTimeout(function(){tbDnd('いつか','今日中');tbReload();},800);}"))
        hang = ("<script>window.AbortController=undefined;var tbOrigFetch=window.fetch;window.fetch=function(u,o){"
                "if(String(u).indexOf('/board/move')>=0)return new Promise(function(){});return tbOrigFetch.apply(this,arguments);};</script>")
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t.replace('<script src="board.js"></script>', hang + '<script src="board.js"></script>', 1))
        dom = self.open_page(self.board, budget=6000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")

    def test_reload_waits_during_time_read_then_post(self):
        """✎ の確定は、読む→送るの途中（読んだ答えから送るまでの間を含む）も読み直しを延ばす（timesBusy）。
        ヘッドレスの仮想時間は要求の答えを待つ間は進まないので、要求の数えを外した状態で、延ばす判定（tbReloadHeld）を直に見る。"""
        self.start_deck()
        dom = self.page("setTimeout(function(){var te=tbItem('会議').querySelector('.time');te.click();"
                        "var inp=te.querySelector('input');inp.value='16:45';"
                        "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));"
                        "var c=tbDeckInFlight;tbDeckInFlight=0;var h=tbReloadHeld();tbDeckInFlight=c;"
                        "document.documentElement.setAttribute('data-held',String(h));},1500);", budget=4000)
        self.assertEqual(self.attr(dom, "data-held"), "true")
        self.assertEqual(self.state()[2], {KEY: "23:30", "15:00|会議": "16:45"})   # 送り終えている

    def test_auto_reload_waits_while_editing_time(self):
        """✎ の時刻の入力欄が開いている間も、自動の読み直しを延ばす。"""
        self.start_deck()
        dom = self.page("if(n===1){setTimeout(function(){tbItem('会議').querySelector('.time').click();tbReload();},1500);"
                        "setTimeout(function(){var i=document.querySelector('.item .time input');"
                        "document.documentElement.setAttribute('data-held',i?'open':'none');},4000);}", budget=5000)
        self.assertEqual(self.attr(dom, "data-loads"), "1")
        self.assertEqual(self.attr(dom, "data-held"), "open")

    def test_broken_time_row_cannot_get_a_date(self):
        """閉じタグの無い時刻の欄の行は、日付を決めて移せない（Deck の _later_due_shape も None で 400）。入力欄はそれを知らせ、日付の欄を
        使えなくする。未定は移せる（Deck も時刻の欄に触れない）。localStorage の記録の再適用でも、日付の付く移動は当てない。"""
        self.start_deck()
        self.write_board(rows=self.rows(self.BROKEN), extra=self.SCRIPT % (
            "setTimeout(function(){tbDnd('崩れ','明日以降');var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');"
            "document.documentElement.setAttribute('data-dlg',[i[0].disabled,i[1].disabled,g.querySelector('.later-due-ok').disabled,"
            "g.querySelector('.later-due-msg').textContent].join('|'));"
            "g.querySelector('.later-due-ok').click();"
            "document.documentElement.setAttribute('data-c1',tbRow('崩れ')+'|'+tbDlg());"
            "g.querySelector('.later-due-none').click();"
            "document.documentElement.setAttribute('data-c2',tbRow('崩れ')+'|'+tbItem('崩れ').querySelectorAll('.task-title').length);},800);"))
        dom = self.open_page(self.board, budget=4000)
        dlg = self.attr(dom, "data-dlg").split("|")
        self.assertEqual(dlg[:3], ["true", "true", "true"])
        self.assertIn("時刻の欄の形が崩れているため、日付を決めて移せません", dlg[3])
        self.assertEqual(self.attr(dom, "data-c1").split("|")[0].split(",")[0], "今日中")   # 「この日にする」は効かない
        # 時刻の入力欄には行の時刻（鍵と同じ読み方の「0:00」＝v2.15）が初めから入る（v2.14 までは欄の文字全体を読み、H:MM でないので空だった）
        self.assertTrue(self.attr(dom, "data-c1").endswith("|true,,%s,00:00,true" % self.plus(1)), self.attr(dom, "data-c1"))
        c2 = self.attr(dom, "data-c2").split("|")
        self.assertEqual((c2[0].split(",")[0], c2[1]), ("明日以降", "1"))                  # 未定は移り、中身は壊さない
        self.assertEqual(self.wait_file_row("崩れ", "明日以降")[0], "明日以降")   # Deck が書き終えるのを待つ
        # Deck は同じ行に日付を当てない（400）。今日中に置いた板で確かめる
        with open(self.board, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.count(self.BROKEN), 1)
        text = text.replace(self.BROKEN, "", 1).replace(
            '<div class="section-label">今日中</div>\n', '<div class="section-label">今日中</div>\n' + self.BROKEN, 1)
        lines = text.splitlines(True)
        k = [dw._item_key("".join(lines[s:e + 1])) for (s, e, name) in dw._scan_board(lines)[1]
             if name == "今日中" and "崩れ" in "".join(lines[s:e + 1])]
        self.assertEqual(k, ["0:00|崩れ"])   # 鍵の時刻の部分は欄そのものの文字（Deck v2.14）
        _new, code, msg = dw.apply_board_move(text, k[0], "明日以降", today=datetime.date.today(), due=self.plus(2), set_due=True)
        self.assertEqual((code, msg), (400, "実施日を当てられない形の行です"))
        # localStorage の記録（Deck が居ないときに残る形）の再適用でも、日付の付く移動は当てずに今日中に残す
        self.stop_deck()
        port = self.free_port()
        self.seed({"tb:mv:" + self.today: json.dumps([{"k": k[0], "sec": "明日以降", "before": None, "due": self.plus(2)},
                                                      {"k": "15:00|会議", "sec": "明日以降", "before": None, "due": self.plus(2)}])})
        self.write_board(port=port, rows=self.rows(self.BROKEN), extra=self.SCRIPT % (
            "setTimeout(function(){document.documentElement.setAttribute('data-r',tbRow('崩れ')+'|'+tbRow('会議'));},800);"))
        dom = self.open_page(self.board, budget=3000)
        r = self.attr(dom, "data-r").split("|")
        self.assertEqual(r[0].split(",")[:2], ["今日中", ""])
        self.assertEqual(r[1], "明日以降,%s,,,,true" % self.plus(2))

    def test_broken_time_key_ignores_added_chips(self):
        """閉じタグの無い時刻の欄には、board.js が足すチップ（「時刻超過」「▶ 次」）がそのまま入る。それでも行の鍵（D&D の要求・
        localStorage の記録）と通知の鍵は HTML の文字のまま変わらず、Deck の鍵（_item_key・read_board_alarms）と合う。
        時刻は 0:00（いつでも過ぎている＝時刻超過）と 23:58（setUp が 23:50 以後を飛ばすので、いつでも先＝▶ 次）で、時計に依らない。"""
        for hm, chip, first in (("0:00", "時刻超過", "23:59"), ("23:58", "▶ 次", "0:00")):
            with self.subTest(hm=hm):
                self.stop_deck()   # 前の subTest が途中で落ちて受信が残っていても、ここで閉じる
                self.start_deck()
                broken = self.BROKEN.replace(">0:00<", ">%s<" % hm, 1)
                rows = ('\n<div class="section-label">今日中</div>\n' + broken
                        + '<div class="section-label">明日以降</div>\n<div class="item flat"><div><p class="task-title">いつか</p></div></div>\n')
                # 今日の予定の「試験」の時刻（first）。23:58 の行を最初の未来の行（▶ 次）にするときは 0:00（過ぎている）にする
                self.write_board(rows=rows, time=first, extra=self.SCRIPT % (
                    "setTimeout(function(){var d=document.querySelector('header .date').textContent.trim();"
                    "document.documentElement.setAttribute('data-shown',tbItem('崩れ').querySelector('.time').textContent);"
                    "document.documentElement.setAttribute('data-fired',localStorage.getItem('tb:fired:'+d)||'[]');"
                    "var of=window.fetch;window.fetch=function(u,o){if(String(u).indexOf('/board/move')>=0)"
                    "document.documentElement.setAttribute('data-mvk',JSON.parse(o.body).k);return of.apply(this,arguments);};"
                    "tbDnd('崩れ','明日以降');document.querySelector('dialog.later-due .later-due-none').click();},800);"))
                with open(self.board, encoding="utf-8") as f:
                    lines = f.read().splitlines(True)
                want = [dw._item_key("".join(lines[s:e + 1])) for (s, e, name) in dw._scan_board(lines)[1]
                        if "崩れ" in "".join(lines[s:e + 1])]
                self.assertEqual(want, ["%s|崩れ" % hm])
                self.assertEqual([a[0] for a in dw.read_board_alarms(self.board) if "崩れ" in a[0]], want)
                dom = self.open_page(self.board, budget=4000)
                self.assertIn(chip, self.attr(dom, "data-shown"))              # 足したチップは欄の中に入っている（前提）
                self.assertEqual([self.attr(dom, "data-mvk")], want)                 # Deck へ送った鍵（localStorage の記録も同じ鍵）
                self.assertEqual(self.wait_file_row("崩れ", "明日以降")[0], "明日以降")          # Deck が同じ鍵で見つけて移した
                # 同じプロファイルなので、前の subTest の行の記録も残る。この行の時刻で始まるものだけを見る
                fired = [k for k in json.loads(self.attr(dom, "data-fired")) if "崩れ" in k and k.startswith(hm)]
                self.assertEqual(fired, want if chip == "時刻超過" else [])     # 通知の鍵も Deck と同じ（先の行はまだ鳴らない）
                self.stop_deck()

    def test_broken_time_hidden_done_row_stays_hidden(self):
        """閉じタグの無い時刻の欄の済の行を × で隠すと、× のボタンも欄の中に入る。読み直した後も同じ鍵で隠れたまま。"""
        self.start_deck()
        done = self.BROKEN.replace('chip pending">未', 'chip done">済', 1)
        self.write_board(rows='\n<div class="section-label">今日中</div>\n' + done, extra=self.SCRIPT % (
            "setTimeout(function(){var d=document.querySelector('header .date').textContent.trim();"
            "if(n===1){tbItem('崩れ').querySelector('.task-hide-btn').click();location.reload();return;}"
            "document.documentElement.setAttribute('data-h',tbItem('崩れ').classList.contains('tb-task-hidden')+'|'"
            "+localStorage.getItem('tb:hideTask:'+d));},800);"))
        dom = self.open_page(self.board, budget=5000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        h = self.attr(dom, "data-h").split("|", 1)
        self.assertEqual(h[0], "true")
        self.assertEqual(json.loads(h[1]), ["0:00|崩れ"])

    def test_overridden_mark_is_cleared(self):
        """✎ で上書きした時刻の行を「明日以降」へ落とすと、✎ の跡（overridden）を外し、時刻の欄は決めた時刻か元の時刻を出す
        （「明日以降」の行は ✎ を受けない）。"""
        js = ("setTimeout(function(){var te=tbItem('会議').querySelector('.time');"
              "document.documentElement.setAttribute('data-b',te.textContent+'|'+te.classList.contains('overridden'));"
              "tbDnd('会議','明日以降');var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');%s"
              "te=tbItem('会議').querySelector('.time');"
              "document.documentElement.setAttribute('data-a',te?te.textContent+'|'+te.classList.contains('overridden'):'none');},1500);")
        for act, want in (("g.querySelector('.later-due-none').click();", "15:00|false"),
                          ("i[0].value='%s';i[1].value='09:30';g.querySelector('.later-due-ok').click();" % self.plus(2), "9:30|false")):
            with self.subTest(want=want):
                self.stop_deck()
                self.start_deck(ovr={"15:00|会議": "16:10"})
                dom = self.page(js % act, budget=3000)
                self.assertEqual(self.attr(dom, "data-b"), "16:10|true")
                self.assertEqual(self.attr(dom, "data-a"), want)


LATER_MSG = "「明日以降」の行の時刻は、ここでは変更できません"
LATER_CHECK = "「明日以降」に、時刻の欄と実施日（日付のチップ）の時刻が違うタスクがあります（%d 件）"
# 画面で行を見出しへ D&D する（dragstart → 見出しへ drop → dragend）・行の時刻の欄を押して入力欄が開くかを書く
LATER_JS = ("<script>function tbItem(title){return Array.prototype.slice.call(document.querySelectorAll('.item')).filter(function(i){"
            "var t=i.querySelector('.task-title');return t&&t.textContent===title;})[0];}"
            "function tbDnd(title, sec){var src=tbItem(title);"
            "var dt=new DataTransfer();src.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));"
            "var tgt=document.querySelector('.section-label[data-sec=\"'+sec+'\"]');"
            "tgt.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));"
            "src.dispatchEvent(new DragEvent('dragend',{bubbles:true}));"
            # 今日の側から「明日以降」へ落とすと実施日を聞く（v2.13）。この試験では「未定にする」で答える
            "var g=document.querySelector('dialog.later-due');if(g)g.querySelector('.later-due-none').click();}"
            "function tbClickTime(title){var t=tbItem(title).querySelector('.time');t.click();"
            "document.documentElement.setAttribute('data-input',t.querySelector('input')?'1':'0');}"
            "%s</script>")


class TestLaterTime(TimeCase):
    """「明日以降」の行の時刻（2026-11-05）。✎ は受けず元の時刻を出す（変えてもその日のうちだけで、今日の通知の対象にならない）。
    時刻の欄が実施日の時刻と違う行（今日の側から D&D・move で戻した行）は、ボードの点検が知らせる（board_edit.py の K14 と同じ条件）。"""

    D = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()

    def setUp(self):
        super().setUp()
        now = datetime.datetime.now()
        if now.hour == 23 and now.minute >= 50:
            self.skipTest("0 時をまたぐと「今日」がずれる")

    @staticmethod
    def row(title, time=None, attrs="", chip="", cls="item flat"):
        return ('<div class="%s"%s>%s<div><p class="task-title">%s</p><div class="chips">%s</div></div></div>'
                % (cls, (" " + attrs) if attrs else "", '<div class="time">%s</div>' % time if time else "", title, chip))

    def later_tag(self, dom, title):
        m = re.search(r'<div[^>]*class="time[^"]*"[^>]*>[^<]*</div><div><p class="task-title">%s</p>' % title, dom)
        self.assertIsNotNone(m, title)
        return m.group(0)

    def test_check_lists_differing_rows_only(self):
        self.start_deck()
        today = datetime.date.today().isoformat()
        rows = ('<div class="section-label">明日以降</div>'
                + self.row("食い違い", "10:00", 'data-due="%s 9:30"' % self.D)
                + self.row("移した後に戻した", "11:00", 'data-due="%s 9:30" data-due-moved="%s"' % (today, today))
                + self.row("同じ", "9:30", 'data-due="%s 09:30"' % self.D)
                + self.row("日付だけ", "10:00", 'data-due="%s"' % self.D)
                + self.row("済", "10:00", 'data-due="%s 9:30"' % self.D, '<span class="chip done">済</span>')
                + self.row("午後", "午後", 'data-due="%s 9:30"' % self.D)
                + self.row("暦に無い", "10:00", 'data-due="2025-02-30 9:30"')
                + self.row("欄なし", None, 'data-due="%s 9:30"' % self.D)
                + self.row("24時", "10:00", 'data-due="%s 24:00"' % self.D)
                + self.row("淡色だけ", "10:00", 'data-due="%s 9:30"' % self.D, cls="item flat done-item"))
        rows_today = '<div class="section-label">今日中</div>' + self.row("今日の側", "10:00", 'data-due="%s 9:30" data-due-moved="%s"' % (today, today))
        # 読み込みの後に drop が起きても、知らせの中身が同じなら作り直さない（読み上げをくり返さない）
        js = ("setTimeout(function(){document.getElementById('tb-board-check').setAttribute('data-mark','1');"
              "document.dispatchEvent(new Event('drop'));},800);")
        self.write_board(rows=rows_today + rows, extra=LATER_JS % js)
        dom = self.open_page(self.board)
        self.assertIn(LATER_CHECK % 3, dom)                    # 済チップの無い done-item の行は数える（読み込みでチップに合わせて外れる）
        self.assertRegex(dom, r'<div[^>]*id="tb-board-check"[^>]*data-mark="1"|<div[^>]*data-mark="1"[^>]*id="tb-board-check"')

    def test_check_is_rebuilt_when_count_changes(self):
        """知らせの中身が変わったとき（2 件→1 件）は作り直す（中身が同じときだけ残す）。"""
        self.start_deck()
        rows = ('<div class="section-label">今日中</div>'
                + '<div class="section-label">明日以降</div>' + self.row("食い違い", "10:00", 'data-due="%s 9:30"' % self.D)
                + self.row("移す行", "11:00", 'data-due="%s 9:45"' % self.D))
        js = ("setTimeout(function(){document.getElementById('tb-board-check').setAttribute('data-mark','1');"
              "tbDnd('移す行','今日中');},800);"
              "setTimeout(function(){var c=document.getElementById('tb-board-check');"
              "document.documentElement.setAttribute('data-after',[c.hasAttribute('data-mark')?'1':'0',c.textContent].join('|'));"
              "document.documentElement.setAttribute('data-checks',String(document.querySelectorAll('#tb-board-check').length));},1200);")
        self.write_board(rows=rows, extra=LATER_JS % js)
        dom = self.open_page(self.board)
        after = html_unescape(re.search(r'data-after="([^"]*)"', dom).group(1)).split("|", 1)
        self.assertEqual(after[0], "0")                       # 作り直した（前の知らせは残っていない）
        self.assertIn(LATER_CHECK % 1, after[1])
        self.assertIn('data-checks="1"', dom)
        self.assertIn("今日の側へ動かすとき（ドラッグ。一度今日へ移した印の無い行は Deck の日付の切り替えも）は時刻の欄の時刻が使われ、"
                      "ボードを作り直すと実施日の時刻だけが残ります。どちらの時刻にするかを決めてください。", dom)
        self.assertIn("Claude に「ボードを直して」と頼んでください。", dom)
        self.assertEqual(dom.count('id="tb-board-check"'), 1)

    def test_replayed_local_move_updates_check_and_edit(self):
        """localStorage に残った移動（Deck に届かなかった D&D）を読み込みで当てた後も、点検と ✎ を作り直す。"""
        today = datetime.date.today()
        self.seed({"tb:mv:" + today.isoformat(): json.dumps([{"k": "10:00|戻す行", "sec": "明日以降", "before": None}])})
        self.start_deck(ovr={KEY: "23:30", "10:00|戻す行": "12:00"})
        rows = ('<div class="section-label">今日中</div>'
                + self.row("戻す行", "10:00", 'data-due="%s 9:30" data-due-moved="%s"' % (today.isoformat(), today.isoformat()),
                           '<span class="chip pending">未</span>')
                + '<div class="section-label">明日以降</div>')
        self.write_board(rows=rows)
        dom = self.open_page(self.board)
        self.assertRegex(dom, r'明日以降</div>(?:(?!section-label).)*戻す行', "移動が当たっていない")
        self.assertIn(LATER_CHECK % 1, dom)
        tag = self.later_tag(dom, "戻す行")
        self.assertIn(">10:00<", tag)
        self.assertIn("time-locked", tag)

    def test_no_check_without_differing_rows(self):
        self.start_deck()
        self.write_board(rows='<div class="section-label">明日以降</div>' + self.row("同じ", "9:30", 'data-due="%s 9:30"' % self.D))
        dom = self.open_page(self.board)
        self.assertNotIn("tb-board-check", dom)

    def test_later_row_takes_no_edit_and_shows_original_time(self):
        self.start_deck(ovr={KEY: "23:30", "10:00|先の行": "11:00"})
        rows = '<div class="section-label">明日以降</div>' + self.row("先の行", "10:00")
        self.write_board(rows=rows, extra=LATER_JS % "setTimeout(function(){tbClickTime('先の行');},800);")
        before = self.sound_bytes()
        dom = self.open_page(self.board)
        tag = self.later_tag(dom, "先の行")
        self.assertIn(">10:00<", tag)                         # Deck の上書き（11:00）は出さない
        self.assertNotIn("overridden", tag)
        self.assertIn("time-locked", tag)
        self.assertIn(LATER_MSG, tag)                         # 時刻の欄の title
        self.assertIn('data-input="0"', dom)                  # 押しても入力欄は開かない
        self.assertIn('<div class="toast">' + LATER_MSG, dom)
        self.assertEqual(self.time_posts(), 0)
        self.assertEqual(self.sound_bytes(), before)
        self.assertEqual(self.time_text(dom), "23:30")        # 今日の予定の行は従来どおり
        self.assertFalse(self.locked(dom))

    def test_dnd_updates_check_and_edit(self):
        """D&D で今日の側から「明日以降」へ戻すと、読み直さずに ✎ を受けなくなる。今日の予定へ戻すと ✎ の上書きがまた出る。

        戻す行は v1.6 までにできた食い違う行（時刻の欄 10:00・実施日 9:30・印あり）。「明日以降」へ落とすと実施日を聞き、ここでは
        「未定にする」で答える（v2.13）ので、実施日が外れて食い違いは無くなり、点検の知らせは出ない。時刻の欄 10:00 は残る。
        今日の予定へ戻すと、実施日の無い行なので時刻の欄のまま動き、✎ の上書き（12:00）がまた出る。"""
        today = datetime.date.today().isoformat()
        self.start_deck(ovr={KEY: "23:30", "10:00|戻す行": "12:00"})
        rows = ('<div class="section-label">今日の予定</div>'
                + self.row("戻す行", "10:00", 'data-due="%s 9:30" data-due-moved="%s"' % (today, today), '<span class="chip pending">未</span>')
                + '<div class="section-label">明日以降</div>')
        js = ("setTimeout(function(){document.documentElement.setAttribute('data-before',document.getElementById('tb-board-check')?'1':'0');"
              "tbDnd('戻す行','明日以降');},800);"
              "setTimeout(function(){var c=document.getElementById('tb-board-check');var t=tbItem('戻す行').querySelector('.time');"
              "document.documentElement.setAttribute('data-after',[c?c.textContent:'',t.textContent,t.className].join('|'));"
              "tbDnd('戻す行','今日の予定');},1200);"
              "setTimeout(function(){var i=tbItem('戻す行');var t=i.querySelector('.time');"
              "document.documentElement.setAttribute('data-back',[document.getElementById('tb-board-check')?'1':'0',t.textContent,t.className,"
              "i.getAttribute('data-due'),String(i.querySelectorAll('.time').length)].join('|'));},1600);")
        self.write_board(rows=rows, extra=LATER_JS % js)
        dom = self.open_page(self.board)
        self.assertIn('data-before="0"', dom)
        after = html_unescape(re.search(r'data-after="([^"]*)"', dom).group(1)).split("|")
        self.assertEqual(after[0], "")                        # 未定で戻したので食い違わない
        self.assertEqual(after[1], "10:00")
        self.assertIn("time-locked", after[2])
        self.assertNotIn("overridden", after[2])
        back = html_unescape(re.search(r'data-back="([^"]*)"', dom).group(1)).split("|")
        self.assertEqual(back[0], "0")
        self.assertEqual(back[1], "12:00")
        self.assertIn("overridden", back[2])
        self.assertNotIn("time-locked", back[2])
        self.assertEqual(back[3], "")                      # 未定で戻した行は実施日を持たない
        self.assertEqual(back[4], "1")


class TestBrokenTimeKeys(BrowserCase):
    """閉じタグの無い時刻の欄の行（補足つき・span のタイトル・2つ目のチップ・複数行の CR LF）で、board.js の鍵（D&D の k・
    localStorage の × の記録・通知の鍵）が Deck の鍵（_item_key・read_board_alarms）と同じ「時刻|タイトル」になる（Deck v2.14・
    2026-11-06 ユーザー決定）。時刻を過ぎた行（時刻超過）・▶ 次の行も、足したチップが鍵に混ざらない。「ボードの点検」に件数が出る。
    時刻は 0:00（いつでも過ぎている）と 23:58（setUp が 23:50 以後を飛ばすので、いつでも先）で、時計に依らない。"""

    # 鍵と同じ形の行を tests/test_board_edit.py の BROKEN_SHAPES と同じ並びで持つ（このファイルは board_edit を読まない）
    SHAPES = [
        ("補足つき", '<div class="item"><span class="time">%s<div><p class="task-title">補足つき</p><p class="task-note">メモ</p>'
                 '<div class="chips"><span class="chip %s</span></div></div></div>\n'),
        ("span題", '<div class="item"><span class="time">%s<div><span class="task-title strike">span題</span>'
                  '<div class="chips"><span class="chip %s</span></div></div></div>\n'),
        ("二つ", '<div class="item crit"><span class="time">%s<div><p class="task-title">二つ</p>'
               '<div class="chips"><span class="chip %s</span><span class="chip crit">重要</span></div></div></div>\n'),
        ("複数行", '<div class="item"><span class="time">%s\n  <div>\n    <p class="task-title">複数行</p>\n'
                '    <div class="chips"><span class="chip %s</span></div>\n  </div>\n</div>\n'),
    ]
    NEXT = ('<div class="item"><span class="time">23:58<div><p class="task-title">次の</p><p class="task-note">あとで</p>'
            '<div class="chips"><span class="chip pending">未</span></div></div></div>\n')

    attr = TestLaterDueAsk.attr

    def setUp(self):
        super().setUp()
        now = datetime.datetime.now()
        if now.hour == 23 and now.minute >= 50:
            self.skipTest("0 時をまたぐと「今日」がずれる・23:58 が過ぎうる")

    def rows(self, chip):
        return '\n<div class="section-label">今日中</div>\n' + "".join(r % ("0:00", chip) for _t, r in self.SHAPES)

    def file_keys(self):
        """board.html（write_board は改行を CR LF で書く）の、タイトルごとの (見出し, Deck の鍵)。"""
        with open(self.board, encoding="utf-8", newline="") as f:
            lines = f.read().splitlines(True)
        out = {}
        for (s, e, name) in dw._scan_board(lines)[1]:
            blk = "".join(lines[s:e + 1])
            out[dw._element_text(blk, "task-title")] = (name, dw._item_key(blk))
        return out

    def test_keys_match_deck(self):
        self.start_deck()
        titles = [t for t, _r in self.SHAPES] + ["次の"]
        self.write_board(rows=self.rows('pending">未') + self.NEXT, time="0:00", extra=TestLaterDueAsk.SCRIPT % (
            "var mv=[];var of=window.fetch;window.fetch=function(u,o){if(String(u).indexOf('/board/move')>=0)"
            "mv.push(JSON.parse(o.body).k);return of.apply(this,arguments);};"
            "setTimeout(function(){if(n!==1)return;var d=document.querySelector('header .date').textContent.trim();var sh={};"
            "%s.forEach(function(t){sh[t]=tbItem(t).querySelector('.time').textContent;});"
            "document.documentElement.setAttribute('data-shown',JSON.stringify(sh));"
            "document.documentElement.setAttribute('data-fired',localStorage.getItem('tb:fired:'+d)||'[]');"
            "var c=document.getElementById('tb-board-check');document.documentElement.setAttribute('data-check',c?c.textContent:'');"
            "%s.forEach(function(t){tbDnd(t,'今日の予定');});"
            "setTimeout(function(){document.documentElement.setAttribute('data-mvk',JSON.stringify(mv));},600);},800);"
            % (json.dumps(titles, ensure_ascii=False), json.dumps(titles, ensure_ascii=False))))
        before = self.file_keys()
        want = {t: before[t][1] for t in titles}
        self.assertEqual(want, dict([(t, "0:00|" + t) for t, _r in self.SHAPES] + [("次の", "23:58|次の")]))
        alarms = [a[0] for a in dw.read_board_alarms(self.board) if a[3] in titles]
        self.assertEqual(sorted(alarms), sorted(want.values()))           # 通知の鍵も同じ（Deck 側）
        dom = self.open_page(self.board, budget=5000)
        shown = json.loads(self.attr(dom, "data-shown"))
        self.assertIn("時刻超過", shown["補足つき"])                  # 足したチップは欄の中に入っている（前提）
        self.assertIn("▶ 次", shown["次の"])
        self.assertIn("メモ", shown["補足つき"])                     # 欄と同じ名前の最初の閉じタグより後ろの文字も欄の中にある（前提）
        self.assertEqual(sorted(json.loads(self.attr(dom, "data-mvk"))), sorted(want.values()))   # Deck へ送った鍵
        end = time.time() + 10
        while time.time() < end and any(self.file_keys()[t][0] != "今日の予定" for t in titles):
            time.sleep(0.1)
        after = self.file_keys()
        self.assertEqual({t: after[t] for t in titles}, {t: ("今日の予定", want[t]) for t in titles})   # Deck が同じ鍵で見つけて移した
        fired = [k for k in json.loads(self.attr(dom, "data-fired")) if k.split("|", 1)[-1] in titles]
        self.assertEqual(sorted(fired), sorted(v for t, v in want.items() if t != "次の"))   # 先の行はまだ鳴らない
        self.assertIn("時刻の欄の閉じタグが無いタスクがあります（5 件）", self.attr(dom, "data-check"))

    def test_hidden_done_rows_stay_hidden(self):
        """済の行を × で隠すと、読み直した後も同じ鍵（Deck の鍵）で隠れたまま。"""
        self.start_deck()
        titles = [t for t, _r in self.SHAPES]
        self.write_board(rows=self.rows('done">済'), extra=TestLaterDueAsk.SCRIPT % (
            "setTimeout(function(){var d=document.querySelector('header .date').textContent.trim();"
            "var ts=%s;if(n===1){ts.forEach(function(t){tbItem(t).querySelector('.task-hide-btn').click();});location.reload();return;}"
            "document.documentElement.setAttribute('data-h',JSON.stringify([ts.map(function(t){return tbItem(t).classList.contains('tb-task-hidden');}),"
            "JSON.parse(localStorage.getItem('tb:hideTask:'+d)||'[]')]));},800);" % json.dumps(titles, ensure_ascii=False)))
        want = self.file_keys()
        dom = self.open_page(self.board, budget=5000)
        self.assertEqual(self.attr(dom, "data-loads"), "2")
        hidden, keys = json.loads(self.attr(dom, "data-h"))
        self.assertEqual(hidden, [True] * len(titles))
        self.assertEqual(sorted(keys), sorted(want[t][1] for t in titles))

    def test_part_free_child_takes_a_date_like_deck(self):
        """閉じタグのある欄の中に部品でない class の子があるだけの行は、「明日以降」へ落とすと日付を当てられる（Deck の _later_due_shape と
        同じく時刻の欄を作り直す＝Deck も 200）。中に部品のある欄だけが日付を当てられない（tbTimeHasPart）。"""
        self.start_deck()
        d = datetime.date.today()
        plus2 = (d + datetime.timedelta(days=2)).isoformat()
        self.write_board(rows='\n<div class="section-label">今日中</div>\n'
                              '<div class="item"><span class="time">9:00<span class="x">a</span></span><div><p class="task-title">子あり</p>'
                              '<div class="chips"><span class="chip pending">未</span></div></div></div>\n'
                              '<div class="section-label">明日以降</div>\n<div class="item flat"><div><p class="task-title">いつか</p></div></div>\n',
                         extra=TestLaterDueAsk.SCRIPT % (
                             "setTimeout(function(){tbDnd('子あり','明日以降');var g=document.querySelector('dialog.later-due');"
                             "var i=g.querySelectorAll('input');document.documentElement.setAttribute('data-dis',[i[0].disabled,"
                             "g.querySelector('.later-due-ok').disabled].join(','));i[0].value='%s';i[1].value='10:00';"
                             "g.querySelector('.later-due-ok').click();document.documentElement.setAttribute('data-after',tbRow('子あり'));},800);" % plus2))
        dom = self.open_page(self.board, budget=4000)
        self.assertEqual(self.attr(dom, "data-dis"), "false,false")
        self.assertEqual(self.attr(dom, "data-after"), "明日以降,%s 10:00,,,10:00,false" % plus2)
        end = time.time() + 10
        while time.time() < end and 'data-due="%s 10:00"' % plus2 not in open(self.board, encoding="utf-8").read():
            time.sleep(0.1)
        text = open(self.board, encoding="utf-8").read()
        self.assertIn('data-due="%s 10:00"' % plus2, text)                     # Deck も同じ形に書いた（200）
        self.assertIn('<div class="time">10:00</div>', text)

    def test_part_free_child_screen_matches_file(self):
        """部品でない class の子だけの欄の行を D&D で動かしても、画面の行と Deck が書いた board.html の行が同じ形になる
        （読み直しても戻らない）。①実施日が今日の「明日以降」の行を今日の予定へ（欄の文字「9:00a」は H:MM でないので実施日の時刻）
        ②今日中の行を未定で「明日以降」へ（時刻の欄に触れない＝子も残る）。"""
        self.start_deck()
        d = datetime.date.today().isoformat()
        child = '<span class="time">9:00<span class="x">a</span></span>'
        self.write_board(rows='\n<div class="section-label">今日中</div>\n'
                              '<div class="item">%s<div><p class="task-title">未定へ</p>'
                              '<div class="chips"><span class="chip pending">未</span></div></div></div>\n'
                              '<div class="section-label">明日以降</div>\n'
                              '<div class="item" data-due="%s 10:00">%s<div><p class="task-title">今日へ</p></div></div>\n' % (child, d, child),
                         extra=TestLaterDueAsk.SCRIPT % (
                             "setTimeout(function(){tbDnd('今日へ','今日の予定');tbDnd('未定へ','明日以降');"
                             "document.querySelector('dialog.later-due .later-due-none').click();"
                             "var o={};['今日へ','未定へ'].forEach(function(t){var it=tbItem(t);o[t]=[tbRow(t),"
                             "Array.prototype.map.call(it.querySelectorAll('.time'),function(e){return e.innerHTML;}).join('+')];});"
                             "document.documentElement.setAttribute('data-o',JSON.stringify(o));},800);"))
        dom = self.open_page(self.board, budget=4000)
        shown = json.loads(self.attr(dom, "data-o"))
        end = time.time() + 10
        def rows():
            with open(self.board, encoding="utf-8") as f:
                lines = f.read().splitlines(True)
            out = {}
            for (s, e, n) in dw._scan_board(lines)[1]:
                b = "".join(lines[s:e + 1])
                t = dw._element_text(b, "task-title")
                if t in ("今日へ", "未定へ"):
                    out[t] = (n, b)
            return out
        while time.time() < end and not (rows().get("今日へ", ("",))[0] == "今日の予定" and rows().get("未定へ", ("",))[0] == "明日以降"):
            time.sleep(0.1)
        f = rows()
        self.assertEqual(f["今日へ"][0], "今日の予定")
        self.assertEqual(f["未定へ"][0], "明日以降")
        # ① 行の時刻は時刻の欄の「9:00」（鍵と同じ読み方＝Deck の _time_text・board.js の tbTimeText・v2.15。v2.14 までは欄の文字全体「9:00a」を
        #    読み、H:MM でないので実施日の時刻 10:00 を使った）。画面も同じ
        self.assertIn('<div class="time">9:00</div>', f["今日へ"][1])
        self.assertNotIn('class="x"', f["今日へ"][1])
        self.assertEqual(shown["今日へ"][1], "9:00")
        self.assertIn('data-due="%s 9:00"' % d, f["今日へ"][1])
        self.assertTrue(shown["今日へ"][0].startswith("今日の予定,%s 9:00," % d), shown["今日へ"][0])
        # ② 未定は時刻の欄に触れない（子も残る）。画面も同じ
        self.assertIn(child, f["未定へ"][1])
        self.assertEqual(shown["未定へ"][1], '9:00<span class="x">a</span>')

    def test_case_of_class_on_quirks_board(self):
        """本物のボード（board-template.html）は doctype が無く互換モードで開かれ、querySelector は class の値の大文字小文字を区別しない。
        その板では、時刻の欄の中に class="Chip" がある行も部品のある欄として扱い、「明日以降」へ日付を当てない（Deck の _ROW_PART_RE も
        re.I で部品とみなし、_later_due_shape は形を作らない＝400）。"""
        self.start_deck()
        self.write_board(rows='\n<div class="section-label">今日中</div>\n'
                              '<div class="item"><span class="time">9:00 <span class="Chip">x</span></span><div><p class="task-title">大文字</p>'
                              '<div class="chips"><span class="chip pending">未</span></div></div></div>\n'
                              '<div class="section-label">明日以降</div>\n<div class="item flat"><div><p class="task-title">いつか</p></div></div>\n',
                         extra=TestLaterDueAsk.SCRIPT % (
                             "setTimeout(function(){document.documentElement.setAttribute('data-mode',document.compatMode);"
                             "tbDnd('大文字','明日以降');var g=document.querySelector('dialog.later-due');var i=g.querySelectorAll('input');"
                             "document.documentElement.setAttribute('data-dis',[i[0].disabled,g.querySelector('.later-due-ok').disabled].join(','));},800);"))
        with open(self.board, encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.lower().startswith("<!doctype html>"))
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(text[len("<!doctype html>"):])                 # 本物のボードと同じ互換モードにする
        dom = self.open_page(self.board, budget=3000)
        self.assertEqual(self.attr(dom, "data-mode"), "BackCompat")
        self.assertEqual(self.attr(dom, "data-dis"), "true,true")
        block = '<div class="item"><span class="time">9:00 <span class="Chip">x</span></span><div><p class="task-title">大文字</p></div></div>\n'
        self.assertEqual(dw._remove_time_elements(block), (block, 0))
        # 手で doctype を足した板（標準モード）でも同じ（tbTimeHasPart は querySelector に頼らず、class の値を小文字にそろえて比べる）
        with open(self.board, "w", encoding="utf-8") as f:
            f.write("<!doctype html>" + text[len("<!doctype html>"):])
        dom = self.open_page(self.board, budget=3000)
        self.assertEqual(self.attr(dom, "data-mode"), "CSS1Compat")
        self.assertEqual(self.attr(dom, "data-dis"), "true,true")

    def test_unclosed_part_free_child_screen_matches_file(self):
        """閉じタグの無い時刻の欄で、ブラウザが欄の中に入れたのが部品でない class の要素だけの行（欄が項目の最後にあり、ブラウザは
        項目の閉じタグで欄を閉じる）。Deck は欄をブラウザが閉じる所までとみなして外す（_implied_close・v2.14）ので、画面の行と
        Deck が書いた board.html の行は同じになる。①今日中の行を日付を決めて「明日以降」へ ②実施日が今日の「明日以降」の行を今日の予定へ。"""
        self.start_deck()
        d = datetime.date.today()
        plus2 = (d + datetime.timedelta(days=2)).isoformat()
        tail = '<span class="time">9:00<span class="x">a</span></div>\n'
        self.write_board(rows='\n<div class="section-label">今日中</div>\n'
                              '<div class="item"><div><p class="task-title">日付へ</p><div class="chips"><span class="chip pending">未</span></div></div>' + tail +
                              '<div class="section-label">明日以降</div>\n'
                              '<div class="item" data-due="%s 10:00"><div><p class="task-title">今日へ</p></div>' % d.isoformat() + tail,
                         extra=TestLaterDueAsk.SCRIPT % (
                             "setTimeout(function(){var n0=[tbTimeHasPartProbe('日付へ'),tbTimeHasPartProbe('今日へ')].join(',');"
                             "document.documentElement.setAttribute('data-n0',n0);"
                             "tbDnd('今日へ','今日の予定');tbDnd('日付へ','明日以降');var g=document.querySelector('dialog.later-due');"
                             "var i=g.querySelectorAll('input');document.documentElement.setAttribute('data-dis',i[0].disabled);"
                             "i[0].value='%s';i[1].value='11:00';g.querySelector('.later-due-ok').click();"
                             "var o={};['今日へ','日付へ'].forEach(function(t){var it=tbItem(t);o[t]=[tbRow(t),"
                             "Array.prototype.map.call(it.querySelectorAll('.time'),function(e){return e.innerHTML;}).join('+'),"
                             "it.textContent.indexOf('a')>=0];});"
                             "document.documentElement.setAttribute('data-o',JSON.stringify(o));},800);"
                             "function tbTimeHasPartProbe(t){return tbItem(t).querySelector('.time').innerHTML;}" % plus2))
        dom = self.open_page(self.board, budget=4000)
        self.assertEqual(self.attr(dom, "data-n0"), '9:00<span class="x">a</span>,9:00<span class="x">a</span>')   # 欄の中は x だけ（前提）
        self.assertEqual(self.attr(dom, "data-dis"), "false")
        shown = json.loads(self.attr(dom, "data-o"))
        def rows():
            with open(self.board, encoding="utf-8") as f:
                lines = f.read().splitlines(True)
            out = {}
            for (s, e, n) in dw._scan_board(lines)[1]:
                b = "".join(lines[s:e + 1])
                t = dw._element_text(b, "task-title")
                if t in ("今日へ", "日付へ"):
                    out[t] = (n, b)
            return out
        end = time.time() + 10
        while time.time() < end and not (rows().get("今日へ", ("",))[0] == "今日の予定" and 'data-due="%s 11:00"' % plus2 in rows().get("日付へ", ("", ""))[1]):
            time.sleep(0.1)
        f = rows()
        self.assertEqual(f["日付へ"][0], "明日以降")
        self.assertIn('data-due="%s 11:00"' % plus2, f["日付へ"][1])
        self.assertIn('<div class="time">11:00</div>', f["日付へ"][1])
        self.assertNotIn('class="time">9:00', f["日付へ"][1])
        self.assertEqual(shown["日付へ"][1], "11:00")
        self.assertTrue(shown["日付へ"][0].startswith("明日以降,%s 11:00," % plus2), shown["日付へ"][0])
        self.assertEqual(f["今日へ"][0], "今日の予定")
        self.assertIn('<div class="time">9:00</div>', f["今日へ"][1])          # 行の時刻は欄の「9:00」（_time_text・v2.15）
        self.assertNotIn('class="x"', f["今日へ"][1])
        self.assertEqual(shown["今日へ"][1], "9:00")
        self.assertEqual([shown[t][2] for t in ("今日へ", "日付へ")], [False, False])   # 欄の中の文字は画面でも欄と一緒に外れる（Deck と同じ）

    def test_time_range_matches_browser(self):
        """Deck の _time_range が読む欄の範囲は、ブラウザの DOM の欄と同じ（閉じタグの無い欄・外側で開いていない閉じタグ・p の欄）。"""
        self.start_deck()
        rows = ['<div class="item"><div><p class="task-title">X</p><span class="time">0:00</div><div class="chips"><span class="chip pending">未</span></div></div>',
                '<div class="item"><div><p class="task-title">Y</p></div><span class="time">9:00</b><span class="x">a</span></div>',
                '<div class="item"><p class="time">9:00<div><p class="task-title">Z</p></div></div>',
                '<div class="item"><div><p class="task-title">W</p></div><p class="time">8:00<li>w</li></p></div>']
        self.write_board(rows='\n<div class="section-label">今日中</div>\n' + "\n".join(rows) + "\n",
                         extra=TestLaterDueAsk.SCRIPT % (
                             "setTimeout(function(){var o={};['X','Y','Z','W'].forEach(function(t){o[t]=tbItem(t).querySelector('.time').textContent;});"
                             "document.documentElement.setAttribute('data-o',JSON.stringify(o));},800);"))
        dom = self.open_page(self.board, budget=3000)
        shown = json.loads(self.attr(dom, "data-o"))
        for title, row in zip("XYZW", rows):
            m = dw._TIME_OPEN_RE.search(row)
            r = dw._time_range(row, m)
            self.assertEqual(html_unescape(dw._STRIP_TAGS_RE.sub("", row[r[0]:r[1]])), shown[title], title)

    def test_screen_closed_close_time_keeps_dom(self):
        """ブラウザが時刻の欄をタイトルやチップの手前で閉じる形（閉じタグは無いが画面は正しい＝_time_screen_closed）は、欄の中に class を
        持つ要素が入らず「ボードの点検」の⑥に出ない。_time_close_at（board_edit.py v1.12 の close-time・Deck v2.16 の日付の切り替え）が
        ブラウザの閉じる位置（その手前の空白を除く）に閉じタグを補った行は、補う前の行と DOM が空白の置き場所のほかは同じ
        （board.js が動く前に読む）。"""
        self.start_deck()
        shapes = ['<div class="item">\n  <p class="time">9:00\n  <div>\n    <p class="task-title">%s</p>\n'
                  '    <div class="chips"><span class="chip pending">未</span></div>\n  </div>\n</div>',
                  '<div class="item"><div><span class="time">9:00</div><p class="task-title">%s</p>'
                  '<div class="chips"><span class="chip pending">未</span></div></div>',
                  '<div class="item"><div><span class="time">9:00</div>am <p class="task-title">%s</p>'
                  '<div class="chips"><span class="chip pending">未</span></div></div>',
                  # v1.11 の close-time が断った形（"after"・"after"・"text"。tests/test_board_edit.py の SHOWN_CLOSED_REFUSED_BEFORE）
                  '<div class="item"><p class="time">9:00 <b>am</b><div><p class="task-title">%s</p>'
                  '<div class="chips"><span class="chip pending">未</span></div></div></div>',
                  '<div class="item"><div><span class="time">9:00 <span>am</div><p class="task-title">%s</p>'
                  '<div class="chips"><span class="chip pending">未</span></div></div>',
                  '<div class="item"><div><span class="time">  </div><p class="task-title">%s</p>'
                  '<div class="chips"><span class="chip pending">未</span></div></div>',
                  # 欄の中の p を後ろの p が閉じる形（足すのは </p></span>）
                  '<div class="item"><div><span class="time">9:00 <p>a<p>b</div><p class="task-title">%s</p>'
                  '<div class="chips"><span class="chip pending">未</span></div></div>']
        rows = []
        for i, s in enumerate(shapes):
            after = s % ("後%d" % i)
            hit = dw._time_open_unclosed(after)
            self.assertIsNotNone(hit, i)
            self.assertIsNotNone(dw._time_screen_closed(after, hit), i)
            at = dw._time_close_at(after)
            self.assertIsInstance(at, tuple, i)
            after = after[:at[0]] + at[1] + after[at[0]:]
            self.assertIsNone(dw._time_open_unclosed(after), i)
            self.assertEqual(dw._item_key(after), dw._item_key(s % ("後%d" % i)), i)
            rows += [s % ("前%d" % i), after]
        cap = ("<script>(function(){var o={};Array.prototype.forEach.call(document.querySelectorAll('.item'),function(i){"
               "var t=i.querySelector('.task-title');if(t)o[t.textContent]=i.outerHTML.split(t.textContent).join('T').replace(/\\s+/g,'');});"
               "document.documentElement.setAttribute('data-o',JSON.stringify(o));})();</script>")
        self.write_board(rows='\n<div class="section-label">今日中</div>\n' + "\n".join(rows) + "\n" + cap,
                         extra=TestLaterDueAsk.SCRIPT % (
                             "setTimeout(function(){document.documentElement.setAttribute('data-n',"
                             "document.querySelectorAll('.time[data-tb-unclosed]').length);},800);"))
        dom = self.open_page(self.board, budget=3000)
        o = json.loads(self.attr(dom, "data-o"))
        for i in range(len(shapes)):
            self.assertEqual(o["前%d" % i], o["後%d" % i], i)
            self.assertNotIn("task-title", o["前%d" % i].split('class="time"')[1].split("</")[0], i)
        self.assertEqual(self.attr(dom, "data-n"), "0")      # ⑥は数えない（board.js は DOM しか見られない）

    def test_formatting_reopened_and_close_time_confirmed(self):
        """時刻の欄の中で閉じていない書式の要素（_FORMATTING_TAGS の14種）は、ブラウザが欄を閉じた後で開き直し、後ろのタイトルを包む
        （_time_reopened。Chrome での確認を試験に残す）。close-time --confirmed と同じ位置に閉じタグを補った行
        （_time_close_at の reopen）は、書式が外れて包まれず、行の鍵は同じ。1種1ページで見る（前の行から書式が漏れないように、補った行を先に置く）。"""
        self.start_deck()
        self.assertEqual(len(dw._FORMATTING_TAGS), 14)
        for tag in sorted(dw._FORMATTING_TAGS):
            with self.subTest(tag=tag):
                row = ('<div class="item"><div><span class="time">9:00 <%s>am</div><p class="task-title">%%s</p>'
                       '<div class="chips"><span class="chip pending">未</span></div></div>' % tag)
                before = row % "前"
                hit = dw._time_open_unclosed(before)
                self.assertTrue(dw._time_reopened(before, hit))
                self.assertIsNone(dw._time_screen_closed(before, hit))
                self.assertEqual(dw._time_close_at(before), "format")
                after = row % "後"
                at = dw._time_close_at(after, reopen=True)
                self.assertEqual(at[1], "</%s></span>" % tag)
                after = after[:at[0]] + at[1] + after[at[0]:]
                self.assertIsNone(dw._time_open_unclosed(after))
                self.assertEqual(dw._item_key(after).replace("後", "前"), dw._item_key(before))
                self.write_board(rows='\n<div class="section-label">今日中</div>\n' + after + "\n" + before + "\n",
                                 extra=TestLaterDueAsk.SCRIPT % (
                                     "setTimeout(function(){var o={};['前','後'].forEach(function(t){var e=tbItem(t).querySelector('.task-title');"
                                     "o[t]=[!!(e.closest('%s')||e.querySelector('%s')),tbItem(t).querySelector('.time').textContent];});"
                                     "document.documentElement.setAttribute('data-o',JSON.stringify(o));},800);" % (tag, tag)))
                o = json.loads(self.attr(self.open_page(self.board, budget=3000), "data-o"))
                self.assertTrue(o["前"][0], "%s は開き直されてタイトルを包む" % tag)
                self.assertFalse(o["後"][0], "%s を補った行は包まれない" % tag)
                self.assertEqual(o["前"][1], o["後"][1])

    def test_keep_open_tags_take_title(self):
        """時刻の欄の中で table・object・script など（_KEEP_OPEN_TAGS）が閉じていない行は、ブラウザが外側の閉じタグで欄を閉じず、
        タイトルが欄の中に入るか文字として読まれる（_time_screen_closed は None にする＝「画面では正しく」の側に入れない）。
        Reviewer が Chrome で試した形を、1種1ページで見る（MathML・SVG の要素は math・svg の中に置く）。
        plaintext・textarea などはページの残りを飲み込むので、board.js を使わず、行1つだけのページの DOM を読んで、欄が閉じてタイトルの要素が
        欄の外に出た形（`</span></div><p class="task-title">中</p>`）が無いことを見る。対照の <span> の行ではその形がある。"""
        openers = {"table": "<table>", "select": "<select>", "textarea": "<textarea>", "object": "<object>", "marquee": "<marquee>",
                   "template": "<template>", "applet": "<applet>", "mi": "<math><mi>", "foreignobject": "<svg><foreignObject>",
                   "script": "<script>", "style": "<style>", "xmp": "<xmp>", "iframe": "<iframe>", "noembed": "<noembed>",
                   "noframes": "<noframes>", "noscript": "<noscript>", "plaintext": "<plaintext>", "title": "<title>",
                   "mo": "<math><mo>", "mn": "<math><mn>", "ms": "<math><ms>", "mtext": "<math><mtext>",
                   "annotation-xml": "<math><annotation-xml>", "desc": "<svg><desc>", "svg-title": "<svg><title>"}
        self.assertTrue(set(openers) - {"svg-title"} <= dw._KEEP_OPEN_TAGS)
        closed = '</span></div><p class="task-title">中</p>'
        page = os.path.join(os.path.dirname(self.board), "keep-open.html")
        # math・svg の外にそのまま書いた MathML・SVG の要素は、ふつうに欄が閉じる（_time_keeps_open が数えない＝画面では正しい側）
        controls = [("span", "<span>"), ("mi-outside", "<mi>"), ("foreignobject-outside", "<foreignObject>"), ("desc-outside", "<desc>")]
        for tag, opener in controls + sorted(openers.items()):
            with self.subTest(tag=tag):
                row = ('<div class="item"><div><span class="time">9:00 %sx</div><p class="task-title">中</p>'
                       '<div class="chips"><span class="chip pending">未</span></div></div>' % opener)
                with open(page, "w", encoding="utf-8") as f:
                    f.write('<html><head><meta charset="utf-8"></head><body>\n%s\n</body></html>' % row)
                dom = self.open_page(page, budget=1000)
                if (tag, opener) in controls:
                    self.assertIsNotNone(dw._time_screen_closed(row, dw._time_open_unclosed(row)))
                    self.assertIn(closed, dom)                 # 対照: ブラウザは </div> で欄を閉じ、タイトルは欄の外
                else:
                    self.assertIsNone(dw._time_screen_closed(row, dw._time_open_unclosed(row)))
                    self.assertNotIn(closed, dom, tag)

    def test_time_field_foreign_matches_browser(self):
        """時刻の欄の中の svg・math の形（tests/test_board_edit.py の TIME_FOREIGN_CASES）を、ブラウザが同じく読む（v2.19 / board_edit.py v1.15）。
        "close" はタイトルが欄の外で書式に包まれず、close-time（_time_close_at）が補った行と DOM が同じ。"reopen" はタイトルが書式に包まれる。
        "keep" はタイトルが欄の中に入る。1形を1ページで見る（補った行を先に置く。board.js は使わず、読み込み後の DOM を読む）。"""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_board_edit as tbe
        fmt = " %s " % " ".join(sorted(dw._FORMATTING_TAGS))
        # 書式の要素は HTML の要素だけを見る（svg の font・a は svg の要素で、書式の要素ではない）
        js = ("<script>var X='http://www.w3.org/1999/xhtml',L='%s';function F(e){return e.namespaceURI===X&&L.indexOf(' '+e.localName+' ')>=0;}"
              "function W(t){for(var a=t;a;a=a.parentElement)if(F(a))return true;var d=t.getElementsByTagName('*');"
              "for(var i=0;i<d.length;i++)if(F(d[i]))return true;return false;}"
              "document.addEventListener('DOMContentLoaded',function(){var o={};"
              "Array.prototype.forEach.call(document.querySelectorAll('.item'),function(it){var t=it.querySelector('.task-title');"
              "var tm=it.querySelector('.time');if(!t)return;o[t.textContent]={inside:!!(tm&&tm.contains(t)),"
              "fmt:W(t),html:it.outerHTML.split(t.textContent).join('T').replace(/\\s+/g,'')};});"
              "document.documentElement.setAttribute('data-o',JSON.stringify(o));});</script>" % fmt)
        page = os.path.join(os.path.dirname(self.board), "foreign.html")
        for i, (inner, want) in enumerate(tbe.TIME_FOREIGN_CASES):
            with self.subTest(inner=inner):
                before = tbe.time_foreign_row(inner, "前")
                rows = [before]
                if want == "close":
                    at = dw._time_close_at(tbe.time_foreign_row(inner, "後"))
                    after = tbe.time_foreign_row(inner, "後")
                    rows.insert(0, after[:at[0]] + at[1] + after[at[0]:])
                with open(page, "w", encoding="utf-8") as f:
                    f.write('<html><head><meta charset="utf-8">%s</head><body>\n%s\n</body></html>' % (js, "\n".join(rows)))
                o = json.loads(self.attr(self.open_page(page, budget=1000), "data-o"))
                self.assertEqual(o["前"]["inside"], want == "keep")
                self.assertEqual(o["前"]["fmt"], want == "reopen")
                if want == "close":
                    self.assertEqual(o["後"]["html"], o["前"]["html"])

    def test_check_counts_items(self):
        """⑥は項目ごとに数える（時刻の欄が2つとも閉じていない行も1件。board_edit.py の K15 と同じ）。"""
        self.start_deck()
        self.write_board(rows='\n<div class="section-label">今日中</div>\n'
                              '<div class="item"><span class="time">9:00<span class="time">9:30<div><p class="task-title">二つ</p>'
                              '<div class="chips"><span class="chip pending">未</span></div></div></div>\n',
                         extra=TestLaterDueAsk.SCRIPT % (
                             "setTimeout(function(){var c=document.getElementById('tb-board-check');"
                             "document.documentElement.setAttribute('data-check',c?c.textContent:'none');"
                             "document.documentElement.setAttribute('data-n',document.querySelectorAll('.time[data-tb-unclosed]').length);},800);"))
        dom = self.open_page(self.board, budget=3000)
        self.assertEqual(self.attr(dom, "data-n"), "2")                         # 欄は2つとも閉じていない（前提）
        self.assertIn("時刻の欄の閉じタグが無いタスクがあります（1 件）", self.attr(dom, "data-check"))

    def test_wellformed_board_has_no_check(self):
        """閉じタグのある行（class の無い入れ子の <div class="time"><div>9:00</div></div> と、class の無い同じ名前の子が先に閉じる
        <span class="time"><span>9</span>:00 <span class="x">a</span></span>＝K15 に当たらない形を含む）では知らせない。"""
        self.start_deck()
        self.write_board(rows='\n<div class="section-label">今日中</div>\n'
                              '<div class="item"><div class="time"><div>9:00</div></div><div><p class="task-title">入れ子</p>'
                              '<div class="chips"><span class="chip pending">未</span></div></div></div>\n'
                              '<div class="item"><span class="time"><span>9</span>:00 <span class="x">a</span></span><div><p class="task-title">子</p>'
                              '<div class="chips"><span class="chip pending">未</span></div></div></div>\n',
                         extra=TestLaterDueAsk.SCRIPT % (
                             "setTimeout(function(){var c=document.getElementById('tb-board-check');"
                             "document.documentElement.setAttribute('data-check',c?c.textContent:'none');},800);"))
        dom = self.open_page(self.board, budget=3000)
        self.assertEqual(self.attr(dom, "data-check"), "none")


class TestMoveOnBrokenBoard(BrowserCase):
    """崩れた板（項目の入れ子＝K1）で D&D をすると、Deck v2.18 は 409（reason "board-broken"）で断り、board.js は移動を localStorage にも残さずに
    読み直して元の位置へ戻し、理由を知らせに出す（2026-11-10）。ボードのファイルは変わらない。"""

    ROWS = ('<div class="section-label">今日の予定</div>\n'
            '<div class="item"><div><p class="task-title">動かす</p><div class="chips"><span class="chip pending">未</span></div></div></div>\n'
            '<div class="section-label">今日中</div>\n'
            '<div class="item"><div><p class="task-title">外</p></div>\n'
            '<div class="item"><div><p class="task-title">中</p></div></div></div>')
    JS = ("<script>window.addEventListener('load',function(){setTimeout(function(){"
          "function item(t){return Array.prototype.slice.call(document.querySelectorAll('.item')).filter(function(i){"
          "var e=i.querySelector('.task-title');return e&&e.textContent===t;})[0];}"
          "if(!sessionStorage.getItem('t-done')){sessionStorage.setItem('t-done','1');var src=item('動かす');var dt=new DataTransfer();"
          "src.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));"
          "document.querySelector('.section-label[data-sec=\"今日中\"]').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));"
          "src.dispatchEvent(new DragEvent('dragend',{bubbles:true}));return;}"
          "var a=item('動かす');var s=a.previousElementSibling;while(s&&!s.classList.contains('section-label'))s=s.previousElementSibling;"
          "var mv=Object.keys(localStorage).filter(function(k){return k.indexOf('mv:')===0;});"
          "var t=document.getElementById('tb-move-broken');"
          "document.documentElement.setAttribute('data-res',JSON.stringify({sec:s?s.textContent.trim():null,mv:mv,toast:t?t.textContent:null}));"
          "},700);});</script>")

    def test_refused_and_restored(self):
        self.start_deck()
        self.write_real_board(extra=self.JS)
        with open(self.board, encoding="utf-8") as f:
            t = f.read()
        t = t.replace('<div class="section-label">今日の予定</div>', self.ROWS, 1)
        with open(self.board, "w", encoding="utf-8") as f:
            f.write(t)
        self.assertEqual(dw.board_broken_reason(t), "項目の入れ子・閉じタグの欠落")
        before = pathlib.Path(self.board).read_bytes()
        dom = self.open_page(self.board, budget=6000)
        m = re.search(r'data-res="([^"]*)"', dom)
        self.assertIsNotNone(m, "読み直した後の確かめが動いていない")
        res = json.loads(html_unescape(m.group(1)))
        self.assertEqual(res["sec"], "今日の予定")          # 元の位置へ戻った（読み直した）
        self.assertEqual(res["mv"], [])                     # localStorage に残していない
        self.assertIn("ボードの形が崩れているため、移動をボードのファイルに書きませんでした", res["toast"] or "")
        self.assertEqual(pathlib.Path(self.board).read_bytes(), before)
        self.assertIn("/board/move", POSTS)


class TestSwallowInBrowser(BrowserCase):
    """K16（Deck v2.17・board_edit.py v1.13 の _swallow_open）の基準＝画面から消える要素がある形と、実行されるはずの board.js が実行されない形
    （2026-11-10 ユーザー決定）を、Chrome の DOM で確かめる。
    tests/swallow_cases.py の板（実物のテンプレートに項目2つ・見出し2つ・Deck の要素2つ。どれにも data-probe を付ける）に形を1つずつ入れて開き、
    「_swallow_open が当たる ⇔ data-probe の要素のどれかが、DOM に同じ名前の HTML の要素として無いか、board.js が動かない」を1つの形を1ページで見る
    （board.js が動いたかは、読み込み時に board.js が書く #loaded-at で見る。swallow_cases.NO_BOARD_JS の形は、board.js の読み込みがまるごと無い
    板なので、当たらず board.js も動かないことを見る＝K16 にはせず、消す書き込みを K17 で断る）。DOM は、head に
    defer で置いた probe.js が読み込みの後に数える（形が後ろを飲み込んでも動く）。CASES の真偽が DOM と合うことも見る。"""

    PROBE_JS = ("var ns='http://www.w3.org/1999/xhtml',seen=[];"
                "document.querySelectorAll('[data-probe]').forEach(function(e){if(e.namespaceURI===ns)seen.push(e.getAttribute('data-probe')+':'+e.localName);});"
                "document.documentElement.setAttribute('data-seen',seen.join(','));")

    def dom(self, text, name):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run(browser_cmd(BROWSER, self.profile, "--disable-sync", "--disable-background-networking",
                                       "--disable-component-update", "--virtual-time-budget=1500",
                                       "--dump-dom", pathlib.Path(p).as_uri()), capture_output=True, timeout=90)
        return r.stdout.decode("utf-8", "replace")

    CUT = "ブラウザが行として読めていない所があります"

    def test_head_board(self):
        """head の形の板（テンプレートのまま）では、本文のどの形でも board.js が動き、「当たる ⇔ 消えた要素がある ⇔ ⑦が出る ⇔ D&D の行が無い」
        （2026-11-10 ユーザー決定。@JS@ の形は末尾の形の板だけ）。"""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import swallow_cases as sc
        with open(os.path.join(self.dir, "probe.js"), "w", encoding="utf-8") as f:
            f.write(self.PROBE_JS)
        with open(os.path.join(ASSETS, "board-template.html"), encoding="utf-8") as f:
            t = sc.board(f.read(), datetime.date.today(), tail=False).replace("</title>", '</title>\n<script src="probe.js" defer></script>', 1)
        n = cut = 0
        for i, (snip, want) in enumerate([("n", False)] + sc.CASES):
            if snip.startswith("@JS@"):
                continue
            with self.subTest(snippet=snip):
                page = sc.page(t, snip)
                hit = dw._swallow_open(page)
                dom = self.dom(page, "h%03d.html" % i)
                m = re.search(r'<html[^>]*\sdata-seen="([^"]*)"', dom)
                self.assertIsNotNone(m, "probe.js が動いていない")
                lost = [x for x in sc.PROBES if x not in set(m.group(1).split(","))]
                m2 = re.search(r'id="loaded-at"[^>]*>([^<]*)<', dom)
                self.assertTrue(m2 and m2.group(1).strip(), "board.js が動いていない")
                self.assertEqual(hit is not None, bool(lost), (hit, lost))
                self.assertEqual(self.CUT in dom, bool(lost), lost)
                self.assertEqual(dom.count('draggable="true"') == 0, bool(lost))
                n += 1
                cut += bool(lost)
        self.assertGreater(cut, 50)
        self.assertGreater(n - cut, 50)

    def test_cut_only(self):
        """形の中に行の部品を書いた形（swallow_cases.CUT_ONLY）は、head の板でも末尾の板でも、K16 が当たり、board.js が動き、⑦が出る。"""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import swallow_cases as sc
        with open(os.path.join(ASSETS, "board-template.html"), encoding="utf-8") as f:
            tpl = f.read()
        for tail in (False, True):
            t = sc.board(tpl, datetime.date.today(), tail=tail)
            for i, snip in enumerate(sc.CUT_ONLY):
                with self.subTest(tail=tail, snippet=snip):
                    page = sc.page(t, snip)
                    self.assertIsNotNone(dw._swallow_open(page))
                    dom = self.dom(page, "c%d%02d.html" % (tail, i))
                    m2 = re.search(r'id="loaded-at"[^>]*>([^<]*)<', dom)
                    self.assertTrue(m2 and m2.group(1).strip(), "board.js が動いていない")
                    self.assertIn(self.CUT, dom)
            for i, snip in enumerate(sc.CUT_MISS):
                with self.subTest(tail=tail, miss=snip):
                    page = sc.page(t, snip)
                    self.assertIsNotNone(dw._swallow_open(page))     # K16 は当たる
                    dom = self.dom(page, "m%d%02d.html" % (tail, i))
                    m2 = re.search(r'id="loaded-at"[^>]*>([^<]*)<', dom)
                    self.assertTrue(m2 and m2.group(1).strip(), "board.js が動いていない")
                    self.assertNotIn(self.CUT, dom)                   # ⑦は出ない（見逃しの限界）

    def test_cut_false_positive_and_limit(self):
        """K16 に当たらない形（swallow_cases.NO_CUT）では⑦が出ず D&D の行があり、限界の形（CUT_LIMIT・エスケープした文字）では⑦が出る。"""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import swallow_cases as sc
        with open(os.path.join(ASSETS, "board-template.html"), encoding="utf-8") as f:
            tpl = f.read()
        for tail in (False, True):
            t = sc.board(tpl, datetime.date.today(), tail=tail)
            for i, (snip, cut) in enumerate([(x, False) for x in sc.NO_CUT] + [(x, True) for x in sc.CUT_LIMIT]):
                with self.subTest(tail=tail, snippet=snip):
                    page = sc.page(t, snip)
                    self.assertIsNone(dw._swallow_open(page))
                    dom = self.dom(page, "f%d%02d.html" % (tail, i))
                    m2 = re.search(r'id="loaded-at"[^>]*>([^<]*)<', dom)
                    self.assertTrue(m2 and m2.group(1).strip(), "board.js が動いていない")
                    self.assertEqual(self.CUT in dom, cut)
                    self.assertEqual(dom.count('draggable="true"') > 0, not cut)

    def test_migrated_board(self):
        """末尾の形の板を migrate_board_js で移した板は、board.js が動き、消えた要素も⑦も無く、D&D の行がある（Deck v2.18）。"""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import swallow_cases as sc
        with open(os.path.join(self.dir, "probe.js"), "w", encoding="utf-8") as f:
            f.write(self.PROBE_JS)
        with open(os.path.join(ASSETS, "board-template.html"), encoding="utf-8") as f:
            tail = sc.page(sc.board(f.read(), datetime.date.today(), tail=True), "n")
        moved = dw.migrate_board_js(tail)
        self.assertIsNotNone(moved)
        moved = moved.replace("</title>", '</title>\n<script src="probe.js" defer></script>', 1)
        dom = self.dom(moved, "moved.html")
        m = re.search(r'<html[^>]*\sdata-seen="([^"]*)"', dom)
        self.assertEqual([x for x in sc.PROBES if x not in set(m.group(1).split(","))], [])
        m2 = re.search(r'id="loaded-at"[^>]*>([^<]*)<', dom)
        self.assertTrue(m2 and m2.group(1).strip())
        self.assertNotIn(self.CUT, dom)
        self.assertGreater(dom.count('draggable="true"'), 0)

    def test_hits_iff_elements_lost(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import swallow_cases as sc
        with open(os.path.join(self.dir, "probe.js"), "w", encoding="utf-8") as f:
            f.write(self.PROBE_JS)
        with open(os.path.join(ASSETS, "board-template.html"), encoding="utf-8") as f:
            t = '<script src="probe.js" defer></script>\n' + sc.board(f.read(), datetime.date.today())
        hits = 0
        for i, (snip, want) in enumerate([("n", False)] + sc.CASES):
            with self.subTest(snippet=snip):
                page = sc.page(t, snip)
                hit = dw._swallow_open(page)
                hits += hit is not None
                dom = self.dom(page, "b%03d.html" % i)
                m = re.search(r'<html[^>]*\sdata-seen="([^"]*)"', dom)
                self.assertIsNotNone(m, "probe.js が動いていない")
                seen = set(m.group(1).split(","))
                lost = [x for x in sc.PROBES if x not in seen]
                m2 = re.search(r'id="loaded-at"[^>]*>([^<]*)<', dom)
                if not (m2 and m2.group(1).strip()):
                    lost.append("board.js")
                if snip in sc.NO_BOARD_JS:
                    self.assertIsNone(hit)
                    self.assertEqual(lost, ["board.js"])
                    continue
                self.assertEqual(hit is not None, bool(lost), (hit, lost))
                self.assertEqual(want, bool(lost))
                if "board.js" not in lost:
                    # board.js が動いた（末尾の形の板でも、後ろの閉じタグで閉じて board.js を飲み込まない形）なら、消えた要素があるときだけ
                    # 「ボードの点検」の⑦（TB_CUT）が出て、D&D の行が無くなる
                    self.assertEqual(self.CUT in dom, bool(lost), lost)
                    self.assertEqual(dom.count('draggable="true"') == 0, self.CUT in dom)
        self.assertEqual(hits, sum(w for _s, w in sc.CASES))
        # DECK の START マーカーの直前の、後ろのコメントの --> で閉じるコメントは、消える要素が無いので当てない。board.js は動き、「ボードの点検」の②を出す
        page = sc.page(t, "n").replace("<!-- DECK:AUTO:START -->", "<!-- x\n<!-- DECK:AUTO:START -->", 1)
        self.assertIsNone(dw._swallow_open(page))
        dom = self.dom(page, "d.html")
        self.assertIn('id="tb-board-check"', dom)
        self.assertIn("Deck の予約領域（DECK:AUTO の目印）がそろっていません", dom)


if __name__ == "__main__":
    unittest.main()
