# PI WEB 桌面布局补丁

本仓库按两个独立分支维护：

- [`main`](https://github.com/lihui-colin/pi-web/tree/main)：完整的官方上游代码与历史，保持与 `jmfederico/pi-web/main` 同步。
- `terminal-patch`：只有布局补丁、安装脚本、文档和测试，不继承上游历史。补丁让桌面的 Chat 与 Workspace Panel 交换位置，并保存浏览器偏好。

需要 Git、Node.js ≥22.19 和 npm。同步上游时需要对 origin 的 Git 推送权限，本地安装不需要。

```bash
git clone --branch terminal-patch git@github.com:lihui-colin/pi-web.git pi-web-opt
cd pi-web-opt
sh scripts/sync.sh  # 首次初始化 main，或同步最新上游
sh scripts/install.sh
```

安装脚本使用本地 `main`，在独立目录应用补丁、安装依赖并测试构建，成功后将全局 `pi-web`、`pi-web-server` 和 `pi-web-sessiond` 命令链接到新版本，最后打印安装目录。它不更新 Pi Agent、不同步远端、不注册或启动后台服务。已运行的服务需要手动重启才能使用新版本。程序启动后，在命令面板中选择 **Swap Chat / Workspace Panel** 切换布局。此操作仅在 Main 和右侧 Panel 并排的宽屏布局（>1180px）可用；窄屏继续使用工具标签切换，Swap 禁用且不会改变桌面布局偏好。

详细的同步、冲突处理和补丁维护方法见 [使用文档](docs/usage.md)。

统一入口支持 `bash scripts/install.sh update`：更新 Pi Agent、同步官方 pi-web 源码、应用补丁并测试构建安装，按选项重启服务。只更新 Agent 可加 `--pi-only`，只更新补丁版 pi-web 可加 `--web-only`，预览可加 `--dry-run`。
