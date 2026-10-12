import React, {useEffect, useState} from 'react';
import {ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';

import {Doc, Page, absoluteUrl, docName, getPages} from '../api';
import {FORMAT_LABEL, colors, confColor} from '../theme';

type Props = {doc: Doc | null; onAsk: () => void};

const BROWSER_IMAGES = ['jpg', 'jpeg', 'png', 'webp'];
const BLOCK_STYLE = {
  paragraph: {label: 'Paragraph', fg: colors.accent, bg: colors.accentSoft},
  table: {label: 'Table', fg: colors.violet, bg: colors.violetSoft},
  image: {label: 'Picture', fg: colors.amber, bg: colors.amberSoft},
};

// A page image at its natural aspect ratio, full width.
function PageImage({uri}: {uri: string}) {
  const [ratio, setRatio] = useState(0.77); // A4 until the real size is known
  useEffect(() => {
    Image.getSize(uri, (w, h) => h && setRatio(w / h), () => {});
  }, [uri]);
  return <Image source={{uri}} style={[styles.pageImg, {aspectRatio: ratio}]} resizeMode="contain" />;
}

export default function PreviewScreen({doc, onAsk}: Props) {
  const [pages, setPages] = useState<Page[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'pages' | 'read'>('pages');

  useEffect(() => {
    setPages(null);
    setError(null);
    if (!doc) {
      return;
    }
    let live = true;
    getPages(doc.doc_id)
      .then(p => live && setPages(p))
      .catch(e => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [doc]);

  if (!doc) {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyIcon}>📄</Text>
        <Text style={styles.empty}>Your document will show here while you ask questions about it.</Text>
      </View>
    );
  }

  const name = docName(doc);
  const ext = (name.split('.').pop() || '').toLowerCase();
  const word = ext === 'pptx' ? 'Slide' : 'Page';

  return (
    <View style={styles.flex}>
      <View style={styles.head}>
        <Text style={styles.title} numberOfLines={1}>{name}</Text>
        <Text style={styles.sub}>
          {FORMAT_LABEL[doc.format_type]} · {doc.page_count} {word.toLowerCase()}{doc.page_count > 1 ? 's' : ''}
        </Text>
        <View style={styles.row}>
          <View style={styles.segment}>
            {(['pages', 'read'] as const).map(m => (
              <Pressable key={m} onPress={() => setMode(m)} style={[styles.segBtn, mode === m && styles.segOn]}>
                <Text style={[styles.segText, mode === m && styles.segTextOn]}>{m === 'pages' ? 'Pages' : 'What I read'}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable style={styles.askBtn} onPress={onAsk}>
            <Text style={styles.askText}>Ask about it →</Text>
          </Pressable>
        </View>
      </View>

      {error ? (
        <Text style={styles.error}>{error}</Text>
      ) : !pages ? (
        <ActivityIndicator style={styles.loading} color={colors.accent} size="large" />
      ) : (
        <ScrollView contentContainerStyle={styles.list}>
          {mode === 'pages' && BROWSER_IMAGES.includes(ext) ? (
            <PageImage uri={absoluteUrl(`/documents/${doc.doc_id}/file`)} />
          ) : (
            pages.map(p => (
              <View key={p.page} style={styles.page}>
                <Text style={styles.pageNo}>
                  {word} {p.page}
                  {doc.format_type !== 'typed' ? `  ·  read with ${Math.round(p.conf * 100)}% confidence` : ''}
                </Text>
                {mode === 'pages' ? (
                  p.image_url ? (
                    <PageImage uri={absoluteUrl(p.image_url)} />
                  ) : (
                    <Text style={styles.pageText}>{p.text || '(no text on this page)'}</Text>
                  )
                ) : p.lines.length ? (
                  p.lines.map((l, i) => (
                    <View key={i} style={styles.item}>
                      <Text style={[styles.conf, {color: confColor(l.conf)}]}>{Math.round(l.conf * 100)}%</Text>
                      <Text style={styles.itemText}>{l.text}</Text>
                    </View>
                  ))
                ) : p.blocks.length ? (
                  p.blocks.map((b, i) => {
                    const s = BLOCK_STYLE[b.type];
                    return (
                      <View key={i} style={styles.item}>
                        <Text style={[styles.kind, {color: s.fg, backgroundColor: s.bg}]}>{s.label}</Text>
                        <Text style={styles.itemText} numberOfLines={6}>
                          {b.type === 'table' && b.rows ? b.rows.map(r => r.join('  |  ')).join('\n') : b.text || '(picture)'}
                        </Text>
                      </View>
                    );
                  })
                ) : (
                  <Text style={styles.pageText}>{p.text || '(no text on this page)'}</Text>
                )}
              </View>
            ))
          )}
          {mode === 'read' && doc.format_type !== 'typed' && (
            <Text style={styles.legend}>Green: clear · Amber: partly legible · Red: hard to read</Text>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: {flex: 1},
  center: {flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32},
  emptyIcon: {fontSize: 40, marginBottom: 10},
  empty: {textAlign: 'center', color: colors.muted, fontSize: 14},
  head: {padding: 16, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: colors.line, backgroundColor: colors.panel},
  title: {fontSize: 17, fontWeight: '700', color: colors.text},
  sub: {fontSize: 12, color: colors.muted, marginTop: 2},
  row: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10, gap: 8},
  segment: {flexDirection: 'row', backgroundColor: colors.soft, borderRadius: 999, padding: 3},
  segBtn: {paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999},
  segOn: {backgroundColor: colors.panel},
  segText: {fontSize: 13, color: colors.muted, fontWeight: '600'},
  segTextOn: {color: colors.accent},
  askBtn: {backgroundColor: colors.accent, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 9},
  askText: {color: '#fff', fontWeight: '700', fontSize: 13},
  loading: {marginTop: 40},
  error: {color: colors.rose, padding: 20, textAlign: 'center'},
  list: {padding: 12, paddingBottom: 24, gap: 12},
  page: {backgroundColor: colors.panel, borderRadius: 10, padding: 10, borderWidth: 1, borderColor: colors.line},
  pageNo: {fontSize: 12, color: colors.muted, fontWeight: '600', marginBottom: 8},
  pageImg: {width: '100%', backgroundColor: '#fff', borderRadius: 4},
  pageText: {fontSize: 14, lineHeight: 21, color: colors.text},
  item: {flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 6, borderTopWidth: 1, borderTopColor: colors.soft},
  conf: {width: 42, fontSize: 12, fontWeight: '800', textAlign: 'right'},
  kind: {fontSize: 11, fontWeight: '800', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, overflow: 'hidden', minWidth: 70, textAlign: 'center'},
  itemText: {flex: 1, fontSize: 14, color: colors.text, lineHeight: 20},
  legend: {fontSize: 12, color: colors.muted, textAlign: 'center'},
});
