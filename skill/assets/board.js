  setTimeout(function () { tbReload(); }, 300000);

  // ---- 発行済みボード判定（Deck への書き込みガード・2026-08-05 新設） ----
  // スキルのテンプレ（board-template.html）やアーカイブのコピーをブラウザで開くと、
  // そのブラウザ／オリジンの localStorage の値が Deck へ送られ、本番の通知音設定（deck/sound.json）と
  // 時刻上書きを上書きしてしまった（通知音と ✎ の時刻は 2026-11-02 から操作したときだけ送る。
  // その操作も含めて書き込みを止めるので、この判定は要る）。
  // 2026-08-05 実測: テンプレを開いた直後に watcher.log へ「通知音設定: 有効=OFF」が記録され、
  // 次の本番タブの push（5分周期）まで通知音が黙った（11:31:51→11:33:03・11:43:37→11:48:03）。
  // D&D 移動の POST /board/move に至っては HTML 正本そのものを書き換える。
  // そこで「実際に発行されたボードとして開かれたときだけ書き込む」判定をここで一度だけ行い、
  // 書き込み系の共通出口（deckPost と persistMove の fetch）でまとめてガードする。
  // 呼び出し側ごとに条件を置くと、書き込み経路が増えたときに必ず漏れるため1か所に集約する。
  // 読み取り系（GET /notifications ＝ Deck の生死判定・GET /sound/config ＝⚙の表示・GET /board/times ＝ ✎ の表示）はガードしない。
  // Deck に副作用が無く、テンプレを開いたときも「監視ねこ」の表示は従来どおり動かしたいため。
  // 判定できないときは書かない（fail-closed）。書けずに困るのは今日のボードで操作し直せば済むが、
  // 誤って書いた場合は本番設定が壊れて気づけないため、倒す向きを「書かない」側に固定する。
  var TB_LIVE = (function () {
    // ① 未置換のプレースホルダが残っていれば、発行前のテンプレ。
    //    走査範囲は「プレースホルダが実際に置かれている構造上の位置」だけに限定する。
    //    2026-08-05 監査で誤検知の経路が判明したため。当初は documentElement.innerHTML
    //    全体を走査していたが、それだと発行済みの本番ボードでも本文のどこかに
    //    {{英数字}} の形の文字列が現れた時点で live:false になり、書き込み系4経路
    //    （/sound/config・/board/times・/notifications/ack・/board/move）が画面に
    //    何も出さないまま止まる。成立経路は実在する:
    //      ・スキルの update 手順で各セッションが「今日中」に足すタスク行の文言
    //      ・Deck が DECK:AUTO 領域に書き込むセッションカードのタスク名
    //    どちらもユーザー／他セッションが自由に書く文字列なので、判定に混ぜてはいけない。
    //    board-template.html でのプレースホルダの位置は以下のとおり:
    //      {{TITLE_DATE}} → <title>
    //      {{FULL_DATE}}  → header .date
    //      {{UPDATED_AT}} → #upd-time
    //      {{DONE}} {{TOTAL}} → .progress のテキスト
    //      {{PERCENT}}    → .progress 内 .bar-fill の style 属性（だから属性値も見る）
    //      {{SECTIONS}}   → 本文の HTML コメント内 ← 走査対象から外す（下記）
    //    .item 配下・HTML コメント・DECK:AUTO 領域には一切触れない。
    //    【帰結・正直に記す】{{SECTIONS}} は HTML コメントの中にあり、textContent にも
    //    属性にも現れないため、本文コメントの置換漏れは層①では検出できない。その分は
    //    層②に依存する。
    //    【層①の位置づけ】テンプレの .date は {{FULL_DATE}} のままで日付として読めず、
    //    層②が単独でテンプレをブロックできる（層①が無くてもテンプレは止まる）。
    //    層①は多重防護として残しているだけなので、走査範囲を狭めても防御力は落ちない。
    //    要素が存在しない場合は空文字として扱う（不在をテンプレの証拠とはしない。
    //    不在で倒すと未知のレイアウト変更が新たな誤検知になるため。日付判定＝層②が本命）。
    function tbScan(el) {
      if (!el) return '';
      var out = el.textContent || '';
      var list = [el];
      if (el.querySelectorAll) Array.prototype.push.apply(list, el.querySelectorAll('*'));
      Array.prototype.forEach.call(list, function (n) {
        Array.prototype.forEach.call(n.attributes || [], function (a) { out += ' ' + a.value; });
      });
      return out;
    }
    var probe = [
      document.title || '',
      tbScan(document.querySelector('header')),
      tbScan(document.getElementById('upd-time')),
      tbScan(document.querySelector('.progress'))
    ].join('\n');
    if (/\{\{\s*[A-Za-z0-9_]+\s*\}\}/.test(probe)) {
      return { live: false, why: '未置換のプレースホルダを検出（発行前のテンプレ）' };
    }
    // ② 日付が今日でなければ、アーカイブや過去日のボードのコピー。
    //    読めないときも発行済みとは見なさない。テンプレは {{FULL_DATE}} が数字を
    //    含まず日付として読めないので、ここで単独で止まる。
    //    【年を任意にした理由・2026-08-05 ユーザー裁定】
    //    当初は4桁年を含む表記（「2026-08-05（水）」）だけを受け付けていた。しかしこの
    //    書式要件は board.js のコメントにしか無く、当時の発行側の手順書 SKILL.md は
    //    {{UPDATED_AT}} の HH:MM しか規定していなかった。しかも SKILL.md の artifact モードは
    //    title を「M/D(曜)」と規定しており、年を含まない表記が同じスキル内に前例として
    //    存在する。つまり {{FULL_DATE}} を「8/5（水）」の形で置換した板は、正規の手順で
    //    発行されたのに書き込み4経路が黙って全部止まる——層①の第1版と同型の塞ぎ残し。
    //    対処として、規約（人が守る側）ではなく構造（機械が判定する側）の許容範囲を
    //    広げる形を採った。判定器が発行側へ暗黙の書式を要求している状態そのものが欠陥
    //    なので、要求を消す向きで直した。この緩和は現行であり撤回していない。
    //    【2026-08-05 追記・SKILL.md 側にも規定を置いた】同日、発行側の SKILL.md
    //    （create モード 5）に「{{FULL_DATE}} は半角数字の YYYY-MM-DD（曜）形式」を追記した。
    //    （2026-10-30 以後、ヘッダの日付は Claude ではなく board_edit.py の create が書く。書式の決まりは
    //    今も SKILL.md の create モード 5 にある＝「ヘッダの日付は board_edit.py が…YYYY-MM-DD（曜）形式に書く」）
    //    上の緩和と両立する——判定器は年なし（M/D）も従来どおり受理し、SKILL.md の規定は
    //    下記【失う能力】を避けるために年ありへ寄せた、実装より狭い**発行側の規定**である
    //    （SKILL.md 上は必須）。
    //    したがって年なし表記を理由に live 判定を落とし返してはならない（判定器は緩いまま）。
    //    受け付ける形: 4桁年あり → 年月日で照合／年なし（M/D）→ 月日だけで照合。
    //    年が読めない形では年を条件にしない。日付そのものが読めなければ従来どおり
    //    live:false（fail-closed）。
    //    【失う能力・正直に記す】年の無い板は年を一切照合しないため、同月同日でありさえすれば
    //    何年の板でも今日として通る（2025-08-05 に限らず任意の年）。さらに年なし枝は .date の
    //    最初に現れた数字ペアを採るので、日付より前に今日と同じ数字ペアが現れる表記にすると、
    //    過去日の板が live になる（＝この枝では fail-close が保証されない・未検証）。
    //    ユーザー裁定でこの穴は許容とした。年ありの板は従来どおり年も照合する。
    var txt = ((document.querySelector('header .date') || {}).textContent || '').trim();
    var now = new Date();
    var y = null, mo = null, d = null;
    var m4 = /(\d{4})[^\d](\d{1,2})[^\d](\d{1,2})/.exec(txt);
    if (m4) { y = +m4[1]; mo = +m4[2]; d = +m4[3]; }
    else {
      var m2 = /(\d{1,2})[^\d](\d{1,2})/.exec(txt);
      if (m2) { mo = +m2[1]; d = +m2[2]; }
    }
    if (mo === null) return { live: false, why: 'ヘッダーの日付を読み取れない（"' + txt + '"）' };
    if ((y !== null && y !== now.getFullYear()) || mo !== now.getMonth() + 1 || d !== now.getDate()) {
      return { live: false, why: '今日のボードではない（' + txt + '）' };
    }
    return { live: true, why: '' };
  })();
  if (!TB_LIVE.live) {
    console.info('[today-board] Deck への書き込みを停止しました: ' + TB_LIVE.why + '（読み取りのみ継続）');
  }
  // 書き込み経路が実際にブロックされたときの1行ログ（デバッグ用・UI は変えない）
  function tbBlockWrite(path) {
    console.info('[today-board] 書き込みをブロック: ' + path + '（' + TB_LIVE.why + '）');
  }

  // ---- 切れた画面の判定（2026-11-10 ユーザー決定・TB_CUT） ----
  // board.js を head に defer で読む板（テンプレート・Deck v2.18 / board_edit.py v1.14 が移した板）では、本文の閉じていない要素などが
  // 後ろを飲み込んでも board.js は動く。そのとき、ブラウザが要素として読めなかった行があるかをここで一度だけ決め、「ボードの点検」の⑦に出し、
  // D&D（board.html を書く唯一の経路）を止める。✎ の時刻・ack・通知音の設定は sound.json に書き、見えている行の鍵か板全体の設定で決まるので
  // 止めない。TB_LIVE の判定は変えない（別の判定として持つ。IIFE の外で定義して中から使う名前は TB_LIVE・tbBlockWrite とこれ）。
  // 元の HTML の文字は file: のページでは読めないので、DOM だけで見る（board_edit.py・Deck の K16 は HTML の文字で見る）:
  //   ① テンプレートの最後の要素 #toast-area が無い（後ろが飲み込まれた）
  //   ② body の中の、閉じタグまでを文字として読む要素（textarea・title・style・xmp・iframe・noembed・noframes・noscript・plaintext・
  //      script）の文字に、行の開きタグ（K16 の _SW_ROW_RE と同じ class）か DECK:AUTO の目印がある
  //   ③ template の中身に同じものがある
  //   ④ 中に <!-- があるコメント（後ろのコメントの --> で閉じた形）に同じものがある。自分の --> で閉じたコメント（テンプレートの
  //      記入例など）は見ない（K16 と同じ）
  //   ⑤ 本文の要素の属性の値に同じものがある（引用符の閉じていない属性の値が、後ろの行のタグを取り込んだ形）
  //   ⑥ svg・math の要素の直下の文字に行の開きタグがある（閉じた CDATA の中など）。偽のコメント（<!・<?・</ で始まる形）が > の無い行の開きタグで終わる
  //   限界: DOM では、エスケープした文字（&lt;…&gt;）を svg の text・math・textarea などに書いた形と、自分の --> で閉じたコメントが空白を挟まずに
  //   行の開きタグの途中で終わる形（<!--<div class="item"-->）を、取り込んだ開きタグと見分けられないので、その形でも⑦が出る（K16 は HTML の文字で
  //   見るので出ない。Chrome で確かめた・2026-11-11・n=1）
  var TB_CUT = (function () {
    var ROW = /<[A-Za-z][\w-]*\b[^<>]*?\sclass\s*=\s*["']?(?:[^"'<>]*\s)?(?:task-title|task-note|chips|chip|item|section-label)(?=["'\s>\/])/i;
    function lost(s) { return !!s && (ROW.test(s) || s.indexOf('DECK:AUTO') >= 0); }
    // 属性の値の中の、class を持つ開きタグ（その class の値は、ブラウザが別の属性として読むので、行の class の名前は値に残らない）
    var CLS = /<[A-Za-z][\w-]*\b[^<>]*\sclass\s*=/i;
    // 開きタグの > の手前まで（名前と、属性の並び）。最後の属性に限り、閉じていない引用符の値を許す（属性の値の中の > で偽のコメントが終わった形
    // ＝<!x<div class="section-label" title="a>b">）
    var TAG = /^<[A-Za-z][^\s\/>]*(?:\s+[^\s"'>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*(?:\s+[^\s"'>\/=]+\s*=\s*(?:"[^"]*$|'[^']*$))?$/;
    // 中身の中の開きタグの始まり（<英字）を後ろから順に試し、そこから終わりまでが TAG に合えば、その開きタグを取り込んだとみなして位置を返す（無ければ -1）
    // （閉じていない引用符の値は < や > を含んでよい＝<!x <span class="chip" title="a のように、値の途中に後ろの閉じタグの < が入る形）。
    // 長いコメントで遅くならないよう、試すのは後ろから 20 か所まで
    function tailTag(d) {
      var k = d.length, n = 0;
      while (n < 20 && (k = d.lastIndexOf('<', k - 1)) >= 0) {
        if (/[A-Za-z]/.test(d.charAt(k + 1))) {
          n++;
          if (TAG.test(d.slice(k))) return k;
        }
        if (k === 0) break;
      }
      return -1;
    }
    try {
      if (!document.getElementById('toast-area')) return true;
      var body = document.body;
      if (!body) return true;
      var raw = body.querySelectorAll('textarea,title,style,xmp,iframe,noembed,noframes,noscript,plaintext,script');
      for (var i = 0; i < raw.length; i++) if (lost(raw[i].textContent)) return true;
      // svg・math の中の文字（閉じた CDATA など）。親が svg・math の要素の文字だけを見る（foreignObject の中の HTML の文字は見ない）。
      // 行の開きタグだけを見て、DECK の目印の文字は見ない（<desc> などの説明の文字で出さないため）
      var XHTML = 'http://www.w3.org/1999/xhtml';
      var tw = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null, false);
      for (var tx = tw.nextNode(); tx; tx = tw.nextNode()) {
        var par = tx.parentNode;
        if (par && par.namespaceURI && par.namespaceURI !== XHTML && ROW.test(tx.data)) return true;
      }
      var tm = document.querySelectorAll('template');
      for (var j = 0; j < tm.length; j++) if (lost(tm[j].innerHTML)) return true;
      var all = body.getElementsByTagName('*');
      for (var a = 0; a < all.length; a++) {
        var at = all[a].attributes || [];
        for (var b = 0; b < at.length; b++) if (at[b].value.indexOf('<') >= 0 && (lost(at[b].value) || CLS.test(at[b].value))) return true;
      }
      // コメントと処理命令（<?x の後ろに空白か改行がある形を、ブラウザは処理命令として読む）
      var w = document.createTreeWalker(body, NodeFilter.SHOW_COMMENT | NodeFilter.SHOW_PROCESSING_INSTRUCTION, null, false);
      for (var c = w.nextNode(); c; c = w.nextNode()) {
        if (c.data.indexOf('<!--') >= 0 && lost(c.data)) return true;
        // 偽のコメント（<!・<?・</ で始まり、最初の > で閉じる形）が、> の無い開きタグで終わる＝その開きタグの要素が読まれない。
        // 偽のコメントは、取り込んだ開きタグの > の手前で終わるので、中身は空白で終わらず、末尾はまるごと属性の並びとして読める（TAG）。
        // 中身が空白で終わる形（自分の --> で閉じたコメントの多く。<!-- <div class="item" -->・<!-- memo <div class="item -->）は見ない。
        // 見つけた末尾の開きタグだけを見る（その前の行のタグは、自分の --> で閉じたコメントの中身でもありうるため）
        var tk = /\s$/.test(c.data) ? -1 : tailTag(c.data);
        if (tk >= 0 && lost(c.data.slice(tk) + '>')) return true;
      }
    } catch (err) {
      return false;
    }
    return false;
  })();
  if (TB_CUT) console.info('[today-board] 切れた画面を検出しました（ドラッグでの移動を止めます）');

  // ---- Deck の受信ポート・トークンと、どのボードからの要求かの申告（Deck v2.1 対応・2026-10-23） ----
  // ※この節（DECK_BOARD・DECK_KEY・deckReloadOnce・DECK_STALE_STUCK・deckReloadStale・deckFetch）は
  //   トップレベルに置く。
  //   使い手が2つの IIFE にまたがる（自動機能の deckPost・監視ねこ と、D&D 移動の persistMove）。
  //   v2.1 で persistMove の fetch を deckFetch に置き換えた際、deckFetch が自動機能の IIFE の
  //   中にあったため D&D 側から見えず、ドロップのたびに ReferenceError で移動が保存されなかった
  //   （2026-10-25 修正）。IIFE の外で定義された名前を IIFE の中から使うのは、ここと
  //   TB_LIVE・tbBlockWrite・TB_CUT（2026-11-10）だけにする。
  // 127.0.0.1 は PC 全体で共有され、ブラウザで開いたどのページからも要求を送れる。そこで:
  //   ・Deck は 8737〜8746 のうち空いている最初の1つで受信し、そのポートと起動ごとの
  //     乱数のトークンを、このボードの DECK:AUTO 領域に
  //     <span id="deck-key" hidden data-port="…" data-k="…"> として書く
  //   ・board.js はそれを読み、そのポートへだけ ?board=<このボードの URL>&k=<トークン> を
  //     付けて送る。Deck はトークンかボードが一致しない要求を 403 で断る（読み取りも断る）。
  //     外部のサイトはこのボードを読めず（ブラウザの権限による）、別の Windows ユーザーも
  //     読めない（OS の既定の権限による・未検証）ので、トークンを知りえない
  //   ・ポートを全部探して回ることはしない（トークンを他のプロセスへ送らないため）
  //   ・接続情報がまだ無い（発行直後で Deck が書く前）ときは、少し待って1回だけ読み直す。
  //     トークンが古い（Deck を再起動した）と Deck が 403 "token mismatch" を返すので、
  //     そのときも読み直す。読み直しは自動再読み込み（5分）を待たずに追従するためで、
  //     どちらも sessionStorage で回数を絞る（Deck が無い環境で読み直しを繰り返さない）
  //   ・トークンが古いときの読み直しは、同じトークンのまま2回読み直しても変わらなければ、
  //     それ以上は行わない（2026-10-26）。読み直しても board.html のトークンが変わらない＝
  //     Deck がこのファイルを書いていない（別の場所へ写したボード等）ので、繰り返すと約60秒ごとに
  //     読み直し続けるため。1回目で止めないのは、遅い PC で Deck の最初の書き込みが6秒の待ちに
  //     間に合わなかっただけの正しいボードを、行き詰まり扱いにしないため（2回目は1回目から
  //     60秒以上あとになるので、Deck が書き込むまで1分あまり待つことになる）。
  //     止めたときは DECK_STALE_STUCK を立て、監視ねこの行で知らせるだけにする
  //     （1行目の5分ごとの再読み込みは止めない）
  // 申告とトークンをヘッダでなくクエリで送るのは、独自ヘッダを付けるとブラウザが送信前に
  // OPTIONS の確認（プリフライト）を挟むようになり、従来の単純な要求の形が変わるため。
  var DECK_BOARD = String(location.href).split('#')[0].split('?')[0];
  // DECK:AUTO の目印の間にある要素だけを読む（2026-10-29・Deck v2.5 と同じ単位）。目印の外に残った
  // 古い #deck-key（目印のコメントだけが消えた板を直したとき等）を先に読むと、古いトークンを送って
  // 断られ続けるため。目印が2つそろっていなければ null（接続情報なし＝監視ねこの行で知らせる）。
  // この関数はトップレベルに置く（下の「ボードの点検」も使う）
  function deckRegionElement(id) {
    var s = null, e = null;
    try {
      var w = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT, null, false);
      var n;
      while ((n = w.nextNode())) {
        var t = (n.data || '').trim();
        if (t === 'DECK:AUTO:START' && !s) s = n;
        else if (t === 'DECK:AUTO:END' && s && !e) e = n;
      }
    } catch (err) { return null; }
    if (!s || !e) return null;
    var els = document.querySelectorAll('[id="' + id + '"]');
    for (var i = 0; i < els.length; i++) {
      if ((s.compareDocumentPosition(els[i]) & Node.DOCUMENT_POSITION_FOLLOWING)
          && (e.compareDocumentPosition(els[i]) & Node.DOCUMENT_POSITION_PRECEDING)) return els[i];
    }
    return null;
  }
  var DECK_KEY = (function () {
    var el = deckRegionElement('deck-key');
    if (!el) return null;
    var port = parseInt(el.getAttribute('data-port') || '', 10);
    var k = el.getAttribute('data-k') || '';
    if (!(port >= 1 && port <= 65535) || !k) return null;
    return { port: port, k: k };
  })();
  // Deck が配ったページか（Deck v2.9・2026-11-04）。Claude デスクトップアプリの内蔵ブラウザは file:// を開けないので、
  // Deck が受信ポートから板そのものを配る（http://127.0.0.1:<ポート>/?v=<表示の鍵>）。そのページは Deck と同じオリジンで、
  // 下の deckFetch の要求は同じオリジンの要求になる。file: のページと同じく「Deck が見ている板を開いたページ」として扱う
  // （今日でないボードの知らせ・ボードの点検の文面）。本当に Deck が見ている板かは、従来どおり Deck が申告とトークンで
  // 確かめる（配った板の申告は http://127.0.0.1:<ポート>/）。接続情報があるのにポートが違うページ（ほかのプログラムが
  // 127.0.0.1 で配った写し等）は含めない。発行済みボード判定（TB_LIVE）はここを見ない（判定は変えない）
  // ✎ の時刻の欄を結ぶ関数（自動機能の IIFE が入れる。D&D の IIFE が、実施日の来た行に足した時刻の欄に使う）
  var tbBindTimeEl = null;
  // 行の鍵（D&D で Deck へ送る k・localStorage の移動と × の記録・✎ の上書き・通知の鍵）の作り方は Deck の _key_text が正本で
  // （Deck v2.14・board_edit.py v1.10 が同じ関数を写して持つ。欄の範囲は Deck v2.15・board_edit.py v1.11）、ここはその規則を DOM に当てたもの
  // （2026-11-06 ユーザー決定「鍵の作り方を1か所にまとめる」）。Deck は HTML の文字を、要素の開きタグの後から、要素と同じ名前の最初の閉じタグの
  // 手前まで読む（stopAtClass が真なら、その前の class を持つ開きタグの手前まで。さらに時刻の欄は、ブラウザが欄とみなす範囲〔Deck の
  // _time_range＝閉じタグの無い欄はブラウザが閉じる所まで、p の欄は後ろの p を閉じる要素の手前まで〕の終わりでも読み終える）。DOM では、
  // 要素の中を HTML の並びどおりにたどって文字を集め、同じ名前の子孫の終わり（＝最初の閉じタグ）か、class を持つ子孫の始まりで読み終える
  // （DOM の要素はブラウザが閉じた所で終わるので、範囲の終わりはそろう。ただし Deck の `_implied_close`・`_P_CLOSERS` の注釈に挙げた形〔同じ名前の閉じタグが外側の閉じタグの後にある欄・標準モードの板の p の欄の table〕は除く）。ブラウザは閉じタグの無い要素の中に後ろの要素を取り込むが、
  // 取り込まれた要素の文字は読まないので、HTML の文字から作る Deck の鍵と合う。
  // file: で開いた板では元の HTML の文字を読めず、Deck が止まっていても鍵は要るので、ブラウザでも作る。一致は試験で見る
  // （tests/test_board_browser.py の TestBrokenTimeKeys）。
  function tbKeyWalk(el, stopAtClass) {
    var out = '', tag = el.tagName, done = false, stopped = false;
    (function walk(n) {
      for (var c = n.firstChild; c && !done; c = c.nextSibling) {
        if (c.nodeType === 3) { out += c.data; continue; }
        if (c.nodeType !== 1) continue;
        if (stopAtClass && c.hasAttribute('class')) { done = stopped = true; return; }
        walk(c);
        if (c.tagName === tag) done = true;
      }
    })(el);
    return { text: out, stopped: stopped };
  }
  function tbKeyText(el, stopAtClass) {
    return tbKeyWalk(el, stopAtClass).text;
  }
  // 時刻の欄の中身を書き換えてはいけない欄か。読み込んだときに、欄の中に class を持つ要素があった欄をそう判定する（閉じタグの無い欄
  // ＝ブラウザが後ろの要素を中に取り込んだ形を含む。「ボードの点検」の⑥は、そのうち data-tb-unclosed の欄を持つ項目を数える）——<span class="time">0:00 の閉じが無いと、後ろの
  // <div><p class="task-title">… が中に入る。<div class="time"><div>9:00</div></div> のような class の無い入れ子は壊れていない（Deck の
  // _TIME_OPEN_RE の前の注記が正しい形として挙げる形）。壊れた欄は ✎ の表示と結び付けが文字を書き換えない（書き換えると、取り込まれた
  // タイトルやチップまで消える）。「ボードの点検」にも出す
  function tbTimeElBroken(el) {
    return el.hasAttribute('data-tb-text');
  }
  // 時刻の欄の中に行の部品（タイトル・補足・チップの箱・チップ・項目）があるか。Deck・board_edit.py の _remove_time_elements が外さない欄と
  // 同じ（_ROW_PART_RE）で、D&D で行の形を作るか（shapeDueMove・setLaterDue）はこれで決める。画面の欄は DOM の欄（ブラウザが閉じタグの無い
  // 欄の中に後ろの要素を取り込んだもの）で、Deck は閉じタグの無い欄をブラウザが閉じる所までの欄とみなす（_implied_close・Deck v2.14）ので、
  // 閉じタグの有無によらず同じ欄を見る——欄の中に部品が入っていれば、画面も Deck も形を作らない（印だけ・400）。部品でない class の要素だけが
  // 入っている欄（閉じタグのある <span class="time">9:00<span class="x">a</span></span> も、閉じタグの無い <span class="time">0:00 <span class="x">a</span></div> も）は、
  // Deck が外して形を作るので、画面も同じ形にする（2026-11-06・11-07）。欄の時刻は、どこでも行の鍵と同じ読み方（tbTimeText＝Deck の _time_text・
  // Deck v2.15）で読む——shapeDueMove はその欄の「9:00」を行の時刻にし（Deck も同じ。Deck v2.14 までは欄の文字全体「9:00a」を読み、H:MM でないので
  // 実施日の時刻を使った）、setLaterDue の未定は欄に触れない（Deck の _later_due_shape と同じ）。画面と board.html が同じになることは tests/test_board_browser.py の
  // test_part_free_child_screen_matches_file で見る。class の値は小文字にそろえて比べる（Deck の _ROW_PART_RE の re.I と同じ）——board-template.html
  // から作った板は doctype が無く互換モードで開かれ、querySelector も大文字小文字を区別しないが、手で doctype を足した板〔標準モード〕では
  // 区別するので、querySelector には頼らない（互換モードの板は test_case_of_class_on_quirks_board、標準モードの板は同じ試験の後半で見る）
  var TB_PART_CLASSES = ['task-title', 'task-note', 'chips', 'chip', 'item'];
  function tbTimeHasPart(el) {
    var all = el.getElementsByTagName('*');
    for (var i = 0; i < all.length; i++) {
      var cls = (all[i].getAttribute('class') || '').toLowerCase().split(/\s+/);
      for (var j = 0; j < cls.length; j++) if (TB_PART_CLASSES.indexOf(cls[j]) >= 0) return true;
    }
    return false;
  }
  // 時刻の欄の文字（行の鍵と通知の鍵に使う。tbKeyText の stopAtClass）。壊れた欄は、board.js が何かを足す前に読み込んだときに控えて、
  // それを返す（欄の中にチップの箱が入っているので、後から足す「時刻超過」「▶ 次」などが混ざらないように。控えは5分ごとの読み直しで
  // HTML から取り直す）。壊れていない欄は、その時点の文字を読む（✎ で変えた時刻の表示を、通知が読むため）
  function tbTimeText(el) {
    var v = el.getAttribute('data-tb-text');
    return v !== null ? v : tbKeyText(el, true);
  }
  // タイトルの文字（行の鍵と通知の鍵に使う。Deck と同じく、同じ名前の最初の閉じタグで読み終える）
  function tbTitleText(el) {
    return el ? tbKeyText(el, false) : '';
  }
  // data-tb-unclosed＝欄と同じ名前の最初の閉じタグより前に class を持つ要素がある欄（tbKeyWalk が class で止まった欄。「ボードの点検」の⑥が
  // 数える）。board_edit.py の _time_open_unclosed・警告 K15 は HTML の文字で同じ形を見るが、ここは DOM しか見られないので、ブラウザが欄を
  // タイトルやチップの手前で閉じる形（<p class="time">9:00<div><p class="task-title">… など。閉じタグは無いが、DOM の欄の中に class を持つ
  // 要素が無い＝Deck v2.16 / board_edit.py v1.12 の _time_screen_closed）は、K15 に出ても⑥には出ない。class の無い同じ名前の子が先に閉じる欄
  // （<span class="time"><span>9</span>:00 <span class="x">…</span></span> など）は、✎ は守るが⑥には数えない（K15 にも出ないため）
  Array.prototype.forEach.call(document.querySelectorAll('.item .time'), function (el) {
    if (!el.querySelector('[class]')) return;
    var w = tbKeyWalk(el, true);
    el.setAttribute('data-tb-text', w.text);
    if (w.stopped) el.setAttribute('data-tb-unclosed', '');
  });
  var TB_SERVED = String(location.protocol) === 'http:' && location.hostname === '127.0.0.1'
    && !!location.port && (location.pathname === '/' || location.pathname === '/board.html')
    && (!DECK_KEY || String(DECK_KEY.port) === String(location.port));
  // ページの読み直し。Deck が配ったページでは、このページを配った本物の Deck が答えるのを確かめてから読み直す。
  //   ・Deck が止まっている間に読み直すと、ブラウザのエラーの画面になって board.js が動かなくなり、Deck が戻っても
  //     自分では戻れない
  //   ・読み直しの URL には表示の鍵（?v=）が入る。Deck が止まっている間に同じ PC の別のユーザーのプログラムが
  //     このポートを取っていると、読み直しで鍵をそのプログラムへ送ってしまう。そのプログラムも固定の文字列は返せるので、
  //     鍵を知る者にしか作れない証しで確かめる: /ping?n=<乱数> を送り、Deck が返す HMAC-SHA256(鍵, "today-board-ping:
  //     <ポート>:<乱数>") を、このページの ?v= と location.port で作った値と比べる（Deck v2.9 の ping_proof。ポートを入れるのは、
  //     別のポートで動く本物の Deck へ乱数を中継して証しを得る形を止めるため）
  // 確かめられなければ読み直さない（証しを作れない環境＝crypto.subtle の無いブラウザでも読み直さない側に倒す）。
  // 自動の読み直しは 15 秒ごとに確かめ直す（その間の監視ねこの行は、Deck が止まっていれば「停止」、受信ポートでほかのものが
  // 答えていれば「古い」か「不明」。同じポートで表示の鍵が替わったときも証しが合わないので「古い」のまま）。手の読み直し（⚙の横の ↻）は
  // 確かめ直さず、読み直さなかったことを右下に知らせる。
  // 確かめるかどうかは「file: でなく、URL に ?v= がある」で決める（TB_SERVED では決めない）。TB_SERVED は接続情報の
  // ポートが配り元と違うページを含めないが、そのページの URL にも鍵が入りうるので、鍵の入った URL はいつも確かめる。
  // file: のページと、?v= の無いページ（artifact など。送る鍵が無い）はそのまま読み直す
  function tbUrlHasViewKey() {
    try { return new URLSearchParams(location.search).has('v'); } catch (err) { return /[?&]v=/.test(String(location.search)); }
  }
  function tbHex(buf) {
    return Array.prototype.map.call(new Uint8Array(buf), function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
  }
  // このページを配った Deck かを確かめる。Promise（true／false）を返す。確かめる手段が無ければ null
  function tbVerifyDeck() {
    var key = null;
    try { key = new URLSearchParams(location.search).get('v'); } catch (err) { key = null; }
    var c = window.crypto;
    if (!key || !c || !c.subtle || !c.getRandomValues || !window.fetch || !window.TextEncoder || !window.Promise) return null;
    var nb = new Uint8Array(16);
    c.getRandomValues(nb);
    var n = tbHex(nb.buffer);
    var enc = new TextEncoder();
    var ctl = window.AbortController ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 3000) : null;
    var opt = { cache: 'no-store' };
    if (ctl) opt.signal = ctl.signal;
    var want, got;
    try {
      want = c.subtle.importKey('raw', enc.encode(key), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
        .then(function (k) { return c.subtle.sign('HMAC', k, enc.encode('today-board-ping:' + location.port + ':' + n)); })
        .then(tbHex);
      got = fetch('/ping?n=' + n, opt).then(function (res) { return res && res.ok ? res.text() : ''; });
    } catch (err) { if (timer) clearTimeout(timer); return null; }
    var main = Promise.all([want, got]).then(function (r) {
      if (timer) clearTimeout(timer);
      return r[1] === 'deck-board-mover ' + r[0];
    }, function () { if (timer) clearTimeout(timer); return false; });
    // AbortController の無いブラウザでは fetch が戻らないことがある。決着しないまま待ち続けないよう、
    // TB_VERIFY_LIMIT_MS で確かめられなかった（false）ことにする
    var limit = new Promise(function (res) { setTimeout(function () { res(false); }, TB_VERIFY_LIMIT_MS); });
    return Promise.race([main, limit]);
  }
  function tbReloadRefused() {
    var area = document.getElementById('toast-area');
    if (!area) return;
    var el = document.createElement('div');
    el.className = 'toast';
    el.textContent = 'このボードを配った Deck の応答を確かめられないため、読み直しませんでした。'
      + 'Deck が動いているかを監視ねこの欄で確かめてください（Deck を起動し直してポートが替わったときは、新しい URL を開き直します）';
    el.addEventListener('click', function () { if (el.parentNode) el.remove(); });
    area.appendChild(el);
    setTimeout(function () { if (el.parentNode) el.remove(); }, 15000);
  }
  // 読み直す前に Deck を確かめるページか（file: でなく、URL に ?v= がある）。監視ねこの「古い」の文面の出し分けにも使う
  function tbReloadIsChecked() {
    return String(location.protocol) !== 'file:' && tbUrlHasViewKey();
  }
  // 自動の読み直しの確かめは同時に1本だけにする（5分ごと・接続情報が古いとき・日付の切り替えなどが重なっても、
  // 15 秒ごとの確かめ直しを何本も並べない）
  var tbReloadWaiting = false;
  var TB_RELOAD_RETRY_MS = 15000;   // 自動の読み直しの確かめ直しの間隔
  var TB_VERIFY_LIMIT_MS = 5000;    // 1回の確かめを待つ上限
  // 利用者が入力している間は、自動の読み直しを延ばす（2026-11-06）——「明日以降」へ戻す行の実施日の入力欄（dialog.later-due）と
  // ✎ の時刻の入力欄が開いている間と、Deck への要求（deckFetch）が答えを待っている間。読み直すと、入れた値が黙って消え、
  // 閉じた直後なら送った移動・時刻の保存を途中で切る。自動の読み直し（5分ごと・日付が変わった直後・Deck の再起動に合わせた
  // 読み直し・発行直後と「今日でないボード」の知らせの読み直し）はどれもここを通るので、どれも同じく延びる。延ばしている間は
  // TB_HOLD_RECHECK_MS ごとに見直し、閉じたら読み直す（Deck を確かめるページは、確かめるところからやり直す）。
  // 手で押した読み直しは入力欄を待たない（押した時点で ✎ の入力欄は閉じて確定する）が、答えを待っている要求は
  // TB_HOLD_MANUAL_MS まで待つ（deckFetch は 1.5 秒で打ち切るので、ふつうはその前に終わる）
  // 読む→送るの途中（✎ の時刻・通知音の設定）も延ばす。読んだ答えから送るまでの間は数えが 0 になりうるため、
  // 自動機能の側が途中かどうかを tbReloadHolds に返す（真なら延ばす）
  var tbDeckInFlight = 0;           // Deck への要求のうち、答えをまだ受けていない数（deckFetch が数える）
  var tbReloadHolds = [];
  var TB_HOLD_RECHECK_MS = 1000;
  var TB_HOLD_MANUAL_MS = 2000;
  function tbReloadHeld() {
    if (document.querySelector('dialog.later-due, .item .time input') || tbDeckInFlight > 0) return true;
    return tbReloadHolds.some(function (f) { return f(); });
  }
  // ---- 開いたまま日付が変わったページからは書かない（2026-11-06） ----
  // 発行済みボード判定（TB_LIVE）は読み込んだときに決まるので、開いたまま 0:00 をまたぐと昨日の板の判定のまま残る。日付が
  // 変わった直後の読み直しは入力欄を閉じるまで延びる（上）ので、その間に決めた操作が昨日の板に書かれうる。そこで Deck へ書く操作
  // （D&D の移動・「明日以降」へ戻す実施日・✎ の時刻・通知音の設定・通知の確認）は、押した時点の暦日が読み込んだ日と違えば
  // 送らず（localStorage にも積まず）、読み直す。利用者の操作なら、その場で TB_DAY_STOP_MSG を出し（Deck を確かめられずに読み直しが
  // 待つ間も、保存していないことが分かるように）、読み直した後に TB_DAY_MSG を1回だけ出す（読み直した後の板が今日のものでなければ、
  // 代わりに TB_DAY_UNSAVED を「書き込み停止中」の知らせに足す。sessionStorage の印は、実際に読み直す
  // 直前にだけ置く＝読み直さなかったときに印が残って、後の別の読み直しで出ることを防ぐ）。D&D は動かす前に止める（行は元の位置のまま）
  function tbDayOf(d) { return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate(); }
  var TB_LOAD_DAY = tbDayOf(new Date());
  var TB_DAY_STOP_MSG = '日付が変わったので、この操作は保存していません。ボードを読み直します';
  var TB_DAY_MSG = '日付が変わったので、ボードを読み直しました。もう一度操作してください';
  // 読み直した後の板が今日のものでない（Deck が止まっていて今日の板がまだ無いなど）ときは、もう一度操作しても保存されないので
  // TB_DAY_MSG は出さない。代わりに「今日でないボードの知らせ」（書き込み停止中）の本文の頭にこの文を足す（知らせの直し方の欄が
  // ふつうは「今日のボードを作って」と頼むよう案内する〔写しの板では Deck が見ている board.html を開くよう案内する〕ので、ここでは繰り返さない。トーストと知らせの二重には出さない）
  var TB_DAY_UNSAVED = '日付が変わったので、前の画面での操作は保存していません。';
  var tbDayNoticeWanted = false;   // 読み直した後に TB_DAY_MSG を出すか（tbReload が読み直す直前に印を置く）
  var tbDayUnsaved = false;        // 読み直した後の板が今日のものでなく、知らせに TB_DAY_UNSAVED を足すか
  var tbDayEl = null;
  function tbDayToast(msg) {   // 続けて出しても1件にまとめる
    var area = document.getElementById('toast-area');
    if (!area) return;
    var el = tbDayEl;
    if (!el || !el.parentNode) {
      el = document.createElement('div');
      el.className = 'toast tb-day-changed';
      el.addEventListener('click', function () { if (el.parentNode) el.remove(); });
      tbDayEl = el;
    }
    el.textContent = msg;
    area.appendChild(el);
    var auto = false;
    try { auto = window.localStorage.getItem('tb:toastMode') === 'auto'; } catch (err) { auto = false; }
    if (auto) setTimeout(function () { if (el.parentNode && el.textContent === msg) el.remove(); }, 30000);
  }
  function tbDayChanged() { return tbDayOf(new Date()) !== TB_LOAD_DAY; }
  // 日付が変わったとして一度でも止めたか。✎ と通知音の操作は、読む→送るの途中で日付が変わると deckPost がここで止めて
  // undefined を返す。それを「Deck に届かなかった」と取り違えて2件目の知らせを出さないよう、呼び出し側がこれを見る（2026-11-06）
  var tbDayStopped = false;
  // 日付が変わっていれば読み直して true（呼び出し側は送らない）。tell が真なら、その場で知らせ、読み直した後にも知らせる
  function tbDayStop(tell) {
    if (!tbDayChanged()) return false;
    tbDayStopped = true;
    if (tell) {
      tbDayToast(TB_DAY_STOP_MSG);
      tbDayNoticeWanted = true;
    }
    tbReload();
    return true;
  }
  (function () {
    var v = null;
    try {
      v = window.sessionStorage.getItem('tbDayNotice');
      if (v) window.sessionStorage.removeItem('tbDayNotice');
    } catch (err) { v = null; }
    if (!v) return;
    if (TB_LIVE.live) tbDayToast(TB_DAY_MSG);
    else tbDayUnsaved = true;
  })();
  function tbReload(manual) {
    if (!manual) {
      if (tbReloadWaiting) return;
      tbReloadWaiting = true;
    }
    var retry = function (ms) { setTimeout(function () { tbReloadWaiting = false; tbReload(); }, ms); };
    if (!manual && tbReloadHeld()) { retry(TB_HOLD_RECHECK_MS); return; }
    var t0 = Date.now();
    var reloadNow = function () {
      if (!manual && tbReloadHeld()) { retry(TB_HOLD_RECHECK_MS); return; }   // 確かめている間に入力が始まった
      if (manual && tbDeckInFlight > 0 && Date.now() - t0 < TB_HOLD_MANUAL_MS) { setTimeout(reloadNow, 100); return; }
      if (tbDayNoticeWanted) {
        try { window.sessionStorage.setItem('tbDayNotice', '1'); } catch (err) { /* 読み直した後には出ない（その場では出した） */ }
      }
      location.reload();
    };
    if (!tbReloadIsChecked()) { reloadNow(); return; }
    var again = function () {
      if (manual) { tbReloadRefused(); return; }
      retry(TB_RELOAD_RETRY_MS);
    };
    var p = tbVerifyDeck();
    if (!p) { again(); return; }
    p.then(function (ok) { if (ok) reloadNow(); else again(); }, again);
  }
  // 読み直し（location.reload）の回数制限。発行済みの今日のボードだけが対象。
  // beforeReload は、実際に読み直す直前にだけ呼ぶ（読み直さなかったときは呼ばない）。
  function deckReloadOnce(kind, minGapMs, beforeReload) {
    if (!TB_LIVE.live) return;
    var name = 'tbDeckReload:' + kind;
    var last = 0;
    try { last = +(window.sessionStorage.getItem(name) || 0); } catch (err) { return; }
    if (Date.now() - last < minGapMs) return;
    try { window.sessionStorage.setItem(name, String(Date.now())); } catch (err) { return; }
    if (beforeReload) beforeReload();
    tbReload();
  }
  // トークンが古いときの読み直し。同じトークンのまま2回読み直しても変わらなければ、もう読み直さない。
  var DECK_STALE_STUCK = false;
  function deckReloadStale() {
    var name = 'tbDeckReload:staleKey', nameN = 'tbDeckReload:staleCount';
    var prev = null, cnt = 0;
    try {
      prev = window.sessionStorage.getItem(name);
      cnt = +(window.sessionStorage.getItem(nameN) || 0);
    } catch (err) { return; }
    var same = !!DECK_KEY && prev === DECK_KEY.k;
    if (same && cnt >= 2) { DECK_STALE_STUCK = true; return; }
    deckReloadOnce('stale', 60000, function () {
      try {
        window.sessionStorage.setItem(name, DECK_KEY ? DECK_KEY.k : '');
        window.sessionStorage.setItem(nameN, String(same ? cnt + 1 : 1));
      } catch (err) { /* 無視 */ }
    });
  }
  if (DECK_KEY) {
    try { window.sessionStorage.removeItem('tbDeckReload:nokey'); } catch (err) { /* 無視 */ }
  } else {
    // 発行直後は Deck が数秒で接続情報を書き込む。8秒後に1回だけ読み直す（その日のうちは
    // 1回まで。Deck を入れていない環境では、以後は通常の5分ごとの再読み込みに任せる）
    setTimeout(function () { deckReloadOnce('nokey', 24 * 3600 * 1000); }, 8000);
  }
  // Deck への要求。タイムアウト 1.5 秒。失敗（未起動・未対応・タイムアウト・403）は
  // 呼び出し側で握る。応答を読みたい場合があるので Promise（無理なら null）を返す。
  function deckFetch(path, opt) {
    if (!window.fetch || !DECK_KEY) return null;
    var ctl = window.AbortController ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 1500) : null;
    var o = { method: (opt && opt.method) || 'GET' };
    if (opt && opt.body !== undefined) o.body = opt.body;
    if (ctl) o.signal = ctl.signal;
    var url = 'http://127.0.0.1:' + DECK_KEY.port + path
      + '?board=' + encodeURIComponent(DECK_BOARD) + '&k=' + encodeURIComponent(DECK_KEY.k);
    var p;
    try { p = fetch(url, o); } catch (err) { p = null; }
    if (!p || !p.then) { if (timer) clearTimeout(timer); return null; }
    // 答えを受けるまで自動の読み直しを延ばす（tbReload）。AbortController の無いブラウザでは fetch が戻らないことがあるので、
    // 1.5 秒で数えから外す（外すのは1回だけ）
    tbDeckInFlight++;
    var counted = true;
    var uncount = function () { if (counted) { counted = false; tbDeckInFlight--; } };
    var uncountTimer = setTimeout(uncount, 1500);
    return p.then(function (res) {
      uncount(); clearTimeout(uncountTimer);
      if (timer) clearTimeout(timer);
      if (res && res.status === 403 && res.clone) {
        // トークンが古い＝Deck が再起動した。新しいトークンは Deck が数秒以内に board.html へ
        // 書くので、6秒待ってから読み直す（直後だと、まだ古い board.html を読むことがある）
        res.clone().json().then(function (d) {
          if (d && d.error === 'token mismatch') {
            setTimeout(deckReloadStale, 6000);
          }
        }, function () {});
      }
      return res;
    }, function (err) {
      uncount(); clearTimeout(uncountTimer);
      if (timer) clearTimeout(timer);
      throw err;
    });
  }

  // ---- 完了表示の自動整合（状態チップを唯一の真実にする・2026-08-03 新設） ----
  // 手書きセクションでは「done-item クラス（淡色化）・打消し線・済チップ」の3点を手で揃える構造のため、
  // 状態変更時に一部だけ書き換わって食い違うことがある（2026-08-03 に3件発生。特に済→保留の差し戻しで
  // 淡色化が残り、承認待ちが完了済みに見える）。表示前にチップ基準へ揃えて、HTML側の付け忘れを吸収する。
  // 自動収集カード（data-sid）は Deck がチップのみを出力する設計のため対象外（見た目を変えない）。
  // 他の自動機能（▶次・時刻超過・通知）は done-item と済チップの両方を見るので、この整合の後に走らせる。
  (function () {
    Array.prototype.forEach.call(document.querySelectorAll('.item'), function (item) {
      if (item.hasAttribute('data-sid')) return;
      var done = !!item.querySelector('.chip.done');
      item.classList.toggle('done-item', done);
      Array.prototype.forEach.call(item.querySelectorAll('.task-title'), function (t) {
        t.classList.toggle('strike', done);
      });
    });
  })();

  // 自動機能（▶次・時刻超過・相対時刻・通知・設定・時刻手動変更）。生成/更新時に手動で触らない
  (function () {
    var LS = {
      get: function (k, d) { try { var v = localStorage.getItem('tb:' + k); return v === null ? d : v; } catch (e) { return d; } },
      set: function (k, v) { try { localStorage.setItem('tb:' + k, v); } catch (e) {} },
      del: function (k) { try { localStorage.removeItem('tb:' + k); } catch (e) {} }
    };
    var dateKey = ((document.querySelector('.date') || {}).textContent || '').trim();

    function parseHM(text) {
      var m = /(\d{1,2}):(\d{2})/.exec(text || '');
      // 範囲外（25:00 など）は読めない時刻にする（Deck の read_board_alarms・board_edit.py の K12 と同じ。2026-11-05）
      return m && +m[1] <= 23 && +m[2] <= 59 ? (+m[1]) * 60 + (+m[2]) : null;
    }
    function fmtHM(mins) { return Math.floor(mins / 60) + ':' + ('0' + (mins % 60)).slice(-2); }
    function taskKey(item) {
      var t = item.querySelector('.time');
      var ti = item.querySelector('.task-title');
      return ((t ? (t.getAttribute('data-orig') || tbTimeText(t).trim()) : '') + '|' + tbTitleText(ti)).trim();
    }
    function readJSON(k, d) { try { return JSON.parse(LS.get(k, JSON.stringify(d))); } catch (e) { return d; } }

    // ---- テーマ切替（⑥） ----
    function applyTheme() {
      var t = LS.get('theme', 'auto');
      if (t === 'auto') document.documentElement.removeAttribute('data-theme');
      else document.documentElement.setAttribute('data-theme', t);
      var btn = document.getElementById('theme-btn');
      if (btn) btn.textContent = t === 'light' ? '☀' : t === 'dark' ? '☾' : '◐';
      Array.prototype.forEach.call(document.querySelectorAll('[data-theme-set]'), function (b) {
        b.classList.toggle('active', b.getAttribute('data-theme-set') === t);
      });
    }

    // ---- 強調色（⑦） ----
    function applyCritColor() {
      var c = LS.get('crit', '');
      var root = document.documentElement;
      if (c) {
        root.style.setProperty('--crit', c);
        root.style.setProperty('--crit-bg', 'color-mix(in srgb, ' + c + ' 14%, var(--surface))');
      } else {
        root.style.removeProperty('--crit');
        root.style.removeProperty('--crit-bg');
      }
      Array.prototype.forEach.call(document.querySelectorAll('.swatch'), function (b) {
        b.classList.toggle('active', b.getAttribute('data-crit') === c);
      });
    }

    // ---- 通知音（③）: 発音は Deck（127.0.0.1 の受信ポート）に委ねる ----
    // ページ内（WebAudio）では鳴らせないと判断した。
    // ブラウザの自動再生制限により、ページ上でユーザー操作が一度も無いと AudioContext が
    // running にならず無音のまま return する。さらに board.html は5分ごとに全リロードされる
    // ため、クリックで得た解除も最大5分で失効する。この道具の想定用途は「サブモニタに置いて
    // 触らない」ので、ページ内再生では構造的に鳴らない。
    // そこで設定UIはこの⚙パネルのまま維持し、値と試聴要求だけを Deck へ送る。
    // 時刻トリガーの判定と発音は Deck が board.html を直接読んで行う（board.js は鳴らさない）。
    // Deck 未起動・未対応・応答なしのときは⚙の通知音を操作できない形にする（音は鳴らないが UI は壊さない）。
    // 書き込み系はここを必ず通るので、発行済みボード判定をこの一点でガードする
    // （/sound/config・/board/times・/notifications/ack が対象）。止めたときは undefined、Deck へ
    // 送ったときは応答の Promise を返す（応答を見ない呼び出し側は使わない）。
    function deckPost(path, obj) {
      if (!TB_LIVE.live) { tbBlockWrite(path); return; }
      if (tbDayStop(path !== '/notifications/ack')) return;   // 開いたまま日付が変わった（通知の確認は知らせずに読み直す）
      var p = deckFetch(path, { method: 'POST', body: JSON.stringify(obj) });
      if (p) p.catch(function () {});
      return p;
    }
    // ---- 通知音の設定（ON/OFF・音種。持ち主は Deck だけ・2026-11-02 ユーザー決定） ----
    // ブラウザには持たない。読み込みでは GET で読んで表示するだけで、送るのは⚙を操作したときだけ。
    // ブラウザが持つと、開いただけで既定値や古い値が Deck を上書きする（2026-08-08 に検証用のブラウザが
    // 本番の通知音を ON→OFF に書き換えた。Deck からは本物のタブと区別できない）。
    // soundCfg＝最後に Deck から読んだ値（null＝読めていない）。古い値を本物に見せないよう、読めない間は
    // 値を出さず、操作もできない形にする。Deck の応答が戻れば pollNotifications から読み直す。
    var soundCfg = null;
    var soundLoaded = false;   // 一度でも結果が出たか（最初の応答を待つ間は知らせを出さない）
    var soundBusy = false;     // 操作の途中（読む→送る）
    var soundReading = false;
    var soundError = '';
    var SOUND_MSG_NO_DECK = '通知音の設定は Deck が持っています。Deck から設定を読めないため、いまは確認も変更もできません。Deck が止まっている、この環境に Deck が無い、このボードは Deck が見ているものではない、Deck を起動し直した直後で読み直しを待っている、などの場合です（状態は監視ねこの欄に出ます）。';
    var SOUND_MSG_NOT_TODAY = '今日のボードではないため、通知音の設定は変更できません。今日のボードを開いて変更してください。';
    var SOUND_MSG_NOT_TODAY_VALUE = SOUND_MSG_NOT_TODAY + '表示は Deck のいまの設定です。';
    var SOUND_MSG_FAILED = 'Deck に届かなかった可能性があります。通知音の操作は反映されていないことがあります。';
    function soundRead(done) {
      var p = deckFetch('/sound/config');
      if (!p) { done(null); return; }
      p.then(function (res) {
        return res && res.ok ? res.json() : null;
      }).then(function (d) {
        var ok = d && d.ok === true && typeof d.enabled === 'boolean' && typeof d.type === 'string';
        done(ok ? { enabled: d.enabled, type: d.type } : null);
      }, function () { done(null); });
    }
    function renderSound() {
      var can = !!soundCfg && TB_LIVE.live && !soundBusy;
      var t = document.getElementById('sound-toggle');
      if (t) {
        t.textContent = soundCfg ? (soundCfg.enabled ? 'ON' : 'OFF') : (soundLoaded ? '—' : '…');
        t.classList.toggle('on', !!soundCfg && soundCfg.enabled);
        t.disabled = !can;
      }
      Array.prototype.forEach.call(document.querySelectorAll('[data-sound]'), function (b) {
        b.classList.toggle('active', !!soundCfg && b.getAttribute('data-sound') === soundCfg.type);
        b.disabled = !can;
      });
      var st = document.getElementById('sound-test');
      if (st) st.disabled = !can;
      var note = document.getElementById('sound-note');
      if (note) {
        var msg = !TB_LIVE.live ? (soundCfg ? SOUND_MSG_NOT_TODAY_VALUE : SOUND_MSG_NOT_TODAY)
          : !soundLoaded ? ''
          : !soundCfg ? SOUND_MSG_NO_DECK
          : soundError;
        note.textContent = msg;
        note.hidden = !msg;
      }
    }
    // 読めたら失敗の知らせを消す。keepError は失敗の直後の読み直し用（値は映すが、知らせは残す）
    function soundRefresh(keepError) {
      if (soundBusy || soundReading) return;
      soundReading = true;
      soundRead(function (cur) {
        soundReading = false;
        if (soundBusy) return;
        soundCfg = cur;
        soundLoaded = true;
        if (cur && !keepError) soundError = '';
        renderSound();
      });
    }
    // ⚙の操作。別のブラウザが変えた値を古い表示で上書きしないよう、送る直前に読み、変えない項目は読んだ値で
    // 埋めて送る（Deck は欠けた値を OFF/std として保存する）。読めなければ送らない。
    // change は読んだ値を受けて送る値を返す。値が変わらず試聴でもなければ送らない。
    // 表示は応答を受けてから変える。応答が得られなければ Deck が受けたかは分からないので、読み直して映し、知らせを出す。
    function soundOperate(change, test) {
      if (soundBusy || !TB_LIVE.live || tbDayStop(true)) return;
      soundBusy = true;
      soundError = '';
      renderSound();
      soundRead(function (cur) {
        soundCfg = cur;
        soundLoaded = true;
        if (!cur) { soundBusy = false; renderSound(); return; }
        var next = change(cur);
        if (!test && next.enabled === cur.enabled && next.type === cur.type) {
          soundBusy = false;
          renderSound();
          return;
        }
        function failed() { soundBusy = false; soundError = SOUND_MSG_FAILED; renderSound(); soundRefresh(true); }
        var p = deckPost('/sound/config', { enabled: next.enabled, type: next.type, test: !!test });
        // 読む間に日付が変わって deckPost が止めたなら、その知らせ（TB_DAY_STOP_MSG）だけにする（送っていないので「届かなかった」は出さない）
        if (!p && tbDayStopped) { soundBusy = false; renderSound(); return; }
        if (!p) { failed(); return; }
        p.then(function (res) {
          return res && res.ok ? res.json() : null;
        }).then(function (d) {
          if (!d || d.ok !== true) { failed(); return; }
          // 応答の形が崩れていれば、送った値を表示する
          soundCfg = {
            enabled: typeof d.enabled === 'boolean' ? d.enabled : next.enabled,
            type: typeof d.type === 'string' ? d.type : next.type
          };
          soundBusy = false;
          renderSound();
        }, failed);
      });
    }
    // ---- ✎ の時刻の上書き（持ち主は Deck だけ・2026-11-02 ユーザー決定。通知音の設定と同じ形） ----
    // ブラウザには持たない。読み込みでは GET /board/times で読んで表示と判定に使うだけで、送るのは ✎ を操作したときだけ。
    // ブラウザが持つと、開いただけで古い記録が Deck を上書きし、別のボードで付けた値まで届く（file: の localStorage は共有される）。
    // キー＝taskKey（data-orig の元時刻 + '|' + タイトル）／値＝上書き後の表示時刻。Deck はこの元キーで HTML の item と突き合わせる。
    // timesMap＝いま読めている地図（null＝読めていない。✎ は操作できない）。timesLast＝このページで最後に読めた地図。
    // 読めない間も、表示と判定は timesLast で続ける（1回の通信の失敗で、元の時刻のポップアップを出さない）。メモリにだけ置くので、
    // ページを読み直した後に読めなければ元の時刻になる（ブラウザには残さない＝Deck の値が正）。
    // 今日でない板では読まない（Deck の地図は今日のボードのもの）。Deck が読めなくてもポップアップは動く（checkAlarms。時刻は timesLast、それも無ければ元の時刻）。
    var timesMap = null;
    var timesLast = null;
    var timesGen = 0;          // 操作のたびに増やす（操作の前に始めた読み直しの結果を、操作の後に適用しない）
    var timesLoaded = false;   // 一度でも結果が出たか。出るまでは時刻の判定をしない（元の時刻で誤って通知を出さないため）
    var timesBusy = false;     // 操作の途中（読む→送る）
    tbReloadHolds.push(function () { return timesBusy || soundBusy; });   // 読む→送るの途中は読み直さない
    var timesReading = false;
    var TIME_MSG_LOCKED = '時刻の変更は Deck に保存します。Deck から読めないため、いまは変更できません。Deck が止まっている、この環境に Deck が無い、このボードは Deck が見ているものではない、Deck を起動し直した直後で読み直しを待っている、などの場合です（状態は監視ねこの欄に出ます）。表示は、このページで最後に読めた時刻か、読めていなければ元の時刻です。';
    var TIME_MSG_NOT_TODAY = '今日のボードではないため、時刻は変更できません。元の時刻を表示しています。';
    var TIME_MSG_READ_FAILED = 'Deck から読めなかったので、時刻の変更は送っていません。';
    var TIME_MSG_FAILED = 'Deck に届かなかった可能性があります。時刻の変更は反映されていないことがあります。';
    // 「明日以降」の行は ✎ で変えさせない（2026-11-05）。✎ の変更は Deck がその日のうちだけ持ち（sound.json の ovr_date）、
    // 「明日以降」の行は今日の通知の対象にならない（checkAlarms・Deck の read_board_alarms）。実施日が来て今日の側へ移る日には
    // 変更はもう無く、移す形（Deck の _due_moved_shape）は HTML の時刻（時刻の欄が H:MM ならそれ、無ければ実施日の時刻）を使うので、変えても効かないまま ✎ だけが残っていた
    var TIME_MSG_LATER = '「明日以降」の行の時刻は、ここでは変更できません（ここでの変更はその日のうちだけ有効で、「明日以降」の行は今日の通知の対象になりません）。時刻を変えるときは Claude に頼んでください。';
    function timesRead(done) {
      var p = deckFetch('/board/times');
      if (!p) { done(null); return; }
      p.then(function (res) {
        return res && res.ok ? res.json() : null;
      }).then(function (d) {
        var ok = d && d.ok === true && d.ovr && typeof d.ovr === 'object' && !Array.isArray(d.ovr);
        done(ok ? d.ovr : null);
      }, function () { done(null); });
    }
    function timesCan() { return TB_LIVE.live && !!timesMap && !timesBusy; }
    // 読み直しの結果を反映する。表示に使う地図が変わったとき（と最初の結果）だけ判定し直す。読めなくなっただけなら操作の可否だけが変わる
    function timesApply(cur) {
      var changed = !timesLoaded || (!!cur && JSON.stringify(cur) !== JSON.stringify(timesLast));
      timesMap = cur;
      if (cur) timesLast = cur;
      timesLoaded = true;
      renderTimes();
      if (changed) refresh();
    }
    function timesRefresh() {
      if (timesBusy || timesReading) return;
      if (!TB_LIVE.live) { timesApply(null); return; }
      timesReading = true;
      var gen = timesGen;
      timesRead(function (cur) {
        timesReading = false;
        if (!timesBusy && gen === timesGen) timesApply(cur);
      });
    }
    var timeMsgEl = null, timeMsgTimer = null;
    function timeToast(msg) {   // 続けて出しても1件にまとめる（D&D の moveSaveFailed と同じ形）
      var area = document.getElementById('toast-area');
      if (!area) return;
      var el = timeMsgEl;
      if (!el || !el.parentNode) {
        el = document.createElement('div');
        el.className = 'toast';
        el.addEventListener('click', function () { if (el.parentNode) el.remove(); });
        timeMsgEl = el;
      }
      el.textContent = msg;
      area.appendChild(el);
      if (timeMsgTimer) { clearTimeout(timeMsgTimer); timeMsgTimer = null; }
      if (LS.get('toastMode', 'stay') === 'auto') {
        timeMsgTimer = setTimeout(function () { if (el.parentNode) el.remove(); }, 30000);
      }
    }
    // ✎ の操作。地図は丸ごと置き換えなので、別のブラウザの上書きを消さないよう、送る直前に読み直して自分の変更だけを足す。
    // 読めなければ送らない。何も変わらなければ送らない。表示は応答を受けてから変える。
    function timesOperate(key, disp, orig) {
      if (timesBusy || !TB_LIVE.live) return;
      timesBusy = true;
      timesGen++;
      renderTimes();
      function finish() { timesBusy = false; renderTimes(); refresh(); }
      function failed() { timeToast(TIME_MSG_FAILED); timesBusy = false; timesRefresh(); renderTimes(); }
      timesRead(function (cur) {
        timesMap = cur;
        if (cur) timesLast = cur;
        timesLoaded = true;
        if (!cur) { timeToast(TIME_MSG_READ_FAILED); finish(); return; }
        var next = {};
        Object.keys(cur).forEach(function (k) { next[k] = cur[k]; });
        if (disp === orig) delete next[key];
        else next[key] = disp;
        if (next[key] === cur[key]) { finish(); return; }
        var p = deckPost('/board/times', { ovr: next });
        // 読む間に日付が変わって deckPost が止めたなら、その知らせ（TB_DAY_STOP_MSG）だけにする（送っていないので「届かなかった」は出さない）
        if (!p && tbDayStopped) { finish(); return; }
        if (!p) { failed(); return; }
        p.then(function (res) {
          return res && res.ok ? res.json() : null;
        }).then(function (d) {
          if (!d || d.ok !== true) { failed(); return; }
          timesMap = next;
          timesLast = next;
          finish();
        }, failed);
      });
    }

    // ---- ポップアップ（③）: 発火判定は Deck、描画はここ ----
    // 既定は「触るまで残す」。サブモニタに置いて放置する運用では、自動で消えると
    // 見逃したまま気づけないため（2026-08-04 ユーザー決定。従来は一律30秒で自動消滅）。
    // ただしこのページは5分ごとに自動リロードされ、DOM ごとトーストが消える。そこで
    // 「まだユーザーが見ていない通知（未確認）」は Deck 側に持たせ、ここは3秒ごとに
    // 取りに行って描画するだけにした。リロードしても未確認分は復元される。
    // ユーザーがトーストを閉じたら ack して Deck の未確認から外す。
    var shownKeys = {};  // このページで描画済みのキー（Deck 経路とローカル経路の二重表示を防ぐ）

    // 日付が変わった後に閉じた通知は、ここでは送らず（deckPost が止めて読み直す）、閉じた鍵を sessionStorage に持ち越す。
    // 読み直した後のページは、読み込んだ後の最初の /notifications の答えにだけ当て、その答えに含まれていた鍵の通知を出さずに
    // 確認として送る。答えを処理したら空にする（通知の鍵〔時刻|タイトル〕には日付が入らないので、後から来た同じ鍵の別の通知
    // 〔毎日のルーチンなど〕は出す）。鍵は板（DECK_BOARD＝このページの板の URL）と組で持ち、同じタブで別の板を開いたときには当てない
    // （Deck のポートは起動し直すと替わるが、板の URL は読み直しても同じなので、板の URL で見る）。
    // 鍵ごとに閉じた時刻（ミリ秒）も持ち越し、答えの項目の at（Deck がその通知を未確認に積んだ、その日の HH:MM:SS）が閉じた時刻より
    // 後なら当てない——閉じた後に鳴った同じ鍵の通知（ほぼ同時に鳴った今日の通知）を、一度も出さずに確認済みにしないため。at は
    // 秒までなので同じ秒は後とみなし、at が無い・読めないときも当てない（どちらも、もう一度出す側に倒す）。at の日付は答えを受けた
    // 日とする（Deck は今日の未確認だけを返す）。持ち越しの形は { board, closed: { 鍵: 閉じた時刻 } }（閉じた時刻の無い形は当てない）
    var ackLater = null;   // 最初の答えを待つ間だけ、持ち越した { 鍵: 閉じた時刻 }
    try {
      var carried = JSON.parse(window.sessionStorage.getItem('tbAckLater') || 'null');
      window.sessionStorage.removeItem('tbAckLater');
      if (carried && carried.board === DECK_BOARD && carried.closed && typeof carried.closed === 'object') {
        Object.keys(carried.closed).forEach(function (k) {
          var ms = +carried.closed[k];
          if (isFinite(ms) && ms > 0) {
            if (!ackLater) ackLater = Object.create(null);
            ackLater[k] = ms;
          }
        });
      }
    } catch (err) { ackLater = null; }
    // 持ち越した鍵を、答えの項目 it に当てるか（Deck がその通知を積んだのが、閉じたより前と言えるときだけ）
    function ackLaterApplies(later, it) {
      if (!later || !(it.key in later)) return false;
      var m = /^(\d{2}):(\d{2}):(\d{2})$/.exec(typeof it.at === 'string' ? it.at : '');
      if (!m) return false;
      var d = new Date();
      var at = new Date(d.getFullYear(), d.getMonth(), d.getDate(), +m[1], +m[2], +m[3]).getTime();
      return at + 1000 <= later[it.key];
    }
    function ackNotifications(keys) {
      if (!keys || !keys.length) return;
      if (tbDayChanged()) {
        try {
          var c = JSON.parse(window.sessionStorage.getItem('tbAckLater') || 'null');
          var closed = c && c.board === DECK_BOARD && c.closed && typeof c.closed === 'object' ? c.closed : {};
          var now = Date.now();
          keys.forEach(function (k) { closed[k] = now; });
          window.sessionStorage.setItem('tbAckLater', JSON.stringify({ board: DECK_BOARD, closed: closed }));
        } catch (err) { /* 持ち越せなければ、読み直した後にもう一度出る */ }
      }
      deckPost('/notifications/ack', { keys: keys });
    }
    // 1件描画する。描画したら true。キー定義は Deck の read_board_alarms と同一。
    function showNotification(key, msg) {
      if (shownKeys[key]) return false;
      // ポップアップ OFF のときは描画も ack もしない（ON に戻したら出せるよう未確認のまま残す）
      if (LS.get('popup', '1') !== '1') return false;
      var area = document.getElementById('toast-area');
      if (!area) return false;
      shownKeys[key] = true;
      var el = document.createElement('div');
      el.className = 'toast'; el.textContent = msg;
      var done = false;
      function dismiss() {
        if (done) return;
        done = true;
        if (el.parentNode) el.remove();
        ackNotifications([key]);
      }
      el.addEventListener('click', dismiss);
      area.appendChild(el);
      // 「30秒で自動」を選んでいるなら、自動で消える時点で確認済みとして扱う
      // （自動消滅を選んだ以上、リロードで復活させないのが一貫した挙動）
      if (LS.get('toastMode', 'stay') === 'auto') setTimeout(dismiss, 30000);
      return true;
    }

    // ---- Deck の未確認通知を取りに行く（3秒周期）＋ Deck 本体の生死判定 ----
    // Deck は自分が止まったことを board.html に書けない（書き手が Deck 自身のため）。
    // この取得の成否がそのまま生死の観測になるので、結果を「監視ねこ」へ描画する。
    // 応答が無い・断られた理由は分けて描く（2026-10-26。それまでは全部「停止」だった）:
    //   up          … 200 と目印 "deck":"today-board"＝稼働
    //   down        … 通信の失敗・タイムアウト（Deck が止まっている等）＝停止
    //   nokey       … ボードの DECK:AUTO の目印の間に接続情報（#deck-key）が無い。Deck が止まっているか、
    //                 受信ポートを取れずに動いている（Deck は自動収集と通知音を続ける）か、目印が欠けている
    //   other-board … 403 "board mismatch"／"board unreadable"。トークンは通っている＝
    //                 Deck は動いているが、このページは Deck が見ている board.html ではない（写し）
    //   stale       … 403 "token mismatch"。Deck を再起動した直後なら読み直しで戻る
    //   foreign     … 上のどれでもない応答（目印の無い 200〔JSON として読めないものを含む〕・
    //                 ほかの 403・それ以外の状態コード）
    //   ※file: の板では、CORS ヘッダの無い応答は fetch 自体が失敗するので down（停止）に入る。Deck が配った板
    //     （Deck v2.9）は同じオリジンへの要求なので CORS は関わらず、上の分け方のとおりになる（受信ポートで Deck 以外の
    //     ものが答えれば foreign、別のユーザーの Deck の token mismatch なら stale）
    var deckAliveAt = null;    // 最後に応答があった時刻
    var deckDownSince = null;  // 稼働以外になった時刻（null＝稼働中）
    var deckState = null;      // 上のどれか（null＝未確定。確定前は何も描かない）

    function setDeckState(st) {
      if (st === 'up') { deckAliveAt = new Date(); deckDownSince = null; }
      else if (!deckDownSince) deckDownSince = new Date();
      deckState = st;
      // ⚙の通知音も Deck の応答に合わせる（読めない間は操作できない。戻ったら読み直す）
      if (st === 'up') { if (!soundCfg) soundRefresh(); }
      else if (!soundBusy && (soundCfg || !soundLoaded)) { soundCfg = null; soundLoaded = true; renderSound(); }
      // ✎ の時刻も同じ（読めない間は操作できない。表示は timesLast で続け、それも無ければ元の時刻。戻ったら読み直す）
      if (TB_LIVE.live) {
        if (st === 'up') { if (!timesMap) timesRefresh(); }
        else if (!timesBusy && !timesReading && (timesMap || !timesLoaded)) timesApply(null);
      }
      renderDeckStatus();
      renderBoardNotice();
    }
    function pollNotifications() {
      if (!DECK_KEY) { setDeckState('nokey'); return; }
      var p = deckFetch('/notifications');
      if (!p) { setDeckState('down'); return; }
      p.then(function (res) {
        if (!res) { setDeckState('down'); return null; }
        if (res.status === 403) {
          return res.json().then(function (d) {
            var e = d && d.error;
            setDeckState(e === 'board mismatch' || e === 'board unreadable' ? 'other-board'
              : e === 'token mismatch' ? 'stale' : 'foreign');
            return null;
          }, function () { setDeckState('foreign'); return null; });
        }
        if (!res.ok) { setDeckState('foreign'); return null; }
        // JSON として読めない 200 も「Deck のものと確かめられない」に数える（停止ではない）
        return res.json().then(null, function () { setDeckState('foreign'); return null; });
      }).then(function (data) {
        if (!data) return;
        // 目印を確かめる（ポートの持ち主が Deck 以外に替わった場合に備える）
        if (data.ok !== true || data.deck !== 'today-board') { setDeckState('foreign'); return; }
        setDeckState('up');
        var later = ackLater;
        ackLater = null;   // 持ち越した鍵は最初の答えにだけ当てる
        if (!data.items) return;
        var done = [];
        data.items.forEach(function (it) {
          if (ackLaterApplies(later, it)) { done.push(it.key); return; }   // 前のページで閉じた通知。出さずに確認として送る
          showNotification(it.key, '⏰ ' + it.time + ' ' + it.title);
        });
        if (done.length) ackNotifications(done);
      }).catch(function () { setDeckState('down'); });
    }

    function fmtClock(d) {
      return d.getHours() + ':' + ('0' + d.getMinutes()).slice(-2) + ':' + ('0' + d.getSeconds()).slice(-2);
    }
    // 「監視ねこ」セクションの末尾（ログ退避行の下）に Deck 本体の生死を1行足す。
    // board.html には書かない（この行は Deck が自動領域を再生成しても壊れない DOM 側の描画）。
    // js-auto を付けて refresh() の張り替え対象にし、既存の「▶ 次」チップと同じ扱いにする。
    function renderDeckStatus() {
      var old = document.getElementById('deck-status-row');
      if (old && old.parentNode) old.parentNode.removeChild(old);
      if (!deckState) return;
      var label = null;
      Array.prototype.forEach.call(document.querySelectorAll('.section-label'), function (el) {
        if (!label && el.textContent.indexOf('監視ねこ') === 0) label = el;
      });
      if (!label) return;
      var anchor = label, n = label.nextSibling;
      while (n) {
        if (n.nodeType === 1 && n.classList) {
          if (n.classList.contains('section-label')) break;
          if (n.classList.contains('item')) anchor = n;
        }
        n = n.nextSibling;
      }
      var since = deckDownSince ? '（' + fmtClock(deckDownSince) + ' から）' : '';
      var view = {
        up: ['active', '稼働', 'Deck本体 ・ 最終応答 ' + (deckAliveAt ? fmtClock(deckAliveAt) : '—')
          + ' ・ 通知音は Deck が担当（ポップアップはブラウザ側でも判定）'],
        down: ['crit', '停止', 'Deck本体 ・ 応答なし' + since + '・通知音が鳴らず、全セッションの自動収集も止まっています'],
        nokey: ['pending', '不明', 'Deck本体 ・ 接続情報がありません。Deck が止まっているか、受信ポートを取れずに動いているか'
          + '（その場合も自動収集と通知音は続きます。watcher.log で確かめられます）、ボードの DECK:AUTO の目印が欠けています'],
        'other-board': ['pending', '写し', 'Deck本体 ・ Deck が見ている board.html ではありません。Deck は動いていますが、'
          + 'このページには通知と設定が届きません'],
        // Deck が配った板（読み直す前に Deck を確かめるページ）では、読み直しはこのボードを配った Deck と確かめられたときだけ
        // 起きる。同じポートで Deck を起動し直したのなら確かめられて読み直すが、ポートを別のもの（別のユーザーの Deck など）が
        // 持っていれば確かめられず、読み直さない。file: の板の文面（写し・書き込めていない／数秒〜1分で戻る）は当たらない
        stale: tbReloadIsChecked()
          ? (DECK_STALE_STUCK
            ? ['pending', '古い', 'Deck本体 ・ 接続情報が古いままです' + since + '。読み直そうとしても新しくなりません。'
              + '表示の鍵が替わった〔state.json を消した・Deck の版が替わった〕か、このポートで別のものが答えているか、'
              + 'Deck が board.html に書き込めていません。Deck の再起動に合わせた読み直しは、これ以上新しくは始めません。'
              + '確かめられずに待っている読み直しがあれば、15 秒ごとに確かめ直し、このボードを配った Deck と確かめられたら読み直します'
              + '（5分ごとの読み直しも、確かめてから行います）。表示の鍵かポートが替わったときは、新しい URL を開き直してください']
            : !TB_LIVE.live
            ? ['pending', '古い', 'Deck本体 ・ 接続情報が古い' + since + '（今日のボードではないので、Deck の再起動に合わせた読み直しは'
              + 'しません。5分ごとの読み直しは、このボードを配った Deck と確かめてから行います。表示の鍵かポートが替わったときは、'
              + '新しい URL を開き直してください）']
            : ['hold', '古い', 'Deck本体 ・ 接続情報が古い' + since + '（同じポートで Deck を起動し直した直後なら、このボードを配った Deck と'
              + '確かめてから読み直して戻ります。戻らないときは、表示の鍵が替わった〔state.json を消した・Deck の版が替わった〕か、'
              + 'このポートで別のものが答えています。どちらのときも、またポートが替わったときも、新しい URL を開き直してください）'])
          : DECK_STALE_STUCK
          ? ['pending', '古い', 'Deck本体 ・ 接続情報が古いままです' + since + '。読み直しても新しくならないため、'
            + 'Deck が見ている board.html ではない（写し）か、Deck が書き込めていません。'
            + 'Deck の再起動に合わせた読み直しは止めました（5分ごとの再読み込みは続きます）']
          : !TB_LIVE.live
            ? ['pending', '古い', 'Deck本体 ・ 接続情報が古い' + since + '（今日のボードではないので、Deck の再起動に合わせた読み直しはしません。5分ごとの再読み込みは続きます）']
            : ['hold', '古い', 'Deck本体 ・ 接続情報が古い' + since + '（Deck を再起動した直後なら、読み直しで数秒〜1分ほどで戻ります）'],
        foreign: ['pending', '不明', 'Deck本体 ・ 受信ポートの応答が Deck のものと確かめられません' + since
          + '。通知と設定が届かない状態です（watcher.log で確かめられます）']
      }[deckState] || ['crit', '停止', 'Deck本体 ・ 応答なし' + since];
      var row = document.createElement('div');
      row.className = 'item flat js-auto';
      row.id = 'deck-status-row';
      var inner = document.createElement('div');
      var chips = document.createElement('div');
      chips.className = 'chips';
      chips.style.marginTop = '0';
      var chip = document.createElement('span');
      chip.className = 'chip ' + view[0];
      chip.textContent = view[1];
      chips.appendChild(chip);
      var note = document.createElement('p');
      note.className = 'task-note';
      note.textContent = view[2];
      inner.appendChild(chips);
      inner.appendChild(note);
      row.appendChild(inner);
      anchor.parentNode.insertBefore(row, anchor.nextSibling);
    }

    // ---- 今日でないボードの知らせ（2026-10-27 新設） ----
    // 発行済みボード判定（TB_LIVE）が偽の板では Deck への書き込み4経路が止まるが、従来は理由が
    // ブラウザのコンソールにしか出ず、画面からは気づけなかった（2026-10-25 発行の板へ、スキルを
    // 通さずに2日間書き足し続けた結果、4経路が止まったままになり、利用者が右上の日付で気づいた）。
    // そこで .updated の直後に #tb-board-notice（role="status"）を置いて知らせる。HTML 正本には書かない。
    // 【出すかどうか】は TB_LIVE.live だけで決める。下の tbBoardKind は文面を選ぶためだけの分類で、
    // TB_LIVE の判定を置き換えも補いもしない（TB_LIVE の判定そのものは変えない。日付の書式との
    // 関係は skill/SKILL.md create モード5。分類を TB_LIVE の外に置く形は 2026-10-27 ユーザー承認）。
    // 分類が誤っても変わるのは文面だけで、書き込みを止めるかどうかには影響しない。
    // 日付の読み方は TB_LIVE 層②と同じ規則（4桁の年あり→年月日／年なし→月日）にそろえてある。
    var NOTICE_WD = '日月火水木金土';
    var NOTICE_LOADED = Date.now();
    var NOTICE_GRACE_MS = 90000;   // Deck が動いている過去日の板で、知らせを待つ時間
    var NOTICE_RELOAD_MS = 60000;  // その間に1回だけ読み直す時点（Deck が今日の板を作っていれば消える）
    var NOTICE_BASE_TITLE = document.title;
    var noticeTimers = {};
    // Deck が見ている板を開いたページか（file: か、Deck が配ったページ〔TB_SERVED・Deck v2.9〕）。
    // それ以外＝artifact など（Deck に届かない）
    var NOTICE_IS_LOCAL = String(location.protocol) === 'file:' || TB_SERVED;

    function noticeMD(dt) {
      return (dt.getMonth() + 1) + '/' + dt.getDate() + '（' + NOTICE_WD.charAt(dt.getDay()) + '）';
    }
    function noticeISO(dt) {
      return dt.getFullYear() + '-' + ('0' + (dt.getMonth() + 1)).slice(-2) + '-' + ('0' + dt.getDate()).slice(-2);
    }
    function noticeToday() {
      var n = new Date();
      return new Date(n.getFullYear(), n.getMonth(), n.getDate());
    }
    // 文面の分類。戻り値の kind: template／unreadable／past／future／other（日付は今日として読めるが
    // TB_LIVE が偽＝分類が TB_LIVE と食い違った場合。文面は TB_LIVE.why をそのまま見せる）
    function tbBoardKind() {
      var probe = [
        document.title || '',
        (document.querySelector('header') || {}).textContent || '',
        (document.getElementById('upd-time') || {}).textContent || '',
        (document.querySelector('.progress') || {}).textContent || ''
      ].join('\n');
      var bf = document.querySelector('.progress .bar-fill');
      if (bf) probe += ' ' + (bf.getAttribute('style') || '');
      if (/\{\{\s*[A-Za-z0-9_]+\s*\}\}/.test(probe)) return { kind: 'template' };
      var txt = ((document.querySelector('header .date') || {}).textContent || '').trim();
      var today = noticeToday();
      var y = null, mo = null, d = null;
      var m4 = /(\d{4})[^\d](\d{1,2})[^\d](\d{1,2})/.exec(txt);
      if (m4) { y = +m4[1]; mo = +m4[2]; d = +m4[3]; }
      else {
        var m2 = /(\d{1,2})[^\d](\d{1,2})/.exec(txt);
        if (m2) { mo = +m2[1]; d = +m2[2]; }
      }
      if (mo === null) return { kind: 'unreadable', text: txt };
      var bd;
      if (y !== null) bd = new Date(y, mo - 1, d);
      else {
        // 年の無い表記は今年とみなす。半年以上先になるなら前年の板とみなす（12/31 の板を 1/1 に見た場合など）
        bd = new Date(today.getFullYear(), mo - 1, d);
        if (bd - today > 183 * 24 * 3600 * 1000) bd = new Date(today.getFullYear() - 1, mo - 1, d);
      }
      if (isNaN(bd.getTime()) || bd.getMonth() !== mo - 1 || bd.getDate() !== d) {
        return { kind: 'unreadable', text: txt };
      }
      if (bd < today) return { kind: 'past', date: bd };
      if (bd > today) return { kind: 'future', date: bd };
      return { kind: 'other' };
    }
    // Deck が動いている過去日の板では、Deck（日付の切り替えに対応した版）が今日の板を作り終えるまでの
    // 数秒〜数十秒に知らせが出て消えるのを避けるため、読み込みから 90 秒は出さず、60 秒の時点で
    // 1回だけ読み直す。読み直した後は待たずに出す（sessionStorage の鍵で「待ち終えた」を覚える）。
    // 5分ごとの再読み込みのたびに待ち直すと、5分のうち1分半は知らせが消えることになるため、
    // 待つのは今日とその板の組み合わせごとに1回だけ。
    // sessionStorage を読めないとき、または試しの書き込み（tbNotice:probe）が失敗したときは
    // 待たない（＝すぐ出す・見える側に倒す）。書けない環境で待つと、「待ち終えた」を覚えられずに
    // 60 秒ごとの読み直しが続き、知らせも出ないまま終わるため（Reviewer 実測 2026-10-27・
    // setItem だけが失敗する環境で読み込み6回まで続いた）。試しの書き込みが通っても、読み直す直前に
    // 本来の鍵を書けなかったときは、読み直さずにその場で出す（deckReloadOnce と同じ形）。
    function noticeGraceActive(bd) {
      var key = 'tbNotice:grace:' + noticeISO(noticeToday()) + '|' + noticeISO(bd);
      try {
        if (window.sessionStorage.getItem(key)) return false;
        window.sessionStorage.setItem('tbNotice:probe', '1');
        window.sessionStorage.removeItem('tbNotice:probe');
      } catch (err) { return false; }
      var left = NOTICE_LOADED + NOTICE_GRACE_MS - Date.now();
      if (left <= 0) return false;
      if (!noticeTimers.reload) {
        noticeTimers.reload = setTimeout(function () {
          try { window.sessionStorage.setItem(key, '1'); } catch (err) { renderBoardNotice(); return; }
          // 日付が変わって保存しなかった操作の知らせは、この読み直しの先へ持ち越す（待つ間は知らせを出さないので、
          // ここで落とすと一度も出ない。読み直した後の板が今日のものなら TB_DAY_MSG、そうでなければ知らせの頭に出る）
          if (tbDayUnsaved) tbDayNoticeWanted = true;
          tbReload();
        }, Math.max(0, NOTICE_LOADED + NOTICE_RELOAD_MS - Date.now()));
      }
      if (!noticeTimers.show) noticeTimers.show = setTimeout(renderBoardNotice, left + 50);
      return true;
    }
    function noticeEl() {
      var el = document.getElementById('tb-board-notice');
      if (el) return el;
      el = document.createElement('div');
      el.id = 'tb-board-notice';
      el.setAttribute('role', 'status');
      el.hidden = true;
      var upd = document.querySelector('.board .updated') || document.querySelector('.updated');
      var hdr = document.querySelector('header');
      if (upd && upd.parentNode) upd.parentNode.insertBefore(el, upd.nextSibling);
      else if (hdr && hdr.parentNode) hdr.parentNode.insertBefore(el, hdr.nextSibling);
      else document.body.insertBefore(el, document.body.firstChild);
      return el;
    }
    // 3秒ごとの Deck の確認のたびに呼ばれるので、中身が前回と同じなら何もしない。
    // 作り直すと role="status" の領域が毎回変化し、読み上げが繰り返されうるため
    // （Reviewer 実測 2026-10-27・作り直していた版で約100秒に101回の変化）。
    function setTitle(t) { if (document.title !== t) document.title = t; }
    function setNotice(cls, icon, label, body, fix) {
      var el = noticeEl();
      if (!label) {
        setTitle(NOTICE_BASE_TITLE);
        if (el.hidden && !el.firstChild) return;
        el.hidden = true;
        el.className = '';
        el.textContent = '';
        el.removeAttribute('data-sig');
        return;
      }
      if (tbDayUnsaved && label === '書き込み停止中') body = TB_DAY_UNSAVED + body;
      var sig = [cls, icon, label, body, fix || ''].join('|');
      setTitle(cls === 'info' ? NOTICE_BASE_TITLE : '⚠ ' + NOTICE_BASE_TITLE);
      if (!el.hidden && el.getAttribute('data-sig') === sig) return;
      el.setAttribute('data-sig', sig);
      el.className = cls;
      el.textContent = '';
      var ic = document.createElement('span');
      ic.className = 'tb-notice-icon';
      ic.setAttribute('aria-hidden', 'true');
      ic.textContent = icon;
      var box = document.createElement('div');
      var lb = document.createElement('strong');
      lb.className = 'tb-notice-label';
      lb.textContent = label;
      box.appendChild(lb);
      box.appendChild(document.createTextNode(' — ' + body));
      if (fix) {
        var fx = document.createElement('span');
        fx.className = 'tb-notice-fix';
        fx.textContent = fix;
        box.appendChild(fx);
      }
      el.appendChild(ic);
      el.appendChild(box);
      el.hidden = false;
    }
    var NOTICE_BLOCKED = '通知音の設定と ✎ の時刻は変更できません。通知の確認は Deck に届かず、'
      + 'ドラッグでの移動はこの画面の中だけの変更になります。';
    var NOTICE_ASK = 'Claude に「今日のボードを作って」と頼むと直ります。';
    function renderBoardNotice() {
      if (TB_LIVE.live) {
        // 今日の板。Deck が日付の切り替えで作った板（.board の data-tb-rolled）なら、引き継いだことを知らせる
        var board = document.querySelector('.board');
        var from = board ? (board.getAttribute('data-tb-rolled') || '') : '';
        var fm = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(from);
        if (!fm) { setNotice(null); return; }
        var fd = new Date(+fm[1], +fm[2] - 1, +fm[3]);
        // 件数は Deck v2.12 が切り替えたときに .board へ書いた数（data-tb-rolled-carried・data-tb-rolled-due）を出す。行の印から数えると、
        // 切り替えの後に add・create が印を足した行・D&D で動かした行まで数え、data-carried-from の残ったまま「明日以降」から移した行を落とすため。
        // 数の無い板（v2.11 までの Deck が切り替えた板）だけ、これまでどおり行の印から数える
        var cnt = function (name) { var v = board.getAttribute(name); return v !== null && /^\d+$/.test(v) ? +v : null; };
        var n = cnt('data-tb-rolled-carried');
        if (n === null) n = document.querySelectorAll('.item[data-carried-from]:not([data-sid])').length;
        var dm = cnt('data-tb-rolled-due');
        // 引き継いだ行（data-carried-from）は数えない: Deck v2.11 の _carry_due_today は、引き継ぐ行の実施日が前の日なら一度移した印も今日で付けるため
        if (dm === null) dm = document.querySelectorAll('.item[data-due-moved="' + noticeISO(noticeToday()) + '"]:not([data-sid]):not([data-carried-from])').length;
        setNotice('info', '↪', '引き継いだボード',
          noticeMD(fd) + 'のボードから、終わっていないタスク' + (n ? n + '件' : '')
          + 'を引き継いで、Deck が作ったボードです。今日の予定はまだ決めていません。'
          + (dm ? '実施日が来た予定 ' + dm + '件を「明日以降」から今日へ移しました。' : ''),
          '今日の予定は、Claude に「今日の予定を決めよう」と頼むと整えられます。');
        return;
      }
      var k = tbBoardKind();
      var today = noticeToday();
      var label = '書き込み停止中';
      if (k.kind === 'template') {
        setNotice('muted', '⚠', label, 'これは発行前のテンプレートです。ボードは Claude が作ります。'
          + (NOTICE_IS_LOCAL ? 'この画面での操作は Deck に届きません。' : ''),
          'Claude に「今日のボードを作って」と頼んでください。');
        return;
      }
      if (k.kind === 'unreadable') {
        setNotice('warn', '⚠', label, 'ヘッダの日付「' + k.text + '」を日付として読み取れません。日付は「'
          + noticeISO(today) + '（' + NOTICE_WD.charAt(today.getDay()) + '）」の形で書く決まりです。'
          + (NOTICE_IS_LOCAL ? '今日のボードと確かめられないため、' + NOTICE_BLOCKED : ''),
          'Claude に「今日のボードを作り直して」と頼んでください。');
        return;
      }
      if (k.kind === 'future') {
        setNotice('warn', '⚠', label, 'ボードの日付が' + noticeMD(k.date) + 'になっていて、今日の' + noticeMD(today)
          + 'より先です。' + (NOTICE_IS_LOCAL ? '今日のボードと確かめられないため、' + NOTICE_BLOCKED : ''),
          'PC の時計か、ボードの日付の書き方を確かめてください。');
        return;
      }
      if (k.kind === 'other') {
        setNotice('warn', '⚠', label, '今日のボードと確かめられません（' + TB_LIVE.why + '）。'
          + (NOTICE_IS_LOCAL ? NOTICE_BLOCKED : ''), NOTICE_ASK);
        return;
      }
      // past: 過去の日付
      var head = 'このボードは' + noticeMD(k.date) + 'のものです。今日は' + noticeMD(today) + 'です。';
      if (!NOTICE_IS_LOCAL) {
        setNotice('warn', '⚠', label, head, 'Claude に「今日のボードを作って」と頼んでください。');
        return;
      }
      if (deckState === null) { setNotice(null); return; }  // Deck の最初の応答（最長約1.5秒）を待つ
      if (deckState === 'other-board' || (deckState === 'stale' && DECK_STALE_STUCK)) {
        setNotice('warn', '⚠', label, 'これは' + noticeMD(k.date) + 'のボードの控え（写し）です。'
          + 'この画面での変更は Deck に届かず、この画面の中だけの変更になります。',
          '今日のボードは、Deck が見ている board.html の方です。そちらを開いてください。');
        return;
      }
      if (deckState === 'up') {
        if (noticeGraceActive(k.date)) { setNotice(null); return; }
        setNotice('warn', '⚠', label, head + '今日のボードではないため、' + NOTICE_BLOCKED
          + 'Deck は動いていますが、今日のボードはまだ作られていません。', NOTICE_ASK);
        return;
      }
      if (deckState === 'down' || deckState === 'nokey') {
        setNotice('warn', '⚠', label, head + '今日のボードではないため、' + NOTICE_BLOCKED
          + 'Deck が止まっているか、このボードに Deck の接続情報がありません。', NOTICE_ASK);
        return;
      }
      // stale（行き詰まる前）・foreign。監視ねこの「古い」はボードの日付ではなく Deck の接続情報の
      // ことなので、日付の古さと読み違えないよう、stale のときはその旨を添える
      setNotice('warn', '⚠', label, head + '今日のボードではないため、' + NOTICE_BLOCKED
        + 'Deck とも正しく通信できていません（監視ねこの欄を参照）。'
        + (deckState === 'stale' ? '監視ねこの「古い」は、ボードの日付ではなく Deck の接続情報が古いという意味です。' : ''),
        NOTICE_ASK);
    }

    // ---- ボードの点検（2026-10-27 新設・Deck v2.2 と同じ単位） ----
    // 書き手（Claude）がスキルの手順を通さずに書いた板では、項目の入れ子や DECK マーカーの欠落が
    // 起きうる。どちらも画面は普通に描かれるが、Deck の走査はそこで止まり、以降の項目は通知音・
    // D&D・進捗の対象から黙って外れる（Deck の _scan_board）。中身は直さず、見える形で知らせる。
    // 2026-10-28 に、正式名に似たセクション名・Deck v2.4 が崩れる前の版を
    // 退避したことも、同じ知らせ（見出し語「ボードの点検」）にまとめた。
    // 形は読み込みの間に変わらないので、読み込み時に1回だけ見る。
    // START の後ろに END があるときだけ「そろっている」とする（2026-10-29。deckRegionElement と同じ見方。
    // 順序が逆の板では接続情報を読まないので、知らせも出す）
    function hasDeckMarkers() {
      var s = false, e = false;
      try {
        var w = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT, null, false);
        var n;
        while ((n = w.nextNode())) {
          var t = (n.data || '').trim();
          if (t === 'DECK:AUTO:START') s = true;
          else if (t === 'DECK:AUTO:END' && s) e = true;
        }
      } catch (err) { return true; }  // 調べられないときは知らせない
      return s && e;
    }
    function renderBoardCheck() {
      // 読み込みの後にも作り直す（D&D で行を動かしたとき・localStorage に残った移動を当てた後）。中身が前と同じなら作り直さない
      // （role="status" の要素を作り直すと、読み上げが同じ知らせをくり返すため。#tb-board-notice と同じ方針）。違えば前の知らせを消して作る
      var prev = document.getElementById('tb-board-check');
      var msgs = [];
      // ⑦ 切れた画面（TB_CUT・2026-11-10 新設）。いちばん重いので先頭に出す
      if (TB_CUT) {
        msgs.push('ボードの HTML に閉じていない要素などがあり、ブラウザが行として読めていない所があります（画面に出ていないタスクや、Deck の欄があるかもしれません）。'
          + 'この間はドラッグでの移動を止めています。');
      }
      var nested = 0;
      Array.prototype.forEach.call(document.querySelectorAll('.item .item'), function (it) {
        if (!(it.closest && it.closest('[data-sid]'))) nested++;
      });
      if (nested) {
        msgs.push('タスクの中に別のタスクが入り込んでいます（入り込んでいるタスク ' + nested + ' 件）。'
          + 'そこから先のタスクは、通知音・ドラッグでの移動・進捗の数え方から外れることがあります。');
      }
      if (NOTICE_IS_LOCAL && !hasDeckMarkers()) {
        msgs.push('Deck の予約領域（DECK:AUTO の目印）がそろっていません（片方だけ・順序が逆を含む）。全セッションの欄と、'
          + 'Deck との接続情報が更新されません。Deck v2.5 以後が動いていれば、目印が2つとも無いときは Deck が足し直します'
          + '（Deck が書いた部分がひと続きに残っていればそれを囲み、1つも無ければボードの末尾に足します）。片方だけ・順序が逆のとき・'
          + 'Deck が書いた部分の間に別の行があるとき・末尾が1か所に決まらないときは足し直しません。');
      }
      // Deck v2.4 が形の崩れに気づいて、崩れる前の版を退避したとき（DECK 領域の #deck-lastgood）だけ添える。
      // Deck の判定（閉じタグの欠落を含む）は上の入れ子の判定より広いので、これだけで知らせを出すこともある。
      // 目印の間のものだけを読む（目印の外に残った古い目印で、済んだ退避を知らせ続けないため・2026-10-29）
      var lg = deckRegionElement('deck-lastgood');
      var lgFile = lg ? (lg.getAttribute('data-file') || '') : '';
      if (lgFile) {
        msgs.push('Deck がボードの形の崩れに気づき、崩れる前の版を board.html と同じフォルダの ' + lgFile
          + ' に残しました（Deck は板を直しません）。');
      }
      // ---- セクション名（2026-10-28 新設・直さずに知らせるだけ） ----
      // セクション名が正式名に似ているのに正式名でないもの。誤って出すと邪魔になるので、範囲は狭く取る——
      // 正式名の語と組み合わさった形で、見出しの全体がそれだけ（後ろに括弧書きが付くのは可）のものに限る:
      //   ①「本日」「きょう」「今日」＋（「の」）＋「予定」「中」「タスク」「やること」
      //   ②「明日」「あした」だけ、またはそれに「の予定」「以降」「から」が付いたもの
      //   ③「ルーチン」「ルーティン」だけ、またはそれに「タスク」「ワーク」が付いたもの
      // 「きょうのボード」「今日の記録ツール」「明日香アプリ」「ルーチン化ツール」のようなプロジェクト名は拾わない。
      // 正式名そのもの（今日の予定・今日中・ルーチンタスク・明日以降）は先頭一致で先に除く（Deck の _canon_section
      // と同じ）。監視ねこ・全セッション（DECK 領域）は見ない
      var TAIL = '(\\s*[（(].*)?$';
      var ODD_RES = [
        new RegExp('^(本日|きょう|今日)の?(予定|中|タスク|やること)' + TAIL),
        new RegExp('^(明日|あした)(の予定|以降|から)?' + TAIL),
        new RegExp('^ルー(チ|ティ)ン(タスク|ワーク)?' + TAIL)
      ];
      var odd = [];
      Array.prototype.forEach.call(document.querySelectorAll('.section-label'), function (el) {
        var s = (el.textContent || '').trim();
        if (!s || s.indexOf('監視ねこ') === 0 || s.indexOf('全セッション') === 0) return;
        if (/^(今日の予定|今日中|ルーチンタスク|明日以降)/.test(s)) return;
        if (ODD_RES.some(function (re) { return re.test(s); })) {
          if (odd.indexOf(s) === -1) odd.push(s);
        }
      });
      if (odd.length) {
        msgs.push('セクション見出し「' + odd.join('」「') + '」は正式名（今日の予定・今日中・ルーチンタスク・明日以降）では'
          + 'ありません。正式名でない見出しの項目は、進捗の数え方・ドラッグでの移動・日付の切り替えでの扱いが正式名と変わります。');
      }
      // ---- 「明日以降」の時刻の食い違い（2026-11-05 新設・直さずに知らせるだけ） ----
      // 「明日以降」の未完了の行で、実施日（data-due）に時刻があり、H:MM の時刻の欄がそれと違うもの。board_edit.py v1.6 までの操作
      // （今日の側で set-time した行を D&D・move で「明日以降」へ戻す等）でできる（v1.7 の set-time・set-due・add・create は作らないが、
      // v1.6 までに今日の側にできた行を戻したとき・restore で v1.6 までの板を戻したときには残る）。このままだと、今日の側へ動かすとき
      // （D&D・move。印の無い行は Deck v2.11 の日付の切り替えも）は時刻の欄の時刻が使われ、ボードを作り直すと実施日の時刻だけが残る。
      // どちらにするかを決めてもらう。時刻の欄が範囲外（25:00 など）の行は対象にしない（K12・「時刻を読めない」の側）
      // 条件は board_edit.py の警告 K14（later_time_mismatches）と同じ。実施日の読み方は Deck の parse_due_value と同じ
      // （YYYY-MM-DD H:MM で、暦にある日・時 0〜23・分 0〜59）。時刻の欄は HTML の元の時刻（✎ の data-orig）で見る。
      // H:MM でない時刻の欄は対象にしない（board_edit.py では K12 が知らせる）
      var laterMis = 0;
      Array.prototype.forEach.call(document.querySelectorAll('.item[data-due]:not([data-sid])'), function (item) {
        if (!inLaterSection(item) || item.classList.contains('done-item') || item.querySelector('.chip.done')) return;
        var f = /^(\d{4})-(\d{2})-(\d{2}) (\d{1,2}):(\d{2})$/.exec(item.getAttribute('data-due') || '');
        if (!f || +f[4] > 23 || +f[5] > 59) return;
        var cal = new Date(+f[1], +f[2] - 1, +f[3]);
        if (cal.getFullYear() !== +f[1] || cal.getMonth() !== +f[2] - 1 || cal.getDate() !== +f[3]) return;
        var timeEl = item.querySelector('.time');
        if (!timeEl || tbTimeElBroken(timeEl)) return;
        var t = /^(\d{1,2}):(\d{2})$/.exec((timeEl.getAttribute('data-orig') || tbTimeText(timeEl)).trim());
        if (t && +t[1] <= 23 && +t[2] <= 59 && (+t[1]) + ':' + t[2] !== (+f[4]) + ':' + f[5]) laterMis++;
      });
      if (laterMis) {
        msgs.push('「明日以降」に、時刻の欄と実施日（日付のチップ）の時刻が違うタスクがあります（' + laterMis + ' 件）。'
          + '今日の側へ動かすとき（ドラッグ。一度今日へ移した印の無い行は Deck の日付の切り替えも）は時刻の欄の時刻が使われ、ボードを作り直すと実施日の時刻だけが残ります。どちらの時刻にするかを決めてください。');
      }
      // ---- 閉じタグの無い時刻の欄（2026-11-06 新設・直さずに知らせるだけ） ----
      // <span class="time">0:00 のように時刻の欄が閉じていない行（data-tb-unclosed）。時刻の欄の中に class を持つ要素があるので、
      // ✎ で時刻を変えられない。欄の中にタイトルやチップが入っている行（tbTimeHasPart）は、「明日以降」へ動かすときに実施日も決められない
      // （欄の中に入ったのが部品でない class の要素だけの行は、閉じタグの有無によらず決められる＝Deck も同じ。行の鍵は Deck と合うので、D&D・通知・× は効く）。
      // board_edit.py の警告 K15 と同じく項目ごとに数える（時刻の欄が2つ以上ある行は、どれか1つが閉じていなければ1件）。DOM しか見られないので、
      // 閉じタグは無いがブラウザが欄をタイトルやチップの手前で閉じる行（K15 には出る＝_time_screen_closed）は数えない。
      // 欄が div の行は後ろの項目も中に入れることが多く、上の入れ子（①）にも数えられる。自動収集カード（data-sid）は見ない
      var unclosedItems = [];
      Array.prototype.forEach.call(document.querySelectorAll('.item .time[data-tb-unclosed]'), function (el) {
        var it = el.closest && el.closest('.item');
        if (it && !it.closest('[data-sid]') && unclosedItems.indexOf(it) < 0) unclosedItems.push(it);
      });
      var unclosed = unclosedItems.length;
      if (unclosed) {
        msgs.push('時刻の欄の閉じタグが無いタスクがあります（' + unclosed + ' 件）。時刻の欄の中にタイトルやチップなど class を持つ要素が入るため、'
          + '✎ で時刻を変えられません。欄の中にタイトルやチップが入っている行は、「明日以降」へ動かすときに実施日も決められません。'
          + '形によっては、今日の予定の未完了の行にあると Deck の日付の切り替えが止まり、翌日のボードが作られないので、今日のうちに直してください。');
      }
      var FIX = 'Claude に「ボードを直して」と頼んでください。';
      if (prev && msgs.length && prev.getAttribute('data-msgs') === msgs.join('')) return;
      if (prev) prev.parentNode.removeChild(prev);
      if (!msgs.length) return;
      var el = document.createElement('div');
      el.id = 'tb-board-check';
      el.setAttribute('data-msgs', msgs.join(''));
      el.setAttribute('role', 'status');
      el.className = 'warn';
      var ic = document.createElement('span');
      ic.className = 'tb-notice-icon';
      ic.setAttribute('aria-hidden', 'true');
      ic.textContent = '⚠';
      var box = document.createElement('div');
      var lb = document.createElement('strong');
      lb.className = 'tb-notice-label';
      lb.textContent = 'ボードの点検';
      box.appendChild(lb);
      box.appendChild(document.createTextNode(' — ' + msgs.join('')));
      var fx = document.createElement('span');
      fx.className = 'tb-notice-fix';
      fx.textContent = FIX;
      box.appendChild(fx);
      el.appendChild(ic);
      el.appendChild(box);
      var anchor = noticeEl();
      anchor.parentNode.insertBefore(el, anchor.nextSibling);
    }

    // 日付が変わった直後（0:00 から 20 秒後）に1回読み直す。開いたままのタブは、読み込み時に
    // 決めた発行済みボード判定のまま日付をまたぐので、5分ごとの再読み込みを待たずに今日の判定へ戻す。
    // 0:00 まで5分以上ある間は、先に5分ごとの再読み込みが来てこの予約ごと作り直される。
    (function () {
      var n = new Date();
      var next = new Date(n.getFullYear(), n.getMonth(), n.getDate() + 1, 0, 0, 20);
      var ms = next - n;
      if (ms > 0 && ms <= 300000) setTimeout(function () { tbReload(); }, ms);
    })();

    // 「明日以降」の行か（見出しをさかのぼって見る。D&D の後の並びで判定する）
    function inLaterSection(item) {
      var s = item.previousElementSibling;
      while (s && !s.classList.contains('section-label')) s = s.previousElementSibling;
      return !!s && s.textContent.trim().indexOf('明日以降') === 0;
    }

    // ---- 時刻トリガー到達の検知（③）: 発火済みはlocalStorageで記憶（リロード耐性） ----
    function checkAlarms(nowMin) {
      var fired = readJSON('fired:' + dateKey, []);
      var changed = false;
      Array.prototype.forEach.call(document.querySelectorAll('.item'), function (item) {
        var timeEl = item.querySelector('.time');
        if (!timeEl || item.classList.contains('done-item') || item.querySelector('.chip.done')) return;
        // 「明日以降」の行は通知の対象にしない（Deck の read_board_alarms と同じ。時刻の欄が残っていても今日のその時刻に出さない）
        if (inLaterSection(item)) return;
        var t = parseHM(tbTimeText(timeEl));
        if (t === null) return;
        // 発火済みキーは「実効時刻|タイトル」で持つ（Deck の read_board_alarms と同一定義）。
        // taskKey は data-orig ＝元の時刻を使うため、時刻を変更しても同じキーのままになり、
        // 変更前に発火済みとして記録された項目が新しい時刻でトーストを出せない。
        // 2026-08-04、音は鳴るのにポップアップだけ出ない事象として実測された。
        var titleEl = item.querySelector('.task-title');
        var key = (tbTimeText(timeEl).trim() + '|' + tbTitleText(titleEl)).trim();
        if (t <= nowMin && fired.indexOf(key) < 0) {
          fired.push(key); changed = true;
          if (nowMin - t <= 5) { // 開くのが遅れた過去分はまとめて出さない
            // 音はここでは鳴らさない（Deck が同じ条件で判定して鳴らす）。両方で鳴らすと
            // ページをクリック済みのときだけ二重に鳴る。
            // この判定は Deck の有無に関わらず常に走る。Deck 稼働中は Deck 経由（3秒周期）が
            // 先に描画することが多いが、同じキーなら showNotification が弾くので二重には出ない。
            showNotification(key, '⏰ ' + tbTimeText(timeEl).replace(' ✎', '') + ' ' + (titleEl ? titleEl.textContent : ''));
          }
        }
      });
      if (changed) LS.set('fired:' + dateKey, JSON.stringify(fired));
    }

    // ---- 時刻の手動変更（④）: 持ち主は Deck（timesMap）・✎印 ----
    function renderTimes() {
      var ovr = timesMap || timesLast || {};
      var can = timesCan();
      var locked = timesLoaded && !timesBusy && !can;
      var msg = can ? 'クリックで時刻を変更' : !locked ? '' : TB_LIVE.live ? TIME_MSG_LOCKED : TIME_MSG_NOT_TODAY;
      Array.prototype.forEach.call(document.querySelectorAll('.item .time'), function (timeEl) {
        if (tbTimeElBroken(timeEl)) return;
        var item = timeEl.closest('.item');
        // 「明日以降」の行は ✎ を受けず、元の時刻（HTML の時刻の欄）を出す（Deck の上書きは今日の側の行にだけ効くため。
        // 同じ日に今日の側へ戻せば、上書きはまた表示と通知に使われる＝Deck の read_board_alarms と同じ）
        var later = inLaterSection(item);
        timeEl.style.cursor = can && !later ? 'pointer' : '';
        timeEl.title = later ? TIME_MSG_LATER : msg;
        timeEl.classList.toggle('time-locked', locked || later);
        if (timeEl.querySelector('input')) return;
        var v = later ? null : ovr[taskKey(item)];
        timeEl.textContent = v || timeEl.getAttribute('data-orig');
        timeEl.classList.toggle('overridden', !!v);
      });
    }
    function makeTimesEditable() {
      Array.prototype.forEach.call(document.querySelectorAll('.item .time'), bindTimeEl);
      // D&D で実施日の来た行に足した時刻の欄にも、同じ ✎ を結ぶ（shapeDueMove が呼ぶ）
      tbBindTimeEl = function (timeEl) { bindTimeEl(timeEl); renderTimes(); };
    }
    function bindTimeEl(timeEl) {
        if (tbTimeElBroken(timeEl)) return;
        timeEl.setAttribute('data-orig', tbTimeText(timeEl).trim());
        timeEl.addEventListener('click', function (ev) {
          ev.stopPropagation();
          if (timeEl.querySelector('input')) return;
          if (inLaterSection(timeEl.closest('.item'))) { timeToast(TIME_MSG_LATER); return; }
          if (!timesCan()) {
            // 読めていない間は開かない（Deck に保存できない変更を受け付けない）。最初の応答を待つ間と操作の途中は黙る
            if (timesLoaded && !timesBusy) timeToast(TB_LIVE.live ? TIME_MSG_LOCKED : TIME_MSG_NOT_TODAY);
            return;
          }
          var item = timeEl.closest('.item');
          var cur = parseHM(timeEl.textContent);
          var inp = document.createElement('input');
          inp.type = 'time';
          if (cur !== null) inp.value = ('0' + Math.floor(cur / 60)).slice(-2) + ':' + ('0' + (cur % 60)).slice(-2);
          timeEl.textContent = '';
          timeEl.appendChild(inp);
          inp.focus();
          var committed = false;
          function commit() {
            if (committed) return;
            committed = true;
            var v = inp.value;
            if (inp.parentNode) timeEl.removeChild(inp);
            renderTimes();
            if (v && tbDayStop(true)) return;   // 開いたまま日付が変わった（送らずに読み直す）
            if (v) timesOperate(taskKey(item), fmtHM(parseHM(v)), timeEl.getAttribute('data-orig'));
            else refresh();
          }
          // change では確定しない。type="time" は既存値が入っているため、時の桁を
          // 1つ打った時点で値が妥当になり change が発火してしまい、分まで入力できない
          // （2026-08-04 ユーザー報告）。確定は Enter と、入力欄を離れたときだけにする。
          inp.title = 'Enter か、他の場所をクリックで確定';
          inp.addEventListener('blur', commit);
          inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') commit(); });
        });
    }

    // ---- 「タスク更新」からの経過表示（相対時刻） ----
    // ヘッダの #upd-time は「HH:MM」だけで日付を持たない。従来は未来の時刻（diff<0）を
    // 無条件に +1440 していたため、現在時刻より数分進んだ時刻が「1435分前」と表示された
    // （2026-08-05 ユーザー目撃）。実在しない経過を捏造しないよう、負の差を3つに分ける。
    //   ① |diff| <= REL_SKEW_MIN … 書き込みから描画までの数十秒差・分の切り捨て・PC の
    //      時計合わせ程度のズレ。「たった今」へ倒す（少し未来は今と見なす）
    //   ② それ以上の未来 かつ ヘッダの日付が今日（TB_LIVE.live）… 今日のボードに未来の
    //      時刻が入っているのは書き手側の誤りで、日跨ぎではありえない。数字を出すと必ず
    //      1300 分台になり「本当に古いボード」と見分けが付かなくなるので、経過を出さずに
    //      「更新時刻が未来」と事実だけを表示する
    //   ③ それ以上の未来 かつ ヘッダの日付が今日でない … 前日のボードを開いたまま日付を
    //      またいだ状態。この場合に限り +1440（＝前日の時刻として数える）が実際の経過と一致する
    // 120分以上は「約N時間前」にする（分のままだと桁が増えて一目で読めないため）。
    var REL_SKEW_MIN = 5;
    function fmtRelative(diff) {
      if (diff < 0) {
        if (diff >= -REL_SKEW_MIN) diff = 0;              // ①
        else if (TB_LIVE.live) return '（更新時刻が未来）'; // ②
        else diff += 1440;                                 // ③
      }
      if (diff <= 0) return '（たった今）';
      if (diff < 120) return '（' + diff + '分前）';
      return '（約' + Math.floor(diff / 60) + '時間前）';
    }

    // ---- ▶次・時刻超過・相対時刻（既存機能） ----
    function addChip(item, cls, label, first) {
      var chips = item.querySelector('.chips');
      if (!chips) return;
      var c = document.createElement('span');
      c.className = 'chip ' + cls + ' js-auto';
      c.textContent = label;
      if (first && chips.firstChild) chips.insertBefore(c, chips.firstChild);
      else chips.appendChild(c);
    }
    function refresh() {
      var now = new Date();
      var nowMin = now.getHours() * 60 + now.getMinutes();

      Array.prototype.forEach.call(document.querySelectorAll('.js-auto'), function (el) { el.remove(); });
      Array.prototype.forEach.call(document.querySelectorAll('.next-up'), function (el) { el.classList.remove('next-up'); });

      // 実施日（data-due。board_edit.py の add / set-due が書き、Deck v2.8 の日付の切り替えが見る）を見えるようにする。
      // 手で書かない（HTML 正本には属性だけがある）。「明日以降」では日付、過ぎていれば知らせ（印のある行〔旧版で戻した行・印を写した行〕・Deck が
      // 切り替えていない行）。今日の側では「いつの予定か」を出す（一度引き継いだ行で、元の日付が同じならチップが重なるので出さない）。
      // 今日の側へ移した行は実施日が今日になり、元の実施日は data-due-from にある（Deck v2.11）ので、そちらから「↪ 11/4 22:05 の予定から」と出す。
      // このチップを出した行には、引き継ぎのチップ（下）を出さない（「↪」のチップは1行に1つ。元の予定の日時のほうが、引き継いだ日より
      // 元をたどれる。引き継いだ日は元の実施日の日か、その後の日〔日付を決め直した行では前の日のこともある〕）
      var fromShown = [];
      Array.prototype.forEach.call(document.querySelectorAll('.item[data-due]:not([data-sid])'), function (item) {
        var f = /^(\d{4})-(\d{1,2})-(\d{1,2})(?: (\d{1,2}:\d{2}))?$/.exec(item.getAttribute('data-due') || '');
        if (!f) return;
        var md = (+f[2]) + '/' + (+f[3]) + (f[4] ? ' ' + f[4] : '');
        var cls = 'pending', label, fromChip = false;
        if (inLaterSection(item)) {
          if (new Date(+f[1], +f[2] - 1, +f[3]) < noticeToday() && !item.querySelector('.chip.done')) { cls = 'hold'; label = md + ' を過ぎました'; }
          else label = md;
        } else {
          var g = /^(\d{4})-(\d{1,2})-(\d{1,2})(?: (\d{1,2}:\d{2}))?$/.exec(item.getAttribute('data-due-from') || '');
          if (g) {
            label = '↪ ' + (+g[2]) + '/' + (+g[3]) + (g[4] ? ' ' + g[4] : '') + ' の予定から';
            fromChip = true;
          } else {
            if (item.getAttribute('data-carried-from') === f[1] + '-' + f[2] + '-' + f[3]) return;
            label = (item.hasAttribute('data-due-moved') ? '↪ ' : '') + md + ' の予定';
          }
        }
        if (!item.querySelector('.chips')) {
          var title = item.querySelector('.task-title');
          if (!title) return;
          var box = document.createElement('div');
          box.className = 'chips';
          title.parentNode.appendChild(box);
        }
        addChip(item, cls, label, false);
        if (fromChip) fromShown.push(item);
      });

      // Deck が日付の切り替えで引き継いだタスク（data-carried-from）に、元の日付と元の予定時刻を出す
      // （Deck v2.2。時刻付きの予定は今日中へ移すので、元の時刻はここでしか見えない）
      Array.prototype.forEach.call(document.querySelectorAll('.item[data-carried-from]:not([data-sid])'), function (item) {
        var f = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(item.getAttribute('data-carried-from') || '');
        if (!f || fromShown.indexOf(item) >= 0) return;
        // data-orig-time は data-carried-from と組（引き継いだ日のその行の時刻。Deck v2.12 は data-carried-from を新しく付けるときだけ書く）
        var ot = (item.getAttribute('data-orig-time') || '').trim();
        addChip(item, 'pending', '↪ ' + (+f[2]) + '/' + (+f[3]) + (ot ? ' ' + ot + ' の予定' : '') + 'から', false);
      });

      var next = null;
      Array.prototype.forEach.call(document.querySelectorAll('.item'), function (item) {
        if (item.classList.contains('done-item') || item.querySelector('.chip.done')) return;
        var timeEl = item.querySelector('.time');
        if (!timeEl) return;
        if (inLaterSection(item)) return;   // 今日の予定ではないので、▶ 次・時刻超過の対象にしない
        var t = parseHM(tbTimeText(timeEl));
        if (t === null) {
          // 時刻の欄が H:MM として読めない（「9時」等）と、通知音・ポップアップ・時刻超過が黙って
          // 発火しないので、その項目に知らせる。✎ で編集中（入力欄がある）ときは除く
          if (tbTimeText(timeEl).trim() && !timeEl.querySelector('input')) {
            addChip(item, 'hold', '時刻を読めない', false);
          }
          return;
        }
        if (t <= nowMin) {
          if (!item.querySelector('.chip.active')) addChip(item, 'hold', '時刻超過', false);
        } else if (!next) {
          next = item;
        }
      });
      if (next) {
        next.classList.add('next-up');
        addChip(next, 'active', '▶ 次', true);
      }

      // ヘッダの「タスク更新」は Claude がボードの中身を書いた時刻（テンプレの {{UPDATED_AT}}）で、
      // 「全セッション（自動収集 HH:MM）」は Deck がセッションカードを作り直した時刻。
      // 意味が違うので一本化しない（2026-08-05 決定）。従来は「新しい方」をヘッダへ写して
      // セクション側の時刻表記を消していたが、Deck は数秒ごとに自動収集を回すため、
      // ヘッダが常にほぼ現在時刻になり「ボードの中身が何分前のものか」が読めなくなる。
      // ——手書きのタスクが半日前のままでも「たった今」と出てしまう。
      // また消す実装は refresh() の2回目以降に時刻を読めず、補正自体が初回しか効いていなかった。
      // 現在は両方をそのまま表示する（ヘッダ＝中身の鮮度／セクション見出し＝自動収集の鮮度）。
      // ヘッダを最新に保つ責任は書き手側にある（skill/SKILL.md「update モード」で #upd-time の
      // 更新を必須にしてある）。Deck の稼働状況は「監視ねこ」の行で別に見える。
      var updEl = document.getElementById('upd-time');
      var relEl = document.getElementById('upd-rel');
      if (updEl && relEl) {
        var t = parseHM(updEl.textContent);
        relEl.textContent = t === null ? '' : fmtRelative(nowMin - t);
      }
      // 上書きの地図の最初の結果を待つ（応答の前に元の時刻で通知を出さない）。Deck が無ければすぐ結果が出て、元の時刻で判定する
      if (timesLoaded) checkAlarms(nowMin);
      applyHidden();
      applyHiddenTasks();  // applyHidden と同じ位置（クラスを付けるだけ）。可視 item を
                           // 数える applyHideDone より必ず前に置く
      renderDeckStatus();  // 冒頭の js-auto 一括削除で消えているため描き直す
      applyHideDone();     // applyHidden（data-sid の display）と renderDeckStatus
                           // （#deck-status-row の挿入）の後に置く。前に置くと
                           // セクションの可視 item 数を数え違える
    }

    // ---- 自動収集カードの非表示（×ボタン・localStorage・設定から復元） ----
    function applyHidden() {
      var hidden = readJSON('hiddenSids', []);
      Array.prototype.forEach.call(document.querySelectorAll('.item[data-sid]'), function (item) {
        var sid = item.getAttribute('data-sid');
        item.style.display = hidden.indexOf(sid) >= 0 ? 'none' : '';
        if (!item.querySelector('.hide-btn')) {
          var b = document.createElement('button');
          b.type = 'button'; b.className = 'hide-btn'; b.textContent = '×';
          b.title = 'このセッションを非表示にする（⚙設定から戻せる）';
          b.addEventListener('click', function () {
            var h = readJSON('hiddenSids', []);
            if (h.indexOf(sid) < 0) h.push(sid);
            LS.set('hiddenSids', JSON.stringify(h));
            applyHidden();
          });
          var inner = item.querySelector('div');
          if (inner) inner.insertBefore(b, inner.firstChild);
        }
      });
      var cnt = document.getElementById('hidden-count');
      if (cnt) cnt.textContent = String(readJSON('hiddenSids', []).length);
    }

    // ---- 手書きの済タスクを1件ずつ非表示（×ボタン・日付スコープ・2026-08-08 新設） ----
    // 隠す規則そのものは board.css 側（.item.tb-task-hidden）にある。ここは
    // 「クラスを localStorage に合わせる」「× を1回だけ生やす」「⚙の件数を書く」だけ。
    // 鍵は既存の taskKey()（= .time の data-orig ＝元の時刻 | タイトル）を再利用する。
    // 実効時刻（checkAlarms 内のローカル key）ではない——✎で時刻を手で変えても
    // 非表示のままにしたいため。4つ目の鍵定義を作らないこと。
    // 日付スコープにするのは、手書きタスクの鍵がタイトル文字列で、ルーチンタスクは
    // 日をまたいで同じ文字列が別の実体に再利用されるため（hiddenSids の sid は
    // transcript 由来の一意 ID なので恒久でよい。この非対称は偶然ではない）。
    // dateKey は IIFE 冒頭で1回だけ読んだ値を使う。ここで .date を読み直してはいけない
    // ——カレンダーポップアップが header .date の中へ差し込まれるため、ホバー後に
    // textContent を読むとカレンダーの文字列が混ざる。
    var HIDE_TASK_KEY = 'hideTask:' + dateKey;

    // × を出してよい item か。**data-sid の有無だけでは決めない**——data-sid が無くても
    // 出してはいけない行がある。Deck が出す「監視ねこ」行は data-sid を持たない
    // （deck_watcher.py の _guard_section が「付けると board.js が × 非表示ボタンを生やし、
    // ユーザーが生死表示を消せてしまう」と明記して意図的に外している）。
    // 下の early-return と同じ順で ①data-sid が無い ②js-auto でない ③済（done-item）
    // ④タスク名がある——の4つすべてを満たしたときだけ真。
    function canHideTask(it) {
      if (it.hasAttribute('data-sid')) return false;
      if (it.classList.contains('js-auto')) return false;      // #deck-status-row
      if (!it.classList.contains('done-item')) return false;   // 済だけに出す
      var ti = it.querySelector('.task-title');
      return !!(ti && ti.textContent.trim());                  // 監視ねこ行を除外
    }

    // 冪等。× は js-auto を付けない（refresh 冒頭の一括削除に巻き込ませない）。
    function applyHiddenTasks() {
      var list = readJSON(HIDE_TASK_KEY, []);
      var items = document.querySelectorAll('.item');
      // 先に「× を出せる item が現に持っている鍵」を集める。鍵の掃除は item ごとではなく
      // **この集合に無い鍵だけ**を落とす形で行う——item ごとに落とすと、同じ鍵の item が
      // 板に2つある形（例: 済の「共通タスク」が今日の予定に、未の同名がルーチンタスクに）で、
      // 対象外の側が対象の側の鍵を巻き添えにする。その結果 × を押しても走査のたびに鍵が消え、
      // refresh()（30秒周期）で元に戻る＝機能そのものが無効化される。
      var live = [];
      Array.prototype.forEach.call(items, function (it) {
        if (!canHideTask(it)) return;
        var k = taskKey(it);
        if (live.indexOf(k) < 0) live.push(k);
      });
      Array.prototype.forEach.call(items, function (it) {
        if (!canHideTask(it)) {
          // 済→保留へ差し戻された行は対象外へ戻す（鍵の掃除は下のループ後にまとめて行う）。
          it.classList.remove('tb-task-hidden');
          var old = it.querySelector('.task-hide-btn');
          if (old && old.parentNode) old.parentNode.removeChild(old);
          return;
        }
        it.classList.toggle('tb-task-hidden', list.indexOf(taskKey(it)) >= 0);
        if (!it.querySelector('.task-hide-btn')) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'hide-btn task-hide-btn';  // 見た目は既存の × と共用（CSS 追加なし）
          b.textContent = '×';
          b.title = 'この済タスクを画面から隠す（⚙設定から戻せます。今日だけ・HTML には書き込みません）';
          // 今日の予定／今日中／明日以降の item は draggable="true"（D&D IIFE の refreshMarks）。
          // その内側のボタンなので、mousedown の既定動作を止めてドラッグ開始を抑える。
          b.addEventListener('mousedown', function (ev) { ev.preventDefault(); });
          b.addEventListener('click', function (ev) {
            ev.stopPropagation();
            var k = taskKey(it);                 // クロージャに固めず毎回読む
            var h = readJSON(HIDE_TASK_KEY, []);
            if (h.indexOf(k) < 0) h.push(k);
            LS.set(HIDE_TASK_KEY, JSON.stringify(h));
            applyHiddenTasks();
            applyHideDone();                     // セクションが空になった場合の要約行を出し直す
          });
          var host = it.querySelector('.task-title').parentNode;  // 内容 div。
          // item.querySelector('div') は使わない——時刻付き item では .time セルを返し、
          // × が時刻列に入るうえ makeTimesEditable のクリックハンドラに食われる。
          // flat item では偶然通るので、時刻付きだけが壊れる気づきにくい形になる。
          host.insertBefore(b, host.firstChild);
        }
      });
      // 鍵の掃除。落とすのは「× を出せる item が1つも持っていない鍵」だけ。
      // ①済→保留へ差し戻された行の鍵はここで落ちる（残すと、同じ日に再び済にした瞬間に
      // × を押していないのに消える＝黙って消える側に倒れる）②板から削除された行の
      // 幽霊鍵も同じ経路で落ちるので、⚙の件数が実体と乖離したまま残らない。
      var kept = list.filter(function (k) { return live.indexOf(k) >= 0; });
      if (kept.length !== list.length) LS.set(HIDE_TASK_KEY, JSON.stringify(kept));
      // 件数は鍵の数ではなく**実際に隠れている item の数**を出す。1つの鍵が同名の item 2つに
      // 当たる板では鍵の数が実体より少なくなり、「すべて戻す」で戻る行数（＝item 数）や
      // セクション要約行の「済 N件を非表示中」（applyHideDone の hidAny も item 単位）と
      // 食い違うため。この時点で上のループがクラスを確定させているので読み取りは安全。
      var cnt = document.getElementById('th-count');
      if (cnt) cnt.textContent = String(document.querySelectorAll('.item.tb-task-hidden').length);
    }

    // ---- 手書きセクションの済タスクを隠す（⚙トグル・localStorage・表示のみ・2026-08-07 新設） ----
    // 隠す規則そのものは board.css 側（:root.tb-hide-done .item.done-item:not([data-sid])）にある。
    // ここは「ルート要素のクラスを LS に合わせる」「⚙の件数を書く」「済だけになった
    // セクションに要約行を1本出す」の3つだけを行う。Deck へは何も送らない
    // （deckPost / soundOperate / timesOperate / persistMove を呼ばない）。
    // ルート要素は board.html に存在しない（テンプレに <html> タグが無く、ブラウザが合成する）ため、
    // Claude の update とも Deck の書き換えとも構造上ぶつからない。data-theme と同じ置き場。
    // セクションの走査は renderDeckStatus() と同じ「見出しから nextSibling を次の見出しまで
    // たどる」形にそろえる。
    function hdGroups() {
      var groups = [];
      Array.prototype.forEach.call(document.querySelectorAll('.section-label'), function (label) {
        var g = { label: label, items: [] };
        var n = label.nextSibling;
        while (n) {
          if (n.nodeType === 1 && n.classList) {
            if (n.classList.contains('section-label')) break;
            if (n.classList.contains('item')) g.items.push(n);
          }
          n = n.nextSibling;
        }
        groups.push(g);
      });
      return groups;
    }
    // 冪等。呼ばれるたびに要約行を全部消してから作り直す。
    function applyHideDone() {
      var on = LS.get('hideDone', '0') === '1';
      document.documentElement.classList.toggle('tb-hide-done', on);
      Array.prototype.forEach.call(document.querySelectorAll('.hd-summary'), function (el) { el.remove(); });
      var total = 0;
      hdGroups().forEach(function (g) {
        var hidT = 0, hidAny = 0, vis = 0;
        g.items.forEach(function (it) {
          // 一括トグルが隠すもの＝手書き（data-sid なし）の済 item
          var byToggle = on && !it.hasAttribute('data-sid') && it.classList.contains('done-item');
          // × で1件ずつ隠したもの（applyHiddenTasks がクラスを付ける。トグルと重なりうる）
          var byX = it.classList.contains('tb-task-hidden');
          if (byToggle) hidT++;
          if (byToggle || byX) hidAny++;
          // 見えているもの（applyHidden が × で隠した data-sid カードは vis に数えない）
          else if (it.style.display !== 'none') vis++;
        });
        total += hidT;   // ⚙の hd-count は「一括トグルが隠している数」のまま（意味を変えない）
        // 「我々が隠した結果ちょうど空になった」ときだけ要約行を出す。
        // hidAny > 0 を条件にするので、元から item が0件の見出しには出ない。
        // 「全セッション」にも出ない——data-sid カードは byToggle の対象外で、
        // tb-task-hidden も付かない（applyHiddenTasks が最初に除外する）ため
        // hidAny が 0 のままになる。あちらを隠しているのは applyHidden の
        // style.display で、それは vis 側でだけ差し引かれる。
        // 2026-08-08 に hid → hidAny へ広げた: × だけでセクションが空になった場合も
        // 説明の1行が要るため（トグル OFF でも出る）。トグルだけを数える hidT は
        // ⚙の hd-count 用に分けてあるので、そちらの意味は変えていない。
        if (hidAny > 0 && vis === 0) {
          var row = document.createElement('div');
          // .task-note を借りるので board.css に追加規則は要らない。
          // js-auto は付けない（refresh 冒頭の一括削除に巻き込ませない。除去は自前で行う）。
          // .item ではないので groupItems / refreshMarks / recalc / refresh の走査には乗らない。
          row.className = 'task-note hd-summary';
          row.style.margin = '0 0 8px 2px';
          row.textContent = '済 ' + hidAny + '件を非表示中';
          g.label.parentNode.insertBefore(row, g.label.nextSibling);
        }
      });
      var cnt = document.getElementById('hd-count');
      if (cnt) cnt.textContent = String(total);
    }

    // ---- 設定パネルの配線 ----
    function initSettings() {
      var panel = document.getElementById('settings-panel');
      var sBtn = document.getElementById('settings-btn');
      if (sBtn && panel) sBtn.addEventListener('click', function () {
        panel.hidden = !panel.hidden;
        if (!panel.hidden) soundRefresh();  // 別のブラウザが変えた値を、開いたときに映す
      });
      var tBtn = document.getElementById('theme-btn');
      if (tBtn) tBtn.addEventListener('click', function () {
        var order = ['auto', 'light', 'dark'];
        LS.set('theme', order[(order.indexOf(LS.get('theme', 'auto')) + 1) % 3]);
        applyTheme();
      });
      Array.prototype.forEach.call(document.querySelectorAll('[data-theme-set]'), function (b) {
        b.addEventListener('click', function () { LS.set('theme', b.getAttribute('data-theme-set')); applyTheme(); });
      });
      function bindToggle(id, key, def, onChange) {
        var b = document.getElementById(id);
        if (!b) return;
        function render() { var on = LS.get(key, def) === '1'; b.textContent = on ? 'ON' : 'OFF'; b.classList.toggle('on', on); }
        b.addEventListener('click', function () {
          LS.set(key, LS.get(key, def) === '1' ? '0' : '1');
          render();
          if (onChange) onChange();
        });
        render();
      }
      bindToggle('popup-toggle', 'popup', '1');
      // ポップアップの消え方（触るまで残す／30秒で自動）。既定は「触るまで残す」
      function renderToastMode() {
        var cur = LS.get('toastMode', 'stay');
        Array.prototype.forEach.call(document.querySelectorAll('[data-toast]'), function (b) {
          b.classList.toggle('active', b.getAttribute('data-toast') === cur);
        });
      }
      Array.prototype.forEach.call(document.querySelectorAll('[data-toast]'), function (b) {
        b.addEventListener('click', function () { LS.set('toastMode', b.getAttribute('data-toast')); renderToastMode(); });
      });
      renderToastMode();
      Array.prototype.forEach.call(document.querySelectorAll('.swatch'), function (b) {
        b.addEventListener('click', function () { LS.set('crit', b.getAttribute('data-crit')); applyCritColor(); });
      });
      // 通知音の設定。以前の版がブラウザに残した値は読まずに消す（Deck の値が正。移行はしない＝2026-11-02
      // ユーザー決定）。残すと、以前の版の board.js に戻したときにその古い値が Deck へ送られるため。
      LS.del('sound');
      LS.del('soundType');
      LS.del('soundFromDeck');
      var sToggle = document.getElementById('sound-toggle');
      if (sToggle) sToggle.addEventListener('click', function () {
        if (!soundCfg) return;
        var want = !soundCfg.enabled;  // 見えている値の反対にする（読み直した値の反対にしない）
        soundOperate(function (cur) { return { enabled: want, type: cur.type }; }, false);
      });
      // 音種のボタンは選んで試聴する。いまの音種を押しただけなら設定は変わらない
      Array.prototype.forEach.call(document.querySelectorAll('[data-sound]'), function (b) {
        b.addEventListener('click', function () {
          var type = b.getAttribute('data-sound');
          soundOperate(function (cur) { return { enabled: cur.enabled, type: type }; }, true);
        });
      });
      // 試聴は読んだ値をそのまま送るので、設定は変わらない
      var sTest = document.getElementById('sound-test');
      if (sTest) sTest.addEventListener('click', function () {
        soundOperate(function (cur) { return cur; }, true);
      });
      // 発行済みの板の説明文は日付の切り替えでも引き継がれるので、表示のときに今の文へ直す（HTML の正本は変えない）。
      // 直すのは「通知音は同梱の」を含む版と、「明日以降」の行を除く旨を足す前の版（2026-11-02〜11-05 のテンプレの文そのもの）
      var sDesc = panel && panel.querySelector('.set-note:not(#sound-note)');
      var sDescPrev = '通知音は Deck（監視ねこ）が鳴らします（Windows のみ・既定は OFF）。タスクの時刻はクリックで変更できます（変更した時刻には ✎ が付きます。Claude 側の記録も直すときはチャットで伝えてください）。通知音の設定と時刻の変更は Deck に保存されます。Deck が止まっている間は音が鳴らず、どちらも変更できません。ほかの設定はブラウザ毎に保存されます。';
      if (sDesc && (sDesc.textContent.indexOf('通知音は同梱の') >= 0 || sDesc.textContent.trim() === sDescPrev)) {
        sDesc.textContent = '通知音は Deck（監視ねこ）が鳴らします（Windows のみ・既定は OFF）。タスクの時刻はクリックで変更できます（「明日以降」の行を除く）（変更した時刻には ✎ が付きます。Claude 側の記録も直すときはチャットで伝えてください）。通知音の設定と時刻の変更は Deck に保存されます。Deck が止まっている間は音が鳴らず、どちらも変更できません。ほかの設定はブラウザ毎に保存されます。';
      }
      var sAnchor = sTest || document.querySelector('[data-sound]') || sToggle;
      if (sAnchor && panel) {
        var sNote = document.createElement('div');
        sNote.id = 'sound-note';
        sNote.className = 'set-note';
        sNote.hidden = true;
        var sRow = sAnchor.closest('.set-row');
        if (sRow) sRow.parentNode.insertBefore(sNote, sRow.nextSibling);
        else panel.appendChild(sNote);
      }
      renderSound();
      soundRefresh();
      // 以前の版がブラウザに残した ✎ の記録（`tb:ovr:<日付>`）は読まずに消す（Deck の値が正。移行はしない＝2026-11-02
      // ユーザー決定）。残すと、以前の版の board.js に戻したときにその古い値が Deck へ送られるため。日付の違う記録も消す
      try {
        Object.keys(localStorage).forEach(function (k) {
          if (k.indexOf('tb:ovr:') === 0) localStorage.removeItem(k);
        });
      } catch (e) {}
      var uBtn = document.getElementById('unhide-all');
      if (uBtn) uBtn.addEventListener('click', function () { LS.set('hiddenSids', '[]'); applyHidden(); });
      // 表示フィルタ行（済タスクを隠す）。renderOrderUI と同じく実行時に注入する——
      // board-template.html へ静的に書くと、既に発行済みの今日の board.html には現れないため
      // （board.html は create 時にテンプレから焼いたコピー。board.js は毎リロード読み直される）。
      if (panel && !document.getElementById('hd-toggle')) {
        var hdRow = document.createElement('div');
        hdRow.className = 'set-row';
        hdRow.title = '手書きセクション（今日の予定・今日中・ルーチンタスク・明日以降など）の'
          + '済タスクを画面から隠します。全セッションのカードは対象外です'
          + '（カードごとの × と「すべて再表示」で操作してください）。'
          + '進捗の N / M とバーは隠しても変わりません（進捗は事実であって表示設定ではないため）。';
        hdRow.innerHTML = '<span>済タスクを隠す（非表示中 <span id="hd-count">0</span>件）</span>'
          + '<button type="button" id="hd-toggle">OFF</button>';
        panel.insertBefore(hdRow, panel.querySelector('.set-note:not(#sound-note)') || null);
      }
      // × で隠した済タスクの復帰行。hd 行と同じく実行時に注入する（board-template.html へ
      // 静的に書くと、既に発行済みの今日の board.html には現れないため）。
      // 既存の「すべて再表示」（#unhide-all）に相乗りさせない——あの行のラベルは
      // 「× で隠したセッションの記録（N件）」で、手書きタスクの復帰を混ぜるとラベルが実挙動より
      // 狭くなる。既存の設計は「機能ごとに1行＋自前のカウント」で統一されている。
      if (panel && !document.getElementById('th-reset')) {
        var thRow = document.createElement('div');
        thRow.className = 'set-row';
        thRow.title = '手書きセクションの済タスクの × で隠した分です。今日のボードにだけ効き、'
          + 'ボードの日付が変わると自動で戻ります。HTML には書き込まないので Claude 側の記録は消えません。'
          + '進捗の N / M とバーは隠しても変わりません。';
        thRow.innerHTML = '<span>× で隠した済タスク（<span id="th-count">0</span>件）</span>'
          + '<button type="button" id="th-reset">すべて戻す</button>';
        panel.insertBefore(thRow, panel.querySelector('.set-note:not(#sound-note)') || null);
      }
      var thBtn = document.getElementById('th-reset');
      if (thBtn) thBtn.addEventListener('click', function () {
        LS.set(HIDE_TASK_KEY, '[]');
        applyHiddenTasks();
        applyHideDone();
      });
      bindToggle('hd-toggle', 'hideDone', '0', applyHideDone);
      var rBtn = document.getElementById('reload-btn');
      if (rBtn) rBtn.addEventListener('click', function () { tbReload(true); });
    }

    var la = document.getElementById('loaded-at');
    if (la) {
      var n = new Date();
      la.textContent = n.getHours() + ':' + ('0' + n.getMinutes()).slice(-2);
    }
    // ヘッダーの猫アイコン（cat.png）をそのままタブアイコン（favicon）にも使う
    try {
      var catSvg = document.getElementById('cat-icon');
      var iconLink = document.querySelector('link[rel="icon"]');
      if (catSvg && iconLink) iconLink.href = catSvg.src;
    } catch (e) {}
    applyTheme();
    applyCritColor();
    initSettings();
    makeTimesEditable();
    renderTimes();
    renderBoardNotice();  // 過去日の板は Deck の最初の応答を待つので、ここでは出ないことがある
    renderBoardCheck();
    refresh();
    timesRefresh();   // 応答を受けて描き直し、判定し直す（別のブラウザの変更も 30 秒ごとに映す）
    setInterval(function () { timesRefresh(); refresh(); }, 30000);
    // 通知の取得は 3 秒周期。Deck の検知からトースト表示までのずれをこの範囲に収める
    // （refresh の 30 秒周期のままだと最大 30 秒ずれる）。読み込み直後にも1回取りに行き、
    // リロードで消えた未確認トーストを復元する。
    pollNotifications();
    setInterval(pollNotifications, 3000);
    // D&D IIFE（replayMoves / applyOrder）はこの後に同期実行されノードを動かす。
    // macrotask へ逃がして、移動と並べ替えが終わった DOM に対して1回だけ数え直す。
    setTimeout(applyHideDone, 0);
    // 可視タスクが「済だけになったセクション」へドロップされたら要約行をその場で畳む。
    // このリスナーは D&D 側の drop ハンドラより先に登録されるが、仕事を macrotask へ
    // 逃がすので同期ハンドラ（移動・recalc）の完了後に走る。取りこぼしても
    // 次の refresh（最大30秒）で回収される。
    document.addEventListener('drop', function () { setTimeout(applyHideDone, 0); });
    // D&D で「明日以降」へ入った行・出た行の ✎ の受け付けと、ボードの点検（「明日以降」の時刻の食い違い）を作り直す。
    // 読み込みの直後にも1回（localStorage に残った移動を D&D の IIFE が当てた後）
    function afterMoves() { renderTimes(); renderBoardCheck(); }
    setTimeout(afterMoves, 0);
    document.addEventListener('drop', function () { setTimeout(afterMoves, 0); });
  })();

  // 日付ホバーのカレンダーポップアップ（◀▶で月移動・再ホバーで当月に戻る）
  (function () {
    var dateEl = document.querySelector('header .date');
    if (!dateEl) return;
    var pop = null, view = null, hideTimer = null;
    function build(y, m) {
      var start = new Date(y, m, 1).getDay();
      var days = new Date(y, m + 1, 0).getDate();
      var today = new Date();
      var wd = ['日', '月', '火', '水', '木', '金', '土'];
      var html = '<div class="cal-head">' +
        '<button class="cal-nav" data-d="-1" type="button">◀</button>' +
        '<span class="cal-title">' + y + '年' + (m + 1) + '月</span>' +
        '<button class="cal-nav" data-d="1" type="button">▶</button></div><table><tr>';
      for (var i = 0; i < 7; i++) {
        html += '<th class="' + (i === 0 ? 'cal-sun' : i === 6 ? 'cal-sat' : '') + '">' + wd[i] + '</th>';
      }
      html += '</tr><tr>';
      var cell = 0;
      for (i = 0; i < start; i++) { html += '<td></td>'; cell++; }
      for (var d = 1; d <= days; d++) {
        var dow = cell % 7;
        var cls = dow === 0 ? 'cal-sun' : dow === 6 ? 'cal-sat' : '';
        if (y === today.getFullYear() && m === today.getMonth() && d === today.getDate()) cls += ' cal-today';
        html += '<td class="' + cls + '">' + d + '</td>';
        cell++;
        if (cell % 7 === 0 && d < days) html += '</tr><tr>';
      }
      pop.innerHTML = html + '</tr></table>';
    }
    function show() {
      clearTimeout(hideTimer);
      // 表示中は再構築しない（日付→ポップアップ間の隙間通過で mouseenter が再発火し、
      // 月送りボタンのクリックが innerHTML 再構築に飲み込まれるのを防ぐ）
      if (pop && pop.style.display === 'block') return;
      if (!pop) {
        pop = document.createElement('div');
        pop.className = 'cal-pop';
        pop.addEventListener('mouseenter', function () { clearTimeout(hideTimer); });
        pop.addEventListener('mouseleave', scheduleHide);
        pop.addEventListener('click', function (e) {
          var b = e.target.closest ? e.target.closest('.cal-nav') : null;
          if (!b) return;
          view.setMonth(view.getMonth() + parseInt(b.getAttribute('data-d'), 10));
          build(view.getFullYear(), view.getMonth());
        });
        dateEl.appendChild(pop);
      }
      view = new Date(); view.setDate(1);
      build(view.getFullYear(), view.getMonth());
      pop.style.display = 'block';
    }
    function scheduleHide() {
      hideTimer = setTimeout(function () { if (pop) pop.style.display = 'none'; }, 200);
    }
    dateEl.addEventListener('mouseenter', show);
    dateEl.addEventListener('mouseleave', scheduleHide);
  })();

  // 自動収集カードの補足行末尾「／計画: ○○」をチップ表示に変換する
  // （Deck の出力形式は変えず、表示だけ板側で加工する）
  (function () {
    var notes = document.querySelectorAll('.item .task-note');
    Array.prototype.forEach.call(notes, function (note) {
      var t = note.textContent;
      var i = t.indexOf('／計画:');
      if (i === -1) return;
      var plan = t.slice(i + 4).replace(/^\s+|\s+$/g, '');
      note.textContent = t.slice(0, i);
      var item = note.closest ? note.closest('.item') : note.parentElement;
      var chips = item && item.querySelector('.chips');
      if (!chips) {
        chips = document.createElement('div');
        chips.className = 'chips';
        note.parentElement.appendChild(chips);
      }
      var c = document.createElement('span');
      c.className = 'chip plan';
      c.textContent = '計画: ' + plan;
      chips.appendChild(c);
    });
  })();

  // 手書きの計画タスクと、それに紐づくセッションカードの枠線を同色にする
  // （計画チップの計画名 = 手書きitemのタイトル、で照合。対応が無いカードは着色しない）
  (function () {
    var PALETTE = ['#d97f2f', '#3a9d5c', '#4a90d9', '#b356c9', '#c94f6d', '#2fa8a0', '#a08c2f', '#7a6ad9'];
    function norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
    var items = document.querySelectorAll('.item');
    var colorByPlan = {}, next = 0;
    function paint(el, c) {
      el.classList.add('plan-linked');
      if (el.classList.contains('crit')) {
        // 重要タスクの赤い左バーは維持し、残り3辺だけ着色する
        el.style.borderTopColor = c;
        el.style.borderRightColor = c;
        el.style.borderBottomColor = c;
      } else {
        el.style.borderColor = c;
      }
    }
    Array.prototype.forEach.call(document.querySelectorAll('.chip.plan'), function (chip) {
      var plan = norm(chip.textContent.replace(/^計画:\s*/, ''));
      if (!plan) return;
      var card = chip.closest ? chip.closest('.item') : null;
      var match = null;
      Array.prototype.forEach.call(items, function (it) {
        if (match || it === card) return;
        var t = it.querySelector('.task-title');
        if (t && norm(t.textContent) === plan) match = it;
      });
      if (!match || !card) return;
      if (!colorByPlan[plan]) colorByPlan[plan] = PALETTE[next++ % PALETTE.length];
      var c = colorByPlan[plan];
      paint(match, c);
      paint(card, c);
      chip.style.borderColor = c;
      chip.style.color = c;
    });
  })();

  // タスクのD&D移動（今日の予定/今日中/明日以降 間）とセクション表示順の設定。
  // いずれもブラウザ内のみの変更（localStorage保存・リロード時に再適用）。HTML正本は変えない。
  (function () {
    var LS = {
      get: function (k, d) { try { var v = localStorage.getItem('tb:' + k); return v === null ? d : v; } catch (e) { return d; } },
      set: function (k, v) { try { localStorage.setItem('tb:' + k, v); } catch (e) {} }
    };
    function readJSON(k, d) { try { return JSON.parse(LS.get(k, JSON.stringify(d))); } catch (e) { return d; } }
    var dateKey = ((document.querySelector('.date') || {}).textContent || '').trim().slice(0, 13);
    var MOVABLE = ['今日の予定', '今日中', '明日以降'];
    var KNOWN = ['今日の予定', '今日中', 'ルーチンタスク', '明日以降', '全セッション'];

    function canon(t) {
      t = (t || '').trim();
      for (var i = 0; i < KNOWN.length; i++) if (t.indexOf(KNOWN[i]) === 0) return KNOWN[i];
      // 未知セクションも末尾の可変部「（…）」を落として名前を安定させる。
      // これが無いと、見出しに時刻等が入った瞬間に保存済みの並び順と一致しなくなる。
      return t.replace(/[（(].*$/, '').trim();
    }
    function key(it) {
      var t = it.querySelector('.time');
      var ti = it.querySelector('.task-title');
      return ((t ? (t.getAttribute('data-orig') || tbTimeText(t).trim()) : '') + '|' + tbTitleText(ti)).trim();
    }
    function getGroups() {
      var first = document.querySelector('.board .section-label') || document.querySelector('.section-label');
      if (!first) return [];
      var groups = [], cur = null;
      Array.prototype.slice.call(first.parentNode.childNodes).forEach(function (n) {
        if (n.nodeType === 1 && (n.id === 'toast-area' || n.tagName === 'SCRIPT')) return;
        if (n.nodeType === 1 && n.classList && n.classList.contains('section-label')) {
          cur = { name: canon(n.textContent), nodes: [n] };
          groups.push(cur);
        } else if (cur) {
          cur.nodes.push(n);
        }
      });
      return groups;
    }
    function groupItems(g) {
      return g.nodes.filter(function (n) { return n.nodeType === 1 && n.classList && n.classList.contains('item'); });
    }
    function findGroup(groups, name) {
      for (var i = 0; i < groups.length; i++) if (groups[i].name === name) return groups[i];
      return null;
    }
    function findItemByKey(k) {
      var all = document.querySelectorAll('.item');
      for (var i = 0; i < all.length; i++) if (key(all[i]) === k) return all[i];
      return null;
    }

    // ---- 進捗の再表示（定義: 今日の予定+今日中のチップ付きitem。移動を反映して再計算） ----
    function recalc() {
      var M = 0, N = 0;
      getGroups().forEach(function (g) {
        if (g.name !== '今日の予定' && g.name !== '今日中') return;
        groupItems(g).forEach(function (it) {
          if (!it.querySelector('.chip:not(.js-auto):not(.plan)')) return;
          M++;
          if (it.querySelector('.chip.done')) N++;
        });
      });
      var lbl = document.querySelector('.progress-label span:last-child');
      if (lbl) lbl.textContent = N + ' / ' + M + ' 完了';
      var bar = document.querySelector('.bar-fill');
      if (bar) bar.style.width = (M ? Math.round(N / M * 100) : 0) + '%';
    }

    // ---- 実施日のある行の形（Deck v2.13 の _due_moved_shape と同じ規則・2026-11-05・2026-11-06） ----
    // 「明日以降」から今日の側へ動かした、実施日（data-due）が読めて済でない行を、一度移した印の有無・実施日が先の日かによらず、
    // Deck の日付の切り替え・D&D の反映・board_edit.py の move と同じ形にする。行の時刻は、時刻の欄が H:MM（時 0〜23・分 0〜59）
    // ならその時刻、無ければ実施日の時刻。行き先が今日の予定で実施日が今日で時刻があれば、時刻の欄をその時刻にして flat を外す。
    // それ以外は時刻の欄を外して flat を付ける（前の日・先の日の時刻を今日のその時刻に鳴らさない）。外した時刻の欄は data-orig-time に残さない
    // （行の時刻は data-due か data-due-from に残る。ただし H:MM でない時刻の欄の文字と、data-due-from が既にある行で時刻の欄の時刻がその時刻と違うときの時刻の欄の時刻は、どこにも残らない。
    // data-orig-time は Deck の日付の切り替えが data-carried-from と組で書く＝Deck v2.12）。
    // 状態チップが無ければ「未」を足す。実施日を今日にし（時刻の欄を付けるならその時刻を含め、付けないなら
    // 日付だけ）、元の実施日〔元の実施日の日付と行の時刻・Deck v2.12〕を data-due-from に残し、一度移した印を付ける（どちらも既にあれば変えない）。先の日の行
    // （前もって今日の側へ動かした行）も今日の行として同じ形にする（時刻は付かない・Deck v2.13。v2.12 までは日付も印も変えなかった）。
    // 画面の DOM だけを直す（HTML 正本は Deck が同じ形に書く）。Deck に届かず localStorage に残した移動を読み込みで再び当てるときも使う。
    // 時刻の欄が2つ以上ある行は印だけを付ける（Deck と同じ）
    function dueISO(d) {
      return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
    }
    function sectionOf(item) {
      var s = item.previousElementSibling;
      while (s && !(s.classList && s.classList.contains('section-label'))) s = s.previousElementSibling;
      return s ? canon(s.textContent) : null;
    }
    // 判定は Deck にそろえる: 実施日は YYYY-MM-DD か YYYY-MM-DD H:MM で、暦にある日・時 0〜23・分 0〜59 のときだけ読む
    // （parse_due_value）。時刻の欄が2つ以上ある行と、中に行の部品のある時刻の欄（tbTimeHasPart。閉じタグの無い欄に、ブラウザが
    // 後ろの要素を取り込んだ形など。Deck では形を作れない）は印だけを付ける。状態チップの判定は span.chip の done・active・pending・hold、
    // 「未」の置き場は、最初の属性が class でその値がちょうど "chips" の div の末尾、無ければ行の最後の div の末尾に chips 欄ごと
    // （_insert_status_chip）。属性の順を見るのは、Deck の <div class="chips" の照合に合わせるため（<div id=… class="chips"> は
    // chips 欄と見ない）。ただし DOM は引用符・空白・大文字を正規化するので、一致するのは板の書き手が書く正規の形
    // （<div class="chips"> を二重引用符・小文字・属性の先頭で書いた形）についてだけ。class='chips' のような形では Deck と違いうる
    function shapeDueMove(item, toSec) {
      var f = /^(\d{4})-(\d{2})-(\d{2})(?: (\d{1,2}):(\d{2}))?$/.exec(item.getAttribute('data-due') || '');
      if (!f || item.querySelector('.chip.done')) return;
      var y = +f[1], mo = +f[2], d = +f[3];
      var cal = new Date(y, mo - 1, d);
      if (cal.getFullYear() !== y || cal.getMonth() !== mo - 1 || cal.getDate() !== d) return;   // 暦に無い日（Deck も読まない）
      if (f[4] !== undefined && (+f[4] > 23 || +f[5] > 59)) return;
      var today = dueISO(new Date());
      var dueDay = f[1] + '-' + f[2] + '-' + f[3];
      var dueTime = f[4] !== undefined ? (+f[4]) + ':' + f[5] : null;
      var when = dueTime;
      var markIt = dueDay <= today && !item.hasAttribute('data-due-moved');
      var times = item.querySelectorAll('.time');
      var broken = times.length === 1 && tbTimeHasPart(times[0]);
      // 形を作れない行は、実施日の来た印の無い行にだけ印を付ける（Deck の _mark_due_moved と同じ）
      if (times.length > 1 || broken) { if (markIt) item.setAttribute('data-due-moved', today); return; }
      var holder = null;
      for (var c = item.lastElementChild; c; c = c.previousElementSibling) {
        if (c.tagName === 'DIV' && !(c.classList && c.classList.contains('time'))) { holder = c; break; }
      }
      var chipsEl = null;
      Array.prototype.forEach.call(item.querySelectorAll('div'), function (dv) {
        if (!chipsEl && dv.attributes.length && dv.attributes[0].name === 'class' && dv.attributes[0].value === 'chips') chipsEl = dv;
      });
      var hasChip = Array.prototype.some.call(item.querySelectorAll('span.chip:not(.js-auto)'), function (sp) {
        return sp.classList.contains('done') || sp.classList.contains('active') || sp.classList.contains('pending') || sp.classList.contains('hold');
      });
      if (!hasChip && !chipsEl && !holder) { if (markIt) item.setAttribute('data-due-moved', today); return; }   // 未を置けない（Deck も印だけ）
      var oldTime = null;
      if (times.length === 1) {
        oldTime = (times[0].getAttribute('data-orig') || tbTimeText(times[0])).trim();   // 鍵と同じ読み方（Deck の _time_text・v2.15）
        times[0].parentNode.removeChild(times[0]);
        var hm = /^(\d{1,2}):(\d{2})$/.exec(oldTime);
        if (hm && +hm[1] <= 23 && +hm[2] <= 59) when = (+hm[1]) + ':' + hm[2];   // 範囲外の時刻の欄は使わない（Deck の _valid_hm）
      }
      if (!hasChip) {
        if (!chipsEl) {
          chipsEl = document.createElement('div');
          chipsEl.className = 'chips';
          holder.appendChild(chipsEl);
        }
        var chip = document.createElement('span');
        chip.className = 'chip pending';
        chip.textContent = '未';
        chipsEl.appendChild(chip);
      }
      var scheduled = when !== null && dueDay === today && toSec === '今日の予定';
      item.classList.toggle('flat', !scheduled);
      // 実施日を今日にし（時刻の欄を付けるならその時刻を含め、付けないなら日付だけ）、元の実施日を data-due-from に残す（Deck v2.11。
      // 時刻は行の時刻〔時刻の欄が H:MM ならそれ、無ければ実施日の時刻〕・Deck v2.12）。先の日の行も今日の行として扱い、同じく
      // 今日にして印を付ける（時刻は付かない＝scheduled は実施日が今日のときだけ。Deck v2.13・2026-11-06 ユーザー決定）
      item.setAttribute('data-due', today + (scheduled ? ' ' + when : ''));
      if (!item.hasAttribute('data-due-moved')) item.setAttribute('data-due-moved', today);
      if (!item.hasAttribute('data-due-from')) item.setAttribute('data-due-from', dueDay + (when !== null ? ' ' + when : ''));
      if (scheduled) {
        var t = document.createElement('div');
        t.className = 'time';
        t.textContent = when;
        t.setAttribute('data-orig', when);   // ✎ の表示（renderTimes）は data-orig を元の時刻として読む
        item.insertBefore(t, item.firstChild);
        if (tbBindTimeEl) tbBindTimeEl(t);    // ✎ のクリックを結ぶ（読み直しを待たせない）
      }
    }

    // ---- 今日の側から「明日以降」へ動かす行の実施日（Deck v2.13 の _later_due_shape と同じ形・2026-11-06 ユーザー決定） ----
    // 実施日は利用者が決める（日付〔時刻は任意〕か未定＝null）。印（data-due-moved）と元の実施日（data-due-from）は外す（その日に
    // Deck が今日の側へ移す）。行の時刻は1つ: 時刻の欄が1つある行は、実施日に時刻があれば時刻の欄をその時刻にし、無ければ外す。
    // 時刻の欄の無い行には足さない。未定は時刻の欄を変えない。画面の DOM だけを直す（HTML 正本は Deck が同じ形に書く）。
    // 中に行の部品がある時刻の欄（tbTimeHasPart。閉じタグの無い欄など）が1つある行に日付を当てる形は作れない（Deck の _later_due_shape も
    // None を返し、D&D の反映は 400 になる）ので、その行は変えずに false を返す（未定は Deck も時刻の欄に触れないので当てる）。
    // 残る時刻の欄は ✎ の上書きを外して元の時刻を出す（「明日以降」の行は ✎ を受けない＝renderTimes と同じ。✎ の跡の overridden を
    // 残さない）
    function laterDueBlocked(item) {
      var times = item.querySelectorAll('.time');
      return times.length === 1 && tbTimeHasPart(times[0]);
    }
    function setLaterDue(item, due) {
      if (due !== null && laterDueBlocked(item)) return false;
      ['data-due', 'data-due-moved', 'data-due-from'].forEach(function (a) { item.removeAttribute(a); });
      var times = item.querySelectorAll('.time');
      if (due !== null) item.setAttribute('data-due', due);
      if (times.length === 1 && !tbTimeHasPart(times[0])) {
        var hm = due !== null ? / (\d{1,2}:\d{2})$/.exec(due) : null;
        if (due !== null && !hm) {
          times[0].parentNode.removeChild(times[0]);
        } else {
          var shown = hm ? hm[1] : times[0].getAttribute('data-orig');
          if (shown !== null) times[0].textContent = shown;
          if (hm) times[0].setAttribute('data-orig', hm[1]);
          times[0].classList.remove('overridden');
        }
      }
      item.classList.toggle('flat', !item.querySelector('.time'));
      return true;
    }
    function hmOf(text) {
      var m = /^(\d{1,2}):(\d{2})$/.exec((text || '').trim());
      return m && +m[1] <= 23 && +m[2] <= 59 ? (+m[1]) + ':' + m[2] : '';
    }
    // 実施日を聞く。決めたら done("YYYY-MM-DD" か "YYYY-MM-DD H:MM" か null＝未定)、やめたら呼ばない。
    // 初めの値: 元の予定（data-due-from）が明日以後ならその日時、時刻はそれが無ければ行の時刻の欄（H:MM）
    function askLaterDue(item, done) {
      var now = new Date();
      var today = dueISO(now);
      var tomorrow = dueISO(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
      var g = /^(\d{4}-\d{2}-\d{2})(?: (\d{1,2}:\d{2}))?$/.exec(item.getAttribute('data-due-from') || '');
      var plan = g && g[1] > today ? g : null;
      var tEl = item.querySelector('.time');
      var tm = (plan && plan[2]) || (tEl ? hmOf(tEl.getAttribute('data-orig') || tbTimeText(tEl)) : '');
      var title = item.querySelector('.task-title');
      var dlg = document.createElement('dialog');
      dlg.className = 'later-due';
      dlg.style.cssText = 'border:1px solid #999;border-radius:8px;padding:14px 16px;font:inherit;max-width:22em';
      var head = document.createElement('p');
      head.style.cssText = 'margin:0 0 8px;font-weight:bold';
      head.textContent = '「' + (title ? title.textContent : '') + '」を明日以降へ';
      var row = document.createElement('p');
      row.style.cssText = 'margin:0 0 6px';
      var d = document.createElement('input');
      d.type = 'date'; d.min = tomorrow; d.value = plan ? plan[1] : '';
      d.setAttribute('aria-label', '実施日');
      var t = document.createElement('input');
      t.type = 'time'; t.value = tm ? ('0' + tm).slice(-5) : '';
      t.setAttribute('aria-label', '時刻（任意）');
      var dl = document.createElement('label'); dl.textContent = '実施日 '; dl.appendChild(d);
      var tl = document.createElement('label'); tl.textContent = ' 時刻（任意） '; tl.appendChild(t);
      row.appendChild(dl); row.appendChild(tl);
      var msg = document.createElement('p');
      msg.className = 'later-due-msg';
      msg.style.cssText = 'margin:0 0 8px;min-height:1.2em;color:#c00;font-size:90%';
      var btns = document.createElement('p');
      btns.style.cssText = 'margin:0;display:flex;gap:6px;flex-wrap:wrap';
      function button(label, cls) {
        var b = document.createElement('button');
        b.type = 'button'; b.className = cls; b.textContent = label;
        btns.appendChild(b);
        return b;
      }
      var ok = button('この日にする', 'later-due-ok');
      var none = button('未定にする', 'later-due-none');
      var cancel = button('やめる', 'later-due-cancel');
      var blocked = laterDueBlocked(item);
      if (blocked) {
        // 閉じタグの無い時刻の欄の行は、日付を決めて移せない（Deck も断る）。未定とやめるは使える
        d.disabled = true; t.disabled = true; ok.disabled = true;
        msg.textContent = 'この行は時刻の欄の形が崩れているため、日付を決めて移せません。「未定にする」で移すか、行を直すよう Claude に伝えてください';
      }
      dlg.appendChild(head); dlg.appendChild(row); dlg.appendChild(msg); dlg.appendChild(btns);
      var closed = false;
      function finish(due) {
        if (closed) return;
        closed = true;
        if (dlg.open && dlg.close) dlg.close();
        if (dlg.parentNode) dlg.parentNode.removeChild(dlg);
        if (due !== undefined) done(due);
      }
      ok.addEventListener('click', function () {
        if (blocked) return;
        if (TB_LIVE.live && tbDayOf(new Date()) !== TB_LOAD_DAY) { finish(); tbDayStop(true); return; }   // 開いたまま日付が変わった（送らずに読み直す）
        if (!/^\d{4}-\d{2}-\d{2}$/.test(d.value) || d.value <= today) {
          msg.textContent = '明日以後の日付を入れてください（決まっていなければ「未定にする」）';
          d.focus();
          return;
        }
        var hm = hmOf(t.value);
        if (t.value && !hm) { msg.textContent = '時刻を読めません'; t.focus(); return; }
        finish(d.value + (hm ? ' ' + hm : ''));
      });
      none.addEventListener('click', function () {
        if (TB_LIVE.live && tbDayOf(new Date()) !== TB_LOAD_DAY) { finish(); tbDayStop(true); return; }
        finish(null);
      });
      cancel.addEventListener('click', function () { finish(); });
      dlg.addEventListener('cancel', function (e) { e.preventDefault(); finish(); });   // Esc はやめると同じ
      document.body.appendChild(dlg);
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
      (blocked ? none : plan ? ok : d).focus();
    }

    // ---- 移動の再適用（記録順にリプレイ） ----
    function replayMoves() {
      readJSON('mv:' + dateKey, []).forEach(function (m) {
        var item = findItemByKey(m.k);
        if (!item) return;
        var g = findGroup(getGroups(), m.sec);
        if (!g) return;
        var fromSec = sectionOf(item);
        if (fromSec === '明日以降' && m.sec !== '明日以降') shapeDueMove(item, m.sec);
        // 当てられない形の行（setLaterDue が false）は動かさない（Deck も 400 で動かさない）
        if ((fromSec === '今日の予定' || fromSec === '今日中') && m.sec === '明日以降' && m.due !== undefined
          && setLaterDue(item, m.due) === false) return;
        var label = g.nodes[0], parent = label.parentNode;
        if (m.head) { parent.insertBefore(item, label.nextSibling); return; }
        var target = null;
        if (m.before) {
          groupItems(g).forEach(function (it) { if (!target && key(it) === m.before) target = it; });
        }
        if (target) parent.insertBefore(item, target);
        else {
          var last = g.nodes[g.nodes.length - 1];
          parent.insertBefore(item, last.nextSibling);
        }
      });
    }

    // ---- セクション表示順 ----
    function applyOrder() {
      var saved = readJSON('secOrder', null);
      if (!saved) return;
      var groups = getGroups();
      if (groups.length < 2) return;
      var parent = groups[0].nodes[0].parentNode;
      var ref = document.createComment('sec-order-ref');
      parent.insertBefore(ref, groups[0].nodes[0]);
      var orig = groups.slice();
      // 設定UIに載らないセクション（Deckが出す常駐の状態など）は保存順に現れないため、
      // 従来は問答無用で末尾へ飛ばされていた。原文でその直後にある既知セクションの
      // 「すぐ手前」に固定して、元の並びを保つ。後から増えるセクションにも効く。
      function idx(g) {
        var oi = orig.indexOf(g);
        var i = saved.indexOf(g.name);
        if (i >= 0) return { a: i, b: 0, c: oi };
        for (var k = oi + 1; k < orig.length; k++) {
          var j = saved.indexOf(orig[k].name);
          if (j >= 0) return { a: j, b: -1, c: oi };
        }
        return { a: saved.length, b: 0, c: oi };
      }
      groups.sort(function (x, y) {
        var p = idx(x), q = idx(y);
        return (p.a - q.a) || (p.b - q.b) || (p.c - q.c);
      });
      groups.forEach(function (g) {
        g.nodes.forEach(function (n) { parent.insertBefore(n, ref); });
      });
      parent.removeChild(ref);
    }
    function renderOrderUI() {
      var panel = document.getElementById('settings-panel');
      if (!panel) return;
      var host = document.getElementById('sec-order-rows');
      if (!host) {
        var row = document.createElement('div');
        row.className = 'set-row';
        row.innerHTML = '<span>セクション表示順</span><span id="sec-order-rows" class="order-ctl"></span>';
        panel.insertBefore(row, panel.querySelector('.set-note:not(#sound-note)') || null);
        host = row.querySelector('#sec-order-rows');
      }
      // 既知セクションに限定しない。Deckが出すセクション（監視ねこ等）も
      // 並び替えの対象にする。特定の名前を board.js に埋め込まずに済ませるため、
      // 文書に実在するセクションをそのまま並べる。
      var order = getGroups().map(function (g) { return g.name; });
      host.innerHTML = '';
      order.forEach(function (name, i) {
        var el = document.createElement('span');
        el.className = 'order-item';
        var up = document.createElement('button'); up.type = 'button'; up.textContent = '↑'; up.disabled = i === 0;
        var dn = document.createElement('button'); dn.type = 'button'; dn.textContent = '↓'; dn.disabled = i === order.length - 1;
        function move(d) {
          var o = order.slice();
          var t = o[i]; o[i] = o[i + d]; o[i + d] = t;
          LS.set('secOrder', JSON.stringify(o));
          applyOrder(); refreshMarks(); renderOrderUI();
        }
        up.addEventListener('click', function () { move(-1); });
        dn.addEventListener('click', function () { move(1); });
        el.appendChild(up); el.appendChild(dn);
        el.appendChild(document.createTextNode(' ' + name));
        host.appendChild(el);
      });
    }

    // ---- D&D ----
    var dragged = null;
    function ensureTails() {
      getGroups().forEach(function (g) {
        if (MOVABLE.indexOf(g.name) < 0) return;
        var hasTail = g.nodes.some(function (n) { return n.nodeType === 1 && n.classList && n.classList.contains('sec-drop-tail'); });
        if (hasTail) return;
        var tail = document.createElement('div');
        tail.className = 'sec-drop-tail';
        var last = g.nodes[g.nodes.length - 1];
        last.parentNode.insertBefore(tail, last.nextSibling);
      });
    }
    function refreshMarks() {
      Array.prototype.forEach.call(document.querySelectorAll('[data-sec]'), function (n) { n.removeAttribute('data-sec'); });
      getGroups().forEach(function (g) {
        if (MOVABLE.indexOf(g.name) < 0) return;
        g.nodes.forEach(function (n) {
          if (n.nodeType !== 1 || !n.classList) return;
          if (n.classList.contains('section-label') || n.classList.contains('item') || n.classList.contains('sec-drop-tail')) {
            n.setAttribute('data-sec', g.name);
          }
        });
        groupItems(g).forEach(function (it) {
          if (TB_CUT) return;   // 切れた画面では動かせるようにしない（TB_CUT・2026-11-10）
          if (it.getAttribute('draggable') === 'true') return;
          it.setAttribute('draggable', 'true');
          it.classList.add('draggable');
          it.addEventListener('dragstart', function (e) {
            dragged = it;
            it.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            try { e.dataTransfer.setData('text/plain', key(it)); } catch (err) {}
          });
          it.addEventListener('dragend', function () {
            it.classList.remove('dragging');
            clearHints();
            dragged = null;
          });
        });
      });
    }
    function clearHints() {
      Array.prototype.forEach.call(document.querySelectorAll('.drop-before, .drop-hint'), function (n) {
        n.classList.remove('drop-before', 'drop-hint');
      });
    }
    document.addEventListener('dragover', function (e) {
      if (!dragged) return;
      var t = e.target && e.target.closest ? e.target.closest('[data-sec]') : null;
      clearHints();
      if (!t) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      t.classList.add(t.classList.contains('item') ? 'drop-before' : 'drop-hint');
    });
    document.addEventListener('drop', function (e) {
      if (!dragged) return;
      var t = e.target && e.target.closest ? e.target.closest('[data-sec]') : null;
      if (!t) return;
      e.preventDefault();
      var it = dragged;
      if (t === it) { clearHints(); return; }
      var rec = { k: key(it), sec: t.getAttribute('data-sec'), before: null };
      var fromSec = sectionOf(it);
      var fromLater = fromSec === '明日以降';
      if (TB_LIVE.live && tbDayChanged()) { clearHints(); tbDayStop(true); return; }   // 開いたまま日付が変わった（動かさずに止める）
      function place() {
        var parent = t.parentNode;
        if (t.classList.contains('item')) {
          parent.insertBefore(it, t);
          rec.before = key(t);
        } else if (t.classList.contains('section-label')) {
          parent.insertBefore(it, t.nextSibling);
          rec.head = true;
        } else {
          parent.insertBefore(it, t);
        }
      }
      // 今日の側から「明日以降」へ落とした行は、実施日（日付か未定）を聞いてから動かす。やめたら動かさない
      // （2026-11-06 ユーザー決定・Deck v2.13。rec.due を Deck の D&D の反映と localStorage の再適用が使う）
      if (rec.sec === '明日以降' && (fromSec === '今日の予定' || fromSec === '今日中')) {
        clearHints();
        askLaterDue(it, function (due) {
          // 聞いている間に画面が組み替わった（自動の読み直しは入力欄を閉じるまで延ばす＝tbReload ので、ふつうは起きない）
          if (!it.isConnected || !t.isConnected) return;
          if (due !== null && laterDueBlocked(it)) return;   // 当てられない形の行（入力欄で日付を選べないので、ふつうは来ない）
          place();
          rec.due = due;
          setLaterDue(it, due);
          persistMove(rec);
          refreshMarks(); recalc();
          document.dispatchEvent(new Event('drop'));   // 済の隠し・表示の整え（drop を待つ他の処理）を動かす
        });
        return;
      }
      place();
      // 実施日の来た行は Deck と同じ形にする（rec.k は形を変える前の key＝Deck・localStorage の再適用が探す key）
      if (fromLater && rec.sec !== '明日以降') shapeDueMove(it, rec.sec);
      persistMove(rec);
      clearHints(); refreshMarks(); recalc();
    });
    // Deck常駐時（127.0.0.1 の受信ポート・board.html の接続情報を deckFetch が使う）はHTML正本へ自動反映し、localStorageには保存しない。
    // Deck未対応・停止中・タイムアウト・別のボードの Deck だけが応答した時は従来どおりlocalStorage保存にフォールバック。
    // 例外は、今日のボードとして読み込んだまま日付が変わったページ（2026-11-06）: Deck へも localStorage へも残さずに読み直す（persistMove の tbDayStop）。
    // Deck が応答したのに保存できなかった（200 以外）ときと、待つのをやめた（タイムアウト）ときは、画面に知らせる
    // （2026-10-30 ユーザー判断。それまでは黙って localStorage に逃がしていた）。Deck に接続できない（止まっている）ときは
    // 知らせない——監視ねこの行が Deck の停止を出す。Deck v2.6 は D&D を受けてから 1 秒以内に書けなければ書かないので、
    // タイムアウト（deckFetch の 1.5 秒）の後に Deck が書くことは無い（v2.5 以前の Deck では起こりうる）
    // 失敗が続いても知らせは1件にまとめる（既に出ていれば積まずに出し直し、30秒で消える設定なら時計を延ばす）
    var moveFailEl = null, moveFailTimer = null;
    function moveSaveFailed() {
      var area = document.getElementById('toast-area');
      if (!area) return;
      var el = moveFailEl;
      if (!el || !el.parentNode) {
        el = document.createElement('div');
        el.className = 'toast';
        el.textContent = '移動を保存できませんでした。このブラウザの表示にだけ残り、ボードのファイルには入っていません。もう一度動かしてください。何度やっても出るときは、動かした項目と行き先を Claude に伝えてください';
        el.addEventListener('click', function () { if (el.parentNode) el.remove(); });
        moveFailEl = el;
      }
      area.appendChild(el);   // 既にあれば末尾へ移して出し直す
      if (moveFailTimer) { clearTimeout(moveFailTimer); moveFailTimer = null; }
      if (LS.get('toastMode', 'stay') === 'auto') {
        moveFailTimer = setTimeout(function () { if (el.parentNode) el.remove(); }, 30000);
      }
    }
    // 崩れた板で Deck が移動を断った（409・reason "board-broken"・Deck v2.18）。画面の移動はどこにも残さず、読み直して元の位置へ戻し、
    // 読み直した後に理由を出す（sessionStorage の印。このタブの次の読み込みだけが見る）
    var MOVE_BROKEN_KEY = 'tb-move-broken';
    var MOVE_BROKEN_MSG = 'ボードの形が崩れているため、移動をボードのファイルに書きませんでした（画面は元の位置に戻しました）。'
      + 'Claude に「ボードを直して」と頼んでください';
    function moveBoardBroken() {
      try { sessionStorage.setItem(MOVE_BROKEN_KEY, '1'); } catch (err) {}
      location.reload();
    }
    function moveBrokenNotice() {
      var flag = null;
      try { flag = sessionStorage.getItem(MOVE_BROKEN_KEY); sessionStorage.removeItem(MOVE_BROKEN_KEY); } catch (err) {}
      var area = document.getElementById('toast-area');
      if (!flag || !area) return;
      var el = document.createElement('div');
      el.className = 'toast';
      el.id = 'tb-move-broken';
      el.textContent = MOVE_BROKEN_MSG;
      el.addEventListener('click', function () { if (el.parentNode) el.remove(); });
      area.appendChild(el);
      if (LS.get('toastMode', 'stay') === 'auto') setTimeout(function () { if (el.parentNode) el.remove(); }, 30000);
    }
    function persistMove(rec) {
      function persistLocal() {
        var arr = readJSON('mv:' + dateKey, []);
        arr.push(rec);
        LS.set('mv:' + dateKey, JSON.stringify(arr));
      }
      // 発行前のテンプレ・過去日のコピーからは HTML 正本を書き換えない（2026-08-05 新設）。
      // ここは deckPost を通らない独立した書き込み経路なので、同じ判定を明示的に置く。
      // localStorage 側の保存はブラウザ内で完結するので残す（画面上の移動は従来どおり効く）。
      if (!TB_LIVE.live) { tbBlockWrite('/board/move'); persistLocal(); return; }
      if (TB_CUT) { console.info('[today-board] 書き込みをブロック: /board/move（切れた画面）'); return; }   // 2026-11-10。refreshMarks で動かせないが念のため
      if (tbDayStop(true)) return;   // 開いたまま日付が変わった（Deck へも localStorage へも残さずに読み直す）
      var p = deckFetch('/board/move', { method: 'POST', body: JSON.stringify(rec) });
      if (!p) { persistLocal(); return; }
      p.then(function (res) {
        if (res && res.status === 409) {
          // 崩れた板（Deck v2.18 の reason "board-broken"）は、理由を出して、移動をどこにも残さずに元の位置へ戻す（読み直す）。
          // それ以外の 409（ほかの書き手と重なって書けなかった）は従来どおり
          return res.json().then(function (j) {
            if (j && j.reason === 'board-broken') { moveBoardBroken(); return; }
            persistLocal(); moveSaveFailed();
          }, function () { persistLocal(); moveSaveFailed(); });
        }
        if (!res || !res.ok) { persistLocal(); moveSaveFailed(); }
      }).catch(function (err) {
        persistLocal();
        if (err && err.name === 'AbortError') moveSaveFailed();   // タイムアウト（Deck が 1.5 秒以内に答えなかった）
      });
    }

    replayMoves();
    applyOrder();
    ensureTails();
    refreshMarks();
    renderOrderUI();
    recalc();
    moveBrokenNotice();
  })();
