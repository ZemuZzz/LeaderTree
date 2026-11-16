# -*- coding: utf-8 -*-
"""章节作业模块的单元测试：python -m unittest discover -s tests -v"""
import io
import json
import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ObjDict import ObjDict
from commander import Commander
import homework


def make_question(qtype=1, options=("苹果", "香蕉", "橘子")):
    raw = {
        "eid": "EID-1",
        "name": "<p>下面哪个是水果？</p>",
        "questionType": {"id": qtype, "name": "单选题"},
        "questionScore": "2",
        "questionOptions": [
            {"id": 101 + i, "content": "<span>%s</span>" % text}
            for i, text in enumerate(options)
        ],
    }
    return homework.normalize_question(raw)


class HtmlTest(unittest.TestCase):
    def test_strip_html(self):
        self.assertEqual(homework.strip_html("<p>你好&nbsp;<b>世界</b></p>"), "你好 世界")

    def test_strip_html_br(self):
        self.assertEqual(homework.strip_html("a<br/>b"), "a\nb")

    def test_strip_html_empty(self):
        self.assertEqual(homework.strip_html(None), "")


class NormalizeTest(unittest.TestCase):
    def test_normalize(self):
        q = make_question()
        self.assertEqual(q["eid"], "EID-1")
        self.assertEqual(q["type"], 1)
        self.assertEqual(q["name"], "下面哪个是水果？")
        self.assertEqual([o["id"] for o in q["options"]], [101, 102, 103])
        self.assertEqual(q["options"][0]["content"], "苹果")

    def test_question_type_int(self):
        raw = {"questionType": 14, "questionOptions": []}
        self.assertEqual(homework.normalize_question(raw)["type"], 14)

    def test_question_type_missing(self):
        self.assertEqual(homework.question_type_id(None), 0)


class ParseAnswerTest(unittest.TestCase):
    def test_single(self):
        q = make_question(1)
        self.assertEqual(homework.parse_answer("B", q), 102)

    def test_single_with_prose(self):
        q = make_question(1)
        self.assertEqual(homework.parse_answer("答案是：C。因为...", q), 103)

    def test_multi(self):
        q = make_question(2)
        self.assertEqual(homework.parse_answer("A,C", q), "101,103")

    def test_judge_letter(self):
        q = make_question(14, ("对", "错"))
        self.assertEqual(homework.parse_answer("A", q), 101)

    def test_judge_word(self):
        q = make_question(14, ("对", "错"))
        self.assertEqual(homework.parse_answer("这句话是对的", q), 101)
        self.assertEqual(homework.parse_answer("错误", q), 102)

    def test_fill(self):
        q = make_question(3, ())
        self.assertEqual(homework.parse_answer("光合作用", q), "光合作用")

    def test_garbage(self):
        q = make_question(1)
        self.assertIsNone(homework.parse_answer("不知道", q))

    def test_empty(self):
        q = make_question(1)
        self.assertIsNone(homework.parse_answer("", q))

    def test_code_fence(self):
        q = make_question(1)
        self.assertEqual(homework.parse_answer("\x60B\x60", q), 102)


class PromptTest(unittest.TestCase):
    def test_prompt_contains_question_and_options(self):
        q = make_question(1)
        prompt = homework.HomeworkAI(model="m", api_key="k").build_prompt(q, "形势与政策")
        self.assertIn("形势与政策", prompt)
        self.assertIn("下面哪个是水果？", prompt)
        self.assertIn("A. 苹果", prompt)
        self.assertIn("只输出正确选项的字母", prompt)

    def test_fill_prompt(self):
        q = make_question(3, ())
        prompt = homework.HomeworkAI(model="m", api_key="k").build_prompt(q)
        self.assertIn("填空答案", prompt)


