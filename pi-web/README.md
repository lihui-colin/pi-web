# PI WEB 定制补丁

Pi Web 的脚本、补丁、文档、测试和本地数据统一放在仓库的 `pi-web/` 目录。下文命令及相对路径均以该目录为基准；从仓库根操作前先执行 `cd pi-web`。

本仓库按两个独立分支维护：

- [`main`](https://github.com/lihui-colin/pi-web/tree/main)：完整的官方上游代码与历史，可独立维护；安装不依赖该分支的位置。
- `terminal-patch`：只有定制补丁、安装脚本、文档和测试，不继承上游历史。保留官方 Chat 与 Workspace Panel 布局，提供终端修复和 Codex 插件等扩展。

需要 Git、Node.js ≥22.19 和 npm。补丁与 `patches/base-commit` 中的完整上游 commit ID 绑定，获取源码不需要 origin 的推送权限。

```bash
git clone --branch terminal-patch git@github.com:lihui-colin/pi-web.git pi-web-opt
cd pi-web-opt/pi-web
sh scripts/install.sh
```

安装脚本先执行 `sync.sh`，优先复用 `data/pi-web-upstream.git` 中的缓存，仅在缺少 `patches/base-commit` 指定提交时下载，再在 `data/pi-web-releases/release.*` 独立目录应用补丁、安装依赖并测试构建，成功后将全局 `pi-web`、`pi-web-server` 和 `pi-web-sessiond` 命令链接到新版本，最后打印安装目录。若 PATH 中没有 `pi` 命令，会自动全局安装 Pi Agent（默认 `latest`，可用 `PI_VERSION` 指定）；已有 Agent 保留当前版本。它不注册或启动后台服务。已运行的服务需要手动先停止再启动才能使用新版本。不再提供 Swap Chat / Workspace Panel 命令，旧的浏览器布局交换偏好不再生效。

`data/` 已被 Git 忽略。可单独运行 `sh scripts/sync.sh` 同步并准备源码；`--local` 仅使用 `data/pi-web-upstream.git` 缓存。`PI_WEB_INSTALL_ROOT` 可覆盖构建安装目录，Git 下载缓存仍保存在 `data/`。运行中的版本依赖对应 release 目录，请勿删除。

补丁按主服务和插件归档：`patches/service/` 保存主服务补丁，`patches/plugins/<插件>/` 保存插件补丁。按编号保留 4 组功能：`plugins/terminal/0001-terminal.patch` 和 `service/0001-clipboard.patch` 包含终端及主服务剪贴板修复与增强，`0006-codex-panel.patch` 包含完整 Codex 插件、Codex / Files 共用公式渲染及历史图片渲染，`service/0007-workspace.patch`、`plugins/files/0007-files-panel.patch`、`plugins/git/0007-git-panel.patch` 分别包含主服务工作区、Files 和 Git 面板调整。`0008-test-isolation.patch` 禁止网站单元测试加载外部 CSS/脚本，避免网络不可用时安装测试挂起。保留主要分组编号，跨目录按文件名的全局数字顺序应用。详细的同步、冲突处理和补丁维护方法见 [使用文档](docs/usage.md)。

终端补丁还会在裁剪回放缓存时保留鼠标跟踪、备用屏幕及粘贴等模式，修复 Codex CLI 长时间运行后刷新页面无法滚动历史的问题。更新后需要重启 `pi-web-sessiond`，再新建终端并用 `codex resume` 恢复会话；旧守护进程已经丢弃的状态无法补回。

安装时默认最多并行运行 4 个测试工作进程，单个测试时限为 30 秒，避免大量并发构建引发超时。可用 `PI_WEB_TEST_MAX_WORKERS` 和 `PI_WEB_TEST_TIMEOUT_MS` 覆盖，例如 `PI_WEB_TEST_MAX_WORKERS=2 PI_WEB_TEST_TIMEOUT_MS=60000 bash scripts/install.sh`。测试失败仍会中止安装，保留原有全局版本。安装测试会自动将 `localhost`、`127.0.0.1` 和 `::1` 加入大小写两种 `NO_PROXY` 环境变量，并保留已有例外；该调整仅作用于测试进程。

运行脚本支持 `bash scripts/pi-web-run-jmfederico.sh update`：更新 Pi Agent 到 latest、将官方 main 最新提交写入 patches/base-commit、应用补丁并测试构建安装，不启停服务。只更新 Agent 可加 `--pi-only`，只更新补丁版 pi-web 可加 `--web-only`，预览可加 `--dry-run`。

## 目录迁移与兼容链接

Pi Web 原位于仓库根的 `scripts/`、`patches/`、`tests/`、`docs/`、`README.md`、`优化.md`、`pi-web.conf.example`、`data/`、`.pi-web/` 和 `.pnpm-store/` 已统一移入 `pi-web/`。本文所说的 Pi Web 根目录是仓库内的 `pi-web/`，与 Git 仓库根目录不同。

以下迁移路径以 **Git 仓库根目录** 为基准：

- 根目录 `data` 和 `.pi-web` 兼容软链接已删除。实际数据、附件分别保存在 `pi-web/data/`、`pi-web/.pi-web/`；全局 Pi Web 安装链接直接指向新目录中的当前 release。
- Paseo 中遗留的 Pi Web 发布版本、旧配置、安装日志和维护记录，以及对应的 `paseo-ws/data/pi-web*` 软链接已清理，临时归档 `pi-web/data/legacy-paseo/` 不再保留。删除旧状态前已确认其文件与现有实例状态一致。
- 迁移验证生成的临时 release、验证日志和未使用的 `.pnpm-store/` 缓存已清理；保留当前安装版本、有效配置、实例状态、附件和上游 Git 缓存。

不再恢复根目录兼容链接。历史附件若记录了旧路径，应将引用更新到新位置；现有实例的 JSON 状态中未发现上述旧绝对路径。删除发布版本前仍需核查全局命令和运行进程的依赖。本次目录迁移及清理不重启服务；后续服务切换应先核对活跃会话并保存恢复信息，在允许中断时进行。

## 手动启动与管理服务

安装完成后，可使用 [`scripts/pi-web-run-jmfederico.sh`](scripts/pi-web-run-jmfederico.sh) 管理服务，适用于容器、WSL 或没有 systemd user 总线的环境。脚本通过 `nohup` 后台启动 `pi-web-sessiond` 和 `pi-web-server`，需要这两个命令已在 PATH 中，并使用 `curl` 探测 HTTP 状态。

在 Pi Web 根目录（仓库的 `pi-web/`，从仓库根先执行 `cd pi-web`）执行：

```bash
bash scripts/pi-web-run-jmfederico.sh start               # 启动，读取本地端口配置
bash scripts/pi-web-run-jmfederico.sh status              # 查看进程和 HTTP 状态
bash scripts/pi-web-run-jmfederico.sh logs                # 跟随日志，Ctrl+C 退出查看
bash scripts/pi-web-run-jmfederico.sh stop                # 停止两个服务
bash scripts/pi-web-run-jmfederico.sh restart             # 先停止，再启动两个服务
bash scripts/pi-web-run-jmfederico.sh --help              # 查看完整帮助
```

仓库提供配置模板 [`pi-web.conf.example`](pi-web.conf.example)。`install.sh` 会在 `data/pi-web.conf` 不存在时自动从模板创建，已有配置不会覆盖。也可手动创建：

```bash
mkdir -p data
cp -n pi-web.conf.example data/pi-web.conf
```

按需编辑 `data/pi-web.conf`（已被 Git 忽略，不提交到仓库），使用 Bash 赋值语法设置端口，例如：

```bash
PI_WEB_PORT=25224
```

所有管理命令都会自动读取该文件，与执行命令时的工作目录无关。服务端口、监听地址、密码和运行目录等配置均从文件读取，不接受 `--port` 参数或同名服务环境变量覆盖。缺少文件或字段时使用默认值；默认监听 `0.0.0.0:8024`。

| 配置 | 说明 |
| --- | --- |
| `PI_WEB_HOST` | 绑定地址，默认 `0.0.0.0`；仅供本机访问可设为 `127.0.0.1` |
| `PI_WEB_PORT` | 监听端口，默认 `8024` |
| `PI_WEB_VOICE_INPUT_ENABLED` | 语音输入入口开关，`true` / `false`，默认 `false`；麦克风按钮始终可见，关闭时禁用，当前开启时也暂不可用 |
| `PI_WEB_DATA_DIR` | 状态目录，默认 Pi Web 根目录下的 `data/pi-web/<port>/state` |
| `PI_WEB_RUN_DIR` | 日志和 PID 目录，默认 Pi Web 根目录下的 `data/pi-web/<port>` |
| `PI_WEB_SESSIOND_SOCKET` | 默认 `<状态目录>/sessiond.sock` |
| `PI_WEB_PASSWORD` | 传给服务的访问密码，是否生效取决于所安装版本的支持情况 |

配置文件也可填写模板中的更新设置，例如下载地址、安装目录和测试并发数。

修改端口或运行目录前，先执行 `stop`，再编辑 `data/pi-web.conf` 并执行 `start`；若已经修改配置，应先恢复原配置并停止旧服务，再切换到新配置。

默认按端口隔离实例，状态、socket、日志和 PID 文件保存在 Pi Web 根目录下的 `data/pi-web/<port>/` 下。`start`、`stop`、`restart`、`status`、`logs` 和 `update` 均使用当前配置，`stop` 不再自动选择其他端口的实例。

`restart` 先执行停止，成功后再启动；停止失败时不会启动新进程。服务未运行时也可以执行 `restart` 启动。 启动成功要求两个服务均为本实例的存活进程，且 HTTP 探测就绪；探测使用配置的监听地址（通配监听使用对应的回环地址），绕过代理并设置超时。

`stop` 会等待进程退出，必要时强制结束，确认退出后才删除 PID 文件；停止失败会保留 PID 文件并报错。Linux 下即使 PID 文件丢失或过期，也会按服务命令及 `PI_WEB_RUN_DIR` 找回本实例的遗留进程。`start` 会先检查端口，端口被占用时不会启动新的 sessiond。

`logs` 默认跟随实例目录中的 `server.log`，不存在时跟随 `sessiond.log`；每次启动对应进程时会覆盖其日志。原先的 `~/.pi-web/` 状态和 `data/pi-web/*.pid` 不会自动迁移或接管，旧实例需通过原管理方式停止。更新会替换全局程序版本；运行脚本的 update 不启停服务。

该脚本也负责更新：

```bash
bash scripts/pi-web-run-jmfederico.sh update --dry-run    # 预览更新
bash scripts/pi-web-run-jmfederico.sh update --web-only   # 只更新补丁版 pi-web
bash scripts/pi-web-run-jmfederico.sh update --pi-only    # 只更新 Pi Agent
```

运行脚本的 `update` 负责更新，不启停服务。更新后需要生效时，执行 `restart`（使用当前配置）。默认升级 Pi Agent 到 latest、获取官方 main 最新提交并写入 `patches/base-commit`，然后构建安装补丁版 pi-web。`PI_VERSION` 仅用于首次 install 补装 Agent。`--update-relay` 同步升级全局 relay skill。`update` 自动跟随官方 `main`；补丁冲突时停止并保留新基线和现场，需要适配补丁后重试。`--dry-run` 不改写基线。

新增独立 **Codex** 插件，可在 Terminal 后打开 Codex 对话、恢复历史并处理审批。安装前置条件和使用限制见 [Codex 插件说明](docs/codex-usage.md)。

语音识别目前仅保留 [实施计划](docs/语音识别.md) 和 [服务设计存档](docs/voice-service.md)，相关实现已移除。麦克风按钮始终可见；`data/pi-web.conf` 中的 `PI_WEB_VOICE_INPUT_ENABLED` 默认为 `false`，按钮禁用并提示语音输入已禁用；设为 `true` 时仍暂不可用，提示尚未实现。修改后需在允许中断会话时重新启动服务并刷新页面。
