# -*- coding: utf-8 -*-
"""
智慧树 / 知到 章节作业（半自动）

不用在网页上点来点去，全部走知到的作业接口：

1. CAS SSO 认证 studentexam-api（用你 cookies.json 里的登录态）
2. getStudentHomework 拉该课程的作业列表（未提交 / 已提交）
3. doHomework 取题目（含保存答案要用的 eid）
4. 用 OpenAI 兼容的大模型逐题给答案（单选/多选/判断/填空）
5. saveStudentAnswer 逐题保存（保存后网页上能看到答案）
6. 默认不提交，等你检查完再自己点提交；加 --submit 才会自动交

用法::

    python homework.py --course <recruitAndCourseId> --list      # 只看有哪些作业
    python homework.py --course <recruitAndCourseId> --dry-run   # 只取题 + AI 答案，不保存
    python homework.py --course <recruitAndCourseId>             # 填答案并保存，停下来问你要不要交
    python homework.py --course <recruitAndCourseId> --submit    # 填完直接交

recruitAndCourseId 就是刷课用的那个课程 ID（URL 里带字母的那串）。
"""
import argparse
import json
import os
import random
import re
import sys
import time
from html import unescape

from utils import (getConfigPath, getRealPath, getStatePath, getProfile,
                   showImage, cookie_jar_to_list, setProfile, resolveProfile,
                   describeProfiles)

# 先确定账号 profile（要在 import logger / commander 之前，日志目录才会跟着走）
setProfile(resolveProfile(sys.argv[1:]))

from ObjDict import ObjDict
from zd_utils import Cipher, EXAM_KEY
from logger import logger
from commander import Commander, CaptchaException

HOME_BASE = "https://studentexam-api.zhihuishu.com"
PASSPORT = "https://passport.zhihuishu.com"

P_SCHOOL_INFO = "/studentExam/gateway/t/v1/exam/getLoginSchoolInfo"
P_LIST = "/studentExam/gateway/t/v1/student/getStudentHomework"
P_DO = "/studentExam/gateway/t/v1/student/doHomework"
P_SAVE = "/studentExam/gateway/t/v1/answer/saveStudentAnswer"
P_SUBMIT = "/studentExam/gateway/t/v1/answer/submit"
P_VALIDATE = "/studentExam/gateway/t/v1/answer/validateSlideToken"
P_ANSWERS = "/studentExam/gateway/t/v1/answer/getStuAnswerInfoNew"

TYPE_NAMES = {1: "单选题", 2: "多选题", 3: "填空题", 5: "简答题", 14: "判断题"}
SUPPORTED_TYPES = (1, 2, 3, 14)   # 简答/论述等暂时不支持，留给人工
LABELS = "ABCDEFGH"


class HomeworkError(Exception):
    def __init__(self, message="", code=None):
        super().__init__(message)
        self.message = message
        self.code = code

    @property
    def need_captcha(self):
        """这个错误是不是"要先过滑块验证"引起的"""
        text = str(self)
        return self.code == -12 or ("滑块" in text) or ("验证码" in text)


def strip_html(text):
    """把题目/选项里的 HTML 变成纯文本"""
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def question_type_id(raw):
    if isinstance(raw, dict):
        raw = raw.get("id")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def normalize_question(raw):
    """把 doHomework 返回的题目整理成统一的 dict"""
    return {
        "eid": raw.get("eid"),
        "id": raw.get("id"),
        "name": strip_html(raw.get("name")),
        "type": question_type_id(raw.get("questionType")),
        "options": [
            {"id": int(opt.get("id")), "content": strip_html(opt.get("content"))}
            for opt in (raw.get("questionOptions") or [])
            if opt.get("id") is not None
        ],
        "score": raw.get("questionScore"),
    }

# ---------------------------------------------------------------------------
# 大题作答
# ---------------------------------------------------------------------------
def thinking_extra(api_base, thinking="auto"):
    """DeepSeek 默认开思考模式，会把 token 花在思维链上，这里默认关掉"""
    thinking = str(thinking or "auto").lower()
    if thinking in ("0", "false", "off", "disabled", "none"):
        return {"thinking": {"type": "disabled"}}
    if thinking in ("1", "true", "on", "enabled"):
        return {"thinking": {"type": "enabled"}}
    return {"thinking": {"type": "disabled"}} if "deepseek" in (api_base or "").lower() else None


