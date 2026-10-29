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

浏览器访问 `https://<server_ip>:<port>/`，默认地址为 `https://10.30.0.25:25228/`。该端口只接受 HTTPS，旧 HTTP 书签需更新。启动顺序为 `magpie serve` → 回环地址上的 dsh → 对外 HTTPS 入口代理。重复 `start` 会复用现有进程；代理单独退出后，再次 `start` 会复用运行中 dsh 的实际端口。

确认没有需要保留的运行中任务后，按相反顺序停止：

```bash
./ds-harness/dsh_web_run.sh stop
```

停止后清除 token；日志和 PID 保存在本目录。配置文件仅当前用户可读写，日志会隐藏启动 token；配置、`tls/` 证书目录、日志、PID 和 Python 缓存均不提交 Git。修改配置后需在合适时机先 `stop` 再 `start`；单独更新入口证书只需重启代理，保留 dsh 后端及运行中的任务。

## 安装与更新

```bash
bash ds-harness/dsh_install.sh
```

默认跳过 PATH 中已有的 DSH、pnpm 和 magpie；插件同时检查 web profile 的依赖声明及实际安装文件，只补装缺失项。官方 Codex 插件版本与 DSH 不一致时仍会对齐。使用 `--upgrade` 可主动更新全部程序和插件。

需要安装时，脚本使用 `latest` 安装 DSH、pnpm 和第三方插件，官方 `@deepseek-ai/dsh-subagent-codex` 按安装后的 `dsh --version` 选择同版发布包。该插件的 `latest` 标签可能仍指向旧版本；已核对 npm 发布元数据，`0.2.1-rc.2` 的 DSH peer 依赖均要求 `0.2.1-rc.2`。保留上游插件管理器的兼容性检查，不自动添加 `allow-version` 豁免；同版包缺失或不兼容时停止安装。

安装不启停服务；在新机器或目标 DSH 已停机时执行。可先用 `--dry-run` 预览，仅在预览需要安装或更新 DSH 时，Codex 插件版本使用占位符，实际执行时才会确定。

## 代理行为

代理使用 Python 标准库终止 TLS、解析 HTTP 和分块响应，WSS 保留升级握手并双向转发；到回环地址上游的连接仍为 HTTP。首次访问 `/` 时补上启动 token，在代理内部完成登录交换，再把首页和 `HttpOnly; SameSite=Strict; Secure` Cookie 一起返回，避免手机从其他网页进入时发生重定向循环。已有 Cookie、自带 token 的请求保持原样；`/connect` 保留独立 API 会话的登录重定向。

已核对本机 `@deepseek-ai/dsh@0.2.1-rc.2` 的 `dsh-client-connection`：token 换 Cookie、Host 校验和浏览器 WebSocket 授权均由上游提供，本目录复用这些能力。免手动输入 token 的入口只应供可信网络使用。

上游 `dsh web --help` 和 `dsh-web-app/README.zh.md` 已提供原生 `--tls-cert/--tls-key`，也支持通过 `--public-url https://…` 配合反向代理。本目录在现有 token 代理上接入 TLS，使入口证书可独立更新；保留上游的 HTTPS Origin 校验，并为上游签发的登录 Cookie 补上 `Secure`。

## 验证

```bash
python3 -m unittest discover -s ds-harness -p 'test_*.py' -v
bash -n ds-harness/dsh_web_run.sh
```

测试需要 OpenSSL，使用临时证书、临时端口和模拟服务，覆盖登录交换、HTTP 请求体、分块响应、HTTPS/WSS、证书验证、Secure Cookie，以及重复启动、代理恢复、停止和 token 脱敏，不启停线上服务。
