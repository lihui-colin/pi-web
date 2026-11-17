# Orca Server

目录名沿用 `ocra_ws`。需要 Linux（x64/arm64、glibc）、Python 3、curl、tar、sha256sum 和 flock。安装官方 server-only 发布包，安装时查询官方最新稳定版本，使用官方发布元数据中的 SHA256 校验，无需系统 Node 或桌面环境。

```bash
bash ocra_ws/install.sh
bash ocra_ws/ocra_web_run.sh start
bash ocra_ws/ocra_web_run.sh status
bash ocra_ws/ocra_web_run.sh stop
```

脚本按自身位置定位目录，可以从任意工作目录执行。安装只准备程序和配置，不会启动或停止服务；已安装最新版本时直接跳过；发现版本不同时提示是否更新，只有输入 y/yes 才更新，直接回车或无输入则跳过。保留已有配置，更新也不会自动重启运行中的服务。程序、下载缓存、日志和进程记录均在本目录的 `data/` 下，不更改全局 Orca 安装。

首次运行会从 `ocra.conf.example` 创建 `data/ocra.conf`：

```json
{
  "ip": "10.30.0.25",
  "port": 25225
}
```

`ip` 是客户端可访问的主机地址；服务监听 `0.0.0.0`，端口来自 `port`，拒绝公网来源。容器环境需要宿主机将对应端口映射到容器。启动只负责启动和就绪检查，不生成配对链接，也不写入配置。需要配对新设备时，按需执行（地址使用 `data/ocra.conf` 中的 `ip`）：

```bash
env -u ORCA_ENVIRONMENT -u ORCA_PAIRING_CODE data/orca-server/bin/orca-ide pair --address 10.30.0.25
```

将输出的链接粘贴到客户端的配对入口。配对链接用于一次性配对，含访问凭据，不保存到配置文件。已配对设备使用自己的凭据连接，无需每次启动重新配对。实际配置权限为 `600`，整个 `data/` 不提交 Git。旧配置中的 `pairingUrl` 字段可删除，脚本不再读取或更新它。

默认使用原生 Chat 通过 Orca 自身的用户设置管理：`agentDefaultSurface` 设为 `chat`，`nativeChatProviders.codex` 设为 `true`。这是 Orca profile 中的设置，不是 `data/ocra.conf` 字段。安装保留用户设置，不修改官方程序包，也不强制覆盖用户选择。已有 CLI 会话不会自动转为原生 Chat。

当前版本的远程 `settings.update` 接口未开放这两个字段。可通过桌面设置界面调整；如需离线维护 SQLite profile，必须在所属服务停止后备份数据库，并同时维护 settings 文档的内容哈希和修订号。

Orca 自身仍使用当前用户的官方默认配置目录（Linux 通常为 `~/.config/orca`），保留已有账号、项目、配对身份和会话。首次运行前需保证该 profile 未被其他 Orca 实例占用。同一 profile 只能运行一个服务。

`ocra_web_run.sh stop` 会中断该服务的客户端连接，执行前请确认任务可以中断。停止仅依据 `data/server.json` 中的 PID 和进程启动时间发送 SIGTERM，不接管或停止其他来源启动的服务。端口被已有进程占用时，`ocra_web_run.sh start` 会报错；应在安排好维护窗口后，用原有方式停止旧服务，再使用本目录脚本启动。修改 IP 或端口后，也需要在允许中断时先停止、再启动。

日志：`data/server.log`；进程记录：`data/server.json`。首次启动不向日志打印配对码。状态脚本就绪时退出码为 0，未就绪或未托管时为 1。

验证：

```bash
python3 -B -m unittest discover -s ocra_ws/tests -p 'test_*.py'
```

上游：[server-only 发布包](https://github.com/stablyai/orca/releases/tag/v1.4.258)、[Remote Orca Servers](https://orca.dev/docs/remote-servers)。
