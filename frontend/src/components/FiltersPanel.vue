<script setup lang="ts">
import type { Filters, Meta, Project } from '../types'

defineProps<{ filters: Filters; meta: Meta | null; projects: Project[] }>()
defineEmits<{ reset: [] }>()
</script>

<template>
  <div class="filters">
    <label
      >с
      <input
        v-model="filters.date_from"
        type="date"
        :min="meta?.min_date ?? undefined"
        :max="filters.date_to ?? meta?.max_date ?? undefined"
    /></label>
    <label
      >по
      <input
        v-model="filters.date_to"
        type="date"
        :min="filters.date_from ?? meta?.min_date ?? undefined"
        :max="meta?.max_date ?? undefined"
    /></label>
    <label>
      Проект
      <select v-model="filters.project_id">
        <option :value="null">Все</option>
        <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.code }}</option>
      </select>
    </label>
    <label>
      Очередь
      <select v-model="filters.queue">
        <option :value="null">Все</option>
        <option v-for="q in meta?.queues ?? []" :key="q" :value="q">{{ q }}</option>
      </select>
    </label>
    <label>
      Задача
      <input v-model="filters.task" class="search" placeholder="Поиск…" />
    </label>
    <label>
      Состояние
      <select v-model="filters.state">
        <option :value="null">Любое</option>
        <option value="synced">в Трекере</option>
        <option value="pending">не синхронизировано</option>
        <option value="excluded">без переноса</option>
      </select>
    </label>
    <button type="button" @click="$emit('reset')">Сбросить</button>
  </div>
</template>
