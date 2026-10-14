# 手机端 / Android

[手机版源码](source/README.md)位于本目录，独立维护，PC发布包不包含手机版。

## 0.2.1 下载与安装

- 直接下载 [KARDS-AUTO-Mobile-v0.2.1.apk](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.1/KARDS-AUTO-Mobile-v0.2.1.apk)。这是APK文件，无需解压。
- 最低Android11/API30，支持arm64-v8a和x86_64；允许安装下载来源应用后打开APK安装。相同签名的已有版本可覆盖更新。
- 已内置Python、NumPy/OpenCV、OCR运行库与模型；运行无需Windows、ADB、Termux、Shizuku或另装Python。
- 安装并登录KARDS后，在系统无障碍设置启用“KARDS 对战助手”。使用简体中文界面；已验证游戏版本1.60.27292/code2703，横屏2772×1240。其他手机布局需实测。
- 选择休闲/排位及局数；`0`表示无限。可从菜单开始或接管当前对局。右侧悬浮条点击展开，展开继续运行，手动点击停止；截图/输入期间自动暂时隐藏面板。
- 当前动作顺序是行动后部署。新截图证据按350MiB预算管理，优先淘汰最旧非活动局；旧版本历史数据不会自动迁移清理。

[公开验证报告与SHA-256](../docs/reports/mobile/APK_0.2.1_RELEASE.md)。本次正式包经过构建/lint、签名与安装验证、Android生产识别保存帧/截图收尾回放；实机对局结论分别来自同维护线code106十局及code107一局，不宣称0.2.1重新跑过十局。实体手机、脱离主机和完整断线重连仍待验收。

旧版0.2.0 zip/清单位于[历史Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.0)，仍保留。