class HomeworkAI:
    """用 OpenAI 兼容接口给作业题答案"""

    def __init__(self, api_base="", api_key="", model="", thinking="auto", timeout=90):
        self.api_base = api_base or ""
        self.api_key = api_key or ""
        self.model = model or ""
        self.thinking = thinking
        self.timeout = timeout

    @property
    def available(self):
        return bool(self.api_key and self.model)

    def build_prompt(self, q, course_name=""):
        lines = ["你在帮学生完成智慧树（知到）的章节作业。"]
        if course_name:
            lines.append("课程：" + course_name)
        lines.append("题型：" + TYPE_NAMES.get(q["type"], "未知题型"))
        lines.append("题目：" + (q["name"] or ""))
        if q["options"]:
            lines.append("选项：")
            for label, opt in zip(LABELS, q["options"]):
                lines.append("%s. %s" % (label, opt["content"]))
        lines.append("")
        if q["type"] == 3:
            lines.append("请直接输出填空答案；如果有多个空，用 | 分隔。不要解释。")
        elif q["type"] == 2:
            lines.append("请只输出正确选项的字母，多个选项用英文逗号分隔（例如 A,C）。不要解释。")
        else:
            lines.append("请只输出正确选项的字母（例如 B）。不要解释。")
        return "\n".join(lines)

    def chat(self, prompt):
        from openai import OpenAI

        client = OpenAI(base_url=self.api_base or None,
                        api_key=self.api_key,
                        timeout=self.timeout)
        kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 800,
        }
        extra = thinking_extra(self.api_base, self.thinking)
        if extra:
            kwargs["extra_body"] = extra
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as exc:
            if "extra_body" not in kwargs:
                raise
            logger.warning("带 thinking 参数调用失败(%s)，去掉重试" % exc)
            kwargs.pop("extra_body", None)
            resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        text = choice.message.content or ""
        if not text:
            reasoning = getattr(choice.message, "reasoning_content", None) or ""
            raise HomeworkError("模型返回空内容(finish_reason=%s, 思维链%d字)"
                                % (getattr(choice, "finish_reason", "?"), len(reasoning)))
        return text

    def answer(self, q, course_name=""):
        """返回答案：单选/判断 -> int 选项 id；多选 -> 'id,id'；填空 -> 文本"""
        if not self.available:
            return None
        text = self.chat(self.build_prompt(q, course_name))
        return parse_answer(text, q)


def parse_answer(text, q):
    text = (text or "").strip()
    if not text:
        return None
    text = re.sub(r"^[\x60\"'\s]+|[\x60\"'\s]+$", "", text)
    if q["type"] == 3:
        text = re.sub(r"\s*\n\s*", " ", text)
        return text.strip() or None

    id_by_label = {label: opt["id"] for label, opt in zip(LABELS, q["options"])}
    # 判断题模型可能直接回"对/错"
    if q["type"] == 14 and len(q["options"]) >= 2 and not re.search(r"[A-H]", text.upper()):
        if re.search(r"对|正确|是|true|√", text, re.I):
            return int(q["options"][0]["id"])
        if re.search(r"错|错误|否|false|×", text, re.I):
            return int(q["options"][1]["id"])
    letters = re.findall(r"[A-H]", text.upper())
    if not letters:
        # 有些模型会直接重复选项内容
        for label, opt in zip(LABELS, q["options"]):
            snippet = (opt["content"] or "").strip()[:10]
            if snippet and snippet in text:
                letters = [label]
                break
    picked = [l for l in dict.fromkeys(letters) if l in id_by_label]
    if not picked:
        return None
    if q["type"] == 2:
        return ",".join(str(id_by_label[l]) for l in picked)
    return int(id_by_label[picked[0]])

