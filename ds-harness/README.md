# DeepSeek Harness

Linux 环境，需要 Bash、Python 3.10+，以及 PATH 中可用的 `dsh` 和 `magpie`。

在仓库根目录配置并启动：

```bash
cp ds-harness/dsh.conf.example ds-harness/dsh.conf
./ds-harness/dsh_web_run.sh start
```

`dsh.conf` 中填写：

- `server_ip`：浏览器访问的服务器地址。
- `port`：对外端口，默认 `25228`。
- `tls_cert`、`tls_key`：PEM 证书链和无口令私钥；默认位于 `tls/fullchain.pem`、`tls/privkey.pem`，相对路径以本目录为基准。证书 SAN 需包含 `server_ip` 对应的 IP 或域名。
- `dsh_token`：启动时自动提取并更新，不需要手动填写。

先放好证书并限制私钥权限（例如目录 `700`、私钥 `600`），再运行 `start`；证书缺失或无法加载时会在启动服务前退出。使用私有 CA 签发的证书时，手机及电脑需信任该 CA；已信任同一 CA 的设备无需重复安装。

浏览器访问 `https://<server_ip>:<port>/dsh-<port>/`，默认地址为 `https://10.30.0.25:25228/dsh-25228/`。路径自动根据 `port` 生成，无需额外配置。该端口只接受 HTTPS，旧 HTTP 书签需更新。启动顺序为 `magpie serve` → 回环地址上的 dsh → 对外 HTTPS 入口代理。重复 `start` 会复用现有进程；代理单独退出后，再次 `start` 会复用运行中 dsh 的实际端口。

确认没有需要保留的运行中任务后，按相反顺序停止：

```bash
./ds-harness/dsh_web_run.sh stop
```

停止后清除 token；日志和 PID 保存在本目录。配置文件仅当前用户可读写，日志会隐藏启动 token；配置、`tls/` 证书目录、日志、PID 和 Python 缓存均不提交 Git。修改配置后需在合适时机先 `stop` 再 `start`；单独更新入口证书只需重启代理，保留 dsh 后端及运行中的任务。

安装脚本同时导出 `tls/ca.crt`，用于手机或电脑导入信任；它是 PEM 编码的公开根证书，与 `ca.pem` 内容对应。`fullchain.pem` 仍用于服务端。已有证书缺少 `.crt` 时可执行：

```bash
bash ds-harness/dsh_install.sh --cert-only
```

此操作校验并保留已有证书、私钥，仅补齐根证书导出，不需要重启服务。不要把 `ca-key.pem` 或 `privkey.pem` 发给客户端。

## 安装与更新

```bash
bash ds-harness/dsh_install.sh
```

默认跳过 PATH 中已有的 DSH、pnpm 和 magpie；插件同时检查 web profile 的依赖声明及实际安装文件，只补装缺失项。官方 Codex 插件版本与 DSH 不一致时仍会对齐。使用 `--upgrade` 可主动更新全部程序和插件。

需要安装时，脚本使用 `latest` 安装 DSH、pnpm 和第三方插件，官方 `@deepseek-ai/dsh-subagent-codex` 按安装后的 `dsh --version` 选择同版发布包。该插件的 `latest` 标签可能仍指向旧版本；已核对 npm 发布元数据，`0.2.1-rc.2` 的 DSH peer 依赖均要求 `0.2.1-rc.2`。保留上游插件管理器的兼容性检查，不自动添加 `allow-version` 豁免；同版包缺失或不兼容时停止安装。

安装不启停服务；在新机器或目标 DSH 已停机时执行。可先用 `--dry-run` 预览，仅在预览需要安装或更新 DSH 时，Codex 插件版本使用占位符，实际执行时才会确定。

### Magpie 下载失败

安装器最多尝试 3 次。若出现 `SSL connection timeout`、`Connection reset by peer` 或 DNS 解析超时，需要先恢复服务器的网络连接，或使用服务器能访问的代理：

```bash
MAGPIE_PROXY=http://<代理主机>:<端口> bash ds-harness/dsh_install.sh
```

代理位于另一台电脑时，填写其局域网地址；`127.0.0.1` 表示运行安装脚本的服务器自身。`MAGPIE_PROXY` 同时用于下载官方安装脚本和官方安装器内部请求。官方还支持 `MAGPIE_MIRROR`，但它只替换 GitHub 二进制下载地址，安装脚本、版本信息及 SHA-256 校验值仍来自 `usemagpie.ai`，因此无法解决官网不可达的问题。

本项目启动脚本要求 `magpie` 可用，安装失败时停止后续步骤，不将缺少 Magpie 的环境报告为安装成功。

## magpie 使用

magpie 统一管理模型服务商、订阅账号和模型路由。DSH 把模型请求发给本机 magpie 网关，再由网关转发到所选渠道；项目文件和工具仍由 DSH 处理。

### 安装与配置模型来源

安装脚本会补装缺失的 DSH、插件和 magpie，并按 DSH 配置生成或校验 HTTPS 证书；主动更新请使用上文的 `--upgrade`。先复制配置示例并填写 `server_ip`，再在仓库根目录运行；已有配置不需要重新复制。安装脚本不启动服务，执行前应确认目标 DSH 已停机。

