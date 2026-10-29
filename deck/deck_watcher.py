#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deck v2.5 — Claude Code 全セッション常駐ウォッチャー。

~/.claude/projects/<エンコード済みパス>/<session-id>.jsonl（セッション transcript）を
監視し、today-board の board.html 内
<!-- DECK:AUTO:START --> 〜 <!-- DECK:AUTO:END --> マーカー間だけを
生成 HTML で置換する。マーカー外の自動書き換えは次に限られる:
ユーザーが board.js の D&D で行ったタスク移動の反映（v1.6・下記受信サーバ経由）、
手書きセクションの完了表示（done-item / strike）を状態チップに合わせて揃える整合
（v1.8・class 属性のトークンだけを足し引きし、テキスト・順序・チップは変えない）、
日付の切り替えで作る今日のボード（v2.2）、ヘッダの値（進捗・<title> の日付・#upd-time）を
計算し直すこと（v2.2）、欠けた DECK マーカーを足すこと（マーカーが2つとも無いときだけ。Deck が書いた部分が
空行だけを挟んでひと続きに残っていればそれを囲み、間に別の行があれば足さない〔v2.5〕。Deck が書いた部分が1つも無ければ、
<footer> がちょうど1つのときにその直前へ足す〔v2.2〕）、引き継いだボードの印（<div class="board"> の data-tb-rolled / data-tb-rolled-fp）を
手書き部分が Deck 以外の書き手で変わったときに外すこと、印の無い板に残った data-tb-rolled-fp を外すこと、
D&D の反映で data-tb-rolled-fp を書き直すこと（v2.3）。
タスクの文言は書き換えない。以上は board.html の中の話で、board.html の外では deck/ の state.json・sound.json・
watcher.log のほか、board.html と同じフォルダの history/（日付の切り替えで退避した元のボードと、形が崩れる前の版・v2.4）・
state.json の date・board.css / board.js / cat.png（スキルの assets/ と中身が違うものだけ・v2.2 / v2.3）と、
多重起動ガードのロックファイル（%TEMP% の下の today-board-deck-locks フォルダ・v1.9）に書く。

タスクは transcript 内の TaskCreate / TaskUpdate（旧形式 TodoWrite）ツール呼び出しを
時系列に畳み込んで再構築する（無いセッションの情報源は下記 v2.0）。transcript は数十 MB になりうるため、ファイルごとに
読了バイトオフセットを deck/state.json に永続化し、追記分だけを読む。

v1.6: 常駐監視モードでのみ 127.0.0.1:8737 に受信専用 HTTP サーバを立て、
board.js からのドロップ通知（POST /board/move）を受けて board.html の手書き
3セクション（今日の予定/今日中/明日以降）間で item ブロックを再配置し、
進捗行を再計算する。外部ネットワーク通信（送信）はしない。

v1.7: 時刻トリガーの通知音を Deck 側に移した。ブラウザは自動再生制限のため、
ページ上でユーザー操作が一度も無いと音を出せない（board.html は 5 分ごとに全リロード
されるため、クリックで得た解除も最大 5 分で失効する）。Deck は board.html の時刻付き
タスクを 5 秒ごとに判定し（board.html を読み直すのは変化したときだけ）、予定時刻に達した未完了タスクを
winsound で鳴らす。
設定 UI は board.js の⚙パネルのままで、値と試聴要求は POST /sound/config で受ける。
✎ による時刻の手動変更（board.js の localStorage にしかない）は POST /board/times で
中継してもらい、上書きがあればその時刻で発火判定する。

v1.8: 手書きセクションの完了表示を HTML 正本ごと整合させる（normalize_done_marks）。
board.js の自動整合は表示層（DOM）だけなので、正本には「済チップはあるのに done-item が
無い」といった不整合が残り続けていた。チップを唯一の真実として done-item / strike を
足し引きし、変更が無ければ書き込まない。

v1.9: 多重起動ガードのロックを board.html のパスに紐づけた。v1.8 以前はロックが
スクリプトの置き場所（SCRIPT_DIR/deck.lock）にあったため、deck_watcher.py のコピーが
2 箇所にあると両方が同時に常駐でき、同じ board.html を奪い合った。詳細と移行の扱いは
「多重起動ガード」節の設計コメントに書いた。

v2.0: TaskCreate に依存しない多情報源の収集。Claude Code 2.1.233 以降、新しいモデルでは
TaskCreate / TaskUpdate / TodoWrite が既定で提供されず、それに頼るカードは「タスク未登録」に
なっていた。カードの情報源を次の優先順で選ぶ:
  ① TaskCreate / TaskUpdate / TodoWrite（従来どおり。metadata.plan の計画リンクも維持）
  ② デスクトップアプリの update_plan（計画一覧）＋ wrap_up（ターンの締め・利用者への問い）
  ③ どちらも無ければ活動（最後の会話イベントの種別と時刻）から「作業中／応答なし／入力待ち」
あわせて、2.1.300 以降に記録される API リクエストの行（過去の tool_use の写しを含む）を
畳み込みから除外し、表示・並び順の時刻を「最後の会話イベントの時刻」にした。

v2.1: 同じ PC の複数ユーザーで受信ポートを分け合う（2026-10-25 に同じ PC の別アカウントで、後から起動した側が 8738 で受信し、先に起動した側のポートへの要求が 403 になることを確認・n=1。逆向きは未確認）。v2.0 までは 127.0.0.1:8737 固定で、
要求がどのボードから来たかを確かめていなかったため、①後から起動した Deck はポートを取れず
D&D・通知音の設定が効かない ②別ユーザーのボードの操作が先に起動した Deck に届き、その人の
sound.json・board.html を書き換えうる——の 2 つが起きうる作りだった（コードの読解による。2 人のユーザーでの実測は無い）。v2.1 は ①8737〜8746 のうち空いている
最初の 1 つで受信し ②board.js が ?board=<ボードの URL> で自分のボードを申告し、Deck は
自分の board.html と一致しない要求（申告なし・読めない申告を含む）を読み書きとも 403 で断る。
照合はドライブ部分を I/O なしで先に比べ、同じドライブのときだけ realpath で比べる
（UNC・デバイスパスは照合しない）。あわせて Host が「127.0.0.1:<自分のポート>」でない要求と、
Origin が付いていて値が "null"（file:// のページ）以外の要求を断り（Origin の無い要求は通す）、CORS の許可も "*" から "null" に絞った。
さらに、起動ごとに乱数のトークンを作り、受信ポートと一緒に board.html の DECK:AUTO 領域へ
<span id="deck-key" hidden data-port=… data-k=…> として書く。board.js はそれを読み、そのポートへ
だけ ?k=<トークン> を添えて送る。Deck はトークンが一致しない要求を 403 で断る（Origin: null を
送る sandbox iframe など、ボード以外のページからの要求を止めるため）。

v2.2: 日付が変わったら Deck が今日のボードを作る（2026-10-27 ユーザー承認の設計 A）。
2026-10-25〜27 に、複数のセッションが today-board スキルを通さずに board.html へ直接書き足し続け、
新しい日のボードが2日間発行されなかった。日付の古い板では board.js の発行済みボード判定が偽になり、
Deck への書き込み4経路が止まる。そこで日付の切り替えを Claude の手順から外し、Deck が持つ。
元のボードは history/ へ退避し、終わっていない項目を引き継ぐ（詳細は「日付の切り替え（v2.2）」節）。
あわせて、Claude が直し忘れても正しい値に戻るよう、進捗・<title> の日付・#upd-time を Deck が
計算し直し、board.html と同じフォルダの state.json の date も今日にそろえる（local モードのときだけ）。

v2.3: Claude が手順を守らなくても残らない・巻き戻らないようにする（2026-10-28 ユーザー承認）。
①引き継いだボード（data-tb-rolled）で、Deck 以外の書き手が手書き部分を変えたら（#upd-time と同じ
  指紋の変化）、Deck が data-tb-rolled を外す。v2.2 の時点の SKILL.md は、印のある板での朝の計画を create と
  決めていたが、別のセッションが update で行を直したため印が外れず、「今日の予定はまだ決めていません」が
  出続けた（v2.3 の SKILL.md では、印が外れた後の板の朝の計画は update になる）。
  切り替えたときの指紋を data-tb-rolled-fp として板に持たせるので、Deck が止まっている間に書き換えられた
  板も、起動直後の1周目で外せる。引き継いだ行の data-carried-from / data-orig-time（行ごとのチップ）は外さない。
②スキルの静的ファイル（board.css / board.js / cat.png）を、起動時と ASSET_SYNC_SEC ごとに board.html の
  隣へそろえる。v2.2 までは日付の切り替えのときだけで、Claude が create を飛ばすと古い版が残った。

v2.4: ボードの形が崩れたとき、崩れる前の版を残す（2026-10-28 ユーザー承認）。Deck はマーカー間を書き直すために
  board.html を読むたびに（inject。日付の切り替え・通知音・D&D の反映のために読むときは確かめない）
  形（_scan_board がすべての item を拾えるか＝board_structure_ok）を確かめ、形が正しい版のバイト列を
  メモリに1つだけ持つ（LASTGOOD_MAX_BYTES まで）。正しい形から崩れた形に変わったのを見つけたら、持っていた
  版を history/board-<その版の日付>-lastgood-<HHMMSS>.html へ退避し、watcher.log に1行残す。同じ崩れが続く
  間は退避し直さない（形が正しく戻ったら、次の崩れでまた退避する）。Deck は板を直さない。退避した間は、
  DECK 領域に <span id="deck-lastgood" hidden data-file="history/…"> を書き、board.js が知らせに添える。

v2.5: マーカーのコメントだけが2つとも消え、Deck が書いた部分（接続情報の span・「監視ねこ」「全セッション」の見出し・
  カード）が残った板で、残った部分を囲む（2026-10-29）。v2.4 までは <footer> の前に空の1組を足していたため、古い部分が
  マーカーの外に残り続けた。見分ける対象は skill/SKILL.md「ボードの点検」の②と同じ（deck_written_part）。Deck が書いた
  部分の間に別の行・見分けられない行が挟まるときはマーカーを足さず（ユーザーの行を囲まない）、watcher.log に理由を残す。
  Deck の部分の外側（前・後ろ）にある行は見ずに、Deck の部分だけを囲む（そこにある行は、書き換え済みの Deck の行も含めて目印の外に残る）。
  マーカーが片方だけ残った板は従来どおり直さない。

制約: Python 標準ライブラリのみ・単一ファイル・外部ネットワーク通信なし
（127.0.0.1 限定の受信ポート 1 つのみ。8737〜8746 のうち空いている 1 つ・v2.1）・
projects/ は読み取り専用。

使い方:
    python deck_watcher.py            # 常駐（5秒ポーリング。transcript か board.html の変化・監視ねこの表示の変化・
                                      #   時間経過による状態の切り替えのときだけ再生成。あわせて、board.html か日付が
                                      #   変わったときなどに日付の切り替えを確かめ〔v2.2〕、起動時と ASSET_SYNC_SEC ごとに
                                      #   静的ファイルをそろえる〔v2.3〕）
    python deck_watcher.py --once     # 1回生成して終了（テスト用）
    python deck_watcher.py --rollover-once [--today YYYY-MM-DD] --board PATH
                                      # 日付の切り替えを1回だけ試して終了（テスト用・v2.2）

テスト用オプション（ユーザーデータを汚さずに検証するためのパス差し替え。通常運用では不要）:
    --projects-dir PATH / --board PATH / --state PATH / --skill-assets PATH
    --today YYYY-MM-DD（--rollover-once と一緒のときだけ受け付ける。「今日」を差し替える）
"""

import array
import calendar
import hashlib
import hmac
import html
import io
import json
import math
import os
import re
import secrets
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:  # 通知音の再生（Windows 専用の標準ライブラリ）。無い環境では鳴らさず継続する
    import winsound
except ImportError:  # pragma: no cover — 非 Windows
    winsound = None

# ---------------------------------------------------------------- 定数

HOME = os.path.expanduser("~")
DEFAULT_PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
DEFAULT_BOARD_PATH = os.path.join(HOME, ".claude", "today-board", "board.html")

# 任意の連携: ログ自動退避の常駐ツールを併用している場合、その状態ファイルを読んで
# 「監視ねこ」セクションに生死を表示する（読み取り専用）。last が古いこと自体が
# 「止まっている」証拠になる。ファイルが無ければ何も表示しない（既定＝連携なし）。
# 形式は "key : value" の行並びで、last（最終確認時刻）・state（OK 等）・
# mirror・archives を見る。
LOG_GUARD_STATUS_PATH = os.path.join(HOME, ".claude", "log-guard", "status.txt")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(SCRIPT_DIR, "watcher.log")
DEFAULT_STATE_PATH = os.path.join(SCRIPT_DIR, "state.json")

# 多重起動ガードのロック置き場（v1.9）。スクリプトの隣ではなく、board.html のパスから
# 決まるファイル名で一時ディレクトリに置く（理由は「多重起動ガード」節の設計コメント）。
LOCK_DIR = os.path.join(tempfile.gettempdir(), "today-board-deck-locks")
# v1.8 以前は SCRIPT_DIR/deck.lock だった。v1.9 は開きも消しもしない（同節の「旧 deck.lock の扱い」）。

MARKER_START = "<!-- DECK:AUTO:START -->"
MARKER_END = "<!-- DECK:AUTO:END -->"

BOARD_MOVE_PORT = 8737          # 受信ポートの先頭（127.0.0.1 限定・受信のみ）
BOARD_PORT_COUNT = 10           # 8737〜8746 のうち空いている最初の 1 つで受信する（v2.1）。
                                # board.js は board.html の接続情報（data-port）でポートを知る
REJECT_LOG_SEC = 60             # 別ボードからの要求を断った記録は、この間隔に 1 行へまとめる
MOVABLE_SECTIONS = ("今日の予定", "今日中", "明日以降")  # D&D 移動の対象セクション

# 通知音（v1.7）: 設定と発火済み記録の保存先。ブラウザの localStorage は読めないため
# 「どの時刻トリガーを鳴らし終えたか」は Deck 側で持つ（日付が変わったらリセット）。
SOUND_STATE_PATH = os.path.join(SCRIPT_DIR, "sound.json")
SOUND_RATE = 22050              # 合成 WAV のサンプリング周波数
SOUND_GAIN = 0.08               # v1.7 より前の board.js が WebAudio（GainNode）で鳴らしていたときと同値
SOUND_FADE_SEC = 0.008          # 各音の立ち上がり/立ち下がり（クリックノイズ防止）
SOUND_MAX_SEC = 3.0             # 合成する音の長さの上限（暴走ガード）
ALARM_GRACE_MIN = 5             # 予定時刻をこれ以上過ぎた分はまとめて鳴らさない（board.js と同値）
DEFAULT_SOUND_TYPE = "std"
OVR_MAX_ENTRIES = 500           # 受け取る時刻上書きの上限（暴走・肥大ガード）
PENDING_MAX = 200               # 未確認通知の保持上限（同上）

# 「HH:MM」の抽出（board.js の parseHM と同じく先頭一致で拾う）
_TIME_HM_RE = re.compile(r"(\d{1,2}):(\d{2})")

# v1.7 より前の board.js にあった SOUNDS と同一定義（いまの board.js には無い）。各音は (周波数Hz, 開始秒, 終了秒) の並び。
# WebAudio の OscillatorNode 既定波形は正弦波なので、こちらも正弦波で合成する。
SOUND_DEFS = {
    "std": ((880.0, 0.0, 0.18), (1175.0, 0.25, 0.45)),
    "chime": ((659.0, 0.0, 0.35), (523.0, 0.4, 0.9)),
    "pip": ((1047.0, 0.0, 0.12),),
    "bell": ((523.0, 0.0, 1.2),),
}

ACTIVE_WINDOW_SEC = 48 * 3600   # この時間内に mtime 更新があったセッションのみ表示
STATE_PRUNE_SEC = 7 * 24 * 3600  # これ以上更新のないファイルの状態は捨てる
POLL_SEC = 5                    # ポーリング間隔
MAX_LOG_BYTES = 1024 * 1024     # 起動時にこれを超えていたら切り詰め
TITLE_MAX_CHARS = 80            # 表示文字列の上限（超過は…で省略）
GUARD_STALE_SEC = 300           # 状態ファイルの last がこれより古ければ「停止」と判定
GUARD_STATUS_MAX_BYTES = 64 * 1024  # 状態ファイルの読み取り上限（暴走・巨大化ガード）
MAX_TAIL_UNTERMINATED = 4 * 1024 * 1024  # 改行未達の末尾行を保留する上限（暴走防止）

# 行を json.loads する前の粗フィルタ用キーワード（これらを含まない行は捨てる）。
# update_plan / wrap_up は「呼び出しそのもの」の形（tool_use ブロックの name の直後に input が
# 続く形）で絞る。道具名だけで拾うと、2.1.300 以降の transcript に記録される道具定義・
# システムプロンプトの写し（数 MB の行）まで json.loads することになるため（v2.0 実測）。
PLAN_TOOL = "mcp__ccd_turn__update_plan"
WRAP_TOOL = "mcp__ccd_turn__wrap_up"
LINE_KEYWORDS = (
    '"TaskCreate"', '"TaskUpdate"', '"TodoWrite"',
    '"name":"%s","input":' % PLAN_TOOL, '"name":"%s","input":' % WRAP_TOOL,
    '"custom-title"', '"ai-title"', '"type":"summary"', '"type": "summary"',
)

# API リクエストの記録行（2.1.300 以降）。過去の会話の写し（tool_use を含む）を持つため、
# 畳み込みに入れるとタスクが二重に数えられる。行頭で判定して最初に捨てる（v2.0）。
SKIP_LINE_PREFIX = '{"type":"api-request'

# ターンの途中（ツール実行中・応答生成中）のまま、これ以上 transcript に動きが無ければ
# 「進行中」ではなく「応答なし」とみなす。実測（本人環境・2026-10-22 時点の直近30日・ターン内の
# 連続イベント間隔 45,649 件）では p99 が 125 秒、15 分超が 88 件（0.19%）だった（v2.0）。
TURN_STALE_SEC = 15 * 60
ASK_TOOL = "AskUserQuestion"     # 結果待ちなら利用者の回答待ち＝保留（v2.0）
# 結果待ちのまま長く止まっても「応答なし」と呼ばない道具（サブエージェント待ち）。
# 15 分超の空白 88 件の直前の道具は Agent 37／SendMessage 19／AskUserQuestion 12／
# Bash 8／Read 4／その他（Reviewer の実測・2026-10-22）。Task は Agent の旧名。
WAIT_TOOLS = ("Agent", "Task", "SendMessage")
LAST_EVENT_SCAN_LINES = 200     # 末尾の会話イベントを探して遡る行数の上限（暴走防止）

_lock_fd = None  # 多重起動ガードのファイル記述子（プロセス生存中は開いたまま保持）

# ---------------------------------------------------------------- ログ


def _truncate_log_if_needed():
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_BYTES:
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.write("")  # 切り詰め（ローテーション不要の方針）
    except OSError:
        pass


def log(msg):
    _truncate_log_if_needed()  # 常駐が長期間続いても 1MB 超で成長しない（起動時だけでなく毎回チェック）
    line = "%s %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 多重起動ガード
#
# v1.9: ロックを「スクリプトの置き場所」から「共有資源＝board.html のパス」へ付け替えた。
# v1.8 以前は SCRIPT_DIR/deck.lock だったため、deck_watcher.py のコピーが 2 箇所にあると
# 別々のロックを取って両方が同時に常駐でき、同じ board.html を奪い合った（ロックが
# ディレクトリ単位であることは v1.8 以前の deck_watcher.py の LOCK_PATH の定義で
# 確認できる）。
# 2026-08-05 の作者の環境での稼働体切替では、旧コピー（開発用の別フォルダ）が 16:03:49 起動・16:07:30 最終
# 書き込み、新コピー（~/.claude/today-board/deck）が 16:08:21 起動で、**両者が同時に
# board.html を書いていた時間はログからは確定できない（重なりの有無・長さは未検証）**。
# ログがそれぞれの SCRIPT_DIR に分かれるため、併存しても気づきにくい。配布物でも同型で、
# setup.bat で配置したあと展開フォルダに残った start-deck.bat を叩けば 2 本目が立った（v1.8 以前。
# v1.9 以降は下の設計により 2 本目がすぐ終わる）。
#
# 設計:
# - ロックファイル名 = board.html のパスを正規化（realpath + normcase）した文字列の SHA-1。
#   同じ board を見る 2 本は置き場所が違っても同じファイルを奪い合い、2 本目が負ける。
#   違う board を見る 2 本（--board を使ったテスト実行など）は別ファイルなので共存する。
# - 置き場所は board.html の隣ではなく一時ディレクトリ配下の専用フォルダ。board.html が
#   未発行（ファイルもフォルダも無い）でも常駐する仕様のため、実体の存在に依存させない。
#   パス正規化は文字列操作で完結するので、board.html が無くてもロック名は決まる。
# - 古いロックが次の起動を妨げることはない。排他は OS のファイルロック
#   （Windows: msvcrt.locking / POSIX: fcntl.flock）で、プロセスが強制終了されても
#   OS が必ず解放する。残るのはロック *ファイル* だけで、それは次の保持者が中身を
#   上書きする空き家にすぎない（2026-08-05 に pythonw が Windows に強制終了された
#   実績がある＝Event 1002 Application Hang。この性質は必須）。
# - 先頭 1 バイトだけをロック領域とし、保持者情報（PID・board・スクリプト位置・ログ位置・
#   起動時刻）はその外側＝1 バイト目以降に JSON 1 行で書く。Windows のロック領域は
#   他プロセスからの読み取りも弾きうるため、情報は必ずロック領域の外に置く。
#
# 旧 deck.lock（SCRIPT_DIR 配下）の扱い: **消さずに放置する**。v1.9 は一切開かない
# ので、残っていても中身も存在も無害な空きファイルにすぎない。削除を試さないのは、まだ
# 動いているかもしれない v1.8 の常駐が掴んでいるファイルに手を出さないため（POSIX では
# 削除できてしまい、旧版のガードを壊す）。掃除は uninstall.ps1 の削除対象に任せる。
# なお v1.8 の常駐が動いたまま v1.9 を起動すると、両者は別のロックを見るので二重起動は
# 防げない。版を上げるときは先に旧プロセスを止めること（移行時の 1 回だけの注意）。

_LOCK_INFO_OFFSET = 1       # 0 バイト目＝ロック領域。保持者情報はその外側に書く
_LOCK_INFO_MAX_BYTES = 4096  # 読み出し上限（壊れたファイルを延々読まないためのガード）


def board_lock_path(board_path):
    """board.html のパスから一意に決まるロックファイルのパス（置き場所に依存しない）。"""
    key = os.path.normcase(os.path.realpath(board_path))
    digest = hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    return os.path.join(LOCK_DIR, "deck-%s.lock" % digest)


def _write_lock_info(fd, board_path):
    """保持者情報をロック領域の外（1 バイト目以降）に JSON 1 行で書く。失敗しても続行。"""
    info = {
        "pid": os.getpid(),
        "board": os.path.abspath(board_path),
        "script": SCRIPT_DIR,
        "log": LOG_PATH,
        "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    data = (json.dumps(info, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        os.lseek(fd, _LOCK_INFO_OFFSET, os.SEEK_SET)
        os.write(fd, data)
        os.ftruncate(fd, _LOCK_INFO_OFFSET + len(data))  # 前の保持者の残骸を切り捨てる
    except OSError as e:
        # 情報が書けなくてもロック自体は有効。2 本目のログが「情報なし」になるだけ。
        log("警告: ロックファイルに保持者情報を書けませんでした: %s" % e)


def _read_lock_info(fd):
    """ロックを持っている 1 本目の情報（辞書）。読めない・壊れていれば None。"""
    try:
        os.lseek(fd, _LOCK_INFO_OFFSET, os.SEEK_SET)
        raw = os.read(fd, _LOCK_INFO_MAX_BYTES)
    except OSError:
        return None
    try:
        info = json.loads(raw.split(b"\n", 1)[0].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return info if isinstance(info, dict) else None


def _format_lock_holder(info):
    """保持者情報 → ログ 1 行分の文字列。"""
    if not isinstance(info, dict):
        return "情報なし（書き込み前か、v1.8 以前の形式）"
    return "pid=%s・board=%s・スクリプト=%s・ログ=%s・起動=%s" % (
        info.get("pid", "?"), info.get("board", "?"), info.get("script", "?"),
        info.get("log", "?"), info.get("started", "?"))


def acquire_single_instance_lock(board_path):
    """board.html ごとの排他ロックを取得する。

    戻り値: (取得できたか, 取れなかった理由＝稼働中の 1 本目の情報 or None)
    取得できた場合、記述子は _lock_fd に保持したままにする（閉じるとロックが外れる）。
    """
    global _lock_fd
    lock_path = board_lock_path(board_path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_BINARY"):  # Windows: 改行変換を挟ませない（バイト位置を確定させる）
        flags |= os.O_BINARY
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        fd = os.open(lock_path, flags, 0o600)
    except OSError as e:
        # ロックを置けない環境では単一インスタンスを保証できない。同じ board への
        # 二重書き込みの方が害が大きいので、起動しない側に倒す（fail-closed）。
        log("警告: ロックファイルを開けません（%s）: %s" % (lock_path, e))
        return False, "ロックファイルを開けません（%s）: %s" % (lock_path, e)
    try:
        os.lseek(fd, 0, os.SEEK_SET)  # ロック領域は必ず先頭 1 バイト（追記位置ではない）
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        holder = _format_lock_holder(_read_lock_info(fd))
        os.close(fd)
        return False, holder
    _write_lock_info(fd, board_path)
    _lock_fd = fd
    return True, None


# ---------------------------------------------------------------- セッション状態（transcript の畳み込み）


def new_session_state():
    """1 transcript 分のパース状態の初期値（state.json にそのまま永続化する形）。"""
    return {
        "offset": 0,          # 読了バイトオフセット
        "size": 0,            # 前回確認時のファイルサイズ
        "cwd": None,          # 最初に見つけた作業ディレクトリ
        "custom_title": None,  # {"type":"custom-title","customTitle":...}（実測スキーマ）
        "ai_title": None,      # {"type":"ai-title","aiTitle":...}（実測スキーマ）
        "summary": None,       # {"type":"summary",...} があれば（未観測・防御的に対応）
        "tasks": [],           # [[id, subject, status, plan], ...] 作成順（plan は metadata.plan / 無ければ None）
        "seq": 0,              # TaskCreate に id が無い場合の連番
        "pending": {},         # tool_use id -> task id（TaskCreate の結果から実 id を拾う用）
        "error": None,         # ファイル単位の読取失敗メッセージ（None なら正常）
        # ---- v2.0: TaskCreate が無いセッション向けの情報源 ----
        "plan_items": None,    # update_plan の畳み込み結果 [[content, status], ...]（未使用なら None）
        "wrap": None,          # 現在のターンの wrap_up {"ask", "blocked", "recap"}（利用者の新しい入力で消す）
        "plan_wrapped": False,  # 最後の update_plan の後に wrap_up があった（表示でだけ全完了扱い）
        "last_event": None,    # 末尾の会話イベント {"kind", "ts", "tools", "question"}
    }


def _task_index(tasks, task_id):
    for i, t in enumerate(tasks):
        if t[0] == task_id:
            return i
    return -1


def _first_str(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def apply_record(st, obj):
    """transcript の 1 行（パース済み JSON）をセッション状態に畳み込む。

    実測済みスキーマ（Claude Code v2.1.219 で確認）:
      {"type":"custom-title","customTitle":"...","sessionId":"..."}
      {"type":"ai-title","aiTitle":"...","sessionId":"..."}
      {"type":"assistant","message":{"content":[{"type":"tool_use","id":"...",
        "name":"...","input":{...}}]},"cwd":"C:\\\\...","timestamp":"...",...}
    未観測・防御的対応（手元の transcript に実例が無いため公知仕様ベース）:
      TodoWrite input {"todos":[{"content","status","activeForm"}]} … 全量書き直し型
      TaskCreate input {subject/content/description, status?,
        metadata?: {"plan": "<対応する計画タスク名>"}} … 新規タスク（plan は v1.5 管制盤対応）
      TaskUpdate input {taskId/task_id/id, status?, subject?} … 状態変更（deleted で削除）
      {"type":"summary","summary":"..."} … セッションタイトル行
    実測済み（v2.0・デスクトップアプリ 2.1.295〜2.1.304 の transcript）:
      mcp__ccd_turn__update_plan input … fold_plan の docstring
      mcp__ccd_turn__wrap_up input {"recap", "ask"?, "actions"?, "blocked"?} … _apply_wrap_up
      user 行（tool_result でも isMeta でもないもの） … 利用者の入力＝新しいターン
    """
    if st["cwd"] is None:
        cwd = obj.get("cwd")
        if isinstance(cwd, str) and cwd:
            st["cwd"] = cwd

    rtype = obj.get("type")
    if rtype == "custom-title":
        v = obj.get("customTitle")
        if isinstance(v, str) and v.strip():
            st["custom_title"] = v
        return
    if rtype == "ai-title":
        v = obj.get("aiTitle")
        if isinstance(v, str) and v.strip():
            st["ai_title"] = v
        return
    if rtype == "summary":
        v = _first_str(obj, ("summary", "title", "text"))
        if v:
            st["summary"] = v
        return

    # ---- tool_use（assistant 行）/ tool_result・利用者の入力（user 行） ----
    # v2.0: 行の type で受け付ける要素を限る。2.1.300 以降は API リクエストの記録行
    # （type=api-request-blob 等）が過去の tool_use の写しを持つため、type を見ないと
    # 同じ TaskCreate / update_plan を二重に畳み込む（粗フィルタでも行頭で捨てている）。
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if rtype == "user" and _is_user_text_line(obj):
        if is_human_prompt(obj) and not _is_interrupt(content):
            st["wrap"] = None  # 利用者が答えた＝前のターンの確認事項は片付いた
        return  # アプリ・サブエージェント由来の差し込み行（turnOrigin が human 以外）は問いを消さない
    if not isinstance(content, list):
        return
    for c in content:
        if not isinstance(c, dict):
            continue
        ctype = c.get("type")
        if ctype == "tool_use" and rtype == "assistant":
            _apply_tool_use(st, c)
        elif ctype == "tool_result" and rtype == "user":
            _apply_tool_result(st, c, obj)


_INTERRUPT_MARK = "[Request interrupted by user"


def _content_text(content):
    """message.content（文字列 or ブロック列）から text を連結して返す。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content
                       if isinstance(c, dict) and isinstance(c.get("text"), str))
    return ""


