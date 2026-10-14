import cv2,numpy as np,time

class Detector:
    def __init__(self,bank,mode='filtered',refine=False):
        self.mode=mode
        self.refine=refine
        self.locations={}
        self.bank=bank
        self.scaled={}

    def match(self, gray, name):
        template = self.bank[name]
        base = gray.shape[0]/720
        best = {'score': -1., 'bounds': None, 'scale': None}
        if self.mode in ('tracked','candidates','filtered') and name in self.locations:
            prev = self.locations[name]
            x,y,w,h = prev['bounds']; pad = 48
            left,top=max(0,x-pad),max(0,y-pad)
            roi=gray[top:min(gray.shape[0],y+h+pad),left:min(gray.shape[1],x+w+pad)]
            needle=self.scaled[(name,gray.shape[0],prev['factor'])]
            response=cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED)
            _,score,_,point=cv2.minMaxLoc(response)
            if score >= (.93 if self.refine else .86):
                found={**prev,'score':float(score),'bounds':[left+point[0],top+point[1],w,h],
                       'ok':True,'search':'tracked_local'}
                self.locations[name]=found
                return found
        # Scale templates isotropically. The source image stays untouched.
        for factor in (.8,.9,1.,1.1,1.2,1.3,1.4):
            scale = base*factor
            key = (name, gray.shape[0], factor)
            if key not in self.scaled:
                h,w = template.shape[:2]
                self.scaled[key] = cv2.cvtColor(cv2.resize(template,
                    (max(8,round(w*scale)),max(8,round(h*scale)))),cv2.COLOR_BGR2GRAY)
            needle = self.scaled[key]
            if needle.shape[0] >= gray.shape[0] or needle.shape[1] >= gray.shape[1]:
                continue
            search_regions = [(0,0,gray.shape[1],gray.shape[0])]
            if self.mode in ('candidates','filtered'):
                # Text candidates are found from this frame; no fixed screen ROI.
                nh,nw = needle.shape
                search_regions=[]
                for cx,cy,cw,ch in self.text_boxes:
                    if cw > nw*2 or ch > nh*2: continue
                    if self.mode == 'filtered' and not (.3*nw <= cw <= 1.5*nw and .45*nh <= ch <= 1.4*nh):
                        continue
                    x0,y0=max(0,cx-nw),max(0,cy-nh)
                    x1,y1=min(gray.shape[1],cx+cw+nw),min(gray.shape[0],cy+ch+nh)
                    if x1-x0>=nw and y1-y0>=nh:
                        search_regions.append((x0,y0,x1,y1))
                if self.mode == 'filtered':
                    # Merge overlapping candidate search windows to avoid
                    # paying for the same image pixels dozens of times.
                    merged=[]
                    for box in search_regions:
                        x0,y0,x1,y1=box
                        for j,(a,b,c,d) in enumerate(merged):
                            if min(x1,c)>max(x0,a) and min(y1,d)>max(y0,b):
                                merged[j]=(min(x0,a),min(y0,b),max(x1,c),max(y1,d))
                                break
                        else: merged.append(box)
                    search_regions=merged
            score,point=-1.,(0,0)
            for x0,y0,x1,y1 in search_regions:
                response=cv2.matchTemplate(gray[y0:y1,x0:x1],needle,cv2.TM_CCOEFF_NORMED)
                _,local_score,_,local_point=cv2.minMaxLoc(response)
                if local_score>score:
                    score,point=local_score,(x0+local_point[0],y0+local_point[1])
            if score > best['score']:
                best = {'score': float(score), 'bounds': [*point,needle.shape[1],needle.shape[0]],
                        'scale': scale, 'factor':factor,'search':'full_screen'}
            if self.mode in ('tracked','candidates','filtered') and score >= .93:
                break
        if self.refine and .86 <= best['score'] < .93:
            # Near misses only propose a local scale search, never authorize.
            # The original source pixels and .93 confirmation threshold stay.
            x,y,w,h=best['bounds'];pad=max(12,round(gray.shape[0]*.025))
            left,top=max(0,x-pad),max(0,y-pad)
            roi=gray[top:min(gray.shape[0],y+h+pad),left:min(gray.shape[1],x+w+pad)]
            factor0=best['factor']
            for delta in (-.05,-.04,-.03,-.02,-.01,.01,.02,.03,.04,.05):
                factor=round(factor0+delta,4);scale=base*factor
                key=(name,gray.shape[0],factor)
                if key not in self.scaled:
                    th,tw=template.shape[:2]
                    self.scaled[key]=cv2.cvtColor(cv2.resize(template,
                        (max(8,round(tw*scale)),max(8,round(th*scale)))),cv2.COLOR_BGR2GRAY)
                needle=self.scaled[key]
                if needle.shape[0]>roi.shape[0] or needle.shape[1]>roi.shape[1]:continue
                _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                if score>best['score']:
                    best={'score':float(score),'bounds':[left+point[0],top+point[1],needle.shape[1],needle.shape[0]],
                          'scale':scale,'factor':factor,'search':'refined_local_scale'}
        best['ok'] = best['score'] >= .82
        if best['ok']:
            self.locations[name]=best
        return best

    def observe(self, frame,features=None):
        started = time.perf_counter()
        gray = features.get('gray') if features is not None else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = features.get('hsv') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv,(5,80,80),(35,255,255))
        contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        boxes = [list(cv2.boundingRect(c)) for c in contours
                 if cv2.boundingRect(c)[2]>=8 and cv2.boundingRect(c)[3]>=5]
        text_mask=cv2.inRange(gray,165,255)
        text_mask=cv2.morphologyEx(text_mask,cv2.MORPH_CLOSE,np.ones((3,11),np.uint8))
        text_contours,_=cv2.findContours(text_mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        self.text_boxes=[cv2.boundingRect(c) for c in text_contours
                         if cv2.boundingRect(c)[2]>=12 and cv2.boundingRect(c)[3]>=8]
        # The ready end-turn control is orange, and falls below the white
        # text threshold. It needs its own CURRENT candidate inventory.
        hsv=features.get('hsv') if features is not None else cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        orange=cv2.inRange(hsv,(5,80,80),(35,255,255))
        orange=cv2.morphologyEx(orange,cv2.MORPH_CLOSE,np.ones((3,11),np.uint8))
        contours,_=cv2.findContours(orange,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        self.text_boxes.extend(cv2.boundingRect(c) for c in contours
                               if cv2.boundingRect(c)[2]>=12 and cv2.boundingRect(c)[3]>=8)
        # Turn labels can be dim grey or have a border joined to tabletop art.
        # Inventory enclosed contours in the established control area; these
        # boxes only propose searches, never establish a state or an absence.
        h,w=gray.shape;left,top=round(.75*w),round(.45*h)
        for threshold in (80,145):
            mask=cv2.inRange(gray[top:round(.82*h),left:],threshold,255)
            mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,11),np.uint8))
            contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
            self.text_boxes.extend((left+x,top+y,bw,bh) for x,y,bw,bh in
                (cv2.boundingRect(c) for c in contours) if 12<=bw<=.4*h and 8<=bh<=.12*h)
        candidates_done = time.perf_counter()
        evidence = {}
        def check(name):
            if name not in evidence:
                evidence[name]=self.match(gray,name)
            return evidence[name]['ok']
        if self.mode == 'full':
            evidence={name:self.match(gray,name) for name in self.bank}
        else:
            # Result evidence is checked before battle: a result overlay can
            # leave an end-turn label visible underneath.
            if not (check('defeat_banner') or check('defeat_btn') or check('victory_btn')):
                if not (check('mulligan_ok_btn') or check('mulligan_ok_btn_compact')):
                    if not (check('end_turn_btn') or check('end_turn_btn_white')):
                        if not (check('opponent_compact') or check('opponent_standard')):
                            for name in ('queue_cancel','home_play','home_tasks','home_play_selected',
                                         'battle_selected','training_unselected','detail_start'):
                                check(name)
        semantic_done = time.perf_counter()
        good = lambda n: evidence.get(n,{}).get('ok',False)
        state,action,target = 'unknown',None,None
        # All states are inferred from image evidence, never filename/index.
        if good('defeat_banner') or good('defeat_btn'):
            state = 'result_defeat'
        elif good('victory_btn'):
            state = 'result_victory'
        elif good('mulligan_ok_btn') or good('mulligan_ok_btn_compact'):
            state,action,target = 'mulligan','confirm_mulligan',('mulligan_ok_btn' if good('mulligan_ok_btn') else 'mulligan_ok_btn_compact')
        elif good('queue_cancel'):
            state = 'queueing'
        elif good('detail_start') and good('battle_selected'):
            state = 'deck_detail'
        elif good('home_play_selected') and good('battle_selected') and good('training_unselected'):
            state = 'deck_menu'
        elif good('home_play') and good('home_tasks'):
            state,action,target = 'home','open_start','home_play'
        elif good('end_turn_btn') or good('end_turn_btn_white'):
            state = 'battle'
        elif good('opponent_compact') or good('opponent_standard'):
            state = 'opponent_turn'
        plan = {'action':action, 'point':None,'dispatch':'offline_only'}
        if target:
            x,y,w,h = evidence[target]['bounds']
            plan['point'] = [x+w/2,y+h/2]
        finished = time.perf_counter()
        return {'state':state,'evidence':evidence,'orange_candidates_source':boxes,
                'plan':plan, 'timings_ms':{'candidates':1000*(candidates_done-started),
                'semantic':1000*(semantic_done-candidates_done),
                'decision':1000*(finished-semantic_done), 'vision_total':1000*(finished-started)},
                'unimplemented':['unit_type','frontline_ownership','deploy_attack_strategy',
                                 'action_postcondition','touch_receipt']}
