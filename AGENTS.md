# 目录与 Pi Web 维护

- 仓库按服务分目录维护：Pi Web 位于 `pi-web/`，DSH 位于 `ds-harness/`，Paseo 位于 `paseo-ws/`。新增代码、补丁、配置和运行数据放在所属服务目录，不再写入旧的根目录布局或其他服务的数据目录。
- Pi Web 的脚本、补丁、测试和文档分别位于 `pi-web/scripts/`、`pi-web/patches/`、`pi-web/tests/` 和 `pi-web/docs/`；本地配置为 `pi-web/data/pi-web.conf`，模板为 `pi-web/pi-web.conf.example`。发布源码位于 `pi-web/data/pi-web-releases/`，上游缓存为 `pi-web/data/pi-web-upstream.git`，默认实例状态为 `pi-web/data/pi-web/<port>/state`，日志和 PID 位于其上一级。
- 从仓库根安装使用 `bash pi-web/scripts/install.sh`，验证使用 `node --test pi-web/tests/*.test.mjs`；Pi Web 自身文档中的相对路径以 `pi-web/` 为基准。脚本应根据自身位置确定组件根目录，不要用 Git 仓库根目录定位 Pi Web 数据或补丁。
- 本地配置、实例数据、上传附件和安装依赖不提交 Git。旧发布版本、历史归档及 `paseo-ws/data/pi-web*` 兼容链接已清理，不要恢复旧目录；保留当前安装版本、有效配置、实例状态、附件及上游缓存。
- 根目录 `data` 和 `.pi-web` 兼容软链接已删除，不要重新创建。全局 Pi Web 安装链接直接指向 `pi-web/data/pi-web-releases/` 中的当前版本；数据与附件仅使用 `pi-web/data/` 和 `pi-web/.pi-web/`。历史附件若记录了旧路径，应更新引用，不能恢复根目录软链接。删除 release 前仍需核查全局命令与运行进程的依赖。

# 代码 Review

- Review 时，重点检查补丁代码在上游代码库中是否已有实现，或上游是否已提供类似功能；结合上游实现评估补丁是否重复、是否可复用上游能力，并在 review 结论中说明核查依据。无法核实时应明确说明，不要默认上游没有实现。

# 服务重启与会话保护

- 会话运行在服务中；停止或重启服务会中断会话，当前执行任务的会话也可能随之终止。不要把重启服务作为修改后的默认验证步骤。
- 重启前检查活跃会话和正在执行的任务，明确中断影响，安排在任务完成或允许中断的时机执行；无法确认会话状态时，不应假定重启无影响。
- 重启前保存工作、执行进度和恢复步骤。若当前任务通过该服务的会话执行，应使用独立于该服务会话的维护进程完成停止、启动和就绪检查，不能依赖被终止的会话继续执行后续步骤。
- 确需重启时，先停止服务，再开启服务，并检查服务是否就绪。Pi Web 使用 `pi-web/scripts/pi-web-run-jmfederico.sh`；DSH 使用 `ds-harness/dsh_web_run.sh stop` 和 `ds-harness/dsh_web_run.sh start`，不要混用两个服务的脚本。
- Paseo 服务统一通过 `paseo-ws/paseo_web_run.sh` 管理，使用 `start`、`stop`、`status`；`paseo-ws/install.sh` 仅用于安装环境。访问配置为 `paseo-ws/data/paseo.conf`（`ip`、`port` 和可选出站网络代理 `networkProxy`），Paseo 官方数据目录为 `paseo-ws/data/.paseo`（`PASEO_HOME`），完整配置为 `paseo-ws/data/.paseo/config.json`；`data/` 与 `runtime/` 不纳入 Git，后端监听 `127.0.0.1:25226`；独立 Nginx 提供 `https://10.30.0.25:25227/`，使用独立的 `paseo-ws/data/tls/10.30.0.25` 证书。管理脚本统一启停后端与 Nginx，安装脚本调用 Paseo 自身的 Nginx 本地安装器，不依赖其他服务目录。

- Paseo 与 DSH 除顶层入口外的辅助脚本、源码、补丁、测试和配置模板统一位于各自 `srcs/`。顶层保留 `paseo-ws/install.sh`、`paseo-ws/paseo_web_run.sh`、`ds-harness/dsh_install.sh`、`ds-harness/dsh_plugins_install.sh`、`ds-harness/dsh_nginx_install.sh`、`ds-harness/dsh_cert.sh`、`ds-harness/dsh_web_run.sh`、`paseo-ws/paseo-proxy.sh` 和 `ds-harness/dsh_proxy.sh` 作为安装、证书生成、服务管理与代理配置入口；数据、日志及安装依赖路径不变。验证使用 `node --test paseo-ws/srcs/test-*.cjs`、`python3 -B paseo-ws/srcs/test-nginx.py` 和 `python3 -B -m unittest discover -s ds-harness/srcs -p "test_*.py"`。
