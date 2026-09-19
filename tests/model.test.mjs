import test from "node:test";
import assert from "node:assert/strict";
import {
  validate,
  width,
  move,
  sources,
  attachSources,
  strip,
  differences,
} from "../pages/manage/model.js";

test("menu limits and CJK names match backend budgeting", () => {
  assert.equal(width("帮助abc😀"), 9);
  const menu = {
    menu: {
      items: [{ type: "send_message", name: "帮助", send_message: "/help" }],
    },
  };
  assert.deepEqual(validate(menu, "menu"), []);
  menu.menu.items[0].name = "中文中文中文";
  assert.ok(validate(menu, "menu").length);
});

test("reordering preserves source identity and serialization removes editor metadata", () => {
  const a = {
    type: "send_message",
    name: "帮助",
    send_message: "/help",
    _source: { handler_full_name: "a" },
  };
  const b = {
    type: "menu",
    name: "更多",
    sub_menu_items: [{ ...a, _source: { handler_full_name: "b" } }],
  };
  const document = { menu: { items: [a, b] } };
  move(document.menu.items, 0, 1);
  const refs = sources(document, "menu");
  assert.deepEqual(
    refs.map((r) => r.path),
    [[0, 0], [1]],
  );
  assert.ok(!JSON.stringify(strip(document)).includes("_source"));
  assert.equal(
    attachSources(strip(document), "menu", refs).menu.items[1]._source
      .handler_full_name,
    "a",
  );
});

test("nested changes and deletions are visible in publication diff", () => {
  const changes = differences(
    { menu: { items: [{ name: "帮助", send_message: "/help" }] } },
    { menu: { items: [] } },
  );
  assert.equal(changes[0].path, "menu.items.0");
  assert.equal(changes[0].after, undefined);
});

test("invalid panel scope, targets and long command are caught before publication", () => {
  const document = {
    scope: "channel",
    target_type: "specific",
    panel: { items: [{ type: "command", name: "123456789012345" }] },
  };
  assert.equal(validate(document, "panel").length, 2);
});

test("empty panel cannot publish and adding an element resolves validation", () => {
  const document = {
    scope: "group",
    target_type: "all",
    panel: { items: [], remark: "" },
  };
  assert.match(validate(document, "panel")[0], /至少需要一个元素/);
  document.panel.items.push({ type: "command", name: "/help", desc: "帮助" });
  assert.deepEqual(validate(document, "panel"), []);
});
