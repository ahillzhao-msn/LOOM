"""I-Ching 64 卦 — Unicode 符号 + 中英文名 + 六爻符号 + 卦辞 (classical judgment).

hexagram_id: 1-64 (King Wen 序)
unicode:   U+4DC0 ~ U+4DFF
six_lines: 六爻符号串
judgment:  周易卦辞（彖辞/断辞，文王系辞）
"""

# 六爻基础符号
_YANG = "⚊"  # U+268A 阳爻
_YIN = "⚋"   # U+268B 阴爻

# 64 卦 King Wen 序：hexagram_id → (unicode, name_zh, name_en, six_lines_str)
_HEXAGRAMS: dict[int, tuple[str, str, str, str]] = {
    1:  ("䷀", "乾", "Qian / The Creative",
         "⚊⚊⚊⚊⚊⚊"),
    2:  ("䷁", "坤", "Kun / The Receptive",
         "⚋⚋⚋⚋⚋⚋"),
    3:  ("䷂", "屯", "Zhun / Difficulty at the Beginning",
         "⚊⚋⚋⚋⚊⚋"),
    4:  ("䷃", "蒙", "Meng / Youthful Folly",
         "⚋⚊⚋⚋⚋⚊"),
    5:  ("䷄", "需", "Xu / Waiting",
         "⚊⚊⚊⚋⚊⚋"),
    6:  ("䷅", "讼", "Song / Conflict",
         "⚋⚊⚋⚊⚊⚊"),
    7:  ("䷆", "师", "Shi / The Army",
         "⚋⚊⚋⚋⚋⚋"),
    8:  ("䷇", "比", "Bi / Holding Together",
         "⚋⚋⚋⚋⚋⚊"),
    9:  ("䷈", "小畜", "Xiao Chu / Small Taming",
         "⚊⚊⚊⚋⚋⚊"),
    10: ("䷉", "履", "Lu / Treading",
         "⚊⚊⚋⚋⚊⚊"),
    11: ("䷊", "泰", "Tai / Peace",
         "⚊⚊⚊⚋⚋⚋"),
    12: ("䷋", "否", "Pi / Standstill",
         "⚋⚋⚋⚊⚊⚊"),
    13: ("䷌", "同人", "Tong Ren / Fellowship",
         "⚊⚊⚋⚊⚊⚊"),
    14: ("䷍", "大有", "Da You / Great Possession",
         "⚊⚊⚊⚊⚊⚋"),
    15: ("䷎", "谦", "Qian / Modesty",
         "⚋⚊⚋⚋⚋⚊"),
    16: ("䷏", "豫", "Yu / Enthusiasm",
         "⚋⚋⚋⚊⚋⚋"),
    17: ("䷐", "随", "Sui / Following",
         "⚊⚊⚋⚋⚊⚋"),
    18: ("䷑", "蛊", "Gu / Decay",
         "⚋⚊⚋⚊⚊⚋"),
    19: ("䷒", "临", "Lin / Approach",
         "⚊⚊⚋⚋⚋⚊"),
    20: ("䷓", "观", "Guan / Contemplation",
         "⚋⚋⚋⚊⚊⚋"),
    21: ("䷔", "噬嗑", "Shi He / Biting Through",
         "⚊⚊⚊⚋⚊⚊"),
    22: ("䷕", "贲", "Bi / Grace",
         "⚊⚊⚋⚊⚊⚋"),
    23: ("䷖", "剥", "Bo / Splitting Apart",
         "⚊⚋⚋⚋⚋⚋"),
    24: ("䷗", "复", "Fu / Return",
         "⚋⚋⚋⚋⚊⚋"),
    25: ("䷘", "无妄", "Wu Wang / Innocence",
         "⚊⚊⚊⚊⚋⚊"),
    26: ("䷙", "大畜", "Da Chu / Great Taming",
         "⚊⚊⚊⚋⚋⚊"),
    27: ("䷚", "颐", "Yi / Mouth Corners",
         "⚊⚋⚋⚋⚋⚊"),
    28: ("䷛", "大过", "Da Guo / Great Crossing",
         "⚋⚊⚋⚊⚊⚋"),
    29: ("䷜", "坎", "Kan / The Abyss",
         "⚋⚊⚋⚋⚊⚋"),
    30: ("䷝", "离", "Li / Clarity",
         "⚊⚊⚋⚊⚊⚊"),
    31: ("䷞", "咸", "Xian / Mutual Influence",
         "⚋⚋⚋⚊⚊⚋"),
    32: ("䷟", "恒", "Heng / Duration",
         "⚋⚊⚊⚊⚊⚋"),
    33: ("䷠", "遁", "Dun / Retreat",
         "⚋⚊⚊⚊⚊⚊"),
    34: ("䷡", "大壮", "Da Zhuang / Great Power",
         "⚊⚊⚊⚊⚋⚊"),
    35: ("䷢", "晋", "Jin / Progress",
         "⚋⚋⚋⚊⚊⚊"),
    36: ("䷣", "明夷", "Ming Yi / Darkening of the Light",
         "⚊⚊⚊⚊⚋⚋"),
    37: ("䷤", "家人", "Jia Ren / Family",
         "⚊⚊⚋⚋⚊⚊"),
    38: ("䷥", "睽", "Kui / Opposition",
         "⚊⚊⚋⚊⚊⚊"),
    39: ("䷦", "蹇", "Jian / Obstruction",
         "⚋⚋⚊⚋⚊⚊"),
    40: ("䷧", "解", "Xie / Release",
         "⚋⚊⚋⚊⚊⚋"),
    41: ("䷨", "损", "Sun / Decrease",
         "⚊⚊⚋⚋⚋⚊"),
    42: ("䷩", "益", "Yi / Increase",
         "⚊⚊⚊⚊⚋⚊"),
    43: ("䷪", "夬", "Guai / Breakthrough",
         "⚊⚊⚊⚊⚊⚋"),
    44: ("䷫", "姤", "Gou / Meeting",
         "⚋⚊⚊⚊⚊⚊"),
    45: ("䷬", "萃", "Cui / Gathering Together",
         "⚋⚋⚋⚊⚊⚋"),
    46: ("䷭", "升", "Sheng / Pushing Upward",
         "⚋⚋⚊⚊⚊⚋"),
    47: ("䷮", "困", "Kun / Difficulty",
         "⚋⚊⚋⚊⚊⚊"),
    48: ("䷯", "井", "Jing / The Well",
         "⚋⚊⚊⚊⚊⚊"),
    49: ("䷰", "革", "Ge / Revolution",
         "⚊⚊⚋⚊⚊⚋"),
    50: ("䷱", "鼎", "Ding / The Cauldron",
         "⚋⚋⚊⚊⚊⚊"),
    51: ("䷲", "震", "Zhen / Arousing",
         "⚊⚊⚋⚊⚊⚋"),
    52: ("䷳", "艮", "Gen / Keeping Still",
         "⚊⚊⚋⚋⚋⚊"),
    53: ("䷴", "渐", "Jian / Development",
         "⚋⚊⚋⚊⚋⚊"),
    54: ("䷵", "归妹", "Gui Mei / Returning Maiden",
         "⚊⚊⚋⚋⚊⚋"),
    55: ("䷶", "丰", "Feng / Abundance",
         "⚊⚊⚋⚊⚊⚋"),
    56: ("䷷", "旅", "Lu / Traveling",
         "⚋⚋⚊⚊⚊⚊"),
    57: ("䷸", "巽", "Xun / Gentle Penetration",
         "⚋⚋⚊⚊⚊⚊"),
    58: ("䷹", "兑", "Dui / Joy",
         "⚊⚊⚊⚋⚊⚊"),
    59: ("䷺", "涣", "Huan / Dispersion",
         "⚋⚋⚊⚊⚊⚋"),
    60: ("䷻", "节", "Jie / Limitation",
         "⚊⚊⚊⚊⚋⚋"),
    61: ("䷼", "中孚", "Zhong Fu / Inner Truth",
         "⚊⚊⚋⚋⚊⚊"),
    62: ("䷽", "小过", "Xiao Guo / Small Exceeding",
         "⚋⚋⚊⚊⚋⚋"),
    63: ("䷾", "既济", "Ji Ji / After Completion",
         "⚊⚊⚊⚊⚊⚊"),
    64: ("䷿", "未济", "Wei Ji / Before Completion",
         "⚋⚊⚊⚊⚊⚋"),
}

