<script setup lang="ts">
import { useData, useRoute } from 'vitepress'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { THEMES, currentTheme, initTheme, setTheme, type ThemeMeta } from '../themes'

const props = withDefaults(
  defineProps<{
    variant?: 'nav' | 'screen'
  }>(),
  {
    variant: 'nav',
  }
)

const { isDark, lang } = useData()
const route = useRoute()

const toggleAppearance = inject('toggle-appearance', () => {
  isDark.value = !isDark.value
})

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const triggerEl = ref<HTMLButtonElement | null>(null)

const isRu = computed(() => lang.value.toLowerCase().startsWith('ru'))
const mode = computed<'light' | 'dark'>(() => (isDark.value ? 'dark' : 'light'))

const themeHeading = computed(() => (isRu.value ? 'Тема' : 'Theme'))
const modeLabel = computed(() =>
  isDark.value ? (isRu.value ? 'Тёмная' : 'Dark') : isRu.value ? 'Светлая' : 'Light'
)
const modeToggleTitle = computed(() =>
  isDark.value
    ? isRu.value
      ? 'Переключить на светлую тему'
      : 'Switch to light mode'
    : isRu.value
      ? 'Переключить на тёмную тему'
      : 'Switch to dark mode'
)
const triggerAriaLabel = computed(() =>
  isRu.value ? 'Выбрать цветовую тему' : 'Select color theme'
)

function themeName(theme: ThemeMeta): string {
  return isRu.value && theme.labelRu ? theme.labelRu : theme.name
}

const activeMeta = computed(
  () => THEMES.find((t) => t.id === currentTheme.value) ?? THEMES[0]
)
const activeAccent = computed(() => activeMeta.value.swatches[mode.value][2])
const activeName = computed(() => themeName(activeMeta.value))

function toggleMenu(): void {
  open.value = !open.value
}

function handleDocumentClick(event: MouseEvent): void {
  if (!open.value || !rootEl.value) return
  const target = event.target as Node | null
  if (target && !rootEl.value.contains(target)) {
    open.value = false
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (open.value && event.key === 'Escape') {
    open.value = false
    triggerEl.value?.focus()
  }
}

watch(
  () => route.path,
  () => {
    open.value = false
  }
)

onMounted(() => {
  initTheme()
  if (props.variant === 'nav') {
    document.addEventListener('click', handleDocumentClick)
    document.addEventListener('keydown', handleKeydown)
  }
})

onBeforeUnmount(() => {
  if (props.variant === 'nav') {
    document.removeEventListener('click', handleDocumentClick)
    document.removeEventListener('keydown', handleKeydown)
  }
})
</script>

<template>
  <div v-if="variant === 'nav'" ref="rootEl" class="theme-switcher-nav">
    <button
      ref="triggerEl"
      type="button"
      class="theme-trigger"
      :aria-expanded="open"
      aria-haspopup="menu"
      :aria-label="triggerAriaLabel"
      :title="activeName"
      @click="toggleMenu"
    >
      <svg
        class="theme-icon"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.9"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <circle cx="13.5" cy="6.5" r=".6" fill="currentColor" />
        <circle cx="17.5" cy="10.5" r=".6" fill="currentColor" />
        <circle cx="8.5" cy="7.5" r=".6" fill="currentColor" />
        <circle cx="6.5" cy="12.5" r=".6" fill="currentColor" />
        <path
          d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2Z"
        />
      </svg>
      <span class="theme-dot" :style="{ backgroundColor: activeAccent }" aria-hidden="true" />
      <span class="theme-label">{{ activeName }}</span>
      <svg
        class="theme-chevron"
        :class="{ open }"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <div v-if="open" class="theme-menu" role="menu" :aria-label="themeHeading">
      <div class="theme-menu-header">
        <span class="theme-menu-title">{{ themeHeading }}</span>
        <button
          type="button"
          class="mode-toggle"
          :title="modeToggleTitle"
          :aria-label="modeToggleTitle"
          @click="toggleAppearance()"
        >
          <svg
            v-if="isDark"
            class="mode-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
          </svg>
          <svg
            v-else
            class="mode-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2" />
            <path d="M12 20v2" />
            <path d="m4.93 4.93 1.41 1.41" />
            <path d="m17.66 17.66 1.41 1.41" />
            <path d="M2 12h2" />
            <path d="M20 12h2" />
            <path d="m6.34 17.66-1.41 1.41" />
            <path d="m19.07 4.93-1.41 1.41" />
          </svg>
          <span>{{ modeLabel }}</span>
        </button>
      </div>

      <div class="theme-menu-list">
        <button
          v-for="t in THEMES"
          :key="t.id"
          type="button"
          role="menuitemradio"
          :aria-checked="currentTheme === t.id"
          class="theme-option"
          :class="{ active: currentTheme === t.id }"
          @click="setTheme(t.id)"
        >
          <span
            class="theme-swatch"
            :style="{
              backgroundColor: t.swatches[mode][0],
              borderColor: t.swatches[mode][1],
            }"
            aria-hidden="true"
          >
            <span class="theme-swatch-dot" :style="{ backgroundColor: t.swatches[mode][2] }" />
            <span class="theme-swatch-dot" :style="{ backgroundColor: t.swatches[mode][3] }" />
          </span>
          <span class="theme-option-name">{{ themeName(t) }}</span>
          <svg
            v-if="currentTheme === t.id"
            class="theme-check"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M20 6 9 17l-5-5" />
          </svg>
        </button>
      </div>
    </div>
  </div>

  <div v-else class="theme-switcher-screen">
    <div class="theme-screen-header">
      <span class="theme-screen-title">{{ themeHeading }}</span>
      <span class="theme-screen-active">{{ activeName }}</span>
    </div>
    <div class="theme-screen-grid" role="radiogroup" :aria-label="themeHeading">
      <button
        v-for="t in THEMES"
        :key="t.id"
        type="button"
        role="radio"
        :aria-checked="currentTheme === t.id"
        class="theme-screen-pill"
        :class="{ active: currentTheme === t.id }"
        @click="setTheme(t.id)"
      >
        <span
          class="theme-swatch-sm"
          :style="{
            backgroundColor: t.swatches[mode][0],
            borderColor: t.swatches[mode][1],
          }"
          aria-hidden="true"
        >
          <span class="theme-swatch-dot-sm" :style="{ backgroundColor: t.swatches[mode][2] }" />
          <span class="theme-swatch-dot-sm" :style="{ backgroundColor: t.swatches[mode][3] }" />
        </span>
        <span class="theme-screen-name">{{ themeName(t) }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.theme-switcher-nav {
  position: relative;
  display: flex;
  align-items: center;
}

@media (min-width: 768px) {
  .theme-switcher-nav {
    margin-left: 14px;
  }
}

@media (min-width: 1280px) {
  .theme-switcher-nav {
    margin-left: 16px;
  }

  .theme-switcher-nav::before {
    content: '';
    display: block;
    width: 1px;
    height: 24px;
    margin-right: 12px;
    background-color: var(--vp-c-divider);
  }
}

.theme-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border-radius: 8px;
  border: 1px solid transparent;
  background-color: transparent;
  color: var(--vp-c-text-1);
  font-size: 13px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease, color 0.2s ease;
}

