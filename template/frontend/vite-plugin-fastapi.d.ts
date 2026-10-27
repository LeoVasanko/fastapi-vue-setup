// auto-upgrade@fastapi-vue-setup -- remove this if you edit the plugin
import type { Plugin } from 'vite'

declare function fastapiVue(options?: { paths?: string[] }): Plugin

export default fastapiVue
