# 手机端 / Android 0.3.1

当前手机版已与 PC 端对齐为 **0.3.1 / versionCode 192**（同挂于 [v0.3.1 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.3.1)）。

[下载 KARDS-AUTO-Mobile-v0.3.1.apk](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.3.1/KARDS-AUTO-Mobile-v0.3.1.apk) · [发布页](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.3.1) · [本次更新与验证](releases/0.3.1.md) · [源码与构建](source/README.md)

## 下载与使用

1. 最低 **Android 10 / API 29**（targetSdk 35），支持 `arm64-v8a` 和 `x86_64`。直接安装 APK，无需解压；原签名旧版（v0.2.3 / v0.2.4）可直接覆盖升级，不要先卸载。安装不同签名自编译包时系统不允许直接覆盖。运行无需 Windows、ADB、Termux、Shizuku 或另装 Python。
2. 安装并登录 KARDS。建议游戏用简体中文、内容比例设为“原生”、UI 比例 1；助手需启用系统无障碍权限。必要时在助手内选择已安装的游戏。
3. Android 14+ 使用游戏窗口截图；Android 11–13 若默认截图黑屏，可在助手主界面启用“兼容截图”并确认屏幕共享；**Android 10 (API 29)** 必须先在主界面启用兼容截图并授予屏幕共享权限。撤销或进程重启后需重新授权。
4. 选休闲/排位及局数（`0` 表示持续运行）。可从助手自动打开游戏，或选“仅启动辅助 · 手动打开游戏”后自行切回游戏。确认人在场、游戏位于前台；异常可从悬浮控制条停止。自动化可能触发游戏检测，不建议无人值守长时运行。
5. 打开助手时内置更新器会自动查询最新发行版；未见提示可直接使用上方固定下载链接。

## 已知限制

- Android 10 (API 29) 兼容层已完成离线字节码/Lint 检查与适配测试，尚未在真实 Android 10 设备上完成实机安装与长稳验证。
- 部分 4:3 布局的**可领取**奖励页仍可能需要手动处理后返回真正游戏主页。
- 部分需要二次选目标的出牌仍不完整；模拟器验证不等于全部实体手机长期稳定。

历史：[0.2.4 手机版](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.4) · [0.2.3 手机版](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.3) · [0.2.3 验证](../docs/reports/mobile/APK_0.2.3_RELEASE.md)。