# 卦辞 (classical judgments from Zhouyi, King Wen tradition)
# hexagram_id → judgment_zh
_JUDGMENTS: dict[int, str] = {
    1:  "元亨利贞",
    2:  "元亨，利牝马之贞",
    3:  "元亨利贞，勿用有攸往",
    4:  "亨。匪我求童蒙，童蒙求我",
    5:  "有孚，光亨，贞吉",
    6:  "有孚窒惕，中吉，终凶",
    7:  "贞，丈人吉，无咎",
    8:  "吉。原筮元永贞，无咎",
    9:  "亨。密云不雨，自我西郊",
    10: "履虎尾，不咥人，亨",
    11: "小往大来，吉亨",
    12: "否之匪人，不利君子贞",
    13: "同人于野，亨",
    14: "元亨",
    15: "亨，君子有终",
    16: "利建侯行师",
    17: "元亨利贞，无咎",
    18: "元亨，利涉大川",
    19: "元亨利贞",
    20: "盥而不荐，有孚颙若",
    21: "亨，利用狱",
    22: "亨。小利有攸往",
    23: "不利有攸往",
    24: "亨。出入无疾",
    25: "元亨利贞。其匪正有眚",
    26: "利贞",
    27: "贞吉。观颐，自求口实",
    28: "栋桡，利有攸往，亨",
    29: "有孚维心亨，行有尚",
    30: "利贞，亨",
    31: "亨，利贞",
    32: "亨，无咎",
    33: "亨，小利贞",
    34: "利贞",
    35: "康侯用锡马蕃庶，昼日三接",
    36: "利艰贞",
    37: "利女贞",
    38: "小事吉",
    39: "利西南，不利东北",
    40: "利西南",
    41: "有孚，元吉，无咎",
    42: "利有攸往，利涉大川",
    43: "扬于王庭，孚号有厉",
    44: "女壮，勿用取女",
    45: "亨。王假有庙",
    46: "元亨",
    47: "亨，贞，大人吉",
    48: "改邑不改井，无丧无得",
    49: "已日乃孚，元亨利贞",
    50: "元吉，亨",
    51: "亨。震来虩虩",
    52: "艮其背，不获其身",
    53: "女归吉，利贞",
    54: "征凶，无攸利",
    55: "亨，王假之",
    56: "小亨，旅贞吉",
    57: "小亨，利有攸往",
    58: "亨，利贞",
    59: "亨。王假有庙",
    60: "亨，苦节不可贞",
    61: "豚鱼吉，利涉大川",
    62: "亨，利贞",
    63: "亨小，利贞",
    64: "亨。小狐汔济，濡其尾",
}


