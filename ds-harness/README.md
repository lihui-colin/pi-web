# DeepSeek Harness

本目录管理 `magpie → DSH 回环后端 → Nginx HTTPS 入口`。需要 Linux、Bash、Node.js ≥24、npm、curl、Python ≥3.10、OpenSSL 和 Nginx ≥1.24（含 HTTP SSL 模块，缺失时可由安装器补装）。入口运行时使用独立配置，不修改或启停系统 Nginx 服务。

## 首次部署

在仓库根目录执行：

```bash
bash ds-harness/dsh_install.sh
cp ds-harness/dsh.conf.example ds-harness/dsh.conf
# 编辑 dsh.conf 中的 server_ip 和 port
bash ds-harness/dsh_cert.sh
./ds-harness/dsh_web_run.sh start
```

`server_ip` 填写浏览器访问的 IP 或域名；`port` 默认 `25228`；`dsh_token` 启动时自动更新。访问 `https://<server_ip>:<port>/`，默认地址为 `https://10.30.0.25:25228/`。入口只接受 HTTPS，普通 URL 自动登录，适用于可信网络。

启动器固定读取 `tls/<server_ip>/fullchain.pem` 和 `privkey.pem`，忽略旧配置中的 `tls_cert`、`tls_key`。域名目录转为小写，IPv6 冒号替换为下划线，例如 `::1` 对应 `tls/__1/`。证书缺失或无效时，在启动服务前退出。

## 安装与更新

```bash
bash ds-harness/dsh_install.sh --dry-run
bash ds-harness/dsh_install.sh --upgrade
```

默认复用已有的 DSH、pnpm 和 magpie，只补装缺失插件；`--upgrade` 更新 DSH、pnpm、Magpie 和插件。官方 Codex 插件版本与 DSH 对齐，保留上游兼容性检查，同版包缺失或不兼容时停止安装。安装器不读取项目配置、不生成证书、不启停服务；安装或更新应在目标 DSH 停机时执行。

Nginx 缺失时，Debian/Ubuntu 使用 `apt-get`，macOS 安装器使用 `brew install nginx`；其他平台请预先安装。APT 安装需要 root 或 sudo，仅该系统包操作提权，DSH 与插件仍以当前用户安装。已有 Nginx 不随 `--upgrade` 更新，只检查版本和 HTTP SSL 模块；版本过低或缺少模块时停止并提示处理。

APT 操作通过临时 `policy-rc.d` 禁止 Nginx 服务启停，并用 `NEEDRESTART_SUSPEND=1` 跳过 needrestart 钩子；正常退出或安装失败后清理本次创建的策略。已有策略不会覆盖，若其允许 Nginx 启停则停止自动安装。Homebrew 不调用 `brew services`。`--dry-run` 仅显示安装计划，不提权、不创建策略、不运行包管理器。

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

证书脚本只生成或校验证书，不修改配置、不启停服务。默认输出到配置文件所在目录的 `tls/<server_ip>/`；`--tls-dir` 改变输出根目录，`--tls-host` 添加额外 SAN。自定义导出后，启动前仍需将证书部署到本项目 `tls/<地址>/`。

每个地址目录包含：

- `fullchain.pem`、`privkey.pem`：服务端证书链和无口令私钥。
- `ca.pem`、`ca.crt`：内容一致的公开根证书，客户端导入 `ca.crt` 建立信任。
- `ca-key.pem`：CA 私钥，仅保留在服务器，不发给客户端。

已有证书会经过校验并保留，不完整或不匹配的文件不会被覆盖；旧的平铺证书保持不变。目录权限为 `700`、私钥为 `600`。变更 `server_ip` 后生成对应地址的证书；客户端已信任同一 CA 时无需重复导入。证书和私钥不入 Git，迁移机器需单独安全传输，或重新生成并信任 CA。

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

## 启停与运行文件

重复 `start` 会复用已有进程；代理单独退出后，再次 `start` 会复用 DSH 的实际回环端口。不要另外启动一套 `magpie serve` 或 `dsh web`。检查 Magpie 网关：

```bash
magpie healthcheck
```

确认运行中的任务可中断后停止全部服务：

```bash
./ds-harness/dsh_web_run.sh stop
```

停止顺序为入口代理、DSH、Magpie，完成后清除启动 token。配置、日志、PID 均保存在本目录并排除 Git。`dsh-token-proxy.pid` 记录 Nginx 监督进程，保留该名称以识别现有实例。

修改代码不会自动替换运行进程。修改配置后应安排维护；只更新入口证书或代理时可保留 DSH 后端，但浏览器连接仍会短暂断开，不把重启作为默认验证步骤。

## Nginx 代理

`dsh_nginx.py` 仅生成/校验配置、管理 Nginx 前台进程并脱敏错误日志。HTTPS、HTTP/WebSocket、连接池、TLS 会话缓存和流式传输均由 Nginx 处理；请求/响应缓冲关闭，DSH 原有 gzip 透传。

无请求体、无显式 token 的首页 GET 在内部完成 token→Cookie→首页交换，浏览器直接收到页面和 `HttpOnly; SameSite=Strict; Secure` Cookie。有效 Cookie 直接复用，失效 Cookie 仅在首页 401 时重新认证；API、WebSocket、写入和带请求体的请求不自动重放。`/connect` 补齐缺失 token 并保留上游 302。

Cookie 使用 DSH 原生 authority 哈希命名，只向后端传递本实例登录 Cookie，同时接受旧的 `dsh<port>_` 前缀，原生名称优先。不同端口的 Cookie 隔离不改变浏览器向同主机各端口发送 Cookie 的规则。登录交换仅接受预期的 `Location: ./` 和单个本实例 Cookie，异常响应返回 502；普通响应正常转发。入口保持 HTTP/1.1，避免 HTTP/2 无 Content-Length 的 DATA 请求绕过自动登录的空请求体判断。

生成配置保存在 `.nginx-<port>/nginx.conf`，包含启动 token：目录 `700`、文件 `600`、运行目录排除 Git。正常退出或配置校验失败时删除配置；访问日志关闭，错误日志脱敏后写入 `dsh-token-proxy.log`。不要打印或分享生成配置。

已核查上游 DSH `0.2.1-rc.2`：原生 Cookie、Host/Origin 校验、流式传输、gzip 和 TLS 均已有实现，本目录复用其能力；`dsh-client-connection`、`dsh-host-webserver` 未提供本入口所需的通用自动登录反向代理，因此使用 Nginx 配置完成。

## 验证

```bash
python3 -B -m unittest discover -s ds-harness -p 'test_*.py' -v
bash -n ds-harness/dsh_web_run.sh
```

测试使用临时证书、随机本地端口和模拟服务，覆盖安装计划、证书校验、Nginx 登录/Cookie、HTTPS/WSS、连接复用、流式传输、请求不重放和启动器生命周期，不启停线上服务。`test_support.py` 仅提供共享测试证书生成函数。
