# DSH 本地补丁

目录按归属分组：`service/` 保存 DSH 主服务的终端、文件资源及会话信息补丁；`plugins/ds_bot/`、`plugins/mobile/` 和 `plugins/git_panel/` 保存对应插件的兼容处理。`common.py` 是共享执行工具。测试及夹具位于服务根目录的 `tests/`，与 `srcs/` 同级。


`dsh_git_panel_apply.py` 移除 `@xbzbing/dsh-git-panel@1.11.2 / 1.13.1` 在 `conversation.input.left` 注册的 `git-panel-pill`，保留 Git 页签与侧栏。安装器自动应用；`--check` 验证，`--git-panel-dir` 可指定隔离安装目录。插件未安装或按钮不存在时跳过。复用原子写入与备份机制，未知版本或存在按钮但注册锚点不匹配时拒绝修改。上游已有 `showInputPill` 显示开关；此处按本地偏好直接省略按钮注册，因此插件配置不会将它重新显示。

会话信息 info 图标通过 `conversation.input.right` 注册，ID 为 `dsh-session-info`、`order: -100`，使用宿主 `chat` locale 和会话投影。`dsh_composer_metadata_apply.py` 会撤销旧的 `trailing` 直接挂载，再注册插槽，保留展开状态与元信息的 React Context。mobile 的额外文件按钮同样先检查是否存在，不存在时保持插件原样；存在但注册代码未知时拒绝修改。

当前核验组合为 **DSH 0.2.2-rc.1、ds-bot 0.3.1、dsh-web-mobile 3.3.0 / 3.3.1、xterm/headless 6.0.0、addon-serialize 0.14.0**。六个独立入口通过 `common.py` 共用补丁校验、宿主定位、原子写入、备份与回滚函数；`apply.py` 统一编排全部补丁，未知版本、混合宿主版本或不完整旧补丁会停止。

| 入口 | 当前版本的处理 |
| --- | --- |
| `plugins/ds_bot/ds_bot_apply.py` | 适配 Bot 0.3.1 的本地输入框、消息操作栏与桌面宽度布局；移除旧手机工具栏覆盖，沿用上游历史、提示词和触屏命中区；撤销宿主旧历史及 Enter 注入。 |
| `plugins/mobile/dsh_mobile_apply.py` | 移除 mobile 3.3.0 / 3.3.1 额外注册的 `ComposerFileButton`；撤销旧宿主 Enter 注入，保留仅在 mobile 布局生效的页签实际宽度测量。 |
| `service/dsh_composer_metadata_apply.py` | 普通 DSH 输入框工具栏内增加会话信息 info 按钮，按需展开原生会话元信息；DS Bot 队列保持可见。 |
| `service/dsh_file_resources_apply.py` | 修复旧手机浏览器解析自定义资源地址时无法匹配文件资源提供器的问题。 |
| `service/dsh_terminal_apply.py` | 继续安装前后端配套的重连、剪贴板、键盘协商、查询应答、搜索与链接增强。 |

历史组合 **Bot 0.2.7 + DSH rc.1**、**Bot 0.2.6 + DSH alpha.2**、**mobile 3.2.1 + DSH alpha.2** 仍走独立旧版路径；不会把旧版 UI 补丁套到新包上。终端也支持原有 alpha.2，但前端与控制器必须同版。

## 新版上游核查与迁移

