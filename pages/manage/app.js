import {
  labels,
  scopes,
  clone,
  width,
  shorten,
  strip,
  defaultItem,
  sources,
  attachSources,
  validate,
  move,
  differences,
} from "./model.js";
import { DynamicEditor } from "./dynamic.js";

const root = document.querySelector("#app");
const dialog = document.querySelector("#dialog");
const bridge = window.AstrBotPluginPage;
const s = {
  bots: [],
  platform: "",
  mode: "menu",
  scope: "c2c",
  panelId: null,
  records: [],
  document: null,
  remote: null,
  baseline: null,
  backup: null,
  saved: "",
  selected: [0],
  busy: false,
  notice: "",
  error: false,
  previewText: "",
  submenu: -1,
  pending: false,
  switchPreview: {},
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat())
    if (child !== null && child !== undefined)
      node.append(
        typeof child === "string" ? document.createTextNode(child) : child,
      );
  return node;
}
const btn = (title, handler, className = "", disabled = false) =>
  el("button", {
    type: "button",
    text: title,
    class: className,
    disabled,
    onclick: handler,
  });
const hint = (text) => el("p", { class: "hint", text });
function field(title, control, note = "") {
  if (control.matches("input, select, textarea"))
    control.setAttribute("aria-label", title);
  return el(
    "label",
    { class: "field" },
    el("span", { text: title }),
    control,
    note ? hint(note) : null,
  );
}
function input(value, change, type = "text") {
  return el(type === "textarea" ? "textarea" : "input", {
    value: value || "",
    ...(type === "textarea" ? {} : { type }),
    oninput: (e) => change(e.target.value),
  });
}
function select(value, options, change, disabled = false) {
  const node = el(
    "select",
    { disabled, onchange: (e) => change(e.target.value) },
    options.map(([id, title]) => el("option", { value: id, text: title })),
  );
  node.value = value;
  return node;
}
const dirty = () =>
  s.mode === "dynamic"
    ? dynamic.dirty()
    : s.document && JSON.stringify(s.document) !== s.saved;
const currentItems = () =>
  s.mode === "menu" ? s.document.menu.items : s.document.panel.items;
