import os
import re
import json
import argparse
import requests
import platform
from functools import partial
from contextlib import suppress
from commander import Commander
from logger import logger
from ObjDict import ObjDict
from utils import showImage, cookie_jar_to_list
from utils import getConfigPath, getRealPath, versionCmp, fillDefaults

DEFAULT_CONFIG = {
    "username": "",
    "password": "",
    "qrlogin": True,
    "save_cookies": True,
    "proxies": {},
    "logLevel": "INFO",
    "tree_view": True,
    "progressbar_view": True,
    "qr_extra": {
        "show_in_terminal": None,
        "ensure_unicode": False
    },
    "image_path":"",
    "pushplus": {
        "enable": False,
        "token": ""
    },
    "bark":{
        "enable": False,
        "token": "https://example.com/xxxxxxxxx"
    },
    "captcha": {
        "solver": "auto",
        "headless": False,
        "timeout": 180,
        "max_retries": 3,
        "browser_channel": "",
        "captcha_id": "4da3050565514a35a50541b0e1f54538",
        "debug_dir": "",
        "vision": {
            "enabled": False,
            "api_base": "",
            "api_key": "",
            "model": "",
            "thinking": "auto",
            "max_tokens": 1200
        }
    },
    "homework": {
        "answer": {
            "api_base": "",
            "api_key": "",
            "model": "",
            "thinking": "auto"
        }
    },
    "config_version": "1.5.0",
    "ai": {
        "enabled": True,
        "use_zhidao_ai": True,
        "openai": {
            "api_base": "https://api.openai.com",
            "api_key": "sk-",
            "model_name": "claude-3-5-sonnet-20240620"
        },
        "ppt_processing": {
            "provide_to_ai": False,
            "moonShot": {
                "base_url": "https://api.moonshot.cn/v1",
                "api_key": "sk-",
                "delete_after_convert": True
            }
        },
        "use_stream": True
    }
}
# get config or create one if not exist
if os.path.isfile(getConfigPath()):
    with open(getConfigPath(), 'r+', encoding="UTF-8") as f:
        # 不指定编码格式会导致config中可能存在的中文字符乱码
        config = ObjDict(json.load(f), default=None)
        if "config_version" not in config:
            config.config_version = "1.0.0"
        if versionCmp(config.config_version, DEFAULT_CONFIG["config_version"]) < 0:
            new = ObjDict(DEFAULT_CONFIG, default=None)
            if versionCmp(config.config_version, "1.0.1") < 0:
                config.pop("qr_extra", None)
            if versionCmp(config.config_version, "1.3.0") < 0:
                pushplus = config.pop("push", {})
                new.pushplus.update(pushplus)
            config.pop("config_version", None)
            new.update(config)
            config = new
            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
            print("****Config file updated****")
else:
    config = ObjDict(DEFAULT_CONFIG, default=None)
    with open(getConfigPath(), 'w') as f:
        json.dump(config, f, indent=4)

# 把版本升级新增的配置段补进旧配置（只补缺失项，不动你填过的值）
try:
    with open(getConfigPath(), 'r', encoding="UTF-8") as f:
        filled = ObjDict(json.load(f), default=None)
    if fillDefaults(filled, ObjDict(DEFAULT_CONFIG, default=None)):
        with open(getConfigPath(), 'w', encoding="UTF-8") as f:
            json.dump(filled, f, indent=4, ensure_ascii=False)
        config = filled
        print("****config.json 已补全新增配置项（不会覆盖已有值）****")
except Exception as e:
    print(f"*补全配置失败: {e}")

# parse arguments
parser = argparse.ArgumentParser(prog="LeaderTree 指挥树")
parser.add_argument("-c", "--course", type=str, nargs="+",
                    help="CourseId or recruitAndCourseId, can be found in URL")
parser.add_argument("-v", "--videos", type=str, nargs="+",
                    help="Video IDs(fileId in URL, or, videoId found in API response")
parser.add_argument("-u", "--username", type=str,
                    help="if not set anywhere, will be prompted")
