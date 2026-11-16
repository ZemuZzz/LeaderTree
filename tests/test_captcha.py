# -*- coding: utf-8 -*-
"""验证码相关单元测试：python -m unittest discover -s tests -v"""
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageFilter, ImageDraw

import captcha
from ObjDict import ObjDict
from commander import Commander, CaptchaException, CaptchaAbort


def make_puzzle(gap_x=180, gap_y=30, size=(320, 160), piece=(52, 52)):
    """生成一张"和易盾结构一样"的测试图：背景 + 被压暗的缺口 + 拼图块"""
    w, h = size
    pw, ph = piece
    noise = Image.effect_noise((w, h), 60).convert("L").filter(ImageFilter.GaussianBlur(2))
    bg = Image.merge("RGB", (
        noise,
        noise.point(lambda v: min(255, int(v * 0.9))),
        noise.point(lambda v: min(255, int(v * 0.8))),
    ))
    piece_img = bg.crop((gap_x, gap_y, gap_x + pw, gap_y + ph)).convert("RGBA")
    piece_img.putalpha(255)
    dark = bg.crop((gap_x, gap_y, gap_x + pw, gap_y + ph)).point(lambda v: int(v * 0.55))
    bg.paste(dark, (gap_x, gap_y))
    return bg, piece_img


class GapDetectTest(unittest.TestCase):
    def test_detect_gap_exact(self):
        bg, piece = make_puzzle(180, 30)
        x, score = captcha.detect_gap(bg, piece, piece_left=10, piece_top=30)
        self.assertEqual(x, 180)
        self.assertGreater(score, 0.9)

    def test_detect_gap_other_position(self):
        bg, piece = make_puzzle(64, 12)
        x, score = captcha.detect_gap(bg, piece, piece_left=8, piece_top=12)
        self.assertEqual(x, 64)

    def test_detect_gap_without_piece_falls_back(self):
        bg, _ = make_puzzle(200, 40)
        x, _score = captcha.detect_gap(bg, None)
        self.assertIsNotNone(x)

    def test_human_track_is_monotonic_and_ends_at_distance(self):
        track = captcha.human_track(120)
        self.assertGreater(len(track), 5)
        self.assertAlmostEqual(track[-1], 120, places=1)
        # 除最后的过冲/回弹外，整体应该一路向右
        self.assertGreater(track[-4], track[0])

    def test_human_track_zero_distance(self):
        self.assertEqual(captcha.human_track(0), [])


class CaptchaRetryTest(unittest.TestCase):
    def setUp(self):
        self.commander = Commander(proxies={})
        self.commander.captcha_max_retries = 3
        self.commander.tree_view = False

    def test_retry_until_success(self):
        calls = {"n": 0}

        def action():
            calls["n"] += 1
            if calls["n"] < 3:
                raise CaptchaException("captcha required", response={"code": -12})
            return "ok"

        self.commander.solveCaptcha = lambda exc=None, ctx=None: True
        with patch("commander.time.sleep", return_value=None):
            result = self.commander._withCaptchaRetry(action, "test")
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)
        self.assertTrue(self.commander.captcha_hit)

    def test_abort_after_retries(self):
        def action():
            raise CaptchaException("captcha required")

        self.commander.solveCaptcha = lambda exc=None, ctx=None: False
        with patch("commander.time.sleep", return_value=None):
            with self.assertRaises(CaptchaAbort):
                self.commander._withCaptchaRetry(action, "test")
        self.assertTrue(self.commander.captcha_hit)

    def test_non_captcha_exception_is_not_swallowed(self):
        def action():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            self.commander._withCaptchaRetry(action, "test")


