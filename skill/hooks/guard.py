#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""guard.py v1.1 — きょうのボードの保護（Claude Code のフック。L1・L3）。

Claude Code が hooks/hooks.json の登録どおりに起動する（make_hooks.py が書く。exec 形式で、小片が
このファイルを runpy で走らせる）。入力はフックの JSON（標準入力）。出力は標準出力に JSON 1つか、何も出さない。
どんな失敗でも終了コード 0 で抜け、2 は使わない（ガード側はフェイルオープン。書き手の board_edit.py はフェイルクローズ）。

- L1（PreToolUse・Write / Edit / MultiEdit / NotebookEdit）: 本番の board.html・board.new.html・.guard/ の下・
  history/ の下、および state.json が local モードで指す file_path への直接の書き込みを deny する。
  Bash・PowerShell は止めない。サンドボックスのボード（board_edit.py --board で指す試験用）は守らない
- L3 の控え（PreToolUse・上の4種と Bash・PowerShell）: 本番の board.html があれば、
  .guard/pre/<session_id>/<tool_use_id>.html（本文）・.json（{v, fp, k, time_ns, tool_name}）を書く。L1 で deny する呼び出しでは取らない
- L3 の比較（PostToolUse・PostToolUseFailure）: 今の板が控えとバイト一致するか、指紋が控えと同じで K1／K3／K5／K16／K17 が
  悪くなっていなければ何もしない。それ以外は、控えから書き込みの記録（.guard/auth/）の鎖を辿って正規の指紋の集合を作り、
  今の板が正規でなければ戻す（今の版は history/board-<日付>-foreign-<時刻>.html へ退避し、指紋が変わるときは自分の記録を
  先に書いてから置き換える。読み直しで板が変わっていたら読み直しからやり直し、前の巡の foreign の退避は残す。最大3回）。
  戻すのは board.html だけ。.guard/ ごと無ければ（データを消した）何もしない
- 拾い直し（UserPromptSubmit・SessionStart）: 中断で Post の来なかった同じ session_id の控えを、古い順に比べる。
  控えから10分以内で崩れていれば戻し、それ以外は控えの本文を history/…-before-interrupt-… へ退避して知らせるだけ。
  最初に24時間より古い控えを掃除する
- 「知らせるだけ」（控えが24時間より古い〔Post のみ〕・Deck が v2.6 未満・.guard/ の版を知らない・format.json が読めない）と
  「戻せなかった」（書き込みの失敗・3回続けて板が変わった）では、控えの本文を history/…-before-tool-…（拾い直しでは
  …-before-interrupt-…）へ退避し、退避できたときだけ控えを消す（できなければ控えを残し、次の拾い直しに回す）
- 控えの .json が読めないとき・控えの版を知らないときは .json だけを消し、本文（.html）は24時間の掃除に任せる
  （控えの版を知らないときは退避せずに知らせる）
- 掃除: 控えは24時間・記録は48時間より古いものを消す（PreToolUse と拾い直しのとき）。.guard/hook.log は 1 MB を超えたら
  後ろ半分に切り詰める

v1.1: 板の形の悪さに K16（ブラウザが要素として読まない所に行・見出し・Deck の欄が入って画面から消える形と、board.js の読み込みが実行されない形＝
_swallow_open。board_edit.py v1.13 の写し）と K17（実行される board.js の読み込みが無い板。K16 に当たらないときだけ）を足す。Bash・PowerShell の
書き込みで新しく K16・K17 を作ったら、K1／K3／K5 と同じく戻すか知らせる（2026-11-10 ユーザー決定）。

Python 3 標準ライブラリのみ・単一ファイル。外部ネットワーク通信はしない。
「board_edit.py の写し」と書いた節の関数・定数は skill/scripts/board_edit.py からそのまま写したもの
（指紋・検査・記録の読み書き・history/ への退避を書き手と同じ定義にするため）。変えるときは board_edit.py と
同時に変え、試験（tests/test_guard.py の T-P）で一致を確かめる。
"""

import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime

VERSION = "1.1"

# ================================================================ board_edit.py の写し（定数）

MARKER_START = "<!-- DECK:AUTO:START -->"
MARKER_END = "<!-- DECK:AUTO:END -->"
MOVABLE_SECTIONS = ("今日の予定", "今日中", "明日以降")  # D&D 移動の対象セクション
_SECTION_LABEL_RE = re.compile(r'<div class="section-label">(.*?)</div>')
_CLASS_TAG_RE = re.compile(r'<(\w+)\b[^>]*?\bclass="([^"]*)"[^>]*>')
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_ITEM_CLASS_RE = re.compile(r'(<div\s+class=")([^"]*)(")')
_ANY_CLASS_TAG_RE = re.compile(r'(<\w+\b[^>]*?\bclass=")([^"]*)(")')
WEEKDAY_JA = "月火水木金土日"    # date.weekday() の 0=月 に合わせる
_HEADER_RE = re.compile(r"<header\b.*?</header>", re.S)
_TITLE_RE = re.compile(r"(<title>)(.*?)(</title>)", re.S)
_UPD_TIME_RE = re.compile(r'(<span id="upd-time"[^>]*>)(.*?)(</span>)', re.S)
HISTORY_DIRNAME = "history"
PLACEHOLDER_RE = re.compile(r"\{\{\s*[A-Za-z0-9_]+\s*\}\}")
STRICT_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})（([月火水木金土日])）$")
GUARD_DIRNAME = ".guard"
GUARD_FORMAT_V = 1
GUARD_RECORD_MAX_AGE_SEC = 48 * 3600
_guard_last_ns = [0]   # このプロセスで最後に使った記録の時刻（消した記録の名前を使い回さないため）


# ================================================================ board_edit.py の写し（関数）

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


def _div_balance(text):
    """コメントの外の <div の数 − </div> の数。"""
    blanked = "".join(_blank_comments(text.splitlines(keepends=True)))
    return len(re.findall(r"<div\b", blanked)) - blanked.count("</div>")


# void 要素（閉じタグを持たない。_swallow_open が開いた要素に数えない。board_edit.py の写し）
_VOID_TAGS = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"))
# 閉じタグまでを文字として読む要素（_swallow_open・v2.17 / board_edit.py v1.13 / guard.py v1.1）。
# HTML の構文解析の決まりのうち、HTML として読む所で閉じタグまでを文字として読む要素: RCDATA＝textarea・title、RAWTEXT＝style・xmp・iframe・
# noembed・noframes・noscript（ボードはスクリプトが動く状態で開くので RAWTEXT）、script（script data）、plaintext（閉じタグを持たない）。
# svg・math の中（foreign content）では文字として読まないので数えない（<svg><style>・<svg><title> は閉じていなくても中の要素は読まれる）。
# K16 の当たりと Chrome の DOM が合うことは tests/test_board_browser.py の TestSwallowInBrowser で確かめる
_SWALLOW_TAGS = frozenset(("textarea", "title", "style", "xmp", "iframe", "noembed", "noframes", "noscript", "script", "plaintext"))
# svg・math の中で、ブラウザが svg・math を閉じて HTML として読み直す開きタグ（HTML の構文解析の foreign content の決まり。font は color・face・size の属性があるときだけ）
_FOREIGN_BREAKOUT = frozenset(("b", "big", "blockquote", "body", "br", "center", "code", "dd", "div", "dl", "dt", "em", "embed",
                               "h1", "h2", "h3", "h4", "h5", "h6", "head", "hr", "i", "img", "li", "listing", "menu", "meta", "nobr",
                               "ol", "p", "pre", "ruby", "s", "small", "span", "strong", "strike", "sub", "sup", "table", "tt", "u",
                               "ul", "var"))
_SW_TAG_RE = re.compile(r"<(/?)([A-Za-z][^\t\n\f\r />]*)")
_SW_ATTR_NAME_RE = re.compile(r"[^\t\n\f\r />][^\t\n\f\r /=>]*")
_SW_UNQUOTED_RE = re.compile(r"[^\t\n\f\r >]*")
_SW_SPACE = "\t\n\f\r "


def _sw_tag_end(text, i):
    """開きタグ・閉じタグの名前の直後（i）から、タグの終わりの > の直後まで読む（属性の値の引用符の中の > は読み飛ばす）。
    (> の直後, /> で終わったか, 属性〔名前は小文字・最初のものだけ〕) か、文書の終わりまで > が無ければ None。"""
    n = len(text)
    attrs = {}
    while i < n:
        c = text[i]
        if c in _SW_SPACE:
            i += 1
        elif c == ">":
            return i + 1, False, attrs
        elif c == "/":
            if text.startswith(">", i + 1):
                return i + 2, True, attrs
            i += 1
        else:
            m = _SW_ATTR_NAME_RE.match(text, i)
            name, i = m.group(0).lower(), m.end()
            while i < n and text[i] in _SW_SPACE:
                i += 1
            value = ""
            if text.startswith("=", i):
                i += 1
                while i < n and text[i] in _SW_SPACE:
                    i += 1
                if i < n and text[i] in "\"'":
                    j = text.find(text[i], i + 1)
                    if j == -1:
                        return None
                    value, i = text[i + 1:j], j + 1
                else:
                    m = _SW_UNQUOTED_RE.match(text, i)
                    value, i = m.group(0), m.end()
            attrs.setdefault(name, value)
    return None


_SW_SCRIPT_RE = re.compile(r"<!--|-->|<(/?)script(?=[\t\n\f\r />])", re.I)


def _sw_text_end(text, start, name):
    """閉じタグまでを文字として読む要素（name）の中身の始まり（start）から、閉じタグの終わりまで読む。(閉じタグの終わり, 読み込みを文字にしたか) か、
    閉じていなければ None（閉じタグが無いか、閉じタグの > が無いまま文書が終わる。plaintext は閉じタグを持たないので、いつも None）。
    script 以外は、最初の閉じタグで閉じる（中に同じ名前の開きタグがあっても文字として読むだけ＝<textarea>a<textarea>b</textarea> は閉じている）。
    script は script data の決まり（<!-- の後の <script で二重になり、そこでは </script> で閉じない）をなぞって閉じる所を決める。2つ目の値は、
    文字として読まれた範囲に src が board.js を指す <script（_sw_is_board_js）が入っているかで、_swallow_open が当たりの種類を "load" にするのに使う
    （当てるかどうかは _sw_lost と _sw_board_js_in で決める）。"""
    if name == "plaintext":
        return None
    if name != "script":
        m = re.compile(r"</%s(?=[\t\n\f\r />])" % name, re.I).search(text, start)
        if not m:
            return None
        end = _sw_tag_end(text, m.end())
        return (end[0], False) if end else None      # > の無いまま文書が終わる閉じタグでは、要素は閉じない
    state, i = 0, start      # 0＝script data・1＝<!-- の後（escaped）・2＝その中の <script の後（double escaped）
    loads = False
    while True:
        m = _SW_SCRIPT_RE.search(text, i)
        if not m:
            return None
        tok = m.group(0)
        if tok == "<!--":
            if state == 0:
                state = 1
            i = m.end() - 2          # <!--> の -- を --> にも数える
        elif tok == "-->":
            if state:
                state = 0
            i = m.end()
        elif m.group(1):            # </script
            if state == 2:
                state, i = 1, m.end()
                continue
            end = _sw_tag_end(text, m.end())
            return (end[0], loads) if end else None
        else:                       # <script
            if state == 1:
                state = 2
            tag = _sw_tag_end(text, m.end())
            if tag is not None and _sw_is_board_js(tag[2].get("src")):
                loads = True
            i = m.end()


def _sw_is_board_js(src):
    """script の src（属性の値。無ければ None）が board.js を指すか（テンプレートの <script src="board.js"> の形。? や # の後ろとパスの前の部分は見ない）。"""
    if src is None:
        return False
    path = re.split(r"[?#]", html.unescape(src).strip(), 1)[0]
    return re.split(r"[/\\]", path)[-1].lower() == "board.js"


