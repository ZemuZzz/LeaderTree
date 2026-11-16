# -*- coding: utf-8 -*-
"""配置补全逻辑的单元测试"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import fillDefaults


class FillDefaultsTest(unittest.TestCase):
    def test_adds_missing_nested(self):
        target = {"captcha": {"solver": "auto"}}
        defaults = {
            "captcha": {"solver": "auto", "vision": {"enabled": False}},
            "homework": {"answer": {"api_key": ""}},
        }
        self.assertTrue(fillDefaults(target, defaults))
        self.assertEqual(target["captcha"]["solver"], "auto")
        self.assertIn("vision", target["captcha"])
        self.assertEqual(target["homework"]["answer"]["api_key"], "")

    def test_does_not_override(self):
        target = {"captcha": {"solver": "manual"}, "ai": {"enabled": False}}
        defaults = {"captcha": {"solver": "auto", "vision": {}}, "ai": {"enabled": True}}
        fillDefaults(target, defaults)
        self.assertEqual(target["captcha"]["solver"], "manual")
        self.assertFalse(target["ai"]["enabled"])
        self.assertIn("vision", target["captcha"])

    def test_no_change(self):
        target = {"a": {"b": 1}}
        self.assertFalse(fillDefaults(target, {"a": {"b": 2}}))

    def test_returns_false_when_complete(self):
        target = {"a": 1, "b": {"c": 2}}
        self.assertFalse(fillDefaults(target, {"a": 1, "b": {"c": 2}}))


if __name__ == "__main__":
    unittest.main()
