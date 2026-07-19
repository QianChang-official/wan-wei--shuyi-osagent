/**
 * 万枢协作平台共享枚举与状态映射（单一事实源，09-#11/#12）。
 *
 * 工作档位与 backend/app/platform_api/deps.py 的三档枚举对齐；
 * 运行状态映射覆盖后端状态机（agents.py）及前端常见同义词。
 * 各视图统一从这里取标签/色调/分组，避免跨视图各自漂移。
 */

/** GfTag 支持的色调（与 components/gf/GfTag.vue 的 tone prop 一致） */
export type TagTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'

/* ── 工作档位 ── */
export type WorkGear = 'human_review' | 'sandbox' | 'device'

export const GEARS: readonly WorkGear[] = ['human_review', 'sandbox', 'device']

export const GEAR_LABELS: Record<WorkGear, string> = {
  human_review: '人工审查',
  sandbox: '沙盒工作',
  device: '整台设备',
}

/**
 * 档位色调约定（全站唯一口径，按风险语义取色）：
 *   人工审查 → gold（鎏金：需人工关注）
 *   沙盒工作 → bamboo（竹青：隔离、风险收敛）
 *   整台设备 → rouge（朱砂：权限最高、风险最大）
 */
export const GEAR_TONES: Record<WorkGear, TagTone> = {
  human_review: 'gold',
  sandbox: 'bamboo',
  device: 'rouge',
}

/* ── 运行状态 ── */

/** 运行状态视觉分组：run=进行中 / review=待审查 / ok=成功 / bad=失败取消 / idle=其他 */
export type RunStatusGroup = 'run' | 'review' | 'ok' | 'bad' | 'idle'

const RUN_STATUS_META: Record<string, { label: string; group: RunStatusGroup; tone: TagTone }> = {
  queued: { label: '排队中', group: 'run', tone: 'ink' },
  pending: { label: '等待中', group: 'run', tone: 'ink' },
  running: { label: '运行中', group: 'run', tone: 'dai' },
  awaiting_review: { label: '待审查', group: 'review', tone: 'gold' },
  review: { label: '待审查', group: 'review', tone: 'gold' },
  completed: { label: '已完成', group: 'ok', tone: 'bamboo' },
  done: { label: '已完成', group: 'ok', tone: 'bamboo' },
  succeeded: { label: '已成功', group: 'ok', tone: 'bamboo' },
  success: { label: '已成功', group: 'ok', tone: 'bamboo' },
  failed: { label: '已失败', group: 'bad', tone: 'rouge' },
  error: { label: '已出错', group: 'bad', tone: 'rouge' },
  rejected: { label: '已驳回', group: 'bad', tone: 'rouge' },
  cancelled: { label: '已取消', group: 'bad', tone: 'ink' },
  canceled: { label: '已取消', group: 'bad', tone: 'ink' },
  paused: { label: '已暂停', group: 'idle', tone: 'ink' },
}

/** 状态 → 中文标签；未知状态原样透出，空值/unknown 显示「未知」 */
export function runStatusLabel(status: string): string {
  const meta = RUN_STATUS_META[status]
  if (meta) return meta.label
  return status && status !== 'unknown' ? status : '未知'
}

/** 状态 → 视觉分组（供徽标底色/数据属性使用） */
export function runStatusGroup(status: string): RunStatusGroup {
  return RUN_STATUS_META[status]?.group ?? 'idle'
}

/** 状态 → GfTag 色调 */
export function runStatusTone(status: string): TagTone {
  return RUN_STATUS_META[status]?.tone ?? 'ink'
}
