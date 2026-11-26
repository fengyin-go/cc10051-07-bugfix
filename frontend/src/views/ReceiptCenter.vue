<template>
  <section class="page receipt-center" data-module="dist_receipt">
    <header class="page-head">
      <div>
        <h2>分发回执中心 · 签收核对</h2>
        <p class="page-desc">
          分发号与实际收件主体共同决定签收资格；签收版本、行数须与原发件核验，
          差异归本件处理，不冲销其他订阅方的成功发放。
        </p>
      </div>
      <div class="role-switch">
        <span class="role-label">当前身份</span>
        <button
          v-for="role in roles"
          :key="role"
          type="button"
          class="btn"
          :class="{ primary: role === activeRole }"
          :data-testid="`role-${role}`"
          @click="switchRole(role)"
        >
          {{ role }}
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">有权查看来件</span>
        <strong class="stat-value">{{ rows.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待签收</span>
        <strong class="stat-value">{{ countByStage('待签收') }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已核销</span>
        <strong class="stat-value">{{ countByStage('已核销') }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">差异/退回</span>
        <strong class="stat-value">{{ countDiff() }}</strong>
      </article>
    </div>

    <div class="receipt-layout">
      <div class="incoming-list">
        <h3>来件列表（{{ scopeText }}）</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>回执编号</th>
              <th>分发批次</th>
              <th>实际收件主体</th>
              <th>处理阶段</th>
              <th>差异类型</th>
              <th>核销凭据</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="Number(row.id)"
              :data-testid="`incoming-row-${row.id}`"
              :class="{ selected: selectedId === Number(row.id) }"
              @click="openDetail(Number(row.id))"
            >
              <td>{{ row.回执编号 }}</td>
              <td>{{ row.分发批次 }}</td>
              <td>{{ row.实际收件主体 }}</td>
              <td>{{ row.处理阶段 }}</td>
              <td>{{ row.差异类型 || '—' }}</td>
              <td>{{ row.核销凭据号 || '—' }}</td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="6" class="empty-state">当前身份没有可查看的来件</td>
            </tr>
          </tbody>
        </table>

        <div v-if="isOperator" class="correction-queue">
          <h3>更正队列（值班员）</h3>
          <table class="data-table">
            <thead>
              <tr>
                <th>更正单号</th>
                <th>申请主体</th>
                <th>关联来件</th>
                <th>关联任务</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in corrections" :key="Number(c.id)">
                <td>{{ c.更正单号 }}</td>
                <td>{{ c.申请主体 }}</td>
                <td>{{ c.回执编号 }}</td>
                <td>{{ c.关联分发任务 ?? '—' }}</td>
                <td :data-testid="`correction-state-${c.id}`">{{ c.更正状态 }}</td>
                <td class="row-actions">
                  <button
                    v-if="c.更正状态 === '待受理'"
                    type="button"
                    class="link"
                    data-testid="correction-accept"
                    @click="review(Number(c.id), 'accept')"
                  >受理</button>
                  <button
                    v-if="c.更正状态 === '待受理'"
                    type="button"
                    class="link"
                    data-testid="correction-reject"
                    @click="review(Number(c.id), 'reject')"
                  >要求补交</button>
                </td>
              </tr>
              <tr v-if="!corrections.length">
                <td colspan="6" class="empty-state">暂无更正单</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <aside class="incoming-detail" v-if="detail">
        <h3>来件详情</h3>
        <dl class="detail-grid">
          <dt>回执编号</dt><dd>{{ detail.entry.回执编号 }}</dd>
          <dt>分发批次</dt><dd>{{ detail.entry.分发批次 }}</dd>
          <dt>实际收件主体</dt><dd>{{ detail.entry.实际收件主体 }}</dd>
          <dt>发件凭证号</dt><dd>{{ detail.entry.发件凭证号 || '—' }}</dd>
          <dt>处理阶段</dt><dd>{{ detail.entry.处理阶段 }}</dd>
          <dt>差异类型</dt><dd>{{ detail.entry.差异类型 || '—' }}</dd>
          <dt>签收凭证号</dt><dd>{{ detail.entry.签收凭证号 || '—' }}</dd>
          <dt>签收版本/行数</dt>
          <dd>{{ detail.entry.签收版本 || '—' }} / {{ detail.entry.签收行数 ?? '—' }}</dd>
          <dt>核销凭据号</dt>
          <dd :data-testid="writeoffTestid">{{ detail.entry.核销凭据号 || '尚未核销' }}</dd>
          <dt>差异说明</dt><dd>{{ detail.entry.差异说明 || '—' }}</dd>
        </dl>

        <div v-if="detail.correction" class="correction-banner" :data-testid="correctionBannerTestid">
          关联更正单 {{ detail.correction.更正单号 }}：
          <strong>{{ detail.correction.更正状态 }}</strong>
          <span v-if="detail.correction.关联发件凭证号">
            （已关联发件凭证 {{ detail.correction.关联发件凭证号 }}）
          </span>
        </div>

        <!-- 订阅方在自己的来件详情提交实际签收归属 -->
        <form
          v-if="canSign"
          class="signoff-form"
          data-testid="signoff-form"
          @submit.prevent="doSignoff"
        >
          <h4>提交实际签收归属</h4>
          <label class="create-field">
            <span>实际收件主体</span>
            <input v-model="signoffForm.实际收件主体" data-testid="sign-recipient" required />
          </label>
          <label class="create-field">
            <span>签收凭证号</span>
            <input v-model="signoffForm.签收凭证号" data-testid="sign-voucher" required />
          </label>
          <label class="create-field">
            <span>签收版本（须与原发件一致）</span>
            <input v-model="signoffForm.签收版本" data-testid="sign-version" required />
          </label>
          <label class="create-field">
            <span>签收行数（须与原发件一致）</span>
            <input
              v-model.number="signoffForm.签收行数"
              data-testid="sign-rows"
              type="number"
              required
            />
          </label>
          <button class="btn primary" data-testid="submit-signoff" type="submit">提交签收核对</button>
        </form>

        <!-- 订阅方退回 / 更正 -->
        <div v-if="isOwner" class="owner-actions">
          <button
            v-if="detail.entry.处理阶段 === '待签收'"
            type="button"
            class="btn"
            data-testid="mark-return"
            @click="doReturn"
          >收件时退回</button>
          <button
            v-if="canCorrect"
            type="button"
            class="btn"
            data-testid="open-correction"
            @click="showCorrection = true"
          >以此原件提交更正</button>
        </div>

        <!-- 补交凭证（需补交状态） -->
        <form
          v-if="resubmitTarget"
          class="signoff-form"
          data-testid="resubmit-form"
          @submit.prevent="doResubmit"
        >
          <h4>补交更正凭证</h4>
          <label class="create-field">
            <span>新更正凭证号</span>
            <input v-model="resubmitVoucher" data-testid="resubmit-voucher" required />
          </label>
          <button class="btn primary" type="submit">补交并重新受理</button>
        </form>

        <!-- 更正提交弹窗 -->
        <div v-if="showCorrection" class="modal-backdrop" data-testid="correction-modal">
          <form class="modal" @submit.prevent="doSubmitCorrection">
            <h3>提交签收更正</h3>
            <p class="page-desc">以错填原件为依据，差异归本件；已办理的差异不能二次更正。</p>
            <label class="create-field">
              <span>更正凭证号</span>
              <input v-model="correctionForm.更正凭证号" data-testid="correction-voucher" required />
            </label>
            <label class="create-field">
              <span>更正说明</span>
              <input v-model="correctionForm.更正说明" data-testid="correction-note" required />
            </label>
            <div class="page-actions">
              <button type="button" class="btn" @click="showCorrection = false">取消</button>
              <button type="submit" class="btn primary" data-testid="submit-correction">提交更正</button>
            </div>
          </form>
        </div>
      </aside>
    </div>

    <footer class="page-foot">
      <span v-if="message" :class="lastOk ? '' : 'error-text'" data-testid="receipt-message">
        {{ message }}
      </span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  fetchCorrections,
  fetchIncoming,
  fetchIncomingDetail,
  markReturn,
  resubmitCorrection,
  reviewCorrection,
  submitCorrection,
  submitSignoff,
  type OperatorRole,
  type SignoffForm,
} from '@/api/receipt-center'

type Row = Record<string, unknown>

const roles: OperatorRole[] = ['值班员', '订阅方A', '订阅方B']
const activeRole = ref<OperatorRole>('值班员')
const rows = ref<Row[]>([])
const corrections = ref<Row[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<{ entry: Row; correction: Row | null } | null>(null)
const message = ref('')
const lastOk = ref(true)
const showCorrection = ref(false)
const resubmitTarget = ref<Row | null>(null)
const resubmitVoucher = ref('')

const emptySignoff = (): SignoffForm => ({
  operator: '',
  实际收件主体: '',
  签收凭证号: '',
  签收版本: '',
  签收行数: null,
})
const signoffForm = ref<SignoffForm>(emptySignoff())
const correctionForm = ref({ 更正凭证号: '', 更正说明: '' })

const isOperator = computed(() => activeRole.value === '值班员')
const scopeText = computed(() =>
  isOperator.value ? '全部来件（值班员视角）' : `仅 ${activeRole.value} 自己的凭证`,
)

const operatorParam = computed(() => (isOperator.value ? null : activeRole.value))

const isOwner = computed(
  () => !!detail.value && !isOperator.value
    && detail.value.entry.实际收件主体 === activeRole.value,
)
const canSign = computed(
  () => isOwner.value && detail.value?.entry.处理阶段 !== '已核销',
)
const canCorrect = computed(
  () => isOwner.value && !detail.value?.correction
    && detail.value?.entry.处理阶段 !== '已核销',
)
const writeoffTestid = computed(() => `writeoff-${selectedId.value ?? 'none'}`)
const correctionBannerTestid = computed(
  () => `correction-banner-${selectedId.value ?? 'none'}`,
)
function countByStage(stage: string): number {
  return rows.value.filter((row) => row.处理阶段 === stage).length
}
function countDiff(): number {
  return rows.value.filter(
    (row) => row.处理阶段 === '已驳回' || row.处理阶段 === '已退回',
  ).length
}

function notify(text: string, ok = true): void {
  message.value = text
  lastOk.value = ok
}

async function loadAll(): Promise<void> {
  try {
    const list = await fetchIncoming(operatorParam.value)
    rows.value = list.items
    const corr = await fetchCorrections(operatorParam.value)
    corrections.value = corr.items
    if (selectedId.value !== null) await openDetail(selectedId.value)
  } catch (error) {
    notify(error instanceof Error ? error.message : '数据加载失败', false)
  }
}

async function switchRole(role: OperatorRole): Promise<void> {
  activeRole.value = role
  selectedId.value = null
  detail.value = null
  resubmitTarget.value = null
  await loadAll()
}

async function openDetail(id: number): Promise<void> {
  selectedId.value = id
  resubmitTarget.value = null
  try {
    detail.value = await fetchIncomingDetail(id, operatorParam.value)
    signoffForm.value = {
      operator: activeRole.value,
      实际收件主体: String(detail.value.entry.实际收件主体 ?? ''),
      签收凭证号: '',
      签收版本: '',
      签收行数: null,
    }
    const corr = detail.value.correction
    if (corr && corr.申请主体 === activeRole.value && corr.更正状态 === '需补交凭证') {
      resubmitTarget.value = corr
    }
  } catch (error) {
    notify(error instanceof Error ? error.message : '来件详情读取失败', false)
    detail.value = null
  }
}

async function doSignoff(): Promise<void> {
  if (selectedId.value === null) return
  const result = await submitSignoff(selectedId.value, {
    ...signoffForm.value,
    operator: activeRole.value,
  })
  notify(result.message, result.ok)
  await loadAll()
}

async function doReturn(): Promise<void> {
  if (selectedId.value === null) return
  const reason = window.prompt('请输入收件时退回原因', '收件时退回') ?? ''
  if (!reason) return
  const result = await markReturn(selectedId.value, activeRole.value, reason)
  notify(result.message, result.ok)
  await loadAll()
}

async function doSubmitCorrection(): Promise<void> {
  if (selectedId.value === null) return
  const result = await submitCorrection(selectedId.value, activeRole.value, correctionForm.value)
  showCorrection.value = false
  notify(result.message, result.ok)
  correctionForm.value = { 更正凭证号: '', 更正说明: '' }
  await loadAll()
}

async function review(id: number, decision: 'accept' | 'reject'): Promise<void> {
  const note = window.prompt(decision === 'accept' ? '受理说明（可空）' : '驳回/补交说明（可空）', '') ?? ''
  const result = await reviewCorrection(id, decision, note)
  notify(result.message, result.ok)
  await loadAll()
}

async function doResubmit(): Promise<void> {
  if (!resubmitTarget.value) return
  const result = await resubmitCorrection(
    Number(resubmitTarget.value.id),
    activeRole.value,
    resubmitVoucher.value,
  )
  notify(result.message, result.ok)
  resubmitVoucher.value = ''
  resubmitTarget.value = null
  await loadAll()
}

onMounted(loadAll)
</script>

<style scoped>
.role-switch { display: flex; gap: 6px; align-items: center; }
.role-label { font-size: 12px; color: var(--muted); margin-right: 4px; }
.receipt-layout { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, 1fr); gap: 16px; }
.incoming-list h3,
.incoming-detail h3 { margin: 8px 0; font-size: 15px; }
.data-table tr.selected { background: #eff6ff; cursor: pointer; }
.data-table tbody tr { cursor: pointer; }
.incoming-detail { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 14px; align-self: start; }
.detail-grid { display: grid; grid-template-columns: 110px 1fr; gap: 6px 10px; margin: 0 0 12px; }
.detail-grid dt { font-size: 12px; color: var(--muted); }
.detail-grid dd { margin: 0; font-size: 13px; }
.correction-banner { background: #fffbeb; border: 1px solid #fcd34d; border-radius: 6px; padding: 8px 10px; font-size: 13px; margin-bottom: 12px; }
.signoff-form { border-top: 1px solid var(--border); padding-top: 12px; margin-top: 8px; }
.signoff-form h4 { margin: 0 0 8px; font-size: 14px; }
.owner-actions { display: flex; gap: 8px; margin-top: 12px; }
.correction-queue { margin-top: 20px; }
@media (max-width: 980px) {
  .receipt-layout { grid-template-columns: 1fr; }
}
</style>