# 画面から消えると数える要素の開きタグ（項目・見出し・行の部品。class の書き方は _ROW_PART_RE と同じ広さ。< と > をまたがない）
_SW_ROW_RE = re.compile(r'<[A-Za-z][\w-]*\b[^<>]*?\sclass\s*=\s*["\']?(?:[^"\'<>]*\s)?(?:task-title|task-note|chips|chip|item|section-label)(?=["\'\s>/])', re.I)
_SW_START_RE = re.compile(r"<[A-Za-z]")


# 実行される script の type（HTML の決まりの JavaScript の MIME 型。大文字小文字を問わない）
_SW_JS_TYPES = frozenset(("application/ecmascript", "application/javascript", "application/x-ecmascript", "application/x-javascript",
                          "text/ecmascript", "text/javascript", "text/javascript1.0", "text/javascript1.1", "text/javascript1.2",
                          "text/javascript1.3", "text/javascript1.4", "text/javascript1.5", "text/jscript", "text/livescript",
                          "text/x-ecmascript", "text/x-javascript"))
_SW_SCRIPT_OPEN_RE = re.compile(r"<script(?=[\t\n\f\r />])", re.I)


def _sw_runs(attrs):
    """script の属性（attrs）が、実行される board.js の読み込みか（最初の src が board.js を指し、nomodule が無く、type が無いか空か JavaScript の MIME 型。
    type が無く language があれば、type を text/<language> とみなす。type="module" は file: のページでは読み込めないので数えない）。
    template の中・svg・math の中・閉じていない script は、呼び出し側が見る（K16 の「board.js が止まる形」・2026-11-10 ユーザー決定）。"""
    if not _sw_is_board_js(attrs.get("src")) or "nomodule" in attrs:
        return False
    t = attrs.get("type")
    if t is None and attrs.get("language"):
        t = "text/" + attrs["language"]          # type が無く language があれば text/<language>（HTML の決まり）
    return t is None or not t.strip() or t.strip().lower() in _SW_JS_TYPES


_SW_SRC_RE = re.compile(r"""[\t\n\f\r /]src[\t\n\f\r ]*=[\t\n\f\r ]*(?:"([^"]*)"|'([^']*)'|([^\t\n\f\r >]+))""", re.I)


def _sw_src_board_js(text, a, b):
    """タグの中（text[a:b]）の src の属性のどれか（重複したものも）が board.js を指すか（board.js が止まる形の候補。属性によらない）。
    _SW_SRC_RE は属性の値の中の文字（<div title="<script src='board.js'>">）も拾う。その形も、board.js が実行されない候補に数える。"""
    return any(_sw_is_board_js(m.group(1) if m.group(1) is not None else m.group(2) if m.group(2) is not None else m.group(3))
               for m in _SW_SRC_RE.finditer(text, a, b))


def _sw_board_js_in(text, a, b):
    """text[a:b]（ブラウザが要素として読まない所）に、src のどれかが board.js を指す <script> の開きタグ（_sw_src_board_js。属性によらない）があるか。"""
    for m in _SW_SCRIPT_OPEN_RE.finditer(text, a, b):
        tag = _sw_tag_end(text, m.end())
        if tag is not None and _sw_src_board_js(text, m.end() - 1, tag[0]):
            return True                              # 候補は src が board.js を指すものすべて（2026-11-10 ユーザー決定）
    return False


def _sw_lost(text, a, b, deck):
    """text[a:b]（ブラウザが要素として読まない所）に、項目・見出し・行の部品（_SW_ROW_RE）の開きタグか、DECK 領域（deck＝(START の位置, END の位置) か None）の
    中の開きタグがあるか（K16 の基準＝画面から消える要素があるか・2026-11-10 ユーザー決定）。"""
    if a >= b:
        return False
    if _SW_ROW_RE.search(text, a, b):
        return True
    if deck:
        lo, hi = max(a, deck[0]), min(b, deck[1])
        if lo < hi and _SW_START_RE.search(text, lo, hi):
            return True
    return False


def _swallow_open(text):
    """K16（構造の検査・v2.17 / board_edit.py v1.13 / guard.py v1.1。基準は 2026-11-10 ユーザー決定）の最初の当たり。(位置, 種類, 名前) か、
    無ければ None（本体は _sw_scan）。当てるのは次の2つ。
    ①画面から消える形: ブラウザが要素として読まない所（閉じタグまでを文字として読む要素〔_SWALLOW_TAGS〕の中・コメントの中・svg や math の中の
    CDATA の中・<! と <? で始まる宣言の中・タグの中〔引用符の閉じていない属性の値を含む〕・<template> の中）に、項目・見出し・行の部品か DECK 領域の
    要素の開きタグが入る（_sw_lost）。閉じていても、閉じるのが後ろの別の要素・コメントの閉じタグなら同じく当てる。自分の --> で閉じるコメントの中の行
    （書き手がわざと隠した行。テンプレートの記入例など）は当てない。後ろのコメントの --> で閉じるコメントでも、間に行・見出し・Deck の欄が無ければ当てない
    （DECK の START マーカーだけを飲み込む形は K3 にも当たらない〔K3 は文字で数える〕が、board.js の「ボードの点検」の②に出る＝Chrome で確かめた・
    2026-11-10・ヘッドレス・実物のテンプレートの板・n=1）。
    ②board.js が止まる形: src が board.js を指す <script>（属性の値の中の文字も含め、属性によらない＝_sw_src_board_js・_sw_board_js_in）が、
    要素として読まれない所・template・svg・math の中にあるか、閉じていないか、属性で実行されない形（_sw_runs が偽）で、実行される board.js の
    読み込み（_sw_runs が真で、閉じていて、template・svg・math の中でない）を文書の終わりまでに1つも読まない。
    種類は "element"（_SWALLOW_TAGS の要素か template）・"comment"（コメントか宣言）・"cdata"・"tag"・"load"（②。①でも、文字として読まれた範囲に
    board.js の読み込みが入る script は "load"）。②の名前は、読み込みを要素として読まない所を作った要素の名前（コメントと宣言は ""、CDATA は "![CDATA["）。
    板が board.js を head で読む形（テンプレート・migrate_board_js が移した板）なら、body の①では board.js は動き、ふつうは画面の「ボードの点検」の⑦（board.js の
    TB_CUT）に出る。末尾で読む形の板では、①が board.js の読み込みも飲み込むと②にもなり、どの知らせも画面に出ない。

    文書の全体（head・手書きの範囲・DECK 領域）を、ブラウザの HTML の構文解析と同じ順で先頭から1回読む（コメント・属性の値の中は読み飛ばす）。
    svg・math の中（foreign content）は別に扱う: その中では _SWALLOW_TAGS を文字として読まない。HTML integration point（svg の foreignObject・
    desc・title、math の mi・mo・mn・ms・mtext、encoding が text/html か application/xhtml+xml の annotation-xml）の中の開きタグは HTML として読む。
    svg・math の中で _FOREIGN_BREAKOUT の開きタグか </p>・</br> が来たら、ブラウザと同じく svg・math を閉じて HTML として読む。閉じタグは、HTML の要素の中では
    svg・math の境界を越えて閉じない（<svg><foreignObject><span>x</svg> の </svg> は読み飛ばす）。
    なぞらない所（申告する限界）: 要素の暗黙の閉じ（p・li など）・表の foster parenting・書式の要素の付け直しなど木を組み立てる段階の細部
    （svg・math の閉じ方にだけ効く）。<template> の中も同じ読み方をする。"""
    return _sw_scan(text)[0]