```bash
bash ds-harness/dsh_install.sh --dry-run
bash ds-harness/dsh_install.sh
```

安装需要 Node.js >=24、OpenSSL、npm、curl 和 sh；运行项目启动脚本还需要 Python 3.10+。模型账号和 API Key 需要另外配置或恢复。

可打开 magpie 界面的 **Providers → Add provider** 添加模型服务商和 API Key。服务器没有桌面时，可通过以下命令打开本机 Web 管理入口，按终端输出访问；该入口默认绑定回环地址，远程机器可通过 SSH 本地端口转发访问，不要直接把带登录凭据的管理链接公开。

```bash
magpie web --no-open
```

也可以通过 CLI 登录支持的订阅账号，例如 Codex / ChatGPT：

```bash
magpie accounts add codex
```

已有 magpie 配置可以直接复用。跨机器迁移时，可使用 `magpie backup` / `magpie restore` 导出和恢复加密备份。

### 为 DSH 选择模型

```bash
# 查看 DSH 当前配置
magpie dsh

# 列出 DSH 可选的模型，复制输出中的完整 provider/model 标识
magpie models dsh

# 使用实际列出的标识替换 <provider/model>
magpie dsh <provider/model>
```

`<provider/model>` 是占位符，不要原样执行。例如，只有列表中存在 `codex/gpt-6.1-sol` 时，才可运行 `magpie dsh codex/gpt-6.1-sol`。

查询或设置推理强度：

```bash
magpie dsh model
magpie dsh effort
magpie dsh effort high

# 恢复该字段原来的设置
magpie dsh effort default
```

推理强度取值取决于模型支持情况。切换后建议新建一个 DSH 会话，检查实际使用的模型；既有会话可能保留自己的模型选择。DS Bot 的每个 Bot 也有独立的模型设置，需要在 Bot 界面中核对。

若要取消 magpie 对 DSH 的接管，恢复接入前保存的配置：

```bash
magpie dsh default
```

### 启动与检查

本项目统一使用 `./ds-harness/dsh_web_run.sh start`，由它启动或复用 magpie 网关、DSH 和 HTTPS 代理。已有实例运行时，不需要另外启动一套 `magpie serve` 或 `dsh web`。可检查 magpie 网关是否响应：

```bash
magpie healthcheck
```

独立使用、不经过本项目启动脚本时，才需要分别运行 `magpie serve` 和 `dsh web --no-open`；后者不会自动采用本项目的 HTTPS 证书或入口代理配置。

## 代理行为

代理使用 Python 标准库终止 TLS、解析 HTTP 和分块响应，WSS 保留升级握手并双向转发；到回环地址上游的连接仍为 HTTP。首次访问实例路径 `/dsh-<port>/` 时补上启动 token，在代理内部完成登录交换，再把首页和 `HttpOnly; SameSite=Strict; Secure` Cookie 一起返回，避免手机从其他网页进入时发生重定向循环。已有有效 Cookie、自带 token 的请求保持原样；首页的失效 Cookie 会触发一次重新认证，API 和写入请求不会被自动重放；实例路径下的 `/connect` 保留独立 API 会话的登录重定向。

代理剥离 `/dsh-<port>/` 前缀后转发 HTTP/API/WebSocket，登录 Cookie 的 `Path` 改为该实例路径，并改写站内绝对路径跳转。访问端口根路径或未带尾斜杠的实例路径会跳转到规范入口；其他前缀不会转发到后端。不同端口隔离 localStorage 等同源存储，不同 Cookie Path 限制 Cookie 发送范围；路径不构成安全隔离边界。

从旧的根路径部署迁移时，DSH 的 `--public-url` 和代理路径需要同时更新。`start` 检测到旧实例时会报错提示，不自动停止会话；请在任务完成后安排停止、启动，并清理一次旧的根路径 Cookie。既有根路径部署在代码更新后继续运行，直至安排迁移。

已核对本机 `@deepseek-ai/dsh@0.2.1-rc.2` 的 `dsh-client-connection`：token 换 Cookie、Host 校验和浏览器 WebSocket 授权均由上游提供，本目录复用这些能力。免手动输入 token 的入口只应供可信网络使用。

上游 `dsh web --help` 和 `dsh-web-app/README.zh.md` 已提供原生 `--tls-cert/--tls-key`，也支持通过 `--public-url https://…` 配合反向代理。本目录在现有 token 代理上接入 TLS，使入口证书可独立更新；保留上游的 HTTPS Origin 校验，并为上游签发的登录 Cookie 补上 `Secure`。

## 验证

```bash
python3 -m unittest discover -s ds-harness -p 'test_*.py' -v
bash -n ds-harness/dsh_web_run.sh
```

测试需要 OpenSSL，使用临时证书、临时端口和模拟服务，覆盖登录交换、HTTP 请求体、分块响应、HTTPS/WSS、证书验证、Secure Cookie，以及重复启动、代理恢复、停止和 token 脱敏，不启停线上服务。
