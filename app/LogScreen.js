import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Keyboard, Platform, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder, useAudioRecorderState } from 'expo-audio';
import { getHealth, logReceiptPhoto, logReceiptText, logTextExpense, logVoiceExpense } from './api';

const P = { bg: '#EFF4F8', white: '#FFFFFF', ink: '#192D42', black: '#111923', muted: '#647687', line: '#DCE5EB', coral: '#FF855B', yellow: '#FFF36A', peach: '#FFF0DE', red: '#AA3030', green: '#287C54' };
const font = { display: Platform.OS === 'ios' ? 'Georgia-Bold' : 'serif', body: Platform.OS === 'ios' ? 'AvenirNext-Regular' : 'sans-serif', bold: Platform.OS === 'ios' ? 'AvenirNext-Bold' : 'sans-serif-medium' };
const money = value => `$${((Number(value) || 0) / 100).toFixed(2)}`;

function MainButton({ title, onPress, disabled, light }) {
  return <TouchableOpacity accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.mainButton, light && styles.lightButton, disabled && styles.disabled]}><Text style={[styles.mainButtonText, light && styles.lightButtonText]}>{title}</Text><Text style={[styles.arrow, light && styles.lightButtonText]}>→</Text></TouchableOpacity>;
}

export default function LogScreen({ onLogged }) {
  const [mode, setMode] = useState(null);
  const [text, setText] = useState('');
  const [receiptText, setReceiptText] = useState('');
  const [photo, setPhoto] = useState(null);
  const [ocrAvailable, setOcrAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder);

  useEffect(() => {
    let active = true;
    getHealth().then(health => {
      if (active) setOcrAvailable(health.receiptOcrEnabled === true || health.capabilities?.receiptOCR === true);
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  function select(next) {
    if (busy || recording) return;
    setMode(current => current === next ? null : next);
    setError('');
    setResult(null);
    Keyboard.dismiss();
  }

  function accept(data) {
    if (!data?.expense) throw new Error('The server did not return a saved expense.');
    setResult(data);
    onLogged();
  }

  async function send(action, reset) {
    if (busy || recording) return;
    setBusy(true); setError(''); setResult(null);
    try { accept(await action()); reset?.(); Keyboard.dismiss(); }
    catch (err) { setError(err.message || 'Could not save this expense.'); }
    finally { setBusy(false); }
  }

  async function captureReceipt() {
    if (busy || recording) return;
    setMode('camera'); setError(''); setResult(null);
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) throw new Error('Camera access is required. Allow it in iPhone Settings and try again.');
      const picture = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.75, allowsEditing: false });
      if (!picture.canceled && picture.assets?.[0]?.uri) { setPhoto(picture.assets[0]); setReceiptText(''); }
    } catch (err) { setError(err.message || 'Could not open the camera.'); }
  }

  async function choosePhoto() {
    if (busy || recording) return;
    setError('');
    try {
      const picture = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.75, allowsEditing: false });
      if (!picture.canceled && picture.assets?.[0]?.uri) { setPhoto(picture.assets[0]); setReceiptText(''); }
    } catch (err) { setError(err.message || 'Could not select a photo.'); }
  }

  async function toggleRecording() {
    if (busy) return;
    setError('');
    if (!recording) {
      setBusy(true); setResult(null);
      try {
        const permission = await AudioModule.requestRecordingPermissionsAsync();
        if (!permission.granted) throw new Error('Microphone access is required. Allow it in iPhone Settings.');
        await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
        await recorder.prepareToRecordAsync();
        recorder.record();
        setRecording(true);
      } catch (err) { setError(err.message || 'Could not start recording.'); await setAudioModeAsync({ allowsRecording: false }).catch(() => {}); }
      finally { setBusy(false); }
      return;
    }
    setBusy(true);
    try {
      await recorder.stop();
      setRecording(false);
      await setAudioModeAsync({ allowsRecording: false });
      accept(await logVoiceExpense(recorder.uri));
    } catch (err) { setRecording(false); setError(err.message || 'Could not save the recording.'); }
    finally { setBusy(false); await setAudioModeAsync({ allowsRecording: false }).catch(() => {}); }
  }

  const expense = result?.expense;
  const limit = result?.limitCheck;
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.page}>
    <View style={styles.brandRow}><View style={styles.brandMark}/><Text style={styles.brand}>WHERE IS MY MONEY</Text></View>
    <Text style={styles.kicker}>01 / EXPENSES</Text>
    <Text style={styles.title}>Log an expense.</Text>
    <Text style={styles.subtitle}>Choose the easiest way to add a purchase.</Text>

    <View style={styles.hero}><Text style={styles.heroSmall}>NEW ENTRY</Text><Text style={styles.heroTitle}>Three ways to keep track.</Text><Text style={styles.heroDescription}>Your expenses, organized in one place.</Text><View style={styles.yellowTab}/></View>

    <Text style={styles.sectionLabel}>CHOOSE AN ENTRY METHOD</Text>
    <TouchableOpacity accessibilityRole="button" accessibilityState={{ expanded: mode === 'camera' }} disabled={busy || recording} onPress={captureReceipt} style={[styles.method, mode === 'camera' && styles.methodSelected]}><View style={[styles.methodIcon, { backgroundColor: P.yellow }]}><Text style={styles.methodGlyph}>▣</Text></View><View style={styles.methodCopy}><Text style={styles.methodTitle}>Scan a receipt</Text><Text style={styles.methodSubtitle}>Use your camera to capture a purchase</Text></View><Text style={styles.methodArrow}>↗</Text></TouchableOpacity>
    <TouchableOpacity accessibilityRole="button" accessibilityState={{ expanded: mode === 'voice' }} disabled={busy || recording} onPress={() => select('voice')} style={[styles.method, mode === 'voice' && styles.methodSelected]}><View style={[styles.methodIcon, { backgroundColor: P.coral }]}><Text style={styles.methodGlyph}>●</Text></View><View style={styles.methodCopy}><Text style={styles.methodTitle}>Record your voice</Text><Text style={styles.methodSubtitle}>Say what you spent, then save</Text></View><Text style={styles.methodArrow}>↗</Text></TouchableOpacity>
    <TouchableOpacity accessibilityRole="button" accessibilityState={{ expanded: mode === 'text' }} disabled={busy || recording} onPress={() => select('text')} style={[styles.method, mode === 'text' && styles.methodSelected]}><View style={[styles.methodIcon, { backgroundColor: P.bg }]}><Text style={styles.methodGlyph}>≡</Text></View><View style={styles.methodCopy}><Text style={styles.methodTitle}>Type an expense</Text><Text style={styles.methodSubtitle}>Quickly add the details yourself</Text></View><Text style={styles.methodArrow}>↗</Text></TouchableOpacity>

    {mode === 'camera' && <View style={styles.panel}>
      <Text style={styles.panelTitle}>Receipt capture</Text>
      {photo ? <Image source={{ uri: photo.uri }} resizeMode="contain" accessibilityLabel="Receipt photo preview" style={styles.preview}/> : <Text style={styles.hint}>Take a picture to preview your receipt.</Text>}
      <MainButton title={photo ? 'Retake photo' : 'Open camera'} onPress={captureReceipt} disabled={busy} light/>
      <TouchableOpacity accessibilityRole="button" onPress={choosePhoto} disabled={busy} style={styles.secondaryLink}><Text style={styles.secondaryLinkText}>Or choose a photo from your library →</Text></TouchableOpacity>
      {photo ? <>
        <Text style={styles.hint}>{ocrAvailable ? 'Your server reports receipt scanning is available. Review the saved amount and category after scanning.' : 'Scan this photo to send it to the backend. Review the saved amount and category after scanning.'}</Text>
        <MainButton title={busy ? 'Scanning…' : 'Scan and add expense'} disabled={busy} onPress={() => send(() => logReceiptPhoto(photo), () => { setPhoto(null); setReceiptText(''); })}/>
        <Text style={styles.fieldLabel}>OR TYPE THE TOTAL AND PURCHASE DETAILS</Text>
        <TextInput accessibilityLabel="Receipt total and purchase details" editable={!busy} multiline placeholder="e.g. $14.00 for lunch at the cafe" placeholderTextColor={P.muted} style={[styles.input, styles.area]} value={receiptText} onChangeText={setReceiptText}/>
        <Text style={styles.hint}>Optional: type the total if you prefer not to scan the photo.</Text>
        <MainButton title={busy ? 'Saving…' : 'Categorize and add expense'} disabled={busy || !receiptText.trim()} onPress={() => send(() => logReceiptText(receiptText), () => { setReceiptText(''); setPhoto(null); })}/>
      </> : null}
    </View>}

    {mode === 'voice' && <View style={styles.panel}><Text style={styles.panelTitle}>Voice recording</Text><Text style={styles.hint}>{recording ? `Recording · ${Math.round((recorderState.durationMillis || 0) / 1000)} seconds` : busy ? 'Processing your recording…' : 'Tap record, describe the purchase, then tap stop to save.'}</Text><TouchableOpacity accessibilityRole="button" accessibilityLabel={recording ? 'Stop and save recording' : 'Start recording'} disabled={busy} onPress={toggleRecording} style={[styles.record, recording && styles.recordActive, busy && styles.disabled]}><Text style={styles.recordSymbol}>{recording ? '■' : '●'}</Text><Text style={styles.recordLabel}>{recording ? 'Stop and save' : busy ? 'Please wait…' : 'Start recording'}</Text></TouchableOpacity></View>}

    {mode === 'text' && <View style={styles.panel}><Text style={styles.panelTitle}>Text entry</Text><Text style={styles.fieldLabel}>WHAT DID YOU SPEND?</Text><TextInput accessibilityLabel="Expense description" editable={!busy} multiline placeholder="e.g. spent fourteen bucks on lunch" placeholderTextColor={P.muted} style={[styles.input, styles.area]} value={text} onChangeText={setText}/><MainButton title={busy ? 'Saving…' : 'Categorize and add expense'} disabled={busy || !text.trim()} onPress={() => send(() => logTextExpense(text), () => setText(''))}/></View>}

    {busy ? <ActivityIndicator style={styles.spinner} color={P.black}/> : null}
    {error ? <View style={styles.errorBox}><Text style={styles.error}>{error}</Text></View> : null}
    {expense ? <View style={styles.success}><Text style={styles.successEyebrow}>EXPENSE SAVED</Text><Text style={styles.successAmount}>{money(expense.amountCents ?? expense.amount_cents ?? expense.cents)}</Text><Text style={styles.successCategory}>{expense.category}{expense.merchant ? ` · ${expense.merchant}` : ''}</Text><Text style={styles.hint}>“{expense.originalText ?? expense.original_text ?? ''}”</Text>{expense.needsReview || expense.needs_review ? <Text style={styles.error}>Please verify the detected amount and category.</Text> : null}</View> : null}
    {limit && Number(limit.overByCents) > 0 ? <View style={styles.over}><Text style={styles.overLabel}>SPENDING LIMIT EXCEEDED</Text><Text style={styles.overTitle}>{money(limit.overByCents)} over your {limit.category} limit</Text><Text style={styles.hint}>{money(limit.weekTotalCents)} spent / {money(limit.limitCents)} limit</Text><Text style={styles.hint}>{limit.action === 'placed_call' ? 'The backend placed your alert call.' : limit.action === 'already_called' ? 'An alert was already sent this week.' : limit.action === 'call_failed' ? 'The alert call failed. Check call settings.' : `Call status: ${limit.action || 'unavailable'}`}</Text></View> : null}
  </ScrollView>;
}

