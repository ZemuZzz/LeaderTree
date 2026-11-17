# -*- coding: utf-8 -*-
"""多账号 profile 的单元测试"""
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


if __name__ == "__main__":
    unittest.main()