# ---------------------------------------------------------------------------
# 作业接口
# ---------------------------------------------------------------------------
class HomeworkClient:
    def __init__(self, commander):
        self.commander = commander
        self.cipher = Cipher(EXAM_KEY)

    def query(self, path, data):
        url = HOME_BASE + path
        payload = {"secretStr": self.cipher.encrypt(json.dumps(data, ensure_ascii=False))}
        try:
            ret = self.commander._apiQuery(url, data=payload, method="POST")
        except Exception as exc:
            raise HomeworkError(
                "请求 %s 失败（登录态可能失效，先跑一次 main.py 重新扫码）: %s" % (path, exc))
        status = str(ret.get("status"))
        if status != "200":
            msg = ret.get("msg") or ret.get("message") or ret.get("errorMsg") or ""
            raise HomeworkError("%s 返回 status=%s %s" % (path, status, msg),
                                code=ret.get("code"))
        return ret

    def sso_login(self):
        """CAS SSO：studentexam-api 和 studyservice-api 不是同一套登录态"""
        service = HOME_BASE + P_LIST
        url = "%s/cas/login?service=%s" % (PASSPORT, service)
        session = self.commander.session
        resp = session.get(url, allow_redirects=False, timeout=20, proxies=self.commander.proxies)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if "ticket=" in location:
                session.get(location, allow_redirects=True, timeout=20, proxies=self.commander.proxies)
                return True
            raise HomeworkError("CAS 没有下发 ticket，可能需要重新登录")
        raise HomeworkError("CAS 返回 %s，登录态可能已过期，请重新扫码登录" % resp.status_code)

    def school_id(self):
        rt = self.query(P_SCHOOL_INFO, {}).get("rt") or {}
        return str(rt.get("schoolId") or "")

    def list_homework(self, recruit_id, course_id, flag):
        rt = self.query(P_LIST, {
            "recruitId": recruit_id,
            "courseId": course_id,
            "flag": flag,
            "pageSize": 100,
            "pageNum": 0,
        }).get("rt") or {}
        return rt.get("studentHomeworkList") or []

    def do_homework(self, recruit_id, course_id, exam_id, stu_exam_id, school_id):
        return self.query(P_DO, {
            "recruitId": recruit_id,
            "examId": exam_id,
            "studentExamId": stu_exam_id,
            "schoolId": school_id,
            "courseId": course_id,
        }).get("rt") or {}

    def save_answer(self, recruit_id, question, item, school_id, answer):
        if not question.get("eid"):
            raise HomeworkError("题目缺少 eid，无法保存答案")
        answer_item = {
            "examId": item.get("examId"),
            "recruitId": recruit_id,
            "stuExamId": item.get("id"),
            "eid": question["eid"],
            "schoolId": school_id,
            "deviceId": "",
            "examType": "",
            "fromType": 3,
            "answer": answer,
            "dataIds": "",
            "questionType": question["type"],
        }
        self.query(P_SAVE, {
            "stuExamAnswer": json.dumps([answer_item], ensure_ascii=False),
            "recruitId": recruit_id,
        })

    def get_saved_answers(self, recruit_id, exam_id, stu_exam_id, school_id, course_id, eids):
        """查这门作业里已经保存过答案的题（返回 {eid: answer}）

        对应网页版的 getStuAnswerInfoNew：打开作业时页面就是靠它回填选择题的。
        """
        if not eids:
            return {}
        try:
            ret = self.query(P_ANSWERS, {
                "recruitId": recruit_id,
                "examId": exam_id,
                "stuExamId": stu_exam_id,
                "schoolId": school_id,
                "courseId": course_id,
                "questionIds": ",".join(str(e) for e in eids),
            })
        except HomeworkError as exc:
            logger.warning("查询已答题目失败(忽略): %s" % exc)
            return {}
        rt = ret.get("rt") or []
        saved = {}
        if isinstance(rt, list):
            for item in rt:
                if not isinstance(item, dict):
                    continue
                qid = item.get("eid") or item.get("questionId")
                ans = item.get("answer")
                if qid and ans not in (None, ""):
                    saved[str(qid)] = ans
        elif isinstance(rt, dict):
            for key, value in rt.items():
                if isinstance(value, dict) and value.get("answer") not in (None, ""):
                    saved[str(key)] = value.get("answer")
        return saved

    def validate_slide_token(self, recruit_id, exam_id, token, check_type=1):
        """把易盾的 validate 上报给作业站，解除"不能答题"的限制

        对应网页版 POST /studentExam/gateway/t/v1/answer/validateSlideToken
        参数：recruitId / token / checkType / chapterId(=examId)
        """
        ret = self.query(P_VALIDATE, {
            "recruitId": recruit_id,
            "token": token,
            "checkType": check_type,
            "chapterId": exam_id,
        })
        return bool(ret.get("pass"))

    def submit(self, recruit_id, exam_id, stu_exam_id, answer_count):
        return self.query(P_SUBMIT, {
            "recruitId": recruit_id,
            "examId": exam_id,
            "stuExamId": stu_exam_id,
            "achieveCount": str(answer_count),
        }).get("rt") or {}


