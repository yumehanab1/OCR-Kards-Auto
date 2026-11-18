"""Real-frame recall + negative authorization regressions; no device inputs."""
import copy
from pathlib import Path
import cv2,numpy as np
from .frame_features import FrameFeatures
from .native_objects import Objects
from .native_board import board
from .native_hand import inspect,operation_components
from .native_guard import Guards
from .combat import markers,observe
from .pipeline import support,deployment
from .action_chain import select


def run(frames,bank):
    checks=[]
    def check(name,value):
        assert value,name
        checks.append(dict(name=name,passed=True))
    def read(name):
        f=cv2.imread(str(Path(frames)/name));assert f is not None
        features=FrameFeatures(f);scene=board(f,Objects(bank).inspect(f,features),features)
        return f,features,scene
    for name,expected in (('optimized-sixth-000020.png','grey'),('optimized-sixth-000035.png','orange'),('optimized-third-000035.png','orange')):
        f,features,scene=read(name);actors=markers(f,scene,features)
        check('recovered_actor_'+name,len(actors)==1 and actors[0]['state']==expected and actors[0]['type']=='infantry')
        if 'sixth' in name:check('recovered_support_vacancy_'+name,support(f,scene,features)['vacancy_candidate'])
        fight=observe(f,dict(dataset='real173',file=name,state='battle',scene=scene),features,Guards(bank))
        if expected=='orange':check('recovered_actor_has_legal_action_'+name,any(o['kind'] in ('movefront','attack_unit','attack_hq') for o in fight['options']))
        else:check('grey_actor_never_acts',not fight['options'])
        enemy=copy.deepcopy(scene)
        for card in enemy['cards']:card['side']='enemy'
        check('enemy_cards_never_our_actors_'+name,not markers(f,enemy,features))
        no_cards=copy.deepcopy(scene);no_cards['cards']=[]
        check('empty_slots_never_actors_'+name,not markers(f,no_cards,features))
        opp=observe(f,dict(dataset='real173',file=name,state='opponent_turn',scene=scene),features,Guards(bank))
        check('opponent_frame_never_action_'+name,not opp['options'])
    f,features,scene=read('optimized-sixth-000064.png');hand=inspect(f)
    recovered=next(b for b in hand if b['box'][0]==726)
    check('clipped_true_operation_digit_recovered',recovered['kind']=='unit' and recovered['orange'])
    # Current upper-right K-only orange fee plates remain blocked, not units.
    for x in (425,624,932):
        b=next(b for b in hand if b['box'][0]==x)
        check('upper_right_K_not_operation_'+str(x),b['kind']=='unknown' and b['suspected_order'])
    plan=deployment(f,'battle',scene,hand,support(f,scene,features))
    check('recovered_hand_generates_deploy',plan['action']=='deploy' and plan['grab_source']==recovered['grab_source'])
    check('opponent_deploy_refused',deployment(f,'opponent_turn',scene,hand,{'vacancy_candidate':True})['action']=='wait')
    for value in (0,35,100,220):
        check('flat_plate_no_unit_'+str(value),not operation_components(np.full((28,28,3),value,np.uint8)))
    for name in ('optimized-third-000021.png','optimized-third-000060.png','optimized-sixth-000110.png','optimized-sixth-000156.png'):
        f,features,scene=read(name)
        check('known_grey_stays_nonorange_'+name,all(a['state']!='orange' for a in markers(f,scene,features)))
    return dict(passed=True,check_count=len(checks),checks=checks,device_inputs=0)
