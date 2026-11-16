# -*- coding: utf-8 -*-
"""
知到 / 智慧树 风控滑块验证码自动处理

背景
----
刷课时服务端偶尔会返回 code: -12（"需要弹出滑块验证"）。知到网页版的处理方式是：

1. 弹出网易易盾（Yidun）行为验证码；
2. 用户拖动滑块通过后，前端拿到 validate；
3. 前端调用 POST /gateway/t/v1/learning/validateSlideToken 把 validate 上报给服务端；
4. 服务端解除风控，前端重发刚才失败的那条学习进度请求。

本项目以前遇到 -12 直接放弃整个课程，这里把上面 1~4 步自动化：

* 用 Playwright 打开智慧树页面（复用脚本自己的 Cookie，保证同源 / 同账号）；
* 注入智慧树自己的易盾加载器 ableCaptcha/yidun-captcha.js，
  用知到实际使用的 captchaId 初始化弹窗验证码（与网页版完全一致）；
* 截图后用归一化互相关（NCC）定位滑块缺口，模拟人手拖动；
* 从 onVerify 回调拿到 validate，交给 commander.py 上报。

如果自动拖动失败，弹窗会保持打开：人工拖一下，脚本会自动拿到 validate 继续刷课，
不需要重启进程（这是最容易兜底、也最不容易误伤的方案）。
"""
from __future__ import annotations

import base64
import io
import os
import random
import time
import urllib.request
from typing import Optional

try:  # Pillow 已经是项目依赖，这里只是防御式导入
    from PIL import Image, ImageChops, ImageStat
except Exception:  # pragma: no cover - 没有 Pillow 时只能人工
    Image = None


#: 知到网页版实际使用的易盾 captchaId（capType == "space"）
CAPTCHA_ID_SPACE = "4da3050565514a35a50541b0e1f54538"
#: 备用 captchaId（capType != "space" 时使用的那个）
CAPTCHA_ID_DEFAULT = "75f9f716460a422f89a628f50fd8cc2b"

