"""platform_api 共享枚举常量，供各子模块复用，避免多头定义漂移。"""

# 思考深度档位（由浅到深）
THINK_DEPTHS = ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode']

THINK_DEPTH_LABELS = {
    'low': '浅思',
    'medium': '常思',
    'high': '深思',
    'xhigh': '极思',
    'max': '穷思',
    'ultracode': '超码',
}

# 工作档位：智能体被允许触达的执行面
WORK_GEARS = {
    'human_review': '人工审查',
    'sandbox': '沙盒工作',
    'device': '整台设备',
}
