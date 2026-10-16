"""Independent layout settings; source ratio selects the profile before recognition.

Shared values are explicit in both profiles. Adjusting wide-screen geometry must
not silently change the established 16:9 profile.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class LayoutProfile:
    name: str
    first_deck_width: tuple
    first_deck_height: tuple
    first_deck_top: tuple
    deck_card_aspect: tuple
    promotion_width: tuple
    promotion_height: tuple

STANDARD_16_9 = LayoutProfile('standard_16_9', (.12,.60), (.18,.75), (.03,.42),
                              (.55,.85), (.35,.55), (.30,.60))
WIDE = LayoutProfile('wide', (.12,.60), (.18,.75), (.03,.42),
                     (.55,.85), (.35,.55), (.30,.60))
OTHER = LayoutProfile('other_native', (.12,.60), (.18,.75), (.03,.42),
                      (.55,.85), (.35,.55), (.30,.60))

def for_shape(shape):
    height,width=shape[:2]
    if height<=0 or width<=0: raise ValueError('invalid_layout_shape')
    ratio=width/height
    if abs(ratio-16/9)<=.02: return STANDARD_16_9
    if ratio>16/9+.02: return WIDE
    return OTHER
