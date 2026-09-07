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
/** InkDivider — 金线渐变分隔，可带居中文字 */
withDefaults(defineProps<{ label?: string }>(), { label: '' })
</script>

<template>
  <div class="gf-divider" :class="{ 'gf-divider--labeled': !!label }" role="separator">
    <template v-if="label">
      <span class="gd-line"></span>
      <span class="gd-label">{{ label }}</span>
      <span class="gd-line"></span>
    </template>
  </div>
</template>

<style scoped>
.gf-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--gold-line) 20%, var(--gold-line) 80%, transparent);
  margin: 18px 0;
}
.gf-divider--labeled {
  height: auto;
  background: none;
  display: flex;
  align-items: center;
  gap: 14px;
}
.gd-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--gold-line));
}
.gd-line:last-child {
  background: linear-gradient(90deg, var(--gold-line), transparent);
}
.gd-label {
  font-family: var(--font-kai);
  font-size: 12px;
  letter-spacing: 3px;
  color: var(--ink-muted);
  white-space: nowrap;
}
</style>
