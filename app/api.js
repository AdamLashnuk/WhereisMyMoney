import { API_BASE_URL } from './config';
import { fetch as expoFetch } from 'expo/fetch';
import { File } from 'expo-file-system';

async function parseResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const details = data.error || data.detail;
    throw new Error(typeof details === 'string' ? details : `Server error (${response.status})`);
  }
  return data;
}

async function request(path, options = {}) {
  try {
    const response = await expoFetch(`${API_BASE_URL}${path}`, options);
    return await parseResponse(response);
  } catch (error) {
    const message = String(error?.message || error);
    if (/Unsupported FormDataPart/i.test(message)) {
      throw new Error('Upload failed (FormData). On Person A laptop: git pull feat/app && cd app && npm i && npx expo start -c');
    }
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
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** Build a FormData file part Expo fetch accepts (not RN {uri,name,type}). */
async function appendLocalFile(form, field, uri, name, mime) {
  if (!uri) throw new Error('Missing local file URI.');
  try {
    form.append(field, new File(uri));
    return;
  } catch (_) {
    // fall through
  }
  const response = await expoFetch(uri);
  if (!response.ok) throw new Error('Could not read the local file for upload.');
  const blob = await response.blob();
  const type = mime || blob.type || 'application/octet-stream';
  try {
    form.append(field, new File([blob], name, { type }));
  } catch (_) {
    form.append(field, blob, name);
  }
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
