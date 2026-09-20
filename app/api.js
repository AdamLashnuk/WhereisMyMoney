import { API_BASE_URL } from './config';

async function request(path, options = {}) {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const details = data.error || data.detail;
      throw new Error(typeof details === 'string' ? details : `Server error (${response.status})`);
    }
    return data;
  } catch (error) {
    if (
      error instanceof TypeError
      || error.message === 'Network request failed'
      || /Unsupported FormDataPart/i.test(String(error?.message || error))
    ) {
      if (/Unsupported FormDataPart/i.test(String(error?.message || error))) {
        throw new Error('Could not upload that file from Expo. Reload the app and try again.');
      }
      throw new Error('Cannot reach the backend. Check that your iPhone and Sebastian’s server are on the same Wi-Fi.');
    }
    throw error;
  }
}

function postJSON(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** Expo global fetch rejects RN {uri,name,type} FormData parts — convert to Blob/File. */
async function appendLocalFile(form, field, uri, name, mime) {
  const response = await fetch(uri);
  if (!response.ok) {
    throw new Error('Could not read the local file for upload.');
  }
  const blob = await response.blob();
  const type = mime || blob.type || 'application/octet-stream';
  try {
    if (typeof File !== 'undefined') {
      form.append(field, new File([blob], name, { type }));
      return;
    }
  } catch (_) {
    // fall through to blob + filename
  }
  form.append(field, blob, name);
}

export const getExpenses = () => request('/expenses');
export const getLimits = () => request('/limits');
export const saveLimit = (category, limitCents) => postJSON('/limits', { category, limitCents });
export const getSettings = () => request('/settings');
export const saveSettings = (settings) => postJSON('/settings', settings);
export const getHealth = () => request('/health');
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
  return request('/log-expense', { method: 'POST', body: form });
}

function voiceFilename(uri) {
  const last = String(uri).split('?')[0].split('/').pop() || '';
  if (/\.(m4a|mp4|wav|mp3|aac|caf|webm|ogg)$/i.test(last)) return last;
  return 'expense.m4a';
}

function voiceMime(name) {
  const lower = String(name).toLowerCase();
  if (lower.endsWith('.wav')) return 'audio/wav';
  if (lower.endsWith('.mp3')) return 'audio/mpeg';
  if (lower.endsWith('.webm')) return 'audio/webm';
  if (lower.endsWith('.ogg')) return 'audio/ogg';
  if (lower.endsWith('.aac')) return 'audio/aac';
  if (lower.endsWith('.caf')) return 'audio/x-caf';
  return 'audio/mp4';
}

export async function logVoiceExpense(uri) {
  if (!uri) throw new Error('Recording was empty. Please try again.');
  const name = voiceFilename(uri);
  const form = new FormData();
  form.append('source', 'voice');
  await appendLocalFile(form, 'file', uri, name, voiceMime(name));
  // Do not set Content-Type — fetch must set the multipart boundary.
  return request('/log-expense', { method: 'POST', body: form });
}

export function logReceiptText(text) {
  if (!text.trim()) throw new Error('Enter the receipt details first.');
  const form = new FormData();
  form.append('source', 'receipt');
  form.append('text', text.trim());
  return request('/log-expense', { method: 'POST', body: form });
}

export async function logReceiptPhoto(photo) {
  if (!photo?.uri) throw new Error('Take a receipt photo first.');
  const name = photo.fileName || 'receipt.jpg';
  const mime = photo.mimeType || 'image/jpeg';
  const form = new FormData();
  form.append('source', 'receipt');
  await appendLocalFile(form, 'file', photo.uri, name, mime);
  return request('/log-expense', { method: 'POST', body: form });
}
