#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_edit.py v1.0 — きょうのボード（board.html）を書き換える専用のスクリプト。

Claude は board.html を直接書かず、このスクリプトに操作を渡す。スクリプトが HTML を機械で書き換え、
書く前に出来上がりの形を検査し（K1〜K9 に当たれば書かない・K11・K12 は書いて警告する）、
書く前に .guard/auth/ へ書き込みの記録を残してから、一時ファイル→os.replace で置き換える。
置き換える直前に板を読み直し、読んだときと違えば（ほかの書き手が書いた）記録を消して最初からやり直す。
create は置き換える前の板を history/board-<日付>-before-create-<時刻>.html に、restore は戻す前の板を
…-before-restore-… に残す。config.json・state.json は読むだけで書かない。

操作: status / create / add / set-chip / edit / set-crit / set-time / move / remove / restore
使い方は `board_edit.py --help` と `board_edit.py <操作> --help`。

- Python 3 標準ライブラリのみ・単一ファイル（Deck と同じ制約）
- 外部ネットワーク通信はしない
- 「Deck の写し」と書いた関数・定数は deck/deck_watcher.py からそのまま写したもの。
  ボードの読み方（項目・セクションの走査、指紋、進捗の数え方、日付の読み方）を Deck と揃えるため。
  変えるときは Deck と同時に変え、試験（tests/test_board_edit.py の T-P）で一致を確かめる
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime

VERSION = "1.0"

# ================================================================ Deck の写し（定数）

MARKER_START = "<!-- DECK:AUTO:START -->"
MARKER_END = "<!-- DECK:AUTO:END -->"
MOVABLE_SECTIONS = ("今日の予定", "今日中", "明日以降")  # D&D 移動の対象セクション
_SECTION_LABEL_RE = re.compile(r'<div class="section-label">(.*?)</div>')
_CLASS_TAG_RE = re.compile(r'<(\w+)\b[^>]*?\bclass="([^"]*)"[^>]*>')
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_CHIP_TOKEN_RE = re.compile(r'class="chip[" ]')  # class="chips"（コンテナ）を誤カウントしない
_CHIP_DONE_RE = re.compile(
    r'<span\b[^>]*?\bclass="(?=(?:[^"]*\s)?chip(?:\s|"))(?=(?:[^"]*\s)?done(?:\s|"))[^"]*"')
_ITEM_CLASS_RE = re.compile(r'(<div\s+class=")([^"]*)(")')
_ANY_CLASS_TAG_RE = re.compile(r'(<\w+\b[^>]*?\bclass=")([^"]*)(")')
CANON_SECTIONS = ("今日の予定", "今日中", "ルーチンタスク", "明日以降")
WEEKDAY_JA = "月火水木金土日"    # date.weekday() の 0=月 に合わせる
_HEADER_RE = re.compile(r"<header\b.*?</header>", re.S)
_TITLE_RE = re.compile(r"(<title>)(.*?)(</title>)", re.S)
_UPD_TIME_RE = re.compile(r'(<span id="upd-time"[^>]*>)(.*?)(</span>)', re.S)
_ITEM_OPEN_RE = re.compile(r'(<div class=")(item\b[^"]*)(")([^>]*)>')
_TIME_OPEN_RE = re.compile(r'<(\w+)\b[^>]*?\bclass="(?:[^"]*\s)?time(?:\s[^"]*)?"[^>]*>')
_FOOTER_LINE_RE = re.compile(r"^[ \t]*<footer\b")


# ================================================================ Deck の写し（関数）

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


def _canon_label(label):
    for name in CANON_SECTIONS:
        if label.startswith(name):
            return name
    return None


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


# ================================================================ ここから board_edit.py 自身のもの

BOM = b"\xef\xbb\xbf"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(SKILL_DIR, "assets", "board-template.html")
ASSET_NAMES = ("board.css", "board.js", "cat.png")
DEFAULT_BOARD = os.path.join(os.path.expanduser("~"), ".claude", "today-board", "board.html")
HISTORY_DIRNAME = "history"
OPS_DIRNAME = "ops"

STATUS_TOKENS = ("done", "active", "pending", "hold")
CHIP_VALUES = ("done", "active", "pending", "wait", "hold", "none")
CHIP_LABELS = {"done": "済", "active": "進行中", "pending": "未", "wait": "条件待ち", "hold": "保留"}
CHIP_CLASS = {"done": "done", "active": "active", "pending": "pending", "wait": "pending", "hold": "hold"}
RESERVED_SECTIONS = ("監視ねこ", "全セッション")
TOMORROW = "明日以降"

PLACEHOLDER_RE = re.compile(r"\{\{\s*[A-Za-z0-9_]+\s*\}\}")
STRICT_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})（([月火水木金土日])）$")
HM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
SPAN_RE = re.compile(r'<span\b[^>]*?\bclass="([^"]*)"[^>]*>([^<]*)</span>')
CHIPS_DIV_RE = re.compile(r'<div class="chips"[^>]*>(.*?)</div>', re.S)
PROGRESS_LABEL_RE = re.compile(r"(\d+)\s*/\s*(\d+) 完了")
BAR_WIDTH_RE = re.compile(r"width:\s*(\d+(?:\.\d+)?)%")
# 正式名に似ているのに正式名でない見出し（board.js の renderBoardCheck の ODD_RES と同じ形）
_TAIL = r"(\s*[（(].*)?$"
ODD_SECTION_RES = (
    re.compile(r"^(本日|きょう|今日)の?(予定|中|タスク|やること)" + _TAIL),
    re.compile(r"^(明日|あした)(の予定|以降|から)?" + _TAIL),
    re.compile(r"^ルー(チ|ティ)ン(タスク|ワーク)?" + _TAIL),
)
RESTORE_NAME_RE = re.compile(
    r"^board-(\d{4}-\d{2}-\d{2})-(lastgood|before-interrupt|before-tool|before-create)-(\d{6})(?:-\d+)?\.html$")

# 試験用のフック（本番では None）。置き換える直前の読み直しの前に呼ぶ（attempt, record_paths）
_HOOK_BEFORE_REREAD = None
# 試験用のフック（本番では None）。history/ へ退避を書く直前に呼ぶ（extra_writes）
_HOOK_BEFORE_EXTRA = None
REPLACE_RETRIES = 5          # os.replace が PermissionError のときのやり直しの回数
REPLACE_RETRY_SEC = 0.2
REREAD_ATTEMPTS = 3          # 読み直しで他の書き込みを見つけたときに、最初からやり直す回数の上限
_last_replace_tries = [0]    # 直近の書き込みで os.replace を試した回数（試験で見る）


class OpError(Exception):
    """操作を拒否した（書かない）。msg は Claude に向けた日本語の理由と次の手。"""

    def __init__(self, msg, **extra):
        Exception.__init__(self, msg)
        self.msg = msg
        self.extra = extra


# ================================================================ 書き込みの記録（.guard/）
# 正規の書き手（board_edit.py・Deck v2.6・ガード）が、指紋を変える書き込みの「前に」残す記録。
# 形式: .guard/format.json（{"v": 1}・無いときだけ作る）と、.guard/auth/<ns 20桁>-<pid>.html（書く版の本文）・.json
# （{v, fp, base_fp, writer, body}＝確定の印）の1件1ファイル。この節の関数は Deck v2.6 へそのまま写す。

GUARD_DIRNAME = ".guard"
GUARD_FORMAT_V = 1
GUARD_RECORD_MAX_AGE_SEC = 48 * 3600
_guard_last_ns = [0]   # このプロセスで最後に使った記録の時刻（消した記録の名前を使い回さないため）


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


# ================================================================ 板の読み取り

def decode_board(raw):
    """バイト列 → (本文, BOM の有無, 改行)。UTF-8 として読めなければ OpError。"""
    bom = raw.startswith(BOM)
    try:
        text = (raw[len(BOM):] if bom else raw).decode("utf-8")
    except UnicodeDecodeError:
        raise OpError("board.html を UTF-8 として読めません。何も書いていません。"
                      "この板は restore でも戻せません（restore もいまの板を読むため）。ボードを書かずに、この出力をユーザーに見せて、どうするかを確かめてください。")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text, bom, nl


def encode_board(text, bom):
    return (BOM if bom else b"") + text.encode("utf-8")


READ_RETRIES = 3
READ_RETRY_SEC = 0.1


def read_raw(path):
    """読めればバイト列、無ければ None。開いてすぐ閉じる。PermissionError は 0.1 秒あけて最大3回やり直す。"""
    for k in range(READ_RETRIES + 1):
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except PermissionError as e:
            if k == READ_RETRIES:
                raise OpError("%s を読めません（%s）。何も書いていません。少し待って1回だけやり直し、"
                              "それでも失敗したらユーザーに伝えてください。" % (os.path.basename(path), e))
            time.sleep(READ_RETRY_SEC)


def esc(s):
    return html.escape(s, quote=False)


def layout(lines):
    """手書き部分（コメントと DECK 領域の外）の見出しと項目。

    戻り値: (sections, items)
      sections: [{"line": 行, "label": 見出し}]
      items:    [{"s": 開始行, "e": 終了行, "section": 見出し or None, "sec_line": 見出しの行 or None}]
    """
    sections, items, _deck = _scan_board(lines)
    secs = [{"line": i, "label": html.unescape(label)} for (i, label, _c) in sections]
    out = []
    for (s, e, _n) in items:
        cur = None
        for sec in secs:
            if sec["line"] < s:
                cur = sec
        out.append({"s": s, "e": e, "section": cur["label"] if cur else None,
                    "sec_line": cur["line"] if cur else None})
    return secs, out


def _open_tag_classes(block):
    m = _ITEM_CLASS_RE.search(block)
    return m.group(2).split() if m else []