class ZhidaoQueryCaptchaTest(unittest.TestCase):
    def setUp(self):
        self.commander = Commander(proxies={})

    def test_minus_12_raises_even_with_ok_code_none(self):
        self.commander._apiQuery = lambda *a, **kw: ObjDict(
            {"code": -12, "message": "需要弹出滑块验证", "data": {"ev": "abc"}})
        with self.assertRaises(CaptchaException) as ctx:
            self.commander.zhidaoQuery("https://example.test/api", {}, encrypt=False, ok_code=None)
        self.assertEqual(ctx.exception.ev(), "abc")
        self.assertIn("滑块", str(ctx.exception))

    def test_ev_is_remembered_from_success(self):
        self.commander._apiQuery = lambda *a, **kw: ObjDict(
            {"code": 0, "data": {"ev": "ev-token-1"}})
        self.commander.zhidaoQuery("https://example.test/api", {}, encrypt=False)
        self.assertEqual(self.commander.ev_log, "ev-token-1")

    def test_validate_slide_token_payload(self):
        captured = {}

        def fake_query(url, data, **kw):
            captured["url"] = url
            captured.update(data)
            return ObjDict({"code": 0})

        self.commander.zhidaoQuery = fake_query
        self.assertTrue(self.commander.validateSlideToken("VALIDATE", ev="EV"))
        self.assertTrue(captured["url"].endswith("/learning/validateSlideToken"))
        self.assertEqual(captured["token"], "VALIDATE")
        self.assertEqual(captured["ev"], "EV")
        self.assertEqual(captured["checkType"], 1)

    def test_validate_slide_token_failure(self):
        self.commander.zhidaoQuery = lambda url, data, **kw: ObjDict({"code": -1, "message": "bad"})
        self.assertFalse(self.commander.validateSlideToken("VALIDATE", ev="EV"))

    def test_solve_captcha_disabled_returns_false(self):
        self.commander.captcha_solver = "none"
        self.assertFalse(self.commander.solveCaptcha(CaptchaException("x")))


class SolverConfigTest(unittest.TestCase):
    def test_solver_receives_config(self):
        f = Commander(proxies={}, captcha_headless=True, captcha_timeout=42,
                   captcha_browser_channel="msedge", captcha_debug_dir="/tmp/x",
                   captcha_max_retries=5)
        self.assertTrue(f.captcha_headless)
        self.assertEqual(f.captcha_timeout, 42)
        self.assertEqual(f.captcha_browser_channel, "msedge")
        self.assertEqual(f.captcha_max_retries, 5)

    def test_available_reports_bool(self):
        self.assertIsInstance(captcha.CaptchaSolver.available(), bool)

    def test_vision_config_passed_to_solver(self):
        f = Commander(proxies={}, captcha_vision={
            "enabled": True, "model": "gpt-4o", "api_key": "k"})
        solver = f._getCaptchaSolver()
        self.assertEqual(solver.vision["model"], "gpt-4o")
        self.assertTrue(solver._vision_available())


class FakeVideoCommander(Commander):
    """只跑 commandZhidaoVideo 的假实现：不发网络请求"""

    def __init__(self, captcha_at=1, solve_ok=True):
        super().__init__(proxies={}, captcha_max_retries=3)
        self.reports = []
        self.report_calls = 0
        self.captcha_calls = 0
        self.captcha_at = captcha_at
        self.solve_ok = solve_ok
        self.always_captcha = not solve_ok
        self.end_thre = 0.91
        self.speed = 1
        self.progressbar_view = False
        self.tree_view = False
        self.uuid = "uuid"
        video = ObjDict({
            "videoId": "v1", "name": "视频1", "videoSec": 100,
            "studyTotalTime": 0, "watchState": 0,
            "lessonId": 11, "id": 22, "chapterId": 33,
        })
        self.ctx = ObjDict({
            "course": ObjDict({"courseInfo": ObjDict({"name": "课程"})}),
            "chapters": ObjDict({"courseId": 1}),
            "videos": ObjDict({"v1": video}),
            "spent_time": 0,
        }, default={})

    def _checkCookies(self):
        pass

    def _checkTimeLimit(self, cid):
        pass

    def getZhidaoContext(self, RAC_id, force=False):
        return self.ctx

    def _sessionReady(self, ctx=None):
        pass

    def prelearningNote(self, RAC_id, video_id):
        return ObjDict({"studiedLessonDto": ObjDict({"id": 1})})

    def loadVideoPointerInfo(self, RAC_id, video_id):
        return ObjDict(default=None)

    def watchVideo(self, video_id):
        pass

    def threeDimensionalCourseWare(self, video_id):
        return ObjDict()

    def saveDatabaseIntervalTimeV2(self, RAC_id, video_id, played_time, last_submit,
                                   watch_point, token_id=None):
        self.report_calls += 1
        if self.report_calls == self.captcha_at or self.always_captcha:
            raise CaptchaException("需要弹出滑块验证", response={"code": -12, "data": {"ev": "EV"}})
        self.reports.append((played_time, last_submit))
        return ObjDict({"code": 0})

    def solveCaptcha(self, exc=None, ctx=None):
        self.captcha_calls += 1
        self.ev_log = exc.ev() if exc is not None else ""
        return self.solve_ok


