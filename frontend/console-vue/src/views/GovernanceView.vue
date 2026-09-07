<!--
 Copyright (c) 2026 QianChang-official

 宛委·枢忆 is licensed under Mulan PSL v2.
 You can use this software according to the terms of the Mulan PSL v2.
 You may obtain a copy of Mulan PSL v2 at:
 http://license.coscl.org.cn/MulanPSL2

 THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
 EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
 MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
 See the Mulan PSL v2 for more details.
-->

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

interface LedgerItem {
  ledger_id: string
  op_type: string
  capsule_id: string
  actor: string
  before_hash?: string
  after_hash?: string
  reason: string
  risk_class: string
  created_at: string
}

interface Incident {
  incident_id: string
  mhg_level: number
  incident_type: string
  description: string
  resolved_at?: string
  created_at: string
}

const gate = ref<{ frozen: boolean; reason?: string; blocking_incidents?: any[] } | null>(null)
const incidents = ref<Incident[]>([])
const ledgerItems = ref<LedgerItem[]>([])
const health = ref<any>(null)
const trend = ref<{ days?: number; points: any[]; min_mhs?: number; max_mhs?: number; latest_mhs?: number; delta?: number; note?: string } | null>(null)
const loading = ref(false)
const err = ref('')
const downloading = ref('')

const deleteRecords = computed(() =>
  ledgerItems.value.filter((r) => r.op_type === 'delete')
)

