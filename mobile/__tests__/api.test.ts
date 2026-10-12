jest.mock('@react-native-async-storage/async-storage', () => ({getItem: jest.fn(), setItem: jest.fn()}));

import {SESSION_ID, absoluteUrl, docName} from '../src/api';
import {SERVER_URL} from '../src/config';

test('session id matches what the server accepts', () => {
  expect(SESSION_ID).toMatch(/^[A-Za-z0-9-]{8,64}$/);
});

test('document name drops the stored doc_id prefix', () => {
  const doc = {doc_id: 'abc123', file_path: '/data/uploads/abc123_my_notes.pdf', format_type: 'typed' as const, page_count: 2};
  expect(docName(doc)).toBe('my_notes.pdf');
});

test('server paths become absolute URLs', () => {
  expect(absoluteUrl('/documents/x/file')).toBe(`${SERVER_URL}/documents/x/file`);
});