class ThinkingTest(unittest.TestCase):
    def test_deepseek_disabled(self):
        self.assertEqual(homework.thinking_extra("https://api.deepseek.com/v1"),
                         {"thinking": {"type": "disabled"}})

    def test_openai_none(self):
        self.assertIsNone(homework.thinking_extra("https://api.openai.com/v1"))

    def test_force_enabled(self):
        self.assertEqual(homework.thinking_extra("https://api.openai.com/v1", "true"),
                         {"thinking": {"type": "enabled"}})


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.commander = Commander(proxies={})
        self.client = homework.HomeworkClient(self.commander)

    def test_query_encrypts_and_checks_status(self):
        captured = {}

        def fake_api(url, data=None, method="POST", **kw):
            captured["url"] = url
            captured["data"] = data
            return ObjDict({"status": "200", "rt": {"ok": 1}})

        self.commander._apiQuery = fake_api
        ret = self.client.query(homework.P_LIST, {"recruitId": "r1"})
        self.assertEqual(ret["status"], "200")
        self.assertTrue(captured["url"].endswith(homework.P_LIST))
        self.assertIn("secretStr", captured["data"])
        self.assertNotIn("dateFormate", captured["data"])

    def test_query_raises_on_bad_status(self):
        self.commander._apiQuery = lambda *a, **k: ObjDict({"status": "403", "msg": "no"})
        with self.assertRaises(homework.HomeworkError):
            self.client.query(homework.P_LIST, {})

    def test_save_answer_payload(self):
        captured = {}

        def fake_api(url, data=None, method="POST", **kw):
            captured["url"] = url
            captured["data"] = data
            return ObjDict({"status": "200", "rt": {}})

        self.commander._apiQuery = fake_api
        q = make_question(1)
        item = {"examId": "EX-1", "id": "SE-1"}
        self.client.save_answer("RID", q, item, "625", 102)
        self.assertTrue(captured["url"].endswith(homework.P_SAVE))
        cipher = homework.Cipher(homework.EXAM_KEY)
        plain = json.loads(cipher.decrypt(captured["data"]["secretStr"]))
        payload = json.loads(plain["stuExamAnswer"])
        self.assertEqual(payload[0]["eid"], "EID-1")
        self.assertEqual(payload[0]["examId"], "EX-1")
        self.assertEqual(payload[0]["stuExamId"], "SE-1")
        self.assertEqual(payload[0]["answer"], 102)
        self.assertEqual(payload[0]["questionType"], 1)
        self.assertEqual(payload[0]["fromType"], 3)
        self.assertEqual(payload[0]["schoolId"], "625")

    def test_save_answer_without_eid(self):
        q = make_question(1)
        q["eid"] = None
        with self.assertRaises(homework.HomeworkError):
            self.client.save_answer("RID", q, {"examId": "E", "id": "S"}, "625", 101)

    def test_submit_payload(self):
        captured = {}

        def fake_api(url, data=None, method="POST", **kw):
            captured["data"] = data
            return ObjDict({"status": "200", "rt": {"statu": "1"}})

        self.commander._apiQuery = fake_api
        self.client.submit("RID", "EX-1", "SE-1", 5)
        cipher = homework.Cipher(homework.EXAM_KEY)
        payload = json.loads(cipher.decrypt(captured["data"]["secretStr"]))
        self.assertEqual(payload["achieveCount"], "5")
        self.assertEqual(payload["stuExamId"], "SE-1")

    def test_sso_login_follows_ticket(self):
        session = Mock()
        resp = Mock(status_code=302)
        resp.headers = {"location": "https://studentexam-api.zhihuishu.com/x?ticket=abc"}
        session.get.side_effect = [resp, Mock(status_code=200)]
        self.commander.session = session
        self.assertTrue(self.client.sso_login())
        self.assertEqual(session.get.call_count, 2)

    def test_sso_login_without_ticket(self):
        session = Mock()
        resp = Mock(status_code=302)
        resp.headers = {"location": "https://passport.zhihuishu.com/login"}
        session.get.return_value = resp
        self.commander.session = session
        with self.assertRaises(homework.HomeworkError):
            self.client.sso_login()