class VideoCaptchaFlowTest(unittest.TestCase):
    def test_video_continues_after_captcha(self):
        f = FakeVideoCommander(captcha_at=1)
        with patch("commander.time.sleep", return_value=None), \
             patch("commander.random", return_value=1.0):
            f.commandZhidaoVideo("course", "v1")
        self.assertEqual(f.captcha_calls, 1)
        self.assertGreaterEqual(len(f.reports), 2)      # 重试后继续上报，视频没有中断
        self.assertEqual(f.ev_log, "EV")                # 上报验证码时带上了服务端的 ev

    def test_video_raises_abort_when_unsolvable(self):
        f = FakeVideoCommander(captcha_at=1, solve_ok=False)
        with patch("commander.time.sleep", return_value=None), \
             patch("commander.random", return_value=1.0):
            with self.assertRaises(CaptchaAbort):
                f.commandZhidaoVideo("course", "v1")
        self.assertEqual(f.captcha_calls, f.captcha_max_retries)


class _FakeMouse:
    def __init__(self):
        self.events = []

    def move(self, x, y):
        self.events.append(("move", x, y))

    def down(self):
        self.events.append(("down",))

    def up(self):
        self.events.append(("up",))

    def click(self, x, y):
        self.events.append(("click", x, y))


class _FakeElement:
    def __init__(self, shots, box=None, visible=True):
        self.shots = list(shots)
        self.box = box or {"x": 100, "y": 400, "width": 40, "height": 30}
        self.visible = visible

    def screenshot(self):
        return self.shots.pop(0)

    def bounding_box(self):
        return self.box if self.visible else None

    def is_visible(self):
        return self.visible

    def click(self):
        pass


class _FakeFrame:
    def __init__(self, info, bg_el, slider_el, point_el=None, tips=""):
        self.info = info
        self.bg_el = bg_el
        self.slider_el = slider_el
        self.point_el = point_el
        self.tips = tips

    def query_selector(self, selector):
        if selector == ".yidun_bgimg":
            return self.bg_el
        if selector == ".yidun_slider":
            return self.slider_el
        if selector == ".yidun_point":
            return self.point_el
        return None

    def evaluate(self, script, *args):
        if "yidun_tips" in script:
            return self.tips
        return self.info


class _FakePage:
    def __init__(self, frame):
        self.main_frame = frame
        self.frames = [frame]
        self.mouse = _FakeMouse()

    def query_selector(self, selector):
        return self.main_frame.query_selector(selector)


