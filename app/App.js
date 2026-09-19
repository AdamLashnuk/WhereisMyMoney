import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Keyboard, RefreshControl, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { getExpenses, getLimits, saveLimit, getSettings, saveSettings, logTextExpense } from './api';

const COLORS = { bg: '#F6F7F4', ink: '#172B25', muted: '#6D7A73', green: '#215D43', pale: '#E5EFE7', white: '#FFFFFF', border: '#E4E9E3', amber: '#B46B24', red: '#A13535' };
const CATEGORIES = ['Food', 'Transport', 'Subscriptions', 'Shopping', 'Bills', 'Other'];
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const money = (value) => `$${((Number(value) || 0) / 100).toFixed(2)}`;
const dollars = (cents) => ((Number(cents) || 0) / 100).toFixed(2);
const readableHour = (hour) => `${hour % 12 || 12}${hour < 12 ? 'am' : 'pm'}`;
const parseDollars = (text) => {
  if (!/^\d+(?:\.\d{1,2})?$/.test(text.trim())) return null;
  const [whole, fractional = ''] = text.trim().split('.');
  const cents = Number(whole) * 100 + Number((fractional + '00').slice(0, 2));
  return Number.isSafeInteger(cents) ? cents : null;
};

function Header({ eyebrow, title, subtitle }) {
  return <View style={styles.header}><Text style={styles.eyebrow}>{eyebrow}</Text><Text style={styles.title}>{title}</Text><Text style={styles.subtitle}>{subtitle}</Text></View>;
}
function Card({ children, style }) { return <View style={[styles.card, style]}>{children}</View>; }
function Action({ title, onPress, disabled, outline }) {
  return <TouchableOpacity accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.button, outline && styles.outlineButton, disabled && styles.disabled]}><Text style={[styles.buttonText, outline && styles.outlineText]}>{title}</Text></TouchableOpacity>;
}
function ErrorMessage({ message }) { return message ? <Text style={styles.error}>{message}</Text> : null; }

