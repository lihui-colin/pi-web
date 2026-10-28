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
- `dsh_token`：启动时自动提取并更新，不需要手动填写。

浏览器访问 `http://<server_ip>:<port>/`。启动顺序为 `magpie serve` → 回环地址上的 dsh → 对外入口代理。重复 `start` 会复用现有进程；代理单独退出后，再次 `start` 会复用运行中 dsh 的实际端口。

确认没有需要保留的运行中任务后，按相反顺序停止：

```bash
./ds-harness/dsh_web_run.sh stop
```

停止后清除 token；日志和 PID 保存在本目录。配置文件仅当前用户可读写，日志会隐藏启动 token；配置、日志、PID 和 Python 缓存均不提交 Git。修改配置后需在合适时机先 `stop` 再 `start`。

## 代理行为

代理使用 Python 标准库解析 HTTP 和分块响应，WebSocket 保留升级握手并双向转发。首次访问 `/` 时补上启动 token，在代理内部完成登录交换，再把首页和原有 `HttpOnly; SameSite=Strict` Cookie 一起返回，避免手机从其他网页进入时发生重定向循环。已有 Cookie、自带 token 的请求保持原样；`/connect` 保留独立 API 会话的登录重定向。

已核对本机 `@deepseek-ai/dsh@0.2.1-rc.2` 的 `dsh-client-connection`：token 换 Cookie、Host 校验和浏览器 WebSocket 授权均由上游提供，本目录复用这些能力。免手动输入 token 的入口只应供可信网络使用。

## 验证

```bash
python3 -m unittest discover -s ds-harness -p 'test_*.py' -v
bash -n ds-harness/dsh_web_run.sh
```

测试使用临时端口和模拟服务，覆盖登录交换、HTTP 请求体、分块响应、WebSocket，以及重复启动、代理恢复、停止和 token 脱敏，不启停线上服务。
