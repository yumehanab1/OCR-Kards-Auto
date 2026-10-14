# 手机版源码

本目录包含 Android **0.2.1 / versionCode 109** 的独立源码快照。项目位于 [`android-app/`](android-app/)，包括 Java 界面与无障碍边界、Python 识别/行动模块、内置引擎、OCR模型和识别模板。PC源码在仓库根目录的`src/`，两条维护线分开。

直接安装请下载 [v0.2.1 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.1) 的 **KARDS-AUTO-Mobile-v0.2.1.apk**。[安装说明](../README.md)及[公开验证报告](../../docs/reports/mobile/APK_0.2.1_RELEASE.md)。APK不用另装Python、ADB或PC软件。

## 构建

需要JDK17、Android SDK35和CPython3.10。Gradle8.7与Chaquopy17由项目配置固定；运行库依赖首次构建需联网下载。设置`ANDROID_HOME`，或在本机创建不提交的`android-app/local.properties`指定SDK。通过`KARDS_BUILD_PYTHON`指定CPython3.10可执行文件。

```powershell
cd android-app
$env:KARDS_BUILD_PYTHON = '你的Python3.10可执行文件路径'
$env:KARDS_PUBLIC_BUILD = 'true'
.\gradlew.bat assembleRelease lintRelease
```

未配置签名时生成`app/build/outputs/apk/release/app-release-unsigned.apk`。发布签名通过本机环境变量`KARDS_ANDROID_KEYSTORE`、`KARDS_ANDROID_KEY_ALIAS`、`KARDS_ANDROID_STORE_PASSWORD`、`KARDS_ANDROID_KEY_PASSWORD`提供；私钥、密码和本机路径不入仓库。当前公开版本沿用既有APK证书，保持覆盖升级兼容；自行构建的不同证书APK不能覆盖官方包。

内置引擎自带230文件SHA-256清单。独立源码克隆构建检查这一完整载荷；原维护环境还可与其外部原始源码逐字节核对。不要从PC源码覆盖内置引擎。手动检查：

```powershell
python tools/prepare_mobile_core.py --check --packaged-only
```

私有实机截图、原始日志、回放图片和构建/运行环境没有上传。Python测试及Android测试的源代码保留，需要真实图像的回归需自行准备测试资产；没有这些资产不能将相应回放记为通过。正式构建排除测试模块和现场截图，保留运行时必需的裁剪模板和蓝图纹理atlas/mask。