#: 智慧树自己的易盾加载器（和网页版引用的是同一个文件）
LOADER_URL = "https://www.zhihuishu.com/assets/ableCaptcha/yidun-captcha.js"
#: 打开验证码用的页面，必须是 zhihuishu.com 域，cookie / referer 才对得上
PAGE_URLS = (
    "https://www.zhihuishu.com/",
    "https://studyvideoh5.zhihuishu.com/",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class CaptchaUnavailable(RuntimeError):
    """没有可用的验证码解决方案（例如没装 Playwright）。"""


class CaptchaSolveTimeout(RuntimeError):
    """超时仍未通过验证码。"""


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - 取决于运行环境
        raise CaptchaUnavailable(
            "未安装 Playwright，无法自动过验证码。"
            "请执行: pip install playwright && playwright install chromium"
        ) from exc
    from playwright.sync_api import sync_playwright

    return sync_playwright


# ---------------------------------------------------------------------------
# 图像处理：滑块缺口定位
# ---------------------------------------------------------------------------
def _to_gray(img):
    return img.convert("L")


def _ncc(piece_pixels, patch_pixels, n, sp, sp2):
    """
    计算 piece 与 patch 的归一化互相关（NCC），返回 [-1, 1] 的得分。

    NCC 对整体明暗变化不敏感，正好适合易盾这种"原图被压暗成缺口"的场景。
    """
    sb = sum(patch_pixels)
    sb2 = sum(v * v for v in patch_pixels)
    spb = sum(p * b for p, b in zip(piece_pixels, patch_pixels))
    num = n * spb - sp * sb
    den = ((n * sp2 - sp * sp) * (n * sb2 - sb * sb)) ** 0.5
    if den <= 0:
        return -1.0
    return num / den


def detect_gap(bg_image, piece_image=None, piece_left=0, piece_top=0, x_min=None, x_max=None):
    """
    在背景图中找出滑块缺口（拼图块要拖到的位置）。

    * bg_image: 背景截图（不含滑块拼图本身）
    * piece_image: 滑块拼图（带 alpha 通道的 PNG），可为 None
    * piece_left: 拼图块当前在背景图中的左边界（拖动距离 = 缺口位置 - 该值）
    * piece_top: 拼图块当前在背景图中的上边界（拼图块只能水平移动，y 固定）

    返回 (target_x, score)，target_x 是缺口左边界在背景图中的像素坐标。
    """
    if bg_image is None:
        return None, 0.0
    bg = _to_gray(bg_image)
    width, height = bg.size
    x_min = 0 if x_min is None else max(0, int(x_min))
    x_max = width if x_max is None else min(width, int(x_max))

    if piece_image is not None:
        piece = piece_image
        if piece.size[0] > width or piece.size[1] > height:
            return None, 0.0
        # 模板过大基本说明取错了元素，直接放弃（否则会拖出很离谱的距离）
        if piece.size[0] * piece.size[1] > 0.4 * width * height:
            return None, 0.0
        # 只看不透明的部分，避免拼图块的透明边角干扰
        alpha = piece.convert("RGBA").split()[-1]
        bbox = alpha.getbbox()
        if bbox:
            piece = piece.crop(bbox)
            alpha = alpha.crop(bbox)
        pg = _to_gray(piece)
        pw, ph = pg.size
        # 用 alpha 做掩码：把透明处置成图片均值，等价于不参与相关
        mask = alpha.point(lambda v: 255 if v > 32 else 0)
        mean = ImageStat.Stat(pg, mask=mask).mean[0]
        pg = Image.composite(pg, Image.new("L", pg.size, int(mean)), mask)
        pg_pixels = list(pg.tobytes())
        n = pw * ph
        sp = sum(pg_pixels)
        sp2 = sum(v * v for v in pg_pixels)

        top = max(0, min(int(piece_top), height - ph))
        best_x, best_score = None, float("-inf")
        limit = max(x_min, min(x_max, width - pw))
        for x in range(x_min, limit + 1):
            if ph > height:
                break
            patch_pixels = list(bg.crop((x, top, x + pw, top + ph)).tobytes())
            score = _ncc(pg_pixels, patch_pixels, n, sp, sp2)
            if score > best_score:
                best_x, best_score = x, score
        if best_x is None:
            return None, 0.0
        return best_x, best_score

    # 没有拼图块时的兜底：找"比周围明显偏暗"的竖直条带（易盾的缺口是一块半透明阴影）
    blur = bg.resize((max(1, width // 8), max(1, height // 8))).resize((width, height))
    diff = ImageChops.subtract(blur, bg)  # 比局部背景更暗的地方为正
    cols = []
    for x in range(width):
        column = diff.crop((x, 0, x + 1, height))
        cols.append(ImageStat.Stat(column).mean[0])
    if not cols:
        return None, 0.0
    lo = x_min if x_min is not None else min(60, width // 4)
    hi = x_max if x_max is not None else width
    best_x = max(range(max(0, lo), min(width, hi)), key=lambda i: cols[i])
    return best_x, cols[best_x] / 255.0


def human_track(distance: float, steps: Optional[int] = None) -> list:
    """
    生成一条"像人"的拖动轨迹（只返回每一步相对起点的 x 偏移）。

    先快后慢（ease-out）、带轻微过冲和回弹，避免被判定为机器匀速拖动。
    """
    distance = float(distance)
    if distance <= 0:
        return []
    steps = steps or random.randint(18, 26)
    track = []
    for i in range(1, steps + 1):
        t = i / steps
        ease = 1 - (1 - t) ** 3
        jitter = random.uniform(-1.2, 1.2) * (1 - t)
        track.append(distance * ease + jitter)
    # 过冲一点点再回弹，更像人手
    track.append(distance + random.uniform(1.0, 3.0))
    track.append(distance + random.uniform(0.3, 1.0))
    track.append(distance)
    return track

def build_click_prompt(tips, width, height):
    """点选验证码的提问模板：先逐字分析，再给坐标"""
    lines = [
        "这是一个网易易盾的人机验证码图片，尺寸 %dx%d 像素。" % (width, height),
        "图中的字符可能被旋转、颜色不同。",
        "验证码要求：" + (tips or "按图片内容点击"),
        "",
        "请严格按顺序思考：",
        "1) 先把图中每个字符逐一列出来：字符是什么、什么颜色、大概位置、朝向；",
        "2) 再对照题目判断哪一个才是要点的目标（题目里可能提到两个字符，",
        "   一个只是参照物，另一个才是目标，千万不要点参照物）；",
        "3) 最后给出目标字符中心的像素坐标。",
        "",
        '只输出 JSON：{"analysis": "你的逐字分析", "points": [[x, y]]}，',
        "points 按点击顺序排列，坐标基于本图（左上角是 (0,0)）。",
    ]
    return "\n".join(lines)


def snap_point_to_ink(image, x, y, radius=50):
    """
    点选验证码的坐标经常"差一点"落在字符旁边的背景上。

    背景是浅灰纯色，字符是彩色/深色，用"饱和度 + 暗度"当墨迹分数：
    如果点周围明显是背景，就在附近找一个墨迹最浓的像素吸附过去。
    """
    try:
        rgb = image.convert("RGB")
        hsv = rgb.convert("HSV")
        width, height = rgb.size
        _, saturation, value = hsv.split()   # HSV 三个波段顺序是 H/S/V
        ps, pv = saturation.load(), value.load()
        ix, iy = int(x), int(y)
        if not (0 <= ix < width and 0 <= iy < height):
            return x, y

        def ink(cx, cy):
            cx = max(0, min(width - 1, cx))
            cy = max(0, min(height - 1, cy))
            return ps[cx, cy] + (255 - pv[cx, cy])

        local = 0
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                local += ink(ix + dx, iy + dy)
        if local / 25.0 >= 45:
            return x, y   # 已经落在字符上

        best = None
        for dy in range(-radius, radius + 1, 2):
            for dx in range(-radius, radius + 1, 2):
                cx, cy = ix + dx, iy + dy
                if not (0 <= cx < width and 0 <= cy < height):
                    continue
                score = ink(cx, cy) - (abs(dx) + abs(dy)) * 0.6
                if best is None or score > best[0]:
                    best = (score, cx, cy)
        if best and best[0] > 45:
            return float(best[1]), float(best[2])
        return x, y
    except Exception:
        return x, y


# ---------------------------------------------------------------------------
# 浏览器求解器
# ---------------------------------------------------------------------------
class CaptchaSolver:
    """
    用真实浏览器通过知到弹出的易盾滑块验证码。

    * headless: 无头模式。默认 False —— 失败时可以直接人工接管
    * manual_fallback: 自动拖动失败后是否等待人工拖动
    * timeout: 整体超时（秒）
    * cookies: 脚本当前会话的 cookies（RequestsCookieJar 或 dict）
    * debug_dir: 非空时把验证码截图保存下来，方便排查
    """

    def __init__(
        self,
        headless: bool = False,
        manual_fallback: bool = True,
        timeout: int = 180,
        cookies=None,
        user_agent: str = DEFAULT_USER_AGENT,
        captcha_id: str = CAPTCHA_ID_SPACE,
        browser_channel: str = "",
        proxy: Optional[dict] = None,
        debug_dir: str = "",
        auto_attempts: int = 6,
        vision: dict = None,
        logger=None,
    ):
        self.headless = headless
        self.manual_fallback = manual_fallback
        self.timeout = max(30, int(timeout))
        self.cookies = cookies
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.captcha_id = captcha_id or CAPTCHA_ID_SPACE
        self.browser_channel = browser_channel or ""
        self.proxy = proxy or None
        self.debug_dir = debug_dir or ""
        self.auto_attempts = max(1, int(auto_attempts))
        self.vision = vision or {}
        self._vision_failures = 0
        self.log = logger or (lambda *a, **k: None)
        self._last_error = ""

    # -- 对外接口 ---------------------------------------------------------
    @staticmethod
    def available() -> bool:
        try:
            _require_playwright()
            return True
        except CaptchaUnavailable:
            return False

    def solve(self) -> Optional[str]:
        """打开验证码并尝试通过，成功返回 validate 字符串。"""
        sync_playwright = _require_playwright()
        self._last_error = ""
        try:
            playwright = sync_playwright().start()
        except Exception as exc:
            raise CaptchaUnavailable(f"Playwright 启动失败: {exc}") from exc
        browser = None
        try:
            launch_kwargs = {
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            }
            if self.browser_channel:
                launch_kwargs["channel"] = self.browser_channel
            if self.proxy:
                launch_kwargs["proxy"] = self.proxy
            try:
                browser = playwright.chromium.launch(**launch_kwargs)
            except Exception as exc:
                # 没下载 chromium 时，尝试用系统已装的 Edge / Chrome
                self.log("warning", "启动 Chromium 失败(%s)，尝试使用系统 Edge/Chrome" % exc)
                browser = None
                for channel in ("msedge", "chrome"):
                    try:
                        launch_kwargs["channel"] = channel
                        browser = playwright.chromium.launch(**launch_kwargs)
                        break
                    except Exception:
                        continue
                if browser is None:
                    raise

            context = browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1366, "height": 800},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            self._apply_cookies(context)
            page = context.new_page()
            return self._solve_in_page(page)
        finally:
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            try:
                playwright.stop()
            except Exception:
                pass

    # -- 内部实现 ---------------------------------------------------------
    def _apply_cookies(self, context):
        cookies = self.cookies
        if not cookies:
            return
        items = []
        try:
            raw = cookies.items()
        except AttributeError:
            raw = []
        for name, value in raw:
            items.append({
                "name": str(name),
                "value": str(value),
                "domain": ".zhihuishu.com",
                "path": "/",
            })
        if items:
            try:
                context.add_cookies(items)
            except Exception as exc:
                self.log("warning", "写入 cookies 失败: %s" % exc)

    def _solve_in_page(self, page) -> Optional[str]:
        deadline = time.time() + self.timeout
        last_error = None
        opened = False
        for url in PAGE_URLS:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                opened = True
                break
            except Exception as exc:
                last_error = exc
        if not opened:
            raise CaptchaSolveTimeout("打开智慧树页面失败: %s" % last_error)

        self._inject_loader(page)
        self._init_widget(page)

        slide_attempts = 0
        click_attempts = 0
        manual_hint = "slide"
        slide_announced = False
        click_announced = False

        while time.time() < deadline:
            validate = self._read_validate(page)
            if validate:
                return validate
            if self._widget_failed(page):
                self._init_widget(page)
                time.sleep(1.0)
                continue
            frame = self._find_captcha_frame(page)
            if frame is None:
                time.sleep(0.4)
                continue

            kind = self._captcha_kind(frame)
            if kind == "slide":
                manual_hint = "slide"
                if slide_attempts < self.auto_attempts and self._slider_ready(frame):
                    slide_attempts += 1
                    self.log("info", "尝试验证码自动拖动 第 %d 次" % slide_attempts)
                    if self._auto_slide(page):
                        time.sleep(0.8)  # 等服务端返回 validate
                        validate = self._read_validate(page)
                        if validate:
                            return validate
                    time.sleep(1.2)
                    continue
                if slide_attempts >= self.auto_attempts and not slide_announced:
                    slide_announced = True
                    self.log("warning",
                             "滑块自动拖动没成功，请在窗口中手动拖动"
                             "（拖完脚本会自动继续）")
            elif kind == "click":
                manual_hint = "click"
                if self._vision_available():
                    if click_attempts < self.auto_attempts and self._click_ready(frame):
                        click_attempts += 1
                        self.log("info", "尝试验证码自动点击 第 %d 次" % click_attempts)
                        if self._auto_click(page, frame):
                            time.sleep(1.0)
                            validate = self._read_validate(page)
                            if validate:
                                return validate
                        time.sleep(1.5)
                        continue
                    if click_attempts >= self.auto_attempts and not click_announced:
                        click_announced = True
                        self.log("warning",
                                 "点选验证码自动识别没成功，请在窗口中手动点击"
                                 "（点完脚本会自动继续）")
                elif not click_announced:
                    click_announced = True
                    self.log("warning",
                             "检测到点选类验证码，请在弹出的窗口中按提示点击完成验证"
                             "（点完脚本会自动继续）")
            time.sleep(0.4)

        if self.manual_fallback and not self.headless:
            hint = "点击" if manual_hint == "click" else "拖动"
            self.log("warning", "自动处理未通过，请在打开的验证码窗口中手动%s" % hint)
            manual_deadline = time.time() + 300
            while time.time() < manual_deadline:
                validate = self._read_validate(page)
                if validate:
                    return validate
                time.sleep(0.5)
        raise CaptchaSolveTimeout(self._last_error or "超时未通过验证码")

    def _inject_loader(self, page):
        try:
            page.add_script_tag(url=LOADER_URL)
            page.wait_for_function(
                "typeof window.initNECaptchaWithFallback === 'function'", timeout=30000
            )
        except Exception as exc:
            raise CaptchaSolveTimeout(
                "加载易盾验证码脚本失败(检查网络/代理): %s" % exc
            ) from exc

    def _init_widget(self, page):
        page.evaluate(
            """
            (captchaId) => {
                const old = document.querySelector('#captchaYidun');
                if (old) old.remove();
                const box = document.createElement('div');
                box.id = 'captchaYidun';
                box.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647';
                document.body.appendChild(box);
                window.__zhsCaptcha = { validate: null, error: null, closed: false, instance: null };
                window.initNECaptchaWithFallback({
                    element: '#captchaYidun',
                    captchaId: captchaId,
                    mode: 'popup',
                    width: '320px',
                    lang: 'zh-CN',
                    enableClose: true,
                    onVerify: function (err, data) {
                        if (err) { window.__zhsCaptcha.error = String((err && err.message) || err); return; }
                        window.__zhsCaptcha.validate = (data && data.validate) || null;
                    },
                    onError: function (err) {
                        window.__zhsCaptcha.error = String((err && err.message) || err);
                    },
                    onClose: function () { window.__zhsCaptcha.closed = true; }
                }, function (instance) {
                    window.__zhsCaptcha.instance = instance;
                    try { instance.popUp(); } catch (e) { window.__zhsCaptcha.error = String(e); }
                }, function (err) {
                    window.__zhsCaptcha.error = String((err && err.message) || err);
                });
            }
            """,
            self.captcha_id,
        )

    def _read_validate(self, page) -> Optional[str]:
        try:
            value = page.evaluate("() => (window.__zhsCaptcha && window.__zhsCaptcha.validate) || null")
        except Exception:
            return None
        return value or None

    def _widget_failed(self, page) -> bool:
        try:
            err = page.evaluate("() => (window.__zhsCaptcha && window.__zhsCaptcha.error) || null")
        except Exception:
            return False
        self._last_error = err or ""
        return bool(err)

    def _find_captcha_frame(self, page):
        """验证码可能渲染在主页面，也可能在易盾的 iframe 里。滑块/点选都有 .yidun_bgimg"""
        try:
            if page.query_selector(".yidun_bgimg"):
                return page.main_frame
        except Exception:
            pass
        for frame in page.frames:
            try:
                if frame.query_selector(".yidun_bgimg"):
                    return frame
            except Exception:
                continue
        return None

    def _read_tips(self, frame) -> str:
        """读取验证码的提示文案，例如"请依次点击..." / "请点击小写q朝向一样的大写F" """
        js = """
        () => {
            const sels = ['.yidun_tips__text', '.yidun_tips', '.yidun_tips__content', '.yidun_panel'];
            for (const s of sels) {
                const e = document.querySelector(s);
                if (e && e.innerText && e.innerText.trim()) return e.innerText.trim();
            }
            return '';
        }
        """
        try:
            return str(frame.evaluate(js) or "").strip()
        except Exception:
            return ""

    def _visible(self, frame, selector) -> bool:
        """元素存在且真的可见（易盾面板里会藏一些不显示的控件，不能只看存在性）"""
        try:
            el = frame.query_selector(selector)
            if not el:
                return False
            if hasattr(el, "is_visible"):
                try:
                    return bool(el.is_visible())
                except Exception:
                    pass
            box = el.bounding_box()
            return bool(box and box.get("width", 0) > 0 and box.get("height", 0) > 0)
        except Exception:
            return False

    def _captcha_kind(self, frame) -> str:
        """
        判断当前题型。

        先看提示文案（最可靠），再看可见控件：
        * 提示里有"点击/依次/选择" -> 点选
        * 有可见的 .yidun_slider -> 滑块
        * 只有图、没有可见滑块 -> 按点选处理（宁可提示人工点，也不乱拖）
        """
        tips = self._read_tips(frame)
        if any(k in tips for k in ("点击", "依次", "选择")):
            return "click"
        if any(k in tips for k in ("拖动", "滑动", "拼图")):
            return "slide" if self._visible(frame, ".yidun_slider") else "unknown"
        if self._visible(frame, ".yidun_slider"):
            return "slide"
        if self._visible(frame, ".yidun_point"):
            return "click"
        if self._visible(frame, ".yidun_bgimg"):
            return "click"
        return "unknown"

    def _refresh_captcha(self, frame):
        """刷新一张新的验证码图片（识别失败时用，避免在旧图上反复试）"""
        try:
            el = frame.query_selector(".yidun_refresh")
            if el is None:
                return
            if hasattr(el, "is_visible") and not el.is_visible():
                return
            el.click()
            time.sleep(0.8)
        except Exception:
            pass

    def _slider_ready(self, frame) -> bool:
        try:
            el = frame.query_selector(".yidun_bgimg")
            if not el:
                return False
            box = el.bounding_box()
            return bool(box and box.get("width", 0) > 100 and box.get("height", 0) > 50)
        except Exception:
            return False

    # -- 点选类验证码 ---------------------------------------------------
    def _vision_extra_body(self):
        """
        思考模式开关。

        * "auto"(默认): 只有 deepseek 才显式关闭（它默认开启思考，会把 token 花在思维链上）
        * "true"/"false": 强制开启/关闭
        """
        thinking = str((self.vision or {}).get("thinking", "auto")).strip().lower()
        base = str((self.vision or {}).get("api_base") or "").lower()
        if thinking in ("0", "false", "off", "disabled", "none"):
            return {"thinking": {"type": "disabled"}}
        if thinking in ("1", "true", "on", "enabled"):
            return {"thinking": {"type": "enabled"}}
        if "deepseek" in base:
            return {"thinking": {"type": "disabled"}}
        return None

    def _vision_available(self) -> bool:
        v = self.vision or {}
        if self._vision_failures >= 2:
            # 连续失败两次就别再调了（模型不支持图片 / key 不对 / 网络不通），直接人工
            return False
        return bool(v.get("enabled") and (v.get("model") or v.get("api_key")))

    def _click_ready(self, frame) -> bool:
        return self._slider_ready(frame)

    def _auto_click(self, page, frame) -> bool:
        """点选类：截图 -> 问多模态模型要坐标 -> 依次点击"""
        if not Image:
            self._last_error = "缺少 Pillow，无法读取验证码图片"
            return False
        try:
            bg_el = frame.query_selector(".yidun_bgimg")
            box = bg_el.bounding_box() if bg_el else None
            if not box:
                return False
            shot = bg_el.screenshot()
        except Exception as exc:
            self._last_error = "验证码截图失败: %s" % exc
            return False

        tips = self._read_tips(frame)
        img = Image.open(io.BytesIO(shot)).convert("RGB")
        points = self._ask_vision_click(shot, tips)
        # 模型给的坐标常常偏到字符旁边的背景上，吸附到最近的"墨迹"里
        if points:
            points = [snap_point_to_ink(img, x, y) for (x, y) in points]
        self._save_debug(shot, None, None)
        if not points:
            self._last_error = "多模态模型没有给出可用的点击坐标"
            return False

        scale_x = (box.get("width") or img.width) / float(img.width or 1)
        scale_y = (box.get("height") or img.height) / float(img.height or 1)
        self.log("info", "点选验证码: %s -> %s" % (tips or "(无提示)", points))
        for (px, py) in points:
            page.mouse.click(box["x"] + px * scale_x,
                             box["y"] + py * scale_y)
            time.sleep(random.uniform(0.25, 0.6))
        return True

    def _ask_vision_click(self, shot, tips):
        """把验证码图片 + 提示交给多模态模型，返回图片像素坐标列表"""
        try:
            from openai import OpenAI  # 项目本身已经依赖 openai
        except Exception as exc:
            self._vision_failures += 1
            self.log("warning", "未安装 openai，无法用多模态模型过点选验证码: %s" % exc)
            return []
        try:
            img = Image.open(io.BytesIO(shot)).convert("RGB")
            width, height = img.size
        except Exception:
            return []

        # 验证码原图只有 320x160 左右，放大 2 倍再给模型，字更清楚
        zoom = 2 if max(width, height) <= 800 else 1
        if zoom != 1:
            big = img.resize((width * zoom, height * zoom), Image.LANCZOS)
            buf = io.BytesIO()
            big.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            send_w, send_h = width * zoom, height * zoom
        else:
            b64 = base64.b64encode(shot).decode()
            send_w, send_h = width, height

        prompt = build_click_prompt(tips, send_w, send_h)
        try:
            client = OpenAI(base_url=self.vision.get("api_base") or None,
                            api_key=self.vision.get("api_key") or "sk-empty",
                            timeout=90)
            kwargs = {
                "model": self.vision.get("model") or "gpt-4o",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": "data:image/png;base64," + b64}},
                    ],
                }],
                # DeepSeek 默认开思考模式，思维链会把小额度吃光导致 content 为空，
                # 所以这里给足额度，并在需要时显式关掉思考
                "max_tokens": int(self.vision.get("max_tokens") or 5000),
            }
            extra_body = self._vision_extra_body()
            if extra_body:
                kwargs["extra_body"] = extra_body
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as exc:
                # 有些中转网关不认识 thinking 参数，去掉再试一次
                if "extra_body" not in kwargs:
                    raise
                self.log("warning", "带 thinking 参数调用失败(%s)，去掉后重试" % exc)
                kwargs.pop("extra_body", None)
                resp = client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            text = choice.message.content or ""
            if not text:
                reasoning = getattr(choice.message, "reasoning_content", None) or ""
                self._vision_failures += 1
                self.log("warning",
                         "多模态模型返回空内容(finish_reason=%s, 思维链%d字)，"
                         "多半是思考模式把 token 用完了"
                         % (getattr(choice, "finish_reason", "?"), len(reasoning)))
                return []
        except Exception as exc:
            self._vision_failures += 1
            self.log("warning", "多模态模型调用失败(%d/2): %s" % (self._vision_failures, exc))
            return []
        points = self._parse_points(text, send_w, send_h)
        if points and zoom != 1:
            points = [(x / zoom, y / zoom) for (x, y) in points]
        if not points:
            self._vision_failures += 1
            self.log("warning", "多模态模型没有返回可用坐标(%d/2): %s"
                     % (self._vision_failures, (text or "")[:200]))
        return points

    @staticmethod
    def _parse_points(text, width=0, height=0):
        """从模型回复里解析点击坐标，容忍代码块/解释文字/0~1 归一化坐标"""
        import json
        import re

        if not text:
            return []
        raw = None
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    raw = data.get("points") or data.get("points_list") or data.get("点")
                elif isinstance(data, list):
                    raw = data
            except Exception:
                raw = None
        if raw is None:
            pairs = re.findall(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", text)
            raw = [[float(a), float(b)] for a, b in pairs]
        points = []
        dropped = []
        for item in raw or []:
            try:
                x, y = float(item[0]), float(item[1])
            except Exception:
                continue
            # 有的模型会返回 0~1 的比例坐标
            if width and height and 0 <= x <= 1 and 0 <= y <= 1 and (x != 0 or y != 0):
                x, y = x * width, y * height
            if width and height and not (0 <= x <= width and 0 <= y <= height):
                dropped.append((x, y))
                continue
            points.append((x, y))
        # 有的模型（比如 qwen-vl）用 0~1000 的相对坐标：全都越界时按这个比例再换算一次
        if not points and dropped and width and height:
            values = [v for pair in dropped for v in pair]
            if values and max(values) <= 1000 and max(values) > max(width, height):
                for x, y in dropped:
                    px, py = x / 1000.0 * width, y / 1000.0 * height
                    if 0 <= px <= width and 0 <= py <= height:
                        points.append((px, py))
        return points[:6]

    def _auto_slide(self, page) -> bool:
        frame = self._find_captcha_frame(page)
        if frame is None:
            return False
        try:
            info = frame.evaluate(
                r"""
                () => {
                    const bg = document.querySelector('.yidun_bgimg');
                    const jig = document.querySelector('.yidun_jigsaw');
                    const slider = document.querySelector('.yidun_slider');
                    if (!bg || !slider) return null;
                    const b = bg.getBoundingClientRect();
                    const j = jig ? jig.getBoundingClientRect() : null;
                    let img = null;
                    const node = jig && (jig.querySelector('img') || jig);
                    if (node && node.tagName === 'IMG') img = node.src;
                    if (!img && jig) {
                        const style = getComputedStyle(jig);
                        const m = /url\(["']?(.*?)["']?\)/.exec(style.backgroundImage || '');
                        if (m) img = m[1];
                    }
                    return {
                        bg: {x: b.x, y: b.y, w: b.width, h: b.height},
                        pieceLeft: j ? (j.x - b.x) : 0,
                        pieceTop: j ? (j.y - b.y) : 0,
                        pieceW: j ? j.width : 52,
                        pieceH: j ? j.height : 52,
                        image: img
                    };
                }
                """
            )
        except Exception as exc:
            self._last_error = str(exc)
            return False
        if not info:
            return False

        if not Image:
            self._last_error = "缺少 Pillow，无法识别滑块"
            return False
        bg_el = frame.query_selector(".yidun_bgimg")
        try:
            shot_with_piece = bg_el.screenshot()   # 带拼图，用来裁模板
        except Exception as exc:
            self._last_error = "验证码截图失败: %s" % exc
            return False
        try:
            frame.evaluate(
                "() => document.querySelectorAll('.yidun_jigsaw').forEach(e => e.style.visibility='hidden')"
            )
            shot = bg_el.screenshot()              # 不带拼图，用来找缺口
        finally:
            try:
                frame.evaluate(
                    "() => document.querySelectorAll('.yidun_jigsaw').forEach(e => e.style.visibility='')"
                )
            except Exception:
                pass

        bg_image = Image.open(io.BytesIO(shot)).convert("RGB")
        scale = (info["bg"]["w"] or 1) / float(bg_image.width or 1)
        piece_left = float(info.get("pieceLeft") or 0) / scale
        piece_top = float(info.get("pieceTop") or 0) / scale
        piece_image = self._load_piece(frame, info.get("image"))
        if piece_image is None:
            piece_image = self._crop_piece(shot_with_piece, info, scale, bg_image)
        target, score = detect_gap(
            bg_image, piece_image, piece_left=piece_left, piece_top=piece_top
        )
        self._save_debug(shot, piece_image, target)
        if target is None:
            self._last_error = "未能识别滑块缺口"
            self._refresh_captcha(frame)
            return False
        # 置信度太低说明模板根本对不上（例如其实是点选验证码），绝不能硬拖
        if score < 0.35:
            self._last_error = "缺口识别置信度过低(score=%.3f)，取消本次拖动" % score
            self.log("warning", self._last_error)
            self._refresh_captcha(frame)
            return False

        bg_width = float(info["bg"].get("w") or 320)
        distance = target - piece_left
        if not (5 <= distance <= bg_width * 0.9):
            self._last_error = ("缺口位置异常: target=%.1f piece=%.1f distance=%.1f"
                                % (target, piece_left, distance))
            self.log("warning", self._last_error)
            self._refresh_captcha(frame)
            return False
        self.log("info", "滑块缺口 x=%.1fpx 拖动 %.1fpx (score=%.3f)" % (target, distance, score))

        slider = frame.query_selector(".yidun_slider")
        box = slider.bounding_box()
        if not box:
            return False
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        self._drag(page, start_x, start_y, distance)
        return True

    def _crop_piece(self, shot_with_piece, info, scale, bg_image):
        """拿不到拼图图片时，直接从"带拼图"的截图里裁一块当模板"""
        try:
            img = Image.open(io.BytesIO(shot_with_piece)).convert("RGB")
            ratio = (img.width or 1) / float(info["bg"]["w"] or 1)
            left = int(float(info.get("pieceLeft") or 0) * ratio)
            top = int(float(info.get("pieceTop") or 0) * ratio)
            w = int(float(info.get("pieceW") or 52) * ratio)
            h = int(float(info.get("pieceH") or 52) * ratio)
            # 有些版本 .yidun_jigsaw 是整个图片容器，宽高会等于背景图，
            # 这时候裁出来的是整张图，退回到一个合理的拼图尺寸
            if w > img.width * 0.6:
                w = min(60, max(30, img.width // 5))
                h = w
            box = (max(0, left), max(0, top),
                   min(img.width, left + w), min(img.height, top + h))
            if box[2] - box[0] < 10 or box[3] - box[1] < 10:
                return None
            return img.crop(box).convert("RGBA")
        except Exception:
            return None

    def _load_piece(self, frame, image_url):
        if not Image or not image_url:
            return None
        try:
            if image_url.startswith("data:"):
                raw = base64.b64decode(image_url.split(",", 1)[-1])
            else:
                if image_url.startswith("//"):
                    image_url = "https:" + image_url
                # 直接用 urllib 下载，避免浏览器里跨域 fetch 被 CORS 拦住
                req = urllib.request.Request(
                    image_url, headers={"User-Agent": self.user_agent,
                                        "Referer": "https://www.zhihuishu.com/"})
                raw = urllib.request.urlopen(req, timeout=20).read()
            img = Image.open(io.BytesIO(raw))
            return img.convert("RGBA")
        except Exception as exc:
            self.log("debug", "读取滑块图片失败: %s" % exc)
            return None

    def _drag(self, page, start_x, start_y, distance):
        page.mouse.move(start_x, start_y)
        time.sleep(random.uniform(0.08, 0.18))
        page.mouse.down()
        time.sleep(random.uniform(0.05, 0.12))
        for offset in human_track(distance):
            page.mouse.move(start_x + offset, start_y + random.uniform(-1.5, 1.5))
            time.sleep(random.uniform(0.008, 0.03))
        time.sleep(random.uniform(0.08, 0.2))
        page.mouse.up()

    def _save_debug(self, shot, piece, target):
        if not self.debug_dir or not Image:
            return
        try:
            os.makedirs(self.debug_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = os.path.join(self.debug_dir, "captcha-%s.png" % stamp)
            img = Image.open(io.BytesIO(shot)).convert("RGB")
            if target is not None:
                from PIL import ImageDraw

                d = ImageDraw.Draw(img)
                d.line([(target, 0), (target, img.height)], fill=(255, 0, 0), width=2)
            img.save(path)
            if piece is not None:
                piece.save(os.path.join(self.debug_dir, "captcha-%s-piece.png" % stamp))
        except Exception:
            pass


def main():  # pragma: no cover - 命令行自测用
    import argparse

    parser = argparse.ArgumentParser(description="单独测试知到验证码自动通过（滑块/点选）")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--captcha-id", default=CAPTCHA_ID_SPACE)
    parser.add_argument("--debug-dir", default="captcha_debug")
    parser.add_argument("--vision-base", default="", help="多模态模型 api_base，用于点选类")
    parser.add_argument("--vision-key", default="", help="多模态模型 api_key")
    parser.add_argument("--vision-model", default="", help="多模态模型名，例如 gpt-4o")
    args = parser.parse_args()
    vision = {
        "enabled": bool(args.vision_key and args.vision_model),
        "api_base": args.vision_base,
        "api_key": args.vision_key,
        "model": args.vision_model,
    }
    solver = CaptchaSolver(
        headless=args.headless,
        timeout=args.timeout,
        captcha_id=args.captcha_id,
        debug_dir=args.debug_dir,
        vision=vision,
        logger=lambda level, msg: print("[%s] %s" % (level, msg)),
    )
    validate = solver.solve()
    print("validate:", validate)


if __name__ == "__main__":  # pragma: no cover
    main()
