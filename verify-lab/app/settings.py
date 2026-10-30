"""积分配置 —— 被数据层和业务层共用

单独成一个模块，避免 db.py / base.py 互相 import 造成循环依赖。
"""

VERIFY_COST = 1        # 一次认证消耗
CHECKIN_REWARD = 1     # 每日签到奖励
INVITE_REWARD = 2      # 邀请奖励
REGISTER_REWARD = 1    # 注册赠送
