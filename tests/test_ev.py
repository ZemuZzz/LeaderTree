# -*- coding: utf-8 -*-
"""风控 ev 计算的单元测试（对照前端 ev.js 的真实输出）"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ObjDict import ObjDict
from commander import Commander
from zd_utils import getEv


class GetEvTest(unittest.TestCase):
    """这些期望值是用前端 ev.js 在 node 里跑出来的"""

    def test_vector_basic(self):
        self.assertEqual(getEv([1, 2, 3, 4, "你"]), "4b41424f475150414f1a")

    def test_vector_course_ids(self):
        self.assertEqual(
            getEv([465101, 12, 0, 1000010466, 998877]),
            "4e4c4545445b5f4b484b444f5b544a4a4045445e524c41494d4c52534d")

    def test_vector_mixed(self):
        self.assertEqual(getEv([465101, "a", 0]), "4e4c4545445b5f1b4140")


def _context():
    video = ObjDict({"chapterId": 556677, "lessonId": 112233, "id": 0,
                     "videoId": 445566, "videoSec": 600},
                    default=None)
    return ObjDict({
        "course": {"recruitId": 465101},
        "chapters": {"courseId": 1000010466},
        "videos": {445566: video},
    }, default=None)


class EvLogTest(unittest.TestCase):
    def setUp(self):
        self.commander = Commander(proxies={})
        self.commander.getZhidaoContext = lambda *a, **k: _context()
        self.captured = {}

        def fake_query(url, data=None, **kwargs):
            self.captured["data"] = data
            return ObjDict({"code": 0, "data": {"studiedLessonDto": {"id": 1}}}, default=None)

        self.commander.zhidaoQuery = fake_query

    def test_prelearning_note_sets_ev(self):
        self.commander.prelearningNote("RAC", 445566)
        expected = getEv([465101, 112233, 0, 445566, 556677])
        self.assertEqual(self.commander.ev_log, expected)

    def test_save_cache_sets_ev(self):
        self.commander.saveCacheIntervalTime("RAC", 445566, 120, 60, "0,1,26", token_id="tok")
        ev = self.captured["data"]["ev"]
        self.assertTrue(ev)
        self.assertEqual(self.commander.ev_log, ev)

    def test_save_database_sets_ev(self):
        self.commander.saveDatabaseIntervalTime("RAC", 445566, 120, 60, "0,1,26", token_id="tok")
        ev = self.captured["data"]["ev"]
        self.assertEqual(self.commander.ev_log, ev)


if __name__ == "__main__":
    unittest.main()
