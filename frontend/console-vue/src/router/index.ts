import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { platformRoutes } from './platform'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'overview', component: () => import('@/views/OverviewView.vue'), meta: { title: '总览', seal: '览' } },
  { path: '/pillars', name: 'pillars', component: () => import('@/views/PillarsView.vue'), meta: { title: '架构', seal: '枢' } },
  { path: '/platform', name: 'platform', component: () => import('@/views/PlatformView.vue'), meta: { title: '舱室', seal: '舱' } },
  { path: '/research-adoption', name: 'researchAdoption', component: () => import('@/views/ResearchAdoptionView.vue'), meta: { title: '权威吸收', seal: '研' } },
  { path: '/workflow', name: 'workflow', component: () => import('@/views/WorkflowView.vue'), meta: { title: '赛题工作流', seal: '流' } },
  { path: '/reproduction', name: 'reproduction', component: () => import('@/views/ReproductionView.vue'), meta: { title: '论文复现', seal: '复' } },
  { path: '/deepening', name: 'deepening', component: () => import('@/views/DeepeningView.vue'), meta: { title: '深做追问', seal: '问' } },
  { path: '/model-gateway', name: 'modelGateway', component: () => import('@/views/ModelGatewayView.vue'), meta: { title: '模型', seal: '玄' } },
  { path: '/skills', name: 'skills', component: () => import('@/views/SkillsRegistryView.vue'), meta: { title: '百工', seal: '工' } },
  { path: '/tuning', name: 'tuning', component: () => import('@/views/TuningView.vue'), meta: { title: '调参', seal: '南' } },
  { path: '/exports', name: 'exports', component: () => import('@/views/ExportCenterView.vue'), meta: { title: '导出', seal: '笈' } },
  { path: '/capsules', name: 'capsules', component: () => import('@/views/CapsuleBrowserView.vue'), meta: { title: '枢忆核', seal: '忆' } },
  { path: '/search', name: 'search', component: () => import('@/views/SearchView.vue'), meta: { title: '琅嬛检索', seal: '琅' } },
  { path: '/command', name: 'command', component: () => import('@/views/CommandView.vue'), meta: { title: '司契指挥', seal: '契' } },
  { path: '/reflection', name: 'reflection', component: () => import('@/views/ReflectionView.vue'), meta: { title: '兰台复盘', seal: '鉴' } },
  { path: '/audit', name: 'audit', component: () => import('@/views/AuditView.vue'), meta: { title: '审计流水', seal: '台' } },
  // v0.11 Soul Awakening
  { path: '/soul', name: 'soul', component: () => import('@/views/SoulView.vue'), meta: { title: '灵魂状态', seal: '灵' } },
  { path: '/chat', name: 'chat', component: () => import('@/views/ChatView.vue'), meta: { title: '灵魂对话', seal: '话' } },
  { path: '/dream', name: 'dream', component: () => import('@/views/DreamView.vue'), meta: { title: '梦境日志', seal: '梦' } },
  // v0.12 万枢协作平台
  ...platformRoutes,
  // 兜底：未匹配路径一律进入 404 引导页（必须位于最后）
  { path: '/:pathMatch(.*)*', name: 'notFound', component: () => import('@/views/NotFoundView.vue'), meta: { title: '迷途', seal: '迷' } },
]

export const router = createRouter({
  history: createWebHashHistory('/console/'),
  routes,
})

// 标题同步守卫：meta.title → document.title（09-#9 顺带补）
router.afterEach((to) => {
  const title = (to.meta.title as string) || ''
  document.title = title ? `${title} · 宛委·枢忆` : '宛委·枢忆 · 花朝台'
})