// MHS 趋势曲线：把 points 映射为 SVG polyline 坐标
const trendLine = computed(() => {
  const pts = (trend.value?.points || []).filter((p) => p.mhs != null)
  if (pts.length < 2) return ''
  const W = 560
  const H = 120
  const PAD = 8
  const values = pts.map((p) => Number(p.mhs))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = (W - PAD * 2) / (pts.length - 1)
  return pts
    .map((p, i) => {
      const x = PAD + i * step
      const y = PAD + (1 - (Number(p.mhs) - min) / span) * (H - PAD * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

async function load() {
  loading.value = true
  err.value = ''
  try {
    const [gateRes, incRes, healthRes, trendRes] = await Promise.all([
      api.governanceReleaseGate(),
      api.governanceIncidents(20, true),
      api.memoryHealth(),
      api.memoryHealthTrend().catch(() => null),
    ])
    gate.value = gateRes
    incidents.value = incRes.items || []
    health.value = healthRes
    trend.value = trendRes
    // 取最近 delete 账目（通过 ledger summary 无直接接口，用 capsule 维度查）
    // 简化：从 health 或 incidents 里提取 capsule_id，再查 ledger
    // 这里用 incidents 里的 capsule_id 作为入口
    const capsuleIds = (incRes.items || [])
      .map((i: any) => i.capsule_id)
      .filter(Boolean)
    const ledgerPromises = capsuleIds.map((id: string) =>
      api.memoryLedger(id, 5).catch(() => ({ items: [] }))
    )
    const ledgerResults = await Promise.all(ledgerPromises)
    ledgerItems.value = ledgerResults.flatMap((r) => r.items || [])
  } catch (e: any) {
    err.value = String(e)
  } finally {
    loading.value = false
  }
}

async function downloadCertificate(capsuleId: string) {
  downloading.value = capsuleId
  try {
    const blobUrl = await api.governanceVerifyDeletionCertificate(capsuleId)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = `deletion-certificate-${capsuleId}.pdf`
    a.click()
    URL.revokeObjectURL(blobUrl)
  } catch (e: any) {
    err.value = String(e)
  } finally {
    downloading.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="hero-wrap">
      <PageHero
        seal="治"
        title="记忆治理"
        en="Memory Governance"
        sub="可追溯 · 可治理 · 可删除 · 可审计"
      />
      <GfButton class="hero-act" variant="ghost" small @click="load">刷新</GfButton>
    </div>

    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="loading" class="loading">研墨中…</div>

    <!-- 发布冻结状态 -->
    <section v-if="gate" class="panel" :class="{ frozen: gate.frozen }">
      <h3>发布闸门</h3>
      <div class="gate-status">
        <span class="dot" :class="{ red: gate.frozen, green: !gate.frozen }"></span>
        <span v-if="gate.frozen">已冻结 — {{ gate.reason }}</span>
        <span v-else>正常放行</span>
      </div>
      <div v-if="gate.blocking_incidents?.length" class="blocking">
        <div v-for="inc in gate.blocking_incidents" :key="inc.incident_id" class="incident-row">
          MHG-{{ inc.mhg_level }} {{ inc.incident_type }}：{{ inc.description || '无描述' }}
        </div>
      </div>
    </section>

    <!-- 未解决事故 -->
    <section v-if="incidents.length" class="panel">
      <h3>未解决事故（{{ incidents.length }}）</h3>
      <div v-for="inc in incidents" :key="inc.incident_id" class="incident-card">
        <div class="incident-head">
          <span class="mhg-badge" :class="`mhg-${inc.mhg_level}`">MHG-{{ inc.mhg_level }}</span>
          <b>{{ inc.incident_type }}</b>
          <code>{{ inc.incident_id }}</code>
        </div>
        <div class="incident-body">{{ inc.description || '无描述' }}</div>
        <div class="incident-time">{{ inc.created_at }}</div>
      </div>
    </section>

    <!-- 删除记录与证明 -->
    <section class="panel">
      <h3>删除记录与证明</h3>
      <GfEmpty v-if="!deleteRecords.length" text="暂无删除记录 — 删除一条记忆后此处将显示可下载的删除证明" />
      <div v-else class="record-list">
        <div v-for="rec in deleteRecords" :key="rec.ledger_id" class="record-card">
          <div class="record-head">
            <code>{{ rec.capsule_id }}</code>
            <span class="risk" :class="rec.risk_class">{{ rec.risk_class }}</span>
          </div>
          <div class="record-body">{{ rec.reason || '无原因记录' }}</div>
          <div class="record-foot">
            <span class="time">{{ rec.created_at }}</span>
            <GfButton
              variant="ghost"
              small
              :disabled="downloading === rec.capsule_id"
              @click="downloadCertificate(rec.capsule_id)"
            >
              {{ downloading === rec.capsule_id ? '生成中…' : '导出证明' }}
            </GfButton>
          </div>
        </div>
      </div>
    </section>

    <!-- 健康度摘要 -->
    <section v-if="health" class="panel">
      <h3>记忆健康度</h3>
      <div class="health-grid">
        <div class="health-item">
          <span class="label">MHS</span>
          <span class="value">{{ health.mhs ?? '—' }}</span>
        </div>
        <div class="health-item">
          <span class="label">总记忆</span>
          <span class="value">{{ health.metrics?.total ?? '—' }}</span>
        </div>
        <div class="health-item">
          <span class="label">过期率</span>
          <span class="value">{{ health.metrics?.stale_rate != null ? (health.metrics.stale_rate * 100).toFixed(1) + '%' : '—' }}</span>
        </div>
        <div class="health-item">
          <span class="label">冲突率</span>
          <span class="value">{{ health.metrics?.conflict_rate != null ? (health.metrics.conflict_rate * 100).toFixed(1) + '%' : '—' }}</span>
        </div>
        <div class="health-item">
          <span class="label">孤儿记忆</span>
          <span class="value" :class="{ warn: health.metrics?.orphan > 0 }">{{ health.metrics?.orphan ?? '—' }}</span>
        </div>
        <div class="health-item">
          <span class="label">重复记忆</span>
          <span class="value" :class="{ warn: health.metrics?.duplicate > 0 }">{{ health.metrics?.duplicate ?? '—' }}</span>
        </div>
        <div class="health-item">
          <span class="label">敏感覆盖</span>
          <span class="value">{{ health.metrics?.sensitive_coverage != null ? (health.metrics.sensitive_coverage * 100).toFixed(0) + '%' : '—' }}</span>
        </div>
        <div class="health-item">
          <span class="label">删除残留</span>
          <span class="value" :class="{ warn: health.metrics?.deletion_residue > 0 }">{{ health.metrics?.deletion_residue ?? '—' }}</span>
        </div>
      </div>

      <!-- MHS 趋势曲线 -->
      <div v-if="trend" class="trend-block">
        <div class="trend-head">
          <span class="label">近 {{ trend.days || 7 }} 天趋势</span>
          <span v-if="trend.delta != null" class="delta" :class="{ up: trend.delta > 0, down: trend.delta < 0 }">
            {{ trend.delta > 0 ? '+' : '' }}{{ trend.delta }}
          </span>
        </div>
        <svg v-if="trendLine" viewBox="0 0 560 120" class="trend-chart" preserveAspectRatio="none">
          <polyline :points="trendLine" fill="none" stroke="var(--accent, #4a6fa5)" stroke-width="2" />
        </svg>
        <div v-else class="trend-empty">{{ trend.note || '采样点不足（需 ≥2 个）' }}</div>
        <div v-if="trend.points?.length" class="trend-meta">
          <span>最低 {{ trend.min_mhs ?? '—' }}</span>
          <span>最高 {{ trend.max_mhs ?? '—' }}</span>
          <span>最新 {{ trend.latest_mhs ?? '—' }}</span>
          <span>共 {{ trend.points.length }} 个采样点</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.hero-wrap { position: relative; }
.hero-act { position: absolute; top: 6px; right: 0; }
.err { color: var(--red, #c0392b); margin-bottom: 12px; }
.loading { color: var(--ink-light, #666); padding: 20px; text-align: center; }

.panel {
  background: var(--card, #fff);
  border: 1px solid var(--line, #e0e0e0);
  border-radius: var(--radius, 8px);
  padding: 16px;
  margin-bottom: 16px;
}
.panel h3 {
  margin: 0 0 12px;
  font-size: 15px;
  color: var(--ink, #333);
}
.panel.frozen { border-color: var(--red, #c0392b); }

.gate-status { display: flex; align-items: center; gap: 8px; }
.dot { width: 10px; height: 10px; border-radius: 50%; }
.dot.green { background: #27ae60; }
.dot.red { background: #c0392b; }

.blocking { margin-top: 8px; padding-left: 18px; }
.incident-row { font-size: 13px; color: var(--ink-light, #666); margin-top: 4px; }

.incident-card {
  border: 1px solid var(--line, #e0e0e0);
  border-radius: var(--radius-small, 4px);
  padding: 10px;
  margin-bottom: 8px;
}
.incident-head { display: flex; align-items: center; gap: 8px; }
.mhg-badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: 600;
}
.mhg-1, .mhg-2 { background: #f39c12; color: #fff; }
.mhg-3 { background: #e67e22; color: #fff; }
.mhg-4, .mhg-5 { background: #c0392b; color: #fff; }
.incident-body { font-size: 13px; margin-top: 6px; color: var(--ink-light, #666); }
.incident-time { font-size: 12px; color: var(--ink-lighter, #999); margin-top: 4px; }

.record-list { display: flex; flex-direction: column; gap: 8px; }
.record-card {
  border: 1px solid var(--line, #e0e0e0);
  border-radius: var(--radius-small, 4px);
  padding: 10px;
}
.record-head { display: flex; align-items: center; gap: 8px; }
.record-head code { font-size: 12px; background: var(--bg, #f5f5f5); padding: 2px 6px; border-radius: 3px; }
.risk { font-size: 11px; padding: 2px 6px; border-radius: 3px; }
.risk.low { background: #27ae60; color: #fff; }
.risk.medium { background: #f39c12; color: #fff; }
.risk.high, .risk.critical { background: #c0392b; color: #fff; }
.record-body { font-size: 13px; margin-top: 6px; color: var(--ink-light, #666); }
.record-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
.time { font-size: 12px; color: var(--ink-lighter, #999); }

.health-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
@media (max-width: 720px) {
  .health-grid { grid-template-columns: repeat(2, 1fr); }
}
.health-item { display: flex; flex-direction: column; align-items: center; }
.health-item .label { font-size: 12px; color: var(--ink-lighter, #999); }
.health-item .value { font-size: 20px; font-weight: 600; color: var(--ink, #333); }
.health-item .value.warn { color: #e67e22; }

.trend-block { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line, #e0e0e0); }
.trend-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.trend-head .label { font-size: 13px; color: var(--ink-light, #666); }
.delta { font-size: 13px; font-weight: 600; }
.delta.up { color: #27ae60; }
.delta.down { color: #c0392b; }
.trend-chart { width: 100%; height: 120px; display: block; }
.trend-empty { font-size: 13px; color: var(--ink-lighter, #999); padding: 20px; text-align: center; }
.trend-meta { display: flex; gap: 16px; margin-top: 8px; font-size: 12px; color: var(--ink-lighter, #999); }
</style>
