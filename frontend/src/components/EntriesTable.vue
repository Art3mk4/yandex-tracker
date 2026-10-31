<script setup lang="ts">
import { computed, ref } from 'vue'

import type { Entry, TrackerState } from '../types'

const props = defineProps<{ entries: Entry[] }>()

const sortKey = ref<'date' | 'hours'>('date')
const sortDir = ref<1 | -1>(-1)

function toggle(key: 'date' | 'hours') {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 1 ? -1 : 1
  } else {
    sortKey.value = key
    sortDir.value = -1
  }
}
function arrow(key: 'date' | 'hours'): string {
  return sortKey.value === key ? (sortDir.value === 1 ? '↑' : '↓') : ''
}

const rows = computed(() =>
  [...props.entries].sort((a, b) => {
    const d = sortKey.value === 'hours' ? a.hours - b.hours : a.work_date.localeCompare(b.work_date)
    return d * sortDir.value || a.id - b.id
  }),
)

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'short',
  day: '2-digit',
  month: '2-digit',
  year: '2-digit',
})
function fmtDate(iso: string): string {
  return dateFmt.format(new Date(`${iso}T00:00:00`))
}

const stateLabel: Record<TrackerState, string> = {
  synced: 'в Трекере',
  pending: 'не синхр.',
  excluded: 'без переноса',
}

const numFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
</script>

<template>
  <div class="table-wrap">
    <table v-if="rows.length">
      <thead>
        <tr>
          <th class="sortable" @click="toggle('date')">Дата {{ arrow('date') }}</th>
          <th>Задача</th>
          <th>Очередь</th>
          <th class="hours sortable" @click="toggle('hours')">Часы {{ arrow('hours') }}</th>
          <th class="desc">Что сделано</th>
          <th>Источник</th>
          <th>Состояние</th>
          <th>Проект</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in rows" :key="e.id">
          <td class="date">{{ fmtDate(e.work_date) }}</td>
          <td>
            <template v-if="e.task_key">{{ e.task_key }}</template>
            <span v-else class="badge">{{ e.label }}</span>
          </td>
          <td>{{ e.task_key ? e.task_key.split('-')[0] : '—' }}</td>
          <td class="hours">{{ numFmt.format(e.hours) }}</td>
          <td class="desc">{{ e.description }}</td>
          <td>{{ e.estimate_source }}</td>
          <td>
            <span class="badge" :class="`state-${e.tracker_state}`">{{
              stateLabel[e.tracker_state]
            }}</span>
          </td>
          <td>{{ e.project?.code ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
    <div v-else class="empty">Нет записей по этим фильтрам</div>
  </div>
</template>
