import React, {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import {errorCodes, isErrorWithCode, pick, types} from '@react-native-documents/picker';
import {Asset, launchCamera, launchImageLibrary} from 'react-native-image-picker';

import {Doc, FormatType, UploadFile, docName, uploadDocument} from '../api';
import {FORMAT_LABEL, colors} from '../theme';

type Props = {
  docs: Doc[];
  selected: Set<string>;
  previewId: string | null;
  publicDemo: boolean;
  onToggle: (docId: string) => void;
  onPreview: (doc: Doc) => void;
  onDelete: (doc: Doc) => void;
  onUploaded: (doc: Doc) => void;
};

type Job = {
  id: number;
  name: string;
  state: 'busy' | 'ok' | 'err';
  message: string;
  started: number;
  size?: number | null;
  sent: number; // share of the file uploaded (0-1)
  readingSince?: number; // when the server started reading it
};

const HINTS: {value: FormatType | null; label: string}[] = [
  {value: null, label: 'Detect for me'},
  {value: 'typed', label: 'Typed'},
  {value: 'scanned', label: 'Printed'},
  {value: 'handwritten', label: 'Handwritten'},
];
const STEPS = ['Uploading', 'Reading your pages', 'Recognising the text', 'Understanding it', 'Almost done'];
const PICK_TYPES = [types.pdf, types.images, types.docx, types.pptx, types.plainText];
// Camera and gallery photos are shrunk by Android before upload: 2600 px on the long side at
// JPEG quality 80 keeps every letter readable and makes a 4-12 MB phone photo well under 1 MB.
const PHOTO = {mediaType: 'photo' as const, quality: 0.8 as const, maxWidth: 2600, maxHeight: 2600};

function sizeText(bytes?: number | null): string {
  if (!bytes) {
    return '';
  }
  return bytes >= 1048576 ? ` of ${(bytes / 1048576).toFixed(1)} MB` : ` of ${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function busyText(j: Job): string {
  if (!j.readingSince) {
    return `Uploading ${Math.round(j.sent * 100)}%${sizeText(j.size)}…`;
  }
  const secs = Math.round((Date.now() - j.readingSince) / 1000);
  return `${STEPS[Math.min(STEPS.length - 1, 1 + Math.floor(secs / 6))]}… ${secs}s`;
}

function photoFile(asset: Asset): UploadFile {
  return {uri: asset.uri!, name: asset.fileName || `photo-${Date.now()}.jpg`, type: asset.type || 'image/jpeg', size: asset.fileSize};
}

function kindBadge(name: string): {short: string; color: string} {
  const ext = (name.split('.').pop() || '').toLowerCase();
  if (ext === 'pdf') {
    return {short: 'PDF', color: '#e5534b'};
  }
  if (['jpg', 'jpeg', 'png', 'tif', 'tiff', 'bmp', 'webp'].includes(ext)) {
    return {short: 'IMG', color: '#2f9e89'};
  }
  if (ext === 'docx') {
    return {short: 'DOC', color: '#3b6fd8'};
  }
  if (ext === 'pptx') {
    return {short: 'PPT', color: '#d9722b'};
  }
  return {short: 'TXT', color: '#7a869f'};
}

export default function DocumentsScreen(props: Props) {
  const [hint, setHint] = useState<FormatType | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [, tick] = useState(0);
  const nextId = useRef(1);

  const busy = jobs.some(j => j.state === 'busy');
  useEffect(() => {
    if (!busy) {
      return;
    }
    const timer = setInterval(() => tick(t => t + 1), 1000); // updates the "Reading… 12s" timer
    return () => clearInterval(timer);
  }, [busy]);

  const update = (id: number, patch: Partial<Job>) => setJobs(js => js.map(j => (j.id === id ? {...j, ...patch} : j)));

  async function uploadAll(files: UploadFile[]) {
    let last: Doc | null = null;
    for (const file of files) {
      const id = nextId.current++;
      setJobs(js => [{id, name: file.name, state: 'busy', message: '', started: Date.now(), size: file.size, sent: 0}, ...js]);
      try {
        const doc = await uploadDocument(file, hint, fraction =>
          setJobs(js =>
            js.map(j => (j.id === id ? {...j, sent: fraction, readingSince: fraction >= 1 ? j.readingSince || Date.now() : undefined} : j)),
          ),
        );
        const pages = `${doc.page_count} page${doc.page_count > 1 ? 's' : ''}`;
        update(id, {state: 'ok', message: `Done! Read as ${FORMAT_LABEL[doc.format_type].toLowerCase()}, ${pages}.`});
        setTimeout(() => setJobs(js => js.filter(j => j.id !== id)), 8000);
        last = doc;
      } catch (e: any) {
        update(id, {state: 'err', message: e.message});
      }
    }
    if (last) {
      props.onUploaded(last);
    }
  }

  async function chooseFiles() {
    try {
      const picked = await pick({type: PICK_TYPES, allowMultiSelection: true});
      await uploadAll(
        picked.map(f => ({uri: f.uri, name: f.name || 'document', type: f.type || 'application/octet-stream', size: f.size})),
      );
    } catch (e) {
      if (!(isErrorWithCode(e) && e.code === errorCodes.OPERATION_CANCELED)) {
        Alert.alert('Could not open the file', String((e as Error).message || e));
      }
    }
  }

  async function takePhoto() {
    const result = await launchCamera({...PHOTO, saveToPhotos: false});
    if (result.didCancel) {
      return;
    }
    const asset = result.assets?.[0];
    if (result.errorCode || !asset?.uri) {
      Alert.alert('Camera', result.errorMessage || 'Could not take the photo.');
      return;
    }
    await uploadAll([photoFile(asset)]);
  }

  async function fromGallery() {
    const result = await launchImageLibrary({...PHOTO, selectionLimit: 0}); // 0 = pick several
    if (result.didCancel) {
      return;
    }
    const assets = (result.assets || []).filter(a => a.uri);
    if (result.errorCode || !assets.length) {
      Alert.alert('Gallery', result.errorMessage || 'Could not open the photo.');
      return;
    }
    await uploadAll(assets.map(photoFile));
  }

  const docs = [...props.docs].reverse(); // newest first
  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.h2}>Your documents</Text>
      <Text style={styles.sub}>Add notes, and I'll read them, even handwriting.</Text>

      <View style={styles.uploadRow}>
        <Pressable style={({pressed}) => [styles.uploadBtn, pressed && styles.pressed]} onPress={chooseFiles}>
          <Text style={styles.uploadIcon}>⇪</Text>
          <Text style={styles.uploadTitle}>Choose file</Text>
          <Text style={styles.uploadSub}>PDF, Word, PowerPoint, text, image</Text>
        </Pressable>
        <Pressable style={({pressed}) => [styles.uploadBtn, pressed && styles.pressed]} onPress={fromGallery}>
          <Text style={styles.uploadIcon}>🖼</Text>
          <Text style={styles.uploadTitle}>From gallery</Text>
          <Text style={styles.uploadSub}>photos, shrunk for a fast upload</Text>
        </Pressable>
        <Pressable style={({pressed}) => [styles.uploadBtn, pressed && styles.pressed]} onPress={takePhoto}>
          <Text style={styles.uploadIcon}>📷</Text>
          <Text style={styles.uploadTitle}>Take photo</Text>
          <Text style={styles.uploadSub}>of printed or handwritten notes</Text>
        </Pressable>
      </View>

      <Text style={styles.label}>Kind of writing</Text>
      <View style={styles.chips}>
        {HINTS.map(h => (
          <Pressable
            key={h.label}
            onPress={() => setHint(h.value)}
            style={[styles.chip, hint === h.value && styles.chipOn]}
            accessibilityRole="radio"
            accessibilityState={{selected: hint === h.value}}>
            <Text style={[styles.chipText, hint === h.value && styles.chipTextOn]}>{h.label}</Text>
          </Pressable>
        ))}
      </View>

      {props.publicDemo && (
        <Text style={styles.privacy}>🔒 Your files are private to this app session and are deleted automatically a few minutes after you leave.</Text>
      )}

      {jobs.map(j => (
        <View key={j.id} style={[styles.job, j.state === 'ok' && styles.jobOk, j.state === 'err' && styles.jobErr]}>
          {j.state === 'busy' ? <ActivityIndicator color={colors.accent} /> : <Text>{j.state === 'ok' ? '✔' : '!'}</Text>}
          <View style={styles.flex}>
            <Text style={styles.jobName} numberOfLines={1}>{j.name}</Text>
            <Text style={[styles.jobMsg, j.state === 'err' && {color: colors.rose}]}>
              {j.state === 'busy' ? busyText(j) : j.message}
            </Text>
          </View>
        </View>
      ))}

      <View style={styles.libHead}>
        <Text style={styles.h3}>Library</Text>
        <Text style={styles.sub}>{docs.length ? `${docs.length} document${docs.length > 1 ? 's' : ''}` : ''}</Text>
      </View>
      {!docs.length && <Text style={styles.empty}>Nothing here yet. Your uploaded notes will appear here.</Text>}
      {docs.map(d => {
        const name = docName(d);
        const badge = kindBadge(name);
        const on = props.selected.has(d.doc_id);
        return (
          <View key={d.doc_id} style={[styles.doc, on && styles.docOn]}>
            <Pressable style={styles.docMain} onPress={() => props.onPreview(d)}>
              <View style={[styles.ficon, {backgroundColor: badge.color}]}>
                <Text style={styles.ficonText}>{badge.short}</Text>
              </View>
              <View style={styles.flex}>
                <Text style={[styles.dname, props.previewId === d.doc_id && {color: colors.accent}]} numberOfLines={1}>{name}</Text>
                <Text style={styles.dsub}>
                  {FORMAT_LABEL[d.format_type]} · {d.page_count} page{d.page_count > 1 ? 's' : ''}
                </Text>
              </View>
            </Pressable>
            <View style={styles.docActions}>
              <Pressable style={styles.askOn} onPress={() => props.onToggle(d.doc_id)} accessibilityRole="checkbox" accessibilityState={{checked: on}}>
                <View style={[styles.box, on && styles.boxOn]}>{on && <Text style={styles.tick}>✓</Text>}</View>
                <Text style={[styles.askOnText, on && styles.askOnTextOn]}>Ask about this</Text>
              </Pressable>
              <Pressable style={styles.smallBtn} onPress={() => props.onPreview(d)}>
                <Text style={styles.smallBtnText}>View</Text>
              </Pressable>
              <Pressable style={[styles.smallBtn, styles.delBtn]} onPress={() => props.onDelete(d)}>
                <Text style={[styles.smallBtnText, {color: colors.rose}]}>Remove</Text>
              </Pressable>
            </View>
          </View>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {flex: 1},
  content: {padding: 16, paddingBottom: 28},
  flex: {flex: 1, minWidth: 0},
  h2: {fontSize: 18, fontWeight: '700', color: colors.text},
  h3: {fontSize: 15, fontWeight: '700', color: colors.text},
  sub: {fontSize: 13, color: colors.muted, marginTop: 2},
  uploadRow: {flexDirection: 'row', gap: 8, marginTop: 14},
  uploadBtn: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 18,
    paddingHorizontal: 8,
    borderRadius: 14,
    borderWidth: 2,
    borderStyle: 'dashed',
    borderColor: '#cfd7ec',
    backgroundColor: '#fafbff',
  },
  pressed: {backgroundColor: colors.accentSoft, borderColor: colors.accent},
  uploadIcon: {fontSize: 24, color: colors.accent},
  uploadTitle: {marginTop: 6, fontSize: 14, fontWeight: '700', color: colors.text},
  uploadSub: {marginTop: 2, fontSize: 11, color: colors.muted, textAlign: 'center'},
  label: {marginTop: 16, fontSize: 13, color: colors.muted},
  chips: {flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8},
  chip: {paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.panel},
  chipOn: {backgroundColor: colors.accentSoft, borderColor: colors.accent2},
  chipText: {fontSize: 13, color: colors.text},
  chipTextOn: {color: colors.accent, fontWeight: '700'},
  privacy: {marginTop: 14, fontSize: 12, color: colors.mint, backgroundColor: colors.mintSoft, borderRadius: 10, padding: 10},
  job: {flexDirection: 'row', gap: 10, alignItems: 'center', marginTop: 10, padding: 12, borderRadius: 12, backgroundColor: colors.soft},
  jobOk: {backgroundColor: colors.mintSoft},
  jobErr: {backgroundColor: colors.roseSoft},
  jobName: {fontWeight: '700', fontSize: 13, color: colors.text},
  jobMsg: {fontSize: 12, color: colors.muted},
  libHead: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 20, marginBottom: 8},
  empty: {textAlign: 'center', color: colors.muted, paddingVertical: 24},
  doc: {borderWidth: 1, borderColor: colors.line, borderRadius: 12, backgroundColor: colors.panel, padding: 10, marginBottom: 8},
  docOn: {borderColor: colors.accent2, backgroundColor: '#f7f9ff'},
  docMain: {flexDirection: 'row', gap: 10, alignItems: 'center'},
  ficon: {width: 38, height: 38, borderRadius: 10, alignItems: 'center', justifyContent: 'center'},
  ficonText: {color: '#fff', fontSize: 11, fontWeight: '800'},
  dname: {fontSize: 14, fontWeight: '700', color: colors.text},
  dsub: {fontSize: 12, color: colors.muted, marginTop: 2},
  docActions: {flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 10, paddingTop: 8, borderTopWidth: 1, borderTopColor: colors.line},
  askOn: {flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 40},
  box: {width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: '#b7c2de', alignItems: 'center', justifyContent: 'center'},
  boxOn: {backgroundColor: colors.accent, borderColor: colors.accent},
  tick: {color: '#fff', fontSize: 13, fontWeight: '800'},
  askOnText: {fontSize: 13, color: colors.muted},
  askOnTextOn: {color: colors.accent, fontWeight: '700'},
  smallBtn: {paddingHorizontal: 12, minHeight: 40, justifyContent: 'center', borderRadius: 10, backgroundColor: colors.soft},
  delBtn: {backgroundColor: colors.roseSoft},
  smallBtnText: {fontSize: 13, fontWeight: '700', color: colors.accent},
});
