"""Browser acceptance using the real host SDK and a simulated QQ backend.

Run as a module: python -m tests.browser_check --astrbot-source D:/Projects/AstrBot
"""

import argparse
import asyncio
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

from tests.browser_dynamic import check_dynamic
from tests.fakes import menu
from tests.test_routes import fixture_app

ROOT = Path(__file__).resolve().parents[1]
HOST = """<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0"><iframe id="plugin" sandbox="allow-scripts allow-forms allow-downloads"
style="width:100%;height:100vh;border:0" src="/pages/manage/index.html"></iframe>
<script>
const frame = document.querySelector('iframe');
window.setTheme = dark => frame.contentWindow.postMessage({channel:'astrbot-plugin-page',kind:'context',
context:{pluginName:'astrbot_plugin_orderui',pageName:'manage',isDark:dark,locale:'zh-CN'}}, '*');
window.addEventListener('message', async event => {
  if(event.source !== frame.contentWindow || event.data?.channel !== 'astrbot-plugin-page') return;
  const m=event.data;
  if(m.kind === 'ready') {setTheme(false);return;}
  if(m.kind !== 'request') return;
  try {
    const base='/api/plug/astrbot_plugin_orderui/'+m.endpoint;
    const result=await fetch(m.action==='api:get'?base+'?'+new URLSearchParams(m.params||{}):base,
      {method:m.action==='api:get'?'GET':'POST',headers:{Authorization:'Bearer fixture','Content-Type':'application/json'},
       body:m.action==='api:get'?undefined:JSON.stringify(m.body)});
    if(!result.ok) throw Error('Unauthorized');
    const body=await result.json();
    frame.contentWindow.postMessage({channel:m.channel,kind:'response',requestId:m.requestId,ok:true,data:body.data},'*');
  } catch(e) {frame.contentWindow.postMessage({channel:m.channel,kind:'response',requestId:m.requestId,ok:false,error:e.message},'*');}
});
</script></body></html>"""


