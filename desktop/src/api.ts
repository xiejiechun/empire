import { useEffect, useRef, useState, useSyncExternalStore } from "react";
export type Data = Record<string, any>;
declare global {
  interface Window {
    empire: {
      read: (op: string, params?: Data, scope?: string) => Promise<any>;
      cancel: (scope: string) => Promise<void>;
      command: (op: string, params: Data, id: string) => Promise<any>;
      status: () => Promise<Data>;
      close: () => Promise<void>;
    };
  }
}
const listeners = new Set<() => void>();
let revision = 0;
export const commandState = { pending: 0, message: "" };
function changed() {
  revision++;
  listeners.forEach((f) => f());
}
export function useCommands() {
  useSyncExternalStore(
    (f) => {
      listeners.add(f);
      return () => {
        listeners.delete(f);
      };
    },
    () => revision,
  );
  return commandState;
}
export async function command(op: string, params: Data) {
  commandState.pending++;
  commandState.message = "正在执行，切换页面不会取消命令";
  changed();
  try {
    const result = await window.empire.command(op, params, crypto.randomUUID());
    commandState.message =
      result?.message || "命令已完成，请以刷新后的实际状态为准";
    return result;
  } catch (e) {
    commandState.message = String(e);
    throw e;
  } finally {
    commandState.pending--;
    changed();
  }
}
export function useQuery(
  op: string,
  params: Data = {},
  period = 5000,
  enabled = true,
) {
  const key = JSON.stringify(params);
  const previous = useRef("");
  const [data, setData] = useState<any>(),
    [error, setError] = useState(""),
    [stamp, setStamp] = useState<number>(),
    [refreshKey, refresh] = useState(0);
  const commands = useCommands();
  useEffect(() => {
    if (!enabled) return;
    const scope = crypto.randomUUID();
    let disposed = false,
      timer: ReturnType<typeof setTimeout>;
    if (previous.current !== op + key) {
      setData(undefined);
      setError("");
      previous.current = op + key;
    }
    const poll = async () => {
      if (document.hidden) {
        timer = setTimeout(poll, period);
        return;
      }
      try {
        const value = await window.empire.read(op, JSON.parse(key), scope);
        if (!disposed) {
          setData(value);
          setError("");
          setStamp(Date.now());
        }
      } catch (e) {
        if (!disposed) setError(String(e));
      } finally {
        if (!disposed) timer = setTimeout(poll, period);
      }
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
      void window.empire.cancel(scope).catch(() => {});
    };
  }, [op, key, period, refreshKey, commands.pending, enabled]);
  return { data, error, stamp, refresh: () => refresh((n) => n + 1) };
}
export const time = (value: any) =>
  value == null
    ? "未知"
    : new Date(typeof value === "number" ? value * 1000 : value).toLocaleString(
        "zh-CN",
        { timeZone: "Asia/Shanghai", hour12: false },
      );
export const labels: Record<string, string> = {
  running: "采集中",
  awaiting_archive: "等待归档",
  complete: "已完成",
  completed: "已完成",
  error: "失败",
  failed: "失败",
  source_gap: "来源缺口",
  idle: "尚未运行",
  paused: "已暂停",
  disabled: "已停用",
  unavailable: "服务不可用",
  success: "成功",
  skipped: "跳过",
  pending: "待处理",
};
export const label = (s: string) => labels[s] || s || "未知";