def _sw_scan(text):
    """_swallow_open の本体。(当たり〔_swallow_open の戻り値〕, ran) を返す。ran＝実行される board.js の <script>（_sw_runs で、閉じていて、
    template・svg・math の中でない）を、当たりを返す所までに読んだか（K17 の「書く前の版にあって出来上がりに無い」の判定に使う）。"""
    # K16 の基準は「画面から消える要素がある形」（2026-11-10 ユーザー決定。board.js が動くかどうかは見ない）。ブラウザが要素として読まない所
    # （閉じタグまでを文字として読む要素の中・コメントの中・CDATA の中・タグの中・閉じタグの無い <template> の中など）に、項目・見出し・行の部品か
    # DECK 領域の要素の開きタグがあれば当てる（_sw_lost）。閉じていても、閉じるのが後ろの別の要素・コメントの閉じタグなら同じく当てる。
    # Chrome で「当たる ⇔ ソースの項目・見出し・Deck の要素のどれかが DOM に HTML の要素として無い」を確かめた＝TestSwallowInBrowser
    stack = []          # 開いている要素 [名前, 名前空間（"html"・"svg"・"math"）, integration point か, 開きタグの終わり〔template だけ〕]
    segs = [{}]         # HTML の要素の名前ごとの数を、svg・math の要素で区切った区間ごとに持つ（segs[-1] が stack の一番上の区間）。閉じタグが
                        # その区間で開いていない要素のものなら、stack を辿らずに読み飛ばす（辿り直しで遅くならないため）
    fcount = {}         # stack の中の svg・math の要素の名前ごとの数（同じ理由。0 なら svg・math の要素を辿らない）
    hidx = []           # stack の中の HTML の要素の位置（昇順。hidx[-1] より上はすべて svg・math の要素）
    tmpl = []           # stack の中の template の (位置, 開きタグの終わり)
    s = text.find(MARKER_START)
    e = text.find(MARKER_END, s + 1) if s != -1 else -1
    deck = (s, e) if s != -1 and e != -1 else None
    i = 0
    bang = text.find("--!>")     # コメントを閉じる --!> の次の位置（無ければ -1。コメントごとに文書の終わりまで探し直さない）
    dash = text.find("-->")      # コメントを閉じる --> の次の位置（同じ理由）
    opener = text.find("<!--")   # 次の <!-- の位置（同じ理由）
    n = len(text)
    # board.js が止まる形（2026-11-10 ユーザー決定）: 実行されるはずの board.js の <script>（_sw_runs）が、要素として読まれない所に入るか、
    # template・svg・math の中にあるか、閉じていない。その最初のもの（cand）を控え、実行される board.js の <script> を読まずに文書の終わりまで
    # 来たら、"load" で返す（ran＝実行される board.js の <script> を読んだ。画面から消える要素の当たりは、見つけた所ですぐ返す）
    cand = None
    ran = False

    def missed(pos, name, a, b):
        return (pos, "load", name) if cand is None and not ran and _sw_board_js_in(text, a, b) else cand

    while True:
        lt = text.find("<", i)
        if lt == -1:
            # 閉じタグの無い template は文書の終わりまで（中身は DOM の外＝template の内容）。一番外側の範囲だけを見る（内側はその中にある）
            if tmpl and _sw_lost(text, tmpl[0][1], n, deck):
                return (tmpl[0][0], "element", "template"), ran
            if tmpl:
                cand = missed(tmpl[0][0], "template", tmpl[0][1], n)
            return (None if ran else cand), ran
        top = stack[-1] if stack else None
        foreign = top is not None and top[1] != "html" and not top[2]
        if text.startswith("<!--", lt):
            if text.startswith(">", lt + 4):
                i = lt + 5
                continue
            if text.startswith("->", lt + 4):
                i = lt + 6
                continue
            if bang != -1 and bang < lt + 4:
                bang = text.find("--!>", lt + 4)
            if dash != -1 and dash < lt + 4:
                dash = text.find("-->", lt + 4)
            ends = [x for x in (dash, bang) if x != -1]
            if not ends:
                if _sw_lost(text, lt + 4, n, deck):
                    return (lt, "comment", ""), ran
                cand = missed(lt, "", lt + 4, n)
                return (None if ran else cand), ran
            end = min(ends)
            # 閉じるのが後ろの別のコメントの --> なら（間に <!-- がある）、その間の行は画面から消える。自分の --> で閉じるコメントは
            # 書き手がわざと隠したもの（テンプレートの記入例のコメントなど）なので当てない
            if opener != -1 and opener < lt + 4:
                opener = text.find("<!--", lt + 4)
            if opener != -1 and opener < end and _sw_lost(text, lt + 4, end, deck):
                return (lt, "comment", ""), ran
            cand = missed(lt, "", lt + 4, end)      # コメントの中の board.js の読み込みは実行されない（わざと隠したものも数える）
            i = end + (3 if text.startswith("-->", end) else 4)
            continue
        if top is not None and top[1] != "html" and text.startswith("<![CDATA[", lt):
            # CDATA は、いまの要素が HTML の要素でなければ読む（integration point の中の直下も＝HTML の構文解析の tokenizer の決まり）
            end = text.find("]]>", lt + 9)
            if _sw_lost(text, lt + 9, n if end == -1 else end, deck):
                return (lt, "cdata", ""), ran
            cand = missed(lt, "![CDATA[", lt + 9, n if end == -1 else end)
            if end == -1:
                return (None if ran else cand), ran
            i = end + 3
            continue
        if text.startswith("<!", lt) or text.startswith("<?", lt) or (text.startswith("</", lt) and not _SW_TAG_RE.match(text, lt)
                                                                         and not text.startswith("</>", lt)):
            end = text.find(">", lt + 2)
            if _sw_lost(text, lt + 2, n if end == -1 else end, deck):
                return (lt, "comment", ""), ran
            cand = missed(lt, "", lt + 2, n if end == -1 else end)
            if end == -1:
                return (None if ran else cand), ran
            i = end + 1
            continue
        m = _SW_TAG_RE.match(text, lt)
        if not m:
            i = lt + (3 if text.startswith("</>", lt) else 1)
            continue
        end = _sw_tag_end(text, m.end())
        if end is None:
            if _sw_lost(text, m.end(), n, deck):
                return (lt, "tag", m.group(2).lower()), ran
            cand = missed(lt, m.group(2).lower(), m.end(), n)
            return (None if ran else cand), ran
        stop, self_closing, attrs = end
        if text.find("<", m.end(), stop) != -1:
            if _sw_lost(text, m.end(), stop, deck):
                return (lt, "tag", m.group(2).lower()), ran     # 引用符の閉じていない属性の値が、後ろの行のタグを取り込んだ
            cand = missed(lt, m.group(2).lower(), m.end(), stop)
        name = m.group(2).lower()
        i = stop
        if m.group(1) and name in ("p", "br") and top is not None and top[1] != "html":
            # svg・math の中の </p>・</br> は、開きタグの _FOREIGN_BREAKOUT と同じく svg・math を閉じる（HTML の構文解析の foreign content の決まり）
            while stack and stack[-1][1] != "html" and not stack[-1][2]:
                fcount[stack.pop()[0]] -= 1
                segs.pop()
            continue
        if m.group(1):
            # 閉じタグ。svg・math の中（integration point を含む）では、上から同じ名前の svg・math の要素を探して閉じる。HTML の要素に
            # 当たったら、そこから下は HTML の決まりで探す（svg・math の要素に当たったらそこで止める＝読み飛ばす）
            k = len(stack) - 1
            if not fcount.get(name):
                k = hidx[-1] if hidx else -1      # 上の svg・math の要素に同じ名前は無い
            while k >= 0 and stack[k][1] != "html":
                if stack[k][0] == name:
                    for x in stack[k:]:
                        fcount[x[0]] -= 1
                    del segs[len(segs) - (len(stack) - k):]
                    del stack[k:]
                    break
                k -= 1
            else:
                f = len(stack) - 1 - k          # 上から通り過ぎた svg・math の要素の数
                seg = segs[len(segs) - 1 - f]
                if seg and seg.get(name):
                    while stack[k][0] != name and stack[k][0] != "template":
                        k -= 1
                    if stack[k][0] != name:
                        continue                    # template の外の要素の閉じタグは、template の中では読み飛ばす（template は境界。境界で辿るのを止める）
                    for x in stack[k:]:
                        if x[1] == "html":
                            seg[x[0]] -= 1
                        else:
                            fcount[x[0]] -= 1
                    while hidx and hidx[-1] >= k:
                        hidx.pop()
                    while tmpl and tmpl[-1][2] >= k:
                        tp, tend, _k = tmpl.pop()   # 閉じた template の中身（DOM の外）。一番外側が閉じたときだけ見る（入れ子ごとに見直すと遅い）
                        if not tmpl:
                            if _sw_lost(text, tend, lt, deck):
                                return (tp, "element", "template"), ran
                            cand = missed(tp, "template", tend, lt)
                    del segs[len(segs) - f:]
                    del stack[k:]
            continue
        if foreign and (name in _FOREIGN_BREAKOUT or (name == "font" and ("color" in attrs or "face" in attrs or "size" in attrs))):
            while stack and stack[-1][1] != "html" and not stack[-1][2]:
                fcount[stack.pop()[0]] -= 1
                segs.pop()
            top = stack[-1] if stack else None
            foreign = False
        if top is not None and top[1] == "math" and top[2] and top[0] != "annotation-xml" and name in ("mglyph", "malignmark"):
            foreign = True       # math の mi などの中の mglyph・malignmark は math の要素
        if foreign:
            if name == "script" and cand is None and not ran and _sw_src_board_js(text, m.end() - 1, stop):
                cand = (lt, "load", "script")       # svg・math の script は HTML の script ではないので、board.js は実行されない
            ns = "svg" if name == "svg" else top[1]
            point = ((ns == "svg" and name in ("foreignobject", "desc", "title"))
                     or (ns == "math" and name in ("mi", "mo", "mn", "ms", "mtext"))
                     or (ns == "math" and name == "annotation-xml"
                         and attrs.get("encoding", "").lower() in ("text/html", "application/xhtml+xml")))
            if not self_closing:
                stack.append((name, ns, point))
                segs.append(None)   # 区間の数は、HTML の要素を初めて置いたときに作る（深い svg で空の dict を積まない）
                fcount[name] = fcount.get(name, 0) + 1
            continue
        if name in ("svg", "math"):
            if not self_closing:
                stack.append((name, name, False))
                segs.append(None)
                fcount[name] = fcount.get(name, 0) + 1
            continue
        if name in _SWALLOW_TAGS:
            r = _sw_text_end(text, stop, name)
            if _sw_lost(text, stop, n if r is None else r[0], deck):
                return (lt, ("load" if r is not None and r[1] else "element"), name), ran
            if name == "script" and _sw_src_board_js(text, m.end() - 1, stop):
                if r is not None and not tmpl and _sw_runs(attrs):
                    ran = True                      # 実行される board.js の読み込み（閉じていて、template の中でない）
                elif cand is None and not ran:
                    cand = (lt, "load", "script")   # 閉じていない（文書の終わりまで）か、template の中か、属性で実行されない
            cand = missed(lt, name, stop, n if r is None else r[0])
            if r is None:
                return (None if ran else cand), ran
            i = r[0]
            continue
        if name not in _VOID_TAGS:
            if name == "template":
                tmpl.append((lt, stop, len(stack)))
            hidx.append(len(stack))
            stack.append((name, "html", False))
            if segs[-1] is None:
                segs[-1] = {}
            segs[-1][name] = segs[-1].get(name, 0) + 1