function selectedItem() {
  const [i, j] = s.selected;
  return j === undefined
    ? currentItems()[i]
    : currentItems()[i]?.sub_menu_items?.[j];
}
function itemList(path = s.selected) {
  return path.length === 2
    ? currentItems()[path[0]].sub_menu_items
    : currentItems();
}
function notify(message, error = false) {
  s.notice = message;
  s.error = error;
  const node = document.querySelector("#notice");
  if (node) {
    node.textContent = message;
    node.className = `notice${error ? " error" : ""}`;
    node.hidden = !message;
  }
}
async function api(endpoint, body) {
  const args = { platform_id: s.platform, ...(body || {}) };
  const response =
    body?._get || body === undefined
      ? await bridge.apiGet(endpoint, args)
      : await bridge.apiPost(endpoint, args);
  if (!response?.ok) {
    const error = Error(response?.error?.message || "请求失败");
    error.info = response?.error;
    throw error;
  }
  return response.result;
}
function showError(error) {
  const info = error.info || {};
  if (info.code === "conflict" && info.details?.remote?.document)
    s.remote = clone(info.details.remote.document);
  const detail = [
    error.message,
    info.details?.qq_code ? `QQ 错误码：${info.details.qq_code}` : "",
    info.trace_id ? `Trace ID：${info.trace_id}` : "",
  ]
    .filter(Boolean)
    .join("\n");
  notify(detail, true);
}
async function run(action) {
  if (s.busy) return;
  s.busy = true;
  root.setAttribute("aria-busy", "true");
  try {
    await action();
  } catch (error) {
    showError(error);
  } finally {
    s.busy = false;
    render();
  }
}
function modal(title, content, choices) {
  return new Promise((resolve) => {
    dialog.replaceChildren(
      el("h2", { id: "dialog-title", text: title }),
      ...content,
    );
    const finish = (value) => {
      dialog.close();
      resolve(value);
    };
    dialog.append(
      el(
        "div",
        { class: "dialog-footer" },
        choices.map(([title, value, style]) =>
          btn(title, () => finish(value), style),
        ),
      ),
    );
    dialog.oncancel = (e) => {
      e.preventDefault();
      finish(null);
    };
    dialog.showModal();
  });
}
async function confirm(title, message, action = "确认") {
  return await modal(
    title,
    [el("p", { text: message })],
    [
      ["取消", false],
      [action, true, "primary"],
    ],
  );
}
function resource() {
  return s.mode === "menu"
    ? "menu"
    : s.panelId
      ? `panel:${s.panelId}`
      : `new:${s.scope}`;
}
async function saveDraft() {
  if (s.mode === "dynamic") return dynamic.save();
  await api("draft/save", {
    resource: resource(),
    document: s.document,
    baseline: s.baseline,
    sources: sources(s.document, s.mode),
  });
  s.saved = JSON.stringify(s.document);
  notify("草稿已保存。QQ 当前配置尚未更改。");
}
async function leave() {
  if (!dirty()) return true;
  const answer = await modal(
    "有尚未保存的编辑",
    [el("p", { text: "离开前可以保存为草稿，稍后继续编辑。" })],
    [
      ["取消", null],
      ["放弃编辑", "discard"],
      ["保存草稿", "save", "primary"],
    ],
  );
  if (answer === "save") await saveDraft();
  return answer !== null;
}
function accept(result, restore = true) {
  const draft = restore && result.draft;
  s.remote = clone(result.document);
  s.baseline = draft ? draft.baseline : result.baseline;
  s.document = clone(draft ? draft.document : result.document);
  attachSources(s.document, s.mode, draft ? draft.sources : []);
  s.backup = result.backup || null;
  s.saved = JSON.stringify(s.document);
  s.selected = [0];
  s.previewText = "";
  s.submenu = -1;
  s.switchPreview = {};
  if (s.mode === "panel") s.panelId = result.document.panel_id;
  const warnings = result.warnings || [];
  if (draft && draft.baseline !== result.baseline)
    warnings.push("草稿基线与远端不同。请查看差异并重新载入远端核对后编辑。");
  if (warnings.length) notify(warnings.join("\n"), true);
}
async function refreshPanels() {
  const result = await api("panels", { _get: true, scope: s.scope });
  s.records = result.records;
  s.pending = result.pending_create;
}
async function newPanel() {
  s.panelId = null;
  s.remote = {
    scope: s.scope,
    target_type: "all",
    panel: { items: [], remark: "" },
    user_openids: [],
    group_openids: [],
  };
  const saved = await api("draft", { _get: true, resource: `new:${s.scope}` });
  s.document = clone(saved.draft?.document || s.remote);
  s.baseline = null;
  s.backup = null;
  if (saved.draft) attachSources(s.document, "panel", saved.draft.sources);
  s.saved = JSON.stringify(s.document);
  s.selected = [0];
}
async function load(restore = true) {
  s.notice = "";
  if (s.mode === "dynamic") await dynamic.load(restore);
  else if (s.mode === "menu") accept(await api("menu"), restore);
  else {
    await refreshPanels();
    if (!s.panelId || !s.records.some((r) => r.panel_id === s.panelId))
      s.panelId = s.records[0]?.panel_id || null;
    if (s.panelId)
      accept(await api("panel", { _get: true, panel_id: s.panelId }), restore);
    else await newPanel();
  }
}
async function navigate(changes, create = false) {
  if (!(await leave())) return;
  const previous = { ...s };
  Object.assign(s, changes);
  try {
    if (create) await newPanel();
    else await load();
  } catch (error) {
    Object.assign(s, previous);
    throw error;
  }
}
function changed() {
  renderList();
  renderPreview();
  const status = document.querySelector("#save-status");
  if (status) status.textContent = dirty() ? "有未保存的编辑" : "草稿已保存";
  const checks = document.querySelector("#validation");
  if (checks) {
    const errors = validate(s.document, s.mode);
    checks.textContent = errors.join(" · ");
    checks.hidden = !errors.length;
  }
}
function addItem(child = false) {
  let list = currentItems(),
    path = [];
  if (child) {
    const parent = currentItems()[s.selected[0]];
    if (parent?.type !== "menu") return;
    list = parent.sub_menu_items;
    path = [s.selected[0]];
  }
  if (list.length >= (child ? 5 : s.mode === "menu" ? 10 : 20)) {
    notify("已达到该层级的数量上限", true);
    return;
  }
  list.push(defaultItem(s.mode === "menu" ? "send_message" : "command"));
  s.selected = [...path, list.length - 1];
  render();
}
function reorder(path, offset) {
  const list = itemList(path),
    index = path.at(-1),
    next = index + offset;
  if (next < 0 || next >= list.length) return;
  move(list, index, next);
  s.selected = [...path.slice(0, -1), next];
  render();
}
function renderList() {
  const node = document.querySelector("#items");
  if (!node || !s.document) return;
  node.replaceChildren();
  function row(item, path) {
    const selected = JSON.stringify(path) === JSON.stringify(s.selected);
    const r = el(
      "div",
      {
        class: `item-row${selected ? " selected" : ""}${path.length === 2 ? " child" : ""}`,
        draggable: true,
        ondragstart: (e) => {
          e.dataTransfer.setData("text/plain", JSON.stringify(path));
        },
        ondragover: (e) => e.preventDefault(),
        ondrop: (e) => {
          e.preventDefault();
          try {
            const from = JSON.parse(e.dataTransfer.getData("text/plain"));
            if (
              Array.isArray(from) &&
              from.length === path.length &&
              from.every(Number.isInteger) &&
              (path.length === 1 || from[0] === path[0])
            ) {
              move(itemList(path), from.at(-1), path.at(-1));
              s.selected = path;
              render();
            }
          } catch {
            /* Ignore external drag payloads. */
          }
        },
      },
      el("span", { class: "grip", text: "⠿", "aria-hidden": "true" }),
      el(
        "button",
        {
          class: "item-select",
          type: "button",
          onclick: () => {
            s.selected = path;
            render();
          },
        },
        el("strong", { text: item.name || "未命名按钮" }),
        el("small", { text: labels[item.type] || item.type }),
      ),
      el(
        "div",
        { class: "item-tools" },
        btn("↑", () => reorder(path, -1), "", path.at(-1) === 0),
        btn(
          "↓",
          () => reorder(path, 1),
          "",
          path.at(-1) === itemList(path).length - 1,
        ),
      ),
    );
    node.append(r);
  }
  currentItems().forEach((item, i) => {
    row(item, [i]);
    (item.sub_menu_items || []).forEach((sub, j) => row(sub, [i, j]));
  });
  if (!currentItems().length)
    node.append(
      el("div", {
        class: "empty",
        text: "从一个按钮开始\n点击下方“新增”或“导入指令”",
      }),
    );
}
function renderEditor() {
  const node = document.querySelector("#editor");
  if (!node || !s.document) return;
  node.replaceChildren();
  const item = selectedItem();
  if (!item) {
    node.append(hint("选择左侧按钮以编辑属性。"));
    return;
  }
  const child = s.selected.length === 2;
  const kinds =
    s.mode === "panel"
      ? ["command", "link"]
      : child
        ? ["send_message", "link"]
        : ["send_message", "link", "menu", "switch"];
  const set = (key, value) => {
    item[key] = value;
    changed();
  };
  node.append(
    field(
      "按钮类型",
      select(
        item.type,
        kinds.map((k) => [k, labels[k]]),
        (kind) =>
          run(async () => {
            if (
              item.type === "menu" &&
              item.sub_menu_items.length &&
              !(await confirm(
                "更改菜单类型",
                "该折叠菜单的子项将被移除，是否继续？",
              ))
            )
              return;
            const replacement = { ...defaultItem(kind), name: item.name };
            if (s.mode === "panel")
              Object.assign(replacement, {
                desc: item.desc || "",
                only_admin: item.only_admin || false,
              });
            itemList()[s.selected.at(-1)] = replacement;
          }),
      ),
    ),
    field(
      "显示名称",
      input(item.name, (value) => set("name", value)),
      s.mode === "panel"
        ? "指令类型会把此名称填入聊天框；上限 14。"
        : `长度上限 ${child ? 14 : 10}；中文按 2 计。`,
    ),
  );
  if (item.type === "send_message")
    node.append(
      field(
        "填入聊天框的内容",
        input(
          item.send_message,
          (value) => set("send_message", value),
          "textarea",
        ),
        "例如 /help。用户在 QQ 中确认发送后才会执行。",
      ),
    );
  if (item.type === "link")
    node.append(
      field(
        "HTTPS 链接",
        input(item.link, (value) => set("link", value)),
        "预览仅展示链接，不打开外部页面。",
      ),
    );
  if (item.type === "menu")
    node.append(
      hint("最多 5 个子项，仅支持填入消息和链接。"),
      btn(
        "新增子菜单",
        () => addItem(true),
        "",
        item.sub_menu_items.length >= 5,
      ),
    );
  if (item.type === "switch") {
    node.append(
      field(
        "开关标识",
        input(item.switch.switch_id, (value) => {
          item.switch.switch_id = value;
          changed();
        }),
      ),
      el(
        "label",
        {},
        el("input", {
          type: "checkbox",
          checked: item.switch.default,
          onchange: (e) => {
            item.switch.default = e.target.checked;
            changed();
          },
        }),
        " 默认打开",
      ),
      hint(
        "这里只配置 QQ 开关。实际功能需要对应插件处理消息中的开关信息，不会直接改变 AstrBot 设置。",
      ),
    );
  }
  if (s.mode === "panel")
    node.append(
      field(
        "描述",
        input(item.desc, (value) => set("desc", value)),
        "上限 30，中文按 2 计。",
      ),
      el(
        "label",
        {},
        el("input", {
          type: "checkbox",
          checked: !!item.only_admin,
          onchange: (e) => set("only_admin", e.target.checked),
        }),
        " 仅 QQ 群／频道管理员可点击",
      ),
      hint("这是 QQ 点击权限；AstrBot 指令执行权限仍独立校验。"),
    );
  if (item._source)
    node.append(
      el("div", {
        class: "notice",
        text: `来源：${item._source.effective_command}\nAstrBot 权限：${item._source.permission === "admin" ? "管理员" : "普通成员"}`,
      }),
      btn(
        "解除指令关联",
        () => {
          delete item._source;
          render();
        },
        "small",
      ),
    );
  node.append(
    el(
      "div",
      { class: "toolbar" },
      btn("复制", () => {
        const list = itemList();
        if (list.length >= (child ? 5 : s.mode === "menu" ? 10 : 20)) {
          notify("已达到数量上限", true);
          return;
        }
        list.splice(s.selected.at(-1) + 1, 0, clone(item));
        s.selected[s.selected.length - 1]++;
        render();
      }),
      btn(
        "删除",
        () =>
          run(async () => {
            if (
              item.type === "menu" &&
              item.sub_menu_items.length &&
              !(await confirm(
                "删除折叠菜单",
                "此操作将同时移除草稿中的子菜单。",
              ))
            )
              return;
            itemList().splice(s.selected.at(-1), 1);
            s.selected = [0];
          }),
        "danger",
      ),
    ),
  );
}
function renderPreview() {
  const node = document.querySelector("#preview");
  if (!node || !s.document) return;
  const simulate = (item) => {
    if (item.type === "link") s.previewText = `将打开：${item.link}`;
    else if (item.type === "switch") {
      const key = item.switch.switch_id;
      s.switchPreview[key] = !(s.switchPreview[key] ?? item.switch.default);
      s.previewText = `模拟 ${key}：${s.switchPreview[key] ? "打开" : "关闭"}（不修改真实状态）`;
    } else s.previewText = item.send_message || item.name || "";
    renderPreview();
  };
  const chat = el(
    "div",
    { class: "phone-chat" },
    el("div", {
      class: "bubble",
      text: "你好！点击下方入口，发现机器人的更多功能。",
    }),
  );
  const phone = el(
    "div",
    { class: "phone" },
    el("div", {
      class: "phone-top",
      text:
        s.mode === "menu"
          ? "QQ 单聊 · 机器人"
          : `${scopes[s.scope]} · 指令面板`,
    }),
    chat,
  );
  if (s.mode === "menu") {
    const folder = currentItems()[s.submenu];
    if (folder?.type === "menu")
      phone.append(
        el(
          "div",
          { class: "phone-submenu" },
          folder.sub_menu_items.map((item) =>
            btn(item.name || "子菜单", () => simulate(item)),
          ),
        ),
      );
    phone.append(
      el("div", {
        class: "phone-input",
        text: s.previewText || "填入聊天框的内容显示在这里",
      }),
      el(
        "div",
        { class: "phone-menu" },
        currentItems().map((item, i) =>
          btn(
            `${item.type === "switch" ? ((s.switchPreview[item.switch.switch_id] ?? item.switch.default) ? "● " : "○ ") : ""}${item.name || "按钮"}${item.type === "menu" ? " ⌃" : ""}`,
            () => {
              if (item.type === "menu") {
                s.submenu = s.submenu === i ? -1 : i;
                renderPreview();
              } else simulate(item);
            },
          ),
        ),
      ),
    );
  } else {
    chat.append(
      el(
        "div",
        { class: "panel-preview" },
        currentItems().map((item) =>
          el(
            "button",
            { type: "button", onclick: () => simulate(item) },
            item.name || "指令",
            el("small", {
              text: `${item.desc || ""}${item.only_admin ? " · QQ 管理员" : ""}`,
            }),
          ),
        ),
      ),
    );
    phone.append(
      el("div", {
        class: "phone-input",
        text: s.previewText || "点击指令预览填入内容",
      }),
    );
  }
  node.replaceChildren(
    phone,
    hint("交互示意预览，实际样式与生效时间以 QQ 客户端为准。"),
  );
}
function panelMeta() {
  const d = s.document;
  const fieldName = d.scope === "c2c" ? "user_openids" : "group_openids";
  const box = el(
    "div",
    { class: "card card-body panel-meta" },
    field(
      "作用范围",
      select(
        d.target_type,
        [
          ["all", "全局"],
          ["specific", "指定用户／群"],
        ],
        (value) => {
          d.target_type = value;
          if (value === "all") {
            d.user_openids = [];
            d.group_openids = [];
          }
          render();
        },
        !!s.panelId || ["channel", "dm"].includes(d.scope),
      ),
    ),
    field(
      "面板备注",
      input(d.panel.remark, (value) => {
        d.panel.remark = value;
        changed();
      }),
    ),
  );
  if (d.target_type === "specific") {
    const f = field(
      d.scope === "c2c" ? "用户 OpenID（每行一个）" : "群 OpenID（每行一个）",
      input(
        (d[fieldName] || []).join("\n"),
        (value) => {
          d[fieldName] = [
            ...new Set(
              value
                .split(/\r?\n/)
                .map((v) => v.trim())
                .filter(Boolean),
            ),
          ];
          changed();
        },
        "textarea",
      ),
      "必须是当前机器人的 OpenID，不是 QQ 号或群号。发布时自动分批。",
    );
    f.classList.add("wide");
    box.append(f);
  }
  if (s.panelId)
    box.append(hint("已创建面板的场景和作用范围固定；需要更改时新建面板。"));
  return box;
}
async function showDiff(publish = false) {
  const entries = differences(strip(s.remote), strip(s.document));
  const table = el(
    "table",
    { class: "diff" },
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        ...["字段", "远端", "待发布"].map((text) => el("th", { text })),
      ),
    ),
    el(
      "tbody",
      {},
      entries.map((entry) =>
        el(
          "tr",
          {},
          el("td", { text: entry.path }),
          el("td", {
            class: "before",
            text: JSON.stringify(entry.before) ?? "（无）",
          }),
          el("td", {
            class: "after",
            text: JSON.stringify(entry.after) ?? "（删除）",
          }),
        ),
      ),
    ),
  );
  const content = [
    el("p", {
      text:
        s.mode === "menu"
          ? "发布会覆盖此机器人当前单聊菜单，对所有单聊用户生效。"
          : "发布会更新此面板内容及指定对象。",
    }),
    entries.length ? table : hint("内容没有差异。"),
  ];
  return await modal(
    publish ? "核对并发布" : "配置差异",
    content,
    publish
      ? [
          ["取消", false],
          ["确认发布", true, "primary"],
        ]
      : [["关闭", false]],
  );
}
async function publish() {
  const errors = validate(s.document, s.mode);
  if (errors.length) {
    notify(errors.join("\n"), true);
    return;
  }
  if (!(await showDiff(true))) return;
  await saveDraft();
  const endpoint =
    s.mode === "menu"
      ? "menu/publish"
      : s.panelId
        ? "panels/update"
        : "panels/create";
  const body = {
    document: strip(s.document),
    baseline: s.baseline,
    panel_id: s.panelId,
    sources: sources(s.document, s.mode),
  };
  let result;
  try {
    result = await api(endpoint, body);
  } catch (error) {
    if (error.info?.code !== "command_changed") {
      if (endpoint === "panels/create") {
        try {
          await refreshPanels();
        } catch {
          /* Preserve the original publication error. */
        }
      }
      throw error;
    }
    if (
      !(await confirm(
        "关联指令已变化",
        error.info.details.warnings.join("\n") + "\n继续发布当前编辑内容？",
        "仍然发布",
      ))
    )
      return;
    result = await api(endpoint, { ...body, ack_warnings: true });
  }
  accept(result, true);
  if (s.mode === "panel") await refreshPanels();
  notify(
    result.partial
      ? `面板已创建／更新，但关联对象未全部完成。${result.targets?.verified ? `当前已确认 ${result.targets.current.length} 个对象，待添加 ${result.targets.remaining_add.length} 个，待移除 ${result.targets.remaining_remove.length} 个。` : "最后一次回读失败，部分对象状态尚待核对。"}\n草稿保留未完成的目标，再次发布会重新核对。\n${JSON.stringify(result.failures, null, 2)}`
      : "发布成功，已回读确认。QQ 客户端可能需要稍后刷新。",
    !!result.partial,
  );
}
async function commandPicker() {
  const data = await api("commands");
  let query = "",
    showAll = false,
    prefix = data.wake_prefix?.[0] || "";
  const picked = new Map();
  const results = el("div");
  function draw() {
    results.replaceChildren();
    const filtered = data.items.filter(
      (c) =>
        (showAll ||
          (c.enabled && !c.has_conflict && c.permission !== "admin")) &&
        `${c.effective_command} ${c.plugin} ${c.description}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    );
    for (const c of filtered) {
      const key = c.handler_full_name;
      const commandInput = input(
        picked.get(key)?.value ?? prefix + c.effective_command,
        (value) => {
          if (picked.has(key)) picked.get(key).value = value;
        },
      );
      const check = el("input", {
        type: "checkbox",
        checked: picked.has(key),
        onchange: (e) => {
          if (e.target.checked)
            picked.set(key, { command: c, value: commandInput.value });
          else picked.delete(key);
        },
      });
      results.append(
        el(
          "div",
          { class: "command-row" },
          check,
          el(
            "div",
            {},
            el("strong", { text: c.effective_command }),
            hint(
              `${c.plugin_display_name || c.plugin} · AstrBot ${c.permission === "admin" ? "管理员" : "普通成员"}${!c.enabled ? " · 已停用" : ""}${c.has_conflict ? " · 有冲突" : ""}`,
            ),
            hint(c.description || "暂无描述"),
            commandInput,
            c.aliases?.length
              ? hint(
                  `别名：${c.aliases.join("、")}（可在上方调整完整指令文本）`,
                )
              : null,
          ),
        ),
      );
    }
    if (!filtered.length) results.append(hint("没有匹配的指令。"));
  }
  draw();
  const content = [
    field(
      "搜索指令或插件",
      input("", (value) => {
        query = value;
        draw();
      }),
    ),
    field(
      "默认唤醒前缀",
      input(prefix, (value) => {
        prefix = value;
        draw();
      }),
      "依据 AstrBot 默认配置预填；不同会话的配置可能不同，请核对。",
    ),
    el(
      "label",
      {},
      el("input", {
        type: "checkbox",
        onchange: (e) => {
          showAll = e.target.checked;
          draw();
        },
      }),
      " 显示管理员、停用或冲突的指令",
    ),
    results,
  ];
  if (
    !(await modal("从 AstrBot 导入指令", content, [
      ["取消", false],
      ["导入选中项", true, "primary"],
    ]))
  )
    return;
  let target = currentItems();
  if (s.mode === "menu" && currentItems()[s.selected[0]]?.type === "menu")
    target = currentItems()[s.selected[0]].sub_menu_items;
  const limit = target === currentItems() ? (s.mode === "menu" ? 10 : 20) : 5;
  if (target.length + picked.size > limit)
    throw Error(`导入后超过 ${limit} 项上限，请减少选择。`);
  if (
    s.mode === "panel" &&
    [...picked.values()].some((p) => width(p.value) > 14)
  )
    throw Error("面板指令超过 14 的长度限制，请重新导入并选择有效短别名。");
  for (const { command: c, value } of picked.values()) {
    const item =
      s.mode === "menu"
        ? {
            type: "send_message",
            name: shorten(
              c.effective_command,
              target === currentItems() ? 10 : 14,
            ),
            send_message: value,
          }
        : {
            type: "command",
            name: value,
            desc: shorten(c.description || "", 30),
            only_admin: false,
          };
    item._source = {
      handler_full_name: c.handler_full_name,
      effective_command: c.effective_command,
      permission: c.permission,
    };
    target.push(item);
  }
  notify(`已导入 ${picked.size} 项，尚未发布。`);
}
function render() {
  root.replaceChildren();
  root.setAttribute("aria-busy", String(s.busy));
  root.append(
    el(
      "header",
      { class: "masthead" },
      el(
        "div",
        {},
        el("div", { class: "eyebrow", text: "QQ BOT · WORKSPACE" }),
        el("h1", { text: "菜单与指令面板" }),
        hint("让每一次对话，都有清晰的起点。"),
      ),
      el(
        "div",
        { class: "robot-picker" },
        field(
          "当前机器人",
          select(
            s.platform,
            s.bots.map((b) => [
              b.platform_id,
              `${b.name} · ${b.appid} · ${b.status}`,
            ]),
            (id) => run(() => navigate({ platform: id, panelId: null })),
            s.busy,
          ),
        ),
      ),
    ),
  );
  root.append(
    el("div", {
      id: "notice",
      class: `notice${s.error ? " error" : ""}`,
      role: s.error ? "alert" : "status",
      hidden: !s.notice,
      text: s.notice,
    }),
  );
  if (!s.platform) {
    root.append(
      el("div", {
        class: "empty",
        text: "请先在 AstrBot 中配置并启用 QQ 官方机器人，然后重新打开此页面。",
      }),
    );
    return;
  }
  root.append(
    el(
      "nav",
      { class: "tabs", "aria-label": "管理功能" },
      btn(
        "单聊菜单",
        () => run(() => navigate({ mode: "menu" })),
        `tab${s.mode === "menu" ? " active" : ""}`,
      ),
      btn(
        "指令面板",
        () => run(() => navigate({ mode: "panel" })),
        `tab${s.mode === "panel" ? " active" : ""}`,
      ),
      btn(
        "动态指令菜单",
        () => run(() => navigate({ mode: "dynamic" })),
        `tab${s.mode === "dynamic" ? " active" : ""}`,
      ),
    ),
  );
  if (s.mode === "dynamic") {
    dynamic.render(root);
    return;
  }
  if (s.mode === "panel") {
    root.append(
      el(
        "div",
        { class: "panel-selectors" },
        field(
          "使用场景",
          select(s.scope, Object.entries(scopes), (scope) =>
            run(() => navigate({ scope, panelId: null })),
          ),
        ),
        field(
          "当前面板",
          select(
            s.panelId || "",
            [
              ["", "新面板草稿"],
              ...s.records.map((r) => [
                r.panel_id,
                `${r.panel?.remark || r.panel_id} · ${r.target_type === "all" ? "全局" : "指定对象"}`,
              ]),
            ],
            (panelId) =>
              run(() => navigate({ panelId: panelId || null }, !panelId)),
          ),
        ),
        btn("新建面板", () =>
          run(async () => {
            if (await leave()) await newPanel();
          }),
        ),
      ),
    );
    if (s.pending)
      root.append(
        el(
          "div",
          { class: "notice" },
          "有待核对的创建操作，已阻止重复创建。",
          el(
            "div",
            { class: "actions" },
            btn("恢复创建结果", () =>
              run(async () => {
                const result = await api("panels/recover", {});
                s.scope = result.document.scope;
                accept(result, true);
                await refreshPanels();
                notify(
                  result.partial
                    ? "面板已找回，关联对象仍有未完成项。"
                    : "已恢复创建结果。",
                  !!result.partial,
                );
              }),
            ),
            btn(
              "人工核对后解除锁定",
              () =>
                run(async () => {
                  if (
                    await confirm(
                      "解除创建保护",
                      "请先核对各场景面板列表，确认无需恢复上次创建。解除后再次新建可能产生重复面板。",
                      "已核对，解除",
                    )
                  ) {
                    await api("panels/unlock", { confirmed_checked: true });
                    await refreshPanels();
                  }
                }),
              "danger",
            ),
          ),
        ),
      );
  }
  if (!s.document) {
    root.append(btn("重新加载", () => run(() => load())));
    return;
  }
  root.append(
    el(
      "div",
      { class: "toolbar" },
      el("span", {
        class: "status-pill",
        id: "save-status",
        text: dirty() ? "有未保存的编辑" : "草稿已保存",
      }),
      el(
        "div",
        { class: "actions" },
        btn("保存草稿", () => run(saveDraft)),
        btn("载入远端", () =>
          run(async () => {
            if (
              await confirm(
                "载入远端配置",
                "当前编辑区将替换为 QQ 远端配置，已保存草稿仍保留，直到再次保存。",
                "载入",
              )
            )
              await load(false);
          }),
        ),
        btn(
          "恢复上次发布前",
          () =>
            run(async () => {
              if (
                s.backup &&
                (await confirm(
                  "恢复为草稿",
                  "将上次发布前的内容放入编辑区；需要再次发布才会影响 QQ。",
                ))
              ) {
                s.document = clone(s.backup);
                notify("已恢复到编辑区，尚未发布。");
              }
            }),
          "",
          !s.backup,
        ),
        btn("查看差异", () => run(() => showDiff(false))),
        btn("发布到 QQ", () => run(publish), "primary"),
      ),
    ),
  );
  if (s.mode === "panel") root.append(panelMeta());
  const errors = validate(s.document, s.mode);
  root.append(
    el("div", {
      class: "notice error",
      id: "validation",
      hidden: !errors.length,
      text: errors.join(" · "),
    }),
  );
  root.append(
    el(
      "div",
      { class: "workspace" },
      el(
        "section",
        { class: "card" },
        el(
          "div",
          { class: "card-head" },
          el("h2", { text: s.mode === "menu" ? "菜单结构" : "面板元素" }),
          hint("拖动排序"),
        ),
        el("div", { class: "list", id: "items" }),
        el(
          "div",
          { class: "section-actions actions" },
          btn("＋ 新增", () => addItem()),
          btn("导入指令", () => run(commandPicker)),
        ),
      ),
      el(
        "section",
        { class: "card" },
        el("div", { class: "card-head" }, el("h2", { text: "编辑属性" })),
        el("div", { class: "card-body", id: "editor" }),
      ),
      el(
        "section",
        { class: "card preview-card" },
        el(
          "div",
          { class: "card-head" },
          el("h2", { text: "效果预览" }),
          hint("仅本地模拟"),
        ),
        el("div", { class: "card-body", id: "preview" }),
      ),
    ),
  );
  if (s.mode === "panel" && s.panelId)
    root.append(
      el(
        "div",
        { class: "toolbar" },
        hint(`面板 ID：${s.panelId}`),
        btn(
          "删除远端面板",
          () =>
            run(async () => {
              if (
                !(await confirm(
                  "删除远端面板",
                  "删除后此面板不再对任何用户或群生效。",
                  "确认删除",
                ))
              )
                return;
              await api("panels/delete", {
                panel_id: s.panelId,
                baseline: s.baseline,
              });
              s.panelId = null;
              await load();
              notify("远端面板已删除。");
            }),
          "danger",
        ),
      ),
    );
  renderList();
  renderEditor();
  renderPreview();
}

window.addEventListener("beforeunload", (event) => {
  if (dirty()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
async function boot() {
  if (!bridge) {
    root.replaceChildren(
      el("div", {
        class: "notice error",
        text: "请从支持 Plugin Pages 的 AstrBot WebUI 打开此插件页面。",
      }),
    );
    return;
  }
  const context = await bridge.ready();
  const theme = (ctx) =>
    (document.documentElement.dataset.theme = ctx.isDark ? "dark" : "light");
  theme(context);
  bridge.onContext(theme);
  const data = await api("bots");
  s.bots = data.items;
  s.platform = s.bots[0]?.platform_id || "";
  render();
  if (s.platform) await run(() => load());
}
const dynamic = new DynamicEditor({
  api,
  el,
  btn,
  input,
  select,
  field,
  hint,
  modal,
  confirm,
  run,
  leave,
  notify,
  redraw: render,
});

boot().catch((error) => {
  root.replaceChildren(
    el("div", {
      class: "notice error",
      text: `页面加载失败：${error.message}`,
    }),
  );
});
