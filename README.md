# LeaderTree 指挥树 · 使用指南

> 我没有智慧，我只是个指挥工具刷课的程序员 —— **指挥树**，谐音“智慧树”，小幽默。

## 这是什么

一个 _Python3_ 的自动化脚本，用来把智慧树 / 知到上的课程学习“指挥”掉：

- 支持校内学分课（hike）与知到共享学分课
- 自动回答视频弹题（接口里自带答案，不需要模型）
- 自动通过风控验证码：滑块自动拖、点选自动点（可接多模态模型）
- 章节作业半自动：SSO → 取题 → AI 作答 → 逐题保存，默认停下来让你确认后再提交
- 支持 AI 智慧课程（`-ai`，可用知到自带 AI，也可接自己的模型）
- 设定时限、无人值守

## 它是从哪来的

本项目 fork 自 [VermiIIi0n/fuckZHS](https://github.com/VermiIIi0n/fuckZHS)（MIT 协议），
原项目的后端逆向（视频 / 弹题 / 考试）是这一切的基石。

在此基础上做了这些改造：

- 新增 `captcha.py`：易盾滑块 + 点选的浏览器求解器（含作业站验证码上报）
- 新增 `homework.py`：章节作业半自动（CAS SSO / 取题 / AI 答案 / 保存 / 可选提交）
- 新增「已答题目跳过」、`--list-courses`、`--test-ai`、作业站 SSO 等易用性功能
- 重构命名与文案：`Fucker` → `Commander`，输出改成“指挥 / 攻打”风格

## 鸣谢 / 灵感来源

- [VermiIIi0n/fuckZHS](https://github.com/VermiIIi0n/fuckZHS) —— 本项目的起点（MIT）
- [pjm314159/zhs](https://github.com/pjm314159/zhs) —— 章节作业接口的参考实现
- 原项目的 [常见问题](https://github.com/VermiIIi0n/fuckZHS/discussions/25) 与 [讨论区](https://github.com/VermiIIi0n/fuckZHS/discussions) 依然适用

---

## 准备工作

您还需要做以下准备：

- _Python3.10_ 及以上版本（或自行改写旧版不兼容的语法）
- 执行 `pip install -r requirements.txt` 安装依赖

---

## 如何使用

因登陆验证改变，为保证指挥官们都能安全落地，**目前本项目与原项目保持一直，仅有二维码登陆可用**。

本块分为

0. Ultra Quick Start：执行 `python main.py`

   - 仅以交互输入信息，除非开 DEBUG 模式否则不留任何敏感记录

1. `Login`：输入账号与密码

   - 使用配置文件
   - 使用命令行参数

2. `Leading`：行动吧，指挥官！

   - 使用命令行参数
   - 拉清单
   - 参数列表

3. `API` 简易文档：用于单独使用模块

### Login

_\*如果非常用地登入（可能？）会需要短信验证，您应该先用浏览器登入一次，以让您的所在地列入白名单。_  
 _\*\*信息优先级：命令行 > 配置文件 > 交互输入_

### 使用配置文件

配置文件 _config.json_ 中有以下字段：

```JSON
{
  "username": "",
  "password": "",
  "qrlogin": true,
  "save_cookies": true,
  "proxies": {},
  "logLevel": "INFO",
  "tree_view": true,
  "progressbar_view": false,
  "qr_extra": {
      "show_in_terminal": null,
      "ensure_unicode": false
  },
  "image_path": "",
  "pushplus": {
      "enable": false,
      "token": ""
  },
  "bark": {
      "enable": false,
      "token": "https://example.com/xxxxxxxxx"
  },
  "config_version": "1.3.0"
}
```

- `username`：账号
- `password`：密码
- `qrlogin`：**目前强制启用**二维码登陆，方便在服务器上部署，优先级高于账号密码
- `proxies`：代理，可留空，在 _Windows_ 上还可解决 _Clash_ 等代理造成的证书错误，详见 [_常见问题_](https://github.com/VermiIIi0n/fuckZHS/discussions/25)
- `logLevel`：日志等级，可选 `NOTSET` `DEBUG` `INFO` `WARNING` `ERROR` `CRITICAL`
- `save_cookies`：保存cookies，*短时间*内可以自动登录。
- `tree_view`：课程目录结构，关闭后不显示所有课程目录。
- `progressbar_view`：进度条控制，关闭后不显示当前视频进度。
- `image_path`：登录二维码保存路径，留空则不保存。
- `qr_extra`：QR 相关配置
  - `show_in_terminal`：将二维码打印至终端
  - `ensure_unicode`：仅使用 Unicode 字符打印二维码
- `pushplus`：基于 [pushplus](https://www.pushplus.plus) 的推送服务
  - `enable`：启用推送
  - `token`：推送 token
- `bark`：基于 [bark](https://github.com/Finb/Bark) 的推送服务
  - `enable`：启用推送
  - `token`：推送 token，例如：`https://api.day.app/xxxxxxxxxxxxx`

~~填入账号密码即可无干预自动登入~~ **当前失效**  
 _\*配置文件如果没有的话会在 main.py 执行时自动创建。_

### 使用命令行参数登入

```bash
python main.py -u <username> -p <password>
python main.py -q
```

- `-u` `--username`：账号
- `-p` `--password`：密码，要注意密码将会明文留在记录中，故不推荐使用 `-p` _\*虽然说这破站密码泄漏就泄露吧，写配置文件里多方便，俗话说晚泄不如早泄（¿）_
- `-q` `--qrlogin` ：启用二维码登陆

---

### Leading

### 命令行指北

**以下假设您已经在配置文件中输入必要信息**  
 _\*信息优先级：命令行 > 配置文件 > 交互输入_

```bash
cd LeaderTree
python main.py # 如果 execution.json 不存在的话, 刷所有课
# 只刷课程 ID 为 114514 和 1919180 的课
python main.py -c 114514 1919180
# 想秒过可以设个很高的 SPEEEED
python main.py -s 444 # 我就感觉到快, 有种催人ban的感觉
# 又或者可以限制每节课学习25分钟
python main.py -c 114514 -l 25
# 遇到问题想开 debug 模式, 顺带加个代理?
python main.py -c 114514 -d --proxy http://127.0.0.1:2333
# 又比如您想只干某几个视频, 那您可以使用 -v 传入视频 ID
python main.py -c 114514 -v 1989 604
# 刷ai课程，ai课程号为 114514，classId为 4444
python main.py -ai 114514 4444
```

什么？不知道课程 ID 或视频 ID？进入课程界面就可以在网址里看到了。  
 _\*课程 ID 为网址中的 `courseId`（校内学分课）或 `recruitAndCourseId`（共享学分课）参数_  
 _\*\*更多选项请使用 `-h` 查看。_

### 拉清单

使用 `--fetch` 参数可从服务器获得所有课程清单，存储到 _execution.json_ 这个小本本里，您可以删去不想干的课程  
当该文件存在且没有指定课程 ID 时，会先看看这个小本本上有没有写着课程 ID  
_\*清单中 `id` 参数是必须的，想额外拉清单时请注意_  
_\*\*修改时请注意 JSON 语法，不然 Exceptions 会一下突开到脸上_

```bash
python main.py --fetch
```

清单示例：

```JSON
[
    {
        "name": "中国近现代史",
        "id": "42"
    },
    {
        "name": "思想道德与法治",
        "id": "1919"
    }
]
```

### 命令行参数列表

- `-c`，`--course`：课程 ID，`courseId` 或 `recruitAndCourseId`，可输入多个
- `-v`，`--videos`：视频 ID，`fileId` 或 `videoId`，可输入多个
- `-u`，`--username`：账号
- `-p`，`--password`：密码
- `-q`，`--qrlogin`：二维码登录，目前**强制开启**
- `-s`，`--speed`：~~**POWERR AND SPEEEEED！**~~ 指定播放速度，想要秒过可以设个很高的值（e.g. 644），但不推荐。默认为浏览器观看能到的最大值
- `-t`，`--threshold`：完成时播放百分比，高于该值视作完成，想要重复刷课可以使用大于 `1.0` 的值，例如 `2.0` 则会再刷一遍
- `-l`，`--limit`：单节课的时限，如果您看得上内点习惯分就用吧
- `-d`，`--debug`：调试级日志记录，会记录请求到日志 **_（可能包含账号密码，别乱分享，当心被盒武_**
- `-f`，`--fetch`：获取课程清单并存入 _execution.json_ 文件
- `--show_in_terminal`：将二维码打印至终端
- `--proxy`：代理设置，本来用来调试的（e.g. <http://127.0.0.1:8080>）
- `--tree_view`：课程目录结构，关闭后不显示所有课程目录。
- `--progressbar_view`：进度条控制，关闭后不显示当前视频进度。
- `--image_path`：登录二维码保存路径，留空则不保存。
- `--captcha_solver`：验证码处理方式，`auto`（自动过滑块）/ `manual`（弹窗等人工）/ `none`（旧行为）
- `--captcha_headless`：验证码浏览器是否无头运行，默认有头，自动失败时可以直接人工接管
- `--captcha_timeout`：等待验证码通过的秒数，默认 180
- `--captcha_channel`：用系统已装浏览器跑验证码，可填 `msedge` / `chrome`
- `--captcha_debug`：验证码调试截图保存目录
- `-ai`，`--aicourse`：AI课程，Input AI Course ID and CLASS ID to fu*k aiCourse
- `-h` `--help`：显示帮助

运行示例如下：
> 运行效果：控制台会按“正在攻打章节/课时/视频 → 已攻下课程，cost Xs”的格式打印进度树。

指北就这些啦，~~代码很少可以自己看~~ 现在不少了（）。

---

### `API` 简介

详见源码

#### 实例化 `Commander`

```Python
from commander import Commander

commander = Commander()
# 或者更进阶一些
commander = Commander(speed=1.5, end_thre=0.91)
# 以上控制播放速度以及终止临界值
# speed: 校内学分课播放速度正常最高为1.25, 共享学分课为1.5, 但似乎更高的服务器也接受, 不过怕暴露就谨慎些吧
# end_thre: 智慧树把高于一定百分比的进度视为完成, 0.91 保险一点
# 以上俩参数仅对视频有效, 其他的内容就只有进度0或1
```

### `login` Method

如果您能自己得到 `Cookies` 就可以略过，直接给 `Commander` 实例的 `cookies` 属性赋值即可
_Python3_ 登入样例

```Python
commander.login(username:str, password:str)
commander.login(username:str, password:str, interactive=False) # 禁用交互, 在账号或密码为空时引发异常

# 如果您不想使用 login
# 也可直接传入符合 requests 库要求的 cookies
commander.cookies = {key: "Angel Beats!", "inside Uncle's eyes": value}
# 该 cookies 会覆盖原有值, 同时请确保它是完整的智慧树 cookies，因为 uuid 需要从 cookies 中解析
```

### `commandCourse` Methods Family

```Python
commander.commandCourse(course_id:str) # 把整个课程都干了
commander.commandCourse(course_id:str, tree_view=False) # 把整个课程都干了, 但不显示树状视图
commander.commandZhidaoCourse(recruitAndCourseId) # 点名就要干知到共享学分课
commander.commandHikeCourse(courseId) # 点名就要干校内学分课(hike)
```

### `commandVideo` Methods Family

```Python
commander.commandVideo(course_id, video_id) # 指定干某节课里某视频
commander.commandZhidaoVideo(recruitAndCourseId, videoId) # 这里的 videoId 是从 网页API响应 中获得的
commander.commandHikeVideo(courseId, fileId) # 这俩就在 校内学分课(hike) 网址里
```

### `getContext` Methods Family

```Python
commander.getZhidaoContext(recruitAndCourseId)
commander.getHikeContext(courseId)
commander.getHikeContext(courseId, force=True) # 强制更新context并重置课程学习时间(本地记录)
'''
自动在 `command*Course` `command*Video` 中被调用
返回一个 `dict`, 内含该 ID 对应课程的必要信息以及实例运行后学习该课的总时间, 必要信息没有的话会向服务器请求
该 `dict` 结构请见源码
'''
```

### `hike` API

```Python
# 自动添加时间戳和签名, 并检查返回代码
def hikeQuery(self, url:str, data:dict,sig:bool=False, ok_code:int=200, setTimeStamp:bool=True, method:str="GET")...
# 以下为与网页接口同名的 API, 只返回响应中的 "rt" 部分
def queryResourceMenuTree(self, course_id)...
def stuViewFile(self, course_id, file_id)...
def saveStuStudyRecord(self, course_id, file_id, played_time, prev_time, start_date)...
```

### `zhidao` API

```Python
# 自动添加时间戳和加密, 并检查返回代码
def zhidaoQuery(self, url:str, data:dict, encrypt:bool=True, ok_code:int=0, setTimeStamp:bool=True, method:str="POST", key=VIDEO_KEY)...
# 以下为与网页接口同名的 API, 只返回响应中的 "data" 部分
def gologin(self, RAC_id)...
def queryCourse(self, RAC_id)...
def videoList(self, RAC_id)...
def queryStudyReadBefore(self, course_id, recruit_id)...
def queryStudyInfo(self, lesson_ids:list, video_ids:list, recruit_id)...
def queryUserRecruitIdLastVideoId(self, recruit_id)...
def prelearningNote(self, RAC_id, video_id)...
def loadVideoPointerInfo(self, RAC_id, video_id)...
def lessonPopoupExam(self, RAC_id, video_id, question_ids:list)...
def saveLessonPopupExamSaveAnswer(self, RAC_id, video_id, question_id, answer_ids:str)...
def saveDatabaseIntervalTime(self, RAC_id, video_id, played_time, last_submit, watch_point, token_id=None)...
def saveCacheIntervalTime(self, RAC_id, video_id, played_time, last_submit, watch_point, token_id=None)
```


---

## 多账号 / 切换账号

每个账号用 `--profile <名字>` 完全隔离，不加参数就和原来一样（单账号，状态文件在根目录）。

```powershell
# 新增账号：第一次跑会建 profiles/<名字>/，并引导扫码登录
python main.py --profile 我的号

# 之后所有命令都带上同一个名字
python main.py --profile 我的号 -c <课程ID>
python homework.py --profile 我的号 --course <recruitAndCourseId>
```

### 账号管理

```powershell
python main.py --profiles                  # 列出所有账号：名字 / 登录态 / 最后使用时间 / 有没有独立配置
python main.py --profile-default 我的号     # 设为默认账号：以后不带 --profile 就用它
python main.py --profile-remove 我的号      # 删除账号（含 cookies / 日志 / 缓存），加 --yes 跳过确认
python homework.py --profiles              # 作业脚本里也能看
```

- 账号名就是 `profiles/` 下的目录名，建议取看得懂的（中文也行）；
- 「登录态」读的是 `profiles/<名字>/cookies.json`，显示“未登录”说明还没扫码或者登录态过期；
- 默认账号记录在根目录 `config.json` 的 `default_profile` 字段里，想取消就设回空字符串；
- 每个 profile 目录里独立存放：`cookies.json`、`config.json`、`execution.json`、`logs/`、`aiexamAnswer/`（AI 课程答题缓存）；
- 第一次用某个 profile 时，如果根目录有 `config.json`，会自动复制一份过去（API key、验证码配置都省得重配）；
- `profiles/` 已经写进 `.gitignore`，不会误提交别人的登录态。

---

## 验证码处理（风控滑块 / 点选）

知到判定“刷课太快”时会返回 `code: -12`，网页版此时会弹出**网易易盾验证码**，
通过之后再调用 `validateSlideToken` 解除风控。

> 注意：易盾同一个 captchaId 会**随机下发两种题型**——滑块，或者点选（如“请点击小写q朝向一样的大写F”
> 这种推理点选）。

原项目的处理是直接放弃整门课（打出 `Captcha required` 然后 return），现在改成：

1. 暂停播放，自动打开一个浏览器窗口（复用当前登录 Cookie，同源同账号）；
2. 加载知到网页版同款易盾验证码；
3. **按题型自动处理**：
   - 滑块：截图后用归一化互相关算出缺口位置，按人手轨迹拖动；
   - 点选/推理点选：截图 + 提示文案交给多模态模型。会先把图放大 2 倍，并要求模型
     “先逐字分析（字符/颜色/位置/朝向）→ 判断目标（题干里的参照物不要点）→ 再给坐标”；
     坐标如果落在字符旁边的背景上，会自动吸附到最近的字符上；
4. 拿到 `validate` 后自动上报 `validateSlideToken`，并重发刚才失败的那条请求；
5. 继续刷课，**不再中断课程**。

自动处理没成功时会保留验证码窗口，您手动拖/点一下即可，脚本拿到 `validate` 后会自动继续，
不需要重启进程。

### 安装（可选）

```bash
pip install playwright
playwright install chromium
```

不装也能跑，只是撞到验证码时只能“等一会再重试”，重试多次还不行才跳过当前视频。
如果 Chromium 下载不动，可以直接用系统里的 Edge / Chrome：

```bash
python main.py --captcha_channel msedge -c 课程ID
```

### 点选类验证码（需要多模态模型）

滑块是纯图像算法，不需要模型；点选（尤其“朝向一样”这种推理题）纯算法很难稳定，
所以走多模态模型：把验证码图片 + 提示文案发给模型，让它返回点击坐标。

在 `config.json` 里打开（需要模型支持图片输入，例如 gpt-4o / claude-3-5-sonnet / qwen-vl-max /
glm-4v 等；api_base/api_key/model 留空会复用 `ai.openai` 里的配置）：

```json
"captcha": {
    "vision": {
        "enabled": true,
        "api_base": "https://api.deepseek.com",
        "api_key": "sk-你的key",
        "model": "deepseek-flash",
        "thinking": "auto",
        "max_tokens": 1200
    }
}
```

常见可用的 OpenAI 兼容配置：

| 服务商 | api_base | model 示例 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com` | `deepseek-flash`（支持图片输入）|
| OpenAI | `https://api.openai.com/v1` | `gpt-6.1-sol` |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-3.8-max` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.3` |
| 各种中转 | 你的中转地址 | `gpt-4o` / `claude-opus-5.5` |

- 不配置也能跑：遇到点选会**直接提示您在窗口里点击**，点完自动继续（默认行为）；
- 配置了但模型不认图 / 返回乱码：会重试几次后回到人工点击，不会卡死；
- 隐私提醒：开了这个功能，验证码截图会发送到您配置的模型服务商。

### 配置

`config.json` 新增 `captcha` 段（旧配置会自动补齐）：

```json
"captcha": {
    "solver": "auto",
    "headless": false,
    "timeout": 180,
    "max_retries": 3,
    "browser_channel": "",
    "captcha_id": "4da3050565514a35a50541b0e1f54538",
    "debug_dir": "",
    "vision": {
        "enabled": false,
        "api_base": "",
        "api_key": "",
        "model": ""
    }
}
```

| 字段 | 说明 |
| --- | --- |
| `solver` | `auto` 自动过滑块 / `manual` 只弹窗等人工 / `none` 关闭（旧行为）|
| `headless` | 验证码浏览器是否无头，默认 `false`，自动失败时可以直接人工接管 |
| `timeout` | 等待验证码通过的秒数 |
| `max_retries` | 单条请求最多重试次数，超过后跳过当前视频 |
| `browser_channel` | `msedge` / `chrome`，用系统已装浏览器 |
| `captcha_id` | 易盾 captchaId，知到网页版用的是 `4da3050565514a35a50541b0e1f54538` |
| `debug_dir` | 非空时保存验证码截图，方便排查识别问题 |
| `vision` | 点选类验证码用的多模态模型配置，见上一节 |

### 常见问题

**日志里出现 `滑块缺口 x=58.0px 拖动 574.9px (score=0.108)` 这种离谱数字**
说明题型判错了（把点选当滑块）或模板没对上。新版本会先按提示文案判题型，
并且加了置信度/距离校验：`score < 0.35` 或拖动距离明显不合理时直接放弃拖动、刷新图片，
不会乱拖。

**日志里出现 `多模态模型返回空内容(finish_reason=length/stop, 思维链xx字)`**
说明模型把 token 都花在“思考”上了（DeepSeek 默认开启思考模式），最终正文是空的。
新版对 deepseek 会自动带上 `thinking: disabled`，并把额度提到 1200；
如果用的是中转网关，可以手动把 `captcha.vision.thinking` 设成 `"false"`。

**日志里出现 `多模态模型调用失败`**
模型不支持图片输入 / key 不对 / 网络不通。连续两次失败会自动关掉模型识别，转为人工点击。
注意 `deepseek-chat` / `deepseek-reasoner` 是纯文本模型；要用看图能力请用 `deepseek-flash`
（官方文档：<https://api-docs.deepseek.com/guides/vision/>）。

**验证码窗口没弹出来 / 一直干等**
看日志里 `启动 Chromium 失败 ... 尝试使用系统 Edge/Chrome` 之后有没有成功；
如果两个都失败，就是 Playwright 没装好，重新 `pip install playwright` 即可。

### 单独调试验证码

```bash
python captcha.py --debug-dir captcha_debug
```

会直接弹出验证码窗口并打印拿到的 `validate`，用来确认网络与识别是否正常。
想顺便测点选类的模型识别，加上模型的三个参数即可：

```bash
python captcha.py --debug-dir captcha_debug \
    --vision-base https://api.openai.com --vision-key sk-xxx --vision-model gpt-4o
```

> 验证码是绑定 captchaId 和出口 IP 的，脚本用的就是您当前的 Cookie 和网络，
> 所以不需要额外登录，也不要把 `validate` / 截图随便发给别人。


---

## 题目怎么处理（弹题 / 考试）

### 1. 视频弹题（播放中弹出的题）

知到的弹题接口 `popupAnswer/lessonPopupExam` 会**直接把正确选项带回来**
（`questionOptions[].result == "1"`），脚本只是把这些选项提交上去：

```Python
# commander.py
def answerZhidao(self, q: dict):
    q = ObjDict(q)
    a = [str(opt.id) for opt in q.questionOptions if opt.result == '1']
    return ','.join(a)
```

所以弹题**不需要 AI、不需要 key、不需要任何配置**。刷视频时到点会自动暂停、作答、继续播放，
进度条旁边会短暂显示 `answering quiz`。

想自己控制答案（比如按自己的题库覆盖），继承 `Commander` 重写 `answerZhidao` 即可：

```Python
from commander import Commander

class MyCommander(Commander):
    def answerZhidao(self, q):
        # q.questionId / q.questionOptions 里都有，返回 "选项id,选项id"
        return super().answerZhidao(q)
```

### 2. AI 课程的测验 / 考试（需要 `-ai` 参数）

```bash
# 刷 AI 课程视频 + 参加课后测验/考试
python main.py -ai <courseId> <classId>

# 只刷视频，不碰考试（--noexam 后面必须跟一个值，这是 argparse 的历史遗留）
python main.py -ai <courseId> <classId> --noexam 1
```

作答方式由 `config.json` 的 `ai` 段决定：

```json
"ai": {
    "enabled": true,
    "use_zhidao_ai": true,   // true: 用知到自带的 AI 助手，不需要自己的 key
    "openai": {              // use_zhidao_ai=false 时才用这里的模型
        "api_base": "https://api.openai.com",
        "api_key": "sk-",
        "model_name": "gpt-6.1-sol"
    }
}
```

答案会缓存在 `aiexamAnswer/<courseId>/` 下，重复刷同一门课不会重复问模型。

### 3. 章节作业（普通课程）

用单独的脚本 `homework.py`。

```bash
# 0. 先正常跑一次 main.py 完成扫码登录（会保存 cookies.json）
python main.py

# 1. 看看这门课有哪些作业
python homework.py --course <recruitAndCourseId> --list

# 2. 只取题 + 出答案，不保存（先看看 AI 靠不靠谱）
python homework.py --course <recruitAndCourseId> --dry-run

# 3. 正式填：逐题保存到服务器，然后停下来让你自己去网页检查并提交
python homework.py --course <recruitAndCourseId>

# 4. 填完直接交（不想手动点提交时用）
python homework.py --course <recruitAndCourseId> --submit
```

> 作业站（studentexam-api）用的是 passport 的 **CAS 登录态**，和视频站不是一套：
> 视频站 cookies 还能用的时候，它可能已经过期了（有效期短得多）。这时脚本会提示你扫码，
> 或者直接加 `--login`；登录后会把作业站的会话一起写进 `cookies.json`，下次能省掉 CAS。

> **recruitId 在哪？** 它不在 URL 里，而在你的课程列表接口里
> （`queryShareCourseInfo` 返回的 `courseOpenDtos[].recruitId`，同一项里还有 `recruitAndCourseId`）。
> 不确定就先跑：
>
> ```bash
> python homework.py --list-courses
> ```
>
> 会打印每门课的 name / courseId / recruitId / recruitAndCourseId；
> 如果你手上只有数字 courseId，直接 `--course-id 1000010466` 就行，脚本会自己反查。

它干的事：

1. 用 `cookies.json` 里的登录态做一次 CAS SSO（studentexam-api 是另一套登录态）；
2. `getStudentHomework` 拉作业列表；
3. `doHomework` 取题目（保留保存答案要用的 `eid`）；
4. 逐题问模型（单选/多选/判断/填空都支持）；
5. `saveStudentAnswer` 逐题保存 —— **保存后网页上打开就能看到答案**；
6. 默认**不提交**，你确认无误再提交；加 `--submit` 才自动交。

模型配置有 4 个地方，优先级从高到低：

1. **命令行**（最快，不用改配置文件）：
   ```bash
   python homework.py --course <RAC> --test-ai --ai-base https://api.deepseek.com/v1 --ai-key sk-xxx --ai-model deepseek-flash
   ```
2. `config.json` → `homework.answer`
3. `config.json` → `captcha.vision`（就是验证码用的那个配置，会被复用）
4. `config.json` → `ai.openai`

推荐写成配置文件（只写一次，以后不用带一长串参数）：

```json
"homework": {
    "answer": {
        "api_base": "https://api.deepseek.com/v1",
        "api_key": "sk-你的key",
        "model": "deepseek-flash",
        "thinking": "auto"
    }
}
```

配完先自检一下（不需要登录、不需要课程 ID）：

```bash
python homework.py --test-ai
```

会打印用的是哪个模型/接口、key 有没有读到，并发一句测试请求验证连通性。
注意配置文件里默认的 `sk-` 会被当成“没填”，别指望它。

> 作业站也有自己的滑块风控：保存答案时可能返回
> `{"status": -1, "msg": "滑块验证未通过，不能答题"}`。
> 工具会自动弹易盾、过验证码、调作业站的 `answer/validateSlideToken` 上报，然后重试保存，
> 不需要你手动去浏览器点。连续 3 次过不去才会停下来提示你。

**作业站验证码**：保存答案时作业站也会要滑块/点选。工具会自动弹易盾过验证码、
调 `answer/validateSlideToken` 上报、再重试保存；点选类需要 `captcha.vision` 配好模型，
没配的话就只能人工在窗口里点一下。

**已答过的题会跳过**：每次开始前会调 `getStuAnswerInfoNew` 查服务器上已经保存过答案的题，
这些题不再重复作答（也不会覆盖），需要全部重做时加 `--force`。

已知限制：

- 只处理**未提交**（state=1/5）的作业；已经交过的要在网页上点“重做”，工具不会替你重置；
- 简答题/论述题（题型 5/6）会跳过，留给你人工写；
- CAS 登录态过期时需要重新扫码（`--login` 可以在本脚本里直接扫，不用回 main.py）；
- 遇到滑块验证会自动弹浏览器过验证码（连续 3 次没过才会停下来提示你手动处理）；
- 多选题、填空题的答案格式与网页一致（多选是选项 id 逗号分隔，填空是文本），
  如果某题模型答不出来，那题会保留为空，不影响其它题。

---

## 结构介绍

### 文件结构

- main.py：命令行主函数
- sign.py：负责生成 hike API 所需的 `signature` 参数
- utils.py：一些常用工具（含配置补全 `fillDefaults`）
- logger.py：日志工具，将不同等级的日志写入不同文件
- commander.py：`Commander` 类定义，所有核心代码全塞一起了，莫在意
- captcha.py：验证码求解器（易盾滑块 / 点选，浏览器 + 图像识别）
- homework.py：章节作业半自动（CAS SSO / 取题 / AI 答案 / 保存 / 提交）
- ObjDict.py：`ObjDict` 类定义，继承自 `dict`，可以 `object` 属性形式访问 `dict`
- zd_utils.py：知到 API 所需的工具，如生成 `ev` 和 `secretStr`
- tests/：单元测试（`python -m unittest discover -s tests`）
- config.json：还能是啥，没有的话初次运行 _main.py_ 时将生成
- meta.json：包含版本和分支等信息，也用于更新检查（把 author 改成你的 GitHub 用户名）
- decrypt：非必要的文件夹，内含逆向源代码的工具及源码打包

### Commander Class Structure

```Python
class Commander:
    def __init__(self, cookies: dict = None,
                 headers: dict = None,
                 proxies: dict = None,
                 limit: int = 0,
                 speed: float = None,
                 end_thre: float = None)...

    @property # cannot directly manipulate _cookies property, we need to parse uuid from cookies
    def cookies(self)...
    @cookies.setter
    def cookies(self, cookies: dict|requests.cookies.RequestsCookieJar)...

    def login(self, username: str=None, password: str=None, interactive: bool=True)...
    def commandCourse(self, course_id:str, tree_view:bool=True)...
    def commandVideo(self, course_id, video_id:str)...
############################################
# for some historical reasons
# there are 2 sets of completely different API for hike.zhihuishu.com and studyservice-api.zhihuishu.com
# so we need to use different methods for different API
#############################################
# following are methods for studyservice-api.zhihuishu.com API
    def getZhidaoContext(self, RAC_id:str, force:bool=False)...
    def commandZhidaoCourse(self, RAC_id:str, tree_view:bool=True)...
    def commandZhidaoVideo(self, RAC_id, video_id)...
    def answerZhidao(self, q:dict)...
    def _zhidaoQuery(self, url:str, data:dict, encrypt:bool=True, ok_code:int=0,
               setTimeStamp:bool=True, method:str="POST")...
# end of zhidao methods
#############################################
# following are methods for hike API
    def getHikeContext(self, course_id:str, force:bool=False)...
    def commandHikeCourse(self, course_id:str, tree_view:bool=True)...
    def commandHikeVideo(self, course_id, file_id, prev_time=0)...
    def commandFile(self, course_id, file_id)...
    def _traverse(self,course_id, node: ObjDict, depth=0, tree_view=True)...
    def _hikeQuery(self, url:str, data:dict,sig:bool=False, ok_code:int=200,
                   setTimeStamp:bool=True, method:str="GET")...
# end of hike methods
#######################################
# shared private methods
    def _watchVideo(self, video_id)... # it's probably unnecessary but let's keep it to fool those idiots
    def _apiQuery(self, url:str, data:dict, method:str="POST")...
    def _checkCookies(self)...
    def _checkTimeLimit(self, cid)...
    def _sessionReady(self, ctx:dict=None)...
```

我的很大，你忍一下（指类定义）

---