def status_chip(block):
    """項目の状態チップ（done/active/pending/wait/hold/none）。"""
    for m in SPAN_RE.finditer(block):
        toks = m.group(1).split()
        if "chip" not in toks:
            continue
        for t in STATUS_TOKENS:
            if t in toks:
                if t == "pending" and m.group(2).strip() == CHIP_LABELS["wait"]:
                    return "wait"
                return t
    return "none"


def is_done_block(block):
    return bool(_CHIP_DONE_RE.search(block))


def item_info(lines, it, index):
    block = "".join(lines[it["s"]:it["e"] + 1])
    t = _element_text(block, "time")
    m = re.search(r'\sdata-carried-from="([^"]*)"', lines[it["s"]])
    return {
        "index": index,
        "key": _item_key(block),
        "section": it["section"],
        "time": t.strip() if t is not None else None,
        "title": _element_text(block, "task-title"),
        "note": _element_text(block, "task-note"),
        "chip": status_chip(block),
        "crit": "crit" in _open_tag_classes(block),
        "carried": m.group(1) if m else None,
    }


def all_item_infos(lines):
    _secs, items = layout(lines)
    return [item_info(lines, it, i + 1) for i, it in enumerate(items)]


def resolve_item(lines, spec, what="--item", multi_note=""):
    """項目の指定（①Deck と同じキー「時刻|タイトル」②タイトルの完全一致 ③status の番号）→ 項目。

    multi_note は、2件以上に当たったときの文の「指定し直してください」の直後に足す（操作ごとの補足）。"""
    if spec is None or not str(spec).strip():
        raise OpError("%s で項目を指定してください（「時刻|タイトル」・タイトル・status の番号のどれか）。" % what)
    spec = str(spec).strip()
    _secs, items = layout(lines)
    infos = [item_info(lines, it, i + 1) for i, it in enumerate(items)]
    hits = []
    if "|" in spec:
        hits = [i for i, inf in enumerate(infos) if inf["key"] == spec]
    if not hits:
        hits = [i for i, inf in enumerate(infos) if (inf["title"] or "").strip() == spec]
    if not hits and spec.isdigit():
        n = int(spec)
        if 1 <= n <= len(infos):
            hits = [n - 1]
    if len(hits) != 1:
        cands = infos if not hits else [infos[i] for i in hits]
        short = [{"index": c["index"], "key": c["key"], "section": c["section"]} for c in cands][:40]
        if not hits:
            raise OpError("%s「%s」に当たる項目がありません。何も書いていません。"
                          "status で項目の一覧を見て、「時刻|タイトル」か番号で指定し直してください。" % (what, spec),
                          candidates=short)
        raise OpError("%s「%s」に当たる項目が %d 件あります。何も書いていません。"
                      "候補の番号（index）か「時刻|タイトル」で1件に絞って指定し直してください%s。" % (what, spec, len(hits), multi_note),
                      candidates=short)
    i = hits[0]
    return items[i], infos[i]


def find_section(lines, name):
    """見出しの名前 → 見出し（完全一致、無ければ正式名の先頭一致）。無ければ None。2件以上なら OpError。"""
    secs, _items = layout(lines)
    hits = [s for s in secs if s["label"] == name]
    if not hits and name in CANON_SECTIONS:
        hits = [s for s in secs if _canon_label(s["label"]) == name]
    if len(hits) > 1:
        raise OpError("見出し「%s」が %d 個あります。何も書いていません。見出しの全体の文字列で指定し直してください（候補: %s）。"
                      % (name, len(hits), "／".join(s["label"] for s in hits)))
    return hits[0] if hits else None


def section_end(lines, sec_line):
    """見出しの範囲の終わり（次の見出し・DECK の始まり・<footer> の手前）。挿入位置＝最後の空でない行の次。"""
    secs, _items = layout(lines)
    boundary = len(lines)
    for s in secs:
        if s["line"] > sec_line:
            boundary = s["line"]
            break
    for i in range(sec_line + 1, boundary):
        if MARKER_START in lines[i] or _FOOTER_LINE_RE.match(lines[i]):
            boundary = i
            break
    j = boundary - 1
    while j > sec_line and lines[j].strip() == "":
        j -= 1
    return j + 1


def indent_of(line):
    return re.match(r"[ \t]*", line).group(0)


def check_text(value, what, allow_empty=False):
    if value is None:
        return None
    if "\n" in value or "\r" in value:
        raise OpError("%s に改行は使えません。1行にして指定し直してください。" % what)
    if not allow_empty and not value.strip():
        raise OpError("%s が空です。文字を指定してください。" % what)
    return value