def _is_interrupt(content):
    return _INTERRUPT_MARK in _content_text(content)


def _is_user_text_line(obj):
    """本文を持つ user 行か（tool_result と isMeta は除く）。誰が送ったかは問わない。"""
    if obj.get("type") != "user" or obj.get("isMeta"):
        return False
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
            return False
        return bool(_content_text(content).strip())
    return isinstance(content, str) and bool(content.strip())


def is_human_prompt(obj):
    """利用者が打った入力（または中断）の user 行か。

    本文を持つ user 行のうち、アプリ・他セッションが差し込む行を除く。実測（2026-10-22・
    直近10日）では turnOrigin に human / task_notification / sdk / peer の4種が出たほか、
    turnOrigin を持たない行もある——古い版に限らず、2.1.304／2.1.308 のサブエージェント
    完了通知も turnOrigin を持たず、origin={"kind": "task-notification"} と
    promptSource（sdk / system）だけを持つ。判定は次の順で、どれかに当たれば除く:
      ① turnOrigin があって human 以外
      ② origin が dict で、その kind があって human 以外
      ③ 本文（ブロック列なら text ブロックごと）の先頭に続く差し込みタグ
         （<system-reminder> / <task-notification> / <cross-session-message>。通知の差し込みと、
         別のセッションから届いた文面）を閉じタグまで取り除くと、何も残らない
    ③で「残り」を見るのは、アプリが利用者の入力の先頭に <system-reminder>…</system-reminder> を
    付けることがあるため（本文が差し込みタグで始まっていても、その後ろは利用者自身の文。
    実測 2026-10-22・直近60日で 9 件。うち 6 件はブロック列の形）。差し込みタグだけの行と、
    閉じタグが無く取り除けない行は利用者の入力とみなさない。turnOrigin=human や
    origin.kind=human の差し込み行もあるため、③は①②と独立に見る。
    """
    if not _is_user_text_line(obj):
        return False
    turn_origin = obj.get("turnOrigin")
    if turn_origin is not None and turn_origin != "human":
        return False
    origin = obj.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = [c.get("text") for c in content
                 if isinstance(c, dict) and isinstance(c.get("text"), str)]
    else:
        return False
    for text in texts:
        rest = _strip_injected_head(text)
        if rest.lstrip().startswith(_INJECTED_PREFIXES):
            continue  # 閉じタグが無い差し込み（取り除けない）＝利用者の文とはみなさない
        if rest.strip():
            return True
    return False


# 利用者の入力に見えるが、アプリ・他セッションが差し込んだ user 行の本文の書き出し
_INJECTED_PREFIXES = ("<system-reminder>", "<task-notification>", "<cross-session-message")
# 先頭の差し込みタグ 1 つ（開きタグから対応する閉じタグまで）
_INJECTED_HEAD_RE = re.compile(
    r"\s*<(system-reminder|task-notification|cross-session-message)\b.*?</\1>", re.S)


def _strip_injected_head(text):
    """本文の先頭に続く差し込みタグを、閉じタグまで順に取り除いた残りを返す。"""
    while True:
        m = _INJECTED_HEAD_RE.match(text)
        if not m:
            return text
        text = text[m.end():]


def _plan_from_metadata(inp):
    """TaskCreate input の metadata.plan（文字列）を取り出す。無ければ None（後方互換）。"""
    meta = inp.get("metadata")
    if isinstance(meta, dict):
        plan = meta.get("plan")
        if isinstance(plan, str) and plan.strip():
            return plan.strip()
    return None


def _apply_tool_use(st, c):
    name = c.get("name")
    inp = c.get("input")
    if not isinstance(inp, dict):
        return

    if name == PLAN_TOOL:
        st["plan_items"] = fold_plan(st.get("plan_items"), inp)
        st["plan_wrapped"] = False  # 一覧が動いた＝wrap_up の「完了扱い」はここで終わる
        return
    if name == WRAP_TOOL:
        _apply_wrap_up(st, inp)
        return

    if name == "TodoWrite":
        todos = inp.get("todos")
        if not isinstance(todos, list):
            return
        tasks = []
        for i, item in enumerate(todos):
            if not isinstance(item, dict):
                continue
            subject = item.get("content")
            if not isinstance(subject, str):
                continue
            status = item.get("status")
            if not isinstance(status, str):
                status = "pending"
            tasks.append(["todo-%d" % i, subject, status, None])
        st["tasks"] = tasks  # 全量書き直し型: 最後の TodoWrite が最新状態
        return

    if name == "TaskCreate":
        subject = _first_str(inp, ("subject", "content", "description", "title"))
        if subject is None:
            return
        status = inp.get("status") if isinstance(inp.get("status"), str) else "pending"
        plan = _plan_from_metadata(inp)
        task_id = _first_str(inp, ("taskId", "task_id", "id"))
        if task_id is None:
            st["seq"] += 1
            task_id = "c%d" % st["seq"]
            tu_id = c.get("id")
            if isinstance(tu_id, str):
                st["pending"][tu_id] = task_id  # 後続の結果行から実 id を拾って差し替える
        st["tasks"].append([task_id, subject, status, plan])
        return

    if name == "TaskUpdate":
        task_id = _first_str(inp, ("taskId", "task_id", "id"))
        if task_id is None:
            return
        idx = _task_index(st["tasks"], task_id)
        status = inp.get("status") if isinstance(inp.get("status"), str) else None
        subject = _first_str(inp, ("subject", "content", "title"))
        if status == "deleted":
            if idx >= 0:
                st["tasks"].pop(idx)
            return
        if idx < 0:
            # 未知 id への更新: 取りこぼし防止でプレースホルダを作る
            st["tasks"].append([task_id, subject or "(不明タスク)", status or "pending", None])
            return
        if subject:
            st["tasks"][idx][1] = subject
        if status:
            st["tasks"][idx][2] = status


_PLAN_STATUSES = ("pending", "in_progress", "completed")


def fold_plan(items, inp):
    """update_plan の入力 1 回分を、それまでの一覧 items に畳み込んだ結果を返す（v2.0）。

    入力の形（デスクトップアプリの道具。公開仕様は無く、transcript の実測で確かめた）:
      {"items": [{"content", "status"}, ...], "scope": ...} … 全量書き直し
      {"advance": true} … 進行中の項目を完了にし、その後ろで最初の未着手を進行中にする
                          （進行中が無ければ先頭の未着手を進行中にする）
      {"done": [番号...], "start": 番号} … 番号は 1 始まり。done を完了にし、start を進行中に
                          する（ほかの進行中は未着手へ戻す）
    この解釈は、各呼び出しにアプリが返す結果文「Plan updated: step K of M is in progress.」
    「Plan shown (M steps).」と突き合わせて、本人環境の 10 セッション・130 回で全件一致した（2026-10-22 測定）。
    範囲外の番号・不正な要素は黙って捨てる（一覧が壊れていても Deck は落とさない）。
    """
    if isinstance(inp.get("items"), list):
        out = []
        for it in inp["items"]:
            if not isinstance(it, dict):
                continue
            content = it.get("content")
            if not isinstance(content, str):
                continue
            status = it.get("status")
            out.append([content, status if status in _PLAN_STATUSES else "pending"])
        return out
    if not isinstance(items, list):
        return items  # 一覧を見る前の差分は適用先が無い（resume で途中から始まった等）
    items = [list(t) for t in items]
    if inp.get("advance") is True:
        cur = next((i for i, t in enumerate(items) if t[1] == "in_progress"), None)
        if cur is None:
            nxt = next((i for i, t in enumerate(items) if t[1] == "pending"), None)
        else:
            items[cur][1] = "completed"
            nxt = next((i for i in range(cur + 1, len(items)) if items[i][1] == "pending"), None)
        if nxt is not None:
            items[nxt][1] = "in_progress"
    done = inp.get("done")
    if isinstance(done, list):
        for n in done:
            if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(items):
                items[n - 1][1] = "completed"
    start = inp.get("start")
    if isinstance(start, int) and not isinstance(start, bool) and 1 <= start <= len(items):
        for t in items:
            if t[1] == "in_progress":
                t[1] = "pending"
        items[start - 1][1] = "in_progress"
    return items


def _apply_wrap_up(st, inp):
    """wrap_up（ターンの締め）を記録する（v2.0）。

    道具の説明文は逐語「it also checks off the task list; no closing update_plan is needed」
    と書くが、アプリが持つ一覧そのものは書き換わらない——wrap_up の後の advance に、
    アプリは wrap_up 前の一覧を基準にした「step K of M」を返す（実測 2026-10-22・
    作者の環境の2セッション（元とそのフォーク）で計4回）。そこで plan_items は変えずに印
    （plan_wrapped）だけを立て、次の update_plan で消す。表示でだけ全完了として扱う。
    ask があればアプリは利用者への問いを表示してターンを終える（blocked=true はそれに加え
    「答えるまで作業が止まる」）。
    """
    def _s(key):
        v = inp.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    st["wrap"] = {"ask": _s("ask"), "blocked": inp.get("blocked") is True, "recap": _s("recap")}
    if isinstance(st.get("plan_items"), list):
        st["plan_wrapped"] = True


def _iso_to_epoch(text):
    """transcript の timestamp（例 2026-10-22T13:47:03.433Z・UTC）→ epoch 秒。読めなければ None。"""
    if not isinstance(text, str) or len(text) < 19:
        return None
    try:
        dt = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return calendar.timegm(dt.timetuple())


def classify_event(obj):
    """会話イベント 1 行 → "busy"（ターンの途中）／"end"（ターンが終わった）／None（対象外）。

    end: assistant の stop_reason が end_turn / stop_sequence、system の stop_hook_summary
         （ターン終了時に記録される）、利用者による中断
    busy: user の本文行（利用者の入力に限らない。通知の差し込みもモデルを動かす）、
          tool_result、それ以外の assistant（tool_use で止まっている等）
    """
    rtype = obj.get("type")
    if rtype == "assistant":
        msg = obj.get("message")
        reason = msg.get("stop_reason") if isinstance(msg, dict) else None
        return "end" if reason in ("end_turn", "stop_sequence") else "busy"
    if rtype == "system":
        return "end" if obj.get("subtype") == "stop_hook_summary" else None
    if rtype == "user":
        if obj.get("isMeta"):
            return None
        msg = obj.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if _is_user_text_line(obj):
            return "end" if _is_interrupt(content) else "busy"
        return "busy" if isinstance(content, list) else None
    return None


def _tool_uses(obj):
    """assistant 行の tool_use ブロック（dict）の一覧。"""
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    return [c for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]


def _ask_question_text(inp):
    """AskUserQuestion の入力 {"questions": [{"question", ...}, ...]} から最初の問い文。"""
    qs = inp.get("questions") if isinstance(inp, dict) else None
    if isinstance(qs, list):
        for q in qs:
            if isinstance(q, dict) and isinstance(q.get("question"), str) and q["question"].strip():
                return q["question"].strip()
    return None


def _scan_last_event(lines):
    """読んだ行の末尾から遡り、最後の会話イベントを返す。無ければ None。

    戻り値 {"kind", "ts", "tools", "question"}。最後のイベントが結果待ちの tool_use なら、
    同じ応答（message.id が同じ assistant 行が続く）の道具名を tools に、AskUserQuestion の
    問い文を question に入れる。1 つの応答は道具ごとに別の行へ分かれて記録されるため。
    """
    found = None
    mid = None
    for line in reversed(lines[-LAST_EVENT_SCAN_LINES:]):
        if not line or line.startswith('{"type":"'):
            continue  # メタ情報の行（タイトル・キュー操作・API 記録等）は先頭が type
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if found is not None:
            # 結果待ちの tool_use の続き: 同じ応答の assistant 行だけを集める
            msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            if obj.get("type") != "assistant" or msg.get("id") != mid:
                break
            _collect_tools(found, obj)
            continue
        kind = classify_event(obj)
        if kind is None:
            continue
        found = {"kind": kind, "ts": _iso_to_epoch(obj.get("timestamp")),
                 "tools": [], "question": None}
        if kind != "busy" or obj.get("type") != "assistant" or not _tool_uses(obj):
            break
        _collect_tools(found, obj)
        msg = obj.get("message")
        mid = msg.get("id") if isinstance(msg, dict) else None
        if mid is None:
            break
    return found


def _collect_tools(found, obj):
    for c in _tool_uses(obj):
        name = c.get("name")
        if isinstance(name, str) and name not in found["tools"]:
            found["tools"].append(name)
        if name == ASK_TOOL and found["question"] is None:
            found["question"] = _ask_question_text(c.get("input"))


def _apply_tool_result(st, c, obj):
    """TaskCreate の tool_result から実タスク id を拾い、仮 id を差し替える。

    実測スキーマ:
      tool_result の content（文字列）: "Task #1 created successfully: <subject>"
      同じ user 行のトップレベル:        "toolUseResult": {"task": {"id": "1", "subject": "..."}}
    ＝実 id は連番の数字文字列で、tool_use の input には含まれない。
    """
    tu_id = c.get("tool_use_id")
    if not (isinstance(tu_id, str) and tu_id in st["pending"]):
        return
    tmp_id = st["pending"].pop(tu_id)
    real_id = _real_task_id_from_result(obj, c)
    if real_id:
        idx = _task_index(st["tasks"], tmp_id)
        if idx >= 0 and _task_index(st["tasks"], real_id) < 0:
            st["tasks"][idx][0] = real_id


_TASK_NUM_RE = re.compile(r"Task #(\d+)\b")


def _real_task_id_from_result(obj, c):
    """実測優先: ① toolUseResult.task.id ② content の "Task #N" パターン。"""
    tur = obj.get("toolUseResult")
    if isinstance(tur, dict):
        task = tur.get("task")
        if isinstance(task, dict):
            tid = task.get("id")
            if isinstance(tid, str) and tid:
                return tid
            if isinstance(tid, int):
                return str(tid)
    content = c.get("content")
    texts = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
    for t in texts:
        m = _TASK_NUM_RE.search(t)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------- 差分読み


def _line_interesting(line, st):
    """json.loads する価値のある行か（粗フィルタ）。"""
    if line.startswith(SKIP_LINE_PREFIX):
        return False
    if (not line.startswith('{"type":"') and '"type":"user"' in line
            and '"tool_use_id"' not in line):
        return True  # 利用者の入力（ターンの区切り・v2.0）。tool_result の行は含めない
    for kw in LINE_KEYWORDS:
        if kw in line:
            return True
    if st["cwd"] is None and '"cwd"' in line:
        return True
    if st["pending"]:
        for tu_id in st["pending"]:
            if tu_id in line:
                return True
    return False


