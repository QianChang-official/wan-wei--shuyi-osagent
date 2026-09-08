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

import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'

export function useHealth(pollMs = 8000) {
  const online = ref(false)
  const version = ref('')
  const name = ref('')
  let timer: number | undefined

  async function check() {
    try {
      const h = await api.health()
      online.value = h.status === 'ok'
      version.value = h.version
      name.value = h.name
    } catch {
      online.value = false
    }
  }

  onMounted(() => { check(); timer = window.setInterval(check, pollMs) })
  onUnmounted(() => { if (timer) window.clearInterval(timer) })
  return { online, version, name, check }
}
