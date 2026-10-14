import React, {useEffect, useState} from 'react';
import {ActivityIndicator, Alert, Image, Linking, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';

import {Doc, ExportFormat, Page, Region, RegionType, absoluteUrl, docName, exportUrl, getPages} from '../api';
import {FORMAT_LABEL, colors, confColor} from '../theme';

type Props = {doc: Doc | null; onAsk: () => void};
type Mode = 'pages' | 'layout' | 'lines' | 'spacing';

const BROWSER_IMAGES = ['jpg', 'jpeg', 'png', 'webp'];
const BLOCK_STYLE = {
  paragraph: {label: 'Paragraph', fg: colors.accent, bg: colors.accentSoft},
  table: {label: 'Table', fg: colors.violet, bg: colors.violetSoft},
  image: {label: 'Picture', fg: colors.amber, bg: colors.amberSoft},
};
// Same colours as the website's layout view.
const REGION_STYLE: Record<RegionType, {label: string; fg: string; bg: string}> = {
  title: {label: 'Title', fg: '#3b5bdb', bg: colors.accentSoft},
  text: {label: 'Text', fg: '#5c6b8a', bg: colors.soft},
  table: {label: 'Table', fg: colors.violet, bg: colors.violetSoft},
  figure: {label: 'Figure', fg: colors.amber, bg: colors.amberSoft},
  caption: {label: 'Caption', fg: '#c2410c', bg: '#fdeee4'},
  formula: {label: 'Formula', fg: colors.mint, bg: colors.mintSoft},
  header: {label: 'Header', fg: '#8a94a8', bg: colors.soft},
  footer: {label: 'Footer', fg: '#8a94a8', bg: colors.soft},
  reference: {label: 'Reference', fg: '#8a94a8', bg: colors.soft},
};
const DOWNLOADS: [ExportFormat, string][] = [
  ['layout', 'Layout text (spacing kept)'],
  ['md', 'Markdown'],
  ['csv', 'Tables (CSV)'],
  ['json', 'JSON (everything)'],
  ['txt', 'Plain text'],
];

// A page image at its natural aspect ratio, full width.
function PageImage({uri}: {uri: string}) {
  const [ratio, setRatio] = useState(0.77); // A4 until the real size is known
  useEffect(() => {
    Image.getSize(uri, (w, h) => h && setRatio(w / h), () => {});
  }, [uri]);
  return <Image source={{uri}} style={[styles.pageImg, {aspectRatio: ratio}]} resizeMode="contain" />;
}

// A detected table as a grid (scrolls sideways when it is wider than the screen).
function TableGrid({rows}: {rows: string[][]}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tableScroll}>
      <View style={styles.table}>
        {rows.map((row, r) => (
          <View key={r} style={styles.tr}>
            {row.map((cell, c) => (
              <Text key={c} style={[styles.td, r === 0 && styles.th]}>
                {cell}
              </Text>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

function RegionItem({region, n}: {region: Region; n: number}) {
  const s = REGION_STYLE[region.type] || REGION_STYLE.text;
  const showConf = region.type !== 'figure' || !!region.text;
  return (
    <View style={styles.region}>
      <View style={styles.regionHead}>
        <Text style={[styles.kind, {color: s.fg, backgroundColor: s.bg}]}>
          {n}. {s.label}
        </Text>
        {showConf && <Text style={[styles.confNote, {color: confColor(region.conf)}]}>{Math.round(region.conf * 100)}%</Text>}
      </View>
      {region.type === 'table' && region.rows?.length ? (
        <TableGrid rows={region.rows} />
      ) : region.text ? (
        <Text style={[styles.itemText, region.type === 'title' && styles.titleText]}>{region.text}</Text>
      ) : null}
    </View>
  );
}

export default function PreviewScreen({doc, onAsk}: Props) {
  const [pages, setPages] = useState<Page[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>('pages');

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
  const scans = doc.format_type !== 'typed';
  const modes: Mode[] = scans ? ['pages', 'layout', 'lines', 'spacing'] : ['pages', 'layout', 'spacing'];
  const labels: Record<Mode, string> = {pages: 'Pages', layout: 'Layout', lines: 'Lines', spacing: 'Spacing'};

  function download() {
    Alert.alert('Download', 'Opens in your browser, which saves the file.', [
      ...DOWNLOADS.map(([format, label]) => ({
        text: label,
        onPress: () => Linking.openURL(exportUrl(doc!.doc_id, format)).catch(() => Alert.alert('Could not open the browser')),
      })),
      {text: 'Cancel', style: 'cancel' as const},
    ]);
  }

  function pageBody(p: Page) {
    if (mode === 'pages') {
      return p.image_url ? <PageImage uri={absoluteUrl(p.image_url)} /> : <Text style={styles.pageText}>{p.text || '(no text on this page)'}</Text>;
    }
    if (mode === 'spacing') {
      return (
        <ScrollView horizontal showsHorizontalScrollIndicator>
          <Text style={styles.mono}>{p.layout_text || p.text || '(no text on this page)'}</Text>
        </ScrollView>
      );
    }
    if (mode === 'layout' && p.regions?.length) {
      return p.regions.map((r, i) => <RegionItem key={i} region={r} n={i + 1} />);
    }
    if ((mode === 'lines' || mode === 'layout') && p.lines.length) {
      return p.lines.map((l, i) => (
        <View key={i} style={styles.item}>
          <Text style={[styles.conf, {color: confColor(l.conf)}]}>{Math.round(l.conf * 100)}%</Text>
          <Text style={styles.itemText}>{l.text}</Text>
        </View>
      ));
    }
    if (p.blocks.length) {
      return p.blocks.map((b, i) => {
        const s = BLOCK_STYLE[b.type];
        return (
          <View key={i} style={styles.region}>
            <Text style={[styles.kind, {color: s.fg, backgroundColor: s.bg}]}>{s.label}</Text>
            {b.type === 'table' && b.rows?.length ? (
              <TableGrid rows={b.rows} />
            ) : (
              <Text style={styles.itemText} numberOfLines={8}>{b.text || '(picture)'}</Text>
            )}
          </View>
        );
      });
    }
    return <Text style={styles.pageText}>{p.text || '(no text on this page)'}</Text>;
  }

  return (
    <View style={styles.flex}>
      <View style={styles.head}>
        <Text style={styles.title} numberOfLines={1}>{name}</Text>
        <Text style={styles.sub}>
          {FORMAT_LABEL[doc.format_type]} · {doc.page_count} {word.toLowerCase()}{doc.page_count > 1 ? 's' : ''}
        </Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
          <View style={styles.segment}>
            {modes.map(m => (
              <Pressable key={m} onPress={() => setMode(m)} style={[styles.segBtn, mode === m && styles.segOn]}>
                <Text style={[styles.segText, mode === m && styles.segTextOn]}>{labels[m]}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable style={styles.dlBtn} onPress={download}>
            <Text style={styles.dlText}>Download</Text>
          </Pressable>
          <Pressable style={styles.askBtn} onPress={onAsk}>
            <Text style={styles.askText}>Ask about it →</Text>
          </Pressable>
        </ScrollView>
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
                  {scans ? `  ·  read with ${Math.round(p.conf * 100)}% confidence` : ''}
                  {mode === 'layout' && p.regions?.length ? `  ·  ${p.regions.length} parts in reading order` : ''}
                </Text>
                {pageBody(p)}
              </View>
            ))
          )}
          {mode === 'lines' && <Text style={styles.legend}>Green: clear · Amber: partly legible · Red: hard to read</Text>}
          {mode === 'spacing' && <Text style={styles.legend}>Spacing and columns as on the page · swipe sideways for wide lines</Text>}
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
  row: {flexDirection: 'row', alignItems: 'center', marginTop: 10, gap: 8},
  segment: {flexDirection: 'row', backgroundColor: colors.soft, borderRadius: 999, padding: 3},
  segBtn: {paddingHorizontal: 11, paddingVertical: 7, borderRadius: 999},
  segOn: {backgroundColor: colors.panel},
  segText: {fontSize: 13, color: colors.muted, fontWeight: '600'},
  segTextOn: {color: colors.accent},
  dlBtn: {backgroundColor: colors.accentSoft, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 9},
  dlText: {color: colors.accent, fontWeight: '700', fontSize: 13},
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
  region: {paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.soft, gap: 6},
  regionHead: {flexDirection: 'row', alignItems: 'center', gap: 8},
  conf: {width: 42, fontSize: 12, fontWeight: '800', textAlign: 'right'},
  confNote: {fontSize: 12, fontWeight: '700'},
  kind: {alignSelf: 'flex-start', fontSize: 11, fontWeight: '800', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, overflow: 'hidden'},
  itemText: {flex: 1, fontSize: 14, color: colors.text, lineHeight: 20},
  titleText: {fontSize: 16, fontWeight: '700'},
  tableScroll: {flexGrow: 0},
  table: {borderTopWidth: 1, borderLeftWidth: 1, borderColor: colors.line},
  tr: {flexDirection: 'row'},
  td: {minWidth: 64, paddingHorizontal: 8, paddingVertical: 5, fontSize: 13, color: colors.text, borderRightWidth: 1, borderBottomWidth: 1, borderColor: colors.line},
  th: {fontWeight: '700', backgroundColor: colors.soft},
  mono: {fontFamily: 'monospace', fontSize: 11, lineHeight: 15, color: colors.text},
  legend: {fontSize: 12, color: colors.muted, textAlign: 'center'},
});
