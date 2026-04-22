import { createRouter, createWebHistory } from 'vue-router'

import HistoryView from '../views/History.vue'
import LiveView from '../views/LiveView.vue'
import StudyLibView from "@/views/StudyLibView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'live',
      component: LiveView,
    },
    {
      path: '/history',
      name: 'history',
      component: HistoryView,
    },
    {
      path: '/workshop',
      name: 'workshop',
      component: StudyLibView,
    },
  ],
})

export default router