def parse_increment(path, st):
    """st["offset"] 以降の追記分だけを読み、状態を更新する。

    - サイズが縮んでいたら先頭から再パース（状態リセット）
    - 末尾の改行未達行は消費せず次回に回す（追記中ファイルへの耐性）
    ファイルを開けない・読めない場合は st["error"] を立てる。
    """
    try:
        size = os.path.getsize(path)
    except OSError as e:
        st["error"] = "stat失敗: %s" % e
        return
    if size < st["offset"]:
        log("縮小を検知（%s）: 先頭から再パース" % os.path.basename(path))
        fresh = new_session_state()
        st.clear()
        st.update(fresh)
    if size == st["offset"]:
        st["size"] = size
        st["error"] = None
        return

    try:
        with open(path, "rb") as f:
            f.seek(st["offset"])
            chunk = f.read(size - st["offset"])
    except OSError as e:
        st["error"] = "読取失敗: %s" % e
        return

    end = chunk.rfind(b"\n")
    if end == -1:
        # 1 行がまだ書きかけ。上限まで待つ（超えたら諦めて全消費）
        if len(chunk) < MAX_TAIL_UNTERMINATED:
            st["size"] = size
            st["error"] = None
            return
        end = len(chunk) - 1
    consumed = chunk[: end + 1]
    st["offset"] += len(consumed)
    st["size"] = size
    st["error"] = None

    text = consumed.decode("utf-8", errors="replace")
    lines = text.split("\n")
    last = _scan_last_event(lines)
    if last is not None:
        st["last_event"] = last  # この追記分に会話イベントが無ければ前回の値を保つ
    for line in lines:
        if not line or not _line_interesting(line, st):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # 個々の行のパース失敗は捨てる（ファイル自体は継続）
        try:
            apply_record(st, obj)
        except Exception as e:  # noqa: BLE001
            log("警告: レコード畳み込みに失敗（%s）: %r" % (os.path.basename(path), e))


# ---------------------------------------------------------------- state.json 永続化


STATE_VERSION = 4  # 畳み込みロジック変更時に上げる → 全ファイル先頭から再パース
                   # v3: tasks 要素を [id, subject, status] → [id, subject, status, plan] に拡張（v1.5）
                   # v4: plan_items / wrap / last_event を追加し、api-request 行を畳み込みから
                   #     除外した（Deck v2.0）。v3 以前の state.json は版数不一致で破棄され、
                   #     48 時間以内の transcript を先頭から読み直す（初回だけ重くなる）


def load_state(state_path):
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if (isinstance(data, dict) and isinstance(data.get("files"), dict)
                and data.get("v") == STATE_VERSION):
            return data
        log("state.json の版数が異なるため破棄して再パースします")
    except (OSError, ValueError):
        pass
    return {"v": STATE_VERSION, "files": {}}


def save_state(state, state_path):
    fd = None
    tmp = None
    try:
        dir_name = os.path.dirname(state_path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".deck-state-", suffix=".tmp", dir=dir_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, state_path)
        tmp = None
    except OSError as e:
        log("警告: state.json の保存に失敗: %s" % e)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


def prune_state(state, now):
    for key in list(state["files"].keys()):
        entry = state["files"][key]
        if not isinstance(entry, dict) or now - entry.get("seen", 0) > STATE_PRUNE_SEC:
            del state["files"][key]


# ---------------------------------------------------------------- 収集


def list_transcripts(projects_dir, now):
    """projects/<dir>/<session>.jsonl（トップレベルのみ・subagents は除外）で 48h 以内のもの。"""
    results = []
    try:
        project_dirs = os.listdir(projects_dir)
    except OSError:
        return results
    for d in project_dirs:
        pdir = os.path.join(projects_dir, d)
        if not os.path.isdir(pdir):
            continue
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, name)
            if not os.path.isfile(path):
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if now - mtime <= ACTIVE_WINDOW_SEC:
                results.append((path, mtime))
    return results


def collect_sessions(projects_dir, state, now=None):
    """48h 以内の transcript を差分パースし、表示用セッションリストを返す（新しい順）。"""
    if now is None:
        now = time.time()
    sessions = []
    files = state["files"]
    wt_map = state.setdefault("wt", {})  # "プロジェクト/wt名" -> 連番（初観測順・永続）
    for path, mtime in list_transcripts(projects_dir, now):
        entry = files.get(path)
        if not isinstance(entry, dict) or not isinstance(entry.get("st"), dict):
            entry = {"st": new_session_state(), "seen": now}
            files[path] = entry
        entry["seen"] = now
        st = entry["st"]
        for k, v in new_session_state().items():  # 旧バージョン state.json の欠損キー補完
            st.setdefault(k, v)
        prev_error = st.get("error")
        try:
            parse_increment(path, st)
        except Exception as e:  # noqa: BLE001
            st["error"] = "パース失敗: %r" % e
        if st.get("error") and st.get("error") != prev_error:
            # 同一エラーの再ログはしない（5秒ポーリングでのログ洪水防止。ボードのカードには出続ける）
            log("警告: セッション読取不能: %s (%s)" % (os.path.basename(path), st["error"]))
        last = st.get("last_event") if isinstance(st.get("last_event"), dict) else None
        last_ts = last.get("ts") if last else None
        sessions.append({
            "path": path,
            "session_id": os.path.splitext(os.path.basename(path))[0],
            "project": project_display_name(
                st.get("cwd"), os.path.basename(os.path.dirname(path)), wt_map),
            "label": st.get("custom_title") or st.get("summary") or st.get("ai_title"),
            "tasks": _normalize_tasks(st.get("tasks", [])),
            "plan_items": _normalize_plan(st.get("plan_items")),
            "plan_wrapped": st.get("plan_wrapped") is True,
            "pending_tools": list(last.get("tools") or []) if last else [],
            "question": last.get("question") if last else None,
            "wrap": st.get("wrap") if isinstance(st.get("wrap"), dict) else None,
            "turn": last.get("kind") if last else None,
            "error": st.get("error"),
            # 表示と並び順は「最後の会話イベントの時刻」。ファイルの mtime は会話が無くても
            # タイトル行等の追記で進む（本人環境で、8 月に止まったセッションの mtime が
            # 当日になっていた＝v2.0 実測）。時刻が取れないときだけ mtime を使う。
            "mtime": last_ts if isinstance(last_ts, (int, float)) and last_ts <= now + 60 else mtime,
        })
    prune_state(state, now)
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def _normalize_plan(items):
    """state 内の plan_items を [[content, status], ...] に正規化する。未使用なら None。"""
    if not isinstance(items, list):
        return None
    return [t for t in items if isinstance(t, list) and len(t) == 2
            and isinstance(t[0], str) and isinstance(t[1], str)]


def _normalize_tasks(tasks):
    """state 内タスクを [id, subject, status, plan] の 4 要素に正規化する。

    旧形式（3 要素・v1.4 以前）は STATE_VERSION で破棄されるが、防御的に plan=None を
    補完して受け入れる。それ以外の形は捨てる。
    """
    out = []
    for t in tasks:
        if not isinstance(t, list):
            continue
        if len(t) == 4:
            out.append(t)
        elif len(t) == 3:
            out.append(t + [None])
    return out


def project_display_name(cwd, encoded_dirname, wt_map=None):
    """cwd（transcript 実測の実パス）→ 表示名。無ければエンコード済みディレクトリ名で代用。

    ワークツリーはランダム名がノイズになるため「プロジェクト（作業コピーN）」で表示する。
    N はプロジェクトごとに初めて観測した順の連番で、wt_map（state.json に永続）により
    再生成をまたいで安定させる。ワークツリーが 1 つでも「作業コピー1」と付ける（一貫性優先）。
    """
    if isinstance(cwd, str) and cwd.strip():
        parts = [p for p in re.split(r"[\\/]+", cwd.strip()) if p]
        if parts:
            base = parts[-1]
            if "worktrees" in parts:
                i = parts.index("worktrees")
                if i >= 2 and parts[i - 1] == ".claude":
                    proj = parts[i - 2]
                    if wt_map is None:
                        return "%s（wt: %s）" % (proj, base)
                    key = proj + "/" + base
                    num = wt_map.get(key)
                    if not isinstance(num, int):
                        num = 1 + sum(1 for k in wt_map
                                      if k.startswith(proj + "/")
                                      and isinstance(wt_map[k], int))
                        wt_map[key] = num
                    return "%s（作業コピー%d）" % (proj, num)
            return base
    return encoded_dirname or "(不明プロジェクト)"


# ---------------------------------------------------------------- HTML 生成


def _fmt_mtime(mtime, now):
    dt = datetime.fromtimestamp(mtime)
    today = datetime.fromtimestamp(now).date()
    if dt.date() == today:
        return dt.strftime("%H:%M")
    return "%d/%d %s" % (dt.month, dt.day, dt.strftime("%H:%M"))


def _pick_display_task(tasks):
    """表示するタスク（4要素リスト）: 進行中 → なければ未着手の先頭 → 全完了なら末尾。"""
    for t in tasks:
        if t[2] == "in_progress":
            return t
    for t in tasks:
        if t[2] != "completed":
            return t
    if tasks:
        return tasks[-1]
    return None


def _pick_plan(display_task, tasks):
    """カードに出す計画名: 表示タスクの plan → 無ければセッション内で最頻の plan → None。

    最頻が同数の場合は先に観測（作成）された plan を採用（決定論・再生成で揺れない）。
    """
    if display_task is not None:
        p = display_task[3]
        if isinstance(p, str) and p:
            return p
    counts = {}
    order = []
    for t in tasks:
        p = t[3]
        if isinstance(p, str) and p:
            if p not in counts:
                counts[p] = 0
                order.append(p)
            counts[p] += 1
    if not order:
        return None
    return max(order, key=lambda p: counts[p])  # max は同数なら order 先頭側を返す


def _clip(text):
    text = " ".join((text or "").split())
    if len(text) > TITLE_MAX_CHARS:
        return text[:TITLE_MAX_CHARS - 1] + "…"
    return text


def _card(title, note, chip_html, sid=None):
    chips = ('\n      <div class="chips">%s</div>' % chip_html) if chip_html else ""
    sid_attr = (' data-sid="%s"' % html.escape(sid, quote=True)) if sid else ""
    return (
        '  <div class="item flat"%s>\n'
        "    <div>\n"
        '      <p class="task-title">%s</p>\n'
        '      <p class="task-note">%s</p>%s\n'
        "    </div>\n"
        "  </div>"
    ) % (sid_attr, html.escape(title), html.escape(note), chips)


def dedup_sessions(sessions):
    """(プロジェクト, タイトル) が同一のセッション群を最新1枚に畳み込む。

    sessions は新しい順である前提。代表＝最終更新（collect_sessions の "mtime"＝最後の会話イベントの時刻）が最新（＝先頭）。畳み込まれた件数は
    代表の "collapsed" に入る。タスク集計は代表のもののみ（resume/fork の重複は
    ほぼ同一内容のため合算すると水増しになる）。読取不能カードは畳み込まない。
    ラベルなしセッションはフォールバック名がセッションIDで一意のため畳み込まれない。
    """
    seen = {}
    out = []
    for sess in sessions:
        if sess["error"]:
            key = ("err", sess["path"])
        else:
            key = (sess["project"], sess["label"] or sess["session_id"])
        if key in seen:
            seen[key]["collapsed"] += 1
        else:
            rep = dict(sess)
            rep["collapsed"] = 0
            seen[key] = rep
            out.append(rep)
    return out


def _session_card(sess, now):
    stamp = _fmt_mtime(sess["mtime"], now)
    sid = sess["session_id"]
    collapsed = sess.get("collapsed", 0)
    suffix = ("（他%d件を畳み込み）" % collapsed) if collapsed >= 1 else ""

    if sess["error"]:
        return _card(
            "(読取不能: %s)" % os.path.basename(sess["path"]),
            "%s ・ 最終更新 %s%s" % (_clip(sess["error"]), stamp, suffix),
            '<span class="chip pending">未</span>',
            sid,
        )

    label = sess["label"] or ("セッション %s" % sid[:8])
    title = "%s — %s" % (sess["project"], _clip(label))

    tasks = sess["tasks"]
    total = len(tasks)
    done = sum(1 for t in tasks if t[2] == "completed")
    has_active = any(t[2] == "in_progress" for t in tasks)

    if total == 0:
        # v2.0: TaskCreate / TodoWrite が無いセッション → 計画一覧（update_plan）→ 活動の順
        note, chip = _fallback_note_and_chip(sess, now, stamp, suffix)
    else:
        display_task = _pick_display_task(tasks)
        current = _clip(display_task[1])
        plan = _pick_plan(display_task, tasks)
        plan_suffix = ("／計画: %s" % _clip(plan)) if plan else ""
        waiting = waiting_on_user(sess, now)
        wait_part = (" ・ %s" % _wait_text(waiting)) if waiting else ""
        note = "%s ・ 完了%d / 全%d%s ・ 最終更新 %s%s%s" % (
            current, done, total, wait_part, stamp, suffix, plan_suffix)
        if waiting:
            # 利用者への問いが未回答（wrap_up の ask/blocked・結果待ちの AskUserQuestion）。
            # 全件完了でも「済」にしない（v2.0）
            chip = _CHIP_HOLD
        elif done == total:
            chip = '<span class="chip done">済</span>'
        elif has_active:
            chip = '<span class="chip active">進行中</span>'
        elif any(t[2] == "pending" and isinstance(t[1], str)
                 and t[1].startswith("【承認待ち】") for t in tasks):
            # ユーザー承認待ちで止まっているセッション（運用ルール: 件名を【承認待ち】で始める）
            chip = '<span class="chip hold">保留</span>'
        else:
            chip = '<span class="chip pending">未</span>'
    return _card(title, note, chip, sid)


_CHIP_PENDING = '<span class="chip pending">未</span>'
_CHIP_ACTIVE = '<span class="chip active">進行中</span>'
_CHIP_DONE = '<span class="chip done">済</span>'
_CHIP_HOLD = '<span class="chip hold">保留</span>'

SOURCE_PLAN_LABEL = "出所: 計画一覧"
SOURCE_ACTIVITY_LABEL = "出所: 活動"


def turn_state(sess, now):
    """セッションのいまのターンの状態: "working" / "stalled" / "ended" / None（イベント無し）。"""
    kind = sess.get("turn")
    if kind == "busy":
        return "working" if now - sess["mtime"] <= TURN_STALE_SEC else "stalled"
    if kind == "end":
        return "ended"
    return None


def waiting_on_user(sess, now):
    """利用者の回答待ちなら (見出し, 問い文 or None)、そうでなければ None（v2.0）。

    ①結果待ちの AskUserQuestion（ターンの途中だが、止まっているのは利用者の回答）
    ②このターンの wrap_up に ask か blocked があり、いまモデルが動いていない
    """
    if sess.get("turn") == "busy" and ASK_TOOL in (sess.get("pending_tools") or []):
        return ("確認待ち", sess.get("question"))
    if turn_state(sess, now) == "working":
        return None
    wrap = sess.get("wrap")
    if wrap and (wrap.get("ask") or wrap.get("blocked")):
        return ("返答待ち（作業停止中）" if wrap.get("blocked") else "確認待ち", wrap.get("ask"))
    return None


def _wait_text(waiting):
    head, question = waiting
    return "%s: %s" % (head, _clip(question)) if question else head


