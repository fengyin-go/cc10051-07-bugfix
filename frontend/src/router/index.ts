import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import ReceiptCenter from '@/views/ReceiptCenter.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 回执中心使用专用签收核对台，其余模块走通用工作台
    { path: '/dist_receipt', name: 'dist_receipt', component: ReceiptCenter },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
