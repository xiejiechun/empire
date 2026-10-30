import { createContext } from "react";
import type { Data } from "../api";

export type TableOrder = { field: string; direction: "asc" | "desc" };
export type TablePreferences = { hidden: string[]; compact: boolean };
export const PreviewOrder = createContext<{
  view: string; order?: TableOrder; change: (order?: TableOrder) => void;
  preferences?: TablePreferences; customize?: (preferences: TablePreferences) => void;
} | null>(null);

const collator = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "variant" });
const numeric = new Set(["number", "num", "decimal", "integer"]);

// Compare decimal strings without ever converting an amount to a JS Number.
function decimal(value: unknown): { sign: number; whole: string; fraction: string } | undefined {
  const match = /^([+-]?)(\d+)(?:\.(\d*))?$/.exec(String(value));
  if (!match) return undefined;
  const whole = match[2].replace(/^0+(?=\d)/, "");
  const fraction = (match[3] || "").replace(/0+$/, "");
  return { sign: whole === "0" && !fraction ? 0 : match[1] === "-" ? -1 : 1, whole, fraction };
}

export function compareValue(a: unknown, b: unknown, kind = ""): number {
  if (numeric.has(kind)) {
    const x = decimal(a), y = decimal(b);
    if (x && y) {
      if (x.sign !== y.sign) return x.sign - y.sign;
      const digits = x.whole.length - y.whole.length;
      const whole = x.whole < y.whole ? -1 : x.whole > y.whole ? 1 : 0;
      const size = Math.max(x.fraction.length, y.fraction.length);
      const left = x.fraction.padEnd(size, "0"), right = y.fraction.padEnd(size, "0");
      return x.sign * (digits || whole || (left < right ? -1 : left > right ? 1 : 0));
    }
  }
  if (kind === "boolean") return Number(a) - Number(b);
  return collator.compare(Array.isArray(a) ? a.join("、") : String(a), Array.isArray(b) ? b.join("、") : String(b));
}

export function orderRows(rows: Data[], order: TableOrder | undefined, kinds: Record<string, string>): Data[] {
  if (!order) return rows;
  return rows.map((row, index) => ({ row, index })).sort((a, b) => {
    const left = a.row[order.field], right = b.row[order.field];
    const emptyA = left == null || left === "", emptyB = right == null || right === "";
    if (emptyA !== emptyB) return emptyA ? 1 : -1;
    return (emptyA ? 0 : compareValue(left, right, kinds[order.field]) * (order.direction === "asc" ? 1 : -1)) || a.index - b.index;
  }).map(item => item.row);
}