def check_time(value):
    m = HM_RE.match(value or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise OpError("時刻「%s」は H:MM の形ではありません（例 9:00・13:30）。指定し直してください。" % value)
    return "%d:%s" % (int(m.group(1)), m.group(2))


def check_chip(value):
    if value is None:
        raise OpError("--chip を指定してください（done・active・pending・wait・hold・none）。")
    if value not in CHIP_VALUES:
        raise OpError("チップ「%s」は使えません。done・active・pending・wait・hold・none のどれかを指定してください。" % value)
    return value


def chip_span(chip):
    return '<span class="chip %s">%s</span>' % (CHIP_CLASS[chip], CHIP_LABELS[chip])


CRIT_SPAN = '<span class="chip crit">重要タスク</span>'


def build_item(indent, nl, title, note=None, chip="pending", crit=False, time_=None):
    cls = "item" + ("" if time_ else " flat") + (" crit" if crit else "")
    out = ['%s<div class="%s">' % (indent, cls)]
    if time_:
        out.append('%s  <div class="time">%s</div>' % (indent, esc(time_)))
    out.append("%s  <div>" % indent)
    out.append('%s    <p class="task-title">%s</p>' % (indent, esc(title)))
    if note:
        out.append('%s    <p class="task-note">%s</p>' % (indent, esc(note)))
    chips = ([CRIT_SPAN] if crit else []) + ([chip_span(chip)] if chip != "none" else [])
    if chips:
        out.append('%s    <div class="chips">%s</div>' % (indent, "".join(chips)))
    out.append("%s  </div>" % indent)
    out.append("%s</div>" % indent)
    return [x + nl for x in out]


def default_chip(section_label):
    return "none" if _canon_label(section_label or "") == TOMORROW else "pending"


# ---------------------------------------------------------------- 項目ブロックの書き換え

def _block_shape_ok(blines):
    return len(blines) >= 3 and blines[-1].strip() == "</div>" and blines[-2].strip() == "</div>"


def _inner_insert_at(blines, before_cls=None):
    """内側の <div> の中で、新しい行を入れる位置と字下げ。before_cls の要素の行があればその前、無ければ内側の閉じの前。"""
    if before_cls:
        for k in range(1, len(blines) - 2):
            for cls in before_cls:
                if 'class="%s"' % cls in blines[k]:
                    return k, indent_of(blines[k])
    ref = None
    for k in range(len(blines) - 3, 0, -1):
        if blines[k].lstrip().startswith(("<p", '<div class="chips"')):
            ref = indent_of(blines[k])
            break
    if ref is None:
        ref = indent_of(blines[-2]) + "  "
    return len(blines) - 2, ref


def _set_chips_content(blines, nl, new_content_fn):
    """chips の div の中身を new_content_fn(今の中身) で置き換える。中身が空になれば div を外し、無ければ足す。"""
    block = "".join(blines)
    m = CHIPS_DIV_RE.search(block)
    if m:
        content = new_content_fn(m.group(1))
        if content:
            block = block[:m.start(1)] + content + block[m.end(1):]
            return block.splitlines(keepends=True)
        # div ごと外す（行にそれだけなら行ごと）
        ls = block.rfind("\n", 0, m.start()) + 1
        le = block.find("\n", m.end())
        line_end = len(block) if le == -1 else le + 1
        if block[ls:m.start()].strip() == "" and block[m.end():line_end].strip() == "":
            block = block[:ls] + block[line_end:]
        else:
            block = block[:m.start()] + block[m.end():]
        return block.splitlines(keepends=True)
    content = new_content_fn("")
    if not content:
        return blines
    if not _block_shape_ok(blines):
        raise OpError("この項目は形が想定と違う（末尾が </div> の2行でない）ため、チップの欄を足せません。何も書いていません。")
    at, ind = _inner_insert_at(blines)
    return blines[:at] + ['%s<div class="chips">%s</div>%s' % (ind, content, nl)] + blines[at:]


def _strip_spans(content, pred):
    return SPAN_RE.sub(lambda m: "" if pred(m.group(1).split()) else m.group(0), content)


def block_set_chip(blines, nl, chip):
    def fn(content):
        content = _strip_spans(content, lambda t: "chip" in t and any(x in t for x in STATUS_TOKENS))
        if chip != "none":
            content += chip_span(chip)
        return content
    return _set_chips_content(blines, nl, fn)


def block_set_crit(blines, nl, on):
    blines = list(blines)
    blines[0] = _ITEM_CLASS_RE.sub(
        lambda m: m.group(1) + _toggle_class_token(m.group(2), "crit", on) + m.group(3), blines[0], count=1)

    def fn(content):
        content = _strip_spans(content, lambda t: "chip" in t and "crit" in t)
        return (CRIT_SPAN + content) if on else content
    return _set_chips_content(blines, nl, fn)


def _replace_element_inner(block, cls, new_inner):
    """class に cls を持つ最初の要素の中身を置き換える。要素が無ければ None。"""
    for m in _CLASS_TAG_RE.finditer(block):
        if cls in m.group(2).split():
            close = block.find("</%s>" % m.group(1), m.end())
            if close == -1:
                raise OpError("この項目の %s の閉じタグが見つからないため、書き換えられません。何も書いていません。" % cls)
            return block[:m.end()] + new_inner + block[close:]
    return None


def _remove_element(block, cls):
    for m in _CLASS_TAG_RE.finditer(block):
        if cls in m.group(2).split():
            close = block.find("</%s>" % m.group(1), m.end())
            if close == -1:
                raise OpError("この項目の %s の閉じタグが見つからないため、書き換えられません。何も書いていません。" % cls)
            end = close + len("</%s>" % m.group(1))
            ls = block.rfind("\n", 0, m.start()) + 1
            le = block.find("\n", end)
            line_end = len(block) if le == -1 else le + 1
            if block[ls:m.start()].strip() == "" and block[end:line_end].strip() == "":
                return block[:ls] + block[line_end:]
            return block[:m.start()] + block[end:]
    return block


def block_edit(blines, nl, title=None, note=None):
    block = "".join(blines)
    if title is not None:
        r = _replace_element_inner(block, "task-title", esc(title))
        if r is None:
            if not _block_shape_ok(blines):
                raise OpError("この項目は形が想定と違うため、タイトルを足せません。何も書いていません。")
            bl = block.splitlines(keepends=True)
            at, ind = _inner_insert_at(bl, ("task-note", "chips"))
            bl = bl[:at] + ['%s<p class="task-title">%s</p>%s' % (ind, esc(title), nl)] + bl[at:]
            block = "".join(bl)
        else:
            block = r
    if note is not None:
        if note == "":
            block = _remove_element(block, "task-note")
        else:
            r = _replace_element_inner(block, "task-note", esc(note))
            if r is None:
                bl = block.splitlines(keepends=True)
                if not _block_shape_ok(bl):
                    raise OpError("この項目は形が想定と違うため、補足を足せません。何も書いていません。")
                at, ind = _inner_insert_at(bl, ("chips",))
                bl = bl[:at] + ['%s<p class="task-note">%s</p>%s' % (ind, esc(note), nl)] + bl[at:]
                block = "".join(bl)
            else:
                block = r
    return block.splitlines(keepends=True)


def block_set_time(blines, nl, value):
    block = "".join(blines)
    n_time = len(list(_TIME_OPEN_RE.finditer(block)))
    if n_time > 1:
        raise OpError("この項目には時刻の欄が %d 個あるため、時刻を書き換えられません。何も書いていません。" % n_time)
    if value is None:
        if n_time == 0:
            return blines
        block, count = _remove_time_elements(block)
        if count != 1:
            raise OpError("この項目の時刻の欄の閉じタグが見つからないため、時刻を外せません。何も書いていません。")
        bl = block.splitlines(keepends=True)
        bl[0] = _ITEM_CLASS_RE.sub(
            lambda m: m.group(1) + _toggle_class_token(m.group(2), "flat", True) + m.group(3), bl[0], count=1)
        return bl
    if n_time == 1:
        r = _replace_element_inner(block, "time", esc(value))
        return r.splitlines(keepends=True)
    if not _block_shape_ok(blines) or len(blines) < 4:
        raise OpError("この項目は形が想定と違うため、時刻の欄を足せません。何も書いていません。")
    bl = list(blines)
    bl[0] = _ITEM_CLASS_RE.sub(
        lambda m: m.group(1) + _toggle_class_token(m.group(2), "flat", False) + m.group(3), bl[0], count=1)
    ind = indent_of(bl[1])
    return [bl[0], '%s<div class="time">%s</div>%s' % (ind, esc(value), nl)] + bl[1:]


def normalize_block(blines):
    block = "".join(blines)
    return _normalize_item_block(block, is_done_block(block)).splitlines(keepends=True)


# ================================================================ 検査（K1〜K12）

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
    """K1〜K3（読んだ板にも当てる）。"""
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
    return errs


def deck_region(text):
    s = text.find(MARKER_START)
    e = text.find(MARKER_END, s)
    return text[s:e + len(MARKER_END)] if s != -1 and e != -1 else None


def hand_units(lines):
    """K7 の比較の単位（見出しと項目）: [(開始行, 文字列)]。"""
    secs, items = layout(lines)
    units = [(s["line"], lines[s["line"]]) for s in secs]
    units += [(it["s"], "".join(lines[it["s"]:it["e"] + 1])) for it in items]
    return sorted(units)


def count_progress(lines):
    copy = list(lines)
    _recalc_progress(copy)
    return copy


def warnings_for(text):
    """K11・K12（書くが警告を返す）。"""
    lines = text.splitlines(keepends=True)
    secs, items = layout(lines)
    warns = []
    odd = []
    for s in secs:
        lb = s["label"]
        if not lb or lb.startswith(RESERVED_SECTIONS) or _canon_label(lb):
            continue
        if any(rx.match(lb) for rx in ODD_SECTION_RES) and lb not in odd:
            odd.append(lb)
    if odd:
        warns.append({"code": "K11", "message": "見出し「%s」は正式名（今日の予定・今日中・ルーチンタスク・明日以降）ではありません。"
                      "この版には見出しの名前を直す操作が無く、move もこの見出しの項目は動かせません。正式名の見出しへ移してよいかをユーザーに確かめ、よいと言われた項目は add で正式名の見出しへ足し直し（status の time・chip・note を写し、重要タスクなら set-crit で付け直す）、remove で元の行を消してください（--confirmed を付ける前に、消す行をユーザーに確かめる）。残った見出しの扱いはユーザーに伝えてください。" % "」「".join(odd)})
    bad = []
    for it in items:
        block = "".join(lines[it["s"]:it["e"] + 1])
        if is_done_block(block) or "done-item" in _open_tag_classes(block):
            continue
        t = _element_text(block, "time")
        if t is not None and t.strip() and not re.search(r"(\d{1,2}):(\d{2})", t):
            bad.append(_item_key(block))
    if bad:
        warns.append({"code": "K12", "message": "時刻の欄が H:MM として読めない未完了の項目があります（%s）。"
                      "正しい時刻をユーザーに確かめてから、set-time --item <項目> --time H:MM で直してください（時刻の無い行にするなら --time none）。" % "、".join(bad)})
    return warns


def run_checks(op, old_text, new_text, intended_date_text, touched_old=(), touched_new=(), delta=0):
    """出来上がりの本文に K1〜K9 を当てる。当たったもの（E）の一覧を返す。"""
    errs = structure_errors(new_text)
    lines = new_text.splitlines(keepends=True)
    # K4
    dtxt = board_header_date_text(new_text)
    if strict_date_ok(dtxt) is None:
        errs.append({"code": "K4", "message": "ヘッダの日付「%s」が YYYY-MM-DD（曜）の形で読めないか、曜日が合いません。"
                     "この板には create 以外の操作では書けません。create で作り直すと spec に入れなかった行は消え、"
                     "置き換える前の板は history/ の …-before-create-… に残りますが、日付が読めないため restore では戻せません。"
                     "status の sections の行をユーザーに番号付きで見せ、作り直すかどうかと残す行を確かめてから、"
                     "残す行を spec に入れて create を実行してください。" % dtxt})
    elif intended_date_text is not None and dtxt != intended_date_text:
        errs.append({"code": "K4", "message": "ヘッダの日付「%s」が意図した日「%s」と違います。" % (dtxt, intended_date_text)})
    # K5
    if PLACEHOLDER_RE.search(placeholder_regions(new_text)):
        errs.append({"code": "K5", "message": "<title>・header・#upd-time・.progress に未置換の {{…}} が残っています。"})
    if op not in ("create", "restore") and old_text is not None:
        # K6
        if deck_region(old_text) != deck_region(new_text):
            errs.append({"code": "K6", "message": "DECK 領域（START〜END）が変わっています。"})
        # K7
        old_lines = old_text.splitlines(keepends=True)
        a = [u for (s, u) in hand_units(old_lines) if s not in touched_old]
        b = [u for (s, u) in hand_units(lines) if s not in touched_new]
        if a != b:
            errs.append({"code": "K7", "message": "操作の対象でない項目か見出しが変わっています（スクリプトの不具合の疑い）。"})
        # K8
        n_old = len(layout(old_lines)[1])
        n_new = len(layout(lines)[1])
        if n_new - n_old != delta:
            errs.append({"code": "K8", "message": "項目の数が %d → %d で、操作どおり（%+d）ではありません。" % (n_old, n_new, delta)})
    # K9
    m = _UPD_TIME_RE.search(new_text)
    if not m or not HM_RE.match(m.group(2).strip()):
        errs.append({"code": "K9", "message": "#upd-time が H:MM になっていません。"})
    if not any('class="progress-label"' in ln and PROGRESS_LABEL_RE.search(ln) for ln in lines) \
            or not any("bar-fill" in ln and BAR_WIDTH_RE.search(ln) for ln in lines) \
            or count_progress(lines) != lines:
        errs.append({"code": "K9", "message": "進捗 N / M かバー幅が、数え直した値と合いません。"})
    return errs


def progress_of(text):
    lines = text.splitlines(keepends=True)
    for ln in lines:
        if 'class="progress-label"' in ln:
            m = PROGRESS_LABEL_RE.search(ln)
            if m:
                n, t = int(m.group(1)), int(m.group(2))
                return {"done": n, "total": t, "percent": int((n / t) * 100 + 0.5) if t else 0}
    return None


def finish_header(text):
    """#upd-time を今の時刻に、進捗 N / M とバー幅を数え直した値にする（すべての書き込みで行う）。"""
    hm = datetime.now().strftime("%H:%M")
    text = _UPD_TIME_RE.sub(lambda m: m.group(1) + hm + m.group(3), text, count=1)
    lines = text.splitlines(keepends=True)
    _recalc_progress(lines)
    return "".join(lines)


# ================================================================ 操作

class Result(object):
    def __init__(self, text, payload=None, touched_old=(), touched_new=(), delta=0,
                 intended_date=None, extra_writes=None):
        self.text = text                  # 出来上がりの本文（None＝書かない）
        self.payload = payload or {}
        self.touched_old = set(touched_old)
        self.touched_new = set(touched_new)
        self.delta = delta
        self.intended_date = intended_date
        self.extra_writes = extra_writes or []   # [(名前の幹, バイト列, payload のキー)]。置き換えの前に history/ へ書く


def require_board(old):
    if old is None:
        raise OpError("board.html がありません。今日のボードを作るには create を使ってください。")


def require_sound(old_text, op):
    errs = structure_errors(old_text)
    if errs:
        raise OpError("いまの board.html は形が崩れているため、%s では書きません。"
                      "status の restorable_today（いまの板と日付が同じで、形の正しい版）を見て、restore --from history/<ファイル名> で戻してから、"
                      "欠けた行をユーザーに見せ、足し直してよいと言われた行だけを add で足し直してください。"
                      "restorable_today が空なら、ボードを書かずに、この出力をユーザーに見せて、どうするかを確かめてください。" % op, checks=errs)


def op_add(text, nl, a):
    if a.title is None:
        raise OpError("add には --title を指定してください。")
    title = check_text(a.title, "--title")
    note = check_text(a.note, "--note", allow_empty=True) or None
    tm = check_time(a.time) if a.time else None
    name = check_text(a.section, "--section")
    if name.startswith(RESERVED_SECTIONS):
        raise OpError("「%s」は Deck が書く見出しなので、ここには足せません。別の見出しを指定してください。" % name)
    lines = text.splitlines(keepends=True)
    sec = find_section(lines, name)
    if a.after and a.head:
        raise OpError("--after と --head は一緒に使えません。どちらか1つにしてください。")
    if sec is None:
        if not a.create_section:
            raise OpError("見出し「%s」がありません。何も書いていません。見出しごと足すなら --create-section を付けてください"
                          "（正式名は 今日の予定・今日中・ルーチンタスク・明日以降）。" % name)
        if a.after:
            raise OpError("新しい見出しには --after で指す項目がありません。--after を外してください。")
        chip = check_chip(a.chip) if a.chip else default_chip(name)
        rank = section_rank(name)
        secs, _items = layout(lines)
        insert_at = None
        for s in secs:
            if section_rank(s["label"]) > rank:
                insert_at = s["line"]
                break
        if secs:
            indent = indent_of(lines[secs[0]["line"]])
        else:
            dl = next((i for i, ln in enumerate(lines) if MARKER_START in ln), None)
            indent = indent_of(lines[dl]) if dl is not None else "  "
        item_lines = build_item(indent, nl, title, note, chip, False, tm)
        label = '%s<div class="section-label">%s</div>%s' % (indent, esc(name), nl)
        if insert_at is not None:
            new = lines[:insert_at] + [label] + item_lines + [nl] + lines[insert_at:]
            lab_at = insert_at
        else:
            dl = next((i for i, ln in enumerate(lines) if MARKER_START in ln), len(lines))
            j = dl - 1
            while j >= 0 and lines[j].strip() == "":
                j -= 1
            pos = j + 1
            new = lines[:pos] + [nl, label] + item_lines + lines[pos:]
            lab_at = pos + 1
        out = "".join(new)
        return Result(out, {"section": name, "created_section": True}, touched_new={lab_at, lab_at + 1}, delta=1)
    chip = check_chip(a.chip) if a.chip else default_chip(sec["label"])
    indent = indent_of(lines[sec["line"]])
    if a.head:
        pos = sec["line"] + 1
    elif a.after:
        it, inf = resolve_item(lines, a.after, "--after")
        if it["sec_line"] != sec["line"]:
            raise OpError("--after の項目「%s」は見出し「%s」の中にありません（「%s」にあります）。何も書いていません。"
                          % (inf["key"], sec["label"], inf["section"]))
        pos = it["e"] + 1
    else:
        pos = section_end(lines, sec["line"])
    item_lines = build_item(indent, nl, title, note, chip, False, tm)
    if pos > 0 and not lines[pos - 1].endswith(("\n", "\r")):
        lines[pos - 1] += nl
    new = lines[:pos] + item_lines + lines[pos:]
    return Result("".join(new), {"section": sec["label"], "created_section": False}, touched_new={pos}, delta=1)


def section_rank(label):
    c = _canon_label(label or "")
    return {"今日の予定": 0, "今日中": 1, "ルーチンタスク": 3, "明日以降": 4}.get(c, 2)


def _item_op(text, nl, a, fn):
    lines = text.splitlines(keepends=True)
    it, inf = resolve_item(lines, a.item)
    blines = lines[it["s"]:it["e"] + 1]
    nb = normalize_block(fn(blines))
    new = lines[:it["s"]] + nb + lines[it["e"] + 1:]
    return Result("".join(new), {"item": inf}, touched_old={it["s"]}, touched_new={it["s"]})


def op_set_chip(text, nl, a):
    chip = check_chip(a.chip)
    return _item_op(text, nl, a, lambda b: block_set_chip(b, nl, chip))


def op_edit(text, nl, a):
    if a.title is None and a.note is None:
        raise OpError("edit には --title か --note（または両方）を指定してください。--note \"\"（PowerShell では --note=）で補足を消せます。")
    title = check_text(a.title, "--title")
    note = check_text(a.note, "--note", allow_empty=True)
    return _item_op(text, nl, a, lambda b: block_edit(b, nl, title, note))


def op_set_crit(text, nl, a):
    if a.value not in ("on", "off"):
        raise OpError("set-crit の値は on か off です。")
    on = a.value == "on"
    return _item_op(text, nl, a, lambda b: block_set_crit(b, nl, on))


def op_set_time(text, nl, a):
    if a.time is None:
        raise OpError("set-time には --time H:MM（外すときは --time none）を指定してください。")
    value = None if a.time == "none" else check_time(a.time)
    return _item_op(text, nl, a, lambda b: block_set_time(b, nl, value))


def op_move(text, nl, a):
    if a.section not in MOVABLE_SECTIONS:
        raise OpError("move の行き先は 今日の予定・今日中・明日以降 のどれかです（Deck の D&D と同じ）。")
    if a.before and a.head:
        raise OpError("--before と --head は一緒に使えません。どちらか1つにしてください。")
    lines = text.splitlines(keepends=True)
    it, inf = resolve_item(lines, a.item)
    if _canon_section(inf["section"] or "") is None:
        raise OpError("項目「%s」は見出し「%s」にあり、move で動かせるのは 今日の予定・今日中・明日以降 の項目だけです。何も書いていません。正式名の見出しへ移すなら、ユーザーに確かめてから add で足し直し、remove で元の行を消してください。"
                      % (inf["key"], inf["section"]))
    before_s = None
    if a.before:
        bit, binf = resolve_item(lines, a.before, "--before")
        if bit["s"] == it["s"]:
            raise OpError("--before に動かす項目そのものを指定しています。別の項目を指定してください。")
        before_s = bit["s"]
        bsec = _canon_section(binf["section"] or "")
        if bsec != a.section:
            raise OpError("--before の項目「%s」は行き先「%s」の中にありません。何も書いていません。" % (binf["key"], a.section))
    block = lines[it["s"]:it["e"] + 1]
    if not block[-1].endswith(("\n", "\r")):
        block[-1] += nl
    rest = lines[:it["s"]] + lines[it["e"] + 1:]
    secs, items = layout(rest)
    label_line = next((s["line"] for s in secs if _canon_section(s["label"]) == a.section), None)
    if label_line is None:
        raise OpError("行き先の見出し「%s」がありません。何も書いていません。この版には見出しだけを作る操作がありません。ユーザーに確かめてから、動かす項目を add --section %s --create-section で（status の time・chip・note を写して）足し直し、remove で元の行を消してください。" % (a.section, a.section))
    if a.head:
        pos = label_line + 1
    elif before_s is not None:
        # 動かす項目を抜いた後の行番号へ直す（中身で探さない＝同じ中身の項目が2つあっても取り違えない）
        pos = before_s if before_s < it["s"] else before_s - (it["e"] - it["s"] + 1)
    else:
        pos = section_end(rest, label_line)
    new = rest[:pos] + block + rest[pos:]
    return Result("".join(new), {"item": inf, "to": a.section}, touched_old={it["s"]}, touched_new={pos})


def op_remove(text, nl, a):
    if a.confirmed and str(a.item or "").strip().isdigit():
        raise OpError("remove --confirmed では番号で項目を指定できません（確かめた後に番号がずれることがあるため）。"
                      "何も書いていません。「時刻|タイトル」かタイトルで指定し直してください。")
    lines = text.splitlines(keepends=True)
    # 2件以上に当たったときの文に回り道を足す（--confirmed では番号を受けないので、「時刻|タイトル」でも絞れないと行き止まりになる）
    it, inf = resolve_item(lines, a.item,
                           multi_note="（同じタイトルの行が複数あって絞れないときは、SKILL.md「ボードの書き方」の remove の回り道）")
    if not a.confirmed:
        return Result(None, {"item": inf, "would_remove": True,
                             "message": "まだ消していません。この行を消してよいかをユーザーに確かめてから、--confirmed を付けて実行してください。"})
    new = lines[:it["s"]] + lines[it["e"] + 1:]
    return Result("".join(new), {"item": inf}, touched_old={it["s"]}, delta=-1)


def load_spec(path_or_obj):
    if isinstance(path_or_obj, dict):
        return path_or_obj
    path_or_obj = os.path.expanduser(path_or_obj)   # PowerShell は ~ を展開せずに渡すため
    try:
        with open(path_or_obj, "rb") as f:
            spec = json.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError) as e:
        raise OpError("spec のファイル「%s」を JSON として読めません（%s）。Write ツールで書き直してください。" % (path_or_obj, e))
    if not isinstance(spec, dict):
        raise OpError("spec は {\"sections\": [...], \"items\": [...]} の形の JSON にしてください。")
    return spec


