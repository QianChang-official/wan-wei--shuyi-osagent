/* gf 组件内部共享：主题与花瓣偏好的读写（不对外暴露为组件） */

export const GF_THEME_KEY = 'gf-theme'
export const GF_PETALS_KEY = 'gf-petals'
export const GF_PETALS_EVENT = 'gf-petals-change'

export type GfTheme = 'day' | 'night'

export function getTheme(): GfTheme {
  try {
    return localStorage.getItem(GF_THEME_KEY) === 'night' ? 'night' : 'day'
  } catch {
    return 'day'
  }
}

export function applyTheme(t: GfTheme) {
  document.documentElement.dataset.theme = t
  try {
    localStorage.setItem(GF_THEME_KEY, t)
  } catch {
    /* 隐私模式等场景下静默失败 */
  }
}

export function getPetalsEnabled(): boolean {
  try {
    return localStorage.getItem(GF_PETALS_KEY) !== 'off'
  } catch {
    return true
  }
}

export function setPetalsEnabled(on: boolean) {
  try {
    localStorage.setItem(GF_PETALS_KEY, on ? 'on' : 'off')
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent<boolean>(GF_PETALS_EVENT, { detail: on }))
}
