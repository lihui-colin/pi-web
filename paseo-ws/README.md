# Paseo HTTPS 部署

首次部署时，在仓库根目录执行以下命令初始化配置；已有配置不要覆盖：

```bash
install -d -m 700 paseo-ws/data/.paseo
cp -n paseo-ws/paseo.conf.example paseo-ws/data/paseo.conf
cp -n paseo-ws/config.json.example paseo-ws/data/.paseo/config.json
chmod 600 paseo-ws/data/paseo.conf paseo-ws/data/.paseo/config.json
```

`paseo.conf.example` 为访问配置模板，只包含 `ip` 和 `port`。按实际地址修改 `data/paseo.conf`，并在 `data/tls/<ip>/` 中提供对应证书及私钥（IPv6 目录名将冒号替换为下划线）。`config.json.example` 提供官方配置初始值，代理认证需另行完成。

- 安装：`./paseo-ws/install.sh`。安装本地 Paseo CLI 和 Nginx，不启停服务。
- 管理：`./paseo-ws/paseo_web_run.sh start|stop|status`。
- `start` 或 `start --proxy`：启用 Nginx HTTPS，外部 `https://10.30.0.25:25227/`，后端 `127.0.0.1:25226`。
- `start --no-proxy`：不启动 Nginx，Paseo 直接监听 `0.0.0.0:25227`，访问 `http://10.30.0.25:25227/`。
- 切换模式必须先 `stop`；两个模式共用同一数据目录。HTTP 与 HTTPS 的浏览器主机记录独立，但服务端项目不变。
- `reload-proxy`：仅校验并重载 Nginx 配置，不重启 Paseo 后端；现有 WebSocket 可能短暂重连。
- HTTPS 手机诊断页面：`https://10.30.0.25:25227/_paseo-check`。临时访问日志位于 `data/nginx/access-diagnostic.log`，不记录查询参数和 Cookie。
- 访问配置：`data/paseo.conf`（JSON），仅包含 `ip` 和 `port`，当前为 `{"ip":"10.30.0.25","port":25227}`。修改后在安全时机重新启动以应用；HTTPS 后端固定监听 `127.0.0.1:25226`。
- Paseo 官方数据目录（`PASEO_HOME`）为 `data/.paseo/`；完整配置保存在 `data/.paseo/config.json` 中，保留代理等设置；启动时按访问配置更新监听地址并启用 Web UI。`nginx.conf.template` 用于生成代理配置及证书路径。
- `data/` 和 `runtime/` 为本机数据与运行环境，不纳入 Git；取消跟踪不会删除磁盘文件。
- 代理配置：`data/nginx.conf`；代理日志和 PID 在 `data/nginx/`。
- 证书使用本目录 `data/tls/10.30.0.25/fullchain.pem` 和 `privkey.pem`。TLS 目录为独立副本，后续证书更新需单独维护；运行和安装均不读取其他服务目录。
- 安装器调用本目录 `paseo_nginx_install.sh`，从固定版本官方源码构建到 `runtime/nginx`，校验 SHA-256 并保留许可证；下载与临时构建目录位于 `runtime` 内。已有本地 Nginx 校验后复用，不自动升级。
- 首次构建需要 `cc`、`make`、`perl`、`curl`、`tar`、Python 3，默认 4 个并行任务，可用 `PASEO_NGINX_BUILD_JOBS` 调整。`bash paseo-ws/paseo_nginx_install.sh --dry-run` 仅显示安装计划，不下载、不修改文件、不启停服务。

## 从旧数据目录迁移

`data/paseo.conf`、`data/tls/`、`data/nginx.conf`、`data/nginx/` 和诊断页面继续留在原处。官方的配置、会话、身份与密钥、认证、模型、项目、调度和 daemon 日志迁入 `data/.paseo/`，不改变代理任务的项目目录。

已有旧实例时不要按首次部署步骤创建新配置。在独立于 Paseo 服务的终端中执行：

```bash
bash paseo-ws/paseo_web_run.sh migrate-home
```

命令先检查目标冲突及所有目录的会话（包含后台和归档会话）；有运行中、初始化中或状态不明的会话时直接退出，不停止服务。检查通过后启动独立维护进程，再次检查并通过管理脚本停止旧服务、移动数据、启动新服务。维护期间持有部署目录的同一把服务锁；服务切换会断开连接中的客户端。

进度和恢复信息在 `data/home-migration.json`，日志在 `data/home-migration.log`，原官方配置备份在 `data/home-migration.config-backup`。目标已有内容时拒绝覆盖。普通失败会停止新实例、将已移动条目恢复原位，并在原实例此前运行时恢复旧服务；恢复失败或进程被强制终止时，按进度文件检查实际路径，确认服务停止后再恢复，禁止覆盖已有文件。

迁移前 `status` 和 `stop` 仍管理旧实例；`start` 和 `set-password` 会提示先迁移，避免创建空实例。完成后所有官方 CLI 操作使用 `--home paseo-ws/data/.paseo`。

## 手机首次连接兼容补丁

手机诊断显示 HTTPS 与 WebSocket 可用，但握手耗时约 7–10 秒。Paseo 0.14.0 首次主机探测只等待 2500ms，已保存主机的常规连接探测又只等待 6000ms；因此仅修复首次探测后，刷新仍可能连续失败。`patch-web-ui.cjs` 将首次探测、后续 TLS 直连探测及对应底层客户端等待时间统一到 20000ms，并生成新内容哈希资源地址避免旧缓存。HTTP 常规探测保持原逻辑。安装脚本自动应用；上游结构变化时明确报错。已使用实际探测模块模拟 9734ms 延迟，确认原逻辑失败、新 TLS 逻辑成功；最终仍需手机刷新确认。临时应用诊断可用 `PASEO_DIAGNOSTICS=1 node paseo-ws/patch-web-ui.cjs` 启用，不设置该变量重新执行即可移除。

补丁基准记录在 `patch-web-ui.baseline.json`：上游 `v0.14.0`，commit [`8c6de842a3157530c26a7a94c78a3d647fb96ce9`](https://github.com/getpaseo/paseo/commit/8c6de842a3157530c26a7a94c78a3d647fb96ce9)（依据上游发布标签核对）。执行补丁时检查已安装 `@getpaseo/server` 的版本和 `gitHead`：版本或 commit 不匹配时向标准错误输出 `[WARN]`；包未提供 `gitHead` 时明确警告无法核对 commit，不将版本匹配视为 commit 已验证。警告后继续现有资源结构检查，结构不匹配仍报错退出。确认新版本兼容后再更新补丁和基准记录；不会自动更新基准。

## 切换记录及恢复

HTTPS 切换前，Paseo 监听 `0.0.0.0:25227`；已检查一个 idle 会话，无运行中的代理任务。当前操作会话运行在 DSH，不在 Paseo。

切换失败时先检查 `data/nginx/error.log` 和 `data/.paseo/daemon.log`，使用管理脚本 `stop` 停止此实例，修正配置后再 `start`。不要重启 DSH。已有 Paseo 会话数据迁移后保存在 `data/.paseo/` 中。

停止服务会断开已连接客户端；执行前检查是否有运行中的任务。配置修改后需要重启时，先 stop 再 start。
