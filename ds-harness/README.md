# DeepSeek Harness

顶层保留主安装、插件安装、Nginx 安装、证书生成、服务管理和代理配置脚本；其他辅助脚本、源码、补丁、测试与配置模板位于 `srcs/`，运行数据、依赖和日志仍使用服务目录下原有位置。

本目录管理 `magpie → DSH 回环后端 → Nginx HTTPS 入口`。运行需要 Linux ≥5.3（允许 pidfd 系统调用）、Bash、Node.js ≥24、npm、curl、Python ≥3.10、OpenSSL 和 `flock`（util-linux）命令行工具。启停前检查 pidfd 能力；Python 未提供包装时优先使用 libc，x86_64/aarch64 还支持原生系统调用。Nginx 由安装器构建到本目录 `data/.local/nginx/`，启动器固定使用这份程序，运行文件也保存在项目内。

## 首次部署

在仓库根目录执行：

```bash
bash ds-harness/dsh_install.sh
# 安装结束后按提示输入 IP 和端口，创建 data/dsh.conf
bash ds-harness/dsh_cert.sh
./ds-harness/dsh_web_run.sh start
```

`server_ip` 填写浏览器访问的 IP 或域名；`port` 默认 `25228`；`dsh_token` 启动时自动更新。访问 `https://<server_ip>:<port>/`，默认地址为 `https://10.30.0.25:25228/`。入口只接受 HTTPS，普通 URL 自动登录，适用于可信网络。

`listen_host` 为 Nginx 本机监听 IP，未填写时优先使用可在本机绑定的 `server_ip`；否则通过 `hostname -I` 检测，只有唯一可绑定 IP 时才自动选择。多网卡或检测失败时明确报错，不取第一块网卡的地址。支持 IPv4 和 IPv6，显式配置的地址会在启动任何服务前检查是否可绑定（使用临时端口探测，不占用服务端口）。也可显式配置本机地址，例如 `server_ip=dsh.example.com`、`listen_host=10.30.0.25`。监听地址必须是 IP；要监听所有 IPv4 接口可显式填写 `0.0.0.0`。已有代理的监听地址与新配置不一致时，启动器会拒绝复用并保留现有进程，需安排维护后生效。

启动器固定读取 `data/tls/<server_ip>/fullchain.pem` 和 `privkey.pem`，忽略旧配置中的 `tls_cert`、`tls_key`。域名目录转为小写，IPv6 冒号替换为下划线，例如 `::1` 对应 `data/tls/__1/`。证书缺失或无效时，在启动服务前退出。

## 安装与更新

```bash
bash ds-harness/dsh_install.sh --dry-run
bash ds-harness/dsh_install.sh --upgrade
```

DSH、pnpm 与全部额外插件统一使用 `srcs/install-versions.json` 的固定版本：DSH `0.2.2-rc.1`、pnpm `12.18.0`，官方 Codex 插件与 DSH 同版。默认补装缺失项并校正版本或声明来源不一致的项；`--upgrade` 先从 npm 和已配置的 GitHub 来源解析最新版本，全部查询成功后原子更新清单，再安装解析到的版本；官方 Codex 始终选用与 DSH 相同的版本，local 插件保留本地链接。版本和来源已经匹配的组件跳过安装，避免同版本重装。原清单备份到 `data/version-backups/`。Magpie 沿用官方安装器，其接口只支持最新版本，因此仍是默认复用、`--upgrade` 更新的独立例外。安装器在安装结束时检查 `data/dsh.conf`：存在则原样保留；只有旧位置 `dsh.conf` 时复制到新位置并保留原文件；两处都没有时提示输入 IPv4/IPv6 地址及 HTTPS 端口（回车默认 `25228`）。无效输入会重新询问，输入结束或中断时不创建半成品；新文件权限为 `600`。`--dry-run` 不询问、不创建配置。安装器不生成证书、不启停服务；安装或更新应在目标 DSH 停机时执行。

额外插件由独立脚本 `dsh_plugins_install.sh` 管理，主安装器会调用它。已有 DSH 环境只安装或更新插件时，可以单独运行：

```bash
bash ds-harness/dsh_plugins_install.sh --dry-run
bash ds-harness/dsh_plugins_install.sh
bash ds-harness/dsh_plugins_install.sh --upgrade
```

脚本管理以下 11 个额外安装包：

