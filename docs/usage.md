# 安装与同步

## 分支约定

`main` 是可独立维护的纯上游分支，安装和同步脚本不更新或依赖它。`terminal-patch` 是独立根提交开始的补丁分支，只保存定制维护所需的文件。不要将这两个分支相互 merge 或 rebase；通过应用 `.patch` 文件组合代码。

`patches/0001-terminal-redraw.patch` 仅包含终端重连重绘修复及其测试；Chat 与 Workspace Panel 使用官方布局；`patches/0002-preserve-terminal-replay-modes.patch` 保留裁剪回放缓存时的终端模式，避免刷新后丢失 Codex 的滚轮输入；`patches/0003-terminal-osc52-clipboard.patch` 将 Codex 等 TUI 发出的复制请求写入浏览器所在电脑的剪贴板。`patches/base-commit` 是整组补丁的唯一上游基线，必须包含一个完整的 40 位小写十六进制 commit ID。同步和普通安装使用这个提交；`update` 会先用官方 `main` 最新提交更新该文件。补丁和基线应一起审查、验证、提交。

## 补丁分组

当前维护 7 个按功能划分的补丁：

| 编号 | 内容 |
| --- | --- |
| `0001` | 终端回放后的 TUI 重绘及测试 |
| `0002` | 回放缓存裁剪时保留终端模式及测试 |
| `0003` | OSC 52 复制请求处理，以及共用剪贴板 API 可用性检查 |
| `0004` | 终端触摸滚动及测试 |
| `0005` | Shift+← 软键 |
| `0006` | 完整 Codex 插件、移动端布局、Plan 入口、复制兼容和构建集成及测试 |
| `0007` | 添加项目弹窗中的候选目录自动换行，并显示完整已选路径 |

原 `0007`–`0017` 的最终效果已合并到上述补丁，不再保留中间界面方案。共用的 `terminal/clipboard.ts` 修复归入 `0003`，其余 Codex 调整归入 `0006`。未来修改已有功能时，更新对应补丁；不要将已经被后续实现替换的中间步骤继续堆叠为新补丁。

整理补丁时，先在独立目录应用原补丁链并记录 `git write-tree`，再从相同基线应用整理后的补丁链，对比 `git write-tree`。仅整理、不改变功能时，两者必须完全一致；测试和构建按下文执行。

## 本地安装（不启动服务）

在 `terminal-patch` 工作区执行：

```bash
# 自动同步固定提交并安装
sh scripts/install.sh
```

`install.sh` 首先检查 `data/pi-web.conf`，不存在时从根目录 `pi-web.conf.example` 创建，已有配置保持不变。随后执行：

1. 创建独立安装仓库，以 detached HEAD 检出 `patches/base-commit` 指定的提交（先由 sync.sh 同步至 data/pi-web-upstream.git），按文件名顺序应用当前工作区 `patches/*.patch`，使用 Git 三方合并。
2. 在生成目录的 `.npmrc` 中配置 node-pty/esbuild 的安装脚本权限，安装依赖。
3. 运行测试并构建。
4. 若 PATH 中没有 `pi` 命令，全局安装 `@earendil-works/pi-coding-agent`（默认 `latest`，可设置 `PI_VERSION`）；已有 Agent 保留当前版本。安装失败会停止，不替换 pi-web。
5. 使用当前 npm 的全局安装前缀，将 `pi-web`、`pi-web-server`、`pi-web-sessiond` 链接到构建成功的新目录，替换旧的全局 npm 安装，打印安装目录和命令路径。此步骤跳过生命周期脚本和自动 peer 依赖安装，不更新 Pi Agent。

默认安装仅补装缺失的 Pi Agent，不升级已有 Agent、不推送 Git 远端，不注册、启动或重启服务，也不会调用 `node dist/cli.js install`。安装会先执行 `sh scripts/sync.sh` 同步指定提交；同步失败即停止，不安装依赖或替换全局命令。旧的 `--port` 等服务安装参数不再接受。

