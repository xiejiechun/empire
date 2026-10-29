import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntApp, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./foundation.css";
import "./collection-layout.css";
import "./style.css";
function Root() {
  const [dark, setDark] = React.useState(false);
  return (
    <ConfigProvider
      locale={zhCN}
      componentSize="small"
      theme={{
        algorithm: [
          dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
          (seed, map) => ({
            ...theme.compactAlgorithm(seed, map),
            fontSize: 13,
            fontSizeSM: 12,
            controlHeight: 30,
            controlHeightSM: 28,
            lineHeight: 1.5,
          }),
        ],
        token: {
          fontSize: 13,
          borderRadius: 5,
          fontFamily: '"Segoe UI", "Microsoft YaHei UI", sans-serif',
        },
        components: {
          Table: {
            cellPaddingBlockSM: 4,
            cellPaddingInlineSM: 12,
            cellPaddingBlockMD: 8,
            cellFontSizeSM: 13,
            headerBorderRadius: 0,
          },
          Button: { fontWeight: 400 },
          Tabs: { horizontalMargin: "0" },
        },
      }}
    >
      <AntApp>
        <App dark={dark} onTheme={() => setDark(!dark)} />
      </AntApp>
    </ConfigProvider>
  );
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