ITEM_KEYS = ("section", "time", "title", "note", "chip", "crit")


def build_sections(spec, nl, indent="  "):
    """create の spec → (セクションの行, 検証で見つけた拒否の理由の一覧)。"""
    unknown = set(spec) - {"sections", "items"}
    if unknown:
        raise OpError("spec に知らないキーがあります（%s）。使えるのは sections と items だけです。" % "・".join(sorted(unknown)))
    order = list(spec.get("sections") or [])
    items = spec.get("items") or []
    if not isinstance(order, list) or not isinstance(items, list):
        raise OpError("spec の sections と items は配列にしてください。")
    for n, sec in enumerate(order, 1):
        if not isinstance(sec, str):
            raise OpError("spec の sections の %d 件目が文字列ではありません。見出しの名前を文字列で書いてください。" % n)
    by = {}
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            raise OpError("spec の items の %d 件目がオブジェクトではありません。" % n)
        for key, types, what in (("title", (str,), "文字列"), ("note", (str, type(None)), "文字列"),
                                 ("time", (str, type(None)), "\"H:MM\" の文字列"),
                                 ("chip", (str, type(None)), "文字列"), ("crit", (bool, type(None)), "true か false")):
            if key in it and not isinstance(it[key], types):
                raise OpError("spec の items の %d 件目の %s は %s にしてください。" % (n, key, what))
        bad = set(it) - set(ITEM_KEYS)
        if bad:
            raise OpError("spec の items の %d 件目に知らないキーがあります（%s）。使えるのは %s です。"
                          % (n, "・".join(sorted(bad)), "・".join(ITEM_KEYS)))
        sec = it.get("section")
        if not isinstance(sec, str) or not sec.strip():
            raise OpError("spec の items の %d 件目に section がありません。" % n)
        if sec not in order:
            order.append(sec)
        by.setdefault(sec, []).append(it)
    out = []
    for k, sec in enumerate(order):
        check_text(sec, "セクション名")
        if sec.startswith(RESERVED_SECTIONS):
            raise OpError("「%s」は Deck が書く見出しなので、spec に入れないでください。" % sec)
        if not _canon_label(sec) and any(rx.match(sec) for rx in ODD_SECTION_RES):
            raise OpError("見出し「%s」は正式名に似ていますが正式名ではありません。今日の予定・今日中・ルーチンタスク・明日以降 の"
                          "どれかにしてください（プロジェクト名の見出しはこの形にしない）。" % sec)
        if k:
            out.append(nl)
        out.append('%s<div class="section-label">%s</div>%s' % (indent, esc(sec), nl))
        for it in by.get(sec, []):
            title = check_text(it.get("title"), "title")
            note = it.get("note")
            note = check_text(note, "note", allow_empty=True) or None if note is not None else None
            tm = check_time(it["time"]) if it.get("time") else None
            chip = check_chip(it["chip"]) if it.get("chip") else default_chip(sec)
            crit = bool(it.get("crit"))
            out += build_item(indent, nl, title, note, chip, crit, tm)
    return out


