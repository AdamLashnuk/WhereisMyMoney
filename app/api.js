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
      throw new Error('Upload failed (FormData). Pull latest feat/app and restart Expo with npx expo start -c.');
    }
    if (error instanceof TypeError || message === 'Network request failed' || /Failed to fetch|NetworkError/i.test(message)) {
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

/**
 * Expo's fetch rejects React Native {uri,name,type} FormData parts.
 * Use expo-file-system File objects (supported by expo/fetch).
 */
function localFile(uri) {
  if (!uri) throw new Error('Missing local file URI.');
  return new File(uri);
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

export function logVoiceExpense(uri) {
  if (!uri) throw new Error('Recording was empty. Please try again.');
  const form = new FormData();
  form.append('source', 'voice');
  form.append('file', localFile(uri));
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
  form.append('file', localFile(photo.uri));
  return request('/log-expense', { method: 'POST', body: form });
}
