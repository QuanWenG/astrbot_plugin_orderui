export const labels = {
  send_message: "填入消息",
  link: "链接",
  menu: "折叠菜单",
  switch: "开关",
  command: "指令",
};
export const scopes = {
  c2c: "单聊",
  group: "群聊",
  channel: "文字子频道",
  dm: "频道私信",
};
export const clone = (value) => JSON.parse(JSON.stringify(value));
export const width = (value) =>
  Array.from(value || "").reduce(
    (n, c) => n + (c.codePointAt(0) < 128 ? 1 : 2),
    0,
  );
export function shorten(value, max) {
  let result = "";
  for (const c of value || "") {
    if (width(result + c) > max) break;
    result += c;
  }
  return result;
}
export function strip(value) {
  if (Array.isArray(value)) return value.map(strip);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .filter(([k]) => k !== "_source")
        .map(([k, v]) => [k, strip(v)]),
    );
  return value;
}
export function defaultItem(type = "send_message") {
  const item = { type, name: "" };
  if (type === "send_message") item.send_message = "";
  if (type === "link") item.link = "https://";
  if (type === "menu") item.sub_menu_items = [];
  if (type === "switch") item.switch = { switch_id: "", default: false };
  if (type === "command") Object.assign(item, { desc: "", only_admin: false });
  return item;
}
export function sources(document, mode) {
  const result = [];
  const items = mode === "menu" ? document.menu.items : document.panel.items;
  items.forEach((item, i) => {
    if (item._source) result.push({ ...item._source, path: [i] });
    (item.sub_menu_items || []).forEach((sub, j) => {
      if (sub._source) result.push({ ...sub._source, path: [i, j] });
    });
  });
  return result;
}
export function attachSources(document, mode, entries = []) {
  const items = mode === "menu" ? document.menu.items : document.panel.items;
  for (const entry of entries) {
    const [i, j] = entry.path || [];
    const item = j === undefined ? items[i] : items[i]?.sub_menu_items?.[j];
    if (item) {
      const { path, ...source } = entry;
      item._source = source;
    }
  }
  return document;
}
export function validate(document, mode) {
  const errors = [];
  const checkName = (value, max, field) => {
    if (typeof value !== "string" || !value.trim())
      errors.push(`${field}不能为空`);
    else if (width(value) > max) errors.push(`${field}超过 ${max} 的长度限制`);
  };
  const checkLink = (value) => {
    try {
      const u = new URL(value);
      if (
        u.protocol !== "https:" ||
        !u.hostname ||
        u.username ||
        u.password ||
        /\s/.test(value)
      )
        throw Error();
    } catch {
      errors.push("链接必须是有效的 HTTPS 地址");
    }
  };
  if (mode === "menu") {
    const items = document.menu.items;
    if (items.length > 10) errors.push("一级菜单最多 10 项");
    const switchIds = new Set();
    function visit(item, child = false) {
      checkName(item.name, child ? 14 : 10, "按钮名称");
      const allowed = child
        ? ["send_message", "link"]
        : ["send_message", "link", "menu", "switch"];
      if (!allowed.includes(item.type)) errors.push("不支持的菜单类型或层级");
      if (item.type === "link") checkLink(item.link);
      if (item.type === "send_message" && !item.send_message?.trim())
        errors.push("请填写要填入聊天框的内容");
      if (item.type === "menu") {
        if (!item.sub_menu_items?.length || item.sub_menu_items.length > 5)
          errors.push("每个折叠菜单需要 1–5 个子项");
        (item.sub_menu_items || []).forEach((sub) => visit(sub, true));
      }
      if (item.type === "switch") {
        if (!item.switch?.switch_id?.trim()) errors.push("请填写开关标识");
        else if (switchIds.has(item.switch.switch_id))
          errors.push("开关标识不能重复");
        switchIds.add(item.switch?.switch_id);
      }
    }
    items.forEach((item) => visit(item));
  } else {
    if (!Object.hasOwn(scopes, document.scope)) errors.push("面板场景无效");
    if (!["all", "specific"].includes(document.target_type))
      errors.push("作用范围无效");
    if (
      ["channel", "dm"].includes(document.scope) &&
      document.target_type !== "all"
    )
      errors.push("该场景仅支持全局配置");
    if (!document.panel.items.length)
      errors.push(
        "发布指令面板至少需要一个元素；如需移除整个面板，请使用“删除面板”",
      );
    if (document.panel.items.length > 20) errors.push("每个面板最多 20 项");
    if (Array.from(document.panel.remark || "").length > 255)
      errors.push("备注最多 255 个字符");
    for (const item of document.panel.items) {
      checkName(item.name, 14, "面板名称");
      if (width(item.desc) > 30) errors.push("描述超过 30 的长度限制");
      if (!["command", "link"].includes(item.type))
        errors.push("面板只支持指令或链接");
      if (item.type === "link") checkLink(item.link);
    }
  }
  return [...new Set(errors)];
}
export function move(items, from, to) {
  if (from < 0 || to < 0 || from >= items.length || to >= items.length) return;
  items.splice(to, 0, items.splice(from, 1)[0]);
}
export function differences(before, after, path = "") {
  if (JSON.stringify(before) === JSON.stringify(after)) return [];
  if (
    before &&
    after &&
    typeof before === "object" &&
    typeof after === "object"
  ) {
    return [...new Set([...Object.keys(before), ...Object.keys(after)])]
      .filter((key) => !["_source", "version", "panel_id"].includes(key))
      .flatMap((key) =>
        differences(before[key], after[key], path ? `${path}.${key}` : key),
      );
  }
  return [{ path, before, after }];
}