async def check(args):
    app, routes, _, qq, _ = fixture_app()
    qq.menus["a"] = {**menu(), "version": 1}
    sdk = (Path(args.astrbot_source) / "astrbot/dashboard/plugin_page_bridge.js").read_text(
        encoding="utf-8"
    )
    client = app.test_client()
    artifacts = ROOT / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    async with async_playwright() as p:
        options = {"headless": True}
        if args.browser:
            options["executable_path"] = args.browser
        browser = await p.chromium.launch(**options)
        page = await browser.new_page(
            viewport={"width": 1440, "height": 1050}, device_scale_factor=1
        )
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def serve(route):
            request = route.request
            parsed = urlsplit(request.url)
            path = parsed.path
            headers = {"Access-Control-Allow-Origin": "*"}
            if path == "/":
                await route.fulfill(body=HOST, content_type="text/html", headers=headers)
            elif path == "/bridge.js":
                await route.fulfill(
                    body=sdk, content_type="application/javascript", headers=headers
                )
            elif path.startswith("/api/"):
                response = await client.open(
                    path + ("?" + parsed.query if parsed.query else ""),
                    method=request.method,
                    headers=await request.all_headers(),
                    data=request.post_data,
                )
                await route.fulfill(
                    status=response.status_code,
                    body=await response.get_data(),
                    content_type="application/json",
                    headers=headers,
                )
            elif path.startswith("/pages/manage/"):
                filename = path.rsplit("/", 1)[-1]
                target = ROOT / "pages/manage" / filename
                if not target.is_file():
                    await route.fulfill(status=404)
                    return
                content = target.read_text(encoding="utf-8")
                if filename == "index.html":
                    content = content.replace(
                        '<script type="module"',
                        '<script src="/bridge.js"></script><script type="module"',
                    )
                content_type = (
                    "application/javascript"
                    if filename.endswith(".js")
                    else mimetypes.guess_type(filename)[0] or "text/plain"
                )
                await route.fulfill(body=content, content_type=content_type, headers=headers)
            else:
                await route.fulfill(status=404)

        await page.route("http://orderui.test/**", serve)
        await page.goto("http://orderui.test/")
        frame = page.frame_locator("#plugin")

        async def idle():
            await expect(frame.locator("#app")).to_have_attribute("aria-busy", "false")

        async def publish():
            await frame.get_by_role("button", name="发布到 QQ", exact=True).click()
            await frame.get_by_role("button", name="确认发布", exact=True).click()
            await idle()

        async def capture(filename):
            viewport = page.viewport_size
            height = await frame.locator("#app").evaluate(
                "e => Math.ceil(e.getBoundingClientRect().height)"
            )
            await page.set_viewport_size(
                {"width": viewport["width"], "height": max(height + 4, viewport["height"])}
            )
            await page.evaluate("window.scrollTo(0, 0)")
            await frame.locator("#app").evaluate(
                "e => new Promise(resolve => { window.scrollTo(0, 0); requestAnimationFrame(() => requestAnimationFrame(resolve)); })"
            )
            await page.screenshot(path=str(artifacts / filename), animations="disabled")
            await page.set_viewport_size(viewport)

        await expect(
            frame.get_by_role("heading", name="菜单与指令面板", exact=True)
        ).to_be_visible()
        await idle()
        assert not any(call[1] != "GET" for call in qq.calls)
        if args.dynamic_only:
            await check_dynamic(page, frame, routes.dynamic, qq, idle, capture)
            assert not errors, errors
            print(json.dumps({"dynamic_browser": "passed", "real_qq_calls": 0}))
            await browser.close()
            return
        await frame.get_by_label("显示名称").fill("使用帮助")
        await frame.get_by_role("button", name="＋ 新增", exact=True).click()
        await frame.get_by_label("按钮类型").select_option("link")
        await idle()
        await frame.get_by_label("显示名称").fill("官网")
        await frame.get_by_label("HTTPS 链接").fill("https://example.com")
        await frame.get_by_role("button", name="＋ 新增", exact=True).click()
        await frame.get_by_label("按钮类型").select_option("menu")
        await idle()
        await frame.get_by_label("显示名称").fill("更多服务")
        await frame.get_by_role("button", name="新增子菜单", exact=True).click()
        await frame.get_by_label("显示名称").fill("设置")
        await frame.get_by_label("填入聊天框的内容").fill("/settings")
        await frame.get_by_role("button", name="＋ 新增", exact=True).click()
        await frame.get_by_label("按钮类型").select_option("switch")
        await idle()
        await frame.get_by_label("显示名称").fill("联网搜索")
        await frame.get_by_label("开关标识").fill("search")
        await frame.get_by_label("默认打开").check()
        await frame.locator(".phone-menu button").last.click()
        await expect(frame.locator(".phone-input")).to_contain_text("关闭")
        await frame.get_by_role("button", name="保存草稿", exact=True).click()
        await idle()
        assert len(qq.menus["a"]["menu"]["items"]) == 1
        await page.reload()
        await idle()
        await expect(frame.locator(".item-row")).to_have_count(5)
        await frame.get_by_role("button", name="发布到 QQ", exact=True).click()
        await expect(frame.locator(".diff")).to_contain_text("联网搜索")
        await frame.get_by_role("button", name="确认发布", exact=True).click()
        await idle()
        await expect(frame.locator("#notice")).to_contain_text("发布成功")
        assert len(qq.menus["a"]["menu"]["items"]) == 4
        await frame.locator(".item-select").first.click()
        await frame.get_by_role("button", name="导入指令", exact=True).click()
        await frame.locator(".command-row input[type=checkbox]").check()
        await frame.get_by_role("button", name="导入选中项", exact=True).click()
        await idle()
        await expect(frame.locator(".item-row")).to_have_count(6)
        await publish()
        assert qq.menus["a"]["menu"]["items"][-1]["send_message"] == "/help"
        await frame.get_by_role("button", name="恢复上次发布前", exact=True).click()
        await frame.get_by_role("button", name="确认", exact=True).click()
        await idle()
        await expect(frame.locator(".item-row")).to_have_count(5)
        assert len(qq.menus["a"]["menu"]["items"]) == 5
        await frame.get_by_role("button", name="载入远端", exact=True).click()
        await frame.get_by_role("button", name="载入", exact=True).click()
        await idle()
        await expect(frame.locator(".item-row")).to_have_count(6)
        await frame.locator("#items").evaluate("""list => {
            const rows = list.querySelectorAll('.item-row:not(.child)');
            const transfer = new DataTransfer();
            rows[0].dispatchEvent(new DragEvent('dragstart', {dataTransfer: transfer, bubbles: true}));
            rows[1].dispatchEvent(new DragEvent('drop', {dataTransfer: transfer, bubbles: true}));
        }""")
        await expect(frame.locator(".item-select").first).to_contain_text("官网")
        await frame.locator(".item-row.selected .item-tools button").first.click()
        await expect(frame.locator(".item-select").first).to_contain_text("使用帮助")
        await capture("qq-menu-light.png")
        await page.evaluate("setTheme(true)")
        await expect(frame.locator("html")).to_have_attribute("data-theme", "dark")
        await capture("qq-menu-dark.png")
        await page.set_viewport_size({"width": 390, "height": 900})
        await capture("qq-menu-mobile.png")
        assert await frame.locator("html").evaluate("e => e.scrollWidth <= innerWidth"), (
            "Mobile horizontal overflow"
        )
        await page.set_viewport_size({"width": 1440, "height": 1050})
        await page.evaluate("setTheme(false)")

        # A remote edit must block publication without losing local input.
        await frame.get_by_label("显示名称").fill("新的帮助")
        qq.menus["a"]["version"] += 1
        qq.menus["a"]["menu"]["items"][0]["name"] = "远端帮助"
        await publish()
        await expect(frame.locator("#notice")).to_contain_text("远端配置已变化")
        await expect(frame.get_by_label("显示名称")).to_have_value("新的帮助")
        await frame.get_by_role("button", name="载入远端", exact=True).click()
        await frame.get_by_role("button", name="载入", exact=True).click()
        await idle()
        await expect(frame.get_by_label("显示名称")).to_have_value("远端帮助")

        # Creating and editing a targeted panel uses the same service and bridge.
        await frame.get_by_role("button", name="指令面板", exact=True).click()
        await idle()
        await frame.get_by_label("使用场景").select_option("group")
        await idle()
        await frame.get_by_label("作用范围").select_option("specific")
        await frame.get_by_label("群 OpenID").fill("\n".join(f"g{i}" for i in range(25)))
        await frame.get_by_label("面板备注").fill("群成员常用指令")
        await frame.get_by_role("button", name="导入指令", exact=True).click()
        await frame.locator(".command-row input[type=checkbox]").check()
        await frame.get_by_role("button", name="导入选中项", exact=True).click()
        await idle()
        await publish()
        await expect(frame.locator("#notice")).to_contain_text("发布成功")
        assert len(qq.panels[("a", "p1")]["group_openids"]) == 25
        await expect(frame.get_by_label("作用范围")).to_be_disabled()
        await capture("qq-panel-light.png")
        await frame.get_by_role("button", name="删除远端面板", exact=True).click()
        await frame.get_by_role("button", name="确认删除", exact=True).click()
        await idle()
        assert not qq.panels

        # Unsaved bot switching offers save/discard and stays isolated.
        await frame.get_by_role("button", name="单聊菜单", exact=True).click()
        await idle()
        await frame.get_by_label("显示名称").fill("切换草稿")
        await frame.get_by_label("当前机器人").select_option("b")
        await expect(frame.locator("#dialog-title")).to_have_text("有尚未保存的编辑")
        await frame.locator("#dialog").get_by_role("button", name="保存草稿", exact=True).click()
        await idle()
        await expect(frame.locator(".item-row")).to_have_count(0)
        await frame.get_by_label("当前机器人").select_option("a")
        await idle()
        await expect(frame.get_by_label("显示名称")).to_have_value("切换草稿")
        await check_dynamic(page, frame, routes.dynamic, qq, idle, capture)
        assert not errors, errors
        print(
            json.dumps(
                {
                    "browser": "passed",
                    "screenshots": str(artifacts),
                    "qq_writes": sum(c[1] != "GET" for c in qq.calls),
                    "real_qq_calls": 0,
                },
                ensure_ascii=False,
            )
        )
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--astrbot-source", required=True)
    parser.add_argument("--browser")
    parser.add_argument("--dynamic-only", action="store_true")
    asyncio.run(check(parser.parse_args()))
