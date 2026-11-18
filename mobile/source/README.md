# 手机版源码

Android **0.2.4 / versionCode 191** 的独立源码位于 [`android-app/`](android-app/)；此版本固定于 [`v0.2.4` 标签](https://github.com/yumehanab1/OCR-Kards-Auto/tree/v0.2.4/mobile/source/android-app)。仓库根目录 `src/` 是独立维护的 PC 线，本次没有 Windows 更新。

普通用户请参阅[安装说明](../README.md)，或直接下载 [APK](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.4/KARDS-AUTO-Mobile-v0.2.4.apk)。本次变更、校验值和测试范围见[版本说明](../releases/0.2.4.md)。

## 从标签构建

需要 JDK 17、Android SDK 35（build-tools 35.0.0）和 CPython 3.10。项目固定 Gradle Wrapper 8.7、Android Gradle Plugin 和 Chaquopy 依赖；首次构建需联网下载依赖。设置 `ANDROID_HOME`，或用不提交的 `android-app/local.properties` 指定 SDK。

```powershell
cd android-app
$env:KARDS_BUILD_PYTHON = '你的 Python 3.10 可执行文件路径'
$env:KARDS_PUBLIC_BUILD = 'true'
.\gradlew.bat assembleRelease lintRelease
python tools/prepare_mobile_core.py --check --packaged-only
```

未配置签名时生成 `app/build/outputs/apk/release/app-release-unsigned.apk`。签名环境变量为 `KARDS_ANDROID_KEYSTORE`、`KARDS_ANDROID_KEY_ALIAS`、`KARDS_ANDROID_STORE_PASSWORD` 和 `KARDS_ANDROID_KEY_PASSWORD`；不要提交密钥、密码或本机配置。不同证书的自编译 APK 不能覆盖官方安装。

独立构建校验内置引擎 230 文件清单，不需要、也不要从 PC 源码覆写。公开源码保留 Wrapper、Java/Python 源码、依赖清单、运行 OCR 模型/字典和必要的裁剪模板；排除原始实机截图、回放素材、日志、宿主配置和构建输出。正式 APK 不含调试入口、Python 测试或测试夹具。要运行完整回放测试，请按 [素材说明](android-app/TEST_FIXTURES.md) 自备素材；仅构建测试 APK 不代表测试已运行。

[OCR 第三方许可与来源](android-app/app/src/main/assets/native-ocr/THIRD_PARTY_NOTICES.txt) · [Java Clipper 许可](android-app/app/src/main/java/de/lighti/clipper/license.txt) · [仓库游戏素材版权说明](../../NOTICE.md)。游戏界面裁剪模板不随项目 GPL 重新授权。

0.2.3 手机版的旧源码仍在 [8fc0b6944a27](https://github.com/yumehanab1/OCR-Kards-Auto/tree/8fc0b6944a277a72b548d87e42fbd194960c69d5/mobile/source/android-app)。
