# QQ 菜单与指令面板管理

在 AstrBot WebUI 中管理 QQ 官方机器人的单聊底部菜单和指令面板。提供可视化编辑、交互预览、草稿、发布差异、远端冲突检查和指令导入。启动插件不会自动修改 QQ 配置。

v1.1.0 新增**动态指令菜单**：在 WebUI 配置 `/工具箱` 等入口及其按钮，保存应用后即时生效。原有菜单、面板和草稿无需迁移。

v1.1.1 增加动态菜单的“文本＋按钮”格式，以及最近请求正文诊断。旧菜单保持 Markdown 格式。若 QQ 菜单顶部有留白，可在升级、重载插件并刷新管理页后，将“消息格式”改为“文本＋按钮”，标题改回 `请选择功能`（去掉 `##`），保存并应用，然后重新发送入口。此格式使用 `msg_type=0`、`content` 和 `keyboard`，避开 Markdown 排版；留白是否消除需在实际 QQ 客户端验证，不会更新已发送的消息。

## 安装与打开

需要 **AstrBot >=4.25.3,<5，且后端和 Dashboard 均支持 Plugin Pages**。本插件以提供的 AstrBot 4.25.3 源码为兼容基线；仅更新版本号而未更新 Dashboard 资源不能保证页面可用。

1. 在 AstrBot 中配置并启用至少一个 `qq_official` 平台，填好 AppID 和 Secret。
2. 在插件管理中上传本项目生成的 `astrbot_plugin_orderui.zip`，或将源码放到 AstrBot 的 `data/plugins/astrbot_plugin_orderui` 目录后重载插件。安装源码需包含隐藏目录 `.astrbot-plugin`。
3. 进入插件详情页，打开 **QQ 菜单与指令面板** 页面。
4. 选择机器人，编辑配置，先保存草稿，再通过“发布到 QQ”确认变更。

页面使用原生 HTML/CSS/ES Modules，不需要 npm 构建，也不启动额外端口。通过 AstrBot 的登录鉴权和 `AstrBotPluginPage` Bridge 请求后端。AppID/Secret 来自现有平台配置，无需再次填写，Secret 和访问令牌不会传给前端。

## 单聊菜单

- 一级菜单支持填入消息、HTTPS 链接、折叠菜单和开关；二级菜单支持填入消息和链接。
- 消息按钮分别设置名称和内容，例如名称“帮助”，内容 `/help`。QQ 点击行为是填入聊天框，用户确认发送后才执行。
- 支持复制、删除、同级拖拽、上下移动，以及模拟点击预览。预览不会发送 QQ 消息，也不会打开链接。
- 开关支持唯一标识和默认状态。业务插件仍需处理 QQ 消息携带的开关信息；本插件不会自动切换联网搜索、LLM 或其他 AstrBot 功能。
- 一级最多 10 项，每个折叠菜单最多 5 个子项。名称长度上限分别为 10、14；编辑器采用 ASCII 计 1、非 ASCII 计 2 的保守预算。其他 Unicode 边界及最终内容审核以 QQ 响应为准。
- 所有菜单发布都是覆盖完整配置，对该机器人全部单聊用户生效。`items: []` 会作为空菜单提交，但 QQ 是否隐藏入口及何时刷新需要真实客户端确认。

## 指令面板

支持单聊、群聊、文字子频道、频道私信四种场景；每机器人最多 20 个面板，每面板最多 20 项。

发布时至少添加一个指令或链接元素。空面板可以读取、编辑和保存草稿，但插件会拦截空面板发布，避免提交可能触发 QQ `40030016` 的空内容。要移除整个面板，请使用“删除面板”。

单聊和群聊支持指定对象，填写当前机器人获取的用户／群 OpenID，每行一个；系统去重后以每批最多 20 个提交。QQ 号、群号以及其他 AppID 下的 OpenID 不能代替。文字子频道和频道私信仅支持全局配置。

创建后的场景和作用范围不可直接修改，需新建面板。指令项的 `name` 本身就是填入聊天框的内容，上限为 14；描述上限为 30。`only_admin` 表示 QQ 群／频道管理员点击权限，不等于 AstrBot 管理员权限。

## 动态指令菜单

1. 打开“动态指令菜单”，选择机器人，点击“＋ 新建菜单”。
2. 填写名称、完整入口（例如 `/工具箱`）、可选别名、回复标题和说明，选择单聊／群聊场景。
3. 新增按钮行，编辑按钮名称、灰色／蓝色样式和动作：普通指令、另一个动态菜单或 HTTPS 链接。普通指令可从 AstrBot 导入，也可手工填写并预填参数。
4. “保存草稿”只保存编辑内容；“保存并应用”更新该机器人的全部动态菜单。新建、改名、启停、删除从下一条菜单消息起生效，无需重启。
5. 在 QQ 发送 `/工具箱`。机器人按所选消息格式返回 Markdown／文本和按钮；每次菜单跳转返回一条新的菜单消息。首次升级默认没有动态菜单。

