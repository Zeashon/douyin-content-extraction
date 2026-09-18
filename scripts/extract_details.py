#!/usr/bin/env python3
"""
extract_details.py — 批量提取视频详情（AI 内容摘要/章节/播放地址），并可当场下载

核心设计（来自实战踩坑）:
  1. 播放地址(play_addr)带签名, 有效期仅 2-3 小时 → 本脚本「提取一批立即下载一批」,
     默认开启下载(--no-download 可关闭), 彻底规避地址过期。
  2. detail API 有递增风控: 连续访问约 24 条后成功率从 100% 降到 50% → 每批默认
     24 条, 批间停 30 秒; 失败条目自动「React Props 内存挖掘」降级(同页零请求)。
  3. 断点续跑: 进度实时写 output/details_progress.json, 中断后重跑自动跳过已完成。

用法:
    python scripts/extract_details.py --ids-file output/account_videos.json
    python scripts/extract_details.py --ids 7671128202903931065,7667764962681863089
    # 只要元数据不下视频:
    python scripts/extract_details.py --ids-file output/account_videos.json --no-download

产物:
    output/details_progress.json   — 全部视频的详情数据(断点续跑的进度文件, 即最终产物)
    output/videos/<id>.mp4         — 下载的视频(--no-download 时无)
"""
import argparse
import asyncio
import json
import os
import sys
import time

from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(ROOT, ".browser_profile")
OUT_DIR = os.path.join(ROOT, "output")
VIDEOS_DIR = os.path.join(OUT_DIR, "videos")
PROGRESS_FILE = os.path.join(OUT_DIR, "details_progress.json")

BATCH_SIZE = 24          # 单批条数(风控临界点)
BATCH_PAUSE_SEC = 30     # 批间隔
PAGE_WAIT_MS = 2500      # 每页等待 API 响应
EXTRA_WAIT_MS = 1500     # 无响应时再等
RETRY_PAUSE_SEC = 3      # 失败重试间隔


def load_ids(args) -> list:
    ids = []
    if args.ids:
        ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    elif args.ids_file:
        if not os.path.exists(args.ids_file):
            sys.exit(f"[x] 找不到 {args.ids_file}")
        data = json.load(open(args.ids_file, encoding="utf-8"))
        if isinstance(data, list) and data and isinstance(data[0], dict):
            ids = [d["id"] for d in data if d.get("type") != "note"]  # 图文笔记无视频
        else:
            ids = [str(d) for d in data]
    else:
        sys.exit("[x] 需要 --ids-file 或 --ids")
    # 陷阱: 个别 ID 可能被截断(标准 19 位), 长度异常的直接告警
    for i in ids:
        if len(i) not in (18, 19):
            print(f"[!] 警告: ID {i} 长度 {len(i)} 异常(正常19位), 可能被截断, 提取大概率失败")
    return ids


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        return json.load(open(PROGRESS_FILE, encoding="utf-8"))
    return {}


