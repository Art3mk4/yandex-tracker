<script setup lang="ts">
import { computed } from 'vue'

import { fmtHours } from '../chart-theme'

const props = defineProps<{ hours: number; days: number; tasks: number }>()

const avg = computed(() => (props.days ? props.hours / props.days : 0))
const intFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const fmt1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
</script>

<template>
  <div class="kpis">
    <div class="kpi">
      <div class="label">Всего часов</div>
      <div class="value">{{ fmtHours(hours) }}</div>
    </div>
    <div class="kpi">
      <div class="label">Дней с записями</div>
      <div class="value">{{ intFmt.format(days) }}</div>
    </div>
    <div class="kpi">
      <div class="label">Среднее в день</div>
      <div class="value">{{ fmt1.format(avg) }} ч</div>
    </div>
    <div class="kpi">
      <div class="label">Задач</div>
      <div class="value">{{ intFmt.format(tasks) }}</div>
    </div>
  </div>
</template>
