<script setup lang="ts">
import { ref, computed } from 'vue'
import { readResourceFile, writeResourceFile } from '@/api/skillStore'
import ResourceTreeNode from './ResourceTreeNode.vue'
import BaseModal from '@/components/BaseModal.vue'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { toast } from '@/composables/useToast'
import { fileIconUrl, type ResTreeNode } from './resourceTree'

interface ResEntry {
  path?: string
  description?: string
}

/** 单文件读取结果（与 @/api/skillStore.readResourceFile 形状一致）。 */
interface FileLoadResult {
  success: boolean
  encoding: 'utf8' | 'base64'
  content: string
  is_binary: boolean
  size: number
  error?: string
}

const props = defineProps<{
  skillId: string
  resources: { scripts?: ResEntry[]; references?: ResEntry[]; assets?: ResEntry[] } | null | undefined
  readonly?: boolean
  // 可选：自定义文件读取器（如市场快照），不传则走默认的个人/团队 Skill 接口。
  fileLoader?: (path: string) => Promise<FileLoadResult>
}>()

const CATS = [
  { key: 'scripts', label: 'Scripts' },
  { key: 'references', label: 'References' },
  { key: 'assets', label: 'Assets' },
] as const

type CatKey = (typeof CATS)[number]['key']

function entriesFor(cat: CatKey): ResEntry[] {
  const list = props.resources?.[cat]
  return Array.isArray(list) ? (list as ResEntry[]) : []
}

function sortNodes(nodes: ResTreeNode[]) {
  nodes.sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0
  })
  for (const n of nodes) if (n.children) sortNodes(n.children)
}

// 由扁平 path（含分类前缀，如 scripts/sub/foo.py）构建文件夹树，去掉首段分类前缀展示。
function buildTree(files: ResEntry[]): ResTreeNode[] {
  const root: ResTreeNode = { name: '', path: '', isDir: true, children: [] }
  for (const f of files) {
    const full = (f.path || '').replace(/\\/g, '/').replace(/^\/+/, '')
    if (!full) continue
    const all = full.split('/')
    const cat = all[0]
    const segs = all.slice(1)
    if (segs.length === 0) continue
    let node = root
    let acc = cat
    segs.forEach((seg, i) => {
      acc += '/' + seg
      const isLast = i === segs.length - 1
      if (isLast) {
        if (!node.children!.some((c) => c.name === seg && !c.isDir)) {
          node.children!.push({ name: seg, path: acc, isDir: false })
        }
      } else {
        let child = node.children!.find((c) => c.name === seg && c.isDir)
        if (!child) {
          child = { name: seg, path: acc, isDir: true, children: [] }
          node.children!.push(child)
        }
        node = child
      }
    })
  }
  sortNodes(root.children!)
  return root.children!
}

const trees = computed<Record<CatKey, ResTreeNode[]>>(() => ({
  scripts: buildTree(entriesFor('scripts')),
  references: buildTree(entriesFor('references')),
  assets: buildTree(entriesFor('assets')),
}))

// ---- 文件编辑器（弹窗）----
const editorOpen = ref(false)
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
// errorMsg 仅用于「文件整体读取失败」时的正文占位状态；保存结果改用全局弹窗反馈。
const errorMsg = ref('')
const curPath = ref('')
const curEncoding = ref<'utf8' | 'base64'>('utf8')
const curContent = ref('')
const isBinary = ref(false)
const curSize = ref(0)

const isImage = computed(() => /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i.test(curPath.value))
const isSvg = computed(() => /\.svg$/i.test(curPath.value))

const imageSrc = computed(() => {
  if (isSvg.value && !isBinary.value) {
    return `data:image/svg+xml;utf8,${encodeURIComponent(curContent.value)}`
  }
  if (isBinary.value && isImage.value) {
    const ext = (curPath.value.split('.').pop() || 'png').toLowerCase()
    const mime = ext === 'jpg' ? 'jpeg' : ext === 'svg' ? 'svg+xml' : ext
    return `data:image/${mime};base64,${curContent.value}`
  }
  return ''
})

async function openFile(path: string) {
  editorOpen.value = true
  loading.value = true
  errorMsg.value = ''
  dirty.value = false
  curPath.value = path
  curContent.value = ''
  isBinary.value = false
  curSize.value = 0
  try {
    const res = props.fileLoader
      ? await props.fileLoader(path)
      : await readResourceFile(props.skillId, path)
    if (!res.success) {
      errorMsg.value = res.error || '读取失败'
      return
    }
    curEncoding.value = res.encoding
    curContent.value = res.content
    isBinary.value = res.is_binary
    curSize.value = res.size
  } catch (e: unknown) {
    errorMsg.value = (e as { message?: string })?.message || '读取失败'
  } finally {
    loading.value = false
  }
}

function onInput(e: Event) {
  curContent.value = (e.target as HTMLTextAreaElement).value
  dirty.value = true
}

const canSave = computed(
  () => !props.readonly && !isBinary.value && !loading.value && !saving.value && dirty.value,
)