def save_progress(progress: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ---- 页面内降级: React Props 内存挖掘（API 被风控时, 同页零请求救回） -----------
# 抖音全站同一套 x-player React 组件, 完整 awemeInfo 挂在播放器祖先节点的
# __reactProps$xxx 上。键名带随机后缀, 必须 indexOf 模糊匹配。
REACT_PROPS_JS = """
() => {
  const videos = document.querySelectorAll('video');
  if (!videos.length) return null;
  const video = Array.from(videos).find(v => !v.paused) || videos[0];
  let parent = video.parentNode, reactProps = null;
  while (parent) {
    const key = Object.keys(parent).find(k => k.indexOf('__reactProps') > -1);
    if (key) { reactProps = parent[key]; break; }
    parent = parent.parentNode;
  }
  if (!reactProps) return null;
  const children = reactProps.children;
  const queue = Array.isArray(children) ? children : [children];
  let player = null;
  for (const c of queue) {
    const p = c && c.props && c.props.value && c.props.value.player;
    if (p) { player = p; break; }
  }
  if (!player || !player.config || !player.config.awemeInfo) return null;
  const info = player.config.awemeInfo;
  const mp4 = (player.videoList || []).filter(v => v.videoFormat === 'mp4').pop();
  return {
    id: info.awemeId,
    desc: info.desc,
    duration: player.config.duration,
    video_url: mp4 ? mp4.playApi : '',
    music_url: (info.music && info.music.playUrl) ? (info.music.playUrl.uri || '') : '',
    is_original_music: info.music ? info.music.isOriginalMusic : null,
  };
}
"""


async def extract_one(page, vid: str) -> dict:
    """访问一条视频详情页, 先拦 API, 失败则 React Props 降级。"""
    detail = None
    handler = None

    def make_handler(holder):
        async def h(response):
            if "/aweme/v1/web/aweme/detail" in response.url:
                try:
                    body = await response.json()
                    if body and body.get("aweme_detail"):
                        holder["d"] = body["aweme_detail"]
                except Exception:
                    pass
        return h

    holder = {}
    handler = make_handler(holder)
    page.on("response", handler)
    try:
        await page.goto(f"https://www.douyin.com/video/{vid}",
                        wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(PAGE_WAIT_MS / 1000)
        if holder.get("d") is None:
            await asyncio.sleep(EXTRA_WAIT_MS / 1000)
    except Exception:
        pass
    finally:
        page.off("response", handler)

    detail = holder.get("d")

    if detail is None:
        # 降级: React Props 同页内存挖掘(零额外请求, 不加重风控)
        try:
            rp = await page.evaluate(REACT_PROPS_JS)
        except Exception:
            rp = None
        if rp:
            return {
                "id": vid, "status": "ok", "via": "react_props",
                "title": (rp.get("desc") or "").split("#")[0].strip(),
                "desc": rp.get("desc") or "",
                "duration": int(rp.get("duration") or 0),
                "create_date": "",
                "digg": None, "collect": None,
                "chapter_abstract": "", "chapters": [],
                "play_url": rp.get("video_url") or "",
                "music": {"url": rp.get("music_url") or "",
                          "is_original": rp.get("is_original_music")},
            }
        return {"id": vid, "status": "failed"}

    bit_rates = (detail.get("video") or {}).get("bit_rate") or []
    play_url = None
    # 选最低画质(转写只需音频): adapt_low / low_540 / lower_540, 否则最后一个 mp4
    for br in bit_rates:
        if br.get("format") == "mp4":
            gear = br.get("gear_name") or ""
            if any(k in gear for k in ("adapt_low", "low_540", "lower_540")):
                urls = ((br.get("play_addr") or {}).get("url_list") or [])
                if urls:
                    play_url = urls[0]
                    break
    if not play_url:
        for br in reversed(bit_rates):
            if br.get("format") == "mp4":
                urls = ((br.get("play_addr") or {}).get("url_list") or [])
                if urls:
                    play_url = urls[0]
                    break

    music = detail.get("music") or {}
    music_urls = (music.get("play_url") or {}).get("url_list") or []
    stats = detail.get("statistics") or {}
    ct = detail.get("create_time")

    return {
        "id": vid, "status": "ok", "via": "api",
        "title": (detail.get("desc") or "").split("#")[0].strip(),
        "desc": detail.get("desc") or "",
        "duration": detail.get("duration") or 0,
        "create_date": time.strftime("%Y-%m-%d", time.gmtime(ct)) if ct else "",
        "digg": stats.get("digg_count"), "collect": stats.get("collect_count"),
        "chapter_abstract": detail.get("chapter_abstract") or "",
        "chapters": [
            {"title": c.get("desc") or "", "detail": c.get("detail") or "",
             "ts": c.get("timestamp") or 0}
            for c in (detail.get("chapter_list") or [])
        ],
        "play_url": play_url,
        "music": {"url": (music.get("play_url") or {}).get("uri")
                  or (music_urls[0] if music_urls else ""),
                  "is_original": music.get("is_original_music")},
    }


async def download_one(context, rec: dict, use_audio: bool) -> str:
    """用浏览器上下文的 request(自动携带登录 Cookie)下载, 绕过 CDN 防盗链。"""
    url = rec["music"]["url"] if (use_audio and rec.get("music", {}).get("url")) \
        else rec.get("play_url")
    if not url:
        return "no_url"
    ext = ".m4a" if use_audio else ".mp4"
    out = os.path.join(VIDEOS_DIR, rec["id"] + ext)
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        return "exists"
    try:
        resp = await context.request.get(url, timeout=120000,
                                         headers={"Referer": "https://www.douyin.com/"})
        if resp.ok:
            body = await resp.body()
            if len(body) > 10000:
                with open(out, "wb") as f:
                    f.write(body)
                return "ok"
        return f"http_{resp.status}"
    except Exception as e:
        return f"err:{type(e).__name__}"


async def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ids-file", help="extract_account.py 的输出 JSON")
    g.add_argument("--ids", help="逗号分隔的视频 ID 列表")
    ap.add_argument("--no-download", action="store_true",
                    help="只提取元数据, 不下载视频")
    ap.add_argument("--audio-first", action="store_true", default=True,
                    help="原声视频优先下载音频流(小一个量级), 默认开启")
    args = ap.parse_args()

    ids = load_ids(args)
    progress = load_progress()
    todo = [i for i in ids if not (progress.get(i, {}).get("status") == "ok")]
    print(f"[*] 共 {len(ids)} 条, 已完成 {len(ids)-len(todo)}, 待处理 {len(todo)}")
    if not todo:
        print("[+] 全部已完成。结果在", PROGRESS_FILE)
        return

    os.makedirs(VIDEOS_DIR, exist_ok=True)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        cookies = await context.cookies()
        if not any(c["name"] == "sessionid" for c in cookies):
            print("[x] 无登录态。先运行 extract_account.py 完成扫码登录。")
            await context.close()
            sys.exit(1)

        batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
        for bi, batch in enumerate(batches, 1):
            print(f"\n=== 第 {bi}/{len(batches)} 批 ({len(batch)} 条) ===")
            failed = []
            for n, vid in enumerate(batch, 1):
                rec = await extract_one(page, vid)
                progress[vid] = rec
                save_progress(progress)
                dl = ""
                if rec["status"] == "ok" and not args.no_download:
                    # 音频流优先: 原声(is_original=1)口播视频直接下音频, 体积小一个量级
                    use_audio = args.audio_first and rec["music"].get("is_original") == 1
                    dl = " | dl:" + await download_one(context, rec, use_audio)
                    if dl.endswith(("http_403", "http_000", "err:", "no_url")) \
                            and not use_audio:
                        pass
                tag = rec.get("via", "")
                ch = len(rec.get("chapters") or [])
                print(f"[{n}/{len(batch)}] {vid} {rec['status']}"
                      f"{'('+tag+')' if tag else ''} 章节:{ch}{dl}")
                if rec["status"] != "ok":
                    failed.append(vid)
                await asyncio.sleep(1.5)

            # 批内失败重试(慢速)
            if failed:
                print(f"[>] {len(failed)} 条失败, 慢速重试...")
                await asyncio.sleep(RETRY_PAUSE_SEC * 3)
                for vid in failed:
                    await asyncio.sleep(RETRY_PAUSE_SEC)
                    rec = await extract_one(page, vid)
                    progress[vid] = rec
                    save_progress(progress)
                    print(f"[retry] {vid} → {rec['status']}")

            if bi < len(batches):
                print(f"[…] 批间暂停 {BATCH_PAUSE_SEC}s (风控缓冲)")
                await asyncio.sleep(BATCH_PAUSE_SEC)

        await context.close()

    ok = sum(1 for v in progress.values() if v.get("status") == "ok")
    print(f"\n[+] 完成: {ok} ok / {len(progress)} total → {PROGRESS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
