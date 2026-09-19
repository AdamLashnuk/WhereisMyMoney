import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator, Keyboard, Platform, RefreshControl, SafeAreaView,
  ScrollView, StatusBar, StyleSheet, Text, TextInput, TouchableOpacity, View,
} from 'react-native';
import { getExpenses, getLimits, saveLimit, getSettings, saveSettings, logTextExpense } from './api';

// Reference-inspired colors. Native iOS fonts: Georgia for display and Avenir Next for UI.
const C = {
  canvas: '#EFF4F8', paper: '#FFFFFF', ink: '#192D42', black: '#111923',
  muted: '#6D7E8D', line: '#DCE5EB', coral: '#FF855B', coralDeep: '#EB6548',
  yellow: '#FFF36A', peach: '#FFF0DE', green: '#287C54', red: '#AF3636',
};
const F = {
  display: Platform.OS === 'ios' ? 'Georgia-Bold' : 'serif',
  body: Platform.OS === 'ios' ? 'AvenirNext-Regular' : 'sans-serif',
  medium: Platform.OS === 'ios' ? 'AvenirNext-DemiBold' : 'sans-serif-medium',
  heavy: Platform.OS === 'ios' ? 'AvenirNext-Bold' : 'sans-serif-medium',
};
const CATEGORIES = ['Food', 'Transport', 'Subscriptions', 'Shopping', 'Bills', 'Other'];
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const money = (cents) => `$${((Number(cents) || 0) / 100).toFixed(2)}`;
const dollars = (cents) => ((Number(cents) || 0) / 100).toFixed(2);
const hourLabel = (hour) => `${hour % 12 || 12}:00 ${hour < 12 ? 'AM' : 'PM'}`;
function parseDollars(value) {
  const clean = String(value).trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(clean)) return null;
  const [whole, fraction = ''] = clean.split('.');
  const cents = Number(whole) * 100 + Number((fraction + '00').slice(0, 2));
  return Number.isSafeInteger(cents) ? cents : null;
}

