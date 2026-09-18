# douyin-content-extraction

抖音内容提取技能包 —— 一套可被任意自主智能体（AI Agent）直接调用的抖音内容提取流水线。

给你的智能体一句"把这个账号的视频逐字稿提取出来"，它就能按本技能的流程跑完：
**作品列表 → 官方 AI 内容摘要 → 视频/音频下载 → 语音转写 → Markdown 学习文档**。

所有能力封装为独立可运行的 Python 脚本，不依赖任何特定智能体框架——人也可以直接跑。

## 它能拿到什么

| 内容 | 来源 | 说明 |
|---|---|---|
| 作品列表 | DOM 提取 | 标题/文案/点赞/置顶/类型/链接，可导出 Excel |
| **AI 内容摘要 + 章节详解** | 拦截官方 detail API | 抖音官方 AI 生成的内容概括与带时间戳章节，零转写成本，约 70-75% 视频有 |
| **完整口播逐字稿** | 下载 + SenseVoice 转写 | 带标点简体中文、整篇成文（非时间戳字幕） |
| 带时间戳字幕（可选） | faster-whisper | 需要对齐时间轴时用 |

## 快速开始

```bash
git clone https://github.com/Zeashon/douyin-content-extraction.git
cd douyin-content-extraction

# 1. 安装依赖（建议 Python 3.10+）
pip install -r requirements.txt
playwright install chromium
# 另需系统安装 ffmpeg 并加入 PATH

# 2. 提取账号全部作品（首次运行弹出浏览器, 用抖音 App 扫码, 之后免登录）
python scripts/extract_account.py https://www.douyin.com/user/<sec_uid> --excel

# 3. 提取 AI 章节摘要 + 当场下载视频/音频（分批 24 条, 自动风控缓冲）
python scripts/extract_details.py --ids-file output/account_videos.json

# 4. 转写为逐字稿（SenseVoice 首次运行自动从 modelscope.cn 下载 ~900MB 模型）
python scripts/transcribe_sensevoice.py

# 5. 整理成 Markdown 学习文档
python scripts/make_docs.py
# → output/docs/  每条视频一个 MD + 索引 README.md
```

## 给智能体用（Claude Code / Codex / WorkBuddy / 任意 Agent）

本仓库遵循 [Agent Skills](https://agentskills.io) 惯例：**`SKILL.md` 是给智能体读的
操作手册**，`scripts/` 是它应该实际执行的命令。通用接入方式：

- **Claude Code / Claude Skills 兼容客户端**：把本目录放入
  `~/.claude/skills/douyin-content-extraction/`（或项目级 `.claude/skills/`），
  对话中说"用 douyin-content-extraction 提取这个账号"即可触发。
- **OpenAI Codex**：在 `AGENTS.md` 中加一行：
  `Read SKILL.md in douyin-content-extraction/ and follow its workflow when the user asks to extract Douyin content.`
- **WorkBuddy / 其他技能型智能体**：把本目录放进其 skills 目录（通常支持任意含
  `SKILL.md` 的文件夹），或把 `SKILL.md` 内容注册为一条技能指令。
- **没有任何技能机制的自定义 Agent**：把 `SKILL.md` 作为 system prompt 的一部分，
  或在用户提问时检索注入。

智能体只需要两个能力：能读文件、能执行 `python` 命令。登录扫码环节需要真人配合
一次（首次运行浏览器窗口 120 秒内扫码，登录态持久保存）。

## 仓库结构

```
├── SKILL.md                     # 给智能体的操作手册（何时用/怎么跑/决策表/陷阱）
├── README.md                    # 本文件
├── requirements.txt
├── LICENSE                      # MIT + 内容合规附加条款
├── scripts/
│   ├── extract_account.py       # 阶段1: 登录+滚动加载+作品列表(JSON/Excel)
│   ├── extract_details.py       # 阶段2: AI章节拦截+React Props降级+分批+当场下载
│   ├── transcribe_sensevoice.py # 阶段3: SenseVoice 转写(中文首选, 断点续跑)
│   ├── transcribe_whisper.py    # 阶段3备选: faster-whisper(带时间戳/国内镜像)
│   └── make_docs.py             # 阶段4: 整理成 Markdown 学习文档+索引
└── references/
    └── pitfalls.md              # 18 条实战陷阱与应对(爬抖音前必读)
```

## 为什么这样设计（实战踩坑沉淀）

- **提取一批 → 立即下载一批**：抖音播放地址带签名，2-3 小时就过期。脚本把提取和
  下载合并为流水线，从根上规避。
- **API 拦截 + React Props 内存挖掘双通道**：detail API 连续访问约 24 条后风控加重；
  失败时脚本自动在同一页面读取 React 内存中的播放器数据（零额外请求），实测可救回
  大部分失败。
- **音频流优先**：口播视频的配乐轨就是原声，直接下载音频比下载视频小一个量级，
  批量任务快得多。
- **SenseVoice 而非 Whisper 作为中文首选**：实测同音字更准、自带标点、直接简体、
  CPU 速度快近一倍；Whisper 中文输出繁体且无标点，作为备选保留（时间戳场景）。
- **断点续跑**：详情提取和转写全量增量写盘，进程被杀（长视频内存压力）后重跑自动续。

完整踩坑记录见 [references/pitfalls.md](references/pitfalls.md)。

## 合规与免责

本工具仅提供技术能力。提取到的文案与逐字稿版权归原作者所有：

- 建议用途：个人学习、内容存档、内部研究
- 公开转载、洗稿、商用需事先取得原作者授权
- 使用者需自行遵守抖音用户协议与所在地版权法律

详见 [LICENSE](LICENSE) 附加条款。

## 已知限制

- 需真人首次扫码登录（登录态长期有效）
- 约 25-30% 的视频没有官方 AI 章节数据（新发布或较老的视频）
- 转写为 AI 自动识别，个别同音字错误属正常现象，重要内容建议人工校对
- 抖音前端结构变动可能需要更新选择器（欢迎提 Issue / PR）
