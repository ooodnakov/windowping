<script setup lang="ts">
import { computed, ref } from 'vue'

type TabId = 'windows' | 'telegram'
type TgAction = 'idle' | 'refresh' | 'ping'

interface MeterSpec {
  label: string
  pct: number
  countdown: string
  tone?: 'brand' | 'warning'
}

interface ProviderRow {
  id: string
  name: string
  status: 'ok' | 'warn'
  badge?: string
  meters: MeterSpec[]
}

const activeTab = ref<TabId>('windows')
const rolledOver = ref(false)
const tgAction = ref<TgAction>('idle')
const tgMuted = ref(false)

function filledBlocks(pct: number): number {
  if (pct <= 0) return 0
  return Math.max(1, Math.min(10, Math.round(pct / 10)))
}

const windowProviders = computed<ProviderRow[]>(() => [
  {
    id: 'codex',
    name: 'Codex · plus',
    status: 'ok',
    badge: rolledOver.value ? 'window opened' : undefined,
    meters: [
      {
        label: '5h',
        pct: rolledOver.value ? 1 : 14,
        countdown: rolledOver.value ? '5h00m' : '2h03m',
        tone: 'brand',
      },
      {
        label: 'weekly',
        pct: rolledOver.value ? 19 : 18,
        countdown: '',
        tone: 'brand',
      },
    ],
  },
  {
    id: 'glm',
    name: 'GLM · lite',
    status: 'ok',
    meters: [
      {
        label: '5h',
        pct: 1,
        countdown: '1h08m',
        tone: 'brand',
      },
      {
        label: 'weekly',
        pct: 32,
        countdown: '2d20h',
        tone: 'brand',
      },
    ],
  },
  {
    id: 'command-code',
    name: 'Command Code',
    status: 'warn',
    badge: 'weekly guard',
    meters: [
      {
        label: '5h',
        pct: 0,
        countdown: '',
        tone: 'brand',
      },
      {
        label: 'weekly',
        pct: 100,
        countdown: '23h27m',
        tone: 'warning',
      },
    ],
  },
])

const telegramProviders = computed<ProviderRow[]>(() => {
  const pinged = tgAction.value === 'ping'
  return [
    {
      id: 'codex',
      name: 'Codex · plus',
      status: 'ok',
      meters: [
        {
          label: '5h',
          pct: pinged ? 1 : 14,
          countdown: pinged ? '5h00m' : '2h03m',
          tone: 'brand',
        },
        {
          label: 'weekly',
          pct: pinged ? 19 : 18,
          countdown: '—',
          tone: 'brand',
        },
      ],
    },
    {
      id: 'command-code',
      name: 'Command Code',
      status: 'warn',
      meters: [
        {
          label: '5h',
          pct: 0,
          countdown: '—',
          tone: 'brand',
        },
        {
          label: 'weekly',
          pct: 100,
          countdown: '23h27m',
          tone: 'warning',
        },
      ],
    },
    {
      id: 'glm',
      name: 'GLM · lite',
      status: 'ok',
      meters: [
        {
          label: '5h',
          pct: 1,
          countdown: '1h08m',
          tone: 'brand',
        },
        {
          label: 'weekly',
          pct: 32,
          countdown: '2d20h',
          tone: 'brand',
        },
      ],
    },
  ]
})

const telegramStatusLine = computed(() => {
  if (tgMuted.value) {
    return 'muted for 8h (until 04:31) · escalations active'
  }
  if (tgAction.value === 'refresh') {
    return 'updated 20:34 · readings current · next auto at 21:04'
  }
  if (tgAction.value === 'ping') {
    return 'tick at 20:34 · Codex window opened (16 tokens)'
  }
  return 'updated 20:31 · next auto at 21:01'
})

function onTabKeydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
    event.preventDefault()
    activeTab.value = activeTab.value === 'windows' ? 'telegram' : 'windows'
  }
}

function toggleRollover(): void {
  rolledOver.value = !rolledOver.value
}

function triggerTgRefresh(): void {
  tgMuted.value = false
  tgAction.value = 'refresh'
}

function triggerTgPing(): void {
  tgMuted.value = false
  tgAction.value = 'ping'
}

function toggleTgMute(): void {
  tgMuted.value = !tgMuted.value
}
</script>

