"""Dynamic-menu browser acceptance against the plugin routes and simulated QQ."""

from playwright.async_api import expect

from orderui.dynamic_sender import DynamicMenuSender
from orderui.errors import OrderUIError


async def check_dynamic(page, frame, service, qq, idle, capture):
    before = len(qq.calls)
    await frame.get_by_role("button", name="动态指令菜单", exact=True).click()
    await idle()
    await frame.get_by_role("button", name="＋ 新建菜单", exact=True).click()
    await idle()
    await frame.get_by_label("菜单名称", exact=True).fill("工具箱")
    await frame.get_by_role("button", name="＋ 新增按钮行", exact=True).click()
    await frame.get_by_label("按钮名称", exact=True).fill("帮助")
    await frame.get_by_role("button", name="从 AstrBot 导入指令", exact=True).click()
    await frame.locator(".dynamic-command-list button").first.click()
    await frame.locator("#dialog").get_by_role("button", name="导入", exact=True).click()
    await idle()
    await expect(frame.get_by_label("对应指令（含前缀和参数）")).to_have_value("/help")
    await frame.get_by_role("button", name="保存草稿", exact=True).click()
    await idle()
    assert not service.match("a", "group", "/工具箱")
    first = (await service.get("a"))["draft"]["document"]["menus"][0]["id"]

    await frame.get_by_role("button", name="＋ 新建菜单", exact=True).click()
    await idle()
    await frame.get_by_label("菜单名称", exact=True).fill("娱乐")
    await frame.get_by_label("完整入口指令").fill("/娱乐")
    await frame.get_by_label("回复标题").fill("娱乐功能")
    await frame.get_by_role("button", name="＋ 新增按钮行", exact=True).click()
    await frame.get_by_label("按钮名称", exact=True).fill("返回")
    await frame.get_by_label("按钮动作").select_option("menu")
    await frame.get_by_label("目标菜单").select_option(first)
    await frame.get_by_role("button", name="保存草稿", exact=True).click()
    await idle()
    second = (await service.get("a"))["draft"]["document"]["menus"][1]["id"]
    await frame.locator("#dynamic-list button").first.click()
    await idle()
    await frame.get_by_role("button", name="＋ 添加按钮", exact=True).click()
    block = frame.locator(".dynamic-button-editor").nth(1)
    await block.get_by_label("按钮名称", exact=True).fill("娱乐")
    await block.get_by_label("按钮动作").select_option("menu")
    await block.get_by_label("目标菜单").select_option(second)
    await block.get_by_label("单聊点击后自动发送").check()

    async def apply():
        await frame.get_by_role("button", name="保存并应用", exact=True).click()
        await frame.locator("#dialog").get_by_role("button", name="保存并应用", exact=True).click()
        await idle()
        await expect(frame.locator("#notice")).to_contain_text("动态菜单已应用")

    await apply()
    assert len(qq.calls) == before, "Editing and applying must not call QQ"
    await frame.locator(".dynamic-row").first.evaluate("""row => {
        const buttons = row.querySelectorAll('.dynamic-button-editor');
        const transfer = new DataTransfer();
        buttons[1].dispatchEvent(new DragEvent('dragstart', {dataTransfer:transfer, bubbles:true}));
        buttons[0].dispatchEvent(new DragEvent('drop', {dataTransfer:transfer, bubbles:true}));
    }""")
    await expect(frame.get_by_label("按钮名称", exact=True).first).to_have_value("娱乐")
    await (
        frame.locator(".dynamic-button-editor")
        .first.get_by_role("button", name="右移", exact=True)
        .click()
    )
    await expect(frame.get_by_label("按钮名称", exact=True).first).to_have_value("帮助")
    preview = frame.locator("#dynamic-preview")
    await preview.get_by_role("button", name="娱乐", exact=True).click()
    await expect(frame.locator("#dynamic-preview-input")).to_have_value("/娱乐")
    await preview.get_by_role("button", name="模拟发送并打开菜单").click()
    await expect(preview.locator(".dynamic-chat-title")).to_have_text("娱乐功能")
    await preview.get_by_role("button", name="返回", exact=True).click()
    await preview.get_by_role("button", name="模拟发送并打开菜单").click()
    await expect(preview.locator(".dynamic-chat-title")).to_have_text("请选择功能")
    await preview.locator("select").select_option("c2c")
    await preview.get_by_role("button", name="娱乐", exact=True).click()
    await expect(preview.locator(".dynamic-chat-title")).to_have_text("娱乐功能")

    sender = DynamicMenuSender(qq, service)

    async def receive(command, message_id):
        match = service.match("a", "group", command)
        assert match
        await sender.send(("a", "secret"), "group", "group-real", message_id, match[1], match[2])

    await receive("/工具箱", "first")
    assert (
        qq.messages[-1][2]["keyboard"]["content"]["rows"][0]["buttons"][1]["action"]["enter"]
        is False
    )
    await frame.get_by_label("完整入口指令").fill("/新工具")
    await apply()
    assert not service.match("a", "group", "/工具箱")
    await receive("/娱乐", "second")
    assert (
        qq.messages[-1][2]["keyboard"]["content"]["rows"][0]["buttons"][0]["action"]["data"]
        == "/新工具"
    )

    def deny_keyboard(method, path, body, phase):
        if phase == "before" and body and "keyboard" in body:
            raise OrderUIError("无自定义按钮权限", "upstream", trace_id="fixture-trace")

    qq.hook = deny_keyboard
    await receive("/新工具", "third")
    qq.hook = lambda *args: None
    assert service.status["a"]["result"] == "text_fallback"
    assert qq.messages[-1][2]["msg_type"] == 0
    await frame.get_by_role("button", name="载入已应用配置").click()
    await frame.locator("#dialog").get_by_role("button", name="确认", exact=True).click()
    await idle()
    await expect(frame.locator("#app")).to_contain_text("已退回文字菜单")
    await expect(frame.locator("#app")).to_contain_text("fixture-trace")
    await frame.get_by_label("消息格式", exact=True).select_option("text")
    await apply()
    await receive("/新工具", "text-format")
    body = qq.messages[-1][2]
    assert body["msg_type"] == 0 and body["content"] == "请选择功能"
    assert "keyboard" in body and "markdown" not in body
    await frame.get_by_role("button", name="载入已应用配置").click()
    await frame.locator("#dialog").get_by_role("button", name="确认", exact=True).click()
    await idle()
    await expect(frame.get_by_label("消息格式", exact=True)).to_have_value("text")
    await frame.locator("summary").filter(has_text="最近请求正文").click()
    await expect(frame.locator(".dynamic-request-body")).to_contain_text('"msg_type": 0')
    await expect(frame.locator(".dynamic-request-body")).to_contain_text('"content": "请选择功能"')
    await capture("qq-dynamic-light.png")
    await page.evaluate("setTheme(true)")
    await capture("qq-dynamic-dark.png")
    await page.set_viewport_size({"width": 390, "height": 900})
    await capture("qq-dynamic-mobile.png")
    assert await frame.locator("html").evaluate("e => e.scrollWidth <= innerWidth")
    await page.set_viewport_size({"width": 1440, "height": 1050})
    await page.evaluate("setTheme(false)")

    # Discard/cancel choices must keep the active catalogue and unrelated robots intact.
    await frame.get_by_label("菜单名称", exact=True).fill("未保存")
    await frame.get_by_label("当前机器人").select_option("b")
    await frame.locator("#dialog").get_by_role("button", name="取消", exact=True).click()
    await idle()
    await expect(frame.get_by_label("菜单名称", exact=True)).to_have_value("未保存")
    await frame.get_by_label("当前机器人").select_option("b")
    await frame.locator("#dialog").get_by_role("button", name="放弃编辑", exact=True).click()
    await idle()
    await expect(frame.locator("#dynamic-list button")).to_have_count(0)
    await frame.get_by_label("当前机器人").select_option("a")
    await idle()
    await expect(frame.get_by_label("完整入口指令")).to_have_value("/新工具")

    # Independent tab loading still works when QQ configuration reads fail.
    qq.hook = lambda *args: (_ for _ in ()).throw(OrderUIError("QQ unavailable", "network"))
    await page.reload()
    await idle()
    await frame.get_by_role("button", name="动态指令菜单", exact=True).click()
    await idle()
    await expect(frame.get_by_label("完整入口指令")).to_have_value("/新工具")
    qq.hook = lambda *args: None
