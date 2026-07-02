import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'overview', component: () => import('@/views/OverviewView.vue'), meta: { title: '总览', seal: '览' } },
  { path: '/pillars', name: 'pillars', component: () => import('@/views/PillarsView.vue'), meta: { title: '九枢', seal: '枢' } },
  { path: '/capsules', name: 'capsules', component: () => import('@/views/CapsuleBrowserView.vue'), meta: { title: '枢忆核', seal: '忆' } },
  { path: '/search', name: 'search', component: () => import('@/views/SearchView.vue'), meta: { title: '琅嬛检索', seal: '琅' } },
  { path: '/command', name: 'command', component: () => import('@/views/CommandView.vue'), meta: { title: '司契指挥', seal: '契' } },
  { path: '/reflection', name: 'reflection', component: () => import('@/views/ReflectionView.vue'), meta: { title: '兰台复盘', seal: '鉴' } },
]

export const router = createRouter({
  history: createWebHashHistory('/console/'),
  routes,
})
