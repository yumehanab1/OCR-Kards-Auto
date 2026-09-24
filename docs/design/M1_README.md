# M1:认出自己在哪个界面

M1 要解决的问题只有一个——脚本怎么知道"我现在在哪个界面"。
是主菜单,还是排队中,还是对局里,还是结算页。

做法是 UI 模板匹配。也就是说,你得先亲手告诉它:每个界面的特征按钮长什么样。

## 整个流程

你在游戏里切到某个界面,跑 template_capture.py,它抓到当前画面,
你用鼠标框住一个有代表性的按钮,按下对应的数字键,它就记下来了。

采完所有界面按 q 结束,然后去编辑 config\states.json,定义"哪个模板代表哪个状态",
最后跑 ui_state.py 看它分类得对不对。

## 第一步,采集模板

    .venv\Scripts\python.exe src\template_capture.py

会弹出 KARDS 当前的画面。全程在这个图像窗口里操作,不用切回终端打字。

鼠标左键拖框选中一个 UI 元素,然后按数字键 1 到 9,就用底部提示条上对应的名字
把当前框选存下来。

切了游戏界面之后,回这个窗口按 c 重新抓取。采完按 q 或 Esc 结束。

窗口底部会显示键位对应关系,大概是 1:play_btn | 2:queue_cancel | 3:end_turn_btn 这样。

默认的九个键位是这样分的:

    1  play_btn        主菜单      进入对战的按钮
    2  queue_cancel    匹配等待中   取消匹配按钮
    3  end_turn_btn    对局中      "结束回合"按钮
    4  victory_btn     胜利结算     "继续"按钮
    5  defeat_btn      失败结算     "继续"按钮
    6  surrender_btn   对局中      投降或退出,可选
    7  hand_area       对局中      手牌区,可选,M3 才用
    8  kredits_roi     对局中      行动点读数,可选,M3 才用
    9  confirm_btn     弹窗        确认按钮,可选

想用别的名字就加 --names 参数,比如 --names a,b,c,d,e,f,g,h,i,最多九个,
键位按顺序排。

框的时候只框按钮本体的图标或文字就行,别框太大。每个模板越小、特征越独特,
匹配越准。如果某个按钮有悬停和按下两种样子,可以各采一张存成不同的名字,
比如 end_turn_btn2。

模板的位置和尺寸会自动写进 config\templates.json,坐标基于 1280x720。

## 第二步,定义状态

编辑 config\states.json,没有就新建。长这样:

    {
      "states": {
        "main_menu":  { "any_of": ["play_btn"] },
        "queueing":   { "any_of": ["queue_cancel"] },
        "in_game":    { "any_of": ["end_turn_btn"] },
        "victory":    { "any_of": ["victory_btn"] },
        "defeat":     { "any_of": ["defeat_btn"] }
      }
    }

规则很简单:any_of 里只要有一个模板匹配上了,就算这个状态。按顺序取第一个命中的。

顺序是有意义的,后面会说到。

## 第三步,验证

分类当前实时窗口:

    .venv\Scripts\python.exe src\ui_state.py

或者拿一张已有的截图来分类,顺便把匹配框画出来:

    .venv\Scripts\python.exe src\ui_state.py --image shots\kards_dpi_fixed.png --show

会打印出状态和匹配分数,类似 state: main_menu,匹配 play_btn 得了 0.931。

匹配阈值默认 0.82。误报了调高,比如 0.9;漏报了调低,比如 0.7。
用 --threshold 0.88 这样指定。

## 状态机

先跑通最小的一条链就够了:

    主菜单 -> 排队中 -> 对局中 -> 胜利或失败 -> 回主菜单

M1 只做"能正确回答当前状态"这一件事。对局里出牌、拖牌、手牌识别是后面 M3 和 M4 的活。

## 常见问题

模板匹配不上,无非三个原因:框太大或太小、按钮有动态效果(发光、动画)、阈值太高。
对策是重新框小一点,多采几张变体,或者先把 --threshold 降到 0.7 试试,再一点点调高。

两个状态都匹配上了,是因为 states.json 里顺序靠前的先胜出。这时候让模板更有专属性,
比如"结束回合"按钮只在对局里出现,就把它放到对局状态下去。

截图画质有问题的话,先确认游戏是 1280x720。模板和实况尺寸一致才能匹配得准,
这个在 M0 的 DPI 修复里处理过了。
