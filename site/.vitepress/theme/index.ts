import type { Theme } from 'vitepress'
import DefaultTheme from 'vitepress/theme'
import { h } from 'vue'
import ThemeSwitcher from './components/ThemeSwitcher.vue'
import WindowpingHeroPanel from './components/WindowpingHeroPanel.vue'
import './custom.css'
import './themes.css'

export default {
  extends: DefaultTheme,
  Layout() {
    return h(DefaultTheme.Layout, null, {
      'nav-bar-content-after': () => h(ThemeSwitcher, { variant: 'nav' }),
      'nav-screen-content-after': () => h(ThemeSwitcher, { variant: 'screen' }),
      'home-hero-image': () => h(WindowpingHeroPanel),
    })
  },
} satisfies Theme
