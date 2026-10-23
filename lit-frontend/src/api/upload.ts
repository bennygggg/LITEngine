import { apiBase, ApiError } from './client'

export interface UploadedDocument {
  text: string
  filename: string
  word_count: number
}

export const ACCEPTED = '.pdf,.docx,.txt'
export const MAX_BYTES = 20 * 1024 * 1024

/** Upload a document for text extraction. XHR rather than fetch because fetch has no upload progress. */
export function uploadDocument(file: File, onProgress: (fraction: number, phase: 'uploading' | 'extracting') => void, signal?: AbortSignal): Promise<UploadedDocument> {
  return new Promise((resolve, reject) => {
    if (file.size > MAX_BYTES) return reject(new ApiError('That file is over the 20 MB limit.', 400, 'too_large'))
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${apiBase()}/chat/upload`)
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total, 'uploading') }
    xhr.upload.onload = () => onProgress(1, 'extracting')
    xhr.onload = () => {
      let body: { detail?: string; text?: string; filename?: string; word_count?: number } = {}
      try { body = JSON.parse(xhr.responseText) } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300 && typeof body.text === 'string') return resolve(body as UploadedDocument)
      reject(new ApiError(body.detail || `Upload failed (${xhr.status}).`, xhr.status, 'upload_failed'))
    }
    xhr.onerror = () => reject(new ApiError('Could not reach the server. It may be waking up — try again in a moment.', 0, 'network'))
    xhr.ontimeout = () => reject(new ApiError('The upload timed out.', 0, 'timeout'))
    xhr.timeout = 120_000
    signal?.addEventListener('abort', () => { xhr.abort(); reject(new DOMException('Aborted', 'AbortError')) })
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}
