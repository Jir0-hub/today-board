# -*- coding: utf-8 -*-
"""K16（_swallow_open）の試験の形と、試験の板の作り方（tests/test_swallow.py と tests/test_board_browser.py が使う。データだけで何も import しない）。

CASES の真偽は「当たる」＝ソースの項目・見出し・行の部品・Deck の要素のどれかが、ブラウザの DOM に HTML の要素として無いか、board.js が動かない
（K16 の基準＝画面から消える要素がある形と、実行されるはずの board.js の読み込みが実行されない形・2026-11-10 ユーザー決定）。Chrome のヘッドレスで、
test_board_browser.TestSwallowInBrowser が1つの形を1ページで確かめる（2026-11-10・Tech Lead・n=1）。
形は、1つ目の項目の補足（task-note）の中に入れる。@END@ で始まる形は板の終わりに足し、
@JS@ で始まる形は板の board.js の読み込みと入れ替える。
"""
import re

# data-probe を付けた要素（id:要素の名前）。DOM に HTML の要素として同じ名前で無ければ「消えた」
PROBES = ["s1:div", "i1:div", "ti1:p", "n1:p", "c1:div", "cp1:span", "s2:div", "i2:div", "ti2:p", "d1:span", "d2:div"]
ROWS = ('<div class="section-label" data-probe="s1">今日の予定</div>\n'
        '  <div class="item" data-probe="i1"><span class="time">9:00</span><div><p class="task-title" data-probe="ti1">A</p>'
        '<p class="task-note" data-probe="n1">@@</p><div class="chips" data-probe="c1"><span class="chip pending" data-probe="cp1">未</span></div></div></div>\n'
        '  <div class="section-label" data-probe="s2">今日中</div>\n'
        '  <div class="item flat" data-probe="i2"><div><p class="task-title" data-probe="ti2">B</p></div></div>')
DECK_PARTS = ('<span id="deck-key" hidden data-port="18999" data-k="t-x" data-probe="d1"></span>'
              '<div class="deck-card" data-probe="d2">セッション</div>')
BOARD_JS = '<script src="board.js"></script>'
HEAD_JS = '<script src="board.js" defer></script>'


def board(template, today, tail=True):
    """実物のテンプレート（template の文字）から、項目2つ・見出し2つ・Deck の要素2つの今日の板を作る（形を入れる所は @@）。
    tail が真なら、board.js の読み込みを末尾の形（body の最後に BOARD_JS。2026-11-10 以前のテンプレート）にする。偽ならテンプレートのまま
    （head に defer で読む形＝HEAD_JS）。CASES の真偽は末尾の形の板で決めたもの（@JS@ の形は末尾の形の板だけで使う）。"""
    t = template
    if tail and HEAD_JS in t:
        t = t.replace(HEAD_JS + "\n", "", 1).rstrip("\n") + "\n\n" + BOARD_JS + "\n"
    for k, v in {"{{TITLE_DATE}}": "%d/%d" % (today.month, today.day), "{{FULL_DATE}}": today.strftime("%Y-%m-%d"),
                 "{{UPDATED_AT}}": "00:00", "{{DONE}}": "0", "{{TOTAL}}": "2", "{{PERCENT}}": "0"}.items():
        t = t.replace(k, v)
    t = re.sub(r"<!-- \{\{SECTIONS\}\}.*?-->", lambda m: ROWS, t, flags=re.S)
    return t.replace("<!-- DECK:AUTO:START -->", "<!-- DECK:AUTO:START -->" + DECK_PARTS)


def page(t, snip):
    """board() の板に形を入れた文字。@END@ の形は @@ を n にした板の終わりに足し、@JS@ の形は板の board.js の読み込みと入れ替える。"""
    if snip.startswith("@END@"):
        return t.replace("@@", "n") + snip[5:]
    if snip.startswith("@JS@"):
        return t.replace("@@", "n").replace(BOARD_JS, snip[4:], 1)
    return t.replace("@@", snip)


