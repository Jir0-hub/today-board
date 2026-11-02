  setTimeout(function () { location.reload(); }, 300000);

  // ---- 発行済みボード判定（Deck への書き込みガード・2026-08-05 新設） ----
  // スキルのテンプレ（board-template.html）やアーカイブのコピーをブラウザで開くと、
  // そのブラウザ／オリジンの localStorage の値が Deck へ送られ、本番の通知音設定（deck/sound.json）と
  // 時刻上書きを上書きしてしまった（通知音は 2026-11-02 から⚙を操作したときだけ送る。✎ の時刻は
  // 今日の記録があれば起動時にも送る。⚙の操作も含めて書き込みを止めるので、この判定は要る）。
  // 2026-08-05 実測: テンプレを開いた直後に watcher.log へ「通知音設定: 有効=OFF」が記録され、
  // 次の本番タブの push（5分周期）まで通知音が黙った（11:31:51→11:33:03・11:43:37→11:48:03）。
  // D&D 移動の POST /board/move に至っては HTML 正本そのものを書き換える。
  // そこで「実際に発行されたボードとして開かれたときだけ書き込む」判定をここで一度だけ行い、
  // 書き込み系の共通出口（deckPost と persistMove の fetch）でまとめてガードする。
  // 呼び出し側ごとに条件を置くと、書き込み経路が増えたときに必ず漏れるため1か所に集約する。
  // 読み取り系（GET /notifications ＝ Deck の生死判定・GET /sound/config ＝⚙の表示）はガードしない。
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

  // ---- Deck の受信ポート・トークンと、どのボードからの要求かの申告（Deck v2.1 対応・2026-10-23） ----
  // ※この節（DECK_BOARD・DECK_KEY・deckReloadOnce・DECK_STALE_STUCK・deckReloadStale・deckFetch）は
  //   トップレベルに置く。
  //   使い手が2つの IIFE にまたがる（自動機能の deckPost・監視ねこ と、D&D 移動の persistMove）。
  //   v2.1 で persistMove の fetch を deckFetch に置き換えた際、deckFetch が自動機能の IIFE の
  //   中にあったため D&D 側から見えず、ドロップのたびに ReferenceError で移動が保存されなかった
  //   （2026-10-25 修正）。IIFE の外で定義された名前を IIFE の中から使うのは、ここと
  //   TB_LIVE・tbBlockWrite だけにする。
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
    location.reload();
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
    return p.then(function (res) {
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
      return m ? (+m[1]) * 60 + (+m[2]) : null;
    }
    function fmtHM(mins) { return Math.floor(mins / 60) + ':' + ('0' + (mins % 60)).slice(-2); }
    function taskKey(item) {
      var t = item.querySelector('.time');
      var ti = item.querySelector('.task-title');
      return ((t ? (t.getAttribute('data-orig') || t.textContent) : '') + '|' + (ti ? ti.textContent : '')).trim();
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
      if (soundBusy || !TB_LIVE.live) return;
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
    // ✎ の時刻上書きは localStorage にしかなく Deck からは見えない。送らないと Deck は
    // HTML 側の元の時刻で鳴り、トーストは上書き後の時刻で出るのでズレる。
    // キー＝taskKey（data-orig の元時刻 + '|' + タイトル）／値＝上書き後の表示時刻。
    // Deck はこの元キーで HTML の item と突き合わせる。差分ではなく毎回まるごと送るので、
    // 上書きを外したときもキーの消えた地図が届いて自然に元の時刻へ戻る。
    function pushTimeOverrides() {
      deckPost('/board/times', { ovr: readJSON('ovr:' + dateKey, {}) });
    }

    // ---- ポップアップ（③）: 発火判定は Deck、描画はここ ----
    // 既定は「触るまで残す」。サブモニタに置いて放置する運用では、自動で消えると
    // 見逃したまま気づけないため（2026-08-04 ユーザー決定。従来は一律30秒で自動消滅）。
    // ただしこのページは5分ごとに自動リロードされ、DOM ごとトーストが消える。そこで
    // 「まだユーザーが見ていない通知（未確認）」は Deck 側に持たせ、ここは3秒ごとに
    // 取りに行って描画するだけにした。リロードしても未確認分は復元される。
    // ユーザーがトーストを閉じたら ack して Deck の未確認から外す。
    var shownKeys = {};  // このページで描画済みのキー（Deck 経路とローカル経路の二重表示を防ぐ）

    function ackNotifications(keys) {
      if (keys && keys.length) deckPost('/notifications/ack', { keys: keys });
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
    //   ※CORS ヘッダの無い応答は fetch 自体が失敗するので down（停止）に入る
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
        if (!data.items) return;
        data.items.forEach(function (it) {
          showNotification(it.key, '⏰ ' + it.time + ' ' + it.title);
        });
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
        stale: DECK_STALE_STUCK
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
    var NOTICE_IS_FILE = String(location.protocol) === 'file:';  // file: 以外＝artifact など（Deck に届かない）

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
          location.reload();
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
    var NOTICE_BLOCKED = '通知音の設定・✎ の時刻の変更・通知の確認・ドラッグでの移動は Deck に届かず、'
      + 'この画面の中だけの変更になります。';
    var NOTICE_ASK = 'Claude に「今日のボードを作って」と頼むと直ります。';
    function renderBoardNotice() {
      if (TB_LIVE.live) {
        // 今日の板。Deck が日付の切り替えで作った板（.board の data-tb-rolled）なら、引き継いだことを知らせる
        var board = document.querySelector('.board');
        var from = board ? (board.getAttribute('data-tb-rolled') || '') : '';
        var fm = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(from);
        if (!fm) { setNotice(null); return; }
        var fd = new Date(+fm[1], +fm[2] - 1, +fm[3]);
        var n = document.querySelectorAll('.item[data-carried-from]:not([data-sid])').length;
        setNotice('info', '↪', '引き継いだボード',
          noticeMD(fd) + 'のボードから、終わっていないタスク' + (n ? n + '件' : '')
          + 'を引き継いで、Deck が作ったボードです。今日の予定はまだ決めていません。',
          '今日の予定は、Claude に「今日の予定を決めよう」と頼むと整えられます。');
        return;
      }
      var k = tbBoardKind();
      var today = noticeToday();
      var label = '書き込み停止中';
      if (k.kind === 'template') {
        setNotice('muted', '⚠', label, 'これは発行前のテンプレートです。ボードは Claude が作ります。'
          + (NOTICE_IS_FILE ? 'この画面での操作は Deck に届きません。' : ''),
          'Claude に「今日のボードを作って」と頼んでください。');
        return;
      }
      if (k.kind === 'unreadable') {
        setNotice('warn', '⚠', label, 'ヘッダの日付「' + k.text + '」を日付として読み取れません。日付は「'
          + noticeISO(today) + '（' + NOTICE_WD.charAt(today.getDay()) + '）」の形で書く決まりです。'
          + (NOTICE_IS_FILE ? '今日のボードと確かめられないため、' + NOTICE_BLOCKED : ''),
          'Claude に「今日のボードを作り直して」と頼んでください。');
        return;
      }
      if (k.kind === 'future') {
        setNotice('warn', '⚠', label, 'ボードの日付が' + noticeMD(k.date) + 'になっていて、今日の' + noticeMD(today)
          + 'より先です。' + (NOTICE_IS_FILE ? '今日のボードと確かめられないため、' + NOTICE_BLOCKED : ''),
          'PC の時計か、ボードの日付の書き方を確かめてください。');
        return;
      }
      if (k.kind === 'other') {
        setNotice('warn', '⚠', label, '今日のボードと確かめられません（' + TB_LIVE.why + '）。'
          + (NOTICE_IS_FILE ? NOTICE_BLOCKED : ''), NOTICE_ASK);
        return;
      }
      // past: 過去の日付
      var head = 'このボードは' + noticeMD(k.date) + 'のものです。今日は' + noticeMD(today) + 'です。';
      if (!NOTICE_IS_FILE) {
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
      var msgs = [];
      var nested = 0;
      Array.prototype.forEach.call(document.querySelectorAll('.item .item'), function (it) {
        if (!(it.closest && it.closest('[data-sid]'))) nested++;
      });
      if (nested) {
        msgs.push('タスクの中に別のタスクが入り込んでいます（入り込んでいるタスク ' + nested + ' 件）。'
          + 'そこから先のタスクは、通知音・ドラッグでの移動・進捗の数え方から外れることがあります。');
      }
      if (NOTICE_IS_FILE && !hasDeckMarkers()) {
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
      if (!msgs.length) return;
      var el = document.createElement('div');
      el.id = 'tb-board-check';
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
      fx.textContent = 'Claude に「ボードを直して」と頼んでください。';
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
      if (ms > 0 && ms <= 300000) setTimeout(function () { location.reload(); }, ms);
    })();

    // ---- 時刻トリガー到達の検知（③）: 発火済みはlocalStorageで記憶（リロード耐性） ----
    function checkAlarms(nowMin) {
      var fired = readJSON('fired:' + dateKey, []);
      var changed = false;
      Array.prototype.forEach.call(document.querySelectorAll('.item'), function (item) {
        var timeEl = item.querySelector('.time');
        if (!timeEl || item.classList.contains('done-item') || item.querySelector('.chip.done')) return;
        var t = parseHM(timeEl.textContent);
        if (t === null) return;
        // 発火済みキーは「実効時刻|タイトル」で持つ（Deck の read_board_alarms と同一定義）。
        // taskKey は data-orig ＝元の時刻を使うため、時刻を変更しても同じキーのままになり、
        // 変更前に発火済みとして記録された項目が新しい時刻でトーストを出せない。
        // 2026-08-04、音は鳴るのにポップアップだけ出ない事象として実測された。
        var titleEl = item.querySelector('.task-title');
        var key = (timeEl.textContent.trim() + '|' + (titleEl ? titleEl.textContent : '')).trim();
        if (t <= nowMin && fired.indexOf(key) < 0) {
          fired.push(key); changed = true;
          if (nowMin - t <= 5) { // 開くのが遅れた過去分はまとめて出さない
            // 音はここでは鳴らさない（Deck が同じ条件で判定して鳴らす）。両方で鳴らすと
            // ページをクリック済みのときだけ二重に鳴る。
            // この判定は Deck の有無に関わらず常に走る。Deck 稼働中は Deck 経由（3秒周期）が
            // 先に描画することが多いが、同じキーなら showNotification が弾くので二重には出ない。
            showNotification(key, '⏰ ' + timeEl.textContent.replace(' ✎', '') + ' ' + (titleEl ? titleEl.textContent : ''));
          }
        }
      });
      if (changed) LS.set('fired:' + dateKey, JSON.stringify(fired));
    }

    // ---- 時刻の手動変更（④）: localStorageに日付単位で保存・✎印 ----
    function renderTimes() {
      var ovr = readJSON('ovr:' + dateKey, {});
      Array.prototype.forEach.call(document.querySelectorAll('.item .time'), function (timeEl) {
        if (timeEl.querySelector('input')) return;
        var item = timeEl.closest('.item');
        var v = ovr[taskKey(item)];
        timeEl.textContent = v || timeEl.getAttribute('data-orig');
        timeEl.classList.toggle('overridden', !!v);
      });
    }
    function makeTimesEditable() {
      Array.prototype.forEach.call(document.querySelectorAll('.item .time'), function (timeEl) {
        timeEl.setAttribute('data-orig', timeEl.textContent.trim());
        timeEl.style.cursor = 'pointer';
        timeEl.title = 'クリックで時刻を変更';
        timeEl.addEventListener('click', function (ev) {
          ev.stopPropagation();
          if (timeEl.querySelector('input')) return;
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
            if (v) {
              var ovr = readJSON('ovr:' + dateKey, {});
              var key = taskKey(item);
              var disp = fmtHM(parseHM(v));
              if (disp === timeEl.getAttribute('data-orig')) delete ovr[key];
              else ovr[key] = disp;
              LS.set('ovr:' + dateKey, JSON.stringify(ovr));
              pushTimeOverrides();  // Deck も新しい時刻で鳴るようにする
            }
            renderTimes(); refresh();
          }
          // change では確定しない。type="time" は既存値が入っているため、時の桁を
          // 1つ打った時点で値が妥当になり change が発火してしまい、分まで入力できない
          // （2026-08-04 ユーザー報告）。確定は Enter と、入力欄を離れたときだけにする。
          inp.title = 'Enter か、他の場所をクリックで確定';
          inp.addEventListener('blur', commit);
          inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') commit(); });
        });
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

      // Deck が日付の切り替えで引き継いだタスク（data-carried-from）に、元の日付と元の予定時刻を出す
      // （Deck v2.2。時刻付きの予定は今日中へ移すので、元の時刻はここでしか見えない）
      Array.prototype.forEach.call(document.querySelectorAll('.item[data-carried-from]:not([data-sid])'), function (item) {
        var f = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(item.getAttribute('data-carried-from') || '');
        if (!f) return;
        var ot = (item.getAttribute('data-orig-time') || '').trim();
        addChip(item, 'pending', '↪ ' + (+f[2]) + '/' + (+f[3]) + (ot ? ' ' + ot + ' の予定' : '') + 'から', false);
      });

      var next = null;
      Array.prototype.forEach.call(document.querySelectorAll('.item'), function (item) {
        if (item.classList.contains('done-item') || item.querySelector('.chip.done')) return;
        var timeEl = item.querySelector('.time');
        if (!timeEl) return;
        var t = parseHM(timeEl.textContent);
        if (t === null) {
          // 時刻の欄が H:MM として読めない（「9時」等）と、通知音・ポップアップ・時刻超過が黙って
          // 発火しないので、その項目に知らせる。✎ で編集中（入力欄がある）ときは除く
          if (timeEl.textContent.trim() && !timeEl.querySelector('input')) {
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
      checkAlarms(nowMin);
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
    // （deckPost / soundOperate / pushTimeOverrides / persistMove を呼ばない）。
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
      // 発行済みの板の説明文は日付の切り替えでも引き継がれるので、表示のときに今の文へ直す（HTML の正本は変えない）
      var sDesc = panel && panel.querySelector('.set-note:not(#sound-note)');
      if (sDesc && sDesc.textContent.indexOf('通知音の設定は Deck に保存され') < 0) {
        sDesc.textContent = sDesc.textContent.replace('設定はこのブラウザに保存されます。',
          '通知音の設定は Deck に保存され、どのブラウザで開いても同じです（Deck が動いていないときは変更できません）。それ以外の設定はこのブラウザに保存されます。');
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
      // 時刻の上書きは、このブラウザに今日の記録があるときだけ起動時にも送る。Deck 側だけ再起動した場合や、
      // Deck 停止中に変えた場合でも、次のリロード（5分以内）で揃う。上書きを全部外すと
      // `ovr:<日付>` は {} として残るので（✎ の処理）、空の地図が届いて Deck も元の時刻へ戻る。記録の無い
      // ブラウザが空の地図を送ると、ほかのブラウザで付けた上書きまで消してしまう。
      if (LS.get('ovr:' + dateKey, null) !== null) pushTimeOverrides();
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
      if (rBtn) rBtn.addEventListener('click', function () { location.reload(); });
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
    setInterval(refresh, 30000);
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
      return ((t ? (t.getAttribute('data-orig') || t.textContent) : '') + '|' + (ti ? ti.textContent : '')).trim();
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

    // ---- 移動の再適用（記録順にリプレイ） ----
    function replayMoves() {
      readJSON('mv:' + dateKey, []).forEach(function (m) {
        var item = findItemByKey(m.k);
        if (!item) return;
        var g = findGroup(getGroups(), m.sec);
        if (!g) return;
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
      var rec = { k: key(dragged), sec: t.getAttribute('data-sec'), before: null };
      var parent = t.parentNode;
      if (t.classList.contains('item')) {
        if (t === dragged) { clearHints(); return; }
        parent.insertBefore(dragged, t);
        rec.before = key(t);
      } else if (t.classList.contains('section-label')) {
        parent.insertBefore(dragged, t.nextSibling);
        rec.head = true;
      } else {
        parent.insertBefore(dragged, t);
      }
      persistMove(rec);
      clearHints(); refreshMarks(); recalc();
    });
    // Deck常駐時（127.0.0.1 の受信ポート・board.html の接続情報を deckFetch が使う）はHTML正本へ自動反映し、localStorageには保存しない。
    // Deck未対応・停止中・タイムアウト・別のボードの Deck だけが応答した時は従来どおりlocalStorage保存にフォールバック。
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
      var p = deckFetch('/board/move', { method: 'POST', body: JSON.stringify(rec) });
      if (!p) { persistLocal(); return; }
      p.then(function (res) {
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
  })();
