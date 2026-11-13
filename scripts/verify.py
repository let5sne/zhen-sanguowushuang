#!/usr/bin/env python3
"""验收脚本：用本机 Chrome 真 GPU 跑一遍游戏，断言状态机、战斗、渲染指标。

用法：
    python3 scripts/verify.py            # 自动起本地静态服务器
    python3 scripts/verify.py --url ...  # 指定已运行的地址

依赖：playwright（pip install playwright）+ 本机 Chrome。
截图输出到 docs/screens/。
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMOS = os.path.join(ROOT, "demos")
SHOTS = os.path.join(ROOT, "docs", "screens")
CHROME_ARGS = ["--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required"]

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve():
    handler = partial(SimpleHTTPRequestHandler, directory=DEMOS)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}/index.html"


def main():
    os.makedirs(SHOTS, exist_ok=True)
    httpd = None
    url = None
    for i, a in enumerate(sys.argv):
        if a == "--url":
            url = sys.argv[i + 1]
    if not url:
        httpd, url = serve()

    from playwright.sync_api import sync_playwright

    errors, console_errors = [], []
    IGNORE = ("pointer lock", "favicon", "Failed to load resource")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=CHROME_ARGS)
        page = browser.new_page(viewport={"width": 1440, "height": 810})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error"
                and not any(k in m.text.lower() for k in IGNORE) else None)

        print("\n== 1. 载入 ==")
        page.goto(url, wait_until="load")
        page.wait_for_function("window.__ready===true", timeout=45000)
        check("页面可载入且模块执行完毕", True)
        check("无 JS 运行时错误", not errors, "; ".join(errors[:3]))
        check("无异常 console 报错", not console_errors, "; ".join(console_errors[:3]))

        gpu = page.evaluate("""() => {
            const c = document.createElement('canvas');
            const gl = c.getContext('webgl2') || c.getContext('webgl');
            const e = gl.getExtension('WEBGL_debug_renderer_info');
            return gl.getParameter(e.UNMASKED_RENDERER_WEBGL);
        }""")
        soft = any(k in gpu.lower() for k in ("swiftshader", "llvmpipe", "software"))
        check("WebGL 运行在真 GPU", not soft, gpu)

        page.wait_for_timeout(1200)
        page.screenshot(path=os.path.join(SHOTS, "title.jpg"), quality=82, type="jpeg")

        print("\n== 2. 开局 ==")
        page.evaluate("__dbg.start()")
        page.wait_for_timeout(3500)
        st = page.evaluate("__dbg.st()")
        check("进入战斗状态", st["state"] == "play", json.dumps(st, ensure_ascii=False))
        check("杂兵已列阵（默认同屏 60 人规模）", st["enemies"] >= 50, f'{st["enemies"]} 人')
        check("华雄已出阵", bool(st["boss"]) and st["boss"]["n"] == "华雄")

        print("\n== 3. 战斗 ==")
        page.evaluate("""() => {
            const d = __dbg;
            d.E.forEach(s => { s.active = false; });
            d.player.pos.set(0, 0, 0); d.player.yaw = Math.PI; d.player.hp = d.player.maxhp;
            d.E.forEach((s, i) => {
                if (i >= 6) return;
                s.active = true; s.wasActive = true; s.type = 'dao'; s.dead = false;
                s.pos.set(-2.5 + i, 0, -2.6); s.hp = s.maxhp = 30;
                s.state = 'chase'; s.t = 0; s.cool = 99; s.scale = 1; s.tilt = 0;
                s.tint.set(0x8a5a3a);
            });
        }""")
        page.wait_for_timeout(200)
        before = page.evaluate("__dbg.st().ko")
        page.evaluate("__dbg.attack(0)")
        page.wait_for_timeout(800)
        page.evaluate("__dbg.attack(2)")
        page.wait_for_timeout(900)
        after = page.evaluate("__dbg.st()")
        check("挥击能命中并击破", after["ko"] > before, f'KO {before} → {after["ko"]}')
        check("连击数累计", after["combo"] > 0, f'combo={after["combo"]}')
        check("无双槽随命中增长", after["musou"] > 0, f'musou={after["musou"]}')
        page.screenshot(path=os.path.join(SHOTS, "combat.jpg"), quality=82, type="jpeg")

        print("\n== 4. 无双乱舞 ==")
        page.evaluate("""() => {
            const d = __dbg;
            for (let i = 0; i < 12; i++) {
                const a = i / 12 * Math.PI * 2, r = 3.2;
                const s = d.E.filter(e => !e.active)[0];
                if (!s) break;
                s.active = true; s.wasActive = true; s.type = 'dao'; s.dead = false;
                s.pos.set(d.player.pos.x + Math.cos(a) * r, 0, d.player.pos.z + Math.sin(a) * r);
                s.hp = s.maxhp = 30; s.state = 'chase'; s.t = 0; s.cool = 99;
                s.scale = 1; s.tilt = 0; s.tint.set(0x8a5a3a);
            }
        }""")
        page.wait_for_timeout(150)
        page.evaluate("__dbg.musou()")
        page.wait_for_timeout(900)
        mid = page.evaluate("__dbg.st()")
        check("无双进入后开始割草", mid["ko"] > after["ko"], f'KO {after["ko"]} → {mid["ko"]}')
        page.wait_for_timeout(2600)
        page.screenshot(path=os.path.join(SHOTS, "musou.jpg"), quality=82, type="jpeg")
        check("无双结束后回到可操作状态", page.evaluate("__dbg.st().state") in ("play", "idle"))

        print("\n== 5. 性能与渲染 ==")
        page.evaluate("__dbg.spawn(60)")
        page.wait_for_timeout(1500)
        info = page.evaluate("__dbg.info()")
        st = page.evaluate("__dbg.st()")
        check("60+ 同屏时帧率 ≥ 45", info["fps"] >= 45,
              f'{info["fps"]}fps / {info["calls"]} draw / {info["tris"]} tris / 单位 {st["enemies"]}')
        lum = page.evaluate("__dbg.lum()")
        check("画面亮度正常（不过曝 / 不死黑）", 0.05 < lum["mean"] < 0.92 and lum["clipped"] < 5.0,
              f'mean={lum["mean"]} clipped={lum["clipped"]}% black={lum["nearBlack"]}%')

        print("\n== 6. 关卡流程 ==")
        page.evaluate("__dbg.killBoss()")
        page.wait_for_timeout(3600)
        st = page.evaluate("__dbg.st()")
        check("华雄讨取后吕布登场", bool(st["boss"]) and st["boss"]["n"] == "吕布",
              json.dumps(st["boss"], ensure_ascii=False))
        page.screenshot(path=os.path.join(SHOTS, "boss2.jpg"), quality=82, type="jpeg")
        page.evaluate("__dbg.killBoss()")
        page.wait_for_timeout(2600)
        st = page.evaluate("__dbg.st()")
        check("吕布讨取后进入结算", st["state"] == "result", st["state"])
        page.screenshot(path=os.path.join(SHOTS, "result.jpg"), quality=82, type="jpeg")

        print("\n== 7. 重开 ==")
        page.evaluate("__dbg.start()")
        page.wait_for_timeout(1200)
        st = page.evaluate("__dbg.st()")
        check("可以重开一局", st["state"] == "play" and st["ko"] == 0 and st["hp"] == st["hp"])

        check("全程无 JS 运行时错误", not errors, "; ".join(errors[:3]))

        browser.close()
    if httpd:
        httpd.shutdown()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'=' * 52}\n验收结果：{passed}/{total} 通过\n{'=' * 52}")
    if passed != total:
        for n, ok, d in results:
            if not ok:
                print(f"  FAIL  {n}  {d}")
        sys.exit(1)


if __name__ == "__main__":
    main()