每次创建的安装目录位于 `data/pi-web-releases/release.*`，可设置 `PI_WEB_INSTALL_ROOT` 改变位置。测试或构建失败会停止并保留现场，已安装或运行的版本不变。旧目录不会自动清理。

构建成功后，全局命令指向新的独立安装目录，因此不要删除正在使用的 release 目录。全局前缀需可写；使用 nvm 时替换的是当前 Node 环境中的安装。如果 `command -v pi-web` 与脚本输出的命令路径不同，请检查 PATH 中是否有其他安装抢先匹配。

已运行的进程需要手动重启。如果自己的启动脚本或服务配置写死了旧 release 的绝对路径，还需要将其改为新的路径。模型提供商认证和启动配置由使用者单独管理；已有 Pi Agent 的升级使用 `update --pi-only`。

`sync.sh` 先检查 `data/pi-web-upstream.git`，已有指定提交时跳过远端下载，可离线准备源码；缺失时才按 commit ID 从官方仓库获取基线，可通过 `PI_WEB_UPSTREAM_URL` 改变上游仓库地址，但不能覆盖基线版本。它不拉取最新 `main`、不修改任何分支、不推送远端，也不要求配置 `origin`。`sync.sh --local` 只使用 `data/pi-web-upstream.git` 缓存中的同一提交，缺失时明确报错。两种脚本都不会自动提交或推送 `terminal-patch` 的修改，安装前应审查补丁工作区并提交要共享的修改。

## 只同步代码并准备补丁版本

```bash
# 在 terminal-patch 分支中
release_dir=$(sh scripts/sync.sh)
cd "$release_dir"
printf '\nallow-scripts=node-pty,esbuild\n' >> .npmrc
npm ci --include=dev
NODE_OPTIONS=--no-experimental-webstorage npm test
npm run build
```

`sync.sh` 获取固定提交，在独立目录应用补丁并输出目录路径，不更新 Pi Agent、不安装依赖、不测试构建、不重启服务。Node 26 的测试需上述 `NODE_OPTIONS`，其他版本可直接运行 `npm test`。

已有的本地或远端 `main` 可以领先于补丁基线，也可以在其他 worktree 中使用；同步不修改这些分支和工作区。基线文件缺失、格式错误、提交不可获取时脚本会失败，不会回退到 `main` 或其他版本。

## Codex 终端选中即复制

Codex TUI 松开鼠标后可能显示 `Copy sent to terminal — paste to verify`，这表示已发送复制请求。补丁版 pi-web 会处理实时输出中的 OSC 52 请求，写入成功后在终端底部居中浮现 `Copied`，2 秒后自动消失；连续复制会重新计时。提示在 Fullscreen 模式下同样可见，不改变终端尺寸，也不拦截鼠标操作。它支持分段传输和 UTF-8 文本；刷新或重连时的历史回放不会再次复制旧内容。

如果浏览器阻止自动写入，终端底部居中会显示 `Automatic copy was blocked.`，保留到重试或手动关闭；点击 **Copy to clipboard** 重试。通过局域网 HTTP 访问时，浏览器通常没有异步剪贴板 API，此按钮会使用点击触发的兼容复制方式。浏览器策略仍可能拒绝写入，只有显示 `Copied` 才表示复制接口报告成功。

安装包含此补丁的版本后，重启提供网页资源的 `pi-web-server` 并刷新页面。本补丁仅修改浏览器端，不需要为此重启 `pi-web-sessiond` 或重新创建 Codex 会话。

## 升级补丁绑定的上游版本

`update` 会自动升级到官方 `main` 最新基线；也可手动选择基线。在 `terminal-patch` 工作区，先获取并选定要适配的上游提交，写入基线，然后准备补丁目录：

```bash
git fetch https://github.com/jmfederico/pi-web.git main
git rev-parse FETCH_HEAD > patches/base-commit
sh scripts/sync.sh
```

这里手动获取 `main` 仅用于选择新基线。也可以获取一个已知的完整 commit ID；后续安装始终使用写入文件的固定提交。准备成功后，在打印的 release 目录安装依赖、测试和构建；如有冲突，按下一节处理。验证通过后，将基线与适配后的补丁一起提交，其他使用者获取补丁分支的更新后执行 `install.sh`。

