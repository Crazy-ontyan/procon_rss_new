import datetime as dt
import unittest

import procon_checker as checker


class DeadlineExtractionTests(unittest.TestCase):
    def setUp(self):
        self.source = {"title": "本選実施要項", "url": "https://example.test/guide.pdf"}

    def test_extracts_last_date_from_submission_period(self):
        text = "1.6 提出書類等\n9月1日(月)17:00 締切分\n令和8年8月25日(月) 8:30 から 9月1日(月) 17:00 までの期間に提出してください。\nパンフレット原稿"
        deadlines = checker.extract_deadlines(text, self.source, 2026)
        self.assertTrue(any(item["due"] == "2026-09-01T17:00:00+09:00" for item in deadlines))
        self.assertFalse(any(item["due"].startswith("2026-08-25") for item in deadlines))

    def test_understands_reiwa_and_date_without_time(self):
        text = "予選応募期間\n令和8年5月18日（月）08:30\n～5月25日（月）17:00\n応募期限です"
        deadlines = checker.extract_deadlines(text, self.source, 2026)
        self.assertEqual(deadlines[0]["due"], "2026-05-25T17:00:00+09:00")

    def test_ignores_other_year(self):
        self.assertEqual(checker.extract_deadlines("提出締切は令和7年9月1日17:00です", self.source, 2026), [])

    def test_reminder_threshold(self):
        self.assertEqual(checker.reminder_threshold(10), 14)
        self.assertEqual(checker.reminder_threshold(7), 7)
        self.assertEqual(checker.reminder_threshold(2), 3)
        self.assertEqual(checker.reminder_threshold(0), 0)
        self.assertIsNone(checker.reminder_threshold(-1))

    def test_default_time_is_end_of_day(self):
        parsed = checker.parse_date(checker.DATE_RE.search("2026年5月25日"), 2026)
        self.assertEqual(parsed, dt.datetime(2026, 5, 25, 23, 59, tzinfo=checker.JST))

    def test_does_not_treat_section_numbers_as_dates(self):
        text = "1.5 日程 1.6 提出書類等 [1] 9月1日(火)17:00 締切分 [2] 10月2日(金)17:00 締切分 1.7 知的財産権"
        due = {item["due"] for item in checker.extract_deadlines(text, self.source, 2026)}
        self.assertEqual(due, {"2026-09-01T17:00:00+09:00", "2026-10-02T17:00:00+09:00"})

    def test_does_not_partially_match_day(self):
        text = "【参加登録・応募期間】令和8年5月18日（月）8:30 ～ 5月25日（月）17:00"
        due = [item["due"] for item in checker.extract_deadlines(text, self.source, 2026)]
        self.assertEqual(due, ["2026-05-25T17:00:00+09:00"])

    def test_associates_start_and_deadline_labels(self):
        text = "システム等の調書登録 開始：8月25日（火）8:30 締切：9月1日（火）17:00"
        due = [item["due"] for item in checker.extract_deadlines(text, self.source, 2026)]
        self.assertEqual(due, ["2026-09-01T17:00:00+09:00"])

    def test_chooses_deadline_not_later_delivery_date(self):
        text = "入力〆切日：10月5日(月)17:00まで URL システムの搬送は10月9日(金)の16:00～18:00"
        due = [item["due"] for item in checker.extract_deadlines(text, self.source, 2026)]
        self.assertEqual(due, ["2026-10-05T17:00:00+09:00"])

    def test_parses_hour_kanji_format(self):
        parsed = checker.parse_date(checker.DATE_RE.search("8月28日(金)23時59分"), 2026)
        self.assertEqual(parsed, dt.datetime(2026, 8, 28, 23, 59, tzinfo=checker.JST))

    def test_deadline_with_spaces_after_gregorian_year(self):
        text = "システム稼働開始日時：2026 年7月1日10時00分 参加登録・入金締切日：2026 年 8月28日23時59分"
        due = [item["due"] for item in checker.extract_deadlines(text, self.source, 2026)]
        self.assertEqual(due, ["2026-08-28T23:59:00+09:00"])


if __name__ == "__main__":
    unittest.main()