def swallow_text(text, hit):
    """_swallow_open の当たり（hit）を、知らせの文の頭にする（K16・Deck の watcher.log）。行は1から数え、DECK 領域の中ならそう添える。"""
    pos, kind, name = hit
    line = text.count("\n", 0, pos) + 1
    s = text.find(MARKER_START)
    e = text.find(MARKER_END, s) if s != -1 else -1
    where = "%d 行目・DECK 領域の中" % line if s != -1 and e != -1 and s < pos < e else "%d 行目" % line
    if kind == "load":
        what = ("ボードのスクリプトの読み込み（<script src=\"board.js\">）を実行させない、svg・math の中の <![CDATA[" if name == "![CDATA[" else
                "ボードのスクリプトの読み込み（<script src=\"board.js\">）を実行させない <%s>" % name if name else
                "ボードのスクリプトの読み込み（<script src=\"board.js\">）を実行させない HTML のコメントか宣言")
    elif kind == "element" and name == "plaintext":
        what = "<plaintext>（閉じタグを持たない要素。後ろをすべて文字として読む）"
    elif kind == "element" and name == "template":
        what = "後ろの行を中身に取り込む <template>"
    elif kind == "element":
        what = "後ろの行を文字として読む <%s>" % name
    elif kind == "comment":
        what = "後ろの行を取り込む HTML のコメントか宣言"
    elif kind == "cdata":
        what = "svg・math の中の、後ろの行を取り込む <![CDATA["
    else:
        what = "後ろの行を取り込むタグ <%s（> が無いか、属性の値の引用符が閉じていない）" % name
    return "%s（%s）" % (what, where)


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


def _region_text(text, start_re):
    """start_re に当たる開始タグの div を、対応する閉じまで（コメントは潰した写しで数える）。"""
    blanked = "".join(_blank_comments(text.splitlines(keepends=True)))
    m = start_re.search(blanked)
    if not m:
        return ""
    depth = 0
    for t in re.finditer(r"<div\b|</div>", blanked[m.start():]):
        depth += 1 if t.group(0) != "</div>" else -1
        if depth == 0:
            return blanked[m.start():m.start() + t.end()]
    return blanked[m.start():]


def placeholder_regions(text):
    blanked = "".join(_blank_comments(text.splitlines(keepends=True)))
    parts = []
    for rx in (_TITLE_RE, _HEADER_RE, _UPD_TIME_RE):
        m = rx.search(blanked)
        if m:
            parts.append(m.group(0))
    parts.append(_region_text(text, re.compile(r'<div class="progress"')))
    return "\n".join(parts)


def strict_date_ok(txt):
    """ヘッダの日付が YYYY-MM-DD（曜）で読め、曜日が合うか。合えば date、合わなければ None。"""
    m = STRICT_DATE_RE.match(txt or "")
    if not m:
        return None
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return d if WEEKDAY_JA[d.weekday()] == m.group(4) else None


def structure_errors(text):
    """K1〜K3・K16（読んだ板にも当てる。K16 は v1.13）。"""
    lines = text.splitlines(keepends=True)
    errs = []
    if not board_structure_ok(lines):
        errs.append({"code": "K1", "message": "項目の入れ子か閉じタグの欠落があります（タスクの中に別のタスクが入り込んでいる等）。"})
    bal = _div_balance(text)
    if bal != 0:
        errs.append({"code": "K2", "message": "コメントの外の <div と </div> の数が合いません（差 %+d）。" % bal})
    s, e = _marker_counts(text)
    if s != 1 or e != 1 or text.find(MARKER_START) > text.find(MARKER_END):
        errs.append({"code": "K3", "message": "DECK マーカーがちょうど1組（START が END より前）になっていません（START %d / END %d）。" % (s, e)})
    hit, ran = _sw_scan(text)
    if hit and hit[1] == "load":
        errs.append({"code": "K16", "message": "%sがあります。ボードのスクリプト（board.js）の読み込みが実行されないので、"
                     "ポップアップの通知・「ボードの点検」・「書き込み停止中」の知らせも画面に出ません。" % swallow_text(text, hit)})
    elif hit and ran:
        errs.append({"code": "K16", "message": "%sがあります。ブラウザはそこに入る行・見出し・Deck の欄を要素として読まないので、それらが画面から消えます"
                     "（ボードのスクリプトは動くので、ふつうは画面の「ボードの点検」にも出ます）。" % swallow_text(text, hit)})
    elif hit:
        errs.append({"code": "K16", "message": "%sがあります。ブラウザはそこに入る行・見出し・Deck の欄を要素として読まないので、それらが画面から消えます。"
                     "ボードのスクリプト（board.js）を末尾で読む板では、その読み込みも飲み込まれてボードのスクリプトが動かないことがあり、"
                     "そのときはポップアップの通知・「ボードの点検」・「書き込み停止中」の知らせも画面に出ません。" % swallow_text(text, hit)})
    return errs


