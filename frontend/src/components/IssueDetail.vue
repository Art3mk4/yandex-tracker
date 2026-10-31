<script setup lang="ts">
import { computed } from 'vue'

import type { IssueDetail } from '../types'

const props = defineProps<{ data: IssueDetail | null; loading: boolean }>()

const dt = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
function fmt(iso: string | null): string {
  return iso ? dt.format(new Date(iso)) : '—'
}
const kb = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
function fmtSize(bytes: number): string {
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} МБ` : `${kb.format(bytes / 1024)} КБ`
}
const meta = computed(() => {
  const i = props.data?.issue
  if (!i) return []
  return [
    ['Статус', i.status_name ?? '—'],
    ['Очередь', i.queue_name || i.queue],
    ['Тип', i.type_name ?? '—'],
    ['Приоритет', i.priority_name ?? '—'],
    ['Исполнитель', i.assignee_name ?? '—'],
    ['Автор', i.created_by_name ?? '—'],
    ['Создана', fmt(i.created_at)],
    ['Обновлена', fmt(i.updated_at)],
  ]
})
</script>

<template>
  <div v-if="loading && !data" class="empty">Загрузка…</div>
  <div v-else-if="!data" class="empty">Выберите задачу</div>
  <article v-else class="issue">
    <header class="issue-head">
      <h3>{{ data.issue.key }} — {{ data.issue.summary }}</h3>
      <span v-for="a in data.issue.aliases" :key="a" class="badge">алиас: {{ a }}</span>
    </header>

    <dl class="issue-meta">
      <template v-for="([k, v], i) in meta" :key="i">
        <dt>{{ k }}</dt>
        <dd>{{ v }}</dd>
      </template>
    </dl>

    <section v-if="data.issue.description" class="issue-section">
      <h4>Описание</h4>
      <p class="issue-desc">{{ data.issue.description }}</p>
    </section>

    <section v-if="data.attachments.length" class="issue-section">
      <h4>Вложения ({{ data.attachments.length }})</h4>
      <ul class="attachments">
        <li v-for="a in data.attachments" :key="a.id">
          <a v-if="a.url" :href="a.url" :download="a.name">{{ a.name }}</a>
          <span v-else>{{ a.name }}</span>
          <span class="muted"> · {{ fmtSize(a.size) }}</span>
        </li>
      </ul>
    </section>

    <section class="issue-section">
      <h4>Комментарии ({{ data.comments.length }})</h4>
      <ol class="comments">
        <li v-for="c in data.comments" :key="c.id" class="comment">
          <div class="comment-head">
            <strong>{{ c.author_name ?? '—' }}</strong>
            <span class="muted">{{ fmt(c.created_at) }}</span>
          </div>
          <p class="comment-text">{{ c.text }}</p>
        </li>
        <li v-if="!data.comments.length" class="muted">Комментариев нет</li>
      </ol>
    </section>

    <details v-if="data.changelog.length" class="changelog">
      <summary>История изменений ({{ data.changelog.length }})</summary>
      <ul>
        <li v-for="(ch, i) in [...data.changelog].reverse()" :key="i">
          <span class="muted">{{ fmt(ch.updated_at) }}</span>
          {{ ch.author_name ?? '—' }}:
          <template v-for="(c, j) in ch.changes" :key="j">
            <em>{{ c.field }}</em> {{ c.from || '∅' }} → {{ c.to || '∅' }}<template v-if="j < ch.changes.length - 1">;</template>
          </template>
        </li>
      </ul>
    </details>
  </article>
</template>
