# PI WEB 桌面布局补丁

本仓库按两个独立分支维护：

- [`main`](https://github.com/lihui-colin/pi-web/tree/main)：完整的官方上游代码与历史，保持与 `jmfederico/pi-web/main` 同步。
- `terminal-patch`：只有布局补丁、安装脚本、文档和测试，不继承上游历史。补丁让桌面的 Chat 与 Workspace Panel 交换位置，并保存浏览器偏好。

需要 Git、Node.js ≥22.19、npm，以及对 origin 的 Git 推送权限。后台安装需要支持的用户服务管理器，例如 Linux systemd。

```bash
git clone --branch terminal-patch git@github.com:lihui-colin/pi-web.git pi-web-opt
cd pi-web-opt
sh install.sh
```

安装脚本依次更新 Pi Agent、同步本地和 origin 的 `main`、在独立目录应用补丁、测试构建、安装用户服务。默认打开 http://127.0.0.1:8504，在命令面板中选择 **Swap Chat / Workspace Panel** 切换布局。

详细的同步、冲突处理和补丁维护方法见 [使用文档](docs/usage.md)。