2026-11-06 对照 npm 官方发布的四个 DSH rc.1 组件包（按注册表 SHA-512 验证），以及 mobile 3.3.0 提交 [`522db94`](https://github.com/mexiaosqwq/dsh-web-mobile/tree/522db94f552d89934f814853ad10c96f31eba6da)：

- mobile 已修复顶栏裁切、文件按钮消失、页签叠字和手机回车换行。旧版顶栏插槽移动、CSS 和 Enter 注入不再用于新版；图标、提示文字和操作栏布局沿用新版上游，不再覆盖为旧的本地偏好。
- 上游 [`composer-enter-newline.ts`](https://github.com/mexiaosqwq/dsh-web-mobile/blob/522db94f552d89934f814853ad10c96f31eba6da/src/client/effects/composer-enter-newline.ts) 会将 Ctrl/Cmd+Enter、斜杠及 @ 候选菜单交回宿主。旧宿主 Enter 注入会抢在仲裁前换行，已复现冲突；迁移会精确撤销该注入。手机换行范围跟随上游的 `<1024px` 粗指针布局。
- Bot 0.2.7 不使用旧 `BotNativeHistory` 所需的宿主插槽。迁移只撤销已识别的宿主历史改动，不把 0.2.6 的历史和提示词变换安装到 0.2.7。布局变换已按 0.2.7 的编译结构单独适配。
- DSH rc.1 仍按 `(row.clientWidth - 48) / 120` 估算页签数；mobile 3.3.0 的修复是样式调整，没有替代宿主的实际宽度测量。因此保留该宿主增强，桌面及未启用 mobile 时回退原逻辑。
- rc.1 原包尚未接入本地终端的重绘、OSC 52、键盘协商、宿主查询应答及搜索/链接辅助逻辑；保留原有宿主控制、快照、流控和主题路径，在版本及匹配点检查后追加增强。

迁移接受原版和完整旧补丁，重复执行不写入；遇到修改过或残缺的旧辅助代码会拒绝，不能通过放宽版本检查强行覆盖。回归覆盖迁移幂等性、未知版本不写入、快捷键/候选菜单恢复及终端真实 headless 协议。源码修改和隔离验证不会自动更新运行实例。

## 安装与检查

主安装器 `dsh_install.sh` 调用插件安装器 `dsh_plugins_install.sh`；后者在下载插件前通过 `dsh_patches_install.sh --validate-tools` 检查本地补丁模块及导入时读取的辅助文件；主安装器也会在安装依赖前执行该检查。插件安装成功后，通过 `dsh_patches_install.sh` 按 DS Bot、mobile、Git panel、terminal、文件资源、会话信息的顺序规划全部补丁。首次安装、`--upgrade`、插件已安装而跳过下载时都会执行。依赖版本与来源由 `srcs/install-versions.json` 固定，mobile 使用已核验提交，Codex 插件与 DSH 同版。补丁失败会使安装返回非零退出码；`--dry-run` 只打印计划，不修改文件。

```sh
bash ds-harness/dsh_install.sh
# 单独补装插件并应用全部补丁
bash ds-harness/dsh_plugins_install.sh
# 手动应用／只检查全部补丁
bash ds-harness/dsh_patches_install.sh
bash ds-harness/dsh_patches_install.sh --check
# 需要单独检查某组补丁时仍可使用原入口
python3 ds-harness/srcs/patches/plugins/ds_bot/ds_bot_apply.py
python3 ds-harness/srcs/patches/plugins/ds_bot/ds_bot_apply.py --check
python3 ds-harness/srcs/patches/plugins/mobile/dsh_mobile_apply.py
python3 ds-harness/srcs/patches/plugins/mobile/dsh_mobile_apply.py --check
python3 ds-harness/srcs/patches/service/dsh_terminal_apply.py
python3 ds-harness/srcs/patches/service/dsh_terminal_apply.py --check
# 全量回归（隔离服务及夹具，不重启线上实例）
python3 -B -m unittest discover -s ds-harness/tests -p 'test_*.py'
```

统一入口 `dsh_patches_install.sh` 复用 `srcs/patches/apply.py`，先完成全部校验，已安装的目标打印“已安装，跳过”，只写入和备份缺失或需要迁移的目标；全部已安装时不创建备份，也不改变文件时间戳。可从任意工作目录调用。默认定位本服务的 web profile 与 PATH 中的 DSH 安装，可用 `--profile-dir`、`--host-dir` 指向隔离安装。DS Bot 独立入口可传 `--bot-dir` 和 `--host-dir`（DSH 的 `node_modules/@deepseek-ai` 目录）。升级到其他版本前必须重新核对上游实现；安装器按 `srcs/install-versions.json` 对齐依赖版本，可能将其他已安装版本恢复到清单值；补丁执行器本身不会变更包版本。

## 旧版本边界

Bot 0.2.6 / DSH alpha.2 保留独立的历史、提示词及 Enter 兼容；Bot 0.2.7 / rc.1 保留自己的 React 别名与布局变换。mobile 3.2.1 / alpha.2 的顶栏及侧栏变换隔离在 `dsh_mobile_legacy.py`，新版不加载。所有版本组合先核验包名和版本，旧辅助代码仅接受完整匹配的已知实现，残缺或未知修改不覆盖。

当前 Bot 的历史、提示词及 mobile 的 Enter 行为由上游维护；迁移会撤销冲突的旧宿主注入。历史排查与部署记录见 [迁移文档](../../MIGRATION.md)。

## 校验与生效

统一入口先核验全部包版本和目标文件，将对同一文件的多组变换按顺序合并到内存中；全部规划成功后才发布，每个目标只备份和替换一次。每个目标在同目录暂存后原子替换；原件与清单备份到 `ds-harness/log/patch-backups/`，后续写入失败会回滚本次全部已完成的替换。`--check` 只校验，不写入；重复应用不创建新备份或改动目标时间戳。独立入口只保证本组文件的回滚范围；npm 插件安装与补丁发布不构成共同事务。进程被强制终止或断电后，先检查备份及 `--check` 结果。

安装器不启停服务。运行实例可能缓存前端 bundle 或服务端模块，安装成功不代表线上已更新；应检查实际 `/plugins/` 响应。需要重载时先检查活跃任务、保存恢复信息，再安排维护，不能默认重启。

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

## mobile 与 Git panel 的上游依据

mobile 3.3.0 提交 [`522db94`](https://github.com/mexiaosqwq/dsh-web-mobile/tree/522db94f552d89934f814853ad10c96f31eba6da) 已修复顶栏裁切、页签命中区及 Enter 仲裁。3.3.1 提交 [`4e71eb6`](https://github.com/mexiaosqwq/dsh-web-mobile/commit/4e71eb67de7dac9d8b2572757c81e47aa32a32fb) 保持 `layout.css.ts` 与 `composer-enter-newline.ts` 不变，继续复用其 UI 和快捷键处理。宿主 rc.1 仍按固定 120px 估算页签宽度，保留 mobile 布局内的实际宽度测量。

mobile 的额外 `ComposerFileButton` 和 Git panel 的 `git-panel-pill` 仍按本地偏好省略注册。Git panel 1.11.2 上游已有 `showInputPill` 开关；本地省略注册可以避免设置将按钮重新显示，因此不是缺失上游开关的兼容修复。

## 手机文件资源不可用

`dsh_file_resources_apply.py` 严格支持 `@deepseek-ai/dsh-client-resources` 的 `0.2.2-rc.1` 和 `0.2.2-alpha.2`（已核对两版发布包的 `protocolOf` 实现相同）。当前发布包的 `protocolOf()` 仍依赖 `new URL(address).hostname`，部分旧版手机浏览器将 `dsh-resource://file/...` 的主机名解析为空，导致资源状态为 `none`，预览显示 “The file resource service is unavailable.”，不会发起文件读取请求。

依据：[上游讨论 #6217](https://github.com/deepseek-ai/deepseek-harness/discussions/6217)。讨论对 Chromium 版本分界有更正，故不按浏览器 UA 或版本号决定是否修复；现代 URL 解析返回主机名时保留原行为，仅当主机名为空时识别大小写不敏感的标准资源提供器名称。保留原文件地址、会话授权和文件读取接口，不改 mobile 插件。

```sh
python3 -B ds-harness/srcs/patches/service/dsh_file_resources_apply.py
python3 -B ds-harness/srcs/patches/service/dsh_file_resources_apply.py --check
python3 -B -m unittest discover -s ds-harness/tests -p 'test_dsh_file_resources.py'
```

插件安装器在其余补丁后自动执行。覆盖现代及模拟旧版 URL 解析、大小写协议、非法地址、未知版本拒绝、重复执行和发布检查。安装器不重启服务；手机需要重新加载页面，才能用到更新后的前端代码。

手机触屏页面回归使用真实 DSH 前端与文件读取接口，在仅模拟旧 URL 主机名解析的条件下，修复前仓库 README 显示资源不可用，修复后进入 `text` 状态且无浏览器异常；25228 响应确认包含新补丁。未操作线上服务启停。

## 主聊天会话信息

`dsh_composer_metadata_apply.py` 适配 DSH `0.2.2-rc.1`，`alpha.2` 明确跳过此 UI 功能。核对当前上游 `ui-conversation` 的 InputBar/ContextMeter 与 `ui-chat` 的 StatsPills：已有实时用量和各项详情，但没有整个元信息区的收起控件。

在输入框工具栏的录音/发送控制之前增加 info 按钮；提示文字复用 `contextPressure` 与 `contextOccupancy` 的上下文用量计算。工作目录、轮次、步骤、速度、Token、缓存命中和原上下文详情默认收起，点击 info 图标展开或收起。保留原生指标组件、弹层和实时更新，切换会话恢复默认收起。按钮有读屏标签、`aria-expanded`/`aria-controls`，支持键盘；展开后点击区域外或按 Esc 自动收起，内部详情操作不触发关闭；鼠标点击保留输入焦点，按钮不会提交表单。DS Bot 替换指标后的 BTW 队列及空状态区不显示此按钮。mobile 的旧圆环定位在元信息内部回退为正常文档流，避免出现第二个工具栏圆环。

```sh
python3 -B ds-harness/srcs/patches/service/dsh_composer_metadata_apply.py
python3 -B ds-harness/srcs/patches/service/dsh_composer_metadata_apply.py --check
python3 -B -m unittest discover -s ds-harness/tests -p 'test_dsh_composer_metadata.py'
```

插件安装器自动应用。浏览器交互回归位于 `tests/test_dsh_composer_metadata.cjs`，依赖通过 `DSH_TEST_PLAYWRIGHT`、`DSH_TEST_REACT_UMD`、`DSH_TEST_REACT_DOM_UMD` 指定已有 Playwright 与 React 18 / ReactDOM 18 的 UMD 文件；Python 测试在缺少这些变量时跳过浏览器项。独立浏览器覆盖 390/820/1600px、默认收起、实时用量、原详情按钮、草稿和输入焦点、键盘切换、会话重置及 Bot 队列，不连接线上服务、不发送消息。

输入工具栏间距修复：mobile 3.3.1 对上传按钮保留 `margin-left:-9px!important`，权限按钮的 18px 图标与 14px 箭头合计 32px，而 modes 分组允许收缩。390px 页面实测上传按钮与权限点击区重叠约 3px。元信息补丁的 CSS 现固定左侧工具分组及权限组的完整宽度，撤销上传负边距，保留 8px 间隔，并限制上传按钮伪元素只向纵向扩展，避免横向盖住箭头。350px 以下右侧控制组换行；规则仅作用于启用了原生元信息圆环的移动主聊天输入框，未改上传或权限处理器。支持从上一版元信息补丁精确迁移，未知修改拒绝覆盖。

实际 25228 主聊天手机页在 320/360/390/820px 下验证权限按钮与箭头到上传按钮均有 8px 间隔，点击命中区域分离，页面无横向溢出；未发送消息或改变权限设置。

## 执行器与核查范围

`common.py` 统一独立入口的参数解析、`--check`、发布和结果输出；包名及版本校验也由共享函数执行。各模块只维护版本组合、变换和文件计划；终端旧剪贴板迁移复用已有撤销函数，会话信息包装从原生片段派生，避免重复维护同一代码。独立入口名称和参数不变，未删除已支持版本及必要迁移，生成的目标 bundle 与精简前一致。

核查依据为 `data/patch-audit-20261106/pristine/` 中已按注册表完整性校验的 DSH rc.1 发布包、`data/bot-audit-20261107/` 中的 Bot 0.3.1 原包，以及当前安装的 mobile 3.3.1 和 Git panel 1.11.2。本次未联网核查这些包之后的新版本；不把本地发布包的核查结论外推到未来版本。

## Bot 0.3.1 补丁复核（2026-11-07）

通过 `npm view ds-bot version dist.tarball dist.integrity gitHead` 确认最新正式版为 0.3.1；标签 [`v0.3.1`](https://github.com/Fei2411/DS-Bot/tree/6559c9e7c4ef71c292e6ac50f690031133536fe0) 与 npm `gitHead` 均为 `6559c9e7c4ef71c292e6ac50f690031133536fe0`。下载发布包并核对注册表 SHA-512，npm 客户端、标签中的客户端和本机安装客户端在应用本次补丁前逐字节一致。原包及隔离验证副本位于不入库的 `data/bot-audit-20261107/`。

| 原补丁或功能 | 上游 0.3.1 的实现及处理 |
| --- | --- |
| 历史分段及导航 | [`cells.js`](https://github.com/Fei2411/DS-Bot/blob/6559c9e7c4ef71c292e6ac50f690031133536fe0/ds-bot/src/client/cells.js) 已由 handoff 节点渲染 `EarlierParts`；[`header-navigation.js`](https://github.com/Fei2411/DS-Bot/blob/6559c9e7c4ef71c292e6ac50f690031133536fe0/ds-bot/src/client/header-navigation.js) 复用宿主导航及 store。不注入旧 BotNativeHistory 或宿主历史插槽，仅迁移仍残留的旧宿主改动。 |
| 提示词 tools 缺失时报错 | [`tools.js`](https://github.com/Fei2411/DS-Bot/blob/6559c9e7c4ef71c292e6ac50f690031133536fe0/ds-bot/src/host/tools.js) 已在 system-prompt/assemble 中以 `Array.isArray(assembled.tools)` 判断后过滤；原生保留 sections 和其他组装字段。新版不修改 Bot 宿主 tools.js。 |
| 手机工具栏浮动及可点击区域 | [`styles.js`](https://github.com/Fei2411/DS-Bot/blob/6559c9e7c4ef71c292e6ac50f690031133536fe0/ds-bot/src/client/styles.js) 已在 `(hover:none)` 下提供右侧浮动位置及 44px 命中区，`cells.js` 支持点击消息打开工具栏。新版删除旧 `MOBILE_PHONE_CSS` 的 640px 浮动覆盖，保留原生触屏命中区；全宽回复由全尺寸 ALIGN_CSS 负责。若安装文件已有该旧覆盖，会精确撤销。 |
| 触屏操作按钮始终可见 | 上游通过点击消息显示，行为与本地常驻偏好不同；保留 TOUCH_ACTIONS_CSS，不把它称为上游已覆盖。 |
| 输入框两行、8px 工具间距 | 上游仍默认单行，仅在有附件时切两行；保留本地常态两行偏好。 |
| 群聊头像与时间同行、窄栏显示名称 | 上游 bubble 布局仍把头像传入 Bubbles，窄栏仍是图标；保留本地元信息及名称布局。 |
| 桌面原生宽度拖动 | 上游仍隐藏宿主 widthHandle、固定正文 960px / 输入框 992px；保留恢复宿主拖动和继承宽度变量的补丁，不另写拖动器。 |
| 全宽回复及下方操作栏、复制/下载直达按钮 | 上游仍是 bubble 侧边工具栏及 More 菜单；保留布局和直达按钮，复用上游复制、下载、引用及表情处理器。 |
| mobile 侧栏网格与测量 | 上游 `styles.js` 仍保留三列网格，`frame-watch.js` 仍将 sidebarCol 的矩形宽度当作网格占位；未识别 mobile 的 absolute/fixed 抽屉。保留 mobile 标记下网格兼容及浮动侧栏占位修正。 |

新版消息组件的 React 别名为 `import_react31`，portal 别名为 `import_react_dom3`；只支持已核对的 0.3.1 + DSH rc.1 版本组合，不以通配版本跳过锚点校验。0.2.7 / rc.1 和 0.2.6 / alpha.2 继续走各自的历史兼容路径，其旧代码不会套用到 0.3.1。

测试夹具 `tests/fixtures/ds_bot_031.js` 摘录自原始发布包，保留原始函数和规则，避免仅用补丁常量拼接测试。回归验证复制、下载、引用、表情弹层、头像点击、flat/bubble 元信息位置、旧覆盖撤销、旧宿主迁移、未知版本和残缺锚点不写入、重复应用不写入，以及完整补丁集的共享文件合并与回滚。完整发布包另在隔离副本验证 JS 语法、原生 tools.js 不变及幂等性。

返回主聊天使用上游入口：左下角头像/齿轮 → Bot 设置 → 常规 → 模式 → 经典 Agent 模式 → 切换；不增加重复的模式切换逻辑。应用本次客户端补丁无需重启服务，浏览器需重新加载资源；已打开页面的视觉效果仍需刷新后验收。


## 2026-11-07 最新版本升级复核

安装器的 `--upgrade` 通过 `update-install-versions.mjs` 先查询 npm 最新标签和 mobile GitHub HEAD，再更新固定版本清单；普通安装使用清单，预览不联网或写入。Codex 的 npm `latest` 标签仍是旧的 0.0.1-rc.1，升级时以 DSH 的 0.2.2-rc.1 精确解析，避免降级。全部查询成功后才发布清单，原清单保存在 `data/version-backups/`。

当前新增 pnpm 12.18.0、dshmarket 1.73.14、dsh-ide-git 0.30.0、Git panel 1.13.1；mobile 同为 3.3.1，但来源从 4e71eb6 更新到 [`d3e7e8e`](https://github.com/mexiaosqwq/dsh-web-mobile/tree/d3e7e8e21a07ff17188d3b344a3d3acfb5acb1e9)。mobile 新增页签布局和滑动手势调整，仍保留额外文件按钮注册；完整新 bundle 已验证能应用现有按钮补丁，宿主宽度测量和 Enter 迁移保持幂等。

Git panel 1.13.1 发布包的注册新增 `useContextMenu`，压缩别名也改变；补丁增加该版本的完整精确注册锚点，复用上游其他视图及菜单，继续按本地偏好省略输入按钮。未知、重复或两代混合注册仍拒绝修改。发布包来自 npm，对照其声明的 [Git panel 上游仓库](https://github.com/xbzbing/dsh-git-panel)，版本兼容范围覆盖 DSH rc.1。最新发布包及安装前备份位于不入库的 `data/upgrade-20261107/`。