def _guard_atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".tb-guard-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


def guard_format_ok(board_path):
    """.guard/format.json を無いときだけ作り、版を読む。(知っている版か, 読んだ版) を返す。読めなければ (False, None)。"""
    gdir = os.path.join(os.path.dirname(os.path.abspath(board_path)), GUARD_DIRNAME)
    os.makedirs(os.path.join(gdir, "auth"), exist_ok=True)
    fpath = os.path.join(gdir, "format.json")
    if not os.path.exists(fpath):
        fd, tmp = tempfile.mkstemp(prefix=".tb-guard-", suffix=".tmp", dir=gdir)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps({"v": GUARD_FORMAT_V}).encode("utf-8"))
        try:
            os.link(tmp, fpath)          # 既にあれば失敗する＝上書きしない
        except FileExistsError:
            pass
        except OSError:
            try:
                with open(fpath, "xb") as f:
                    f.write(json.dumps({"v": GUARD_FORMAT_V}).encode("utf-8"))
            except FileExistsError:
                pass
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    for k in range(3):
        try:
            with open(fpath, "rb") as f:
                v = json.loads(f.read().decode("utf-8-sig")).get("v")
            return v == GUARD_FORMAT_V, v
        except (OSError, ValueError, AttributeError):
            time.sleep(0.1)
    # 読めない（壊れている等）は「知らない版」と同じに扱う: 記録は書かず、書き手は板を書いて知らせる（2026-10-30 ユーザー判断）
    return False, None


