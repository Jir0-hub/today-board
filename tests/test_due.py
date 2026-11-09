# -*- coding: utf-8 -*-
"""実施日（「明日以降」の行の data-due）の試験。board_edit.py の add / set-due / create / status と、Deck v2.8 の日付の切り替え。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
すべて一時フォルダのサンドボックスで行う（test_board_edit.Sandbox）。画面の表示は test_board_browser.py の TestDueChips。
"""

import json
import os
import re
import sys
import unittest
from datetime import date, timedelta

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skill", "hooks"))
from test_board_edit import Sandbox, be, dw, run  # noqa: E402
import guard  # noqa: E402

TODAY = date.today()


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


def base(*later, today_rows=()):
    return {"sections": ["今日の予定", "今日中", "ルーチンタスク", "明日以降"],
            "items": list(today_rows) + [{"section": "明日以降", "title": t, **kw} for (t, kw) in later]}


def block_of(text, title):
    lines = text.splitlines(keepends=True)
    for (s, e, name) in dw._scan_board(lines)[1]:
        blk = "".join(lines[s:e + 1])
        if dw._element_text(blk, "task-title") == title:
            return blk, name
    return None, None


class TestAddAndSetDue(Sandbox):
    def test_add_with_date_and_time(self):
        self.create()
        rc, out = self.ed("add", "--section", "明日以降", "--title", "判定", "--due", iso(3) + " 22:05")
        self.assertEqual(rc, 0, out)
        blk, sec = block_of(self.text(), "判定")
        self.assertEqual(sec, "明日以降")
        self.assertIn('data-due="%s 22:05"' % iso(3), blk)
        self.assertNotIn('class="time"', blk)     # 今日のその時刻に通知が出ないよう、時刻の要素にしない
        self.assertNotIn('class="chip', blk)      # 明日以降の既定はチップ無し
        it = [i for i in self.items() if i["title"] == "判定"][0]
        self.assertEqual((it["due"], it["due_moved"], it["time"]), (iso(3) + " 22:05", None, None))

    def test_due_forms_are_normalized(self):
        self.create()
        for given, want in ((iso(3) + "T09:05", iso(3) + " 9:05"), (iso(4), iso(4))):
            rc, out = self.ed("add", "--section", "明日以降", "--title", given, "--due", given)
            self.assertEqual(rc, 0, out)
            self.assertIn('data-due="%s"' % want, block_of(self.text(), given)[0])

    def test_bad_due_writes_nothing(self):
        self.create()
        before = self.read()
        for bad in ("2026-02-30", "2026-13-01", "11/4", "2026-11-4", iso(1) + " 25:00", iso(1) + " 9:60", "来週"):
            rc, out = self.ed("add", "--section", "明日以降", "--title", "x", "--due", bad)
            self.assertEqual(rc, 1, bad)
            self.assertIn("実施日", out["error"])
            self.assertUnchanged(before)
            rc, out = self.ed("set-due", "--item", "来週の件", "--due", bad)
            self.assertEqual(rc, 1, bad)
            self.assertUnchanged(before)

    def test_due_only_on_tomorrow_section(self):
        self.create()
        before = self.read()
        rc, out = self.ed("add", "--section", "今日中", "--title", "x", "--due", iso(1))
        self.assertEqual(rc, 1)
        self.assertIn("明日以降", out["error"])
        rc, out = self.ed("set-due", "--item", "作業A", "--due", iso(1))
        self.assertEqual(rc, 1)
        self.assertIn("move --section 明日以降", out["error"])
        self.assertUnchanged(before)

    def test_time_and_due_together_rejected(self):
        self.create()
        before = self.read()
        rc, out = self.ed("add", "--section", "明日以降", "--title", "x", "--time", "9:00", "--due", iso(1))
        self.assertEqual(rc, 1)
        self.assertIn("--time と --due", out["error"])
        self.assertUnchanged(before)

    def test_set_due_add_change_remove(self):
        self.create()
        others = [it for it in self.items() if it["title"] != "来週の件"]
        rc, out = self.ed("set-due", "--item", "来週の件", "--due", iso(2))
        self.assertEqual(rc, 0, out)
        self.assertIn('data-due="%s"' % iso(2), block_of(self.text(), "来週の件")[0])
        rc, out = self.ed("set-due", "--item", "来週の件", "--due", iso(5) + " 8:00")
        self.assertEqual(rc, 0, out)
        blk = block_of(self.text(), "来週の件")[0]
        self.assertEqual(len(re.findall(r"data-due=", blk)), 1)
        self.assertIn('data-due="%s 8:00"' % iso(5), blk)
        rc, out = self.ed("set-due", "--item", "来週の件", "--due", "none")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("data-due", block_of(self.text(), "来週の件")[0])
        self.assertEqual([it for it in self.items() if it["title"] != "来週の件"], others)

    def test_set_due_clears_moved_mark(self):
        self.create()
        self.ed("set-due", "--item", "来週の件", "--due", iso(2))
        text = self.text().replace('data-due="%s"' % iso(2), 'data-due="%s" data-due-moved="%s"' % (iso(-1), iso(-1)))
        self.write(text)
        self.assertEqual(self.status()["due_now"], [])
        rc, out = self.ed("set-due", "--item", "来週の件", "--due", iso(-1))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("data-due-moved", block_of(self.text(), "来週の件")[0])
        self.assertEqual([i["title"] for i in self.status()["due_now"]], ["来週の件"])

    def test_none_is_allowed_outside_tomorrow(self):
        self.create()
        text = self.text()
        self.write(re.sub(r'(<div class="item flat")(>\s*<div>\s*<p class="task-title">作業A)', r'\1 data-due="%s"\2' % iso(0), text))
        self.assertIn("data-due", block_of(self.text(), "作業A")[0])
        rc, out = self.ed("set-due", "--item", "作業A", "--due", "none")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("data-due", block_of(self.text(), "作業A")[0])

    def test_ops_file_with_space(self):
        self.create()
        p = os.path.join(self.dir, "op.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"op": "add", "section": "明日以降", "title": "判定", "due": iso(3) + " 22:05", "board": self.board}, f, ensure_ascii=False)
        rc, out = run(["--ops", p])
        self.assertEqual(rc, 0, out)
        self.assertIn('data-due="%s 22:05"' % iso(3), block_of(self.text(), "判定")[0])

    def test_other_ops_keep_due(self):
        self.create()
        self.ed("add", "--section", "明日以降", "--title", "判定", "--due", iso(3))
        for args in (("set-chip", "--item", "判定", "--chip", "pending"), ("edit", "--item", "判定", "--note", "補足"),
                     ("set-crit", "--item", "判定", "on")):
            rc, out = self.ed(*args)
            self.assertEqual(rc, 0, (args, out))
            self.assertIn('data-due="%s"' % iso(3), block_of(self.text(), "判定")[0], args)
        # 先の日の行を前もって今日の側へ動かすと今日の行になる（実施日は今日・元の予定は data-due-from・印＝v1.9）
        rc, out = self.ed("move", "--item", "判定", "--section", "今日中")
        self.assertEqual(rc, 0, out)
        blk = block_of(self.text(), "判定")[0]
        for attr in ('data-due="%s"' % iso(0), 'data-due-moved="%s"' % iso(0), 'data-due-from="%s"' % iso(3)):
            self.assertIn(attr, blk)
        # 「明日以降」へ戻すときは実施日を決め直す（印と元の予定は外れる＝v1.9）
        rc, out = self.ed("move", "--item", "判定", "--section", "明日以降", "--due", iso(5))
        self.assertEqual(rc, 0, out)
        blk = block_of(self.text(), "判定")[0]
        self.assertIn('data-due="%s"' % iso(5), blk)
        self.assertNotIn("data-due-moved", blk)
        self.assertNotIn("data-due-from", blk)


class TestStatus(Sandbox):
    def test_due_now_and_warning(self):
        self.create(base(("未来", {"due": iso(1)})))
        self.assertEqual(self.status()["due_now"], [])
        self.assertEqual([w for w in self.status()["warnings"] if w["code"] == "K13"], [])
        rc, out = self.ed("add", "--section", "明日以降", "--title", "今日分", "--due", iso(0))
        self.assertEqual(rc, 0, out)
        self.assertEqual([w["code"] for w in out["warnings"]], ["K13"])    # 今日以前を足すと、その場で気づける
        self.ed("add", "--section", "明日以降", "--title", "過去分", "--due", iso(-2) + " 9:00")
        st = self.status()
        self.assertEqual([i["title"] for i in st["due_now"]], ["今日分", "過去分"])
        msg = [w["message"] for w in st["warnings"] if w["code"] == "K13"][0]
        self.assertIn("今日分", msg)
        self.assertIn("過去分", msg)

    def test_done_is_not_due_now(self):
        self.create()
        self.ed("add", "--section", "明日以降", "--title", "済んだ", "--due", iso(0), "--chip", "done")
        self.assertEqual(self.status()["due_now"], [])

    def test_row_on_today_side_is_not_due_now(self):
        self.create()
        self.ed("add", "--section", "明日以降", "--title", "移す", "--due", iso(0))
        self.assertEqual(len(self.status()["due_now"]), 1)
        rc, out = self.ed("move", "--item", "移す", "--section", "今日中")
        self.assertEqual(rc, 0, out)
        self.ed("set-chip", "--item", "移す", "--chip", "pending")
        st = self.status()
        self.assertEqual(st["due_now"], [])
        self.assertEqual(st["progress"]["total"], 5)   # SPEC の4行＋移した行


class TestCreate(Sandbox):
    def test_future_stays_in_tomorrow(self):
        out = self.create(base(("先", {"due": iso(1) + " 9:00"})))
        self.assertEqual(out["moved_due"], [])
        blk, sec = block_of(self.text(), "先")
        self.assertEqual(sec, "明日以降")
        self.assertIn('data-due="%s 9:00"' % iso(1), blk)
        self.assertNotIn("data-due-moved", blk)

    def test_today_with_time_goes_to_plan_in_order(self):
        rows = ({"section": "今日の予定", "time": "9:00", "title": "朝"}, {"section": "今日の予定", "time": "23:00", "title": "夜"})
        out = self.create(base(("昼", {"due": iso(0) + " 12:30"}), today_rows=rows))
        self.assertEqual([m["section"] for m in out["moved_due"]], ["今日の予定"])
        text = self.text()
        blk, sec = block_of(text, "昼")
        self.assertEqual(sec, "今日の予定")
        self.assertIn('<div class="time">12:30</div>', blk)
        self.assertIn('data-due-moved="%s"' % iso(0), blk)
        self.assertIn('class="chip pending"', blk)
        self.assertNotIn(" flat", blk.splitlines()[0])
        self.assertLess(text.index(">朝<"), text.index(">昼<"))
        self.assertLess(text.index(">昼<"), text.index(">夜<"))
        self.assertEqual(self.status()["progress"]["total"], 3)
        self.assertEqual(self.status()["due_now"], [])

    def test_past_or_untimed_goes_to_today_head_without_time(self):
        rows = ({"section": "今日中", "title": "既存"},)
        self.create(base(("過去", {"due": iso(-2) + " 22:05"}), ("当日", {"due": iso(0)}), today_rows=rows))
        text = self.text()
        for t in ("過去", "当日"):
            blk, sec = block_of(text, t)
            self.assertEqual(sec, "今日中")
            self.assertNotIn('class="time"', blk)        # 前の日の時刻を今日の時刻にしない
            self.assertIn('class="chip pending"', blk)
        # 実施日は今日（時刻を付けないので日付だけ）になり、元の実施日は data-due-from に残る（v1.7・Deck v2.11）
        self.assertIn('data-due="%s"' % iso(0), block_of(text, "過去")[0])
        self.assertIn('data-due-from="%s 22:05"' % iso(-2), block_of(text, "過去")[0])
        self.assertLess(text.index(">過去<"), text.index(">当日<"))
        self.assertLess(text.index(">当日<"), text.index(">既存<"))

    def test_done_row_stays(self):
        out = self.create(base(("済", {"due": iso(-1), "chip": "done"})))
        self.assertEqual(out["moved_due"], [])
        self.assertEqual(block_of(self.text(), "済")[1], "明日以降")

    def test_chip_none_becomes_pending_when_moved(self):
        self.create(base(("c", {"due": iso(0), "chip": "none"})))
        self.assertIn('class="chip pending"', block_of(self.text(), "c")[0])

    def test_missing_sections_are_placed_in_order(self):
        self.create({"sections": ["明日以降"], "items": [{"section": "明日以降", "title": "予定", "due": iso(0) + " 10:00"},
                                                       {"section": "明日以降", "title": "中", "due": iso(0)},
                                                       {"section": "明日以降", "title": "残る", "due": iso(1)}]})
        names = [s["name"] for s in self.status()["sections"]]
        self.assertEqual(names, ["今日の予定", "今日中", "明日以降"])

    def test_due_on_today_section_rejected(self):
        p = self.write_spec({"sections": ["今日中"], "items": [{"section": "今日中", "title": "x", "due": iso(0)}]})
        rc, out = run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 1)
        self.assertIn("明日以降", out["error"])
        self.assertFalse(os.path.exists(self.board))

    def test_bad_due_rejected(self):
        p = self.write_spec({"sections": ["明日以降"], "items": [{"section": "明日以降", "title": "x", "due": "2026-02-30"}]})
        rc, out = run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 1)
        self.assertIn("実施日", out["error"])
        self.assertFalse(os.path.exists(self.board))

    def test_time_and_due_rejected(self):
        p = self.write_spec({"sections": ["明日以降"], "items": [{"section": "明日以降", "title": "x", "due": iso(1), "time": "9:00"}]})
        rc, out = run(["create", "--board", self.board, "--spec", p])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.board))

    def test_replacing_old_board_does_not_count_moved_row_as_missing(self):
        self.create(base(("先", {"due": iso(1)})))
        # 同じ行の実施日が今日になった板（実際は翌日に起きる）。消える行の確かめは「明日以降」の行の実施日も比べるので、
        # spec には板と同じ実施日を写す（create が今日の側へ置いても、消える行には数えない）
        self.write(self.text().replace('data-due="%s"' % iso(1), 'data-due="%s"' % iso(0)))
        out = self.create(base(("先", {"due": iso(0)})))
        self.assertEqual(out["removed"], [])
        self.assertEqual([m["title"] for m in out["moved_due"]], ["先"])
        self.assertEqual(block_of(self.text(), "先")[1], "今日中")


