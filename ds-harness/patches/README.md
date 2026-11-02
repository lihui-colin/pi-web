# DS Bot 本地兼容补丁

当前统一入口支持 **ds-bot 0.2.6 + DSH chat/conversation 0.2.2-alpha.2**，默认使用本服务的 web profile。先核验所有包版本和代码匹配点，再写入；未知版本或结构会停止，不自动重启服务。

```sh
# 应用全部已核查修复
python3 ds-harness/patches/ds_bot_apply.py
# 只检查，不写文件；缺失补丁返回 1
python3 ds-harness/patches/ds_bot_apply.py --check
# 回归测试
python3 -B -m unittest discover -s ds-harness -p 'test_ds_bot_*.py'
```

## 当前修复

- **历史入口**：`ds_bot_history_native.py` 让有历史分段的空会话进入正常聊天视图，在原生 ChatFlow 前挂载 DS Bot 的 `EarlierParts`。保留消息列居中、分页和插槽所有权，不新增 CSS、Hero 历史容器或固定高度。会话数据不变。
- **接口兼容**：`ds_bot_prompt.py` 仅在提示词组装结果包含 tools 数组时过滤工具；保留 sections 过滤、tools.restrict 和执行 guard。支持 0.2.5 / 0.2.6。新版宿主的 scope-local 工具声明不能再通过该钩子隐藏。
- **手机与侧栏**：`ds_bot_mobile.py` 修复移动侧栏网格和抽屉占位，保留侧栏名称、群聊头像位置及操作按钮浮层。在不超过640px的触屏上放宽回复气泡至可用消息宽度，桌面保持原有宽度规则。支持 0.2.4 / 0.2.5 / 0.2.6，可幂等迁移此前仅保留操作按钮的中间版本。

旧 `ds_bot_history.py` 仅供历史记录与匹配锚点使用，不要重新执行：其 Hero 布局会导致空白、限高和样式冲突。原生补丁遇到仍含旧 Hero 补丁的包会停止，需先恢复对应发布包再应用，不叠加两套入口。

## 上游核查与生效方式

2026-11-02 核对已安装发布包：DS Bot 0.2.6 仍只在 handoff 消息分支挂载历史；DSH conversation 按当前空分段进入 Hero 并跳过 Views，ChatFlow 未提供历史前置插槽；DS Bot 的提示词钩子仍直接读取 `assembled.tools.filter()`，而当前 DSH 在 waterfall 结束后才附加 tools。移动端修改对应的原始匹配点也仍存在。

前端补丁修改发布包，刷新浏览器即可加载；服务端提示词补丁需模块重载或维护重启。安装器不自动执行本补丁，升级覆盖后先核对新版本，再运行检查。应用时在每个目标目录暂存完整文件，再原子替换；原件和目标清单保存在 `ds-harness/log/patch-backups/`。后续写入失败会回滚已完成的替换，回滚失败时按错误提示和备份清单恢复。突然断电或进程被强制终止仍可能中断多文件应用，恢复后先运行检查。

## 验证记录

0.2.6 在实际25228入口以桌面1602×900、触屏390×844验证：Chief 历史分页由18条增至31条，桌面切换其他会话再返回正常；无页面错误和横向溢出。桌面消息列960px、长回复气泡768px，手机消息列及长回复气泡均为273px。测试未发送聊天消息或重启服务。

旧版排查、重启注意事项和会话存储格式见 [迁移记录](../MIGRATION.md)。