def op_create(old_raw, a, board_path):
    spec = load_spec(a.spec_obj if getattr(a, "spec_obj", None) is not None else a.spec)
    try:
        with open(TEMPLATE_PATH, "rb") as f:
            tpl = f.read().decode("utf-8-sig")
    except OSError as e:
        raise OpError("テンプレート %s を読めません（%s）。ユーザーに、スキルを入れ直す（Windows では setup.bat をもう一度実行する）よう伝えてください（setup.bat は Claude が実行しない）。" % (TEMPLATE_PATH, e))
    bom, nl = False, "\n"
    old_text = None
    if old_raw is not None:
        try:
            old_text, bom, nl = decode_board(old_raw)
        except OpError:
            # UTF-8 として読めない板は、消える行を確かめられないので、--confirmed が無ければ書かない
            if not getattr(a, "confirmed", False):
                e = sys.exc_info()[1]
                e.extra.update(missing=[], missing_incomplete=True)   # 行を拾えない＝拾いきれていない
                raise
            old_text = None
    tpl = tpl.replace("\r\n", "\n")
    today = date.today()
    full = fmt_full_date(today)
    tl = tpl.split("\n")
    s = next((i for i, ln in enumerate(tl) if "{{SECTIONS}}" in ln and "<!--" in ln), None)
    if s is None:
        raise OpError("テンプレートに {{SECTIONS}} のコメントがありません。ユーザーに、スキルを入れ直す（Windows では setup.bat をもう一度実行する）よう伝えてください（setup.bat は Claude が実行しない）。")
    e = next((i for i in range(s, len(tl)) if "-->" in tl[i]), None)
    sec_lines = [x.rstrip("\n") for x in build_sections(spec, "\n")]
    tl = tl[:s] + sec_lines + tl[e + 1:]
    text = "\n".join(tl)
    text = (text.replace("{{TITLE_DATE}}", fmt_title_date(today)).replace("{{FULL_DATE}}", full)
            .replace("{{UPDATED_AT}}", "0:00").replace("{{DONE}}", "0").replace("{{TOTAL}}", "0")
            .replace("{{PERCENT}}", "0"))
    # いまの板の DECK 領域が1組なら引き継ぐ（Deck の接続情報を、Deck が書き直すまでの間も残すため）
    if old_text is not None and _marker_counts(old_text) == (1, 1) \
            and old_text.find(MARKER_START) < old_text.find(MARKER_END):
        region = deck_region(old_text).replace("\r\n", "\n")
        text = text.replace(deck_region(text), region, 1)
    if nl != "\n":
        text = text.replace("\n", nl)
    payload = {"date": today.isoformat()}
    extra = []
    if old_raw is not None:
        # いまの板が今日のもので、Deck が引き継いだ板でもないなら、spec に無い行（消える行）があれば確かめる
        # （ヘッダの日付が読めない板も同じに扱う＝2026-10-29 ユーザー判断）
        if old_text is not None and not getattr(a, "confirmed", False):
            bd = parse_board_date(board_header_date_text(old_text), today)
            if (bd == today or bd is None) and board_attr(old_text, "data-tb-rolled") is None:
                missing, complete = missing_rows(old_text, spec)
                if missing or not complete:
                    head = ("まだ作り直していません。いまのボード（今日の板か、日付の読めない板）にある %d 行が spec に入っていないため、"
                            "このまま作り直すとその行が消えます。" % len(missing)) if missing else \
                        ("まだ作り直していません。いまのボードは形が崩れているため、spec に入っていない行があるかを確かめきれません。")
                    msg = (head + "missing の行をユーザーに番号付きで見せ、残したい行を"
                           "選んでもらってください（4件以下なら選択肢で、5件以上なら番号で答えてもらう）。"
                           "残すと言われた行を spec に足して、もう一度 create を実行してください。足さない行が残るときは、"
                           "その行が消えることをユーザーが確かめてから --confirmed を付けてください。"
                           "置き換える前の板は history/ に残ります。")
                    if not complete:
                        msg += ("いまの板は形が崩れているため、missing の行のチップ・補足が欠けているか、拾えていない行があるかもしれません"
                                "（missing_incomplete）。また、置き換える前の板は形が崩れているため restore では戻せません。"
                                "作り直す前に、いまの board.html を Read で読み、missing に無い行もユーザーに見せてください。")
                    raise OpError(msg, missing=missing, missing_incomplete=not complete)
        if old_text is not None:
            removed, complete = missing_rows(old_text, spec)
            payload["removed"] = removed
            payload["removed_incomplete"] = not complete
        else:
            payload["removed"] = None            # いまの板が UTF-8 で読めないので、消える行を数えられない
            payload["removed_incomplete"] = True
        bd = parse_board_date(board_header_date_text(old_text), today) if old_text is not None else None
        extra.append(("board-%s-before-create-%s" % ((bd or today).isoformat(), datetime.now().strftime("%H%M%S")),
                      old_raw, "saved"))
    return Result(text, payload, intended_date=full, extra_writes=extra), bom


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


def _norm_time(t):
    if t is None or not t.strip():
        return None
    m = HM_RE.match(t.strip())
    return "%d:%s" % (int(m.group(1)), m.group(2)) if m else t.strip()


def missing_rows(old_text, spec):
    """いまの板の手書きの項目のうち、spec の items に同じ section＋time＋title が無いもの。(行の一覧, 拾いきれたか)。

    各行の no は、この一覧の中の番号（1 から）。status の index（板の中の番号）とは別物なので、
    板の中の番号は status_index として持たせる（ユーザーに見せる番号は no）。
    """
    want = set()
    for it in spec.get("items") or []:
        want.add((it.get("section"), _norm_time(it.get("time")), it.get("title")))
    entries, complete = item_entries(old_text)
    rows = [e for e in entries if (e["section"], _norm_time(e["time"]), e["title"]) not in want]
    out = []
    for n, e in enumerate(rows, 1):
        r = {"no": n, "status_index": e["index"]}
        r.update({k: e[k] for k in ("section", "time", "title", "chip", "note")})
        out.append(r)
    return out, complete


def fmt_full_date(d):
    return "%04d-%02d-%02d（%s）" % (d.year, d.month, d.day, WEEKDAY_JA[d.weekday()])


