import { clone } from "./model.js";

export const uid = () =>
  globalThis.crypto?.randomUUID?.() ||
  `d${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
export const newMenu = () => ({
  id: uid(),
  name: "新菜单",
  trigger: "/工具箱",
  aliases: [],
  enabled: true,
  scopes: ["c2c", "group"],
  message_format: "markdown",
  title: "请选择功能",
  description: "",
  rows: [],
});
export const newButton = () => ({
  id: uid(),
  label: "新按钮",
  type: "command",
  command: "",
  style: 0,
  enter: false,
});
export function copyMenu(menu) {
  const result = clone(menu);
  result.id = uid();
  result.name += " 副本";
  result.trigger += "副本";
  result.aliases = [];
  result.enabled = false;
  for (const row of result.rows)
    for (const button of row) {
      button.id = uid();
      if (button.type === "menu" && button.menu_id === menu.id)
        button.menu_id = result.id;
    }
  return result;
}
export function validateDynamic(document) {
  const errors = [],
    ids = new Set(),
    triggers = new Set();
  const menus = document.menus;
  if (menus.length > 100) errors.push("最多 100 个动态菜单");
  for (const menu of menus) {
    if (!menu.id || ids.has(menu.id)) errors.push("菜单 ID 缺失或重复");
    ids.add(menu.id);
    if (
      !["markdown", "text"].includes(
        menu.message_format === undefined ? "markdown" : menu.message_format,
      )
    )
      errors.push("消息格式只支持 Markdown 或文本");
    if (!menu.name.trim() || Array.from(menu.name).length > 100)
      errors.push("菜单名称必填，最多 100 字符");
    if (!menu.title.trim() || Array.from(menu.title).length > 200)
      errors.push("回复标题必填，最多 200 字符");
    if (Array.from(menu.description).length > 2000)
      errors.push("说明最多 2000 字符");
    if (
      !menu.scopes.length ||
      menu.scopes.some((s) => !["c2c", "group"].includes(s))
    )
      errors.push("请选择有效场景");
    if (menu.aliases.length > 20) errors.push("最多 20 个入口别名");
    for (const value of [menu.trigger, ...menu.aliases]) {
      const trigger = value.trim();
      if (
        !trigger ||
        /\s|[\x00-\x1f]/.test(trigger) ||
        Array.from(trigger).length > 64
      )
        errors.push("入口必填，最多 64 字符，不能含空白或参数");
      if (triggers.has(trigger)) errors.push(`入口指令或别名重复：${trigger}`);
      triggers.add(trigger);
    }
    if (!menu.rows.length || menu.rows.length > 5)
      errors.push(`${menu.name} 需要 1–5 行按钮`);
    const bids = new Set();
    for (const row of menu.rows) {
      if (!row.length || row.length > 5) errors.push("每行需要 1–5 个按钮");
      for (const button of row) {
        if (!button.id || bids.has(button.id))
          errors.push("按钮 ID 缺失或重复");
        bids.add(button.id);
        if (!button.label.trim() || Array.from(button.label).length > 10)
          errors.push("按钮名称必填，最多 10 字符");
        if (![0, 1].includes(button.style)) errors.push("按钮样式无效");
        if (button.type === "command") {
          if (
            !button.command?.trim() ||
            Array.from(button.command).length > 2000
          )
            errors.push("按钮指令必填，最多 2000 字符");
        } else if (button.type === "menu") {
          const target = menus.find((m) => m.id === button.menu_id);
          if (!target) errors.push("跳转目标不存在");
          else if (
            menu.enabled &&
            (!target.enabled ||
              menu.scopes.some((s) => !target.scopes.includes(s)))
          )
            errors.push("跳转目标未启用或场景不兼容");
        } else if (button.type === "link") {
          try {
            const url = new URL(button.url);
            if (
              url.protocol !== "https:" ||
              !url.hostname ||
              url.username ||
              url.password ||
              /\s|[\x00-\x1f]/.test(button.url)
            )
              throw Error();
          } catch {
            errors.push("链接必须是有效的 HTTPS 地址");
          }
        } else errors.push("按钮动作无效");
      }
    }
  }
  return [...new Set(errors)];
}
export function moveButton(menu, from, to) {
  const [r, b] = from,
    [tr, tb] = to;
  if (
    !menu.rows[r]?.[b] ||
    !menu.rows[tr] ||
    (r !== tr && menu.rows[tr].length >= 5)
  )
    return false;
  const [button] = menu.rows[r].splice(b, 1);
  menu.rows[tr].splice(tb, 0, button);
  if (!menu.rows[r].length) menu.rows.splice(r, 1);
  return true;
}
