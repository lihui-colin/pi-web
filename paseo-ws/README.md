# Paseo 部署

顶层保留主安装、服务管理和代理配置脚本；其他辅助脚本、源码、补丁、测试与配置模板位于 `srcs/`，运行数据、依赖和日志仍使用服务目录下原有位置。

## 安装与配置

运行 `bash paseo-ws/install.sh` 安装固定版本 **0.16.0-beta.2（官方测试版）** 的 CLI、后台及配套网页、Nginx 和必要的 Web UI 补丁；安装不启停服务。安装和服务管理均排除 Conda 环境的 Node/npm，即使它们可运行也不使用。选择顺序为显式 `PASEO_NODE_BIN`、项目 `runtime/node/bin`、PATH 中独立的 Node.js >=22/npm、本机已安装的 NVM 版本。通过 Conda 路径、环境前缀及 `conda-meta` 识别环境，并检查可执行文件符号链接的真实路径。

升级准备可用 `PASEO_RUNTIME_PREFIX=/absolute/path` 将 CLI 依赖安装到独立目录，管理入口仍使用项目的 `runtime/`；`PASEO_UPSTREAM_ONLY=1` 仅跳过本地服务补丁。安装版本固定为 `0.16.0-beta.2`。

没有可用独立运行时时，安装器自动调用 `srcs/install-node.sh`：从 `nodejs.org` 下载当前平台的 Node.js 24 LTS，核对官方 SHA-256 后安装到 `runtime/node`。此步骤需要 curl、tar、Python 3；支持 Linux/macOS 的 x64/arm64，不修改 Conda、系统动态库或全局 PATH。已有 `runtime/node` 不覆盖；服务管理只选择运行时，不自动下载。

也可用 `PASEO_NODE_BIN=/absolute/path/to/node/bin bash paseo-ws/install.sh` 显式指定同时包含 `node` 和 `npm` 的独立目录；服务管理脚本支持同一变量。显式指定无效或 Conda 路径会直接报错，不回退。

Nginx 从固定版本源码构建，校验 SHA-256 并保留许可证，已有安装校验后复用。首次构建需要 `cc`、`make`、`perl`、`curl`、`tar`、Python 3；`PASEO_NGINX_BUILD_JOBS` 默认 4。可用 `bash paseo-ws/srcs/paseo_nginx_install.sh --dry-run` 查看安装计划。

如果 `data/paseo.conf` 不存在，安装脚本会提示输入 IP 和端口（回车使用 `10.30.0.25`、`25227`），验证后创建包含这两个字段及空 `networkProxy`、权限为 `600` 的 JSON 文件。支持 IPv4/IPv6；端口不能与后端 `25226` 冲突。已有配置不覆盖，也不再询问；没有标准输入时明确报错，不写入不完整配置。

安装脚本会自动从 `srcs/config.json.example` 初始化缺失的官方完整配置 `data/.paseo/config.json`（目录权限 `700`、文件权限 `600`）；已有文件保持不变。对于此前已安装但缺少配置的实例，首次 `start` 确认服务已停止后也会自动补建，无需重新安装或手工复制。符号链接配置会被拒绝，避免覆盖访问配置或其他文件。

