<script setup lang="ts">
import { Chart } from 'chart.js/auto'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { cssVar, fmtHours, isoDayTitle, isoRange, onThemeChange } from '../chart-theme'
import type { DailyTotal } from '../types'

const props = defineProps<{ days: DailyTotal[] }>()
const canvas = ref<HTMLCanvasElement | null>(null)
let chart: Chart | null = null
let offTheme: (() => void) | undefined

function render() {
  if (!canvas.value) return
  // непрерывная ось дат: пропущенные дни — нули, разрывы не исчезают
  const byDate = new Map(props.days.map((d) => [d.work_date, d.hours]))
  const labels = props.days.length
    ? isoRange(props.days[0].work_date, props.days[props.days.length - 1].work_date)
    : []
  const values = labels.map((iso) => byDate.get(iso) ?? 0)

  chart?.destroy()
  chart = new Chart(canvas.value, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: cssVar('--series-1'),
          hoverBackgroundColor: cssVar('--series-1-hover'),
          maxBarThickness: 24,
          borderRadius: 4,
          borderSkipped: 'bottom', // скругление у данных, у базовой линии квадрат
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false }, // один ряд — заголовок карточки называет его
        tooltip: {
          backgroundColor: cssVar('--surface-1'),
          titleColor: cssVar('--text-secondary'),
          bodyColor: cssVar('--text-primary'),
          borderColor: cssVar('--border'),
          borderWidth: 1,
          padding: 10,
          displayColors: false,
          callbacks: {
            title: (items) => isoDayTitle(String(items[0].label)),
            label: (item) => `${fmtHours(Number(item.raw))} ч`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: cssVar('--baseline') },
          ticks: {
            color: cssVar('--text-muted'),
            maxRotation: 0,
            autoSkip: true,
            callback(value) {
              const iso = this.getLabelForValue(Number(value))
              return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`
            },
          },
        },
        y: {
          beginAtZero: true,
          grid: { color: cssVar('--gridline') },
          border: { display: false },
          ticks: { color: cssVar('--text-muted') },
        },
      },
    },
  })
}

onMounted(() => {
  render()
  offTheme = onThemeChange(render)
})
onBeforeUnmount(() => {
  offTheme?.()
  chart?.destroy()
})
watch(() => props.days, render)
</script>

<template>
  <div class="chart-box">
    <canvas ref="canvas"></canvas>
  </div>
</template>
