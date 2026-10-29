import { useRef, useState } from "react";
import { Button, Empty, Input } from "antd";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import article0 from "../../src/empire/documentation/topics/desktop-client.md?raw";
import article1 from "../../src/empire/documentation/topics/desktop-collect.md?raw";
import article2 from "../../src/empire/documentation/topics/desktop-results.md?raw";
import article3 from "../../src/empire/documentation/topics/desktop-resources.md?raw";
import article4 from "../../src/empire/documentation/topics/desktop-problems.md?raw";
const source = [article0, article1, article2, article3, article4].join("\n");
import "./help.css";

const articles = source.split("<!-- topic:").slice(1).map((part) => {
  const boundary = part.indexOf(" -->");
  const [category, title] = part.slice(0, boundary).split("|");
  const summary = part.match(/<!-- summary:(.*?) -->/)?.[1] || "";
  const group = part.match(/<!-- group:(.*?) -->/)?.[1] || "";
  const body = part.slice(boundary + 4).replace(/<!-- (?:summary|group):.*? -->/g, "").trim();
  return { category, title, summary, group, body };
});

export default function Help() {
  const [selected, setSelected] = useState("快速开始");
  const [search, setSearch] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const reader = useRef<HTMLDivElement>(null);
  const article = articles.find((a) => a.title === selected) || articles[0];
  const words = search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches = articles.filter((a) => words.every((w) =>
    `${a.title} ${a.summary} ${a.body}`.toLocaleLowerCase().includes(w)));
  const open = (title: string) => {
    if (!articles.some((a) => a.title === title)) return;
    setHistory((h) => [...h, selected].slice(-50));
    setSelected(title);
    reader.current?.scrollTo(0, 0);
  };
  const sections = [...article.body.matchAll(/^## (.+)$/gm)].map((m) => m[1]);
  return <div className="help-layout">
    <aside className="help-index" aria-label="说明目录">
      <Input.Search aria-label="搜索说明全文" placeholder="搜索说明全文…" allowClear
        value={search} onChange={(e) => setSearch(e.target.value)} />
      <p className="muted">{matches.length} 篇离线说明</p>
      {!matches.length && <Empty description="没有匹配说明，请减少关键词" />}
      {matches.map((a) => <button key={a.title}
        aria-current={a.title === selected ? "page" : undefined}
        title={a.summary} onClick={() => open(a.title)}>{a.title}</button>)}
    </aside>
    <section className="help-reader" ref={reader} aria-label="说明正文">
      <Button disabled={!history.length} onClick={() => {
        setSelected(history[history.length - 1]); setHistory((h) => h.slice(0, -1));
        reader.current?.scrollTo(0, 0);
      }}>返回上一篇</Button>
      <p className="muted">使用帮助 / {article.title}</p>
      <p>{article.summary}</p>
      <nav aria-label="本页章节" className="help-sections">{sections.map((s) =>
        <button key={s} onClick={() => {
          Array.from(reader.current?.querySelectorAll("h2") || []).find((h) => h.textContent === s)?.scrollIntoView({ block: "start" });
        }}>{s}</button>)}</nav>
      <Markdown remarkPlugins={[remarkGfm]} urlTransform={(url) => url.startsWith("help:") ? url : ""}
        components={{ a: ({ href, children }) => href?.startsWith("help:")
          ? <button className="help-link" onClick={() => open(decodeURIComponent(href.slice(5)))}>{children}</button>
          : <span>{children}</span> }}>{article.body}</Markdown>
    </section>
  </div>;
}
