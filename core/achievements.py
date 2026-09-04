# -*- coding: utf-8 -*-
"""成就徽章系统（Achievements）：按用户档案完整度与打卡情况解锁徽章。

游戏化激励用户坚持记录饮食；徽章为纯展示，无额外持久化（数据来自现有档案与每日打卡日志）。
"""


def compute_achievements(streak=0, log_count=0, profile_loaded=False, goal=None):
    """返回徽章列表 [{emoji, name, desc, earned}]，已解锁的排在前面。

    - streak：连续打卡天数
    - log_count：累计记录天数
    - profile_loaded：是否已完善健康档案
    - goal：健康目标（无则 None）
    """
    items = [
        ("🗂️", "档案完善者", "完善身高体重等健康档案", bool(profile_loaded)),
        ("🎯", "目标践行者", "设定自己的健康目标", bool(goal)),
        ("🌱", "初来乍到", "完成第一次饮食打卡", log_count >= 1),
        ("🔥", "坚持三天", "连续打卡 3 天", streak >= 3),
        ("🏆", "一周之约", "连续打卡 7 天", streak >= 7),
        ("📊", "饮食达人", "累计记录 10 天", log_count >= 10),
        ("🌕", "满月坚持", "累计记录 30 天", log_count >= 30),
    ]
    badges = [
        {"emoji": e, "name": n, "desc": d, "earned": ok}
        for e, n, d, ok in items
    ]
    # 稳定排序：已解锁在前，未解锁在后（各自保持定义顺序）
    badges.sort(key=lambda b: not b["earned"])
    return badges
