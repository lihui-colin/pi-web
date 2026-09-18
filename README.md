# PI WEB 桌面布局补丁

本仓库按两个独立分支维护：

- [`main`](https://github.com/lihui-colin/pi-web/tree/main)：完整的官方上游代码与历史，保持与 `jmfederico/pi-web/main` 同步。
- `terminal-patch`：只有布局补丁、安装脚本、文档和测试，不继承上游历史。补丁让桌面的 Chat 与 Workspace Panel 交换位置，并保存浏览器偏好。

需要 Git、Node.js ≥22.19 和 npm。同步上游时需要对 origin 的 Git 推送权限，本地安装不需要。

```bash
git clone --branch terminal-patch git@github.com:lihui-colin/pi-web.git pi-web-opt
cd pi-web-opt
sh sync.sh  # 首次初始化 main，或同步最新上游
sh install.sh
```

安装脚本使用本地 `main`，在独立目录应用补丁、安装依赖并测试构建，最后打印安装目录。它不更新 Pi Agent、不同步远端、不注册或启动后台服务。程序启动后，在命令面板中选择 **Swap Chat / Workspace Panel** 切换布局。

详细的同步、冲突处理和补丁维护方法见 [使用文档](docs/usage.md)。