# ── 查询函数 ──


def hexagram_symbol(hid: int) -> str:
    """返回卦符 Unicode 字符。"""
    entry = _HEXAGRAMS.get(hid)
    return entry[0] if entry else "?"


def hexagram_display(hid: int) -> str:
    """返回卦名（中文）。"""
    entry = _HEXAGRAMS.get(hid)
    return entry[1] if entry else "?"


def hexagram_english(hid: int) -> str:
    """返回卦名（英文）。"""
    entry = _HEXAGRAMS.get(hid)
    return entry[2] if entry else "?"


def hexagram_six_lines(hid: int) -> str:
    """返回六爻符号串。"""
    entry = _HEXAGRAMS.get(hid)
    return entry[3] if entry else ""


def hexagram_judgment(hid: int) -> str:
    """返回卦辞（周易原文）。"""
    return _JUDGMENTS.get(hid, "")


def hexagram_chain(ids: list[int]) -> str:
    """完整卦链：䷀乾→䷁坤→䷂屯（符号+名称）。"""
    parts = []
    for hid in ids:
        entry = _HEXAGRAMS.get(hid)
        if entry:
            parts.append(f"{entry[0]}{entry[1]}")
        else:
            parts.append(f"?({hid})")
    return " → ".join(parts)


def hexagram_chain_compact(ids: list[int]) -> str:
    """卦链精简显示：䷄→䷊→䷎→䷭（仅符号，无名称）。"""
    if not ids:
        return ""
    return "→".join(hexagram_symbol(hid) for hid in ids if _HEXAGRAMS.get(hid))
