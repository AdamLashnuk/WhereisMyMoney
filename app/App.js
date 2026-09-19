import React, { useState } from 'react';
import { SafeAreaView, StatusBar, StyleSheet, Text, TouchableOpacity, View, ScrollView } from 'react-native';

const COLORS = { bg: '#F6F7F4', ink: '#172B25', muted: '#6D7A73', green: '#215D43', pale: '#E5EFE7', white: '#FFFFFF', border: '#E4E9E3', amber: '#B46B24' };
const CATEGORIES = ['Food', 'Transport', 'Subscriptions', 'Shopping', 'Bills', 'Other'];
const sampleExpenses = [
  { id: '1', label: 'Lunch', category: 'Food', cents: 1400, original: 'spent fourteen bucks on lunch', date: 'Today' },
  { id: '2', label: 'Bus fare', category: 'Transport', cents: 250, original: 'two fifty for the bus', date: 'Yesterday' },
  { id: '3', label: 'Groceries', category: 'Food', cents: 3245, original: 'thirty two forty five on groceries', date: 'Yesterday' },
];
const money = (cents) => `$${(cents / 100).toFixed(2)}`;

function SectionHeader({ eyebrow, title, subtitle }) {
  return <View style={styles.header}><Text style={styles.eyebrow}>{eyebrow}</Text><Text style={styles.title}>{title}</Text><Text style={styles.subtitle}>{subtitle}</Text></View>;
}
function Card({ children, style }) { return <View style={[styles.card, style]}>{children}</View>; }

function LogScreen() {
  return <ScrollView contentContainerStyle={styles.page}>
    <SectionHeader eyebrow="WHERE IS MY MONEY" title="Log an expense" subtitle="Spend it. Say it. We'll sort it." />
    <Card style={styles.hero}>
      <Text style={styles.heroEyebrow}>VOICE EXPENSE</Text>
      <View style={styles.micCircle}><Text style={styles.micIcon}>●</Text></View>
      <Text style={styles.heroTitle}>Your money, in your words.</Text>
      <Text style={styles.heroDescription}>Recording is coming next. For now, explore the app while we connect the microphone.</Text>
      <View style={styles.disabledButton}><Text style={styles.disabledText}>Hold to record · Coming soon</Text></View>
    </Card>
    <Card style={styles.rowCard}><View style={styles.cameraIcon}><Text style={styles.cameraIconText}>▣</Text></View><View style={styles.flex}><Text style={styles.cardTitle}>Snap a receipt</Text><Text style={styles.cardSub}>Camera upload coming soon</Text></View><Text style={styles.arrow}>›</Text></Card>
    <Text style={styles.sectionTitle}>How it works</Text>
    <Card><Text style={styles.step}>01  Say “spent fourteen bucks on lunch”</Text><View style={styles.line}/><Text style={styles.step}>02  Nemotron finds $14.00 · Food</Text><View style={styles.line}/><Text style={styles.step}>03  We save it to your history</Text></Card>
    <Text style={styles.previewNote}>Preview mode · No expenses are being recorded yet.</Text>
  </ScrollView>;
}
function HistoryScreen() {
  const total = sampleExpenses.reduce((sum, expense) => sum + expense.cents, 0);
  const [openExpense, setOpenExpense] = useState(null);
  return <ScrollView contentContainerStyle={styles.page}>
    <SectionHeader eyebrow="YOUR WEEK" title="Spending history" subtitle="Every number has a story." />
    <Card style={styles.totalCard}><Text style={styles.totalLabel}>TOTAL THIS WEEK · SAMPLE DATA</Text><Text style={styles.totalAmount}>{money(total)}</Text><Text style={styles.totalHint}>3 example expenses</Text></Card>
    <Text style={styles.sectionTitle}>By category</Text>
    <Card>{CATEGORIES.map((category, index) => {
      const cents = sampleExpenses.filter((expense) => expense.category === category).reduce((sum, expense) => sum + expense.cents, 0);
      return <View key={category} style={[styles.categoryRow, index > 0 && styles.categoryBorder]}><Text style={styles.categoryName}>{category}</Text><Text style={styles.categoryAmount}>{money(cents)}</Text></View>;
    })}</Card>
    <Text style={styles.sectionTitle}>Recent expenses</Text>
    {sampleExpenses.map((expense) => <TouchableOpacity accessibilityRole="button" key={expense.id} onPress={() => setOpenExpense(openExpense === expense.id ? null : expense.id)}><Card style={styles.expenseCard}><View style={styles.flex}><Text style={styles.cardTitle}>{expense.label}</Text><Text style={styles.cardSub}>{expense.category} · {expense.date}</Text></View><Text style={styles.expenseAmount}>−{money(expense.cents)}</Text>{openExpense === expense.id && <Text style={styles.original}>Original words: “{expense.original}”</Text>}</Card></TouchableOpacity>)}
    <Text style={styles.previewNote}>Preview mode · These are example expenses, not real transactions.</Text>
  </ScrollView>;
}
function LimitsScreen() {
  return <ScrollView contentContainerStyle={styles.page}>
    <SectionHeader eyebrow="STAY ON TRACK" title="Your limits" subtitle="Make a plan that calls you back." />
    <Card style={styles.notice}><Text style={styles.noticeTitle}>Your rules, your money</Text><Text style={styles.noticeText}>When a category goes even one cent over your weekly limit, you'll get a phone call. Limit editing is coming next.</Text></Card>
    <Text style={styles.sectionTitle}>Weekly category limits</Text>
    <Card>{CATEGORIES.map((category, index) => <View key={category} style={[styles.categoryRow, index > 0 && styles.categoryBorder]}><Text style={styles.categoryName}>{category}</Text><Text style={styles.unset}>Not set</Text></View>)}</Card>
    <Text style={styles.sectionTitle}>Weekly summary call</Text>
    <Card><Text style={styles.cardTitle}>Your call schedule</Text><Text style={styles.cardSub}>Day and hour picker coming next</Text><View style={styles.schedule}><Text style={styles.scheduleText}>We'll call you Sundays at 6pm.</Text></View></Card>
    <Text style={styles.previewNote}>Preview mode · Settings won't save until the backend is connected.</Text>
  </ScrollView>;
}

