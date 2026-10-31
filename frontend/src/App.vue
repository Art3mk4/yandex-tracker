<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'

import DailyChart from './components/DailyChart.vue'
import EntriesTable from './components/EntriesTable.vue'
import FiltersPanel from './components/FiltersPanel.vue'
import KpiTiles from './components/KpiTiles.vue'
import TaskChart from './components/TaskChart.vue'
import TasksView from './components/TasksView.vue'
import { useDashboard } from './composables/useDashboard'
import { useFilters } from './composables/useFilters'

const { filters, reset } = useFilters()
const { state } = useDashboard(filters)

// вкладки без роутера: hash «#/tasks»
type View = 'timesheet' | 'tasks'
const view = ref<View>(location.hash === '#/tasks' ? 'tasks' : 'timesheet')
function setView(v: View) {
  view.value = v
  location.hash = v === 'tasks' ? '#/tasks' : ''
}
function onHash() {
  view.value = location.hash === '#/tasks' ? 'tasks' : 'timesheet'
}
onMounted(() => addEventListener('hashchange', onHash))
onBeforeUnmount(() => removeEventListener('hashchange', onHash))

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
})
const subtitle = computed(() => {
  const m = state.meta
  if (!m || !m.min_date || !m.max_date) return ''
  const from = dateFmt.format(new Date(`${m.min_date}T00:00:00`))
  const to = dateFmt.format(new Date(`${m.max_date}T00:00:00`))
  const period = m.min_date === m.max_date ? `за ${from}` : `с ${from} по ${to}`
  return `${period} · записей ${m.entries_count}`
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="head-row">
        <h1>Учёт времени</h1>
        <nav class="view-switch">
          <button
            type="button"
            :class="{ active: view === 'timesheet' }"
            @click="setView('timesheet')"
          >
            Табель
          </button>
          <button type="button" :class="{ active: view === 'tasks' }" @click="setView('tasks')">
            Задачи
          </button>
        </nav>
      </div>
      <p class="subtitle">{{ subtitle }}</p>
    </header>

    <div v-show="view === 'timesheet'" class="content" :class="{ loading: state.loading }">
      <FiltersPanel :filters="filters" :meta="state.meta" :projects="state.projects" @reset="reset" />
      <KpiTiles :hours="state.totalHours" :days="state.daily.length" :tasks="state.tasksTotal" />
      <div class="charts">
        <section class="card">
          <h2>Часы по дням</h2>
          <DailyChart :days="state.daily" />
        </section>
        <section class="card">
          <h2>Задачи с наибольшими часами</h2>
          <TaskChart :tasks="state.tasks" />
        </section>
      </div>
      <section class="card">
        <h2>Записи</h2>
        <EntriesTable :entries="state.entries" />
      </section>
    </div>

    <TasksView v-if="view === 'tasks'" />
  </div>
</template>
