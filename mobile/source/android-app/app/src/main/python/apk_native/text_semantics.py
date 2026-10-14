import numpy as np

def classify_text(items):
    confident=[r for r in items if r['score']>=.93]
    words={r['text'].replace(' ',''):r for r in confident}
    def has(word): return word in words
    state,action,target='unknown',None,None
    result_words={r['text'].replace(' ','') for r in items if r['score']>=.98}
    if {'胜利','继续','查看战场'}<=result_words and '失败' not in result_words:
        state='result_victory'
    elif {'失败','继续','查看战场'}<=result_words and '胜利' not in result_words:
        state='result_defeat'
    elif has('入伍任务') or has('加倍'):
        # A task/reward overlay blocks the board. It is an observation state,
        # never an inferred dismiss target; the menu/settlement owner decides
        # whether a reviewed control is available.
        state='blocking_popup'
    elif has('敌方'):
        state='opponent_turn'
    elif has('继续') and any('等级' in text or '下一级奖励' in text for text in words):
        state,action,target='level_settlement','continue_settlement',words['继续']
    elif has('对战模式') and has('训练模式'):
        if has('开始') and has('休闲') and has('排位'):
            state='deck_detail'
        else: state='deck_menu'
    elif has('开始') and has('收藏') and has('卡包') and has('卡牌'):
        state='card_collection'
    elif has('对战') and has('先手'):
        state='match_intro'
    plan={'action':action,'point':None,'dispatch':'offline_only'}
    if target:
        points=np.asarray(target['box']);plan['point']=points.mean(axis=0).tolist()
    return state,plan