class TestRollover(Sandbox):
    """Deck の日付の切り替え。板は今日付けで作り、切り替える日を先へずらして試す"""

    def board_with(self, *later, today_rows=()):
        self.create(base(*later, today_rows=today_rows))
        return self.text()

    def roll(self, text, days):
        return dw.roll_board_text(text, TODAY + timedelta(days=days), "0:00")

    def test_today_with_time_goes_to_plan(self):
        rows = ({"section": "今日の予定", "title": "時刻の無い予定"},)
        t = self.board_with(("判定", {"due": iso(2) + " 22:05"}), today_rows=rows)
        new, info = self.roll(t, 2)
        self.assertEqual(info["due_moved"], 1)
        blk, sec = block_of(new, "判定")
        self.assertEqual(sec, "今日の予定")
        self.assertIn('<div class="time">22:05</div>', blk)
        self.assertIn('class="chip pending"', blk)
        self.assertIn('data-due-moved="%s"' % iso(2), blk)
        self.assertNotIn(" flat", blk.splitlines()[0])
        self.assertNotIn("data-carried-from", blk)
        m = re.search(r"(\d+) / (\d+) 完了", new)
        self.assertEqual(int(m.group(2)), 2)          # 進捗の分母に入る
        # 通知の対象になる
        p = os.path.join(self.dir, "r.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(new)
        self.assertIn("22:05|判定", [a[0] for a in dw.read_board_alarms(p)])

    def test_rows_in_time_order(self):
        t = self.board_with(("遅", {"due": iso(2) + " 22:05"}), ("早", {"due": iso(2) + " 9:00"}), ("間", {"due": iso(2) + " 12:00"}))
        new, _ = self.roll(t, 2)
        self.assertLess(new.index(">早<"), new.index(">間<"))
        self.assertLess(new.index(">間<"), new.index(">遅<"))
        self.assertLess(new.index(">遅<"), new.index('<div class="section-label">今日中'))

    def test_goes_after_untimed_rows_of_plan(self):
        # 済でない時刻付きは今日中へ移るので、切り替えの後の今日の予定に残るのは時刻の無い行だけ＝その後ろへ入る
        t = self.board_with(("中", {"due": iso(2) + " 12:00"}), today_rows=({"section": "今日の予定", "title": "時刻なし"},))
        out, _ = self.roll(t, 2)
        self.assertLess(out.index(">時刻なし<"), out.index(">中<"))

    def test_untimed_goes_to_today(self):
        t = self.board_with(("当日", {"due": iso(2)}))
        new, info = self.roll(t, 2)
        blk, sec = block_of(new, "当日")
        self.assertEqual((sec, info["due_moved"]), ("今日中", 1))
        self.assertNotIn('class="time"', blk)
        self.assertIn('class="chip pending"', blk)
        self.assertEqual(int(re.search(r"(\d+) / (\d+) 完了", new).group(2)), 1)

    def test_many_days_closed_old_time_is_not_today_time(self):
        t = self.board_with(("過去", {"due": iso(2) + " 22:05"}))
        new, _ = self.roll(t, 5)
        blk, sec = block_of(new, "過去")
        self.assertEqual(sec, "今日中")
        self.assertNotIn('class="time"', blk)
        self.assertIn('data-due="%s"' % iso(5), blk)                  # 実施日は今日（日付だけ）・元の実施日は data-due-from（v2.11）
        self.assertIn('data-due-from="%s 22:05"' % iso(2), blk)
        self.assertIn('data-due-moved="%s"' % iso(5), blk)
        p = os.path.join(self.dir, "r.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(new)
        self.assertEqual(dw.read_board_alarms(p), [])

    def test_future_stays(self):
        t = self.board_with(("先", {"due": iso(3)}))
        new, info = self.roll(t, 2)
        self.assertEqual(info["due_moved"], 0)
        blk, sec = block_of(new, "先")
        self.assertEqual(sec, "明日以降")
        self.assertNotIn("data-due-moved", blk)
        self.assertNotIn('class="chip', blk)

    def test_done_stays(self):
        t = self.board_with(("済", {"due": iso(2), "chip": "done"}))
        new, info = self.roll(t, 2)
        self.assertEqual((info["due_moved"], block_of(new, "済")[1]), (0, "明日以降"))

    def test_unreadable_due_stays(self):
        t = self.board_with(("読めない", {"due": iso(2)})).replace('data-due="%s"' % iso(2), 'data-due="いつか"')
        new, info = self.roll(t, 2)
        self.assertEqual((info["due_moved"], block_of(new, "読めない")[1]), (0, "明日以降"))

    def test_no_due_board_is_unchanged_in_tomorrow(self):
        self.create()
        t = self.text()
        new, info = self.roll(t, 2)
        self.assertEqual(info["due_moved"], 0)
        self.assertEqual(block_of(t, "来週の件")[0], block_of(new, "来週の件")[0])
        self.assertEqual(block_of(new, "来週の件")[1], "明日以降")

    def test_dragged_back_row_is_not_moved_again(self):
        t = self.board_with(("戻す", {"due": iso(2)}))
        new, _ = self.roll(t, 2)
        self.assertEqual(block_of(new, "戻す")[1], "今日中")
        # 利用者がドラッグで「明日以降」へ戻す（Deck の D&D）
        moved, code, _msg = dw.apply_board_move(new, "|戻す", "明日以降")
        self.assertEqual(code, 200)
        self.assertEqual(block_of(moved, "戻す")[1], "明日以降")
        self.assertIn('data-due="%s"' % iso(2), block_of(moved, "戻す")[0])
        again, info = self.roll(moved, 3)
        self.assertEqual((info["due_moved"], block_of(again, "戻す")[1]), (0, "明日以降"))

    def test_not_moved_row_is_carried_next_day(self):
        t = self.board_with(("残る", {"due": iso(2) + " 22:05"}))
        new, _ = self.roll(t, 2)
        next_day, _info = self.roll(new, 3)
        blk, sec = block_of(next_day, "残る")
        self.assertEqual(sec, "今日中")
        self.assertIn('data-carried-from="%s"' % iso(2), blk)
        self.assertIn('data-orig-time="22:05"', blk)
        self.assertNotIn('class="time"', blk)
        # 引き継ぐ日にも実施日を今日にする（前の日の時刻は付けない）。元の実施日と印は最初の値のまま（v2.11）
        self.assertIn('data-due="%s"' % iso(3), blk)
        self.assertIn('data-due-from="%s 22:05"' % iso(2), blk)
        self.assertIn('data-due-moved="%s"' % iso(2), blk)
        self.assertEqual(blk.count("data-due-from="), 1)

    def test_same_titles_both_move(self):
        t = self.board_with(("同名", {"due": iso(2)}), ("同名", {"due": iso(2) + " 9:00"}), ("同名", {"due": iso(3)}))
        new, info = self.roll(t, 2)
        self.assertEqual(info["due_moved"], 2)
        secs = [n for (_s, _e, n) in dw._scan_board(new.splitlines(keepends=True))[1]]
        self.assertEqual(secs.count("今日の予定") + secs.count("今日中"), 2)
        self.assertEqual(secs.count("明日以降"), 1)

    def test_crit_and_other_chips_kept(self):
        t = self.board_with(("重要", {"due": iso(2), "crit": True}))
        blk = block_of(t, "重要")[0]
        self.assertIn("重要タスク", blk)
        new, _ = self.roll(t, 2)
        blk = block_of(new, "重要")[0]
        self.assertIn("重要タスク", blk)
        self.assertIn('class="chip pending"', blk)
        self.assertRegex(blk.splitlines()[0], r'class="item[^"]*crit')

    def test_existing_status_chip_is_kept(self):
        t = self.board_with(("進行", {"due": iso(2), "chip": "active"}))
        blk = block_of(self.roll(t, 2)[0], "進行")[0]
        self.assertIn('class="chip active"', blk)
        self.assertNotIn('class="chip pending"', blk)

    def test_sections_created_when_missing(self):
        self.create({"sections": ["明日以降"], "items": [{"section": "明日以降", "title": "予定", "due": iso(2) + " 10:00"},
                                                       {"section": "明日以降", "title": "中", "due": iso(2)}]})
        new, _ = self.roll(self.text(), 2)
        labels = [lb for (_i, lb, _c) in dw._scan_board(new.splitlines(keepends=True))[0]]
        self.assertEqual(labels[:3], ["今日の予定", "今日中", "明日以降"])

    def test_one_line_item_block(self):
        self.create()
        t = self.text()
        one = ('  <div class="item flat" data-due="%s 9:00"><div><p class="task-title">一行</p></div></div>\n' % iso(2))
        lines = t.splitlines(keepends=True)
        s = next(i for i, ln in enumerate(lines) if 'section-label">明日以降' in ln)
        lines.insert(s + 1, one)
        new, info = self.roll("".join(lines), 2)
        self.assertEqual(info["due_moved"], 1)
        blk, sec = block_of(new, "一行")
        self.assertEqual(sec, "今日の予定")
        self.assertIn('<div class="time">9:00</div>', blk)
        self.assertIn('class="chip pending"', blk)
        self.assertTrue(dw.board_structure_ok(new.splitlines(keepends=True)))

    def test_row_with_two_time_elements_stays(self):
        self.create()
        lines = self.text().splitlines(keepends=True)
        s = next(i for i, ln in enumerate(lines) if 'section-label">明日以降' in ln)
        lines.insert(s + 1, '  <div class="item" data-due="%s"><div class="time">1:00</div><div class="time">2:00</div>'
                            '<div><p class="task-title">二つ</p></div></div>\n' % iso(2))
        new, info = self.roll("".join(lines), 2)
        self.assertEqual((info["due_moved"], block_of(new, "二つ")[1]), (0, "明日以降"))

    def test_crlf_board(self):
        t = self.board_with(("改行", {"due": iso(2) + " 9:00"})).replace("\n", "\r\n")
        new, _ = self.roll(t, 2)
        self.assertNotIn("\n", new.replace("\r\n", ""))
        self.assertTrue(dw.board_structure_ok(new.splitlines(keepends=True)))

    def test_result_passes_all_readers(self):
        """切り替えた板を board_edit の検査・ガード・指紋が受け付ける（属性で壊れない）。"""
        t = self.board_with(("a", {"due": iso(2) + " 9:00"}), ("b", {"due": iso(2)}), ("c", {"due": iso(3)}))
        new, _ = self.roll(t, 2)
        self.assertEqual(be.structure_errors(new), [])
        self.assertEqual(guard.shape_codes(new), guard.shape_codes(t))
        self.assertEqual(dw.board_attr(new, "data-tb-rolled-fp"), dw.rolled_fp(new))
        self.assertEqual(be.hand_fingerprint(new), dw.hand_fingerprint(new))
        self.assertEqual(guard.hand_fingerprint(new), dw.hand_fingerprint(new))
        self.write(new)
        self.assertEqual(self.status()["sections"][0]["items"][0]["due_moved"], iso(2))
        rc, out = self.ed("set-chip", "--item", "a", "--chip", "done")   # 板の日付が今日でなくても操作は通る（K4 は意図した日と比べる）
        self.assertEqual(rc, 0, out)

    def test_date_attr_changes_fingerprint(self):
        """実施日を変えるのは手書き部分の変更（引き継いだボードの印が外れる・ガードが見る）。"""
        self.create()
        a = self.text()
        self.ed("set-due", "--item", "来週の件", "--due", iso(2))
        self.assertNotEqual(dw.hand_fingerprint(a), dw.hand_fingerprint(self.text()))


class TestLaterRowsDoNotAlarm(Sandbox):
    """「明日以降」の行は、どの入口で時刻の欄が付いても通知の対象にならない（毎日鳴り続けないため）"""

    def alarms(self, text=None):
        p = os.path.join(self.dir, "a.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.text() if text is None else text)
        return [a[0] for a in dw.read_board_alarms(p)]

    def test_dragged_back_timed_row(self):
        self.create(base(("判定", {"due": iso(2) + " 22:05"})))
        day, _ = dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")
        self.assertEqual(self.alarms(day), ["22:05|判定"])
        back, code, _m = dw.apply_board_move(day, "22:05|判定", "明日以降")
        self.assertEqual(code, 200)
        self.assertIn('class="time"', block_of(back, "判定")[0])
        self.assertEqual(self.alarms(back), [])
        later, info = dw.roll_board_text(back, TODAY + timedelta(days=3), "0:00")
        self.assertEqual((info["due_moved"], block_of(later, "判定")[1]), (0, "明日以降"))
        self.assertEqual(self.alarms(later), [])

    def test_set_time_on_future_due_row(self):
        self.create(base(("先", {"due": iso(2)})))
        rc, out = self.ed("set-time", "--item", "先", "--time", "9:30")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.alarms(), [])
        # その日になれば、行の時刻で今日の予定へ移り、通知の対象になる
        day, _ = dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")
        blk, sec = block_of(day, "先")
        self.assertEqual(sec, "今日の予定")
        self.assertEqual(blk.count('class="time"'), 1)
        self.assertEqual(self.alarms(day), ["9:30|先"])

    def test_add_time_on_later_row(self):
        self.create()
        rc, out = self.ed("add", "--section", "明日以降", "--title", "時刻", "--time", "9:30")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("9:30|時刻", self.alarms())

    def test_other_sections_still_alarm(self):
        self.create({"sections": ["今日の予定", "今日中", "プロジェクトX", "ルーチンタスク", "明日以降"], "items": [
            {"section": "今日の予定", "time": "9:00", "title": "予定"},
            {"section": "今日中", "time": "10:00", "title": "中"},
            {"section": "プロジェクトX", "time": "11:00", "title": "案件"},
            {"section": "ルーチンタスク", "time": "12:00", "title": "定型"},
            {"section": "明日以降", "time": "13:00", "title": "先"}]})
        self.assertEqual(self.alarms(), ["9:00|予定", "10:00|中", "11:00|案件", "12:00|定型"])

    def test_time_element_past_due_goes_to_today_with_orig_time(self):
        self.create(base(("過去", {"due": iso(2)})))
        rc, out = self.ed("set-time", "--item", "過去", "--time", "7:40")
        self.assertEqual(rc, 0, out)
        day, _ = dw.roll_board_text(self.text(), TODAY + timedelta(days=4), "0:00")
        blk, sec = block_of(day, "過去")
        self.assertEqual(sec, "今日中")
        self.assertNotIn('class="time"', blk)
        self.assertNotIn("data-orig-time", blk)                      # 行の時刻は data-due-from に残る（Deck v2.12）
        self.assertIn('data-due-from="%s 7:40"' % iso(2), blk)
        self.assertEqual(self.alarms(day), [])

    def test_set_time_moves_due_time_and_rolls_with_it(self):
        """set-time は実施日の時刻も同じ値にする（v1.7）ので、その日に移るときもその時刻になる。"""
        self.create(base(("両方", {"due": iso(2) + " 22:05"})))
        rc, out = self.ed("set-time", "--item", "両方", "--time", "7:40")
        self.assertEqual(rc, 0, out)
        self.assertIn('data-due="%s 7:40"' % iso(2), block_of(self.text(), "両方")[0])
        day, _ = dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")
        self.assertEqual(self.alarms(day), ["7:40|両方"])


class TestMoveMarks(Sandbox):
    """実施日の来た行を「明日以降」から今日の側へ動かすと印が付く（経路によらない）。実施日の前に動かした行には付かない"""

    MARK = 'data-due-moved="%s"' % TODAY.isoformat()

    def test_move_marks_due_row(self):
        self.create(base(("当日", {"due": iso(1)})))
        self.write(self.text().replace('data-due="%s"' % iso(1), 'data-due="%s"' % iso(0)))
        rc, out = self.ed("move", "--item", "当日", "--section", "今日中")
        self.assertEqual(rc, 0, out)
        self.assertIn(self.MARK, block_of(self.text(), "当日")[0])
        # 戻すときは実施日を決め直し（v1.9）、決めた日より前には移し直さず、その日に移す
        rc, out = self.ed("move", "--item", "当日", "--section", "明日以降", "--due", iso(2))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("data-due-moved", block_of(self.text(), "当日")[0])
        self.assertEqual(self.status()["due_now"], [])
        self.assertEqual(dw.roll_board_text(self.text(), TODAY + timedelta(days=1), "0:00")[1]["due_moved"], 0)
        self.assertEqual(dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")[1]["due_moved"], 1)

    def test_move_before_due_makes_a_today_row(self):
        """実施日の前に動かした行も今日の行になり、印が付く（v1.9・Deck v2.13・2026-11-06 ユーザー決定）。
        「明日以降」へ戻すときは実施日を決め直す（未定なら実施日の無い行になり、日付の切り替えは移さない）。"""
        self.create(base(("先", {"due": iso(2)})))
        self.ed("move", "--item", "先", "--section", "今日中")
        blk = block_of(self.text(), "先")[0]
        for attr in (self.MARK, 'data-due="%s"' % iso(0), 'data-due-from="%s"' % iso(2)):
            self.assertIn(attr, blk)
        self.ed("move", "--item", "先", "--section", "明日以降", "--due", "none")
        blk = block_of(self.text(), "先")[0]
        for attr in ("data-due=", "data-due-moved", "data-due-from"):
            self.assertNotIn(attr, blk)
        new, info = dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")
        self.assertEqual(info["due_moved"], 0)
        self.assertEqual(block_of(new, "先")[1], "明日以降")

    def test_rollover_fixes_rows_moved_early_by_older_versions(self):
        """v1.8・Deck v2.12 までに先の日の行を前もって今日の側へ動かした行（実施日が先の日のまま・印なし）は、
        次の日付の切り替えで今日の行の形になる（実施日はその日・元の予定は data-due-from・印＝Deck v2.13 の _carry_due_today）。"""
        self.create(base(("前倒し", {"due": iso(3) + " 10:00"})))
        self.ed("move", "--item", "前倒し", "--section", "今日中")
        self.put_legacy_early("前倒し", iso(3) + " 10:00")
        blk = block_of(self.text(), "前倒し")[0]
        self.assertNotIn("data-due-moved", blk)
        self.assertNotIn("data-due-from", blk)
        new, _info = dw.roll_board_text(self.text(), TODAY + timedelta(days=1), "0:00")
        blk, sec = block_of(new, "前倒し")
        self.assertEqual(sec, "今日中")
        for attr in ('data-due="%s"' % iso(1), 'data-due-moved="%s"' % iso(1), 'data-due-from="%s 10:00"' % iso(3)):
            self.assertIn(attr, blk)
        # 実施日の日の切り替えでも、時刻の無い今日の行のまま（鳴らさない）
        again, _info = dw.roll_board_text(new, TODAY + timedelta(days=3), "0:00")
        blk, sec = block_of(again, "前倒し")
        self.assertEqual(sec, "今日中")
        self.assertIn('data-due="%s"' % iso(3), blk)
        self.assertNotIn('class="time"', blk)

    def test_move_within_later_is_not_marked(self):
        self.create(base(("x", {"due": iso(1)}), ("y", {})))
        self.write(self.text().replace('data-due="%s"' % iso(1), 'data-due="%s"' % iso(0)))
        rc, out = self.ed("move", "--item", "x", "--section", "明日以降")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("data-due-moved", block_of(self.text(), "x")[0])

    def test_done_row_is_not_marked(self):
        self.create()
        self.ed("add", "--section", "明日以降", "--title", "済", "--due", iso(0), "--chip", "done")
        self.ed("move", "--item", "済", "--section", "今日中")
        self.assertNotIn("data-due-moved", block_of(self.text(), "済")[0])

    def test_deck_drag_marks_due_row(self):
        self.create(base(("当日", {"due": iso(2)}), ("先", {"due": iso(3)})))
        t = self.text()
        day = TODAY + timedelta(days=2)
        new, code, _m = dw.apply_board_move(t, "|当日", "今日中", today=day)
        self.assertEqual(code, 200)
        self.assertIn('data-due-moved="%s"' % iso(2), block_of(new, "当日")[0])
        back, code, _m = dw.apply_board_move(new, "|当日", "明日以降", today=day)
        self.assertEqual(code, 200)
        self.assertEqual(dw.roll_board_text(back, day + timedelta(days=1), "0:00")[1]["due_moved"], 1)  # 「先」だけ
        self.assertEqual(block_of(dw.roll_board_text(back, day + timedelta(days=1), "0:00")[0], "当日")[1], "明日以降")
        new2, code, _m = dw.apply_board_move(t, "|先", "今日中", today=day)
        self.assertEqual(code, 200)
        blk = block_of(new2, "先")[0]          # 実施日の前の行も今日の行になり、印が付く（v2.13）
        for attr in ('data-due-moved="%s"' % iso(2), 'data-due="%s"' % iso(2), 'data-due-from="%s"' % iso(3)):
            self.assertIn(attr, blk)


class TestMoveBackToLater(Sandbox):
    """今日の予定・今日中の行を「明日以降」へ動かすときは、実施日をユーザーが決める（move --due・D&D の "due"・2026-11-06 ユーザー決定・
    board_edit.py v1.9・Deck v2.13）。実施日はその値にし、印と元の実施日を外す。行の時刻は1つ（時刻の欄は決めた時刻か、無ければ外す）。
    未定は実施日・印・元の実施日を外し、時刻の欄は変えない。D&D の反映は move と同じ形。"""

    def later_board(self):
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日の予定", "time": "15:00", "title": "会議"},
            {"section": "今日中", "title": "前倒し", "due": iso(0), "due_moved": iso(0), "due_from": iso(3) + " 10:00"},
            {"section": "今日中", "title": "ふつう"},
            {"section": "明日以降", "title": "いつか"}]})
        return self.text()

    def attrs(self, text, title):
        blk, sec = block_of(text, title)
        head = blk.split(">", 1)[0]
        get = lambda n: (re.search(r'\s%s="([^"]*)"' % n, head) or [None, None])[1]
        return (sec, get("data-due"), get("data-due-moved"), get("data-due-from"), re.findall(r'class="time">([^<]*)<', blk),
                " flat" in " " + re.search(r'class="([^"]*)"', head).group(1) + " ")

    def both(self, start, key, due):
        """move --due と D&D の反映（due）で同じ行になることを確かめ、move の後の板を返す。"""
        deck, code, msg = dw.apply_board_move(start, key, "明日以降", due=None if due == "none" else due, set_due=True)
        self.assertEqual(code, 200, msg)
        self.write(start)
        rc, out = self.ed("move", "--item", key, "--section", "明日以降", "--due", due)
        self.assertEqual(rc, 0, out)
        title = key.split("|", 1)[1]
        self.assertEqual(block_of(deck, title), block_of(self.text(), title), (key, due))
        return self.text()

    def test_date_with_time_aligns_time_field(self):
        start = self.later_board()
        t = self.both(start, "15:00|会議", iso(2) + " 9:30")
        self.assertEqual(self.attrs(t, "会議"), ("明日以降", iso(2) + " 9:30", None, None, ["9:30"], False))
        t = self.both(start, "|前倒し", iso(4) + " 8:00")       # 時刻の欄の無い行には足さない。印と元の実施日は外す
        self.assertEqual(self.attrs(t, "前倒し"), ("明日以降", iso(4) + " 8:00", None, None, [], True))

    def test_date_only_removes_time_field(self):
        t = self.both(self.later_board(), "15:00|会議", iso(2))
        self.assertEqual(self.attrs(t, "会議"), ("明日以降", iso(2), None, None, [], True))

    def test_undecided_removes_due_and_keeps_time_field(self):
        start = self.later_board()
        t = self.both(start, "15:00|会議", "none")
        self.assertEqual(self.attrs(t, "会議"), ("明日以降", None, None, None, ["15:00"], False))
        t = self.both(start, "|前倒し", "none")
        self.assertEqual(self.attrs(t, "前倒し"), ("明日以降", None, None, None, [], True))
        self.assertEqual(self.status()["due_now"], [])

    def test_deck_moves_it_on_the_decided_day(self):
        self.both(self.later_board(), "|前倒し", iso(2) + " 10:00")
        new, info = dw.roll_board_text(self.text(), TODAY + timedelta(days=1), "0:00")
        self.assertEqual(block_of(new, "前倒し")[1], "明日以降")
        new, info = dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")
        self.assertEqual((info["due_moved"], block_of(new, "前倒し")[1]), (1, "今日の予定"))
        self.assertIn('<div class="time">10:00</div>', block_of(new, "前倒し")[0])

    def test_refusals(self):
        start = self.later_board()
        for args, word in ((("--item", "|ふつう", "--section", "明日以降"), "--due で実施日を指定してください"),
                           (("--item", "|ふつう", "--section", "明日以降", "--due", iso(0)), "今日以前"),
                           (("--item", "|ふつう", "--section", "明日以降", "--due", iso(-1) + " 9:00"), "今日以前"),
                           (("--item", "|ふつう", "--section", "明日以降", "--due", "来週"), "使えません"),
                           (("--item", "|ふつう", "--section", "今日の予定", "--due", iso(2)), "だけ使えます"),
                           (("--item", "|いつか", "--section", "明日以降", "--due", iso(2)), "だけ使えます")):
            rc, out = self.ed("move", *args)
            self.assertEqual(rc, 1, (args, out))
            self.assertIn(word, out["error"], args)
            self.assertEqual(self.text(), start, args)
        for bad in (iso(0), iso(-1), "来週", "2026-02-30"):
            new, code, _m = dw.apply_board_move(start, "|ふつう", "明日以降", due=bad, set_due=True)
            self.assertEqual((new, code), (None, 400), bad)
        # due の無い要求（v2.12 と同時の board.js）は従来どおり形を変えない
        new, code, _m = dw.apply_board_move(start, "|前倒し", "明日以降")
        self.assertEqual(code, 200)
        self.assertEqual(self.attrs(new, "前倒し")[1:4], (iso(0), iso(0), iso(3) + " 10:00"))
        # 「明日以降」の中の並べ替えと、「明日以降」から今日の側へは due を見ない
        new, code, _m = dw.apply_board_move(start, "|いつか", "明日以降", due=iso(0), set_due=True)
        self.assertEqual(code, 200)


