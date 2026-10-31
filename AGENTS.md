# 代码 Review

- Review 时，重点检查补丁代码在上游代码库中是否已有实现，或上游是否已提供类似功能；结合上游实现评估补丁是否重复、是否可复用上游能力，并在 review 结论中说明核查依据。无法核实时应明确说明，不要默认上游没有实现。

# 服务重启与会话保护

- 会话运行在服务中；停止或重启服务会中断会话，当前执行任务的会话也可能随之终止。不要把重启服务作为修改后的默认验证步骤。
- 重启前检查活跃会话和正在执行的任务，明确中断影响，安排在任务完成或允许中断的时机执行；无法确认会话状态时，不应假定重启无影响。
- 重启前保存工作、执行进度和恢复步骤。若当前任务通过该服务的会话执行，应使用独立于该服务会话的维护进程完成停止、启动和就绪检查，不能依赖被终止的会话继续执行后续步骤。
- 确需重启时，先停止服务，再开启服务，并检查服务是否就绪。Pi Web 使用 `scripts/pi-web-run-jmfederico.sh`；DSH 使用 `ds-harness/dsh_web_run.sh stop` 和 `ds-harness/dsh_web_run.sh start`，不要混用两个服务的脚本。
- Paseo 服务统一通过 `paseo-ws/paseo_web_run.sh` 管理，使用 `start`、`stop`、`status`；`paseo-ws/install.sh` 仅用于安装环境。访问配置为 `paseo-ws/data/paseo.conf`（仅 `ip` 和 `port`），官方完整配置为独立的 `paseo-ws/data/config.json`；`data/` 与 `runtime/` 不纳入 Git，后端监听 `127.0.0.1:25226`；独立 Nginx 提供 `https://10.30.0.25:25227/`，使用独立的 `paseo-ws/data/tls/10.30.0.25` 证书。管理脚本统一启停后端与 Nginx，安装脚本调用 Paseo 自身的 Nginx 本地安装器，不依赖其他服务目录。
