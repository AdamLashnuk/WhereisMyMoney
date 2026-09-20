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
    if (error instanceof TypeError || error.message === 'Network request failed') {
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

export function logVoiceExpense(uri) {
  if (!uri) throw new Error('Recording was empty. Please try again.');
  const name = voiceFilename(uri);
  const form = new FormData();
  form.append('source', 'voice');
  form.append('file', { uri, name, type: voiceMime(name) });
  // React Native supplies the multipart boundary. Do not set Content-Type.
  return request('/log-expense', { method: 'POST', body: form });
}

export function logReceiptText(text) {
  if (!text.trim()) throw new Error('Enter the receipt details first.');
  const form = new FormData();
  form.append('source', 'receipt');
  form.append('text', text.trim());
  return request('/log-expense', { method: 'POST', body: form });
}

export function logReceiptPhoto(photo) {
  if (!photo?.uri) throw new Error('Take a receipt photo first.');
  const form = new FormData();
  form.append('source', 'receipt');
  form.append('file', {
    uri: photo.uri,
    name: photo.fileName || 'receipt.jpg',
    type: photo.mimeType || 'image/jpeg',
  });
  return request('/log-expense', { method: 'POST', body: form });
}