class TestSkillProcedure(Sandbox):
    """SKILL.md update モード 9 の手順を実物で通す"""

    def add_due(self, title, due):
        rc, out = self.ed("add", "--section", "明日以降", "--title", title, "--due", due)
        self.assertEqual(rc, 0, out)

    def test_timed_row_into_plan_in_order(self):
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日の予定", "time": "9:00", "title": "朝"}, {"section": "今日の予定", "time": "23:00", "title": "夜"}]})
        self.add_due("昼", iso(0) + " 12:30")
        self.assertEqual([i["title"] for i in self.status()["due_now"]], ["昼"])
        # move だけで時刻の欄・時刻の順の位置・未チップ・印がそろう（set-time・set-chip・--before は要らない）
        rc, out = self.ed("move", "--item", "昼", "--section", "今日の予定")
        self.assertEqual(rc, 0, out)
        st = self.status()
        self.assertEqual(st["due_now"], [])
        self.assertEqual([w["code"] for w in st["warnings"]], [])
        rows = st["sections"][0]["items"]
        self.assertEqual([(i["time"], i["title"], i["chip"]) for i in rows],
                         [("9:00", "朝", "pending"), ("12:30", "昼", "pending"), ("23:00", "夜", "pending")])
        self.assertEqual(rows[1]["due_moved"], iso(0))
        self.assertEqual(st["progress"]["total"], 3)

    def test_untimed_row_to_today_head_keeps_hold_chip(self):
        self.create({"sections": ["今日中", "明日以降"], "items": [{"section": "今日中", "title": "既存"}]})
        rc, out = self.ed("add", "--section", "明日以降", "--title", "保留", "--due", iso(0), "--chip", "hold")
        self.assertEqual(rc, 0, out)
        st = self.status()
        self.assertEqual(st["due_now"][0]["chip"], "hold")      # chip が none でないので set-chip しない
        rc, out = self.ed("move", "--item", "保留", "--section", "今日中", "--head")
        self.assertEqual(rc, 0, out)
        rows = self.status()["sections"][0]["items"]
        self.assertEqual([(i["title"], i["chip"]) for i in rows], [("保留", "hold"), ("既存", "pending")])

    def test_no_plan_section(self):
        self.create({"sections": ["今日中", "明日以降"], "items": [{"section": "明日以降", "title": "予定", "due": iso(1)}]})
        self.write(self.text().replace('data-due="%s"' % iso(1), 'data-due="%s 12:30"' % iso(0)))
        before = self.read()
        rc, out = self.ed("move", "--item", "予定", "--section", "今日の予定")
        self.assertEqual(rc, 1)
        self.assertIn("--create-section", out["error"])
        self.assertUnchanged(before)
        # SKILL.md update モード 9: 元の行を先に消してから、実施日と今日の日付の印を付けて足す
        due = self.status()["due_now"][0]["due"]
        rc, out = self.ed("remove", "--item", "|予定", "--confirmed")
        self.assertEqual(rc, 0, out)
        rc, out = self.ed("add", "--section", "今日の予定", "--create-section", "--time", "12:30", "--title", "予定",
                          "--due", due, "--due-moved", iso(0))
        self.assertEqual(rc, 0, out)
        st = self.status()
        self.assertEqual(st["due_now"], [])
        self.assertEqual([s["name"] for s in st["sections"]], ["今日の予定", "今日中", "明日以降"])
        it = st["sections"][0]["items"][0]
        self.assertEqual((it["time"], it["due"], it["due_moved"]), ("12:30", iso(0) + " 12:30", iso(0)))


