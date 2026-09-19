# 第三方内容与版权说明

这个项目以 GPL-3.0 发布(全文见 LICENSE)。下面把仓库里那些不属于本项目的东西
逐条说清楚,免得以后有人误会。

## 游戏素材不在授权范围内

`ui_templates\` 里那 41 张 PNG,是从《KARDS》游戏画面上裁下来的按钮和图标。
比如 `end_turn_btn.png` 就是"结束回合"那四个字那一小块,`order_icon.png` 是卡牌的
类型图标。

《KARDS》的著作权属于开发商 1939 Games。这些图的版权不归本项目,本项目也无权用
GPL 把它们再授权给任何人。

那为什么还要放进仓库?因为引擎干活的方式就是"拿这些小图去屏幕上找位置",不放进去
程序跑不起来。这跟截图讨论游戏是一个性质,属于对游戏内容的指涉性使用,目的不是
再分发游戏素材本身。

所以如果你要二次分发这个项目,这一点请自行判断在你的法域下是否可接受。另一种做法
是让使用者自己用 `dev\template_capture.py` 从自己的游戏里录一遍模板 —— 这个脚本
就是干这个的,录出来的东西存在本机,不用进仓库。

`config\` 下面那些 JSON(states、templates、card_hashes 之类)装的是尺寸、坐标、
匹配阈值这些数值,是项目自己量出来的,跟着 GPL 一起授权没问题。`assets` 里那两个
图标是项目自己画的,同样没问题。

## 用到的第三方库

依赖都由 pip 自己装(清单见 requirements.txt),仓库里不含任何第三方二进制。

引擎跑起来需要的这几个:

    mss                    截屏,MIT
    opencv-python          图像识别的地基,Apache-2.0
    numpy                  数组运算,BSD-3-Clause
    pywin32                Windows 窗口操作,PSF
    rapidocr_onnxruntime   OCR,只用在少数几个字段上,Apache-2.0
      onnxruntime          推理后端,MIT
      pyclipper / shapely  OCR 的几何后处理,MIT 和 BSD-3-Clause

界面和开发工具会用到的:

    pywebview                   面板窗口,走 WebView2,BSD-3-Clause
      pythonnet / clr_loader    pywebview 的 Windows 后端,MIT
    Pillow                      生成图标,只在 make_icon.py 里用,MIT-CMU
    requests                    检查更新,只在 vision_ask.py 里用,Apache-2.0
    pyinstaller                 打包 exe,只在开发时用,GPL-2.0 带例外条款

这些全都是自由软件许可,和 GPL-3.0 兼容,没有冲突。

关于 pyinstaller 多说一句。它本体是 GPL-2.0,但带一条明确的例外条款,允许用它打包
出来的程序按你自己的许可分发。不过这个项目本身就是 GPL-3.0,所以打包出来的 exe
自然也是 GPL-3.0,这一点没有争议。

## 关于 MAA 和 ALAS

开发过程中参考过这两个项目:

    MaaAssistantArknights    https://github.com/MaaAssistantArknights/MaaAssistantArknights
    AzurLaneAutoScript       https://github.com/LmeSzinc/AzurLaneAutoScript

借的主要是思路和经验。前者那边确认了一件事:所谓"手机端"其实是引擎跑在电脑上、
靠 ADB 去操作手机,它自己不跑在手机上,这个判断影响了后来的技术选型。后者那边借的
是面板"左边开关、中间状态、右边日志"的布局。

这两个项目都是 GPL-3.0。所以这里要说清楚:本项目没有复制它们的任何一行代码,只借
鉴了思路、界面布局,以及它们公开记录过的踩坑结论 —— 这些东西不受著作权保护。

代码注释里凡是提到它们的地方,写的都是"别照抄、为什么不能照抄"。比如 `src\gui.py`
开头那段就写着:ALAS 是 GPL-3.0,照抄源码会让本项目变成派生作品,所以只抄形。
这是刻意做的。

## 免责

这是个游戏自动化工具,靠"看屏幕 + 模拟鼠标"替你操作。

它不读游戏内存,不改游戏文件,不往进程里注入任何东西。但自动化操作本身可能违反
游戏用户协议,理论上存在账号被处罚的风险。用不用、用在哪个账号上,请自行判断。

作者不对使用本工具造成的任何后果负责,包括但不限于账号处罚和数据丢失。

## 本项目自己写的部分

`src\`、`dev\`、`docs\`、`build_gui.bat`、`calibrate.cmd`、`snap-kards.cmd`、
`make_release.py`、`.github\`、README.md、CHANGELOG.md、CONTRIBUTING.md、
LICENSE、NOTICE.md、.gitignore、requirements.txt,以及 `assets` 里的两个图标
文件,都是原创的,适用 GPL-3.0。

`card_db\kards_data.json` 是从官网接口抓下来的卡牌数据(来源与更新方式见
CONTRIBUTING.md「卡库」那一节),著作权属于 1939 Games —— 放进来是因为程序跑
起来必须读它,理由和 `ui_templates\` 那一节相同。