class ExtractTest(unittest.TestCase):
    def test_extract_questions(self):
        detail = {
            "examBase": {
                "workExamParts": [
                    {"questionDtos": [{"eid": "a", "questionType": 1,
                                       "questionOptions": []}]},
                    {"questionDtos": [{"eid": "b", "questionType": 2,
                                       "questionOptions": []}]},
                ]
            }
        }
        base, questions = homework.extract_questions(detail)
        self.assertEqual(len(questions), 2)
        self.assertEqual([q["eid"] for q in questions], ["a", "b"])

    def test_extract_empty(self):
        _, questions = homework.extract_questions({})
        self.assertEqual(questions, [])


class ResolveAiTest(unittest.TestCase):
    def test_uses_captcha_vision_when_ai_empty(self):
        config = ObjDict({
            "ai": {"openai": {"api_base": "https://api.openai.com", "api_key": "sk-",
                              "model_name": "x"}},
            "captcha": {"vision": {"api_base": "https://api.deepseek.com/v1",
                                   "api_key": "sk-real", "model": "deepseek-flash"}},
        }, default=None)
        ai = homework.resolve_ai(config)
        self.assertEqual(ai.api_key, "sk-real")
        self.assertEqual(ai.model, "deepseek-flash")

    def test_homework_answer_overrides(self):
        config = ObjDict({
            "homework": {"answer": {"api_base": "https://my", "api_key": "k1",
                                    "model": "m1"}},
            "captcha": {"vision": {"api_key": "other", "model": "other"}},
        }, default=None)
        ai = homework.resolve_ai(config)
        self.assertEqual(ai.model, "m1")

    def test_not_available_without_key(self):
        ai = homework.resolve_ai(ObjDict({}, default=None))
        self.assertFalse(ai.available)

class EnsureSessionTest(unittest.TestCase):
    def _args(self, login=False):
        return homework.argparse.Namespace(login=login)

    def test_existing_session_skips_sso(self):
        client = Mock()
        client.school_id.return_value = "625"
        ok = homework.ensure_session(client, Mock(), ObjDict({}, default=None), self._args())
        self.assertTrue(ok)
        client.sso_login.assert_not_called()

    def test_sso_path(self):
        client = Mock()
        client.school_id.side_effect = [Exception("no session"), "625"]
        ok = homework.ensure_session(client, Mock(), ObjDict({}, default=None), self._args())
        self.assertTrue(ok)
        client.sso_login.assert_called_once()

    def test_no_tty_no_login_returns_false(self):
        client = Mock()
        client.school_id.side_effect = Exception("no session")
        client.sso_login.side_effect = homework.HomeworkError("CAS 返回 200")
        with unittest.mock.patch("sys.stdin.isatty", return_value=False):
            ok = homework.ensure_session(client, Mock(), ObjDict({}, default=None), self._args())
        self.assertFalse(ok)

    def test_relogin_when_forced(self):
        client = Mock()
        client.school_id.side_effect = [Exception("no session"), "625"]
        client.sso_login.side_effect = [homework.HomeworkError("CAS 200"), None]
        with unittest.mock.patch("homework.do_qr_login") as relogin, \
             unittest.mock.patch("sys.stdin.isatty", return_value=False):
            ok = homework.ensure_session(client, Mock(), ObjDict({}, default=None), self._args(login=True))
        self.assertTrue(ok)
        relogin.assert_called_once()

