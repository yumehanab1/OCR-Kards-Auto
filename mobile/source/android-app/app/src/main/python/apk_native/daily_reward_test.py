"""Strict daily claim phase contracts; synthetic geometry, not live OCR proof."""
import copy
import unittest
import cv2
import numpy as np
from .daily_reward import recognize,ACTIONS
from apk_match_entry import MenuFlow


def row(text,x,y,w,h):
    return dict(text=text,score=.99,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])


class DailyRewardTests(unittest.TestCase):
    def setUp(self):
        self.frame=np.zeros((720,1612,3),np.uint8)
        cv2.rectangle(self.frame,(875,413),(949,516),(240,240,240),2)
        self.rows=[row('每日登录奖励',697,111,216,36),row('奖励现可领取',751,584,111,24),row('领取',885,370,55,32)]

    def observation(self,stage):
        if stage==0:p=recognize(self.frame,self.rows)
        else:p=recognize(self.frame,[row('第7天',751,14,112,44),row('轻触领取' if stage==1 else '轻触继续',766,683,80,23)])
        self.assertIsNotNone(p)
        return dict(state=p['state'],daily_reward_evidence=p,targets={ACTIONS[p['state']]:p['target_bounds']})

    def test_card_target_is_measured_not_label(self):
        obs=self.observation(0);x,y,w,h=obs['daily_reward_evidence']['target_bounds']
        self.assertLess(abs(x-875),4);self.assertGreater(y,402);self.assertGreater(h,100)

    def test_negative_claim_semantics(self):
        for bad in (self.rows[:2],self.rows[1:],self.rows+[self.rows[2]],
                    self.rows+[row('立即购买',100,100,150,30)],self.rows+[row('开启卡包',100,100,150,30)],
                    [dict(r,score=.89) for r in self.rows]):
            self.assertIsNone(recognize(self.frame,bad))
        self.assertIsNone(recognize(np.zeros_like(self.frame),self.rows))
        bad=copy.deepcopy(self.rows);bad[0]['box'][0][0]=float('nan')
        self.assertIsNone(recognize(self.frame,bad))

    def test_full_phase_chain_and_no_repeat(self):
        f=MenuFlow('casual',0,direct_controls=True)
        for stage in range(3):
            obs=self.observation(stage);decision=f.observe(obs,stage+1,1000+stage*1000)
            self.assertEqual(ACTIONS[obs['state']],decision['action'])
            f.accepted(decision['action'],1100+stage*1000)
            self.assertIn('wait',f.observe(obs,stage+1,1200+stage*1000))
        home=dict(state='home',targets={'menu_home_start':[100,100,40,40]})
        self.assertEqual('menu_home_start',f.observe(home,4,4500)['action'])
        self.assertIn('stop',f.observe(self.observation(0),5,5000))

    def test_orphan_prompt_refused(self):
        for stage in (1,2):
            f=MenuFlow('casual',0,direct_controls=True)
            self.assertIn('stop',f.observe(self.observation(stage),1,1000))

    def test_phase_timeout_and_day_mismatch(self):
        f=MenuFlow('casual',0,direct_controls=True);o=self.observation(0)
        f.observe(o,1,100);f.accepted('menu_claim_daily',200)
        self.assertIn('stop',f.observe(o,2,16000))
        f=MenuFlow('casual',0,direct_controls=True)
        for stage in (0,1):
            o=self.observation(stage);f.observe(o,stage+1,1000);f.accepted(ACTIONS[o['state']],1100)
        o=self.observation(2);o['daily_reward_evidence']['day']=6
        self.assertIn('stop',f.observe(o,3,2000))

    def test_budget_and_wrong_prompt(self):
        f=MenuFlow('casual',0,direct_controls=True);f.inputs=f.max_inputs
        self.assertEqual('menu_input_budget',f.observe(self.observation(0),1,1000)['stop'])
        for text in ('轻触继续购买','轻触开包','轻触领取奖励'):
            self.assertIsNone(recognize(self.frame,[row('第7天',751,14,112,44),row(text,766,683,80,23)]))

    def test_ticket_silhouette_and_caption_are_both_required(self):
        frame=np.zeros((720,1440,3),np.uint8)
        cv2.fillConvexPoly(frame,np.array([[985,191],[972,197],[942,257],[991,289],[1032,220]]), (0,170,240))
        rows=[row('每日登录奖励',580,42,277,46),row('奖励现可领取',648,645,144,29),
              row('领取',954,116,70,43),row('1竞技场门票',914,316,150,30)]
        proof=recognize(frame,rows)
        self.assertIsNotNone(proof)
        self.assertTrue(proof['basis'].endswith('_ticket'))
        self.assertIsNone(recognize(frame,rows[:-1]))
        self.assertIsNone(recognize(frame,rows+[rows[2]]))
        self.assertIsNone(recognize(np.zeros_like(frame),rows))
        for text in ('立即购买','开启卡包','排竞技场'):
            bad=copy.deepcopy(rows);bad[3]['text']=text
            self.assertIsNone(recognize(frame,bad))
        bad=copy.deepcopy(rows);bad[3]['box']=[[100,316],[250,316],[250,346],[100,346]]
        self.assertIsNone(recognize(frame,bad))

    def returned(self,frame_id=3,captured=2000,state='home'):
        from .daily_reward import ticket_return_evidence
        packet=dict(frame_id=frame_id,captured_elapsed_ms=captured,foreground_generation=7,
                    source_width=2160,source_height=1080)
        obs=dict(state=state,targets={'menu_home_start':[100,100,40,40]})
        obs['daily_ticket_return']=ticket_return_evidence(obs,[],packet,captured+100,True)
        return obs

    def collected(self,ticket=True):
        f=MenuFlow('casual',0,direct_controls=True)
        for stage in (0,1):
            o=self.observation(stage)
            if stage==0 and ticket:o['daily_reward_evidence']['basis']='current_daily_title_available_unique_claim_ticket'
            f.observe(o,stage+1,1000+stage*300);f.accepted(ACTIONS[o['state']],1100+stage*300)
        return f

    def test_ticket_return_requires_two_fresh_independent_destinations(self):
        f=self.collected();o=self.returned()
        self.assertIn('wait',f.observe(o,3,2100))
        self.assertIn('wait',f.observe(o,3,2200))
        o=self.returned(4,2600)
        self.assertEqual('menu_home_start',f.observe(o,4,2700)['action'])
        self.assertTrue(f.daily_no_continue_verified)
        self.assertNotIn('menu_continue_daily',f.daily_issued)

    def test_card_cannot_use_ticket_return(self):
        f=self.collected(False)
        for i in (3,4):self.assertIn('wait',f.observe(self.returned(i,2000+i*600),i,2100+i*600))
        self.assertFalse(f.daily_no_continue_verified)
        self.assertIn('stop',f.observe(self.returned(5,17000),5,17100))

    def test_ticket_return_does_not_replace_collect_receipt(self):
        f=MenuFlow('casual',0,direct_controls=True);o=self.observation(0)
        o['daily_reward_evidence']['basis']='current_daily_title_available_unique_claim_ticket'
        f.observe(o,1,1000);f.accepted('menu_claim_daily',1100)
        for i in (3,4):self.assertIn('wait',f.observe(self.returned(i,2000+i*600),i,2100+i*600))
        self.assertFalse(f.daily_no_continue_verified)

    def test_ticket_return_rejects_bad_identity_and_interrupted_pair(self):
        for key,value in [('captured_elapsed_ms',1200),('frame_id',88),('destination','unknown')]:
            f=self.collected();o=self.returned();o['daily_ticket_return'][key]=value
            self.assertIn('wait',f.observe(o,3,2100));self.assertIsNone(f.daily_return_pair)
        f=self.collected();f.observe(self.returned(),3,2100)
        f.observe(dict(state='unknown',targets={}),4,2300)
        self.assertIn('wait',f.observe(self.returned(5,2600),5,2700))
        self.assertFalse(f.daily_no_continue_verified)
        f=self.collected();f.observe(self.returned(),3,2100)
        o=self.returned(4,2600);o['daily_ticket_return']['foreground_generation']=8
        self.assertIn('wait',f.observe(o,4,2700));self.assertFalse(f.daily_no_continue_verified)

    def test_return_evidence_requires_current_destination_and_ocr(self):
        from .daily_reward import ticket_return_evidence
        o=self.returned();p={k:v for k,v in o['daily_ticket_return'].items() if k not in ('basis','destination')}
        for state in ('unknown','login_reward','daily_reward_continue','arena','generic_popup'):
            self.assertIsNone(ticket_return_evidence(dict(state=state),[],p,2100,True))
        self.assertIsNone(ticket_return_evidence(o,[],p,2100,False))
        self.assertIsNone(ticket_return_evidence(o,[],p,5100,True))
        for text in ('轻触继续','第4天轻触领取','1竞技场门票','立即购买','开启卡包'):
            self.assertIsNone(ticket_return_evidence(o,[dict(text=text,score=.20)],p,2100,True))



if __name__=='__main__':unittest.main()