class TestMisc(Sandbox):
    def test_empty_due_rejected(self):
        self.create()
        before = self.read()
        rc, out = self.ed("add", "--section", "明日以降", "--title", "x", "--due", "")
        self.assertEqual(rc, 1)
        self.assertIn("実施日", out["error"])
        rc, out = self.ed("add", "--section", "今日中", "--title", "x", "--due=")
        self.assertEqual(rc, 1)
        self.assertUnchanged(before)
        p = self.write_spec({"sections": ["明日以降"], "items": [{"section": "明日以降", "title": "x", "due": ""}]})
        rc, out = run(["create", "--board", os.path.join(self.dir, "other.html"), "--spec", p])
        self.assertEqual(rc, 1)
        self.assertIn("実施日", out["error"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "other.html")))

    def test_null_due_in_spec_is_no_due(self):
        self.create(base(("n", {"due": None})))
        self.assertNotIn("data-due", block_of(self.text(), "n")[0])

    def test_hold_row_does_not_get_pending(self):
        self.create(base(("保留", {"due": iso(2), "chip": "hold"})))
        blk = block_of(dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")[0], "保留")[0]
        self.assertIn('class="chip hold"', blk)
        self.assertNotIn('class="chip pending"', blk)

    def test_no_k13_for_today_side_row(self):
        self.create()
        self.write(re.sub(r'(<div class="item flat")(>\s*<div>\s*<p class="task-title">作業A)', r'\1 data-due="%s"\2' % iso(-1), self.text()))
        st = self.status()
        self.assertEqual(st["due_now"], [])
        self.assertEqual([w["code"] for w in st["warnings"]], [])


class TestCarriedTime(Sandbox):
    """引き継ぎのチップの時刻（data-orig-time）は data-carried-from と組（引き継いだ日のその行の時刻・Deck v2.12）。
    D&D・move が時刻の欄を外したときに残した data-orig-time（実施日の時刻）は、引き継ぐときに外す。"""

    def roll(self, text, days):
        return dw.roll_board_text(text, TODAY + timedelta(days=days), "0:00")

    def test_early_moved_future_row_does_not_carry_its_due_time(self):
        # 先の日（+2 の 9:00）の行を、時刻の欄つきで今日中へ前もって動かす。move は時刻の欄を外し、data-orig-time には残さない（v1.8）。
        # 実施日は今日になり、元の予定は data-due-from に残る（v1.9）
        self.create(base(("前倒し", {"due": iso(2) + " 9:00"})))
        t = re.sub(r'(<div class="item[^"]*"[^>]*>)(\s*<div>\s*<p class="task-title">前倒し</p>)',
                   r'\1<div class="time">9:00</div>\2', self.text(), count=1)
        self.write(t)
        rc, out = self.ed("move", "--item", "9:00|前倒し", "--section", "今日中")
        self.assertEqual(rc, 0, out)
        blk = block_of(self.text(), "前倒し")[0]
        self.assertNotIn("data-orig-time", blk)
        self.assertIn('data-due="%s"' % iso(0), blk)
        self.assertIn('data-due-from="%s 9:00"' % iso(2), blk)                  # 行の時刻は元の予定に残る
        # v1.7 までの move・v2.11 までの D&D が残した data-orig-time（実施日の時刻）を持つ板も、引き継ぐときに外す
        self.write(self.text().replace(blk, blk.replace('data-due="%s"' % iso(0), 'data-due="%s" data-orig-time="9:00"' % iso(0), 1), 1))
        self.assertIn('data-orig-time="9:00"', block_of(self.text(), "前倒し")[0])
        new, _ = self.roll(self.text(), 1)
        blk, sec = block_of(new, "前倒し")
        self.assertEqual(sec, "今日中")
        self.assertIn('data-carried-from="%s"' % iso(0), blk)
        self.assertNotIn("data-orig-time", blk)            # 9:00 は +2 の時刻で、引き継いだ日（今日）の時刻ではない
        self.assertIn('data-due="%s"' % iso(1), blk)       # 引き継いだ日の実施日になる
        self.assertIn('data-due-from="%s 9:00"' % iso(2), blk)  # 元の予定はそのまま
        # 次の日も足さない（data-carried-from が既にある）
        again, _ = self.roll(new, 2)
        self.assertNotIn("data-orig-time", block_of(again, "前倒し")[0])

    def test_fresh_carry_overwrites_stale_orig_time(self):
        # 今日の予定の時刻つきの行に、前から data-orig-time が残っている。引き継いだ日のその行の時刻にする
        self.create(base(today_rows=({"section": "今日の予定", "time": "10:30", "title": "付け直した"},)))
        t, k = re.subn(r'(<div class="item[^"]*")([^>]*>\s*<div class="time">10:30)', r'\1 data-orig-time="8:00"\2', self.text(), count=1)
        self.assertEqual(k, 1)
        new, _ = self.roll(t, 1)
        blk = block_of(new, "付け直した")[0]
        self.assertIn('data-orig-time="10:30"', blk)
        self.assertEqual(blk.count("data-orig-time="), 1)

    def test_recarry_does_not_pair_a_later_time_with_the_first_date(self):
        # 引き継いだ行（data-carried-from あり）に次の日に時刻を付けて今日の予定へ置き、また引き継ぐ。
        # data-carried-from は最初の日のままなので、後の日の時刻を組にしない
        self.create(base(today_rows=({"section": "今日中", "title": "残り"},)))
        first, _ = self.roll(self.text(), 1)
        self.assertIn('data-carried-from="%s"' % iso(0), block_of(first, "残り")[0])
        self.write(first)
        rc, out = self.ed("move", "--item", "残り", "--section", "今日の予定")
        self.assertEqual(rc, 0, out)
        rc, out = self.ed("set-time", "--item", "残り", "--time", "11:00")
        self.assertEqual(rc, 0, out)
        timed, sec = block_of(self.text(), "残り")
        self.assertEqual(sec, "今日の予定")
        self.assertIn('<div class="time">11:00</div>', timed)
        second, _ = self.roll(self.text(), 2)
        blk2, sec2 = block_of(second, "残り")
        self.assertEqual(sec2, "今日中")
        self.assertIn('data-carried-from="%s"' % iso(0), blk2)
        self.assertNotIn("data-orig-time", blk2)
        self.assertNotIn('class="time"', blk2)


class TestCarriedDueFromTime(Sandbox):
    """日付の切り替えで今日の側から引き継ぐ行の元の実施日（data-due-from）の時刻は、行の時刻（時刻の欄が H:MM ならその時刻、
    無ければ実施日の時刻）。_due_moved_shape と同じ（Deck v2.12）。"""

    def test_rollover_uses_the_row_time(self):
        rows = ({"section": "今日の予定", "time": "10:30", "title": "食い違う予定"},
                {"section": "今日中", "title": "時刻なし"})
        self.create(base(today_rows=rows))
        t = self.text()
        # 時刻の欄（10:30）と実施日の時刻（9:00）が違う、前の日の実施日の行（v1.6 までの操作でできた行）を手で作る
        t, k1 = re.subn(r'(<div class="item[^"]*")([^>]*>\s*<div class="time">10:30)',
                        r'\1 data-due="%s 9:00" data-due-moved="%s"\2' % (iso(-1), iso(-1)), t, count=1)
        t, k2 = re.subn(r'(<div class="item[^"]*")([^>]*>\s*<div>\s*<p class="task-title">時刻なし)',
                        r'\1 data-due="%s 8:15" data-due-moved="%s"\2' % (iso(-1), iso(-1)), t, count=1)
        self.assertEqual((k1, k2), (1, 1))
        new, _ = dw.roll_board_text(t, TODAY + timedelta(days=1), "0:00")
        blk = block_of(new, "食い違う予定")[0]
        self.assertIn('data-due-from="%s 10:30"' % iso(-1), blk)     # 外した時刻の欄の時刻
        self.assertIn('data-due="%s"' % iso(1), blk)
        self.assertIn('data-orig-time="10:30"', blk)
        self.assertIn('data-due-from="%s 8:15"' % iso(-1), block_of(new, "時刻なし")[0])   # 時刻の欄が無ければ実施日の時刻


class TestRolledCounts(Sandbox):
    """「引き継いだボード」の件数は、切り替えた件数を .board に持たせる（data-tb-rolled-carried・data-tb-rolled-due・Deck v2.12）"""

    def test_counts_are_what_the_rollover_did(self):
        rows = ({"section": "今日中", "title": "残り1"}, {"section": "今日中", "title": "残り2"},
                {"section": "今日の予定", "time": "9:00", "title": "予定"})
        self.create(base(("来た", {"due": iso(1)}), ("来た時刻", {"due": iso(1) + " 22:05"}), ("先", {"due": iso(5)}),
                         today_rows=rows))
        new, info = dw.roll_board_text(self.text(), TODAY + timedelta(days=1), "0:00")
        self.assertEqual((info["carried"], info["due_moved"]), (3, 2))
        self.assertEqual(dw.board_attr(new, "data-tb-rolled"), iso(0))
        self.assertEqual(dw.board_attr(new, "data-tb-rolled-carried"), "3")
        self.assertEqual(dw.board_attr(new, "data-tb-rolled-due"), "2")
        self.assertIsNotNone(dw.board_attr(new, "data-tb-rolled-fp"))
        # 重ねて切り替えると、新しい切り替えの件数になる（前の値は残らない）
        again, info2 = dw.roll_board_text(new, TODAY + timedelta(days=2), "0:00")
        self.assertEqual(dw.board_attr(again, "data-tb-rolled-carried"), str(info2["carried"]))
        self.assertEqual(dw.board_attr(again, "data-tb-rolled-due"), "0")
        self.assertEqual(len(re.findall(r'data-tb-rolled-due="', again)), 1)
        self.assertEqual(len(re.findall(r'data-tb-rolled-carried="', again)), 1)

    def test_counts_go_with_the_mark(self):
        self.create(base(("来た", {"due": iso(1)}), today_rows=({"section": "今日中", "title": "残り"},)))
        new, _ = dw.roll_board_text(self.text(), TODAY + timedelta(days=1), "0:00")
        p = os.path.join(self.dir, "counts.html")
        dw.derive_header(new, p, 0)
        same = dw.derive_header(new, p, 0)
        self.assertEqual(dw.board_attr(same, "data-tb-rolled-due"), "1")       # 誰も触らなければ外さない
        self.assertEqual(dw.board_attr(same, "data-tb-rolled-carried"), "1")
        # 手書き部分を変えると、印と一緒に件数も外す
        edited = new.replace("残り</p>", "残り（直した）</p>", 1)
        self.assertNotEqual(edited, new)
        out = dw.derive_header(edited, p, 0)
        for a in ("data-tb-rolled", "data-tb-rolled-fp", "data-tb-rolled-carried", "data-tb-rolled-due"):
            self.assertIsNone(dw.board_attr(out, a), a)
        # 印が無いのに件数だけ残っている板（書き写し等）は片付ける
        for a in ("data-tb-rolled-due", "data-tb-rolled-carried"):
            orphan = dw.set_board_attrs(self.text(), add=((a, "4"),))
            self.assertEqual(dw.board_attr(orphan, a), "4")
            q = os.path.join(self.dir, "orphan-%s.html" % a)
            self.assertIsNone(dw.board_attr(dw.derive_header(orphan, q, 0), a), a)


if __name__ == "__main__":
    unittest.main()