| 插件 | 新 profile 默认状态 |
| --- | --- |
| `@deepseek-ai/dsh-subagent-codex` | 启用 |
| `ds-bot` | 启用 |
| `dsh-web-mobile` | 启用 |
| `dshmarket` | 启用 |
| `@xbzbing/dsh-git-panel` | 仅安装，不启用 |
| `dsh-sidebar-enhancement` | 启用 |
| `dsh-sidebar-plus` | 启用 |
| `dsh-better-sidebar` | 启用 |
| `@local/dsh-codex-quota` | 启用（链接本服务 `srcs/plugins/codex-quota`） |
| `dsh-composer-plus` | 启用 |
| `dsh-ide-git` | 仅安装，不启用 |

已有 profile 保留额外插件的启用／停用状态和其他 bundle。固定版本和来源统一由 `srcs/install-versions.json` 维护：DS Bot `0.3.1`、dshmarket `1.73.16`、dsh-ide-git `0.30.0`、sidebar-enhancement `1.4.1`、sidebar-plus `0.4.4`、better-sidebar `0.30.1`、Git panel `1.13.2`；mobile `3.3.5` 固定提交 `646fe837440f9939228bdba0024d407eaac01128`，composer-plus 使用 `1.24.1` 压缩包。本地 codex-quota `1.0.0` 使用相对 profile 的 `link:../../../../srcs/plugins/codex-quota` 来源，不从 npm 下载。版本和声明来源均匹配时跳过；存在 `^` 范围、其他版本或其他来源时恢复为清单值。新 profile 默认启用 9 个，dsh-ide-git 和 Git panel 仅安装。独立插件安装器遇到其他 DSH 版本会要求先运行主安装器，避免混装。`--dry-run` 仅用当前清单预览，提示实际升级会解析最新版，不联网查询或写入；独立脚本不安装 DSH、Nginx 或 Magpie，也不启停服务。

主安装器及插件安装器会在安装前检查本地补丁工具是否完整；插件安装后通过 `dsh_patches_install.sh` 统一校验并迁移全部本地补丁，同一文件的变换按顺序合并，全部校验通过后才写入，写入失败会回滚本次已替换文件。可单独运行 `bash ds-harness/dsh_patches_install.sh` 安装主服务与插件补丁；已安装的补丁打印“已安装，跳过”，不重复写入、备份或修改时间戳。加 `--check` 只读检查，支持 `--profile-dir`、`--host-dir` 指定安装目录；该入口不下载依赖、不重启服务。当前支持 DSH 0.2.2-rc.1、ds-bot 0.3.1（兼容旧 0.2.7）和 mobile 3.3.0 / 3.3.1 / 3.3.5：Bot 保留本地输入框、消息操作栏和桌面宽度布局，沿用上游历史、提示词和触屏命中区，移除旧手机工具栏覆盖；mobile 保持上游界面；撤销旧宿主历史及 Enter 注入，保留页签宽度与终端增强，并修复旧手机浏览器文件资源地址解析；mobile 使用版本清单中固定的 GitHub 提交。参见 [补丁说明](srcs/patches/README.md)。

