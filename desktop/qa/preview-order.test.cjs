const test = require("node:test"), assert = require("node:assert/strict");
const ordering = import("../src/preview/tableOrder.ts");

test("complete detail decimal ordering never rounds through Number", async () => {
  const { compareValue, orderRows } = await ordering;
  assert.equal(compareValue("9007199254740993.00000001", "9007199254740993.00000002", "decimal"), -1);
  assert.equal(compareValue("-9007199254740993.00000001", "-9007199254740993.00000002", "decimal"), 1);
  assert.equal(compareValue("-0.000", "0", "decimal"), 0);
  assert.equal(compareValue("0010.50", "10.5", "decimal"), 0);
  assert.ok(compareValue("2", "10", "integer") < 0);
});

test("complete detail sorting is stable, immutable and null last in both directions", async () => {
  const { compareValue, orderRows } = await ordering;
  const rows = [null, "2", "", "10", "2", "-1"].map((value, id) => ({ value, id }));
  const original = JSON.stringify(rows);
  assert.deepEqual(orderRows(rows, { field: "value", direction: "asc" }, { value: "decimal" }).map(r => r.id), [5, 1, 4, 3, 0, 2]);
  assert.deepEqual(orderRows(rows, { field: "value", direction: "desc" }, { value: "decimal" }).map(r => r.id), [3, 1, 4, 5, 0, 2]);
  assert.equal(JSON.stringify(rows), original);
});

test("dates, natural text and booleans have deterministic comparisons", async () => {
  const { compareValue, orderRows } = await ordering;
  assert.ok(compareValue("2026-01-02", "2026-10-01", "date") < 0);
  assert.ok(compareValue("机构2", "机构10", "text") < 0);
  assert.ok(compareValue(false, true, "boolean") < 0);
});
