import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Dropdown,
  Input,
  Modal,
  Spin,
  Tag,
  Tooltip,
  theme,
} from "antd";
import {
  ArrowRightOutlined,
  ClockCircleOutlined,
  FundOutlined,
  CalendarOutlined,
  FileTextOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  SettingOutlined,
  SunOutlined,
} from "@ant-design/icons";
import { useCommands, useQuery } from "./api";
import Tasks from "./Tasks";
import Records from "./Records";
import Management from "./Management";
import Help from "./Help";
import ObservationCalendar from "./observation/ObservationCalendar";
const DailyReview = lazy(() => import("./daily-review/DailyReview"));
const observationPages = [["observation", "多指标观察日历"], ["market_review", "每日复盘"]];
const destinations = [
  ...observationPages,
  ["help", "说明文档"],
  ["tasks", "采集任务"],
  ["archived", "已归档任务"],
  ["records", "跨任务记录"],
  ["sites", "站点访问规则"],
  ["exits", "采集出口"],
  ["resources", "共享资源"],
  ["identities", "身份管理"],
  ["health", "运行状态"],
];
export default function App({
  dark,
  onTheme,
}: {
  dark: boolean;
  onTheme: () => void;
}) {
  const [page, setPage] = useState("tasks"),
    [status, setStatus] = useState<any>({ status: "正在连接" }),
    [collapsed, setCollapsed] = useState(false),
    [searchOpen, setSearchOpen] = useState(false),
    [search, setSearch] = useState(""),
    [panel, setPanel] = useState(""),
    [comfortable, setComfortable] = useState(false);
  const searchRef = useRef<any>(null);
  const commands = useCommands();
  const observing = observationPages.some(([id]) => id === page);
  const { token } = theme.useToken();
  const counts = useQuery("tasks.list", { limit: 1 }, 15000, !!status.online);
  const archived = useQuery(
    "tasks.list",
    { limit: 1, archived: true },
    15000,
    !!status.online,
  );
  useEffect(() => {
    const poll = () => window.empire.status().then(setStatus);
    void poll();
    const timer = setInterval(poll, 2000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const values = {
      "--canvas": token.colorBgLayout,
      "--surface": token.colorBgContainer,
      "--raised": token.colorBgElevated,
      "--border": token.colorBorderSecondary,
      "--border-strong": token.colorBorder,
      "--text": token.colorText,
      "--muted": token.colorTextSecondary,
      "--blue": token.colorPrimary,
      "--blue-soft": token.colorPrimaryBg,
      "--selected": token.controlItemBgActive,
      "--hover": token.colorFillTertiary,
      "--amber": token.colorWarningText,
      "--amber-bg": token.colorWarningBg,
    };
    Object.entries(values).forEach(([k, v]) =>
      document.documentElement.style.setProperty(k, v),
    );
  }, [token]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
      if (e.ctrlKey && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setCollapsed((v) => !v);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const navigate = (id: string) => {
    if (["records", "sites", "health", "help"].includes(id)) setPanel(id);
    else setPage(id);
    setSearchOpen(false);
    setSearch("");
  };
  return (
    <div
      className={`review-app shell ${dark ? "dark" : ""} ${comfortable ? "comfortable" : ""}`}
    >
      <header className="global-header">
        <div className="wordmark">
          <span className="brand-glyph">E</span>
          <strong>EMPIRE</strong>
          <span className="wordmark-divider" />
          <span className="muted">研究工作空间</span>
        </div>
        <nav className="global-navigation" aria-label="主导航">
          <button aria-current={!observing ? "page" : undefined} onClick={() => navigate("tasks")}>
            <ClockCircleOutlined />
            采集管理
          </button>
          <button aria-current={observing ? "page" : undefined} onClick={() => navigate("observation")}><FundOutlined />市场观察</button>
          <button onClick={() => navigate("help")}><QuestionCircleOutlined />说明文档</button>
        </nav>
        <div className="global-tools">
          <button
            className="command-trigger"
            onClick={() => setSearchOpen(true)}
          >
            <SearchOutlined />
            <span>搜索功能</span>
            <kbd>Ctrl K</kbd>
          </button>
          <Tag className="design-badge">{observing ? "市场观察" : "采集管理"}</Tag>
          <Tooltip title={dark ? "切换浅色" : "切换深色"}>
            <Button
              type="text"
              aria-label="切换主题"
              icon={dark ? <SunOutlined /> : <MoonOutlined />}
              onClick={onTheme}
            />
          </Tooltip>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "density",
                  label: comfortable ? "切换紧凑密度" : "切换舒适密度",
                },
                { key: "health", label: "运行状态" },
                { key: "exit", label: "正常退出" },
              ],
              onClick: ({ key }) =>
                key === "exit"
                  ? window.empire.close()
                  : key === "density"
                    ? setComfortable(!comfortable)
                    : navigate(key),
            }}
          >
            <Button
              type="text"
              aria-label="界面与运行设置"
              icon={<SettingOutlined />}
            />
          </Dropdown>
          <Button
            type="text"
            aria-label="使用说明"
            icon={<QuestionCircleOutlined />}
            onClick={() => navigate("help")}
          />
        </div>
      </header>
      <div className={`review-body ${collapsed ? "rail-mode" : ""}`}>
        <aside className="context-sidebar" aria-label={observing ? "市场观察菜单" : "采集管理菜单"}>
          <div className="sidebar-title">
            <strong>{observing ? "市场观察" : "采集管理"}</strong>
            <Button
              type="text"
              aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
            />
          </div>
          {!collapsed && observing && (
            <nav className="sidebar-scroll" aria-label="观察功能">
              <div className="sidebar-section">观察工具</div>
              {observationPages.map(([id, name]) => <button key={id} className={`context-item ${page === id ? "active" : ""}`} aria-current={page === id ? "page" : undefined} onClick={() => navigate(id)}>{id === "observation" ? <CalendarOutlined /> : <FileTextOutlined />}<span>{name}</span></button>)}
            </nav>
          )}
          {!collapsed && !observing && (
            <div className="sidebar-scroll">
              <div className="sidebar-section">任务视图</div>
              {[
                ["tasks", "采集任务", counts.data?.total],
                ["archived", "已归档任务", archived.data?.total],
              ].map(([id, name, count]) => (
                <button
                  key={String(id)}
                  className={`context-item ${page === id ? "active" : ""}`}
                  onClick={() => navigate(String(id))}
                >
                  <span>{name}</span>
                  <span className="count">{count ?? "—"}</span>
                </button>
              ))}
              <div className="sidebar-section">运行与配置</div>
              {[
                ["sites", "站点访问规则"],
                ["exits", "采集出口"],
                ["identities", "身份管理"],
                ["resources", "共享资源"],
              ].map(([id, name]) => (
                <button
                  key={id}
                  className={`context-item ${page === id ? "active" : ""}`}
                  onClick={() => navigate(id)}
                >
                  <span>{name}</span>
                </button>
              ))}
            </div>
          )}
        </aside>
        <main className="main-workspace">
          {!status.online && (
            <Alert
              className="connection-notice"
              type="warning"
              title={status.status}
              showIcon
            />
          )}
          {status.closing && (
            <Alert
              type="info"
              title="正在正常关闭"
              description={status.status}
            />
          )}
          <div
            className="screen-container"
            hidden={page !== "tasks" && page !== "archived"}
          >
            <Tasks
              active={page === "tasks" || page === "archived"}
              archived={page === "archived"}
              onPage={navigate}
            />
          </div>
          {page === "observation" && <div className="screen-container observation-container"><ObservationCalendar /></div>}
          {page === "market_review" && <div className="screen-container observation-container"><Suspense fallback={<Spin />}><DailyReview /></Suspense></div>}
          {!["tasks", "archived", "observation", "market_review"].includes(page) && (
            <div className="screen-container">
              <Management page={page} onNavigate={navigate} />
            </div>
          )}
        </main>
      </div>
      <footer className="review-statusbar">
        <span>
          <span className="design-dot" />
          {commands.pending ? (
            <>
              <Spin size="small" /> {commands.pending} 个操作处理中
            </>
          ) : status.online ? (
            "已连接本地服务"
          ) : (
            status.status
          )}
        </span>
        <span className="command-message" title={commands.message}>
          {commands.message}
        </span>
        <span className="flex-gap" />
        <span>北京时间</span>
        <span>Ctrl K 搜索 · Ctrl B 侧栏</span>
      </footer>
      <Drawer
        className="task-context-drawer"
        open={!!panel}
        title={destinations.find((r) => r[0] === panel)?.[1]}
        size="min(1240px,95vw)"
        onClose={() => setPanel("")}
      >
        {panel === "help" ? <Help /> : panel === "records" ? (
          <Records />
        ) : (
          panel && <Management page={panel} onNavigate={navigate} />
        )}
      </Drawer>
      <Modal
        className="command-modal"
        open={searchOpen}
        onCancel={() => setSearchOpen(false)}
        footer={null}
        closable={false}
        width={620}
        afterOpenChange={(open) => open && searchRef.current?.focus()}
      >
        <Input
          ref={searchRef}
          size="large"
          prefix={<SearchOutlined />}
          aria-label="全局功能搜索"
          placeholder="搜索功能名称…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="command-caption">功能入口</div>
        <div className="command-results">
          {destinations
            .filter((r) => r[1].includes(search))
            .map(([id, name]) => (
              <button key={id} onClick={() => navigate(id)}>
                <FileTextOutlined />
                <span>{name}</span>
                <small>{observationPages.some(([pageId]) => pageId === id) ? "市场观察" : "采集管理"}</small>
                <ArrowRightOutlined />
              </button>
            ))}
        </div>
      </Modal>
    </div>
  );
}