async function save() {
  if (props.readonly || isBinary.value) return
  saving.value = true
  try {
    const res = await writeResourceFile(props.skillId, curPath.value, curContent.value, curEncoding.value)
    if (!res.success) {
      toast.error(res.error || '保存失败')
      return
    }
    dirty.value = false
    toast.success('已保存')
  } catch (e: unknown) {
    toast.error((e as { message?: string })?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function close() {
  if (dirty.value) {
    const ok = await confirmDialog({
      title: '关闭编辑',
      message: '有未保存的修改，确定关闭吗？',
      confirmText: '关闭',
      danger: true,
    })
    if (!ok) return
  }
  editorOpen.value = false
}

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <div class="rfp">
    <div v-for="cat in CATS" :key="cat.key" class="rfp-cat">
      <h4 class="rfp-cat-title">{{ cat.label }}</h4>
      <div v-if="trees[cat.key].length === 0" class="rfp-empty">暂无文件</div>
      <div v-else class="rfp-tree">
        <ResourceTreeNode
          v-for="n in trees[cat.key]"
          :key="n.path"
          :node="n"
          :depth="0"
          :active-path="curPath"
          @select="openFile"
        />
      </div>
    </div>

    <!-- File editor modal -->
    <BaseModal
      :model-value="editorOpen"
      :title="curPath.split('/').pop() || '文件'"
      :width="860"
      @update:model-value="close"
    >
      <div class="rfp-modal-titlebar">
        <img class="rfp-modal-icon" :src="fileIconUrl(curPath.split('/').pop() || '')" alt="" aria-hidden="true" />
        <span class="rfp-modal-path" :title="curPath">{{ curPath }}</span>
        <span v-if="curSize" class="rfp-modal-size">{{ fmtSize(curSize) }}</span>
      </div>

      <div class="rfp-modal-body">
        <div v-if="loading" class="rfp-state">加载中…</div>
        <div v-else-if="errorMsg && !curContent && !imageSrc" class="rfp-state rfp-err">{{ errorMsg }}</div>
        <template v-else>
          <div v-if="imageSrc" class="rfp-preview">
            <img :src="imageSrc" :alt="curPath" />
          </div>
          <textarea
            v-if="!isBinary"
            class="rfp-editor"
            :value="curContent"
            spellcheck="false"
            :placeholder="readonly ? '只读' : '在此编辑文件内容…'"
            :readonly="readonly"
            @input="onInput"
          ></textarea>
          <div v-else-if="!imageSrc" class="rfp-state">二进制文件，暂不支持在线编辑（{{ fmtSize(curSize) }}）</div>
        </template>
      </div>

      <template v-if="!isBinary && !readonly" #footer>
        <span v-if="dirty" class="rfp-foot-msg rfp-dirty">未保存</span>
        <span class="rfp-foot-spacer"></span>
        <button
          type="button"
          class="rfp-btn rfp-btn-primary"
          :disabled="!canSave"
          @click="save"
        >
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
.rfp {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.rfp-cat-title {
  margin: 0 0 0.6rem;
  font-size: 1rem;
  font-weight: 600;
  color: #151717;
}

.rfp-tree {
  background: #eef0f3;
  border: none;
  border-radius: 12px;
  padding: 0.35rem 0.4rem;
}

.rfp-empty {
  padding: 0.9rem 1rem;
  font-size: 0.86rem;
  color: #9ca3af;
  background: #eef0f3;
  border: none;
  border-radius: 12px;
}

/* Modal */
.rfp-modal-titlebar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.8rem;
  padding-bottom: 0.8rem;
  border-bottom: 1px solid #ebedf0;
}
.rfp-modal-icon {
  flex-shrink: 0;
  width: 1.15rem;
  height: 1.15rem;
  display: block;
  object-fit: contain;
}
.rfp-modal-path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
  font-weight: 600;
  color: #151717;
}
.rfp-modal-size {
  flex-shrink: 0;
  font-size: 0.78rem;
  color: #9ca3af;
}
.rfp-modal-body {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}

.rfp-state {
  padding: 2rem 1rem;
  text-align: center;
  color: #6b7280;
  font-size: 0.9rem;
}
.rfp-err { color: #dc2626; }
.rfp-dirty { color: #b45309; }

.rfp-preview {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 0.5rem;
  background: #eef0f3;
  border: none;
  border-radius: 10px;
}
.rfp-preview img {
  max-width: 100%;
  max-height: 320px;
  object-fit: contain;
}

.rfp-editor {
  flex: 1;
  min-height: 55vh;
  width: 100%;
  box-sizing: border-box;
  resize: none;
  padding: 0.85rem 1rem;
  border: none;
  border-radius: 10px;
  background: #eef0f3;
  color: #151717;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.88rem;
  line-height: 1.6;
  tab-size: 2;
}
.rfp-editor:focus {
  outline: none;
  background: #ffffff;
  box-shadow: inset 0 0 0 2px #151717;
}

.rfp-foot-msg { font-size: 0.84rem; }
.rfp-foot-spacer { flex: 1; }

.rfp-btn {
  padding: 0.5rem 1rem;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
  color: #374151;
  font-size: 0.88rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.rfp-btn:hover:not(:disabled) { border-color: #d1d5db; color: #151717; }
.rfp-btn-primary {
  background: #151717;
  border-color: #151717;
  color: #ffffff;
  font-weight: 600;
}
.rfp-btn-primary:hover:not(:disabled) { background: #2d2f2f; }
.rfp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
