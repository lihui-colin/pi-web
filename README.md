# 本地 Web 服务工作区

各服务的代码、脚本、配置模板和文档分别放在独立目录：

- [Pi Web](pi-web/README.md)：定制补丁、源码同步、安装与服务管理。
- [DeepSeek Harness](ds-harness/README.md)：DSH 安装与服务管理。
- [Paseo](paseo-ws/README.md)：Paseo 安装与服务管理。

## Pi Web

从本仓库根目录执行：

```bash
bash pi-web/scripts/install.sh                         # 安装，不启停服务
bash pi-web/scripts/pi-web-run-jmfederico.sh status     # 查看实例状态
bash pi-web/scripts/pi-web-run-jmfederico.sh start      # 启动
bash pi-web/scripts/pi-web-run-jmfederico.sh stop       # 停止
node --test pi-web/tests/*.test.mjs                    # 验证管理脚本
```

以下路径均相对于仓库根目录；进入 `pi-web/` 后，请按 [Pi Web 文档](pi-web/README.md) 中的相对路径操作。

| 内容 | 位置 |
| --- | --- |
| 安装、同步和服务管理脚本 | [pi-web/scripts/](pi-web/scripts/) |
| 定制补丁与上游基线 | [pi-web/patches/](pi-web/patches/) |
| 脚本测试 | [pi-web/tests/](pi-web/tests/) |
| 配置模板 | [pi-web.conf.example](pi-web/pi-web.conf.example) |
| 本地配置 | `pi-web/data/pi-web.conf` |
| 构建源码与发布版本 | `pi-web/data/pi-web-releases/` |
| 上游 Git 缓存 | `pi-web/data/pi-web-upstream.git` |
| 默认实例状态 | `pi-web/data/pi-web/<port>/state/` |
| 默认实例日志和 PID | `pi-web/data/pi-web/<port>/` |
| 已迁入的工作区附件 | `pi-web/.pi-web/uploads/` |

本地配置、运行数据、附件及依赖不提交 Git。新文件和配置统一使用所属服务目录，不再写入旧的根目录布局或其他服务的数据目录。

## 清理与兼容

旧 Pi Web 发布版本、重复状态、旧配置、历史维护资料、迁移验证临时文件及 Paseo 数据目录中的 `pi-web*` 兼容链接已清理；临时归档 `pi-web/data/legacy-paseo/` 已删除。保留当前安装版本、有效配置、实例状态、附件和上游缓存。

根目录的 `data` 和 `.pi-web` 兼容软链接已删除，不再保留旧入口。全局 Pi Web 安装链接已直接指向 `pi-web/data/pi-web-releases/` 中的当前版本。

实际数据和附件仍完整保存在 `pi-web/data/`、`pi-web/.pi-web/`。历史附件若使用根目录的旧路径，需要将引用更新到新位置。不要重新创建旧目录或兼容链接；删除发布版本前，应先确认全局命令和运行进程已解除引用。

安装、更新和文件清理不自动重启服务。确需重启时，先核查活跃会话并保存恢复信息，在允许中断时先停止再启动。维护约定见 [AGENTS.md](AGENTS.md)。