const styles = StyleSheet.create({
  page: { paddingHorizontal: 23, paddingTop: 18, paddingBottom: 55, backgroundColor: P.bg },
  brandRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 29 }, brandMark: { width: 11, height: 11, backgroundColor: P.coral, transform: [{ rotate: '45deg' }], marginRight: 11 }, brand: { fontFamily: font.bold, letterSpacing: 1.7, fontSize: 10, color: P.ink },
  kicker: { fontFamily: font.bold, fontSize: 10, letterSpacing: 1.5, color: '#E96042', marginBottom: 8 }, title: { fontFamily: font.display, color: P.black, fontSize: 37, lineHeight: 44 }, subtitle: { fontFamily: font.body, color: P.muted, fontSize: 14, lineHeight: 21, marginTop: 8, marginBottom: 23 },
  hero: { backgroundColor: P.coral, padding: 23, minHeight: 165, overflow: 'hidden', borderTopRightRadius: 40, borderRadius: 6 }, heroSmall: { fontFamily: font.bold, letterSpacing: 1.6, fontSize: 10, color: P.black }, heroTitle: { fontFamily: font.display, color: P.white, fontSize: 29, lineHeight: 35, marginTop: 18, maxWidth: 248 }, heroDescription: { fontFamily: font.body, fontSize: 12, color: P.black, marginTop: 10 }, yellowTab: { backgroundColor: P.yellow, height: 70, width: 70, transform: [{ rotate: '32deg' }], position: 'absolute', bottom: -36, right: -30 },
  sectionLabel: { fontFamily: font.bold, fontSize: 10, letterSpacing: 1.2, color: P.muted, marginTop: 28, marginBottom: 11 },
  method: { flexDirection: 'row', alignItems: 'center', paddingVertical: 15, paddingHorizontal: 14, marginBottom: 9, backgroundColor: P.white, borderWidth: 1, borderColor: P.line, borderRadius: 6 }, methodSelected: { borderColor: P.coral, borderWidth: 2, paddingVertical: 14, paddingHorizontal: 13 }, methodIcon: { width: 48, height: 48, borderRadius: 5, justifyContent: 'center', alignItems: 'center', marginRight: 14 }, methodGlyph: { color: P.black, fontSize: 25, fontFamily: font.bold }, methodCopy: { flex: 1 }, methodTitle: { fontFamily: font.bold, color: P.ink, fontSize: 15 }, methodSubtitle: { fontFamily: font.body, color: P.muted, fontSize: 11, marginTop: 4, lineHeight: 16 }, methodArrow: { color: P.ink, fontSize: 20, marginLeft: 8 },
  panel: { marginTop: 13, backgroundColor: P.white, borderColor: P.line, borderWidth: 1, padding: 19, borderRadius: 6 }, panelTitle: { color: P.black, fontFamily: font.display, fontSize: 23, marginBottom: 13 }, fieldLabel: { color: P.ink, fontFamily: font.bold, fontSize: 10, letterSpacing: 1, marginTop: 12 }, hint: { fontFamily: font.body, color: P.muted, fontSize: 12, lineHeight: 19, marginTop: 10 }, preview: { width: '100%', height: 235, backgroundColor: P.bg, marginVertical: 8, borderRadius: 4 },
  mainButton: { backgroundColor: P.black, padding: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderRadius: 4, marginTop: 16 }, mainButtonText: { fontFamily: font.bold, color: P.white, fontSize: 14 }, arrow: { color: P.yellow, fontSize: 21 }, lightButton: { backgroundColor: P.yellow }, lightButtonText: { color: P.black }, secondaryLink: { paddingVertical: 14 }, secondaryLinkText: { color: P.ink, fontSize: 13, fontFamily: font.bold }, disabled: { opacity: 0.48 }, input: { backgroundColor: P.white, borderColor: P.line, borderWidth: 1, padding: 13, marginTop: 11, borderRadius: 4, fontFamily: font.body, color: P.black, fontSize: 15 }, area: { minHeight: 95, textAlignVertical: 'top' }, info: { backgroundColor: P.peach, borderLeftWidth: 3, borderLeftColor: P.coral, padding: 13, marginTop: 14 }, infoText: { fontFamily: font.body, color: P.ink, fontSize: 12, lineHeight: 19 }, record: { marginTop: 18, padding: 18, borderRadius: 4, backgroundColor: P.black, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 11 }, recordActive: { backgroundColor: '#E96042' }, recordSymbol: { color: P.coral, fontSize: 23 }, recordLabel: { fontFamily: font.bold, color: P.white, fontSize: 14 }, spinner: { marginTop: 17 }, errorBox: { padding: 14, backgroundColor: P.peach, marginTop: 18 }, error: { color: P.red, fontFamily: font.body, fontSize: 13, lineHeight: 20 }, success: { marginTop: 20, padding: 20, backgroundColor: P.yellow, borderRadius: 5 }, successEyebrow: { color: P.black, fontFamily: font.bold, fontSize: 10, letterSpacing: 1 }, successAmount: { color: P.black, fontFamily: font.display, fontSize: 42, marginTop: 7 }, successCategory: { color: P.ink, fontFamily: font.bold, fontSize: 14 }, over: { marginTop: 15, padding: 18, backgroundColor: P.peach, borderLeftColor: '#E96042', borderLeftWidth: 4 }, overLabel: { color: P.red, fontFamily: font.bold, fontSize: 10 }, overTitle: { color: P.black, fontFamily: font.display, fontSize: 22, marginTop: 8 },
});