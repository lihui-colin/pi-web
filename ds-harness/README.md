# DeepSeek Harness

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

默认复用已有的 DSH、pnpm 和 magpie，只补装缺失插件；`--upgrade` 更新 DSH、pnpm、Magpie 和插件。官方 Codex 插件版本与 DSH 对齐，保留上游兼容性检查，同版包缺失或不兼容时停止安装。安装器在安装结束时检查 `data/dsh.conf`：存在则原样保留；只有旧位置 `dsh.conf` 时复制到新位置并保留原文件；两处都没有时提示输入 IPv4/IPv6 地址及 HTTPS 端口（回车默认 `25228`）。无效输入会重新询问，输入结束或中断时不创建半成品；新文件权限为 `600`。`--dry-run` 不询问、不创建配置。安装器不生成证书、不启停服务；安装或更新应在目标 DSH 停机时执行。

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

## 数据目录

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

`dsh_web_run.sh` 负责启停顺序和启动锁；`dsh_runtime.py` 负责进程身份、token、旧运行文件迁移和启动配置校验；`dsh_nginx.py` 负责代理配置和 Nginx 监督。部署时保留这些文件在同一目录。

重复 `start` 会复用身份匹配且 token 已就绪的进程；代理单独退出后，再次 `start` 会复用 DSH 的实际回环端口。整个 `start/stop` 流程共用 `log/.launcher.lock` 的内核文件锁；已有操作进行中时，新调用立即失败并提示重试。锁在操作结束时自动释放，后台服务和日志读取器不继承锁。锁文件应长期保留，运行中不要删除。不要另外启动一套 `magpie serve` 或 `dsh web`。

每个 PID 配有 `.identity` 记录，校验启动时间、系统启动标识、完整参数、用户和实例随机标识；发信号使用 pidfd 固定进程，避免 PID 复用误停。缺少或不匹配身份记录的存活进程会被拒绝接管，原文件保留。升级旧实例时，须安排独立维护，核验并停止旧进程后再用新版启动；不要删除 PID 或身份文件绕过检查。

新后端启动前清空旧 token；就绪记录与当前进程身份及 token 摘要绑定。捕获超时会保留后端，重试 `start` 继续等待同一进程，未就绪时不会启动代理。后台只捕获一次匹配本实例地址的原生启动 URL，并脱敏日志中的 token（包括编码参数名）。捕获、就绪写入和 token 清理使用 `log/.process-state.lock` 协调；该锁文件同样应保留。

检查 Magpie 网关：

```bash
magpie healthcheck
```

确认运行中的任务可中断后停止全部服务：

```bash
./ds-harness/dsh_web_run.sh stop
```

停止顺序为入口代理、DSH、Magpie，完成后清除启动 token。配置保存在 `data/dsh.conf`；启动器仅在新配置不存在时兼容读取旧位置的 `dsh.conf`，安装器会保留其副本到新位置。日志、PID、身份和 token 就绪记录统一放在 `log/`（权限 `700`，排除 Git）；配置更新在配置所在目录创建私有临时文件并原子替换。`log/dsh-token-proxy.pid` 记录 Nginx 监督进程。

启动器在启停前迁移旧位置的运行文件，不覆盖同名目标。日志移动后，已打开的文件描述符继续写入原文件，无需重启；旧 `.nginx-<port>/` 会保留指向 `log/.nginx-<port>/` 的兼容链接，确保旧进程的绝对路径仍有效。新部署不创建这些根目录链接。

修改代码不会自动替换运行进程。修改配置后应安排维护；只更新入口证书或代理时可保留 DSH 后端，但浏览器连接仍会短暂断开，不把重启作为默认验证步骤。

## Nginx 代理

`dsh_nginx.py` 仅生成/校验配置、管理 Nginx 前台进程并脱敏错误日志。HTTPS、HTTP/WebSocket、连接池、TLS 会话缓存和流式传输均由 Nginx 处理；请求/响应缓冲关闭，DSH 原有 gzip 透传。

监督进程为 Nginx 注册 Linux 父进程退出信号；监督进程被强杀时，内核向 master 发送 TERM，由 Nginx 停止 worker 并释放端口。项目 Nginx 不能设置 set-ID 位或文件 capabilities，因为提权 exec 会清除该保护；启动检查会明确拒绝此类二进制。

无请求体、无显式 token 的首页 GET 在内部完成 token→Cookie→首页交换，浏览器直接收到页面和 `HttpOnly; SameSite=Strict; Secure` Cookie。有效 Cookie 直接复用，失效 Cookie 仅在首页 401 时重新认证；API、WebSocket、写入和带请求体的请求不自动重放。`/connect` 补齐缺失 token 并保留上游 302。

Cookie 使用 DSH 原生 authority 哈希命名，只向后端传递本实例登录 Cookie，同时接受旧的 `dsh<port>_` 前缀，原生名称优先。不同端口的 Cookie 隔离不改变浏览器向同主机各端口发送 Cookie 的规则。登录交换仅接受预期的 `Location: ./` 和单个本实例 Cookie，异常响应返回 502；普通响应正常转发。入口保持 HTTP/1.1，避免 HTTP/2 无 Content-Length 的 DATA 请求绕过自动登录的空请求体判断。

生成配置保存在 `log/.nginx-<port>/nginx.conf`，包含启动 token：目录 `700`、文件 `600`、运行目录排除 Git。请求体、HTTP 代理、FastCGI、uWSGI、SCGI 的临时目录都显式放在该运行目录下，普通用户启动无需创建 `/var/lib/nginx/` 等系统目录。正常退出或配置校验失败时删除配置；访问日志关闭，错误日志脱敏后写入 `log/dsh-token-proxy.log`。不要打印或分享生成配置。

已核查上游 DSH `0.2.1-rc.2`：原生 Cookie、Host/Origin 校验、流式传输、gzip 和 TLS 均已有实现，本目录复用其能力；`dsh-client-connection`、`dsh-host-webserver` 未提供本入口所需的通用自动登录反向代理，因此使用 Nginx 配置完成。

## 验证

```bash
python3 -B -m unittest discover -s ds-harness -p 'test_*.py' -v
bash -n ds-harness/dsh_web_run.sh
```

测试使用临时证书、随机本地端口和模拟服务，覆盖安装计划、源码校验与失败清理、证书校验、Nginx 登录/Cookie、HTTPS/WSS、连接复用、流式传输、请求不重放、全部临时目录权限和启动器生命周期，不启停线上服务。代理集成测试需要先安装项目本地 Nginx。`test_support.py` 提供共享证书和本地 Nginx 测试夹具。
