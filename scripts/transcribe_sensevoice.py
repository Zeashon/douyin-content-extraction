#!/usr/bin/env python3
"""
transcribe_sensevoice.py — SenseVoice-Small 批量语音转写（中文场景首选，优于 Whisper）

实测对比（同一 7 分钟中文口播）:
    SenseVoice-Small: 同音字准 / 自带标点 / 直接简体 / rtf≈0.17 (CPU)
    faster-whisper-base: 同音字错多 / 无标点 / 输出繁体 / rtf≈0.30

要点:
  - 模型(~900MB)首次运行自动从 modelscope.cn 下载(国内直连, 无需翻墙)
  - 增量保存: 每条完成立即写盘, 进程被杀后重跑自动续(长视频批量时内存压力大)
  - 输出为整段带标点简体文本(无时间戳), 适合直接作为逐字稿

用法:
    python scripts/transcribe_sensevoice.py                    # 转 output/videos/ 全部
    python scripts/transcribe_sensevoice.py --dir output/videos --out output/transcripts.json

产物: output/transcripts.json  { "<video_id>": {"text": "带标点逐字稿"} }
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "output")
DEFAULT_VIDEOS = os.path.join(OUT_DIR, "videos")

MEDIA_EXTS = (".mp4", ".m4a", ".aac", ".mp3", ".wav")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_VIDEOS, help="媒体文件目录")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "transcripts.json"))
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.dir)
                   if f.lower().endswith(MEDIA_EXTS)) \
        if os.path.isdir(args.dir) else []
    if not files:
        sys.exit(f"[x] {args.dir} 下没有媒体文件。先运行 extract_details.py 下载。")

    results = {}
    if os.path.exists(args.out):
        results = json.load(open(args.out, encoding="utf-8"))
        print(f"[*] 已有 {len(results)} 条转写结果, 断点续跑")

    todo = [f for f in files if os.path.splitext(f)[0] not in results]
    print(f"[*] 共 {len(files)} 个文件, 待转写 {len(todo)}")

    print("[*] 加载 SenseVoice-Small (首次运行自动下载约 900MB)...")
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess

    model = AutoModel(
        model="iic/SenseVoiceSmall",
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 30000},
        device="cpu",
        disable_update=True,  # 跳过版本检查, 加速启动
    )
    print("[+] 模型就绪")

    t0 = time.time()
    for i, fn in enumerate(todo, 1):
        vid = os.path.splitext(fn)[0]
        path = os.path.join(args.dir, fn)
        try:
            res = model.generate(
                input=path, cache={}, language="zh", use_itn=True,
                batch_size_s=60, merge_vad=True, merge_length_s=15,
            )
            text = rich_transcription_postprocess(res[0]["text"])
            # 后处理可能残留开头标点(如 "。xxx"), 清理掉
            text = text.lstrip("。，、！？；：").strip()
            results[vid] = {"text": text}
        except Exception as e:
            print(f"[ERR] {vid}: {e}")
            continue
        # 增量保存: 每条写盘, 崩了也能续
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        cost = time.time() - t0
        eta = cost / i * (len(todo) - i) if i < len(todo) else 0
        print(f"[{i}/{len(todo)}] {vid} OK ({len(text)}字, 剩余约{eta/60:.0f}分钟)")

    print(f"[+] 完成, 共 {len(results)} 条 → {args.out}")


if __name__ == "__main__":
    main()
