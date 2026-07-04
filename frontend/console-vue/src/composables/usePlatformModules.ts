import { computed, onMounted, shallowRef } from 'vue'
import { api, type PlatformModule } from '@/api/client'

export function usePlatformModules() {
  const modules = shallowRef<PlatformModule[]>([])
  const loading = shallowRef(true)
  const error = shallowRef('')

  const statusCounts = computed(() => {
    const counts = { done: 0, partial: 0, planned: 0 }
    for (const item of modules.value) counts[item.status] += 1
    return counts
  })

  const byPillar = computed(() => {
    const groups: Record<string, PlatformModule[]> = {}
    for (const item of modules.value) {
      if (!groups[item.pillar]) groups[item.pillar] = []
      groups[item.pillar].push(item)
    }
    return groups
  })

  async function load() {
    loading.value = true
    error.value = ''
    try {
      const res = await api.platformModules()
      modules.value = res.items
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  onMounted(load)

  return { modules, loading, error, statusCounts, byPillar, load }
}