class AutoSlideTest(unittest.TestCase):
    """用假的 page/frame 走一遍 _auto_slide，确认截图->识别->拖动这条链路是对的"""

    def _build(self):
        gap_x, gap_y, pw = 180, 30, 52
        bg, piece = make_puzzle(gap_x, gap_y, piece=(pw, pw))
        piece_left = 10
        with_piece = bg.copy()
        with_piece.paste(piece.convert("RGB"), (piece_left, gap_y))
        buf1, buf2 = io.BytesIO(), io.BytesIO()
        with_piece.save(buf1, format="PNG")
        bg.save(buf2, format="PNG")
        info = {
            "bg": {"x": 0, "y": 0, "w": bg.width, "h": bg.height},
            "pieceLeft": piece_left, "pieceTop": gap_y,
            "pieceW": pw, "pieceH": pw, "image": None,
        }
        bg_el = _FakeElement([buf1.getvalue(), buf2.getvalue()])
        slider_el = _FakeElement([], {"x": 200, "y": 500, "width": 40, "height": 30})
        frame = _FakeFrame(info, bg_el, slider_el)
        return _FakePage(frame), gap_x, piece_left, slider_el

    def test_auto_slide_drags_to_gap(self):
        page, gap_x, piece_left, slider_el = self._build()
        solver = captcha.CaptchaSolver(headless=True, auto_attempts=1)
        with patch("captcha.time.sleep", return_value=None):
            ok = solver._auto_slide(page)
        self.assertTrue(ok)
        moves = [e for e in page.mouse.events if e[0] == "move"]
        downs = [e for e in page.mouse.events if e[0] == "down"]
        ups = [e for e in page.mouse.events if e[0] == "up"]
        self.assertEqual(len(downs), 1)
        self.assertEqual(len(ups), 1)
        start_x = slider_el.box["x"] + slider_el.box["width"] / 2
        final_x = moves[-1][1]
        self.assertAlmostEqual(final_x - start_x, gap_x - piece_left, delta=2.0)


