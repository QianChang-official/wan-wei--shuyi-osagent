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

def render_report(results):
    keys=list(next(iter(results.values())).keys()); lines=["# EGPM Benchmark Report","","| Method | "+" | ".join(keys)+" |","|---|"+"---|"*len(keys)]
    lines.insert(1, "Usage: `PYTHONPATH=. python scripts/bench_egpm.py` (CI entry point).")
    for method, vals in results.items():
        rendered = " | ".join(["未验证（组件未实现）"] * len(keys)) if vals is None else " | ".join(f"{vals[k]:.4f}" for k in keys)
        lines.append("| "+method+" | "+rendered+" |")
    lines += ["","## 结论","基于真实运行结果生成；Emotion、Persona、Safety Consistency 组件未实现（超出本次范围），相关指标标记为未验证。"]
    return "\n".join(lines)+"\n"
