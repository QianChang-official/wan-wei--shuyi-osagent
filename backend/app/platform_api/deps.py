# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

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