function LogScreen({ onLogged }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const submit = async () => {
    if (!text.trim()) { setError('Describe your expense first.'); return; }
    setBusy(true); setError(''); setResult(null);
    try {
      const data = await logTextExpense(text.trim());
      if (!data.expense) throw new Error('The server did not return an expense.');
      setResult(data);
      setText('');
      Keyboard.dismiss();
      onLogged();
    } catch (err) { setError(err.message || 'Could not log expense.'); }
    finally { setBusy(false); }
  };
  const expense = result?.expense;
  const check = result?.limitCheck;
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.page}>
    <Header eyebrow="WHERE IS MY MONEY" title="Log an expense" subtitle="Tell us what you spent. We'll sort it." />
    <Card style={styles.hero}><Text style={styles.heroEyebrow}>EXPENSE LOGGER</Text><View style={styles.micCircle}><Text style={styles.micIcon}>●</Text></View><Text style={styles.heroTitle}>Your money, in your words.</Text><Text style={styles.heroDescription}>Type what you would say. Microphone recording is the next feature.</Text></Card>
    <Card><Text style={styles.cardTitle}>What did you spend?</Text><TextInput accessibilityLabel="Expense description" multiline placeholder="spent fourteen bucks on lunch" placeholderTextColor={COLORS.muted} value={text} onChangeText={setText} style={[styles.input, styles.textArea]} /><Action title={busy ? 'Saving...' : 'Log expense'} onPress={submit} disabled={busy} /><ErrorMessage message={error} /></Card>
    {expense && <Card style={styles.success}><Text style={styles.successTitle}>Expense saved ✓</Text><Text style={styles.resultAmount}>{money(expense.amountCents ?? expense.amount_cents ?? expense.cents)}</Text><Text style={styles.resultCategory}>{expense.category} {expense.merchant ? `· ${expense.merchant}` : ''}</Text><Text style={styles.cardSub}>Original words: “{expense.originalText ?? expense.original_text ?? ''}”</Text>{expense.needsReview || expense.needs_review ? <Text style={styles.warning}>Please check this expense in History — the AI wasn't confident.</Text> : null}</Card>}
    {check && Number(check.overByCents) > 0 && <Card style={styles.alert}><Text style={styles.alertTitle}>Over your {check.category} limit by {money(check.overByCents)}</Text><Text style={styles.cardSub}>Spent {money(check.weekTotalCents)} / limit {money(check.limitCents)}</Text><Text style={styles.warning}>{check.action === 'placed_call' ? 'The backend placed your alert call.' : check.action === 'already_called' ? 'You were already called about this category this week.' : check.action === 'call_failed' ? 'The call could not be placed. Check Twilio and your saved phone number.' : 'Call status: ' + (check.action || 'not available')}</Text></Card>}
    <Card><Text style={styles.cardTitle}>Snap a receipt</Text><Text style={styles.cardSub}>Camera upload coming next.</Text></Card>
  </ScrollView>;
}

function HistoryScreen({ revision }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(null);
  const load = useCallback(async () => {
    setBusy(true); setError('');
    try { setData(await getExpenses()); }
    catch (err) { setError(err.message || 'Could not load expenses.'); setData(null); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load, revision]);
  const expenses = Array.isArray(data?.expenses) ? data.expenses : [];
  return <ScrollView refreshControl={<RefreshControl refreshing={busy} onRefresh={load} />} contentContainerStyle={styles.page}>
    <Header eyebrow="YOUR WEEK" title="Spending history" subtitle="Real expenses from Sebastian's backend." />
    <ErrorMessage message={error} />
    {!data && busy ? <ActivityIndicator color={COLORS.green} /> : null}
    {data && <><Card style={styles.totalCard}><Text style={styles.totalLabel}>TOTAL THIS WEEK</Text><Text style={styles.totalAmount}>{money(data.weekTotalCents)}</Text><Text style={styles.totalHint}>{expenses.length} expenses · Pull down to refresh</Text></Card><Text style={styles.sectionTitle}>By category</Text><Card>{CATEGORIES.map((category, index) => <View key={category} style={[styles.categoryRow, index > 0 && styles.categoryBorder]}><Text style={styles.categoryName}>{category}</Text><Text style={styles.categoryAmount}>{money(data.totalsByCategory?.[category])}</Text></View>)}</Card><Text style={styles.sectionTitle}>Recent expenses</Text>{!expenses.length && <Card><Text style={styles.cardSub}>No expenses this week. Log one in the Log tab!</Text></Card>}{expenses.map((expense, index) => {
      const id = String(expense.id ?? index);
      const original = expense.originalText ?? expense.original_text ?? '';
      const cents = expense.amountCents ?? expense.amount_cents ?? expense.cents;
      const date = expense.createdAt ?? expense.created_at ?? expense.occurredAt ?? expense.occurred_at ?? '';
      return <TouchableOpacity accessibilityRole="button" key={id} onPress={() => setOpen(open === id ? null : id)}><Card style={styles.expenseCard}><View style={styles.flex}><Text style={styles.cardTitle}>{expense.merchant || expense.category || 'Expense'}</Text><Text style={styles.cardSub}>{expense.category}{date ? ` · ${String(date).slice(0, 10)}` : ''}</Text></View><Text style={styles.expenseAmount}>−{money(cents)}</Text>{open === id && <Text style={styles.original}>Original words: “{original || 'Not available'}”</Text>}</Card></TouchableOpacity>;
    })}</>}
  </ScrollView>;
}

function LimitsScreen() {
  const [limits, setLimits] = useState({});
  const [inputs, setInputs] = useState({});
  const [settings, setSettings] = useState({ callDay: 0, callHour: 18, phoneNumber: '' });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [limitData, settingsData] = await Promise.all([getLimits(), getSettings()]);
      const values = limitData.limits || {};
      setLimits(values);
      setInputs(Object.fromEntries(CATEGORIES.map((category) => [category, dollars(values[category])])));
      setSettings({ callDay: settingsData.settings?.callDay ?? 0, callHour: settingsData.settings?.callHour ?? 18, phoneNumber: settingsData.settings?.phoneNumber || '' });
    } catch (err) { setError(err.message || 'Could not load limits and settings.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const saveCategory = async (category) => {
    const cents = parseDollars(inputs[category] || '');
    if (cents === null) { setError(`Enter a valid ${category} limit, like 50 or 50.25.`); return; }
    setSaving(category); setError(''); setNotice('');
    try { const data = await saveLimit(category, cents); setLimits(data.limits || { ...limits, [category]: cents }); setInputs((old) => ({ ...old, [category]: dollars(cents) })); setNotice(`${category} limit saved: ${money(cents)}.`); }
    catch (err) { setError(err.message || 'Could not save limit.'); }
    finally { setSaving(''); }
  };
  const saveSchedule = async () => {
    if (!/^\+?[1-9]\d{7,14}$/.test(settings.phoneNumber.trim())) { setError('Enter a valid phone number with country code, for example +14155550123.'); return; }
    setSaving('settings'); setError(''); setNotice('');
    try { const data = await saveSettings(settings); if (data.settings) setSettings(data.settings); setNotice('Call schedule saved.'); }
    catch (err) { setError(err.message || 'Could not save call settings.'); }
    finally { setSaving(''); }
  };
  return <ScrollView keyboardShouldPersistTaps="handled" refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />} contentContainerStyle={styles.page}>
    <Header eyebrow="STAY ON TRACK" title="Your limits" subtitle="Make a plan that calls you back." />
    <Card style={styles.notice}><Text style={styles.noticeTitle}>Your rules, your money</Text><Text style={styles.noticeText}>Any amount over a weekly limit triggers a call. A second call for the same category in the same week is suppressed.</Text></Card>
    <ErrorMessage message={error} />{notice ? <Text style={styles.saved}>{notice}</Text> : null}
    <Text style={styles.sectionTitle}>Weekly category limits</Text>
    <Card>{CATEGORIES.map((category, index) => <View key={category} style={[styles.limitRow, index > 0 && styles.categoryBorder]}><Text style={styles.categoryName}>{category} · {money(limits[category])}</Text><View style={styles.limitControls}><Text style={styles.dollarSign}>$</Text><TextInput accessibilityLabel={`${category} weekly limit in dollars`} keyboardType="decimal-pad" value={inputs[category] ?? ''} onChangeText={(value) => setInputs((old) => ({ ...old, [category]: value }))} style={[styles.input, styles.limitInput]} /><TouchableOpacity accessibilityRole="button" disabled={!!saving} onPress={() => saveCategory(category)} style={[styles.smallButton, !!saving && styles.disabled]}><Text style={styles.smallButtonText}>{saving === category ? '...' : 'Save'}</Text></TouchableOpacity></View></View>)}</Card>
    <Text style={styles.sectionTitle}>Weekly summary call</Text>
    <Card><Text style={styles.cardTitle}>Which day should we call?</Text><View style={styles.pills}>{DAYS.map((day, index) => <TouchableOpacity accessibilityRole="button" key={day} onPress={() => setSettings((old) => ({ ...old, callDay: index }))} style={[styles.pill, settings.callDay === index && styles.selectedPill]}><Text style={[styles.pillText, settings.callDay === index && styles.selectedText]}>{day.slice(0, 3)}</Text></TouchableOpacity>)}</View><Text style={[styles.cardTitle, styles.fieldTitle]}>What hour?</Text><View style={styles.pills}>{Array.from({ length: 24 }, (_, hour) => <TouchableOpacity accessibilityRole="button" key={hour} onPress={() => setSettings((old) => ({ ...old, callHour: hour }))} style={[styles.pill, settings.callHour === hour && styles.selectedPill]}><Text style={[styles.pillText, settings.callHour === hour && styles.selectedText]}>{readableHour(hour)}</Text></TouchableOpacity>)}</View><Text style={[styles.cardTitle, styles.fieldTitle]}>Phone number</Text><TextInput accessibilityLabel="Phone number for weekly calls" autoComplete="tel" keyboardType="phone-pad" placeholder="+14155550123" value={settings.phoneNumber} onChangeText={(value) => setSettings((old) => ({ ...old, phoneNumber: value }))} style={styles.input} /><View style={styles.schedule}><Text style={styles.scheduleText}>We'll call you {DAYS[settings.callDay]}s at {readableHour(settings.callHour)}.</Text></View><Action title={saving === 'settings' ? 'Saving...' : 'Save call settings'} onPress={saveSchedule} disabled={!!saving} /></Card>
  </ScrollView>;
}

const TABS = [{ key: 'Log', symbol: '●' }, { key: 'History', symbol: '▤' }, { key: 'Limits', symbol: '◉' }];
export default function App() {
  const [tab, setTab] = useState('Log');
  const [revision, setRevision] = useState(0);
  return <SafeAreaView style={styles.safe}><StatusBar barStyle="dark-content" backgroundColor={COLORS.bg} /><View style={styles.content}>{tab === 'Log' ? <LogScreen onLogged={() => setRevision((v) => v + 1)} /> : tab === 'History' ? <HistoryScreen revision={revision} /> : <LimitsScreen />}</View><View style={styles.tabBar}>{TABS.map((item) => <TouchableOpacity key={item.key} accessibilityRole="tab" accessibilityState={{ selected: tab === item.key }} onPress={() => setTab(item.key)} style={styles.tab}><Text style={[styles.tabSymbol, tab === item.key && styles.tabActive]}>{item.symbol}</Text><Text style={[styles.tabLabel, tab === item.key && styles.tabActive]}>{item.key}</Text></TouchableOpacity>)}</View></SafeAreaView>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg }, content: { flex: 1 }, page: { paddingHorizontal: 22, paddingTop: 24, paddingBottom: 32 },
  header: { marginBottom: 24 }, eyebrow: { fontSize: 11, fontWeight: '800', letterSpacing: 2, color: COLORS.green, marginBottom: 12 }, title: { fontSize: 34, fontWeight: '800', letterSpacing: -1.4, color: COLORS.ink }, subtitle: { fontSize: 15, color: COLORS.muted, marginTop: 8, lineHeight: 22 },
  card: { backgroundColor: COLORS.white, borderRadius: 22, borderWidth: 1, borderColor: COLORS.border, padding: 20, marginBottom: 12 },
  hero: { backgroundColor: COLORS.green, borderColor: COLORS.green, alignItems: 'center', paddingVertical: 22 }, heroEyebrow: { fontSize: 10, fontWeight: '800', letterSpacing: 2, color: '#BFE0CE' }, micCircle: { width: 70, height: 70, borderRadius: 35, backgroundColor: '#39785B', alignItems: 'center', justifyContent: 'center', marginTop: 18, marginBottom: 14 }, micIcon: { fontSize: 35, color: COLORS.white }, heroTitle: { fontSize: 22, fontWeight: '800', color: COLORS.white, textAlign: 'center' }, heroDescription: { fontSize: 13, color: '#D2E5D9', textAlign: 'center', lineHeight: 20, marginTop: 10 },
  input: { backgroundColor: COLORS.white, borderRadius: 12, borderWidth: 1, borderColor: '#CCD8CE', color: COLORS.ink, padding: 13, fontSize: 15, marginVertical: 12 }, textArea: { minHeight: 80, textAlignVertical: 'top' }, button: { backgroundColor: COLORS.green, borderRadius: 12, padding: 15, alignItems: 'center', marginTop: 4 }, buttonText: { fontWeight: '800', color: COLORS.white }, outlineButton: { backgroundColor: COLORS.white, borderWidth: 1, borderColor: COLORS.green }, outlineText: { color: COLORS.green }, disabled: { opacity: 0.5 }, error: { color: COLORS.red, fontSize: 13, lineHeight: 19, marginVertical: 12 }, saved: { color: COLORS.green, fontSize: 13, marginBottom: 12, fontWeight: '700' }, warning: { color: COLORS.amber, marginTop: 12, fontSize: 13, lineHeight: 20 },
  flex: { flex: 1 }, cardTitle: { fontSize: 15, fontWeight: '800', color: COLORS.ink }, cardSub: { fontSize: 12, color: COLORS.muted, marginTop: 5, lineHeight: 18 }, sectionTitle: { color: COLORS.ink, fontSize: 17, fontWeight: '800', marginTop: 17, marginBottom: 13 },
  totalCard: { backgroundColor: COLORS.green, borderColor: COLORS.green, paddingVertical: 27 }, totalLabel: { color: '#BFE0CE', fontSize: 10, letterSpacing: 1.4, fontWeight: '800' }, totalAmount: { color: COLORS.white, fontSize: 48, fontWeight: '800', letterSpacing: -2, marginTop: 10 }, totalHint: { color: '#D2E5D9', marginTop: 5, fontSize: 12 }, categoryRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 42 }, categoryBorder: { borderTopWidth: 1, borderTopColor: COLORS.border }, categoryName: { fontSize: 14, fontWeight: '600', color: COLORS.ink }, categoryAmount: { fontSize: 14, fontWeight: '800', color: COLORS.ink }, expenseCard: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' }, expenseAmount: { fontSize: 15, fontWeight: '800', color: COLORS.ink }, original: { width: '100%', borderTopWidth: 1, borderTopColor: COLORS.border, marginTop: 15, paddingTop: 15, color: COLORS.muted, fontSize: 13, lineHeight: 20 },
  success: { borderColor: '#8BCAA1' }, successTitle: { fontSize: 14, fontWeight: '800', color: COLORS.green }, resultAmount: { fontSize: 34, fontWeight: '800', color: COLORS.ink, marginTop: 8 }, resultCategory: { fontSize: 15, color: COLORS.green, marginVertical: 6, fontWeight: '700' }, alert: { backgroundColor: '#FFF4E5', borderColor: '#F0C89A' }, alertTitle: { color: COLORS.amber, fontSize: 16, fontWeight: '800' },
  notice: { backgroundColor: COLORS.pale, borderColor: COLORS.pale }, noticeTitle: { fontSize: 15, fontWeight: '800', color: COLORS.green }, noticeText: { fontSize: 13, lineHeight: 20, color: COLORS.green, marginTop: 7 }, limitRow: { paddingVertical: 11 }, limitControls: { flexDirection: 'row', alignItems: 'center', marginTop: 3 }, dollarSign: { color: COLORS.ink, fontSize: 17, fontWeight: '800' }, limitInput: { flex: 1, marginHorizontal: 8, marginVertical: 5 }, smallButton: { backgroundColor: COLORS.green, padding: 12, borderRadius: 10 }, smallButtonText: { color: COLORS.white, fontWeight: '800' }, fieldTitle: { marginTop: 22 }, pills: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginTop: 13 }, pill: { borderRadius: 10, borderWidth: 1, borderColor: COLORS.border, paddingVertical: 10, paddingHorizontal: 12 }, selectedPill: { backgroundColor: COLORS.green, borderColor: COLORS.green }, pillText: { fontSize: 12, fontWeight: '700', color: COLORS.ink }, selectedText: { color: COLORS.white }, schedule: { marginTop: 17, marginBottom: 10, backgroundColor: COLORS.pale, borderRadius: 12, padding: 14 }, scheduleText: { color: COLORS.green, fontWeight: '800', fontSize: 13 },
  tabBar: { backgroundColor: COLORS.white, borderTopWidth: 1, borderTopColor: COLORS.border, flexDirection: 'row', paddingTop: 11, paddingBottom: 9 }, tab: { flex: 1, alignItems: 'center', paddingVertical: 3 }, tabSymbol: { fontSize: 23, color: '#A0ABA3', marginBottom: 3 }, tabLabel: { color: '#88948B', fontSize: 11, fontWeight: '700' }, tabActive: { color: COLORS.green },
});