# (形, 当たるか)
CASES = [
    ('<textarea>', True),
    ('<textarea/>', True),
    ('<TEXTAREA>', True),
    ('<title>x', True),
    ('<style>', True),
    ('<xmp>', True),
    ('<iframe>', True),
    ('<noembed>', True),
    ('<noframes>', True),
    ('<noscript>', True),
    ('<script>', True),
    ('<script><!--<script></script>x', True),
    ('<plaintext>', True),
    ('<!-- x', True),
    ('<svg><foreignObject><textarea>x</foreignObject></svg>', True),
    ('<svg><span><textarea>', True),
    ('<math><mi><style>', True),
    ('<math><annotation-xml encoding="text/html"><style>', True),
    ('<svg><font color="red"><textarea>', True),
    ('<svg><style>x</style></svg><textarea>', True),
    ('<svg><foreignObject><span>x</svg><textarea>', True),
    ('<svg><![CDATA[x', True),
    ('<textarea>a</textarea >', False),
    ("<script>var a='</scriptx>';</script>", False),
    ('<script><!--x</script>', False),
    ('<style>a</style>', False),
    ('<TITLE>x</Title>', False),
    ('<!-- a -->', False),
    ('<svg><style>x</svg>', False),
    ('<svg><title>x', False),
    ("<div title='<script>'>x</div>", False),
    ('<math><mi><mglyph><style>', False),
    ('<math><annotation-xml><style>', False),
    ('<svg><font><textarea>', False),
    ('<!x', False),
    ('<select>', False),
    ('<select><option>x', False),
    ('<template>', True),
    ('<frameset>', False),
    ('<table>', False),
    ('<object>', False),
    ('<svg>', False),
    ('<math>', False),
    ('<details>', False),
    ('<span class="x', True),
    ('<span title="x', True),
    ("<a b='x>", True),
    ('<!-- x --!>', False),
    ('<!x <div>', False),
    ('</1 x', False),
    ('<?x', False),
    ('@END@<textarea>', False),
    ('@END@<!-- x', False),
    ('@END@<plaintext>', False),
    ('@END@<template>', False),
    ('@JS@<script src="board.js">', True),
    ('@JS@<script src="board.js">x', True),
    ('@JS@<script src="board.js"></scrip', True),
    ('@JS@<script src="board.js" type="text/plain"></script>', True),
    ('@JS@<script src="board.js" nomodule></script>', True),
    ('@JS@<script src="board.js" type="module"></script>', True),
    ('@JS@<script src="board.js" async></script>', False),
    ('@JS@<script src="./board.js?v=1"></script>', False),
    ('@JS@<script src="board.js" type=" TEXT/JavaScript "></script>', False),
    ('@JS@<template><script src="board.js"></script></template>', True),
    ('@JS@<template><script src="board.js"></script>', True),
    ('@JS@<svg><script src="board.js"></script></svg>', True),
    ('@JS@<!-- <script src="board.js"></script> -->', True),
    ('@JS@<textarea><script src="board.js"></script></textarea>', True),
    ('@JS@<noscript><script src="board.js"></script></noscript>', True),
    ('@JS@<svg><foreignObject><script src="board.js"></script></foreignObject></svg>', False),
    ('@JS@<script>x</script><script src="board.js"></script>', False),
    ('@JS@<script src="board.js"></script><textarea>', False),
    ('<textarea>a<textarea>b</textarea>', False),
    ('<script>a<script>b</script>', False),
    ('<style>/* <style> */</style>', False),
    ('<title>a<title>b</title>', False),
    ('<svg></p><textarea>', True),
    ('<svg></br><textarea>', True),
    ('<svg></P><textarea>', True),
    ('<math></p><textarea>', True),
    ('<select><style>', True),
    ('<select><title>', True),
    ('<select><textarea>', True),
    ('<select><xmp>', True),
    ('<select><iframe>', True),
    ('<select><noscript>', True),
    ('<select><plaintext>', True),
    ('<select><script>', True),
    ('<table><style>', True),
    ('<table><textarea>', True),
    ('<svg><p><textarea>', True),
    ('<math><mi></p><textarea>', True),
    ('<svg><desc><textarea>', True),
    ('<svg><title><textarea>', True),
    ('<svg><foreignObject></p><textarea>', True),
    ('<svg><font size=2><textarea>', True),
    ('<math><annotation-xml encoding="TEXT/HTML"><textarea>', True),
    ('<math><annotation-xml encoding=" text/html"><textarea>', False),
    ('<script>a</script x>', False),
    ('<script>a</SCRIPT>', False),
    ('<script><!--<script>a</script>-->x</script>', False),
    ('<script><!--<script>', True),
    ('<script src="x.js">', True),
    ('<script src="./BOARD.JS?v=1">a</script>', False),
    ('<script>a<script src="sub/board.js"></script>', False),
    ('<script>a<script src="board.json"></script>', False),
    ("<script>a<script src='board.js'></script>", False),
    ('<script>a<script src=board.js></script>', False),
    ('<script>a<script src="board&#46;js"></script>', False),
    ('<textarea x', True),
    ('<div <textarea>x</div>', False),
    ('<svg><foreignObject><![CDATA[x', True),
    ('<math><![CDATA[x', True),
    ('<svg><script>x', False),
    ('<svg><plaintext>', False),
    ('<svg><textarea>', False),
    ('<?php x', False),
    ('<!--->', False),
    ('<!-- a --!> b', False),
    ('<!-- a -- >', True),
    ('<template><textarea>', True),
    ('<textarea>x</textarea\n>', False),
    ('<noscript><p>x</noscript>', False),
    ('<svg><g></p><textarea>', True),
    ('<math><mi><svg></p><textarea>', True),
    ('<svg><foreignObject><svg></br><textarea>', True),
    ('<frameset><textarea>', True),
    ('<iframe srcdoc="<textarea>"></iframe>', False),
    ('<object><textarea>', True),
    ('<svg><a></br>x</a></svg>', False),
    ('<svg></p>', False),
    ('<svg></br>', False),
    ('<svg><foreignObject><![CDATA[ a > b', True),
    ('<svg><foreignObject><![CDATA[x]]>y</foreignObject></svg>', False),
    ('<svg><desc><![CDATA[x', True),
    ('<math><mi><![CDATA[x', True),
    ('<math><mi><![CDATA[a>b', True),
    ('<svg><foreignObject><span><![CDATA[x', False),
    ('<math><annotation-xml encoding="text/html"><![CDATA[x', True),
    ('<script>a<script src="board.js"></script>', False),
    ('<script>/* <script src="board.js"> */', True),
    ('<svg><foreignObject><script src="x.js">', True),
    ('<script><!--<script src="board.js"></script>-->x</script>', False),
    ('<script>a<script src=board.js></script><textarea>', True),
    ('<script>a<script src=board.js></script><script>', True),
    ('<script>a<script src=board.js></script><!-- x', True),
    ('<script>a<script src=board.js></script><svg><script src=board.js></script></svg>', False),
    ('<script>a<script src=board.js></script><template><script src="board.js"></script></template>', False),
    ('<script>a<script src="board.js"></script><script src="board.js"></script>', False),
    ('<script src="board.js">', True),
    ('<script src="board.js"></script><script>', True),
    ('<svg><script src="board.js"></script></svg>', False),
    ('<script>a<script src=board.js></script><svg><foreignObject><script>', True),
    ('<script>a<script src=board.js></script><math><mi><![CDATA[x', True),
    ("<script>a<script src=board.js></script><a b='x>", True),
    ('<noscript><script src="board.js"></script></noscript><script>', True),
    ('<script>a<script src="board.js"></script><noscript><script src="board.js"></script></noscript>', False),
    ('<template><script>', True),
    ('<script>a<script src=board.js></script><plaintext>', True),
    ('<script src="board.js"></script><textarea>', True),
    ('<script src="board.js"></script><script>a<script src=board.js></script>', False),
    ('<template><script src="board.js"></script></template><script>', True),
    ('<script src="board.js" type="text/plain"></script><script>', True),
    ('<script src="board.js" nomodule></script><script>', True),
    ('<script src="board.js" type="module"></script><script>', True),
    ('<script src="board.js" async></script><script>', True),
    ('<script src="board.js" type="text/javascript"></script><script>', True),
    ('<svg><foreignObject><script src="board.js"></script></foreignObject></svg><script>', True),
    ('@END@<script src="board.js">', False),
    ('@END@<script>', False),
    ('@END@<script src="board.js">x', False),
    ('@JS@', False),
    ('@JS@<script src="board.js" type="text/javascript; charset=utf-8"></script>', True),
    ('@JS@<script src="board.js" language="vbscript"></script>', True),
    ('@JS@<script src="board.js" type=" TEXT/JAVASCRIPT "></script>', False),
    ('@JS@<script src="board.js" defer></script>', False),
    ('@JS@<script src="./board.js?v=3"></script>', False),
    ('@JS@<SCRIPT SRC="BOARD.JS"></SCRIPT>', False),
    ('@JS@<script src="board.js"></script><script src="board.js" type="text/plain"></script>', False),
    ('@JS@<script src="board.js" type="text/plain"></script><script src="board.js"></script>', False),
    ('@JS@<div title="<script src=\'board.js\'></script>"></div>', True),
    ('@JS@<script src="board.js" src="x.js"></script>', False),
    ('@JS@<script src="x.js" src="board.js"></script>', True),
    ('@JS@<script src="board.js"></script', True),
    ('@JS@<script src="board.js"/>', True),
    ('@JS@<script src="board.js" type=""></script>', False),
    ('@JS@<script src="board.js" type="application/javascript"></script>', False),
    ('@JS@<script src=" board.js "></script>', False),
    ('@JS@<object><script src="board.js"></script></object>', False),
    ('@JS@<select><script src="board.js"></script></select>', False),
    ('<script src="board.js"></script>', False),
    ('<template><script src="board.js"></script></template>', False),
    ('<!-- <script src="board.js"></script> -->', False),
    ('<script src="board.js" type="text/plain"></script>', False),
]