# ---------------------------------------------------------------------------
# 参数 / 主流程
# ---------------------------------------------------------------------------
def extract_questions(detail):
    exam_base = detail.get("examBase") or {}
    questions = []
    for part in exam_base.get("workExamParts") or []:
        for raw in part.get("questionDtos") or []:
            questions.append(normalize_question(raw))
    return exam_base, questions


def load_config():
    path = getConfigPath()
    if not os.path.isfile(path):
        root = getRealPath("config.json")
        if getProfile() and os.path.isfile(root):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            import shutil
            shutil.copyfile(root, path)
            print("已从根目录 config.json 复制配置到 profiles/%s/" % getProfile())
        else:
            raise SystemExit(
                "找不到 config.json，请先跑一次 python main.py 生成配置文件%s"
                % ("（--profile %s）" % getProfile() if getProfile() else ""))
    with open(path, "r", encoding="utf-8") as f:
        return ObjDict(json.load(f), default=None)


def load_cookies():
    path = getStatePath("cookies.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def do_qr_login(commander, config):
    """重新扫码登录，并刷新 cookies.json（作业站的 CAS 登录态要它）"""
    from functools import partial

    qr_extra = config.get("qr_extra") or {}
    show_in_terminal = qr_extra.get("show_in_terminal")
    if show_in_terminal is None:
        show_in_terminal = sys.platform.startswith("win")
    callback = partial(showImage,
                       show_in_terminal=bool(show_in_terminal),
                       ensure_unicode=bool(qr_extra.get("ensure_unicode") or False))
    commander.login(use_qr=True, qr_callback=callback)
    try:
        with open(getStatePath("cookies.json"), "w", encoding="utf-8") as f:
            json.dump(cookie_jar_to_list(commander.cookies), f, indent=2, ensure_ascii=False)
        print("已刷新 cookies.json")
    except Exception as exc:
        logger.warning("保存 cookies 失败: %s" % exc)


def resolve_ai(config, overrides=None):
    hw = ((config.get("homework") or {}).get("answer") or {})
    ai = ((config.get("ai") or {}).get("openai") or {})
    vis = ((config.get("captcha") or {}).get("vision") or {})

    def first(*values):
        for value in values:
            if value and str(value).strip() and str(value).strip() != "sk-":
                return str(value).strip()
        return ""

    if overrides is not None:
        # 命令行参数优先级最高
        api_base = getattr(overrides, "ai_base", None) or ""
        api_key = getattr(overrides, "ai_key", None) or ""
        model = getattr(overrides, "ai_model", None) or ""
        thinking = getattr(overrides, "ai_thinking", None) or ""
    else:
        api_base = api_key = model = thinking = ""

    return HomeworkAI(
        api_base=api_base or first(hw.get("api_base"), vis.get("api_base"), ai.get("api_base")),
        api_key=api_key or first(hw.get("api_key"), vis.get("api_key"), ai.get("api_key")),
        model=model or first(hw.get("model"), vis.get("model"), ai.get("model_name")),
        thinking=thinking or hw.get("thinking") or "auto",
    )


def format_answer(answer, question):
    if answer is None:
        return "（未作答）"
    if question["type"] == 3:
        return str(answer)
    ids = [int(x) for x in str(answer).split(",")]
    labels = []
    for opt, label in zip(question["options"], LABELS):
        if opt["id"] in ids:
            labels.append(label)
    return "%s（选项 %s）" % (",".join(labels) or answer, answer)


def print_question(index, question):
    name = question["name"].replace("\n", " ")
    print("  %2d. [%s] %s" % (index, TYPE_NAMES.get(question["type"], "题型%s" % question["type"]), name))
    for label, opt in zip(LABELS, question["options"]):
        content = opt["content"].replace("\n", " ")
        print("      %s. %s" % (label, content))


def with_captcha(client, commander, recruit_id, exam_id, action, desc="操作"):
    """
    执行 action，遇到"要先过滑块验证"就自动过验证码、上报、再重试。

    作业站返回形如 {"status": -1, "msg": "滑块验证未通过，不能答题"}，
    网页版的处理是：弹易盾 -> onVerify 拿到 validate ->
    POST /answer/validateSlideToken {recruitId, token, checkType, chapterId} -> 重试。
    """
    last = None
    for attempt in range(1, 4):
        try:
            return action()
        except HomeworkError as exc:
            if not exc.need_captcha:
                raise
            last = exc
            print("  !! %s需要滑块验证（第 %d 次）：%s" % (desc, attempt, exc))
            print("     正在自动过验证码（会弹浏览器窗口；若十几秒没动静，请在窗口里手动点/拖一下）...")
            validate = commander.solveCaptchaToken()
            if not validate:
                raise HomeworkError("验证码没通过，请重跑，或在浏览器里手动做一次")
            if not client.validate_slide_token(recruit_id, exam_id, validate):
                raise HomeworkError("验证码上报没通过（validateSlideToken 返回 pass=false）")
            print("     -> 验证码通过，重试 %s" % desc)
    raise HomeworkError("多次过验证码后仍然失败：%s" % last)


def process_one(client, ai, item, recruit_id, course_id, school_id, args, course_name, commander=None):
    exam_name = item.get("examName") or "未命名作业"
    print("\n== %s (%s 题, %s 分, 截止 %s)" % (
        exam_name, item.get("problemNum"), item.get("totalScore"), item.get("endDate") or "-"))

    exam_id = item.get("examId")

    def _do():
        return client.do_homework(recruit_id, course_id, exam_id, item.get("id"), school_id)

    detail = with_captcha(client, commander, recruit_id, exam_id, _do, "取题") if commander else _do()
    exam_base, questions = extract_questions(detail)
    if not questions:
        print("  !! 没有取到题目（可能已提交或需要验证码）")
        return

    # 先看服务器上已经保存过答案的题，避免重复作答/覆盖
    eids = [q["eid"] for q in questions if q.get("eid")]
    saved_answers = {}
    if eids and not getattr(args, "force", False):
        saved_answers = client.get_saved_answers(
            recruit_id, exam_id, item.get("id"), school_id, course_id, eids)
        if saved_answers:
            print("  服务器上已有 %d 题答案，这些题会跳过" % len(saved_answers))

    planned = []
    for index, question in enumerate(questions, 1):
        print_question(index, question)
        if str(question.get("eid")) in saved_answers:
            print("      -> 已经答过（服务器已有答案），跳过")
            continue
        if question["type"] not in SUPPORTED_TYPES:
            print("      -> 暂不支持的题型，跳过（请手动作答）")
            continue
        try:
            answer = ai.answer(question, course_name)
        except Exception as exc:
            logger.error("第 %d 题作答失败: %s" % (index, exc))
            answer = None
        print("      -> 答案: %s" % format_answer(answer, question))
        planned.append((question, answer))

    if args.dry_run:
        print("  (--dry-run，不保存)")
        return

    saved = 0
    for index, (question, answer) in enumerate(planned, 1):
        if answer is None:
            continue

        def _save(q=question, a=answer):
            return client.save_answer(recruit_id, q, item, school_id, a)

        if commander:
            with_captcha(client, commander, recruit_id, exam_id, _save, "保存第%d题" % index)
        else:
            _save()
        saved += 1
        time.sleep(random.uniform(args.delay_min, args.delay_max))
    print("  已保存 %d/%d 题答案（服务端已保存，网页上打开就能看到）" % (saved, len(questions)))

    if args.submit and saved:
        def _submit():
            return client.submit(recruit_id, exam_id, item.get("id"), saved)

        result = with_captcha(client, commander, recruit_id, exam_id, _submit, "提交") if commander else _submit()
        print("  已提交：%s" % (result or ""))
    elif saved:
        print("  未提交 —— 去网页里检查一遍再点提交，或下次加 --submit")


def save_cookies(commander):
    """把当前会话 cookies 写回 cookies.json（视频站 + 作业站的都存）"""
    try:
        with open(getStatePath("cookies.json"), "w", encoding="utf-8") as f:
            json.dump(cookie_jar_to_list(commander.session.cookies), f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("保存 cookies 失败: %s" % exc)


def course_course_id(course):
    """课程列表项里的数字 courseId（顶层为 0 时回退 courseInfo.courseId）"""
    try:
        cid = int(course.get("courseId") or 0)
    except Exception:
        cid = 0
    if cid <= 0:
        info = course.get("courseInfo") or {}
        try:
            cid = int(info.get("courseId") or 0)
        except Exception:
            cid = 0
    return cid


def find_course(commander, course_id=None, rac=None):
    """在“我的课程”列表里找课程，拿到 recruitId / recruitAndCourseId / courseId"""
    for course in commander.getZhidaoList():
        if rac and course.get("recruitAndCourseId") == rac:
            return course
        if course_id and course_course_id(course) == int(course_id):
            return course
    return None


def print_courses(commander):
    courses = commander.getZhidaoList()
    if not courses:
        print("没有查到课程（cookies 可能过期了）")
        return
    print("（只列\"共享课\"——作业走的就是这套接口；翻转课/AI智课/职教云课不在里面）")
    print("%-32s %-13s %-9s %s" % ("课程名", "courseId", "recruitId", "recruitAndCourseId"))
    print("-" * 100)
    for course in courses:
        name = str(course.get("courseName") or "")[:30]
        print("%-32s %-13s %-9s %s" % (
            name, course_course_id(course) or "-",
            course.get("recruitId") or "-",
            course.get("recruitAndCourseId") or "-"))


def build_commander(config):
    """按 config.json 里的 captcha 配置构造 Commander（作业站也要能过验证码）"""
    cap = config.get("captcha") or {}
    vision = dict(cap.get("vision") or {})
    return Commander(
        proxies=config.proxies or {},
        tree_view=False,
        progressbar_view=False,
        captcha_solver=cap.get("solver") or "auto",
        captcha_headless=bool(cap.get("headless")),
        captcha_timeout=int(cap.get("timeout") or 180),
        captcha_browser_channel=cap.get("browser_channel") or "",
        captcha_id=cap.get("captcha_id") or "4da3050565514a35a50541b0e1f54538",
        captcha_debug_dir=cap.get("debug_dir") or "",
        captcha_max_retries=int(cap.get("max_retries") or 3),
        captcha_vision=vision,
    )


def ensure_session(client, commander, config, args):
    """保证作业站可用：先试旧会话 -> CAS SSO -> 必要时重新扫码"""
    try:
        client.school_id()
        print("作业站会话仍然有效")
        return True
    except Exception:
        pass

    try:
        client.sso_login()
        client.school_id()
        print("CAS SSO 成功")
        return True
    except Exception as exc:
        print("SSO 失败：%s" % exc)
        print("作业站（studentexam-api）用的是 passport 的 CAS 登录态，")
        print("视频站 cookies 还能用不代表它没过期——它的有效期比视频站短得多。")

    if args.login:
        need_login = True
    elif sys.stdin.isatty():
        need_login = input("现在扫码重新登录一次？[Y/n] ").strip().lower() in ("", "y", "yes")
    else:
        need_login = False
    if not need_login:
        print("没登录就没法做作业。加 --login 可以在本脚本里直接扫码。")
        return False

    try:
        do_qr_login(commander, config)
    except Exception as exc:
        print("扫码登录失败：%s" % exc)
        return False

    try:
        client.sso_login()
        client.school_id()
        print("重新登录后 SSO 成功")
        return True
    except Exception as exc:
        print("重新登录后 SSO 还是失败：%s" % exc)
        return False


def main():
    parser = argparse.ArgumentParser(description="智慧树/知到 章节作业半自动助手")
    parser.add_argument("--course", help="recruitAndCourseId（刷课用的那个课程ID，带字母）")
    parser.add_argument("--recruit-id", help="直接指定 recruitId（不想解析课程时用）")
    parser.add_argument("--course-id", help="数字 courseId；脚本会自动从课程列表里找 recruitId")
    parser.add_argument("--list-courses", action="store_true",
                        help="列出你所有知到课程及其 courseId / recruitId / recruitAndCourseId")
    parser.add_argument("--list", action="store_true", help="只列出作业，不做题")
    parser.add_argument("--dry-run", action="store_true", help="只取题 + 给答案，不保存不提交")
    parser.add_argument("--submit", action="store_true", help="填完直接提交（默认停下来问你）")
    parser.add_argument("--only", help="只处理名称包含该关键字的作业")
    parser.add_argument("--profile", type=str, default=None,
                        help="账号 profile（多账号用）：cookies/config/日志放到 profiles/<名字>/")
    parser.add_argument("--profiles", action="store_true", help="列出所有账号 profile")
    parser.add_argument("--login", action="store_true", help="SSO 失败时直接扫码重新登录")
    parser.add_argument("--force", action="store_true", help="忽略已答题目，全部重做")
    parser.add_argument("--limit", type=int, default=0, help="最多处理几个作业")
    parser.add_argument("--delay-min", type=float, default=1.0)
    parser.add_argument("--delay-max", type=float, default=2.5)
    parser.add_argument("--ai-base", help="覆盖模型的 api_base（不写配置文件）")
    parser.add_argument("--ai-key", help="覆盖模型的 api_key")
    parser.add_argument("--ai-model", help="覆盖模型名，如 deepseek-flash")
    parser.add_argument("--ai-thinking", choices=["auto", "true", "false"],
                        help="思考模式开关（DeepSeek 默认开，做题建议关）")
    parser.add_argument("--test-ai", action="store_true", help="只测一下模型能不能用，然后退出")
    args = parser.parse_args()

    if args.profiles:
        rows = describeProfiles()
        if not rows:
            print("还没有任何账号。跑 python main.py --profile <名字> 新建一个")
            return 0
        print("%-18s %-8s %-20s %s" % ("名字", "登录态", "最后使用", "配置"))
        print("-" * 66)
        for row in rows:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["mtime"])) if row["mtime"] else "-"
            print("%-18s %-8s %-20s %s" % (
                row["name"],
                "已登录" if row["logged"] else "未登录",
                when,
                "有" if row["config"] else "-"))
        return 0

    config = load_config()

    if args.test_ai:
        ai = resolve_ai(config, args)
        print("模型：%s" % (ai.model or "(未配置)"))
        print("接口：%s" % (ai.api_base or "(默认)"))
        print("Key ：%s" % ("已配置" if ai.api_key else "(未配置)"))
        if not ai.available:
            print("")
            print("没配全（缺 api_key 或 model），用 --ai-key/--ai-model 传一个，")
            print("或者写进 config.json 的 homework.answer 里")
            return 1
        try:
            print("")
            print("测试调用中...")
            reply = ai.chat("请只回四个字：模型可用")
            print("模型回复：%s" % reply.strip()[:200])
            print("")
            print("OK，模型可用")
            return 0
        except Exception as exc:
            print("")
            print("调用失败：%s" % exc)
            return 1

    if not args.course and not args.course_id and not args.list_courses:
        parser.error("请用 --course <recruitAndCourseId> 或 --course-id <数字ID>，先 --list-courses 看看有哪些课")

    commander = build_commander(config)
    cookies = load_cookies()
    if not cookies:
        cmd = "python main.py" + (" --profile %s" % getProfile() if getProfile() else "")
        print("没找到 cookies.json，请先跑一次 %s 完成扫码登录（会自动保存）" % cmd)
        return 1
    commander.cookies = cookies
    commander._sessionReady()   # 把 cookies 同步到 requests.Session，SSO 才有登录态

    if args.list_courses:
        print_courses(commander)
        return 0

    if args.recruit_id and args.course_id:
        recruit_id = str(args.recruit_id)
        course_id = int(args.course_id)
        course_name = ""
    elif args.course_id and not args.course:
        # 只给了数字 courseId：从课程列表反查 recruitId / RAC
        course = find_course(commander, course_id=args.course_id)
        if not course:
            print("共享课列表里没有 courseId=%s 这门课。" % args.course_id)
            print("如果你是从 wenda.zhihuishu.com（翻转课）复制的 courseId，那门课不属于共享课体系，")
            print("它的 recruitId 是 null、作业也走另一套接口，这个工具做不了。")
            print("先跑 --list-courses 看看你有哪些共享课。")
            return 1
        rac = course.get("recruitAndCourseId")
        recruit_id = str(course.get("recruitId") or "")
        course_id = course_course_id(course)
        course_name = str(course.get("courseName") or "")
        print("课程：%s (recruitId=%s, courseId=%s)" % (course_name, recruit_id or "-", course_id))
        if not recruit_id and not rac:
            print("这门课没有 recruitId（可能是共享课/职教云课），做不了作业")
            return 1
    else:
        try:
            ctx = commander.getZhidaoContext(args.course)
        except CaptchaException as exc:
            print("拉取课程信息时被风控拦了，正在尝试自动过验证码...")
            if not commander.solveCaptcha(exc):
                print("验证码没通过，重跑一次再试")
                return 1
            ctx = commander.getZhidaoContext(args.course)
        recruit_id = str(ctx.course.recruitId)
        course_id = int(ctx.chapters.courseId)
        course_name = str(ctx.course.courseInfo.name or "")
        print("课程：%s (recruitId=%s, courseId=%s)" % (course_name, recruit_id, course_id))

    client = HomeworkClient(commander)
    if not ensure_session(client, commander, config, args):
        return 1
    save_cookies(commander)
    school_id = client.school_id()
    logger.info("schoolId=%s" % school_id)

    pending = client.list_homework(recruit_id, course_id, 1)
    submitted = client.list_homework(recruit_id, course_id, 2)

    print("\n未提交作业 %d 个，已提交 %d 个" % (len(pending), len(submitted)))
    for item in pending + submitted:
        state = item.get("state")
        print("  [%s] %s  分数=%s/%s  截止=%s" % (
            "已提交" if state == 4 else "未提交",
            item.get("examName"), item.get("score") or "-",
            item.get("totalScore") or "-", item.get("endDate") or "-"))
    if args.list:
        return 0

    todo = [item for item in pending if item.get("state") in (1, 5)]
    if args.only:
        todo = [item for item in todo if args.only in (item.get("examName") or "")]
    if args.limit:
        todo = todo[:args.limit]
    if not todo:
        print("\n没有需要做的作业")
        return 0

    ai = resolve_ai(config, args)
    if not ai.available:
        print("\n没配置可用的模型，只能列题不能给答案。")
        print("三种办法选一个：")
        print("  1) 命令行：--ai-base https://api.deepseek.com/v1 --ai-key sk-xxx --ai-model deepseek-flash")
        print("  2) config.json 里配 homework.answer（api_base/api_key/model）")
        print("  3) config.json 里配 captcha.vision（验证码用的那个，也复用它）")
        print("先用 --test-ai 验证配置是否可用。")
        return 1

    print("\n使用模型：%s (%s)" % (ai.model, ai.api_base or "default"))
    for item in todo:
        try:
            process_one(client, ai, item, recruit_id, course_id, school_id, args, course_name,
                        commander=commander)
        except HomeworkError as exc:
            print("  !! %s" % exc)
            if "滑块" in str(exc) or "验证码" in str(exc):
                print("  !! 自动过验证码没成功，重跑一次；或者在浏览器里手动做一次验证再重跑")
                break
        except Exception as exc:
            logger.exception(exc)
            print("  !! 处理失败: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
