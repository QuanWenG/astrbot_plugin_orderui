import { clone } from "./model.js";
import {
  newMenu,
  newButton,
  copyMenu,
  validateDynamic,
  moveButton,
} from "./dynamic-model.js";

export class DynamicEditor {
  constructor(host) {
    Object.assign(this, host);
    this.document = null;
    this.saved = "";
    this.selected = null;
    this.previewId = null;
    this.previewText = "";
    this.scene = "group";
  }
  dirty() {
    return this.document && JSON.stringify(this.document) !== this.saved;
  }
  current() {
    return this.document?.menus.find((m) => m.id === this.selected);
  }
  accept(result, restore = true) {
    this.remote = clone(result.document);
    this.backup = result.backup;
    this.document = clone(
      restore && result.draft ? result.draft.document : result.document,
    );
    this.revision =
      restore && result.draft ? result.draft.revision : result.revision;
    this.saved = JSON.stringify(this.document);
    this.selected = this.document.menus[0]?.id || null;
    this.previewId = this.selected;
    this.previewText = "";
    this.pendingPreview = null;
    this.warnings = result.warnings || [];
    this.status = result.status;
    if (this.revision !== result.revision)
      this.warnings.push("草稿版本已过期，请载入已应用配置后核对。");
  }
  async load(restore = true) {
    this.accept(await this.api("dynamic-menus"), restore);
  }
  async save() {
    await this.api("dynamic-menus/draft", {
      document: this.document,
      revision: this.revision,
    });
    this.saved = JSON.stringify(this.document);
    this.notify("动态菜单草稿已保存，尚未应用。");
  }
  async apply() {
    const errors = validateDynamic(this.document);
    if (errors.length) {
      this.notify(errors.join("\n"), true);
      return;
    }
    if (
      !(await this.confirm(
        "应用动态菜单",
        "将应用当前机器人全部动态菜单，包括入口变更、启停和删除。下一条菜单请求起生效。",
        "保存并应用",
      ))
    )
      return;
    await this.save();
    this.accept(
      await this.api("dynamic-menus/apply", {
        document: this.document,
        revision: this.revision,
      }),
    );
    this.notify("动态菜单已应用。无需重启；QQ 原生菜单和面板未更改。");
  }
  changed() {
    const status = document.querySelector("#dynamic-save-status");
    if (status)
      status.textContent = this.dirty() ? "有未保存的编辑" : "草稿已保存";
    const errors = validateDynamic(this.document),
      box = document.querySelector("#dynamic-validation");
    if (box) {
      box.textContent = errors.join(" · ");
      box.hidden = !errors.length;
    }
    this.drawPreview();
    this.drawList();
  }
  async selectMenu(id) {
    if (!(await this.leave())) return;
    // A discard choice reloads the last locally saved catalogue before changing selection.
    if (this.dirty()) this.document = JSON.parse(this.saved);
    this.selected = this.document.menus.some((m) => m.id === id)
      ? id
      : this.document.menus[0]?.id;
    this.previewId = this.selected;
    this.previewText = "";
  }
  render(root) {
    const { el, btn, hint } = this;
    if (!this.document) {
      root.append(btn("加载动态菜单", () => this.run(() => this.load())));
      return;
    }
    root.append(
      el(
        "div",
        { class: "toolbar" },
        el("span", {
          id: "dynamic-save-status",
          class: "status-pill",
          text: this.dirty() ? "有未保存的编辑" : "草稿已保存",
        }),
        el(
          "div",
          { class: "actions" },
          btn("保存草稿", () => this.run(() => this.save())),
          btn("载入已应用配置", () =>
            this.run(async () => {
              if (
                await this.confirm(
                  "载入已应用配置",
                  "替换当前编辑内容，已保存草稿仍保留。",
                )
              )
                await this.load(false);
            }),
          ),
          btn(
            "恢复上次应用前",
            () =>
              this.run(async () => {
                if (
                  await this.confirm(
                    "恢复为草稿",
                    "替换编辑区内容，重新应用后才生效。",
                  )
                ) {
                  this.document = clone(this.backup);
                  this.selected = this.document.menus[0]?.id;
                  this.previewId = this.selected;
                }
              }),
            "",
            !this.backup,
          ),
          btn("保存并应用", () => this.run(() => this.apply()), "primary"),
        ),
      ),
    );
    root.append(
      hint(
        "本页配置动态消息菜单。群聊按钮填入指令后需确认发送；单聊可开启自动发送。历史消息中的按钮不会自动更新。",
      ),
    );
    if (this.warnings?.length)
      root.append(
        el("div", { class: "notice", text: this.warnings.join("\n") }),
      );
    if (this.status) {
      const labels = {
        sent: "按钮菜单发送成功",
        text_fallback: "已退回文字菜单",
        failed: "菜单发送失败",
        conflict: "入口指令冲突",
      };
      const error = this.status.error || this.status.fallback_reason;
      root.append(
        el("div", {
          class: "notice",
          text: [
            labels[this.status.result],
            this.status.time,
            this.status.message,
            error?.message,
            error?.details?.qq_code && `QQ 错误码：${error.details.qq_code}`,
            error?.trace_id && `Trace ID：${error.trace_id}`,
          ]
            .filter(Boolean)
            .join("\n"),
        }),
      );
      if (this.status.request_body)
        root.append(
          el(
            "details",
            { class: "notice" },
            el("summary", { text: "最近请求正文（JSON，换行显示为 \\n）" }),
            hint(
              "msg_type 0 为文本，2 为 Markdown；has_keyboard 表示是否携带按钮。这里只展示正文，不包含接收方或凭证。",
            ),
            el("pre", {
              class: "dynamic-request-body",
              text: JSON.stringify(this.status.request_body, null, 2),
            }),
          ),
        );
    }
    root.append(el("div", { id: "dynamic-validation", class: "notice error" }));
    root.append(
      el(
        "div",
        { class: "workspace dynamic-workspace" },
        el(
          "section",
          { class: "card" },
          el("div", { class: "card-head" }, el("h2", { text: "动态菜单" })),
          el("div", { id: "dynamic-list", class: "list" }),
          el(
            "div",
            { class: "section-actions actions" },
            btn("＋ 新建菜单", () =>
              this.run(async () => {
                if (!(await this.leave())) return;
                if (this.dirty()) this.document = JSON.parse(this.saved);
                const menu = newMenu();
                this.document.menus.push(menu);
                this.selected = menu.id;
                this.previewId = menu.id;
              }),
            ),
          ),
        ),
        el(
          "section",
          { class: "card" },
          el(
            "div",
            { class: "card-head" },
            el("h2", { text: "菜单与按钮属性" }),
          ),
          el("div", { id: "dynamic-editor", class: "card-body" }),
        ),
        el(
          "section",
          { class: "card preview-card" },
          el("div", { class: "card-head" }, el("h2", { text: "聊天预览" })),
          el("div", { id: "dynamic-preview", class: "card-body" }),
        ),
      ),
    );
    this.drawEditor();
    this.changed();
  }
  drawList() {
    const target = document.querySelector("#dynamic-list");
    if (!target) return;
    const { el, btn } = this;
    target.replaceChildren(
      ...this.document.menus.map((menu) =>
        el(
          "div",
          { class: "dynamic-menu-row" },
          btn(
            `${menu.enabled ? "●" : "○"} ${menu.name} · ${menu.trigger}`,
            () => this.run(() => this.selectMenu(menu.id)),
            menu.id === this.selected ? "selected" : "",
          ),
        ),
      ),
    );
    if (!this.document.menus.length)
      target.append(
        el("p", { class: "empty", text: "新建一个菜单，配置入口和按钮。" }),
      );
  }
  drawEditor() {
    const target = document.querySelector("#dynamic-editor");
    if (!target) return;
    const { el, btn, field, input, select, hint } = this,
      menu = this.current();
    target.replaceChildren();
    if (!menu) {
      target.append(hint("请选择或新建菜单。"));
      return;
    }
    const edit = (key, value) => {
      menu[key] = value;
      this.changed();
    };
    target.append(
      field(
        "菜单名称",
        input(menu.name, (v) => edit("name", v)),
      ),
      field(
        "完整入口指令",
        input(menu.trigger, (v) => edit("trigger", v)),
        "包含前缀，例如 /工具箱；不支持参数。",
      ),
      btn("复制入口", () =>
        this.run(async () => {
          const area = el("textarea", { value: menu.trigger, readOnly: true });
          await this.modal(
            "复制入口",
            [
              hint("选中以下入口后复制，可粘贴到现有 QQ 指令面板编辑器。"),
              area,
            ],
            [["关闭", true]],
          );
        }),
      ),
      field(
        "入口别名（每行一个）",
        input(
          menu.aliases.join("\n"),
          (v) =>
            edit(
              "aliases",
              v
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean),
            ),
          "textarea",
        ),
      ),
      field(
        "启用菜单",
        el("input", {
          type: "checkbox",
          checked: menu.enabled,
          onchange: (e) => edit("enabled", e.target.checked),
        }),
      ),
      field(
        "使用场景",
        select(
          menu.scopes.length === 2 ? "both" : menu.scopes[0],
          [
            ["both", "单聊和群聊"],
            ["c2c", "仅单聊"],
            ["group", "仅群聊"],
          ],
          (v) => edit("scopes", v === "both" ? ["c2c", "group"] : [v]),
        ),
      ),
      field(
        "消息格式",
        select(
          menu.message_format ?? "markdown",
          [
            ["markdown", "Markdown＋按钮"],
            ["text", "文本＋按钮（不使用 Markdown）"],
          ],
          (v) => edit("message_format", v),
        ),
        "遇到 Markdown 顶部留白时可尝试文本格式。文本不会解析 ##、加粗或图片语法；实际排版以 QQ 为准。",
      ),
      field(
        "回复标题",
        input(menu.title, (v) => edit("title", v)),
      ),
      field(
        "菜单说明",
        input(menu.description, (v) => edit("description", v), "textarea"),
      ),
      el(
        "div",
        { class: "actions" },
        btn("复制菜单", () => {
          const copy = copyMenu(menu);
          this.document.menus.push(copy);
          this.selected = copy.id;
          this.previewId = copy.id;
          this.redraw();
        }),
        btn(
          "删除菜单",
          () =>
            this.run(async () => {
              if (
                !(await this.confirm(
                  "删除菜单",
                  "应用后入口将失效。指向此菜单的按钮也需要修改。",
                  "删除",
                ))
              )
                return;
              this.document.menus = this.document.menus.filter(
                (m) => m.id !== menu.id,
              );
              this.selected = this.document.menus[0]?.id;
              this.previewId = this.selected;
            }),
          "danger",
        ),
      ),
      hint("最多 5 行，每行最多 5 个按钮；拖动按钮可调整位置。"),
    );
    menu.rows.forEach((row, r) => {
      const section = el("section", {
        class: "dynamic-row",
        "data-row": r,
        ondragover: (e) => e.preventDefault(),
        ondrop: (e) => {
          e.preventDefault();
          if (this.drag && moveButton(menu, this.drag, [r, row.length]))
            this.redraw();
          this.drag = null;
        },
      });
      section.append(
        el(
          "div",
          { class: "actions" },
          el("h3", { text: `第 ${r + 1} 行` }),
          btn(
            "行上移",
            () => {
              [menu.rows[r - 1], menu.rows[r]] = [
                menu.rows[r],
                menu.rows[r - 1],
              ];
              this.redraw();
            },
            "small",
            r === 0,
          ),
          btn(
            "行下移",
            () => {
              [menu.rows[r + 1], menu.rows[r]] = [
                menu.rows[r],
                menu.rows[r + 1],
              ];
              this.redraw();
            },
            "small",
            r === menu.rows.length - 1,
          ),
          btn(
            "删除行",
            () => {
              menu.rows.splice(r, 1);
              this.redraw();
            },
            "small danger",
          ),
        ),
      );
      row.forEach((button, b) => {
        const block = el("div", {
          class: "dynamic-button-editor",
          draggable: true,
          ondragstart: (e) => {
            if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) {
              e.preventDefault();
              return;
            }
            this.drag = [r, b];
            e.dataTransfer.setData("text/plain", button.id);
          },
          ondragend: () => {
            this.drag = null;
          },
          ondragover: (e) => e.preventDefault(),
          ondrop: (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (this.drag && moveButton(menu, this.drag, [r, b])) this.redraw();
            this.drag = null;
          },
        });
        const change = (key, v) => {
          button[key] = v;
          this.changed();
        };
        block.append(
          field(
            "按钮名称",
            input(button.label, (v) => change("label", v)),
            "最多 10 字符",
          ),
          field(
            "按钮样式",
            select(
              String(button.style),
              [
                ["0", "灰色线框"],
                ["1", "蓝色线框"],
              ],
              (v) => change("style", Number(v)),
            ),
          ),
          field(
            "按钮动作",
            select(
              button.type,
              [
                ["command", "发送普通指令"],
                ["menu", "打开另一个菜单"],
                ["link", "打开 HTTPS 链接"],
              ],
              (v) => {
                const keep = {
                  id: button.id,
                  label: button.label,
                  style: button.style,
                  type: v,
                  enter: false,
                };
                if (v === "command") keep.command = "";
                if (v === "menu") keep.menu_id = "";
                if (v === "link") keep.url = "https://";
                row[b] = keep;
                this.redraw();
              },
            ),
          ),
        );
        if (button.type === "command") {
          block.append(
            field(
              "对应指令（含前缀和参数）",
              input(button.command, (v) => change("command", v)),
            ),
            btn("从 AstrBot 导入指令", () =>
              this.run(() => this.importCommand(button)),
            ),
          );
          if (button.source)
            block.append(
              hint(
                `来源：${button.source.plugin || ""} · ${button.source.effective_command} · AstrBot 权限：${button.source.permission === "admin" ? "管理员" : "普通用户"}`,
              ),
            );
        } else if (button.type === "menu")
          block.append(
            field(
              "目标菜单",
              select(
                button.menu_id,
                [
                  ["", "请选择"],
                  ...this.document.menus.map((m) => [
                    m.id,
                    `${m.name} · ${m.trigger}${m.enabled ? "" : "（停用）"}`,
                  ]),
                ],
                (v) => change("menu_id", v),
              ),
            ),
          );
        else
          block.append(
            field(
              "HTTPS 地址",
              input(button.url, (v) => change("url", v)),
            ),
          );
        if (button.type !== "link")
          block.append(
            field(
              "单聊点击后自动发送",
              el("input", {
                type: "checkbox",
                checked: button.enter,
                onchange: (e) => change("enter", e.target.checked),
              }),
              "群聊始终填入后确认发送。",
            ),
          );
        block.append(
          el(
            "div",
            { class: "actions" },
            btn(
              "左移",
              () => {
                moveButton(menu, [r, b], [r, b - 1]);
                this.redraw();
              },
              "small",
              b === 0,
            ),
            btn(
              "右移",
              () => {
                moveButton(menu, [r, b], [r, b + 1]);
                this.redraw();
              },
              "small",
              b === row.length - 1,
            ),
            btn(
              "移到上一行",
              () => {
                moveButton(menu, [r, b], [r - 1, menu.rows[r - 1].length]);
                this.redraw();
              },
              "small",
              r === 0 || menu.rows[r - 1]?.length >= 5,
            ),
            btn(
              "移到下一行",
              () => {
                moveButton(menu, [r, b], [r + 1, menu.rows[r + 1].length]);
                this.redraw();
              },
              "small",
              r === menu.rows.length - 1 || menu.rows[r + 1]?.length >= 5,
            ),
            btn(
              "删除按钮",
              () => {
                row.splice(b, 1);
                if (!row.length) menu.rows.splice(r, 1);
                this.redraw();
              },
              "small danger",
            ),
          ),
        );
        section.append(block);
      });
      section.append(
        btn(
          "＋ 添加按钮",
          () => {
            row.push(newButton());
            this.redraw();
          },
          "",
          row.length >= 5,
        ),
      );
      target.append(section);
    });
    target.append(
      btn(
        "＋ 新增按钮行",
        () => {
          menu.rows.push([newButton()]);
          this.redraw();
        },
        "",
        menu.rows.length >= 5,
      ),
    );
  }
  async importCommand(button) {
    const data = await this.api("commands"),
      { el, input, field, btn, hint } = this;
    let prefix = data.wake_prefix?.[0] || "",
      query = "",
      all = false,
      chosen = null;
    const list = el("div", { class: "dynamic-command-list" });
    const draw = () =>
      list.replaceChildren(
        ...data.items
          .filter(
            (c) =>
              (all ||
                (c.enabled &&
                  !c.has_conflict &&
                  c.permission !== "admin" &&
                  !c.is_group)) &&
              `${c.plugin} ${c.effective_command} ${c.description}`
                .toLowerCase()
                .includes(query.toLowerCase()),
          )
          .map((c) =>
            el(
              "div",
              {},
              btn(
                `${c.effective_command} · ${c.plugin || ""} · ${c.permission === "admin" ? "管理员" : "普通用户"}${c.enabled ? "" : " · 停用"}${c.has_conflict ? " · 冲突" : ""}`,
                () => {
                  chosen = c;
                  selection.textContent = `已选择：${c.effective_command}`;
                },
              ),
              hint(c.description || ""),
            ),
          ),
      );
    const selection = hint("请选择一个指令。");
    draw();
    const ok = await this.modal(
      "导入 AstrBot 指令",
      [
        field(
          "唤醒前缀",
          input(prefix, (v) => {
            prefix = v;
          }),
        ),
        field(
          "搜索指令",
          input("", (v) => {
            query = v;
            draw();
          }),
        ),
        field(
          "显示管理员、停用及冲突指令",
          el("input", {
            type: "checkbox",
            onchange: (e) => {
              all = e.target.checked;
              draw();
            },
          }),
        ),
        list,
        selection,
      ],
      [
        ["取消", false],
        ["导入", true, "primary"],
      ],
    );
    if (ok && chosen) {
      button.command = prefix + chosen.effective_command;
      button.source = {
        handler_full_name: chosen.handler_full_name,
        effective_command: chosen.effective_command,
        permission: chosen.permission,
        plugin: chosen.plugin,
      };
      this.notify("指令已预填，可继续编辑参数；尚未应用。");
    }
  }
  drawPreview() {
    const target = document.querySelector("#dynamic-preview");
    if (!target) return;
    const { el, btn, hint, select } = this;
    const menu =
      this.document.menus.find((m) => m.id === this.previewId) ||
      this.current();
    target.replaceChildren();
    if (!menu) return;
    target.append(
      select(
        this.scene,
        [
          ["group", "群聊预览"],
          ["c2c", "单聊预览"],
        ],
        (value) => {
          this.scene = value;
          this.drawPreview();
        },
      ),
      hint(`模拟 ${menu.trigger} · ${menu.enabled ? "启用" : "停用"}`),
      el("div", { class: "dynamic-chat-title", text: menu.title }),
      el("p", { class: "dynamic-description", text: menu.description }),
    );
    menu.rows.forEach((row) =>
      target.append(
        el(
          "div",
          { class: "dynamic-keyboard-row" },
          ...row.map((button) =>
            btn(
              button.label || "未命名",
              () => {
                if (button.type === "menu") {
                  const next = this.document.menus.find(
                    (m) => m.id === button.menu_id,
                  );
                  if (
                    !next ||
                    !next.enabled ||
                    !next.scopes.includes(this.scene)
                  ) {
                    this.previewText = "目标菜单不可用";
                    this.pendingPreview = null;
                  } else if (this.scene === "c2c" && button.enter) {
                    this.previewId = next.id;
                    this.previewText = `模拟自动发送：${next.trigger}`;
                  } else {
                    this.previewText = next.trigger;
                    this.pendingPreview = next.id;
                  }
                } else {
                  this.pendingPreview = null;
                  this.previewText =
                    button.type === "link"
                      ? `模拟打开：${button.url}`
                      : (this.scene === "c2c" && button.enter
                          ? "模拟自动发送："
                          : "") + (button.command || "");
                }
                this.drawPreview();
              },
              button.style === 1 ? "dynamic-blue" : "",
            ),
          ),
        ),
      ),
    );
    target.append(
      el("textarea", {
        id: "dynamic-preview-input",
        value: this.previewText,
        readOnly: true,
        "aria-label": "模拟聊天输入框",
      }),
      btn(
        "模拟发送并打开菜单",
        () => {
          this.previewId = this.pendingPreview;
          this.pendingPreview = null;
          this.previewText = "";
          this.drawPreview();
        },
        "",
        !this.pendingPreview,
      ),
      btn("返回当前编辑菜单", () => {
        this.previewId = this.selected;
        this.pendingPreview = null;
        this.previewText = "";
        this.drawPreview();
      }),
      hint("仅本地模拟，不执行指令或打开链接。"),
    );
  }
}
