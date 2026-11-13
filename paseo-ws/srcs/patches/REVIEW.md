# Paseo v0.16.0-beta.2 补丁复核

本次基准为官方 `v0.16.0-beta.2`，Git tag 解引用提交 `23bae61535542a45ade7196a7b3c152705f16de3`。CLI、server、client、protocol 使用同一版本。npm server 包未提供 `gitHead`，因此单独核对官方 tag，并将包内原始 Web entry 固定在 `patch-web-ui.baseline.json`；不凭缺失的 `gitHead` 推断源码版本。

官方来源：[发布说明](https://github.com/getpaseo/paseo/releases/tag/v0.16.0-beta.2)、[beta.1 → beta.2 差异](https://github.com/getpaseo/paseo/compare/v0.16.0-beta.1...v0.16.0-beta.2)。

| 本地补丁 | 上游核查及处理 |
| --- | --- |
| TLS 连接等待预算 | `runtime/host-runtime.ts` 的初次连接探测及普通连接预算未覆盖本地 TLS 场景的 20 秒预算；保留现有三处限定替换，不改变普通非 TLS 连接。 |
| 聊天公式 | 核对官方 beta.2 原始 bundle：`MarkdownRenderer` 已接入 md4c、`loadKaTeX` 与 `KaTeXRenderer`（MathML），但 `latexMath` 关闭；真实 WASM 仅识别美元符号分隔符。保留 KaTeX 和普通 Markdown 解析，启用原标志及主题色。在 `parseMarkdownSync` 内接入锁定版本的 micromark/mdast 语法识别及反斜杠分隔符扩展，公式正文用不冲突的临时文本槽隔离，再还原成上游数学 AST 节点；不再改写消息或重用美元符号承载公式。显式分隔符内的内容直接交给 KaTeX，去掉命令白名单和代数猜测；未知命令按上游 `throwOnError: false` 显示。代码、链接、嵌套容器、相邻公式、已有数学区域、流式闭合及显示公式节点均使用真实 WASM 回归；测试同时确认 KaTeX 模块逐字不变。 |
| 宽屏触摸消息操作 | `components/message.tsx` 的 `showActions` 仍仅判断紧凑布局、原生平台和悬停。iPad 宽屏 Web 未覆盖；复用现有操作行及复制逻辑，增加 `(hover: none), (pointer: coarse)` 媒体查询和输入能力变化订阅。待发送、无正文及桌面鼠标行为保持上游逻辑。 |
| 项目菜单新建工作区 | 官方 beta.2 entry 的项目菜单 `Qe` 不含新建工作区，而项目行 `rr` 已有路由回调、`Ve` 已接收按钮回调。菜单复用这两个现有回调，覆盖 context 与 dropdown 两种菜单；缺少 worktree 目标时不显示，不改变悬停和长按行为。 |
| 触摸信息卡片 | `components/ui/hover-card.tsx` 仍直接以 `openNow` 处理 pointer enter，focus enter 不以 `:focus-visible` 阻止普通点击产生的焦点。保留鼠标/键盘过滤及 pointer dismissal，卡片内部鼠标链接与按钮操作继续可用。上游的单卡片协调不替代这些触摸规则。 |
| 整块文件/更改侧栏最大化 | 官方 beta.2 `ExplorerSidebarDock` 已有标签栏右端 `headerAction`（收起），但未提供侧栏最大化；`ExplorerFrame` 的几何仅负责宽度与拖动。复用 `WorkspaceDesktopTabsRow` 中原有最大化/恢复 ToolbarButton，在该插槽与原收起控件并列；仅在 dock 并排布局显示该按钮，overlay 模式保持原收起控件且清除最大化状态。状态由侧栏 Frame 持有，订阅上游 `useRetainedPanelActive` 并在 layout effect 中清除失活 workspace 的最大化，覆盖保留页面的焦点属性延迟更新；渲染时扩展右侧栏到整个中间聊天区及原侧栏区域，保留左侧导航；最大化期间直接替换 frameStyle，避免原像素宽度内联样式压过百分比 CSS 类，恢复不改已保存宽度。保留 SplitContainer 内部逻辑、终端渲染及收起动作；仅包装主内容出口，在最大化时设置 inert 并通过上游 RetainedPanelActivity 与 isWorkspaceFocused 暂停被覆盖的聊天区交互，临时状态按 workspace 隔离、恢复/离开时清除。撤回仅针对终端的特殊处理。 |
| 触屏终端虚拟键 | [beta.2 `terminal-virtual-keyboard.ts`](https://github.com/getpaseo/paseo/blob/v0.16.0-beta.2/packages/app/src/terminal/runtime/terminal-virtual-keyboard.ts#L92) 仅判断 `isNative || isCompact`。TerminalPane 复用上游响应式指针能力 hook 与 `hasTouchScreen`，补充所有触屏设备，包含宽屏和平板连接鼠标的情况；Metro 模块 ID 从当前官方资源解析，不固定编号。同时复用原有 useKeyboardShiftStyle 和键盘变化回调，以相同条件启用 padding 与 keyboardInset，避免宽屏触屏只显示按键而缺少避让。原有按键布局、发送及剪贴板策略保持原样。 |
| Web 终端右键菜单 | `components/terminal-emulator.tsx` 仍先 `preventDefault()`，自定义菜单依赖 Electron。保留仅存在 Electron 菜单接口时拦截的补丁。beta.2 对共用 `context-menu.tsx` 的嵌套按钮调整不覆盖此缺口。 |
| 移动侧栏开启边缘 | 保留左侧 32px 的浏览器手势仲裁；上游仍控制布局、动画和状态。关闭侧栏的原生手势及聊天正文不修改。 |
| 首次工作区 Git 刷新 | `workspace-git-service.ts` 的初次刷新仍 `includeForge: true`。保留先本地、后 Forge 的异步刷新，调用上游 `refreshWorkspaceTarget`，保留活动观察/成功快照 guard，不重复刷新本地 worktree，后台续刷绕过首次刷新节流。 |
| DSH catalog 屏障 | 第三方 `paseo-dsh 0.2.17` 的 [固定上游实现](https://github.com/liuxing7954/paseo-dsh/blob/c642c604aeb5b409a6237ca3ef54fdb82801677d/dsh-bridge/lib/index.js#L82) 仍仅让 initialize 等待 loader。保留 catalog 等待和插件范围内的 DSH home 默认值；不因 Paseo 版本变化修改第三方插件版本或其他插件环境。 |

上游实现链接均相对于 [beta.2 app 源码](https://github.com/getpaseo/paseo/tree/23bae61535542a45ade7196a7b3c152705f16de3/packages/app/src) 和 [首次 Git 刷新实现](https://github.com/getpaseo/paseo/blob/23bae61535542a45ade7196a7b3c152705f16de3/packages/server/src/server/workspace-git-service.ts)。本次没有以版本号替换代替逐项核查，也没有发现可整项删除的现行补丁。

此前退役的终端剪贴板按钮和独立 diff 连接/压缩继续保持退役；宽屏触摸消息操作因 iPad 实际无法悬停而补回输入能力判断。beta.2 的官方 diff 流、用户长消息首帧折叠、目录建议和侧栏手势模块保留原样。

补丁从包内官方资源重建，生成新哈希、Brotli 和 Gzip，不改写原始 entry。HTML entry、模块和替换锚点必须唯一；未知预算、重复 bootstrap、新旧混装和重复 entry 均应在发布前失败。测试验证失败时 HTML 和已有发布资源不变。

验证使用真实 beta.2 server 包；设置 `PASEO_RUNTIME_PREFIX` 后，真实模块测试缺包或版本不符必须失败，不能以 skip 掩盖。Git 回归执行实际首次调度、刷新入口、队列和快照流程，仅模拟 shell/Forge 外部边界；DSH 回归只读核验实际 bridge 与插件内嵌资源。

运行部署需独立安装到候选目录，在维护窗口先停止再切换 CLI 包并启动；保留旧包、官方原始资源及停止后的 Paseo home 备份。当前会话本身由 Paseo 承载，维护进程必须独立，并保存执行进度、结果与恢复方法。`data/`、`runtime/` 和日志不提交 Git。

恢复 Web 添加项目的 Browse：beta.2 AddProjectFlow 的 canBrowse 和 pickDirectory 仍仅支持 Electron 本机，目录建议不能代替逐层浏览。恢复服务器目录窗口，复用所选主机 listDirectory/createFileEntry API，保留官方路径搜索及 Electron 本机选择器。

目录浏览窗口通过上游 Unistyles `:root` 的 `--colors-*` 变量使用当前应用主题，覆盖操作系统偏好回退；主题切换无需重新打开窗口。
