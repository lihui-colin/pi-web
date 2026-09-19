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

安装脚本使用本地 `main`，在独立目录应用补丁、安装依赖并测试构建，成功后将全局 `pi-web`、`pi-web-server` 和 `pi-web-sessiond` 命令链接到新版本，最后打印安装目录。若 PATH 中没有 `pi` 命令，会自动全局安装 Pi Agent（默认 `latest`，可用 `PI_VERSION` 指定）；已有 Agent 保留当前版本。它不同步远端、不注册或启动后台服务。已运行的服务需要手动重启才能使用新版本。程序启动后，在命令面板中选择 **Swap Chat / Workspace Panel** 切换布局。此操作仅在 Main 和右侧 Panel 并排的宽屏布局（>1180px）可用；窄屏继续使用工具标签切换，Swap 禁用且不会改变桌面布局偏好。

详细的同步、冲突处理和补丁维护方法见 [使用文档](docs/usage.md)。

统一入口支持 `bash scripts/install.sh update`：更新 Pi Agent、同步官方 pi-web 源码、应用补丁并测试构建安装，按选项重启服务。只更新 Agent 可加 `--pi-only`，只更新补丁版 pi-web 可加 `--web-only`，预览可加 `--dry-run`。

## 手动启动与管理服务

安装完成后，可使用 [`scripts/pi-web-run-jmfederico.sh`](scripts/pi-web-run-jmfederico.sh) 管理服务，适用于容器、WSL 或没有 systemd user 总线的环境。脚本通过 `nohup` 后台启动 `pi-web-sessiond` 和 `pi-web-server`，需要这两个命令已在 PATH 中，并使用 `curl` 探测 HTTP 状态。

在仓库根目录执行：

```bash
bash scripts/pi-web-run-jmfederico.sh start               # 启动，默认端口 8024
bash scripts/pi-web-run-jmfederico.sh status              # 查看进程和 HTTP 状态
bash scripts/pi-web-run-jmfederico.sh logs                # 跟随日志，Ctrl+C 退出查看
bash scripts/pi-web-run-jmfederico.sh stop                # 停止两个服务
bash scripts/pi-web-run-jmfederico.sh restart --port 8080 # 重启并使用指定端口
bash scripts/pi-web-run-jmfederico.sh status --port 8080  # 探测指定端口
bash scripts/pi-web-run-jmfederico.sh --help              # 查看完整帮助
```

默认监听 `0.0.0.0:8024`，本机访问 <http://localhost:8024>，其他设备使用服务器地址访问。可通过环境变量配置：

| 配置 | 说明 |
| --- | --- |
| `PI_WEB_HOST` | 绑定地址，默认 `0.0.0.0`；仅供本机访问可设为 `127.0.0.1` |
| `PI_WEB_PORT` | 监听端口，默认 `8024`；命令行 `--port` 优先 |
| `PI_WEB_PASSWORD` | 传给服务的访问密码，是否生效取决于所安装版本的支持情况 |

```bash
PI_WEB_HOST=127.0.0.1 PI_WEB_PORT=8080 bash scripts/pi-web-run-jmfederico.sh start
```

配置不会自动保存；后续 `restart`、`status` 和涉及重启的 `update` 命令应传入相同配置，或提前 `export` 环境变量。服务运行时修改配置需要执行 `restart`。

日志和 PID 文件保存在仓库的 `data/pi-web/` 目录。`logs` 默认跟随 `server.log`，不存在时跟随 `sessiond.log`；排查会话守护进程可直接查看 `data/pi-web/sessiond.log`。每次启动对应进程时会覆盖其日志。

该脚本也可调用统一更新入口：

```bash
bash scripts/pi-web-run-jmfederico.sh update --dry-run    # 预览更新
bash scripts/pi-web-run-jmfederico.sh update --port 8080  # 更新，并使用指定端口重启原本运行的服务
bash scripts/pi-web-run-jmfederico.sh update --web-only   # 只更新补丁版 pi-web
bash scripts/pi-web-run-jmfederico.sh update --pi-only    # 只更新 Pi Agent
```

`update` 转交给 `scripts/install.sh update`，默认升级 Pi Agent、同步上游并构建安装补丁版 pi-web；可用 `PI_VERSION` 指定 Agent 版本。`--no-restart` 跳过重启，`--restart` 在服务原先未运行时也启动，`--update-relay` 同步升级全局 relay skill。同步上游仍需要 origin 的 Git 推送权限。
