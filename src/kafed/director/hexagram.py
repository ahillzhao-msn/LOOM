"""I-Ching 64 卦 — Unicode 符號 + 中英文名 + 六爻符號。

hexagram_id: 1-64 (King Wen 序)
unicode:   U+4DC0 ~ U+4DFF
six_lines: 六爻符號串（如 ☰☰☰☰☰☰ = 乾 / ⚊⚊⚊⚊⚊⚊ = 未濟）
"""

# 六爻基礎符號
_YANG = "⚊"  # U+268A 陽爻
_YIN = "⚋"   # U+268B 陰爻

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
    6:  ("䷅", "訟", "Song / Conflict",
         "⚋⚊⚋⚊⚊⚊"),
    7:  ("䷆", "師", "Shi / The Army",
         "⚋⚊⚋⚋⚋⚋"),
    8:  ("䷇", "比", "Bi / Holding Together",
         "⚋⚋⚋⚋⚋⚊"),
    9:  ("䷈", "小畜", "Xiao Chu / Small Taming",
         "⚊⚊⚊⚋⚊⚊"),
    10: ("䷉", "履", "Lü / Treading",
         "⚊⚊⚋⚊⚊⚊"),
    11: ("䷊", "泰", "Tai / Peace",
         "⚊⚊⚊⚋⚋⚋"),
    12: ("䷋", "否", "Pi / Standstill",
         "⚋⚋⚋⚊⚊⚊"),
    13: ("䷌", "同人", "Tong Ren / Fellowship",
         "⚊⚋⚊⚊⚊⚊"),
    14: ("䷍", "大有", "Da You / Great Possession",
         "⚊⚊⚊⚊⚋⚊"),
    15: ("䷎", "謙", "Qian / Modesty",
         "⚋⚋⚊⚋⚋⚋"),
    16: ("䷏", "豫", "Yu / Enthusiasm",
         "⚋⚋⚋⚋⚊⚋"),
    17: ("䷐", "隨", "Sui / Following",
         "⚊⚋⚋⚊⚊⚋"),
    18: ("䷑", "蠱", "Gu / Decay",
         "⚋⚊⚊⚋⚋⚊"),
    19: ("䷒", "臨", "Lin / Approach",
         "⚊⚊⚋⚋⚋⚋"),
    20: ("䷓", "觀", "Guan / Contemplation",
         "⚋⚋⚋⚋⚊⚊"),
    21: ("䷔", "噬嗑", "Shi He / Biting Through",
         "⚊⚋⚋⚊⚋⚊"),
    22: ("䷕", "賁", "Bi / Grace",
         "⚊⚋⚊⚊⚋⚋"),
    23: ("䷖", "剝", "Bo / Splitting Apart",
         "⚋⚋⚋⚋⚋⚊"),
    24: ("䷗", "復", "Fu / Return",
         "⚊⚋⚋⚋⚋⚋"),
    25: ("䷘", "无妄", "Wu Wang / Innocence",
         "⚊⚋⚋⚊⚊⚊"),
    26: ("䷙", "大畜", "Da Chu / Great Taming",
         "⚊⚊⚊⚋⚋⚊"),
    27: ("䷚", "頤", "Yi / Nourishment",
         "⚊⚋⚋⚋⚋⚊"),
    28: ("䷛", "大過", "Da Guo / Great Excess",
         "⚋⚊⚊⚊⚊⚋"),
    29: ("䷜", "坎", "Kan / The Abyss",
         "⚋⚊⚋⚋⚊⚋"),
    30: ("䷝", "離", "Li / The Clinging",
         "⚊⚋⚊⚊⚋⚊"),
    31: ("䷞", "咸", "Xian / Influence",
         "⚋⚋⚊⚊⚊⚋"),
    32: ("䷟", "恆", "Heng / Duration",
         "⚋⚊⚊⚊⚊⚋"),
    33: ("䷠", "遯", "Dun / Retreat",
         "⚋⚋⚊⚊⚊⚊"),
    34: ("䷡", "大壯", "Da Zhuang / Great Power",
         "⚊⚊⚊⚊⚋⚋"),
    35: ("䷢", "晉", "Jin / Progress",
         "⚋⚋⚋⚊⚋⚊"),
    36: ("䷣", "明夷", "Ming Yi / Darkening Light",
         "⚊⚋⚊⚋⚋⚋"),
    37: ("䷤", "家人", "Jia Ren / The Family",
         "⚊⚋⚊⚊⚊⚋"),
    38: ("䷥", "睽", "Kui / Opposition",
         "⚊⚊⚋⚊⚊⚋"),
    39: ("䷦", "蹇", "Jian / Obstruction",
         "⚋⚋⚊⚋⚊⚋"),
    40: ("䷧", "解", "Jie / Deliverance",
         "⚋⚊⚋⚊⚊⚋"),
    41: ("䷨", "損", "Sun / Decrease",
         "⚊⚊⚋⚋⚋⚊"),
    42: ("䷩", "益", "Yi / Increase",
         "⚊⚋⚋⚊⚊⚊"),
    43: ("䷪", "夬", "Guai / Breakthrough",
         "⚊⚊⚊⚊⚊⚋"),
    44: ("䷫", "姤", "Gou / Coming to Meet",
         "⚋⚊⚊⚊⚊⚊"),
    45: ("䷬", "萃", "Cui / Gathering Together",
         "⚋⚋⚋⚊⚊⚋"),
    46: ("䷭", "升", "Sheng / Pushing Upward",
         "⚋⚊⚊⚋⚋⚋"),
    47: ("䷮", "困", "Kun / Oppression",
         "⚋⚊⚋⚊⚊⚋"),
    48: ("䷯", "井", "Jing / The Well",
         "⚋⚊⚊⚊⚋⚊"),
    49: ("䷰", "革", "Ge / Revolution",
         "⚊⚋⚊⚊⚊⚋"),
    50: ("䷱", "鼎", "Ding / The Cauldron",
         "⚋⚊⚊⚊⚊⚋"),
    51: ("䷲", "震", "Zhen / The Arousing",
         "⚊⚋⚋⚊⚋⚋"),
    52: ("䷳", "艮", "Gen / Keeping Still",
         "⚋⚋⚊⚊⚋⚊"),
    53: ("䷴", "漸", "Jian / Development",
         "⚋⚋⚊⚊⚊⚋"),
    54: ("䷵", "歸妹", "Gui Mei / The Marrying Maiden",
         "⚊⚊⚋⚊⚋⚋"),
    55: ("䷶", "豐", "Feng / Abundance",
         "⚊⚋⚊⚊⚋⚋"),
    56: ("䷷", "旅", "Lü / The Wanderer",
         "⚋⚋⚊⚊⚋⚊"),
    57: ("䷸", "巽", "Xun / The Gentle",
         "⚋⚊⚊⚋⚊⚊"),
    58: ("䷹", "兌", "Dui / The Joyous",
         "⚊⚊⚋⚊⚋⚊"),
    59: ("䷺", "渙", "Huan / Dispersion",
         "⚋⚊⚋⚋⚊⚊"),
    60: ("䷻", "節", "Jie / Limitation",
         "⚊⚊⚋⚋⚊⚋"),
    61: ("䷼", "中孚", "Zhong Fu / Inner Truth",
         "⚊⚊⚋⚋⚊⚊"),
    62: ("䷽", "小過", "Xiao Guo / Small Excess",
         "⚋⚋⚊⚊⚋⚋"),
    63: ("䷾", "既濟", "Ji Ji / After Completion",
         "⚊⚋⚊⚋⚊⚋"),
    64: ("䷿", "未濟", "Wei Ji / Before Completion",
         "⚋⚊⚋⚊⚋⚊"),
}


