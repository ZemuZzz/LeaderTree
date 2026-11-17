# -*- coding: utf-8 -*-
"""多账号 profile 的单元测试"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = utils.getDir
        utils.getDir = lambda: self.tmp
        utils.setProfile(None)

    def tearDown(self):
        utils.setProfile(None)
        utils.getDir = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prescan_space_form(self):
        self.assertEqual(utils.prescanProfile(["-c", "x", "--profile", "alice"]), "alice")

    def test_prescan_equals_form(self):
        self.assertEqual(utils.prescanProfile(["--profile=bob"]), "bob")

    def test_prescan_missing(self):
        self.assertIsNone(utils.prescanProfile(["-c", "x"]))

    def test_prescan_ignores_flag_value(self):
        self.assertIsNone(utils.prescanProfile(["--profile", "--debug"]))

    def test_no_profile_paths(self):
        self.assertIsNone(utils.getProfile())
        self.assertEqual(utils.getConfigPath(), os.path.join(self.tmp, "config.json"))
        self.assertEqual(utils.getStatePath("cookies.json"),
                         os.path.join(self.tmp, "cookies.json"))

    def test_profile_paths(self):
        utils.setProfile("alice")
        base = os.path.join(self.tmp, "profiles", "alice")
        self.assertEqual(utils.getProfile(), "alice")
        self.assertEqual(utils.getConfigPath(), os.path.join(base, "config.json"))
        self.assertEqual(utils.getStatePath("cookies.json"), os.path.join(base, "cookies.json"))
        self.assertTrue(os.path.isdir(base))

    def test_switch_and_reset(self):
        utils.setProfile("alice")
        utils.setProfile("bob")
        self.assertEqual(utils.getProfile(), "bob")
        utils.setProfile(None)
        self.assertIsNone(utils.getProfile())

    def test_blank_name_resets(self):
        utils.setProfile("alice")
        utils.setProfile("   ")
        self.assertIsNone(utils.getProfile())


class ProfileManageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = utils.getDir
        utils.getDir = lambda: self.tmp
        utils.setProfile(None)

    def tearDown(self):
        utils.setProfile(None)
        utils.getDir = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_resolve_from_argv(self):
        self.assertEqual(utils.resolveProfile(["--profile", "x"]), "x")

    def test_resolve_default_from_config(self):
        with io.open(os.path.join(self.tmp, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"default_profile": "dflt"}, f)
        self.assertEqual(utils.resolveProfile([]), "dflt")

    def test_resolve_no_config(self):
        self.assertIsNone(utils.resolveProfile([]))

    def test_list_and_describe(self):
        utils.setProfile("alice")
        with io.open(utils.getStatePath("cookies.json"), "w", encoding="utf-8") as f:
            json.dump({"uuid": "u"}, f)
        with io.open(utils.getStatePath("config.json"), "w", encoding="utf-8") as f:
            json.dump({}, f)
        utils.setProfile(None)
        self.assertEqual(utils.listProfiles(), ["alice"])
        rows = utils.describeProfiles()
        self.assertEqual(rows[0]["name"], "alice")
        self.assertTrue(rows[0]["logged"])
        self.assertTrue(rows[0]["config"])
        self.assertGreater(rows[0]["mtime"], 0)

    def test_safe_profile_name(self):
        self.assertIsNone(utils.safeProfileName("../etc"))
        self.assertIsNone(utils.safeProfileName("a/b"))
        self.assertIsNone(utils.safeProfileName(""))
        self.assertIsNone(utils.safeProfileName(".."))
        self.assertEqual(utils.safeProfileName(" 张三 "), "张三")


if __name__ == "__main__":
    unittest.main()