import { useEffect, useState } from "react";
import { Data } from "../api";

// A result belongs to one exact query, never to newly edited or failed filters.
export function usePreviewRead(project: string, view: string, filters: Data, cursor: any, revision: number, order?: Data) {
  const key = JSON.stringify({ ident: project, view, filters, cursor: JSON.stringify(cursor), order });
  const identity = key + ":" + revision;
  const [result, setResult] = useState<{ identity: string; data?: Data; error: string; stamp?: number }>({ identity: "", error: "" });
  useEffect(() => {
    const scope = crypto.randomUUID();
    let disposed = false;
    window.empire.read("preview.read", JSON.parse(key), scope).then(data => {
      if (!disposed) setResult({ identity, data, error: "", stamp: Date.now() });
    }).catch(error => {
      if (!disposed) setResult({ identity, error: String(error) });
    });
    return () => { disposed = true; void window.empire.cancel(scope).catch(() => {}); };
  }, [key, identity]);
  return result.identity === identity ? { ...result, loading: false } : { data: undefined, error: "", stamp: undefined, loading: true };
}