def hexagram_symbol(hexagram_id: int) -> str:
    """卦象 ID → Unicode 符號（如 ䷀）。"""
    entry = _HEXAGRAMS.get(hexagram_id)
    return entry[0] if entry else "?"


def hexagram_name(hexagram_id: int, lang: str = "zh") -> str:
    """卦象 ID → 名稱。lang: zh / en。"""
    entry = _HEXAGRAMS.get(hexagram_id)
    if not entry:
        return "?"
    return entry[1] if lang == "zh" else entry[2]


def hexagram_six_lines(hexagram_id: int) -> str:
    """卦象 ID → 六爻符號（如 ⚊⚊⚊⚊⚊⚊）。"""
    entry = _HEXAGRAMS.get(hexagram_id)
    return entry[3] if entry else "?"


def hexagram_display(hexagram_id: int, q_value: float = 0.0,
                     lang: str = "zh") -> str:
    """卦象顯示字串（含符號 + 名稱 + 可選 Q 值）。

    中文環境: ䷀ 乾卦
    英文環境: ䷀ Qian / The Creative
    卦鏈時不加 Q 值。
    """
    entry = _HEXAGRAMS.get(hexagram_id)
    if not entry:
        return f"? (id={hexagram_id})"

    symbol, name_zh, name_en, six = entry
    name = name_zh if lang == "zh" else name_en

    if q_value > 0:
        return f"{symbol} {name}  {six}"
    return f"{symbol} {name}"


def hexagram_chain(ids: list[int], lang: str = "zh") -> str:
    """卦鏈顯示：䷄ → ䷊ → ䷎ → ䷭。

    用箭頭連接多個卦象符號，顯示命名和六爻。
    """
    if not ids:
        return ""
    symbols = []
    for hid in ids:
        entry = _HEXAGRAMS.get(hid)
        if entry:
            symbols.append(f"{entry[0]}{entry[1]}")
        else:
            symbols.append(f"?({hid})")
    return " → ".join(symbols)


def hexagram_chain_compact(ids: list[int]) -> str:
    """卦鏈精簡顯示：䷄→䷊→䷎→䷭（僅符號，無名稱）。"""
    if not ids:
        return ""
    return "→".join(hexagram_symbol(hid) for hid in ids if _HEXAGRAMS.get(hid))