.theme-trigger:hover {
  background-color: var(--vp-c-bg-soft);
  border-color: var(--vp-c-divider);
}

.theme-trigger:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.theme-icon {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
}

.theme-dot {
  position: absolute;
  right: 5px;
  bottom: 5px;
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  box-shadow: 0 0 0 1.5px var(--vp-nav-bg-color);
  flex-shrink: 0;
}

.theme-label,
.theme-chevron {
  display: none;
}

@media (min-width: 768px) {
  .theme-trigger {
    width: auto;
    height: 32px;
    padding: 0 9px;
    gap: 6px;
    border-color: var(--vp-c-divider);
    background-color: var(--vp-c-bg-soft);
  }

  .theme-trigger:hover {
    border-color: var(--vp-c-brand-1);
  }

  .theme-icon {
    width: 15px;
    height: 15px;
    color: var(--vp-c-text-2);
  }

  .theme-dot {
    position: static;
    width: 8px;
    height: 8px;
    box-shadow: 0 0 0 1px var(--vp-c-divider);
  }
}

@media (min-width: 960px) {
  .theme-trigger {
    padding: 0 10px;
  }

  .theme-label {
    display: inline;
    max-width: 112px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .theme-chevron {
    display: block;
    width: 14px;
    height: 14px;
    color: var(--vp-c-text-2);
    transition: transform 0.2s ease;
  }

  .theme-chevron.open {
    transform: rotate(180deg);
  }
}

.theme-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 100;
  width: 236px;
  max-width: calc(100vw - 24px);
  white-space: normal;
  background-color: var(--vp-c-bg-elv);
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  box-shadow: var(--vp-shadow-3);
  padding: 6px;
}

.theme-menu-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 6px 8px;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--vp-c-divider);
}

.theme-menu-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--vp-c-text-2);
  letter-spacing: 0.01em;
}

.mode-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--vp-c-divider);
  background-color: var(--vp-c-bg-soft);
  color: var(--vp-c-text-1);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease;
}

.mode-toggle:hover {
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-brand-1);
}

.mode-icon {
  width: 13px;
  height: 13px;
}

.theme-menu-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.theme-option {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 7px 8px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--vp-c-text-1);
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}

.theme-option:hover {
  background-color: var(--vp-c-bg-soft);
}

.theme-option.active {
  background-color: var(--vp-c-brand-soft);
  border-color: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
  font-weight: 600;
}

.theme-swatch {
  width: 28px;
  height: 18px;
  border-radius: 5px;
  border: 1px solid;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  flex-shrink: 0;
  box-sizing: border-box;
}

.theme-swatch-dot {
  width: 6px;
  height: 6px;
  border-radius: 9999px;
}

.theme-option-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.theme-check {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--vp-c-brand-1);
}

/* Mobile NavScreen (hamburger menu) variant */
.theme-switcher-screen {
  margin-top: 16px;
  border-radius: 8px;
  padding: 12px;
  background-color: var(--vp-c-bg-soft);
}

.theme-screen-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.theme-screen-title {
  line-height: 20px;
  font-size: 12px;
  font-weight: 500;
  color: var(--vp-c-text-2);
}

.theme-screen-active {
  font-size: 12px;
  font-weight: 600;
  color: var(--vp-c-brand-1);
}

.theme-screen-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.theme-screen-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 6px 7px;
  border-radius: 7px;
  border: 1px solid var(--vp-c-divider);
  background-color: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  font-size: 12px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease, color 0.15s ease;
}

.theme-screen-pill.active {
  border-color: var(--vp-c-brand-1);
  background-color: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
  font-weight: 600;
}

.theme-swatch-sm {
  width: 22px;
  height: 15px;
  border-radius: 4px;
  border: 1px solid;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  flex-shrink: 0;
  box-sizing: border-box;
}

.theme-swatch-dot-sm {
  width: 5px;
  height: 5px;
  border-radius: 9999px;
}

.theme-screen-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