<template>
  <section class="wp-panel" aria-label="windowping live telemetry preview">
    <header class="wp-header">
      <div class="wp-brand">
        <span class="wp-dot wp-dot-ok" aria-hidden="true" />
        <span class="wp-cmd">windowping watch</span>
      </div>

      <div
        class="wp-tablist"
        role="tablist"
        aria-label="Telemetry views"
        @keydown="onTabKeydown"
      >
        <button
          id="wp-tab-windows"
          type="button"
          role="tab"
          class="wp-tab"
          :class="{ active: activeTab === 'windows' }"
          :aria-selected="activeTab === 'windows'"
          :tabindex="activeTab === 'windows' ? 0 : -1"
          aria-controls="wp-panel-windows"
          @click="activeTab = 'windows'"
        >
          Rolling Windows
        </button>
        <button
          id="wp-tab-telegram"
          type="button"
          role="tab"
          class="wp-tab"
          :class="{ active: activeTab === 'telegram' }"
          :aria-selected="activeTab === 'telegram'"
          :tabindex="activeTab === 'telegram' ? 0 : -1"
          aria-controls="wp-panel-telegram"
          @click="activeTab = 'telegram'"
        >
          Telegram Card
        </button>
      </div>
    </header>

    <div
      v-if="activeTab === 'windows'"
      id="wp-panel-windows"
      role="tabpanel"
      aria-labelledby="wp-tab-windows"
      class="wp-body"
    >
      <div class="wp-rows">
        <div
          v-for="row in windowProviders"
          :key="row.id"
          class="wp-row"
          :class="{
            'is-highlight': rolledOver && row.id === 'codex',
          }"
        >
          <div class="wp-row-head">
            <span class="wp-provider">
              <span
                class="wp-dot"
                :class="row.status === 'warn' ? 'wp-dot-warn' : 'wp-dot-ok'"
                aria-hidden="true"
              />
              <span class="wp-provider-name">{{ row.name }}</span>
            </span>
            <span
              v-if="row.badge"
              class="wp-pill"
              :class="row.status === 'warn' ? 'wp-pill-warn' : 'wp-pill-ok'"
            >
              {{ row.badge }}
            </span>
          </div>

          <div class="wp-meters">
            <div v-for="meter in row.meters" :key="meter.label" class="wp-meter-line">
              <span class="wp-meter-label">{{ meter.label }}</span>
              <span class="wp-blocks" aria-hidden="true">
                <span
                  v-for="block in 10"
                  :key="block"
                  class="wp-block"
                  :class="{
                    filled: block <= filledBlocks(meter.pct),
                    warn: meter.tone === 'warning' && block <= filledBlocks(meter.pct),
                  }"
                />
              </span>
              <span class="wp-meter-value">
                {{ meter.pct }}%<template v-if="meter.countdown"> · {{ meter.countdown }}</template>
              </span>
            </div>
          </div>
        </div>
      </div>

      <div class="wp-log-bar" :class="{ 'is-rollover': rolledOver }">
        <div class="wp-log-msg">
          <svg
            v-if="rolledOver"
            class="wp-icon wp-icon-ok"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="9" />
            <path d="m9 12 2 2 4-4" />
          </svg>
          <svg
            v-else
            class="wp-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M22 12h-4l-3 7-6-14-3 7H2" />
          </svg>
          <span class="wp-log-text">
            {{
              rolledOver
                ? 'Codex: window opened (1.9s, 16 tokens) · reset +5h00m'
                : 'watching 6 providers · next check 30m'
            }}
          </span>
        </div>

        <button
          type="button"
          class="wp-action-btn"
          :class="{ active: rolledOver }"
          :aria-pressed="rolledOver"
          @click="toggleRollover"
        >
          <svg
            class="wp-btn-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M21 12a9 9 0 1 1-2.64-6.36" />
            <path d="M21 3v6h-6" />
          </svg>
          <span>{{ rolledOver ? 'Reset sample' : 'Simulate rollover' }}</span>
        </button>
      </div>
    </div>

    <div
      v-else
      id="wp-panel-telegram"
      role="tabpanel"
      aria-labelledby="wp-tab-telegram"
      class="wp-body"
    >
      <div class="wp-tg-card">
        <div class="wp-tg-head">
          <span class="wp-tg-title">
            <svg
              class="wp-btn-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M4 18V8" />
              <path d="M10 18V4" />
              <path d="M16 18v-7" />
              <path d="M22 18V11" />
            </svg>
            <span>limits</span>
          </span>
          <span class="wp-tg-pin" :class="{ muted: tgMuted }">
            {{ tgMuted ? 'muted 8h' : 'pinned' }}
          </span>
        </div>

        <div class="wp-tg-list">
          <div v-for="row in telegramProviders" :key="row.id" class="wp-tg-provider">
            <div class="wp-tg-provider-head">
              <span
                class="wp-dot"
                :class="row.status === 'warn' ? 'wp-dot-warn' : 'wp-dot-ok'"
                aria-hidden="true"
              />
              <span class="wp-tg-provider-name">{{ row.name }}</span>
            </div>

            <div v-for="meter in row.meters" :key="meter.label" class="wp-tg-line">
              <span class="wp-tg-k">{{ meter.label }}</span>
              <span class="wp-blocks wp-blocks-sm" aria-hidden="true">
                <span
                  v-for="block in 10"
                  :key="block"
                  class="wp-block"
                  :class="{
                    filled: block <= filledBlocks(meter.pct),
                    warn: meter.tone === 'warning' && block <= filledBlocks(meter.pct),
                  }"
                />
              </span>
              <span class="wp-tg-pct">{{ meter.pct }}%</span>
              <span class="wp-tg-time">{{ meter.countdown }}</span>
            </div>
          </div>
        </div>

        <div class="wp-tg-status" :class="{ muted: tgMuted }">
          {{ telegramStatusLine }}
        </div>
      </div>

      <div class="wp-tg-actions" role="group" aria-label="Telegram card controls">
        <button
          type="button"
          class="wp-tg-btn"
          :class="{ active: tgAction === 'refresh' && !tgMuted }"
          @click="triggerTgRefresh"
        >
          <svg
            class="wp-btn-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.36-2.64" />
            <path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.36 2.64" />
            <path d="M21 3v5h-5" />
            <path d="M3 21v-5h5" />
          </svg>
          <span>Refresh</span>
        </button>

        <button
          type="button"
          class="wp-tg-btn"
          :class="{ active: tgAction === 'ping' && !tgMuted }"
          @click="triggerTgPing"
        >
          <svg
            class="wp-btn-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="13" r="8" />
            <path d="M12 9v4l2.5 2.5" />
            <path d="M9 2h6" />
          </svg>
          <span>Ping</span>
        </button>

        <button
          type="button"
          class="wp-tg-btn"
          :class="{ active: tgMuted }"
          :aria-pressed="tgMuted"
          @click="toggleTgMute"
        >
          <svg
            class="wp-btn-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M10.27 4.27A6 6 0 0 1 18 10c0 3.5 1.5 5 2 6H4c.5-1 2-2.5 2-6a6 6 0 0 1 .48-2.36" />
            <path d="M10.3 20a2 2 0 0 0 3.4 0" />
            <path d="m2 2 20 20" />
          </svg>
          <span>{{ tgMuted ? 'Unmute' : 'Mute 8h' }}</span>
        </button>
      </div>
    </div>

    <footer class="wp-footer">
      <span>Sample output · Python 3.11+ stdlib</span>
    </footer>
  </section>
