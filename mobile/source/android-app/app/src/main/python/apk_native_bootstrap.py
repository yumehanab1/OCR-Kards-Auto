"""Make the separately verified embedded core available before native imports."""
import sys
from pathlib import Path

def special_skins_replay(directory,core,menu,opening):
    path=str(Path(core)/'src')
    if path not in sys.path:sys.path.insert(0,path)
    from apk_native.special_skins_replay import run
    return run(directory,core,menu,opening)

def saved_pipeline(directory,core,menu,opening,engine,characters_json):
    path=str(Path(core)/'src')
    if path not in sys.path:sys.path.insert(0,path)
    from apk_native.saved_pipeline import run
    return run(directory,core,menu,opening,engine,characters_json)

def live_observe(bridge,core,menu,opening,evidence):
    path=str(Path(core)/'src')
    if path not in sys.path:sys.path.insert(0,path)
    from apk_native.live_observer import run
    return run(bridge,core,menu,opening,evidence)

def run_battle(bridge,core,menu,opening,evidence,options_json='{}'):
    path=str(Path(core)/'src')
    if path not in sys.path:sys.path.insert(0,path)
    from apk_native.runtime import run
    return run(bridge,core,menu,opening,evidence,options_json)