def _fallback_note_and_chip(sess, now, stamp, suffix):
    """TaskCreate 系の一覧が無いセッションの (note, chip)（v2.0）。

    状態の判定（上から順に最初に当てはまるもの）:
      利用者の回答待ち（waiting_on_user）                → 保留「確認待ち」／「返答待ち（作業停止中）」
      ターンの途中で、最後の動きから TURN_STALE_SEC 以内 → 進行中「作業中」
      ターンの途中のまま、それより長く動きが無い         → 未「応答なし」（結果待ちの道具が
                                                           サブエージェント系なら「15分以上動きなし」）
      このターンの wrap_up がある（問いなし）             → 済「完了報告あり」
      ターンが終わっている                               → 「入力待ち」（チップは計画一覧が全完了なら済、それ以外は未）
    計画一覧（update_plan）があれば現在の項目と「完了N / 全M」を添える。最後の update_plan の
    後に wrap_up があれば、一覧は表示でだけ全完了として数える（_apply_wrap_up）。
    計画タスク名（「／計画: ○○」）は update_plan に欄が無いので出さない。
    """
    plan = sess.get("plan_items")
    if plan and sess.get("plan_wrapped"):
        plan = [[t[0], "completed"] for t in plan]
    wrap = sess.get("wrap")
    state = turn_state(sess, now)
    waiting = waiting_on_user(sess, now)

    if state is None and plan is None:
        return ("タスク未登録 ・ 最終更新 %s%s" % (stamp, suffix), _CHIP_PENDING)

    all_done = bool(plan) and all(t[1] == "completed" for t in plan)
    if waiting:
        chip, status = _CHIP_HOLD, _wait_text(waiting)
    elif state == "working":
        chip, status = _CHIP_ACTIVE, "作業中"
    elif state == "stalled":
        subagent_wait = any(t in WAIT_TOOLS for t in (sess.get("pending_tools") or []))
        chip = _CHIP_PENDING
        status = ("%d分以上動きなし" % (TURN_STALE_SEC // 60)) if subagent_wait else "応答なし"
    elif wrap:
        chip = _CHIP_DONE
        status = ("完了報告あり: %s" % _clip(wrap["recap"])) if wrap.get("recap") else "完了報告あり"
    elif all_done:
        chip, status = _CHIP_DONE, "入力待ち"
    else:
        chip, status = _CHIP_PENDING, "入力待ち"

    parts = []
    if plan:
        tasks = [["p%d" % i, t[0], t[1], None] for i, t in enumerate(plan)]
        parts.append(_clip(_pick_display_task(tasks)[1]))
        parts.append("完了%d / 全%d" % (sum(1 for t in plan if t[1] == "completed"), len(plan)))
    parts.append(status)
    parts.append("最終更新 %s%s" % (stamp, suffix))
    parts.append(SOURCE_PLAN_LABEL if plan else SOURCE_ACTIVITY_LABEL)
    return (" ・ ".join(parts), chip)


def next_refresh_at(sessions, now):
    """「作業中」が「応答なし」へ切り替わる最も近い時刻（無ければ None）。

    transcript が動かなくても時間経過だけで表示が変わるため、常駐ループはこの時刻に
    再生成する（監視ねこの「停止」判定と同じ考え方）。①（TaskCreate 系）のカードも含める——
    wrap_up の問いが残ったまま差し込み行でターンが動いた場合、15 分後に「保留」へ戻るため。
    """
    deadlines = [s["mtime"] + TURN_STALE_SEC for s in sessions
                 if s.get("turn") == "busy"
                 and s["mtime"] + TURN_STALE_SEC > now]
    return min(deadlines) if deadlines else None


# ------------------------------------------------ 「監視ねこ」セクション（外部常駐の生死表示）

# 同じ判定不能エラーを毎回ログに書かないための直近値（None = 直近は正常）
_last_guard_error = None


def _parse_guard_status(path):
    """status.txt を {キー小文字: 値} で返す。読めなければ None。

    形式は "key       : value" の行並び。値側にも ':' が出る（時刻・Windows パス）ため
    最初の ':' だけで分割する。書き出し側が BOM 付き UTF-8 のため utf-8-sig で読む。
    """
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read(GUARD_STATUS_MAX_BYTES)
    except OSError:
        return None
    fields = {}
    for line in raw.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        if key:
            fields[key] = value.strip()
    return fields


def _parse_guard_time(text):
    """status.txt の last を datetime にする。解釈できなければ None。"""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _fmt_guard_stamp(dt, now_dt):
    """同日は HH:MM、日付をまたいだら M/D HH:MM。"""
    if dt.date() == now_dt.date():
        return dt.strftime("%H:%M")
    return "%d/%d %s" % (dt.month, dt.day, dt.strftime("%H:%M"))


def _fmt_guard_elapsed(seconds):
    """経過時間を「N分前」「N時間前」「N日前」に丸める。"""
    seconds = int(seconds)
    if seconds < 0:
        return "時刻が未来"
    minutes = seconds // 60
    if minutes < 60:
        return "%d分前" % minutes
    hours = minutes // 60
    if hours < 24:
        return "%d時間前" % hours
    return "%d日前" % (hours // 24)


def _guard_details(fields):
    """mirror / archives 行を「ミラー5件/main.log 226KB」「退避0件」に整形する。"""
    parts = []
    mirror = fields.get("mirror", "")
    if mirror:
        m = re.match(r"(\d+)\s*file\(s\)\s*,?\s*(.*)$", mirror)
        if m:
            tail = m.group(2).strip()
            parts.append("ミラー%s件%s" % (m.group(1), ("/" + tail) if tail else ""))
        else:
            parts.append("ミラー %s" % mirror)
    archives = fields.get("archives", "")
    if archives:
        m = re.match(r"(\d+)", archives)
        if m:
            parts.append("退避%s件" % m.group(1))
        else:
            parts.append("退避 %s" % archives)
    return parts


GUARD_TARGET_LOG = "ログ退避"   # 監視対象の識別子（note 先頭に置く短い名前）

# セクション見出しの行。監視対象が1つも無くてもこの行だけは必ず出す——board.js が
# 「監視ねこ」見出しを目印に Deck 自身の生死行を差し込むため、消すと生死表示が出なくなる。
GUARD_SECTION_LABEL = '  <div class="section-label">監視ねこ</div>'


def _guard_section(chip_cls, chip_label, note, target=GUARD_TARGET_LOG):
    """「監視ねこ」セクション（ラベル + 監視対象1行）の行リスト。

    セクション名＝監視する主体（監視ねこ）、配下の行＝監視されている対象、という構造。
    行は状態チップを主役にするため task-title を持たず、チップを先頭に置いて
    対象の識別子（「ログ退避」）を note の先頭に短く入れる（対象が増えたときに
    どの行がどの対象かが分かるようにするため）。

    data-sid は付けない（付けると board.js が × 非表示ボタンを生やし、ユーザーが
    生死表示を消せてしまう）。付けないことで board.js の完了表示自動整合の対象になるが、
    済チップ（.chip.done）を出さない限り strike/done-item は必ず外される側に倒れる。
    task-title を持たないことは board.js 側で許容される（taskKey/key は
    「ti ? ti.textContent : ''」、計画チップ照合は「t &&」でガードされ、
    時刻系の自動機能は .time 要素が必須のため本行は対象外）。

    .chips の margin-top: 6px は note の後ろに置く前提の値なので、先頭に置く本行では
    インラインで 0 に上書きする（board.css は共有ファイルのため変更しない）。
    """
    return [
        GUARD_SECTION_LABEL,
        '  <div class="item flat">\n'
        "    <div>\n"
        '      <div class="chips" style="margin-top:0"><span class="chip %s">%s</span></div>\n'
        '      <p class="task-note">%s</p>\n'
        "    </div>\n"
        "  </div>" % (chip_cls, chip_label,
                      html.escape(" ・ ".join([target, note]) if target else note)),
    ]


def _build_guard_lines(now, status_path):
    now_dt = datetime.fromtimestamp(now)
    if not os.path.exists(status_path):
        # 監視対象の常駐ツールを併用していない環境（既定）。見出しだけを残す。
        return [GUARD_SECTION_LABEL]
    fields = _parse_guard_status(status_path)
    if fields is None:
        return _guard_section(
            "pending", "不明",
            "状態ファイルを読めません（%s）" % status_path)

    last_dt = _parse_guard_time(fields.get("last", ""))
    if last_dt is None:
        return _guard_section(
            "pending", "不明",
            "最終確認の時刻を読み取れません（last: %s）" % (fields.get("last", "") or "未記載"))

    age = (now_dt - last_dt).total_seconds()
    stamp = _fmt_guard_stamp(last_dt, now_dt)
    details = _guard_details(fields)
    state = fields.get("state", "")

    if age > GUARD_STALE_SEC:
        # mirror/archives は止まった時点の値＝現況ではないので、そうと分かる形で添える
        head = "最終確認 %s（%s）＝停止しています" % (stamp, _fmt_guard_elapsed(age))
        tail = ["停止時点 " + "・".join(details)] if details else []
        return _guard_section("crit", "停止", " ・ ".join([head] + tail))
    if state == "OK":
        return _guard_section("active", "稼働",
                              " ・ ".join(["最終確認 %s" % stamp] + details))
    head = "最終確認 %s ・ 状態 %s" % (stamp, state or "未記載")
    return _guard_section("crit", "異常", " ・ ".join([head] + details))


def build_guard_html(now=None, status_path=None):
    """「監視ねこ」セクションの行リストを返す。絶対に例外を投げない。

    連携する常駐ツールの状態ファイルが無ければ見出し1行だけを返す（既定）。
    """
    global _last_guard_error
    if now is None:
        now = time.time()
    if status_path is None:
        status_path = LOG_GUARD_STATUS_PATH
    try:
        lines = _build_guard_lines(now, status_path)
    except Exception as e:  # noqa: BLE001 — 生死表示の失敗で Deck 本体を落とさない
        signature = repr(e)
        if signature != _last_guard_error:
            log("警告: 監視対象の状態を判定できません（不明として表示）: %s" % signature)
            _last_guard_error = signature
        return _guard_section("pending", "不明", "状態を判定できません（%s）" % signature)
    _last_guard_error = None
    return lines


def build_html(sessions, now=None):
    """マーカー間に入れる HTML ブロックを生成（board.html の既存 CSS クラスのみ使用）。"""
    if now is None:
        now = time.time()
    stamp = datetime.fromtimestamp(now).strftime("%H:%M")
    lines = build_guard_html(now)
    lines.append('  <div class="section-label">全セッション（自動収集 %s）</div>' % stamp)

    if not sessions:
        lines.append(_card("アクティブなセッションなし",
                           "過去48時間に更新されたセッションはありません", ""))
        return "\n".join(lines)

    sessions = dedup_sessions(sessions)  # 同名（同プロジェクト×同タイトル）は最新1枚に畳む

    # プロジェクトごとにグループ化（グループ順・グループ内とも新しい順）
    order = []
    groups = {}
    for sess in sessions:  # sessions は新しい順
        key = sess["project"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(sess)
    for key in order:
        for sess in groups[key]:
            lines.append(_session_card(sess, now))
    return "\n".join(lines)


# ---------------------------------------------------------------- board.html 書き込み

# inject（マーカー間置換）と移動適用（v1.6）の read-modify-write 全体を直列化するロック。
# 受信サーバはデーモンスレッドで動くため、これが無いと書き込みが競合しうる。
_BOARD_LOCK = threading.Lock()


def _atomic_write_board(board_path, new_text):
    """一時ファイル → os.replace で board.html をアトミックに書き込む。成功なら True。"""
    tmp_fd = None
    tmp_path = None
    try:
        dir_name = os.path.dirname(board_path) or "."
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=".deck-", suffix=".tmp", dir=dir_name)
        with os.fdopen(tmp_fd, "wb") as f:
            tmp_fd = None
            f.write(new_text.encode("utf-8"))
        os.replace(tmp_path, board_path)
        tmp_path = None
        return True
    except OSError as e:
        log("警告: board.html への書き込みに失敗: %s" % e)
        return False
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def inject(board_path, html_block):
    """マーカー間を置換して board.html をアトミックに更新する。

    戻り値: "written" | "unchanged" | "no-board" | "no-marker" | "error"
    マーカー間の置換に加えて、手書きセクションの完了表示（done-item / strike）を
    状態チップに合わせて整合させる（normalize_done_marks）。
    加えて、欠けたマーカーを足し（_restore_markers）、ヘッダの値と引き継いだボードの印を計算し直す（derive_header）。
    それ以外のバイトには触れない。
    """
    global _restore_skip_reason
    with _BOARD_LOCK:
        if not os.path.isfile(board_path):
            return "no-board"
        try:
            mtime = os.path.getmtime(board_path)
            with open(board_path, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log("警告: board.html を読めません: %s" % e)
            return "error"

        # 形が崩れたら崩れる前の版を退避する（v2.4）。退避した間は DECK 領域に目印を書く
        saved = track_structure(board_path, raw, text)
        if saved:
            html_block = html_block + "\n" + lastgood_element(saved)

        base = text
        start = base.find(MARKER_START)
        end = base.find(MARKER_END, start + len(MARKER_START)) if start != -1 else -1
        if start == -1 or end == -1:
            # マーカーが2つとも無ければ、残っている Deck の部分を囲む（v2.5）か、それが無く <footer> が
            # ちょうど1つなら、その直前に足す（v2.2）。片方だけ・順序が逆・多い・Deck の部分の間に別の行がある・footer が無い／
            # 複数の形は直さない（ユーザーの行を囲まない・末尾が1か所に決まらないため）
            restored, how = _restore_markers(base)
            if restored is None:
                _restore_skip_reason = how
                return "no-marker"
            _restore_skip_reason = None
            log("DECK マーカーが無かったため、%s" % how)
            base = restored
            start = base.find(MARKER_START)
            end = base.find(MARKER_END, start + len(MARKER_START))

        before = base[: start + len(MARKER_START)]
        after = base[end:]
        new_text = before + "\n" + html_block + "\n  " + after

        # 手書きセクションの完了表示（done-item / strike）を状態チップに合わせて正本ごと
        # 揃える。board.js の自動整合は DOM だけなので、正本には不整合が残り続けるため。
        # 書き込み経路を増やさずここに相乗りさせる（_BOARD_LOCK の内側・一時ファイル →
        # os.replace という既存の作法をそのまま通す）。マーカー間の置換で差が無くても、
        # 整合で差が出れば書く。どちらにも差が無ければ書かない（mtime を無駄に動かさない）。
        normalized = normalize_done_marks(new_text)
        if normalized is not None:
            new_text = normalized
        # 進捗・<title> の日付・#upd-time を計算し直す（v2.2・Claude が直し忘れても正しい値に戻す）
        new_text = derive_header(new_text, board_path, mtime)

        if new_text == text:
            return "unchanged"
        if not _atomic_write_board(board_path, new_text):
            return "error"
        # 書いた版が形の正しい版なら、それを「崩れる前の版」として持ち直す（v2.4。直前に読んだ版より新しいため）
        st = _lastgood.get(os.path.abspath(board_path))
        if st is not None and not st["broken"] and board_structure_ok(new_text.splitlines(keepends=True)):
            data = new_text.encode("utf-8")
            st["raw"] = data if len(data) <= LASTGOOD_MAX_BYTES else None
        return "written"


# ---------------------------------------------------------------- ボードD&D移動の反映（v1.6）
#
# board.js はドロップ時に POST http://127.0.0.1:<見つけたポート>/board/move?board=<ボードの URL> へ
# （ポートと ?board= は v2.1。「受信の照合」節）
# {"k": "<key>", "sec": "今日の予定|今日中|明日以降", "before": "<key>|null", "head": true}
# を送る（200 なら localStorage 保存をスキップ＝ファイルが正）。
# key の定義は board.js の key() と完全一致させる:
#   (time要素の textContent（無ければ ''）+ '|' + task-title要素の textContent).trim()
# textContent 相当 = 内部タグ除去 + HTML エンティティ復号（空白の正規化はしない）。


_SECTION_LABEL_RE = re.compile(r'<div class="section-label">(.*?)</div>')
_CLASS_TAG_RE = re.compile(r'<(\w+)\b[^>]*?\bclass="([^"]*)"[^>]*>')
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_CHIP_TOKEN_RE = re.compile(r'class="chip[" ]')  # class="chips"（コンテナ）を誤カウントしない
# 済チップは <span class="… chip … done …"> のタグの形だけで判定する（v2.2 で文字列一致から変更）。
# task-note の平文に「class="chip done"」と書かれた未完了の行を、済と見なして数えたり、日付の切り替えで
# 捨てたりしないため
_CHIP_DONE_RE = re.compile(
    r'<span\b[^>]*?\bclass="(?=(?:[^"]*\s)?chip(?:\s|"))(?=(?:[^"]*\s)?done(?:\s|"))[^"]*"')


def _blank_comments(lines):
    """各行の HTML コメント部分を空白で潰した行リストを返す（構造走査専用）。

    board.html の先頭付近にはマークアップ例を書いたコメントブロックがあり、
    その中の <div class="section-label"> / <div class="item ...> を実物として
    拾ってはならない。元の行は変更せず、走査用のコピーだけを潰す。
    """
    out = []
    in_comment = False
    for line in lines:
        buf = []
        i = 0
        while i < len(line):
            if in_comment:
                j = line.find("-->", i)
                if j == -1:
                    buf.append(" " * (len(line) - i))
                    i = len(line)
                else:
                    buf.append(" " * (j + 3 - i))
                    i = j + 3
                    in_comment = False
            else:
                j = line.find("<!--", i)
                if j == -1:
                    buf.append(line[i:])
                    i = len(line)
                else:
                    buf.append(line[i:j])
                    i = j
                    in_comment = True
        out.append("".join(buf))
    return out


def _canon_section(label):
    """section-label テキスト → 移動対象セクション名（先頭一致）。対象外は None。

    「全セッション（自動収集 HH:MM）」のように後続文字が付くラベルがあるため
    完全一致にしない。
    """
    for name in MOVABLE_SECTIONS:
        if label.startswith(name):
            return name
    return None


def _scan_board(lines):
    """board.html の行リスト（keepends）を走査し (sections, items, deck_range) を返す。

    - コメント内の見本マークアップと DECK マーカー間（自動領域）は対象外
    - item ブロックは「<div class="item で始まる行」から div 深度カウントで
      対応する閉じ行まで（正規表現の貪欲マッチ禁止）
    sections: [(行idx, ラベル文字列, 正規化名 or None)]
    items:    [(開始行idx, 終了行idx, 属するセクションの正規化名 or None)]
    deck_range: (開始行idx, 終了行idx) or None（マーカー行自身を含む・不可侵領域）
    """
    blanked = _blank_comments(lines)
    deck_start = deck_end = None
    for i, line in enumerate(lines):
        if deck_start is None and MARKER_START in line:
            deck_start = i
        if deck_end is None and MARKER_END in line:
            deck_end = i
    deck_range = ((deck_start, deck_end)
                  if deck_start is not None and deck_end is not None else None)

    sections = []
    items = []
    cur = None  # 直近 section-label の正規化名（対象3セクション以外の配下は None）
    n = len(lines)
    i = 0
    while i < n:
        if deck_range and deck_range[0] <= i <= deck_range[1]:
            i += 1
            continue
        bl = blanked[i]
        m = _SECTION_LABEL_RE.search(bl)
        if m:
            label = m.group(1).strip()
            cur = _canon_section(label)
            sections.append((i, label, cur))
            i += 1
            continue
        if bl.lstrip().startswith('<div class="item'):
            depth = 0
            j = i
            while j < n:
                if deck_range and deck_range[0] <= j:
                    # 閉じ忘れ </div> 等で item ブロックがマーカー領域へ食い込む
                    # ＝構造異常。安全側で走査を打ち切る（この item は載せない →
                    # 移動は 404 → board.js が localStorage にフォールバックする）
                    j = n
                    break
                depth += blanked[j].count("<div") - blanked[j].count("</div>")
                if depth <= 0:
                    break
                j += 1
            if j >= n:
                break  # 閉じタグ未達＝構造異常。以降の走査は打ち切る（安全側）
            items.append((i, j, cur))
            i = j + 1
            continue
        i += 1
    return sections, items, deck_range


def _element_text(block, cls_token):
    """block 内で class トークンに cls_token を持つ最初の要素の textContent 相当。

    無ければ None。内部タグ（<span class="strike"> 等）は除去し、HTML エンティティは
    復号する（例: D&amp;D → D&D）。空白の正規化はしない（board.js の textContent と同じ）。
    """
    for m in _CLASS_TAG_RE.finditer(block):
        if cls_token in m.group(2).split():
            close = block.find("</%s>" % m.group(1), m.end())
            if close == -1:
                return ""
            return html.unescape(_STRIP_TAGS_RE.sub("", block[m.end():close]))
    return None


def _item_key(block):
    """item ブロックの key（board.js key() と同一定義）。"""
    t = _element_text(block, "time")
    ti = _element_text(block, "task-title")
    return ((t or "") + "|" + (ti or "")).strip()


def _recalc_progress(lines):
    """「今日の予定」+「今日中」のチップ付き item から進捗行を再計算し lines を更新。

    M = class="chip …" を持つ item 数、N = うち chip done を含む数。
    P = round(N/M*100) は JS の Math.round と同じ半上げ（banker's rounding 不可）。
    ※ファイル内のチップは手書きのみ（js-auto / plan チップは JS 注入でファイルに無い）。
    """
    _sections, items, _deck = _scan_board(lines)
    m_count = 0
    n_count = 0
    for (s, e, name) in items:
        if name not in ("今日の予定", "今日中"):
            continue
        blk = "".join(lines[s:e + 1])
        if not _CHIP_TOKEN_RE.search(blk):
            continue
        m_count += 1
        if _CHIP_DONE_RE.search(blk):
            n_count += 1
    pct = int((n_count / m_count) * 100 + 0.5) if m_count else 0
    for i, line in enumerate(lines):
        if 'class="progress-label"' in line:
            lines[i] = re.sub(r"\d+\s*/\s*\d+ 完了",
                              "%d / %d 完了" % (n_count, m_count), line, count=1)
            break
    for i, line in enumerate(lines):
        if "bar-fill" in line:
            lines[i] = re.sub(r"width:\s*\d+(?:\.\d+)?%", "width:%d%%" % pct,
                              line, count=1)
            break


# ------------------------------------------------- 完了表示の正本整合（done-item / strike）
#
# 手書きセクションは「済チップ・淡色化（item の done-item）・打ち消し線（task-title の
# strike）」の3点を揃える構造だった。board.js は表示時にチップ基準で付け外しするが、
# それは DOM だけの整合で HTML 正本には不整合な記述が残り続ける
# （2026-08-04 のボードに「strike と済チップだけ持ち done-item を欠く」行が2件実在した）。
# Deck は board.html をアトミックに書けるので、正本側もチップに合わせて揃える。
#
# 原則: **チップが唯一の真実**。チップの有無・種類・タスクのテキスト・順序・セクション所属は
# 一切変えず、done-item / strike の class トークンだけを足し引きする。
# 対象外: DECK マーカー間（自動収集カード）と、コメント内のマークアップ例
# （どちらも _scan_board が走査対象から外す）。data-sid を持つ item も明示的に飛ばす。

_ITEM_CLASS_RE = re.compile(r'(<div\s+class=")([^"]*)(")')
_ANY_CLASS_TAG_RE = re.compile(r'(<\w+\b[^>]*?\bclass=")([^"]*)(")')


def _toggle_class_token(class_value, token, present):
    """class 属性値の文字列に token を足す／外す。並びは既存トークンの順を保つ。"""
    tokens = class_value.split()
    has = token in tokens
    if present == has:
        return class_value
    if present:
        tokens.append(token)
    else:
        tokens = [t for t in tokens if t != token]
    return " ".join(tokens)


def _normalize_item_block(block, done):
    """1つの item ブロックの done-item / strike をチップ基準に揃えた文字列を返す。"""
    # ① item 開始タグ（ブロック先頭に必ずある。_scan_board が '<div class="item' で
    #    始まる行だけを item 開始と認めているため、最初の1件だけを対象にすれば足りる）
    def fix_item(m):
        return m.group(1) + _toggle_class_token(m.group(2), "done-item", done) + m.group(3)

    block = _ITEM_CLASS_RE.sub(fix_item, block, count=1)

    # ② 配下すべての task-title 要素（board.js は querySelectorAll('.task-title') で
    #    全件に付け外しするので同じ範囲にする）
    def fix_title(m):
        if "task-title" not in m.group(2).split():
            return m.group(0)
        return m.group(1) + _toggle_class_token(m.group(2), "strike", done) + m.group(3)

    return _ANY_CLASS_TAG_RE.sub(fix_title, block)


def normalize_done_marks(text):
    """board.html 全文の done-item / strike を状態チップに合わせて整合させる。

    戻り値: 変更後の全文（変更が無ければ None）。
    行数は変えない（class 属性の中だけを書き換える）ので、item の行範囲はずれない。
    """
    lines = text.splitlines(keepends=True)
    _sections, items, _deck = _scan_board(lines)
    changed = False
    for (s, e, _name) in items:
        if "data-sid" in lines[s]:
            continue  # 自動収集カードは Deck がチップのみを出す設計（見た目を変えない）
        block = "".join(lines[s:e + 1])
        new_block = _normalize_item_block(block, bool(_CHIP_DONE_RE.search(block)))
        if new_block == block:
            continue
        new_lines = new_block.splitlines(keepends=True)
        if len(new_lines) != e - s + 1:
            # 行数が変わる＝想定外の書き換え。安全側でこの item は触らない
            log("警告: 完了表示の整合で行数が変化したためスキップしました（行 %d）" % (s + 1))
            continue
        lines[s:e + 1] = new_lines
        changed = True
    return "".join(lines) if changed else None


def apply_board_move(text, k, sec, before=None, head=False):
    """純関数: board.html 全文 text に 1 件の移動を適用する。

    戻り値: (新テキスト or None, ステータスコード, メッセージ)
      200 = 適用成功 / 400 = 不正な入力 / 404 = key 不一致
    DECK マーカー間には一切触れない（走査対象からも除外）。
    """
    if not isinstance(sec, str) or sec not in MOVABLE_SECTIONS:
        return None, 400, "不正な sec: %r" % (sec,)
    if not isinstance(k, str) or not k.strip():
        return None, 400, "k が空です"

    lines = text.splitlines(keepends=True)
    _sections, items, _deck = _scan_board(lines)

    # 1) k に一致する item を移動対象3セクションから探す
    src = None
    for (s, e, name) in items:
        if name is None:
            continue
        if _item_key("".join(lines[s:e + 1])) == k:
            src = (s, e)
            break
    if src is None:
        return None, 404, "key に一致するタスクがありません"

    # 2) ブロックを切り取る（行番号がずれるため以降は再走査した構造を使う）
    block = lines[src[0]:src[1] + 1]
    if not block[-1].endswith("\n"):
        block[-1] += "\n"  # 文書末の item を移動する場合の保険
    del lines[src[0]:src[1] + 1]
    sections, items, deck_range = _scan_board(lines)

    # 3) 移動先セクションの label 行と境界（次の section-label / DECK:START / 文書末）
    label_idx = None
    for (li, _label, canon) in sections:
        if canon == sec:
            label_idx = li
            break
    if label_idx is None:
        return None, 404, "移動先セクションが見つかりません: %s" % sec
    boundary = len(lines)
    for (li, _label, _canon) in sections:
        if li > label_idx:
            boundary = li
            break
    if deck_range is not None and label_idx < deck_range[0] < boundary:
        boundary = deck_range[0]

    # 4) 挿入位置の決定
    if head:
        insert_at = label_idx + 1  # section-label 行の直後
    else:
        insert_at = None
        if isinstance(before, str) and before.strip():
            for (s, e, _name) in items:
                if label_idx < s < boundary and _item_key("".join(lines[s:e + 1])) == before:
                    insert_at = s
                    break
        if insert_at is None:
            # セクション末尾 = 最後の非空行の直後（セクション間の空行レイアウトを壊さない）
            j = boundary - 1
            while j > label_idx and lines[j].strip() == "":
                j -= 1
            insert_at = j + 1
    lines[insert_at:insert_at] = block

    # 5) 進捗の再計算
    _recalc_progress(lines)
    return "".join(lines), 200, "ok"


def apply_move_to_board(board_path, k, sec, before=None, head=False):
    """board.html を読み、移動を適用してアトミックに書き戻す。(コード, メッセージ) を返す。

    read-modify-write 全体を _BOARD_LOCK で包み、inject と同時に走っても競合しない。
    """
    with _BOARD_LOCK:
        if not os.path.isfile(board_path):
            return 500, "board.html がありません"
        try:
            with open(board_path, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log("警告: board.html を読めません（移動適用）: %s" % e)
            return 500, "board.html を読めません"
        new_text, code, msg = apply_board_move(text, k, sec, before, head)
        if code != 200:
            return code, msg
        if new_text == text:
            return 200, "unchanged"
        # 引き継いだボードの印の指紋（v2.3）: 動かす前の板が「切り替えてから誰も触っていない」状態なら、
        # D&D は Deck 自身の書き込みなので、印を外さないよう指紋を新しい値に書き換える。動かす前に既に
        # 外の書き手が変えていた（指紋が合わない）なら、書き換えずに残す（次の再生成で外れる）
        stored = board_attr(text, "data-tb-rolled-fp")
        if stored is not None and stored == rolled_fp(text):
            new_text = set_board_attrs(new_text, add=(("data-tb-rolled-fp", rolled_fp(new_text)),))
        if not _atomic_write_board(board_path, new_text):
            return 500, "書き込みに失敗しました"
        remember_hand_fingerprint(board_path, new_text)  # Deck 自身の書き込みでは #upd-time を動かさない（v2.2）
        return 200, "ok"


# ---------------------------------------------------------------- 日付の切り替え（v2.2）
#
# ボードの日付（ヘッダの .date）が今日より前になったら、Deck が今日のボードを作る。
# 2026-10-25〜27 に、複数のセッションが today-board スキルを通さずに board.html へ直接行を
# 書き足し続け、create モード（新しい日のボードの発行）が2日間走らなかった。日付の古い板では
# board.js の発行済みボード判定（TB_LIVE）が偽になり、Deck への書き込み4経路が止まる。
# 「スキルの手順を守れば防げる」形では、守られなかったときに黙って止まるので、日付の切り替えを
# Claude の手順から外して Deck が持つ（2026-10-27 ユーザー承認の設計 A）。
#
# 「今日」は PC のローカル時刻の暦日（0:00 で切り替え）。board.js の TB_LIVE 層②がブラウザの
# 暦日で照合しているのに合わせる（深夜をずらす扱いは TB_LIVE と食い違うので採らない）。
# 日付の読み方も TB_LIVE 層②と同じ（4桁の年あり→年月日／年なし→月日）。
#
# 切り替える条件（すべて満たすとき）:
#   ① ヘッダの日付が読めて、今日より前（先の日付・読めない日付は触らない）
#   ② ボードと同じフォルダの config.json の mode が artifact ではない
#   ③ 同じフォルダの state.json に url が無い（artifact からの移行中は触らない）
#   ④ state.json の file_path が無いか、このボードと同じファイル
#   ⑤ DECK マーカーがちょうど1組
#   ⑥ その日の試行が ROLLOVER_MAX_PER_DAY 回未満（失敗の再試行は ROLLOVER_RETRY_SEC 以上空ける）
# 引き継ぎ（元のボードを変形して作る。テンプレートは使わない＝スキルのフォルダに依存しないため）:
#   今日の予定 … 済は捨てる。時刻付きの未完了は今日中の先頭へ移す（.time を外して flat を付け、
#                 data-orig-time に元の時刻を残す。そのままだと昨日の 9:00 が今日の 9:00 に鳴る）
#   今日中・プロジェクト名のセクション … 済は捨て、残りは引き継ぐ（空になったプロジェクト名の見出しは除く）
#   ルーチンタスク … 全部残し、済は未に戻す（毎日の定型作業のため）
#   明日以降 … そのまま
#   引き継いだ項目には data-carried-from="<元の日付>" を付ける（既にあれば最初の値を保つ）。
#   .board には data-tb-rolled="<元の日付>" を付ける（board.js が「引き継いだボード」と知らせる。
#   スキルの create がテンプレートから書き直せば消える）
#   DECK マーカーの間はバイト列そのまま。ヘッダの日付・<title>・#upd-time・進捗は今日の値にする。
# 元のボードは history/board-<元の日付>.html へバイト列のまま退避する（同名があれば -2, -3 …）。
# 自動では消さない（2026-10-27 ユーザー承認）。

CANON_SECTIONS = ("今日の予定", "今日中", "ルーチンタスク", "明日以降")
ROLLOVER_MAX_PER_DAY = 10       # 1日あたりの切り替えの試行の上限（古い日付で書き戻され続けた場合の歯止め）
ROLLOVER_RETRY_SEC = 60         # 失敗・中止のあと、次に試すまでの間隔
HISTORY_DIRNAME = "history"     # 元のボードの退避先（board.html と同じフォルダの下）
WEEKDAY_JA = "月火水木金土日"    # date.weekday() の 0=月 に合わせる
DEFAULT_SKILL_ASSETS = os.path.join(HOME, ".claude", "skills", "today-board", "assets")
ASSET_NAMES = ("board.css", "board.js", "cat.png")
ASSET_SETTLE_SEC = 5            # 写し元の更新時刻がこれより新しいものは、書きかけとみなして今回は写さない（v2.3）
_ASSET_READ_HOOK = None         # 試験用のフック（本番では None）。写し元を読んだ直後に呼ぶ
_asset_skipped = {"n": 0}       # 直近の sync_assets で書きかけとして見送った数（asset_step が再試行の時刻に使う）
ASSET_SYNC_SEC = 300            # スキルの静的ファイルを board.html の隣へそろえる間隔（起動時にも1回・v2.3）。
                                # ページの自動再読み込み（5分）と同じ間隔にする

_HEADER_RE = re.compile(r"<header\b.*?</header>", re.S)
_TITLE_RE = re.compile(r"(<title>)(.*?)(</title>)", re.S)
_TITLE_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}\s*[\(（][^\)）]{1,3}[\)）]")
_UPD_TIME_RE = re.compile(r'(<span id="upd-time"[^>]*>)(.*?)(</span>)', re.S)
_BOARD_TAG_RE = re.compile(r'<div class="board"([^>]*)>')
ROLLED_FP_LEN = 16              # data-tb-rolled-fp に持たせる指紋の長さ（16進の文字数・v2.3）
_ITEM_OPEN_RE = re.compile(r'(<div class=")(item\b[^"]*)(")([^>]*)>')
# class に time トークンを持つ要素の開始タグ（タグの種類は問わない。<div class="time"> に限ると
# <span class="time">9:00</span> の行が時刻を残したまま今日中へ移り、今日のその時刻に鳴る）。
# 要素の終わりは正規表現の最短一致では決めない——<div class="time"><div>9:00</div></div> のように
# 同じタグが入れ子になっていると内側の閉じタグで止まり、閉じタグが1つ余ったまま板が書かれるため。
# 同じタグの開きと閉じを数えて、対応する閉じタグで決める（_remove_time_elements）。
_TIME_OPEN_RE = re.compile(r'<(\w+)\b[^>]*?\bclass="(?:[^"]*\s)?time(?:\s[^"]*)?"[^>]*>')
# class 属性を持つ span（class の前に別の属性があってもよい）。済チップの判定は _CHIP_DONE_RE と同じ
_SPAN_CLASS_RE = re.compile(r'(<span\b[^>]*?\bclass=")([^"]*)("[^>]*>)([^<]*)(</span>)')
_FOOTER_LINE_RE = re.compile(r"^[ \t]*<footer\b")


class RolloverError(Exception):
    """切り替えの本文を作れなかった（構造が想定外）。元のボードは触らない。"""


def board_header_date_text(text):
    """ヘッダの .date の textContent 相当（board.js の document.querySelector('header .date')）。

    コメントの中は見ない。見つからなければ None。
    """
    blanked = "".join(_blank_comments(text.splitlines(keepends=True)))
    m = _HEADER_RE.search(blanked)
    if not m:
        return None
    block = text[m.start():m.end()]
    t = _element_text(block, "date")
    return None if t is None else t.strip()


def parse_board_date(txt, today):
    """ヘッダの日付の文字列を date にする（board.js の TB_LIVE 層②と同じ読み方）。読めなければ None。

    年の無い表記は今年とみなし、半年より先になるなら前年とみなす（12/31 の板を 1/1 に見た場合）。
    """
    if not txt:
        return None
    m4 = re.search(r"(\d{4})[^\d](\d{1,2})[^\d](\d{1,2})", txt)
    try:
        if m4:
            return date(int(m4.group(1)), int(m4.group(2)), int(m4.group(3)))
        m2 = re.search(r"(\d{1,2})[^\d](\d{1,2})", txt)
        if not m2:
            return None
        mo, d = int(m2.group(1)), int(m2.group(2))
        bd = date(today.year, mo, d)
        if (bd - today).days > 183:
            bd = date(today.year - 1, mo, d)
        return bd
    except ValueError:
        return None


def fmt_full_date(d):
    """ヘッダの日付（skill/SKILL.md create モード5 の YYYY-MM-DD（曜）形式）。"""
    return "%04d-%02d-%02d（%s）" % (d.year, d.month, d.day, WEEKDAY_JA[d.weekday()])


def fmt_title_date(d):
    """<title> の日付（skill/SKILL.md の「M/D(曜)」形式）。"""
    return "%d/%d(%s)" % (d.month, d.day, WEEKDAY_JA[d.weekday()])


def _marker_counts(text):
    return text.count(MARKER_START), text.count(MARKER_END)


def _item_start_lines(lines, deck_range):
    """コメントと DECK 領域の外で、<div class="item で始まる行の番号の一覧（入れ子も数える）。"""
    blanked = _blank_comments(lines)
    out = []
    for i, bl in enumerate(blanked):
        if deck_range and deck_range[0] <= i <= deck_range[1]:
            continue
        if bl.lstrip().startswith('<div class="item'):
            out.append(i)
    return out


def board_structure_ok(lines):
    """_scan_board がすべての item を拾えているか（入れ子・閉じタグの欠落が無いか）。

    _scan_board は構造の異常に出会うとそこで走査を打ち切るので、以降の item が黙って
    対象から外れる。切り替えでそれを捨ててしまわないよう、拾えた数と実在の数を突き合わせる。
    """
    _sections, items, deck = _scan_board(lines)
    starts = _item_start_lines(lines, deck)
    return [s for (s, _e, _n) in items] == starts


def _canon_label(label):
    for name in CANON_SECTIONS:
        if label.startswith(name):
            return name
    return None


def _set_item_open_tag(block, carried_from=None, orig_time=None, add_flat=False):
    """item ブロックの開始タグに flat・data-carried-from・data-orig-time を足す。"""
    def fix(m):
        cls = m.group(2)
        if add_flat:
            cls = _toggle_class_token(cls, "flat", True)
        attrs = m.group(4)
        if carried_from and "data-carried-from=" not in attrs:
            attrs += ' data-carried-from="%s"' % carried_from
        if orig_time is not None and "data-orig-time=" not in attrs:
            attrs += ' data-orig-time="%s"' % html.escape(orig_time.strip(), quote=True)
        return m.group(1) + cls + m.group(3) + attrs + ">"

    return _ITEM_OPEN_RE.sub(fix, block, count=1)


def _reset_done_chip(block):
    """済チップを未へ戻す（ルーチンタスク用）。チップ以外は触らない。

    済チップの見分け方は _CHIP_DONE_RE と同じ（span の class に chip と done の両方がある。
    class の前に別の属性があってもよい）。class の done を pending に替え、文字を「未」にする。
    """
    def fix(m):
        tokens = m.group(2).split()
        if "chip" not in tokens or "done" not in tokens:
            return m.group(0)
        tokens = [c for c in tokens if c not in ("done", "pending")] + ["pending"]
        return m.group(1) + " ".join(tokens) + m.group(3) + "未" + m.group(5)

    return _SPAN_CLASS_RE.sub(fix, block)


def _remove_time_elements(block):
    """class に time を持つ要素を、対応する閉じタグまで丸ごと外す。(外した後の文字列, 外した数) を返す。

    要素の終わりは、同じタグ名の開きと閉じを数えて決める（入れ子に強い）。閉じタグが見つからない
    要素は外さずに数えない（その場合、外した数が1にならず切り替えを止める＝構造が崩れた板の扱い）。
    要素の前が空白だけなら、その空白と、要素の後ろの空白・改行1つも一緒に外す（行ごと消す）。
    """
    out = []
    pos = 0
    count = 0
    while True:
        m = _TIME_OPEN_RE.search(block, pos)
        if not m:
            break
        tag = m.group(1)
        tok_re = re.compile(r"<(/?)%s\b[^>]*>" % re.escape(tag), re.I)
        depth = 1
        i = m.end()
        end = None
        for tm in tok_re.finditer(block, i):
            if tm.group(0).endswith("/>"):
                continue
            depth += -1 if tm.group(1) else 1
            if depth == 0:
                end = tm.end()
                break
        if end is None:
            out.append(block[pos:m.end()])
            pos = m.end()
            continue
        start = m.start()
        line_start = block.rfind("\n", 0, start) + 1
        if not block[line_start:start].strip():
            start = line_start
            rest = re.match(r"[ \t]*(?:\r?\n)?", block[end:])
            if rest:
                end += rest.end()
        out.append(block[pos:start])
        pos = end
        count += 1
    out.append(block[pos:])
    return "".join(out), count


def _div_balance(text):
    """コメントの外の <div の数 − </div> の数。"""
    blanked = "".join(_blank_comments(text.splitlines(keepends=True)))
    return len(re.findall(r"<div\b", blanked)) - blanked.count("</div>")


def roll_board_text(text, today, now_hm):
    """日付の古いボードの本文から、今日のボードの本文を作る（純粋関数・I/O なし）。

    戻り値: (新しい本文, 内訳の dict)。作れないときは RolloverError。
    """
    nl = "\r\n" if "\r\n" in text else "\n"
    starts, ends = _marker_counts(text)
    if starts != 1 or ends != 1 or text.find(MARKER_START) > text.find(MARKER_END):
        raise RolloverError("DECK マーカーがちょうど1組ではない（START %d / END %d）" % (starts, ends))
    from_date = parse_board_date(board_header_date_text(text), today)
    if from_date is None:
        raise RolloverError("ヘッダの日付を読めない")
    from_iso = from_date.isoformat()

    lines = text.splitlines(keepends=True)
    if not board_structure_ok(lines):
        raise RolloverError("ボードの構造が崩れている（item の入れ子か閉じタグの欠落）")
    sections, items, deck = _scan_board(lines)
    sec_at = {i: label for (i, label, _c) in sections}
    item_at = {s: e for (s, e, _n) in items}

    info = {"from": from_iso, "carried": 0, "moved": 0, "dropped_done": 0, "routine_reset": 0}
    out = []            # 出力する「塊」の並び: ("line", 文字列) / ("label", 文字列, 正規名) / ("item", 文字列)
    moved = []          # 今日中の先頭へ移す item
    cur = None          # 直近のセクションの正規名（"" はプロジェクト名のセクション、None はセクション前）
    i = 0
    n = len(lines)
    while i < n:
        if deck and deck[0] <= i <= deck[1]:
            out.append(("line", lines[i]))
            i += 1
            continue
        if i in sec_at:
            canon = _canon_label(sec_at[i])
            cur = canon if canon else ""
            out.append(("label", lines[i], cur))
            i += 1
            continue
        if i in item_at:
            e = item_at[i]
            block = "".join(lines[i:e + 1])
            i = e + 1
            done = bool(_CHIP_DONE_RE.search(block))
            if cur is None or cur == "明日以降":
                out.append(("item", block))
                continue
            if cur == "ルーチンタスク":
                if done:
                    block = _reset_done_chip(block)
                    info["routine_reset"] += 1
                out.append(("item", block))
                continue
            if done:
                info["dropped_done"] += 1
                out.append(("dropped", ""))
                continue
            info["carried"] += 1
            t = _element_text(block, "time")
            if cur == "今日の予定" and t is not None:
                block2, n_time = _remove_time_elements(block)
                if n_time != 1:
                    raise RolloverError("時刻の要素を1つに決められない項目がある（%d 個）" % n_time)
                block2 = _set_item_open_tag(block2, carried_from=from_iso, orig_time=t, add_flat=True)
                moved.append(block2)
                info["moved"] += 1
                out.append(("dropped", ""))
                continue
            out.append(("item", _set_item_open_tag(block, carried_from=from_iso)))
            continue
        out.append(("line", lines[i]))
        i += 1

    # 捨てた item の直後の空行は1つだけ詰める（空行が積み重ならないように）
    tidy = []
    skip_blank = False
    for part in out:
        if part[0] == "dropped":
            skip_blank = True
            continue
        if skip_blank and part[0] == "line" and not part[1].strip():
            skip_blank = False
            continue
        skip_blank = False
        tidy.append(part)

    # 空になったプロジェクト名のセクションの見出しを除く（正式名の4つは空でも残す）
    final = []
    for k, part in enumerate(tidy):
        if part[0] == "label" and part[2] == "":
            has_item = False
            for nxt in tidy[k + 1:]:
                if nxt[0] == "label":
                    break
                if nxt[0] == "item":
                    has_item = True
                    break
                if nxt[0] == "line" and MARKER_START in nxt[1]:
                    break
            if not has_item:
                continue
        final.append(part)

    # 移した時刻付きの項目を今日中の先頭へ。今日中が無ければ、ルーチンタスク／明日以降／DECK の前に作る
    if moved:
        pos = None
        for k, part in enumerate(final):
            if part[0] == "label" and part[2] == "今日中":
                pos = k + 1
                break
        if pos is None:
            indent = "  "
            for k, part in enumerate(final):
                if ((part[0] == "label" and part[2] in ("ルーチンタスク", "明日以降"))
                        or (part[0] == "line" and MARKER_START in part[1])):
                    pos = k
                    break
            if pos is None:
                raise RolloverError("今日中セクションを置く位置が決まらない")
            final.insert(pos, ("label", indent + '<div class="section-label">今日中</div>' + nl, "今日中"))
            pos += 1
        final[pos:pos] = [("item", b) for b in moved]

    new_text = "".join(p[1] for p in final)

    # ヘッダの日付・<title>・#upd-time・.board の data-tb-rolled
    hm = _HEADER_RE.search(new_text)
    if not hm:
        raise RolloverError("header が無い")
    header = new_text[hm.start():hm.end()]
    header2 = re.sub(r'(<span class="date"[^>]*>)(.*?)(</span>)',
                     lambda m: m.group(1) + fmt_full_date(today) + m.group(3), header, count=1, flags=re.S)
    new_text = new_text[:hm.start()] + header2 + new_text[hm.end():]
    new_text = _TITLE_RE.sub(
        lambda m: m.group(1) + _TITLE_DATE_RE.sub(fmt_title_date(today), m.group(2), count=1) + m.group(3),
        new_text, count=1)
    new_text = _UPD_TIME_RE.sub(lambda m: m.group(1) + now_hm + m.group(3), new_text, count=1)

    def fix_board(m):
        attrs = re.sub(r'\s*data-tb-rolled(?:-fp)?="[^"]*"', "", m.group(1))
        return '<div class="board"%s data-tb-rolled="%s">' % (attrs, from_iso)

    new_text, nb = _BOARD_TAG_RE.subn(fix_board, new_text, count=1)
    if nb != 1:
        raise RolloverError('<div class="board"> が無い')

    lines2 = new_text.splitlines(keepends=True)
    _recalc_progress(lines2)
    new_text = "".join(lines2)
    normalized = normalize_done_marks(new_text)
    if normalized is not None:
        new_text = normalized
    # 切り替えた時点の手書き部分の指紋を板に持たせる（v2.3）。Deck が止まっている間に書き換えられても、
    # 起動したときに違いが分かるようにするため（.board の属性は指紋に入らないので、足しても値は変わらない）
    new_text = set_board_attrs(new_text, add=(("data-tb-rolled-fp", rolled_fp(new_text)),))

    # 検査: 日付が今日として読める・マーカーが1組・DECK 領域がバイト一致・構造が崩れていない
    if parse_board_date(board_header_date_text(new_text), today) != today:
        raise RolloverError("作ったボードの日付が今日として読めない")
    if _marker_counts(new_text) != (1, 1):
        raise RolloverError("作ったボードの DECK マーカーが1組ではない")
    if _deck_region(new_text) != _deck_region(text):
        raise RolloverError("DECK 領域が元と一致しない")
    if not board_structure_ok(new_text.splitlines(keepends=True)):
        raise RolloverError("作ったボードの構造が崩れている")
    # 内部の検査: 正しく作れていれば、板全体の <div と </div> の差は元と同じになる（外したのも足したのも
    # 開きと閉じがそろった塊だけのため）。外れたら作り方の誤りなので書かない（次の機会にやり直す）
    if _div_balance(new_text) != _div_balance(text):
        raise RolloverError("作ったボードの <div と </div> の差が元と一致しない（%d → %d）"
                            % (_div_balance(text), _div_balance(new_text)))
    return new_text, info


def board_attr(text, name):
    """<div class="board"> の属性 name の値（無ければ None）。"""
    m = _BOARD_TAG_RE.search(text)
    if not m:
        return None
    a = re.search(r'\s%s="([^"]*)"' % re.escape(name), m.group(1))
    return a.group(1) if a else None


def set_board_attrs(text, remove=(), add=()):
    """<div class="board"> から属性 remove を外し、(名前, 値) の並び add を足す（足すものは先に外してから）。"""
    def fix(m):
        attrs = m.group(1)
        for name in list(remove) + [n for (n, _v) in add]:
            attrs = re.sub(r'\s*%s="[^"]*"' % re.escape(name), "", attrs)
        for (name, value) in add:
            attrs += ' %s="%s"' % (name, html.escape(value, quote=True))
        return '<div class="board"%s>' % attrs

    return _BOARD_TAG_RE.sub(fix, text, count=1)


def rolled_fp(text):
    """引き継いだボードの印に持たせる、手書き部分の指紋（短い形）。"""
    return hand_fingerprint(text)[:ROLLED_FP_LEN]


def _deck_region(text):
    s = text.find(MARKER_START)
    e = text.find(MARKER_END, s)
    return text[s:e + len(MARKER_END)] if s != -1 and e != -1 else None


# ---- 目印が2つとも無い板で、Deck が書いた部分を見分ける（v2.5） ----
# 目印のコメントだけが消え、Deck が書いた部分（接続情報の span・見出し・カード）が残った板では、v2.4 までは
# <footer> の前に空の1組を足していた。それだと古い部分が目印の外に残り、古いカードが手書きの側に残り続け、
# board.js が古い接続情報を読みうる。そこで、残っている Deck の部分を囲む。
# 見分ける対象（Deck が書いた部分に数えるもの）は skill/SKILL.md「ボードの点検」の②（「ボードを直して」と頼まれたときの
# 直し方）と同じ。対象を変えるときは両方を変える。見分けられない行の扱いは違う——Deck は Deck の部分の外側（前・後ろ）に
# ある行を見ずに、Deck の部分だけを囲み、間にあるときだけ足さない。Claude（SKILL.md ②）は見分けられない行があればユーザーに聞く。
_DECK_SPAN_LINE_RE = re.compile(r'<span id="deck-(?:key|lastgood)"[^>]*></span>')
_restore_skip_reason = None   # 直近の inject が目印を足さなかった理由（regenerate がログに添える）
_SECTION_LABEL_LINE_RE = re.compile(r'<div class="section-label">(.*?)</div>')
GUARD_SECTION_NAME = "監視ねこ"
SESSIONS_SECTION_PREFIX = "全セッション（自動収集"
NO_SESSION_TITLE = "アクティブなセッションなし"


def _plain_item_block(lines, blanked, i, j):
    """行 i〜j が、閉じの行が開きの行と同じ字下げの「</div>」だけで、中に別の項目・見出し・<footer> を
    含まない1つの項目か。閉じ忘れの項目が後ろの行（板の閉じ・<footer> など）を飲み込んだ形を、
    Deck が書いた部分として囲まないため。"""
    indent = re.match(r"[ \t]*", lines[i]).group(0)
    if lines[j].rstrip("\r\n") != indent + "</div>":
        return False
    for k in range(i + 1, j + 1):
        bl = blanked[k]
        if '<div class="item' in bl or 'class="section-label"' in bl or "<footer" in bl:
            return False
    return True


def _is_guard_row(block):
    """_guard_section が書く監視対象の行の形か（チップの欄が style="margin-top:0" で先頭にあり、
    task-title が無く、task-note が「ログ退避 ・ 」で始まる）。"""
    if _element_text(block, "task-title") is not None:
        return False
    chips = block.find('<div class="chips" style="margin-top:0">')
    note_at = block.find('class="task-note"')
    if chips == -1 or note_at == -1 or chips > note_at:
        return False
    return (_element_text(block, "task-note") or "").startswith(GUARD_TARGET_LOG + " ・ ")


def deck_written_part(text):
    """コメントの外で、Deck が書いた部分（DECK マーカーの間に Deck が書くもの）を探す（v2.5）。

    Deck が書いた部分＝次のものだけ（skill/SKILL.md「ボードの点検」の②と同じ）:
      ・id="deck-key" と id="deck-lastgood" の span
      ・「監視ねこ」と「全セッション（自動収集 …）」の見出し
      ・data-sid の付いたカード・「アクティブなセッションなし」のカード
      ・「監視ねこ」の見出しの直後の1行のうち、_guard_section が書く形のもの（_is_guard_row）
    それぞれ1行（項目は開きから対応する閉じまで）を単位に見る。空行は間に挟まってよい。
    戻り値:
      ("none", None)          … Deck が書いた部分が1つも無い
      ("run", (first, last))  … Deck が書いた部分が、空行だけを挟んでひと続きに並んでいる（行の番号・両端を含む）
      ("mixed", 行の番号)      … Deck が書いた部分の間に、それ以外の行（ユーザーの行・コメント・見分けられない行）がある
    閉じタグが見つからない・対応しない項目は、その開きの行を見分けられない行として扱う（_plain_item_block）。
    """
    lines = text.splitlines(keepends=True)
    blanked = _blank_comments(lines)
    units = []   # (開始行, 終了行, 種類)。種類は "blank" / "other" / "deck" / "guard-label"
    prev_kind = None   # 直前の空行でない単位の種類
    n = len(lines)
    i = 0
    while i < n:
        s = blanked[i].strip()
        if not s:
            kind = "blank" if not lines[i].strip() else "other"   # コメントだけの行は other
            units.append((i, i, kind))
            if kind != "blank":
                prev_kind = kind
            i += 1
            continue
        if _DECK_SPAN_LINE_RE.fullmatch(s):
            kind, j = "deck", i
        elif _SECTION_LABEL_LINE_RE.fullmatch(s):
            label = _SECTION_LABEL_LINE_RE.fullmatch(s).group(1).strip()
            if label == GUARD_SECTION_NAME:
                kind = "guard-label"
            elif label.startswith(SESSIONS_SECTION_PREFIX):
                kind = "deck"
            else:
                kind = "other"
            j = i
        elif s.startswith('<div class="item'):
            depth = 0
            j = i
            while j < n:
                depth += blanked[j].count("<div") - blanked[j].count("</div>")
                if depth <= 0:
                    break
                j += 1
            if j >= n or not _plain_item_block(lines, blanked, i, j):
                # 閉じタグが見つからない・閉じが対応しない・中に別の項目や見出しがある＝どこまでが1つの
                # 項目か決まらない。この行は見分けられない行として扱い、次の行から見直す（囲む側に倒さない）
                units.append((i, i, "other"))
                prev_kind = "other"
                i += 1
                continue
            block = "".join(lines[i:j + 1])
            if "data-sid=" in blanked[i]:
                kind = "deck"
            elif (_element_text(block, "task-title") or "") == NO_SESSION_TITLE:
                kind = "deck"
            elif prev_kind == "guard-label" and _is_guard_row(block):
                kind = "deck"
            else:
                kind = "other"
        else:
            kind, j = "other", i
        units.append((i, j, kind))
        prev_kind = kind
        i = j + 1
    deck = [u for u in units if u[2] in ("deck", "guard-label")]
    if not deck:
        return ("none", None)
    first, last = deck[0][0], deck[-1][1]
    for (a, _b, kind) in units:
        if first <= a <= last and kind == "other":
            return ("mixed", a)
    return ("run", (first, last))


def _restore_markers(text):
    """DECK マーカーが2つとも無い板に、マーカーを足す。戻り値: (足した本文, 説明) か (None, 足さない理由)。

    ①Deck が書いた部分が残っていて、空行だけを挟んでひと続きなら、その前後に足して囲む（v2.5）
    ②Deck が書いた部分の間に別の行・見分けられない行があるときは足さない（v2.5。ユーザーの行を囲まない）
    ③Deck が書いた部分が無く、<footer> の行がちょうど1つなら、その直前に足す（v2.2）
    マーカーが片方だけある・順序が逆・多重の板と、③で footer が無い・複数の板は直さない（2026-10-27 ユーザー承認）。
    """
    starts, ends = _marker_counts(text)
    if (starts, ends) != (0, 0):
        # 足さない理由を形ごとに言い分ける（警告ログに出る）。inject から来るのは前の2つだけで、
        # 3つ目（最初の START の後ろに END がある）は関数を単独で呼んだときのためのもの
        if starts == 0 or ends == 0:
            return None, "目印が片方だけある（START %d / END %d）" % (starts, ends)
        first = text.find(MARKER_START)
        if text.find(MARKER_END, first + len(MARKER_START)) == -1:
            return None, "目印の順序が逆で、END が START より前にある（START %d / END %d）" % (starts, ends)
        return None, "目印はすでにある（START %d / END %d）" % (starts, ends)
    lines = text.splitlines(keepends=True)
    nl = "\r\n" if "\r\n" in text else "\n"
    found, where = deck_written_part(text)
    if found == "run":
        first, last = where
        indent = ""
        for k in range(first, last + 1):
            if lines[k].strip() and not _DECK_SPAN_LINE_RE.fullmatch(lines[k].strip()):
                indent = re.match(r"[ \t]*", lines[k]).group(0)
                break
        if not lines[last].endswith(("\n", "\r")):
            lines[last] += nl
        lines[last + 1:last + 1] = [indent + MARKER_END + nl]
        lines[first:first] = [indent + MARKER_START + nl]
        return "".join(lines), "残っていた Deck の部分（%d〜%d 行目）を囲みました" % (first + 1, last + 1)
    if found == "mixed":
        return None, "Deck が書いた部分の間に別の行がある（%d 行目）" % (where + 1)
    blanked = _blank_comments(lines)
    hits = [i for i, bl in enumerate(blanked) if _FOOTER_LINE_RE.match(bl)]
    if len(hits) != 1 or sum(bl.count("<footer") for bl in blanked) != 1:
        return None, "<footer> がちょうど1つではない"
    i = hits[0]
    indent = re.match(r"[ \t]*", lines[i]).group(0)
    lines[i:i] = [indent + MARKER_START + nl, indent + MARKER_END + nl, nl]
    return "".join(lines), "<footer> の直前に足しました"


# ---- 手書き部分の指紋と、Deck が計算し直す値（v2.2） ----
# #upd-time（タスク更新）は「ボードの中身がいつ書かれたか」を示すが、書き手が直し忘れると嘘になる
# （2026-10-27 に 23:49 のまま2日残った）。Deck は手書き部分の指紋を覚えておき、Deck 以外の書き手の
# せいで指紋が変わったら、#upd-time をそのファイルの更新時刻にする（2026-10-27 ユーザー承認）。
# 指紋に入れるのは、ヘッダの日付・DECK 領域の外のセクション見出しと item の中身。Deck 自身が直す値
# （#upd-time・進捗・<title>・done-item / strike）は入れない（入れると自分の書き込みで指紋が動く）。
# Deck 自身の書き込み（D&D の反映・日付の切り替え）の後は、指紋だけを更新して時刻は動かさない。
_hand_fp = {}   # {board_path: 指紋}


def hand_fingerprint(text):
    lines = text.splitlines(keepends=True)
    sections, items, _deck = _scan_board(lines)
    h = hashlib.sha256()
    h.update((board_header_date_text(text) or "").encode("utf-8"))
    for (i, label, _c) in sections:
        h.update(b"\x00L" + label.encode("utf-8"))
    for (s, e, _n) in items:
        block = _normalize_item_block("".join(lines[s:e + 1]), False)
        h.update(b"\x00I" + block.replace("\r\n", "\n").encode("utf-8"))
    return h.hexdigest()


def remember_hand_fingerprint(board_path, text):
    _hand_fp[os.path.abspath(board_path)] = hand_fingerprint(text)


def derive_header(text, board_path, mtime):
    """Deck が計算し直す値をそろえた本文を返す（変えるものが無ければ同じ文字列）。

    ①進捗（N / M とバー幅）②<title> の日付（ヘッダの日付から）③#upd-time（手書き部分が
    Deck 以外の書き手で変わったとき、そのファイルの更新時刻）④data-tb-rolled（同じく手書き部分が
    Deck 以外の書き手で変わったら外す・v2.3）。
    起動直後（指紋をまだ覚えていない）と、Deck 自身の書き込み（D&D の反映・日付の切り替えは書いた直後に
    指紋を覚え直す。完了表示の整合と、ここで直す値は指紋に入らない）では、③④は動かない。
    """
    key = os.path.abspath(board_path)
    fp = hand_fingerprint(text)
    prev = _hand_fp.get(key)
    _hand_fp[key] = fp
    if prev is not None and fp != prev and mtime:
        hm = datetime.fromtimestamp(mtime).strftime("%H:%M")
        text = _UPD_TIME_RE.sub(lambda m: m.group(1) + hm + m.group(3), text, count=1)
    # 引き継いだボードの案内は、誰かが手書き部分を直した時点で役目を終える（朝の計画が create を
    # 通らなくても消えるようにする）。判定は板に持たせた指紋（data-tb-rolled-fp）と今の指紋の比較で行う
    # ——メモリの指紋と違い、Deck が止まっている間の書き換えも起動直後の1周目で分かる。指紋を持たない板
    # （v2.2 で切り替えた板）だけは、メモリの指紋の変化で判定する。行ごとの data-carried-from /
    # data-orig-time は残す
    has_rolled = board_attr(text, "data-tb-rolled") is not None
    stored = board_attr(text, "data-tb-rolled-fp")
    if has_rolled:
        if stored is not None:
            strip = fp[:ROLLED_FP_LEN] != stored
        else:
            strip = prev is not None and fp != prev
    else:
        strip = stored is not None   # 印が無いのに指紋だけ残っている（書き写し等）なら片付ける
    if strip:
        text = set_board_attrs(text, remove=("data-tb-rolled", "data-tb-rolled-fp"))
    today = date.today()
    bd = parse_board_date(board_header_date_text(text), today)
    if bd is not None:
        text = _TITLE_RE.sub(
            lambda m: m.group(1) + _TITLE_DATE_RE.sub(fmt_title_date(bd), m.group(2), count=1) + m.group(3),
            text, count=1)
    lines = text.splitlines(keepends=True)
    _recalc_progress(lines)
    return "".join(lines)


# ---- 切り替えの実行（I/O） ----
_rollover = {"day": None, "count": 0, "next_at": 0.0, "logged": set()}
_ROLLOVER_BEFORE_COMMIT = None   # 試験用のフック（本番では None）。重なった書き込みを再現するのに使う


def _log_once_per_day(today, reason, msg):
    key = (today.isoformat(), reason)
    if key in _rollover["logged"]:
        return
    _rollover["logged"].add(key)
    log(msg)


def _read_json_file(path):
    """JSON を読む。(dict または None, 生バイト列 または None)。BOM 付きも読む。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None, None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None, raw
    return (data if isinstance(data, dict) else None), raw


def _atomic_write_bytes(path, data):
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".deck-", suffix=".tmp", dir=os.path.dirname(path) or ".")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
        tmp_path = None
        return True
    except OSError as e:
        log("警告: 書き込みに失敗: %s (%s)" % (path, e))
        return False
    finally:
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def rollover_blocker(board_path):
    """切り替えを止める設定上の理由（無ければ None）。条件②③④。"""
    board_dir = os.path.dirname(os.path.abspath(board_path))
    config, _ = _read_json_file(os.path.join(board_dir, "config.json"))
    if config and config.get("mode") == "artifact":
        return "artifact", "config.json の mode が artifact"
    state, _ = _read_json_file(os.path.join(board_dir, "state.json"))
    if state:
        if state.get("url"):
            return "artifact-url", "state.json に url がある（artifact モードの運用中）"
        fp = state.get("file_path")
        if fp and not same_board(fp, os.path.abspath(board_path)):
            return "other-board", "state.json の file_path がこのボードではない"
    return None


def update_state_date(board_path, today):
    """state.json の date を今日にする（ほかのキー・BOM・改行の形は保つ）。書いたら True。

    local モードで url が無く、file_path が無いかこのボードと同じときだけ書く。
    """
    path = os.path.join(os.path.dirname(os.path.abspath(board_path)), "state.json")
    state, raw = _read_json_file(path)
    if state is None or raw is None:
        return False
    if state.get("url") or state.get("mode", "local") != "local":
        return False
    fp = state.get("file_path")
    if fp and not same_board(fp, os.path.abspath(board_path)):
        return False
    iso = today.isoformat()
    if state.get("date") == iso:
        return False
    state["date"] = iso
    body = json.dumps(state, ensure_ascii=False, indent=2)
    if raw.rstrip(b"\r\n") != raw:
        body += "\n"
    if b"\r\n" in raw:
        body = body.replace("\n", "\r\n")
    data = body.encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        data = b"\xef\xbb\xbf" + data
    return _atomic_write_bytes(path, data)


def sync_assets(board_path, assets_dir):
    """スキルの静的ファイル（board.css / board.js / cat.png）を board.html の隣へ写す。

    skill/SKILL.md create モード6 の cp と同じ向き（本番スキル → board.html の隣）で、本番スキルを正とする
    （配る順は「リポジトリ → 本番スキル → 実行系」。中間の本番スキルを飛ばすと create の cp で
    巻き戻るため、本番スキルは常に最新である前提に立っている。mtime では比べない——実行系だけを先に
    新しくする正規の手順は無く、実行系は生成物＝利用者が編集する場所ではないため）。
    呼ぶのは、常駐の起動時と ASSET_SYNC_SEC ごと（v2.3）、および日付の切り替えで新しいボードを作ったとき。
    中身が同じなら書かない。写した数を返す。
    """
    _asset_skipped["n"] = 0
    if not assets_dir or not os.path.isdir(assets_dir):
        return 0
    board_dir = os.path.dirname(os.path.abspath(board_path))
    if not os.path.isdir(board_dir):
        return 0
    if os.path.normcase(os.path.realpath(board_dir)) == os.path.normcase(os.path.realpath(assets_dir)):
        return 0
    copied = 0
    for name in ASSET_NAMES:
        src = os.path.join(assets_dir, name)
        dst = os.path.join(board_dir, name)
        # 写し元が書きかけ（配っている最中など）のときは、半端なファイルを写さない（v2.3）:
        # 更新したばかり（ASSET_SETTLE_SEC 以内）なら見送り、読む前と後で大きさか更新時刻が変われば見送る。
        # 見送ったものは次の機会（ASSET_SYNC_SEC 後）に写す
        try:
            st_a = os.stat(src)
            age = time.time() - st_a.st_mtime
            if 0 <= age < ASSET_SETTLE_SEC:   # 更新時刻が未来（時計のずれ等）なら見送らない
                _asset_skipped["n"] += 1
                continue
            with open(src, "rb") as f:
                data = f.read()
            if _ASSET_READ_HOOK is not None:
                _ASSET_READ_HOOK(src)
            st_b = os.stat(src)
        except OSError:
            continue
        if (st_a.st_size, st_a.st_mtime_ns) != (st_b.st_size, st_b.st_mtime_ns) or len(data) != st_b.st_size:
            _asset_skipped["n"] += 1
            continue
        try:
            with open(dst, "rb") as f:
                if f.read() == data:
                    continue
        except OSError:
            pass
        if _atomic_write_bytes(dst, data):
            copied += 1
    return copied


LASTGOOD_MAX_BYTES = 2 * 1024 * 1024   # 形が正しい版としてメモリに持つ大きさの上限（超える版は持たない・v2.4）
_lastgood = {}   # {board の絶対パス: {"raw": 形が正しい最後の版のバイト列 or None, "broken": 崩れている間 True,
                 #  "saved": 今の崩れで退避したファイル（board.html のフォルダからの相対パス）or None}}


def _lastgood_path(board_path, date_iso, hhmmss):
    hdir = os.path.join(os.path.dirname(os.path.abspath(board_path)), HISTORY_DIRNAME)
    base = os.path.join(hdir, "board-%s-lastgood-%s" % (date_iso, hhmmss))
    path = base + ".html"
    k = 2
    while os.path.exists(path):
        path = "%s-%d.html" % (base, k)
        k += 1
    return hdir, path


def track_structure(board_path, raw, text, now=None):
    """読んだ板の形を確かめ、正しい形から崩れたら、持っていた正しい版を history/ へ退避する（v2.4）。

    戻り値: 今の崩れで退避したファイルの相対パス（崩れていない・退避していなければ None）。
    形が正しい版はバイト列のまま1つだけ持つ（LASTGOOD_MAX_BYTES を超える版は持たない）。崩れが続く間は
    退避し直さない。起動直後から崩れていて正しい版を持っていないときは、退避せずにログだけ1回残す。
    """
    key = os.path.abspath(board_path)
    st = _lastgood.setdefault(key, {"raw": None, "broken": False, "saved": None})
    if board_structure_ok(text.splitlines(keepends=True)):
        st["broken"] = False
        st["saved"] = None
        st["raw"] = raw if len(raw) <= LASTGOOD_MAX_BYTES else None
        return None
    if st["broken"]:
        return st["saved"]
    st["broken"] = True
    if st["raw"] is None:
        log("ボードの形が崩れています（項目の入れ子・閉じタグの欠落）。崩れる前の版を持っていないため退避しません")
        return None
    now_dt = datetime.fromtimestamp(time.time() if now is None else now)
    try:
        good_text = st["raw"].decode("utf-8")
    except UnicodeDecodeError:
        good_text = ""
    bd = parse_board_date(board_header_date_text(good_text), now_dt.date())
    hdir, hpath = _lastgood_path(board_path, (bd or now_dt.date()).isoformat(), now_dt.strftime("%H%M%S"))
    try:
        os.makedirs(hdir, exist_ok=True)
    except OSError as e:
        log("ボードの形が崩れています。崩れる前の版を退避できません（%s）" % e)
        return None
    if not _atomic_write_bytes(hpath, st["raw"]):
        log("ボードの形が崩れています。崩れる前の版を退避できません")
        return None
    rel = os.path.relpath(hpath, os.path.dirname(os.path.abspath(board_path))).replace(os.sep, "/")
    st["saved"] = rel
    log("ボードの形が崩れています（項目の入れ子・閉じタグの欠落）。崩れる前の版を %s へ退避しました（Deck は板を直しません）" % rel)
    return rel


def lastgood_element(rel):
    """DECK 領域に書く、退避したファイルの目印（board.js が「ボードの点検」の知らせに添える）。"""
    return '<span id="deck-lastgood" hidden data-file="%s"></span>' % html.escape(rel, quote=True)


def _history_path(board_path, from_iso):
    hdir = os.path.join(os.path.dirname(os.path.abspath(board_path)), HISTORY_DIRNAME)
    base = os.path.join(hdir, "board-%s" % from_iso)
    path = base + ".html"
    k = 2
    while os.path.exists(path):
        path = "%s-%d.html" % (base, k)
        k += 1
    return hdir, path


def note_rollover_exception(count_before, now=None, today=None):
    """try_rollover が例外を出したときに呼ぶ。試行を1回と数え、次の試行を ROLLOVER_RETRY_SEC 後にする。

    count_before は呼ぶ前のその日の試行回数（記録が別の日なら 0）。数が count_before のままのときだけ
    数える＝try_rollover が既に数えていれば二重には数えない（日付が変わった最初の試行でも同じ）。
    例外が試行回数・間隔の設定より前で出ても、5秒ごとに試し直し続けないようにする。
    """
    now = time.time() if now is None else now
    today = today or date.today()
    if _rollover["day"] != today:
        _rollover.update({"day": today, "count": 0, "next_at": 0.0})
    if _rollover["count"] == count_before:
        _rollover["count"] += 1
    _rollover["next_at"] = max(_rollover["next_at"], now + ROLLOVER_RETRY_SEC)


def asset_step(board_path, assets_dir, loop_state, now=None):
    """常駐の1周ぶんの静的ファイルの同期（v2.3）。loop_state は {"next": 次にそろえる時刻}。

    起動直後の1周目と、そこから ASSET_SYNC_SEC ごとに sync_assets を呼ぶ。写した数を返す（呼ばなければ None）。
    例外はここで受け止め、ログに残す（再生成・通知音を止めない）。
    """
    now = time.time() if now is None else now
    if now < loop_state.get("next", 0.0):
        return None
    loop_state["next"] = now + ASSET_SYNC_SEC
    try:
        n = sync_assets(board_path, assets_dir)
    except Exception as e:  # noqa: BLE001
        log("エラー（静的ファイルの同期・継続）: %r" % e)
        return 0
    if _asset_skipped["n"]:
        # 書きかけとして見送ったものがあれば、5分待たずに、落ち着いた頃にもう一度試す
        loop_state["next"] = now + ASSET_SETTLE_SEC + 1
    if n:
        log("静的ファイルをスキルにそろえました（%d 件）" % n)
    return n


def rollover_step(board_path, assets_dir, loop_state, now=None, today=None):
    """常駐の1周ぶんの日付の切り替え。loop_state は {"seen": …, "last": …}（watch_loop が持つ）。

    ボードが変わったとき・日付が変わったとき・前回が待ち／中止／失敗／例外だったときだけ確かめる。
    前回が例外で、その日の試行が上限に達しているか、次の試行の時刻より前なら、確かめない。
    例外はここで受け止め、ログに残して "exception" とする（再生成・通知音を止めない）。
    """
    now = time.time() if now is None else now
    today = today or date.today()
    cur_seen = (_board_mtime(board_path), today)
    if loop_state.get("last") == "exception" and _rollover["day"] == today and (
            now < _rollover["next_at"] or _rollover["count"] >= ROLLOVER_MAX_PER_DAY):
        return None
    if cur_seen == loop_state.get("seen") and loop_state.get("last") not in ("wait", "conflict", "error", "exception"):
        return None
    count_before = _rollover["count"] if _rollover["day"] == today else 0
    try:
        result = try_rollover(board_path, today=today, now=now, assets_dir=assets_dir)
    except Exception as e:  # noqa: BLE001 — 切り替えの失敗で再生成・通知音を止めない
        log("エラー（日付の切り替え・継続）: %r" % e)
        note_rollover_exception(count_before, now, today)
        result = "exception"
    loop_state["last"] = result
    loop_state["seen"] = (_board_mtime(board_path), today)
    return result


def try_rollover(board_path, today=None, now=None, assets_dir=DEFAULT_SKILL_ASSETS):
    """日付の古いボードを今日のボードへ切り替える。結果の文字列を返す。

    rolled … 切り替えた／not-needed … 今日（または読めない・先の日付）のボード／
    no-board … ボードが無い／blocked … 設定上の理由で対象外／wait … 再試行の間隔待ち／
    limit … その日の上限に達した／conflict … 途中で別の書き手が書いた（次の機会にやり直す）／
    error … 作れなかった・書けなかった（元のボードは無傷）
    """
    today = today or date.today()
    now = time.time() if now is None else now
    if _rollover["day"] != today:
        _rollover.update({"day": today, "count": 0, "next_at": 0.0})
    try:
        st0 = os.stat(board_path)
        with open(board_path, "rb") as f:
            raw0 = f.read()
        text = raw0.decode("utf-8")
    except FileNotFoundError:
        return "no-board"
    except (OSError, UnicodeDecodeError) as e:
        _log_once_per_day(today, "read", "警告: 日付の切り替え: board.html を読めません: %s" % e)
        return "error"
    bd = parse_board_date(board_header_date_text(text), today)
    if bd is None:
        _log_once_per_day(today, "unreadable", "日付の切り替え: ヘッダの日付を読めないため切り替えません")
        return "not-needed"
    if bd >= today:
        if bd > today:
            _log_once_per_day(today, "future", "日付の切り替え: ボードの日付（%s）が今日より先のため切り替えません" % bd)
        elif not rollover_blocker(board_path) and update_state_date(board_path, today):
            # 今日のボードなのに state.json の date が古い（スキルを通さずに今日のボードが作られた等）
            log("state.json の date を今日（%s）にそろえました" % today.isoformat())
        return "not-needed"
    blocker = rollover_blocker(board_path)
    if blocker:
        _log_once_per_day(today, "blocked-" + blocker[0], "日付の切り替え: 対象外（%s）" % blocker[1])
        return "blocked"
    if _rollover["count"] >= ROLLOVER_MAX_PER_DAY:
        _log_once_per_day(today, "limit", "日付の切り替え: 今日の上限（%d 回）に達したため、これ以上試しません"
                          % ROLLOVER_MAX_PER_DAY)
        return "limit"
    if now < _rollover["next_at"]:
        return "wait"
    _rollover["count"] += 1
    _rollover["next_at"] = now + ROLLOVER_RETRY_SEC
    now_hm = datetime.fromtimestamp(now).strftime("%H:%M")
    try:
        new_text, info = roll_board_text(text, today, now_hm)
    except RolloverError as e:
        log("日付の切り替え: 作れませんでした（%s）。元のボードはそのままです" % e)
        return "error"
    if _ROLLOVER_BEFORE_COMMIT is not None:
        _ROLLOVER_BEFORE_COMMIT(board_path)
    with _BOARD_LOCK:
        try:
            with open(board_path, "rb") as f:
                raw1 = f.read()
            st1 = os.stat(board_path)
        except OSError as e:
            log("日付の切り替え: board.html を読み直せません（%s）。次の機会にやり直します" % e)
            return "error"
        if raw1 != raw0 or st1.st_mtime_ns != st0.st_mtime_ns:
            log("日付の切り替え: 作っている間に board.html が書き換えられたため中止しました。次の機会にやり直します")
            return "conflict"
        hdir, hpath = _history_path(board_path, info["from"])
        try:
            os.makedirs(hdir, exist_ok=True)
        except OSError as e:
            log("日付の切り替え: 退避先を作れません（%s）。元のボードはそのままです" % e)
            return "error"
        if not _atomic_write_bytes(hpath, raw0):
            log("日付の切り替え: 元のボードを退避できません。元のボードはそのままです")
            return "error"
        try:
            with open(hpath, "rb") as f:
                if f.read() != raw0:
                    log("日付の切り替え: 退避したファイルが元と一致しません。元のボードはそのままです")
                    return "error"
            st2 = os.stat(board_path)
        except OSError as e:
            log("日付の切り替え: 退避の確認に失敗（%s）。元のボードはそのままです" % e)
            return "error"
        if st2.st_mtime_ns != st1.st_mtime_ns or st2.st_size != st1.st_size:
            log("日付の切り替え: 退避の間に board.html が書き換えられたため中止しました。次の機会にやり直します")
            return "conflict"
        if not _atomic_write_board(board_path, new_text):
            return "error"
        remember_hand_fingerprint(board_path, new_text)
    state_written = update_state_date(board_path, today)
    copied = sync_assets(board_path, assets_dir)
    log("日付の切り替え: %s → %s（引き継ぎ %d 件〔うち時刻付きを今日中へ %d 件〕・済を除外 %d 件・"
        "ルーチンを未に %d 件・退避 %s・state.json %s・静的ファイル %d 件）"
        % (info["from"], today.isoformat(), info["carried"], info["moved"], info["dropped_done"],
           info["routine_reset"], os.path.relpath(hpath, os.path.dirname(os.path.abspath(board_path))),
           "更新" if state_written else "そのまま", copied))
    return "rolled"


# ---------------------------------------------------------------- 通知音（v1.7）
#
# 時刻トリガーの通知音を、ブラウザ（board.js の WebAudio）から Deck 側へ移した。
# 理由: ブラウザの自動再生制限により、ページ上でユーザー操作が一度も無いと
# AudioContext が running にならず無音のまま return する。
# board.html は 5 分ごとに全リロードされるため、クリックで得た解除も最大 5 分で失効する。
# この道具の想定用途は「サブモニタに置いて触らない」ため、ページ内再生では構造的に鳴らない。
# 設定 UI は board.js の⚙パネルのまま維持し、値と試聴要求だけを POST /sound/config で受ける。


_WAVE_CACHE = {}          # {音種: WAV バイト列}（合成結果の使い回し）
_WAVE_CACHE_LOCK = threading.Lock()
_SOUND_BUSY = threading.Lock()   # 再生スレッドの積み上がり防止（掴めなければ今回は鳴らさない）


def _synth_wave_bytes(notes):
    """(周波数, 開始秒, 終了秒) の並びから 16bit モノラル WAV のバイト列を作る。

    v1.7 より前の board.js の WebAudio 版（正弦波 + GainNode 0.08）と同じ鳴り分けになるよう、
    同一の周波数・時刻表で合成する。端に短いフェードを入れて発音時のプチノイズを消す。
    """
    total = min(max(n[2] for n in notes), SOUND_MAX_SEC)
    n_samples = max(1, int(total * SOUND_RATE))
    buf = [0.0] * n_samples
    for (freq, start, end) in notes:
        s0 = max(0, int(start * SOUND_RATE))
        s1 = min(n_samples, int(min(end, SOUND_MAX_SEC) * SOUND_RATE))
        length = s1 - s0
        if length <= 0:
            continue
        fade = max(1, int(SOUND_FADE_SEC * SOUND_RATE))
        step = 2.0 * math.pi * freq / SOUND_RATE
        for i in range(length):
            env = 1.0
            if i < fade:
                env = i / float(fade)
            remain = length - i
            if remain < fade:
                env = min(env, remain / float(fade))
            buf[s0 + i] += math.sin(step * (s0 + i)) * env
    samples = array.array("h")
    for v in buf:
        v *= SOUND_GAIN
        if v > 1.0:
            v = 1.0
        elif v < -1.0:
            v = -1.0
        samples.append(int(v * 32767))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SOUND_RATE)
        w.writeframes(samples.tobytes())
    return out.getvalue()


def _wave_for(sound_type):
    """音種に対応する WAV バイト列（合成は初回のみ）。未知の音種は既定音にフォールバック。"""
    notes = SOUND_DEFS.get(sound_type)
    if notes is None:
        sound_type = DEFAULT_SOUND_TYPE
        notes = SOUND_DEFS[DEFAULT_SOUND_TYPE]
    with _WAVE_CACHE_LOCK:
        data = _WAVE_CACHE.get(sound_type)
        if data is None:
            data = _synth_wave_bytes(notes)
            _WAVE_CACHE[sound_type] = data
        return data


def _play_sound_blocking(sound_type):
    """1 回分を同期再生する。鳴らせたら True。例外は出さない（呼び出し元スレッド専用）。"""
    if winsound is None:
        log("通知音: winsound が使えない環境のため鳴らしません")
        return False
    try:
        data = _wave_for(sound_type)
    except (ValueError, OverflowError, MemoryError) as e:  # noqa: BLE001
        log("警告: 通知音の合成に失敗（%s）: %r" % (sound_type, e))
        data = None
    if data:
        try:
            # SND_MEMORY は既定で同期再生。data はこの呼び出し中ずっと参照が生きている。
            winsound.PlaySound(data, winsound.SND_MEMORY)
            return True
        except (RuntimeError, OSError) as e:  # noqa: BLE001
            log("警告: 通知音の再生に失敗（PlaySound・Beep へ退避）: %r" % e)
    try:  # 退避経路: 合成 WAV が鳴らない環境でも最低限の鳴り分けは残す
        for (freq, start, end) in SOUND_DEFS.get(sound_type, SOUND_DEFS[DEFAULT_SOUND_TYPE]):
            ms = int(max(0.0, min(end, SOUND_MAX_SEC) - start) * 1000)
            if ms > 0:
                winsound.Beep(int(freq), ms)
        return True
    except (RuntimeError, OSError, ValueError) as e:  # noqa: BLE001
        log("警告: 通知音の再生に失敗（Beep）: %r" % e)
        return False


def play_sound_async(sound_type):
    """通知音を別スレッドで鳴らす。再生中の重ね掛けは捨てる（スレッドの積み上がり防止）。"""
    def _run():
        try:
            _play_sound_blocking(sound_type)
        except Exception as e:  # noqa: BLE001 — 再生スレッドで本体を落とさない
            log("エラー（通知音再生・継続）: %r" % e)
        finally:
            try:
                _SOUND_BUSY.release()
            except RuntimeError:
                pass

    if not _SOUND_BUSY.acquire(False):
        log("通知音: 直前の再生が続いているため今回はスキップ")
        return False
    try:
        threading.Thread(target=_run, daemon=True, name="deck-sound").start()
        return True
    except RuntimeError as e:  # noqa: BLE001 — スレッドを作れない場合も本体は継続
        log("警告: 通知音のスレッド起動に失敗: %r" % e)
        try:
            _SOUND_BUSY.release()
        except RuntimeError:
            pass
        return False


def _clean_overrides(mapping):
    """受け取った時刻上書きを検証して {str: "HH:MM"} に正規化する。不正な項目は捨てる。"""
    out = {}
    if not isinstance(mapping, dict):
        return out
    for key, value in mapping.items():
        if len(out) >= OVR_MAX_ENTRIES:
            break
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        m = _TIME_HM_RE.search(value)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            continue
        out[key] = value.strip()
    return out


class SoundStore:
    """board.js から中継されるボード側の状態を保持する。

    内訳は ①通知音の設定（ON/OFF・音種）②当日の発火済みキー ③✎ による時刻の手動上書き。
    ①③は HTTP スレッド、②は監視ループスレッドが書くため、ロックで保護する。
    プロセス再起動後も残るよう sound.json に永続化する（保存失敗は警告のみ）。
    ※ファイル名とクラス名は通知音だけを持っていた頃のまま。既存の設定を捨てないため据え置く。
    """

    def __init__(self, path=SOUND_STATE_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._enabled = False
        self._type = DEFAULT_SOUND_TYPE
        self._fired_date = ""
        self._fired = set()
        self._ovr = {}        # {元キー（HTMLの時刻|タイトル）: 上書き後の表示時刻}
        self._ovr_date = ""   # 受け取った日（Deck のローカル日付）。日付が変われば無効
        self._ovr_rev = 0     # 版数。時刻トリガーのキャッシュを作り直す判定に使う
        self._pending = []    # 未確認通知（まだユーザーが見ていないもの）
        self._pending_date = ""
        self._load()

    def _load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self._enabled = bool(data.get("enabled"))
        stype = data.get("type")
        self._type = stype if stype in SOUND_DEFS else DEFAULT_SOUND_TYPE
        self._fired_date = data.get("fired_date") if isinstance(data.get("fired_date"), str) else ""
        fired = data.get("fired")
        if isinstance(fired, list):
            self._fired = set(k for k in fired if isinstance(k, str))
        self._ovr_date = data.get("ovr_date") if isinstance(data.get("ovr_date"), str) else ""
        self._ovr = _clean_overrides(data.get("ovr"))
        self._pending_date = (data.get("pending_date")
                              if isinstance(data.get("pending_date"), str) else "")
        pending = data.get("pending")
        if isinstance(pending, list):
            self._pending = [p for p in pending
                             if isinstance(p, dict) and isinstance(p.get("key"), str)][:PENDING_MAX]

    def _save_locked(self):
        """呼び出し元がロックを保持している前提で保存する（save_state と同じ原子的置換）。"""
        payload = {
            "enabled": self._enabled,
            "type": self._type,
            "fired_date": self._fired_date,
            "fired": sorted(self._fired),
            "ovr_date": self._ovr_date,
            "ovr": self._ovr,
            "pending_date": self._pending_date,
            "pending": self._pending,
        }
        fd = None
        tmp = None
        try:
            dir_name = os.path.dirname(self._path) or "."
            fd, tmp = tempfile.mkstemp(prefix=".deck-sound-", suffix=".tmp", dir=dir_name)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fd = None
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self._path)
            tmp = None
        except OSError as e:
            log("警告: sound.json の保存に失敗: %s" % e)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp is not None:
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def config(self):
        """(有効か, 音種) を返す。"""
        with self._lock:
            return self._enabled, self._type

    def set_config(self, enabled, sound_type):
        """設定を更新して永続化する。適用後の (有効か, 音種) を返す。"""
        with self._lock:
            self._enabled = bool(enabled)
            self._type = sound_type if sound_type in SOUND_DEFS else DEFAULT_SOUND_TYPE
            self._save_locked()
            return self._enabled, self._type

    def set_overrides(self, mapping):
        """✎ の時刻上書きを丸ごと差し替えて永続化する。採用した件数を返す。

        board.js は差分ではなく毎回すべてを送るため、ここでも置き換えにする
        （上書きを外したときは、そのキーが消えた地図が届いて元の時刻へ戻る）。
        """
        cleaned = _clean_overrides(mapping)
        with self._lock:
            self._ovr = cleaned
            self._ovr_date = datetime.now().strftime("%Y-%m-%d")
            self._ovr_rev += 1
            self._save_locked()
            return len(cleaned)

    def overrides(self):
        """(版数, {元キー: 上書き後の表示時刻}) を返す。日付が変わっていれば空。"""
        with self._lock:
            if self._ovr_date != datetime.now().strftime("%Y-%m-%d"):
                return self._ovr_rev, {}
            return self._ovr_rev, dict(self._ovr)

    def add_pending(self, date_str, key, time_text, title):
        """未確認通知に積む。既にあれば何もしない。積んだら True。

        fired（もう判定しない）とは別concept: こちらは「まだユーザーが見ていない」。
        ブラウザを閉じていても・リロードで消えても、ack されるまで残す。
        """
        with self._lock:
            if date_str != self._pending_date:
                self._pending_date = date_str
                self._pending = []
            if any(p.get("key") == key for p in self._pending):
                return False
            if len(self._pending) >= PENDING_MAX:
                return False
            self._pending.append({
                "key": key,
                "time": time_text,
                "title": title,
                "at": datetime.now().strftime("%H:%M:%S"),
            })
            self._save_locked()
            return True

    def pending(self):
        """未確認通知の一覧。日付が変わっていれば空。"""
        with self._lock:
            if self._pending_date != datetime.now().strftime("%Y-%m-%d"):
                return []
            return [dict(p) for p in self._pending]

    def ack(self, keys):
        """指定キーを未確認から外す。外した件数を返す。"""
        wanted = set(k for k in keys if isinstance(k, str))
        if not wanted:
            return 0
        with self._lock:
            before = len(self._pending)
            self._pending = [p for p in self._pending if p.get("key") not in wanted]
            removed = before - len(self._pending)
            if removed:
                self._save_locked()
            return removed

    def mark_fired(self, date_str, key):
        """未発火なら記録して True。既に発火済み（または記録済み）なら False。"""
        with self._lock:
            if date_str != self._fired_date:
                self._fired_date = date_str
                self._fired = set()
            if key in self._fired:
                return False
            self._fired.add(key)
            self._save_locked()
            return True


def read_board_alarms(board_path, overrides=None):
    """board.html から時刻付き・未完了の item を拾う。

    返り値: [(発火済み判定に使うキー, 予定時刻の分, 表示時刻文字列, タイトル), ...]
    board.js の checkAlarms と同じ条件で絞る（time 要素があり、済チップを持たない item）。
    完了判定はチップを唯一の真実とする（done-item クラスは board.js が表示時に付けるため
    HTML 正本には無いことがある・board.js の完了表示自動整合と同じ考え方）。

    overrides（✎ の手動変更・board.js から中継）に HTML 由来の元キーがあれば、その時刻を
    実効時刻として採用する。返すキーも「実効時刻|タイトル」にするので、時刻を動かすたびに
    別キーとなり、新しい時刻で鳴る（古い発火記録は消さなくても邪魔をしない）。
    """
    try:
        with open(board_path, "rb") as f:
            lines = f.read().decode("utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError) as e:
        log("警告: board.html を読めません（時刻トリガー判定）: %s" % e)
        return []
    _sections, items, _deck = _scan_board(lines)
    out = []
    for (s, e, _name) in items:
        blk = "".join(lines[s:e + 1])
        if _CHIP_DONE_RE.search(blk):
            continue
        disp = _element_text(blk, "time")
        if not disp:
            continue
        title_raw = _element_text(blk, "task-title") or ""
        if overrides:
            # board.js の taskKey は data-orig（＝HTML の元時刻）で作られるため、
            # 突き合わせは上書き前のキーで行う。
            eff = overrides.get(_item_key(blk))
            if eff and _TIME_HM_RE.search(eff):
                disp = eff
        m = _TIME_HM_RE.search(disp)
        if not m:
            continue
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            continue
        # board.js の checkAlarms と同一定義（時刻は個別に trim してから連結する）
        key = (disp.strip() + "|" + title_raw).strip()
        out.append((key, hour * 60 + minute, disp.strip(), title_raw.strip()))
    return out


def check_alarms(board_path, store, cache, now=None):
    """時刻トリガーを判定し、未発火のものを記録して必要なら鳴らす。鳴らした件数を返す。

    cache は {"stamp": ..., "alarms": [...]} の可変辞書。board.html の mtime・時刻上書きの
    版数・日付のいずれかが変わったときだけ読み直す（監視ループは 5 秒ごとに呼ばれるため）。
    """
    now_dt = datetime.fromtimestamp(now) if now else datetime.now()
    date_str = now_dt.strftime("%Y-%m-%d")
    now_min = now_dt.hour * 60 + now_dt.minute
    ovr_rev, ovr = store.overrides()
    stamp = (_board_mtime(board_path), ovr_rev, date_str)
    if cache.get("stamp") != stamp:
        cache["stamp"] = stamp
        cache["alarms"] = read_board_alarms(board_path, ovr)
    played = 0
    for (key, minutes, disp, title) in cache["alarms"]:
        if minutes > now_min:
            continue
        if not store.mark_fired(date_str, key):
            continue
        late = now_min - minutes
        if late > ALARM_GRACE_MIN:
            # 開くのが遅れた過去分はまとめて鳴らさない（board.js と同じ扱い）
            log("時刻トリガー: %s %s（%d分超過のため鳴らさない）" % (disp, title, late))
            continue
        # ポップアップは Deck が「未確認」として持ち、board.js が取りに来て描画する。
        # ブラウザが閉じていても・5分ごとの自動リロードで消えても、ack されるまで残る。
        store.add_pending(date_str, key, disp, title)
        enabled, sound_type = store.config()
        log("時刻トリガー: %s %s（通知音=%s・音種=%s）"
            % (disp, title, "ON" if enabled else "OFF", sound_type))
        if enabled and play_sound_async(sound_type):
            played += 1
    return played


# ---------------------------------------------------------------- 受信の照合（v2.1）
#
# 127.0.0.1 は PC 全体で共有され、ブラウザで開いたどのページからも要求を送れる。Deck は
# 「自分の board.html を開いたページから来た要求か」を確かめてから応じる。
# 検査は次の順に行い、最初に外れたところで 403 を返す（_request_ok → _token_ok → _board_ok）。
#
# - Host: 「127.0.0.1:<自分のポート>」だけを受ける（board.js が使う表記。localhost も断る）。
#   ブラウザの DNS リバインディング（外部の名前を 127.0.0.1 に向け直す攻撃）では、ページと
#   Deck が同じオリジン扱いになり、GET には Origin が付かない。Host にはその外部の名前が
#   残るので、ここで断れる（HTTP の仕様による・未実測）。
# - Origin: ヘッダがあって値が "null" 以外なら断る。file:// で開いたボードは Origin: null を
#   送る（実ブラウザでの実測は deck/README.md「受信ポートと照合（v2.1）」）。この検査が断るのは、
#   外部のサイトが自分のオリジンのまま送る要求だけである。sandbox 属性付きの iframe など
#   オリジンが不透明なページも Origin: null を送り、ここを通る（Reviewer の実測: 公開サイトを
#   模したページの sandbox iframe から、トークン導入前の v2.1 に読み書きとも通った）。
#   それを止めるのは次のトークンである。
#   Origin が無い要求（curl・Python 等、ブラウザ以外の同じ PC のプロセス）は通す——
#   ブラウザは CORS の要求と GET 以外の要求に Origin を付けるので、ブラウザから Origin 無しで
#   届くのは副作用の無い GET の一部に限られ（その応答は読めない）、ブラウザ以外のプロセスは
#   Origin を自由に偽れるので、求めても守りにならないため。
#   OPTIONS（プリフライト）にも同じ Host / Origin の検査をかける。
# - トークン: 起動ごとに secrets.token_urlsafe(32) で作り、受信ポートと一緒に board.html の
#   DECK:AUTO 領域へ書く（deck_key_element）。board.js は自分のボードの DOM からそれを読み、
#   全要求に ?k=<トークン> を添える。一致は hmac.compare_digest（定数時間）で比べる。
#   外部のサイト（sandbox iframe を含む）はローカルの board.html を読めず（ブラウザの権限による）、
#   別の Windows ユーザーは他人のプロファイルの board.html を読めない（OS の既定の権限による・
#   未検証）ので、トークンを知りえない。それ以外に知りうるものは下の「限界」。
#   クエリで送るのは申告と同じ理由（ヘッダだとプリフライトが増える）。/ping と OPTIONS は
#   トークンを求めない。
# - 申告（ボード）: board.js は全要求に ?board=<location.href から # と ? 以降を除いたもの> を
#   付ける。ヘッダで送らないのは、独自ヘッダを付けるとブラウザが送信前に OPTIONS の確認
#   （プリフライト）を挟むようになり、v2.0 まで実ブラウザで動いてきた単純な要求の形を
#   変えてしまうため（クエリなら要求の形は変わらない）。
# - 照合: 申告の file: URL をローカルパスに直し、自分の board_path と比べる。まず I/O の無い
#   abspath と splitdrive でドライブ部分を比べ、同じドライブ文字のときだけ realpath + normcase
#   （多重起動ガードのロックと同じ正規化）で比べる。UNC（\\server\share）・デバイスパス
#   （\\.\pipe 等）・別ドライブは realpath を呼ばずに不一致にする——申告されたパスをそのまま
#   realpath に渡すと、UNC では名前解決・SMB 接続まで進む（Reviewer の実測: 存在しないホストで
#   約 1.25 秒）。そのため board.html 自体が UNC 上にある構成では、どの申告とも一致しない。
# - 失敗の扱い: トークン・申告が無い／読めない／一致しない要求は、読み取り（GET）も
#   書き込み（POST）も 403 で断る。読み取りも断るのは、/notifications・/sound/config・
#   /board/times が別ユーザーのタスク名・時刻・設定を返してしまうため。トークンと申告を
#   求めないのは /ping（固定文字列を返すだけ）と OPTIONS（プリフライトへの応答）だけ。
# - 限界: トークンは board.html に平文で書く。board.html を読めるもの——同じ Windows ユーザーの
#   プロセス、管理者、board.html を読み込む Claude のセッション（today-board スキルの update
#   モードは board.html 全体を読む）とその記録、artifact モードで発行したボード——はトークンを
#   知りうる。Deck を再起動すればトークンは替わる。


def board_path_from_url(value):
    """board.js が ?board= で送るボードの URL（file:）をローカルパスにする。読めなければ None。

    ホスト名付きの file: URL（file://server/... ・file://./pipe/...）は扱わない（None）。
    """
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    try:
        parts = urllib.parse.urlsplit(value)
        if parts.scheme.lower() != "file":
            return None
        if parts.netloc and parts.netloc.lower() != "localhost":
            return None
        path = urllib.request.url2pathname(parts.path)
    except (ValueError, OSError):
        return None
    return path or None


def _drive_key(path):
    """I/O をしないドライブ部分の比較キー。照合しない形（UNC・デバイスパス等）なら None。"""
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if os.name == "nt":
        # 「C:」の形だけを照合する。UNC（\\server\share）・\\.\ ・\\?\ はここで落とす
        if len(drive) != 2 or drive[1] != ":" or not drive[0].isalpha():
            return None
    return os.path.normcase(drive)


def same_board(claimed, own):
    """申告されたパス claimed が自分のボード own と同じファイルを指すか。

    ドライブ部分を I/O なしで先に比べ、同じドライブのときだけ realpath + normcase で比べる
    （UNC・デバイスパス・別ドライブは realpath を呼ばずに False）。
    """
    try:
        if not (os.path.isabs(claimed) and os.path.isabs(own)):
            return False
        key = _drive_key(claimed)
        if key is None or key != _drive_key(own):
            return False
        return (os.path.normcase(os.path.realpath(os.path.abspath(claimed)))
                == os.path.normcase(os.path.realpath(own)))
    except (OSError, ValueError, TypeError):
        return False


_reject_log_state = {"at": 0.0, "count": 0}
_reject_log_lock = threading.Lock()


def _log_rejected(method, route, reason):
    """受信を断った記録。古いトークンのまま開いているページ（3 秒ごとに要求を出す）で
    watcher.log が埋まらないよう、REJECT_LOG_SEC に 1 行へまとめる（件数と、最後に断った要求の理由）。
    申告されたパス・トークン・Host・Origin の値は書かない（別ユーザーのパスや外部の名前のため）。"""
    now = time.time()
    with _reject_log_lock:
        _reject_log_state["count"] += 1
        if now - _reject_log_state["at"] < REJECT_LOG_SEC:
            return
        count = _reject_log_state["count"]
        _reject_log_state["at"] = now
        _reject_log_state["count"] = 0
    log("受信を拒否: %s %s → 403 %s（直近 %d 件）"
        % (method, route, reason, count))


class _BoardMoveHandler(BaseHTTPRequestHandler):
    """ボードD&D移動の受信ハンドラ（127.0.0.1 限定・受信のみ・送信なし）。

    どの経路でも例外でウォッチャー本体を落とさない。board_path はサブクラス属性で
    差し替える（start_move_server() が type() で生成。テストでは臨時パス・臨時ポート）。
    全経路で Host / Origin を確かめ、/ping と OPTIONS 以外は ?board= の申告が board_path と
    一致したときだけ応じる（v2.1。順序と理由は「受信の照合」節）。
    """

    board_path = None
    sound_store = None
    token = None  # 起動ごとのトークン（start_move_server が渡す。None なら全要求を断る）
    server_version = "DeckBoardMover/2.1"
    timeout = 10  # 遅いクライアントがスレッドを掴み続けないように

    def log_message(self, fmt, *args):  # noqa: N802
        # 必須オーバーライド: 既定実装は sys.stderr に書くが、pythonw では
        # sys.stderr が None のため例外になる。アクセスログは不要なので握り潰す。
        pass

    def _split_path(self):
        """(経路, ?board= の値または None) を返す。?k= は self._key_value に控える。"""
        parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parts.query)
        keys = query.get("k")
        self._key_value = keys[0] if keys else None
        values = query.get("board")
        return parts.path, (values[0] if values else None)

    def _token_ok(self, method, route):
        """?k= が起動時のトークンと一致すれば True（定数時間で比べる）。違えば 403 で False。"""
        given = getattr(self, "_key_value", None)
        if not self.token:
            reason = "token unavailable"
        elif not given:
            reason = "token required"
        elif not hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8")):
            reason = "token mismatch"
        else:
            return True
        _log_rejected(method, route, reason)
        self._send(403, json.dumps({"ok": False, "error": reason}).encode("utf-8"))
        return False

    def _request_ok(self, method, route):
        """Host と Origin を確かめる。通れば True。外れたら 403 を返して False。"""
        host = (self.headers.get("Host") or "").strip().lower()
        if host != "127.0.0.1:%d" % self.server.server_address[1]:
            reason = "host not allowed"
        else:
            origin = self.headers.get("Origin")
            if origin is not None and origin.strip() != "null":
                reason = "origin not allowed"
            else:
                return True
        _log_rejected(method, route, reason)
        self._send(403, json.dumps({"ok": False, "error": reason}).encode("utf-8"))
        return False

    def _board_ok(self, method, route, board_value):
        """申告が自分の board.html と一致すれば True。違えば 403 を返して False。"""
        if board_value is None:
            reason = "board required"
        else:
            claimed = board_path_from_url(board_value)
            if claimed is None:
                reason = "board unreadable"
            elif self.board_path is None or not same_board(claimed, self.board_path):
                reason = "board mismatch"
            else:
                return True
        _log_rejected(method, route, reason)
        self._send(403, json.dumps({"ok": False, "error": reason}).encode("utf-8"))
        return False

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        """CORS ヘッダ付きで応答を返す（file:// で開いたボードからの fetch を通す）。

        許すオリジンは "null"（file:// のページ）だけ。v2.0 までは "*" だった（v2.1）。
        """
        try:
            self.send_response(code)
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            if code == 204:
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()
                return
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
        except OSError:
            pass  # クライアント切断等は無視（本体を落とさない）

    def do_OPTIONS(self):  # noqa: N802 — Chrome の Private Network Access プリフライト
        try:
            if not self._request_ok("OPTIONS", urllib.parse.urlsplit(self.path).path):
                return
            self._send(204)
        except Exception as e:  # noqa: BLE001
            log("エラー（OPTIONS 応答・継続）: %r" % e)

    def do_GET(self):  # noqa: N802
        try:
            route, board_value = self._split_path()
            if not self._request_ok("GET", route):
                return
            if route == "/ping":
                self._send(200, b"deck-board-mover", "text/plain; charset=utf-8")
                return
            if route not in ("/sound/config", "/board/times", "/notifications"):
                self._send(404, b'{"ok": false, "error": "not found"}')
                return
            if not self._token_ok("GET", route):
                return
            if not self._board_ok("GET", route, board_value):
                return
            if route == "/sound/config":
                enabled, sound_type = (self.sound_store.config()
                                       if self.sound_store else (False, DEFAULT_SOUND_TYPE))
                body = json.dumps({"ok": True, "enabled": enabled, "type": sound_type},
                                  ensure_ascii=False).encode("utf-8")
                self._send(200, body)
            elif route == "/board/times":
                _rev, ovr = (self.sound_store.overrides()
                             if self.sound_store else (0, {}))
                body = json.dumps({"ok": True, "ovr": ovr},
                                  ensure_ascii=False).encode("utf-8")
                self._send(200, body)
            else:  # /notifications
                items = self.sound_store.pending() if self.sound_store else []
                # "deck" は board.js が「稼働」と描く前に確かめる目印（v2.1）
                body = json.dumps({"ok": True, "deck": "today-board", "items": items},
                                  ensure_ascii=False).encode("utf-8")
                self._send(200, body)
        except Exception as e:  # noqa: BLE001
            log("エラー（GET 応答・継続）: %r" % e)

    def do_POST(self):  # noqa: N802
        try:
            route, board_value = self._split_path()
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            # 経路の判定・照合より先に本文を読み切る。読まずに 404 / 403 を返して接続を閉じると、
            # Windows では未読のデータが残った接続が中止され、応答が届かないことがある
            # （v2.1 作成時の実測: v2.0 は未知の経路への POST に本文を読まず 404 を返す。同じ要求を
            # 2 回送り、1 回目はクライアント側が WinError 10053 で応答を受け取れず、2 回目は届いた）
            raw = self.rfile.read(length) if 0 < length <= 1024 * 1024 else b""
            if not self._request_ok("POST", route):
                return
            if route not in ("/board/move", "/sound/config", "/board/times",
                             "/notifications/ack"):
                self._send(404, b'{"ok": false, "error": "not found"}')
                return
            if not self._token_ok("POST", route):
                return
            if not self._board_ok("POST", route, board_value):
                return
            # Content-Type は問わない（board.js は文字列 body で送るため text/plain で届く）
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                data = None
            if not isinstance(data, dict):
                log("受信: 不正JSON（%s）→ 400" % route)
                self._send(400, b'{"ok": false, "error": "invalid json"}')
                return
            if route == "/sound/config":
                self._handle_sound_config(data)
                return
            if route == "/board/times":
                self._handle_board_times(data)
                return
            if route == "/notifications/ack":
                self._handle_notifications_ack(data)
                return
            k = data.get("k")
            sec = data.get("sec")
            before = data.get("before")
            if not isinstance(before, str):
                before = None  # null / 欠落は「末尾へ」
            head = bool(data.get("head"))
            code, msg = apply_move_to_board(self.board_path, k, sec, before, head)
            log("移動受信: k=%r sec=%r → %d (%s)" % (k, sec, code, msg))
            if code == 200:
                body = b'{"ok": true}'
            else:
                body = json.dumps({"ok": False, "error": msg},
                                  ensure_ascii=False).encode("utf-8")
            self._send(code, body)
        except Exception as e:  # noqa: BLE001 — どの経路でも本体を落とさない
            log("エラー（移動処理・継続）: %r" % e)
            try:
                self._send(500, b'{"ok": false, "error": "internal error"}')
            except Exception:  # noqa: BLE001
                pass

    def _handle_sound_config(self, data):
        """通知音の設定更新（と試聴）。board.js の⚙パネルからの POST を受ける。"""
        if self.sound_store is None:
            self._send(503, b'{"ok": false, "error": "sound store unavailable"}')
            return
        enabled, sound_type = self.sound_store.set_config(
            data.get("enabled"), data.get("type"))
        tested = bool(data.get("test")) and play_sound_async(sound_type)
        log("通知音設定: 有効=%s 音種=%s%s"
            % ("ON" if enabled else "OFF", sound_type, "（試聴）" if tested else ""))
        body = json.dumps({"ok": True, "enabled": enabled, "type": sound_type,
                           "tested": tested}, ensure_ascii=False).encode("utf-8")
        self._send(200, body)

    def _handle_board_times(self, data):
        """✎ の時刻上書き（board.js の localStorage `ovr:<日付>` の写し）を受ける。"""
        if self.sound_store is None:
            self._send(503, b'{"ok": false, "error": "store unavailable"}')
            return
        count = self.sound_store.set_overrides(data.get("ovr"))
        log("時刻上書き受信: %d 件" % count)
        body = json.dumps({"ok": True, "count": count},
                          ensure_ascii=False).encode("utf-8")
        self._send(200, body)

    def _handle_notifications_ack(self, data):
        """ユーザーがトーストを閉じた通知を未確認から外す。"""
        if self.sound_store is None:
            self._send(503, b'{"ok": false, "error": "store unavailable"}')
            return
        keys = data.get("keys")
        if not isinstance(keys, list):
            keys = []
        removed = self.sound_store.ack(keys)
        if removed:
            log("通知の確認: %d 件を未確認から外した" % removed)
        body = json.dumps({"ok": True, "removed": removed},
                          ensure_ascii=False).encode("utf-8")
        self._send(200, body)


class _DeckMoveServer(ThreadingHTTPServer):
    # Windows の SO_REUSEADDR は「使用中ポートへの二重バインド」を黙って成功させて
    # しまう（HTTPServer 既定の allow_reuse_address=1 では衝突を検知できない）ため、
    # Windows では無効化してバインド失敗を確実に OSError にする。POSIX では既定どおり
    # （TIME_WAIT 直後の再起動失敗を避ける）。
    allow_reuse_address = os.name != "nt"


def new_deck_token():
    """起動ごとのトークン（32 バイトの乱数を URL 安全な文字で 43 文字にしたもの）。"""
    return secrets.token_urlsafe(32)


def deck_key_element(port, token):
    """DECK:AUTO 領域の先頭に置く、board.js 向けの接続情報（画面には出ない）。"""
    return ('<span id="deck-key" hidden data-port="%d" data-k="%s"></span>'
            % (int(port), html.escape(token, quote=True)))


def start_move_server(board_path, sound_store=None, port=None, token=None):
    """受信サーバをデーモンスレッドで起動する。全ポートでバインド失敗なら None（監視は継続）。

    port を省くと BOARD_MOVE_PORT から BOARD_PORT_COUNT 個を順に試し、最初に取れたもので
    受信する（v2.1。同じ PC の別ユーザーの Deck や他のプログラムが先に使っていれば次へ）。
    port を渡したときはそのポートだけを試す（テスト用）。
    """
    handler = type("DeckBoardMoveHandler", (_BoardMoveHandler,),
                   {"board_path": board_path, "sound_store": sound_store, "token": token})
    if port is None:
        ports = list(range(BOARD_MOVE_PORT, BOARD_MOVE_PORT + BOARD_PORT_COUNT))
    else:
        ports = [port]
    failures = []
    for p in ports:
        try:
            server = _DeckMoveServer(("127.0.0.1", p), handler)
        except OSError as e:
            failures.append("%d: %s" % (p, e))
            continue
        thread = threading.Thread(target=server.serve_forever, daemon=True,
                                  name="deck-board-move-server")
        thread.start()
        if failures:
            log("受信ポート %s は使用中のため %d で受信します" % (
                "・".join(f.split(":", 1)[0] for f in failures), p))
        log("受信サーバ起動: http://127.0.0.1:%d/ (board/move・sound/config, board=%s)"
            % (p, board_path))
        return server
    log("警告: 受信ポート %d〜%d をすべてバインドできません（ボードD&D反映・通知音の設定・"
        "未確認通知の受け渡しは無効・監視と通知音の発音は継続）: %s"
        % (ports[0], ports[-1], " / ".join(failures)))
    return None


# ---------------------------------------------------------------- 再生成 1 回分


_last_inject_result = None  # no-marker / no-board 警告の連続再ログ抑止（ログ洪水防止）
_last_restore_skip_reason = None  # 同じく、目印を足さなかった理由（理由が変わったときだけ書き直す・v2.5）


_activity_refresh_at = None  # 次に時間経過だけで再生成すべき時刻（next_refresh_at・v2.0）


def regenerate(projects_dir, board_path, state, state_path, deck_key=None):
    """収集 → 生成 → 注入 → 状態保存 を 1 回実行。inject の結果文字列を返す。

    deck_key は deck_key_element() の文字列。常駐で受信サーバが動いているときだけ渡し、
    DECK:AUTO 領域の先頭に置く（--once では渡さない＝常駐が書いたトークンを別の値で上書きしない。
    消えた分は常駐が board.html の変化を検知して次の周回で書き戻す）。
    """
    global _last_inject_result, _last_restore_skip_reason
    now = time.time()
    global _activity_refresh_at
    sessions = collect_sessions(projects_dir, state, now)
    _activity_refresh_at = next_refresh_at(sessions, now)
    block = build_html(sessions, now)
    if deck_key:
        block = deck_key + "\n" + block
    result = inject(board_path, block)
    save_state(state, state_path)
    if result == "written":
        log("再生成: セッション %d 件を board.html に反映" % len(sessions))
    elif result == "no-marker" and (result != _last_inject_result
                                    or _restore_skip_reason != _last_restore_skip_reason):
        log("警告: board.html に DECK:AUTO マーカーが見つかりません（挿入は行いません%s）"
            % (("・" + _restore_skip_reason) if _restore_skip_reason else ""))
    elif result == "no-board" and result != _last_inject_result:
        log("警告: board.html が存在しません（まだ一度も発行されていないか、移動・削除されています）。スキップして継続")
    _last_inject_result = result
    _last_restore_skip_reason = _restore_skip_reason if result == "no-marker" else None
    return result


# ---------------------------------------------------------------- 監視ループ


def snapshot_transcripts(projects_dir, now):
    """{path: (size, mtime)} スナップショット（48h 以内の transcript のみ）。"""
    snap = {}
    for path, mtime in list_transcripts(projects_dir, now):
        try:
            snap[path] = (os.path.getsize(path), mtime)
        except OSError:
            pass
    return snap


def _board_mtime(board_path):
    try:
        return os.path.getmtime(board_path)
    except OSError:
        return None


def watch_loop(projects_dir, board_path, state, state_path, sound_store=None, deck_key=None,
               assets_dir=DEFAULT_SKILL_ASSETS):
    log("起動: 常駐モード開始 (projects=%s, board=%s)" % (projects_dir, board_path))
    if not os.path.isdir(projects_dir):
        log("警告: projects ディレクトリが存在しません: %s" % projects_dir)

    last_snapshot = object()   # 初回は必ず不一致 → 起動直後に 1 回生成
    known_board_mtime = None   # 自分の書き込み後（または直近確認時）の board mtime
    last_guard_block = None    # 監視ねこセクション（変化＝時間経過だけでも再生成する）
    board_missing_logged = False
    alarm_cache = {}           # 時刻トリガー判定用（board.html の mtime 変化時だけ読み直す）
    roll_state = {"seen": None, "last": None}  # 日付の切り替えを最後に確かめた (board の mtime, 日付) と結果
    asset_state = {"next": 0.0}  # 次にスキルの静的ファイルをそろえる時刻（起動直後の1周目にも走る・v2.3）

    while True:
        try:
            now = time.time()
            asset_step(board_path, assets_dir, asset_state, now)
            # 日付の切り替え（v2.2）。確かめる契機と、例外のときの間隔・回数は rollover_step が持つ
            # （毎周回ボードを読まない。起動直後の1周目にも走る）
            rollover_step(board_path, assets_dir, roll_state, now)
            snapshot = snapshot_transcripts(projects_dir, now)
            current_board_mtime = _board_mtime(board_path)
            # 常駐の生死は時間経過だけで変わる（transcript が動かなくても「停止」に落ちる）。
            # transcript 変化のみを再生成条件にすると、死んだ常駐が「稼働」のまま残る。
            guard_block = "\n".join(build_guard_html(now))

            # 「作業中」→「応答なし」の切り替えも時間経過だけで起きる（v2.0）
            refresh_due = _activity_refresh_at is not None and now >= _activity_refresh_at
            if (snapshot != last_snapshot
                    or current_board_mtime != known_board_mtime
                    or guard_block != last_guard_block
                    or refresh_due):
                result = regenerate(projects_dir, board_path, state, state_path, deck_key)
                last_snapshot = snapshot
                last_guard_block = guard_block
                known_board_mtime = _board_mtime(board_path)

                if result == "no-board":
                    board_missing_logged = True
                elif board_missing_logged:
                    board_missing_logged = False
                    log("board.html を検出。監視を再開しました")
            # 変化なし → 何もしない（CPU をほぼ使わない）

            # 時刻トリガー（通知音）は再生成の有無に関わらず毎周回で判定する。
            # ブラウザ側は自動再生制限で鳴らせないため、発音は Deck が受け持つ。
            if sound_store is not None:
                check_alarms(board_path, sound_store, alarm_cache, now)
        except Exception as e:  # noqa: BLE001 — 常駐は何があっても落とさない
            log("エラー（継続）: %r" % e)
        time.sleep(POLL_SEC)


# ---------------------------------------------------------------- main


def main(argv):
    args = list(argv[1:])
    once = False
    projects_dir = DEFAULT_PROJECTS_DIR
    board_path = DEFAULT_BOARD_PATH
    state_path = DEFAULT_STATE_PATH
    rollover_once = False
    today_arg = None
    assets_dir = DEFAULT_SKILL_ASSETS
    assets_explicit = False

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--once":
            once = True
        elif a == "--rollover-once":
            rollover_once = True
        elif a == "--today" and i + 1 < len(args):
            i += 1
            try:
                today_arg = datetime.strptime(args[i], "%Y-%m-%d").date()
            except ValueError:
                print("--today は YYYY-MM-DD で指定してください: %s" % args[i], file=sys.stderr)
                return 2
        elif a == "--skill-assets" and i + 1 < len(args):
            i += 1
            assets_dir = args[i]
            assets_explicit = True
        elif a == "--projects-dir" and i + 1 < len(args):
            i += 1
            projects_dir = args[i]
        elif a == "--board" and i + 1 < len(args):
            i += 1
            board_path = args[i]
        elif a == "--state" and i + 1 < len(args):
            i += 1
            state_path = args[i]
        else:
            print("不明な引数: %s" % a, file=sys.stderr)
            print(__doc__, file=sys.stderr)
            return 2
        i += 1

    if today_arg is not None and not rollover_once:
        print("--today は --rollover-once と一緒のときだけ使えます", file=sys.stderr)
        return 2

    _truncate_log_if_needed()

    # 既定以外のボード（試験用のフォルダ等）を --board で指し、--skill-assets を明示していないときは、
    # 本番スキルの静的ファイルを写さない（v2.3）。試験中の board.js を黙って本番スキルの版に戻さないため
    is_default_board = (board_path == DEFAULT_BOARD_PATH   # 文字列で一致すれば既定（UNC のホームでも止めない）
                        or same_board(os.path.abspath(board_path), os.path.abspath(DEFAULT_BOARD_PATH)))
    if not assets_explicit and not is_default_board:
        assets_dir = None
        log("静的ファイルの同期は行いません（--board が既定のボード以外で、--skill-assets の指定がないため）")

    if rollover_once:
        # 日付の切り替えを1回だけ試す（テスト用）。同じボードを見る常駐と競合しないようロックを取る
        acquired, holder = acquire_single_instance_lock(board_path)
        if not acquired:
            print("Deck が同じボードで稼働中のため試しません: %s" % holder, file=sys.stderr)
            return 1
        result = try_rollover(board_path, today=today_arg, assets_dir=assets_dir)
        log("--rollover-once 実行: 結果=%s" % result)
        print("deck_watcher --rollover-once: %s" % result)
        return 0 if result in ("rolled", "not-needed") else 1

    state = load_state(state_path)

    if once:
        t0 = time.perf_counter()
        result = regenerate(projects_dir, board_path, state, state_path)
        elapsed = (time.perf_counter() - t0) * 1000
        log("--once 実行: 結果=%s (%.0f ms)" % (result, elapsed))
        print("deck_watcher --once: %s (%.0f ms)" % (result, elapsed))
        return 0 if result in ("written", "unchanged") else 1

    # 多重起動ガードは board.html 単位（v1.9）。同じ board を見る 2 本目はここで終わる。
    acquired, holder = acquire_single_instance_lock(board_path)
    if not acquired:
        log("多重起動を検出したため終了します（board=%s / lock=%s）: 稼働中の1本目 → %s"
            % (os.path.abspath(board_path), board_lock_path(board_path), holder))
        print("Deck は既に稼働中です（多重起動ガード）: %s" % holder, file=sys.stderr)
        return 1

    # 常駐監視モードのみ受信サーバを起動（--once では起動しない）。
    # バインド失敗（ポート使用中等）でも None が返るだけで監視は継続する。
    sound_store = SoundStore()
    token = new_deck_token()  # 起動ごと。ログにもファイルにも board.html 以外には書かない
    move_server = start_move_server(board_path, sound_store, token=token)
    deck_key = (deck_key_element(move_server.server_address[1], token)
                if move_server is not None else None)
    try:
        watch_loop(projects_dir, board_path, state, state_path, sound_store, deck_key, assets_dir)
    except KeyboardInterrupt:
        log("停止: KeyboardInterrupt")
    finally:
        if move_server is not None:
            try:
                move_server.shutdown()
                move_server.server_close()
            except Exception:  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
