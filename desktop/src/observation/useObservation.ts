import { useEffect, useState } from 'react';

// User-driven reads: a new identity immediately hides the previous result.
export function useObservation<T>(operation: string, params: object, enabled = true) {
  const key = JSON.stringify(params);
  const [revision, setRevision] = useState(0);
  const identity = operation + key + revision;
  const [state, setState] = useState<{ identity: string; data?: T; error?: string }>({ identity: '' });
  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    const scope = crypto.randomUUID();
    window.empire.read(operation, JSON.parse(key), scope).then(
      data => { if (!disposed) setState({ identity, data }); },
      error => { if (!disposed) setState({ identity, error: String(error) }); },
    );
    return () => { disposed = true; void window.empire.cancel(scope).catch(() => {}); };
  }, [operation, key, identity, enabled]);
  const current = enabled && state.identity === identity ? state : undefined;
  return { identity, data: current?.data, error: current?.error, loading: enabled && !current,
    refresh: () => setRevision(v => v + 1) };
}
