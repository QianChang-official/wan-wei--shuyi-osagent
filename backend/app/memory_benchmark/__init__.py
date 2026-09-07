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

"""EGPM 偏好记忆评测基准。指标均基于逐事件预测与场景真值计算。"""

from .dataset import DatasetLoader, generate_dataset
from .metrics import compute_metrics
from .runner import BenchmarkRunner

__all__ = ["DatasetLoader", "generate_dataset", "compute_metrics", "BenchmarkRunner"]
