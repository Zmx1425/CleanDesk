# CleanDesk 0.7.2-beta 测试报告

## 自动验证

- `python -m compileall .`：通过；
- `build_windows.bat`：通过，生成完整 `dist\CleanDesk\` 目录；
- PyInstaller 使用 `--windowed`，生成的应用为无控制台窗口模式；
- `build_installer.bat`：通过，使用 Inno Setup 6.7.3 生成安装程序；
- Inno Setup 脚本从 `version.py` 读取 `0.7.2-beta`；
- 安装负载包含完整 `dist\CleanDesk\`，不是单独 EXE；
- 安装负载中未发现 `config.json`、`logs`、日志文件或 Python 缓存；
- Windows 便携 ZIP 可正常解压，包含 159 个文件；
- 便携 ZIP 中 `CleanDesk.exe` 与本次 `dist` 构建结果 SHA-256 一致；
- 便携 ZIP 未发现配置、日志、测试目录或缓存。

## Windows 安装验证

- 简体中文安装向导可正常打开；
- 安装向导显示版本 `0.7.2-beta`；
- 默认目录为当前用户的 `%LOCALAPPDATA%\Programs\CleanDesk`；
- 安装日志确认使用当前用户安装模式，未使用管理员安装模式；
- 桌面快捷方式为可选任务，实际启用后创建成功；
- 开始菜单快捷方式创建成功；
- “已安装的应用”卸载项包含名称、版本、发布者、安装目录和卸载程序；
- 安装后程序文件完整，首次运行前没有携带 `config.json` 或 `logs`；
- 安装后的 `CleanDesk.exe` 可启动，未显示 CMD 窗口；
- 主窗口与设置窗口可打开，关于信息显示 `0.7.2-beta` 和开发者 `Zmx`；
- 第二次启动未创建第二个实例；
- 覆盖安装成功，已生成的配置仍保留，未被安装包默认数据覆盖；
- 标准卸载成功，程序 EXE、卸载程序、开始菜单快捷方式和桌面快捷方式被删除；
- 卸载项从注册表移除，卸载后没有残留 CleanDesk 进程；
- 卸载保留程序运行后生成的 `config.json` 与 `logs`；
- 卸载未删除独立测试目录中的用户文件；
- 验证结束后仅清理了本次测试生成的配置、日志和临时测试文件。

## 尚未验证

- 未在非管理员标准账户中重复安装；脚本使用 `PrivilegesRequired=lowest`，本次安装日志确认未进入管理员安装模式；
- 未在包含中文和空格的自定义安装目录中重复安装；Inno Setup 与安装脚本均使用 Unicode 和带引号路径；
- 未逐步点击完成页的“运行 CleanDesk”，但该选项已写入脚本并通过 Inno Setup 编译；
- 本轮未修改主题、通知、托盘、开机自启、文件整理或撤销逻辑，未重新执行这些功能的完整人工回归；
- 安装程序未进行代码签名，Windows SmartScreen 提示效果需在发布前按实际分发环境复核。
