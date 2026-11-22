import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'windowping',
  description:
    'Keep Codex, Command Code, GLM Coding Plan, Claude Code, Kimi and MiniMax 5-hour rate-limit windows back-to-back.',
  base: '/windowping/',
  cleanUrls: true,

  head: [
    ['link', { rel: 'icon', href: '/windowping/logo.svg', type: 'image/svg+xml' }],
    [
      'script',
      { id: 'check-color-theme' },
      "(()=>{try{const t=localStorage.getItem('ooodnakov-docs-theme');if(t&&/^(solarized|gruvbox|catppuccin|nord|tokyo-night|dracula|rose-pine)$/.test(t))document.documentElement.setAttribute('data-theme',t)}catch{}})()",
    ],
  ],

  themeConfig: {
    logo: '/logo.svg',

    search: {
      provider: 'local',
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/ooodnakov/windowping' },
    ],

    nav: [
      { text: 'Guide', link: '/guide/what-it-does' },
      { text: 'Providers', link: '/providers/overview' },
      { text: 'Config', link: '/config/reference' },
      { text: 'Operations', link: '/operations/telegram' },
      { text: 'Changelog', link: '/reference/changelog' },
      { text: 'PyPI', link: 'https://pypi.org/project/windowping/' },
    ],

    sidebar: [
      {
        text: 'Getting Started',
        items: [
          { text: 'What It Does', link: '/guide/what-it-does' },
          { text: 'Install', link: '/guide/install' },
          { text: 'CLI Usage', link: '/guide/usage' },
        ],
      },
      {
        text: 'Providers',
        items: [
          { text: 'Supported Providers', link: '/providers/overview' },
          { text: 'Codex Ping Modes', link: '/providers/codex' },
          { text: 'Claude Code & API Ping', link: '/providers/claude' },
          { text: 'Provider Research', link: '/providers/research' },
        ],
      },
      {
        text: 'Configuration',
        items: [
          { text: 'Config Reference', link: '/config/reference' },
          { text: 'Per-Provider Schedules', link: '/config/schedules' },
        ],
      },
      {
        text: 'Operations',
        items: [
          { text: 'Telegram & Live Card', link: '/operations/telegram' },
          { text: 'Stats & Morning Digest', link: '/operations/stats-digest' },
          { text: 'Doctor & Diagnostics', link: '/operations/doctor' },
          { text: 'systemd Service', link: '/operations/systemd' },
        ],
      },
      {
        text: 'Internals & Reference',
        items: [
          { text: 'Decision Engine', link: '/reference/decision-engine' },
          { text: 'Adding a Provider & Tests', link: '/reference/developing' },
          { text: 'Changelog', link: '/reference/changelog' },
        ],
      },
    ],

    editLink: {
      pattern: 'https://github.com/ooodnakov/windowping/edit/master/site/:path',
      text: 'Edit this page on GitHub',
    },

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © Aleksandr Odnakov',
    },
  },
})
