# Paseo 部署

## 安装与配置

运行 `bash paseo-ws/install.sh` 安装本地 CLI、Nginx 并应用 Web UI 补丁；安装不启停服务。安装和服务管理均排除 Conda 环境的 Node/npm，即使它们可运行也不使用。选择顺序为显式 `PASEO_NODE_BIN`、项目 `runtime/node/bin`、PATH 中独立的 Node.js >=22/npm、本机已安装的 NVM 版本。通过 Conda 路径、环境前缀及 `conda-meta` 识别环境，并检查可执行文件符号链接的真实路径。

没有可用独立运行时时，安装器自动调用 `install-node.sh`：从 `nodejs.org` 下载当前平台的 Node.js 24 LTS，核对官方 SHA-256 后安装到 `runtime/node`。此步骤需要 curl、tar、Python 3；支持 Linux/macOS 的 x64/arm64，不修改 Conda、系统动态库或全局 PATH。已有 `runtime/node` 不覆盖；服务管理只选择运行时，不自动下载。

也可用 `PASEO_NODE_BIN=/absolute/path/to/node/bin bash paseo-ws/install.sh` 显式指定同时包含 `node` 和 `npm` 的独立目录；服务管理脚本支持同一变量。显式指定无效或 Conda 路径会直接报错，不回退。

Nginx 从固定版本源码构建，校验 SHA-256 并保留许可证，已有安装校验后复用。首次构建需要 `cc`、`make`、`perl`、`curl`、`tar`、Python 3；`PASEO_NGINX_BUILD_JOBS` 默认 4。可用 `bash paseo-ws/paseo_nginx_install.sh --dry-run` 查看安装计划。

如果 `data/paseo.conf` 不存在，安装脚本会提示输入 IP 和端口（回车使用 `10.30.0.25`、`25227`），验证后创建包含这两个字段及空 `networkProxy`、权限为 `600` 的 JSON 文件。支持 IPv4/IPv6；端口不能与后端 `25226` 冲突。已有配置不覆盖，也不再询问；没有标准输入时明确报错，不写入不完整配置。

安装脚本会自动从 `config.json.example` 初始化缺失的官方完整配置 `data/.paseo/config.json`（目录权限 `700`、文件权限 `600`）；已有文件保持不变。对于此前已安装但缺少配置的实例，首次 `start` 确认服务已停止后也会自动补建，无需重新安装或手工复制。符号链接配置会被拒绝，避免覆盖访问配置或其他文件。

- `data/paseo.conf`：包含访问地址 `ip` 和 `port`（默认 `10.30.0.25:25227`），以及可选的出站网络代理 `networkProxy`。
- `data/.paseo/`：官方数据目录（`PASEO_HOME`），包含完整配置 `config.json`、会话、认证和模型。代理 CLI 需另行安装并认证；任务工作目录由会话指定。
- `log/daemon.log`：后端日志及轮转文件所在目录，通过官方 `log.file.path` 配置。停止后的下一次 `start` 会保留旧主日志到 `log/legacy-*/daemon.log`，并将旧位置 `data/.paseo/daemon.log` 链接到新日志，以兼容上游固定写入旧路径的退出记录；已有历史轮转文件不自动移动。运行中的后端不迁移日志。
- `data/tls/<ip>/`：从 `ds-harness/data/tls/<ip>/` 复制的 `fullchain.pem` 与 `privkey.pem`，IPv6 目录名将冒号替换为下划线。HTTPS 启动时若文件缺失、为空或不可读，立即退出并提示复制，不自动启动 DSH 或生成证书。
- `data/nginx.conf`：由 `nginx.conf.template` 生成；Nginx PID、进程启动身份记录 `master.json` 和临时文件在 `data/nginx/`，错误日志在 `log/nginx/error.log`。Paseo 与 DSH 各自使用独立的 Nginx 二进制、配置、进程、PID 和日志目录，分别启停。
- `data/`、`log/`、`runtime/` 和 `.npm-cache/` 不纳入 Git。

## Provider 网络代理

在 `data/paseo.conf` 中设置 `networkProxy`，例如：

```json
{
  "ip": "10.30.0.25",
  "port": 25227,
  "networkProxy": "http://127.0.0.1:7890"
}
```

支持 HTTP/HTTPS 代理 URL（可带认证信息，不支持路径、查询参数或片段）；地址须能从 Paseo 后端访问，`127.0.0.1` 指后端服务器。缺省或空字符串表示不覆盖启动环境中的代理设置，并非强制直连。

`start` 将非空值通过大小写两套 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量传给后端，其启动的 provider CLI 可继承使用；具体代理支持取决于 CLI，自定义 provider 的 `env` 可以覆盖继承值。`NO_PROXY` / `no_proxy` 合并已有绕过列表并加入 `localhost,127.0.0.1,::1`，保护本地控制连接。代理地址不会写入官方 `config.json`。