- `data/paseo.conf`：包含访问地址 `ip` 和 `port`（默认 `10.30.0.25:25227`），以及可选的出站网络代理 `networkProxy`。
- `data/.paseo/`：官方数据目录（`PASEO_HOME`），包含完整配置 `config.json`、会话、认证和模型。代理 CLI 需另行安装并认证；任务工作目录由会话指定。
- `log/daemon.log`：后端日志及轮转文件所在目录，通过官方 `log.file.path` 配置。停止后的下一次 `start` 会保留旧主日志到 `log/legacy-*/daemon.log`，并将旧位置 `data/.paseo/daemon.log` 链接到新日志，以兼容上游固定写入旧路径的退出记录；已有历史轮转文件不自动移动。运行中的后端不迁移日志。
- `data/tls/<ip>/`：从 `ds-harness/data/tls/<ip>/` 复制的 `fullchain.pem` 与 `privkey.pem`，IPv6 目录名将冒号替换为下划线。HTTPS 启动时若文件缺失、为空或不可读，立即退出并提示复制，不自动启动 DSH 或生成证书。
- `data/nginx.conf`：由 `srcs/nginx.conf.template` 生成；Nginx PID、进程启动身份记录 `master.json` 和临时文件在 `data/nginx/`，错误日志在 `log/nginx/error.log`。Paseo 与 DSH 各自使用独立的 Nginx 二进制、配置、进程、PID 和日志目录，分别启停。
- `data/`、`log/`、`runtime/` 和 `.npm-cache/` 不纳入 Git。

## Provider 网络代理

可用脚本设置或删除 `data/paseo.conf` 中的代理字段（保留 IP 和端口）：

```bash
bash paseo-ws/paseo-proxy.sh set http://127.0.0.1:7890
bash paseo-ws/paseo-proxy.sh clear
bash paseo-ws/paseo-proxy.sh show
```

配置命令与 DSH 统一为 `set`、`clear`、`show`；不带参数默认 `show`，`help` 查看用法，旧 `delete` 命令仍作为 `clear` 的别名。`show` 隐藏代理认证信息。脚本支持从任意工作目录调用，不自动重启服务，也不修改 shell 或 provider 的环境配置。删除字段不等于强制直连：后续启动仍可能继承启动环境中的代理变量。

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

`srcs/patches/plugins/dsh/patch-dsh-catalog.cjs` 优先采用显式 `DSH_HOME`；未设置时，根据脚本所在的 `paseo-ws/` 目录计算 `../ds-harness/data/.dsh`，不依赖当前工作目录或用户主目录，也不需要本地绝对路径配置文件。安装/应用补丁时将解析后的目录写成 DSH 插件自身的启动默认值，运行时显式 `DSH_HOME` 仍优先；Paseo 主进程和其他插件环境不修改。不复制凭据或会话数据。移动仓库或升级插件后需重新应用补丁，确认 DSH 会话空闲后执行插件 reload；目录变更影响模型、凭据和历史会话位置，不能仅刷新模型快照。

