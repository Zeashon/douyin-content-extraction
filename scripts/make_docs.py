#!/usr/bin/env python3
"""
make_docs.py — 把提取数据整理成 Markdown 学习文档（最终交付物）

读取:
    output/account_videos.json   — 作品列表(extract_account.py)
    output/details_progress.json — 视频详情/AI章节(extract_details.py)
    output/transcripts.json      — 逐字稿(transcribe_sensevoice.py, 可选)

输出:
    output/docs/<日期>_<标题>.md  — 每条视频一个文档
    output/docs/README.md        — 总索引

文档结构:
    # 标题
    ## 基本信息 (ID/日期/时长/点赞/链接)
    ## 视频文案
    ## AI 内容摘要 (抖音官方AI生成, 若有; 注明"非逐字稿")
    ## 口播逐字稿 (SenseVoice 转写, 按句末标点每3句分段, 无时间戳)

用法:
    python scripts/make_docs.py                    # 默认读 output/ 下三个文件
    python scripts/make_docs.py --outdir output/docs
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "output")


def load_json(path):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return None


def safe_filename(name: str, max_len: int = 60) -> str:
    name = re.sub(r'[\\/:*?"<>|#%&{}$!\'@+`=\s]+', "_", name).strip("_.")
    return (name[:max_len].rstrip("_")) or "untitled"


def fmt_duration(ms) -> str:
    try:
        s = int(ms) // 1000
        return f"{s // 60}分{s % 60}秒" if s >= 60 else f"{s}秒"
    except Exception:
        return "未知"


def to_paragraphs(text: str, sents_per_para: int = 3) -> str:
    """带标点整段文本 → 按句末标点切句, 每 N 句合并为一段。"""
    parts = re.split(r"(?<=[。！？!?；;])", text)
    parts = [p.strip() for p in parts if p.strip()]
    return "\n\n".join(
        "".join(parts[i:i + sents_per_para])
        for i in range(0, len(parts), sents_per_para)
    )


def fmt_ts(ms) -> str:
    try:
        s = int(ms) // 1000
        return f"{s // 60:02d}:{s % 60:02d}"
    except Exception:
        return "00:00"


def build_doc(vid, list_rec, detail, transcript) -> str:
    title = (detail or {}).get("title") or (list_rec or {}).get("text") or vid
    lines = [f"# {title}", ""]

    # 基本信息
    dur = (detail or {}).get("duration") or 0
    date = (detail or {}).get("create_date") or ""
    digg = (detail or {}).get("digg")
    is_note = (list_rec or {}).get("type") == "note"
    url = ((list_rec or {}).get("url")
           or f"https://www.douyin.com/{'note' if is_note else 'video'}/{vid}")
    lines += ["## 基本信息", "",
              f"- **视频ID**: {vid}"]
    if date:
        lines.append(f"- **发布日期**: {date}")
    if dur:
        lines.append(f"- **时长**: {fmt_duration(dur)}")
    if digg is not None:
        lines.append(f"- **点赞**: {digg}")
    lines.append(f"- **链接**: {url}", "")

    # 视频文案
    desc = (detail or {}).get("desc") or (list_rec or {}).get("text") or ""
    if desc:
        lines += ["## 视频文案", "", desc.strip(), ""]

    # AI 内容摘要(非逐字稿, 明确标注)
    abstract = (detail or {}).get("chapter_abstract") or ""
    chapters = (detail or {}).get("chapters") or []
    if abstract or chapters:
        lines += ["## AI 内容摘要", "",
                  "> 抖音平台 AI 自动生成，高度概括，非逐字稿。", ""]
        if abstract:
            lines += [abstract.strip(), ""]
        if chapters:
            lines += ["### 章节详解", ""]
            for i, c in enumerate(chapters, 1):
                head = f"{i}. **[{fmt_ts(c.get('ts'))}] {c.get('title', '')}**"
                if c.get("detail"):
                    head += f" — {c['detail']}"
                lines.append(head)
            lines.append("")

    # 口播逐字稿
    lines += ["## 口播逐字稿", ""]
    text = (transcript or {}).get("text", "").strip()
    if text:
        lines += ["> 以下为 SenseVoice 语音识别转写，完整记录口播内容；"
                  "可能存在少量识别错误。", "", to_paragraphs(text), ""]
    elif is_note:
        lines += ["> 本条为图文笔记，无音频。上方「视频文案」即为完整文字内容。", ""]
    else:
        lines += ["> 暂无转写数据。运行 transcribe_sensevoice.py 后重新生成本文档。", ""]

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default=os.path.join(OUT_DIR, "account_videos.json"))
    ap.add_argument("--details", default=os.path.join(OUT_DIR, "details_progress.json"))
    ap.add_argument("--transcripts", default=os.path.join(OUT_DIR, "transcripts.json"))
    ap.add_argument("--outdir", default=os.path.join(OUT_DIR, "docs"))
    args = ap.parse_args()

    videos = load_json(args.list) or []
    details = load_json(args.details) or {}
    transcripts = load_json(args.transcripts) or {}

    if not videos and not details:
        sys.exit("[x] 没有数据。先运行 extract_account.py / extract_details.py")

    # 合并 ID 全集（列表为准, 详情补充）
    ids = []
    seen = set()
    for it in videos:
        if it["id"] not in seen:
            seen.add(it["id"])
            ids.append(it["id"])
    for vid in details:
        if vid not in seen:
            seen.add(vid)
            ids.append(vid)

    list_by_id = {it["id"]: it for it in videos}
    os.makedirs(args.outdir, exist_ok=True)

    index = []
    n_tr = 0
    for vid in ids:
        lr = list_by_id.get(vid)
        d = details.get(vid, {})
        tr = transcripts.get(vid)
        if tr:
            n_tr += 1
        doc = build_doc(vid, lr, d, tr)
        date = d.get("create_date") or ""
        title = d.get("title") or (lr or {}).get("text") or vid
        fn = (f"{date}_{safe_filename(title)}.md") if date else f"{safe_filename(title)}.md"
        with open(os.path.join(args.outdir, fn), "w", encoding="utf-8") as f:
            f.write(doc)
        index.append((title, fn, date))

    # 索引
    with open(os.path.join(args.outdir, "README.md"), "w", encoding="utf-8") as f:
        f.write("# 抖音内容学习库\n\n")
        f.write(f"> 共 {len(ids)} 条 | 含逐字稿 {n_tr} 条\n\n")
        for title, fn, date in index:
            enc = fn.replace("#", "%23")
            f.write(f"- [{title}](./{enc}){(' (' + date + ')') if date else ''}\n")

    print(f"[+] 生成 {len(ids)} 个文档 → {args.outdir}")
    print(f"[*] 含逐字稿: {n_tr} 条（缺转写的先跑 transcribe_sensevoice.py 再重跑本脚本）")


if __name__ == "__main__":
    main()