function Heading({ kicker, title, subtitle }) {
  return <View style={s.heading}>
    <View style={s.brandLine}><View style={s.brandMark}/><Text style={s.brand}>WHERE IS MY MONEY</Text></View>
    <Text style={s.kicker}>{kicker}</Text>
    <Text style={s.headingTitle}>{title}</Text>
    {subtitle ? <Text style={s.headingSub}>{subtitle}</Text> : null}
  </View>;
}
function ErrorText({ value }) { return value ? <Text style={s.error}>{value}</Text> : null; }
function Button({ title, onPress, disabled, light }) {
  return <TouchableOpacity accessibilityRole="button" disabled={disabled} onPress={onPress} activeOpacity={0.85} style={[s.button, light && s.buttonLight, disabled && s.dim]}>
    <Text style={[s.buttonText, light && s.buttonLightText]}>{title}</Text><Text style={[s.buttonArrow, light && s.buttonLightText]}>↗</Text>
  </TouchableOpacity>;
}
function SectionTitle({ title, detail }) {
  return <View style={s.sectionHeading}><Text style={s.sectionTitle}>{title}</Text>{detail ? <Text style={s.sectionDetail}>{detail}</Text> : null}</View>;
}
function LogScreen({ onLogged }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const submit = async () => {
    if (!text.trim()) { setError('Enter an expense description first.'); return; }
    setBusy(true); setError(''); setResult(null);
    try {
      const data = await logTextExpense(text.trim());
      if (!data.expense) throw new Error('The server did not return an expense.');
      setResult(data); setText(''); Keyboard.dismiss(); onLogged();
    } catch (err) { setError(err.message || 'Could not log expense.'); }
    finally { setBusy(false); }
  };
  const expense = result?.expense;
  const check = result?.limitCheck;
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.page}>
    <Heading kicker="01 / EXPENSES" title="Log an expense." subtitle="Keep track of every purchase, without the busywork."/>
    <View style={s.logHero}>
      <Text style={s.heroKicker}>QUICK ENTRY</Text>
      <View style={s.heroTextRow}><Text style={s.heroTitle}>Money in.\nDetails sorted.</Text><View style={s.heroCoin}><Text style={s.coinSymbol}>$</Text></View></View>
      <View style={s.heroFoot}><View style={s.heroFootLine}/><Text style={s.heroFootText}>Voice recording and receipts coming soon</Text></View>
    </View>
    <SectionTitle title="New expense" detail="TEXT ENTRY"/>
    <View style={s.formPanel}>
      <Text style={s.fieldLabel}>WHAT DID YOU SPEND?</Text>
      <TextInput accessibilityLabel="Expense description" multiline placeholder="e.g. spent fourteen bucks on lunch" placeholderTextColor={C.muted} value={text} onChangeText={setText} style={[s.input, s.descriptionInput]}/>
      <Button title={busy ? 'Saving expense...' : 'Add expense'} disabled={busy} onPress={submit}/>
      <ErrorText value={error}/>
    </View>
    {expense ? <View style={s.resultPanel}>
      <Text style={s.resultKicker}>EXPENSE SAVED</Text>
      <Text style={s.resultAmount}>{money(expense.amountCents ?? expense.amount_cents ?? expense.cents)}</Text>
      <Text style={s.resultDescription}>{expense.category}{expense.merchant ? `  /  ${expense.merchant}` : ''}</Text>
      <View style={s.rule}/><Text style={s.originalText}>“{expense.originalText ?? expense.original_text ?? ''}”</Text>
      {expense.needsReview || expense.needs_review ? <Text style={s.warning}>Please review this expense. The category may need correcting.</Text> : null}
    </View> : null}
    {check && Number(check.overByCents) > 0 ? <View style={s.alertPanel}>
      <Text style={s.alertKicker}>SPENDING LIMIT</Text>
      <Text style={s.alertTitle}>{money(check.overByCents)} over your {check.category} limit</Text>
      <Text style={s.alertBody}>{money(check.weekTotalCents)} spent of {money(check.limitCents)} budgeted.</Text>
      <Text style={s.alertBody}>{check.action === 'placed_call' ? 'Your alert call was placed.' : check.action === 'already_called' ? 'You have already received an alert for this category this week.' : check.action === 'call_failed' ? 'The call could not be placed. Check your call settings.' : `Call status: ${check.action || 'unavailable'}`}</Text>
    </View> : null}
  </ScrollView>;
}
function HistoryScreen({ revision }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(null);
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { setData(await getExpenses()); }
    catch (err) { setError(err.message || 'Could not load expenses.'); setData(null); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load, revision]);
  const expenses = Array.isArray(data?.expenses) ? data.expenses : [];
  return <ScrollView refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={C.coralDeep}/>} contentContainerStyle={s.page}>
    <Heading kicker="02 / OVERVIEW" title="Your history." subtitle="A clear view of where your money went."/>
    <ErrorText value={error}/>
    {!data && loading ? <ActivityIndicator color={C.coralDeep}/> : null}
    {data ? <>
      <View style={s.balancePanel}>
        <Text style={s.balanceLabel}>TOTAL SPENT THIS WEEK</Text>
        <Text style={s.balanceAmount}>{money(data.weekTotalCents)}</Text>
        <View style={s.balanceFooter}><View style={s.balanceDash}/><Text style={s.balanceFooterText}>{expenses.length} transactions  ·  This week</Text></View>
        <View style={s.yellowCorner}/>
      </View>
      <SectionTitle title="Category breakdown" detail="THIS WEEK"/>
      <View style={s.ledger}>
        {CATEGORIES.map((category, i) => <View key={category} style={[s.ledgerRow, i > 0 && s.ledgerDivider]}>
          <View style={[s.categoryMarker, { backgroundColor: i % 2 ? C.yellow : C.coral }]}/>
          <Text style={s.ledgerName}>{category}</Text><Text style={s.ledgerValue}>{money(data.totalsByCategory?.[category])}</Text>
        </View>)}
      </View>
      <SectionTitle title="Transactions" detail="TAP FOR DETAILS"/>
      <View style={s.ledger}>
        {expenses.length === 0 ? <Text style={s.emptyText}>No expenses yet this week. Add one from the Log tab.</Text> : null}
        {expenses.map((expense, index) => {
          const id = String(expense.id ?? index);
          const original = expense.originalText ?? expense.original_text ?? '';
          const cents = expense.amountCents ?? expense.amount_cents ?? expense.cents;
          const date = expense.createdAt ?? expense.created_at ?? expense.occurredAt ?? expense.occurred_at ?? '';
          return <TouchableOpacity key={id} accessibilityRole="button" onPress={() => setExpanded(expanded === id ? null : id)} activeOpacity={0.7} style={[s.transaction, index > 0 && s.ledgerDivider]}>
            <View style={s.transactionGlyph}><Text style={s.transactionGlyphText}>↗</Text></View>
            <View style={s.transactionCopy}><Text style={s.transactionName}>{expense.merchant || expense.category || 'Expense'}</Text><Text style={s.transactionMeta}>{expense.category}{date ? `  ·  ${String(date).slice(0, 10)}` : ''}</Text></View>
            <Text style={s.transactionAmount}>−{money(cents)}</Text>
            {expanded === id ? <Text style={s.transactionOriginal}>Original entry: “{original || 'Not available'}”</Text> : null}
          </TouchableOpacity>;
        })}
      </View>
    </> : null}
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
    } catch (err) { setError(err.message || 'Could not load settings.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const saveCategory = async (category) => {
    const cents = parseDollars(inputs[category] || '');
    if (cents === null) { setError(`Enter a valid ${category} limit, such as 50.25.`); return; }
    setSaving(category); setError(''); setNotice('');
    try {
      const data = await saveLimit(category, cents);
      setLimits(data.limits || { ...limits, [category]: cents });
      setInputs(old => ({ ...old, [category]: dollars(cents) }));
      setNotice(`${category} limit saved: ${money(cents)}`);
    } catch (err) { setError(err.message || 'Could not save limit.'); }
    finally { setSaving(''); }
  };
  const saveSchedule = async () => {
    if (!/^\+?[1-9]\d{7,14}$/.test(settings.phoneNumber.trim())) { setError('Enter your number with country code, e.g. +14155550123.'); return; }
    setSaving('settings'); setError(''); setNotice('');
    try {
      const data = await saveSettings({ ...settings, phoneNumber: settings.phoneNumber.trim() });
      if (data.settings) setSettings(data.settings);
      setNotice('Call settings saved.');
    } catch (err) { setError(err.message || 'Could not save call settings.'); }
    finally { setSaving(''); }
  };
  return <ScrollView keyboardShouldPersistTaps="handled" refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={C.coralDeep}/>} contentContainerStyle={s.page}>
    <Heading kicker="03 / PREFERENCES" title="Spending limits." subtitle="Set a weekly budget and choose when we call."/>
    <View style={s.noticePanel}><Text style={s.noticeNumber}>01</Text><View style={s.noticeCopy}><Text style={s.noticeHeading}>Your limits, your rules.</Text><Text style={s.noticeBody}>Going over by even one cent triggers an alert call, once per category each week.</Text></View></View>
    <ErrorText value={error}/>{notice ? <Text style={s.saved}>{notice}</Text> : null}
    <SectionTitle title="Weekly budgets" detail="AMOUNTS IN USD"/>
    <View style={s.ledger}>
      {CATEGORIES.map((category, index) => <View key={category} style={[s.limitRow, index > 0 && s.ledgerDivider]}>
        <View style={s.limitHeading}><Text style={s.limitCategory}>{category}</Text><Text style={s.limitCurrent}>Current: {money(limits[category])}</Text></View>
        <View style={s.limitControls}><Text style={s.dollar}>$</Text><TextInput accessibilityLabel={`${category} weekly limit in dollars`} keyboardType="decimal-pad" value={inputs[category] ?? ''} onChangeText={value => setInputs(old => ({ ...old, [category]: value }))} style={s.limitInput}/><TouchableOpacity accessibilityRole="button" disabled={!!saving} onPress={() => saveCategory(category)} style={[s.saveChip, !!saving && s.dim]}><Text style={s.saveChipText}>{saving === category ? '...' : 'Save'}</Text></TouchableOpacity></View>
      </View>)}
    </View>
    <SectionTitle title="Weekly phone call" detail="SCHEDULE"/>
    <View style={s.settingsPanel}>
      <Text style={s.fieldLabel}>DAY OF THE WEEK</Text>
      <View style={s.days}>{DAYS.map((day, index) => <TouchableOpacity key={day} accessibilityRole="button" accessibilityState={{ selected: settings.callDay === index }} onPress={() => setSettings(old => ({ ...old, callDay: index }))} style={[s.day, settings.callDay === index && s.daySelected]}><Text style={[s.dayText, settings.callDay === index && s.dayTextSelected]}>{day.slice(0, 3)}</Text></TouchableOpacity>)}</View>
      <Text style={[s.fieldLabel, s.fieldSpace]}>CALL TIME</Text>
      <View style={s.hourPicker}><TouchableOpacity accessibilityRole="button" accessibilityLabel="One hour earlier" onPress={() => setSettings(old => ({ ...old, callHour: (old.callHour + 23) % 24 }))} style={s.hourControl}><Text style={s.hourControlText}>−</Text></TouchableOpacity><Text style={s.hourValue}>{hourLabel(settings.callHour)}</Text><TouchableOpacity accessibilityRole="button" accessibilityLabel="One hour later" onPress={() => setSettings(old => ({ ...old, callHour: (old.callHour + 1) % 24 }))} style={s.hourControl}><Text style={s.hourControlText}>+</Text></TouchableOpacity></View>
      <Text style={[s.fieldLabel, s.fieldSpace]}>PHONE NUMBER</Text><TextInput accessibilityLabel="Phone number for weekly calls" autoComplete="tel" keyboardType="phone-pad" placeholder="+14155550123" placeholderTextColor={C.muted} value={settings.phoneNumber} onChangeText={phoneNumber => setSettings(old => ({ ...old, phoneNumber }))} style={s.input}/>
      <View style={s.scheduleNote}><Text style={s.scheduleNoteText}>Scheduled: {DAYS[settings.callDay]}s at {hourLabel(settings.callHour)}</Text></View>
      <Button title={saving === 'settings' ? 'Saving...' : 'Save call settings'} disabled={!!saving} onPress={saveSchedule}/>
    </View>
  </ScrollView>;
}
const TABS = [{ key: 'Log', symbol: '+' }, { key: 'History', symbol: '≡' }, { key: 'Limits', symbol: '◉' }];
export default function App() {
  const [tab, setTab] = useState('Log');
  const [revision, setRevision] = useState(0);
  return <SafeAreaView style={s.safe}>
    <StatusBar barStyle="dark-content" backgroundColor={C.canvas}/>
    <View style={s.content}>{tab === 'Log' ? <LogScreen onLogged={() => setRevision(value => value + 1)}/> : tab === 'History' ? <HistoryScreen revision={revision}/> : <LimitsScreen/>}</View>
    <View style={s.tabs}>{TABS.map(item => <TouchableOpacity accessibilityRole="tab" accessibilityState={{ selected: tab === item.key }} key={item.key} onPress={() => setTab(item.key)} style={[s.tab, tab === item.key && s.tabSelected]}><Text style={[s.tabIcon, tab === item.key && s.tabIconSelected]}>{item.symbol}</Text><Text style={[s.tabName, tab === item.key && s.tabNameSelected]}>{item.key}</Text></TouchableOpacity>)}</View>
  </SafeAreaView>;
}
const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.canvas }, content: { flex: 1 }, page: { paddingHorizontal: 24, paddingTop: 20, paddingBottom: 42 },
  heading: { paddingBottom: 28 }, brandLine: { flexDirection: 'row', alignItems: 'center', marginBottom: 34 }, brandMark: { width: 11, height: 11, backgroundColor: C.coral, transform: [{ rotate: '45deg' }], marginRight: 12 }, brand: { fontFamily: F.heavy, fontSize: 11, letterSpacing: 2.1, color: C.ink },
  kicker: { fontFamily: F.heavy, fontSize: 11, letterSpacing: 1.8, color: C.coralDeep, marginBottom: 7 }, headingTitle: { fontFamily: F.display, fontSize: 39, letterSpacing: -1.4, color: C.black, lineHeight: 45 }, headingSub: { fontFamily: F.body, fontSize: 14, lineHeight: 22, color: C.muted, marginTop: 10, maxWidth: 305 },
  sectionHeading: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 29, marginBottom: 13 }, sectionTitle: { fontFamily: F.heavy, color: C.ink, fontSize: 19 }, sectionDetail: { fontFamily: F.heavy, color: C.muted, fontSize: 9, letterSpacing: 1.1 },
  logHero: { backgroundColor: C.coral, paddingHorizontal: 23, paddingTop: 25, paddingBottom: 20, overflow: 'hidden', borderTopRightRadius: 42, borderBottomLeftRadius: 9, borderTopLeftRadius: 9, borderBottomRightRadius: 9 }, heroKicker: { fontFamily: F.heavy, color: C.black, fontSize: 10, letterSpacing: 1.8 }, heroTextRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 27 }, heroTitle: { fontFamily: F.display, color: C.white, fontSize: 30, lineHeight: 37, flex: 1 }, heroCoin: { width: 77, height: 77, borderRadius: 39, backgroundColor: C.yellow, borderWidth: 2, borderColor: C.black, alignItems: 'center', justifyContent: 'center', transform: [{ rotate: '-14deg' }] }, coinSymbol: { fontFamily: F.display, fontSize: 39, color: C.black }, heroFoot: { flexDirection: 'row', alignItems: 'center', marginTop: 35 }, heroFootLine: { backgroundColor: C.yellow, width: 25, height: 3, marginRight: 11 }, heroFootText: { fontFamily: F.medium, color: C.black, fontSize: 10, flex: 1 },
  formPanel: { backgroundColor: C.paper, padding: 20, borderWidth: 1, borderColor: C.line, borderRadius: 8 }, fieldLabel: { fontFamily: F.heavy, fontSize: 10, letterSpacing: 1.1, color: C.ink }, input: { backgroundColor: C.paper, borderWidth: 1, borderColor: C.line, borderRadius: 5, padding: 13, marginTop: 12, fontFamily: F.body, fontSize: 15, color: C.black }, descriptionInput: { minHeight: 86, textAlignVertical: 'top', marginBottom: 14 }, button: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 16, paddingHorizontal: 18, backgroundColor: C.black, borderRadius: 4, marginTop: 9 }, buttonLight: { backgroundColor: C.yellow }, buttonText: { fontFamily: F.heavy, fontSize: 14, color: C.white }, buttonArrow: { fontFamily: F.heavy, color: C.yellow, fontSize: 20 }, buttonLightText: { color: C.black }, dim: { opacity: 0.5 }, error: { color: C.red, fontFamily: F.medium, fontSize: 13, marginTop: 12, lineHeight: 19 }, saved: { fontFamily: F.heavy, color: C.green, fontSize: 13, marginTop: 15 },
  resultPanel: { marginTop: 19, backgroundColor: C.yellow, padding: 22, borderRadius: 6 }, resultKicker: { fontFamily: F.heavy, color: C.ink, letterSpacing: 1.3, fontSize: 10 }, resultAmount: { fontFamily: F.display, color: C.black, fontSize: 42, marginTop: 6 }, resultDescription: { fontFamily: F.heavy, color: C.ink, fontSize: 14, marginTop: 2 }, rule: { height: 1, backgroundColor: '#D5C852', marginVertical: 17 }, originalText: { fontFamily: F.body, color: C.ink, fontSize: 13, lineHeight: 19 }, warning: { fontFamily: F.medium, color: C.red, fontSize: 13, marginTop: 12 }, alertPanel: { padding: 20, marginTop: 15, borderLeftWidth: 5, borderLeftColor: C.coralDeep, backgroundColor: C.peach }, alertKicker: { fontFamily: F.heavy, fontSize: 10, color: C.red, letterSpacing: 1.2 }, alertTitle: { fontFamily: F.display, fontSize: 22, marginTop: 7, color: C.ink }, alertBody: { fontFamily: F.body, color: C.ink, fontSize: 13, lineHeight: 20, marginTop: 8 },
  balancePanel: { padding: 23, paddingBottom: 24, backgroundColor: C.coral, overflow: 'hidden', minHeight: 204, borderRadius: 6, borderTopRightRadius: 47 }, balanceLabel: { fontFamily: F.heavy, letterSpacing: 1.4, fontSize: 10, color: C.black }, balanceAmount: { fontFamily: F.display, fontSize: 47, color: C.white, marginTop: 21, letterSpacing: -2 }, balanceFooter: { flexDirection: 'row', alignItems: 'center', marginTop: 21, zIndex: 1 }, balanceDash: { width: 19, height: 3, backgroundColor: C.yellow, marginRight: 10 }, balanceFooterText: { fontFamily: F.medium, color: C.black, fontSize: 11 }, yellowCorner: { position: 'absolute', width: 96, height: 96, backgroundColor: C.yellow, right: -38, bottom: -46, transform: [{ rotate: '36deg' }] },
  ledger: { backgroundColor: C.paper, borderColor: C.line, borderWidth: 1, borderRadius: 5, paddingHorizontal: 18 }, ledgerRow: { flexDirection: 'row', alignItems: 'center', minHeight: 59 }, ledgerDivider: { borderTopColor: C.line, borderTopWidth: 1 }, categoryMarker: { height: 11, width: 11, borderRadius: 2, marginRight: 13 }, ledgerName: { fontFamily: F.medium, fontSize: 14, color: C.ink, flex: 1 }, ledgerValue: { fontFamily: F.heavy, fontSize: 14, color: C.black }, emptyText: { fontFamily: F.body, fontSize: 13, lineHeight: 21, color: C.muted, paddingVertical: 22 },
  transaction: { flexDirection: 'row', alignItems: 'center', minHeight: 78, flexWrap: 'wrap' }, transactionGlyph: { backgroundColor: C.canvas, width: 37, height: 37, borderRadius: 4, alignItems: 'center', justifyContent: 'center', marginRight: 12 }, transactionGlyphText: { fontSize: 20, color: C.coralDeep }, transactionCopy: { flex: 1, paddingVertical: 15 }, transactionName: { fontFamily: F.heavy, fontSize: 13, color: C.ink }, transactionMeta: { fontFamily: F.body, fontSize: 11, marginTop: 3, color: C.muted }, transactionAmount: { fontFamily: F.heavy, color: C.black, fontSize: 13 }, transactionOriginal: { width: '100%', fontFamily: F.body, borderTopWidth: 1, borderTopColor: C.line, paddingVertical: 13, color: C.muted, fontSize: 13 },
  noticePanel: { backgroundColor: C.yellow, flexDirection: 'row', padding: 19, alignItems: 'flex-start', borderRadius: 5 }, noticeNumber: { fontFamily: F.display, fontSize: 27, color: C.black, marginRight: 18 }, noticeCopy: { flex: 1 }, noticeHeading: { fontFamily: F.heavy, fontSize: 15, color: C.black }, noticeBody: { fontFamily: F.body, fontSize: 12, lineHeight: 19, color: C.ink, marginTop: 6 }, limitRow: { paddingVertical: 16 }, limitHeading: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, limitCategory: { fontFamily: F.heavy, color: C.black, fontSize: 15 }, limitCurrent: { fontFamily: F.body, color: C.muted, fontSize: 11 }, limitControls: { flexDirection: 'row', alignItems: 'center', marginTop: 7 }, dollar: { fontFamily: F.heavy, fontSize: 20, color: C.ink }, limitInput: { borderBottomWidth: 1, borderBottomColor: C.line, fontFamily: F.medium, fontSize: 16, color: C.black, paddingVertical: 8, paddingHorizontal: 8, flex: 1, marginLeft: 6, marginRight: 10 }, saveChip: { backgroundColor: C.black, borderRadius: 3, paddingHorizontal: 15, paddingVertical: 10 }, saveChipText: { fontFamily: F.heavy, color: C.white, fontSize: 12 },
  settingsPanel: { backgroundColor: C.paper, borderWidth: 1, borderColor: C.line, borderRadius: 5, padding: 19 }, days: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 13 }, day: { borderColor: C.line, borderWidth: 1, borderRadius: 3, paddingHorizontal: 13, paddingVertical: 10, minWidth: 55, alignItems: 'center' }, daySelected: { backgroundColor: C.coral, borderColor: C.coral }, dayText: { fontFamily: F.heavy, fontSize: 11, color: C.ink }, dayTextSelected: { color: C.black }, fieldSpace: { marginTop: 27 }, hourPicker: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: C.canvas, padding: 5, marginTop: 11 }, hourControl: { width: 47, height: 46, justifyContent: 'center', alignItems: 'center', backgroundColor: C.paper }, hourControlText: { fontFamily: F.heavy, color: C.ink, fontSize: 23 }, hourValue: { fontFamily: F.heavy, color: C.black, fontSize: 17 }, scheduleNote: { backgroundColor: C.yellow, padding: 14, marginTop: 18, marginBottom: 8, borderRadius: 2 }, scheduleNoteText: { fontFamily: F.heavy, fontSize: 12, color: C.black },
  tabs: { backgroundColor: C.paper, borderTopWidth: 1, borderTopColor: C.line, flexDirection: 'row', paddingTop: 10, paddingBottom: 10, paddingHorizontal: 17 }, tab: { flex: 1, alignItems: 'center', paddingVertical: 4, borderBottomWidth: 3, borderBottomColor: 'transparent' }, tabSelected: { borderBottomColor: C.coral }, tabIcon: { color: C.muted, fontFamily: F.heavy, fontSize: 23, height: 28 }, tabIconSelected: { color: C.black }, tabName: { color: C.muted, fontFamily: F.medium, fontSize: 11 }, tabNameSelected: { color: C.black, fontFamily: F.heavy },
});
