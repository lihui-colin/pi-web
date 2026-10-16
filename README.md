# PI WEB 定制补丁

本仓库按两个独立分支维护：

- [`main`](https://github.com/lihui-colin/pi-web/tree/main)：完整的官方上游代码与历史，可独立维护；安装不依赖该分支的位置。
- `terminal-patch`：只有定制补丁、安装脚本、文档和测试，不继承上游历史。保留官方 Chat 与 Workspace Panel 布局，提供终端修复和 Codex 插件等扩展。

需要 Git、Node.js ≥22.19 和 npm。补丁与 `patches/base-commit` 中的完整上游 commit ID 绑定，获取源码不需要 origin 的推送权限。

```bash
git clone --branch terminal-patch git@github.com:lihui-colin/pi-web.git pi-web-opt
cd pi-web-opt
sh scripts/sync.sh  # 获取 patches/base-commit 指定的上游提交
sh scripts/install.sh
```

安装脚本使用本地缓存的 `patches/base-commit` 指定提交，在独立目录应用补丁、安装依赖并测试构建，成功后将全局 `pi-web`、`pi-web-server` 和 `pi-web-sessiond` 命令链接到新版本，最后打印安装目录。若 PATH 中没有 `pi` 命令，会自动全局安装 Pi Agent（默认 `latest`，可用 `PI_VERSION` 指定）；已有 Agent 保留当前版本。它不同步远端、不注册或启动后台服务。已运行的服务需要手动先停止再启动才能使用新版本。不再提供 Swap Chat / Workspace Panel 命令，旧的浏览器布局交换偏好不再生效。

详细的同步、冲突处理和补丁维护方法见 [使用文档](docs/usage.md)。

终端补丁还会在裁剪回放缓存时保留鼠标跟踪、备用屏幕及粘贴等模式，修复 Codex CLI 长时间运行后刷新页面无法滚动历史的问题。更新后需要重启 `pi-web-sessiond`，再新建终端并用 `codex resume` 恢复会话；旧守护进程已经丢弃的状态无法补回。

安装时默认最多并行运行 4 个测试工作进程，单个测试时限为 30 秒，避免大量并发构建引发超时。可用 `PI_WEB_TEST_MAX_WORKERS` 和 `PI_WEB_TEST_TIMEOUT_MS` 覆盖，例如 `PI_WEB_TEST_MAX_WORKERS=2 PI_WEB_TEST_TIMEOUT_MS=60000 bash scripts/install.sh`。测试失败仍会中止安装，保留原有全局版本。

运行脚本支持 `bash scripts/pi-web-run-jmfederico.sh update`：更新 Pi Agent 到 latest、将官方 main 最新提交写入 patches/base-commit、应用补丁并测试构建安装，不启停服务。只更新 Agent 可加 `--pi-only`，只更新补丁版 pi-web 可加 `--web-only`，预览可加 `--dry-run`。

## 手动启动与管理服务

安装完成后，可使用 [`scripts/pi-web-run-jmfederico.sh`](scripts/pi-web-run-jmfederico.sh) 管理服务，适用于容器、WSL 或没有 systemd user 总线的环境。脚本通过 `nohup` 后台启动 `pi-web-sessiond` 和 `pi-web-server`，需要这两个命令已在 PATH 中，并使用 `curl` 探测 HTTP 状态。

在仓库根目录执行：

```bash
bash scripts/pi-web-run-jmfederico.sh start               # 启动，默认端口 8024
bash scripts/pi-web-run-jmfederico.sh status              # 查看进程和 HTTP 状态
bash scripts/pi-web-run-jmfederico.sh logs                # 跟随日志，Ctrl+C 退出查看
bash scripts/pi-web-run-jmfederico.sh stop                # 停止两个服务
bash scripts/pi-web-run-jmfederico.sh stop --port 8080   # 停止 8080 实例
bash scripts/pi-web-run-jmfederico.sh start --port 8080  # 启动 8080 实例
bash scripts/pi-web-run-jmfederico.sh status --port 8080  # 探测指定端口
bash scripts/pi-web-run-jmfederico.sh --help              # 查看完整帮助
```

默认监听 `0.0.0.0:8024`，本机访问 <http://localhost:8024>，其他设备使用服务器地址访问。可通过环境变量配置：

| 配置 | 说明 |
| --- | --- |
| `PI_WEB_HOST` | 绑定地址，默认 `0.0.0.0`；仅供本机访问可设为 `127.0.0.1` |
| `PI_WEB_PORT` | 监听端口，默认 `8024`；命令行 `--port` 优先 |
| `PI_WEB_DATA_DIR` | 状态目录，默认仓库 `data/pi-web/<port>/state` |
| `PI_WEB_RUN_DIR` | 日志和 PID 目录，默认仓库 `data/pi-web/<port>` |
| `PI_WEB_SESSIOND_SOCKET` | 默认 `<状态目录>/sessiond.sock` |
| `PI_WEB_PASSWORD` | 传给服务的访问密码，是否生效取决于所安装版本的支持情况 |

```bash
PI_WEB_HOST=127.0.0.1 PI_WEB_PORT=8080 bash scripts/pi-web-run-jmfederico.sh start
```

配置不会自动保存；后续 `stop`、`start` 和 `status` 命令应传入相同配置，或提前 `export` 环境变量。服务运行时修改配置需要先执行 `stop`，再执行 `start`。

默认按端口隔离实例，状态、socket、日志和 PID 文件全部保存在仓库 `data/pi-web/<port>/` 下，不再使用 `~/.pi-web/`。例如可以同时运行：

```bash
bash scripts/pi-web-run-jmfederico.sh start --port 8424
bash scripts/pi-web-run-jmfederico.sh start --port 8425
bash scripts/pi-web-run-jmfederico.sh stop --port 8424  # 只停止 8424
```

`start`、`stop`、`status`、`logs` 和 `update` 都按端口选择实例；不传端口时选择 `PI_WEB_PORT` 或默认的 8024。例外：`stop` 未指定 `--port`、`PI_WEB_PORT` 或 `PI_WEB_RUN_DIR` 时，若 `data/pi-web` 下只有一个有效端口实例目录，就自动停止该实例；没有或存在多个实例时仍使用默认 8024。`stop --port 8425` 只停止 8425 实例。显式设置状态或端点环境变量会覆盖隔离默认值，因此多实例时不要让这些变量指向同一目录或端点（包括 `PI_WEB_SESSIOND_PORT` 和 `PI_WEB_SESSIOND_URL`）。

`stop` 会等待进程退出，必要时强制结束，确认退出后才删除 PID 文件；停止失败会保留 PID 文件并报错。Linux 下即使 PID 文件丢失或过期，也会按服务命令及 `PI_WEB_RUN_DIR` 找回本实例的遗留进程。`start` 会先检查端口，端口被占用时不会启动新的 sessiond。

`logs` 默认跟随实例目录中的 `server.log`，不存在时跟随 `sessiond.log`；每次启动对应进程时会覆盖其日志。原先的 `~/.pi-web/` 状态和 `data/pi-web/*.pid` 不会自动迁移或接管，旧实例需通过原管理方式停止。更新会替换全局程序版本；运行脚本的 update 不启停服务。

该脚本也负责更新：

```bash
bash scripts/pi-web-run-jmfederico.sh update --dry-run    # 预览更新
bash scripts/pi-web-run-jmfederico.sh update --port 8080  # 更新指定端口配置对应的程序，不启停服务
bash scripts/pi-web-run-jmfederico.sh update --web-only   # 只更新补丁版 pi-web
bash scripts/pi-web-run-jmfederico.sh update --pi-only    # 只更新 Pi Agent
```

运行脚本的 `update` 负责更新，不启停服务。更新后需要生效时，手动执行同一端口的 `stop`、`start`。默认升级 Pi Agent 到 latest、获取官方 main 最新提交并写入 `patches/base-commit`，然后构建安装补丁版 pi-web。`PI_VERSION` 仅用于首次 install 补装 Agent。`--update-relay` 同步升级全局 relay skill。`update` 自动跟随官方 `main`；补丁冲突时停止并保留新基线和现场，需要适配补丁后重试。`--dry-run` 不改写基线。

新增独立 **Codex** 插件，可在 Terminal 后打开 Codex 对话、恢复历史并处理审批。安装前置条件和使用限制见 [Codex 插件说明](docs/codex-usage.md)。
