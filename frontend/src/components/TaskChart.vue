<script setup lang="ts">
import { Chart } from 'chart.js/auto'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { cssVar, fmtHours, onThemeChange } from '../chart-theme'
import type { TaskTotal } from '../types'

const props = defineProps<{ tasks: TaskTotal[] }>()
const canvas = ref<HTMLCanvasElement | null>(null)
let chart: Chart | null = null
let offTheme: (() => void) | undefined

function render() {
  if (!canvas.value) return
  chart?.destroy()
  chart = new Chart(canvas.value, {
    type: 'bar',
    data: {
      labels: props.tasks.map((t) => t.task),
      datasets: [
        {
          data: props.tasks.map((t) => Number(t.hours)),
          backgroundColor: cssVar('--series-1'), // номинальные категории — один цвет
          hoverBackgroundColor: cssVar('--series-1-hover'),
          maxBarThickness: 24,
          borderRadius: 4,
          borderSkipped: 'start', // скругление у данных (справа), у базовой линии квадрат
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar('--surface-1'),
          titleColor: cssVar('--text-secondary'),
          bodyColor: cssVar('--text-primary'),
          borderColor: cssVar('--border'),
          borderWidth: 1,
          padding: 10,
          displayColors: false,
          callbacks: {
            label: (item) => {
              const t = props.tasks[item.dataIndex]
              return `${fmtHours(Number(item.raw))} ч · ${t.entries} запис.`
            },
          },
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: cssVar('--gridline') },
          border: { display: false },
          ticks: { color: cssVar('--text-muted') },
        },
        y: {
          grid: { display: false },
          border: { color: cssVar('--baseline') },
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
watch(() => props.tasks, render)
</script>

<template>
  <div class="chart-box tall">
    <canvas ref="canvas"></canvas>
  </div>
</template>