def fmt_title_date(d):
    return "%d/%d(%s)" % (d.month, d.day, WEEKDAY_JA[d.weekday()])


def copy_assets(board_path):
    """スキルの静的ファイル3つを board.html の隣へ写す（中身が同じなら写さない）。警告の一覧を返す。"""
    warns = []
    src_dir = os.path.join(SKILL_DIR, "assets")
    dst_dir = os.path.dirname(os.path.abspath(board_path))
    if os.path.normcase(os.path.realpath(src_dir)) == os.path.normcase(os.path.realpath(dst_dir)):
        return warns
    for name in ASSET_NAMES:
        try:
            with open(os.path.join(src_dir, name), "rb") as f:
                data = f.read()
            dst = os.path.join(dst_dir, name)
            if read_raw(dst) == data:
                continue
            fd, tmp = tempfile.mkstemp(prefix=".tb-edit-", suffix=".tmp", dir=dst_dir)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dst)
        except OSError as e:
            warns.append({"code": "assets", "message": "%s を board.html の隣へ写せませんでした（%s）。ボードの表示が古い版のままかもしれません。" % (name, e)})
    return warns


def history_dir(board_path):
    return os.path.join(os.path.dirname(os.path.abspath(board_path)), HISTORY_DIRNAME)


def restorable(board_path):
    try:
        names = sorted(os.listdir(history_dir(board_path)))
    except OSError:
        return []
    return [HISTORY_DIRNAME + "/" + n for n in names if RESTORE_NAME_RE.match(n)]


def restorable_today(board_path):
    """restorable のうち、restore で実際に戻せる版（いまの板とヘッダの日付が同じ・UTF-8 で読める・形が正しい）。"""
    raw = read_raw(board_path)
    if raw is None:
        return []
    try:
        cur = board_header_date_text(decode_board(raw)[0])
    except OpError:
        return []
    if strict_date_ok(cur) is None:
        return []
    out = []
    for rel in restorable(board_path):
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(board_path)), rel), "rb") as f:
                t = decode_board(f.read())[0]
        except (OSError, OpError):
            continue
        if board_header_date_text(t) != cur or structure_errors(t) or PLACEHOLDER_RE.search(placeholder_regions(t)):
            continue
        out.append(rel)
    return out


def resolve_restore_source(board_path, src):
    if not src:
        raise OpError("restore には --from history/<ファイル名> を指定してください。")
    name = os.path.basename(src.replace("\\", "/"))
    parent = os.path.dirname(src.replace("\\", "/"))
    hdir = history_dir(board_path)
    want = os.path.normcase(os.path.realpath(hdir))
    if parent not in ("", HISTORY_DIRNAME):
        got = os.path.normcase(os.path.realpath(parent if os.path.isabs(parent)
                                                else os.path.join(os.path.dirname(os.path.abspath(board_path)), parent)))
        if got != want:
            raise OpError("restore で戻せるのは board.html と同じフォルダの history/ にある版だけです（指定: %s）。" % src)
    if not RESTORE_NAME_RE.match(name):
        raise OpError("「%s」は restore で戻せる名前ではありません。戻せるのは history/board-<日付>-lastgood-<時刻>.html・"
                      "…-before-interrupt-….html・…-before-tool-….html・…-before-create-….html だけです。status の restorable_today に、いま戻せる版の一覧があります。"
                      "restorable_today が空なら、ボードを書かずに、この出力をユーザーに見せて、どうするかを確かめてください。" % name,
                      candidates=restorable_today(board_path))
    return os.path.join(hdir, name), HISTORY_DIRNAME + "/" + name


def item_entries(text):
    """手書きの項目の一覧（restore の差・create の消える行に使う）。(項目の一覧, 拾いきれたか) を返す。

    形が正しい板は layout の走査で拾う。形が崩れた板（K1）は走査が途中で止まるので、
    「<div class="item で始まる行」から、次の項目・見出し・DECK の始まりの手前までを1つの項目とみなして拾う。
    そのとき、閉じが合わない項目やタイトルの無い項目があれば「拾いきれていない」（False）とする。
    """
    lines = text.splitlines(keepends=True)
    keys = ("index", "section", "time", "title", "note", "chip", "crit", "carried")
    if board_structure_ok(lines):
        return [{k: inf[k] for k in keys} for inf in all_item_infos(lines)], True
    blanked = _blank_comments(lines)
    ds = next((i for i, ln in enumerate(lines) if MARKER_START in ln), None)
    de = next((i for i, ln in enumerate(lines) if MARKER_END in ln), None)
    deck = (ds, de) if ds is not None and de is not None and ds <= de else None
    starts = _item_start_lines(lines, deck)
    labels = []
    for i, bl in enumerate(blanked):
        if deck and deck[0] <= i <= deck[1]:
            continue
        m = _SECTION_LABEL_RE.search(bl)
        if m:
            labels.append((i, html.unescape(m.group(1).strip())))
    stops = sorted(set(starts) | set(i for (i, _l) in labels) | ({deck[0]} if deck else set()) | {len(lines)})
    out = []
    complete = True
    for n, st in enumerate(starts, 1):
        end = min(x for x in stops if x > st)
        seg = "".join(lines[st:end])
        sec = None
        for (i, lb) in labels:
            if i < st:
                sec = lb
        t = _element_text(seg, "time")
        title = _element_text(seg, "task-title")
        m = re.search(r'\sdata-carried-from="([^"]*)"', lines[st])
        if title is None or _div_balance(seg) != 0:
            complete = False
        out.append({"index": n, "section": sec, "time": t.strip() if t is not None else None, "title": title,
                    "note": _element_text(seg, "task-note"), "chip": status_chip(seg),
                    "crit": "crit" in _open_tag_classes(seg), "carried": m.group(1) if m else None})
    return out, complete


def _entry_cmp(e):
    return (e["section"], e["time"], e["title"], e["note"], e["chip"], e["crit"], e["carried"])


def op_restore(old_raw, a, board_path):
    require_board(old_raw)
    path, rel = resolve_restore_source(board_path, getattr(a, "from_"))
    src_raw = read_raw(path)
    if src_raw is None:
        raise OpError("%s がありません。status の restorable_today で名前を確かめてください。restorable_today が空なら、ボードを書かずに、この出力をユーザーに見せて、どうするかを確かめてください。" % rel,
                      candidates=restorable_today(board_path))
    cur_text, bom, nl = decode_board(old_raw)
    try:
        src_text, sbom, _snl = decode_board(src_raw)
    except OpError:
        raise OpError("%s（戻す版）を UTF-8 として読めないため戻せません。何も書いていません。"
                      "status の restorable_today から別の版を選んでください。restorable_today が空なら、ボードを書かずに、この出力をユーザーに見せて、どうするかを確かめてください。" % rel, candidates=restorable_today(board_path))
    cur_date = board_header_date_text(cur_text)
    if strict_date_ok(cur_date) is None:
        raise OpError("いまの board.html のヘッダの日付「%s」が読めないため、戻す版の日付を確かめられません。何も書いていません。"
                      "create で今日のボードを作り直すことはできますが、spec に入れなかった行は消え、"
                      "置き換える前の板は history/ の …-before-create-… に残るだけで restore では戻せません。"
                      "status の sections の行をユーザーに番号付きで見せ、作り直すかどうかと残す行を確かめてから決めてください。" % cur_date)
    src_date = board_header_date_text(src_text)
    if src_date != cur_date:
        raise OpError("%s のヘッダの日付「%s」が、いまの板の日付「%s」と違うため戻せません。" % (rel, src_date, cur_date))
    errs = [x for x in structure_errors(src_text)]
    if strict_date_ok(src_date) is None:
        errs.append({"code": "K4", "message": "戻す版のヘッダの日付が YYYY-MM-DD（曜）で読めません。"})
    if PLACEHOLDER_RE.search(placeholder_regions(src_text)):
        errs.append({"code": "K5", "message": "戻す版に未置換の {{…}} があります。"})
    if errs:
        raise OpError("%s は形が崩れているため戻せません。status の restorable_today から別の版を選んでください。restorable_today が空なら、ボードを書かずに、この出力をユーザーに見せて、どうするかを確かめてください。" % rel,
                      checks=errs, candidates=restorable_today(board_path))
    cur_e, cur_complete = item_entries(cur_text)
    src_e, _src_complete = item_entries(src_text)
    cur_keys = [_entry_cmp(e) for e in cur_e]
    src_keys = [_entry_cmp(e) for e in src_e]
    strip = lambda e: {k: e[k] for k in ("section", "time", "title", "note", "chip", "crit", "carried")}
    diff = {"only_now": [strip(e) for e in cur_e if _entry_cmp(e) not in src_keys],
            "only_restore": [strip(e) for e in src_e if _entry_cmp(e) not in cur_keys],
            "now_broken": bool(structure_errors(cur_text)),
            "only_now_incomplete": not cur_complete}
    incomplete_note = ("" if cur_complete else
                       "いまの板は形が崩れているため、only_now の行のチップ・補足が欠けているか、拾えていない行がある"
                       "かもしれません（only_now_incomplete）。戻す前に、いまの board.html を Read で読み、only_now に無い行も"
                       "ユーザーに見せてください。")
    if not a.confirmed:
        return Result(None, {"from": rel, "diff": diff,
                             "message": "まだ戻していません。diff（only_now＝いまの板にだけある行・only_restore＝戻す版にだけある行）を"
                                        "ユーザーに見せ、戻してよいと言われてから --confirmed を付けて実行してください。" + incomplete_note}), bom
    stem = "board-%s-before-restore-%s" % (strict_date_ok(cur_date).isoformat(), datetime.now().strftime("%H%M%S"))
    text = src_text.replace("\r\n", "\n")
    if nl != "\n":
        text = text.replace("\n", nl)
    res = Result(text, {"from": rel, "diff": diff,
                        "message": "戻しました。戻す前の板は saved の名前で残しています。only_now の行をユーザーに見せ、足し直してよいと言われた行だけを add で足し直してください。"},
                 intended_date=cur_date, extra_writes=[(stem, old_raw, "saved")])
    return res, bom


