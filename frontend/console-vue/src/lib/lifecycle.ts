// Copyright (c) 2026 QianChang-official
//
// 宛委·枢忆 is licensed under Mulan PSL v2.
// You can use this software according to the terms of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
// http://license.coscl.org.cn/MulanPSL2
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

export const CLASS_LABEL: Record<string, string> = {
  preference: '玄珠·偏好', knowledge: '琅嬛·知识', experience: '经验',
  policy: '司契·规则', risk: '风险', skill: '技能',
  affective: '灵犀·情感', audit: '兰台·审计',
}
export function lifecycleColor(lc: string): string {
  switch (lc) {
    case 'active':
    case 'reinforced': return 'var(--jade)'
    case 'candidate': return 'var(--gamboge)'
    case 'quarantined':
    case 'rejected': return 'var(--cinnabar)'
    case 'forgotten':
    case 'deprecated': return 'var(--ink-soft)'
    case 'conflicted': return 'var(--mineral)'
    default: return 'var(--ink-soft)'
  }
}
export function policyColor(p: string): string {
  switch (p) {
    case 'allow': return 'var(--jade)'
    case 'require_confirmation': return 'var(--gamboge)'
    case 'redact': return 'var(--mineral)'
    case 'quarantine':
    case 'reject': return 'var(--cinnabar)'
    default: return 'var(--ink-soft)'
  }
}
