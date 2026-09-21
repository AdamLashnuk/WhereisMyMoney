import { API_BASE_URL } from './config';
import { File, UploadType } from 'expo-file-system';

async function parseJsonBody(body) {
  if (body == null || body === '') return {};
  if (typeof body === 'object') return body;
  try {
    return JSON.parse(String(body));
  } catch {
    return {};
  }
}

async function requestJson(path, options = {}) {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const details = data.error || data.detail;
      throw new Error(typeof details === 'string' ? details : `Server error (${response.status})`);
    }
    return data;
  } catch (error) {
    const message = String(error?.message || error);
    if (
      error instanceof TypeError
      || message === 'Network request failed'
      || /Failed to fetch|NetworkError/i.test(message)
    ) {
      throw new Error('Cannot reach the backend. Check that your iPhone and Sebastian’s server are on the same Wi-Fi.');
    }
    throw error;
  }
}

function postJSON(path, body) {
  return requestJson(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * Native multipart upload — avoids Expo fetch FormDataPart errors entirely.
 */
async function uploadExpenseFile({ source, uri, parameters = {} }) {
  if (!uri) throw new Error('Missing local file URI.');
  const file = new File(uri);
  const task = file.createUploadTask(`${API_BASE_URL}/log-expense`, {
    uploadType: UploadType.MULTIPART,
    fieldName: 'file',
    mimeType: guessMime(uri, source),
    parameters: { source, ...parameters },
  });
  const result = await task.uploadAsync();
  const status = result?.status ?? result?.statusCode ?? 0;
  const data = await parseJsonBody(result?.body);
  if (status < 200 || status >= 300) {
    const details = data.error || data.detail;
    throw new Error(typeof details === 'string' ? details : `Server error (${status})`);
  }
  return data;
}

function guessMime(uri, source) {
  const lower = String(uri).split('?')[0].toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.webp')) return 'image/webp';
  if (lower.endsWith('.heic') || lower.endsWith('.heif')) return 'image/heic';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.wav')) return 'audio/wav';
  if (lower.endsWith('.mp3')) return 'audio/mpeg';
  if (lower.endsWith('.webm')) return 'audio/webm';
  if (source === 'receipt') return 'image/jpeg';
  return 'audio/mp4';
}

export const getExpenses = () => requestJson('/expenses');
export const getLimits = () => requestJson('/limits');
export const saveLimit = (category, limitCents) => postJSON('/limits', { category, limitCents });
export const getSettings = () => requestJson('/settings');
export const saveSettings = (settings) => postJSON('/settings', settings);
export const getHealth = () => requestJson('/health');

export function triggerWeeklyCall(phoneNumber) {
  const body = { kind: 'weekly_summary' };
  const trimmed = typeof phoneNumber === 'string' ? phoneNumber.trim() : '';
  if (trimmed) body.phoneNumber = trimmed;
  return postJSON('/trigger-call', body);
}

export function logTextExpense(text) {
  const form = new FormData();
  form.append('source', 'voice');
  form.append('text', text);
  return requestJson('/log-expense', { method: 'POST', body: form });
}

export function logVoiceExpense(uri) {
  if (!uri) throw new Error('Recording was empty. Please try again.');
  return uploadExpenseFile({ source: 'voice', uri });
}

export function logReceiptText(text) {
  if (!text.trim()) throw new Error('Enter the receipt details first.');
  const form = new FormData();
  form.append('source', 'receipt');
  form.append('text', text.trim());
  return requestJson('/log-expense', { method: 'POST', body: form });
}

export function logReceiptPhoto(photo) {
  if (!photo?.uri) throw new Error('Take a receipt photo first.');
  return uploadExpenseFile({ source: 'receipt', uri: photo.uri });
}
