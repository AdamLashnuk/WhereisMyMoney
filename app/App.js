import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator, Alert, Keyboard, Platform, RefreshControl, SafeAreaView,
  ScrollView, StatusBar, StyleSheet, Text, TextInput, TouchableOpacity, View,
} from 'react-native';
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder, useAudioRecorderState } from 'expo-audio';
import {
  getExpenses, getLimits, saveLimit, getSettings, saveSettings,
  logTextExpense, logVoiceExpense, triggerWeeklyCall,
} from './api';

// Editorial banking palette. No pirate copy, credentials, or server code in this app.
const C = {
  bg: '#EFF4F8', white: '#FFFFFF', ink: '#192D42', black: '#111923',
  muted: '#647687', line: '#DCE5EB', coral: '#FF855B', orange: '#E96042',
  yellow: '#FFF36A', peach: '#FFF0DE', red: '#AA3030', green: '#287C54',
  devBg: '#130B0D', devPanel: '#270F14', devRed: '#D0444F', devMuted: '#D6A5AA',
};
const F = {
  display: Platform.OS === 'ios' ? 'Georgia-Bold' : 'serif',
  body: Platform.OS === 'ios' ? 'AvenirNext-Regular' : 'sans-serif',
  medium: Platform.OS === 'ios' ? 'AvenirNext-DemiBold' : 'sans-serif-medium',
  bold: Platform.OS === 'ios' ? 'AvenirNext-Bold' : 'sans-serif-medium',
};
const CATEGORIES = ['Food', 'Transport', 'Subscriptions', 'Shopping', 'Bills', 'Other'];
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const money = (cents) => `$${((Number(cents) || 0) / 100).toFixed(2)}`;
const dollars = (cents) => ((Number(cents) || 0) / 100).toFixed(2);
const hourLabel = (hour) => `${hour % 12 || 12}:00 ${hour < 12 ? 'AM' : 'PM'}`;
const validPhone = (number) => /^\+[1-9]\d{7,14}$/.test(number.trim());
function parseDollars(value) {
  const text = String(value).trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(text)) return null;
  const [whole, frac = ''] = text.split('.');
  const cents = Number(whole) * 100 + Number((frac + '00').slice(0, 2));
  return Number.isSafeInteger(cents) ? cents : null;
}
function Brand() {
  return <View style={s.brandRow}><View style={s.brandMark}/><Text style={s.brand}>WHERE IS MY MONEY</Text></View>;
}
function Header({ number, title, subtitle }) {
  return <View style={s.header}><Brand/><Text style={s.kicker}>{number}</Text><Text style={s.title}>{title}</Text><Text style={s.subtitle}>{subtitle}</Text></View>;
}
function Section({ title, caption }) {
  return <View style={s.section}><Text style={s.sectionTitle}>{title}</Text>{caption ? <Text style={s.sectionCaption}>{caption}</Text> : null}</View>;
}
function Button({ title, onPress, disabled, secondary }) {
  return <TouchableOpacity accessibilityRole="button" activeOpacity={0.82} disabled={disabled} onPress={onPress} style={[s.button, secondary && s.buttonSecondary, disabled && s.disabled]}><Text style={[s.buttonLabel, secondary && s.buttonSecondaryLabel]}>{title}</Text><Text style={[s.buttonArrow, secondary && s.buttonSecondaryLabel]}>↗</Text></TouchableOpacity>;
}
function Message({ text, positive }) { return text ? <Text style={[s.message, positive && s.positive]}>{text}</Text> : null; }
function Result({ data }) {
  if (!data?.expense) return null;
  const expense = data.expense;
  const limit = data.limitCheck;
  return <>
    <View style={s.savedPanel}>
      <Text style={s.smallCap}>EXPENSE SAVED</Text>
      <Text style={s.savedAmount}>{money(expense.amountCents ?? expense.amount_cents ?? expense.cents)}</Text>
      <Text style={s.savedCategory}>{expense.category}{expense.merchant ? `  /  ${expense.merchant}` : ''}</Text>
      <View style={s.divider}/>
      <Text style={s.smallBody}>Original entry: “{expense.originalText ?? expense.original_text ?? ''}”</Text>
      {(expense.needsReview || expense.needs_review) ? <Text style={s.warn}>Low confidence — please verify this amount and category.</Text> : null}
    </View>
    {limit && Number(limit.overByCents) > 0 ? <View style={s.overPanel}>
      <Text style={s.smallCap}>SPENDING LIMIT EXCEEDED</Text>
      <Text style={s.overTitle}>{money(limit.overByCents)} over · {limit.category}</Text>
      <Text style={s.smallBody}>{money(limit.weekTotalCents)} spent against {money(limit.limitCents)} budgeted.</Text>
      <Text style={s.smallBody}>{limit.action === 'placed_call' ? 'The server placed an alert call.' : limit.action === 'already_called' ? 'An alert call was already placed for this category this week.' : limit.action === 'call_failed' ? 'The server could not place the call. Check Twilio and the saved phone number.' : `Call status: ${limit.action || 'unavailable'}`}</Text>
    </View> : null}
  </>;
}
function LogScreen({ onLogged }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder);
  const accept = (data) => {
    if (!data?.expense) throw new Error('The server did not return an expense.');
    setResult(data); onLogged();
  };
  const submitText = async () => {
    if (!text.trim()) { setError('Describe an expense first.'); return; }
    setBusy(true); setError(''); setResult(null);
    try { accept(await logTextExpense(text.trim())); setText(''); Keyboard.dismiss(); }
    catch (err) { setError(err.message || 'Could not log expense.'); }
    finally { setBusy(false); }
  };
  const toggleRecording = async () => {
    if (busy) return;
    setError('');
    if (!recording) {
      setBusy(true); setResult(null);
      try {
        const permission = await AudioModule.requestRecordingPermissionsAsync();
        if (!permission.granted) throw new Error('Microphone permission denied. Allow microphone access in iPhone Settings.');
        await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
        await recorder.prepareToRecordAsync();
        recorder.record();
        setRecording(true);
      } catch (err) { setError(err.message || 'Could not start microphone.'); }
      finally { setBusy(false); }
      return;
    }
    setBusy(true);
    try {
      await recorder.stop();
      setRecording(false);
      await setAudioModeAsync({ allowsRecording: false });
      accept(await logVoiceExpense(recorder.uri));
    } catch (err) {
      setRecording(false);
      setError(err.message || 'Could not upload recording. Try typed entry.');
    } finally { setBusy(false); }
  };
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.page}>
    <Header number="01 / EXPENSES" title="Log an expense." subtitle="Capture a purchase with your voice or type it in."/>
    <View style={s.hero}>
      <Text style={s.smallCap}>QUICK ENTRY</Text>
      <View style={s.heroRow}><View style={s.heroWords}><Text style={s.heroTitle}>Money in.</Text><Text style={s.heroTitle}>Details sorted.</Text></View><View style={s.coin}><Text style={s.coinText}>$</Text></View></View>
      <View style={s.heroRule}/><Text style={s.heroFoot}>Record your purchase. We'll save the result.</Text>
    </View>
    <Section title="Voice entry" caption="MICROPHONE"/>
    <View style={s.whitePanel}>
      <Text style={s.smallBody}>{recording ? `Recording · ${Math.round((recorderState.durationMillis || 0) / 1000)} seconds` : busy ? 'Processing your expense…' : 'Tap to start. Speak naturally, then tap again to finish.'}</Text>
      <TouchableOpacity accessibilityRole="button" accessibilityLabel={recording ? 'Stop and upload recording' : 'Start voice recording'} disabled={busy} onPress={toggleRecording} style={[s.recordButton, recording && s.recordActive, busy && s.disabled]}><Text style={s.recordIcon}>{recording ? '■' : '●'}</Text><Text style={s.recordText}>{recording ? 'Stop & log recording' : busy ? 'Please wait…' : 'Record an expense'}</Text></TouchableOpacity>
      <Message text={error}/>
    </View>
    <Section title="Text entry" caption="ALTERNATIVE"/>
    <View style={s.whitePanel}>
      <Text style={s.fieldLabel}>EXPENSE DESCRIPTION</Text>
      <TextInput accessibilityLabel="Expense description" multiline editable={!busy && !recording} placeholder="e.g. spent fourteen bucks on lunch" placeholderTextColor={C.muted} value={text} onChangeText={setText} style={[s.input, s.textArea]}/>
      <Button title={busy ? 'Saving…' : 'Add expense'} disabled={busy || recording} onPress={submitText}/>
    </View>
    <Result data={result}/>
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
  const items = Array.isArray(data?.expenses) ? data.expenses : [];
  return <ScrollView refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={C.orange}/>} contentContainerStyle={s.page}>
    <Header number="02 / OVERVIEW" title="Your history." subtitle="Your spending, with the original entry behind every number."/>
    <Message text={error}/>{loading && !data ? <ActivityIndicator color={C.orange}/> : null}
    {data ? <>
      <View style={s.balance}><Text style={s.smallCap}>TOTAL SPENT THIS WEEK</Text><Text style={s.balanceAmount}>{money(data.weekTotalCents)}</Text><Text style={s.balanceFoot}>{items.length} transactions · Pull down to refresh</Text><View style={s.balanceCorner}/></View>
      <Section title="By category" caption="THIS WEEK"/>
      <View style={s.ledger}>{CATEGORIES.map((cat, i) => <View key={cat} style={[s.ledgerRow, i > 0 && s.ledgerBorder]}><View style={[s.marker, { backgroundColor: i % 2 ? C.yellow : C.coral }]}/><Text style={s.ledgerName}>{cat}</Text><Text style={s.ledgerValue}>{money(data.totalsByCategory?.[cat])}</Text></View>)}</View>
      <Section title="Transactions" caption="TAP FOR DETAILS"/>
      <View style={s.ledger}>{items.length === 0 ? <Text style={s.empty}>No expenses this week. Add your first expense in Log.</Text> : items.map((item, i) => {
        const id = String(item.id ?? i); const original = item.originalText ?? item.original_text ?? '';
        const cents = item.amountCents ?? item.amount_cents ?? item.cents;
        const date = item.createdAt ?? item.created_at ?? item.occurredAt ?? item.occurred_at ?? '';
        return <TouchableOpacity accessibilityRole="button" key={id} onPress={() => setExpanded(expanded === id ? null : id)} style={[s.transaction, i > 0 && s.ledgerBorder]}>
          <View style={s.transactionGlyph}><Text style={s.transactionGlyphText}>↗</Text></View>
          <View style={s.transactionCopy}><Text style={s.ledgerName}>{item.merchant || item.category || 'Expense'}</Text><Text style={s.transactionMeta}>{item.category}{date ? ` · ${String(date).slice(0, 10)}` : ''}</Text></View>
          <Text style={s.ledgerValue}>−{money(cents)}</Text>
          {expanded === id ? <Text style={s.transactionOriginal}>Original entry: “{original || 'Not available'}”</Text> : null}
        </TouchableOpacity>;
      })}</View>
    </> : null}
  </ScrollView>;
}
function LimitsScreen() {
  const [limits, setLimits] = useState({});
  const [inputs, setInputs] = useState({});
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { const { limits: values = {} } = await getLimits(); setLimits(values); setInputs(Object.fromEntries(CATEGORIES.map(cat => [cat, dollars(values[cat])]))); }
    catch (err) { setError(err.message || 'Could not load limits.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const save = async (cat) => {
    const cents = parseDollars(inputs[cat] || '');
    if (cents === null) { setError(`Enter a valid ${cat} limit, such as 50.25.`); return; }
    setBusy(cat); setError(''); setSaved('');
    try { const data = await saveLimit(cat, cents); setLimits(data.limits || { ...limits, [cat]: cents }); setInputs(old => ({ ...old, [cat]: dollars(cents) })); setSaved(`${cat} limit saved: ${money(cents)}`); }
    catch (err) { setError(err.message || 'Could not save limit.'); }
    finally { setBusy(''); }
  };
  return <ScrollView keyboardShouldPersistTaps="handled" refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={C.orange}/>} contentContainerStyle={s.page}>
    <Header number="03 / BUDGETS" title="Spending limits." subtitle="Set weekly limits for each spending category."/>
    <View style={s.notice}><Text style={s.noticeIndex}>01</Text><Text style={s.noticeCopy}>The backend checks every new expense. Exceeding a category limit triggers an alert call; repeat alerts for that category are suppressed for the week.</Text></View>
    <Message text={error}/><Message text={saved} positive/>
    <Section title="Weekly budgets" caption="AMOUNTS IN USD"/>
    <View style={s.ledger}>{CATEGORIES.map((cat, i) => <View key={cat} style={[s.limitRow, i > 0 && s.ledgerBorder]}><View style={s.limitTop}><Text style={s.ledgerName}>{cat}</Text><Text style={s.transactionMeta}>Current: {money(limits[cat])}</Text></View><View style={s.limitBottom}><Text style={s.currency}>$</Text><TextInput keyboardType="decimal-pad" accessibilityLabel={`${cat} limit in dollars`} value={inputs[cat] ?? ''} onChangeText={value => setInputs(old => ({ ...old, [cat]: value }))} style={s.limitInput}/><TouchableOpacity accessibilityRole="button" disabled={!!busy} onPress={() => save(cat)} style={[s.saveChip, !!busy && s.disabled]}><Text style={s.saveChipText}>{busy === cat ? '…' : 'Save'}</Text></TouchableOpacity></View></View>)}</View>
  </ScrollView>;
}
function SettingsScreen() {
  const [days, setDays] = useState([0]);
  const [hour, setHour] = useState(18);
  const [phone, setPhone] = useState('');
  const [savedSettings, setSavedSettings] = useState(null);
  const [multiSupported, setMultiSupported] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [developer, setDeveloper] = useState(false);
  const [testNumber, setTestNumber] = useState('');
  const [callMessage, setCallMessage] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const data = await getSettings(); const value = data.settings || {};
      const supported = Array.isArray(value.callDays);
      setMultiSupported(supported);
      setDays(supported && value.callDays.length ? value.callDays : [value.callDay ?? 0]);
      setHour(value.callHour ?? 18); setPhone(value.phoneNumber || '');
      setSavedSettings(value); setTestNumber(value.phoneNumber || '');
    } catch (err) { setError(err.message || 'Could not load call settings.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const toggleDay = (index) => setDays(old => old.includes(index) ? (old.length === 1 ? old : old.filter(n => n !== index)) : [...old, index].sort((a, b) => a - b));
  const save = async () => {
    if (!validPhone(phone)) { setError('Use a phone number with country code, e.g. +14155550123.'); return; }
    if (!multiSupported && days.length > 1) { setError('Multiple scheduled days need a backend update. Choose one day to save for now.'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      const payload = { callDay: days[0], callHour: hour, phoneNumber: phone.trim() };
      if (multiSupported) payload.callDays = days;
      const data = await saveSettings(payload);
      const value = data.settings || payload;
      setSavedSettings(value); setTestNumber(value.phoneNumber || phone.trim());
      setNotice('Call settings saved on the server.');
    } catch (err) { setError(err.message || 'Could not save call settings.'); }
    finally { setBusy(false); }
  };
  const placeTestCall = async () => {
    setBusy(true); setCallMessage('');
    try {
      if (!savedSettings) throw new Error('Load and save call settings first.');
      const number = testNumber.trim();
      if (!validPhone(number)) throw new Error('Enter a phone number with country code, e.g. +14155550123.');
      // The existing backend only dials the saved number. Do not silently edit it.
      if (number !== savedSettings.phoneNumber) throw new Error('This backend can only dial the saved phone number. Save this number in regular Settings first, then try again. Ask Sebastian to support a one-time phoneNumber override.');
      const data = await triggerWeeklyCall();
      if (!data.ok) throw new Error(data.error || data.call?.error || 'The server could not place the call. Check Twilio and number verification.');
      setCallMessage('The server accepted the summary call request to your saved number.');
    } catch (err) { setCallMessage(err.message || 'Call failed.'); }
    finally { setBusy(false); }
  };
  if (developer) return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.devScreen}>
    <TouchableOpacity accessibilityRole="button" onPress={() => setDeveloper(false)} style={s.devBack}><Text style={s.devBackText}>← Back to settings</Text></TouchableOpacity>
    <Text style={s.devKicker}>INTERNAL / DEVELOPER</Text>
    <Text style={s.devTitle}>Call testing.</Text>
    <Text style={s.devDescription}>Development tool only. This panel is not password-protected. Calls may incur charges; trial Twilio accounts can dial only verified numbers.</Text>
    <View style={s.devCard}>
      <Text style={s.devLabel}>DESTINATION NUMBER</Text>
      <TextInput accessibilityLabel="Developer call destination" keyboardType="phone-pad" autoComplete="tel" placeholder="+14155550123" placeholderTextColor={C.devMuted} style={s.devInput} value={testNumber} onChangeText={setTestNumber}/>
      <Text style={s.devHint}>The current backend dials the saved number only. To use a different number, save it on the regular Settings screen first.</Text>
      <TouchableOpacity accessibilityRole="button" disabled={busy} onPress={() => Alert.alert('Place summary call?', `Call ${testNumber.trim() || 'the saved number'} now with your weekly spending summary? Carrier/Twilio charges may apply.`, [{ text: 'Cancel', style: 'cancel' }, { text: 'Call now', onPress: placeTestCall }])} style={[s.devButton, busy && s.disabled]}><Text style={s.devButtonText}>{busy ? 'Calling…' : 'Call spending summary'}</Text><Text style={s.devButtonText}>↗</Text></TouchableOpacity>
      <Message text={callMessage} positive={callMessage.startsWith('The server accepted')}/>
    </View>
  </ScrollView>;
  return <ScrollView keyboardShouldPersistTaps="handled" refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={C.orange}/>} contentContainerStyle={s.page}>
    <Header number="04 / PREFERENCES" title="Call settings." subtitle="Choose when to receive your spending summary."/>
    <Message text={error}/><Message text={notice} positive/>
    <Section title="Frequency" caption="PER WEEK"/>
    <View style={s.whitePanel}>
      <Text style={s.frequencyNumber}>{days.length} <Text style={s.frequencyUnit}>{days.length === 1 ? 'day per week' : 'days per week'}</Text></Text>
      <Text style={s.smallBody}>Select the days you want us to call.</Text>
      <View style={s.dayRow}>{DAYS.map((day, index) => <TouchableOpacity key={day} accessibilityRole="checkbox" accessibilityState={{ checked: days.includes(index) }} onPress={() => toggleDay(index)} style={[s.dayChip, days.includes(index) && s.dayChipActive]}><Text style={[s.dayText, days.includes(index) && s.dayTextActive]}>{day.slice(0, 3)}</Text></TouchableOpacity>)}</View>
      {!multiSupported ? <Text style={s.infoNote}>Sebastian’s server currently supports one scheduled day per week. You can preview multiple days here, but only one can be saved until the server is updated.</Text> : null}
    </View>
    <Section title="Call time" caption="LOCAL TIME"/>
    <View style={s.whitePanel}><View style={s.hourRow}><TouchableOpacity accessibilityRole="button" accessibilityLabel="Earlier by one hour" onPress={() => setHour(n => (n + 23) % 24)} style={s.hourButton}><Text style={s.hourButtonText}>−</Text></TouchableOpacity><Text style={s.hourText}>{hourLabel(hour)}</Text><TouchableOpacity accessibilityRole="button" accessibilityLabel="Later by one hour" onPress={() => setHour(n => (n + 1) % 24)} style={s.hourButton}><Text style={s.hourButtonText}>+</Text></TouchableOpacity></View></View>
    <Section title="Call destination" caption="PHONE"/>
    <View style={s.whitePanel}><Text style={s.fieldLabel}>PHONE NUMBER</Text><TextInput accessibilityLabel="Scheduled call phone number" keyboardType="phone-pad" autoComplete="tel" placeholder="+14155550123" placeholderTextColor={C.muted} style={s.input} value={phone} onChangeText={setPhone}/>
      <View style={s.scheduleNote}><Text style={s.scheduleText}>{days.map(n => DAYS[n]).join(', ')} at {hourLabel(hour)}.</Text></View>
      <Button title={busy ? 'Saving…' : 'Save call settings'} disabled={busy || loading || (!multiSupported && days.length > 1)} onPress={save}/>
    </View>
    <Section title="Developer" caption="TESTING"/>
    <TouchableOpacity accessibilityRole="button" onPress={() => { setCallMessage(''); setDeveloper(true); }} style={s.devLink}><Text style={s.devLinkTitle}>Developer tools</Text><Text style={s.devLinkArrow}>→</Text></TouchableOpacity>
  </ScrollView>;
}
const TABS = [{ key: 'Log', icon: '+' }, { key: 'History', icon: '≡' }, { key: 'Limits', icon: '◉' }, { key: 'Settings', icon: '⚙' }];
export default function App() {
  const [tab, setTab] = useState('Log');
  const [revision, setRevision] = useState(0);
  return <SafeAreaView style={s.safe}>
    <StatusBar barStyle={tab === 'Settings' ? 'dark-content' : 'dark-content'} backgroundColor={C.bg}/>
    <View style={s.content}>{tab === 'Log' ? <LogScreen onLogged={() => setRevision(n => n + 1)}/> : tab === 'History' ? <HistoryScreen revision={revision}/> : tab === 'Limits' ? <LimitsScreen/> : <SettingsScreen/>}</View>
    <View style={s.tabs}>{TABS.map(item => <TouchableOpacity key={item.key} accessibilityRole="tab" accessibilityState={{ selected: tab === item.key }} onPress={() => setTab(item.key)} style={[s.tab, tab === item.key && s.tabActive]}><Text style={[s.tabIcon, tab === item.key && s.tabIconActive]}>{item.icon}</Text><Text style={[s.tabName, tab === item.key && s.tabNameActive]}>{item.key}</Text></TouchableOpacity>)}</View>
  </SafeAreaView>;
}
const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg }, content: { flex: 1 }, page: { paddingHorizontal: 23, paddingTop: 18, paddingBottom: 55 },
  brandRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 29 }, brandMark: { width: 11, height: 11, backgroundColor: C.coral, transform: [{ rotate: '45deg' }], marginRight: 11 }, brand: { fontFamily: F.bold, letterSpacing: 1.7, fontSize: 10, color: C.ink },
  header: { marginBottom: 21 }, kicker: { fontFamily: F.bold, fontSize: 10, letterSpacing: 1.5, color: C.orange, marginBottom: 8 }, title: { fontFamily: F.display, color: C.black, fontSize: 37, lineHeight: 44 }, subtitle: { fontFamily: F.body, color: C.muted, fontSize: 14, lineHeight: 21, marginTop: 8 },
  section: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 26, marginBottom: 12 }, sectionTitle: { fontFamily: F.bold, fontSize: 19, color: C.ink }, sectionCaption: { fontFamily: F.bold, color: C.muted, fontSize: 9, letterSpacing: 1 },
  hero: { backgroundColor: C.coral, padding: 22, borderRadius: 7, borderTopRightRadius: 42, overflow: 'hidden' }, smallCap: { fontFamily: F.bold, fontSize: 10, letterSpacing: 1.5, color: C.black }, heroRow: { flexDirection: 'row', alignItems: 'center', marginTop: 25 }, heroWords: { flex: 1 }, heroTitle: { fontFamily: F.display, fontSize: 29, lineHeight: 37, color: C.white }, coin: { height: 68, width: 68, borderRadius: 34, backgroundColor: C.yellow, borderColor: C.black, borderWidth: 2, justifyContent: 'center', alignItems: 'center', transform: [{ rotate: '-14deg' }] }, coinText: { fontFamily: F.display, fontSize: 38, color: C.black }, heroRule: { width: 23, height: 3, backgroundColor: C.yellow, marginTop: 30 }, heroFoot: { fontFamily: F.medium, color: C.black, fontSize: 11, marginTop: 10 },
  whitePanel: { backgroundColor: C.white, borderColor: C.line, borderWidth: 1, borderRadius: 6, padding: 18 }, smallBody: { fontFamily: F.body, fontSize: 13, lineHeight: 20, color: C.ink, marginTop: 7 }, fieldLabel: { fontFamily: F.bold, fontSize: 10, letterSpacing: 1, color: C.ink }, input: { borderWidth: 1, borderColor: C.line, backgroundColor: C.white, padding: 12, marginTop: 12, borderRadius: 4, fontFamily: F.body, fontSize: 15, color: C.black }, textArea: { minHeight: 82, textAlignVertical: 'top', marginBottom: 12 },
  button: { backgroundColor: C.black, marginTop: 10, paddingHorizontal: 17, paddingVertical: 15, borderRadius: 4, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, buttonSecondary: { backgroundColor: C.yellow }, buttonLabel: { fontFamily: F.bold, color: C.white, fontSize: 14 }, buttonArrow: { color: C.yellow, fontSize: 20 }, buttonSecondaryLabel: { color: C.black }, disabled: { opacity: 0.47 }, message: { fontFamily: F.medium, color: C.red, fontSize: 12, lineHeight: 19, marginTop: 13 }, positive: { color: C.green },
  recordButton: { backgroundColor: C.black, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingVertical: 18, borderRadius: 4, marginTop: 16, gap: 12 }, recordActive: { backgroundColor: C.orange }, recordIcon: { color: C.coral, fontSize: 22 }, recordText: { fontFamily: F.bold, color: C.white, fontSize: 14 },
  savedPanel: { backgroundColor: C.yellow, borderRadius: 5, marginTop: 20, padding: 21 }, savedAmount: { fontFamily: F.display, color: C.black, fontSize: 42, marginTop: 7 }, savedCategory: { fontFamily: F.bold, color: C.ink, marginTop: 4 }, divider: { backgroundColor: '#D7CB58', height: 1, marginVertical: 16 }, warn: { fontFamily: F.medium, color: C.red, fontSize: 13, marginTop: 12 }, overPanel: { backgroundColor: C.peach, padding: 20, marginTop: 16, borderLeftWidth: 4, borderLeftColor: C.orange }, overTitle: { fontFamily: F.display, fontSize: 22, color: C.black, marginTop: 8 },
  balance: { backgroundColor: C.coral, minHeight: 205, padding: 23, borderRadius: 7, borderTopRightRadius: 42, overflow: 'hidden' }, balanceAmount: { fontFamily: F.display, fontSize: 46, color: C.white, marginTop: 24 }, balanceFoot: { fontFamily: F.medium, color: C.black, fontSize: 11, marginTop: 21 }, balanceCorner: { position: 'absolute', width: 85, height: 85, backgroundColor: C.yellow, right: -38, bottom: -37, transform: [{ rotate: '33deg' }] },
  ledger: { backgroundColor: C.white, borderWidth: 1, borderColor: C.line, borderRadius: 5, paddingHorizontal: 18 }, ledgerRow: { flexDirection: 'row', alignItems: 'center', minHeight: 56 }, ledgerBorder: { borderTopWidth: 1, borderTopColor: C.line }, marker: { width: 11, height: 11, borderRadius: 2, marginRight: 12 }, ledgerName: { flex: 1, color: C.ink, fontFamily: F.medium, fontSize: 14 }, ledgerValue: { fontFamily: F.bold, fontSize: 14, color: C.black }, empty: { fontFamily: F.body, color: C.muted, fontSize: 13, lineHeight: 20, paddingVertical: 22 },
  transaction: { minHeight: 73, flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap' }, transactionGlyph: { height: 36, width: 36, borderRadius: 4, backgroundColor: C.bg, justifyContent: 'center', alignItems: 'center', marginRight: 11 }, transactionGlyphText: { fontSize: 19, color: C.orange }, transactionCopy: { flex: 1, paddingVertical: 13 }, transactionMeta: { fontFamily: F.body, color: C.muted, fontSize: 11, marginTop: 4 }, transactionOriginal: { width: '100%', borderTopWidth: 1, borderTopColor: C.line, paddingVertical: 14, fontFamily: F.body, fontSize: 13, color: C.muted },
  notice: { backgroundColor: C.yellow, padding: 18, borderRadius: 4, flexDirection: 'row' }, noticeIndex: { fontFamily: F.display, fontSize: 29, marginRight: 18, color: C.black }, noticeCopy: { flex: 1, fontFamily: F.body, fontSize: 12, lineHeight: 19, color: C.ink }, limitRow: { paddingVertical: 16 }, limitTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, limitBottom: { flexDirection: 'row', alignItems: 'center', marginTop: 7 }, currency: { fontFamily: F.bold, color: C.black, fontSize: 19 }, limitInput: { flex: 1, borderBottomWidth: 1, borderBottomColor: C.line, paddingVertical: 7, paddingHorizontal: 10, fontFamily: F.medium, color: C.black, fontSize: 16, marginHorizontal: 8 }, saveChip: { backgroundColor: C.black, paddingHorizontal: 16, paddingVertical: 10, borderRadius: 3 }, saveChipText: { fontFamily: F.bold, color: C.white, fontSize: 12 },
  frequencyNumber: { fontFamily: F.display, color: C.black, fontSize: 38 }, frequencyUnit: { fontFamily: F.medium, fontSize: 14 }, dayRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginTop: 17 }, dayChip: { borderWidth: 1, borderColor: C.line, borderRadius: 3, paddingVertical: 11, paddingHorizontal: 13, minWidth: 59, alignItems: 'center' }, dayChipActive: { backgroundColor: C.coral, borderColor: C.coral }, dayText: { fontFamily: F.bold, fontSize: 11, color: C.ink }, dayTextActive: { color: C.black }, infoNote: { fontFamily: F.body, color: C.red, fontSize: 12, lineHeight: 19, marginTop: 18 }, hourRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: C.bg, padding: 5 }, hourButton: { backgroundColor: C.white, height: 46, width: 48, alignItems: 'center', justifyContent: 'center' }, hourButtonText: { fontFamily: F.bold, fontSize: 23, color: C.black }, hourText: { fontFamily: F.bold, fontSize: 18, color: C.black }, scheduleNote: { backgroundColor: C.yellow, padding: 13, marginTop: 17 }, scheduleText: { fontFamily: F.bold, color: C.black, fontSize: 12 },
  devLink: { backgroundColor: C.black, borderRadius: 5, padding: 20, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, devLinkTitle: { fontFamily: F.bold, color: C.white, fontSize: 15 }, devLinkArrow: { fontSize: 20, color: C.coral }, devScreen: { backgroundColor: C.devBg, flexGrow: 1, paddingHorizontal: 23, paddingTop: 28, paddingBottom: 50 }, devBack: { paddingVertical: 12 }, devBackText: { fontFamily: F.bold, color: C.devMuted, fontSize: 13 }, devKicker: { fontFamily: F.bold, color: C.devRed, letterSpacing: 2, fontSize: 10, marginTop: 30 }, devTitle: { fontFamily: F.display, color: C.white, fontSize: 39, marginTop: 9 }, devDescription: { fontFamily: F.body, color: C.devMuted, lineHeight: 21, fontSize: 13, marginTop: 14, marginBottom: 28 }, devCard: { borderWidth: 1, borderColor: '#63323B', backgroundColor: C.devPanel, padding: 19, borderRadius: 4 }, devLabel: { fontFamily: F.bold, color: C.devMuted, fontSize: 10, letterSpacing: 1.2 }, devInput: { borderWidth: 1, borderColor: '#7D3B45', color: C.white, fontSize: 16, marginTop: 12, padding: 13, borderRadius: 3, fontFamily: F.body }, devHint: { fontFamily: F.body, color: C.devMuted, fontSize: 12, lineHeight: 19, marginTop: 16 }, devButton: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', backgroundColor: C.devRed, borderRadius: 3, padding: 16, marginTop: 22 }, devButtonText: { fontFamily: F.bold, color: C.white, fontSize: 14 },
  tabs: { backgroundColor: C.white, flexDirection: 'row', paddingHorizontal: 10, paddingTop: 10, paddingBottom: 10, borderTopColor: C.line, borderTopWidth: 1 }, tab: { flex: 1, alignItems: 'center', paddingVertical: 4, borderBottomWidth: 3, borderBottomColor: 'transparent' }, tabActive: { borderBottomColor: C.coral }, tabIcon: { fontFamily: F.bold, fontSize: 20, height: 27, color: C.muted }, tabIconActive: { color: C.black }, tabName: { fontFamily: F.medium, fontSize: 10, color: C.muted }, tabNameActive: { fontFamily: F.bold, color: C.black },
});
