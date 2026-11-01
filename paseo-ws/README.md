# Paseo 部署

## 安装与配置

运行 `bash paseo-ws/install.sh` 安装本地 CLI、Nginx 并应用 Web UI 补丁；安装不启停服务。Nginx 从固定版本源码构建，校验 SHA-256 并保留许可证，已有安装校验后复用。首次构建需要 `cc`、`make`、`perl`、`curl`、`tar`、Python 3；`PASEO_NGINX_BUILD_JOBS` 默认 4。可用 `bash paseo-ws/paseo_nginx_install.sh --dry-run` 查看安装计划。

首次部署时初始化配置，已有文件不要覆盖：

```bash
install -d -m 700 paseo-ws/data/.paseo
cp -n paseo-ws/paseo.conf.example paseo-ws/data/paseo.conf
cp -n paseo-ws/config.json.example paseo-ws/data/.paseo/config.json
chmod 600 paseo-ws/data/paseo.conf paseo-ws/data/.paseo/config.json
```

- `data/paseo.conf`：只包含访问地址 `ip` 和 `port`，默认 `10.30.0.25:25227`。
- `data/.paseo/`：官方数据目录（`PASEO_HOME`），包含完整配置 `config.json`、会话、认证、模型和 daemon 日志。代理 CLI 需另行安装并认证；任务工作目录由会话指定。
- `data/tls/<ip>/`：独立维护的 `fullchain.pem` 与 `privkey.pem`，IPv6 目录名将冒号替换为下划线。
- `data/nginx.conf`：由 `nginx.conf.template` 生成；Nginx 日志、PID 和临时文件在 `data/nginx/`。
- `data/`、`runtime/` 和 `.npm-cache/` 不纳入 Git；运行和安装不依赖其他服务目录。

## 服务管理

```bash
bash paseo-ws/paseo_web_run.sh start             # Nginx HTTPS，后端 127.0.0.1:25226
bash paseo-ws/paseo_web_run.sh start --no-proxy  # HTTP，直接监听配置端口
bash paseo-ws/paseo_web_run.sh status
bash paseo-ws/paseo_web_run.sh set-password
bash paseo-ws/paseo_web_run.sh reload-proxy      # 校验并重载 Nginx
bash paseo-ws/paseo_web_run.sh stop
```

默认访问 `https://10.30.0.25:25227/`；无代理模式使用 HTTP。切换模式先停止再启动。停止服务会断开客户端，重载代理可能触发 WebSocket 重连，操作前检查活跃会话和运行任务；依赖本服务的会话应由独立维护进程完成启停与就绪检查。

旧数据已迁入 `data/.paseo/`，迁移工具和临时诊断已移除。故障时检查 `data/nginx/error.log`、`data/.paseo/daemon.log`；勿重启其他服务。

## Web UI 补丁

`patch-web-ui.cjs` 将首次连接探测和后续 TLS 连接等待时间调整为 20 秒，修复手机慢连接超时；生成新哈希资源地址，保留原 JS。安装时自动执行，也可运行 `node paseo-ws/patch-web-ui.cjs` 后刷新网页，无需重启。

`patch-web-ui.baseline.json` 记录适用版本 `v0.14.0` 及上游 commit [`8c6de842a3157530c26a7a94c78a3d647fb96ce9`](https://github.com/getpaseo/paseo/commit/8c6de842a3157530c26a7a94c78a3d647fb96ce9)。版本、commit 不匹配或缺少 `gitHead` 时输出 `[WARN]`；资源结构不匹配时退出，不自动更新基准。适配新版本后应同步更新基准。

验证：`node --test paseo-ws/test-*.cjs`，测试使用临时目录与模拟服务，不启停线上服务。
