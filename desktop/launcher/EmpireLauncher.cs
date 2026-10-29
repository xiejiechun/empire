using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

internal static class EmpireLauncher
{
    // Quote one Windows command-line argument, including trailing backslashes.
    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char ch in value)
        {
            if (ch == '\\') { slashes++; continue; }
            if (ch == '"')
                result.Append('\\', slashes * 2 + 1).Append(ch);
            else
                result.Append('\\', slashes).Append(ch);
            slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }

    [STAThread]
    private static int Main()
    {
        Application.EnableVisualStyles();
        try
        {
            string program = AppDomain.CurrentDomain.BaseDirectory;
            string root = Path.GetFullPath(Path.Combine(program, "..", ".."));
            string desktop = Path.Combine(root, "desktop");
            string electron = Path.Combine(desktop, "node_modules", "electron", "dist", "electron.exe");
            string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
            string config = Path.Combine(program, "config.toml");
            foreach (string file in new string[] { electron, python, config,
                Path.Combine(desktop, "dist", "index.html"),
                Path.Combine(desktop, "electron", "main.cjs") })
            {
                if (!File.Exists(file))
                    throw new InvalidOperationException("缺少启动文件：" + file +
                        "\n\n这是本机启动版，请保留 dist\\EmpireDesktop 与项目目录的相对位置。");
            }
            var start = new ProcessStartInfo(electron,
                Quote(desktop) + " " + Quote("--empire-config=" + config));
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.EnvironmentVariables.Remove("ELECTRON_RUN_AS_NODE");
            using (Process child = Process.Start(start))
            {
                if (child == null)
                    throw new InvalidOperationException("无法启动新版桌面。");
                if (child.WaitForExit(1200) && child.ExitCode != 0)
                    throw new InvalidOperationException("新版桌面未能启动，退出码：" + child.ExitCode);
            }
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Empire 新版启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