parser.add_argument("-p", "--password", type=str,
                    help="If not set anywhere, will be prompted. Be careful, it will be stored in history")
parser.add_argument("-s", "--speed", type=float,
                    help="Video Play Speed, default value is maximum speed found on site")
parser.add_argument("-t", "--threshold", type=float,
                    help="Video End Threshold, above this will be considered finished, overloaded when there are questions left unanswered")
parser.add_argument("-l", "--limit", type=int, default=0,
                    help="Time Limit (in minutes, 0 for no limit), default is 0")
parser.add_argument("-q", "--qrlogin", action="store_true",
                    help="Use QR Login")
parser.add_argument("-d", "--debug", action="store_true", help="Debug Mode")
parser.add_argument("-f", "--fetch", action="store_true",
                    help="Fetch new course list")
parser.add_argument("--show_in_terminal",
                    action="store_true", help="Show QR in terminal")
parser.add_argument("--proxy", type=str,
                    help="Proxy Config, e.g: http://127.0.0.1:8080")
parser.add_argument("--tree_view", type=bool,
                    help="print the tree progress view of the course")
parser.add_argument("--progressbar_view", type=bool,
                    help="print the progressbar view of the course")
parser.add_argument("--image_path", type=str,
                    help="Image save path, default is empty (do not save)")
parser.add_argument("--captcha_solver", type=str,
                    choices=["auto", "manual", "none"],
                    help="验证码处理方式: auto(浏览器自动过滑块) / manual(弹窗等人工拖) / none(旧行为)")
parser.add_argument("--captcha_headless", type=bool,
                    help="验证码浏览器是否无头运行, 默认 False 以便自动失败时人工接管")
parser.add_argument("--captcha_timeout", type=int,
                    help="等待验证码通过的秒数, 默认 180")
parser.add_argument("--captcha_channel", type=str,
                    help="用系统已装浏览器跑验证码: msedge / chrome")
parser.add_argument("--captcha_debug", type=str,
                    help="验证码调试截图保存目录")
parser.add_argument("-ai", "--aicourse", type=str, nargs=2,
                    metavar=('COURSE_ID', 'CLASS_ID'),
                    help="AI 课程 ID 和班级 ID，用来攻打 AI 课程")

parser.add_argument("--noexam", type=bool,
                    help="Disable AI exam")

args = parser.parse_args()

course = args.course
username = args.username or config.username
password = args.password or config.password
qrlogin = args.qrlogin or config.qrlogin or True  # Force enabled for v2.3.*
save_cookies = config.save_cookies or False
qr_extra = config.qr_extra or ObjDict(default=None)
show_in_terminal = args.show_in_terminal or config.qr_extra.show_in_terminal
tree_view = args.tree_view or config.tree_view
progressbar_view = args.progressbar_view or config.progressbar_view
image_path = args.image_path or config.image_path
if show_in_terminal is None:
    # Defaults to terminal in Windows
    show_in_terminal = platform.system() == "Windows"
ensure_unicode = qr_extra.ensure_unicode or False
logger.setLevel("DEBUG" if args.debug else (config.logLevel or "WARNING"))
proxies = config.proxies or {}
pushplus_token = config.pushplus.enable and config.pushplus.token or ""
bark_token = config.bark.enable and config.bark.token or ""

# captcha（滑块验证码）配置
captcha_conf = config.get("captcha") or {}
captcha_solver = (args.captcha_solver or captcha_conf.get("solver") or "auto").lower()
captcha_headless = args.captcha_headless if args.captcha_headless is not None \
    else bool(captcha_conf.get("headless", False))
captcha_timeout = args.captcha_timeout or int(captcha_conf.get("timeout") or 180)
captcha_max_retries = int(captcha_conf.get("max_retries") or 3)
captcha_channel = args.captcha_channel or captcha_conf.get("browser_channel") or ""
captcha_id = captcha_conf.get("captcha_id") or "4da3050565514a35a50541b0e1f54538"
captcha_debug_dir = args.captcha_debug or captcha_conf.get("debug_dir") or ""

