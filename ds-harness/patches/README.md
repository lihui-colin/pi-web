# DS Bot 统一补丁

所有补丁实现、版本校验、备份与回滚都集中在 **`ds_bot_apply.py`**，仅支持 **ds-bot 0.2.6 + DSH chat/conversation 0.2.2-alpha.2**。旧版本分支、独立补丁脚本和旧 Hero 实验入口已删除。未知版本或匹配点变化会停止，不猜测兼容性。

## 安装与检查

主安装器 `dsh_install.sh` 调用插件安装器 `dsh_plugins_install.sh`；插件安装成功后，后者自动执行统一补丁。首次安装、`--upgrade`、插件已安装而跳过下载时都会执行，防止重新安装覆盖补丁或遗漏共用输入框修复。补丁失败会使安装返回非零退出码；`--dry-run` 只打印计划，不修改文件。

```sh
bash ds-harness/dsh_install.sh
# 单独补装插件并应用全部补丁
bash ds-harness/dsh_plugins_install.sh
# 手动应用／只检查全部补丁
python3 ds-harness/patches/ds_bot_apply.py
python3 ds-harness/patches/ds_bot_apply.py --check
# 回归测试
python3 -B -m unittest discover -s ds-harness -p 'test_ds_bot*.py'
python3 -B -m unittest discover -s ds-harness -p 'test_dsh_composer_enter.py'
python3 -B -m unittest discover -s ds-harness -p 'test_dsh_plugins_install.py'
```

默认定位本服务的 web profile 与 PATH 中的 DSH 安装；测试或明确的自定义安装可传 `--bot-dir` 和 `--host-dir`（DSH 的 `node_modules/@deepseek-ai` 目录）。升级到其他版本前必须重新核对上游实现；安装器仍按现有策略选择依赖版本，不会为了通过补丁检查静默降级。

## 包含的修复

- **历史记录**：通过原生 ChatFlow 展示归档分段，空会话有历史时进入正常聊天视图；保留分页和插槽所有权，不恢复旧 Hero 容器。
- **提示词接口**：当前 DSH 在 prompt waterfall 结束后附加工具，补丁不再在该钩子访问 tools；保留 sections 过滤、tools.restrict 与执行 guard。已打补丁的当前 0.2.6 安装会转换为同一实现，不支持旧宿主接口。
- **布局**：修复移动侧栏网格、抽屉占位、窄侧栏名称、群聊头像和操作按钮；手机长回复使用可用宽度。手机与 PC 输入框均为上下两行，工具按钮间距 8px。
- **共用输入框**：普通 DSH 和 ds-bot 手机 Enter 只换行，点击按钮发送；PC 保留 Enter 发送、Shift+Enter 换行。复用宿主移动设备检测，保留输入法组合保护和 `beforeinput` 换行处理。

## 校验与生效

先核验全部包版本和四个目标文件，再统一写入。每个目标在同目录暂存后原子替换；原件与清单备份到 `ds-harness/log/patch-backups/`，后续写入失败会回滚已完成的替换。进程被强制终止或断电后，先检查备份及 `--check` 结果。

安装器不启停服务。运行实例可能缓存前端 bundle 或服务端模块，安装成功不代表线上已更新；应检查实际 `/plugins/` 响应。需要重载时先检查活跃任务、保存恢复信息，再安排维护，不能默认重启。

核查依据：2026-11-02/03 的本机发布包中，DS Bot 0.2.6 仍依赖 handoff 展示历史、直接访问 prompt tools 并采用同行输入布局；DSH 0.2.2-alpha.2 的输入键盘逻辑没有手机 Enter 分支。这些匹配点经严格校验，未来版本需重新核查。

2026-11-03 经授权重启 25228 后，普通 DSH 与 Chief 均完成线上手机换行和 PC 快捷键验证，未发送模型测试消息；25028/25128 的进程未变化。合并补丁的回归覆盖独立单文件执行、四个目标全量应用、缺失输入框补丁检测、幂等性、未知版本拒绝、失败不写入及安装入口调用。历史排查记录见 [迁移文档](../MIGRATION.md)。
