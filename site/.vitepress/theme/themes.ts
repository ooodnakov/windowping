import { ref } from 'vue'

export const THEME_STORAGE_KEY = 'ooodnakov-docs-theme'

export type ThemeId =
  | 'default'
  | 'solarized'
  | 'gruvbox'
  | 'catppuccin'
  | 'nord'
  | 'tokyo-night'
  | 'dracula'
  | 'rose-pine'

export type SwatchTuple = readonly [bg: string, surface: string, accent1: string, accent2: string]

export interface ThemeMeta {
  id: ThemeId
  name: string
  labelRu?: string
  swatches: {
    light: SwatchTuple
    dark: SwatchTuple
  }
}

export const THEMES: readonly ThemeMeta[] = [
  {
    id: 'default',
    name: 'Default',
    labelRu: 'По умолчанию',
    swatches: {
      light: ['#ffffff', '#f6f6f7', '#059669', '#0284c7'],
      dark: ['#0b1120', '#131c2e', '#34d399', '#38bdf8'],
    },
  },
  {
    id: 'solarized',
    name: 'Solarized',
    swatches: {
      light: ['#fdf6e3', '#eee8d5', '#268bd2', '#2aa198'],
      dark: ['#002b36', '#073642', '#2aa198', '#268bd2'],
    },
  },
  {
    id: 'gruvbox',
    name: 'Gruvbox',
    swatches: {
      light: ['#fbf1c7', '#ebdbb2', '#af3a03', '#b57614'],
      dark: ['#282828', '#3c3836', '#fe8019', '#b8bb26'],
    },
  },
  {
    id: 'catppuccin',
    name: 'Catppuccin',
    swatches: {
      light: ['#eff1f5', '#e6e9ef', '#8839ef', '#179299'],
      dark: ['#1e1e2e', '#252538', '#cba6f7', '#94e2d5'],
    },
  },
  {
    id: 'nord',
    name: 'Nord',
    swatches: {
      light: ['#eceff4', '#e5e9f0', '#436690', '#4f7d7a'],
      dark: ['#2e3440', '#3b4252', '#88c0d0', '#8fbcbb'],
    },
  },
  {
    id: 'tokyo-night',
    name: 'Tokyo Night',
    swatches: {
      light: ['#e1e2e7', '#d5d6db', '#2e7de9', '#007197'],
      dark: ['#1a1b26', '#24283b', '#7aa2f7', '#73daca'],
    },
  },
  {
    id: 'dracula',
    name: 'Dracula',
    swatches: {
      light: ['#f8f8f2', '#efefe7', '#6d44c9', '#1c854a'],
      dark: ['#282a36', '#343746', '#bd93f9', '#ff79c6'],
    },
  },
  {
    id: 'rose-pine',
    name: 'Rosé Pine',
    swatches: {
      light: ['#faf4ed', '#f2e9e1', '#9f4f68', '#286983'],
      dark: ['#191724', '#26233a', '#ebbcba', '#c4a7e7'],
    },
  },
] as const

const VALID_THEME_IDS = new Set<string>(THEMES.map((t) => t.id))

export const currentTheme = ref<ThemeId>('default')

let storageListenerBound = false

export function isValidTheme(value: unknown): value is ThemeId {
  return typeof value === 'string' && VALID_THEME_IDS.has(value)
}

export function applyThemeToDom(id: ThemeId): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (id === 'default') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', id)
  }
}

export function setTheme(id: ThemeId): void {
  const next: ThemeId = isValidTheme(id) ? id : 'default'
  currentTheme.value = next
  applyThemeToDom(next)
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // Ignore storage errors (private browsing / restricted storage)
    }
  }
}

function handleStorageEvent(event: StorageEvent): void {
  if (event.key !== null && event.key !== THEME_STORAGE_KEY) return
  const next: ThemeId = isValidTheme(event.newValue) ? event.newValue : 'default'
  currentTheme.value = next
  applyThemeToDom(next)
}

export function initTheme(): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return

  let stored: string | null = null
  try {
    stored = window.localStorage.getItem(THEME_STORAGE_KEY)
  } catch {
    stored = null
  }

  const domAttr = document.documentElement.getAttribute('data-theme')
  const resolved: ThemeId = isValidTheme(stored)
    ? stored
    : isValidTheme(domAttr)
      ? domAttr
      : 'default'

  currentTheme.value = resolved
  applyThemeToDom(resolved)

  if (!storageListenerBound) {
    window.addEventListener('storage', handleStorageEvent)
    storageListenerBound = true
  }
}