Nginx 固定安装到 `ds-harness/data/.local/nginx/sbin/nginx`；即使系统已有 Nginx，也不会复用系统版本。`dsh_nginx_install.sh` 使用 [Nginx 官方构建流程](https://nginx.org/en/docs/configure.html)，固定 Nginx 1.30.6、OpenSSL 3.5.9、PCRE2 10.49、zlib 1.3.2，下载后先校验 SHA-256。三项库静态链接，不再依赖容器中额外安装的共享库；编译成功、版本和 SSL 模块检查通过后才发布完整安装目录。

首次构建需要 `cc`、`make`、`perl`、`curl`、`tar`、Python 3，默认 4 个并行任务，可用 `DSH_NGINX_BUILD_JOBS` 调整。缺少构建工具时直接报错；不使用 sudo、APT 或 Homebrew，不写系统目录、不启停服务。已有本地 Nginx 不随 `--upgrade` 更新，只检查版本 ≥1.24 和 HTTP SSL 模块；`--dry-run` 不下载、不编译、不创建目录。只补装 Nginx 时可单独执行：

```bash
bash ds-harness/dsh_nginx_install.sh
```

容器部署需把项目目录或父目录放在持久卷中，并保留隐藏目录 `data/.local/`。在相同架构、兼容 glibc/动态加载器的基础镜像中，容器重建后可直接复用本地二进制；切换不兼容的基础镜像需重新构建。安装成功后仅保留 `data/.local/nginx/sbin/nginx` 和 `licenses/`，清理默认配置、示例页面、默认日志目录及本次源码下载缓存；已有有效安装再次运行安装器也会执行清理，`--dry-run` 只预览。构建失败时保留已下载源码供重试。`data/.local/` 不入 Git，重新克隆仓库时需运行安装器。

Magpie 安装失败最多重试三次。网络不通时可指定代理，安装仍失败则停止后续步骤：

```bash
MAGPIE_PROXY=http://<代理主机>:<端口> bash ds-harness/dsh_install.sh
```

代理地址中的 `127.0.0.1` 指服务器自身。官方 `MAGPIE_MIRROR` 仅替换 GitHub 二进制下载地址，无法解决 `usemagpie.ai` 官网不可达的问题。

兼容处理会在主安装／插件安装完成后自动执行。当前组合对 Bot 0.2.7 单独适配布局增强，不再注入旧历史处理、mobile UI 或手机 Enter 逻辑；Ctrl/Cmd+Enter、候选菜单和手机换行沿用上游。旧版 alpha.2 组合保留独立适配路径；未知或混合版本、迁移匹配失败会中止安装。详见 [统一补丁说明](srcs/patches/README.md)。

## 证书

```bash
bash ds-harness/dsh_cert.sh --dry-run
bash ds-harness/dsh_cert.sh --config /path/to/dsh.conf --tls-dir /path/to/tls --tls-host extra.example.com
```

证书脚本只生成或校验证书，不修改配置、不启停服务。默认读取 `data/dsh.conf`，输出到 `data/tls/<server_ip>/`；自定义 `--config` 时默认输出到该配置所在目录的 `tls/<server_ip>/`。`--tls-dir` 改变输出根目录，`--tls-host` 添加额外 SAN。自定义导出后，启动前仍需将证书部署到本项目 `data/tls/<地址>/`。旧部署可将脚本同级的 `tls/` 整体移到 `data/tls/`，保留原证书、私钥和权限，无需重新签发。

每个地址目录包含：

- `fullchain.pem`、`privkey.pem`：服务端证书链和无口令私钥。
- `ca.pem`、`ca.crt`：内容一致的公开根证书，客户端导入 `ca.crt` 建立信任。
- `ca-key.pem`：CA 私钥，仅保留在服务器，不发给客户端。

已有证书会经过校验并保留，不完整或不匹配的文件不会被覆盖；旧的平铺证书保持不变。目录权限为 `700`、私钥为 `600`。变更 `server_ip` 后生成对应地址的证书；客户端已信任同一 CA 时无需重复导入。证书和私钥不入 Git，迁移机器需单独安全传输，或重新生成并信任 CA。

同一地址的证书检查、生成和发布通过 Node 内置 SQLite 目录锁串行执行，最多等待 60 秒；异常退出或进程被终止后，系统释放锁。目录中的 `.dsh-cert-lock.sqlite` 是长期保留的锁载体，运行中不要删除或移动它。`--dry-run` 不创建锁或其他文件，仅作只读预览，不保证与并发生成的一致快照。

发布前将证书材料和摘要清单持久化到 `.dsh-cert-pending/`，再通过排他硬链接发布；需要支持硬链接和 SQLite 锁的本地文件系统。发布中断后重试原命令，会验证摘要、文件身份、SAN、有效期及 CA 链，然后继续未完成的步骤。`--dry-run` 也验证恢复方案，但不发布文件。未知文件、被修改的事务材料或依赖不会被覆盖；此时应保留现场并检查备份。事务及 `.generate-*` 临时目录可能含私钥，不要分享或在操作进行中删除；只有脚本确认属于自身的事务才会被自动清理。

## 模型配置

Magpie 管理模型来源，DSH 保持项目文件和工具执行。账号/API Key 需单独配置；服务商可在 Magpie 的 **Providers → Add provider** 添加，也可以登录支持的订阅：

```bash
magpie web --no-open
magpie accounts add codex
magpie models dsh
magpie dsh <provider/model>
magpie dsh effort high
```

远程访问 Magpie 的回环管理入口时使用 SSH 端口转发，不公开带凭据的管理链接。`<provider/model>` 必须替换为模型列表中的实际标识，推理强度取值取决于模型。

`magpie dsh`、`magpie dsh model`、`magpie dsh effort` 查看当前配置；`magpie dsh effort default` 恢复原推理强度，`magpie dsh default` 取消接管并恢复此前配置。已有会话和 DS Bot 各自可能保留模型设置，切换后需分别核对。跨机器迁移账号可使用 `magpie backup` / `magpie restore` 加密备份。

Codex CLI 通过 `HTTPS_PROXY`、`HTTP_PROXY`、`ALL_PROXY` 和 `NO_PROXY` 走代理。Magpie 里的 Codex 若在 provider 上单独配置了 `proxy`，则优先于这些环境变量。`dsh_web_run.sh start` 读取 `data/dsh.conf` 的 `outbound_proxy` 和 `no_proxy`，在拉起服务前写入三处：新进程的 `HTTPS_PROXY`、`HTTP_PROXY`、`ALL_PROXY`、`NO_PROXY`；`data/proxy.env`；Magpie 的全局 `settings.json` 和 Codex provider 的 `proxy`。未配置 `outbound_proxy` 时才回退到已有的 `data/proxy.env`。已运行的进程不会自动改用新环境。`no_proxy` 默认包含 `127.0.0.1,localhost,::1`，避免本机回环再绕外网代理。

```bash
bash ds-harness/dsh_proxy.sh set http://<代理主机>:<端口>
bash ds-harness/dsh_proxy.sh show
source ds-harness/dsh_proxy.sh
bash ds-harness/dsh_proxy.sh run -- codex
```

清除出站代理使用 `bash ds-harness/dsh_proxy.sh clear`：删除 `data/proxy.env`、`data/dsh.conf` 的 `outbound_proxy/no_proxy`、Magpie `settings.json` 的全局 `proxy` 和 `providers.json` 中所有 provider 的 `proxy`，保留其他设置。加 `--env-only` 时保留 Magpie 配置。配置文件缺失或重复清理均可正常完成。此命令不会重启服务，也无法修改父 shell 或已运行进程的环境；若启动终端仍导出了代理变量，需要先在该终端执行 `unset HTTPS_PROXY HTTP_PROXY ALL_PROXY NO_PROXY https_proxy http_proxy all_proxy no_proxy outbound_proxy`，避免下次启动继续继承旧代理。

## 数据目录

DSH 0.2.2 系列与 ds-bot 0.2.5 的兼容问题、补丁应用及升级验收见 [迁移文档](MIGRATION.md)。现场核验版本为 DSH 0.2.2-alpha.2。

安装器和启动器固定设置 `DSH_HOME=<脚本目录>/data/.dsh`、`DSH_AGENTS_HOME=<脚本目录>/data/.agents`，覆盖继承的同名环境变量。路径以脚本所在位置为准，与执行命令时的工作目录无关；`data/` 不入 Git。日志放在 `log/`，证书放在 `data/tls/`。Magpie 自身的数据和 Node/npm 安装目录不受这两个变量影响。

已有部署切换前，需要先结束活跃任务，在独立维护终端停服，再把旧数据完整复制到新目录；不能在 DSH 正在写入时把普通文件复制当作最终迁移。默认旧目录的迁移示例（仓库根目录执行，目标目录必须尚不存在；如旧实例使用自定义目录，请替换来源）：

```bash
# 先按部署维护流程停止服务，确认没有进程继续使用旧数据。
install -d -m 700 ds-harness/data
test ! -e ds-harness/data/.dsh && cp -a "$HOME/.dsh" ds-harness/data/.dsh
test ! -e ds-harness/data/.agents && cp -a "$HOME/.agents" ds-harness/data/.agents
```

确认两份数据复制完成后再启动服务。保留旧目录作为回退副本；直接启动空数据目录不会自动继承旧会话和插件。日常手动执行 `dsh plugin` 或 `magpie dsh` 等涉及 DSH 配置的命令前，也需设置这两个环境变量指向本项目数据目录。

## 启停与运行文件

`dsh_web_run.sh` 负责启停顺序和启动锁；`srcs/dsh_runtime.py` 负责进程身份、token、旧运行文件迁移和启动配置校验；`srcs/dsh_nginx.py` 负责代理配置和 Nginx 监督。部署时保留顶层入口与 `srcs/` 的相对目录结构。

重复 `start` 会复用身份匹配且 token 已就绪的进程；代理单独退出后，再次 `start` 会复用 DSH 的实际回环端口。整个 `start/stop` 流程共用 `log/.launcher.lock` 的内核文件锁；已有操作进行中时，新调用立即失败并提示重试。锁在操作结束时自动释放，后台服务和日志读取器不继承锁。锁文件应长期保留，运行中不要删除。不要另外启动一套 `magpie serve` 或 `dsh web`。

每个 PID 配有 `.identity` 记录，校验启动时间、系统启动标识、完整参数、用户和实例随机标识；发信号使用 pidfd 固定进程，避免 PID 复用误停。缺少或不匹配身份记录的存活进程会被拒绝接管，原文件保留。升级旧实例时，须安排独立维护，核验并停止旧进程后再用新版启动；不要删除 PID 或身份文件绕过检查。

DSH 插件自重启可能替换主进程 PID。启动检查仅在实例随机标识、完整命令、用户及启动时间匹配时登记替代进程；存在待执行的自重启且尚无主进程时，拒绝另起一份服务。`stop` 根据同一实例的 `DSH_LAUNCH_ID` 与 `DSH_LAUNCH_ROOT` 查找并停止主进程、插件及其脱离父进程运行的自重启辅助进程，使用 pidfd 逐个复核并发送 TERM，反复扫描以处理退出期间新拉起的进程。确认无残留后才清除登记；超时或身份核验失败时返回失败并保留记录。插件子进程须继承启动环境；主动清除实例标识的进程无法通过此机制识别。

首次登记进程必须读取环境中的实例随机标识。已登记进程的 `/proc/<PID>/environ` 若因权限限制不可读，可在当前用户、PID、启动时间、系统启动标识及完整参数全部匹配时使用已有身份记录；仍使用 pidfd 核验并发送信号，不绕过实际发信号的权限检查。

新后端启动前清空旧 token；就绪记录与当前进程身份及 token 摘要绑定。捕获超时会保留后端，重试 `start` 继续等待同一进程，未就绪时不会启动代理。后台只捕获一次匹配本实例地址的原生启动 URL，并脱敏日志中的 token（包括编码参数名）。捕获、就绪写入和 token 清理使用 `log/.process-state.lock` 协调；该锁文件同样应保留。

检查 Magpie 网关：

```bash
magpie healthcheck
```

确认运行中的任务可中断后停止全部服务：

```bash
./ds-harness/dsh_web_run.sh stop
```

停止顺序为入口代理、DSH、Magpie；单个组件停止失败时仍继续尝试其余组件，最后汇总失败项并返回非零状态。已退出进程视为已停止；全部停止成功且确认 DSH 后端已退出后清除启动 token；有停止失败或身份不明时保留 token 及就绪记录供排查。缺失或不匹配的身份记录不会被绕过，也不会按进程名称批量杀死其他实例。配置保存在 `data/dsh.conf`；启动器仅在新配置不存在时兼容读取旧位置的 `dsh.conf`，安装器会保留其副本到新位置。日志、PID、身份和 token 就绪记录统一放在 `log/`（权限 `700`，排除 Git）；配置更新在配置所在目录创建私有临时文件并原子替换。`log/dsh-token-proxy.pid` 记录 Nginx 监督进程。

启动器在启停前迁移旧位置的运行文件，不覆盖同名目标。日志移动后，已打开的文件描述符继续写入原文件，无需重启；旧 `.nginx-<port>/` 会保留指向 `log/.nginx-<port>/` 的兼容链接，确保旧进程的绝对路径仍有效。新部署不创建这些根目录链接。

修改代码不会自动替换运行进程。修改配置后应安排维护；只更新入口证书或代理时可保留 DSH 后端，但浏览器连接仍会短暂断开，不把重启作为默认验证步骤。

## Nginx 代理

`srcs/dsh_nginx.py` 仅生成/校验配置、管理 Nginx 前台进程并脱敏错误日志。HTTPS、HTTP/WebSocket、连接池、TLS 会话缓存和流式传输均由 Nginx 处理；请求/响应缓冲关闭，DSH 原有 gzip 透传。

监督进程为 Nginx 注册 Linux 父进程退出信号；监督进程被强杀时，内核向 master 发送 TERM，由 Nginx 停止 worker 并释放端口。项目 Nginx 不能设置 set-ID 位或文件 capabilities，因为提权 exec 会清除该保护；启动检查会明确拒绝此类二进制。

无请求体、无显式 token 的首页 GET 在内部完成 token→Cookie→首页交换，浏览器直接收到页面和 `HttpOnly; SameSite=Strict; Secure` Cookie。有效 Cookie 直接复用，失效 Cookie 仅在首页 401 时重新认证；API、WebSocket、写入和带请求体的请求不自动重放。`/connect` 补齐缺失 token 并保留上游 302。

Cookie 使用 DSH 原生 authority 哈希命名，只向后端传递本实例登录 Cookie，同时接受旧的 `dsh<port>_` 前缀，原生名称优先。不同端口的 Cookie 隔离不改变浏览器向同主机各端口发送 Cookie 的规则。登录交换仅接受预期的 `Location: ./` 和单个本实例 Cookie，异常响应返回 502；普通响应正常转发。入口保持 HTTP/1.1，避免 HTTP/2 无 Content-Length 的 DATA 请求绕过自动登录的空请求体判断。

生成配置保存在 `log/.nginx-<port>/nginx.conf`，包含启动 token：目录 `700`、文件 `600`、运行目录排除 Git。请求体、HTTP 代理、FastCGI、uWSGI、SCGI 的临时目录都显式放在该运行目录下，普通用户启动无需创建 `/var/lib/nginx/` 等系统目录。正常退出或配置校验失败时删除配置；访问日志关闭，错误日志脱敏后写入 `log/dsh-token-proxy.log`。不要打印或分享生成配置。

已核查上游 DSH `0.2.1-rc.2`：原生 Cookie、Host/Origin 校验、流式传输、gzip 和 TLS 均已有实现，本目录复用其能力；`dsh-client-connection`、`dsh-host-webserver` 未提供本入口所需的通用自动登录反向代理，因此使用 Nginx 配置完成。

## 验证

```bash
python3 -B -m unittest discover -s ds-harness/tests -p 'test_*.py' -v
bash -n ds-harness/dsh_web_run.sh
```

测试使用临时证书、随机本地端口和模拟服务，覆盖安装计划、源码校验与失败清理、证书校验、Nginx 登录/Cookie、HTTPS/WSS、连接复用、流式传输、请求不重放、全部临时目录权限和启动器生命周期，不启停线上服务。代理集成测试需要先安装项目本地 Nginx。`test_support.py` 提供共享证书和本地 Nginx 测试夹具。

主聊天输入框下方的元信息默认收起，通过工具栏内的 info 按钮展开或收起，点击区域外或按 Esc 自动收起。该功能由 `srcs/patches/service/dsh_composer_metadata_apply.py` 为 DSH rc.1 安装，详见 [补丁说明](srcs/patches/README.md)。

### Codex 额度按钮（本地插件）

运行 `bash ds-harness/srcs/install-codex-quota.sh`，在 web profile 中启用 `@local/dsh-codex-quota`。插件源码位于 `srcs/plugins/codex-quota/`，通过本地链接安装，无须重新下载现有插件。安装脚本可重复运行，保留其他依赖与 bundle。新插件在 DSH 下次加载 profile 时生效；安装器不会重启服务，重启前须检查活跃会话。

输入框的 `conversation.composer.dock` 中显示圆圈图标，悬停提示“Codex 额度”。仅当前会话选择 Codex 来源时显示：Magpie provider（`magpie` 或 `magpie-*`）下的 `codex/…` 模型查询 `magpie accounts codex --json`；原生 `codex` / `openai-codex` provider 通过 `codex app-server --listen stdio://` 的 `account/read` 和 `account/rateLimits/read` 查询本机登录账户。其他来源隐藏入口；切换来源会关闭旧面板并取消旧请求。查询结果展示账户套餐、各额度窗口的已用比例与进度条、重置倒计时、剩余积分、邮箱和数据更新时间，可手动刷新。手机端显示底部面板。数据由 DSH 已认证的连接接口返回，只保留展示字段；查询超时为 20 秒，并发查询合并，失败可重试。未登录或缺失窗口、积分时显示相应提示。

验证：`node --test tests/test_codex_quota.mjs`；浏览器回归使用 `tests/test_codex_quota_browser.cjs`，通过 `DSH_TEST_PLAYWRIGHT`、`DSH_TEST_REACT_UMD` 和 `DSH_TEST_REACT_DOM_UMD` 指定本地测试依赖。