“消息格式”默认 Markdown，支持 Markdown 标题、加粗等语法；选择文本格式后，标题和说明按原文发送，`##` 等标记也会成为普通文字。两种格式均保留按钮。发送后点击“载入已应用配置”，展开“最近请求正文”可查看 `msg_type`、正文和是否携带按钮；JSON 中的 `\n` 表示正文换行。该诊断只保留最近一次请求，不包含接收方或凭证；请求失败时也可查看尝试发送的正文。

最多配置 100 个动态菜单（插件本地限制），每个菜单最多 5 行、每行 5 个按钮。按钮名称最多 10 个 Unicode 字符；入口最多 64 个字符，不能包含空白或参数。菜单名称和入口可以不同；菜单间关联使用稳定 ID，目标改名后新消息自动使用新的入口。历史消息中的按钮不更新。

普通指令默认填入输入框，单聊可勾选“点击后自动发送”；群聊始终由用户确认发送。需要补充参数的指令请保留填入模式。按钮点击权限默认所有人，但目标指令仍经过 AstrBot 原有插件启停、会话配置及管理员权限检查。按钮不会直接调用其他插件函数。

入口与已注册的 AstrBot 指令／别名冲突时不能应用；后续其他插件新增冲突指令时，动态菜单会让已有指令处理，并在管理页提示。被停用的插件或会话不会运行动态菜单。若聊天配置使用不同唤醒前缀，运行时还会按该会话的前缀检查冲突。

配置按 AppID 隔离，同一 AppID 的不同平台配置共享菜单。草稿与应用版本独立保存；多个页面编辑时，旧版本应用会被阻止，草稿保留。可“载入已应用配置”核对，也可将“上次应用前”恢复到编辑区后重新应用。

QQ 明确返回无自定义按钮／Markdown 权限时，会退回一条文字菜单。管理页重新加载可查看最近发送结果、降级原因、错误码及 Trace ID；最近发送状态保存在内存，重启后清空。鉴权、内容审核、限流及网络错误不会被当作缺少按钮能力；发送超时结果不明时不重试，以免重复发送。重复来源消息在当前进程中保留最多一小时、最多 10000 条去重记录。

本页预览完全在本地运行。应用配置不会自动发送测试消息，也不会修改 QQ 原生指令面板；需要可点击入口时，通过“复制入口”将 `/工具箱` 加入现有指令面板草稿后人工发布。自定义按钮是否开放及客户端表现仍需实际机器人验证。

## 指令导入与发布

“导入指令”列出 AstrBot 指令、所属插件、描述、别名和权限。默认显示启用、无冲突的普通指令，可以展开其余项。选择折叠菜单或其子项时，导入菜单指令会添加到该折叠菜单。

唤醒前缀取 AstrBot 默认配置，可在导入窗口调整；不同会话的配置仍需人工核对。面板中的长指令需要选择有效短别名。本插件不修改 AstrBot 指令名称、别名或执行权限，也不会保证候选指令在每个会话都可执行。

草稿记录导入来源；打开及发布前检测指令消失、停用、改名、冲突和权限变化，提醒核对。确认后可以发布当前内容，不会自动同步 QQ 配置。

草稿、远端基线和上次发布前快照使用 AstrBot 插件 KV 存储，按 AppID 与资源隔离；同一个 AppID 的多个平台配置共用同一远端资源和发布锁。切换机器人或页签前提示处理未保存编辑。

- **保存草稿**：只保存本地数据，不调用 QQ 写接口。
- **载入远端**：用当前 QQ 配置替换编辑区及基线，已保存草稿直到再次保存才被覆盖。
- **恢复上次发布前**：将最近发布前的快照放入编辑区，仍需手动发布。
- **发布到 QQ**：展示差异，保存草稿，再回读远端检查冲突；冲突时保留草稿供核对。检查无法替代 QQ 服务端原子版本锁，检查与提交之间仍可能发生外部并发修改。

请求按 AppID 串行写入，并按各端点的 QQ 额度限制频率（菜单更新 5 QPM）。此限流只统计当前插件进程；其他进程、管理工具的请求仍可能触发 QQ 限流。

写请求超时不会盲目重试，而是回读核对。创建面板的结果无法唯一确认时，会持久化锁定新建操作；可用“恢复创建结果”继续核对。只有人工检查各场景列表后才应解除无面板 ID 的创建锁定。已返回面板 ID 的操作只能恢复，不能通过解除锁定重复创建。

