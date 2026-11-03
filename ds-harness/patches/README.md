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
- **布局**：修复移动侧栏网格、抽屉占位、窄侧栏名称、群聊头像和操作按钮；手机长回复使用可用宽度。手机与 PC 输入框均为上下两行，工具按钮间距 8px。会话顶栏保留宿主的固定偏好和更多菜单，按页签实际渲染宽度决定折叠，不再按每项 120px 粗估或强制手机只显示 Chat。
- **桌面聊天宽度**：恢复 DSH 原生聊天区左右拖动条，正文和输入框同步调整，保留宿主输入框多出的 32px 内边距空间，沿用宿主的本地宽度记忆（与普通 DSH 聊天共享）。仅在视口至少 1024px、精确指针且支持悬停时启用；触屏与窄屏维持原有布局。
- **共用输入框**：普通 DSH 和 ds-bot 手机 Enter 只换行，点击按钮发送；PC 保留 Enter 发送、Shift+Enter 换行。复用宿主移动设备检测，保留输入法组合保护和 `beforeinput` 换行处理。

- **消息与操作栏**：保留回复气泡和左对齐文字，回复铺满正文宽度，与发送气泡共用右边界。表情、回复、复制、下载在回复下方独占一行，桌面端悬停显示，触屏端（无悬停或粗指针）常驻显示，无需先触摸消息。

## 校验与生效

先核验全部包版本和四个目标文件，再统一写入。每个目标在同目录暂存后原子替换；原件与清单备份到 `ds-harness/log/patch-backups/`，后续写入失败会回滚已完成的替换。进程被强制终止或断电后，先检查备份及 `--check` 结果。

安装器不启停服务。运行实例可能缓存前端 bundle 或服务端模块，安装成功不代表线上已更新；应检查实际 `/plugins/` 响应。需要重载时先检查活跃任务、保存恢复信息，再安排维护，不能默认重启。

核查依据：2026-11-02/03 的本机发布包中，DS Bot 0.2.6 仍依赖 handoff 展示历史、直接访问 prompt tools 并采用同行输入布局；DSH 0.2.2-alpha.2 的输入键盘逻辑没有手机 Enter 分支。这些匹配点经严格校验，未来版本需重新核查。

消息布局核查：DS Bot 0.2.6 的泡泡模式限制回复宽度并为右侧工具栏预留 82px；原生平铺会去掉气泡背景。因此用 CSS 调整气泡和按钮排版，保留布局偏好。`MessageTools` 的复制、下载原本仅在「更多」菜单中，补丁将其改为直接按钮，复用原有处理器并移除菜单与对应定位分支。

验证：20 项 DS Bot、2 项共用输入框和 13 项插件安装测试通过。25228 Chief 的 20 条回复在 1600px 和 390px 视口中右边界误差为 0px，按钮位于气泡下方 4px，无横向溢出或浏览器错误；复制反馈、下载内容和表情菜单均通过验证。补丁应用保持幂等，未发送消息或重启服务。

宽度调整核查：本机 DSH 0.2.2-alpha.2 的 `dsh-client-ui-conversation/lib/client.js` 已包含 `ConversationWidthControls`、`WidthHandle`、指针捕获、宽度限制和 `dsh.conversation.contentWidth` 持久化。DS Bot 0.2.6 的 `client.js` 隐藏 `_widthHandle`，固定 `--dsh-chat-content-width` 为 960px，并将宿主宽度变量注册为不继承。补丁仅在桌面恢复原生拖动条、让 body 显式继承宿主宽度变量并使用宿主宽度公式，不增加另一套拖动逻辑。

2026-11-03 宽度补丁验证：25228 的 Chief 会话在 1600px 浏览器中左拖 80px，正文从约 845px 增至 1005px，输入框从约 877px 增至 1037px；刷新后保持宽度。900px 窄屏隐藏拖动条；390px 触屏隐藏拖动条且无页面横向溢出。浏览器无运行错误，20 项 DS Bot 回归及 2 项共用输入框测试通过。只刷新独立测试浏览器，未重启服务、未发送消息。