此配置在后端进程启动时生效；已运行时再次 `start` 不会更新进程环境，`paseo reload` 也不会应用这一启动项。修改后需在允许中断会话时先 `stop` 再 `start`。`--proxy` / `--no-proxy` 和 `reload-proxy` 仅控制 Nginx 入站代理，HTTP 直连模式同样支持 `networkProxy`。本设置作用于后端及其子进程，不限于模型请求。

官方逐 provider 配置方式参见 [Custom providers](https://paseo.sh/docs/custom-providers.md)。

## 服务管理

```bash
bash paseo-ws/paseo_web_run.sh start             # Nginx HTTPS，后端 127.0.0.1:25226
bash paseo-ws/paseo_web_run.sh start --no-proxy  # HTTP，直接监听配置端口
bash paseo-ws/paseo_web_run.sh status
bash paseo-ws/paseo_web_run.sh set-password
bash paseo-ws/paseo_web_run.sh reload-proxy      # 校验并重载 Nginx
bash paseo-ws/paseo_web_run.sh stop
```

服务管理使用 Linux `/proc` 和 Python 3 校验 Nginx 可执行文件、实例参数、系统启动标识和进程启动时间，拒绝向身份不符的 PID 发信号。`reload-proxy` 校验候选配置成功后才原子替换正式配置，失败保留原文件；`stop` 直接向已验证的主进程发信号，不依赖当前配置或证书是否有效。

默认访问 `https://10.30.0.25:25227/`；无代理模式使用 HTTP。切换模式先停止再启动。停止服务会断开客户端，重载代理可能触发 WebSocket 重连，操作前检查活跃会话和运行任务；依赖本服务的会话应由独立维护进程完成启停与就绪检查。

旧数据已迁入 `data/.paseo/`，迁移工具和临时诊断已移除。故障时检查 `log/nginx/error.log`、`log/daemon.log`；修改日志配置后需在允许中断会话时先 `stop` 再 `start` 才会全部生效，勿重启其他服务。

## DSH 插件模型目录

`paseo-dsh` 使用 `$DSH_HOME/profiles/paseo/cordis.patch.yml`；可通过 `DSH_PASEO_PROFILE` 选择其他 profile。DSH Web 使用自己的 `web` profile，新增模型不会自动同步到 Paseo。模型定义及其引用的凭据需要在选定的 DSH home 中配置，例如 `xinmian/grok-4.7` 引用 `XINMIAN_API_KEY`；默认使用本仓库的 `ds-harness/data/.dsh`。

`patch-dsh-catalog.cjs` 优先采用显式 `DSH_HOME`；未设置时，根据脚本所在的 `paseo-ws/` 目录计算 `../ds-harness/data/.dsh`，不依赖当前工作目录或用户主目录，也不需要本地绝对路径配置文件。安装/应用补丁时将解析后的目录写成 DSH 插件自身的启动默认值，运行时显式 `DSH_HOME` 仍优先；Paseo 主进程和其他插件环境不修改。不复制凭据或会话数据。移动仓库或升级插件后需重新应用补丁，确认 DSH 会话空闲后执行插件 reload；目录变更影响模型、凭据和历史会话位置，不能仅刷新模型快照。

`patch-dsh-catalog.cjs` 修复 `paseo-dsh 0.2.17` 的冷启动目录查询：让 `paseo/catalog` 和 `initialize` 一样等待 `loader.await()`，防止凭据服务尚未加载时漏报自定义模型。已核查[上游实现](https://github.com/liuxing7954/paseo-dsh/blob/c642c604aeb5b409a6237ca3ef54fdb82801677d/dsh-bridge/lib/index.js#L83)，该提交仅对 initialize 等待。补丁同时更新当前桥接入口与插件内嵌资源；安装脚本会应用，也可在插件安装/升级后运行 `node paseo-ws/patch-dsh-catalog.cjs`（使用与运行中插件一致的 `DSH_HOME` 和 `DSH_PASEO_PROFILE`；默认 home 为本仓库的 `ds-harness/data/.dsh`）。结构不匹配会停止，需重新核查上游。无需重启服务；变更后需刷新 Paseo 的全局 provider snapshot：在 Providers 中打开 DeepSeek Harness (native)，点击 Refresh；客户端 API 为 `refreshProvidersSnapshot({ providers: ['deepseek-harness-native'] })`，不传 `cwd`。传 `cwd` 只刷新对应项目的快照，设置页仍可能显示旧列表。验证时需打开实际提供商详情，核对该 profile 实际配置的模型列表及 reasoning 档位，例如 `xinmian/grok-4.7`，不要仅确认提供商出现在列表中。插件自身目录另有最长五分钟缓存。

## Web UI 补丁

`patch-web-ui.cjs` 将首次连接探测和后续 TLS 连接等待时间调整为 20 秒，修复手机慢连接超时；同时给网页版 Add projects 增加 **Browse** 服务器目录树入口。补丁生成新哈希资源地址，保留原 JS。安装时自动执行，也可运行 `node paseo-ws/patch-web-ui.cjs` 后刷新网页，无需重启。

手机侧栏修复也由该入口自动应用（`mobile-sidebar-swipe.js`）：从屏幕左边缘 32px 内右滑打开左侧栏，在已打开的左侧栏内左滑关闭；保留原有宽度和布局，右侧栏不变。仍由上游手势负责动画和状态提交。已核对 [v0.14.0 上游侧栏手势](https://github.com/getpaseo/paseo/blob/8c6de842a3157530c26a7a94c78a3d647fb96ce9/packages/app/src/mobile-panels/gestures.ts) 和 [根布局](https://github.com/getpaseo/paseo/blob/8c6de842a3157530c26a7a94c78a3d647fb96ce9/packages/app/src/app/_layout.tsx)：原版已经支持侧滑，但 Web 的 `touch-action: auto` 允许浏览器抢占横向触摸。Chromium 手机模拟中可复现 `pointercancel` 导致打开失败。补丁只在紧凑布局下的左边缘右滑、或已打开左侧栏内的左滑时阻止浏览器默认横向移动；不拦截竖向滚动、聊天区中部横向滚动、输入区域、多指触摸、右侧栏或桌面布局，不另建侧栏状态。打开和关闭共用同一方向判定与事件清理逻辑，不注入布局样式、不改写上游手势模块。执行 `node --test paseo-ws/test-mobile-sidebar-swipe.cjs paseo-ws/test-patch-web-ui.cjs paseo-ws/test-directory-picker-patch.cjs` 验证事件边界与资源发布幂等性。

目录选择器由 `server-directory-picker.js` 实现，复用已连接主机的 `listDirectory(cwd, path)` 会话接口。点击名称选中并按需展开子目录，左侧箭头可展开或折叠，再点击 **Select this folder** 添加；支持上级目录、刷新、错误重试、键盘和手机布局。可浏览服务器进程有权限访问的目录，包括隐藏目录；默认从已有推荐绝对路径开始，没有推荐路径则从 `/` 开始。已有路径搜索和 Electron 本机原生选择器保留。

上游核查：[`v0.14.0` AddProjectFlow](https://github.com/getpaseo/paseo/blob/v0.14.0/packages/app/src/components/add-project-flow.tsx#L359) 的 Browse 仅适用于 Electron 本机；main 提交 `5afa1a9f8ef4b069ff84278668c1fd030df42273` 同样如此。后端已有 [`listDirectory`](https://github.com/getpaseo/paseo/blob/v0.14.0/packages/client/src/daemon-client.ts#L5068)，本补丁只补界面接入，不新增文件访问服务。

Web 终端使用浏览器原生右键菜单：PC 右键、手机长按的菜单和复制粘贴选项由浏览器提供，不注入自定义菜单或常驻按钮。补丁移除 Web 终端对 `contextmenu` 的默认行为拦截，Electron 继续使用原生应用菜单。具体可用选项由浏览器、选区和当前焦点决定。已应用旧自定义菜单补丁的安装会在再次运行补丁时自动移除旧实现，刷新页面后生效。

上游核查：[`v0.14.0` TerminalEmulator](https://github.com/getpaseo/paseo/blob/v0.14.0/packages/app/src/components/terminal-emulator.tsx) 的右键处理无条件调用 `preventDefault()`，但菜单实现依赖 Electron，因此浏览器默认菜单被拦截后没有替代菜单。本补丁仅在 Electron 菜单接口存在时拦截事件。

`patch-web-ui.baseline.json` 记录适用版本 `v0.14.0` 及上游 commit [`8c6de842a3157530c26a7a94c78a3d647fb96ce9`](https://github.com/getpaseo/paseo/commit/8c6de842a3157530c26a7a94c78a3d647fb96ce9)。版本、commit 不匹配或缺少 `gitHead` 时输出 `[WARN]`；资源结构不匹配时退出，不自动更新基准。适配新版本后应同步更新基准。

验证：`node --test paseo-ws/test-*.cjs` 和 `python3 -B paseo-ws/test-nginx.py`。生命周期测试需要 `cc` 与 Python 3，使用临时目录和独立测试进程，不启停线上服务。目录树浏览器测试需安装 Playwright/Chromium 及其运行库；可用 `PASEO_PLAYWRIGHT_MODULE=/path/to/playwright node --test paseo-ws/test-server-directory-picker.cjs` 指定模块路径。未安装时该浏览器测试明确跳过，其余测试继续运行。浏览器用例覆盖桌面/手机尺寸、懒加载、选择确认、取消、上级导航、空目录、权限失败重试和晚到响应。