class ClickCaptchaTest(unittest.TestCase):
    """点选类验证码：题型判定 / 提示文案 / 模型坐标解析 / 点击执行"""

    def _frame(self, tips="", slider=None, point=None, bg_visible=True):
        bg = _FakeElement([b""], {"x": 100, "y": 300, "width": 320, "height": 160},
                          visible=bg_visible)
        return _FakeFrame({}, bg, slider, point_el=point, tips=tips)

    def test_kind_slide(self):
        slider = _FakeElement([], {"x": 100, "y": 460, "width": 40, "height": 30})
        frame = self._frame("请拖动滑块完成验证", slider=slider)
        self.assertEqual(captcha.CaptchaSolver(headless=True)._captcha_kind(frame), "slide")

    def test_kind_click_wins_over_hidden_slider(self):
        # 易盾的点选面板里可能藏着一个不可见的滑块控件，不能因此判成滑块
        hidden = _FakeElement([], {"x": 100, "y": 460, "width": 40, "height": 30},
                              visible=False)
        frame = self._frame("请点击绿色小写m", slider=hidden)
        self.assertEqual(captcha.CaptchaSolver(headless=True)._captcha_kind(frame), "click")

    def test_kind_click_when_only_image(self):
        frame = self._frame("")
        self.assertEqual(captcha.CaptchaSolver(headless=True)._captcha_kind(frame), "click")

    def test_kind_click_by_tips(self):
        frame = self._frame("请依次点击'今日快乐'")
        self.assertEqual(captcha.CaptchaSolver(headless=True)._captcha_kind(frame), "click")

    def test_kind_click_by_inference_tips(self):
        frame = self._frame("请点击小写q朝向一样的大写F")
        self.assertEqual(captcha.CaptchaSolver(headless=True)._captcha_kind(frame), "click")

    def test_kind_unknown_without_image(self):
        frame = self._frame("", bg_visible=False)
        self.assertEqual(captcha.CaptchaSolver(headless=True)._captcha_kind(frame), "unknown")

    def test_read_tips(self):
        frame = self._frame("请点击小写q朝向一样的大写F")
        self.assertEqual(captcha.CaptchaSolver(headless=True)._read_tips(frame),
                         "请点击小写q朝向一样的大写F")

    def test_parse_points_json(self):
        fence = chr(96) * 3
        text = "好的，结果如下：\n" + fence + 'json\n{"points": [[10, 20], [30, 40]]}\n' + fence
        self.assertEqual(captcha.CaptchaSolver._parse_points(text, 320, 160),
                         [(10.0, 20.0), (30.0, 40.0)])

    def test_parse_points_normalized(self):
        text = '{"points": [[0.5, 0.25]]}'
        self.assertEqual(captcha.CaptchaSolver._parse_points(text, 320, 160),
                         [(160.0, 40.0)])

    def test_parse_points_fallback_regex(self):
        text = "点击 [12, 34] 和 [56,78] 即可"
        self.assertEqual(captcha.CaptchaSolver._parse_points(text, 320, 160),
                         [(12.0, 34.0), (56.0, 78.0)])

    def test_parse_points_1000_scale(self):
        # qwen-vl 这类模型用 0~1000 的相对坐标
        text = '{"points": [[500, 250]]}'
        self.assertEqual(captcha.CaptchaSolver._parse_points(text, 320, 160),
                         [(160.0, 40.0)])

    def test_parse_points_out_of_range_dropped(self):
        text = '{"points": [[999, 20], [30, 40]]}'
        self.assertEqual(captcha.CaptchaSolver._parse_points(text, 320, 160),
                         [(30.0, 40.0)])

    def test_parse_points_empty(self):
        self.assertEqual(captcha.CaptchaSolver._parse_points("", 320, 160), [])
        self.assertEqual(captcha.CaptchaSolver._parse_points("不知道", 320, 160), [])

    def test_vision_extra_body_deepseek_disables_thinking(self):
        solver = captcha.CaptchaSolver(
            headless=True,
            vision={"enabled": True, "api_base": "https://api.deepseek.com/v1",
                    "model": "deepseek-flash", "api_key": "k"})
        self.assertEqual(solver._vision_extra_body(), {"thinking": {"type": "disabled"}})

    def test_vision_extra_body_openai_untouched(self):
        solver = captcha.CaptchaSolver(
            headless=True,
            vision={"enabled": True, "api_base": "https://api.openai.com/v1",
                    "model": "gpt-4o", "api_key": "k"})
        self.assertIsNone(solver._vision_extra_body())

    def test_vision_extra_body_forced(self):
        solver = captcha.CaptchaSolver(
            headless=True,
            vision={"enabled": True, "api_base": "https://api.openai.com/v1",
                    "model": "gpt-4o", "api_key": "k", "thinking": "enabled"})
        self.assertEqual(solver._vision_extra_body(), {"thinking": {"type": "enabled"}})

    def test_vision_available_flag(self):
        self.assertFalse(captcha.CaptchaSolver(headless=True)._vision_available())
        solver = captcha.CaptchaSolver(
            headless=True,
            vision={"enabled": True, "model": "gpt-4o", "api_key": "sk-x"})
        self.assertTrue(solver._vision_available())

    def test_auto_click_clicks_model_points(self):
        buf = io.BytesIO()
        Image.new("RGB", (320, 160), (200, 200, 200)).save(buf, format="PNG")
        bg = _FakeElement([buf.getvalue()], {"x": 100, "y": 300, "width": 320, "height": 160})
        frame = _FakeFrame({}, bg, None, tips="请点击小写q朝向一样的大写F")
        page = _FakePage(frame)
        solver = captcha.CaptchaSolver(
            headless=True,
            vision={"enabled": True, "model": "gpt-4o", "api_key": "sk-x"})
        solver._ask_vision_click = lambda shot, tips: [(10.0, 20.0), (100.0, 40.0)]
        with patch("captcha.time.sleep", return_value=None):
            ok = solver._auto_click(page, frame)
        self.assertTrue(ok)
        clicks = [e for e in page.mouse.events if e[0] == "click"]
        self.assertEqual(clicks, [("click", 110.0, 320.0), ("click", 200.0, 340.0)])