关联对象部分失败时保留目标草稿和失败批次；再次发布会计算尚未完成的差异，不重复提交已确认成功的对象。错误提示包含可用的 QQ 错误码和 Trace ID。

## 开发与验证

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/model.test.mjs tests/dynamic-model.test.mjs
node --test tests/model.test.mjs
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

浏览器验收读取指定 AstrBot 源码中的真实 `plugin_page_bridge.js`，使用相同的受限 iframe 和模拟宿主、模拟 QQ 后端。不会调用真实 QQ API：

```powershell
.\.venv\Scripts\python.exe -m tests.browser_check --astrbot-source D:\Projects\AstrBot --browser "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

未指定 `--browser` 时使用 Playwright 的 Chromium，需预先运行 `python -m playwright install chromium`。截图输出到 `.artifacts/`。此验收覆盖菜单四类按钮、草稿刷新、指令导入、差异发布、冲突保留、指定群面板创建删除、多机器人切换和主题／窄屏布局；宿主完整 JWT 登录链路不在模拟测试范围内。

生成只包含运行文件的安装包：

```powershell
python scripts/package_plugin.py
```

输出 `.artifacts/astrbot_plugin_orderui.zip`，不包含虚拟环境、测试、草稿或凭证。

浏览器验收还覆盖动态菜单创建、指令导入、双菜单导航、单聊／群聊预览、应用后热更新、能力不足文字降级、多机器人隔离，以及 QQ 菜单查询失败时仍可打开动态菜单页签。

当前尚未指定真实测试机器人。部署后仍需在测试机器人上验证 API 权限、QQ 客户端展示与生效延迟、开关消息的 SDK 暴露方式、空菜单行为、多个面板的覆盖关系、动态按钮能力／群聊点击行为，以及部署版本的完整 Plugin Pages／登录流程。

## 接口与结构

后端接口通过宿主注册为插件相对路径，只能经登录后的 Dashboard 使用。页面始终通过 Bridge 调用；宿主可能使用 `/api/plug/astrbot_plugin_orderui/` 或新版 `/api/v1/plugins/extensions/astrbot_plugin_orderui/` 前缀。

| 方法 | 相对路径 | 用途 |
| --- | --- | --- |
| GET | `bots`、`commands` | 机器人列表与指令候选 |
| GET | `menu`、`panels`、`panel`、`draft` | 远端配置与本地草稿 |
| POST | `draft/save`、`menu/publish` | 保存草稿与发布菜单 |
| POST | `panels/create`、`panels/update`、`panels/delete` | 面板生命周期 |
| POST | `panels/targets` | 按完整目标配置核对并同步面板与关联对象 |
| POST | `panels/recover`、`panels/unlock` | 恢复不确定的新建操作或人工核对解锁 |
| GET | `dynamic-menus` | 已应用集合、版本、草稿、上次快照、冲突及最近发送状态 |
| POST | `dynamic-menus/draft` | 保存完整动态菜单草稿，携带 `platform_id`、`document`、`revision` |
| POST | `dynamic-menus/apply` | 校验并应用完整集合；版本冲突时保留草稿 |

请求通过 `platform_id` 选择平台。更新／删除需要读取响应中的 `baseline`。发布携带 `document` 和可选 `sources`；草稿另携带 `resource`（`menu`、`panel:<id>` 或 `new:<scope>`）。Bridge 数据封装为 `{ok, result}` 或 `{ok:false, error:{code,message,trace_id,details}}`，避免宿主丢弃业务错误的结构化信息。

`main.py` 处理插件生命周期和平台／指令发现；`orderui/` 分离字段校验、QQ HTTP 客户端、业务服务和路由；`pages/manage/` 保存编辑器与预览。测试和打包脚本均不依赖真实机器人凭证。

动态菜单 `document` 为 `{menus: [...]}`。菜单包含稳定 `id`、`name`、`trigger`、`aliases`、`enabled`、`scopes`、`message_format`、`title`、`description`、`rows`；`message_format` 为 `markdown`（缺省值）或 `text`，`rows` 是按钮二维数组。按钮包含 `id`、`label`、`style`、`type`、`enter`，以及按类型选择的 `command`、`menu_id` 或 `url`，导入指令还记录 `source`。配置保存在插件 KV 的 `orderui.dynamic.v1:<AppID>`，不会注册为 AstrBot 独立原生指令条目；入口由专用过滤器动态匹配。

QQ 契约参考：[自定义菜单与指令面板](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/menu-panel/)、[菜单修改](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_menu.put.html)、[访问凭证](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html)。

消息格式参考：[群聊消息接口](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html)。文本加按钮的布局和能力需使用实际机器人验证；本地模拟测试不代替 QQ 验收。
