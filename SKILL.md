---
name: douyin-content-extraction
description: Extract Douyin (抖音) account video lists, captions, official AI chapter summaries, and full spoken-word transcripts. Pipeline: Playwright login-persistent browsing → DOM/API interception → anti-hotlink download → SenseVoice/Whisper speech-to-text → formatted Markdown deliverables. Use when the user wants to extract, archive, or analyze Douyin video content, captions (文案), or transcripts (逐字稿) for any account or video link.
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '71119f3c-2dd6-44c3-bdab-15e8da0e8c15'
  PropagateID: '71119f3c-2dd6-44c3-bdab-15e8da0e8c15'
  ReservedCode1: '9b821af4-70b9-402b-abf0-f3b7997daee9'
  ReservedCode2: '9b821af4-70b9-402b-abf0-f3b7997daee9'
---

# 抖音内容提取 (Douyin Content Extraction)

从抖音账号或视频链接提取：作品列表 → 官方 AI 内容摘要/章节 → 完整口播逐字稿，
最终整理成 Markdown 学习文档。本技能的所有能力都封装在 `scripts/` 下的独立脚本中，
**优先调用脚本执行，不要在对话里重写爬取逻辑**。

## 适用场景

- 提取某个抖音账号的全部视频文案/标题/点赞等元数据
- 用户提供一个或多个视频链接，要求提取内容摘要或逐字稿
- 分析竞品/对标账号的内容结构
- 用户明确要求"完整口播逐字稿"（需下载 + 语音转写）

## 前置条件（第一次使用前与用户确认）

1. **必须登录**：抖音网页端有登录墙，未登录无法查看任何作品。脚本首次运行会打开
   浏览器窗口，用户需用抖音 App 扫码（120 秒内）。登录态保存在 `.browser_profile/`，
   之后免扫码。
2. **环境准备**（一次性）：

   ```bash
   pip install -r requirements.txt
   playwright install chromium
   # ffmpeg 需系统安装并在 PATH 中（转写需要）
   ffmpeg -version
   ```

3. **合规告知**：提取内容仅限个人学习/存档/内部研究；公开转载、洗稿、商用需原作者
   授权。开始前向用户说明这一边界。

## 工作流程

按需选择入口；所有产物默认写入 `output/`。

### 阶段 1：账号作品列表

```bash
python scripts/extract_account.py <主页URL或sec_uid> --excel
```

- 产出 `output/account_videos.json`（ID/标题/点赞/置顶/类型/链接）
- 图文笔记（`/note/`）文案很长，本身就是完整文字内容，**无需转写**
- 若用户只给了视频链接，可跳过本阶段，直接进入阶段 2 的 `--ids`

### 阶段 2：视频详情 + AI 章节 + 当场下载（核心）

```bash
python scripts/extract_details.py --ids-file output/account_videos.json
# 或单个/多个链接:
python scripts/extract_details.py --ids <id1>,<id2>
```

- 拦截抖音官方 detail API，拿到 **AI 内容摘要**（`chapter_abstract`）和**带时间戳
  章节详解**（`chapter_list`）——这是比标题文案有价值得多的内容，且零转写成本。
  约 70-75% 的视频有 AI 章节数据。
- **默认每批提取完立即下载该批视频**（`--no-download` 关闭）。不要先提取全部地址
  再统一下载——播放地址带签名，2-3 小时就过期。
- 原声口播视频（`is_original_music=1`）优先下载音频流（小一个量级）。
- 进度实时写入 `output/details_progress.json`，中断重跑自动续。

### 阶段 3：语音转写（需要逐字稿时）

```bash
python scripts/transcribe_sensevoice.py     # 中文首选: 带标点/简体/同音字准/快
# 需要时间戳对齐(字幕)或 funasr 不可用时:
python scripts/transcribe_whisper.py --model <本地CT2模型目录> --timestamps
```

- SenseVoice 模型首次运行从 modelscope.cn 自动下载（约 900MB，国内直连）。
- 每条完成即写盘，长视频批量时若进程被杀，重跑自动续。
- 转写完成后**校验**：若音频流转写结果疑似歌词/重复句（BGM 非原声），改用视频
  文件重转（`transcribe_sensevoice.py --dir` 指向视频目录只补缺）。

### 阶段 4：整理交付文档

```bash
python scripts/make_docs.py
```

产出 `output/docs/`：每条视频一个 MD（基本信息/文案/AI 内容摘要/逐字稿）+ 总索引
README.md。逐字稿按用户常规偏好格式化：**整篇连续文本、无时间戳、按句末标点每 3 句
分段**；AI 摘要章节明确标注"非逐字稿"，避免与真逐字稿混淆。

## 决策要点

| 用户需求 | 执行路径 |
|---|---|
| 只要文案清单 | 阶段 1，交付 JSON/Excel |
| 要"内容/学什么" | 阶段 1+2，AI 章节已覆盖核心，交付 MD |
| 要"完整逐字稿" | 全部 4 阶段，明确告知约 45-60 分钟/百条(CPU) |
| 单个视频链接 | 跳过阶段 1，`--ids` 直接进阶段 2 |

## 陷阱速查（完整版见 references/pitfalls.md）

- **风控递增**：连续访问详情页 >24 条后成功率骤降 → 脚本已内置分批(24/批)与批间
  30s 缓冲；API 拦截失败时脚本自动降级 React Props 内存挖掘（同页零请求）
- **地址过期**：play_addr 签名 2-3 小时失效 → 提取一批立即下载一批（脚本默认行为）
- **ID 截断**：上游数据个别 ID 可能缺位（19 位变 16 位），访问会跳转精选页 →
  脚本启动时自动校验 ID 长度并告警
- **滚动容器**：抖音是内嵌滚动（`.route-scroll-container`），`window.scrollTo` 无效
- **CDN 防盗链**：下载必须带登录 Cookie → 脚本用浏览器上下文 request 自动携带

## 注意

- 不要在输出文档里把 AI 章节摘要标题写成"逐字稿"，两者必须明确区分。
- 转写结果开头可能有残留标点，脚本已清理；交付前抽查 1-2 条确认质量。
- 提醒用户：转写为 AI 自动生成，个别同音字错误属正常，重要段落建议人工校对。