class SlideGuardTest(unittest.TestCase):
    """识别不可靠时宁可不拖，也不能乱拖（真实场景里把点选当滑块拖过）"""

    def _solver_and_page(self):
        gap_x, gap_y, pw = 180, 30, 52
        bg, piece = make_puzzle(gap_x, gap_y, piece=(pw, pw))
        buf1, buf2 = io.BytesIO(), io.BytesIO()
        with_piece = bg.copy()
        with_piece.paste(piece.convert("RGB"), (10, gap_y))
        with_piece.save(buf1, format="PNG")
        bg.save(buf2, format="PNG")
        info = {
            "bg": {"x": 0, "y": 0, "w": bg.width, "h": bg.height},
            "pieceLeft": 10, "pieceTop": gap_y, "pieceW": pw, "pieceH": pw,
            "image": None,
        }
        bg_el = _FakeElement([buf1.getvalue(), buf2.getvalue()])
        slider_el = _FakeElement([], {"x": 200, "y": 500, "width": 40, "height": 30})
        frame = _FakeFrame(info, bg_el, slider_el)
        return captcha.CaptchaSolver(headless=True), _FakePage(frame), frame

    def test_low_score_does_not_drag(self):
        solver, page, frame = self._solver_and_page()
        with patch("captcha.detect_gap", return_value=(58.0, 0.108)), \
             patch("captcha.time.sleep", return_value=None):
            ok = solver._auto_slide(page)
        self.assertFalse(ok)
        self.assertEqual([e for e in page.mouse.events if e[0] in ("down", "up")], [])
        self.assertIn("置信度", solver._last_error)

    def test_absurd_distance_does_not_drag(self):
        solver, page, frame = self._solver_and_page()
        # 目标 58px、拼图块在 -517px -> 拖动距离 575px，明显不合理
        with patch("captcha.detect_gap", return_value=(58.0, 0.99)), \
             patch("captcha.time.sleep", return_value=None):
            frame.info["pieceLeft"] = -517
            ok = solver._auto_slide(page)
        self.assertFalse(ok)
        self.assertEqual([e for e in page.mouse.events if e[0] in ("down", "up")], [])
        self.assertIn("异常", solver._last_error)

    def test_good_detection_still_drags(self):
        solver, page, frame = self._solver_and_page()
        with patch("captcha.time.sleep", return_value=None):
            ok = solver._auto_slide(page)
        self.assertTrue(ok)
        self.assertTrue([e for e in page.mouse.events if e[0] == "down"])


class ClickPrecisionTest(unittest.TestCase):
    def test_prompt_forces_analysis_first(self):
        prompt = captcha.build_click_prompt("请点击大写F朝向一样的小写r", 640, 320)
        self.assertIn("请点击大写F朝向一样的小写r", prompt)
        self.assertIn("640x320", prompt)
        self.assertIn("不要点参照物", prompt)
        self.assertIn('"analysis"', prompt)
        self.assertIn("points", prompt)

    def _glyph_image(self):
        img = Image.new("RGB", (320, 160), (235, 235, 235))
        d = ImageDraw.Draw(img)
        d.rectangle([100, 40, 130, 70], fill=(220, 40, 40))
        return img

    def test_snap_background_point_to_glyph(self):
        img = self._glyph_image()
        x, y = captcha.snap_point_to_ink(img, 150, 55)
        self.assertTrue(95 <= x <= 135, (x, y))
        self.assertTrue(35 <= y <= 75, (x, y))

    def test_snap_keeps_point_on_glyph(self):
        img = self._glyph_image()
        x, y = captcha.snap_point_to_ink(img, 115, 55)
        self.assertAlmostEqual(x, 115, delta=6)
        self.assertAlmostEqual(y, 55, delta=6)

    def test_snap_out_of_bounds_unchanged(self):
        img = self._glyph_image()
        self.assertEqual(captcha.snap_point_to_ink(img, 999, 999), (999, 999))

    def test_snap_without_glyph_unchanged(self):
        img = Image.new("RGB", (320, 160), (235, 235, 235))
        x, y = captcha.snap_point_to_ink(img, 150, 55)
        self.assertEqual((x, y), (150, 55))


if __name__ == "__main__":
    unittest.main()