def guard_write_record(board_path, body, fp, base_fp, writer):
    """書き込みの記録を1件書く（本文 .html → 確定の印 .json の順）。(json のパス, html のパス) を返す。

    書けなければ OSError。format.json の版を知らない・読めないときは書かずに None を返す。
    """
    known, _v = guard_format_ok(board_path)
    if not known:
        return None
    adir = os.path.join(os.path.dirname(os.path.abspath(board_path)), GUARD_DIRNAME, "auth")
    ns = max(time.time_ns(), _guard_last_ns[0] + 1)
    while True:
        # 時計の刻みが粗い（Windows）と、同じプロセスの続けた記録が同じ名前になるので、空くまで 1 ns ずつ進める
        base = "%020d-%d" % (ns, os.getpid())
        html_path = os.path.join(adir, base + ".html")
        json_path = os.path.join(adir, base + ".json")
        if not os.path.exists(html_path) and not os.path.exists(json_path):
            break
        ns += 1
    _guard_last_ns[0] = ns
    _guard_atomic_write(html_path, body)
    try:
        rec = {"v": GUARD_FORMAT_V, "fp": fp, "base_fp": base_fp, "writer": writer, "body": base + ".html"}
        _guard_atomic_write(json_path, json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    except BaseException:
        try:
            os.remove(html_path)
        except OSError:
            pass
        raise
    return json_path, html_path


def guard_remove_record(paths):
    """自分の記録を消す（確定の印 .json → 本文 .html の順）。"""
    if not paths:
        return
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def guard_prune_records(board_path, now_ns=None, max_age_sec=GUARD_RECORD_MAX_AGE_SEC):
    """max_age_sec より古い記録を消す（.json → .html の順）。消した件数を返す。"""
    adir = os.path.join(os.path.dirname(os.path.abspath(board_path)), GUARD_DIRNAME, "auth")
    now_ns = time.time_ns() if now_ns is None else now_ns
    limit = now_ns - int(max_age_sec * 1e9)
    try:
        names = sorted(os.listdir(adir))
    except OSError:
        return 0
    removed = 0
    for name in names:
        m = re.match(r"^(\d{20})-(\d+)\.json$", name)
        if not m or int(m.group(1)) >= limit:
            continue
        guard_remove_record([os.path.join(adir, name), os.path.join(adir, name[:-5] + ".html")])
        removed += 1
    for name in names:
        m = re.match(r"^(\d{20})-(\d+)\.html$", name)
        if m and int(m.group(1)) < limit and not os.path.exists(os.path.join(adir, name[:-5] + ".json")):
            guard_remove_record([os.path.join(adir, name)])
    return removed


def _write_tmp(dir_name, data):
    fd, tmp = tempfile.mkstemp(prefix=".tb-edit-", suffix=".tmp", dir=dir_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        _rm(tmp)          # 書きかけの一時ファイルを残さない
        raise
    return tmp


def _rm(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def history_dir(board_path):
    return os.path.join(os.path.dirname(os.path.abspath(board_path)), HISTORY_DIRNAME)


def create_history_file(board_path, stem, data):
    """history/<stem>.html を排他的に作る（既にあれば <stem>-2.html, -3 … と進める）。作ったパスを返す。

    一時ファイルに書いてから os.link で付ける（既にある名前には付かない＝他の書き手の退避を上書きしない）。
    os.link が使えないファイルシステムでは open(…, "xb") で直接書く。一時ファイルはどの場合も消す。
    """
    hdir = history_dir(board_path)
    os.makedirs(hdir, exist_ok=True)
    tmp = _write_tmp(hdir, data)
    try:
        k = 1
        while True:
            path = os.path.join(hdir, stem + (".html" if k == 1 else "-%d.html" % k))
            try:
                os.link(tmp, path)
                return path
            except FileExistsError:
                k += 1
                continue
            except OSError:
                try:
                    f = open(path, "xb")
                except FileExistsError:
                    k += 1
                    continue
                try:
                    with f:
                        f.write(data)
                except BaseException:
                    _rm(path)     # 自分が作った（書きかけの）ファイルだけを消す
                    raise
                return path
    finally:
        _rm(tmp)


# ================================================================ ここから guard.py 自身のもの

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD_EDIT = os.path.join(SKILL_DIR, "scripts", "board_edit.py")
BOM = b"\xef\xbb\xbf"

L1_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
L3_TOOLS = L1_TOOLS + ("Bash", "PowerShell")
RESCAN_EVENTS = ("UserPromptSubmit", "SessionStart")

GRACE_SEC = 10                 # 記録を鎖に入れる猶予（控えの時刻からさかのぼる秒数）
PRE_MAX_AGE_SEC = 24 * 3600    # これより古い控えは正規かどうかを決めない（知らせるだけ）・掃除で消す
RESCAN_REVERT_SEC = 10 * 60    # 拾い直しで戻すのは、控えからこの秒数以内で崩れているときだけ
LOG_MAX_BYTES = 1024 * 1024
READ_RETRIES = 3
READ_RETRY_SEC = 0.1
REPLACE_RETRIES = 5
REPLACE_RETRY_SEC = 0.2
REREAD_ATTEMPTS = 3
DECK_MIN_VERSION = (2, 6)
_DECK_VERSION_RE = re.compile(r"Deck v(\d+)\.(\d+)")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]")

# 試験用のフック（本番では None）
_HOOK_AFTER_READ = None        # 比べるときに板を読んだ後・記録を列挙する前に呼ぶ（引数なし）
_HOOK_BEFORE_REREAD = None     # 戻すときに置き換える直前の読み直しの前に呼ぶ（引数なし）


class ReadFail(Exception):
    pass


# ---------------------------------------------------------------- 置き場

def data_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "today-board")


def board_file():
    return os.path.join(data_dir(), "board.html")


def guard_dir():
    return os.path.join(data_dir(), GUARD_DIRNAME)


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def _safe_id(s):
    s = _SAFE_ID_RE.sub("_", str(s or ""))
    return s if s.strip("._") else ""


# ---------------------------------------------------------------- hook.log

def log(event, msg):
    """.guard/hook.log に1行残す（.guard/ が無ければ残さない）。stdout・stderr には何も書かない。"""
    gd = guard_dir()
    if not os.path.isdir(gd):
        return
    path = os.path.join(gd, "hook.log")
    line = "%s guard v%s %s %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), VERSION, event,
                                     msg.replace("\r", " ").replace("\n", " "))
    try:
        if os.path.getsize(path) > LOG_MAX_BYTES:
            with open(path, "rb") as f:
                f.seek(-LOG_MAX_BYTES // 2, os.SEEK_END)
                tail = f.read()
            tail = tail[tail.find(b"\n") + 1:]
            _guard_atomic_write(path, tail)
    except OSError:
        pass
    try:
        with open(path, "ab") as f:
            f.write(line.encode("utf-8"))
    except OSError:
        pass


# ---------------------------------------------------------------- 読み取り

def read_bytes(path):
    """読めればバイト列、無ければ None。開いてすぐ閉じる。PermissionError 等は 0.1 秒あけて最大3回やり直し、使い切れば ReadFail。"""
    for k in range(READ_RETRIES + 1):
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except OSError as e:
            if k == READ_RETRIES:
                raise ReadFail("%s: %s" % (os.path.basename(path), e))
            time.sleep(READ_RETRY_SEC)


def decode(raw):
    """バイト列 → 本文（BOM を除く）。UTF-8 として読めなければ None。"""
    try:
        return (raw[len(BOM):] if raw.startswith(BOM) else raw).decode("utf-8")
    except UnicodeDecodeError:
        return None


def shape_codes(text):
    """K1／K3／K5／K16／K17 のうち当たるもの（板の形の悪さ。K16・K17 は v1.1。K17＝実行される board.js の読み込みが無い・K16 に当たらないときだけ）。"""
    codes = set()
    if not board_structure_ok(text.splitlines(keepends=True)):
        codes.add("K1")
    s, e = _marker_counts(text)
    if s != 1 or e != 1 or text.find(MARKER_START) > text.find(MARKER_END):
        codes.add("K3")
    if PLACEHOLDER_RE.search(placeholder_regions(text)):
        codes.add("K5")
    hit, ran = _sw_scan(text)
    if hit:
        codes.add("K16")
    elif not ran:
        codes.add("K17")         # 実行される board.js の読み込みが無い（控えにあって今の板に無ければ、悪くなったとして戻す＝v1.1）
    return codes


def describe(raw):
    """板のバイト列 → (指紋, 形の悪さの集合)。

    UTF-8 として読めない板の指紋は "raw:<sha256>"（記録の指紋とは突き合わない）、形の悪さは K1／K3／K5／K16／K17／UTF8 のすべて。
    板が無い（raw が None）ときは (None, 同じすべて)。
    """
    worst = {"K1", "K3", "K5", "K16", "K17", "UTF8"}
    if raw is None:
        return None, set(worst)
    text = decode(raw)
    if text is None:
        return "raw:" + hashlib.sha256(raw).hexdigest(), set(worst)
    return hand_fingerprint(text), shape_codes(text)


def board_date_iso(raw):
    """history/ の名前に使う板の日付（board_edit.py・Deck と同じ: ヘッダの日付、読めなければ今日）。"""
    today = date.today()
    text = decode(raw) if raw is not None else None
    bd = parse_board_date(board_header_date_text(text), today) if text is not None else None
    return (bd or today).isoformat()


# ---------------------------------------------------------------- .guard/ の版

def format_state():
    """.guard/format.json を読むだけ（作らない）。"ok"（v1・無い）/ "unknown"（知らない版）/ "corrupt"（読めない）。"""
    path = os.path.join(guard_dir(), "format.json")
    try:
        raw = read_bytes(path)
    except ReadFail:
        return "corrupt"
    if raw is None:
        return "ok"          # 書き手はまだ記録を書いていない（記録を書く前に必ず作る）
    try:
        v = json.loads(raw.decode("utf-8-sig")).get("v")
    except (ValueError, AttributeError):
        return "corrupt"
    return "ok" if v == GUARD_FORMAT_V else "unknown"


def deck_version_ok():
    """稼働体の deck_watcher.py の docstring の版が v2.6 以上か。Deck が入っていなければ True（D&D を書く Deck が無い）。"""
    path = os.path.join(data_dir(), "deck", "deck_watcher.py")
    try:
        with open(path, "rb") as f:
            head = f.read(4096).decode("utf-8", "replace")
    except FileNotFoundError:
        return True
    except OSError:
        return False
    m = _DECK_VERSION_RE.search(head)
    if not m:
        return False
    return (int(m.group(1)), int(m.group(2))) >= DECK_MIN_VERSION


# ---------------------------------------------------------------- 控え

def pre_paths(sid, tuid):
    base = os.path.join(guard_dir(), "pre", sid, tuid)
    return base + ".json", base + ".html"


def take_snapshot(sid, tuid, tool_name):
    board = board_file()
    if not os.path.isfile(board):
        return
    now_ns = time.time_ns()
    try:
        raw = read_bytes(board)
    except ReadFail as e:
        log("PreToolUse", "板を読めないため控えを取りませんでした（%s・%s）" % (tool_name, e))
        return
    if raw is None:
        return
    fp, codes = describe(raw)
    jpath, hpath = pre_paths(sid, tuid)
    os.makedirs(os.path.dirname(jpath), exist_ok=True)
    _guard_atomic_write(hpath, raw)
    try:
        info = {"v": GUARD_FORMAT_V, "fp": fp, "k": sorted(codes), "time_ns": now_ns, "tool_name": tool_name}
        _guard_atomic_write(jpath, json.dumps(info, ensure_ascii=False).encode("utf-8"))
    except BaseException:
        _rm(hpath)
        raise


def load_snapshot(jpath):
    """控えを読む。(情報, 本文) か、読めなければ (None, None)。"""
    try:
        with open(jpath, "rb") as f:
            info = json.loads(f.read().decode("utf-8"))
        if not isinstance(info, dict):
            return None, None
        with open(jpath[:-5] + ".html", "rb") as f:
            body = f.read()
        return info, body
    except (OSError, ValueError):
        return None, None


def remove_snapshot(jpath):
    guard_remove_record([jpath, jpath[:-5] + ".html"])     # .json → .html の順
    try:
        os.rmdir(os.path.dirname(jpath))                     # 空になったセッションのフォルダ
    except OSError:
        pass


def prune_snapshots(now_ns=None, max_age_sec=PRE_MAX_AGE_SEC):
    """max_age_sec より古い控えを消す。消した件数を返す。"""
    pre = os.path.join(guard_dir(), "pre")
    now_ns = time.time_ns() if now_ns is None else now_ns
    limit = now_ns - int(max_age_sec * 1e9)
    removed = 0
    try:
        sids = os.listdir(pre)
    except OSError:
        return 0
    for sid in sids:
        sdir = os.path.join(pre, sid)
        try:
            names = os.listdir(sdir)
        except OSError:
            continue
        for name in names:
            p = os.path.join(sdir, name)
            try:
                old = os.path.getmtime(p) * 1e9 < limit
            except OSError:
                continue
            if name.endswith(".json") and old:
                info, _b = load_snapshot(p)
                t = info.get("time_ns") if info else None
                if isinstance(t, int) and t >= limit:
                    continue
                remove_snapshot(p)
                removed += 1
            elif name.endswith(".html") and old and not os.path.exists(p[:-5] + ".json"):
                _rm(p)
        try:
            os.rmdir(sdir)
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------- 記録の鎖

def list_records(since_ns):
    """.guard/auth/ の記録のうち、時刻が since_ns より新しいもの（名前の順＝時刻の順）。.json のあるものだけ。"""
    adir = os.path.join(guard_dir(), "auth")
    try:
        names = sorted(os.listdir(adir))
    except OSError:
        return []
    out = []
    for name in names:
        m = re.match(r"^(\d{20})-(\d+)\.json$", name)
        if not m or int(m.group(1)) <= since_ns:
            continue
        try:
            with open(os.path.join(adir, name), "rb") as f:
                rec = json.loads(f.read().decode("utf-8"))
            if not isinstance(rec, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as e:
            log("record", "記録 %s を読めませんでした（%s）" % (name, e))
            continue
        body = os.path.basename(str(rec.get("body") or name[:-5] + ".html"))
        out.append({"name": name, "v": rec.get("v"), "fp": rec.get("fp"), "base_fp": rec.get("base_fp"),
                    "writer": rec.get("writer"), "body": os.path.join(adir, body)})
    return out


def observe(since_ns):
    """今の板を読み、その後で記録を列挙する（この順でなければならない。逆の順では、列挙と読む間に入った正規の書き込みを
    正規と認められずに戻してしまう）。(板のバイト列 or None, 記録の一覧)。"""
    raw = read_bytes(board_file())
    if _HOOK_AFTER_READ is not None:
        _HOOK_AFTER_READ()
    return raw, list_records(since_ns)


def build_chain(seed, records):
    """辿れる指紋の集合 R と、鎖に入った記録（base_fp が R にあるもの）の一覧。"""
    R = set(seed)
    members = []
    changed = True
    while changed:
        changed = False
        for r in records:
            if r in members or r["base_fp"] not in R:
                continue
            members.append(r)
            changed = True
            if r["fp"] not in R:
                R.add(r["fp"])
    members.sort(key=lambda r: r["name"])
    return R, members


# ---------------------------------------------------------------- 知らせの文

def _rel(path):
    return HISTORY_DIRNAME + "/" + os.path.basename(path)


def restore_hint(rel, saved_raw):
    """退避した版を restore で戻せるか（board_edit.py の restore が受ける条件）に応じた後半の文。"""
    why = None
    try:
        cur_raw = read_bytes(board_file())
    except ReadFail:
        cur_raw = None
    cur = decode(cur_raw) if cur_raw is not None else None
    saved = decode(saved_raw)
    if cur is None:
        why = "いまの board.html が無いか、UTF-8 として読めないため"
    elif strict_date_ok(board_header_date_text(cur)) is None:
        why = "いまの board.html のヘッダの日付が読めないため"
    elif saved is None:
        why = "退避した版が UTF-8 として読めないため"
    elif board_header_date_text(saved) != board_header_date_text(cur):
        why = "退避した版のヘッダの日付がいまの板と違うため"
    elif structure_errors(saved) or PLACEHOLDER_RE.search(placeholder_regions(saved)):
        why = "退避した版の形が崩れているため"
    if why:
        return ("この版は restore では戻せません（%s）。ボードを書かずに、退避の所在（%s）を利用者に伝えてください。" % (why, rel))
    return ("戻すときは、%s restore --from %s を --confirmed なしで実行して差分を利用者に見せ、"
            "利用者が確かめてから --confirmed を付けてください。" % (BOARD_EDIT, rel))


NOTIFY_REASON = {
    "old": "このツールの前に控えた版が24時間より古いため、書き換えが正規のものか確かめられず、元に戻していません。",
    "deck": "入っている Deck（~/.claude/today-board/deck/deck_watcher.py）の版が v2.6 未満か、版を読み取れないため、正規の書き換えと見分けられず、元に戻していません。ユーザーに、Deck を新しくする（Windows では setup.bat をもう一度実行する）よう伝えてください（setup.bat は Claude が実行しない）。",
    "unknown": "ガードの版が古いため確かめられず、元に戻していません。直前のツールが board_edit.py の実行だった場合も、この知らせが出ることがあります（この状態では board_edit.py の書き込みを正規と確かめられないため）。ユーザーに、スキルを入れ直す（Windows では setup.bat をもう一度実行する）よう伝えてください（setup.bat は Claude が実行しない）。",
    "corrupt": ".guard/format.json が読めないため確かめられず、元に戻していません。直前のツールが board_edit.py の実行だった場合も、この知らせが出ることがあります（この状態では board_edit.py の書き込みを正規と確かめられないため）。この出力をユーザーに伝えてください。",
}


def notify_text(kind, mode, rel, saved_raw):
    if mode == "post":
        head = "このツールの実行中に、board.html が board_edit.py を通さずに書き換えられた可能性があります。"
        what = "ツールの前の版"
    else:
        head = ("中断したツールの実行中か、その後に、board.html が board_edit.py を通さずに書き換えられていました。"
                "利用者が自分で編集したものかもしれません。")
        what = "中断の前の版"
    reason = NOTIFY_REASON.get(kind, "")
    if rel is None:
        return head + reason + "%sを history/ に残せませんでした。この出力を利用者に伝えてください。" % what
    return head + reason + "%sを %s に残しました。" % (what, rel) + restore_hint(rel, saved_raw)


def revert_text(mode, rel):
    saved = "（退避: %s）" % rel if rel else "（ツールの実行中に board.html が消えていました）"
    if mode == "post":
        head = "board.html が board_edit.py を通さずに書き換えられたため、元に戻しました%s。" % saved
    else:
        head = ("中断したツールの実行中か、その後に、board.html が board_edit.py を通さずに崩れた形に書き換えられていたため、"
                "中断の前の版へ戻しました%s。" % saved)
    return head + "ボードの操作は %s で行ってください。" % BOARD_EDIT


def failed_text(mode, why, rel, saved_raw):
    head = ("このツールの実行中に" if mode == "post" else "中断したツールの実行中か、その後に、")
    what = "ツールの前の版" if mode == "post" else "中断の前の版"
    text = (head + "board.html が board_edit.py を通さずに書き換えられましたが、元に戻せませんでした（%s）。"
            "%s status で板の状態を確かめ、崩れていればこの出力を利用者に伝えてください。" % (why, BOARD_EDIT))
    if rel is None:
        return text + "%sを history/ に残せませんでした。" % what
    return text + "%sを %s に残しました。" % (what, rel) + restore_hint(rel, saved_raw)


# ---------------------------------------------------------------- 戻す・知らせる

def save_snapshot_body(info, body, kind_name):
    """控えの本文を history/board-<控えの日付>-<kind_name>-<時刻>.html へ退避する。退避したパス、失敗なら None。"""
    try:
        return create_history_file(board_file(), "board-%s-%s-%s" % (
            board_date_iso(body), kind_name, datetime.now().strftime("%H%M%S")), body)
    except OSError as e:
        log("history", "控えの本文を history/ へ退避できませんでした（%s）" % e)
        return None


def try_revert(raw_now, info, body, snap_codes, members):
    """戻す。("done", 退避の相対パス or None) / ("changed",)（読み直しで変化＝最初からやり直す）/ ("failed", 理由)。

    foreign の退避は "changed" でも消さない（やり直す前の巡で見た版も、正規でない書き込みの版のため）。
    """
    board = board_file()
    target = body
    for r in reversed(members):
        try:
            with open(r["body"], "rb") as f:
                cand = f.read()
        except OSError:
            continue          # 本文の無い記録は鎖には使うが、戻し先には選ばない
        fp_c, codes_c = describe(cand)
        if fp_c == r["fp"] and codes_c <= snap_codes:
            target = cand
            break
    cur_fp, _c = describe(raw_now)
    tgt_fp, _t = describe(target)
    saved = record = tmp = None
    try:
        if raw_now is not None:
            saved = create_history_file(board, "board-%s-foreign-%s" % (
                board_date_iso(raw_now), datetime.now().strftime("%H%M%S")), raw_now)
        if tgt_fp != cur_fp:
            record = guard_write_record(board, target, tgt_fp, cur_fp, "guard")
            if record is None:
                _rm(saved)
                return ("failed", ".guard/format.json の版が変わったため")
        tmp = _write_tmp(os.path.dirname(board), target)
        if _HOOK_BEFORE_REREAD is not None:
            _HOOK_BEFORE_REREAD()
        if read_bytes(board) != raw_now:
            guard_remove_record(record)
            return ("changed",)          # foreign の退避は残す（その版も正規でない書き込みだったため）
        for k in range(REPLACE_RETRIES + 1):
            try:
                os.replace(tmp, board)
                tmp = None
                break
            except PermissionError:
                if k == REPLACE_RETRIES:
                    raise
                time.sleep(REPLACE_RETRY_SEC)
                if read_bytes(board) != raw_now:
                    guard_remove_record(record)
                    return ("changed",)
        return ("done", _rel(saved) if saved else None)
    except (OSError, ReadFail) as e:
        guard_remove_record(record)
        _rm(saved)
        log("revert", "戻せませんでした（%s）" % e)
        return ("failed", "書き込みに失敗したため: %s" % e)
    finally:
        _rm(tmp)


def handle_snapshot(jpath, mode, now_ns=None):
    """控え1件を比べて扱う（mode は "post" か "rescan"）。Claude へ返す文か None。

    控えは、扱いが済んだら消す（知らせるだけの経路では、控えの本文を history/ へ退避できたときだけ消す）。
    """
    info, body = load_snapshot(jpath)
    if info is None:
        log(mode, "控え %s を読めないため消しました（本文は24時間の掃除に任せます）" % os.path.basename(jpath))
        _rm(jpath)
        return None
    now_ns = time.time_ns() if now_ns is None else now_ns
    snap_ns = info.get("time_ns") if isinstance(info.get("time_ns"), int) else 0
    age = (now_ns - snap_ns) / 1e9
    snap_known = info.get("v") == GUARD_FORMAT_V
    snap_fp, snap_codes = describe(body)     # 控えの指紋と形は本文から求め直す（.json の fp は記録のため）
    seed = {snap_fp} | ({None} if "UTF8" in snap_codes else set())
    fmt = format_state()
    msg = failed = None
    done = False
    for attempt in range(REREAD_ATTEMPTS):
        try:
            raw_now, records = observe(snap_ns - GRACE_SEC * 10 ** 9)
        except ReadFail as e:
            log(mode, "板を読めないため比べられませんでした（%s）。控えは残します" % e)
            return None
        cur_fp, cur_codes = describe(raw_now)
        if raw_now == body or (raw_now is not None and cur_fp == snap_fp and cur_codes <= snap_codes):
            done = True          # 変わっていないか、指紋の外だけが変わった（Deck のふだんの書き込み等）
            break
        kind = None
        if not snap_known or fmt == "unknown" or any(r["v"] != GUARD_FORMAT_V for r in records):
            kind = "unknown"
        elif fmt == "corrupt":
            kind = "corrupt"
        elif mode == "post" and age > PRE_MAX_AGE_SEC:
            kind = "old"
        if kind is None:
            R, members = build_chain(seed, records)
            if raw_now is None and not os.path.isdir(guard_dir()):
                done = True          # データを消した（.guard/ ごと無い）
                break
            if raw_now is not None and cur_fp in R and cur_codes <= snap_codes:
                done = True          # 正規
                break
            worse = raw_now is None or not (cur_codes <= snap_codes)
            if mode == "rescan" and (age > RESCAN_REVERT_SEC or not worse):
                kind = "interrupt"
            elif not deck_version_ok():
                kind = "deck"
        if kind is not None:
            if not snap_known:
                log(mode, "控えの版を知らないため知らせるだけにしました（退避はせず、本文は24時間の掃除に任せます）")
                _rm(jpath)
                return notify_text(kind, mode, None, body).replace(
                    "history/ に残せませんでした", "history/ に残していません（控えの形式を知らないため）")
            saved = save_snapshot_body(info, body, "before-tool" if mode == "post" else "before-interrupt")
            if saved is None:
                return notify_text(kind, mode, None, body)       # 控えは消さない（次の拾い直しに回す）
            log(mode, "知らせるだけ（%s）。控えの本文を %s へ退避しました" % (kind, _rel(saved)))
            msg = notify_text(kind, mode, _rel(saved), body)
            done = True
            break
        res = try_revert(raw_now, info, body, snap_codes, members)
        if res[0] == "changed":
            continue
        if res[0] == "done":
            log(mode, "正規でない書き換えを戻しました（退避: %s）" % (res[1] or "なし・板が消えていた"))
            msg = revert_text(mode, res[1])
            done = True
            break
        failed = res[1]
        break
    else:
        log(mode, "戻す間に別の書き手が %d 回書き込んだため戻せませんでした" % REREAD_ATTEMPTS)
        failed = "戻す間に別の書き手が書き込み続けたため"
    if failed is not None:
        # 戻せなかった: 控えの本文を退避し、退避できたときだけ控えを消す（できなければ次の拾い直しに回す）
        saved = save_snapshot_body(info, body, "before-tool" if mode == "post" else "before-interrupt")
        if saved is None:
            return failed_text(mode, failed, None, body)
        log(mode, "戻せなかったため、控えの本文を %s へ退避しました" % _rel(saved))
        remove_snapshot(jpath)
        return failed_text(mode, failed, _rel(saved), body)
    remove_snapshot(jpath)
    return msg


# ---------------------------------------------------------------- L1

def state_board_path():
    try:
        raw = read_bytes(os.path.join(data_dir(), "state.json"))
        if raw is None:
            return None
        st = json.loads(raw.decode("utf-8-sig"))
    except (ReadFail, ValueError, AttributeError):
        return None
    if isinstance(st, dict) and st.get("mode") == "local" and isinstance(st.get("file_path"), str) and st["file_path"]:
        return st["file_path"]
    return None


def protected_kind(path, cwd):
    """守る対象なら "board" / ".guard" / "history"、そうでなければ None。"""
    if not isinstance(path, str) or not path.strip():
        return None
    p = os.path.expanduser(path.strip())
    if not os.path.isabs(p):
        p = os.path.join(cwd if isinstance(cwd, str) and cwd else os.getcwd(), p)
    n = _norm(p)
    d = data_dir()
    boards = [os.path.join(d, "board.html"), os.path.join(d, "board.new.html")]
    sp = state_board_path()
    if sp:
        boards.append(sp)
    if n in [_norm(b) for b in boards]:
        return "board"
    for sub in (GUARD_DIRNAME, HISTORY_DIRNAME):
        base = _norm(os.path.join(d, sub))
        if n == base or n.startswith(base.rstrip(os.sep) + os.sep):
            return sub
    return None


DENY_TEXT = {
    "board": ("ボードのファイル（board.html・board.new.html・state.json の file_path が指すファイル）は board_edit.py 以外で書き換えないでください。Write・Edit はこのとおり止めます。"
              "Bash・PowerShell など別の手段でも書かないでください（ボードの保護があとから確かめるのは、既定の board.html のタスクの行・見出し・ヘッダの日付と、形の一部だけです。"
              "知らせが無くても、書いてよいという意味ではありません）。"
              "%s で操作してください（使い方は today-board スキルの SKILL.md「ボードの書き方」）。"
              "SKILL.md にその節が無いか、このスクリプトが無いときは、ボードを書かずに、この出力をユーザーに伝えてください。"),
    HISTORY_DIRNAME: ("~/.claude/today-board/history/ はボードの退避の置き場です。Claude はここに書かないでください"
                      "（Write・Edit はこのとおり止めます。Bash・PowerShell など別の手段でも書かないでください）。"
                      "版を戻すときは %s の restore を使ってください（使い方は today-board スキルの SKILL.md「ボードの書き方」）。"
                      "SKILL.md にその節が無いか、このスクリプトが無いときは、ボードを書かずに、この出力をユーザーに伝えてください。"),
    GUARD_DIRNAME: ("~/.claude/today-board/.guard/ はボードの保護が使う記録の置き場です。Claude はここに書かないでください"
                    "（Write・Edit はこのとおり止めます。Bash・PowerShell など別の手段でも書かないでください）。"
                    "ボードの操作は %s で行ってください（使い方は today-board スキルの SKILL.md「ボードの書き方」）。"
                    "SKILL.md にその節が無いか、このスクリプトが無いときは、ボードを書かずに、この出力をユーザーに伝えてください。"),
}


# ---------------------------------------------------------------- イベント

def on_pre(d):
    tool = d.get("tool_name")
    if tool not in L3_TOOLS:
        return None
    if tool in L1_TOOLS:
        ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
        target = ti.get("notebook_path") if tool == "NotebookEdit" else ti.get("file_path")
        if target is None:
            target = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
        kind = protected_kind(target, d.get("cwd"))
        if kind:
            log("PreToolUse", "deny %s %s" % (tool, target))
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": DENY_TEXT[kind] % BOARD_EDIT}}
    if not os.path.isfile(board_file()):
        return None
    try:
        prune_snapshots()
        guard_prune_records(board_file())
    except OSError as e:
        log("PreToolUse", "掃除に失敗しました（%s）" % e)
    sid, tuid = _safe_id(d.get("session_id")), _safe_id(d.get("tool_use_id"))
    if not sid or not tuid:
        log("PreToolUse", "session_id か tool_use_id が無いため控えを取りませんでした（%s）" % tool)
        return None
    take_snapshot(sid, tuid, tool)
    return None


def on_post(d):
    if d.get("tool_name") not in L3_TOOLS:
        return None
    sid, tuid = _safe_id(d.get("session_id")), _safe_id(d.get("tool_use_id"))
    if not sid or not tuid:
        return None
    jpath, _h = pre_paths(sid, tuid)
    if not os.path.exists(jpath):
        return None
    msg = handle_snapshot(jpath, "post")
    if msg:
        return {"decision": "block", "reason": msg}
    return None


def on_rescan(d, event):
    sid = _safe_id(d.get("session_id"))
    if not sid:
        return None
    sdir = os.path.join(guard_dir(), "pre", sid)
    if not os.path.isdir(sdir):
        return None
    try:
        prune_snapshots()
    except OSError as e:
        log(event, "掃除に失敗しました（%s）" % e)
    try:
        names = [n for n in os.listdir(sdir) if n.endswith(".json")]
    except OSError:
        return None
    snaps = []
    for n in names:
        info, _b = load_snapshot(os.path.join(sdir, n))
        t = info.get("time_ns") if info and isinstance(info.get("time_ns"), int) else 0
        snaps.append((t, n))
    msgs = []
    for _t, n in sorted(snaps):
        m = handle_snapshot(os.path.join(sdir, n), "rescan")
        if m:
            msgs.append(m)
    if not msgs:
        return None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n\n".join(msgs)}}


def dispatch(d):
    if not isinstance(d, dict):
        return None
    event = d.get("hook_event_name")
    if event == "PreToolUse":
        return on_pre(d)
    if event in ("PostToolUse", "PostToolUseFailure"):
        return on_post(d)
    if event in RESCAN_EVENTS:
        return on_rescan(d, event)
    return None          # 知らないイベント（過去・将来の登録から呼ばれた）は何もしない


def main():
    out = None
    try:
        raw = sys.stdin.buffer.read()
        d = json.loads(raw.decode("utf-8-sig")) if raw.strip() else None
        out = dispatch(d)
    except BaseException as e:      # 何が起きてもツールを止めない（終了コード 0・出力なし）
        out = None
        try:
            log("error", "%s: %s" % (type(e).__name__, e))
        except BaseException:
            pass
    if out is not None:
        try:
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=True).encode("ascii"))
            sys.stdout.buffer.flush()
        except BaseException:
            pass


if __name__ == "__main__":
    main()
