# M0:环境、截图和标定工具

M0 这一步做的是地基。让脚本能找到 KARDS 的窗口、把它固定成 1280x720、稳定地截到图,
顺便做一个手动划 ROI 的小工具。

代码都在 src\ 下面,Python 3.14,独立 venv 在 .venv。

## 做完了什么

win.py 管窗口:枚举、置前、强制客户区尺寸,还有截图。截图有两条通道,先试
PrintWindow,发现抓到空图就回退到 mss 直接抓屏幕矩形。

capture.py 是个命令行工具。list 列窗口,snap 截图,支持 --client WxH 和 --pos x,y。

calibrate.py 是交互式标定:在图上拖框画区域,n 和 b 切换名字,d 删掉,s 存成 JSON。

selfcheck.py 是个冒烟自检,把枚举、截屏、窗口截图各跑一遍。

snap-kards.cmd 一键把游戏窗口固定成 1280x720 然后截图到 shots\kards_720p.png。
calibrate.cmd 一键在截图上标 ROI,存到 config\roi.json。

## 实测踩到的三个坑

第一个,窗口截图对 GPU 渲染的窗口不管用。PrintWindow 抓 MuMu 返回全黑,
平均值 0.0。加了 mss 回退之后重测正常。KARDS 也是 GPU 渲染的,所以 mss 才是主力
通道——前提是游戏窗口可见、不被完全遮挡,挂机场景天然满足。

第二个,系统缩放到 125% 或 150% 的时候截图会少半圈。因为进程如果没声明 DPI 感知,
SetWindowPos(1280x720) 是按逻辑像素设的,物理窗口变成 1600x900,而截图还是只裁
1280x720,右下角就缺一块。修法是 win.py 里加了 set_dpi_aware(),在所有 CLI 入口
自动声明 per-monitor DPI aware,窗口尺寸和截图统一走物理像素。修完 client rect 精确
1280x720,截图 96.5% 非黑。

第三个,PrintWindow 有时返回全白。同一次会话可能给全黑,重启电脑之后又可能给全白,
标准差是 0。所以回退条件不能只判黑,得判"有没有有效内容"——纯黑、纯白、任何平坦色
都算无效。win.py 里的 _is_blank() 就是这么写的。

## 一个要记住的坑:别用窗口标题找游戏

KARDS 的窗口标题是 kards,而这个项目的文件夹叫 kards-auto。用标题做子串匹配的话,
资源管理器的文件夹窗口会先被命中,结果就是窗口被拖走、截图只拍到文件夹。

所以 capture.py snap 默认用 --proc kards,按进程的 exe 名匹配,文件夹永远不会被误伤。
手动跑的时候照这个来:

    .venv\Scripts\python.exe src\capture.py snap --proc kards --client 1280x720 --out shots\kards_720p.png

实测确认:KARDS 的进程名是 kards-Win64-Shipping.exe,窗口标题是 kards。

## 怎么用

先确认窗口和进程名:

    .venv\Scripts\python.exe src\diagnose.py

然后一键固定尺寸加截图:

    snap-kards.cmd

再标定关键区域:

    calibrate.cmd

最后检查 config\roi.json 对不对。

calibrate.py 的按键:鼠标左键拖框画一个矩形,n 和 b 切换下一个或上一个 ROI 名字,
d 删掉当前 ROI 最后一个矩形,s 保存退出,q 或 Esc 不保存退出。

默认标五个区域,够 M1 起步用:hand_area 手牌区、end_turn_btn 结束回合、
kredits_roi 行动点读数、play_btn 开始匹配、surrender_btn 投降。想加更多(比如每张
手牌的槽位、总部血量)就在 --names 里加。

## 技术备注

截图坐标一律基于 1280x720 的客户区。ROI JSON 里带着 image_size,换分辨率能检测到
不匹配,不过这一步还没实现,留到 M1。

全黑自动回退的阈值是 _is_black,平均小于 8。PrintWindow 用的是 PW_CLIENTONLY,
mss 回退靠 ClientToScreen(0,0) 定位客户区原点。
