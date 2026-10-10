# 安装与同步

## 分支约定

`main` 是可独立维护的纯上游分支，安装和同步脚本不更新或依赖它。`terminal-patch` 是独立根提交开始的补丁分支，只保存定制维护所需的文件。不要将这两个分支相互 merge 或 rebase；通过应用 `.patch` 文件组合代码。

`patches/0001-swap-chat-workspace.patch` 包含面板交换、终端重绘及其测试；`patches/0002-preserve-terminal-replay-modes.patch` 保留裁剪回放缓存时的终端模式，避免刷新后丢失 Codex 的滚轮输入。`patches/base-commit` 是整组补丁的唯一上游基线，必须包含一个完整的 40 位小写十六进制 commit ID。同步、安装和 `update` 都使用这个提交；上游或本地 `main` 前进不会改变安装版本。补丁和基线应一起审查、验证、提交。

## 本地安装（不启动服务）

在 `terminal-patch` 工作区执行：

```bash
# 首次安装或补丁基线变更后，获取固定的上游提交
sh scripts/sync.sh
# 使用本地缓存的固定提交安装
sh scripts/install.sh
```

`install.sh` 的执行顺序：

1. 创建独立安装仓库，以 detached HEAD 检出 `patches/base-commit` 指定的本地缓存提交，按文件名顺序应用当前工作区 `patches/*.patch`，使用 Git 三方合并。
2. 在生成目录的 `.npmrc` 中配置 node-pty/esbuild 的安装脚本权限，安装依赖。
3. 运行测试并构建。
4. 若 PATH 中没有 `pi` 命令，全局安装 `@earendil-works/pi-coding-agent`（默认 `latest`，可设置 `PI_VERSION`）；已有 Agent 保留当前版本。安装失败会停止，不替换 pi-web。
5. 使用当前 npm 的全局安装前缀，将 `pi-web`、`pi-web-server`、`pi-web-sessiond` 链接到构建成功的新目录，替换旧的全局 npm 安装，打印安装目录和命令路径。此步骤跳过生命周期脚本和自动 peer 依赖安装，不更新 Pi Agent。

默认安装仅补装缺失的 Pi Agent，不升级已有 Agent、不拉取或推送 Git 远端，不注册、启动或重启服务，也不会调用 `node dist/cli.js install`。若本地缺少指定提交，会提示先运行 `sh scripts/sync.sh`；上游同步与安装分开执行。旧的 `--port` 等服务安装参数不再接受。

每次创建的安装目录位于 `~/.local/share/pi-web-opt/release.*`，可设置 `PI_WEB_INSTALL_ROOT` 改变位置。测试或构建失败会停止并保留现场，已安装或运行的版本不变。旧目录不会自动清理。

构建成功后，全局命令指向新的独立安装目录，因此不要删除正在使用的 release 目录。全局前缀需可写；使用 nvm 时替换的是当前 Node 环境中的安装。如果 `command -v pi-web` 与脚本输出的命令路径不同，请检查 PATH 中是否有其他安装抢先匹配。

已运行的进程需要手动重启。如果自己的启动脚本或服务配置写死了旧 release 的绝对路径，还需要将其改为新的路径。模型提供商认证和启动配置由使用者单独管理；已有 Pi Agent 的升级使用 `update --pi-only`。

`sync.sh` 按 commit ID 从官方仓库获取基线，可通过 `PI_WEB_UPSTREAM_URL` 改变上游仓库地址，但不能覆盖基线版本。它不拉取最新 `main`、不修改任何分支、不推送远端，也不要求配置 `origin`。`sync.sh --local` 只使用本地已有的同一提交，缺失时明确报错。两种脚本都不会自动提交或推送 `terminal-patch` 的修改，安装前应审查补丁工作区并提交要共享的修改。

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

## 升级补丁绑定的上游版本

升级基线是显式的维护操作。在 `terminal-patch` 工作区，先获取并选定要适配的上游提交，写入基线，然后准备补丁目录：

```bash
git fetch https://github.com/jmfederico/pi-web.git main
git rev-parse FETCH_HEAD > patches/base-commit
sh scripts/sync.sh
```

这里手动获取 `main` 仅用于选择新基线。也可以获取一个已知的完整 commit ID；后续安装始终使用写入文件的固定提交。准备成功后，在打印的 release 目录安装依赖、测试和构建；如有冲突，按下一节处理。验证通过后，将基线与适配后的补丁一起提交，其他使用者获取补丁分支的更新后执行 `sync.sh` 和 `install.sh`。

## 上游变化导致补丁冲突

脚本会停止，打印保留的安装目录；纯上游 `main` 中不会写入补丁，也不会执行服务安装。在保留目录中查看 `git status`，解决冲突并测试，再生成替换补丁：

```bash
cd /脚本打印的/release.目录
git status
# 编辑并解决冲突后，仅暂存补丁涉及的文件
git add <已解决的文件>
# 全部解决后，该命令应无输出
git diff --name-only --diff-filter=U
printf '\nallow-scripts=node-pty,esbuild\n' >> .npmrc
npm ci --include=dev
NODE_OPTIONS=--no-experimental-webstorage npm test
npm run build

# 将路径替换为 terminal-patch 工作区的实际位置
git diff --cached --binary --full-index HEAD -- <该补丁涉及的文件> > /补丁工作区/patches/<对应补丁>.patch
git rev-parse HEAD > /补丁工作区/patches/base-commit
```

当前两个补丁修改不同文件，应按各自涉及的文件分别重新生成，避免把相同修改重复放入多个补丁。不要将 release 目录中的全部累计修改写入单个补丁后，继续保留包含相同变更的其他补丁。

然后在补丁工作区提交并推送：

```bash
cd /补丁工作区
node --test tests/*.test.mjs
git add patches
git commit -m "fix: adapt layout patch to upstream"
git push origin terminal-patch
sh scripts/install.sh
```

更新基线时，应验证补丁在新提交上的测试和构建，再同时提交 `patches/base-commit` 和补丁。仅运行 `sync.sh` 不会升级基线，安装始终可复现同一组上游源码与补丁。

## 统一入口更新

```bash
bash scripts/install.sh update                  # 更新 Pi Agent，并同步、构建补丁版 pi-web
bash scripts/install.sh update --pi-only        # 只更新 Pi Agent
bash scripts/install.sh update --web-only       # 只同步、构建补丁版 pi-web
bash scripts/install.sh update --dry-run        # 预览操作
bash scripts/install.sh update --no-restart     # 不停止或重启服务
```

`install` 使用本地缓存的固定提交；`update` 默认先更新 Pi Agent，再调用 `sync.sh` 获取 `patches/base-commit` 指定提交、应用补丁，随后安装依赖、测试、构建和替换全局命令。更新不需要 origin 的推送权限，也不会自动更新补丁分支；要升级 pi-web，应先获取已适配新基线的补丁分支版本。补丁冲突或测试构建失败时，不会替换已安装的 pi-web；之前已完成的 Agent 更新或源码同步不会回滚。

`update` 默认只重启原先正在运行的服务；`--restart` 会在更新后启动服务，`--no-restart` 保持服务原有状态。更新失败时可能保留已停止的服务，修复后可通过运行脚本启动。支持 `--update-relay` 和 `PI_VERSION`（Agent 目标版本，默认 `latest`）。pi-web 使用 `patches/base-commit`，不使用 `PI_WEB_VERSION`。运行脚本的 `update` 命令也转入此统一入口。旧的 `update-pi-web-jmfederico.sh` 已移除；不带子命令仍默认执行 `install`。
