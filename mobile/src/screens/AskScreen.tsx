import React, {useRef, useState} from 'react';
import {ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';

import {Answer, Source, ask} from '../api';
import {RELIABILITY, colors} from '../theme';

type Props = {selectedIds: string[]; nameOf: (docId: string) => string; onAsked: () => void; onPickDocs: () => void};

type Message =
  | {id: number; me: true; text: string}
  | {id: number; me: false; pending: true}
  | {id: number; me: false; pending: false; answer?: Answer; sources?: Source[]; looked?: string[]; error?: string};

const SUGGESTIONS = ["What's this document about?", 'Sum up the key points', 'What are the main topics?', 'Explain the first idea simply'];

function Meter({label, value}: {label: string; value: number}) {
  return (
    <View style={styles.meter}>
      <Text style={styles.meterLabel}>{label}</Text>
      <View style={styles.bar}>
        <View style={[styles.barFill, {width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`}]} />
      </View>
      <Text style={styles.meterLabel}>{value.toFixed(2)}</Text>
    </View>
  );
}

function Sources({sources, nameOf}: {sources: Source[]; nameOf: (id: string) => string}) {
  const [open, setOpen] = useState(false);
  return (
    <View style={styles.sources}>
      <Pressable onPress={() => setOpen(!open)} hitSlop={8}>
        <Text style={styles.srcToggle}>{open ? '▾' : '▸'} Where I found this ({sources.length})</Text>
      </Pressable>
      {open &&
        sources.map(s => (
          <View key={s.chunk_id} style={styles.source}>
            <Text style={styles.srcMeta} numberOfLines={1}>
              {nameOf(s.doc_id)} · {s.content_type}
            </Text>
            <Meter label="match" value={s.similarity} />
            <Meter label="legibility" value={s.confidence} />
            <Text style={styles.srcText} numberOfLines={8}>{s.text}</Text>
          </View>
        ))}
    </View>
  );
}

export default function AskScreen({selectedIds, nameOf, onAsked, onPickDocs}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const scroll = useRef<React.ComponentRef<typeof ScrollView>>(null);
  const nextId = useRef(1);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy || !selectedIds.length) {
      return;
    }
    setQuestion('');
    setBusy(true);
    const mine = nextId.current++;
    const reply = nextId.current++;
    setMessages(m => [...m, {id: mine, me: true, text: q}, {id: reply, me: false, pending: true}]);
    const looked = selectedIds.map(nameOf);
    let done: Message;
    try {
      const {answer, sources} = await ask(q, selectedIds);
      done = {id: reply, me: false, pending: false, answer, sources, looked};
    } catch (e: any) {
      done = {id: reply, me: false, pending: false, error: e.message};
    }
    setMessages(m => m.map(x => (x.id === reply ? done : x)));
    setBusy(false);
    onAsked();
  }

  return (
    <View style={styles.flex}>
      <View style={styles.scope}>
        {selectedIds.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.scopeRow}>
            <Text style={styles.scopeLabel}>Reading from:</Text>
            {selectedIds.map(id => (
              <Text key={id} style={styles.tag} numberOfLines={1}>{nameOf(id)}</Text>
            ))}
          </ScrollView>
        ) : (
          <Pressable onPress={onPickDocs}>
            <Text style={styles.scopeNone}>Tick “Ask about this” on a document so I know which one you mean →</Text>
          </Pressable>
        )}
      </View>

      <ScrollView
        ref={scroll}
        style={styles.flex}
        contentContainerStyle={styles.chat}
        onContentSizeChange={() => scroll.current?.scrollToEnd({animated: true})}
        keyboardShouldPersistTaps="handled">
        {!messages.length && (
          <View style={styles.welcome}>
            <Text style={styles.bot}>🤖</Text>
            <Text style={styles.welcomeTitle}>Hi there! 👋</Text>
            <Text style={styles.welcomeText}>
              Share a document with me and ask anything you like. I'll answer from your notes, tell you honestly how sure I am, and show you exactly where I found it.
            </Text>
          </View>
        )}
        {messages.map(m => {
          if (m.me) {
            return (
              <View key={m.id} style={[styles.bubble, styles.mine]}>
                <Text style={styles.mineText}>{m.text}</Text>
              </View>
            );
          }
          if (m.pending) {
            return (
              <View key={m.id} style={styles.bubble}>
                <ActivityIndicator color={colors.accent} />
              </View>
            );
          }
          if (m.error || !m.answer) {
            return (
              <View key={m.id} style={styles.bubble}>
                <Text style={[styles.rel, {color: colors.rose, backgroundColor: colors.roseSoft}]}>! Sorry</Text>
                <Text style={styles.answer}>{m.error}</Text>
              </View>
            );
          }
          const r = RELIABILITY[m.answer.reliability_label];
          return (
            <View key={m.id} style={styles.bubble}>
              <Text style={[styles.rel, {color: r.fg, backgroundColor: r.bg}]}>
                {r.icon} {r.title}
              </Text>
              <Text style={styles.answer} selectable>{m.answer.answer_text}</Text>
              <Text style={styles.why}>{r.why}</Text>
              <Text style={styles.from}>From: {m.looked?.join(', ')}</Text>
              {!!m.sources?.length && <Sources sources={m.sources} nameOf={nameOf} />}
            </View>
          );
        })}
      </ScrollView>

      {!messages.length && !!selectedIds.length && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.suggest} style={styles.suggestBar}>
          {SUGGESTIONS.map(s => (
            <Pressable key={s} style={styles.suggestBtn} onPress={() => send(s)}>
              <Text style={styles.suggestText}>{s}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}

      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          value={question}
          onChangeText={setQuestion}
          placeholder="Ask me anything about your notes…"
          placeholderTextColor={colors.muted}
          multiline
          maxLength={2000}
        />
        <Pressable style={[styles.send, (busy || !question.trim()) && styles.sendOff]} onPress={() => send(question)} disabled={busy}>
          <Text style={styles.sendText}>Ask</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: {flex: 1},
  scope: {paddingHorizontal: 14, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.line, backgroundColor: colors.panel},
  scopeRow: {alignItems: 'center', gap: 6},
  scopeLabel: {fontSize: 13, color: colors.muted},
  tag: {maxWidth: 200, fontSize: 12, fontWeight: '700', color: colors.accent, backgroundColor: colors.accentSoft, paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, overflow: 'hidden'},
  scopeNone: {fontSize: 13, color: colors.rose},
  chat: {padding: 12, gap: 12, flexGrow: 1},
  welcome: {flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24},
  bot: {fontSize: 44},
  welcomeTitle: {fontSize: 17, fontWeight: '700', color: colors.text, marginTop: 8},
  welcomeText: {fontSize: 14, color: colors.muted, textAlign: 'center', marginTop: 6, lineHeight: 20},
  bubble: {alignSelf: 'flex-start', maxWidth: '94%', backgroundColor: colors.panel, borderRadius: 16, borderTopLeftRadius: 4, padding: 12, borderWidth: 1, borderColor: colors.line},
  mine: {alignSelf: 'flex-end', backgroundColor: colors.accent, borderColor: colors.accent, borderTopLeftRadius: 16, borderTopRightRadius: 4},
  mineText: {color: '#fff', fontSize: 15},
  rel: {alignSelf: 'flex-start', fontSize: 12, fontWeight: '800', paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, overflow: 'hidden', marginBottom: 8},
  answer: {fontSize: 15, lineHeight: 22, color: colors.text},
  why: {fontSize: 13, color: colors.muted, marginTop: 8},
  from: {fontSize: 12, color: colors.muted, marginTop: 4},
  sources: {marginTop: 10},
  srcToggle: {fontSize: 13, fontWeight: '700', color: colors.accent},
  source: {marginTop: 8, padding: 10, borderRadius: 10, backgroundColor: '#fafbff', borderWidth: 1, borderColor: colors.line, gap: 4},
  srcMeta: {fontSize: 12, color: colors.text, fontWeight: '700'},
  srcText: {fontSize: 13, color: colors.text, marginTop: 4, lineHeight: 19},
  meter: {flexDirection: 'row', alignItems: 'center', gap: 6},
  meterLabel: {fontSize: 11, color: colors.muted, minWidth: 30},
  bar: {width: 70, height: 6, borderRadius: 3, backgroundColor: colors.line, overflow: 'hidden'},
  barFill: {height: '100%', backgroundColor: colors.accent},
  suggestBar: {flexGrow: 0},
  suggest: {paddingHorizontal: 12, paddingBottom: 8, gap: 8},
  suggestBtn: {borderWidth: 1, borderColor: colors.line, backgroundColor: colors.panel, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8},
  suggestText: {fontSize: 13, color: colors.text},
  composer: {flexDirection: 'row', alignItems: 'flex-end', gap: 8, padding: 10, borderTopWidth: 1, borderTopColor: colors.line, backgroundColor: colors.panel},
  input: {flex: 1, minHeight: 44, maxHeight: 120, fontSize: 16, color: colors.text, backgroundColor: colors.bg, borderRadius: 12, borderWidth: 1, borderColor: colors.line, paddingHorizontal: 12, paddingVertical: 10},
  send: {height: 44, paddingHorizontal: 18, borderRadius: 12, backgroundColor: colors.accent, justifyContent: 'center'},
  sendOff: {opacity: 0.5},
  sendText: {color: '#fff', fontWeight: '700', fontSize: 15},
});