# 板に board.js の読み込みがまるごと無い形。K16 にはしない（試験や sandbox の小さい板のため）。Chrome では board.js は動かない。
# 書く前の版にあった読み込みを消す書き込みは、board_edit.py の K17・guard.py の K17・Deck の退避が受け持つ（2026-11-10 ユーザー決定）
NO_BOARD_JS = [
    '@JS@',
]

# 形の中に行の部品（チップ）を書いた形。K16 は当たる（その部品が画面から消える）。data-probe の要素は消えないので CASES に入れず、
# 「当たる ⇔ 画面の「ボードの点検」の⑦（board.js の TB_CUT）」だけを、head の板と末尾の板の両方で見る（どれも board.js は動く）
CUT_ONLY = [
    '<!x<span class="chip">',
    '<?x<span class="chip">',
    '</ x<span class="chip">',
    '<svg><![CDATA[<span class="chip">]]></svg>',
    '<script src="x.js"><span class="chip">x</span></script>',
    '<textarea><span class="chip">x</span></textarea>',
    '<!-- a <!-- <span class="chip">x</span> -->',
    "<a title=\"<span class='chip'>\">x</a>",
    '<template><span class="chip">x</span></template>',
    '<noscript><span class="chip">x</span></noscript>',
    '<style><span class="chip"></style>',
    '<!x<span class="chip" title="it\'s">',
    '<svg><text><![CDATA[<span class="chip">]]></text></svg>',
    '<!x<span class="chip" title="a>b">',        # 属性の値の中の > で偽のコメントが終わる
    '<?x\n<span class="chip">',                  # <?x の後ろに改行・空白があると、ブラウザは処理命令として読む
    '<?x <span class="chip">',
    '<!x <span class="chip" title="a',           # 閉じていない引用符の値の途中に、後ろの閉じタグの < が入る
]