# 点选类验证码（易盾会随机下发滑块/点选）需要能看图的多模态模型
captcha_vision = dict(captcha_conf.get("vision") or {})
if captcha_vision.get("enabled"):
    ai_openai = (config.get("ai") or {}).get("openai") or {}
    for field in ("api_base", "api_key", "model"):
        if not captcha_vision.get(field):
            captcha_vision[field] = ai_openai.get(field) or ""
    if not (captcha_vision.get("api_key") and captcha_vision.get("model")):
        print("*captcha.vision 配置不完整(缺 api_key/model), 点选类验证码将退回人工点击\n")
        captcha_vision["enabled"] = False

if captcha_solver == "auto":
    from captcha import CaptchaSolver
    if not CaptchaSolver.available():
        print("*未安装 Playwright，遇到验证码只能等待重试；"
              "想要自动过滑块请执行: pip install playwright && playwright install chromium\n")

if logger.getLevel() == "DEBUG":
    print("*****************************\n" +
          "DEBUG MODE ENABLED\n" +
          "SENSITIVE DATA WILL BE LOGGED\n" +
          "*****************************\n")

if args.proxy:  # parse proxy
    match args.proxy.lower().split("://"):
        case ["http" | "https", proxy]:
            proxies["http"] = args.proxy
            proxies["https"] = args.proxy
        case ["socks5", proxy]:
            proxies["socks5"] = args.proxy
        case ["all", proxy]:
            proxies["http"] = args.proxy
            proxies["https"] = args.proxy
            proxies["socks5"] = args.proxy
        case [schema]:
            print(f"*Unsupported proxy type: {schema}")
            exit(1)

# check update
with open(getRealPath("meta.json"), "r") as f:
    try:  # some exceptions won't be caught by 'with'
        m = ObjDict(json.load(f))
        url = f"https://raw.githubusercontent.com/{m.author}/LeaderTree/{m.branch}/meta.json"
        r = ObjDict(requests.get(url, proxies=proxies, timeout=5).json())
        current = m.version
        latest = r.version
        if versionCmp(current, latest) < 0:
            print("*********************************\n" +
                  f"New version available: {latest}\n" +
                  f"Current version: {current}\n" +
                  "*********************************\n")
    except Exception:
        print("*Failed to check update\n")

# 创建实例，准备开打
commander = Commander(proxies=proxies, speed=args.speed, end_thre=args.threshold, limit=args.limit,
                pushplus_token=pushplus_token, bark_token=bark_token, tree_view=tree_view, progressbar_view=progressbar_view, image_path=image_path,
                captcha_solver=captcha_solver, captcha_headless=captcha_headless, captcha_timeout=captcha_timeout,
                captcha_browser_channel=captcha_channel, captcha_id=captcha_id,
                captcha_debug_dir=captcha_debug_dir, captcha_max_retries=captcha_max_retries,
                captcha_vision=captcha_vision)

cookies_path = getRealPath("./cookies.json")
cookies_loaded = False
if save_cookies and os.path.exists(cookies_path):
    with open(cookies_path, 'r') as f:
        raw = f.read() or '{}'
        cookies = json.loads(raw)
    with suppress(Exception):
        commander.cookies = cookies
        ls = commander.getZhidaoList()
        if ls:
            commander.getZhidaoContext(ls[-1].secret)
        ls = commander.getHikeList()
        if ls:
            commander.getHikeContext(ls[-1].courseId)

        ls = commander.getZhidaoAiList()
        if ls:
            pass
        print("Successfully recovered from saved cookies\n")
        cookies_loaded = True


# first you need to login to get cookies
if not cookies_loaded:
    try:
        if qrlogin:
            callback = partial(
                showImage, show_in_terminal=show_in_terminal, ensure_unicode=ensure_unicode)
            commander.login(use_qr=True, qr_callback=callback)
        else:
            commander.login(username, password)
        print("Login Successful\n")
        if save_cookies:
            with open(cookies_path, 'w') as f:
                json.dump(cookie_jar_to_list(commander.cookies), f,
                          indent=2, ensure_ascii=False)
    except Exception as e:
        print(e)
        exit(1)

