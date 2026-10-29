const { EventEmitter } = require("node:events");
const MAX = 2 * 1024 * 1024;
class Frames {
  constructor(onMessage) {
    this.buffer = Buffer.alloc(0);
    this.onMessage = onMessage;
  }
  push(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    for (;;) {
      const end = this.buffer.indexOf("\r\n\r\n");
      if (end < 0) {
        if (this.buffer.length > 128) throw Error("Invalid protocol header");
        return;
      }
      const h = this.buffer.subarray(0, end).toString("ascii");
      if (!/^Content-Length: [0-9]+$/.test(h))
        throw Error("Invalid protocol header");
      const n = Number(h.slice(16));
      if (n < 1 || n > MAX) throw Error("Protocol frame too large");
      if (this.buffer.length < end + 4 + n) return;
      const body = this.buffer.subarray(end + 4, end + 4 + n);
      this.buffer = this.buffer.subarray(end + 4 + n);
      this.onMessage(JSON.parse(body.toString("utf8")));
    }
  }
}
function encode(value) {
  const body = Buffer.from(JSON.stringify(value));
  if (body.length > MAX) throw Error("Request exceeds limit");
  return Buffer.concat([
    Buffer.from(`Content-Length: ${body.length}\r\n\r\n`),
    body,
  ]);
}
class Backend extends EventEmitter {
  constructor(child) {
    super();
    this.child = child;
    this.pending = new Map();
    this.scopes = new Map();
    this.sequence = 0;
    this.session = "";
    this.dead = false;
    this.diagnostic = "";
    const frames = new Frames((m) => this.receive(m));
    child.stdout.on("data", (b) => {
      try {
        frames.push(b);
      } catch (e) {
        this.fail(e.message);
        child.stdin.end();
      }
    });
    child.stderr.on("data", (b) => {
      this.diagnostic = (this.diagnostic + b.toString("utf8")).slice(-4096);
    });
    child.on("error", (e) => this.fail(e.message));
    child.on("exit", () =>
      this.fail(
        this.diagnostic.trim() || "后台已退出；未确认的命令请核实实际状态",
      ),
    );
    this.ready = this.request("session.handshake").then((r) => {
      if (r.protocol !== 1) throw Error("前后端协议不匹配");
      this.session = r.session_id;
      return r;
    });
  }
  request(operation, params = {}, operationId, scope) {
    if (this.dead)
      return Promise.reject(Error(this.diagnostic || "后台未运行"));
    if (this.pending.size >= 24) return Promise.reject(Error("请求繁忙"));
    const id = String(++this.sequence);
    if (scope) this.scopes.set(scope, id);
    return new Promise((resolve, reject) => {
      const timer =
        operationId || operation === "desktop.shutdown"
          ? null
          : setTimeout(() => {
              this.pending.delete(id);
              reject(Error("查询超时"));
              if (this.session && operation !== "request.cancel")
                this.request("request.cancel", { request_id: id }).catch(
                  () => {},
                );
            }, 30000);
      this.pending.set(id, { resolve, reject, timer, scope });
      try {
        this.child.stdin.write(
          encode({
            id,
            operation,
            params,
            session_id: this.session,
            ...(operationId ? { operation_id: operationId } : {}),
          }),
          (e) => {
            if (e) {
              const p = this.pending.get(id);
              if (p) {
                clearTimeout(p.timer);
                this.pending.delete(id);
                p.reject(e);
              }
            }
          },
        );
      } catch (e) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(e);
      }
    });
  }
  cancel(scope) {
    const id = this.scopes.get(scope);
    this.scopes.delete(scope);
    if (id && this.pending.has(id) && this.session && !this.dead)
      return this.request("request.cancel", { request_id: id });
    return Promise.resolve();
  }
  receive(message) {
    const p = this.pending.get(message.id);
    if (!p) return;
    this.pending.delete(message.id);
    if (p.scope && this.scopes.get(p.scope) === message.id)
      this.scopes.delete(p.scope);
    clearTimeout(p.timer);
    if (message.error)
      p.reject(
        Error(
          `${message.error.message}${message.error.outcome === "unknown" ? "（执行结果需核实，不自动重试）" : ""}`,
        ),
      );
    else p.resolve(message.result);
  }
  fail(message) {
    if (this.dead) return;
    this.dead = true;
    this.diagnostic = message;
    for (const p of this.pending.values()) {
      clearTimeout(p.timer);
      p.reject(Error(message));
    }
    this.pending.clear();
    this.emit("offline", message);
  }
}
module.exports = { Frames, encode, Backend };