# K16 に当たらず、⑦（TB_CUT）も出ない形（TB_CUT の偽陽性を直した形を含む）。head の板と末尾の板の両方で見る
NO_CUT = [
    '<svg><foreignObject><p>&lt;span class="chip"&gt;</p></foreignObject></svg>',
    '<script src="x.js">var a = 1;</script>',
    '<script src="x.js"></script>',
    '<!-- memo <div class="item -->',
    '<!x>',
    '<?xml version="1.0"?>',
    '<svg><text>a &lt; b</text></svg>',
    '<svg viewBox="0 0 10 10"><circle r="4"/></svg>',
    '<math><mi>x</mi><mo>&lt;</mo><mi>y</mi></math>',
    '<svg><desc>DECK:AUTO</desc></svg>',
    '<!-- <div class="item" -->',
    '<!-- <span class="chip" -->',
    '<!-- メモ: <p class="task-title" -->',
    '<svg><style>.chip{}</style></svg>',
    '<!-- <div class="item -->',
    '<a title="&lt;b&gt;">x</a>',
    '<?xml version="1.0" encoding="utf-8"?>',
    '<?php echo 1; ?>',
    '<!-- a <b>c</b> -->',
    '<!-- <span class="chip" title="x" -->',
    '<!--<div class="item"<a <a x-->',      # 末尾の開きタグ（<a x）だけを見る
]
# K16 に当たらないが、⑦が出る形（限界。DOM では、エスケープした文字と、空白を挟まずに閉じたコメントが行の開きタグの途中で終わる形を、
# 取り込んだ開きタグと見分けられない）
CUT_LIMIT = [
    '<svg><foreignObject><textarea>&lt;span class="chip"&gt;</textarea></foreignObject></svg>',
    '<!--<div class="item"-->',
    '<!--<span class="chip"-->',
    '<!--x<span class="chip" title="a-->',
    '<a title="&lt;span class=&quot;x&quot;&gt;">x</a>',   # 属性の値にエスケープして書いた開きタグ（TB_CUT の⑤）
    '<svg><text>&lt;span class="chip"&gt;</text></svg>',
    '<math><mi>&lt;span class="chip"&gt;</mi></math>',
    '<textarea>&lt;span class="chip"&gt;</textarea>',
]

# K16 は当たるが、⑦（TB_CUT）が出ない形（見逃しの限界。DOM の処理命令の中身が、引用符で属性の並びとして読めない形など）。⑦は画面の側の目安で、正は status の K16
CUT_MISS = [
    "<?php echo \"<div class='item'\"; ?>",
]