# you can add cookies manually by setting cookies property of a Commander instance
# notice that cookies of zhihuishu.com expires if you login again in somewhere else
# commander.cookies = {}

if args.aicourse:
    course_id, class_id = args.aicourse
    try:
        def validate_config(config):
            ai_config = config.get("ai", {})
            
            if not isinstance(ai_config, dict):
                raise ValueError("AI配置不是字典，请检查配置文件")

            # 用知到自带 AI 时不需要自己的 OpenAI 配置；只有走自己的模型才校验
            if ai_config.get("enabled", False) and not ai_config.get("use_zhidao_ai", False):
                validate_openai_config(ai_config.get("openai", {}))
            
            validate_ppt_config(ai_config.get("ppt_processing", {}))

        def validate_openai_config(openai_config):
            if not isinstance(openai_config, dict):
                raise ValueError(f"OpenAI配置不是字典，而是{type(openai_config)}，请检查配置文件")
            
            required_fields = ["api_key", "api_base", "model_name"]
            missing_fields = [field for field in required_fields if not openai_config.get(field)]
            
            if missing_fields:
                raise ValueError(f"OpenAI配置不完整，缺少以下字段：{', '.join(missing_fields)}。请检查配置文件")

        def validate_ppt_config(ppt_config):
            if not isinstance(ppt_config, dict):
                raise ValueError(f"PPT处理配置不是字典，而是{type(ppt_config)}，请检查配置文件")
            
            if ppt_config.get("provide_to_ai", False):
                moonShot_conf = ppt_config.get("moonShot", {})
                required_fields = ["base_url", "api_key"]
                missing_fields = [field for field in required_fields if not moonShot_conf.get(field)]
                
                if missing_fields:
                    raise ValueError(f"PPT处理配置不完整，缺少以下字段：{', '.join(missing_fields)}。请检查配置文件")

        # 使用示例
        try:
            validate_config(config)
        except ValueError as e:
            print(f"配置错误: {e}")
            exit(1)

        if args.noexam:
            no_exam = True
        else:
            no_exam = False

        commander.commandAiCourse(course_id, class_id, aiConfig=config.ai, no_exam = no_exam)
    except Exception as e:
        logger.exception(e)
        print(f"指挥攻打 AI 课程 {course_id} 出错:\n{e}")
    finally:
        print("AI exam finished")
        exit(0)


exec_list = getRealPath("execution.json")
# fetch course list
if args.fetch:
    with open(exec_list, "w") as f:
        zhidao_ids = [{"name": c.courseName, "id": c.secret}
                      for c in commander.getZhidaoList()]
        hike_ids = [{"name": c.courseName, "id": str(
            c.courseId)} for c in commander.getHikeList()]
        json.dump(zhidao_ids + hike_ids, f, indent=4, ensure_ascii=False)
    exit(0)

# get courses from file if not specified
if not course and os.path.isfile(exec_list):
    with open(exec_list, "r") as f:
        try:
            course = [str(c["id"]) for c in json.load(f)]
        except Exception as e:
            print(f"*Failed to load course list from file: {e}")
            exit(1)

# still not found?
if not course:
    commander.commandAll()
    exit(0)

# auto detect mode
for c in course.copy():
    if args.videos:
        for v in args.videos:
            try:
                commander.commandVideo(course_id=c, video_id=v)
                print(f"已攻下 {v}")
                args.videos.remove(v)
            except Exception:
                pass
    else:
        try:
            commander.commandCourse(course_id=c)
            course.remove(c)
        except Exception as e:
            logger.exception(e)
            print(f"指挥攻打课程 {c} 出错:\n{e}")
if args.videos:
    print(f"*以下视频还没攻下: {args.videos}")

# 用 commandCourse 攻打整门课
# commander.commandCourse(course_id="")

# 或者用 commandVideo 打单个视频
# commander.commandVideo(course_id="", file_id="")

# check the source code or README to find more info
