# DSH 本地补丁

当前核验组合为 **DSH 0.2.2-rc.1、ds-bot 0.2.7、dsh-web-mobile 3.3.0、xterm/headless 6.0.0、addon-serialize 0.14.0**。三个入口共用原子写入、备份与回滚函数，未知版本、混合宿主版本或不完整旧补丁会停止。

| 入口 | 当前版本的处理 |
| --- | --- |
| `ds_bot_apply.py` | 保持 Bot 0.2.7 原生代码；撤销升级时遗留在宿主中的旧历史插槽和手机 Enter 注入。 |
| `dsh_mobile_apply.py` | 保持 mobile 3.3.0 文件不变；撤销旧宿主 Enter 注入，保留仅在 mobile 布局生效的页签实际宽度测量。 |
| `dsh_terminal_apply.py` | 继续安装前后端配套的重连、剪贴板、键盘协商、查询应答、搜索与链接增强。 |

历史组合 **Bot 0.2.6 + DSH alpha.2**、**mobile 3.2.1 + DSH alpha.2** 仍走独立旧版路径；不会把旧版 UI 补丁套到新包上。终端也支持原有 alpha.2，但前端与控制器必须同版。

## 新版上游核查与迁移

2026-11-06 对照 npm 官方发布的四个 DSH rc.1 组件包（按注册表 SHA-512 验证），以及 mobile 3.3.0 提交 [`522db94`](https://github.com/mexiaosqwq/dsh-web-mobile/tree/522db94f552d89934f814853ad10c96f31eba6da)：

- mobile 已修复顶栏裁切、文件按钮消失、页签叠字和手机回车换行。旧版顶栏插槽移动、CSS 和 Enter 注入不再用于新版；图标、提示文字和操作栏布局沿用新版上游，不再覆盖为旧的本地偏好。
- 上游 [`composer-enter-newline.ts`](https://github.com/mexiaosqwq/dsh-web-mobile/blob/522db94f552d89934f814853ad10c96f31eba6da/src/client/effects/composer-enter-newline.ts) 会将 Ctrl/Cmd+Enter、斜杠及 @ 候选菜单交回宿主。旧宿主 Enter 注入会抢在仲裁前换行，已复现冲突；迁移会精确撤销该注入。手机换行范围跟随上游的 `<1024px` 粗指针布局。
- Bot 0.2.7 不使用旧 `BotNativeHistory` 所需的宿主插槽。迁移只撤销已识别的宿主历史改动，不把 0.2.6 的历史、提示词或外观变换安装到 0.2.7。
- DSH rc.1 仍按 `(row.clientWidth - 48) / 120` 估算页签数；mobile 3.3.0 的修复是样式调整，没有替代宿主的实际宽度测量。因此保留该宿主增强，桌面及未启用 mobile 时回退原逻辑。
- rc.1 原包尚未接入本地终端的重绘、OSC 52、键盘协商、宿主查询应答及搜索/链接辅助逻辑；保留原有宿主控制、快照、流控和主题路径，在版本及匹配点检查后追加增强。

迁移接受原版和完整旧补丁，重复执行不写入；遇到修改过或残缺的旧辅助代码会拒绝，不能通过放宽版本检查强行覆盖。回归覆盖迁移幂等性、未知版本不写入、快捷键/候选菜单恢复及终端真实 headless 协议。源码修改和隔离验证不会自动更新运行实例。

## 安装与检查

主安装器 `dsh_install.sh` 调用插件安装器 `dsh_plugins_install.sh`；插件安装成功后，后者依次执行 DS Bot 迁移、mobile 兼容处理和 terminal 补丁。首次安装、`--upgrade`、插件已安装而跳过下载时都会执行。mobile 已声明的 `github:` 来源（包括提交固定值）会保留，Codex 插件与 DSH 同版。补丁失败会使安装返回非零退出码；`--dry-run` 只打印计划，不修改文件。

```sh
bash ds-harness/dsh_install.sh
# 单独补装插件并应用全部补丁
bash ds-harness/dsh_plugins_install.sh
# 手动应用／只检查全部补丁
python3 ds-harness/srcs/patches/ds_bot_apply.py
python3 ds-harness/srcs/patches/ds_bot_apply.py --check
python3 ds-harness/srcs/patches/dsh_mobile_apply.py
python3 ds-harness/srcs/patches/dsh_mobile_apply.py --check
python3 ds-harness/srcs/patches/dsh_terminal_apply.py
python3 ds-harness/srcs/patches/dsh_terminal_apply.py --check
# 回归测试
python3 -B -m unittest discover -s ds-harness/srcs -p 'test_ds_bot*.py'
python3 -B -m unittest discover -s ds-harness/srcs -p 'test_dsh_composer_enter.py'
python3 -B -m unittest discover -s ds-harness/srcs -p 'test_dsh_plugins_install.py'
python3 -B -m unittest discover -s ds-harness/srcs -p 'test_dsh_mobile_apply.py'
python3 -B -m unittest discover -s ds-harness/srcs -p 'test_dsh_terminal_apply.py'
```

默认定位本服务的 web profile 与 PATH 中的 DSH 安装；测试或明确的自定义安装可传 `--bot-dir` 和 `--host-dir`（DSH 的 `node_modules/@deepseek-ai` 目录）。升级到其他版本前必须重新核对上游实现；安装器仍按现有策略选择依赖版本，不会为了通过补丁检查静默降级。

## 历史组合的修复（Bot 0.2.6 / DSH alpha.2）

- **历史记录**：通过原生 ChatFlow 展示归档分段，空会话有历史时进入正常聊天视图；保留分页和插槽所有权，不恢复旧 Hero 容器。
- **提示词接口**：当前 DSH 在 prompt waterfall 结束后附加工具，补丁不再在该钩子访问 tools；保留 sections 过滤、tools.restrict 与执行 guard。已打补丁的当前 0.2.6 安装会转换为同一实现，不支持旧宿主接口。
- **布局**：修复移动侧栏网格、抽屉占位、窄侧栏名称、群聊头像和操作按钮；手机长回复使用可用宽度。手机与 PC 输入框均为上下两行，工具按钮间距 8px。页签按实际宽度折叠由 `dsh_mobile_apply.py` 负责，保留宿主固定偏好和更多菜单。
- **桌面聊天宽度**：恢复 DSH 原生聊天区左右拖动条，正文和输入框同步调整，保留宿主输入框多出的 32px 内边距空间，沿用宿主的本地宽度记忆（与普通 DSH 聊天共享）。仅在视口至少 1024px、精确指针且支持悬停时启用；触屏与窄屏维持原有布局。
- **共用输入框**：普通 DSH 和 ds-bot 手机 Enter 只换行，点击按钮发送；PC 保留 Enter 发送、Shift+Enter 换行。复用宿主移动设备检测，保留输入法组合保护和 `beforeinput` 换行处理。

- **消息与操作栏**：保留回复气泡和左对齐文字，回复铺满正文宽度，与发送气泡共用右边界。表情、回复、复制、下载在回复下方独占一行，桌面端悬停显示，触屏端（无悬停或粗指针）常驻显示，无需先触摸消息。

## 校验与生效

每个入口先核验其全部包版本和目标文件，再统一写入。每个目标在同目录暂存后原子替换；原件与清单备份到 `ds-harness/log/patch-backups/`，该入口后续写入失败会回滚已完成的替换。三个入口依次执行，不构成跨入口事务。进程被强制终止或断电后，先检查备份及 `--check` 结果。

安装器不启停服务。运行实例可能缓存前端 bundle 或服务端模块，安装成功不代表线上已更新；应检查实际 `/plugins/` 响应。需要重载时先检查活跃任务、保存恢复信息，再安排维护，不能默认重启。

核查依据：2026-11-02/03 的本机发布包中，DS Bot 0.2.6 仍依赖 handoff 展示历史、直接访问 prompt tools 并采用同行输入布局；DSH 0.2.2-alpha.2 的输入键盘逻辑没有手机 Enter 分支。这些匹配点经严格校验，未来版本需重新核查。

消息布局核查：DS Bot 0.2.6 的泡泡模式限制回复宽度并为右侧工具栏预留 82px；原生平铺会去掉气泡背景。因此用 CSS 调整气泡和按钮排版，保留布局偏好。`MessageTools` 的复制、下载原本仅在「更多」菜单中，补丁将其改为直接按钮，复用原有处理器并移除菜单与对应定位分支。

验证：20 项 DS Bot、2 项共用输入框和 13 项插件安装测试通过。25228 Chief 的 20 条回复在 1600px 和 390px 视口中右边界误差为 0px，按钮位于气泡下方 4px，无横向溢出或浏览器错误；复制反馈、下载内容和表情菜单均通过验证。补丁应用保持幂等，未发送消息或重启服务。

宽度调整核查：本机 DSH 0.2.2-alpha.2 的 `dsh-client-ui-conversation/lib/client.js` 已包含 `ConversationWidthControls`、`WidthHandle`、指针捕获、宽度限制和 `dsh.conversation.contentWidth` 持久化。DS Bot 0.2.6 的 `client.js` 隐藏 `_widthHandle`，固定 `--dsh-chat-content-width` 为 960px，并将宿主宽度变量注册为不继承。补丁仅在桌面恢复原生拖动条、让 body 显式继承宿主宽度变量并使用宿主宽度公式，不增加另一套拖动逻辑。

2026-11-03 宽度补丁验证：25228 的 Chief 会话在 1600px 浏览器中左拖 80px，正文从约 845px 增至 1005px，输入框从约 877px 增至 1037px；刷新后保持宽度。900px 窄屏隐藏拖动条；390px 触屏隐藏拖动条且无页面横向溢出。浏览器无运行错误，20 项 DS Bot 回归及 2 项共用输入框测试通过。只刷新独立测试浏览器，未重启服务、未发送消息。

2026-11-03 经授权重启 25228 后，普通 DSH 与 Chief 均完成线上手机换行和 PC 快捷键验证，未发送模型测试消息；25028/25128 的进程未变化。合并补丁的回归覆盖独立单文件执行、四个目标全量应用、缺失输入框补丁检测、幂等性、未知版本拒绝、失败不写入及安装入口调用。历史排查记录见 [迁移文档](../../MIGRATION.md)。

## 历史 mobile 3.2.1 顶栏按钮

`python3 -B ds-harness/srcs/patches/dsh_mobile_apply.py`（仓库根目录运行，`--check` 只验证）统一修复 3.2.1 的手机顶栏布局及 DSH 0.2.2-alpha.2 的页签宽度折叠，插件安装入口自动执行。先校验插件和宿主两个目标，再共用原子写入与备份机制发布；任一目标版本或锚点不符都不写入。`--check` 同时检查两个目标，`--mobile-dir` / `--host-dir` 可指定隔离安装目录。

本机 3.2.1 发布源码把 `MobileNavToggle` 注入 `conversation.session.header.actions`，同时给其祖先 `headerActions` / `titleCluster` 设置滚动裁剪；侧边栏、文件按钮绝对定位到顶栏两端，落在裁剪区外而不可见，标题仍留有 32px。DSH 0.2.2-alpha.2 已有独立的 `conversation.header.leading` 槽位，因此补丁复用该槽位，只在手机且槽内存在本插件按钮时解除其隐藏。保留标题滚动、原有按钮事件及桌面隐藏条件；不修改宿主布局、不重启服务。

2026-11-03 验证：25228 实际资源刷新后，360/390/820px 触屏下侧边栏按钮可见且可命中，点击成功打开抽屉；900/1600px 鼠标界面按钮隐藏、leading 槽宽度为 0，均无页面横向溢出。52 项安装相关测试通过，重复 `--check` 通过。未重启服务。

手机页签间距：DSH 0.2.2-alpha.2 的 `.wSkVaW_tab` 通过 `--dsh-tab-hit-inline:10px` 同时设置横向内边距和负外边距；mobile 3.2.1 清零了内边距但保留负外边距，让 16px 的页签间距变成文字重叠 4px。移动补丁在手机页签规则中把该变量归零，同时修正间距及选中下划线宽度，桌面仍使用宿主原值。25228 的 360/390/820px 触屏验证文字间距均为 16px、首项不再被裁切，Chat / Trajectory 切换正常；无服务重启。

手机「更多视图」同行：宿主 `.wSkVaW_tabs` 允许换行，mobile 3.2.1 又将内部 tablist 设为 `width:100%`，导致兄弟节点「更多」独占下一行。补丁仅在移动端使外层不换行、tablist 按内容占宽且允许收缩，并清除页签条和按钮各自的负上边距，统一垂直居中。25228 在 360/390/820px 下验证页签与更多间距 16px、按钮中心高度一致，无横向溢出；页签切换和更多菜单打开均通过，补丁幂等检查通过，未重启服务。

页签自适应验证：DSH 0.2.2-alpha.2 原实现按 `(row.clientWidth - 48) / 120` 估算数量。补丁在同一 CSS 环境中测量候选页签，计入文字截断、内外边距、页签间距及更多按钮占用；宽度、候选视图、固定偏好和字体加载变化时重新计算。25228 的 360/390/820px 触屏均直接显示 Chat、Trajectory、Git、Statistics；240px 时只将 Statistics 收进更多，拉宽自动恢复，页签无横向溢出。20 项 DS Bot 回归、JS 语法及补丁幂等检查通过，未重启服务。

左侧边栏保留日志下载：恢复 3.2.1 的 `createDrawerSessionLogTask` 注册；补丁会迁移已移除该入口的本地安装，保留宿主日志导出服务。顶栏右侧按钮复用宿主 `IconPanelLeft` 并水平镜像，与宿主右侧栏入口一致；提示改为「打开右侧栏 / Open right sidebar」，点击逻辑保持原样。更新后刷新页面生效，无需重启。

顶栏动作横向滑动：3.2.1 将 headerActions 固定为不可收缩，同时隐藏团队文字与后台任务计数。补丁让动作区占用标题之外的剩余宽度并可横向滚动，各控件按自然宽度显示，恢复团队和任务文字，标题与左右侧栏按钮保持固定。复用插件现有手势对横向滚动容器的让位规则及宿主弹层。25228 的真实触屏事件验证滚动 27px、未打开抽屉，Agent team 弹层正常显示；按当前 jobs DOM 构造的浏览器测试节点在 360/390/820px 下文字不隐藏、内容可达、无页面横向溢出。未创建后台任务或重启服务。

移动补丁维护：顶栏样式共用选择器前缀与规则生成函数，保持输出 CSS 字节和选择器权重不变；保留已发布补丁的迁移，移除未发布的临时图标位置迁移。已核验原始 3.2.1、已发布补丁和当前安装三种输入均生成相同结果，重复应用不写入，未知锚点仍拒绝。

页签宽度补丁仅在运行时检测到 mobile 的 frame 标记且匹配 `(max-width:1023px) and (pointer:coarse)` 时使用实际宽度测量；无插件标记、桌面或非触屏布局直接走宿主原有 120px 估算规则。监听插件标记和媒体查询变化，启停插件或切换布局时重新计算。归属与运行时范围回归覆盖原版、旧补丁迁移、缺少宿主修复检测、宿主校验失败不写入，以及三种非移动组合的原生回退。


## 终端与 Codex CLI 重连

`dsh_terminal_apply.py` 在安装和插件更新后自动执行，也可单独执行；`--host-dir` 可指向隔离的 DSH `node_modules/@deepseek-ai`。它先核验终端前端、控制器和 xterm 版本及全部锚点，再一起发布三个文件。原件和清单保存在 `ds-harness/log/patch-backups/`；`--check` 检查所有目标。宿主服务已经加载的模块不会因写入文件而更新，需在确认活跃会话及中断影响后安排维护窗口，按服务管理约定先停再启动并检查就绪；浏览器需要刷新。补丁本身不会重启服务。

上游 DSH 0.2.2-alpha.2 已使用 xterm headless 和 serialize addon 为重连提供有界屏幕快照，并在浏览器使用 xterm 6 和 FitAddon；因此沿用其快照、流控和尺寸管理，不复制 Pi Web 的历史缓冲实现。核查本机 xterm serialize 0.14.0，快照保留备用屏幕及多数输入模式，但遗漏鼠标 SGR/像素编码、光标隐藏状态和同步输出模式；补丁补齐这三项。前两项只能从 headless 6.0.0 的内部状态读取，因此严格限定版本，升级时须重新核查上游实现。

参考 Pi Web 的终端重绘处理，客户端等快照解析完成后临时改变一列并于 100ms 后恢复，让增量更新的 TUI 重绘。尺寸变化遵循宿主上下限；待宿主确认期间强制发送恢复尺寸，避免旧状态误判为无需恢复。不可见、只读和断连时等待可控制的视图；切换或销毁时恢复临时尺寸，屏幕变化期间采用最新布局。

选区复制：上游终端未注册 OSC 52 处理器。补丁参考 Pi Web，接收实时输出中的 UTF-8 复制请求并调用浏览器剪贴板；只对可见、拥有控制权的当前视图生效。复制成功显示 `Copied`，自动写入被拒绝时显示手动 `Copy` 按钮；忽略读取请求、无效内容和历史快照，卸载时清理处理器和提示。

Paseo 终端增强：参考 [Paseo 运行时](https://github.com/getpaseo/paseo/blob/bfbd4d5175e35d5389457cf62cda69dcdd699771/packages/app/src/terminal/runtime/terminal-emulator-runtime.ts)，增加页面重新可见、窗口聚焦、窗口及 `visualViewport` 尺寸变化、字体就绪与加载完成后的重算和下一帧刷新。沿用快照解析屏障，仅由可见且拥有控制权的连接调整 PTY；恢复页面不抢焦点，不改变控制权，销毁时移除监听和待执行回调。

组合键：前后端共用 xterm 解析器跟踪 Kitty 键盘协商，支持分段序列、设置/叠加/清除、最多 32 层的模式栈，以及普通/备用屏幕的独立状态；快照恢复两套栈。当前实现 CSI-u 按键消歧（flag 1），其他增强位不报告为已启用，不支持 Win32 输入模式。程序协商后可区分 `Shift+Enter`、`Ctrl+Enter`、`Alt+Enter` 及其他控制组合键，退出模式后恢复 xterm 原生输入。普通文本、IME、AltGr 和浏览器 Command 快捷键沿用原输入路径；保留粘贴，有原生选区时 `Ctrl+C` 仅复制，不额外发送中断。协议依据：[Kitty keyboard protocol](https://sw.kovidgoyal.net/kitty/keyboard-protocol/)。

查询应答：宿主收集 headless xterm 自带的设备属性、状态、光标位置、模式和 DCS 状态查询响应，并在输出解析后直接写回 PTY；Kitty 状态查询也由宿主应答。无需浏览器连接，浏览器同时吞掉这些查询，避免多个视图重复回包；应答有 64 KiB 上限，进程退出或关闭后不再写入。OSC 颜色查询继续由现有浏览器主题实现处理，不使用固定颜色替代 DSH 实际配色。

搜索和链接：终端右上角 `Find` 或 `Ctrl+Shift+F` / `Cmd+F` 打开搜索，支持上下匹配、`Enter` / `Shift+Enter` 和 `Escape` 关闭；只读视图也可搜索。HTTP(S) 文本链接通过 `Ctrl` / `Cmd` + 点击打开。复用官方 `@xterm/addon-search@0.16.0` 和 `@xterm/addon-web-links@0.12.0`，文件、MIT 许可和校验摘要保存在 [vendor](vendor/README.md)，安装无需联网。

上游复核：对照 DSH 提交 `8bd073392eef6f54e921a093b95076248eb08cbb` 的[终端前端](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/client/ui-sidebar-terminal/src/client/terminal.tsx)和[宿主控制器](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/api/terminal-controller/src/terminal.ts)，上述生命周期监听、键盘协商、宿主应答转发和搜索/链接插件尚未接入。继续复用上游已有的快照、输入控制、流控和主题实现。补丁可从原版或上一版终端补丁升级；未知或不完整的辅助代码拒绝覆盖。前后端需要配套部署，应在安排好的服务维护窗口应用并重启后刷新页面，避免新版前端抑制查询而旧宿主尚未应答。

验证：此前真实 Codex CLI 0.166.0 在隔离的临时配置及 PTY 中显示登录界面，快照恢复并执行重绘后，与持续连接的 xterm/headless 屏幕逐行一致。另用指向本地不可用地址的测试 provider 启动主界面，确认它启用备用屏幕和 SGR 鼠标模式，发送鼠标拖选后实际产生 OSC 52；没有发送模型消息。回归覆盖鼠标、剪贴板、重绘时序和补丁幂等性，并增加真实 headless 查询、多视图去重、后台控制器独立应答、键盘栈重连、页面/字体事件、旧补丁迁移及不完整补丁拒绝。

新增 Chromium 验证加载的是隔离副本中补丁后的完整 DSH 前端 bundle，通过轻量 hook harness 挂载真实终端组件，覆盖搜索导航、修饰键链接点击、协商前后的组合键、选区复制、粘贴、中文输入和只读视图；通过环境变量 `DSH_TEST_PLAYWRIGHT` 指定已安装的 Playwright 模块启用，可选 `DSH_TEST_CHROMIUM` 指定浏览器。默认测试不依赖浏览器。未操作在线服务或已登录 Codex 会话，尚未覆盖真实 React 调度及服务网络的端到端交互。

### Mobile 3.3.0 补丁复核（2026-11-06）

核对上游提交 `522db94f552d89934f814853ad10c96f31eba6da`，当前安装的 `lib/client.js` 与上游文件逐字节一致。

- 顶栏开关被裁、文件按钮消失：上游 `src/client/styles/layout.css.ts` 已调整 titleCluster 的 overflow，沿用上游方案，无需旧版移槽补丁。
- 页签叠字、文字被裁：上游已清零 `--dsh-tab-hit-inline`，恢复自动行高并调整外边距；无需重复注入旧 CSS。上游对齐方式与旧版强制居中偏好不完全相同。
- 手机 Enter 换行：上游 `src/client/effects/composer-enter-newline.ts` 已实现，并将修饰键、候选菜单及输入法交回宿主；应撤销旧宿主 Enter 注入。
- 动作区横向滚动：上游已有 overflow 处理，但布局收缩策略、标签显示与旧本地偏好不同，不视为逐项等价；3.3.0 沿用上游布局。
- 右侧栏图标与文案替换属于本地偏好，上游仍使用文件夹图标和 Files 文案；新版不再覆盖。
- 根据页签实际宽度计算可见数量：mobile 上游未实现；当前 DSH rc.1 原始逻辑仍按固定 120px 估算，保留宿主侧自适应补丁。

3.3.0 分支保持 mobile 文件原样，仅迁移宿主旧 Enter 注入并维护页签自适应。3.2.1 的旧 UI 补丁已隔离到 `dsh_mobile_legacy.py`，仅在确认 3.2.1 / alpha.2 版本组合后加载；新版不加载这些变换。
