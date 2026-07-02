<script setup lang="ts">
const PILLARS = [
  { seal:'渠', cn:'石渠校验', fn:'Input & Source Validation', desc:'入库前质量、格式、source_layer 校验，防止 HTML/JSON residue 污染记忆库。', mod:'source_layer check' },
  { seal:'契', cn:'司契护栏', fn:'Policy Gate',             desc:'敏感分级 S0-S3、投毒拦截、确认机制：allow/redact/quarantine/reject。每条记忆必经此闸。', mod:'policy_gate.py' },
  { seal:'枢', cn:'枢忆核',  fn:'MemoryCapsule Core',      desc:'MemoryCapsule 2.0 生命周期：写入、状态流转、FTS 索引，SQLite+JSON。', mod:'capsule_store.py' },
  { seal:'玄', cn:'玄珠偏好', fn:'Preference Memory',       desc:'显式/推断偏好：inferred+affects_future_behavior → require_confirmation，不得直接 active。', mod:'preference class' },
  { seal:'琅', cn:'琅嬛知识', fn:'Knowledge Memory',        desc:'事实、引用规范、证据链、冲突检测：无 provenance 不得 active，conflicted 不进高风险指挥。', mod:'knowledge class' },
  { seal:'建', cn:'建木网络', fn:'Relation Graph',           desc:'relation_edges：supports/supersedes/derived_from，跨记忆关联召回，级联遗忘路径。', mod:'relation_edges' },
  { seal:'灵', cn:'灵犀情感', fn:'Affective Modulation',    desc:'emotional_salience 只调 retention/retrieval 排序，绝不覆盖司契护栏的安全决策。', mod:'affective_metadata' },
  { seal:'忘', cn:'忘机机制', fn:'Forget & Rollback',       desc:'forgotten/quarantined/rejected 不进生成上下文；快照回滚还原 known-good state。', mod:'forget / lifecycle' },
  { seal:'台', cn:'兰台鉴证', fn:'Audit & Eval',            desc:'证据卡、审计链路、MemoryArena-Lite 多会话评测，5 cases / 16 assertions，unsafe=0。', mod:'evidence.py + reports' },
]
</script>

<template>
  <div>
    <div class="page-head"><h1>九枢架构</h1><p>九层国风记忆架构 · Nine-Pillar Memory Architecture</p></div>
    <div class="grid9">
      <div v-for="p in PILLARS" :key="p.cn" class="pillar">
        <div class="p-stamp">{{ p.seal }}</div>
        <div class="p-cn">{{ p.cn }}</div>
        <div class="p-fn">{{ p.fn }}</div>
        <p class="p-desc">{{ p.desc }}</p>
        <div class="p-mod">▸ {{ p.mod }}</div>
      </div>
    </div>
    <div class="principle">
      <h3>六条架构原则</h3>
      <ol>
        <li>Memory is a control plane. 记忆是 Agent 行为控制平面。</li>
        <li>No memory without provenance. 没有来源证明的记忆不得长期化。</li>
        <li>No personalization without governance. 没有治理的个性化就是风险。</li>
        <li>No retrieval without trust. 检索不能只看相关性，必须看可信度。</li>
        <li>No deletion without verification. 遗忘必须可验证。</li>
        <li>No humanization without boundaries. 人性化必须服从安全与显式授权。</li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 28px; }
.page-head h1 { font-size: 28px; font-weight: 700; letter-spacing: 3px; }
.page-head p { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.grid9 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.pillar { border: 1px solid var(--line); background: rgba(255,255,255,.38); padding: 18px 16px; position: relative; transition: box-shadow .18s, transform .18s; }
.pillar:hover { transform: translateY(-3px); box-shadow: 0 10px 28px rgba(28,26,23,.1); }
.p-stamp { position: absolute; top: 14px; right: 14px; width: 36px; height: 36px; border: 2px solid var(--cinnabar); border-radius: 5px; display: grid; place-items: center; font-size: 16px; font-weight: 700; color: var(--cinnabar); }
.p-cn { font-size: 18px; font-weight: 700; letter-spacing: 2px; }
.p-fn { font-size: 11.5px; color: var(--mineral); margin: 5px 0 8px; font-family: Georgia, serif; letter-spacing: 1px; }
.p-desc { font-size: 12.5px; color: var(--ink-soft); line-height: 1.65; margin-right: 42px; }
.p-mod { margin-top: 10px; font-size: 11px; color: var(--gamboge); font-family: var(--mono); }
.principle { margin-top: 32px; border: 1px solid var(--line); background: rgba(255,255,255,.38); padding: 20px 24px; border-left: 4px solid var(--cinnabar); }
.principle h3 { font-size: 16px; letter-spacing: 2px; margin-bottom: 12px; }
.principle ol { padding-left: 20px; }
.principle li { font-size: 13.5px; color: var(--ink-soft); margin-bottom: 6px; line-height: 1.6; }
.principle li::marker { color: var(--cinnabar); font-weight: 700; }
@media (max-width: 900px) { .grid9 { grid-template-columns: repeat(2,1fr); } }
</style>
