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

from pathlib import Path
from backend.app.memory_benchmark import DatasetLoader, BenchmarkRunner
from backend.app.memory_benchmark.report import render_report

results=BenchmarkRunner(DatasetLoader.synthetic(seed=42)).run()
path=Path("reports/egpm_benchmark_report.md"); path.parent.mkdir(exist_ok=True)
path.write_text(render_report(results), encoding="utf-8")
print(path)
