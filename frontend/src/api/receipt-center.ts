/**
 * 分发回执中心专用接口：来件核对、签收核销、更正受理、分发任务结算。
 * 与通用 backend-service 的资源接口并存，操作均带 operator 做服务端权限收敛。
 */
import { request } from './client'

export type OperatorRole = '值班员' | '订阅方A' | '订阅方B'

export type SignoffForm = {
  operator: string
  实际收件主体: string
  签收凭证号: string
  签收版本: string
  签收行数: number | null
  差异说明?: string
}

export type CorrectionForm = {
  更正凭证号: string
  更正说明: string
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return (await response.json()) as T
}

function qs(params: Record<string, string>): string {
  const query = new URLSearchParams(params).toString()
  return query ? `?${query}` : ''
}

export type ReceiptResult = {
  ok: boolean
  code?: string
  message: string
  entry?: Record<string, unknown>
  writeoff_token?: string
  duplicate_of?: number
  correction?: Record<string, unknown>
  settle?: Record<string, unknown>
}

export async function fetchIncoming(operator: string | null, status?: string) {
  const params: Record<string, string> = {}
  if (operator) params.operator = operator
  if (status) params.status = status
  const response = await request(`/api/dist_receipt/incoming${qs(params)}`)
  return (await response.json()) as {
    items: Record<string, unknown>[]
    total: number
  }
}

export async function fetchIncomingDetail(id: number, operator: string | null) {
  const params: Record<string, string> = {}
  if (operator) params.operator = operator
  const response = await request(`/api/dist_receipt/incoming/${id}${qs(params)}`)
  return (await response.json()) as {
    entry: Record<string, unknown>
    correction: Record<string, unknown> | null
  }
}

export function submitSignoff(id: number, form: SignoffForm): Promise<ReceiptResult> {
  return postJson(`/api/dist_receipt/incoming/${id}/signoff`, form)
}

export function markReturn(
  id: number,
  operator: string,
  reason: string,
): Promise<ReceiptResult> {
  return postJson(`/api/dist_receipt/incoming/${id}/return`, { operator, reason })
}

export function submitCorrection(
  id: number,
  operator: string,
  form: CorrectionForm,
): Promise<ReceiptResult> {
  return postJson(`/api/dist_receipt/incoming/${id}/corrections`, {
    operator,
    更正凭证号: form.更正凭证号,
    更正说明: form.更正说明,
  })
}

export async function fetchCorrections(operator: string | null) {
  const params: Record<string, string> = {}
  if (operator) params.operator = operator
  const response = await request(`/api/dist_receipt/corrections${qs(params)}`)
  return (await response.json()) as { items: Record<string, unknown>[] }
}

export function reviewCorrection(
  id: number,
  decision: 'accept' | 'reject',
  note: string,
): Promise<ReceiptResult> {
  return postJson(`/api/dist_receipt/corrections/${id}/review`, { decision, note })
}

export function resubmitCorrection(
  id: number,
  operator: string,
  voucher: string,
): Promise<ReceiptResult> {
  return postJson(`/api/dist_receipt/corrections/${id}/resubmit`, {
    operator,
    更正凭证号: voucher,
  })
}

export function settleTask(taskId: number): Promise<ReceiptResult> {
  return postJson(`/api/dist_receipt/tasks/${taskId}/settle`, {})
}