class HomeworkCaptchaTest(unittest.TestCase):
    def setUp(self):
        self.commander = Commander(proxies={})
        self.client = homework.HomeworkClient(self.commander)

    def test_validate_slide_token_payload(self):
        captured = {}

        def fake_api(url, data=None, method="POST", **kw):
            captured["url"] = url
            captured["data"] = data
            return ObjDict({"status": "200", "pass": True})

        self.commander._apiQuery = fake_api
        ok = self.client.validate_slide_token("RID", "EX-1", "VALIDATE")
        self.assertTrue(ok)
        self.assertTrue(captured["url"].endswith(homework.P_VALIDATE))
        cipher = homework.Cipher(homework.EXAM_KEY)
        payload = json.loads(cipher.decrypt(captured["data"]["secretStr"]))
        self.assertEqual(payload["recruitId"], "RID")
        self.assertEqual(payload["token"], "VALIDATE")
        self.assertEqual(payload["checkType"], 1)
        self.assertEqual(payload["chapterId"], "EX-1")

    def test_validate_slide_token_fail(self):
        self.commander._apiQuery = lambda *a, **k: ObjDict({"status": "200", "pass": False})
        self.assertFalse(self.client.validate_slide_token("RID", "EX-1", "V"))

    def test_error_need_captcha(self):
        self.assertTrue(homework.HomeworkError("滑块验证未通过，不能答题").need_captcha)
        self.assertTrue(homework.HomeworkError("x", code=-12).need_captcha)
        self.assertFalse(homework.HomeworkError("网络错误").need_captcha)

    def test_with_captcha_retries_after_solving(self):
        calls = {"n": 0}

        def action():
            calls["n"] += 1
            if calls["n"] == 1:
                raise homework.HomeworkError("滑块验证未通过，不能答题")
            return "ok"

        commander = Mock()
        commander.solveCaptchaToken.return_value = "VALIDATE"
        self.client.validate_slide_token = Mock(return_value=True)
        result = homework.with_captcha(self.client, commander, "RID", "EX-1", action, "保存")
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 2)
        self.client.validate_slide_token.assert_called_once_with("RID", "EX-1", "VALIDATE")

    def test_with_captcha_no_token_raises(self):
        def action():
            raise homework.HomeworkError("滑块验证未通过")

        commander = Mock()
        commander.solveCaptchaToken.return_value = ""
        with self.assertRaises(homework.HomeworkError):
            homework.with_captcha(self.client, commander, "RID", "EX-1", action)

    def test_with_captcha_non_captcha_error_propagates(self):
        def action():
            raise homework.HomeworkError("网络错误")

        commander = Mock()
        with self.assertRaises(homework.HomeworkError):
            homework.with_captcha(self.client, commander, "RID", "EX-1", action)
        commander.solveCaptchaToken.assert_not_called()

    def test_commander_solve_captcha_token(self):
        commander = Commander(proxies={})
        solver = Mock()
        solver.solve.return_value = "VALIDATE-X"
        commander._captchaSolver = solver
        self.assertEqual(commander.solveCaptchaToken(), "VALIDATE-X")
        self.assertTrue(commander.captcha_hit)

    def test_commander_solve_captcha_token_disabled(self):
        commander = Commander(proxies={}, captcha_solver="none")
        self.assertEqual(commander.solveCaptchaToken(), "")

class HomeworkSavedAnswersTest(unittest.TestCase):
    def setUp(self):
        self.commander = Commander(proxies={})
        self.client = homework.HomeworkClient(self.commander)

    def test_parse_list_shape(self):
        self.commander._apiQuery = lambda *a, **k: ObjDict({
            "status": "200",
            "rt": [
                {"eid": "E1", "answer": "101", "dataIds": ""},
                {"eid": "E2", "answer": "", "dataIds": ""},
            ],
        })
        saved = self.client.get_saved_answers("R", "EX", "SE", "625", 1, ["E1", "E2"])
        self.assertEqual(saved, {"E1": "101"})

    def test_parse_dict_shape(self):
        self.commander._apiQuery = lambda *a, **k: ObjDict({
            "status": "200",
            "rt": {"E1": {"answer": "101"}, "E2": {"answer": ""}},
        })
        saved = self.client.get_saved_answers("R", "EX", "SE", "625", 1, ["E1", "E2"])
        self.assertEqual(saved, {"E1": "101"})

    def test_query_failure_returns_empty(self):
        def boom(*a, **k):
            raise homework.HomeworkError("status=500")
        self.commander._apiQuery = boom
        self.assertEqual(self.client.get_saved_answers("R", "EX", "SE", "625", 1, ["E1"]), {})

    def test_no_eids_no_request(self):
        called = {"n": 0}
        def fake(*a, **k):
            called["n"] += 1
            return ObjDict({"status": "200", "rt": []})
        self.commander._apiQuery = fake
        self.assertEqual(self.client.get_saved_answers("R", "EX", "SE", "625", 1, []), {})
        self.assertEqual(called["n"], 0)

    def test_get_saved_answers_payload(self):
        captured = {}
        def fake(url, data=None, method="POST", **kw):
            captured["url"] = url
            captured["data"] = data
            return ObjDict({"status": "200", "rt": []})
        self.commander._apiQuery = fake
        self.client.get_saved_answers("R", "EX", "SE", "625", 7, ["E1", "E2"])
        self.assertTrue(captured["url"].endswith(homework.P_ANSWERS))
        cipher = homework.Cipher(homework.EXAM_KEY)
        payload = json.loads(cipher.decrypt(captured["data"]["secretStr"]))
        self.assertEqual(payload["questionIds"], "E1,E2")
        self.assertEqual(payload["courseId"], 7)
        self.assertEqual(payload["stuExamId"], "SE")


