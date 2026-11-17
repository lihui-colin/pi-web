# Orca Server

目录名沿用 `ocra_ws`。需要 Linux（x64/arm64、glibc）、Python 3、curl、tar、sha256sum 和 flock。安装官方 server-only 发布包，固定版本为 1.4.258，使用官方 SHA256 校验，无需系统 Node 或桌面环境。

```bash
bash ocra_ws/install.sh
bash ocra_ws/ocra_web_run.sh start
bash ocra_ws/ocra_web_run.sh status
bash ocra_ws/ocra_web_run.sh stop
```

脚本按自身位置定位目录，可以从任意工作目录执行。安装只准备程序和配置，不会启动或停止服务；重复安装复用相同版本，保留已有配置。程序、下载缓存、日志和进程记录均在本目录的 `data/` 下，不更改全局 Orca 安装。

首次运行会从 `ocra.conf.example` 创建 `data/ocra.conf`：

```json
{
  "ip": "10.30.0.25",
  "port": 25225,
  "pairingUrl": ""
}
```

`ip` 是客户端可访问的主机地址；服务监听 `0.0.0.0`，端口来自 `port`，拒绝公网来源。容器环境需要宿主机将对应端口映射到容器。启动就绪后，脚本调用 `orca pair --address <ip>`，验证配对链接内的地址与配置相符，再将完整链接写入 `pairingUrl`；已启动时再次执行 `ocra_web_run.sh start` 可刷新/补写链接，不会重启。将链接粘贴到 Orca 桌面客户端 Settings → Remote Orca Servers → Add Server。配对链接含访问凭据，实际配置权限为 `600`，整个 `data/` 不提交 Git。

Orca 自身仍使用当前用户的官方默认配置目录（Linux 通常为 `~/.config/orca`），保留已有账号、项目、配对身份和会话。首次运行前需保证该 profile 未被其他 Orca 实例占用。同一 profile 只能运行一个服务。

`ocra_web_run.sh stop` 会中断该服务的客户端连接，执行前请确认任务可以中断。停止仅依据 `data/server.json` 中的 PID 和进程启动时间发送 SIGTERM，不接管或停止其他来源启动的服务。端口被已有进程占用时，`ocra_web_run.sh start` 会报错；应在安排好维护窗口后，用原有方式停止旧服务，再使用本目录脚本启动。修改 IP 或端口后，也需要在允许中断时先停止、再启动。

日志：`data/server.log`；进程记录：`data/server.json`。首次启动不向日志打印配对码。状态脚本就绪时退出码为 0，未就绪或未托管时为 1。

验证：

```bash
python3 -B -m unittest discover -s ocra_ws/tests -p 'test_*.py'
```

上游：[server-only 发布包](https://github.com/stablyai/orca/releases/tag/v1.4.258)、[Remote Orca Servers](https://orca.dev/docs/remote-servers)。
