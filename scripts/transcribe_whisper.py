#!/usr/bin/env python3
"""
transcribe_whisper.py — faster-whisper 批量转写（SenseVoice 的备选方案）

何时用这个而不是 SenseVoice:
  - 需要【时间戳对齐】(字幕/剪辑) 时: Whisper 按 segment 输出起止时间
  - 环境装不了 funasr / 模型下载受限时

中国大陆注意:
  - OpenAI 官方模型源被墙, load_model() 直接失败
  - 本脚本支持从本地目录加载 CTranslate2 模型: 用 hf-mirror.com 下载
    https://hf-mirror.com/Systran/faster-whisper-base/resolve/main/{model.bin,
    config.json, tokenizer.json, vocabulary.txt} 四个文件放到一个目录,
    然后 --model <目录路径>
  - Whisper 中文输出为繁体 → 本脚本自动用 zhconv 转简体

用法:
    python scripts/transcribe_whisper.py --model <本地模型目录>
    python scripts/transcribe_whisper.py --model <本地模型目录> --timestamps

产物: output/transcripts_whisper.json
      {"<id>": {"segments": [[start, end, text], ...], "text": "整篇"}}
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
    ap.add_argument("--model", required=True,
                    help="本地 CTranslate2 模型目录(hf-mirror 下载) 或模型名")
    ap.add_argument("--dir", default=DEFAULT_VIDEOS)
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "transcripts_whisper.json"))
    ap.add_argument("--timestamps", action="store_true",
                    help="同时保留带时间戳的 segments")
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        sys.exit(f"[x] 目录不存在: {args.dir}")
    files = sorted(f for f in os.listdir(args.dir)
                   if f.lower().endswith(MEDIA_EXTS))
    if not files:
        sys.exit("[x] 没有可转写的媒体文件")

    try:
        from zhconv import convert as zh_convert
    except ImportError:
        zh_convert = None
        print("[!] 未装 zhconv, 繁体输出将保留原样 (pip install zhconv)")

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print("[+] 模型就绪")

    results = {}
    if os.path.exists(args.out):
        results = json.load(open(args.out, encoding="utf-8"))
    todo = [f for f in files if os.path.splitext(f)[0] not in results]
    print(f"[*] 共 {len(files)}, 待转写 {len(todo)}")

    for i, fn in enumerate(todo, 1):
        vid = os.path.splitext(fn)[0]
        try:
            segments, info = model.transcribe(
                os.path.join(args.dir, fn), language="zh", vad_filter=True)
            segs = []
            texts = []
            for s in segments:
                t = s.text.strip()
                if zh_convert:
                    t = zh_convert(t, "zh-cn")
                segs.append([round(s.start, 1), round(s.end, 1), t])
                texts.append(t)
            rec = {"text": "".join(texts)}
            if args.timestamps:
                rec["segments"] = segs
            results[vid] = rec
        except Exception as e:
            print(f"[ERR] {vid}: {e}")
            continue
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[{i}/{len(todo)}] {vid} OK ({len(texts)}段)")

    print(f"[+] 完成 → {args.out}")


if __name__ == "__main__":
    main()