class BuildCommanderTest(unittest.TestCase):
    def test_captcha_config_is_passed(self):
        config = ObjDict({
            "proxies": {},
            "captcha": {
                "solver": "auto",
                "headless": False,
                "timeout": 90,
                "vision": {"enabled": True, "api_base": "https://api.deepseek.com/v1",
                           "api_key": "sk-x", "model": "deepseek-flash"},
            },
        }, default=None)
        f = homework.build_commander(config)
        self.assertEqual(f.captcha_timeout, 90)
        self.assertTrue(f.captcha_vision.get("enabled"))
        self.assertEqual(f.captcha_vision.get("model"), "deepseek-flash")
        solver = f._getCaptchaSolver()
        self.assertTrue(solver._vision_available())

    def test_captcha_defaults(self):
        f = homework.build_commander(ObjDict({"proxies": {}}, default=None))
        self.assertEqual(f.captcha_solver, "auto")
        self.assertEqual(f.captcha_vision, {})

class CourseLookupTest(unittest.TestCase):
    def _commander(self, courses):
        f = Mock()
        f.getZhidaoList.return_value = courses
        return f

    def test_course_id_top_level(self):
        self.assertEqual(homework.course_course_id({"courseId": 123}), 123)

    def test_course_id_fallback_to_info(self):
        self.assertEqual(homework.course_course_id({"courseId": 0,
                                                   "courseInfo": {"courseId": 456}}), 456)

    def test_course_id_missing(self):
        self.assertEqual(homework.course_course_id({}), 0)

    def test_find_by_course_id(self):
        courses = [
            {"courseName": "A", "courseId": 1, "recruitId": 11,
             "recruitAndCourseId": "aaa"},
            {"courseName": "B", "courseId": 0, "courseInfo": {"courseId": 2},
             "recruitId": 22, "recruitAndCourseId": "bbb"},
        ]
        course = homework.find_course(self._commander(courses), course_id=2)
        self.assertEqual(course["courseName"], "B")

    def test_find_by_rac(self):
        courses = [{"courseName": "A", "recruitAndCourseId": "RAC-1"}]
        course = homework.find_course(self._commander(courses), rac="RAC-1")
        self.assertEqual(course["courseName"], "A")

    def test_find_missing(self):
        self.assertIsNone(homework.find_course(self._commander([]), course_id=9))

    def test_print_courses_output(self):
        import contextlib
        courses = [{"courseName": "中国近现代史", "courseId": 1000010466,
                    "recruitId": 465101, "recruitAndCourseId": "4e5e5c"}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            homework.print_courses(self._commander(courses))
        out = buf.getvalue()
        self.assertIn("1000010466", out)
        self.assertIn("465101", out)
        self.assertIn("4e5e5c", out)
