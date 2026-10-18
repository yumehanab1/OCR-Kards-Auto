# KARDS Android 0.2.3 / code148

这是手机版独立源码快照。Java 管理界面、无障碍截图、前台身份、取消、预算及真实触控回执；内置 Python/OpenCV 模块负责画面识别、动作选择和动作后验。OCR 模型、运行库、模板及内置引擎随 APK 提供，使用 APK 无需 PC、ADB、Termux 或另装 Python。

Android 11/API30 起可安装，包含 arm64-v8a 和 x86_64。Android 14/API34 及以上使用游戏窗口截图；更早系统可在系统截图黑屏时手动启用兼容截图，并亲自在系统弹窗授权屏幕共享。进程重启或授权被撤销后需要重新授权。部分 MuMu 环境还需处理虚拟屏旋转，不能由现有测试推断所有设备均无需调整。

截图不完整、黑帧及临时窗口错误共用最多三次新鲜重采，含首次最多四次采集。重采期间不触控，取消及原预算优先；持续异常仍停止。透明帧不会变成有效帧。坏帧 PNG 的有界异步诊断仅在 debug 包开启，正式包关闭该诊断。

完整安装说明和验证范围见[手机版文档](../../README.md)及[0.2.3 发布报告](../../../docs/reports/mobile/APK_0.2.3_RELEASE.md)。连续十局记录属于 code147 开发包，与新构建的 code148 正式包分开记录；触控完成不等于每项游戏效果均已确认。

## 构建

需要 JDK17、Android SDK35、Gradle8.7 与 CPython3.10。通过本机 `local.properties` 或 `ANDROID_HOME` 指定 SDK；不要提交本机环境路径。

```powershell
$env:KARDS_BUILD_PYTHON = '你的Python3.10可执行文件路径'
$env:KARDS_PUBLIC_BUILD = 'true'
.\gradlew.bat assembleRelease lintRelease
```

首次构建需要联网获取运行库。未配置签名时输出 unsigned APK；发布签名使用 `KARDS_ANDROID_KEYSTORE`、`KARDS_ANDROID_KEY_ALIAS`、`KARDS_ANDROID_STORE_PASSWORD`、`KARDS_ANDROID_KEY_PASSWORD` 环境变量。不同证书不能覆盖安装官方 APK。

内置引擎有 230 文件 SHA-256 清单，构建前会校验；独立克隆可执行：

```powershell
python tools/prepare_mobile_core.py --check --packaged-only
```

Python 与 Android 测试源码保留，私有实机截图及运行日志不公开。需要回放图片的组件检查须先按 [TEST_FIXTURES.md](TEST_FIXTURES.md) 准备本地测试资产，缺图不能跳过断言或计为通过。正式 APK 排除测试 Python 及私有夹具；运行所需 OCR、引擎、模板及 atlas/mask 保留。

手机版与 PC 源码独立维护；不要从仓库根目录 PC `src/` 覆盖 APK 内置引擎。
