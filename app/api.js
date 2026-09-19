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
export const triggerWeeklyCall = () => postJSON('/trigger-call', { kind: 'weekly_summary' });

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
  form.append('file', { uri, name: 'expense.m4a', type: 'audio/mp4' });
  // React Native supplies the multipart boundary. Do not set Content-Type.
  return request('/log-expense', { method: 'POST', body: form });
}