# ================================================================ 書き込み（記録を先に・読み直しの比較・置き換えの再試行）

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


def commit(board_path, op, compute):
    """compute(old_raw) → (Result, bom)。検査を通った版だけを、記録→読み直し→置き換えの順で書く。"""
    board_dir = os.path.dirname(os.path.abspath(board_path))
    for attempt in range(REREAD_ATTEMPTS):
        old_raw = read_raw(board_path)
        res, bom = compute(old_raw)
        if res.text is None:
            return res, False
        old_text = None
        if old_raw is not None:
            try:
                old_text = decode_board(old_raw)[0]
            except OpError:
                old_text = None
        new_text = finish_header(res.text)
        errs = run_checks(op, old_text, new_text, res.intended_date, res.touched_old, res.touched_new, res.delta)
        if errs:
            raise OpError("出来上がりの板が検査（%s）に当たったため、書いていません。"
                          "引数を見直してください。直らなければ、この出力をそのままユーザーに見せてください。"
                          % "・".join(sorted(set(x["code"] for x in errs))), checks=errs)
        new_raw = encode_board(new_text, bom)
        if new_raw == old_raw:
            res.payload.pop("saved", None)   # 書かないので退避もしない
            res.payload["progress"] = progress_of(new_text)
            res.payload["warnings"] = warnings_for(new_text)
            return res, False
        base_fp = hand_fingerprint(old_text) if old_text is not None else None
        fp = hand_fingerprint(new_text)
        tmp = record = None
        extra_done = []
        try:
            tmp = _write_tmp(board_dir, new_raw)
            warn = []
            if fp != base_fp:
                try:
                    guard_prune_records(board_path)
                    record = guard_write_record(board_path, new_raw, fp, base_fp, "board_edit")
                except OSError as e:
                    raise OpError("書き込みの記録（.guard/auth/）を書けなかったため、board.html を書いていません（%s）。" % e)
                if record is None:
                    warn.append({"code": "guard", "message": ".guard/format.json の版を知らないため、書き込みの記録を残していません。"
                                 "ボードの保護に戻されることがあります。ユーザーに、スキルを入れ直す（Windows では setup.bat をもう一度実行する）よう伝えてください（setup.bat は Claude が実行しない）。"})
            if _HOOK_BEFORE_EXTRA is not None:
                _HOOK_BEFORE_EXTRA(res.extra_writes)
            for (stem, data, key) in res.extra_writes:
                try:
                    p = create_history_file(board_path, stem, data)
                except OSError as e:
                    raise OpError("history/ へ置き換える前の板を退避できなかったため、board.html を書いていません（%s）。"
                                  "この出力をユーザーに見せてください。" % e)
                extra_done.append(p)
                res.payload[key] = HISTORY_DIRNAME + "/" + os.path.basename(p)
            if _HOOK_BEFORE_REREAD is not None:
                _HOOK_BEFORE_REREAD(attempt, record)
            if read_raw(board_path) != old_raw:
                guard_remove_record(record)
                record = None
                for p in extra_done:
                    _rm(p)
                extra_done = []
                _rm(tmp)
                tmp = None
                continue
            replaced_by_other = False
            for k in range(REPLACE_RETRIES + 1):
                _last_replace_tries[0] = k + 1
                try:
                    os.replace(tmp, board_path)
                    tmp = None
                    break
                except PermissionError:
                    if k == REPLACE_RETRIES:
                        raise
                    time.sleep(REPLACE_RETRY_SEC)
                    # 待つ間に別の書き手が置き換えていたら、その版を消さない（読み直して比べ、違えば最初からやり直す）
                    if read_raw(board_path) != old_raw:
                        replaced_by_other = True
                        break
            if replaced_by_other:
                guard_remove_record(record)
                record = None
                for p in extra_done:
                    _rm(p)
                extra_done = []
                _rm(tmp)
                tmp = None
                continue
        except OpError:
            guard_remove_record(record)
            for p in extra_done:
                _rm(p)
            raise
        except OSError as e:
            guard_remove_record(record)
            for p in extra_done:
                _rm(p)
            raise OpError("board.html を置き換えられませんでした（%s）。何も書いていません。"
                          "ブラウザや別のプログラムが開いている間は失敗することがあります。少し待って1回だけやり直し、"
                          "それでも失敗したらユーザーに伝えてください。" % e)
        finally:
            _rm(tmp)
        res.payload["progress"] = progress_of(new_text)
        res.payload["warnings"] = warn + warnings_for(new_text)
        return res, True
    raise OpError("書く直前に別の書き手が board.html を書き換えたため、%d 回やり直しても書けませんでした。何も書いていません。"
                  "少し待ってから、もう一度同じ操作を実行してください。やり直しは1回だけにし、それでも失敗したらユーザーに伝えてください。" % REREAD_ATTEMPTS)


# ================================================================ status

def op_status(board_path):
    board_dir = os.path.dirname(os.path.abspath(board_path))
    out = {"board": board_path, "exists": False}
    for name, key in (("config.json", "mode"), ("state.json", "date")):
        try:
            with open(os.path.join(board_dir, name), "rb") as f:
                d = json.loads(f.read().decode("utf-8-sig"))
            out["mode" if name == "config.json" else "state_date"] = d.get(key) if isinstance(d, dict) else None
        except (OSError, ValueError):
            out["mode" if name == "config.json" else "state_date"] = None
    today = date.today()
    out["today"] = today.isoformat()
    out["restorable"] = restorable(board_path)
    out["restorable_today"] = restorable_today(board_path)
    raw = read_raw(board_path)
    if raw is None:
        out["suggest"] = "create"
        return out
    out["exists"] = True
    try:
        text = decode_board(raw)[0]
    except OpError as e:
        out["suggest"] = None
        out["errors"] = [{"code": "UTF8", "message": e.msg}]
        out["warnings"] = []
        return out
    lines = text.splitlines(keepends=True)
    dtxt = board_header_date_text(text)
    bd = parse_board_date(dtxt, today)
    out["board_date"] = bd.isoformat() if bd else None
    out["board_date_text"] = dtxt
    out["live"] = bool(bd == today and not PLACEHOLDER_RE.search(placeholder_regions(text)))
    out["rolled"] = board_attr(text, "data-tb-rolled")
    # skill/SKILL.md「状態ファイル」と同じ判定: state の date が今日なら update。ただし ①local モードで板の日付が
    # 今日でなければ create ②data-tb-rolled のある板では、朝の計画（今日の予定の整理・今日のタスク一覧）のときだけ create
    local = out["mode"] != "artifact"
    if out["state_date"] == today.isoformat() and not (local and bd != today):
        out["suggest"] = "update"
    else:
        out["suggest"] = "create"
    out["suggest_if_planning"] = "create" if out["rolled"] is not None else out["suggest"]
    secs, items = layout(lines)
    infos = [item_info(lines, it, i + 1) for i, it in enumerate(items)]
    out["sections"] = [{"name": s["label"], "items": [inf for inf in infos if inf["section"] == s["label"]
                                                       and items[inf["index"] - 1]["sec_line"] == s["line"]]}
                       for s in secs]
    orphans = [inf for inf in infos if inf["section"] is None]
    if orphans:
        out["items_before_sections"] = orphans
    out["progress"] = progress_of(text)
    errs = structure_errors(text)
    if strict_date_ok(dtxt) is None:
        errs.append({"code": "K4", "message": "ヘッダの日付「%s」が YYYY-MM-DD（曜）の形で読めないか、曜日が合いません。"
                     "この板には create 以外の操作では書けません。create で作り直すと spec に入れなかった行は消え、"
                     "置き換える前の板は history/ の …-before-create-… に残りますが、日付が読めないため restore では戻せません。"
                     "status の sections の行をユーザーに番号付きで見せ、作り直すかどうかと残す行を確かめてから、"
                     "残す行を spec に入れて create を実行してください。" % dtxt})
    if PLACEHOLDER_RE.search(placeholder_regions(text)):
        errs.append({"code": "K5", "message": "<title>・header・#upd-time・.progress に未置換の {{…}} が残っています。"})
    out["errors"] = errs
    out["warnings"] = warnings_for(text)
    return out


def board_attr(text, name):
    m = re.search(r'<div class="board"([^>]*)>', text)
    if not m:
        return None
    a = re.search(r'\s%s="([^"]*)"' % re.escape(name), m.group(1))
    return a.group(1) if a else None


# ================================================================ コマンドライン

HELP = """きょうのボード（board.html）を書き換える専用のスクリプトです。Claude は board.html を直接書かず、これを使います。
出力は標準出力に JSON 1つ（ok・changed・progress・warnings・board ほか）。拒否・失敗のときは終了コードが 0 以外になり、
理由を標準エラーにも出します（そのときボードは書いていません）。項目の指定（--item 等）は、
「時刻|タイトル」（時刻の無い項目は「|タイトル」）・タイトルの完全一致・status が返す番号（index）のどれかです。
日本語を含む引数がシェルで崩れるときは、引数を JSON ファイルに書いて --ops <ファイル> で渡してください。"""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise OpError("引数が正しくありません（%s）。何も書いていません。board_edit.py <操作> --help で使い方を確かめてください。" % message)


