"""足し直しの経路（move で動かせない見出しのとき・restore の後）と、行き先の見出しが無い板での move --create-section の試験。

SKILL.md update モード 9 の「行き先の見出しが無い板」の手順（move --create-section）と、board_edit.py の move・restore の
エラー文／案内の文が指す手順を、サンドボックスの板で実際にたどる。チップ・重要タスク・実施日・印が写る（残る）ことを確かめる。
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_board_edit as tbe  # noqa: E402  （Sandbox と run を借りる。名前は取り込まない）


class TestReaddPaths(tbe.Sandbox):
    TODAY_LESS = {
        "sections": ["ルーチンタスク", "明日以降"],
        "items": [
            {"section": "ルーチンタスク", "title": "ログを更新する"},
            {"section": "明日以降", "title": "保留の件"},
            {"section": "明日以降", "title": "チップ無しの件"},
        ],
    }

    def ok(self, *args):
        rc, out = self.ed(*args)
        self.assertEqual(rc, 0, out)
        return out

    def by(self, title, section=None):
        hits = [i for i in self.items() if i["title"] == title and (section is None or i["section"] == section)]
        self.assertEqual(len(hits), 1, hits)
        return hits[0]

    def block(self, title):
        lines = self.text().splitlines(keepends=True)
        _secs, items = tbe.be.layout(lines)
        it = [x for x in items if tbe.be._element_text("".join(lines[x["s"]:x["e"] + 1]), "task-title") == title]
        self.assertEqual(len(it), 1)
        return "".join(lines[it[0]["s"]:it[0]["e"] + 1])

    def setUpTodayLess(self):
        self.create(self.TODAY_LESS)
        names = [s["name"] for s in self.status()["sections"]]
        self.assertNotIn("今日の予定", names)
        self.assertNotIn("今日中", names)
        today = date.today().isoformat()
        self.ok("set-due", "--item", "保留の件", "--due", today)
        self.ok("set-chip", "--item", "保留の件", "--chip", "hold")
        self.ok("set-crit", "--item", "保留の件", "on")
        self.ok("set-due", "--item", "チップ無しの件", "--due", today)
        due_now = [i["title"] for i in self.status()["due_now"]]
        self.assertEqual(sorted(due_now), ["チップ無しの件", "保留の件"])

    def test_move_without_create_section_names_the_flag(self):
        """行き先の見出しが無ければ、move は書かずに --create-section を案内する（足し直しの回り道は案内しない）。"""
        self.setUpTodayLess()
        before = self.read()
        for sec in ("今日中", "今日の予定"):
            rc, out = self.ed("move", "--item", "保留の件", "--section", sec)
            self.assertEqual(rc, 1, out)
            msg = out["error"]
            self.assertIn("行き先の見出し「%s」がありません" % sec, msg)
            self.assertIn("見出しごと作って動かすなら --create-section を付けてください", msg)
            self.assertNotIn("この版には見出しだけを作る操作がありません", msg)
            self.assertNotIn("remove で元の行を先に消し", msg)
            self.assertUnchanged(before)

    def test_move_create_section_keeps_chip_crit_due(self):
        """move --create-section は見出しを add --create-section と同じ位置に作り、チップ・重要タスクを残したまま、
        実施日の来た行を Deck の日付の切り替えと同じ形にする（未チップ・一度移した印）。"""
        self.setUpTodayLess()
        today = date.today().isoformat()
        out = self.ok("move", "--item", "保留の件", "--section", "今日中", "--create-section")
        self.assertTrue(out["created_section"])
        out = self.ok("move", "--item", "チップ無しの件", "--section", "今日中", "--create-section")
        self.assertFalse(out["created_section"])          # 2回目は見出しがあるので作らない
        it = self.by("保留の件")
        self.assertEqual((it["section"], it["chip"], it["crit"], it["due"], it["due_moved"]), ("今日中", "hold", True, today, today))
        it = self.by("チップ無しの件")
        self.assertEqual((it["section"], it["chip"], it["crit"], it["due"], it["due_moved"]),
                         ("今日中", "pending", False, today, today))
        names = [x["name"] for x in self.status()["sections"]]
        self.assertEqual(names, ["今日中", "ルーチンタスク", "明日以降"])
        moved_text = self.text()
        # 見出しの位置は add --create-section と同じ
        os.remove(self.board)
        self.setUpTodayLess()
        self.ok("add", "--section", "今日中", "--create-section", "--title", "比べる行")
        self.assertEqual([x["name"] for x in self.status()["sections"]], names)
        # 見出しの行は字下げまで add と同じで、ほかの見出しの字下げとも同じ。行の字下げも、ほかの行と同じ
        def label_line(text, name):
            return [ln for ln in text.splitlines() if '<div class="section-label">%s</div>' % name in ln]
        self.assertEqual(label_line(moved_text, "今日中"), label_line(self.text(), "今日中"))
        ind = lambda ln: ln[:len(ln) - len(ln.lstrip())]
        self.assertEqual(ind(label_line(moved_text, "今日中")[0]), ind(label_line(moved_text, "ルーチンタスク")[0]))
        item_open = lambda text, title: [ln for ln in text.splitlines()[:[i for i, l in enumerate(text.splitlines()) if title in l][0]]
                                         if '<div class="item' in ln][-1]
        self.assertEqual(ind(item_open(moved_text, "保留の件")), ind(item_open(self.text(), "比べる行")))
        st = self.status()
        self.assertEqual(st["errors"], [])

    def test_add_chip_none_stays_none_on_today_side(self):
        self.setUpTodayLess()
        self.ok("add", "--section", "今日中", "--create-section", "--title", "none のまま", "--chip", "none")
        self.assertEqual(self.by("none のまま")["chip"], "none")
        self.ok("add", "--section", "今日中", "--title", "省いた行")
        self.assertEqual(self.by("省いた行")["chip"], "pending")

    def test_update_mode9_path_without_heading_matches_deck(self):
        """update モード 9 の手順（見出しが無い板では move に --create-section）で移した形が、Deck の日付の切り替えと同じになる。"""
        self.setUpTodayLess()
        today = date.today()
        deck = {}
        for t in ("保留の件", "チップ無しの件"):
            blk = self.block(t)
            due = tbe.dw.parse_due_value(tbe.dw._item_open_attr(blk, "data-due"))
            new_block, dest = tbe.dw._move_due_block(blk, due, today, "\n")
            deck[t] = (dest, tbe.dw._element_text(new_block, "time"), "chip pending" in new_block, 'data-due-moved="%s"' % today.isoformat() in new_block)
        for t in ("チップ無しの件", "保留の件"):           # 下の行から移すと Deck と同じ並び
            self.ok("move", "--item", t, "--section", "今日中", "--head", "--create-section")
        mine = {}
        for t in ("保留の件", "チップ無しの件"):
            blk = self.block(t)
            mine[t] = (self.by(t)["section"], self.by(t)["time"], "chip pending" in blk, 'data-due-moved="%s"' % today.isoformat() in blk)
        self.assertEqual(mine, deck)
        self.assertEqual([i["title"] for i in self.status()["sections"][0]["items"]], ["保留の件", "チップ無しの件"])
        st = self.status()
        self.assertEqual(st["due_now"], [])
        self.assertEqual(st["errors"], [])

    def test_restore_then_readd_keeps_chip_none_and_crit(self):
        self.create()
        good = self.read()
        self.ok("add", "--section", "今日中", "--title", "後の行", "--chip", "none")
        self.ok("set-crit", "--item", "後の行", "on")
        h = os.path.join(self.dir, "history")
        os.makedirs(h, exist_ok=True)
        name = "board-%s-lastgood-120000.html" % date.today().isoformat()
        with open(os.path.join(h, name), "wb") as f:
            f.write(good)
        out = self.ok("restore", "--from", "history/" + name, "--confirmed")
        self.assertIn("chip が none でも --chip none で写す", out["message"])
        self.assertIn("crit が付いていた行は足した後に set-crit で付け直す", out["message"])
        row = [x for x in out["diff"]["only_now"] if x["title"] == "後の行"]
        self.assertEqual(len(row), 1)
        self.assertEqual((row[0]["chip"], row[0]["crit"]), ("none", True))
        self.assertNotIn("後の行", [i["title"] for i in self.items()])
        # only_now の chip と crit を写して足し直す
        self.ok("add", "--section", row[0]["section"], "--title", row[0]["title"], "--chip", row[0]["chip"])
        self.ok("set-crit", "--item", "後の行", "on")
        it = self.by("後の行")
        self.assertEqual((it["section"], it["chip"], it["crit"]), ("今日中", "none", True))

    # ---- restore の差の実施日（due）と一度移した印（due_moved）
    def hist(self, data, stamp="120000"):
        h = os.path.join(self.dir, "history")
        os.makedirs(h, exist_ok=True)
        name = "board-%s-lastgood-%s.html" % (date.today().isoformat(), stamp)
        with open(os.path.join(h, name), "wb") as f:
            f.write(data)
        return "history/" + name

    def test_restore_diff_carries_due_and_readd_keeps_it(self):
        self.create()
        rel = self.hist(self.read())
        due = "%s 9:30" % (date.today() + timedelta(days=7)).isoformat()
        self.ok("add", "--section", "明日以降", "--title", "X-due", "--due", due)
        out = self.ok("restore", "--from", rel, "--confirmed")
        row = [x for x in out["diff"]["only_now"] if x["title"] == "X-due"]
        self.assertEqual(len(row), 1)
        self.assertEqual((row[0].get("due"), row[0].get("due_moved")), (due, None))
        self.assertIn("due は --due、due_moved は --due-moved で写す", out["message"])
        self.ok("add", "--section", row[0]["section"], "--title", row[0]["title"], "--due", row[0]["due"])
        it = self.by("X-due")
        self.assertEqual((it["section"], it["due"], it["chip"]), ("明日以降", due, "none"))

    def test_restore_detects_due_only_change(self):
        self.create()
        a = (date.today() + timedelta(days=3)).isoformat()
        b = (date.today() + timedelta(days=5)).isoformat()
        self.ok("set-due", "--item", "来週の件", "--due", a)
        rel = self.hist(self.read())
        self.ok("set-due", "--item", "来週の件", "--due", b)
        out = self.ok("restore", "--from", rel)
        self.assertEqual([(x["title"], x["due"]) for x in out["diff"]["only_now"]], [("来週の件", b)])
        self.assertEqual([(x["title"], x["due"]) for x in out["diff"]["only_restore"]], [("来週の件", a)])

    def test_restore_detects_due_moved_only_change(self):
        self.create()
        today = date.today().isoformat()
        self.ok("set-due", "--item", "来週の件", "--due", today)
        cur = self.text()
        marked = cur.replace(' data-due="%s"' % today, ' data-due="%s" data-due-moved="%s"' % (today, today), 1)
        self.assertNotEqual(marked, cur)
        rel = self.hist(marked.encode("utf-8"))
        out = self.ok("restore", "--from", rel)
        self.assertEqual([(x["title"], x["due_moved"]) for x in out["diff"]["only_now"]], [("来週の件", None)])
        self.assertEqual([(x["title"], x["due_moved"]) for x in out["diff"]["only_restore"]], [("来週の件", today)])

    def test_require_sound_message_names_due(self):
        self.create()
        label = '<div class="section-label">今日中</div>\n'
        self.write(self.text().replace(label, label + tbe.NESTED))
        rc, out = self.ed("add", "--section", "今日中", "--title", "z")
        self.assertEqual(rc, 1, out)
        self.assertIn("due は --due、due_moved は --due-moved で写す", out["error"])

    def test_row_on_both_sides_is_fixed_in_place_with_set_due(self):
        self.create()
        a = (date.today() + timedelta(days=3)).isoformat()
        b = (date.today() + timedelta(days=5)).isoformat()
        self.ok("set-due", "--item", "来週の件", "--due", a)
        rel = self.hist(self.read())
        self.ok("set-due", "--item", "来週の件", "--due", b)
        out = self.ok("restore", "--from", rel, "--confirmed")
        self.assertIn("only_restore にも同じタイトルの行がある only_now の行は", out["message"])
        now = [x for x in out["diff"]["only_now"] if x["title"] == "来週の件"]
        old = [x for x in out["diff"]["only_restore"] if x["title"] == "来週の件"]
        self.assertEqual((len(now), len(old)), (1, 1))
        self.assertEqual(now[0]["section"], old[0]["section"])
        # 案内のとおり add で足さず、違う欄（due）だけを set-due で当てる
        self.ok("set-due", "--item", "来週の件", "--due", now[0]["due"])
        rows = [i for i in self.items() if i["title"] == "来週の件"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["section"], rows[0]["due"]), ("明日以降", b))

    def test_create_missing_lists_crit_due_due_moved(self):
        self.create()
        due = (date.today() + timedelta(days=4)).isoformat()
        self.ok("add", "--section", "今日中", "--title", "重要な行")
        self.ok("set-crit", "--item", "重要な行", "on")
        self.ok("add", "--section", "明日以降", "--title", "日付の行", "--due", due)
        p = self.write_spec(tbe.SPEC)
        rc, out = tbe.run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 1, out)
        self.assertIn("missing の time・chip・note・crit・due・due_moved・due_from を写し", out["error"])
        m = {r["title"]: r for r in out["missing"]}
        self.assertEqual((m["重要な行"]["crit"], m["重要な行"]["due"], m["重要な行"]["due_moved"]), (True, None, None))
        self.assertEqual((m["日付の行"]["crit"], m["日付の行"]["due"], m["日付の行"]["due_moved"]), (False, due, None))

    def test_restore_diff_has_due_on_broken_board(self):
        self.create()
        rel = self.hist(self.read())
        due = (date.today() + timedelta(days=6)).isoformat()
        self.ok("add", "--section", "明日以降", "--title", "X-due", "--due", due)
        label = '<div class="section-label">今日中</div>\n'
        self.write(self.text().replace(label, label + tbe.NESTED))
        rc, out = self.ed("restore", "--from", rel)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out["diff"]["now_broken"])
        row = [x for x in out["diff"]["only_now"] if x["title"] == "X-due"]
        self.assertEqual(len(row), 1)
        self.assertEqual((row[0]["due"], row[0]["due_moved"]), (due, None))

    def test_row_moved_across_sections_is_moved_back_then_fixed(self):
        """戻す版を取った後に見出しをまたいで動かした行は、move で動かしてから違う欄だけを当てると1行のまま。"""
        self.create()
        rel = self.hist(self.read())
        self.ok("move", "--item", "作業B", "--section", "明日以降", "--due", "none")
        self.ok("set-chip", "--item", "作業B", "--chip", "done")
        out = self.ok("restore", "--from", rel, "--confirmed")
        self.assertIn("only_restore にも同じタイトルの行がある only_now の行は", out["message"])
        self.assertNotIn("同じ見出し・同じタイトル", out["message"])
        now = [x for x in out["diff"]["only_now"] if x["title"] == "作業B"]
        old = [x for x in out["diff"]["only_restore"] if x["title"] == "作業B"]
        self.assertEqual([(x["section"], x["chip"]) for x in now], [("明日以降", "done")])
        self.assertEqual([(x["section"], x["chip"]) for x in old], [("今日中", "pending")])
        # 案内のとおり: 見出しが違うので先に move、それから違う欄（chip）だけを当てる
        # 今日の側から「明日以降」へ動かすので --due が要る。案内のとおり none で動かし、実施日は違う欄として set-due で当てる（v1.9）
        self.ok("move", "--item", "作業B", "--section", now[0]["section"], "--due", "none")
        self.ok("set-chip", "--item", "作業B", "--chip", now[0]["chip"])
        rows = [i for i in self.items() if i["title"] == "作業B"]
        self.assertEqual([(i["section"], i["chip"]) for i in rows], [("明日以降", "done")])

    def test_row_from_unmovable_section_is_added_and_old_removed(self):
        """move で動かせない見出し（ルーチンタスク）の行は、add で足して戻した板の行を remove で消すと1行のまま。"""
        self.create()
        good = self.read()
        self.ok("add", "--section", "今日中", "--title", "ログを更新する", "--chip", "active")
        self.ok("edit", "--item", str(self.by("ログを更新する", "ルーチンタスク")["index"]), "--title", "仮-ルーチン")
        self.ok("remove", "--item", "仮-ルーチン", "--confirmed")
        rel = self.hist(good)
        out = self.ok("restore", "--from", rel, "--confirmed")
        now = [x for x in out["diff"]["only_now"] if x["title"] == "ログを更新する"]
        old = [x for x in out["diff"]["only_restore"] if x["title"] == "ログを更新する"]
        self.assertEqual([x["section"] for x in now], ["今日中"])
        self.assertEqual([x["section"] for x in old], ["ルーチンタスク"])
        # 案内の文が move できない見出しの経路を名指ししている
        self.assertIn("move で動かせないときは、先に戻した板の行を remove で消してから〔消す前の欄は only_restore にある〕、"
                      "上のとおり add で足す", out["message"])
        self.assertNotIn("上のとおり add で足し、戻した板の行を remove で消す", out["message"])
        rc, err = self.ed("move", "--item", "ログを更新する", "--section", "今日中")
        self.assertEqual(rc, 1, err)                     # ルーチンタスクの行は move で動かせない
        # 案内の順（先に戻した板の行を消してから足す）なら、同じタイトルが2行並ばず回り道が要らない
        self.ok("remove", "--item", "ログを更新する")
        self.ok("remove", "--item", "ログを更新する", "--confirmed")
        self.ok("add", "--section", now[0]["section"], "--title", now[0]["title"], "--chip", now[0]["chip"])
        rows = [i for i in self.items() if i["title"] == "ログを更新する"]
        self.assertEqual([(i["section"], i["chip"]) for i in rows], [("今日中", "active")])

    def test_create_spec_chip_none_stays_none_on_today_side(self):
        self.create()
        self.ok("add", "--section", "今日中", "--title", "none の行", "--chip", "none")
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(tbe.SPEC)])
        self.assertEqual(rc, 1, out)
        self.assertIn('chip が none でも "none" と書く', out["error"])
        m = [r for r in out["missing"] if r["title"] == "none の行"]
        self.assertEqual((m[0]["section"], m[0]["chip"]), ("今日中", "none"))
        spec = {"sections": tbe.SPEC["sections"], "items": tbe.SPEC["items"] + [
            {"section": m[0]["section"], "title": m[0]["title"], "chip": m[0]["chip"]}]}
        self.create(spec)
        self.assertEqual(self.by("none の行")["chip"], "none")

    # ---- 見出しが無い「明日以降」へ今日の側から動かす（move --create-section）・足し直す（add）
    DUE_CLAUSE = "due は --due、due_moved は --due-moved で写す"
    MERGE = "due に時刻が無く time が H:MM ならその時刻を --due に含め（--due \"<due> <time>\"）、それ以外は time を写さない"
    TODAY_SIDE = "今日の予定・今日中へ足す行で due があれば due_moved も対で写し、null なら --due-moved none"
    OLD_TODAY_SIDE = ("今日の側へ足すなら due・due_moved は写さない", "元の実施日の表示が消える", "due が今日の日付で時刻を持つなら")

    def setUpNoTomorrow(self):
        """今日の側に、印の無い実施日付きの行（時刻あり）と、印のある行を置き、「明日以降」の見出しを消した板。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "先の件"},
            {"section": "明日以降", "title": "来た件"}]})
        self.future = (date.today() + timedelta(days=4)).isoformat()
        self.today = date.today().isoformat()
        self.ok("set-due", "--item", "先の件", "--due", self.future)
        self.ok("set-due", "--item", "来た件", "--due", self.today)
        self.ok("move", "--item", "先の件", "--section", "今日の予定")
        self.ok("set-time", "--item", "先の件", "--time", "18:00")
        # v1.8 までの move（実施日が先なので日付も印も変えなかった）と v1.6 までの set-time でできた、先の日の日付だけの実施日と時刻の欄の行
        self.put_legacy_early("先の件", self.future)
        self.ok("move", "--item", "来た件", "--section", "今日中")         # 実施日が来ているので印が付く
        self.assertEqual((self.by("先の件")["due"], self.by("先の件")["due_moved"]), (self.future, None))
        self.assertEqual((self.by("来た件")["due"], self.by("来た件")["due_moved"]), (self.today, self.today))
        self.write(self.text().replace('<div class="section-label">明日以降</div>\n', "", 1))
        self.assertNotIn("明日以降", [s["name"] for s in self.status()["sections"]])

    def test_move_to_missing_tomorrow_with_create_section_keeps_due(self):
        """今日の側の行を、見出しの無い「明日以降」へ move --create-section で動かすと、--due で決めた実施日になる
        （時刻の欄はその時刻・印は外れる＝v1.9）。--due none（未定）は実施日を外す。--due が無ければ書かずに断る。"""
        self.setUpNoTomorrow()
        before = self.read()
        rc, out = self.ed("move", "--item", "先の件", "--section", "明日以降")
        self.assertEqual(rc, 1, out)
        self.assertIn("--due で実施日を指定してください", out["error"])
        self.assertUnchanged(before)
        rc, out = self.ed("move", "--item", "先の件", "--section", "明日以降", "--due", self.future + " 18:00")
        self.assertEqual(rc, 1, out)
        self.assertIn("--create-section", out["error"])
        self.assertUnchanged(before)
        self.ok("move", "--item", "先の件", "--section", "明日以降", "--create-section", "--due", self.future + " 18:00")
        self.ok("move", "--item", "来た件", "--section", "明日以降", "--due", "none")
        it = self.by("先の件")
        self.assertEqual((it["section"], it["time"], it["due"], it["due_moved"]), ("明日以降", "18:00", self.future + " 18:00", None))
        it = self.by("来た件")
        self.assertEqual((it["section"], it["due"], it["due_moved"], it["due_from"]), ("明日以降", None, None, None))
        self.assertEqual([x["name"] for x in self.status()["sections"]][-1], "明日以降")
        self.assertEqual(self.status()["due_now"], [])

    def test_readd_to_missing_tomorrow_keeps_due(self):
        self.setUpNoTomorrow()
        st = self.by("先の件")
        # add は --time と --due を一緒に受けない
        rc, out = self.ed("add", "--section", "明日以降", "--create-section", "--title", "先の件",
                          "--due", st["due"], "--time", st["time"])
        self.assertEqual(rc, 1, out)
        # 案内のとおり: 元の行を先に消し、due に時刻が無いので、time をその時刻として --due に含めて足す
        self.ok("remove", "--item", "18:00|先の件", "--confirmed")
        self.ok("add", "--section", "明日以降", "--create-section", "--title", "先の件",
                "--due", "%s %s" % (st["due"], st["time"]))
        it = self.by("先の件")
        self.assertEqual((it["section"], it["time"], it["due"], it["due_moved"]),
                         ("明日以降", None, "%s 18:00" % self.future, None))
        self.assertEqual(self.status()["due_now"], [])

    def test_readd_then_deck_moves_on_due_day_at_that_time(self):
        """時刻があり実施日が日付だけの行を、案内どおり足し直しても、move --create-section で動かしても、
        Deck が実施日にその時刻で「今日の予定」へ移す。"""
        for how in ("add", "move"):
            if os.path.exists(self.board):
                os.remove(self.board)
            self.setUpNoTomorrow()
            st = self.by("先の件")
            if how == "add":
                self.ok("remove", "--item", "18:00|先の件", "--confirmed")
                self.ok("add", "--section", "明日以降", "--create-section", "--title", "先の件",
                        "--due", "%s %s" % (st["due"], st["time"]))
            else:
                self.ok("move", "--item", "18:00|先の件", "--section", "明日以降", "--create-section",
                        "--due", "%s %s" % (st["due"], st["time"]))
            block = self.block("先の件")
            due = tbe.dw.parse_due_value(tbe.dw._item_open_attr(block, "data-due"))
            self.assertEqual(due[0].isoformat(), self.future)
            placed = tbe.dw._move_due_block(block, due, due[0], "\n")
            self.assertIsNotNone(placed)
            new_block, dest = placed
            self.assertEqual(dest, "今日の予定", how)
            self.assertIn('<div class="time">18:00</div>', new_block)

    def test_readd_marked_row_keeps_due_and_mark(self):
        """印のある行を「明日以降」へ足し直すと、実施日と印を写すので、Deck も move も今日の側へ移し直さない。"""
        self.setUpNoTomorrow()
        st = self.by("来た件", "今日中")
        self.ok("remove", "--item", "来た件", "--confirmed")
        self.ok("add", "--section", "明日以降", "--create-section", "--title", "来た件",
                "--chip", st["chip"], "--due", st["due"], "--due-moved", st["due_moved"])
        it = self.by("来た件")
        self.assertEqual((it["section"], it["due"], it["due_moved"]), ("明日以降", self.today, self.today))
        self.assertEqual(self.status()["due_now"], [])
        self.assertEqual(tbe.dw.roll_board_text(self.text(), date.today() + timedelta(days=1), "0:00")[1]["due_moved"], 0)

    def test_odd_section_messages_name_due(self):
        self.create()
        rc, out = self.ed("add", "--section", "本日中", "--create-section", "--title", "x")
        self.assertEqual(rc, 0, out)
        k11 = [w["message"] for w in out["warnings"] if w["code"] == "K11"][0]
        rc, out = self.ed("move", "--item", "x", "--section", "明日以降")
        self.assertEqual(rc, 1, out)
        for msg in (k11, out["error"]):
            self.assertIn(self.DUE_CLAUSE, msg)
            self.assertIn(self.MERGE, msg)
            self.assertIn(self.TODAY_SIDE, msg)
            self.assertNotIn("元の行を消した後に set-time で付け直す", msg)
            self.assertNotIn("due の時刻だけが効く", msg)
            # 確かめは remove の句に付く（set-crit の句の後ろではない）。元の行を先に消してから足す
            self.assertIn("remove で元の行を先に消し（--confirmed を付ける前に、消す行をユーザーに確かめる）、", msg)
            self.assertIn("重要タスクだった項目は足した後に set-crit で付け直してください。", msg)
            for old in self.OLD_TODAY_SIDE:
                self.assertNotIn(old, msg)
            self.assertNotIn("set-crit で付け直してください（--confirmed を付ける前に", msg)

    def test_skill_heading_fix_names_due(self):
        with open(os.path.join(tbe.ROOT, "skill", "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("`due` は `--due`、`due_moved` は `--due-moved`、`due_from` は `--due-from`（`null` なら省く）で写す〔今日の予定・今日中へ足すなら、`due` のある項目は `due_moved` も対で写し", text)
        self.assertIn("`due` に時刻が無く時刻が `H:MM` の項目はその時刻を `--due` に含め（`--due \"<due> <time>\"`）", text)
        self.assertIn("`status` の欄を控えてから元の行を `remove` で先に消し", text)
        self.assertNotIn("足した項目から元の実施日の表示が消える", text)
        self.assertNotIn("今日の側へ足すなら `due`・`due_moved` は写さない", text)
        self.assertNotIn("元の行を消した後に `set-time` で付け直す", text)
        self.assertNotIn("`due` の時刻だけが効く", text)


    # ---- 足し直しの案内（restore・create・update モード 9）を、文と実物の両方で確かめる

    def skill(self):
        with open(os.path.join(tbe.ROOT, "skill", "SKILL.md"), encoding="utf-8") as f:
            return f.read()

    def broken(self):
        label = '<div class="section-label">今日中</div>\n'
        self.write(self.text().replace(label, label + tbe.NESTED))

    def test_restore_message_names_pairing_before_mark_and_renumber(self):
        self.create()
        rel = self.hist(self.read())
        out = self.ok("restore", "--from", rel, "--confirmed")
        msg = out["message"]
        self.assertIn("同じタイトルの行が only_now か only_restore に2つ以上あるときは、見出し・時刻・補足の近いものを組にし、"
                      "決まらなければ両方の行をユーザーに見せて組を確かめる", msg)
        self.assertIn("今日の予定へは、時刻のある行は時刻の順の位置へ入る", msg)
        self.assertNotIn("--before でその時刻より後の最初の行の前へ置く", msg)
        self.assertIn("set-due --due <only_now の due> --due-moved <only_now の due_moved> --due-from <only_now の due_from>（due_moved が null なら、"
                      "今日の予定・今日中の行では --due-moved none、「明日以降」の行では省く＝set-due は印も外す", msg)
        self.assertIn("status の番号で指し、move などで書いた後は status で番号を取り直す", msg)
        self.assertIn(self.TODAY_SIDE, msg)
        self.assertNotIn("--item が断るときは status の番号で指す（", msg)
        # 形の崩れた板の案内（require_sound）も同じ文
        self.broken()
        rc, err = self.ed("add", "--section", "今日中", "--title", "z")
        self.assertEqual(rc, 1, err)
        for s in ("見出し・時刻・補足の近いものを組にし", "時刻のある行は時刻の順の位置へ入る",
                  "set-due は印も外す", "番号を取り直す", "先に戻した板の行を remove で消してから", self.TODAY_SIDE,
                  "その時刻を --due に含め"):
            self.assertIn(s, err["error"])

    def test_mark_only_on_restored_row_is_removed_with_set_due(self):
        """印が戻した板の行にだけあるときは、set-due で同じ実施日を当てると印が外れる。"""
        self.create()
        today = date.today().isoformat()
        self.ok("set-due", "--item", "来週の件", "--due", today)
        cur = self.text()
        marked = cur.replace(' data-due="%s"' % today, ' data-due="%s" data-due-moved="%s"' % (today, today), 1)
        rel = self.hist(marked.encode("utf-8"))
        out = self.ok("restore", "--from", rel, "--confirmed")
        now = [x for x in out["diff"]["only_now"] if x["title"] == "来週の件"]
        old = [x for x in out["diff"]["only_restore"] if x["title"] == "来週の件"]
        self.assertEqual((now[0]["due_moved"], old[0]["due_moved"]), (None, today))
        self.assertEqual(self.by("来週の件")["due_moved"], today)
        self.ok("set-due", "--item", "来週の件", "--due", now[0]["due"])
        it = self.by("来週の件")
        self.assertEqual((it["due"], it["due_moved"]), (today, None))

    def test_move_back_to_plan_with_before_keeps_time_order(self):
        """今日の予定へ move で戻すと、--before が無くても時刻順の位置へ入る。"""
        self.create()
        self.ok("move", "--item", "9:00|朝会", "--section", "今日中")
        rel = self.hist(self.read())                       # 戻す版では朝会が今日中にある
        self.ok("move", "--item", "9:00|朝会", "--section", "今日の予定", "--head")
        self.ok("set-chip", "--item", "9:00|朝会", "--chip", "done")
        out = self.ok("restore", "--from", rel, "--confirmed")
        self.assertIn("今日の予定へは、時刻のある行は時刻の順の位置へ入る", out["message"])
        now = [x for x in out["diff"]["only_now"] if x["title"] == "朝会"]
        self.assertEqual([(x["section"], x["time"], x["chip"]) for x in now], [("今日の予定", "9:00", "done")])
        # --before を省いても時刻の順の位置（16:00 の前）に入る
        self.ok("move", "--item", "9:00|朝会", "--section", "今日の予定")
        self.ok("set-chip", "--item", "9:00|朝会", "--chip", now[0]["chip"])
        rows = self.status()["sections"][0]["items"]
        self.assertEqual([(i["title"], i["chip"]) for i in rows], [("朝会", "done"), ("判断する", "pending")])

    def test_today_side_readd_copies_due_and_mark(self):
        """今日の側の行は、time・due・due_moved をそのまま写すと元の行と同じになる（時刻を due から作らない＝利用者が外した時刻を戻さない）。"""
        self.create()
        rel = self.hist(self.read())
        today = date.today().isoformat()
        self.ok("add", "--section", "明日以降", "--title", "来た件", "--due", today + " 21:00")
        self.ok("move", "--item", "来た件", "--section", "今日の予定")
        out = self.ok("restore", "--from", rel, "--confirmed")
        self.assertIn(self.TODAY_SIDE, out["message"])
        for old in self.OLD_TODAY_SIDE:
            self.assertNotIn(old, out["message"])
        row = [x for x in out["diff"]["only_now"] if x["title"] == "来た件"][0]
        self.assertEqual((row["section"], row["time"], row["due"], row["due_moved"], row["chip"]),
                         ("今日の予定", "21:00", today + " 21:00", today, "pending"))
        self.ok("add", "--section", row["section"], "--title", row["title"], "--chip", row["chip"], "--time", row["time"],
                "--due", row["due"], "--due-moved", row["due_moved"])
        it = self.by("来た件")
        self.assertEqual((it["section"], it["time"], it["due"], it["due_moved"]), ("今日の予定", "21:00", today + " 21:00", today))
        self.assertIn("21:00|来た件", [a[0] for a in tbe.dw.read_board_alarms(self.board)])

    def test_incomplete_messages_name_fields_and_where_to_copy_from(self):
        """崩れた板の補足は欄を広く挙げ、写し元を戻す前の板と言う。"""
        self.create()
        rel = self.hist(self.read())
        self.broken()
        rc, out = self.ed("restore", "--from", rel)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out["diff"]["only_now_incomplete"])
        self.assertIn("only_now の行の欄（チップ・補足・実施日など）が欠けているか", out["message"])
        self.assertIn("欠けた欄は、その Read で読んだ板から写してください（戻した後は、戻す前の板が saved の名前で history/ に残ります）", out["message"])
        self.assertNotIn("チップ・補足が欠けているか", out["message"])
        out = self.ok("restore", "--from", rel, "--confirmed")
        self.assertIn("saved の板を Read で読み、欠けた欄はそこから写し、only_now に無い行もユーザーに見せてください", out["message"])
        self.broken()
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(tbe.SPEC)])
        self.assertEqual(rc, 1, out)
        self.assertIn("missing の行の欄（チップ・補足・実施日など）が欠けているか", out["error"])
        self.assertIn("欠けた欄は、その Read で読んだ板から写してください。", out["error"])
        self.assertNotIn("チップ・補足が欠けているか", out["error"])

    def test_complete_restore_has_no_incomplete_note(self):
        self.create()
        rel = self.hist(self.read())
        out = self.ok("restore", "--from", rel, "--confirmed")
        self.assertNotIn("only_now_incomplete", out["message"])

    def test_create_merges_time_into_due_and_deck_moves_it_on_the_day(self):
        """create の経路も、時刻を due に含める1通りで、Deck は実施日にその時刻で今日の予定へ移す。"""
        self.create()
        future = (date.today() + timedelta(days=3)).isoformat()
        self.ok("add", "--section", "明日以降", "--title", "先の件", "--due", future)
        self.ok("set-time", "--item", "先の件", "--time", "18:00")
        self.put_legacy_due("先の件", future)                              # v1.6 までの set-time でできた、日付だけの実施日と時刻の欄の行
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(tbe.SPEC)])
        self.assertEqual(rc, 1, out)
        self.assertIn("spec が time と due を一緒に受けないので、due に時刻が無く time が H:MM ならその時刻を due に含め", out["error"])
        self.assertNotIn("作った板から元の実施日の表示が消える", out["error"])
        m = [r for r in out["missing"] if r["title"] == "先の件"][0]
        self.assertEqual((m["time"], m["due"]), ("18:00", future))
        orig = self.block("先の件")
        both = {"section": m["section"], "title": m["title"], "time": m["time"], "due": m["due"]}
        rc, err = tbe.run(["create", "--board", self.board, "--spec",
                           self.write_spec({"sections": tbe.SPEC["sections"], "items": tbe.SPEC["items"] + [both]})])
        self.assertEqual(rc, 1, err)                  # spec は time と due を一緒に受けない
        merged = {"section": m["section"], "title": m["title"], "due": "%s %s" % (m["due"], m["time"])}
        self.create({"sections": tbe.SPEC["sections"], "items": tbe.SPEC["items"] + [merged]})
        day = date.today() + timedelta(days=3)
        for blk in (orig, self.block("先の件")):
            due = tbe.dw.parse_due_value(tbe.dw._item_open_attr(blk, "data-due"))
            new_block, dest = tbe.dw._move_due_block(blk, due, day, "\n")
            self.assertEqual(dest, "今日の予定")
            self.assertIn('<div class="time">18:00</div>', new_block)

    def test_row_with_due_time_and_time_element_readds_with_due_only(self):
        """due に時刻があり時刻の欄が違う行（v1.6 までにできた行）は、Deck は時刻の欄の時刻で移す（v2.11）。due だけを写すと
        due の時刻になる（time が消える）ので、案内はどちらの時刻にするかを確かめさせる。time にするなら due に含めて写せば同じになる。"""
        self.create()
        future = (date.today() + timedelta(days=2)).isoformat()
        # 時刻の欄と実施日の時刻が違う行は v1.7 の操作では作れない。今日の側の行を move で戻した後に data-due を書き換える
        self.ok("add", "--section", "今日中", "--title", "両方", "--time", "7:40", "--due", future + " 22:05", "--due-moved", "none", "--chip", "none")
        self.ok("move", "--item", "両方", "--section", "明日以降", "--due", future + " 7:40")
        self.put_legacy_due("両方", future + " 22:05")
        orig = self.block("両方")
        st = self.by("両方")
        self.assertEqual((st["time"], st["due"]), ("7:40", future + " 22:05"))
        self.ok("edit", "--item", str(st["index"]), "--title", "仮-両方")
        self.ok("remove", "--item", "仮-両方", "--confirmed")
        self.ok("add", "--section", "明日以降", "--title", "両方", "--due", st["due"])   # time は写さない（due の時刻にする）
        self.ok("add", "--section", "明日以降", "--title", "欄の時刻", "--due", future + " " + st["time"])   # time の時刻にする
        day = date.today() + timedelta(days=2)
        got = []
        for blk in (orig, self.block("両方"), self.block("欄の時刻")):
            due = tbe.dw.parse_due_value(tbe.dw._item_open_attr(blk, "data-due"))
            new_block, dest = tbe.dw._move_due_block(blk, due, day, "\n")
            got.append((dest, tbe.dw._element_text(new_block, "time")))
        self.assertEqual(got, [("今日の予定", "7:40"), ("今日の予定", "22:05"), ("今日の予定", "7:40")])

    def test_update_mode9_matches_deck_for_time_element_rows(self):
        """update モード 9 の手順（move だけで時刻の欄・チップ・印がそろう）が Deck の移し方と同じになる。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日の予定", "time": "23:00", "title": "夜"},
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "今日の件", "time": "9:30"},
            {"section": "明日以降", "title": "過去の件", "time": "18:00"}]})
        today = date.today()
        self.ok("set-due", "--item", "今日の件", "--due", today.isoformat())
        self.ok("set-due", "--item", "過去の件", "--due", (today - timedelta(days=2)).isoformat())
        deck = {}
        for t in ("今日の件", "過去の件"):
            blk = self.block(t)
            due = tbe.dw.parse_due_value(tbe.dw._item_open_attr(blk, "data-due"))
            new_block, dest = tbe.dw._move_due_block(blk, due, today, "\n")
            deck[t] = (dest, tbe.dw._element_text(new_block, "time"))
        self.assertEqual(deck, {"今日の件": ("今日の予定", "9:30"), "過去の件": ("今日中", None)})
        # SKILL.md の手順: 時刻は due の時刻、無ければ status の time
        rows = {r["title"]: r for r in self.status()["due_now"]}
        r = rows["今日の件"]
        tm = (r["due"].split(" ")[1] if " " in r["due"] else None) or r["time"]
        self.assertEqual(tm, "9:30")
        self.ok("move", "--item", "9:30|今日の件", "--section", "今日の予定")      # --before・set-time・set-chip は要らない
        self.ok("move", "--item", "18:00|過去の件", "--section", "今日中", "--head")
        for t in ("今日の件", "過去の件"):
            self.assertEqual(self.by(t)["chip"], "pending")
        self.assertEqual([i["title"] for i in self.status()["sections"][0]["items"]], ["今日の件", "夜"])
        mine = {t: (self.by(t)["section"], self.by(t)["time"]) for t in ("今日の件", "過去の件")}
        self.assertEqual(mine, deck)
        alarms = [a[0] for a in tbe.dw.read_board_alarms(self.board)]
        self.assertIn("9:30|今日の件", alarms)
        self.assertNotIn("18:00|過去の件", alarms)
        self.assertEqual(self.status()["due_now"], [])

    def test_skill_and_readme_texts(self):
        text = self.skill()
        # restore: 崩れた板の欠けた欄の写し元
        self.assertIn("`only_now_incomplete` のときは、欠けた欄（チップ・補足・実施日など）を、戻す前に Read で読んだ板"
                      "（戻した後は restore の出力の `saved` の名前で `history/` にある）から写す。", text)
        self.assertNotIn("チップと実施日を Read で読んだいまの板から写す", text)
        # restore: 組の作り方・時刻の順の位置・印の当て方・番号の取り直し・消してから足す順
        self.assertIn("見出し・時刻・補足の近いものを組にし、決まらなければ両方の行をユーザーに見せて組を確かめる", text)
        self.assertIn("今日の予定へは、時刻のある行は時刻の順の位置へ入る", text)
        self.assertNotIn("`--before` でその時刻より後の最初の行の前へ置く", text)
        self.assertIn("`set-due --due <only_now の due> --due-moved <only_now の due_moved> --due-from <only_now の due_from>`（`due_moved` が `null` なら、"
                      "今日の予定・今日中の行では `--due-moved none`、「明日以降」の行では省く＝`set-due` は印も外す", text)
        self.assertIn("`move` などで書いた後は `status` で番号を取り直す", text)
        self.assertIn("先に戻した板の行を `remove` で消してから〔消す前の欄は `only_restore` にある〕、上のとおり `add` で足す", text)
        self.assertNotIn("上のとおり `add` で足し、戻した板の行を `remove` で消す", text)
        # create モード 2: chip が none の行
        self.assertIn("`status` から写す行は、`chip` が `none` でも `\"chip\": \"none\"` と書く", text)
        # 「明日以降」へ足し直す行の時刻と実施日
        self.assertIn("`due` に時刻が無く `time` が `H:MM` ならその時刻を `--due` に含め（`--due \"<due> <time>\"`）、それ以外は `time` を写さない", text)
        self.assertIn("spec が `time` と `due` を一緒に受けないので、`due` に時刻が無く `time` が `H:MM` ならその時刻を `due` に含め", text)
        for old in ("元の実施日の表示が消える", "`due` が今日の日付で時刻を持つなら", "足した行に実施日は付かない"):
            self.assertNotIn(old, text)
        # update モード 9・実施日の節
        self.assertIn("時刻は `status` の `time`（「明日以降」の行の時刻の欄。`H:MM` のときに限る）とし、無ければ `due` の時刻とする（Deck v2.11 も同じ順で見る。", text)
        self.assertNotIn("続けて `set-time --item <タイトル> --time none` で外す", text)
        self.assertNotIn("（前の日の時刻は `set-time` しない。今日のその時刻に通知が出る）。", text)
        self.assertIn("実施日が今日で時刻があれば（行の時刻は、時刻の欄が `H:MM`〔時 0〜23・分 0〜59〕ならその時刻、無ければ実施日の時刻＝Deck v2.11）「今日の予定」", text)
        self.assertIn("行き先の見出しが無い板では、同じ `move` に `--create-section` を付ける", text)
        self.assertNotIn("行き先の見出しが無い板では `move` が断るので", text)
        self.assertIn("形を作れない行（時刻の欄が2つ以上など）は、`move` は印だけを付けて動かす（Deck の日付の切り替えは、その行を動かさない）", text)
        self.assertIn("写さなかった `time` はユーザーに伝え、`H:MM` の時刻にするかをユーザーに確かめる（ユーザーが `H:MM` の時刻を言ったときだけ、その時刻を写す。確かめずに `H:MM` を当てない）", text)
        self.assertIn("写さなかった時刻はユーザーに伝え、`H:MM` の時刻にするかをユーザーに確かめる（ユーザーが `H:MM` の時刻を言ったときだけ、その時刻を写す。確かめずに `H:MM` を当てない）", text)
        self.assertNotIn("の時刻が分かればその時刻を写す", text)
        self.assertNotIn("写せなかった `time` はユーザーに伝える", text)
        # create の消える時刻の確かめ（H:MM でない時刻は残さず、dropped_times を見せて確かめる）
        self.assertIn("**消える時刻の確かめ**", text)
        self.assertIn("確かめた後に `--confirmed` を付けて create を実行する（ユーザーに確かめずに `H:MM` を当てて `--confirmed` を付けない）", text)
        self.assertIn("その文字は板に表示されていて、作り直すと消える", text)
        self.assertNotIn("どこにも使われていない", text)
        self.assertIn("**`version` が 1.10 より前なら書かずに", text)
        self.assertIn("**どの `result` でも**、出力の `skipped_writes`", text)
        self.assertIn("時刻の欄は外し、行の時刻は `data-due-from` に残す＝Deck v2.12", text)
        self.assertNotIn("時刻の欄は外し、元の時刻は `data-orig-time` に残す", text)
        with open(os.path.join(tbe.ROOT, "deck", "README.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn("行の時刻は、時刻の要素が `H:MM`〔時 0〜23・分 0〜59〕ならその時刻、無ければ実施日の時刻＝v2.11", readme)
        self.assertIn("行に時刻の要素があれば外し、行の時刻は `data-due-from` に残る", readme)
        self.assertNotIn("行に時刻の要素があれば外し、その時刻を `data-orig-time` に残す", readme)

    def test_create_missing_check_compares_later_rows_by_effective_time(self):
        """時刻を due に含めて写した行・due に時刻があり時刻の欄を写さない行は消える行に数えず、時刻が違えば数える。"""
        self.create()
        d = (date.today() + timedelta(days=3)).isoformat()
        self.ok("add", "--section", "明日以降", "--title", "欄だけ", "--due", d)
        self.ok("set-time", "--item", "欄だけ", "--time", "18:00")
        self.put_legacy_due("欄だけ", d)                                   # v1.6 までの set-time でできた、日付だけの実施日と時刻の欄の行
        self.ok("add", "--section", "今日中", "--title", "両方", "--time", "7:40", "--due", d + " 22:05", "--due-moved", "none", "--chip", "none")
        self.ok("move", "--item", "両方", "--section", "明日以降", "--due", d + " 7:40")
        self.put_legacy_due("両方", d + " 22:05")             # v1.6 までにできた、時刻の欄と実施日の時刻が違う行
        base_items = tbe.SPEC["items"]
        ok_spec = {"sections": tbe.SPEC["sections"], "items": base_items + [
            {"section": "明日以降", "title": "欄だけ", "due": d + " 18:00"},
            {"section": "明日以降", "title": "両方", "due": d + " 22:05"}]}
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(ok_spec)])
        self.assertEqual(rc, 1, out)                # 両方: 消える行ではないが、時刻の欄の 7:40 が消えるので確かめる（v1.5）
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["title"], r["time"], r["new_time"], r["due"]) for r in out["dropped_times"]],
                         [("両方", "7:40", "22:05", d + " 22:05")])
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(ok_spec), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.by("欄だけ")["due"], self.by("両方")["due"]), (d + " 18:00", d + " 22:05"))
        bad_spec = {"sections": tbe.SPEC["sections"], "items": base_items + [
            {"section": "明日以降", "title": "欄だけ", "due": d + " 19:00"},
            {"section": "明日以降", "title": "両方", "due": d + " 22:05"}]}
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(bad_spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual([r["title"] for r in out["missing"]], ["欄だけ"])

if __name__ == "__main__":
    unittest.main()