</template>

<style scoped>
.wp-panel {
  width: 100%;
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  background-color: var(--vp-c-bg-alt);
  overflow: hidden;
  text-align: left;
  color: var(--vp-c-text-1);
}

.wp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--vp-c-divider);
  background-color: var(--vp-c-bg-soft);
}

.wp-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.wp-cmd {
  font-family: var(--vp-font-family-mono);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--vp-c-text-1);
  letter-spacing: -0.01em;
}

.wp-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  flex-shrink: 0;
}

.wp-dot-ok {
  background-color: var(--vp-c-success-1);
}

.wp-dot-warn {
  background-color: var(--vp-c-warning-1);
}

.wp-tablist {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  background-color: var(--vp-c-bg);
}

.wp-tab {
  padding: 5px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--vp-c-text-2);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.25;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.wp-tab:hover {
  color: var(--vp-c-text-1);
}

.wp-tab.active {
  background-color: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
}

.wp-body {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.wp-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.wp-row {
  padding: 10px 12px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  background-color: var(--vp-c-bg);
  transition: border-color 0.18s ease, background-color 0.18s ease;
}

.wp-row.is-highlight {
  border-color: color-mix(in srgb, var(--vp-c-success-1) 45%, var(--vp-c-divider));
  background-color: color-mix(in srgb, var(--vp-c-success-1) 7%, var(--vp-c-bg));
}

.wp-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.wp-provider {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.wp-provider-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--vp-c-text-1);
}

.wp-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-family: var(--vp-font-family-mono);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.3;
  white-space: nowrap;
}

.wp-pill-warn {
  background-color: var(--vp-c-warning-soft);
  color: var(--vp-c-warning-1);
  border: 1px solid color-mix(in srgb, var(--vp-c-warning-1) 35%, transparent);
}

.wp-pill-ok {
  background-color: var(--vp-c-success-soft);
  color: var(--vp-c-success-1);
  border: 1px solid color-mix(in srgb, var(--vp-c-success-1) 35%, transparent);
}

