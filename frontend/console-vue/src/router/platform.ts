import type { RouteRecordRaw } from 'vue-router'

// 万枢协作平台路由（v0.12）。各视图由后续子代理整体实现，
// 当前为最小占位文件，懒加载仅在实际访问时解析。
export const platformRoutes: RouteRecordRaw[] = [
  { path: '/platform/workbench', name: 'platformWorkbench', component: () => import('@/views/platform/WorkbenchView.vue'), meta: { title: '万枢工作台', seal: '枢' } },
  { path: '/platform/providers', name: 'platformProviders', component: () => import('@/views/platform/ProvidersView.vue'), meta: { title: '模型接入', seal: '接' } },
  { path: '/platform/agents', name: 'platformAgents', component: () => import('@/views/platform/AgentsView.vue'), meta: { title: '智能体', seal: '智' } },
  { path: '/platform/spaces', name: 'platformSpaces', component: () => import('@/views/platform/SpacesView.vue'), meta: { title: '空间', seal: '域' } },
  { path: '/platform/automation', name: 'platformAutomation', component: () => import('@/views/platform/AutomationView.vue'), meta: { title: '自动化', seal: '自' } },
  { path: '/platform/knowledge', name: 'platformKnowledge', component: () => import('@/views/platform/KnowledgeView.vue'), meta: { title: '知识库', seal: '知' } },
  { path: '/platform/memory', name: 'platformMemory', component: () => import('@/views/platform/MemoryCenterView.vue'), meta: { title: '记忆中枢', seal: '心' } },
  { path: '/platform/sessions', name: 'platformSessions', component: () => import('@/views/platform/SessionsView.vue'), meta: { title: '会话管理', seal: '笺' } },
  { path: '/platform/settings', name: 'platformSettings', component: () => import('@/views/platform/SettingsView.vue'), meta: { title: '通用设置', seal: '设' } },
  { path: '/platform/help', name: 'platformHelp', component: () => import('@/views/platform/HelpView.vue'), meta: { title: '帮助', seal: '助' } },
  { path: '/mobile', name: 'mobile', component: () => import('@/views/platform/MobileView.vue'), meta: { title: '手机伴侣', seal: '伴' } },
]
