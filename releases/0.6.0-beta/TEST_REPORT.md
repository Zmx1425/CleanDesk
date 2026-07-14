# CleanDesk 0.6.0-beta 测试记录

本记录区分自动验证、开发期间人工确认和本次未验证项目，不代表所有 Windows 环境均已覆盖。

## 已自动验证

- 旧配置、部分 settings、非法 settings 和未知字段兼容；
- 多监控文件夹添加、选择、移除、重复/嵌套/不存在路径拒绝；
- “整理当前文件夹”只处理当前文件夹；
- 相对目标分别落在来源目录，绝对目标不被再次拼接；
- move/ignore 规则、忽略优先级、规则顺序保存和智能建议排除忽略类型；
- 扫描移动、活动来源信息和撤销批次；
- 两个目录同时监听、Stop 和 `scan_existing_on_start=false`；
- 手动/自动重名策略的 ask、keep_both、skip 路径；
- 设置窗口字段、保存/取消、活动上限、清空活动不清除 undo；
- `1600x900`、`1200x800`、`850x700` 响应式模式及无横向滚动策略；
- Windows Run 命令生成、旧命令识别、内存注册表启用/关闭和失败保护；
- 普通启动与 `--startup` 分流、隐藏启动自动整理调度；
- 双进程 QLocalServer/QLocalSocket 唤醒、stale server 和启动竞态；
- `python -m compileall .`；
- PyInstaller onedir 构建及发布 ZIP 结构检查。
- 从 Windows ZIP 解压到全新临时目录后，`CleanDesk.exe --startup` 可后台存活并生成首次配置；
- 再启动第二个 exe 时，第二进程快速退出，首进程随后出现可响应的 `CleanDesk` 窗口句柄。

## 开发期间已人工确认

- 系统托盘图标、关闭到托盘和后台 watcher；
- 托盘恢复、托盘菜单和托盘退出；
- Windows 登录后自动启动；
- 开机自启不显示 CMD、不显示主窗口并静默进入托盘。

## 本次未验证

- 未执行真实 Windows 注销或重启；注册表自动测试使用内存 backend，未改写真实 Run 项；
- 未在无 Python 的另一台全新 Windows 设备上验证；
- Windows Explorer 中“打开所在位置并选中文件”的视觉结果未自动验证；
- 系统托盘图标、窗口置前和图标视觉需在最终发布包上人工复核；
- 自动脚本无法通过 PowerShell `CloseMainWindow()` 关闭 Qt 窗口，发布包托盘退出仍以开发期间人工确认为准；
- 未使用用户真实 Downloads、Desktop、真实配置或真实规则测试。
