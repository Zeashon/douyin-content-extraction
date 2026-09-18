---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'b6f4952b-1b7c-4890-9e1b-8d41b108e390'
  PropagateID: 'b6f4952b-1b7c-4890-9e1b-8d41b108e390'
  ReservedCode1: 'cadae823-fed9-4787-931f-d955e03bac4d'
  ReservedCode2: 'cadae823-fed9-4787-931f-d955e03bac4d'
---

# 抖音内容提取：实战陷阱手册

来自 72 条视频全流程提取的踩坑记录。爬抖音前先过一遍，能省数小时调试时间。

## 浏览器与页面结构

### 1. 登录墙
未登录时搜索结果和用户主页均被拦截，弹出强制扫码。
**应对**：persistent context 保存登录态（本仓库 `.browser_profile/`），首次扫码后长期免登录。

### 2. 滑块验证码
搜索页可能弹出滑块验证。
**应对**：拿到主页 URL（`/user/{sec_uid}`）直接导航，可绕过搜索页验证。

### 3. 整页滚动无效
抖音网页端是内嵌滚动容器，`window.scrollTo()` 无效（scrollY 恒为 0）。
**应对**：找 `.route-scroll-container`，设置其 `scrollTop = scrollHeight`，连续 5 轮无新增即到底。

### 4. 作品列表不在 tabpanel 里
`#semiTabPanelpost` 面板内可能只有 motion overlay。
**应对**：直接从 `.route-scroll-container` 下取最大的 `ul`（children 最多者即作品列表）。

### 5. 共创视频与图文笔记
- 共创视频 aria-label 以"共创"开头而非点赞数字，解析点赞时需单独处理
- 图文笔记 href 是 `/note/` 而非 `/video/`，文案几百字，本身就是完整内容，无需转写

### 6. 作品计数差异
页面"作品 N"标签与实际 li 数可能不一致（置顶/图文计数规则不同）。以 DOM 实际提取数为准。

## API 与数据

### 7. RENDER_DATA 循环引用
`window.RENDER_DATA` 等 React 内部对象含 Fiber 循环引用，整体 `JSON.stringify` 必失败。
**注意**：不是不能读，是不能整体序列化。单点读属性路径完全可行（见下条）。

### 8. React Props 内存挖掘（API 失败的救星）
抖音全站同一套 x-player，完整 `awemeInfo` 挂在播放器 DOM 祖先节点的
`__reactProps$xxx` 属性上：
- 键名带随机后缀，必须 `indexOf('__reactProps')` 模糊匹配，硬编码必失败
- 从 `<video>` 元素沿 `parentNode` 向上爬
- player 路径 `props.children[0].props.value.player`（children 可能不是数组）
- 拿到的 `playApi` 可能是 302 跳转地址，下载需跟随重定向

**何时用**：detail API 被风控返回空时，同页 evaluate 读取，零额外请求、不加重风控。

### 9. API 风控递增
连续访问详情页约 24 条后，成功率从 100% 骤降到约 50%。
**应对**：每批 ≤24 条，批间停 30 秒；批内失败条目以 3-4 秒/条间隔单独重试。

### 10. 视频 ID 截断
上游数据中个别视频 ID 可能被截断（19 位变 16 位），访问时页面跳转到精选页。
**应对**：提取前校验 ID 长度；DOM 列表、API 响应、已有文档三处交叉核对。

## 下载

### 11. 播放地址 2-3 小时过期
`play_addr` URL 带签名参数（`l=20260918...`），延迟下载会全部 403。
**应对**：**提取一批立即下载一批**。本仓库 extract_details.py 已内置为默认行为。

### 12. CDN 防盗链
douyinvod.com 直接 requests/httpx 下载返回 403 或连接重置。
**应对**：必须带登录 Cookie（`sessionid`/`ttwid`/`sid_guard`/`odin_tt` 等）+
`Referer: https://www.douyin.com/`。最省事的方式：直接用 playwright 浏览器上下文的
`context.request.get()`，自动携带全部 Cookie。

### 13. 画质选择
`video.bit_rate[]` 有多档画质。转写只需音频，选 `gear_name` 含
`adapt_low`/`low_540`/`lower_540` 的最低档；没有则取最后一个 mp4。

### 14. 音频流优先
口播视频的配乐轨即原声（`music.is_original_music=1`），`music.play_url` 音频流
只有几 MB，比视频小一个量级。**但** `is_original_music=0`（第三方 BGM）时音频流
转写出来是歌词/噪音——先判断标记，转写后校验有效语音时长，异常则降级下视频抽轨。

## 转写

### 15. 引擎选择（中文场景）
| | faster-whisper base | SenseVoice-Small |
|---|---|---|
| 同音字 | 错误较多（"舰人下菜碟"） | 明显更准（"见人下菜碟"） |
| 标点 | 无 | 自带 |
| 繁简 | 输出繁体，需 zhconv | 简体 |
| CPU 速度 | rtf≈0.30 | rtf≈0.17 |

**结论**：中文逐字稿首选 SenseVoice；需要时间戳对齐（字幕）或 funasr 不可用时用 Whisper。

### 16. 模型下载（中国大陆）
- OpenAI 官方 Whisper 模型源（openaipublic.azureedge.net）被墙
- **SenseVoice**：funasr 自动从 modelscope.cn 下载，国内直连无需翻墙
- **Whisper 备选**：hf-mirror.com 下载 `Systran/faster-whisper-base` 的 4 个文件
  （model.bin/config.json/tokenizer.json/vocabulary.txt）本地加载
- funasr 报 `torchaudio is not installed` → 装 `kaldi-native-fbank` 即可

### 17. 批量转写崩溃
长视频（>5 分钟）批量时可能内存压力导致进程被杀。
**应对**：增量保存（每条完成立即写盘）+ 断点续跑（重跑自动跳过已完成）。

### 18. 环境细节
- 多 Python 共存时用 `python -m pip install`，避免 pip 装到别的解释器
- SenseVoice 后处理的文本开头可能残留标点（如"。xxx"），`lstrip("。，、！？；：")`
- Whisper 中文输出繁体 → `zhconv.convert(text, "zh-cn")`

## 输出规范

- AI 章节摘要 ≠ 逐字稿：文档里必须分开设节、明确标注，不可混用标题
- 逐字稿用户常规偏好：整篇连续文本、无时间戳、按句末标点每 3 句分段
- 转写说明保留一行"AI 语音识别转写，可能存在少量识别错误"