`srcs/patches/plugins/dsh/patch-dsh-catalog.cjs` 修复 `paseo-dsh 0.2.17` 的冷启动目录查询：让 `paseo/catalog` 和 `initialize` 一样等待 `loader.await()`，防止凭据服务尚未加载时漏报自定义模型。已核查[上游实现](https://github.com/liuxing7954/paseo-dsh/blob/c642c604aeb5b409a6237ca3ef54fdb82801677d/dsh-bridge/lib/index.js#L83)，该提交仅对 initialize 等待。补丁同时更新当前桥接入口与插件内嵌资源；安装脚本会应用，也可在插件安装/升级后运行 `node paseo-ws/srcs/patches/plugins/dsh/patch-dsh-catalog.cjs`（使用与运行中插件一致的 `DSH_HOME` 和 `DSH_PASEO_PROFILE`；默认 home 为本仓库的 `ds-harness/data/.dsh`）。结构不匹配会停止，需重新核查上游。无需重启服务；变更后需刷新 Paseo 的全局 provider snapshot：在 Providers 中打开 DeepSeek Harness (native)，点击 Refresh；客户端 API 为 `refreshProvidersSnapshot({ providers: ['deepseek-harness-native'] })`，不传 `cwd`。传 `cwd` 只刷新对应项目的快照，设置页仍可能显示旧列表。验证时需打开实际提供商详情，核对该 profile 实际配置的模型列表及 reasoning 档位，例如 `xinmian/grok-4.7`，不要仅确认提供商出现在列表中。插件自身目录另有最长五分钟缓存。

## Web UI 补丁

`srcs/patches/service/patch-web-ui.cjs` 仅保留尚未被上游覆盖的修复：20 秒 TLS 探测预算、触摸信息卡片、宽屏触摸消息操作、触屏终端虚拟键、Web 终端原生右键菜单、移动侧栏开启边缘的浏览器仲裁，以及聊天公式渲染。每次从基准记录的官方原始资源重新构建，生成新哈希及 Brotli/Gzip 副本，确保删除的本地补丁不会残留。安装时自动执行，也可运行 `node paseo-ws/srcs/patches/service/patch-web-ui.cjs` 后刷新网页，无需重启。

`srcs/patches/service/patch-workspace-git-startup.cjs` 让侧栏先收到本地 Git 状态，再立即通过上游刷新流程异步查询远端 Forge/PR 状态，包括冷启动时的自建 Forge 与 SSH 别名识别。后台查询不重复刷新本地 Git，并绕过首次本地刷新后的节流；工作区已不再被观察或没有成功加载快照时跳过。补丁可从旧版仅跳过 Forge 的实现升级，重复应用不改变结果。安装时自动执行；单独应用后需重启 Paseo 服务。

聊天公式保留上游 KaTeX MathML 渲染，只打开 `latexMath` 并修正公式前景色。识别层使用 micromark/mdast 的 Markdown 语法及数学扩展，增加 `\(...\)`、`\[...\]` 规则，在普通 Markdown 转义前识别公式。公式通过临时文本槽传递给上游 md4c，再还原为 `LatexMathInline` / `LatexMathDisplay` 节点；公式正文不转换成美元符号、不修改消息原文。只有美元符号公式的消息保留原解析路径。代码块、行内代码、链接目标和 HTML 的边界由解析器处理，未闭合公式随流式输入等待闭合。显式分隔符即声明公式，无命令白名单或内容评分：`\(x\)`、`\(\alpha\)`、`\[E=mc^2\]` 均支持；需要原样展示分隔符或其中的路径时使用代码标记。KaTeX 的 `trust: false` 和错误显示行为保持上游实现。

识别器源码及锁定依赖位于 `srcs/patches/service/math-parser/`，发布资源为同级 `math-parser.js`。修改源码后运行 `node paseo-ws/srcs/patches/service/math-parser/build.cjs` 重建；依赖只安装到 `data/math-parser-build/js/`，生成资源包含依赖许可，常规安装及补丁发布无需联网安装前端依赖。验证使用 `node --test paseo-ws/tests/test-math-parser.cjs paseo-ws/tests/test-web-ui-bundle.cjs`，测试实际加载官方 beta.2 的 md4c WASM 并对比 AST，同时核验 KaTeX 模块未变。

修改面板使用 [官方 0.16 的 diff 协议](https://github.com/getpaseo/paseo/releases/tag/v0.16.0-beta.2)：先显示文件目录，正文分批传输、完成后提交，后续只传有变化的文件正文。旧的独立 diff 连接及 WebSocket 压缩补丁已移除。新版保留上游的大文件与总量限制，目录可先显示不代表所有文件正文都能展开。各本地补丁共用 `srcs/patches/patch-utils.cjs` 的版本检查、安装路径和源码校验。

用户消息操作复用[上游操作行和复制实现](https://github.com/getpaseo/paseo/blob/v0.16.0-beta.2/packages/app/src/components/message.tsx#L422)，补充宽屏触摸设备的常显判断：`(hover: none), (pointer: coarse)` 匹配时，无需悬停即可看到拷贝按钮及同一行的时间、回退操作。上游仅依据紧凑布局、原生平台或悬停状态判断，未覆盖 iPad 宽屏网页版。通过 React 外部订阅监听输入能力变化；普通电脑仍在悬停时显示，待发送及无正文消息保持上游行为。验证使用 `node --test paseo-ws/tests/test-message-actions-patch.cjs paseo-ws/tests/test-web-ui-bundle.cjs`。

左侧项目行的弹出菜单补充“新建工作区”：右键/长按菜单与三点下拉菜单共用已有的新建工作区回调，进入与 `+` 按钮相同的设置流程。仅在项目具有可用 worktree 创建目标时显示，不改变按钮的悬停显示及菜单触发方式。依据官方 beta.2 Web entry：项目菜单 `Qe` 原本只有设置、打开目录/新窗口和移除项目，新建回调仅绑定项目行按钮。验证使用 `node --test paseo-ws/tests/test-project-workspace-menu.cjs paseo-ws/tests/test-web-ui-bundle.cjs`。

侧栏信息卡片修复 iPad 宽屏下触摸误触发与多卡片滞留：仅鼠标指针进入和键盘可见焦点可打开卡片，触摸及触控笔进入、普通点击产生的焦点不打开；外部鼠标按下或触摸、触控笔按下时关闭已有卡片，卡片内部鼠标按下保留链接和按钮操作。依据基准 v0.16.0-beta.2 安装包的 `WorkspaceHoverCard` / `HoverCard` 实现：上游仅在紧凑布局禁用卡片，宽屏的 `pointerenter` 与 `focusin` 未过滤触摸输入。补丁保留上游布局、点击导航和菜单；验证使用 `node --test paseo-ws/tests/test-hover-card-patch.cjs paseo-ws/tests/test-web-ui-bundle.cjs`。

`mobile-sidebar-swipe.js` 仅在紧凑布局的左边缘 32px 右滑时阻止浏览器抢占；动画与状态提交仍由官方手势负责。上游[根布局](https://github.com/getpaseo/paseo/blob/v0.16.0-beta.2/packages/app/src/app/_layout.tsx#L380) 开启手势仍使用 `touch-action: auto`，所以保留这一缺口修复；[侧栏关闭](https://github.com/getpaseo/paseo/blob/v0.16.0-beta.2/packages/app/src/mobile-panels/presentation.tsx#L91) 已使用 `pan-y`，本地关闭仲裁已删除。不会把整个聊天区域改成 `pan-y`，避免禁用正文中的横向滚动。

添加项目时，Web **Browse** 使用 `server-directory-picker.js` 浏览所选主机的目录，支持双栏、面包屑、隐藏目录、路径编辑及新建目录；手机显示单栏。保留上游路径搜索，Electron 本机继续使用原生选择器。

“文件／更改／＋”侧栏标签栏右端提供最大化／恢复按钮，旁边保留原有收起按钮，控制整块侧栏而不是某一个终端。仅在聊天区与右侧栏并排显示的 dock 布局中提供最大化；窄屏 overlay 模式不显示该按钮，进入该模式时会清除最大化状态。最大化使右侧栏覆盖中间聊天区及原右侧栏区域，左侧工作区导航保持不变，所有侧栏标签共用状态；中间聊天区保持挂载，但在最大化期间通过 inert、RetainedPanel 活动状态和原有窗格焦点标志暂停键盘/焦点交互，恢复时重新启用，避免操作被覆盖的聊天控件；恢复后聊天区重新露出、右侧栏回到此前宽度，收起或切换工作区会清除最大化状态。切换检测同时使用上游 RetainedPanel 活动上下文，在布局提交时复位，避免后台保留的 workspace 因焦点属性滞后而在切回后恢复异常宽度；内容组件保持挂载。复用上游窗格最大化按钮的图标、标签与样式，只覆盖 ExplorerFrame 的渲染几何，不修改持久宽度、不搬动或重挂载标签内容，不改变主窗格的原生最大化。`explorer-sidebar-maximize.js` 通过公共标签栏 action 插槽加入按钮。验证使用 `node --test paseo-ws/tests/test-explorer-sidebar-maximize.cjs paseo-ws/tests/test-web-ui-bundle.cjs`；设置 `PASEO_PLAYWRIGHT_MODULE=/path/to/playwright` 可运行 Chromium 触屏检查，复用官方 React/ReactDOM 以及实际补丁 Frame 与 React Native Web/Unistyles 渲染器验证三栏边界、跨标签状态、恢复宽度、收起、横竖屏和组件身份，不创建真实 PTY。

所有触屏终端均显示上游 Esc、Tab、Ctrl、方向键等虚拟键，包括宽屏平板和带鼠标的触屏电脑。复用上游响应式 `usePointerCapabilities`、`hasTouchScreen`：按 `any-pointer: coarse` 或 `navigator.maxTouchPoints` 检测触屏能力，保留原生平台与紧凑布局的既有显示逻辑，普通宽屏非触屏电脑保持隐藏。键盘 padding 和终端 keyboardInset 同步沿用虚拟键显示条件，使宽屏触屏设备弹出软键盘时也能避让，指针能力变化会更新对应回调。上游 `terminal-virtual-keyboard.ts` 的显示判断仅覆盖原生平台和紧凑布局，因此补充触屏参数；按可用宽度排列按键、按键发送和剪贴板策略不变。验证使用 `node --test paseo-ws/tests/test-terminal-touch-keys.cjs paseo-ws/tests/test-web-ui-bundle.cjs`。

Web 终端使用浏览器原生右键菜单：PC 右键、手机长按的菜单和复制粘贴选项由浏览器提供，不注入自定义菜单或常驻按钮。补丁移除 Web 终端对 `contextmenu` 的默认行为拦截，Electron 继续使用原生应用菜单。具体可用选项由浏览器、选区和当前焦点决定。重新发布从官方原始资源构建，刷新页面后生效。

上游核查：[`v0.16.0-beta.2` TerminalEmulator](https://github.com/getpaseo/paseo/blob/v0.16.0-beta.2/packages/app/src/components/terminal-emulator.tsx) 的右键处理无条件调用 `preventDefault()`，但菜单实现依赖 Electron，因此浏览器默认菜单被拦截后没有替代菜单。本补丁仅在 Electron 菜单接口存在时拦截事件。

`srcs/patches/service/patch-web-ui.baseline.json` 记录官方原始 Web 资源、适用版本 `v0.16.0-beta.2` 及上游 commit [`23bae61535542a45ade7196a7b3c152705f16de3`](https://github.com/getpaseo/paseo/commit/23bae61535542a45ade7196a7b3c152705f16de3)。版本、commit 不匹配或缺少 `gitHead` 时输出 `[WARN]`；资源结构不匹配时退出，不自动更新基准。共用替换函数及 DSH 桥接补丁只接受唯一的原始或已修补实现，拒绝新旧混杂或重复实现。适配新版本后应同步更新基准。

验证：`node --test paseo-ws/tests/test-*.cjs` 和 `python3 -B paseo-ws/tests/test-nginx.py`。生命周期测试需要 `cc` 与 Python 3，使用临时目录和独立测试进程，不启停线上服务。资源发布测试验证从官方原始资源重建、旧补丁移除及幂等，并校验 diff 和侧栏手势的上游模块保持逐字不变，核对消息模块仅应用输入能力补丁，并检查 Web 目录浏览接入。

beta.2 逐项复核依据见 [补丁审查记录](srcs/patches/REVIEW.md)。指定 `PASEO_RUNTIME_PREFIX` 后，实际资源测试缺包或版本不匹配会失败，避免将升级适配误报为 skip。设置 `PASEO_PLAYWRIGHT_MODULE=/path/to/playwright` 可运行可选的原生 DOM 鼠标、触摸、键盘焦点和卡片链接检查；它验证实际补丁处理器，不等同于完整 React 应用端到端测试。

测试代码、脚本及测试夹具统一位于 `tests/`，与 `srcs/` 同级。主服务补丁及其辅助资源位于 `srcs/patches/service/`；DSH 插件补丁位于 `srcs/patches/plugins/dsh/`。安装入口使用新路径，测试夹具维持同样的目录结构。
