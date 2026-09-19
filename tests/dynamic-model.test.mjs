import test from "node:test";
import assert from "node:assert/strict";
import {
  newMenu,
  newButton,
  copyMenu,
  validateDynamic,
  moveButton,
} from "../pages/manage/dynamic-model.js";

function menu() {
  const m = newMenu();
  m.rows = [[{ ...newButton(), command: "/help", label: "帮助" }]];
  return m;
}

test("message format accepts text, preserves legacy Markdown and rejects invalid values", () => {
  const m = menu();
  assert.equal(m.message_format, "markdown");
  m.message_format = "text";
  assert.deepEqual(validateDynamic({ menus: [m] }), []);
  assert.equal(copyMenu(m).message_format, "text");
  delete m.message_format;
  assert.deepEqual(validateDynamic({ menus: [m] }), []);
  for (const value of ["invalid", null]) {
    m.message_format = value;
    assert.ok(
      validateDynamic({ menus: [m] }).some((e) => e.includes("消息格式")),
    );
  }
});
test("dynamic menu entry validation, links, scene compatibility and live target identity", () => {
  const a = menu(),
    b = menu();
  b.trigger = "/娱乐";
  a.rows[0].push({ ...newButton(), type: "menu", menu_id: b.id });
  const doc = { menus: [a, b] };
  assert.deepEqual(validateDynamic(doc), []);
  b.trigger = "/新娱乐";
  assert.deepEqual(validateDynamic(doc), []);
  b.scopes = ["c2c"];
  assert.ok(validateDynamic(doc).some((e) => e.includes("场景")));
  b.scopes = ["c2c", "group"];
  b.trigger = a.trigger;
  assert.ok(validateDynamic(doc).some((e) => e.includes("重复")));
});
test("button movement and menu duplication preserve references without reusing IDs", () => {
  const m = menu(),
    b = { ...newButton(), type: "menu", menu_id: m.id };
  m.rows.push([b]);
  assert.ok(moveButton(m, [1, 0], [0, 0]));
  assert.equal(m.rows.length, 1);
  assert.equal(m.rows[0][0], b);
  const copy = copyMenu(m);
  assert.notEqual(copy.id, m.id);
  assert.notEqual(copy.rows[0][0].id, b.id);
  assert.equal(copy.rows[0][0].menu_id, copy.id);
  assert.equal(copy.enabled, false);
});
test("labels use codepoints and keyboards enforce row and column boundaries", () => {
  const m = menu();
  m.rows[0][0].label = "中".repeat(9) + "😀";
  assert.deepEqual(validateDynamic({ menus: [m] }), []);
  m.rows[0][0].label += "中";
  assert.ok(validateDynamic({ menus: [m] }).some((e) => e.includes("10 字符")));
  m.rows = [[]];
  assert.ok(validateDynamic({ menus: [m] }).some((e) => e.includes("每行")));
});