def build_parser():
    p = _Parser(prog="board_edit.py", description=HELP,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("--ops", help="引数を書いた JSON ファイル（例 {\"op\": \"add\", \"section\": \"今日中\", \"title\": \"…\"}）。"
                                 "Write ツールで ~/.claude/today-board/ops/ に書く（シェルを通さない）。成功したら board_edit.py が消す")
    sub = p.add_subparsers(dest="op", metavar="<操作>")

    def add(name, help_):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.add_argument("--board", help="board.html のパス（既定は ~/.claude/today-board/board.html）")
        return sp

    add("status", "板の状態を JSON で返す（書かない）。mode・state_date・board_date・live・rolled・suggest（create か update か）・"
                  "セクションと項目の一覧（index・key・time・title・note・chip・crit・carried）・進捗・検査の結果・"
                  "restorable（history/ にある、restore が受ける名前の版）・restorable_today（そのうち、いまの板と日付が同じで形の正しい、"
                  "restore で実際に戻せる版）")
    sp = add("create", "spec（JSON）から今日のボードを作り、静的ファイル3つを board.html の隣へ写す。"
                       "置き換える前の板は history/board-<日付>-before-create-<時刻>.html に残す。"
                       "restore で戻せるのは、その版のヘッダの日付がいまの板と同じで形も正しいときだけ"
                       "（前の日の板・日付の読めない板・形の崩れた板は history/ に残るだけで、restore では戻せない）。"
                       "いまの板が今日のものか日付の読めない板で（Deck が引き継いだ板を除く）、spec に無い行があるとき、"
                       "または形が崩れていて spec に無い行を拾いきれないときは、--confirmed が無ければ書かずに missing（消える行）と"
                       " missing_incomplete（拾いきれていないとき true）を返す。state.json は書かない（SKILL.md の手順で書く）")
    sp.add_argument("--confirmed", action="store_true", help="spec に無い行が消えることをユーザーが確かめた後に付ける")
    sp.add_argument("--spec", help="{\"sections\": [見出し…], \"items\": [{\"section\", \"time\"?, \"title\", \"note\"?, \"chip\"?, \"crit\"?}…]} の JSON ファイル")
    sp = add("add", "見出しの中に項目を1行足す（必ず足す。重複かどうかは先に status で確かめる）")
    sp.add_argument("--section", required=False, help="足す先の見出し")
    sp.add_argument("--create-section", action="store_true", help="見出しが無ければ作る")
    sp.add_argument("--after", help="この項目の直後に足す（既定は見出しの末尾）")
    sp.add_argument("--head", action="store_true", help="見出しの直後（先頭）に足す")
    sp.add_argument("--title")
    sp.add_argument("--note")
    sp.add_argument("--chip", help="done・active・pending・wait・hold・none（既定は「明日以降」なら none、それ以外は pending）")
    sp.add_argument("--time", help="H:MM（付けると時刻付きの行、無ければ時刻なしの行）")
    sp = add("set-chip", "項目の状態チップを替える（wait＝条件待ち・none＝チップを外す）")
    sp.add_argument("--item")
    sp.add_argument("--chip")
    sp = add("edit", "項目のタイトルか補足を書き換える（--note \"\"、PowerShell では --note= で補足を消す）")
    sp.add_argument("--item")
    sp.add_argument("--title")
    sp.add_argument("--note")
    sp = add("set-crit", "重要タスクを付ける（on）／外す（off）。項目の crit と「重要タスク」のチップの両方を付け外しする")
    sp.add_argument("--item")
    sp.add_argument("value", nargs="?", help="on か off")
    sp = add("set-time", "項目の時刻を替える（--time none で時刻を外す）")
    sp.add_argument("--item")
    sp.add_argument("--time")
    sp = add("move", "項目を 今日の予定・今日中・明日以降 の間で動かす（Deck の D&D と同じ規則）")
    sp.add_argument("--item")
    sp.add_argument("--section", help="行き先（今日の予定・今日中・明日以降）")
    sp.add_argument("--before", help="この項目の直前へ（既定は見出しの末尾）")
    sp.add_argument("--head", action="store_true", help="見出しの直後（先頭）へ")
    sp = add("remove", "項目を1行消す。--confirmed が無ければ対象を示すだけで消さない")
    sp.add_argument("--item")
    sp.add_argument("--confirmed", action="store_true")
    sp = add("restore", "板を history/ の版（lastgood・before-interrupt・before-tool・before-create）へ丸ごと戻す。--confirmed が無ければ差を示すだけで戻さない")
    sp.add_argument("--from", dest="from_", help="history/<ファイル名>")
    sp.add_argument("--confirmed", action="store_true")
    return p


POSITIONAL = {"set-crit": ("value",)}


def expand_ops(argv):
    """--ops <file> を、その JSON の中身の引数へ展開する。(argv, spec の中身 or None, 読んだファイル)"""
    if "--ops" not in argv and not any(x.startswith("--ops=") for x in argv):
        return argv, None, None
    rest = []
    path = None
    i = 0
    while i < len(argv):
        x = argv[i]
        if x == "--ops":
            path = argv[i + 1] if i + 1 < len(argv) else None
            i += 2
            continue
        if x.startswith("--ops="):
            path = x[len("--ops="):]
            i += 1
            continue
        rest.append(x)
        i += 1
    if not path:
        raise OpError("--ops にファイルを指定してください。")
    path = os.path.expanduser(path)   # PowerShell は ~ を展開せずに渡すため（成功したときの ops/ の掃除も展開後のパスで比べる）
    try:
        with open(path, "rb") as f:
            obj = json.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError) as e:
        raise OpError("--ops のファイル「%s」を JSON として読めません（%s）。Write ツールで書き直してください。" % (path, e))
    if not isinstance(obj, dict):
        raise OpError("--ops の JSON はオブジェクト（{…}）にしてください。")
    obj = dict(obj)
    op = obj.pop("op", None)
    if not rest or rest[0].startswith("-"):
        if not op:
            raise OpError("--ops の JSON に \"op\"（操作の名前）がありません。")
        rest = [op] + rest
    spec = obj.pop("spec", None)
    if isinstance(spec, str):
        rest += ["--spec=" + spec]
        spec = None
    pos = []
    for k, v in obj.items():
        name = k.replace("_", "-")
        if name in POSITIONAL.get(rest[0], ()):
            pos.append(str(v))
        elif v is True:
            rest.append("--" + name)
        elif v is False or v is None:
            continue
        else:
            rest.append("--%s=%s" % (name, v))
    if pos:
        rest += ["--"] + pos
    return rest, spec, path


def emit(obj, stream=None):
    data = json.dumps(obj, ensure_ascii=False, indent=1) + "\n"
    out = stream or sys.stdout
    try:
        out.buffer.write(data.encode("utf-8"))
        out.flush()
    except AttributeError:
        out.write(data)


def emit_err(msg):
    data = "board_edit.py: " + msg + "\n"
    try:
        sys.stderr.buffer.write(data.encode("utf-8"))
        sys.stderr.flush()
    except AttributeError:
        sys.stderr.write(data)


def _cleanup_ops_file(path, board_path):
    """成功したら、ボードのフォルダの ops/ に置いた引数のファイルを消す（それ以外の場所のファイルは消さない）。"""
    if not path:
        return
    ops_dir = os.path.normcase(os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(board_path)), OPS_DIRNAME)))
    if os.path.normcase(os.path.dirname(os.path.realpath(path))) == ops_dir:
        _rm(path)


ITEM_OPS = {"add": op_add, "set-chip": op_set_chip, "edit": op_edit, "set-crit": op_set_crit,
            "set-time": op_set_time, "move": op_move, "remove": op_remove}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    op = None
    try:
        argv, spec_obj, ops_path = expand_ops(argv)
        parser = build_parser()
        a = parser.parse_args(argv)
        op = a.op
        if not op:
            parser.print_help()
            return 2
        a.spec_obj = spec_obj
        if getattr(a, "spec", None):
            a.spec = os.path.expanduser(a.spec)   # ~ のまま渡されても読めて、成功したときの ops/ の掃除でも比べられるように
        board_path = os.path.abspath(os.path.expanduser(a.board or DEFAULT_BOARD))
        if op == "status":
            emit(dict(ok=True, op=op, version=VERSION, **op_status(board_path)))
            return 0
        if op == "create":
            if a.spec is None and spec_obj is None:
                raise OpError("create には --spec <JSON ファイル> を指定してください。")
            res, changed = commit(board_path, op, lambda raw: op_create(raw, a, board_path))
            warns = copy_assets(board_path)
            res.payload["warnings"] = res.payload.get("warnings", []) + warns
        elif op == "restore":
            res, changed = commit(board_path, op, lambda raw: op_restore(raw, a, board_path))
        else:
            if op in ("add", "move") and not a.section:
                raise OpError("%s には --section を指定してください。" % op)

            def compute(raw):
                require_board(raw)
                text, bom, nl = decode_board(raw)
                require_sound(text, op)
                cur = board_header_date_text(text)
                r = ITEM_OPS[op](text, nl, a)
                r.intended_date = cur
                return r, bom
            res, changed = commit(board_path, op, compute)
        out = dict(ok=True, op=op, version=VERSION, changed=changed, board=board_path)
        out.update(res.payload)
        out.setdefault("warnings", [])
        emit(out)
        if not (res.payload.get("would_remove") or (op == "restore" and not a.confirmed)):
            _cleanup_ops_file(ops_path, board_path)
            if op == "create" and a.spec:
                _cleanup_ops_file(a.spec, board_path)
        return 0
    except OpError as e:
        out = {"ok": False, "op": op, "version": VERSION, "error": e.msg}
        out.update(e.extra)
        emit(out)
        emit_err(e.msg)
        return 1


if __name__ == "__main__":
    sys.exit(main())
