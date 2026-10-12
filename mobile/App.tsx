/**
 * DocBlendAI mobile app: upload notes, see them, ask questions with a reliability label.
 * Talks to the DocBlendAI server (src/config.ts); all recognition and answering happens there.
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  BackHandler,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import {SafeAreaProvider, useSafeAreaInsets} from 'react-native-safe-area-context';

import * as api from './src/api';
import type {Doc, Stats} from './src/api';
import AskScreen from './src/screens/AskScreen';
import DocumentsScreen from './src/screens/DocumentsScreen';
import PreviewScreen from './src/screens/PreviewScreen';
import {colors} from './src/theme';

type View_ = 'docs' | 'preview' | 'chat';
const TABS: {view: View_; icon: string; label: string}[] = [
  {view: 'docs', icon: '📄', label: 'Documents'},
  {view: 'preview', icon: '👁', label: 'Preview'},
  {view: 'chat', icon: '💬', label: 'Ask'},
];

function Main() {
  const insets = useSafeAreaInsets();
  const [view, setView] = useState<View_>('docs');
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [publicDemo, setPublicDemo] = useState(false);
  const [connection, setConnection] = useState<'waking' | 'ok' | 'error'>('waking');
  const beatEvery = useRef(60);

  const refreshStats = useCallback(() => {
    api.getStats().then(setStats).catch(() => {});
  }, []);

  const loadDocs = useCallback(async (newDocId?: string) => {
    const list = await api.listDocuments(); // oldest first
    const ids = new Set(list.map(d => d.doc_id));
    setDocs(list);
    setSelected(prev => {
      let next = newDocId ? new Set([newDocId]) : new Set([...prev].filter(id => ids.has(id)));
      if (!next.size && list.length) {
        next = new Set([list[list.length - 1].doc_id]);
      }
      return next;
    });
    setPreviewId(prev =>
      newDocId || (prev && ids.has(prev) ? prev : list.length ? list[list.length - 1].doc_id : null),
    );
  }, []);

  const connect = useCallback(async () => {
    setConnection('waking');
    try {
      const info = await api.heartbeat();
      beatEvery.current = Math.max(10, info.heartbeat_seconds);
      setPublicDemo(info.public_demo);
      setConnection('ok');
      refreshStats();
      await loadDocs();
    } catch {
      setConnection('error');
    }
  }, [loadDocs, refreshStats]);

  useEffect(() => {
    connect();
  }, [connect]);

  // Heartbeats while the app is open keep this session's documents; they stop in the background,
  // and the server deletes the documents a few minutes later.
  useEffect(() => {
    if (connection !== 'ok') {
      return;
    }
    const timer = setInterval(() => {
      api.heartbeat(30000).catch(() => {});
      refreshStats();
    }, beatEvery.current * 1000);
    const sub = AppState.addEventListener('change', state => {
      if (state === 'active') {
        api
          .heartbeat()
          .then(() => loadDocs())
          .catch(() => {});
        refreshStats();
      }
    });
    return () => {
      clearInterval(timer);
      sub.remove();
    };
  }, [connection, loadDocs, refreshStats]);

  // Android back button: go back to Documents before leaving the app.
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (view !== 'docs') {
        setView('docs');
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, [view]);

  const nameOf = (docId: string) => {
    const d = docs.find(x => x.doc_id === docId);
    return d ? api.docName(d) : docId.slice(0, 8);
  };

  function toggle(docId: string) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(docId) ? next.delete(docId) : next.add(docId);
      return next;
    });
  }

  function remove(doc: Doc) {
    Alert.alert('Remove document', `Remove "${api.docName(doc)}"? I won't use it for answers any more.`, [
      {text: 'Cancel', style: 'cancel'},
      {
        text: 'Remove',
        style: 'destructive',
        onPress: async () => {
          try {
            await api.deleteDocument(doc.doc_id);
            await loadDocs();
          } catch (e: any) {
            Alert.alert('Could not remove', e.message);
          }
        },
      },
    ]);
  }

  const previewDoc = docs.find(d => d.doc_id === previewId) || null;

  return (
    <View style={[styles.root, {paddingTop: insets.top}]}>
      <StatusBar barStyle="dark-content" />
      <View style={styles.header}>
        <View style={styles.logo}>
          <Text style={styles.logoText}>D</Text>
        </View>
        <Text style={styles.title}>DocBlendAI</Text>
        {stats && (
          <View style={styles.stats}>
            <Text style={styles.stat}>👥 {stats.visitors_today}</Text>
            <Text style={styles.stat}>💬 {stats.questions_today} today</Text>
          </View>
        )}
      </View>

      {connection !== 'ok' && (
        <View style={[styles.banner, connection === 'error' && styles.bannerErr]}>
          {connection === 'waking' ? <ActivityIndicator color={colors.accent} /> : null}
          <Text style={[styles.bannerText, connection === 'error' && {color: colors.rose}]}>
            {connection === 'waking'
              ? 'Connecting to the server… the free server sleeps when idle, so the first start can take up to a minute.'
              : "Couldn't reach the server."}
          </Text>
          {connection === 'error' && (
            <Pressable style={styles.retry} onPress={connect}>
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          )}
        </View>
      )}

      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <View style={[styles.flex, view !== 'docs' && styles.hidden]}>
          <DocumentsScreen
            docs={docs}
            selected={selected}
            previewId={previewId}
            publicDemo={publicDemo}
            onToggle={toggle}
            onPreview={d => {
              setPreviewId(d.doc_id);
              setView('preview');
            }}
            onDelete={remove}
            onUploaded={async d => {
              try {
                await loadDocs(d.doc_id);
              } catch {}
              setView('preview');
            }}
          />
        </View>
        <View style={[styles.flex, view !== 'preview' && styles.hidden]}>
          <PreviewScreen
            doc={previewDoc}
            onAsk={() => {
              if (previewDoc && !selected.has(previewDoc.doc_id)) {
                setSelected(prev => new Set(prev).add(previewDoc.doc_id));
              }
              setView('chat');
            }}
          />
        </View>
        <View style={[styles.flex, view !== 'chat' && styles.hidden]}>
          <AskScreen
            selectedIds={docs.filter(d => selected.has(d.doc_id)).map(d => d.doc_id)}
            nameOf={nameOf}
            onAsked={refreshStats}
            onPickDocs={() => setView('docs')}
          />
        </View>
      </KeyboardAvoidingView>

      <View style={[styles.tabbar, {paddingBottom: Math.max(6, insets.bottom)}]}>
        {TABS.map(t => {
          const on = view === t.view;
          return (
            <Pressable
              key={t.view}
              style={[styles.tab, on && styles.tabOn]}
              onPress={() => setView(t.view)}
              accessibilityRole="tab"
              accessibilityState={{selected: on}}>
              <Text style={styles.tabIcon}>{t.icon}</Text>
              <Text style={[styles.tabLabel, on && styles.tabLabelOn]}>{t.label}</Text>
              {t.view === 'docs' && docs.length > 0 && (
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>{docs.length}</Text>
                </View>
              )}
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <Main />
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.bg},
  flex: {flex: 1},
  hidden: {display: 'none'},
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: colors.panel,
    borderBottomWidth: 1,
    borderBottomColor: colors.line,
  },
  logo: {width: 34, height: 34, borderRadius: 10, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center'},
  logoText: {color: '#fff', fontWeight: '800', fontSize: 17},
  title: {fontSize: 18, fontWeight: '800', color: colors.text},
  stats: {marginLeft: 'auto', flexDirection: 'row', gap: 6},
  stat: {fontSize: 12, color: colors.text, backgroundColor: colors.soft, borderRadius: 999, paddingHorizontal: 9, paddingVertical: 3, overflow: 'hidden'},
  banner: {flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12, backgroundColor: colors.accentSoft},
  bannerErr: {backgroundColor: colors.roseSoft},
  bannerText: {flex: 1, fontSize: 13, color: colors.text},
  retry: {backgroundColor: colors.accent, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 8},
  retryText: {color: '#fff', fontWeight: '700'},
  tabbar: {flexDirection: 'row', gap: 4, paddingHorizontal: 8, paddingTop: 6, backgroundColor: colors.panel, borderTopWidth: 1, borderTopColor: colors.line},
  tab: {flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 54, borderRadius: 12},
  tabOn: {backgroundColor: colors.accentSoft},
  tabIcon: {fontSize: 20},
  tabLabel: {fontSize: 12, fontWeight: '600', color: colors.muted, marginTop: 2},
  tabLabelOn: {color: colors.accent},
  badge: {position: 'absolute', top: 4, right: '28%', minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 5},
  badgeText: {color: '#fff', fontSize: 11, fontWeight: '800'},
});