2026-11-03 经授权重启 25228 后，普通 DSH 与 Chief 均完成线上手机换行和 PC 快捷键验证，未发送模型测试消息；25028/25128 的进程未变化。合并补丁的回归覆盖独立单文件执行、四个目标全量应用、缺失输入框补丁检测、幂等性、未知版本拒绝、失败不写入及安装入口调用。历史排查记录见 [迁移文档](../MIGRATION.md)。

## dsh-web-mobile 顶栏按钮

`python3 -B ds-harness/patches/dsh_mobile_apply.py`（仓库根目录运行，`--check` 只验证）修复 3.2.1 的手机顶栏按钮裁剪问题，插件安装入口自动执行。复用统一补丁的原子写入与备份机制，未知版本或锚点不符时拒绝应用。

本机 3.2.1 发布源码把 `MobileNavToggle` 注入 `conversation.session.header.actions`，同时给其祖先 `headerActions` / `titleCluster` 设置滚动裁剪；侧边栏、文件按钮绝对定位到顶栏两端，落在裁剪区外而不可见，标题仍留有 32px。DSH 0.2.2-alpha.2 已有独立的 `conversation.header.leading` 槽位，因此补丁复用该槽位，只在手机且槽内存在本插件按钮时解除其隐藏。保留标题滚动、原有按钮事件及桌面隐藏条件；不修改宿主布局、不重启服务。

2026-11-03 验证：25228 实际资源刷新后，360/390/820px 触屏下侧边栏按钮可见且可命中，点击成功打开抽屉；900/1600px 鼠标界面按钮隐藏、leading 槽宽度为 0，均无页面横向溢出。52 项安装相关测试通过，重复 `--check` 通过。未重启服务。

手机页签间距：DSH 0.2.2-alpha.2 的 `.wSkVaW_tab` 通过 `--dsh-tab-hit-inline:10px` 同时设置横向内边距和负外边距；mobile 3.2.1 清零了内边距但保留负外边距，让 16px 的页签间距变成文字重叠 4px。移动补丁在手机页签规则中把该变量归零，同时修正间距及选中下划线宽度，桌面仍使用宿主原值。25228 的 360/390/820px 触屏验证文字间距均为 16px、首项不再被裁切，Chat / Trajectory 切换正常；无服务重启。

手机「更多视图」同行：宿主 `.wSkVaW_tabs` 允许换行，mobile 3.2.1 又将内部 tablist 设为 `width:100%`，导致兄弟节点「更多」独占下一行。补丁仅在移动端使外层不换行、tablist 按内容占宽且允许收缩，并清除页签条和按钮各自的负上边距，统一垂直居中。25228 在 360/390/820px 下验证页签与更多间距 16px、按钮中心高度一致，无横向溢出；页签切换和更多菜单打开均通过，补丁幂等检查通过，未重启服务。

页签自适应验证：DSH 0.2.2-alpha.2 原实现按 `(row.clientWidth - 48) / 120` 估算数量。补丁在同一 CSS 环境中测量候选页签，计入文字截断、内外边距、页签间距及更多按钮占用；宽度、候选视图、固定偏好和字体加载变化时重新计算。25228 的 360/390/820px 触屏均直接显示 Chat、Trajectory、Git、Statistics；240px 时只将 Statistics 收进更多，拉宽自动恢复，页签无横向溢出。20 项 DS Bot 回归、JS 语法及补丁幂等检查通过，未重启服务。

左侧边栏移除日志下载：3.2.1 的 `createDrawerSessionLogTask` 原本向 logo 行注入当前会话下载按钮。移动补丁不再注册该任务，因此不生成按钮或占位包装；宿主日志导出服务保持不变。更新后刷新页面生效，无需重启。
