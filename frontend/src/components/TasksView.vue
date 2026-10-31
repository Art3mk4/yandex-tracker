<script setup lang="ts">
import { useTasks } from '../composables/useTasks'
import IssueDetail from './IssueDetail.vue'

const { state, filters, queues, open } = useTasks()

const dt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
function fmtDay(iso: string): string {
  return dt.format(new Date(iso))
}
</script>

<template>
  <div>
    <p v-if="state.mirror" class="subtitle mirror-status">
      Зеркало Трекера: {{ state.mirror.issues ?? 0 }} задач · {{ state.mirror.comments ?? 0 }} комментариев ·
      {{ state.mirror.attachments ?? 0 }} файлов<template v-if="state.mirror.last_run_at">
        · последний синк {{ fmtDay(state.mirror.last_run_at) }} ({{ state.mirror.last_mode }})</template>
    </p>

    <div class="filters">
      <label>
        Задача
        <input v-model="filters.q" class="search" placeholder="Поиск по названию…" />
      </label>
      <label>
        Очередь
        <select v-model="filters.queue">
          <option :value="null">Все</option>
          <option v-for="q in queues" :key="q" :value="q">{{ q }}</option>
        </select>
      </label>
    </div>

    <div class="tasks-layout" :class="{ loading: state.loading }">
      <nav class="issue-list">
        <button
          v-for="i in state.list"
          :key="i.key"
          type="button"
          class="issue-item"
          :class="{ active: i.key === state.selected }"
          @click="open(i.key)"
        >
          <span class="issue-item-key">{{ i.key }}</span>
          <span class="issue-item-summary">{{ i.summary }}</span>
          <span class="badge">{{ i.status_name ?? '—' }}</span>
          <span class="issue-item-meta muted">
            {{ fmtDay(i.updated_at) }}
            · 💬 {{ i.comments_count }} · 📎 {{ i.attachments_count }}
            <template v-if="i.timesheet_hours"> · {{ i.timesheet_hours }} ч в табеле</template>
          </span>
        </button>
        <div v-if="!state.list.length && !state.loading" class="empty">
          Нет задач в зеркале — запустите синк
        </div>
      </nav>
      <IssueDetail :data="state.detail" :loading="state.loadingDetail" />
    </div>
  </div>
</template>