## 上游变化导致补丁冲突

脚本会在冲突补丁处停止并打印保留目录，后面的补丁尚未应用。可在该目录查看 `git status` 和冲突内容。

重新生成补丁时，使用独立维护工作区，从 `patches/base-commit` 指定的纯上游提交开始。按编号逐个应用补丁，每个补丁解决冲突后生成差异并做一个本地维护提交，再处理下一个：

```bash
# HEAD 必须是当前补丁应用前的状态：上游基线 + 已提交的前序补丁
# 将路径和编号替换为实际值
git apply --3way --index /补丁工作区/patches/0001-terminal-redraw.patch
# 如有冲突，编辑解决后仅暂存对应文件
git add <已解决的文件>
# 全部解决后，该命令应无输出
git diff --name-only --diff-filter=U
git diff --cached --binary --full-index HEAD > /补丁工作区/patches/0001-terminal-redraw.patch
git commit -m "Apply patch 0001"
# 对 0002、0003 依次重复，然后安装依赖、运行测试和构建
```

`0001` 与 `0003` 会修改同一文件，因此不能按文件名将整个 release 的累计差异分别导出。`patches/base-commit` 始终记录纯上游提交，不要写入上述本地维护提交的 ID。全部补丁适配后，在补丁工作区重新运行 `sync.sh --local`，验证整组补丁可从上游基线顺序应用，并在新目录完成测试和构建。

然后在补丁工作区提交并推送：

```bash
cd /补丁工作区
node --test tests/*.test.mjs
git add patches
git commit -m "fix: adapt patches to upstream"
git push origin terminal-patch
sh scripts/install.sh
```

更新基线时，应验证补丁在新提交上的测试和构建，再同时提交 `patches/base-commit` 和补丁。仅运行 `sync.sh` 不会升级基线，安装始终可复现同一组上游源码与补丁。

## 运行脚本更新

```bash
bash scripts/pi-web-run-jmfederico.sh update                  # 更新 Pi Agent，并同步、构建补丁版 pi-web
bash scripts/pi-web-run-jmfederico.sh update --pi-only        # 只更新 Pi Agent
bash scripts/pi-web-run-jmfederico.sh update --web-only       # 只同步、构建补丁版 pi-web
bash scripts/pi-web-run-jmfederico.sh update --dry-run        # 预览操作
```

`install` 先执行 `sync.sh` 复用缓存（缺失时下载）并应用补丁；`update` 默认先将 Pi Agent 更新到 latest，再获取官方 `main` 最新提交并原子写入 `patches/base-commit`，随后调用 `sync.sh` 同步并应用补丁，随后安装依赖、测试、构建和替换全局命令。更新不需要 origin 的推送权限，也不会自动更新补丁分支；新基线如与补丁冲突，更新停止并保留新基线和冲突目录，需适配补丁后重试。拉取失败不改写基线，`--dry-run` 不拉取或改写基线。补丁冲突或测试构建失败时，不会替换已安装的 pi-web；之前已完成的 Agent 更新或源码同步不会回滚。

`update` 不启停服务。支持 `--update-relay`；update 的 Agent 目标固定为 `latest`，`PI_VERSION` 只控制普通 install 补装 Agent 的版本。pi-web 使用 `patches/base-commit`，不使用 `PI_WEB_VERSION`。更新仅通过运行脚本 `pi-web-run-jmfederico.sh update` 执行；`install.sh` 只负责安装，不接受 `update` 子命令。更新完成后，如需生效，先确认活跃会话允许中断并保存恢复信息，再执行 `bash scripts/pi-web-run-jmfederico.sh restart`；实例由当前 `data/pi-web.conf` 选择，不接受 `--port` 参数。旧的 `update-pi-web-jmfederico.sh` 已移除；`install.sh` 不带子命令时默认执行 `install`，运行管理脚本则必须指定子命令。
