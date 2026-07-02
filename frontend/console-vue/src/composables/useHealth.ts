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