.wp-meters {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.wp-meter-line {
  display: grid;
  grid-template-columns: 48px minmax(72px, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.wp-meter-label {
  font-family: var(--vp-font-family-mono);
  font-size: 11.5px;
  color: var(--vp-c-text-2);
}

.wp-blocks {
  display: grid;
  grid-template-columns: repeat(10, minmax(0, 1fr));
  gap: 2.5px;
}

.wp-block {
  height: 7px;
  border-radius: 2px;
  background-color: color-mix(in srgb, var(--vp-c-text-3) 20%, transparent);
}

.wp-block.filled {
  background-color: var(--vp-c-brand-1);
}

.wp-block.warn {
  background-color: var(--vp-c-warning-1);
}

.wp-meter-value {
  font-family: var(--vp-font-family-mono);
  font-size: 11.5px;
  font-weight: 500;
  color: var(--vp-c-text-1);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  text-align: right;
  min-width: 96px;
}

.wp-log-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 9px 11px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  background-color: var(--vp-c-bg);
  transition: border-color 0.18s ease, background-color 0.18s ease;
}

.wp-log-bar.is-rollover {
  border-color: color-mix(in srgb, var(--vp-c-success-1) 45%, var(--vp-c-divider));
  background-color: color-mix(in srgb, var(--vp-c-success-1) 8%, var(--vp-c-bg));
}

.wp-log-msg {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  flex: 1 1 200px;
}

.wp-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--vp-c-text-2);
}

.wp-icon-ok {
  color: var(--vp-c-success-1);
}

.wp-log-text {
  font-family: var(--vp-font-family-mono);
  font-size: 11.5px;
  line-height: 1.4;
  color: var(--vp-c-text-2);
  font-variant-numeric: tabular-nums;
}

.wp-log-bar.is-rollover .wp-log-text {
  color: var(--vp-c-text-1);
}

.wp-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--vp-c-border);
  border-radius: 6px;
  background-color: var(--vp-c-bg-soft);
  color: var(--vp-c-text-1);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.25;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s ease, background-color 0.15s ease, color 0.15s ease;
}

.wp-action-btn:hover {
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-brand-1);
}

.wp-action-btn.active {
  border-color: var(--vp-c-brand-1);
  background-color: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
}

.wp-btn-icon {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

.wp-tg-card {
  padding: 12px 14px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  background-color: var(--vp-c-bg);
}

.wp-tg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 9px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--vp-c-divider);
}

.wp-tg-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--vp-font-family-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--vp-c-text-1);
}

.wp-tg-pin {
  padding: 2px 7px;
  border-radius: 6px;
  border: 1px solid var(--vp-c-divider);
  background-color: var(--vp-c-bg-soft);
  color: var(--vp-c-text-2);
  font-family: var(--vp-font-family-mono);
  font-size: 11px;
  font-weight: 600;
}

.wp-tg-pin.muted {
  border-color: color-mix(in srgb, var(--vp-c-warning-1) 40%, transparent);
  background-color: var(--vp-c-warning-soft);
  color: var(--vp-c-warning-1);
}

.wp-tg-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.wp-tg-provider {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.wp-tg-provider-head {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.wp-tg-provider-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--vp-c-text-1);
}

.wp-tg-line {
  display: grid;
  grid-template-columns: 46px minmax(64px, 1fr) 36px 52px;
  align-items: center;
  gap: 8px;
  font-family: var(--vp-font-family-mono);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.wp-tg-k {
  color: var(--vp-c-text-2);
}

.wp-blocks-sm .wp-block {
  height: 6px;
}

.wp-tg-pct {
  text-align: right;
  color: var(--vp-c-text-1);
  font-weight: 500;
}

.wp-tg-time {
  text-align: right;
  color: var(--vp-c-text-2);
}

.wp-tg-status {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--vp-c-divider);
  font-family: var(--vp-font-family-mono);
  font-size: 11.5px;
  color: var(--vp-c-text-2);
  font-variant-numeric: tabular-nums;
}

.wp-tg-status.muted {
  color: var(--vp-c-warning-1);
}

.wp-tg-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.wp-tg-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  padding: 5px 8px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 6px;
  background-color: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease, color 0.15s ease;
}

.wp-tg-btn:hover {
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-brand-1);
}

.wp-tg-btn.active {
  border-color: var(--vp-c-brand-1);
  background-color: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
}

.wp-footer {
  padding: 8px 14px;
  border-top: 1px solid var(--vp-c-divider);
  background-color: var(--vp-c-bg-soft);
  font-family: var(--vp-font-family-mono);
  font-size: 11.5px;
  color: var(--vp-c-text-3);
}

@media (max-width: 420px) {
  .wp-header {
    padding: 10px 12px;
  }

  .wp-body {
    padding: 12px;
  }

  .wp-meter-line {
    grid-template-columns: 44px minmax(54px, 1fr) auto;
    gap: 8px;
  }

  .wp-meter-value {
    min-width: 84px;
  }

  .wp-tg-line {
    grid-template-columns: 42px minmax(52px, 1fr) 34px 48px;
    gap: 6px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wp-tab,
  .wp-row,
  .wp-log-bar,
  .wp-action-btn,
  .wp-tg-btn {
    transition: none;
  }
}
</style>
