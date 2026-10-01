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

import { onMounted, onUnmounted, type Ref } from 'vue'

/** Modal keyboard boundary with focus restoration. No document-global key handlers. */
export function useDialogFocus(panel: Ref<HTMLElement | null>, close: () => void) {
  let previous: HTMLElement | null = null
  const focusable = () => Array.from(panel.value?.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]',
  ) ?? []).filter(el => !el.hidden && !el.closest('[hidden]'))
  function keydown(event: KeyboardEvent) {
    if (event.key === 'Escape') { event.preventDefault(); close(); return }
    if (event.key !== 'Tab') return
    const elements = focusable()
    const first = elements[0]
    const last = elements[elements.length - 1]
    if (!first) { event.preventDefault(); panel.value?.focus(); return }
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) {
      event.preventDefault(); last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus()
    }
  }
  onMounted(() => {
    previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    ;(focusable()[0] ?? panel.value)?.focus()
    panel.value?.addEventListener('keydown', keydown)
  })
  onUnmounted(() => {
    panel.value?.removeEventListener('keydown', keydown)
    if (previous?.isConnected) previous.focus()
  })
}
