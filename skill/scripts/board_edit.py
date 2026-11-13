#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_edit.py v1.17 — きょうのボード（board.html）を書き換える専用のスクリプト。

Claude は board.html を直接書かず、このスクリプトに操作を渡す。スクリプトが HTML を機械で書き換え、
書く前に出来上がりの形を検査し（K1〜K9・K16・K17 に当たれば書かない・K11〜K15 は書いて警告する）、
書く前に .guard/auth/ へ書き込みの記録を残してから、一時ファイル→os.replace で置き換える。
置き換える直前に板を読み直し、読んだときと違えば（ほかの書き手が書いた）記録を消して最初からやり直す。
create は置き換える前の板を history/board-<日付>-before-create-<時刻>.html に、restore は戻す前の板を
…-before-restore-… に残す。config.json・state.json は読むだけで書かない。

操作: status / create / add / set-chip / edit / set-crit / set-time / set-due / move / remove / restore / close-time（v1.10） /
      deck-snap / deck-wait（v1.2。Deck を起動し直す前後の確かめ。どちらも板を読むだけで書かない）
      move --create-section（v1.3。行き先の見出しが無ければ add --create-section と同じ位置に作る）
      create の dropped_times（v1.4。H:MM でない時刻が消えるか変わる行。今日の板では --confirmed が要る）
      v1.5: 「明日以降」の行で、時刻の欄が実施日の時刻と違う（H:MM でも）行も dropped_times に出す。
      set-due・set-time はこの食い違いを作らない（同じ時刻なら書く）
      v1.6: move・D&D で今日の側から「明日以降」へ戻してできた食い違いを、警告 K14 で知らせる（status と書き込みの出力の warnings）
      v1.7: 行の時刻を1つにする。set-time・set-due・add・create は時刻の欄と実施日の時刻を同じ値にし（set-due・set-time が
      食い違いで断るのはやめた）、move は印の有無・実施日の前かによらず同じ形にする（Deck v2.11 の D&D と同じ）。
      今日の側へ移した行・今日の側に書く行の実施日は今日にし、元の実施日を due_from（data-due-from）に残す（status・add --due-from・
      set-due --due-from・spec の due_from）。時刻の欄の無い行の set-time --time none は何もしない
      v1.8: move が「明日以降」の行を今日の側へ動かして時刻の欄を外すとき、その時刻を data-orig-time に残さない（行の時刻は
      data-due か data-due-from に残る。ただし H:MM でない時刻の欄の文字と、data-due-from が既にある行で時刻の欄の時刻がその時刻と違うときの時刻の欄の時刻は、どこにも残らない。data-orig-time は Deck v2.12 の日付の切り替えが
      data-carried-from と組で書く）。
      data-due-from の時刻は行の時刻にする（時刻の欄が H:MM ならそれ。v1.7 までは元の data-due そのまま）。Deck v2.12 の _due_moved_shape の写し
      v1.9: add・set-due・create が今日の側の行の実施日を今日にするとき（roll_due_today）も、data-due-from（渡さなかったとき）の時刻を
      行の時刻にする（Deck v2.12 の _carry_due_today と同じ。v1.8 までは渡された実施日そのまま）。
      move で「明日以降」の先の日の行を今日の側へ動かすと、今日の行として扱う（実施日を今日にし、時刻の欄を外して flat、元の予定を
      data-due-from に残し、一度移した印を付ける。add・set-due・create も今日の側の行の先の日の実施日を今日にする＝Deck v2.13 と同じ。
      v1.8 までは先の日の行の日付も印も変えなかった）。
      move で今日の予定・今日中の行を「明日以降」へ動かすときは --due（ユーザーに確かめた実施日か none＝未定）が要る。
      実施日をその値にし、印と元の実施日を外す（_later_due_shape。Deck v2.13 の写し・2026-11-06 ユーザー決定）
      v1.10: 行の鍵（status の key・--item の「時刻|タイトル」）の時刻の部分を、時刻の欄そのものの文字にする（_key_text。Deck v2.14 の写し。
      閉じタグの無い時刻の欄〔<span class="time">0:00<div>…〕でも「0:00|タイトル」になり、Deck と board.js の鍵と合う。2026-11-06 ユーザー決定）。
      status の time・K12 も同じ規則で読む。閉じタグの無い時刻の欄を警告 K15 で知らせ、close-time で閉じタグを補う
      （set-time はその行を書き換えずに断る）。時刻の欄を外す操作（move・set-time --time none）は、欄の中にタイトル・補足・チップの箱・チップ・
      項目があれば外さない（set-time --time none と、今日の側から「明日以降」への move は書かずに断る。「明日以降」から今日の側への move は、時刻の欄を残したまま、実施日の来た行に一度移した印だけを付けて動かす＝_mark_due_moved。_remove_time_elements・Deck v2.14 の写し。閉じタグが項目の終わりに置かれた形では、v1.9 は外して消した）
      v1.11: 時刻の欄の時刻を読む所（K14・move の形作り・今日の予定の位置・create の時刻）を、行の鍵の時刻と同じ読み方にする（_time_text。
      Deck v2.15 の写し。v1.10 までは _element_text で最初の同じ名前の閉じタグまで読み、閉じタグの無い欄では後ろのチップの文字まで入った）。
      欄の範囲（_time_range）は、外側で開いていない閉じタグを読み飛ばし、p の欄を後ろの p を閉じる要素の手前で閉じる（Deck v2.15 と同じ）。
      行の鍵（status の key）の時刻の部分もこの範囲で読むので、範囲の外に文字がある形（p の欄の後ろの div の文字・閉じタグの無い欄の
      閉じる所より後ろの文字）では鍵が変わる（Deck v2.15・board.js の鍵と合う）
      v1.12: 閉じタグの無い時刻の欄のうち、ブラウザが欄をタイトルやチップの手前で閉じる形（<p class="time">9:00<div><p class="task-title">…・
      <div><span class="time">9:00</div><p class="task-title">…。画面は正しく、board.js の「ボードの点検」の⑥には出ない＝_time_screen_closed）を、
      警告 K15 で別の文で知らせ、close-time はブラウザが閉じる位置（その手前の空白を除く）に閉じタグを補う（画面も鍵も変わらない。v1.11 までは時刻の文字の直後に補い、
      時刻の文字の後ろにタグで囲んだ文字がある形〔<p class="time">9:00 <b>am</b><div>…・<div><span class="time">9:00 <span>am</div>…・
      <div><span class="time">9:00</div>am <p class="task-title">…〕は断って restore を案内し、欄に時刻の文字が無い形〔<div><span class="time">  </div>…〕は断って
      時刻の欄の文字を確かめるよう案内した）。欄の中で開いて閉じていない要素があれば、その閉じタグも
      足す（書式の要素〔b・i など＝_FORMATTING_TAGS〕が欄の中で閉じていない行〔_time_reopened〕は K15 の3つ目の文で知らせ、close-time は
      --confirmed のときだけ同じく補う〔タイトルやチップを包んでいた書式が外れ、画面が変わるため〕。欄そのものが書式の要素の行と、欄の中で
      table・object・script などが閉じていない行は、この扱いをせず上の判定に戻る）。Deck v2.16 の _time_close_at・_time_screen_closed の写し
      v1.13: 構造の検査 K16（E）を足す（_swallow_open・2026-11-10 ユーザー決定「断る」）。ブラウザが要素として読まない所（閉じていない textarea・script など
      の中・コメント・CDATA・タグ・template の中）に行・見出し・Deck の欄が入って画面から消える形と、board.js の読み込みが実行されない形を当てる
      （基準は _swallow_open の注釈）。status の structure_errors に出し、K1〜K3 と同じく、いまの板にあれば書かずに restore を案内し（require_sound）、
      出来上がりにあれば書かない。restorable_today と restore の戻す版からも外れる。K16 の行がある項目には K15 を出さない（その行は K16 で知らせる）。
      あわせて K17（E）を足す: 書く前の板で実行される board.js の読み込みが、出来上がりで無いか実行されない形なら書かない。Deck v2.17・guard.py v1.1 と同じ写し
      v1.14: 書く操作のたびに、末尾の形の板（body の最後に <script src="board.js"></script>）を head の形（board.css の読み込みの直後に
      <script src="board.js" defer></script>）へ移す（migrate_board_js。Deck v2.18 の写し・2026-11-10 ユーザー決定「自動で移す」）。
      テンプレート（create）は head の形で作る。移すのは操作の前で、移した板に操作を当てる。移した書き込みの出力には migrated: true が付き、操作の
      中身が何も変わらなくても changed は真になる。create・restore が history/ に残す「置き換える前の板」も、移した後の版になる（行・見出し・DECK 領域・
      ヘッダは同じ）。移しても行の指紋・K6〜K8・K17 は変わらない
      v1.15: 時刻の欄の中の svg・math を、ブラウザと同じく名前空間で読む（_tag_walk。K16 の _sw_scan と同じ決まり＝math・svg の中から抜ける HTML の
      タグ・</p>・</br>、HTML として読む所、スコープの境界の中では外側の閉じタグを読み飛ばす）。K15 の文の選び方・close-time・set-time の断り方に効く。
      v1.14 までは名前だけで見て、<svg><span><desc>x や <svg><textarea>x を「ブラウザが欄を閉じない」と数え、<svg><foreignObject><span>x</svg> の
      </svg> で欄を閉じたとみなした（どれも手書きでしか生まれない形）。Deck v2.19 と同じ写し
      v1.16: 時刻の欄の閉じタグを、同じ名前の開きと閉じを数えて決める（_time_match_close。2026-11-13 ユーザー決定「直す」）。中で閉じた
      同じ名前の要素（<span class="time"><span>9</span>:00 <span class="x">a</span></span> の <span>）の閉じタグは欄を閉じない。K15（_time_open_unclosed）・
      欄の文字と行の鍵（_key_text・_time_text）・set-time（_replace_element_inner）・close-time がこれで読む。v1.15 までは同じ名前の最初の閉じタグを
      欄の閉じタグと読み、<span class="time">9:00 <span>a</span>x</div>… の閉じていない欄を K15 に出さず、上の形の行の鍵の時刻は「9」で、
      set-time は中の span の閉じタグまでを書き換えた。board.js の鍵（tbKeyWalk）・⑥も同じ読み方にそろえた（Deck v2.20 と同じ写し）。
      数えるときは、ブラウザが要素として読まない所（コメント〔<! ・<? で始まる形と、</ の後に英字が続かない形を含む〕・属性の値・閉じタグまでを文字として読む要素の中身〔svg・math の要素として読むもの（<svg><style> など）を除く。foreignObject など HTML として読む所の中のものは除かない〕・svg・math の中の CDATA）のタグを読まず（_blank_markup）、HTML の void でない要素の /> を開きタグとして数える（ブラウザと同じ）
      v1.17: 時刻の欄の閉じタグを、ブラウザの読み方で決める（_time_match_close が _tag_walk の base で読む）。HTML として読む所（svg の foreignObject
      など）の中から書いた欄の閉じタグ（<svg><foreignObject></span>）と、欄が _OWN_END_RULE に無い名前（span など）のときに、間に special の要素（p・div など＝_HTML_SPECIAL）がある欄の閉じタグ
      （<span class="time">0:00 <p>x</span>）は欄を閉じず、K15 に当たる（v1.16 までは閉じたと読み、K15 に出さなかった）。HTML として読む所の中の
      HTML の要素の直下の <![CDATA[ は偽のコメントとして読む（中身は鍵に入らない。v1.16 までは CDATA として中身を鍵に入れ、board.js と分かれた）。
      閉じタグに自分の決まりがある名前（div・p・li・書式の要素など＝_OWN_END_RULE）の閉じタグは、範囲の境界（table・td・object など＝_SCOPE_BOUNDS）を越えない
      （<div class="time">9:00 <table><tr><td>a</div> の </div> は欄を閉じない）。限界: 欄そのものが書式の要素の行の付け直し（adoption agency）はなぞらない。
      p の欄は、p を閉じる開きタグでもボタンの範囲の中でだけ閉じる（_time_range。<p class="time">9:00 <button>a</p><p class="task-title">… は
      タイトルも欄の中）。見出しの閉じタグは、範囲の中のどの見出しでも閉じる（<h2 class="time">9:00</h1> は欄を閉じる）
      Deck v2.21 と同じ写し
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
import math
import os
import re
import sys
import tempfile
import time
import urllib.parse
from collections import Counter
from datetime import date, datetime

VERSION = "1.17"

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
_DUE_VALUE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?: (\d{1,2}):(\d{2}))?$")
_SPAN_CLASS_RE = re.compile(r'(<span\b[^>]*?\bclass=")([^"]*)("[^>]*>)([^<]*)(</span>)')


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


# 行の鍵の時刻の部分は、class を持つ開きタグの手前で読み終える（v2.14 / board_edit.py v1.10。下の _key_text）
_KEY_STOP_RE = re.compile(r'<\w+\b[^>]*?\sclass\s*=', re.I)


def _key_text(block, cls_token, stop_at_class=False):
    """行の鍵に使う、class トークンに cls_token を持つ最初の要素の文字（v2.14 / board_edit.py v1.10 で新設。欄の範囲〔_time_range〕で読み終えるのは v2.15 / board_edit.py v1.11）。無ければ None。

    鍵の作り方の正本。board.js の tbKeyText が同じ規則を DOM に当て、board_edit.py は写しを持つ（試験 T-P が一致を見る）。
    要素の開きタグの後から、要素と同じ名前の最初の閉じタグの手前までを読む（_element_text と同じ。タイトルに使う）。stop_at_class が真なら
    （時刻の欄に使う）、欄の範囲（_time_range＝欄を閉じる閉じタグ〔ブラウザの読み方で決める＝_time_match_close。v2.21 / board_edit.py v1.17〕まで、閉じタグの無い欄はブラウザが閉じる所まで）を読み、
    その中に class を持つ開きタグがあればその手前で読み終える（v2.15 / board_edit.py v1.11。中で開いて閉じた同じ名前の要素の閉じタグで読み終えない
    のは v2.20 / board_edit.py v1.16＝<span class="time"><span>9</span>:00</span> は「9:00」。v1.15 までは「9」）。範囲が決まらなければ、
    class を持つタグの手前か block の終わりまで読む
    （時刻の欄に使う。閉じタグの無い <span class="time">0:00<div><p class="task-title">… でも「0:00」になる＝閉じタグを
    補っても鍵が変わらない。ブラウザは欄の中に後ろの要素を取り込むが、board.js も同じ所で読み終える）。
    タグを除き、エンティティを復号し、改行を LF にそろえる（ブラウザは CR LF・CR を LF にして読むので、CR LF の板でも合わせる）。
    """
    bl = _blank_markup(block) if stop_at_class else block
    for m in _CLASS_TAG_RE.finditer(block):
        if cls_token in m.group(2).split() and bl[m.start()] == "<":
            end = block.find("</%s>" % m.group(1), m.end())
            if stop_at_class:
                # 欄の範囲（_time_range）を読む＝閉じタグの無い欄は、ブラウザが閉じる所まで（v2.15 / board_edit.py v1.11）。閉じタグは入れ子を
                # 数えて決める（v2.20 / board_edit.py v1.16。board.js の tbKeyText は DOM の欄を読むので同じになる）
                r = _time_range(block, m)
                end = -1 if r is None else r[1]
                stop = _KEY_STOP_RE.search(bl, m.end(), len(block) if end == -1 else end)
                if stop:
                    end = stop.start()
                elif end == -1:
                    end = len(block)
            if end == -1:
                return ""
            if stop_at_class:
                # コメントと、属性の値の中の > を含むタグも、ブラウザと同じく文字に入れない（_markup_free・v2.20 / board_edit.py v1.16）
                text = html.unescape(_markup_free(block, bl, m.end(), end))
            else:
                text = html.unescape(_STRIP_TAGS_RE.sub("", block[m.end():end]))
            return text.replace("\r\n", "\n").replace("\r", "\n")
    return None


def _item_key(block):
    """item ブロックの key（board.js の key()・taskKey() と同一定義＝_key_text）。

    「時刻の欄の文字（前後の空白を除く）|タイトルの文字」の前後の空白を除いたもの（v2.14。v2.13 までは時刻の欄を
    _element_text で読み、空白を除かなかった）。
    """
    t = _key_text(block, "time", stop_at_class=True)
    ti = _key_text(block, "task-title")
    return ((t or "").strip() + "|" + (ti or "")).strip()


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


def _time_open_unclosed(block):
    """閉じていない時刻の欄の最初のもの（v2.14 / board_edit.py v1.10）。(開きタグの match, 読み終える位置) か、無ければ None。

    閉じていない＝欄の開きタグの後、欄の閉じタグ（欄を閉じるもの＝_time_match_close。v2.20 / board_edit.py v1.16 は同じ名前の開きと閉じを数えて決め、v2.21 / board_edit.py v1.17 からはブラウザの読み方で決める。
    v2.19 / board_edit.py v1.15 までは同じ名前の最初の閉じタグ）より前に class を持つ開きタグがある形。閉じタグの無い欄では block の終わりまでを見る
    （<span class="time">9:00 <span>a</span>x</div><p class="task-title">… の </span> は中の span を閉じるもので、欄は閉じていない。v1.15 までは
    欄が閉じたと読み、K15 に出さず、set-time は中の span の閉じタグまでを書き換えて後ろの文字を欄の外へ出した）。
    板の文字の上で閉じタグが無い形を見るので、ブラウザの画面の側では2つに分かれる（_time_screen_closed・v2.16 / board_edit.py v1.12）:
    欄の範囲がその開きタグより後ろまで続く形では、ブラウザはその要素を欄の中に取り込む（board.js の data-tb-unclosed・「ボードの点検」の⑥も
    数える）。欄の範囲がその開きタグ以前で終わる形（<p class="time">9:00<div><p class="task-title">… や、<div><span class="time">9:00</div>
    <p class="task-title">…）では、ブラウザは欄をその手前で閉じ、欄の中に class を持つ要素は入らない——画面は正しく、board.js は DOM しか
    見られないので⑥には出ない。それでも閉じていないと数えるのは、欄の閉じタグまでを欄として書き換える set-time
    （_replace_element_inner）が、閉じタグの無い欄では後ろのタイトルやチップまで消すため。時刻の欄が2つ以上ある行では、どの欄も見る（board_edit.py の
    警告 K15 もこれで見る）。"""
    bl = _blank_markup(block)
    for m in _CLASS_TAG_RE.finditer(block):
        if "time" in m.group(2).split() and bl[m.start()] == "<":    # ブラウザが要素として読まない所（コメント〔<! ・<? で始まる形と、</ の後に英字が続かない形を含む〕・属性の値・閉じタグまでを文字として読む要素の中身〔svg・math の要素として読むもの（<svg><style> など）を除く。foreignObject など HTML として読む所の中のものは除かない〕・svg・math の中の CDATA）のタグは欄ではない
            end = _time_match_close(block, m)
            stop = _KEY_STOP_RE.search(bl, m.end(), len(block) if end is None else end)
            if stop:
                return m, stop.start()
    return None


def _time_match_close(block, m):
    """欄（開きタグの match＝m。group(1) がタグ名）を閉じる閉じタグの位置（v2.20 / board_edit.py v1.16）。欄の開きタグから、ブラウザの HTML の
    構文解析と同じ順でタグを読み（_tag_walk の base）、欄を閉じたのが欄と同じ名前の閉じタグならその始まりを返す。見つからないか、欄を閉じたのが
    ほかのもの（外側の要素の閉じタグ・p を閉じる開きタグ）なら None（閉じタグの無い欄）。_time_range・_time_open_unclosed・_key_text・
    board_edit.py の set-time（_replace_element_inner）が使う。中で開いて閉じた同じ名前の要素の閉じタグ（<span class="time">9:00 <span>a</span>…）は
    欄を閉じない。ブラウザが要素として読まない所（コメント〔<! ・<? で始まる形と、</ の後に英字が続かない形を含む〕・属性の値の引用符の中・閉じタグまでを
    文字として読む要素の中身〔svg・math の要素として読むもの（<svg><style> など）を除く。foreignObject など HTML として読む所の中のものは除かない〕・svg・math の中の CDATA）は数えず（_blank_markup）、HTML の void でない要素の /> は開きタグと
    して数える（コメント・属性の値と /> の扱いは v2.20 / board_edit.py v1.16 から）。HTML として読む所（svg の foreignObject など）の中から書いた欄の
    閉じタグ（<svg><foreignObject></span>）と、欄が span など（_OWN_END_RULE に無い名前）のときに、間に special の要素がある欄の閉じタグ（<span class="time">0:00 <p>x</span>）は、ブラウザと同じく欄を
    閉じない（_tag_walk。v2.21 / board_edit.py v1.17。v2.20 / v1.16 までは同じ名前の開きと閉じの数だけで決め、閉じたと読んだ）。"""
    pos = _tag_walk(block, m.start(), None, outer=_open_stack(block, m.start()), p_closers=True, base=m.group(1).lower())[1]
    return pos if pos is not None and pos >= 0 else None


# コメントと、タグの属性の値の引用符の中（_blank_markup）
_MARKUP_TAG_RE = re.compile(r"""<(/?)[A-Za-z][^\t\n\f\r />]*(?:[^>"']|"[^"]*"|'[^']*')*>""")


# _blank_markup の結果を、同じ文字列について使い回す（最後の数個）
_BLANK_CACHE = {}


def _blank_markup(text):
    """ブラウザが要素として読まない所を空白にした、同じ長さの文字列（改行はそのまま。v2.20 / board_edit.py v1.16）。空白にするのは、コメントの中身・
    タグの属性の値の引用符の中・閉じタグまでを文字として読む要素（_SWALLOW_TAGS。閉じ方は _sw_text_end と同じ。svg・math の要素として読むもの〔<svg><style> など〕を除く）の中身・svg・math の中の
    <![CDATA[ … ]]> の中身（svg・math の要素の直下のもの。HTML として読む所の中の HTML の要素の直下では偽のコメント＝最初の > まで）。時刻の欄の読み方（_time_match_close・_time_open_unclosed・_key_text・_tag_walk）が、そこにあるタグ（<!-- </span> --> の
    </span>・title="</span>" の </span>・<script></span></script> の </span>）を数えないために使う。コメントは <!-- から --> か --!> まで
    （<!--> と <!---> はそこで閉じる。閉じなければ終わりまで）、<! ・<? ・</ に英字が続かない形は最初の > まで（偽のコメント）。
    svg・math の中かどうかは、svg・math の要素と抜けるタグ（_FOREIGN_BREAKOUT）・HTML として読む所だけを見て決める（_sw_scan より粗い。
    HTML として読む所の中の HTML の要素は数を持つだけで、名前は見ない。その数が 0 でないところ〔HTML として読む所の中の HTML の要素の直下〕の
    <![CDATA[ は CDATA ではなく偽のコメント＝ブラウザと同じ。v2.21 / board_edit.py v1.17）。--> と --!> は一度探した位置を持ち、通り過ぎたときだけ探し直す（_sw_scan と同じ。
    閉じないコメントが並ぶ形で遅くならないため）。同じ文字列は最後の数個を覚えて使い回す（_BLANK_CACHE。1つの行を何度も読むため）。"""
    hit = _BLANK_CACHE.get(text)
    if hit is not None:
        return hit
    out = []
    i = 0
    n = len(text)
    dash = text.find("-->")
    bang = text.find("--!>")
    fstack = []          # 開いている svg・math の要素 [名前, HTML として読む所か, その中で開いている HTML の要素の数]

    def blank(s):
        return re.sub(r"[^\r\n]", " ", s)

    while True:
        lt = text.find("<", i)
        if lt == -1:
            out.append(text[i:])
            break
        out.append(text[i:lt])
        if text.startswith("<!--", lt):
            if text.startswith(">", lt + 4) or text.startswith("->", lt + 4):
                e = lt + (5 if text.startswith(">", lt + 4) else 6)
                out.append(text[lt:e])
                i = e
                continue
            if dash != -1 and dash < lt + 4:
                dash = text.find("-->", lt + 4)
            if bang != -1 and bang < lt + 4:
                bang = text.find("--!>", lt + 4)
            ends = [x for x in (dash, bang) if x != -1]
            if not ends:
                out.append("<!--" + blank(text[lt + 4:]))
                break
            e = min(ends)
            close = 3 if text.startswith("-->", e) else 4
            out.append("<!--" + blank(text[lt + 4:e]) + text[e:e + close])
            i = e + close
            continue
        if fstack and not fstack[-1][2] and text.startswith("<![CDATA[", lt):
            # CDATA は、いまの要素が svg・math の要素のときだけ（HTML として読む所の中の HTML の要素の直下では偽のコメント。v2.21 / board_edit.py v1.17）
            e = text.find("]]>", lt + 9)
            if e == -1:
                out.append("<![CDATA[" + blank(text[lt + 9:]))
                break
            out.append("<![CDATA[" + blank(text[lt + 9:e]) + "]]>")
            i = e + 3
            continue
        tm = _MARKUP_TAG_RE.match(text, lt)
        if tm:
            out.append(re.sub(r"""("[^"]*"|'[^']*')""", lambda q: q.group(0)[0] + blank(q.group(0)[1:-1]) + q.group(0)[-1], tm.group(0)))
            i = tm.end()
            name = _SW_TAG_RE.match(text, lt).group(2).lower()
            selfc = tm.group(0).endswith("/>")
            foreign = bool(fstack) and not fstack[-1][1]
            if tm.group(1):
                if fstack and fstack[-1][2]:
                    fstack[-1][2] -= 1      # HTML として読む所の中の HTML の要素を閉じる（名前は見ない＝粗い）
                    continue
                for k in range(len(fstack) - 1, -1, -1):
                    if fstack[k][0] == name:
                        del fstack[k:]
                        break
                continue
            if foreign and name in _FOREIGN_BREAKOUT:
                while fstack and not fstack[-1][1]:
                    fstack.pop()
                foreign = bool(fstack) and not fstack[-1][1]
            if foreign or name in ("svg", "math"):
                if not selfc:
                    fstack.append([name, name in _SVG_POINTS or (name in _MATH_POINTS and name != "annotation-xml"), 0])
                continue
            if fstack and name not in _SWALLOW_TAGS and name not in _VOID_TAGS:
                fstack[-1][2] += 1          # HTML として読む所の中の HTML の要素（その中の <![CDATA[ は CDATA ではない）
            if name in _SWALLOW_TAGS:
                r = _sw_text_end(text, i, name)
                if r is None:
                    out.append(blank(text[i:]))
                    break
                c = text.rfind("</", i, r[0])
                out.append(blank(text[i:c]) + text[c:r[0]])
                i = r[0]
            continue
        if text.startswith("<!", lt) or text.startswith("<?", lt) or (text.startswith("</", lt) and not text[lt + 2:lt + 3].isalpha()):
            e = text.find(">", lt + 2)
            if e == -1:
                out.append(text[lt:lt + 2] + blank(text[lt + 2:]))
                break
            out.append(text[lt:lt + 2] + blank(text[lt + 2:e]) + ">")
            i = e + 1
            continue
        out.append("<")
        i = lt + 1
    res = "".join(out)
    if len(_BLANK_CACHE) >= 8:
        _BLANK_CACHE.clear()
    _BLANK_CACHE[text] = res
    return res


def _markup_free(text, blanked, a, b):
    """text[a:b] から、blanked（_blank_markup）で見たタグとコメントを除いた文字（v2.20 / board_edit.py v1.16。時刻の欄の鍵の文字）。
    svg・math の中の <![CDATA[ … ]]> は、ブラウザと同じく中身を文字として残す（印の <![CDATA[ と ]]> だけを除く）。"""
    out = []
    pos = a
    for t in _STRIP_TAGS_RE.finditer(blanked, a, b):
        out.append(text[pos:t.start()])
        if blanked.startswith("<![CDATA[", t.start()) and blanked.startswith("]]>", t.end() - 3):
            out.append(text[t.start() + 9:t.end() - 3])
        pos = t.end()
    out.append(text[pos:b])
    return "".join(out)


# ブラウザが閉じた後の文字の前に開き直す書式の要素（HTML の構文解析の formatting elements。_time_screen_closed・_time_reopened・v2.16 / board_edit.py v1.12。
# 14種とも開き直すことを Chrome で確かめた＝2026-11-10・Reviewer・1種を1行1ページ・n=1）
_FORMATTING_TAGS = frozenset(("a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike", "strong", "tt", "u"))
# 中で開いていると、ブラウザが外側の要素の閉じタグで時刻の欄を閉じない要素（_time_screen_closed・_time_reopened・v2.16 / board_edit.py v1.12）。
# 名前は _time_inner_open と同じく小文字（foreignObject も foreignobject）。3種類ある:
#   ・スコープの境界になる要素: table・object・marquee・template・applet（ブラウザは中で外側の閉じタグを読み飛ばす。select も読み飛ばす）
#   ・MathML・SVG の中に HTML を入れる所: mi・mo・mn・ms・mtext・annotation-xml（MathML）・foreignobject・desc（SVG）
#     （_time_keeps_open が、math・svg の要素として読まれたものだけを数える＝_tag_walk・v2.19 / board_edit.py v1.15。<math>・<svg> の外にそのまま
#     書いたもの・svg・math の中から抜ける HTML のタグの後ろに書いたもの〔<svg><span><desc>〕は HTML の要素で、ブラウザは外側の閉じタグで欄を閉じる。
#     Chrome で確かめた＝2026-11-10・Reviewer・n=1、抜ける形は Chrome と Edge で 2026-11-13・各 n=1）
#   ・閉じタグまでを文字として読む要素: textarea・script・style・xmp・iframe・noembed・noframes・noscript・plaintext・title
#     （HTML の要素として読まれたものだけを数える＝_KEEP_OPEN_HTML・v2.19 / board_edit.py v1.15。<svg><title> は SVG の境界として数え、欄を閉じない）
# Chrome で確かめた（1種を1行1ページ・n=1）＝table・select・textarea（2026-11-10・Reviewer）、object・marquee・template・applet・<math><mi>・
# <svg><foreignObject>・script・style・xmp・iframe・noembed・noframes・noscript・plaintext・title（同日・Reviewer）、
# <math><mo>・<math><mn>・<math><ms>・<math><mtext>・<math><annotation-xml>・<svg><desc>・<svg><title>（同日・Reviewer）
_KEEP_OPEN_TAGS = frozenset(("table", "select", "object", "marquee", "template", "applet",
                             "mi", "mo", "mn", "ms", "mtext", "annotation-xml", "foreignobject", "desc",
                             "textarea", "script", "style", "xmp", "iframe", "noembed", "noframes", "noscript", "plaintext", "title"))
# MathML・SVG の要素のうち、HTML の構文解析でスコープの境界になるもの（中では外側の閉じタグを読み飛ばす＝_time_keeps_open・_tag_walk）。
# SVG の title は v2.19 / board_edit.py v1.15 で足した（v2.18 までは _KEEP_OPEN_TAGS の title を名前だけで見て、<svg><title> も数えていた）
_MATH_POINTS = frozenset(("mi", "mo", "mn", "ms", "mtext", "annotation-xml"))
_SVG_POINTS = frozenset(("foreignobject", "desc", "title"))
# 上のうち HTML の要素として数えるもの（_KEEP_OPEN_TAGS から MathML・SVG の要素を除き、HTML の title〔閉じタグまでを文字として読む〕を残す）
_KEEP_OPEN_HTML = (_KEEP_OPEN_TAGS - _MATH_POINTS - _SVG_POINTS) | frozenset(("title",))


def _time_keeps_open(inner):
    """_time_inner_stack の結果（外側から順の (名前, 名前空間, HTML として読む所か, 境界か)）に、ブラウザが外側の閉じタグで時刻の欄を
    閉じなくなる要素があるか（v2.16 / board_edit.py v1.12。名前空間で見るのは v2.19 / board_edit.py v1.15）。HTML の要素は _KEEP_OPEN_HTML
    （table・object・script・title など）。MathML・SVG の要素は、HTML の構文解析でスコープの境界になるもの（MathML の mi・mo・mn・ms・mtext・
    annotation-xml、SVG の foreignObject・desc・title＝_MATH_POINTS・_SVG_POINTS。4つ目が真）。math・svg の中から抜ける HTML のタグ
    （_FOREIGN_BREAKOUT・</p>・</br>）の後ろの mi・desc などは HTML の要素なので数えず（<svg><span><desc>x）、svg・math の中の textarea・style
    なども svg・math の要素なので数えない（<svg><textarea>x。v2.18 / board_edit.py v1.14 までは名前だけで見て、どちらも数えた）。"""
    for name, ns, _point, boundary in inner:
        if (name in _KEEP_OPEN_HTML) if ns == "html" else boundary:
            return True
    return False


def _time_screen_closed(block, hit):
    """閉じていない時刻の欄（hit＝_time_open_unclosed の戻り値）を、ブラウザが class を持つ開きタグ以前で閉じるか（v2.16 / board_edit.py v1.12）。
    閉じるなら、その位置（欄の範囲〔_time_range〕の中身の終わり）、閉じなければ None。

    閉じる形では、ブラウザの欄の中に class を持つ要素は入らず、画面は正しい（board.js は DOM しか見られないので、「ボードの点検」の⑥には
    出ない）。この位置はブラウザが自分で欄を閉じる位置（外側の要素の閉じタグか、p を閉じる開きタグの手前）なので、ここに閉じタグを補っても
    ブラウザの DOM は変わらない（_time_range がブラウザと違う所で閉じる形〔_implied_close の注釈〕を除く。_time_close_at はこの位置の手前の
    空白を除いた所に補うので、その空白だけが欄の外へ出る）。
    欄そのものが書式の要素（<b class="time">…＝_FORMATTING_TAGS）の行と、欄の中に閉じていない書式の要素がある行（<span class="time">9:00 <b>am</div>…）は
    None（画面が正しくないため。ブラウザは欄を閉じた後で書式の要素を開き直し、後ろのタイトルやチップをその要素で包む。前者は class="time" ごと
    開き直すので、欄が増えてタイトルも欄の中に入る＝⑥にも出る。後者は _time_reopened。Chrome で確かめた＝2026-11-10・Reviewer・書式の要素14種・
    1種を1行1ページ・n=1）。欄の中で table・object・script など（_KEEP_OPEN_HTML）か、MathML・SVG のスコープの境界の要素（math の mi・svg の
    foreignObject など）が閉じていない行も None（ブラウザは外側の閉じタグで欄を閉じないので、タイトルやチップも欄の中に入るか、文字として読まれる＝
    _time_keeps_open。試した要素は _KEEP_OPEN_TAGS の注釈）。svg・math の中は名前空間で読む（_time_inner_stack・v2.19 / board_edit.py v1.15）。"""
    m, stop = hit
    if m.group(1).lower() in _FORMATTING_TAGS:
        return None
    r = _time_range(block, m)
    if r is None or r[1] > stop:
        return None
    inner = _time_inner_stack(block, m.end(), r[1])
    if _time_keeps_open(inner) or any(ns == "html" and name in _FORMATTING_TAGS for name, ns, _p, _b in inner):
        return None
    return r[1]


def _time_reopened(block, hit):
    """閉じていない時刻の欄（hit＝_time_open_unclosed の戻り値）で、ブラウザが欄を class を持つ開きタグ以前で閉じるが、欄の中に閉じていない
    書式の要素があるので、閉じた後でその要素を開き直す行か（v2.16 / board_edit.py v1.12。<span class="time">9:00 <b>am</div><p class="task-title">…）。
    画面では後ろのタイトルやチップがその書式で表示され、board.js の欄の中には class を持つ要素が入らない（⑥には出ない）。ブラウザが欄を
    閉じる位置に、中で閉じていない要素の閉じタグ（書式の要素を含む）と欄の閉じタグを足すと、書式の要素は開き直されなくなり、タイトルや
    チップを包んでいた書式が外れる（行の鍵は変わらない。Chrome で確かめた＝2026-11-10・Reviewer・18通り・n=1）。画面が変わるので、
    _time_close_at は reopen が真のとき（board_edit.py の close-time --confirmed）だけ補い、それ以外は "format" を返す。欄そのものが書式の
    要素の行と、欄の中に table・object・script など・MathML・SVG のスコープの境界の要素がある行（_time_keeps_open）は含めない（_time_screen_closed の注釈）。
    書式の要素は HTML の要素だけを数える（svg の中の <a> は svg の要素。math・svg の中から抜けた <b> は HTML の要素＝<math><b><mi>x も
    この形。Chrome と Edge で確かめた＝2026-11-13・各 n=1。v2.19 / board_edit.py v1.15）。"""
    m, stop = hit
    if m.group(1).lower() in _FORMATTING_TAGS:
        return False
    r = _time_range(block, m)
    if r is None or r[1] > stop:
        return False
    inner = _time_inner_stack(block, m.end(), r[1])
    if _time_keeps_open(inner):
        return False
    return any(ns == "html" and name in _FORMATTING_TAGS for name, ns, _p, _b in inner)


def _time_inner_open(block, start, end):
    """start から end までに開いて、end でまだ閉じていない要素の名前（外側から順。v2.16 / board_edit.py v1.12。_time_close_at が足す閉じタグ）。
    数え方は _time_inner_stack（名前だけを返す）。"""
    return [x[0] for x in _time_inner_stack(block, start, end)]


def _time_inner_stack(block, start, end):
    """start から end までに開いて、end でまだ閉じていない要素（外側から順の (名前, 名前空間, HTML として読む所か, 境界か)。v2.19 / board_edit.py v1.15。
    v2.16〜v2.18 / board_edit.py v1.12〜v1.14 の _time_inner_open が名前だけで数えていたもの）。読み方は _tag_walk（p を閉じる開きタグの扱いを付ける）。
    void 要素は数えず（HTML の void でない要素の /> は開きタグ＝v2.20 / board_edit.py v1.16）、開いていない要素の閉じタグは読み飛ばす。p を閉じる開きタグ（_P_CLOSERS）が来たら、開いている p を
    そこで閉じたことにする（ブラウザと同じ。<span class="time">9:00 <p>a<p>b</div> の2つ目の <p> は1つ目を閉じる）。"""
    return _tag_walk(block, start, end, p_closers=True)[0]


# HTML の構文解析の special の要素（HTML の要素のうち、_tag_walk で「ほかの閉じタグ」〔_OWN_END_RULE に無い名前〕が越えられないもの。v2.21 /
# board_edit.py v1.17。<span class="time">0:00 <p>x</span> の </span> は p に遮られて読み飛ばされる）
_HTML_SPECIAL = frozenset(("address", "applet", "area", "article", "aside", "base", "basefont", "bgsound", "blockquote", "body", "br", "button",
                           "caption", "center", "col", "colgroup", "dd", "details", "dir", "div", "dl", "dt", "embed", "fieldset", "figcaption",
                           "figure", "footer", "form", "frame", "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr",
                           "html", "iframe", "img", "input", "keygen", "li", "link", "listing", "main", "marquee", "menu", "meta", "nav", "noembed",
                           "noframes", "noscript", "object", "ol", "p", "param", "plaintext", "pre", "script", "search", "section", "select",
                           "source", "style", "summary", "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "title", "tr",
                           "track", "ul", "wbr", "xmp"))
# 閉じタグに自分の決まりがある名前。範囲（scope）の中に同じ名前の HTML の要素があるときだけ、その要素まで閉じる（範囲の境界＝applet・caption・html・table・td・th・marquee・object・template と、MathML・SVG の HTML として読む所。p はボタンの範囲、li はリストの項目の範囲）。無ければ読み飛ばす
_OWN_END_RULE = frozenset(("address", "article", "aside", "blockquote", "button", "center", "details", "dialog", "dir", "div", "dl", "fieldset",
                           "figcaption", "figure", "footer", "header", "hgroup", "listing", "main", "menu", "nav", "ol", "pre", "search", "section",
                           "summary", "ul", "form", "p", "li", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "a", "b", "big", "code", "em", "font",
                           "i", "nobr", "s", "small", "strike", "strong", "tt", "u", "applet", "marquee", "object", "br", "template", "body", "html"))
# 範囲（scope）の境界になる HTML の要素（_OWN_END_RULE の閉じタグが越えない。v2.21 / board_edit.py v1.17。MathML・SVG の境界は _tag_walk の区間で見る）
_SCOPE_BOUNDS = frozenset(("applet", "caption", "html", "table", "td", "th", "marquee", "object", "template"))
# 見出し（閉じタグは、範囲の中にあるどの見出しでも閉じる＝_tag_walk。v2.21 / board_edit.py v1.17）
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


# _tag_walk の結果を、同じ引数について使い回す（最後の数十個。1つの行を何度も読むため＝v2.21 / board_edit.py v1.17）
_WALK_CACHE = {}


def _tag_walk(block, start, end=None, outer=None, p_closers=False, base=None):
    """_tag_walk_once の結果を、同じ引数について使い回す（並びは写しを返す）。読み方は _tag_walk_once。"""
    key = (block, start, end, None if outer is None else tuple(outer), p_closers, base)
    hit = _WALK_CACHE.get(key)
    if hit is None:
        if len(_WALK_CACHE) >= 32:
            _WALK_CACHE.clear()
        hit = _WALK_CACHE[key] = _tag_walk_once(block, start, end, outer, p_closers, base)
    return list(hit[0]), hit[1]


def _tag_walk_once(block, start, end=None, outer=None, p_closers=False, base=None):
    """block の start から end（None なら終わり）までのタグを、ブラウザの HTML の構文解析と同じ順で読み、開いている要素の並びを返す
    （v2.19 / board_edit.py v1.15。時刻の欄の読み方＝_time_inner_stack・_implied_close）。(並び, 位置) を返す。並びは外側から順の
    (名前〔小文字〕, 名前空間〔"html"・"svg"・"math"〕, HTML として読む所〔integration point〕か, スコープの境界か)。位置は、outer（start より
    外側で開いている HTML の要素の名前＝_open_stack）のどれかを閉じる閉じタグの位置で、そこで読むのをやめる。無ければ None。

    svg・math の中（foreign content）は _sw_scan（K16）と同じ決まりで読む: svg・math の中で _FOREIGN_BREAKOUT の開きタグ（font は color・face・
    size の属性があるときだけ）か </p>・</br> が来たら、svg・math を閉じて HTML として読む。HTML として読む所（svg の foreignObject・desc・title、
    math の mi・mo・mn・ms・mtext、encoding が text/html か application/xhtml+xml の annotation-xml）の中の開きタグは HTML の要素。閉じタグは、
    上から svg・math の要素を同じ名前まで探して閉じ、HTML の要素に当たったら HTML の決まりで探す——そのときスコープの境界（_MATH_POINTS・
    _SVG_POINTS の要素）を越えない（<svg><foreignObject><span>x</svg> の </svg> と、その後の外側の閉じタグは読み飛ばす）。
    HTML の要素は、void 要素を開いたものに数えず、開いていない要素の閉じタグは読み飛ばす。HTML の void でない要素の /> は、ブラウザと同じく開きタグ
    として数え、ブラウザが要素として読まない所（コメント〔<! ・<? で始まる形と、</ の後に英字が続かない形を含む〕・属性の値・閉じタグまでを文字として読む要素の中身〔svg・math の要素として読むもの（<svg><style> など）を除く。foreignObject など HTML として読む所の中のものは除かない〕・svg・math の中の CDATA）のタグは
    読まない（_blank_markup。この2つは v2.20 / board_edit.py v1.16。閉じていない textarea・script などは後ろをすべて文字として読み、K16 が知らせる）。
    なぞらない所: 表の foster parenting・書式の要素の付け直しなど木を組み立てる段階の細部。
    並びは、名前空間の同じ要素が続く区間（parts）ごとに名前の数を持ち、閉じタグの名前が区間に無ければ辿らない（_sw_scan の segs と同じ。
    境界の中で HTML の要素が深く入れ子になった形で、閉じタグごとに並びを辿り直して遅くならないため）。HTML の要素の区間のすぐ下は、必ず
    HTML として読む所（境界）の要素になる（HTML の要素は、HTML の要素か HTML として読む所の中にしか積まれない）。
    HTML の閉じタグのうち、自分の決まりを持たない名前（_OWN_END_RULE に無いもの。span など）は、上から同じ名前の要素を探す途中に special の要素
    （_HTML_SPECIAL。p・div・table など）があれば読み飛ばす（ブラウザの「ほかの閉じタグ」の決まり。v2.21 / board_edit.py v1.17。
    <span class="time">0:00 <p>x</span> の </span> は欄を閉じない）。そのため、HTML の要素の名前ごとの位置（idx）と special の要素の位置（specials）を持つ。
    base（欄のタグの名前）を渡すと、start の開きタグを並びの一番下に置いて読み、それが閉じたところで (並び, 位置) を返す——位置は、閉じたのが
    同じ名前の閉じタグならその始まり、ほかの理由（p を閉じる開きタグ・outer の閉じタグ）なら None（_time_match_close）。"""
    src = block
    block = _blank_markup(block)    # ブラウザが要素として読まない所（コメント〔<! ・<? で始まる形と、</ の後に英字が続かない形を含む〕・属性の値・閉じタグまでを文字として読む要素の中身〔svg・math の要素として読むもの（<svg><style> など）を除く。foreignObject など HTML として読む所の中のものは除かない〕・svg・math の中の CDATA）のタグは読まない（v2.20 / board_edit.py v1.16）
    stack = []
    parts = []          # [HTML の区間か, 名前ごとの数, 要素の数, 境界の数]（parts[-1] が stack の一番上の区間）
    idx = {}            # HTML の要素の名前 → stack の中の位置（昇順）
    specials = []       # stack の中の special の HTML の要素の位置（昇順）
    bounds = []         # stack の中の範囲の境界（_SCOPE_BOUNDS）の位置（昇順）
    buttons = []        # stack の中の button の位置（p のボタンの範囲）
    lists = []          # stack の中の ol・ul の位置（li のリストの項目の範囲）

    def out_of_scope(name, k):
        # _OWN_END_RULE の閉じタグ（と p を閉じる開きタグ）が、位置 k の同じ名前の要素まで届かないか（k が -1 なら、ここで開いた要素の中に境界があるか）
        return bool((bounds and bounds[-1] > k) or (name == "p" and buttons and buttons[-1] > k)
                    or (name == "li" and lists and lists[-1] > k))

    def push(item):
        html = item[1] == "html"
        if not parts or parts[-1][0] != html:
            parts.append([html, {}, 0, 0])
        p = parts[-1]
        p[1][item[0]] = p[1].get(item[0], 0) + 1
        p[2] += 1
        p[3] += item[3]
        if item[1] == "html":
            idx.setdefault(item[0], []).append(len(stack))
            if item[0] in _HTML_SPECIAL:
                specials.append(len(stack))
            if item[0] in _SCOPE_BOUNDS:
                bounds.append(len(stack))
            if item[0] == "button":
                buttons.append(len(stack))
            if item[0] in ("ol", "ul"):
                lists.append(len(stack))
        stack.append(item)

    def pop_to(k):
        while len(stack) > k:
            item = stack.pop()
            p = parts[-1]
            p[1][item[0]] -= 1
            p[2] -= 1
            p[3] -= item[3]
            if not p[2]:
                parts.pop()
            if item[1] == "html":
                idx[item[0]].pop()
                for lst in (specials, bounds, buttons, lists):
                    if lst and lst[-1] == len(stack):
                        lst.pop()

    def pop_foreign_run():
        # 一番上の svg・math の要素を、HTML の要素か HTML として読む所まで閉じる（抜ける開きタグ・</p>・</br>）
        k = len(stack)
        while k and stack[k - 1][1] != "html" and not stack[k - 1][2]:
            k -= 1
        pop_to(k)

    def find_in_part(name, html):
        # 一番上の区間の中で、上から最初の name の位置
        k = len(stack) - 1
        while stack[k][0] != name or (stack[k][1] == "html") != html:
            k -= 1
        return k

    for t in _TAG_TOKEN_RE.finditer(block, start, len(block) if end is None else end):
        name = t.group(2).lower()
        top = stack[-1] if stack else None
        if t.group(1):
            if name in ("p", "br") and top is not None and top[1] != "html":
                pop_foreign_run()
                if name == "br":
                    continue                    # </br> は <br>（void）として読む
            if parts and not parts[-1][0]:
                if parts[-1][1].get(name):
                    pop_to(find_in_part(name, False))   # svg・math の要素を閉じる
                    continue
                if parts[-1][3]:
                    continue                    # HTML の決まりで探すと、境界を越えられない（読み飛ばす）
                hp, below = (parts[-2], len(parts) > 2) if len(parts) > 1 else (None, False)
            else:
                hp, below = (parts[-1], len(parts) > 1) if parts else (None, False)
            own = name in _OWN_END_RULE
            blocked = not own and specials      # 「ほかの閉じタグ」は special の要素を越えない
            if name in _HEADINGS:
                # 見出しの閉じタグは、範囲の中にあるどの見出し（h1〜h6）でも閉じる（HTML の構文解析の決まり。<h2 class="time">9:00</h1> は欄を閉じる）
                ks = [idx[h][-1] for h in _HEADINGS if hp is not None and hp[1].get(h)]
                if ks:
                    k = max(ks)
                    if out_of_scope(name, k):
                        continue
                    closed = stack[k][0]
                    pop_to(k)
                    if base is not None and not stack:
                        return stack, (t.start() if closed == base else None)
                    continue
            if hp is not None and hp[1].get(name):
                k = idx[name][-1]
                if blocked and specials[-1] > k:
                    continue                    # 同じ名前の要素より上に special の要素がある（読み飛ばす）
                if own and out_of_scope(name, k):
                    continue                    # 同じ名前の要素が範囲の外にある（読み飛ばす）
                pop_to(k)
                if base is not None and not stack:
                    return stack, (t.start() if name == base else None)
                continue
            if below or blocked or (own and out_of_scope(name, -1)):
                continue                        # HTML の要素の区間のすぐ下は境界・special の要素や範囲の境界を越えない（読み飛ばす）
            if outer is not None and name in outer:
                return stack, (None if base is not None else t.start())
            continue
        foreign = top is not None and top[1] != "html" and not top[2]
        if foreign and (name in _FOREIGN_BREAKOUT or (name == "font" and re.search(r"[\s/](?:color|face|size)(?=[\s/=>])", t.group(0), re.I))):
            pop_foreign_run()
            top = stack[-1] if stack else None
            foreign = False
        if top is not None and top[1] == "math" and top[2] and top[0] != "annotation-xml" and name in ("mglyph", "malignmark"):
            foreign = True                      # math の mi などの中の mglyph・malignmark は math の要素
        if foreign or name in ("svg", "math"):
            if not t.group(3):
                ns = name if name in ("svg", "math") else top[1]
                point = ((ns == "svg" and name in _SVG_POINTS) or (ns == "math" and name in _MATH_POINTS and name != "annotation-xml")
                         or (ns == "math" and name == "annotation-xml"
                             and re.search(r"""\sencoding\s*=\s*["']?(?:text/html|application/xhtml\+xml)["'\s/>]""", src[t.start():t.end()], re.I)))
                boundary = name in (_SVG_POINTS if ns == "svg" else _MATH_POINTS)
                push((name, ns, bool(point), boundary))
            continue
        if p_closers and name in _P_CLOSERS and parts and parts[-1][0] and parts[-1][1].get("p") and not out_of_scope("p", idx["p"][-1]):
            pop_to(idx["p"][-1])
            if base is not None and not stack:
                return stack, -1 - t.start()    # 欄の p を、後ろの p を閉じる開きタグが閉じた（欄の閉じタグではない。位置は -1 - 開きタグの始まり）
        if name not in _VOID_TAGS:
            push((name, "html", False, False))      # HTML の void でない要素の /> は開きタグ（ブラウザは / を読み捨てる。v2.20 / board_edit.py v1.16）
    return stack, None


def _time_close_at(block, reopen=False):
    """閉じていない時刻の欄に閉じタグを補う位置（v2.14 / board_edit.py v1.10。board_edit.py の close-time と、Deck の日付の切り替え）。

    (位置, 足す閉じタグの文字列〔ふつうは "</タグ名>"〕) か、補えない理由: "none"（閉じていない欄が無い）・"div"（欄が div）・"after"（時刻の文字の後ろ、class を
    持つタグより前にタグで囲んだ文字がある＝補うと欄の外へ出て鍵が変わる）・"text"（欄の始まりの直後に時刻の文字が無い）・
    "count"（欄と同じ名前のタグの開きと閉じの数が、1つ足して合う形でない）・"format"（下の _time_reopened）。位置は時刻の文字（後ろの空白を除く）の直後。
    ただし、ブラウザが欄を class を持つ開きタグ以前で閉じる形（_time_screen_closed）では、ブラウザが閉じる位置（その手前の空白を除く）に補い、
    "div"・"after"・"text"・"count" は見ない（補っても画面と行の鍵は変わらず、DOM で変わるのは欄の終わりの空白が欄の外へ出ることだけのため。
    v2.16 / board_edit.py v1.12。v2.15 / board_edit.py v1.11 までは
    この形でも時刻の文字の直後に補い、時刻の文字の後ろにタグで囲んだ文字がある形〔<p class="time">9:00 <b>am</b><div>…・
    <div><span class="time">9:00 <span>am</div>…・<div><span class="time">9:00</div>am <p class="task-title">…〕は "after"、欄に時刻の文字が無い形
    〔<div><span class="time">  </div>…〕は "text" で断った）。欄の中で開いて閉じていない要素（<span class="time">9:00 <span>am</div> の <span>）が
    あれば、その閉じタグも内側から順に足す（ブラウザはその位置でそれらも閉じる。数え方は _time_inner_open）。
    欄そのものが書式の要素の行と、欄の中で table・object・script などが閉じていない行はこの扱いをせず、上の判定に戻る（_time_screen_closed が
    None）。欄の中に閉じていない書式の要素がある行（_time_reopened）は、reopen が真なら同じ位置に同じく補い（書式の要素の閉じタグも足すので、
    タイトルやチップを包んでいた書式が外れ、画面が変わる。board_edit.py の close-time --confirmed）、偽なら "format" を返す（Deck の日付の
    切り替えは偽で呼び、補わずに欄を外す。外す範囲に書式の要素の開きタグが入るので、同じく書式が外れる）。"""
    hit = _time_open_unclosed(block)
    if hit is None:
        return "none"
    m, stop = hit
    tag = m.group(1)
    shown = _time_screen_closed(block, hit)
    if shown is not None:
        pos = m.end() + len(block[m.end():shown].rstrip())
        return pos, "".join("</%s>" % name for name in reversed(_time_inner_open(block, m.end(), pos))) + "</%s>" % tag
    if _time_reopened(block, hit):
        if not reopen:
            return "format"
        r = _time_range(block, m)
        pos = m.end() + len(block[m.end():r[1]].rstrip())
        return pos, "".join("</%s>" % name for name in reversed(_time_inner_open(block, m.end(), pos))) + "</%s>" % tag
    if tag.lower() == "div":
        return "div"
    region = block[m.end():stop]
    lt = region.find("<")
    text = (region if lt == -1 else region[:lt]).rstrip()
    if lt != -1 and html.unescape(_STRIP_TAGS_RE.sub("", region[lt:])).strip():
        return "after"
    if not text.strip():
        return "text"
    opens = len(re.findall(r"<%s\b[^>]*>" % re.escape(tag), block, re.I))
    closes = len(re.findall(r"</%s\s*>" % re.escape(tag), block, re.I))
    if opens != closes + 1:
        return "count"
    return m.end() + len(text), "</%s>" % tag


def _time_unclosed(block):
    return _time_open_unclosed(block) is not None


def block_close_time(blines, confirmed=False):
    """閉じタグの無い時刻の欄に閉じタグを補う（close-time・v1.10）。欄の時刻の文字（開きタグの直後から最初のタグの手前まで。
    後ろの空白は含めない）の直後に </タグ名> を1つ足す。その後ろ、class を持つタグより前に文字があれば（足すと欄の外へ出て
    行の鍵が変わるので）断る。ただし、ブラウザが欄を class を持つタグ以前で閉じる形（画面は正しい形＝_time_screen_closed）では、
    ブラウザが閉じる位置（その手前の空白を除く）に足し、この断り方はしない（v1.12。画面も鍵も変わらない。欄の中で開いて閉じていない要素が
    あれば、その閉じタグも足す）。書式の要素〔b・i・a など＝_FORMATTING_TAGS〕が欄の中で閉じていない行（_time_reopened）は、confirmed
    （--confirmed）のときだけ同じく補い（書式の要素の閉じタグも足すので、タイトルやチップを包んでいた書式が外れ、画面が変わる）、そうでなければ
    断る（"format"）。欄そのものが書式の要素の行と、欄の中で table・object・script などが閉じていない行はこの扱いをせず上の判定に戻る。
    補えない形なら OpError（断った後の扱いは SKILL.md「ボードの点検」の⑥）。"""
    block = "".join(blines)
    at = _time_close_at(block, reopen=confirmed)
    if at == "none":
        raise OpError("この項目の時刻の欄には閉じタグがあります（直すものはありません）。何も書いていません。")
    if at == "div":
        raise OpError("この項目の時刻の欄は div で、閉じタグが無いため、後ろの項目が中に入った形になっています。close-time では直せません。"
                      "何も書いていません。SKILL.md「ボードの点検」の①の直し方（restore）で直してください。")
    if at == "after":
        # 時刻の文字の後ろ、class を持つタグより前に文字がある（<b>am</b> など）。補うと欄の外へ出て鍵が変わるので断る
        raise OpError("この項目の時刻の欄には、時刻の文字の後ろにタグで囲んだ文字があり、閉じタグを足す位置を決められません。何も書いていません。"
                      "SKILL.md「ボードの点検」の①の直し方（restore）で直してください。")
    if at == "format":
        raise OpError("この項目の時刻の欄の中に閉じていない書式の要素（b・i など）があり、ブラウザは時刻の欄を閉じた後でその要素を開き直して、"
                      "後ろのタイトルやチップをその書式で表示しています。閉じタグを補うとその書式が外れ、画面が変わります（タスクの文言・状態・行の鍵は変わりません）。"
                      "何も書いていません。板のその行をユーザーに見せ、書式が外れてよいと確かめてから、--confirmed を付けてもう一度呼んでください。")
    if at == "text":
        raise OpError("この項目の時刻の欄の文字が、欄の始まりの直後に見つからないため、閉じタグを足す位置を決められません。何も書いていません。"
                      "ユーザーに時刻の欄の文字を確かめてください。")
    if at == "count":
        m, _stop = _time_open_unclosed(block)
        tag = m.group(1)
        opens = len(re.findall(r"<%s\b[^>]*>" % re.escape(tag), block, re.I))
        closes = len(re.findall(r"</%s\s*>" % re.escape(tag), block, re.I))
        raise OpError("この項目の <%s> と </%s> の数（%d と %d）が、閉じタグを1つ足して合う形ではありません。何も書いていません。"
                      "閉じタグが項目の終わりに置かれた形か、閉じタグのある欄の中に class を持つ要素がある形かもしれません。SKILL.md「ボードの点検」の⑥のとおり、restore するかをユーザーに確かめてください。" % (tag, tag, opens, closes))
    pos, close = at
    return (block[:pos] + close + block[pos:]).splitlines(keepends=True)


def op_close_time(text, nl, a):
    return _item_op(text, nl, a, lambda b: block_close_time(b, getattr(a, "confirmed", False)))


def _canon_label(label):
    for name in CANON_SECTIONS:
        if label.startswith(name):
            return name
    return None


# 閉じタグの無い要素がブラウザでどこまで続くか（_implied_close・v2.14 / board_edit.py v1.10。外側で開いていない閉じタグを読み飛ばすのと、
# p を後ろの block 要素の手前で閉じるのは v2.15 / board_edit.py v1.11）
_TAG_TOKEN_RE = re.compile(r'<(/?)([A-Za-z][\w-]*)\b[^>]*?(/?)>')
_VOID_TAGS = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"))
# p を閉じる開きタグ（HTML の構文解析で p を閉じる要素。互換モードに合わせて table は入れない＝board-template.html から作った板は doctype が無く
# 互換モードで開かれ、そこでは table は p を閉じない。手で doctype を足した板〔標準モード〕では table も p を閉じるので、その板の
# <p class="time">…<table> だけは画面と違う所で閉じる）。ブラウザがこれらの開きタグで p を閉じるのは、p が button scope にあるとき
# （欄の p と開きタグの間に button・表などの境界の要素が無いとき）で、ここではその前提を置いて調べない（手書きでしか生まれない形）
_P_CLOSERS = frozenset(("address", "article", "aside", "blockquote", "center", "dd", "details", "dialog", "dir", "div", "dl", "dt",
                        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr",
                        "li", "listing", "main", "menu", "nav", "ol", "p", "plaintext", "pre", "search", "section", "summary", "ul", "xmp"))


def _open_stack(block, upto):
    """block の先頭から upto までに開いて、まだ閉じていない要素の名前の並び（外側から順。v2.15 / board_edit.py v1.11）。
    /> の要素も開きタグとして数え、ブラウザが要素として読まない所（コメント〔<! ・<? で始まる形と、</ の後に英字が続かない形を含む〕・属性の値・閉じタグまでを文字として読む要素の中身〔svg・math の要素として読むもの（<svg><style> など）を除く。foreignObject など HTML として読む所の中のものは除かない〕・svg・math の中の CDATA）のタグは読まない（v2.20 / board_edit.py v1.16）。"""
    stack = []
    for t in _TAG_TOKEN_RE.finditer(_blank_markup(block[:upto]), 0, upto):
        name = t.group(2).lower()
        if not t.group(1):
            if name not in _VOID_TAGS:      # /> の要素も開きタグ（v2.20 / board_edit.py v1.16。コメント・属性の値の中は読まない）
                stack.append(name)
        elif name in stack:
            while stack.pop() != name:
                pass
    return stack


def _implied_close(block, pos, outer=()):
    """閉じタグの無い要素の終わり（v2.14 / board_edit.py v1.10 で新設。outer と、開いていない閉じタグの読み飛ばしは v2.15 / board_edit.py v1.11）。pos（要素の開きタグの直後）から読み、外側で開いている要素（outer＝
    _open_stack）の閉じタグの位置を返す。無ければ None。ブラウザはそこで閉じタグの無い要素を閉じる。中で開いた要素の閉じタグは読み飛ばし、
    void 要素は開いたものに数えない（HTML の void でない要素の /> は開きタグ・ブラウザが要素として読まない所（コメント〔<! ・<? で始まる形と、</ の後に英字が続かない形を含む〕・属性の値・閉じタグまでを文字として読む要素の中身〔svg・math の要素として読むもの（<svg><style> など）を除く。foreignObject など HTML として読む所の中のものは除かない〕・svg・math の中の CDATA）のタグは読まない＝_tag_walk・v2.20 /
    board_edit.py v1.16）。中でも外側でも開いていない要素の閉じタグ（<span class="time">9:00</b>… の </b>）は、ブラウザと
    同じく読み飛ばす（v2.15 / board_edit.py v1.11。v2.14 はそこで閉じた）。svg・math の中は名前空間で読み、スコープの境界（math の mi・svg の
    foreignObject など）の中では外側の閉じタグを読み飛ばす（_tag_walk・v2.19 / board_edit.py v1.15。v2.18 / board_edit.py v1.14 までは
    <svg><foreignObject><span>x</svg></div> の </svg> で svg を閉じ、</div> で欄を閉じた。ブラウザはどちらも読み飛ばす）。
    ブラウザの構文解析のすべてをなぞるものではない——なぞるのはこれらと、_time_range の p の扱いだけで、表・書式要素の付け替えなど
    手書きでしか生まれない形は、画面と違う所で閉じることがある（例: 外側の閉じタグの後に欄と同じ名前の閉じタグがある
    <span class="time">9:00</div>tail</span></div> は、_time_range が同じ名前の閉じタグまでを欄とみなすので、画面より広くなる）。
    _remove_time_elements・_key_text が、閉じタグの無い時刻の欄を画面と同じ所までの欄として扱うために使う（board.js は DOM しか見られない
    ので、画面の側に合わせる）。"""
    return _tag_walk(block, pos, None, outer=outer)[1]


def _time_range(block, m):
    """時刻の欄（開きタグの match＝m。group(1) がタグ名）の、ブラウザが欄とみなす範囲（v2.15 / board_edit.py v1.11）。
    (中身の始まり, 中身の終わり, 要素の終わり) か、決まらなければ None。

    要素の終わりは、同じタグ名の開きと閉じを数えて決める（入れ子に強い）。閉じタグが見つからない要素は、ブラウザが閉じる所
    （外側の要素の閉じタグの手前＝_implied_close）まで。欄が p なら、その前に p を閉じる要素（div・li など＝_P_CLOSERS）が始まればその手前まで
    （ブラウザは p をそこで閉じる。互換モードの板に合わせた集合で、標準モードの板の table だけは違う＝_P_CLOSERS の前の注釈）。項目の閉じタグは項目の中にあるので、閉じタグの無い欄でもふつうは決まる。"""
    tag = m.group(1)
    inner_end = _time_match_close(block, m)
    end = None if inner_end is None else block.index(">", inner_end) + 1
    if end is None:
        end = inner_end = _implied_close(block, m.end(), _open_stack(block, m.start()))
        if end is None:
            return None
    if tag.lower() == "p":
        # 欄の p を、後ろの p を閉じる開きタグ（_P_CLOSERS）が閉じるか。ブラウザと同じく、欄の p がボタンの範囲の中にあるときだけ閉じる
        # （間に開いたままの button・範囲の境界〔table など〕があれば閉じない＝<p class="time">9:00 <button>a</p><p class="task-title">… は
        # タイトルも欄の中に入る。_tag_walk の base。v2.21 / board_edit.py v1.17。v2.20 / v1.16 までは範囲を見ずに最初の開きタグで閉じた）
        pos = _tag_walk(block, m.start(), inner_end, p_closers=True, base="p")[1]
        if pos is not None and pos < 0:
            end = inner_end = -1 - pos
    return m.end(), inner_end, end


def _time_text(block):
    """行の時刻の欄の文字（v2.15 / board_edit.py v1.11）。行の鍵の時刻の部分と同じ読み方（_key_text の stop_at_class）で、
    board.js の tbTimeText（✎ の data-orig・D&D の形作り）と同じ。時刻の欄が無ければ None。
    日付の切り替え・D&D の形作り・move・K14 など、時刻の欄の時刻を読む所はすべてこれで読む（v2.14 / v1.10 までは _element_text で
    最初の同じ名前の閉じタグまで読み、閉じタグの無い欄では後ろの文字〔チップの「未」など〕まで時刻の文字に入った）。"""
    return _key_text(block, "time", stop_at_class=True)


# 時刻の欄を外すとき、中にあれば外さない行の部品（タイトル・補足・チップの箱・チップ・項目。v2.14 / board_edit.py v1.10。_remove_time_elements）。
# class の書き方（空白・大文字・' の引用符・引用符なし）を問わない（ブラウザはどの書き方でも部品として扱う。_KEY_STOP_RE と同じ広さ）。
# class の値も大文字小文字を区別しない（board-template.html から作ったボードは doctype が無く互換モードで開かれ、ブラウザの class セレクタと
# CSS が class の値の大文字小文字を区別しないため。class="Chip" も部品＝board.js の tbTimeHasPart と同じ。tbTimeHasPart は class の値を
# 小文字にそろえて比べるので、手で doctype を足した板〔標準モード〕でも同じ判定になる）
_ROW_PART_RE = re.compile(r'<\w+\b[^>]*?\sclass\s*=\s*["\']?(?:[^"\'>]*\s)?(?:task-title|task-note|chips|chip|item)(?=["\'\s>/])', re.I)


def _remove_time_elements(block):
    """class に time を持つ要素を、対応する閉じタグまで丸ごと外す。(外した後の文字列, 外した数) を返す。

    要素の範囲は _time_range（同じタグ名の開きと閉じを数えて決め、閉じタグが見つからない要素は、ブラウザが閉じる所＝外側の要素の閉じタグの
    手前まで。v2.14 / board_edit.py v1.10。board.js の画面と同じ欄になる。v2.13 までは外さずに数えなかった）。範囲が決まらない要素は外さずに
    数えない（項目の閉じタグは項目の中にあるので、ふつうは起きない。起きれば外した数が1にならず切り替えを止める）。
    要素の中に行の部品（タイトル・補足・チップの箱・チップ・項目＝_ROW_PART_RE）があるときも外さずに数えない
    （v2.14 / board_edit.py v1.10。閉じタグの無い欄の閉じが項目の終わりに置かれた形〔<span class="time">9:00 … </span></div>〕では、
    外すとタイトル・補足・チップが一緒に消えた。v2.13 までの日付の切り替え・D&D・move はそのまま外した）。呼ぶ側は外した数が
    1でなければ形を作らない（切り替えは止め、D&D・move は印だけを付けるか断る）。
    要素の前が空白だけなら、その空白と、要素の後ろの空白・改行1つも一緒に外す（行ごと消す）。
    """
    out = []
    pos = 0
    count = 0
    while True:
        m = _TIME_OPEN_RE.search(block, pos)
        if not m:
            break
        r = _time_range(block, m)     # ブラウザが欄とみなす範囲（閉じタグの無い欄は閉じる所まで・v2.14。p と読み飛ばす閉じタグは v2.15）
        end = inner_end = None
        if r is not None:
            _s, inner_end, end = r
        if end is None or _ROW_PART_RE.search(block, m.end(), inner_end):
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


def _insert_status_chip(block, nl):
    """状態チップが無い item に「未」を足す（chips の欄が無ければ欄ごと、内側の閉じの前に足す）。作れなければ None。"""
    for m in _SPAN_CLASS_RE.finditer(block):
        tokens = m.group(2).split()
        if "chip" in tokens and any(t in tokens for t in ("done", "active", "pending", "hold")):
            return block
    chip = '<span class="chip pending">未</span>'
    m = re.search(r'(<div class="chips"[^>]*>)(.*?)(</div>)', block, re.S)
    if m:
        return block[:m.end(2)] + chip + block[m.end(2):]
    last = block.rfind("</div>")
    inner = block.rfind("</div>", 0, last) if last != -1 else -1
    if inner == -1:
        return None
    ls = block.rfind("\n", 0, inner) + 1
    if block[ls:inner].strip():
        return block[:inner] + '<div class="chips">' + chip + "</div>" + block[inner:]
    ind = block[ls:inner]
    return block[:ls] + ind + '  <div class="chips">' + chip + "</div>" + nl + block[ls:]


def _div_balance(text):
    """コメントの外の <div の数 − </div> の数。"""
    blanked = "".join(_blank_comments(text.splitlines(keepends=True)))
    return len(re.findall(r"<div\b", blanked)) - blanked.count("</div>")


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


# board.js の読み込みの形（2026-11-10 ユーザー決定。テンプレートは head に defer で読む。migrate_board_js が末尾の形の板を移す）
_BOARD_JS_TAIL_RE = re.compile(r'[ \t]*<script src="board\.js"></script>[ \t\r\n]*\Z')
_BOARD_CSS_LINK = '<link rel="stylesheet" href="board.css">'
_BOARD_JS_HEAD = '<script src="board.js" defer></script>'


def migrate_board_js(text):
    """末尾の形の板（body の最後に <script src="board.js"></script> がある・2026-11-10 以前のテンプレート）を、head の形（board.css の
    読み込みの直後に <script src="board.js" defer></script>）へ移した本文を返す（Deck v2.18 / board_edit.py v1.14・2026-11-10 ユーザー決定）。
    移さないときは None。移すのは、その1行が文書の最後のタグで、board.css の読み込みがちょうど1つあり、head の形の読み込みがまだ無く、
    板が崩れていない（項目の入れ子・閉じタグの欠落〔board_structure_ok〕と K16〔_sw_scan の当たり〕が無く、board.js が実行される）とき。
    移した後も K16 に当たらず board.js が実行されることを確かめる。手書きの行・見出し・DECK 領域・ヘッダは変えないので、行の指紋
    （hand_fingerprint）と board_edit.py の K6〜K8・K17 は変わらない。head の板では、body の中の閉じていない要素などが後ろを飲み込んでも
    board.js は動き、ふつうは画面の「ボードの点検」の⑦（board.js の TB_CUT）に出る。"""
    m = _BOARD_JS_TAIL_RE.search(text)
    if not m or text.count(_BOARD_CSS_LINK) != 1 or _BOARD_JS_HEAD in text:
        return None
    hit, ran = _sw_scan(text)
    if hit is not None or not ran or not board_structure_ok(text.splitlines(keepends=True)):
        return None
    nl = "\r\n" if "\r\n" in text else "\n"
    body = text[:m.start()].rstrip(" \t\r\n") + nl
    i = body.index(_BOARD_CSS_LINK) + len(_BOARD_CSS_LINK)
    new = body[:i] + nl + _BOARD_JS_HEAD + body[i:]
    hit, ran = _sw_scan(new)
    if hit is not None or not ran:
        return None
    return new


def parse_due_value(value):
    """実施日の値（YYYY-MM-DD か YYYY-MM-DD H:MM）→ (date, "H:MM" か None)。読めなければ None。"""
    m = _DUE_VALUE_RE.match(value or "")
    if not m:
        return None
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    if m.group(4) is None:
        return d, None
    if int(m.group(4)) > 23 or int(m.group(5)) > 59:
        return None
    return d, "%d:%s" % (int(m.group(4)), m.group(5))


def _item_open_attr(block, name):
    """item の開始タグの属性 name の値（無ければ None）。"""
    m = _ITEM_OPEN_RE.search(block)
    if not m:
        return None
    a = re.search(r'\s%s="([^"]*)"' % re.escape(name), m.group(4))
    return a.group(1) if a else None


def _item_due_pending(block, today):
    """「明日以降」の行で、今日の側へ移す対象なら (date, "H:MM" か None)、そうでなければ None。

    実施日が今日以前・済でない・一度移した印（data-due-moved）が無い、の3つがそろうときだけ。
    印は日付の切り替えが移し直さないための印。今日の側の行を「明日以降」へ戻すときは実施日を決め直し、印は外れる
    （_later_due_shape・Deck v2.13・board_edit.py v1.9）ので、その行は決めた日に移る。印が付いたまま「明日以降」にあるのは、
    旧版（Deck v2.12 以前か due を送らない board.js の D&D・board_edit.py v1.8 以前の move）で戻した行と、印を写した行
    （add の --due-moved・spec の due_moved）で、それらは移し直さない。"""
    due = parse_due_value(_item_open_attr(block, "data-due"))
    if due is None or due[0] > today:
        return None
    if _CHIP_DONE_RE.search(block) or _item_open_attr(block, "data-due-moved") is not None:
        return None
    return due


def _later_time_conflict(block, due_time):
    """「明日以降」の行の時刻の欄が、実施日の時刻 due_time（"H:MM"）と違うなら、その時刻の欄の文字を返す（同じ・欄が無い・空なら None）。

    警告 K14（later_time_mismatches）が使う。v1.7 の set-time・set-due・add・create はこの食い違いを作らないが、v1.6 までに今日の側に
    できた食い違いの行を move・D&D で「明日以降」へ戻したときと、restore で v1.6 までの板を戻したときには残る。"""
    if not due_time:
        return None
    t = (_time_text(block) or "").strip()
    if not t or _norm_time(t) == _norm_time(due_time):
        return None
    return t


def _mark_due_moved(block, today):
    """「明日以降」から今日の側へ動かす行に、実施日が来ていれば一度移した印を付ける（どの経路で動かしても同じ印。日付の切り替えが
    移し直さないための印で、「明日以降」へ戻すときは実施日を決め直し、印は外れる＝_later_due_shape）。"""
    if _item_due_pending(block, today) is None:
        return block
    return _ITEM_OPEN_RE.sub(lambda m: m.group(0)[:-1] + ' data-due-moved="%s">' % today.isoformat(), block, count=1)


def _item_due_shapeable(block):
    """「明日以降」から今日の側へ動かす行で、形を作る対象なら実施日 (date, "H:MM" か None)、そうでなければ None（move・D&D・v2.11）。

    実施日が読めて済でない行は、一度移した印の有無にも、実施日が先の日かにもよらず対象にする（印は日付の切り替えが
    移し直さないための印で、形の規則は変えない。印のある「明日以降」の行は、旧版で戻した行か印を写した行＝_item_due_pending）。
    日付の切り替えが移す対象を決めるのは _item_due_pending（印を見る）。"""
    due = parse_due_value(_item_open_attr(block, "data-due"))
    if due is None or _CHIP_DONE_RE.search(block):
        return None
    return due


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
    t = _key_text(block, "time", stop_at_class=True)    # 鍵と同じ読み方（閉じタグの無い欄でも欄そのものの文字・v1.10）
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
        "due": _item_open_attr(block, "data-due"),
        "due_moved": _item_open_attr(block, "data-due-moved"),
        "due_from": _item_open_attr(block, "data-due-from"),
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


def check_due(value):
    """実施日の引数を調べて、板に書く形（YYYY-MM-DD か YYYY-MM-DD H:MM）にする。読めなければ OpError。"""
    text = (value or "").strip().replace("T", " ", 1)
    due = parse_due_value(text)
    if due is None:
        raise OpError("実施日「%s」は使えません。何も書いていません。YYYY-MM-DD か、時刻も分かるなら YYYY-MM-DD H:MM の形で、"
                      "実在する日付と時刻を指定してください（例 2026-11-04・2026-11-04 22:05。空白の代わりに T でもよい）。" % value)
    return due[0].isoformat() + (" " + due[1] if due[1] else "")


def check_due_moved(value):
    """一度移した印の引数（YYYY-MM-DD か none）→ 板に書く日付の文字列か None（none＝印なし）。読めなければ OpError。"""
    text = (value or "").strip()
    if text == "none":
        return None
    due = parse_due_value(text)
    if due is None or due[1] is not None:
        raise OpError("一度移した印（--due-moved・spec の due_moved）「%s」は使えません。何も書いていません。"
                      "元の行の status の due_moved の日付（YYYY-MM-DD）を写し、印が無ければ none（spec では null）を指定してください。" % value)
    return due[0].isoformat()


def due_attrs(due, moved, came=None):
    """開始タグに足す実施日・一度移した印・元の実施日の属性（Deck と同じ順＝data-due・data-due-moved・data-due-from）。"""
    return (' data-due="%s"' % due + (' data-due-moved="%s"' % moved if moved else "")
            + (' data-due-from="%s"' % came if came else ""))


def check_due_from(value):
    """元の実施日（--due-from・spec の due_from。今日の側へ移した行の、移す前の実施日・v1.7）の引数 → 板に書く値か None（none＝無し）。"""
    if value is None or str(value).strip() == "none":
        return None
    try:
        return check_due(value)
    except OpError:
        raise OpError("元の実施日（--due-from・spec の due_from）「%s」は使えません。何も書いていません。"
                      "元の行の status の due_from を写し、無ければ省いてください（spec では null）。" % value)


def roll_due_today(due, tm, moved, came, today):
    """今日の側の行で、実施日が今日でなければ、実施日を今日にする（Deck の日付の切り替えの _carry_due_today と同じ規則・v1.7。先の日の行は v1.9）。

    (実施日, 印, 元の実施日) を返す。時刻は tm（行の時刻の欄）があれば含め、無ければ日付だけ。元の実施日は came があればそのまま、
    無ければ due の日付と行の時刻（tm、無ければ due の時刻。Deck v2.12 の _carry_due_today と同じ・v1.9。v1.8 までは due そのままで、
    時刻の欄と実施日の時刻が違う行では足し直しと Deck の引き継ぎとで元の実施日の時刻が変わった）。印は moved が無ければ今日。
    実施日が今日・読めない行はそのまま。実施日が先の日の行も今日にする（今日の側の行は今日の行＝Deck v2.13 と同じ・v1.9）。tm は呼び手が操作の後の行の時刻を渡す（add・create は --time・spec の time、
    set-due は渡された実施日に時刻があり時刻の欄があればその時刻＝set-due は時刻の欄を実施日の時刻にそろえるため、それ以外は H:MM の時刻の欄）。"""
    pd = parse_due_value(due) if due else None
    if pd is None or pd[0] == today:
        return due, moved, came
    rt = tm or pd[1]
    return (today.isoformat() + (" " + tm if tm else ""), moved or today.isoformat(),
            came or pd[0].isoformat() + (" " + rt if rt else ""))


TODAY_SIDE = ("今日の予定", "今日中")
# 今日の側の行を「明日以降」へ動かすときの --due の断りの文（move・v1.9）
MOVE_LATER_DUE_RULE = ("項目「%s」は「%s」にあります。何も書いていません。「明日以降」へ動かすときは --due で実施日を指定してください。"
                       "実施日はユーザーに確かめる（日付〔時刻は任意〕か、未定か。status の due_from が今日より後ならそれを元の予定として、"
                       "time が H:MM ならその時刻を行の時刻として見せる。確かめずに当てない）。日付なら --due YYYY-MM-DD か --due \"YYYY-MM-DD H:MM\"、"
                       "未定なら --due none。move は実施日をその値にし、一度移した印と元の実施日を外す（その日に Deck が今日の側へ移す）。"
                       "時刻の欄は、--due に時刻があればその時刻にし、無ければ外す（未定では変えない）。")
# 今日の側の行に実施日を付けるのは、足し直す行に元の行の実施日を写すときだけ（印と対で写す）。add・set-due・spec の断りの文で使う
DUE_TODAY_SIDE_RULE = ("今日の予定・今日中の行に実施日を付けるのは、足し直す行に元の行の実施日を写すときだけで、"
                       "そのときは一度移した印（status の due_moved）も対で写します（%s）。")


def check_chip(value):
    if value is None:
        raise OpError("--chip を指定してください（done・active・pending・wait・hold・none）。")
    if value not in CHIP_VALUES:
        raise OpError("チップ「%s」は使えません。done・active・pending・wait・hold・none のどれかを指定してください。" % value)
    return value


def chip_span(chip):
    return '<span class="chip %s">%s</span>' % (CHIP_CLASS[chip], CHIP_LABELS[chip])


CRIT_SPAN = '<span class="chip crit">重要タスク</span>'


def build_item(indent, nl, title, note=None, chip="pending", crit=False, time_=None, attrs=""):
    cls = "item" + ("" if time_ else " flat") + (" crit" if crit else "")
    out = ['%s<div class="%s"%s>' % (indent, cls, attrs)]
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
    """class に cls を持つ最初の要素の中身を置き換える。要素が無ければ None。時刻の欄（cls が "time"）は、同じ名前の開きと閉じを数えて
    欄を閉じる閉じタグまでを中身とする（_time_match_close・v1.16。v1.15 までは同じ名前の最初の閉じタグまでで、
    <span class="time"><span>9</span>:00</span> の set-time は「:00」と閉じタグを後ろに残した）。ほかは同じ名前の最初の閉じタグまで。"""
    for m in _CLASS_TAG_RE.finditer(block):
        if cls in m.group(2).split():
            if cls == "time":
                close = _time_match_close(block, m)
                close = -1 if close is None else close
            else:
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
    if _time_unclosed(block):
        # 閉じタグの無い欄を書き換えると、後ろのタイトルとチップまで消える。ブラウザが欄の中に入れた行でも、手前で閉じる行でも同じ（v1.10）
        raise OpError("この項目の時刻の欄には閉じタグが無いため、時刻を書き換えられません。何も書いていません。"
                      "先に close-time --item <項目> で閉じタグを補ってください（警告 K15）。")
    n_time = len(list(_TIME_OPEN_RE.finditer(block)))
    if n_time > 1:
        raise OpError("この項目には時刻の欄が %d 個あるため、時刻を書き換えられません。何も書いていません。" % n_time)
    if value is None:
        if n_time == 0:
            return blines
        block, count = _remove_time_elements(block)
        if count != 1:
            raise OpError("この項目の時刻の欄は、閉じタグが見つからないか、中にタイトル・補足・チップが入っているため、外せません。何も書いていません。")
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


def block_set_due(blines, value, moved=None, came=None):
    """開始タグの実施日を value にする（None で外す）。一度移した印は moved にする（None なら外す＝日付を決め直した行は、また移す対象になる）。
    元の実施日（data-due-from）は came にする（None なら外す＝日付を決め直した行は、新しい予定になる）。"""
    bl = list(blines)

    def fix(m):
        attrs = re.sub(r'\s*data-due(?:-moved|-from)?="[^"]*"', "", m.group(4))
        if value:
            attrs += due_attrs(value, moved, came)
        return m.group(1) + m.group(2) + m.group(3) + attrs + ">"
    bl[0], n = _ITEM_OPEN_RE.subn(fix, bl[0], count=1)
    if n != 1:
        raise OpError("この項目は開始タグの形が想定と違うため、実施日を書けません。何も書いていません。")
    return bl


def normalize_block(blines):
    block = "".join(blines)
    return _normalize_item_block(block, is_done_block(block)).splitlines(keepends=True)


# ================================================================ 検査（K1〜K17）

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


def readd_fields(src):
    """add で足し直すときに写す欄の文（K11・move・restore・require_sound で同じ文を使う）。src は写し元の名前。"""
    return ("%s の time・chip・note・due・due_moved・due_from を写す〔chip が none でも --chip none で写す。time は --time、due は --due、"
            "due_moved は --due-moved で写す（今日の予定・今日中へ足す行で due があれば due_moved も対で写し、null なら --due-moved none。"
            "「明日以降」へ足す行で due_moved が null なら --due-moved は省く）。"
            "due_from（元の実施日）は --due-from で写す（null なら省く）。"
            "ただし「明日以降」へ足す行に due があるときは、add が --time と --due を一緒に受けないので、due に時刻が無く time が H:MM なら"
            "その時刻を --due に含め（--due \"<due> <time>\"）、それ以外は time を写さない"
            "（時刻の欄の無い行は、今日の側へ動かすときに実施日の時刻が使われる）。"
            "due に時刻があり、time がそれと違う行は（H:MM でも）、time が消えるので、due の時刻と time をユーザーに見せてどちらの時刻にするかを確かめ、"
            "time にすると言われたら --due \"<due の日付> <time>\" で写す（同じ時刻なら確かめない）。"
            "今日の予定・今日中へ足す行は time と due を写す（due に時刻があれば、add が due の時刻を time と同じ値にする＝行の時刻は1つ・v1.7。"
            "due の日付が今日でなければ（先の日の due は v1.9 から）、add が実施日を今日にし、元の実施日を due_from に残す）。今日の側へ足す行でも、due に時刻があり time がそれと違えば（H:MM でも）、"
            "同じくどちらの時刻にするかを確かめ、due の時刻にすると言われたら --time にその時刻を写す（restore の足し直しと同じ）。"
            "due の無い行の time は、「明日以降」へ足すときも --time で写す。"
            "time が H:MM でない行（「午後」など）は time を写さない（板の時刻の欄は H:MM と決まっていて、--time も H:MM だけを受ける）。"
            "写さなかった time はユーザーに伝え、H:MM の時刻にするかをユーザーに確かめる（ユーザーが H:MM の時刻を言ったときだけ、その時刻を写す。確かめずに H:MM を当てない）〕" % src)


def readd_order(add_part, fields, extra=""):
    """元の行を先に消してから足し直す手順の文（同じタイトルの行が2つ並ばないよう、消してから足す）。"""
    return ("status で元の行の欄を控え、remove で元の行を先に消し（--confirmed を付ける前に、消す行をユーザーに確かめる）、"
            "%s で足し直し（%s%s）、重要タスクだった項目は足した後に set-crit で付け直してください。" % (add_part, fields, extra))


def restore_readd_text(src):
    """restore で戻した後に、いまの板にだけあった行を足し直す手順の文（restore の案内と require_sound で同じ文を使う）。"""
    return ("足し直してよいと言われた行だけを add で足し直してください（%s。crit が付いていた行は足した後に set-crit で付け直す。"
            "「明日以降」へ足した行で K13 が出たら SKILL.md update モード 9 の手順で今日の側へ移す）。"
            "only_restore にも同じタイトルの行がある only_now の行は、戻した板にその行が残っているので add で足さず、違う欄だけをその行に当ててください"
            "（同じタイトルの行が only_now か only_restore に2つ以上あるときは、見出し・時刻・補足の近いものを組にし、決まらなければ両方の行をユーザーに見せて組を確かめる）。"
            "見出しが違うときは、先に move --item <タイトル> --section <only_now の見出し> で戻した板の行を動かし（今日の予定へは、時刻のある行は時刻の順の位置へ入る。行き先の見出しが戻した板に無ければ --create-section を付ける。今日の予定・今日中から「明日以降」へ動かすときは --due none を付けて動かし、実施日は下のとおり set-due で当てる＝v1.9）、"
            "動かした後は status でその行を読み直して only_now と違う欄を当てる"
            "（動かす元か行き先が 今日の予定・今日中・明日以降 でなく move で動かせないときは、先に戻した板の行を remove で消してから"
            "〔消す前の欄は only_restore にある〕、上のとおり add で足す）。"
            "当てる欄は、chip は set-chip、note は edit、time は set-time（H:MM でない time は当てない＝板の時刻の欄は H:MM と決まっていて、set-time も H:MM だけを受ける。当てなかった time はユーザーに伝える。"
            "time は due より先に当てる〔set-time は実施日の時刻も同じ値にし〈--time none なら外す〉、set-due は時刻の欄を実施日の時刻にそろえるので、後に当てた due の時刻が残る＝v1.7〕。"
            "only_now の due に時刻があり、time がそれと違えば〔H:MM でも〕どちらの時刻にするかをユーザーに確かめ、time にするなら set-due --due \"<due の日付> <time>\" で当てる〔同じ時刻なら確かめない〕）、"
            "crit は set-crit、due と due_moved と due_from は "
            "set-due --due <only_now の due> --due-moved <only_now の due_moved> --due-from <only_now の due_from>"
            "（due_moved が null なら、今日の予定・今日中の行では --due-moved none、「明日以降」の行では省く＝set-due は印も外す。"
            "due_from が null なら --due-from を省く＝set-due は元の実施日も外す。"
            "only_now の due が null なら set-due --due none）。"
            "同じタイトルの行が戻した板に2つ以上あって --item が断るときは status の番号で指し、move などで書いた後は status で番号を取り直す"
            "（remove の --confirmed は番号で指せないので、SKILL.md「ボードの書き方」の remove の回り道に従う）。" % readd_fields(src))


def warnings_for(text):
    """K11〜K15（書くが警告を返す）。"""
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
        warns.append({"code": "K11", "message": ("見出し「%s」は正式名（今日の予定・今日中・ルーチンタスク・明日以降）ではありません。"
                      "この版には見出しの名前を直す操作が無く、move もこの見出しの項目は動かせません。正式名の見出しへ移してよいかをユーザーに確かめ、よいと言われた項目は、"
                      % "」「".join(odd))
                      + readd_order("正式名の見出しへ add", readd_fields("控えた status")) + "残った見出しの扱いはユーザーに伝えてください。"})
    bad = []
    for it in items:
        block = "".join(lines[it["s"]:it["e"] + 1])
        if is_done_block(block):       # 済の判定はチップだけ（K14 と同じ。board.js の「時刻を読めない」チップも、done-item をチップに合わせた後に見る）
            continue
        t = _key_text(block, "time", stop_at_class=True)   # board.js の「時刻を読めない」と同じ読み方（v1.10）
        hm = re.search(r"(\d{1,2}):(\d{2})", t or "")
        if t is not None and t.strip() and (not hm or int(hm.group(1)) > 23 or int(hm.group(2)) > 59):
            # 範囲外（25:00 など）も読めない時刻に数える（Deck の read_board_alarms・board.js の parseHM と同じ。v1.7）
            bad.append(_item_key(block))
    if bad:
        warns.append({"code": "K12", "message": "時刻の欄が H:MM として読めない（時 0〜23・分 0〜59 の範囲外を含む）未完了の項目があります（%s）。"
                      "正しい時刻をユーザーに確かめてから、set-time --item <項目> --time H:MM で直してください（時刻の無い行にするなら --time none）。"
                      "実施日のある行では、set-time は実施日の時刻も同じ値にし、--time none なら実施日の時刻も外します（日付と一度移した印は変えない・v1.7）。" % "、".join(bad)})
    today = date.today()
    due_now = [_item_key("".join(lines[it["s"]:it["e"] + 1])) for it in items
               if _canon_label(it["section"] or "") == TOMORROW
               and _item_due_pending("".join(lines[it["s"]:it["e"] + 1]), today)]
    # Deck の日付の切り替えが形を作れない行（_due_moved_shape が None＝時刻の欄が2つ以上・欄の中に行の部品がある等）は、切り替えでは
    # 移らずその場に残る（Deck の roll_board_text の「明日以降」・v1.10）
    stuck = [_item_key("".join(lines[it["s"]:it["e"] + 1])) for it in items
             if _canon_label(it["section"] or "") == TOMORROW
             and _item_due_pending("".join(lines[it["s"]:it["e"] + 1]), today)
             and _due_moved_shape("".join(lines[it["s"]:it["e"] + 1]), _item_due_pending("".join(lines[it["s"]:it["e"] + 1]), today),
                                  today, "\n", True) is None]
    if due_now:
        warns.append({"code": "K13", "message": "「明日以降」に実施日が今日以前の行があります（%s）。SKILL.md update モード 9 の手順で今日の側へ移してください"
                      "（移した行は status の due_now から外れます。Deck が動いていれば、移さなくても次の日付の切り替えで移ります%s）。"
                      % ("、".join(due_now),
                         "。ただし %s は、行の形が想定と違う（時刻の欄が2つ以上ある・時刻の欄の中にタイトルやチップが入っている等）ため、Deck の日付の切り替えでは移らずその場に残ります（K15 があれば先にその直し方で直してください）"
                         % "、".join(stuck) if stuck else "")})
    # 閉じタグの無い時刻の欄を、ブラウザが欄の中に後ろの要素を取り込む行（unclosed）と、ブラウザがその手前で欄を閉じて画面は正しい行
    # （shown＝_time_screen_closed。board.js の⑥には出ない）に分けて知らせる（v1.12）
    # 書式の要素を開き直す行（reopened＝_time_reopened。画面は正しくなく、close-time は --confirmed のときだけ補う）も分ける。shown は close-time で --confirmed なしに直せる行だけ
    # 板に K16（_swallow_open）があれば、その行のある項目は K15 に入れない（ブラウザはそこから後ろを飲み込み、board.js が動かない。K16 で知らせる・v1.13）
    sw = _swallow_open(text)
    sw_line = text.count("\n", 0, sw[0]) if sw else -1
    unclosed, shown, reopened = [], [], []
    for it in items:
        if it["s"] <= sw_line <= it["e"]:
            continue
        b = "".join(lines[it["s"]:it["e"] + 1])
        hit = _time_open_unclosed(b)
        if hit is None:
            continue
        if _time_screen_closed(b, hit) is not None:
            shown.append(_item_key(b))
        elif _time_reopened(b, hit):
            reopened.append(_item_key(b))
        else:
            unclosed.append(_item_key(b))
    if unclosed:
        warns.append({"code": "K15", "message": "時刻の欄の閉じタグが無い項目があります（%s）。ブラウザでは時刻の欄の中にタイトルやチップなど class を持つ要素が入り、"
                      "✎ で時刻を変えられません。欄の中にタイトルやチップが入っている行は、「明日以降」へ動かすときに実施日も決められません。"
                      "ユーザーに「ボードを直して」と頼まれたら、"
                      "close-time --item <項目> で閉じタグを補ってください（タスクの文言・状態は変わりません）。" % "、".join(unclosed)})
    if shown:
        warns.append({"code": "K15", "message": "時刻の欄の閉じタグが無い項目があります（%s）。ブラウザは時刻の欄をタイトルやチップの手前で閉じるので、"
                      "画面では正しく表示されます（「ボードの点検」の⑥には出ません）。ただし HTML に閉じタグが無いため、set-time では時刻を書き換えられません"
                      "（書き換えると、後ろのタイトルやチップまで消えるため）。時刻を書き換える前か、ユーザーに「ボードを直して」と頼まれたら、"
                      "close-time --item <項目> で閉じタグを補ってください（画面・タスクの文言・状態は変わりません）。" % "、".join(shown)})
    if reopened:
        warns.append({"code": "K15", "message": "時刻の欄の閉じタグが無い項目があります（%s）。時刻の欄の中に閉じていない書式の要素（b・i など）があり、"
                      "ブラウザは時刻の欄を閉じた後でその要素を開き直すので、画面では後ろのタイトルやチップがその書式で表示されます（「ボードの点検」の⑥には出ません）。"
                      "set-time では時刻を書き換えられません。ユーザーに「ボードを直して」と頼まれたら、板のその行をユーザーに見せ、"
                      "タイトルやチップの書式が外れてよいかを確かめてから、close-time --item <項目> --confirmed で閉じタグを補ってください"
                      "（画面の書式は外れますが、タスクの文言・状態・行の鍵は変わりません）。" % "、".join(reopened)})
    mism = later_time_mismatches(lines, items)
    if mism:
        warns.append({"code": "K14", "message": "「明日以降」に、時刻の欄が実施日の時刻と違う行があります（%s）。"
                      % "、".join("%s〔時刻の欄 %s・実施日 %s〕" % m for m in mism)
                      + "v1.6 までの操作（今日の側で set-time した行を move・D&D で戻す等）でできた形です（v1.7 の set-time・set-due・add・create は、時刻の欄と実施日の時刻を同じ値にする）。"
                        "このままだと、今日の側へ動かすとき（move・D&D。一度移した印の無い行は Deck の日付の切り替えも＝Deck v2.11 から）は時刻の欄の時刻が使われ、create で作り直すと実施日の時刻だけが残ります。"
                        "時刻の欄の時刻と実施日の時刻をユーザーに見せて、どちらの時刻にするかを確かめ（確かめずにどちらかを消さない）、"
                        "set-time --item <項目> --time <決めた時刻> で揃えてください（実施日の時刻も同じ値になる。日付と一度移した印は変えない）。"})
    return warns


def later_time_mismatches(lines, items):
    """「明日以降」の未完了の行で、実施日に時刻があり、H:MM の時刻の欄がそれと違うもの（警告 K14・v1.6）。[(項目, 時刻の欄, 実施日)] を返す。

    v1.6 までの操作（今日の側で set-time した行を move・D&D で戻す等）でできた形（v1.7 の set-time・set-due・add・create は作らないが、
    v1.6 までに今日の側にできた行を戻したとき・restore で v1.6 までの板を戻したときには残る）。
    今日の側へ動かすとき（move・D&D。印の無い行は Deck v2.11 の日付の切り替えも）は時刻の欄の時刻が使われ、create では実施日の時刻だけが残る。
    済の判定は状態チップだけで行う（チップが唯一の真実。board.js は読み込みで done-item をチップに合わせ、Deck の read_board_alarms もチップだけを見る）。
    時刻の欄が H:MM でない行は K12 が知らせる。board.js の「ボードの点検」の⑤（renderBoardCheck）が同じ条件で知らせる。"""
    out = []
    for it in items:
        if _canon_label(it["section"] or "") != TOMORROW:
            continue
        block = "".join(lines[it["s"]:it["e"] + 1])
        if is_done_block(block):
            continue
        raw = _item_open_attr(block, "data-due")
        due = parse_due_value(raw)
        t = _later_time_conflict(block, due[1]) if due else None
        if t is not None and _valid_hm(t):
            out.append((_item_key(block), t, raw))
    return out


def run_checks(op, old_text, new_text, intended_date_text, touched_old=(), touched_new=(), delta=0):
    """出来上がりの本文に K1〜K9・K16・K17 を当てる。当たったもの（E）の一覧を返す。"""
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
    # K17（v1.13）: 書く前の板で実行される board.js の読み込みが、出来上がりでは無いか実行されない（K16 に当たる出来上がりは K16 で断る）
    if old_text is not None and _sw_scan(old_text)[1]:
        hit, ran = _sw_scan(new_text)
        if hit is None and not ran:
            errs.append({"code": "K17", "message": "書く前の板にあったボードのスクリプト（board.js）の読み込み（<script src=\"board.js\"></script>）が、"
                         "出来上がりの板では無いか、実行されない形になっています。"})
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
        raise OpError(("いまの board.html は形が崩れているため、%s では書きません。"
                       "status の restorable_today（いまの板と日付が同じで、形の正しい版）を見て、restore --from history/<ファイル名> で戻してから、"
                       "欠けた行をユーザーに見せ、" % op) + restore_readd_text("restore の diff の only_now") +
                      "restorable_today が空なら、ボードを書かずに、この出力をユーザーに見せて、どうするかを確かめてください。", checks=errs)


def new_section_indent(lines):
    """新しい見出しの字下げ（最初の見出しと同じ。見出しが無ければ DECK の始まりの行と同じ）。"""
    secs, _items = layout(lines)
    if secs:
        return indent_of(lines[secs[0]["line"]])
    dl = next((i for i, ln in enumerate(lines) if MARKER_START in ln), None)
    return indent_of(lines[dl]) if dl is not None else "  "


def insert_new_section(lines, name, item_lines, nl, indent):
    """見出し name を作り、その直後に item_lines を置く（add と move の --create-section で同じ）。(新しい行の一覧, 見出しの行) を返す。

    置き場は見出しの正式な順（今日の予定・今日中・その他・ルーチンタスク・明日以降）で、後ろに来るべき最初の見出しの前。
    無ければ DECK の始まりの前の、最後の空でない行の後ろ。"""
    rank = section_rank(name)
    secs, _items = layout(lines)
    insert_at = next((s["line"] for s in secs if section_rank(s["label"]) > rank), None)
    label = '%s<div class="section-label">%s</div>%s' % (indent, esc(name), nl)
    if insert_at is not None:
        return lines[:insert_at] + [label] + item_lines + [nl] + lines[insert_at:], insert_at
    dl = next((i for i, ln in enumerate(lines) if MARKER_START in ln), len(lines))
    j = dl - 1
    while j >= 0 and lines[j].strip() == "":
        j -= 1
    pos = j + 1
    return lines[:pos] + [nl, label] + item_lines + lines[pos:], pos + 1


def op_add(text, nl, a):
    if a.title is None:
        raise OpError("add には --title を指定してください。")
    title = check_text(a.title, "--title")
    note = check_text(a.note, "--note", allow_empty=True) or None
    tm = check_time(a.time) if a.time else None
    due = check_due(a.due) if a.due is not None else None
    if a.due_moved is not None and due is None:
        raise OpError("--due-moved（一度移した印）は --due と一緒にだけ使えます。何も書いていません。")
    moved = check_due_moved(a.due_moved) if a.due_moved is not None else None
    if getattr(a, "due_from", None) is not None and due is None:
        raise OpError("--due-from（元の実施日）は --due と一緒にだけ使えます。何も書いていません。")
    came = check_due_from(getattr(a, "due_from", None))
    name = check_text(a.section, "--section")
    canon = _canon_label(name)
    if due and canon == TOMORROW and tm:
        raise OpError("「明日以降」の行では --time と --due は一緒に使えません。何も書いていません。「明日以降」の行の時刻は --due に含めてください（例 --due \"2026-11-04 22:05\"）。"
                      "「明日以降」の行は、--time を付けても通知の対象になりません。")
    if due and canon in TODAY_SIDE and a.due_moved is None:
        raise OpError("--due には --due-moved も要ります。何も書いていません。" + DUE_TODAY_SIDE_RULE % "--due-moved <日付>。null なら --due-moved none"
                      + "新しく足す今日の行なら --due を外してください（先の日にやるなら「明日以降」へ足す）。")
    if due and canon not in TODAY_SIDE and canon != TOMORROW:
        raise OpError("実施日（--due）を付けられるのは「明日以降」の行と、今日の予定・今日中へ足し直す行だけです。何も書いていません。今日の行なら --due を外してください。")
    if due and canon in TODAY_SIDE:
        # 今日の側の行で実施日が今日でなければ（先の日の実施日は v1.9 から）、実施日を今日にする（create・Deck の日付の切り替えと同じ・v1.7）
        due, moved, came = roll_due_today(due, tm, moved, came, date.today())
    if due and tm and parse_due_value(due)[1]:
        due = due.split(" ")[0] + " " + tm      # 行の時刻は1つ（時刻の欄と実施日の時刻を同じ値にする・v1.7）
    due_attr = due_attrs(due, moved, came) if due else ""
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
        indent = new_section_indent(lines)
        item_lines = build_item(indent, nl, title, note, chip, False, tm, due_attr)
        new, lab_at = insert_new_section(lines, name, item_lines, nl, indent)
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
    elif tm and _canon_label(sec["label"]) == "今日の予定":
        pos = plan_time_pos(lines, sec["line"], _hm_minutes(tm))
    else:
        pos = section_end(lines, sec["line"])
    item_lines = build_item(indent, nl, title, note, chip, False, tm, due_attr)
    if pos > 0 and not lines[pos - 1].endswith(("\n", "\r")):
        lines[pos - 1] += nl
    new = lines[:pos] + item_lines + lines[pos:]
    return Result("".join(new), {"section": sec["label"], "created_section": False}, touched_new={pos}, delta=1)


def _block_minutes(block):
    """項目の時刻の欄の分（Deck の日付の切り替えが「今日の予定」の並びに使うのと同じ読み方）。読めなければ None。"""
    m = re.search(r"(\d{1,2}):(\d{2})", _time_text(block) or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def plan_time_pos(lines, sec_line, minutes):
    """「今日の予定」の見出し（sec_line）の中で、minutes の行を入れる位置（その時刻より後の最初の行の前。無ければ見出しの末尾）。

    Deck の日付の切り替えが実施日の来た行を「今日の予定」へ置く位置と同じ（時刻の読めない行は飛ばす）。"""
    if minutes is not None:
        _secs, items = layout(lines)
        for it in items:
            if it["sec_line"] != sec_line:
                continue
            t = _block_minutes("".join(lines[it["s"]:it["e"] + 1]))
            if t is not None and t > minutes:
                return it["s"]
    return section_end(lines, sec_line)


def _valid_hm(text):
    """H:MM（時 0〜23・分 0〜59）なら "H:MM"（時の先頭の 0 を落とす）、そうでなければ None。行の時刻の欄を時刻として使うかの判定（v2.11）。"""
    m = re.match(r"^(\d{1,2}):(\d{2})$", (text or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return "%d:%s" % (int(m.group(1)), m.group(2))


def _due_moved_shape(block, due, today, nl, to_plan):
    """「明日以降」から今日の側へ動かす行の形（Deck の日付の切り替え・D&D の反映・board_edit.py の move で同じ）。

    行の時刻は、時刻の欄が H:MM（時 0〜23・分 0〜59）ならその時刻、無ければ実施日の時刻（v2.11。時刻の欄を書く操作は実施日の
    時刻も同じ値にするので、ふつうは同じ値。違う行〔v1.6 までの操作でできた行〕では時刻の欄を使う＝2026-11-05 ユーザー決定。
    どちらが後から書かれたかは板からは分からない）。to_plan は行き先が「今日の予定」か。行き先が「今日の予定」で、実施日が今日で
    時刻があれば、時刻の欄をその時刻にして flat を外す（通知の対象になる）。それ以外（前の日・先の日の行、今日中へ動かす行）は
    時刻の欄を外して flat を付ける（その日の時刻を、今日のその時刻に鳴らさない）。外した時刻の欄は data-orig-time に残さない
    （行の時刻は data-due か data-due-from に残る。ただし H:MM でない時刻の欄の文字と、data-due-from が既にある行で時刻の欄の時刻がその時刻と違うときの時刻の欄の時刻は、どこにも残らない。data-orig-time は日付の切り替えが
    data-carried-from と組で書く＝Deck v2.12・board_edit.py v1.8。v2.11・v1.7 までは残し、引き継いだ翌日のチップが別の日の時刻を出した）。
    状態チップが無ければ「未」を足す。
    実施日は今日にする（時刻の欄を付けるならその時刻を含め、付けないなら日付だけ。2026-11-05 ユーザー決定）。実施日が先の日の行
    （前もって今日の側へ動かす行）も今日の行として扱い、実施日を今日にする（時刻は付けない＝前の日の行と同じく時刻の欄を外して flat。
    2026-11-06 ユーザー決定・v2.13・board_edit.py v1.9。v2.12・v1.8 までは先の日の行の日付も印も変えず、実施日の日が来ても鳴らなかった）。
    元の実施日は data-due-from に残し（既にあれば変えない。日付は元の実施日の日付、時刻は行の時刻＝v2.12・v1.8。v2.11・v1.7 までは
    元の data-due そのままで、時刻の欄と実施日の時刻が違う行〔v1.6 までの操作でできた行〕では実施日の時刻が残った）、
    一度移した印を付ける（既にあれば変えない。先の日の行にも付ける＝今日の行になったので、他の今日の側の行と同じ・v2.13。
    「明日以降」へ戻すときは利用者が実施日を決め直し、印は外れる＝_later_due_shape）。
    形が想定外（時刻の欄が2つ以上など）なら None。
    日付の切り替えは to_plan=True で呼び、出来上がりに時刻の欄があれば「今日の予定」、無ければ「今日中」へ置く（_move_due_block）。"""
    when = due[1]
    n_time = len(_TIME_OPEN_RE.findall(block))
    old_time = None
    if n_time > 1:
        return None
    if n_time == 1:
        old_time = (_time_text(block) or "").strip()
        block, removed = _remove_time_elements(block)
        if removed != 1:
            return None
        when = _valid_hm(old_time) or when
    block = _insert_status_chip(block, nl)
    if block is None:
        return None
    scheduled = bool(when) and due[0] == today and to_plan
    new_due = today.isoformat() + (" " + when if scheduled else "")   # 先の日の行も今日にする（v2.13）

    def fix(m):
        cls = _toggle_class_token(m.group(2), "flat", not scheduled)
        attrs = m.group(4)
        raw = re.search(r'\sdata-due="([^"]*)"', attrs).group(1)
        if new_due != raw:
            attrs = re.sub(r'(\sdata-due=")[^"]*(")', lambda a: a.group(1) + new_due + a.group(2), attrs, count=1)
        if not re.search(r'\sdata-due-moved="', attrs):
            attrs += ' data-due-moved="%s"' % today.isoformat()
        if not re.search(r'\sdata-due-from="', attrs):
            attrs += ' data-due-from="%s"' % (due[0].isoformat() + (" " + when if when else ""))
        return m.group(1) + cls + m.group(3) + attrs + ">"

    m = _ITEM_OPEN_RE.search(block)
    if not m:
        return None
    tag = fix(m)
    rest = block[m.end():]
    if scheduled:
        time_el = '<div class="time">%s</div>' % html.escape(when, quote=False)
        if rest.startswith(("\r\n", "\n")):
            ind = re.match(r"[ \t]*", block).group(0)
            tag += nl + ind + "  " + time_el
        else:
            tag += time_el
    return block[:m.start()] + tag + rest


def _later_due_shape(block, due, nl):
    """今日の側から「明日以降」へ動かす行に、利用者が決めた実施日を当てる（D&D の反映・board_edit.py の move で同じ・Deck v2.13・
    board_edit.py v1.9・2026-11-06 ユーザー決定）。due は (date, "H:MM" か None)、未定なら None。

    実施日はその値にし、一度移した印（data-due-moved）と元の実施日（data-due-from）は外す（その日に日付の切り替えが今日の側へ
    移す対象にする。元の予定は決め直した値に置き換わり、その日に移したときにあらためて data-due-from に残る）。行の時刻は1つにする:
    時刻の欄が1つある行は、実施日に時刻があれば時刻の欄をその時刻にし、無ければ時刻の欄を外す（flat を付ける）。時刻の欄の
    無い行には足さない。未定（None）は実施日・印・元の実施日を外し、時刻の欄は変えない。時刻の欄が2つ以上の行は時刻の欄を変えない。
    形が想定外なら None。"""
    m = _ITEM_OPEN_RE.search(block)
    if not m:
        return None
    n_time = len(_TIME_OPEN_RE.findall(block))
    put_time = None
    timed = n_time > 0
    if due is not None and n_time == 1:
        block, removed = _remove_time_elements(block)
        if removed != 1:
            return None
        put_time = due[1]
        timed = bool(put_time)
        m = _ITEM_OPEN_RE.search(block)
        if not m:
            return None
    attrs = re.sub(r'\sdata-due(?:-moved|-from)?="[^"]*"', "", m.group(4))
    if due is not None:
        attrs += ' data-due="%s"' % (due[0].isoformat() + (" " + due[1] if due[1] else ""))
    tag = m.group(1) + _toggle_class_token(m.group(2), "flat", not timed) + m.group(3) + attrs + ">"
    rest = block[m.end():]
    if put_time:
        time_el = '<div class="time">%s</div>' % html.escape(put_time, quote=False)
        if rest.startswith(("\r\n", "\n")):
            ind = re.match(r"[ \t]*", block).group(0)
            tag += nl + ind + "  " + time_el
        else:
            tag += time_el
    return block[:m.start()] + tag + rest


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


def align_due_time(blines, value):
    """実施日（data-due）のある行の、実施日の時刻を value（"H:MM"。None なら時刻を外して日付だけにする）にする（v1.7）。

    行の時刻は1つにする（時刻の欄を書く操作は、実施日の時刻も同じ値にする。日付・一度移した印・元の実施日は変えない）。
    日付だけの実施日にも時刻を含める（今日の側へ移した行の実施日は今日なので、前の日の予定に時刻を書き足すことにはならない）。
    set-time --time none は、時刻の欄のある行でだけ呼ぶ（欄の無い行では実施日の時刻を消さない）。実施日の無い行はそのまま。"""
    bl = list(blines)
    due = parse_due_value(_item_open_attr(bl[0], "data-due"))
    if not due or (not due[1] and not value):
        return bl
    new = due[0].isoformat() + (" " + value if value else "")
    bl[0] = re.sub(r'(\sdata-due=")[^"]*(")', lambda m: m.group(1) + new + m.group(2), bl[0], count=1)
    return bl


def op_set_time(text, nl, a):
    if a.time is None:
        raise OpError("set-time には --time H:MM（外すときは --time none）を指定してください。")
    value = None if a.time == "none" else check_time(a.time)

    def fn(b):
        if value is None and not _TIME_OPEN_RE.search("".join(b)):
            return b            # 時刻の欄の無い行の --time none は何もしない（実施日の時刻だけを消さない）
        return align_due_time(block_set_time(b, nl, value), value)
    return _item_op(text, nl, a, fn)


def op_set_due(text, nl, a):
    if a.due is None:
        raise OpError("set-due には --due YYYY-MM-DD か --due \"YYYY-MM-DD H:MM\"（外すときは --due none）を指定してください。")
    value = None if a.due == "none" else check_due(a.due)
    if a.due_moved is not None and value is None:
        raise OpError("--due-moved（一度移した印）は実施日（--due）と一緒にだけ使えます。--due none は印も一緒に外します。何も書いていません。")
    moved = check_due_moved(a.due_moved) if a.due_moved is not None else None
    if getattr(a, "due_from", None) is not None and value is None:
        raise OpError("--due-from（元の実施日）は実施日（--due）と一緒にだけ使えます。--due none は元の実施日も一緒に外します。何も書いていません。")
    came = check_due_from(getattr(a, "due_from", None))
    if value:
        lines = text.splitlines(keepends=True)
        _it, inf = resolve_item(lines, a.item)
        canon = _canon_label(inf["section"] or "")
        if canon in TODAY_SIDE and a.due_moved is None:
            raise OpError("項目「%s」は「%s」にあります。何も書いていません。先の日へ延ばすなら、実施日をユーザーに確かめてから move --section 明日以降 --due <実施日> で動かしてください（未定なら --due none）。"
                          % (inf["key"], inf["section"])
                          + DUE_TODAY_SIDE_RULE % "--due-moved <日付>。null なら --due-moved none")
        if canon not in TODAY_SIDE and canon != TOMORROW:
            raise OpError("実施日を付けられるのは「明日以降」の行（と、今日の予定・今日中で元の実施日を写し直す行）だけです。何も書いていません。項目「%s」は「%s」にあります。"
                          "先の日へ延ばすなら、先に move --section 明日以降 で動かしてください。" % (inf["key"], inf["section"]))
    today_side = bool(value) and canon in TODAY_SIDE

    def fn(b):
        v, mk, cm = value, moved, came
        if today_side:
            # 今日の側の行で実施日が今日でなければ（先の日の実施日は v1.9 から）、実施日を今日にする（add・create・Deck の日付の切り替えと同じ・v1.7）
            # 行の時刻は操作の後の時刻（実施日に時刻があり時刻の欄があれば、下で時刻の欄をその時刻にそろえるので、その時刻・v1.9）
            n_t = len(_TIME_OPEN_RE.findall("".join(b)))
            pv = parse_due_value(v)
            tm = (pv[1] if pv and pv[1] else _valid_hm(_time_text("".join(b)))) if n_t == 1 else None
            v, mk, cm = roll_due_today(v, tm, mk, cm, date.today())
        b = block_set_due(b, v, mk, cm)
        pd = parse_due_value(v) if v else None
        # 実施日に時刻を書いたら、時刻の欄があればそれも同じ時刻にする（行の時刻は1つ・v1.7。時刻の欄が無ければ足さない）
        if pd and pd[1] and len(_TIME_OPEN_RE.findall("".join(b))) == 1:
            b = block_set_time(b, nl, pd[1])
        return b
    return _item_op(text, nl, a, fn)


def op_move(text, nl, a):
    if a.section not in MOVABLE_SECTIONS:
        raise OpError("move の行き先は 今日の予定・今日中・明日以降 のどれかです（Deck の D&D と同じ）。")
    if a.before and a.head:
        raise OpError("--before と --head は一緒に使えません。どちらか1つにしてください。")
    lines = text.splitlines(keepends=True)
    it, inf = resolve_item(lines, a.item)
    if _canon_section(inf["section"] or "") is None:
        raise OpError(("項目「%s」は見出し「%s」にあり、move で動かせるのは 今日の予定・今日中・明日以降 の項目だけです。何も書いていません。"
                       "正式名の見出しへ移すなら、ユーザーに確かめてから、" % (inf["key"], inf["section"]))
                      + readd_order("add", readd_fields("控えた status")))
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
    to_later = a.section == TOMORROW and _canon_section(inf["section"] or "") in TODAY_SIDE
    due_arg = getattr(a, "due", None)
    if due_arg is not None and not to_later:
        raise OpError("--due（実施日）は、今日の予定・今日中の行を「明日以降」へ動かすときだけ使えます。何も書いていません。"
                      "「明日以降」の行の実施日は set-due で変えてください。")
    if to_later:
        # 実施日はユーザーが決める（日付・時刻は任意、か未定）。印と元の実施日を外し、行の時刻は1つにする（v1.9・Deck v2.13 と同じ）
        if due_arg is None:
            raise OpError(MOVE_LATER_DUE_RULE % (inf["key"], inf["section"]))
        pd = None
        if str(due_arg).strip() != "none":
            pd = parse_due_value(check_due(due_arg))
            if pd[0] <= date.today():
                raise OpError("実施日「%s」は今日以前です。何も書いていません。「明日以降」へ動かす行の実施日は明日以後の日付にしてください"
                              "（今日やるなら今日の側に残す。決まっていなければ --due none）。" % due_arg)
        shaped = _later_due_shape("".join(block), pd, nl)
        if shaped is None:
            raise OpError("項目「%s」は形が想定外で、実施日を当てられません。何も書いていません。" % inf["key"])
        block = shaped.splitlines(keepends=True)
    if _canon_section(inf["section"] or "") == TOMORROW and a.section != TOMORROW:
        # 実施日のある行は、Deck の日付の切り替えと同じ形にする（時刻の欄・未チップ・一度移した印。印の有無・先の日の行かによらない＝v1.7）。
        # 形が想定外なら、実施日の来た行に印だけ付ける
        today = date.today()
        joined = "".join(block)
        due = _item_due_shapeable(joined)
        shaped = _due_moved_shape(joined, due, today, nl, a.section == "今日の予定") if due else None
        block = (shaped if shaped is not None else _mark_due_moved(joined, today)).splitlines(keepends=True)
    rest = lines[:it["s"]] + lines[it["e"] + 1:]
    secs, items = layout(rest)
    label_line = next((s["line"] for s in secs if _canon_section(s["label"]) == a.section), None)
    if label_line is None:
        if not a.create_section:
            raise OpError("行き先の見出し「%s」がありません。何も書いていません。見出しごと作って動かすなら --create-section を付けてください"
                          "（見出しは add の --create-section と同じ位置に作り、行はその直後に置く。行の形は見出しがあるときと同じ）。" % a.section)
        new, lab_at = insert_new_section(rest, a.section, block, nl, new_section_indent(rest))
        return Result("".join(new), {"item": inf, "to": a.section, "created_section": True},
                      touched_old={it["s"]}, touched_new={lab_at, lab_at + 1})
    if a.head:
        pos = label_line + 1
    elif before_s is not None:
        # 動かす項目を抜いた後の行番号へ直す（中身で探さない＝同じ中身の項目が2つあっても取り違えない）
        pos = before_s if before_s < it["s"] else before_s - (it["e"] - it["s"] + 1)
    elif a.section == "今日の予定":
        # 時刻のある行は時刻の順の位置へ（時刻の無い行・読めない行は見出しの末尾）
        pos = plan_time_pos(rest, label_line, _block_minutes("".join(block)))
    else:
        pos = section_end(rest, label_line)
    new = rest[:pos] + block + rest[pos:]
    return Result("".join(new), {"item": inf, "to": a.section, "created_section": False}, touched_old={it["s"]}, touched_new={pos})


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


ITEM_KEYS = ("section", "time", "title", "note", "chip", "crit", "due", "due_moved", "due_from")


def _spec_mark(it):
    """spec の項目の一度移した印（due_moved）→ 日付の文字列か None。"""
    return check_due_moved(it["due_moved"]) if it.get("due_moved") is not None else None


def _hm_minutes(t):
    m = HM_RE.match((t or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _place_due_items(order, by, today, moved_out):
    """「明日以降」の行で実施日が今日以前のものを、今日の側へ置き直す（Deck の日付の切り替えと同じ規則）。

    済の行・一度移した印（due_moved）のある行は動かさない。実施日が今日で時刻があれば「今日の予定」の時系列の位置へ、それ以外は「今日中」の先頭へ。
    前の日の時刻は今日の時刻にしない（今日のその時刻に通知が出るため）。"""
    def label_of(name):
        for s in order:
            if _canon_label(s) == name:
                return s
        if name == "今日の予定":
            at = 0
        else:
            plan = next((k for k, s in enumerate(order) if _canon_label(s) == "今日の予定"), None)
            at = 0 if plan is None else plan + 1
        order.insert(at, name)
        return name

    head = []
    for sec in list(by):
        if _canon_label(sec) != TOMORROW:
            continue
        keep = []
        for it in by[sec]:
            due = parse_due_value(check_due(it["due"])) if it.get("due") else None
            if due is None or due[0] > today or it.get("chip") == "done" or _spec_mark(it):
                keep.append(it)
                continue
            row = dict(it)
            row["_moved"] = True
            # 元の実施日を残す（実施日を今日にするのは build_sections の roll_due_today。実施日が今日の行はそこで変わらないので、ここで残す）
            row["due_from"] = check_due_from(it.get("due_from")) or check_due(it["due"])
            if row.get("chip") == "none":
                del row["chip"]
            if due[1] and due[0] == today:
                row["time"] = due[1]
                label = label_of("今日の予定")
                rows = by.setdefault(label, [])
                t = _hm_minutes(due[1])
                at = next((k for k, r in enumerate(rows) if (_hm_minutes(r.get("time")) or -1) > t), len(rows))
                rows.insert(at, row)
            else:
                label = label_of("今日中")
                head.append((label, row))
            moved_out.append({"title": it.get("title"), "due": check_due(it["due"]), "section": label})
        by[sec] = keep
    for label, row in reversed(head):
        by.setdefault(label, []).insert(0, row)


def build_sections(spec, nl, indent="  ", moved_out=None):
    """create の spec → セクションの行。moved_out を渡すと、実施日で今日の側へ置いた行をそこへ足す。"""
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
                                 ("chip", (str, type(None)), "文字列"), ("crit", (bool, type(None)), "true か false"),
                                 ("due", (str, type(None)), "\"YYYY-MM-DD\" か \"YYYY-MM-DD H:MM\" の文字列"),
                                 ("due_moved", (str, type(None)), "\"YYYY-MM-DD\" の文字列か null"),
                                 ("due_from", (str, type(None)), "\"YYYY-MM-DD\" か \"YYYY-MM-DD H:MM\" の文字列か null")):
            if key in it and not isinstance(it[key], types):
                raise OpError("spec の items の %d 件目の %s は %s にしてください。" % (n, key, what))
        bad = set(it) - set(ITEM_KEYS)
        if bad:
            raise OpError("spec の items の %d 件目に知らないキーがあります（%s）。使えるのは %s です。"
                          % (n, "・".join(sorted(bad)), "・".join(ITEM_KEYS)))
        sec = it.get("section")
        if not isinstance(sec, str) or not sec.strip():
            raise OpError("spec の items の %d 件目に section がありません。" % n)
        if it.get("due_moved") is not None and it.get("due") is None:
            raise OpError("spec の items の %d 件目: due_moved（一度移した印）は due と一緒にだけ書けます。" % n)
        if it.get("due_from") is not None and it.get("due") is None:
            raise OpError("spec の items の %d 件目: due_from（元の実施日）は due と一緒にだけ書けます。" % n)
        check_due_from(it.get("due_from"))
        if it.get("due") is not None:
            check_due(it["due"])
            _spec_mark(it)
            canon = _canon_label(sec)
            if canon in TODAY_SIDE and "due_moved" not in it:
                raise OpError(("spec の items の %d 件目: due には due_moved も要ります。" % n)
                              + DUE_TODAY_SIDE_RULE % "spec では \"due_moved\": \"<日付>\"。印が無ければ \"due_moved\": null"
                              + "新しく書く今日の行なら due を外してください（先の日にやるなら「明日以降」へ書く）。")
            if canon not in TODAY_SIDE and canon != TOMORROW:
                raise OpError("spec の items の %d 件目: due（実施日）を付けられるのは「明日以降」の行と、今日の予定・今日中へ写し直す行だけです。今日の行なら due を外してください。" % n)
            if canon == TOMORROW and it.get("time"):
                raise OpError("spec の items の %d 件目: 「明日以降」の行では time と due は一緒に使えません。「明日以降」の行の時刻は due に含めてください（例 \"2026-11-04 22:05\"）。" % n)
        if sec not in order:
            order.append(sec)
        by.setdefault(sec, []).append(it)
    today = date.today()
    _place_due_items(order, by, today, [] if moved_out is None else moved_out)
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
            attrs = ""
            if it.get("due"):
                dv = check_due(it["due"])
                mk = today.isoformat() if it.get("_moved") else _spec_mark(it)
                came = check_due_from(it.get("due_from"))
                if _canon_label(sec) in TODAY_SIDE:
                    # 今日の側の行で実施日が今日でなければ（先の日の実施日は v1.9 から）、実施日を今日にする（Deck の日付の切り替えと同じ・v1.7）
                    dv, mk, came = roll_due_today(dv, tm, mk, came, today)
                if tm and parse_due_value(dv)[1]:
                    dv = dv.split(" ")[0] + " " + tm    # 行の時刻は1つ（add と同じ・v1.7）
                attrs = due_attrs(dv, mk, came)
            out += build_item(indent, nl, title, note, chip, crit, tm, attrs)
    return out


DROPPED_TIMES_HEAD = ("まだ作り直していません。いまのボード（今日の板か、日付の読めない板）にある %d 行は、時刻の欄が H:MM でない（「午後」など）か、"
                      "「明日以降」の行で実施日の時刻と違うため、このまま作り直すとその時刻が消えるか、spec の時刻に変わります（dropped_times）。")
DROPPED_TIMES_RULE = ("板の時刻の欄は H:MM と決まっていて、H:MM でない時刻は作り直した板に残さない。「明日以降」の行で実施日に時刻があれば、"
                      "作り直した板に残るのは実施日の時刻だけ（spec は「明日以降」の行で time と due を一緒に受けない）。dropped_times の行と、元の時刻（time）と、"
                      "作り直した板での時刻（new_time。null なら時刻が消える）をユーザーに見せ、時刻をどうするか（H:MM の時刻にするか、消すか。"
                      "「明日以降」の行で元の時刻が H:MM なら、元の時刻と実施日の時刻のどちらにするか）を確かめてください。"
                      "H:MM にすると言われたら、その時刻を spec に書き（今日の予定・今日中の行と、due の無い「明日以降」の行は time に。「明日以降」の行で due があれば due に含める）、"
                      "確かめた後に --confirmed を付けて create を実行してください（ユーザーに確かめずに H:MM を当てて --confirmed を付けない）。")


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
    moved_due = []
    sec_lines = [x.rstrip("\n") for x in build_sections(spec, "\n", moved_out=moved_due)]
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
    payload = {"date": today.isoformat(), "moved_due": moved_due}
    extra = []
    if old_raw is not None:
        # いまの板が今日のもので、Deck が引き継いだ板でもないなら、spec に無い行（消える行）と、時刻が消える行があれば確かめる
        # （ヘッダの日付が読めない板も同じに扱う＝2026-10-29 ユーザー判断）
        if old_text is not None and not getattr(a, "confirmed", False):
            bd = parse_board_date(board_header_date_text(old_text), today)
            if (bd == today or bd is None) and board_attr(old_text, "data-tb-rolled") is None:
                missing, complete, dropped = match_rows(old_text, spec)
                if dropped and not missing and complete:
                    raise OpError(DROPPED_TIMES_HEAD % len(dropped) + DROPPED_TIMES_RULE + "置き換える前の板は history/ に残ります。",
                                  missing=[], missing_incomplete=False, dropped_times=dropped)
                if missing or not complete:
                    head = ("まだ作り直していません。いまのボード（今日の板か、日付の読めない板）にある %d 行が spec に入っていないため、"
                            "このまま作り直すとその行が消えます。" % len(missing)) if missing else \
                        ("まだ作り直していません。いまのボードは形が崩れているため、spec に入っていない行があるかを確かめきれません。")
                    msg = (head + "missing の行をユーザーに番号付きで見せ、残したい行を"
                           "選んでもらってください（4件以下なら選択肢で、5件以上なら番号で答えてもらう）。"
                           "残すと言われた行を spec に足して（missing の time・chip・note・crit・due・due_moved・due_from を写し〔chip が none でも \"none\" と書く。省くと「明日以降」以外では「未」に変わる。"
                           "今日の予定・今日中の行で due があれば、due_moved も対で書く（null のままでよい）。due_from は null なら書かなくてよい。"
                           "「明日以降」の行に due があるときは、spec が time と due を一緒に受けないので、due に時刻が無く time が H:MM ならその時刻を due に含め（\"<due> <time>\"）、"
                           "それ以外は time を書かない。due に時刻があり、time がそれと違う行は（H:MM でも）、作り直すと time が消えるので、"
                           "残す行を選んでもらうときに due の時刻と一緒にユーザーに見せ、time の時刻にすると言われたら due に含める（\"<due の日付> <time>\"）。"
                           "due の無い行の time は time に書く。time が H:MM でない行（「午後」など）は time を写さない"
                           "（板の時刻の欄は H:MM と決まっていて、H:MM でない時刻は残さない）。その行の元の時刻は、残す行を選んでもらうときに一緒にユーザーに見せ、"
                           "H:MM にすると言われたらその時刻を書く〕）、もう一度 create を実行してください。足さない行が残るとき・時刻が消えるか変わる行（H:MM でない時刻の行・「明日以降」で実施日の時刻と違う時刻の行）を足したときは、"
                           "その行が消えること・その時刻が消えるか変わることをユーザーが確かめてから --confirmed を付けてください。"
                           "置き換える前の板は history/ に残ります。")
                    if dropped:
                        msg += (("また、spec に入っている %d 行も、時刻の欄が H:MM でないか、「明日以降」の行で実施日の時刻と違うため、このまま作り直すとその時刻が消えるか、spec の時刻に変わります（dropped_times）。"
                                 % len(dropped)) + DROPPED_TIMES_RULE)
                    if not complete:
                        msg += ("いまの板は形が崩れているため、missing の行の欄（チップ・補足・実施日など）が欠けているか、拾えていない行があるかもしれません"
                                "（missing_incomplete）。また、置き換える前の板は形が崩れているため restore では戻せません。"
                                "作り直す前に、いまの board.html を Read で読み、missing に無い行もユーザーに見せてください。"
                                "欠けた欄は、その Read で読んだ板から写してください。")
                    raise OpError(msg, missing=missing, missing_incomplete=not complete, dropped_times=dropped)
        if old_text is not None:
            removed, complete, dropped = match_rows(old_text, spec)
            payload["removed"] = removed
            payload["removed_incomplete"] = not complete
            payload["dropped_times"] = dropped
        else:
            payload["removed"] = None            # いまの板が UTF-8 で読めないので、消える行を数えられない
            payload["removed_incomplete"] = True
            payload["dropped_times"] = None      # 同じく、時刻が消える行も数えられない
        bd = parse_board_date(board_header_date_text(old_text), today) if old_text is not None else None
        extra.append(("board-%s-before-create-%s" % ((bd or today).isoformat(), datetime.now().strftime("%H%M%S")),
                      old_raw, "saved"))
    else:
        payload["dropped_times"] = []            # 板が無い＝消える時刻も無い
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


ANY_TIME = object()     # match_rows: 時刻を問わずに組にしてよい行の印


def _norm_time(t):
    if t is None or not t.strip():
        return None
    m = HM_RE.match(t.strip())
    return "%d:%s" % (int(m.group(1)), m.group(2)) if m else t.strip()


def missing_rows(old_text, spec):
    """いまの板の手書きの項目のうち、spec の items のどの行とも組にならないもの（消える行）。(行の一覧, 拾いきれたか)。
    組にする規則（section＋time＋title。「明日以降」の行は実施日の日付と時刻〔実施日の時刻、無ければ H:MM の時刻の欄〕。時刻の欄が H:MM でない行は
    時刻を問わない）は match_rows のとおり。"""
    missing, complete, _dropped = match_rows(old_text, spec)
    return missing, complete


def match_rows(old_text, spec):
    """いまの板の手書きの項目を spec の items と組にする。(消える行の一覧, 拾いきれたか, 時刻が落ちる行の一覧) を返す。

    消える行＝spec に同じ section＋time＋title（「明日以降」の行は実施日の日付も）が無い行。同じ鍵の行が spec より多ければ、
    多い分を消える行に数える（同じタイトルの2行に spec が1行など）。
    「明日以降」の行で実施日のあるものの time は、実施日の時刻とみなす（無ければ H:MM の時刻の欄。Deck v2.11 が当日に使うのは、時刻の欄が
    H:MM ならその時刻、無ければ実施日の時刻で、v1.7 の操作でできた行では両方あれば同じ値。食い違う行は下のとおり、どちらの時刻でも組にする。
    時刻の欄を due に含めて写した行・due に時刻があり時刻の欄を写さなかった行を、消える行に数えない）。
    時刻の欄が H:MM でない行（「午後」など）は、時刻を比べずに section＋title（と実施日の日付）で組にする（spec の time は
    H:MM だけを受けるので、時刻なしで入れても、ユーザーに確かめた H:MM で入れても、同じ行とみなす）。
    「明日以降」の行で実施日に時刻があり、時刻の欄がそれと違う行（食い違う行。v1.5）は、spec の実施日の時刻が実施日の時刻でも
    時刻の欄の時刻でも、時刻なし（日付だけ）でも同じ行とみなす（時刻の欄が H:MM でなければ時刻を問わない。どちらの時刻を残すか、
    どちらも消すかをユーザーに確かめた後に、選んだとおりに due を写せるように。時刻なしで組になれば new_time は None）。
    組にする順は、H:MM の行・時刻の無い行を先に、鍵が同じものから（H:MM でない行・食い違う行が、ほかの行の組を横取りしないため）。
    鍵が同じでない組は、食い違う H:MM の行（時刻の欄の時刻、次に時刻なし）を先に、時刻を問わない行（ANY_TIME）を後にする
    （「午後」の行が、時刻の欄の時刻で組にしたい行の spec の行を横取りしないため）。ANY_TIME の行どうし（同じタイトル・同じ実施日の
    日付の「午後」の行が2つなど）は、板の上からの順に spec の行を取るので、spec の行の順によっては、ユーザーが選んだ時刻と違う行と
    組になることがある（どちらの行も消える行には出ない。dropped_times の time と new_time で確かめる）。

    時刻が落ちる行＝spec と組になった行のうち、時刻の欄が空でなく、作り直した板で表示されていた時刻が消えるか変わるもの——
    時刻の欄が H:MM でない、時刻の欄が作り直した板の時刻（new_time）と違う、または「明日以降」の行で実施日の時刻が new_time と違う。
    new_time は作り直した板で使われる時刻（今日の予定・今日中の行と、実施日の無い「明日以降」の行は spec の time、
    「明日以降」の行で実施日のあるものは spec の実施日の時刻。どちらも無ければ None）。板の時刻の欄は H:MM と決まっていて、
    H:MM でない時刻は作り直した板に残らず、消えるか spec の時刻に変わる。「明日以降」の行で実施日のあるものは、spec が time と due を
    一緒に受けないので、作り直した板には時刻の欄が無く、残るのは実施日の時刻だけ——時刻の欄と実施日の時刻が食い違う行は、
    どれを選んでも板に表示されていた時刻の少なくとも一方が消える（いまの板のまま今日の側へ動かすと、時刻の欄の時刻が使われる・v1.7）。
    どれもユーザーが書いた時刻が確かめなしに変わるので、ユーザーが確かめる。時刻の欄と実施日の時刻が同じ行は数えない
    （「明日以降」の行では、作り直した板に時刻の欄は無くなるが、同じ時刻が実施日に残り、今日の側へ動かすときはそれが使われる。
    一度移した印の有無によらない＝v1.7。v1.6 までは、印のある行を move・D&D で今日の側へ動かすと時刻の欄が使われ、作り直した後は時刻が無くなった）。今日の予定・今日中の行と、実施日の無い「明日以降」の行で、H:MM の時刻の欄で組になったものは、
    時刻が同じなので数えない。各行の due は元の行の実施日（無ければ None）。

    各行の no は、それぞれの一覧の中の番号（1 から）。status の index（板の中の番号）とは別物なので、
    板の中の番号は status_index として持たせる（ユーザーに見せる番号は no）。
    """
    def key(section, time, title, due):
        # 「明日以降」の行は、実施日の日付と時刻（実施日の時刻、無ければ H:MM の時刻の欄。v1.7 の操作では、両方あれば同じ値）で比べる。
        # 時刻を due に含めて写した行（spec は「明日以降」の行で time と due を一緒に受けない）を、消える行に数えないため
        raw = time
        day = None
        alt = None
        if isinstance(due, str) and due.strip() and _canon_label(section or "") == TOMORROW:
            try:
                pd = parse_due_value(check_due(due))
            except OpError:
                pd = None
            if pd is None:
                day = None          # 読めない実施日は比べない（spec はその値を受けないので、比べると行を残す手段が無くなる）
            else:
                day = pd[0].isoformat()
                if pd[1]:
                    time = pd[1]
                    # 時刻の欄が実施日の時刻と違う行（食い違う行）は、時刻の欄の時刻（H:MM でなければどの時刻でも）でも組にしてよい
                    if isinstance(raw, str) and raw.strip() and _norm_time(raw) != pd[1]:
                        alt = _norm_time(raw) if HM_RE.match(raw.strip()) else ANY_TIME
                elif not (isinstance(time, str) and HM_RE.match(time.strip())):
                    time = None
        if isinstance(time, str) and time.strip() and not HM_RE.match(time.strip()):
            time = None         # H:MM でない時刻は比べない（spec の time は H:MM だけを受けるので、比べると行を残す手段が無くなる）
        # 時刻の欄が H:MM でなく、実施日からも時刻が決まらない行は、時刻を問わずに組にしてよい（wild）
        if isinstance(raw, str) and bool(raw.strip()) and not HM_RE.match(raw.strip()) and time is None:
            alt = ANY_TIME
        return (section, _norm_time(time), title, day), alt

    want = [key(it.get("section"), it.get("time"), it.get("title"), it.get("due"))[0] for it in spec.get("items") or []]
    used = [False] * len(want)
    entries, complete = item_entries(old_text)
    keyed = [(e,) + key(e["section"], e["time"], e["title"], e["due"]) for e in entries]
    pair = {}

    def take(n, ok):
        for j, w in enumerate(want):
            if not used[j] and ok(w):
                used[j] = True
                pair[n] = w
                return True
        return False

    for n, (e, k, alt) in enumerate(keyed):
        if alt is None:
            take(n, lambda w, k=k: w == k)
    for n, (e, k, alt) in enumerate(keyed):
        if alt is not None:
            take(n, lambda w, k=k: w == k)
    # 時刻を問わない組は、食い違う H:MM の行（時刻の欄の時刻、次に時刻なし）を先に、ANY_TIME の行を後に
    # （ANY_TIME の行が、時刻の欄の時刻で組にしたい行の spec の行を横取りしないため）
    same = lambda w, k: (w[0], w[2], w[3]) == (k[0], k[2], k[3])
    for want_time in ("alt", None):
        for n, (e, k, alt) in enumerate(keyed):
            if alt is not None and alt is not ANY_TIME and n not in pair:
                take(n, lambda w, k=k, t=(alt if want_time == "alt" else None): same(w, k) and w[1] == t)
    for n, (e, k, alt) in enumerate(keyed):
        if alt is ANY_TIME and n not in pair:
            take(n, lambda w, k=k: same(w, k))
    out, dropped = [], []
    for n, (e, k, alt) in enumerate(keyed):
        if n not in pair:
            r = {"no": len(out) + 1, "status_index": e["index"]}
            r.update({f: e[f] for f in ("section", "time", "title", "chip", "note", "crit", "due", "due_moved", "due_from")})
            out.append(r)
            continue
        t, new = e["time"], pair[n][1]
        # 時刻の欄が H:MM でない行・作り直した板の時刻と違う行と、「明日以降」の行で実施日の時刻が変わる行（時刻の欄が実施日の時刻と
        # 食い違う行は、どちらを選んでもこれに当たる。v1.5）。時刻の欄が無い行は数えない（実施日の時刻を変えたのは spec を書いた側）
        if isinstance(t, str) and t.strip() and (not HM_RE.match(t.strip()) or _norm_time(t) != new
                                                  or (alt is not None and k[3] is not None and k[1] is not None and k[1] != new)):
            dropped.append({"no": len(dropped) + 1, "status_index": e["index"], "section": e["section"],
                            "time": t, "new_time": new, "title": e["title"], "due": e["due"]})
    return out, complete, dropped


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
    keys = ("index", "section", "time", "title", "note", "chip", "crit", "carried", "due", "due_moved", "due_from")
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
        t = _key_text(seg, "time", stop_at_class=True)    # status の time と同じ読み方（v1.10）
        title = _element_text(seg, "task-title")
        m = re.search(r'\sdata-carried-from="([^"]*)"', lines[st])
        if title is None or _div_balance(seg) != 0:
            complete = False
        out.append({"index": n, "section": sec, "time": t.strip() if t is not None else None, "title": title,
                    "note": _element_text(seg, "task-note"), "chip": status_chip(seg),
                    "crit": "crit" in _open_tag_classes(seg), "carried": m.group(1) if m else None,
                    "due": _item_open_attr(seg, "data-due"), "due_moved": _item_open_attr(seg, "data-due-moved"),
                    "due_from": _item_open_attr(seg, "data-due-from")})
    return out, complete


def _entry_cmp(e):
    return (e["section"], e["time"], e["title"], e["note"], e["chip"], e["crit"], e["carried"], e["due"], e["due_moved"],
            e["due_from"])


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
    strip = lambda e: {k: e[k] for k in ("section", "time", "title", "note", "chip", "crit", "carried", "due", "due_moved", "due_from")}
    diff = {"only_now": [strip(e) for e in cur_e if _entry_cmp(e) not in src_keys],
            "only_restore": [strip(e) for e in src_e if _entry_cmp(e) not in cur_keys],
            "now_broken": bool(structure_errors(cur_text)),
            "only_now_incomplete": not cur_complete}
    incomplete_note = ("" if cur_complete else
                       "いまの板は形が崩れているため、only_now の行の欄（チップ・補足・実施日など）が欠けているか、拾えていない行がある"
                       "かもしれません（only_now_incomplete）。戻す前に、いまの board.html を Read で読み、only_now に無い行も"
                       "ユーザーに見せてください。欠けた欄は、その Read で読んだ板から写してください"
                       "（戻した後は、戻す前の板が saved の名前で history/ に残ります）。")
    if not a.confirmed:
        return Result(None, {"from": rel, "diff": diff,
                             "message": "まだ戻していません。diff（only_now＝いまの板にだけある行・only_restore＝戻す版にだけある行）を"
                                        "ユーザーに見せ、戻してよいと言われてから --confirmed を付けて実行してください。" + incomplete_note}), bom
    stem = "board-%s-before-restore-%s" % (strict_date_ok(cur_date).isoformat(), datetime.now().strftime("%H%M%S"))
    text = src_text.replace("\r\n", "\n")
    if nl != "\n":
        text = text.replace("\n", nl)
    res = Result(text, {"from": rel, "diff": diff,
                        "message": "戻しました。戻す前の板は saved の名前で残しています。only_now の行をユーザーに見せ、" + restore_readd_text("only_now") + (
                            "" if cur_complete else
                            "戻す前の板は形が崩れていたため、only_now の行の欄が欠けているか、拾えていない行があるかもしれません"
                            "（only_now_incomplete）。saved の板を Read で読み、欠けた欄はそこから写し、only_now に無い行もユーザーに見せてください。")},
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
        # 末尾の形の板は、操作の前に head の形へ移し、移した板に操作を当てる（v1.14・migrate_board_js）。操作の前に移すので、
        # 操作の対象の行の位置と K6〜K8 の比べ方は移した板の上でそろう。置き換える直前の読み直しは、読んだままの old_raw と比べる
        in_raw = old_raw
        if old_raw is not None:
            try:
                t0, b0 = decode_board(old_raw)[:2]
                moved = migrate_board_js(t0)
                if moved is not None:
                    in_raw = encode_board(moved, b0)
            except OpError:
                pass
        res, bom = compute(in_raw)
        if res.text is None:
            return res, False
        if in_raw is not old_raw:
            res.payload["migrated"] = True   # 末尾の形の板を head の形へ移した（v1.14）。操作の中身が何も変わらなくても changed は真になる
        old_text = None
        if in_raw is not None:
            try:
                old_text = decode_board(in_raw)[0]
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
    out["due_now"] = [inf for inf, it in zip(infos, items)
                      if _canon_label(inf["section"] or "") == TOMORROW
                      and _item_due_pending("".join(lines[it["s"]:it["e"] + 1]), today)]
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


# ================================================================ Deck を起動し直す前後の確かめ（v1.2・読むだけ）
#
# 配った板（Deck v2.9 が http://127.0.0.1:<ポート>/?v=<表示の鍵> で配る板）を開いたまま Deck を起動し直すと、
# ポートと表示の鍵が替わることがある。起動し直した直後の板には止まった Deck の接続情報が残っているので
# （Deck は止まっても #deck-key を消さず、新しい Deck が書くのは常駐の1周目）、data-k（起動ごとのトークン）が
# 替わるまで待ってから比べる。待ち・打ち切り・watcher.log の読み分けを1回の呼び出しの中で行い、上限で必ず終わる。
# 出力にはトークンと表示の鍵を出さない（指紋〔sha256 の先頭〕だけ。新しい URL は --print-url のときだけ出す）。

DECK_KEY_TAG_RE = re.compile(r'<span id="deck-key"[^>]*>')
DECK_LOG_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ")
# watcher.log の読み分け（deck/deck_watcher.py が書く文言。上から順に見る）
DECK_LOG_KINDS = (
    ("duplicate", "多重起動を検出"),
    ("no-port", "をすべてバインドできません"),
    ("no-marker", "DECK:AUTO マーカーが見つかりません"),
)
DECK_LOG_STARTED = "常駐モード開始"
DECK_LOG_REGEN = "再生成: セッション"   # 板へ書けたときの行（書けなかったときの行では数えない）
DECK_LOG_REGEN_SKIPPED = "再生成: 書く直前に"   # 書けなかったときの行（数えないが log には入れる＝書き込みが競合したことが見える）
DECK_LOG_SERVER = "受信サーバ起動"
DECK_FP_RE = re.compile(r"^[0-9a-f]{16}$")


def _fp(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else None


def _tag_attr(tag, name):
    m = re.search(r'\s%s="([^"]*)"' % re.escape(name), tag)
    return html.unescape(m.group(1)) if m else None


def read_deck_key(board_path):
    """board.html の DECK マーカーの間の #deck-key を読む。
    目印が START・END の順に1つずつ、別々の行にあるときだけ間を読む（skill/SKILL.md の読み方と同じ。目印の外に残った
    古い #deck-key は読まない）。戻り値 {"markers": "ok"|理由, "present": bool, "k": …, "port": …, "view": …}"""
    out = {"markers": "ok", "present": False, "k": None, "port": None, "view": None}
    try:
        with open(board_path, "rb") as f:
            text = f.read().decode("utf-8-sig", errors="replace")
    except OSError:
        out["markers"] = "no-board"
        return out
    if text.count(MARKER_START) != 1 or text.count(MARKER_END) != 1:
        out["markers"] = "count"
        return out
    a, b = text.index(MARKER_START), text.index(MARKER_END)
    if not a < b:
        out["markers"] = "order"
        return out
    region = text[a + len(MARKER_START):b]
    if "\n" not in region:
        out["markers"] = "same-line"
        return out
    m = DECK_KEY_TAG_RE.search(region)
    if not m:
        return out
    tag = m.group(0)
    out["k"] = _tag_attr(tag, "data-k") or None
    port = _tag_attr(tag, "data-port")
    out["port"] = int(port) if port and port.isascii() and port.isdigit() and 1 <= int(port) <= 65535 else None
    out["view"] = _tag_attr(tag, "data-view") or None
    out["present"] = bool(out["k"]) and out["port"] is not None
    return out


def _public_key(key):
    return {"markers": key["markers"], "present": key["present"], "k_fp": _fp(key["k"]) if key["present"] else None,
            "port": key["port"] if key["present"] else None, "view_fp": _fp(key["view"]) if key["present"] else None}


def default_deck_log(board_path):
    return os.path.join(os.path.dirname(os.path.abspath(board_path)), "deck", "watcher.log")


def deck_log_since(log_path, since):
    """watcher.log のうち、時刻が since（YYYY-MM-DD HH:MM:SS）以後の行。時刻の読めない行は直前の行と同じ扱いにする。"""
    try:
        with open(log_path, "rb") as f:
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out, keep = [], False
    for ln in lines:
        m = DECK_LOG_TIME_RE.match(ln)
        if m:
            keep = m.group(1) >= since
        if keep:
            out.append(ln)
    return out


def classify_deck_log(lines):
    """起動し直した後の watcher.log の行から、data-k が替わらない理由を読み分ける。
    duplicate／no-port／no-marker／collecting（常駐を始めたが、まだ再生成もこれらの行も無い）／unknown／not-started"""
    for kind, word in DECK_LOG_KINDS:
        if any(word in ln for ln in lines):
            return kind
    started = [i for i, ln in enumerate(lines) if DECK_LOG_STARTED in ln]
    if not started:
        return "not-started"
    after = lines[started[-1] + 1:]
    if any(DECK_LOG_REGEN in ln for ln in after):
        return "unknown"
    return "collecting"


def _parse_since(value):
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        raise OpError("--since は deck-snap が返した since（YYYY-MM-DD HH:MM:SS）をそのまま渡してください。")
    return value


def op_deck_snap(board_path):
    key = read_deck_key(board_path)
    return dict(since=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), deck_key=_public_key(key),
                prev_k_fp=_fp(key["k"]) if key["present"] else "none")


def _seconds(value, name):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = None
    if v is None or not math.isfinite(v):
        raise OpError("--%s は秒の数（有限の数）で指定してください。" % name)
    return v


def op_deck_wait(board_path, a, sleep=time.sleep, clock=time.monotonic):
    prev = a.prev_k_fp
    if not prev or not (prev == "none" or DECK_FP_RE.match(prev)):
        raise OpError("--prev-k-fp に、起動し直す前の deck-snap が返した prev_k_fp（16 桁の 16 進か none）をそのまま渡してください。")
    since = _parse_since(a.since)
    log_path = os.path.abspath(os.path.expanduser(a.log)) if a.log else default_deck_log(board_path)
    url_port = url_view = None
    if a.url:
        try:
            u = urllib.parse.urlsplit(a.url)
            url_port = u.port            # ポートが数でない・範囲外なら ValueError。ポートの無い URL は None（比べずに written）
        except ValueError:
            raise OpError("--url の形が正しくありません（ポートを読めません）。開いている板の URL をそのまま渡してください。")
        url_view = (urllib.parse.parse_qs(u.query).get("v") or [None])[0]
    interval = max(0.01, _seconds(a.interval, "interval"))
    limit, extra = max(0.0, _seconds(a.limit, "limit")), max(0.0, _seconds(a.extra, "extra"))
    start = clock()
    deadline = start + limit
    extended = False
    key = None
    result = None
    while True:
        key = read_deck_key(board_path)
        cur = _fp(key["k"]) if key["present"] else "none"
        # 読めなかった周回（板が無い・開けない）と、目印が崩れていて間を読めない周回は、替わったかどうかの判断に使わない
        # （崩れた板では接続情報が「消えた」と見分けられないため。上限まで崩れたままなら board-markers を返す）
        if key["markers"] == "ok" and cur != prev:
            # 替わった（#deck-key が現れた・替わった・消えた）
            if not key["present"]:
                result = "no-key"
            elif url_port is None:
                result = "written"
            elif key["port"] == url_port and key["view"] == url_view:
                result = "same-url"
            else:
                result = "open-new-url"
            break
        lines = deck_log_since(log_path, since)
        kind = classify_deck_log(lines)
        if kind == "duplicate":
            result = kind          # 新しい Deck はもう終わっている。待っても替わらない
            break
        if clock() >= deadline:
            if key["markers"] not in ("ok", "no-board"):
                result = "board-markers"
                break
            if kind == "collecting" and not extended:
                extended = True
                deadline += extra
                continue
            result = "not-written-yet" if kind == "collecting" else kind
            break
        # 最後の待ちは残り時間で切り詰める（待ちの合計が limit＋extra を超えない）
        sleep(max(0.0, min(interval, deadline - clock())))
    lines = deck_log_since(log_path, since)
    # 起動の手がかりの行（最後の 10 行と、手がかりの文言ごとの最後の1行）と、unknown のときの「再生成: セッション」の行の最後の1行と、
    # 書けなかった「再生成: 書く直前に」の行の最後の1行を、元の順に並べる
    # （「再生成」の行がいくつ続いても「常駐モード開始」「受信サーバ起動」などを押し出さない。書けなかった行の数は skipped_writes）
    clue_words = [w for _k, w in DECK_LOG_KINDS] + [DECK_LOG_STARTED, DECK_LOG_SERVER]
    main_at = [i for i, ln in enumerate(lines) if any(w in ln for w in clue_words)]
    last_each = [max(i for i in main_at if w in lines[i]) for w in clue_words if any(w in lines[i] for i in main_at)]
    regen_at = [i for i, ln in enumerate(lines) if DECK_LOG_REGEN in ln] if result == "unknown" else []
    skipped_at = [i for i, ln in enumerate(lines) if DECK_LOG_REGEN_SKIPPED in ln]
    picked = [lines[i] for i in sorted(set(main_at[-10:]) | set(last_each) | set(regen_at[-1:]) | set(skipped_at[-1:]))]
    out = dict(result=result, waited_sec=round(clock() - start, 1), extended=extended,
               deck_key=_public_key(key), log=picked, skipped_writes=len(skipped_at), log_path=log_path)
    if a.url and key["present"]:
        out["port_changed"] = key["port"] != url_port
        out["view_changed"] = key["view"] != url_view
    if a.print_url and result in ("open-new-url", "written") and key["present"] and key["view"]:
        out["url"] = "http://127.0.0.1:%d/?v=%s" % (key["port"], urllib.parse.quote(key["view"], safe=""))
    return out


# ================================================================ コマンドライン

HELP = """きょうのボード（board.html）を書き換える専用のスクリプトです。Claude は board.html を直接書かず、これを使います。
出力は標準出力に JSON 1つ（ok・changed・progress・warnings・board ほか。末尾で board.js を読む形の板を head の形へ移した書き込みでは
migrated: true が付き、操作の中身が何も変わらなくても changed は真になる＝v1.14）。拒否・失敗のときは終了コードが 0 以外になり、
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
                  "セクションと項目の一覧（index・key・time・title・note・chip・crit・carried・due・due_moved・due_from）・"
                  "due_now（「明日以降」の行で実施日が今日以前のもの）・進捗・検査の結果・"
                  "restorable（history/ にある、restore が受ける名前の版）・restorable_today（そのうち、いまの板と日付が同じで形の正しい、"
                  "restore で実際に戻せる版）")
    sp = add("create", "spec（JSON）から今日のボードを作り、静的ファイル3つを board.html の隣へ写す。"
                       "置き換える前の板は history/board-<日付>-before-create-<時刻>.html に残す。"
                       "restore で戻せるのは、その版のヘッダの日付がいまの板と同じで形も正しいときだけ"
                       "（前の日の板・日付の読めない板・形の崩れた板は history/ に残るだけで、restore では戻せない）。"
                       "いまの板が今日のものか日付の読めない板で（Deck が引き継いだ板を除く）、spec に無い行があるとき、"
                       "または形が崩れていて spec に無い行を拾いきれないときは、--confirmed が無ければ書かずに missing（消える行）と"
                       " missing_incomplete（拾いきれていないとき true）を返す。同じ板で、時刻の欄が H:MM でない（「午後」など）行を spec に時刻なしで"
                       "入れたとき・H:MM の時刻で入れたとき、「明日以降」の行で時刻の欄が実施日の時刻と違う（H:MM でも。v1.5 から）行を入れたときも、--confirmed が無ければ書かずに dropped_times（時刻が消えるか変わる行。new_time は作り直した板での時刻か null）を返す（板の時刻の欄は H:MM と決まっていて、"
                       "H:MM でない時刻は残さない）。書いた後の出力にも removed（消えた行）と dropped_times（時刻が消えたか変わった行）を出す（v1.4 から）。"
                       "state.json は書かない（SKILL.md の手順で書く）")
    sp.add_argument("--confirmed", action="store_true", help="spec に無い行が消えること・時刻の欄の時刻が消えるか変わること（dropped_times）をユーザーが確かめた後に付ける")
    sp.add_argument("--spec", help="{\"sections\": [見出し…], \"items\": [{\"section\", \"time\"?, \"title\", \"note\"?, \"chip\"?, \"crit\"?, \"due\"?, \"due_moved\"?, \"due_from\"?}…]} の JSON ファイル。"
                                            "「明日以降」の行で due が今日以前・due_moved が無いものは、今日の側へ置く（出力の moved_due。実施日は今日になり、元の実施日は due_from に残る）。"
                                            "今日の予定・今日中の行の due は、元の行の due と due_moved（と due_from）を写すときだけ書く"
                                            "（due が今日でなければ、実施日を今日にし、元の実施日を due_from に残す・v1.7。先の日の due は v1.9 から）")
    sp = add("add", "見出しの中に項目を1行足す（必ず足す。重複かどうかは先に status で確かめる）")
    sp.add_argument("--section", required=False, help="足す先の見出し")
    sp.add_argument("--create-section", action="store_true", help="見出しが無ければ作る")
    sp.add_argument("--after", help="この項目の直後に足す（既定は見出しの末尾。今日の予定へ時刻付きの行を足すときは時刻の順の位置）")
    sp.add_argument("--head", action="store_true", help="見出しの直後（先頭）に足す")
    sp.add_argument("--title")
    sp.add_argument("--note")
    sp.add_argument("--chip", help="done・active・pending・wait・hold・none（既定は「明日以降」なら none、それ以外は pending）")
    sp.add_argument("--time", help="H:MM（付けると時刻付きの行、無ければ時刻なしの行）")
    sp.add_argument("--due", help="実施日。YYYY-MM-DD か YYYY-MM-DD H:MM。「明日以降」の行（--time とは一緒に使えない）と、"
                                  "今日の予定・今日中へ足し直す行（元の行の due を写すとき。--due-moved と対で）に付く")
    sp.add_argument("--due-moved", help="一度移した印の日付（YYYY-MM-DD）か none。足し直す行に元の行の due_moved を写すときに --due と一緒に使う"
                                        "（今日の予定・今日中の行では --due に必ず添える）")
    sp.add_argument("--due-from", help="元の実施日（YYYY-MM-DD か YYYY-MM-DD H:MM）か none。足し直す行に元の行の due_from を写すときに --due と一緒に使う"
                                       "（null なら省く。v1.7）")
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
    sp = add("set-time", "項目の時刻を替える（--time none で時刻を外す）。実施日のある行では、実施日の時刻も同じ値にする"
                         "（--time none なら実施日の時刻も外す。時刻の欄の無い行の --time none は何もしない。日付と一度移した印は変えない。v1.7）")
    sp.add_argument("--item")
    sp.add_argument("--time")
    sp = add("set-due", "「明日以降」の行の実施日を付ける・直す（--due none で印と一緒に外す）。実施日が来ると Deck の日付の切り替えが今日の側へ移す。"
                        "今日の予定・今日中の行には、元の行の実施日を写し直すときだけ --due-moved と対で付ける。"
                        "時刻を含めて付けると、時刻の欄があればそれも同じ時刻にする（時刻の欄が無ければ足さない。v1.7）")
    sp.add_argument("--item")
    sp.add_argument("--due", help="YYYY-MM-DD か YYYY-MM-DD H:MM か none")
    sp.add_argument("--due-moved", help="一度移した印の日付（YYYY-MM-DD）か none（省くと印を外す。今日の予定・今日中の行では --due に必ず添える）")
    sp.add_argument("--due-from", help="元の実施日（YYYY-MM-DD か YYYY-MM-DD H:MM）か none（省くと外す。元の行の due_from を写すときに付ける・v1.7）")
    sp = add("move", "項目を 今日の予定・今日中・明日以降 の間で動かす（位置は Deck の D&D と同じ。ただし今日の予定へは、--before・--head が無ければ"
                     "時刻の順の位置へ入る）。実施日のある「明日以降」の行を今日の側へ動かすときは、Deck の日付の切り替えと同じ形にする"
                     "（今日の予定へは実施日が今日なら時刻の欄をその行の時刻〔時刻の欄が H:MM ならそれ、無ければ実施日の時刻〕にし、それ以外と今日中へは時刻の欄を外す〔行の時刻は data-due か data-due-from に残り、data-orig-time には残さない＝v1.8。H:MM でない時刻の欄の文字と、data-due-from が既にある行で時刻の欄の時刻がその時刻と違うときの時刻の欄の時刻は、どこにも残らない〕。"
                     "状態チップが無ければ未を付け、実施日を今日にし、元の実施日を data-due-from に残し、一度移した印を付ける。印のある行・実施日の前の行も同じ形にする＝v1.7。実施日の前の行〔先の日の行〕も今日の行として扱い、実施日を今日にして時刻の欄を外し〔今日の予定へも時刻は付かない〕、元の予定を data-due-from に残し、印を付ける＝v1.9）。"
                     "今日の予定・今日中の行を「明日以降」へ動かすときは --due が要る（ユーザーに確かめた実施日か none＝未定。v1.9）")
    sp.add_argument("--item")
    sp.add_argument("--section", help="行き先（今日の予定・今日中・明日以降）")
    sp.add_argument("--before", help="この項目の直前へ（既定は見出しの末尾。今日の予定では時刻の順の位置）")
    sp.add_argument("--head", action="store_true", help="見出しの直後（先頭）へ")
    sp.add_argument("--create-section", action="store_true", help="行き先の見出しが無ければ作る（v1.3。add の --create-section と同じ位置）")
    sp.add_argument("--due", help="今日の予定・今日中の行を「明日以降」へ動かすときの実施日（YYYY-MM-DD か \"YYYY-MM-DD H:MM\"。明日以後）か none（未定）。"
                                  "ユーザーに確かめた値を渡す。印と元の実施日は外れ、時刻の欄はこの時刻になる（時刻が無ければ外す。none では変えない）・v1.9")
    sp = add("close-time", "閉じタグの無い時刻の欄（警告 K15）に閉じタグを補う（v1.10）。欄の時刻の文字の直後に、欄と同じ名前の"
                           "閉じタグを足すだけで、タスクの文言・状態・位置と行の鍵は変えない。欄が div のとき・閉じタグを足すと数が合わなくなる"
                           "とき・欄の始まりの直後に時刻の文字が無いとき・時刻の文字の後ろにタグで囲んだ文字があるときは書かずに断る"
                           "（断った後の扱いは SKILL.md の「ボードの点検」の⑥）。ブラウザが欄をタイトルやチップの手前で閉じる形（画面は正しい形）"
                           "では、ブラウザが閉じる位置（その手前の空白を除く）に足し、この断り方はしない（欄の中で閉じていない要素があれば、その閉じタグも足す。v1.12）。"
                           "ただし、書式の要素〔b・i・a など〕が欄の中で閉じていない行は --confirmed のときだけ補い（タイトルやチップを包んでいた書式が外れ、"
                           "画面が変わる。ユーザーに確かめてから付ける）、欄そのものが書式の要素の行と、欄の中で table・object・script などが閉じていない行は"
                           "上の判定に戻る")
    sp.add_argument("--item")
    sp.add_argument("--confirmed", action="store_true",
                    help="時刻の欄の中に閉じていない書式の要素がある行で、タイトルやチップの書式が外れることをユーザーが確かめた後に付ける（v1.12）")
    sp = add("remove", "項目を1行消す。--confirmed が無ければ対象を示すだけで消さない")
    sp.add_argument("--item")
    sp.add_argument("--confirmed", action="store_true")
    add("deck-snap", "Deck を起動し直す前に呼ぶ（読むだけ・v1.2）。DECK マーカーの間の #deck-key を読み、"
                     "prev_k_fp（起動ごとのトークンの指紋。#deck-key が無ければ none）と since（いまの時刻）を返す。"
                     "トークンと表示の鍵は出さない")
    sp = add("deck-wait", "Deck を起動し直した後に呼ぶ（読むだけ・v1.2）。#deck-key のトークンが deck-snap のときから替わるまで "
                          "--interval 秒ごとに読み直し、替わったら --url（開いている板の URL）のポートと ?v= と比べて result を返す: "
                          "same-url（そのままでよい）／open-new-url（新しい URL を開く。--print-url で url も出す）／written（--url なし・ポートの無い URL）／"
                          "no-key（#deck-key が消えた）。目印が崩れて間を読めないまま --limit 秒たてば board-markers。--limit 秒たっても替わらなければ、watcher.log の --since 以後の行で読み分ける: "
                          "duplicate（同じボードを見る古い Deck が動いていて、新しい Deck はすぐ終わった。この行が出た時点で返す）／"
                          "no-port（受信ポートを取れずに動いている）／no-marker（板に書けていない）／"
                          "collecting（transcript を集めている途中）なら --extra 秒だけ待ち足し、それでも替わらなければ not-written-yet／"
                          "unknown（「再生成: セッション」の行はあるのに替わらない。その行の最後の1行も log に入れる）／not-started（どの行も無い＝起動できていない）。"
                          "書けなかった「再生成: 書く直前に」の行は、どの result でも最後の1行を log に入れ、数を skipped_writes に出す（無ければ 0）"
                          "（log はほかに起動の手がかりの行を最後の 10 行までと、手がかりの文言ごとの最後の1行。「再生成」の行がいくつ続いても押し出されない）。上限で必ず終わる")
    sp.add_argument("--prev-k-fp", dest="prev_k_fp", help="deck-snap が返した prev_k_fp（16 桁の 16 進か none）")
    sp.add_argument("--since", help="deck-snap が返した since")
    sp.add_argument("--url", help="開いている板の URL（ポートと ?v= を比べる。省いたとき・ポートの無い URL では比べずに written を返す）")
    sp.add_argument("--print-url", action="store_true", help="result が open-new-url・written のとき、新しい URL を出す（表示の鍵が出力に入る）")
    sp.add_argument("--log", help="watcher.log のパス（既定は board.html と同じフォルダの deck/watcher.log）")
    sp.add_argument("--interval", default="2", help="読み直す間隔の秒（既定 2）")
    sp.add_argument("--limit", default="60", help="替わるのを待つ上限の秒（既定 60）")
    sp.add_argument("--extra", default="60", help="transcript を集めている途中のときに待ち足す秒（既定 60・1回だけ）")
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
        elif v is None and name == "due-moved" and obj.get("due") not in (None, "none"):
            rest.append("--due-moved=none")     # status の due_moved（null＝印なし）をそのまま写した ops も通す
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
            "set-time": op_set_time, "set-due": op_set_due, "move": op_move, "remove": op_remove,
            "close-time": op_close_time}


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
        if op == "deck-snap":
            emit(dict(ok=True, op=op, version=VERSION, board=board_path, **op_deck_snap(board_path)))
            return 0
        if op == "deck-wait":
            emit(dict(ok=True, op=op, version=VERSION, board=board_path, **op_deck_wait(board_path, a)))
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
