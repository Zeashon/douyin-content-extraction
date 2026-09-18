#!/usr/bin/env python3
"""
extract_account.py — 提取抖音账号主页的全部作品列表（标题/点赞/类型/ID/链接）

用法:
    python scripts/extract_account.py <主页URL或sec_uid> [--out output/account_videos.json] [--excel]

示例:
    python scripts/extract_account.py https://www.douyin.com/user/MS4wLjABAAAAxxxx
    python scripts/extract_account.py MS4wLjABAAAAxxxx

首次运行会打开浏览器窗口，请在 120 秒内用抖音 App 扫码登录；
登录态保存在 .browser_profile/，之后无需重复登录。

产物: output/account_videos.json（全部作品的 ID/标题/点赞/置顶/类型/链接）
      output/account_videos.xlsx（可选，--excel 开启）
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

LOGIN_WAIT_SECONDS = 120  # 首次登录最长等待扫码时间


def normalize_target(target: str) -> str:
    if target.startswith("http"):
        return target
    return f"https://www.douyin.com/user/{target}"


async def wait_for_login(page) -> bool:
    """轮询 cookie 中的 sessionid 判断是否已登录。"""
    deadline = time.time() + LOGIN_WAIT_SECONDS
    while time.time() < deadline:
        cookies = await page.context.cookies()
        if any(c["name"] == "sessionid" for c in cookies):
            return True
        await asyncio.sleep(3)
    return False


# ---- 页面内脚本 ----------------------------------------------------------

SCROLL_LOAD_JS = """
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  // 关键陷阱: 抖音网页端是内嵌滚动容器, window.scrollTo() 无效
  const container = document.querySelector('.route-scroll-container');
  if (!container) return { error: 'scroll container not found' };
  let lastCount = 0, stable = 0;
  const items = [];
  const seen = new Set();
  for (let i = 0; i < 100; i++) {
    container.scrollTop = container.scrollHeight;
    await sleep(1200);
    const links = container.querySelectorAll('a[href*="/video/"], a[href*="/note/"]');
    links.forEach(a => {
      const href = a.getAttribute('href');
      if (!seen.has(href)) { seen.add(href); items.push(href); }
    });
    if (seen.size === lastCount) {
      stable++;
      if (stable >= 5) break;   // 连续 5 轮无增长 → 到底了
    } else { stable = 0; }
    lastCount = seen.size;
  }
  return { count: seen.size };
}
"""

EXTRACT_ITEMS_JS = """
() => {
  // 作品列表在 .route-scroll-container 内最大的 ul 中
  const uls = document.querySelectorAll('.route-scroll-container ul');
  let ul = null;
  let best = 0;
  for (const u of uls) {
    if (u.children.length > best) { best = u.children.length; ul = u; }
  }
  if (!ul) return [];
  const items = [];
  ul.querySelectorAll('li').forEach(li => {
    const a = li.querySelector('a[href*="/video/"], a[href*="/note/"]');
    if (!a) return;
    const href = a.getAttribute('href');
    const raw = (a.getAttribute('aria-label') || a.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!raw) return;
    const isPinned = raw.startsWith('置顶') || raw.startsWith('共创');
    let rest = isPinned ? raw.replace(/^(置顶|共创)\\s*/, '') : raw;
    // 点赞数在开头, 如 "4.2万 xxx" / "3831 xxx"（共创视频可能没有）
    let likes = '', body = rest;
    const m = rest.match(/^([\\d.]+万?)\\s+(.*)$/);
    if (m) { likes = m[1]; body = m[2]; }
    const isNote = href.includes('/note/');
    items.push({
      href,
      id: href.split('/').pop().split('?')[0],
      pinned: isPinned,
      likes,
      text: body,
      type: isNote ? 'note' : 'video',
      url: (isNote ? 'https://www.douyin.com/note/' : 'https://www.douyin.com/video/')
            + href.split('/').pop().split('?')[0],
    });
  });
  return items;
}
"""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="主页 URL 或 sec_uid")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "account_videos.json"))
    ap.add_argument("--excel", action="store_true", help="同时导出 xlsx")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    url = normalize_target(args.target)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        cookies = await context.cookies()
        if not any(c["name"] == "sessionid" for c in cookies):
            print("[!] 未检测到登录态，请在打开的浏览器中用抖音 App 扫码登录 "
                  f"（{LOGIN_WAIT_SECONDS}s 内）...")
            ok = await wait_for_login(page)
            if not ok:
                print("[x] 登录超时，退出。重新运行即可继续。")
                await context.close()
                sys.exit(1)
            print("[+] 登录成功，登录态已保存，下次无需重复扫码。")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

        print("[*] 滚动加载全部作品（内嵌容器，连续 5 轮无新增则停止）...")
        r = await page.evaluate(SCROLL_LOAD_JS)
        if isinstance(r, dict) and r.get("error"):
            print("[x]", r["error"])
            await context.close()
            sys.exit(1)
        print(f"[+] 加载完成，共发现 {r['count']} 个链接")

        items = await page.evaluate(EXTRACT_ITEMS_JS)
        print(f"[+] 提取到 {len(items)} 条作品")

        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"[+] 已保存 {args.out}")

        if args.excel:
            try:
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.title = "作品列表"
                ws.append(["序号", "类型", "置顶/共创", "点赞数", "视频文案", "视频ID", "链接"])
                for i, it in enumerate(items, 1):
                    ws.append([i, "图文笔记" if it["type"] == "note" else "视频",
                               "是" if it["pinned"] else "",
                               it["likes"], it["text"], it["id"], it["url"]])
                xlsx = os.path.splitext(args.out)[0] + ".xlsx"
                wb.save(xlsx)
                print(f"[+] 已保存 {xlsx}")
            except ImportError:
                print("[!] 未安装 openpyxl，跳过 Excel 导出（pip install openpyxl）")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
