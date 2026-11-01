# Paseo 部署

## 安装与配置

运行 `bash paseo-ws/install.sh` 安装本地 CLI、Nginx 并应用 Web UI 补丁；安装不启停服务。安装和服务管理均排除 Conda 环境的 Node/npm，即使它们可运行也不使用。选择顺序为显式 `PASEO_NODE_BIN`、项目 `runtime/node/bin`、PATH 中独立的 Node.js >=22/npm、本机已安装的 NVM 版本。通过 Conda 路径、环境前缀及 `conda-meta` 识别环境，并检查可执行文件符号链接的真实路径。

没有可用独立运行时时，安装器自动调用 `install-node.sh`：从 `nodejs.org` 下载当前平台的 Node.js 24 LTS，核对官方 SHA-256 后安装到 `runtime/node`。此步骤需要 curl、tar、Python 3；支持 Linux/macOS 的 x64/arm64，不修改 Conda、系统动态库或全局 PATH。已有 `runtime/node` 不覆盖；服务管理只选择运行时，不自动下载。

也可用 `PASEO_NODE_BIN=/absolute/path/to/node/bin bash paseo-ws/install.sh` 显式指定同时包含 `node` 和 `npm` 的独立目录；服务管理脚本支持同一变量。显式指定无效或 Conda 路径会直接报错，不回退。

Nginx 从固定版本源码构建，校验 SHA-256 并保留许可证，已有安装校验后复用。首次构建需要 `cc`、`make`、`perl`、`curl`、`tar`、Python 3；`PASEO_NGINX_BUILD_JOBS` 默认 4。可用 `bash paseo-ws/paseo_nginx_install.sh --dry-run` 查看安装计划。

如果 `data/paseo.conf` 不存在，安装脚本会提示输入 IP 和端口（回车使用 `10.30.0.25`、`25227`），验证后创建仅含这两个字段、权限为 `600` 的 JSON 文件。支持 IPv4/IPv6；端口不能与后端 `25226` 冲突。已有配置不覆盖，也不再询问；没有标准输入时明确报错，不写入不完整配置。

安装脚本会自动从 `config.json.example` 初始化缺失的官方完整配置 `data/.paseo/config.json`（目录权限 `700`、文件权限 `600`）；已有文件保持不变。对于此前已安装但缺少配置的实例，首次 `start` 确认服务已停止后也会自动补建，无需重新安装或手工复制。符号链接配置会被拒绝，避免覆盖访问配置或其他文件。

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

`patch-web-ui.cjs` 将首次连接探测和后续 TLS 连接等待时间调整为 20 秒，修复手机慢连接超时；同时给网页版 Add projects 增加 **Browse** 服务器目录树入口。补丁生成新哈希资源地址，保留原 JS。安装时自动执行，也可运行 `node paseo-ws/patch-web-ui.cjs` 后刷新网页，无需重启。

目录选择器由 `server-directory-picker.js` 实现，复用已连接主机的 `listDirectory(cwd, path)` 会话接口。点击名称选中并按需展开子目录，左侧箭头可展开或折叠，再点击 **Select this folder** 添加；支持上级目录、刷新、错误重试、键盘和手机布局。可浏览服务器进程有权限访问的目录，包括隐藏目录；默认从已有推荐绝对路径开始，没有推荐路径则从 `/` 开始。已有路径搜索和 Electron 本机原生选择器保留。

上游核查：[`v0.14.0` AddProjectFlow](https://github.com/getpaseo/paseo/blob/v0.14.0/packages/app/src/components/add-project-flow.tsx#L359) 的 Browse 仅适用于 Electron 本机；main 提交 `5afa1a9f8ef4b069ff84278668c1fd030df42273` 同样如此。后端已有 [`listDirectory`](https://github.com/getpaseo/paseo/blob/v0.14.0/packages/client/src/daemon-client.ts#L5068)，本补丁只补界面接入，不新增文件访问服务。

`patch-web-ui.baseline.json` 记录适用版本 `v0.14.0` 及上游 commit [`8c6de842a3157530c26a7a94c78a3d647fb96ce9`](https://github.com/getpaseo/paseo/commit/8c6de842a3157530c26a7a94c78a3d647fb96ce9)。版本、commit 不匹配或缺少 `gitHead` 时输出 `[WARN]`；资源结构不匹配时退出，不自动更新基准。适配新版本后应同步更新基准。

验证：`node --test paseo-ws/test-*.cjs`，测试使用临时目录与模拟服务，不启停线上服务。目录树浏览器测试需安装 Playwright/Chromium 及其运行库；可用 `PASEO_PLAYWRIGHT_MODULE=/path/to/playwright node --test paseo-ws/test-server-directory-picker.cjs` 指定模块路径。未安装时该浏览器测试明确跳过，其余测试继续运行。浏览器用例覆盖桌面/手机尺寸、懒加载、选择确认、取消、上级导航、空目录、权限失败重试和晚到响应。