const TABS = [{ key: 'Log', symbol: '●' }, { key: 'History', symbol: '▤' }, { key: 'Limits', symbol: '◉' }];
export default function App() {
  const [tab, setTab] = useState('Log');
  return <SafeAreaView style={styles.safe}><StatusBar barStyle="dark-content" backgroundColor={COLORS.bg} /><View style={styles.content}>{tab === 'Log' ? <LogScreen /> : tab === 'History' ? <HistoryScreen /> : <LimitsScreen />}</View><View style={styles.tabBar}>{TABS.map((item) => <TouchableOpacity key={item.key} accessibilityRole="tab" accessibilityState={{ selected: tab === item.key }} onPress={() => setTab(item.key)} style={styles.tab}><Text style={[styles.tabSymbol, tab === item.key && styles.tabActive]}>{item.symbol}</Text><Text style={[styles.tabLabel, tab === item.key && styles.tabActive]}>{item.key}</Text></TouchableOpacity>)}</View></SafeAreaView>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg }, content: { flex: 1 }, page: { paddingHorizontal: 22, paddingTop: 24, paddingBottom: 32 },
  header: { marginBottom: 24 }, eyebrow: { fontSize: 11, fontWeight: '800', letterSpacing: 2, color: COLORS.green, marginBottom: 12 }, title: { fontSize: 34, fontWeight: '800', letterSpacing: -1.4, color: COLORS.ink }, subtitle: { fontSize: 15, color: COLORS.muted, marginTop: 8, lineHeight: 22 },
  card: { backgroundColor: COLORS.white, borderRadius: 22, borderWidth: 1, borderColor: COLORS.border, padding: 20, marginBottom: 12 },
  hero: { backgroundColor: COLORS.green, borderColor: COLORS.green, alignItems: 'center', paddingVertical: 28 }, heroEyebrow: { fontSize: 10, fontWeight: '800', letterSpacing: 2, color: '#BFE0CE' }, micCircle: { width: 88, height: 88, borderRadius: 44, backgroundColor: '#39785B', alignItems: 'center', justifyContent: 'center', marginTop: 26, marginBottom: 20 }, micIcon: { fontSize: 43, color: '#FFFFFF' }, heroTitle: { fontSize: 22, fontWeight: '800', color: COLORS.white, textAlign: 'center' }, heroDescription: { fontSize: 13, color: '#D2E5D9', textAlign: 'center', lineHeight: 20, marginTop: 10, marginBottom: 20, paddingHorizontal: 10 }, disabledButton: { borderRadius: 14, backgroundColor: '#FFFFFF', paddingVertical: 16, width: '100%' }, disabledText: { color: COLORS.green, textAlign: 'center', fontWeight: '800', fontSize: 13 },
  rowCard: { flexDirection: 'row', alignItems: 'center' }, cameraIcon: { width: 46, height: 46, borderRadius: 13, backgroundColor: COLORS.pale, justifyContent: 'center', alignItems: 'center', marginRight: 13 }, cameraIconText: { fontSize: 24, color: COLORS.green }, flex: { flex: 1 }, cardTitle: { fontSize: 15, fontWeight: '800', color: COLORS.ink }, cardSub: { fontSize: 12, color: COLORS.muted, marginTop: 5, lineHeight: 17 }, arrow: { fontSize: 27, color: COLORS.muted }, sectionTitle: { color: COLORS.ink, fontSize: 17, fontWeight: '800', marginTop: 17, marginBottom: 13 }, step: { color: COLORS.ink, fontSize: 13, lineHeight: 20, paddingVertical: 6 }, line: { borderTopWidth: 1, borderTopColor: COLORS.border, marginVertical: 9 }, previewNote: { textAlign: 'center', color: COLORS.muted, fontSize: 11, marginTop: 12, lineHeight: 17 },
  totalCard: { backgroundColor: COLORS.green, borderColor: COLORS.green, paddingVertical: 27 }, totalLabel: { color: '#BFE0CE', fontSize: 10, letterSpacing: 1.4, fontWeight: '800' }, totalAmount: { color: COLORS.white, fontSize: 48, fontWeight: '800', letterSpacing: -2, marginTop: 10 }, totalHint: { color: '#D2E5D9', marginTop: 5, fontSize: 12 }, categoryRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 42 }, categoryBorder: { borderTopWidth: 1, borderTopColor: COLORS.border }, categoryName: { fontSize: 14, fontWeight: '600', color: COLORS.ink }, categoryAmount: { fontSize: 14, fontWeight: '800', color: COLORS.ink }, expenseCard: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' }, expenseAmount: { fontSize: 15, fontWeight: '800', color: COLORS.ink }, original: { width: '100%', borderTopWidth: 1, borderTopColor: COLORS.border, marginTop: 15, paddingTop: 15, color: COLORS.muted, fontSize: 13, lineHeight: 20 },
  notice: { backgroundColor: COLORS.pale, borderColor: COLORS.pale }, noticeTitle: { fontSize: 15, fontWeight: '800', color: COLORS.green }, noticeText: { fontSize: 13, lineHeight: 20, color: COLORS.green, marginTop: 7 }, unset: { fontSize: 12, color: COLORS.muted }, schedule: { marginTop: 17, backgroundColor: COLORS.pale, borderRadius: 12, padding: 14 }, scheduleText: { color: COLORS.green, fontWeight: '800', fontSize: 13 },
  tabBar: { backgroundColor: COLORS.white, borderTopWidth: 1, borderTopColor: COLORS.border, flexDirection: 'row', paddingTop: 11, paddingBottom: 9 }, tab: { flex: 1, alignItems: 'center', paddingVertical: 3 }, tabSymbol: { fontSize: 23, color: '#A0ABA3', marginBottom: 3 }, tabLabel: { color: '#88948B', fontSize: 11, fontWeight: '700' }, tabActive: { color: COLORS.green },
});
