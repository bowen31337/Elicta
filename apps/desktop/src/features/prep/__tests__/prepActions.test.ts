import { describe, expect, it, vi } from 'vitest';

import {
  addVocabularyTerm,
  deleteDocument,
  deleteVocabularyTerm,
  compileBank,
  linkDocument,
  moveCandidate,
  pruneCandidate,
  retagDocument,
  uploadDocument,
} from '../prepActions';

/**
 * The seven writes the preparation screen makes.
 *
 * Journey 1 says the operator sets up the engagement, tags documents, keeps a
 * vocabulary list and prunes the question bank. Every one of those had an
 * endpoint and no caller — the screen rendered `Prune` and `Compile` as
 * buttons with no `onClick`, so the journey described the API, not the
 * product. These assert the calls exist and carry the shape the service
 * validates against.
 */
function stubFetch(body: unknown, { ok = true, status = 200 } = {}) {
  return vi.fn(
    async (_path: string, _init: RequestInit) => ({ ok, status, json: async () => body }) as Response,
  );
}

describe('attaching a document', () => {
  it('sends the link and the tag it was given', async () => {
    const fetch = stubFetch({ id: 'reference-document-1' }, { status: 201 });

    const id = await linkDocument(
      'eng-7',
      { url: 'https://northwind.sharepoint.com/sites/d/RFP.pdf', status: 'ground truth' },
      { fetch },
    );

    expect(id).toBe('reference-document-1');
    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/engagements/eng-7/documents/link');
    expect(JSON.parse(init.body as string)).toEqual({
      url: 'https://northwind.sharepoint.com/sites/d/RFP.pdf',
      status: 'ground truth',
    });
  });

  it('surfaces the service’s own words when it refuses the link', async () => {
    const fetch = stubFetch(
      { detail: [{ msg: 'Value error, url must be a SharePoint or Teams link' }] },
      { ok: false, status: 422 },
    );

    await expect(
      linkDocument('eng-7', { url: 'https://elsewhere.example/x.pdf', status: 'hypothesis' }, { fetch }),
    ).rejects.toThrow('url must be a SharePoint or Teams link');
  });
});

describe('re-tagging a document', () => {
  it('patches only the status, since the tag is the thing being changed', async () => {
    const fetch = stubFetch({ document_id: 'doc-1', name: 'RFP.pdf', status: 'superseded' });

    await retagDocument('doc-1', 'superseded', { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/documents/doc-1/status');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body as string)).toEqual({ status: 'superseded' });
  });
});

describe('adding a vocabulary term', () => {
  it('sends the term with the kind of word it is', async () => {
    const fetch = stubFetch({ term_id: 't-1' }, { status: 201 });

    await addVocabularyTerm('eng-7', { term: 'Zephyr WMS', termType: 'product_name' }, { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/engagements/eng-7/vocabulary');
    expect(JSON.parse(init.body as string)).toEqual({
      term: 'Zephyr WMS',
      term_type: 'product_name',
    });
  });

  it('reports a rejected term type rather than swallowing it', async () => {
    const fetch = stubFetch({ detail: 'unknown term type' }, { ok: false, status: 422 });

    await expect(
      addVocabularyTerm('eng-7', { term: 'Zephyr', termType: 'product_name' }, { fetch }),
    ).rejects.toThrow('unknown term type');
  });
});

describe('compiling the bank', () => {
  it('triggers the compile for the engagement', async () => {
    const fetch = stubFetch({ job_id: 'job-1' }, { status: 202 });

    await compileBank('eng-7', { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/engagements/eng-7/bank/compile');
    expect(init.method).toBe('POST');
  });
});

describe('editing the bank', () => {
  it('prunes a candidate by marking it pruned, not by deleting it', async () => {
    const fetch = stubFetch({ id: 'c-1', pruned: true });

    await pruneCandidate('c-1', { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/bank/candidates/c-1');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body as string)).toEqual({ pruned: true });
  });

  it('reorders by setting the candidate’s priority', async () => {
    const fetch = stubFetch({ id: 'c-3', priority: 1 });

    await moveCandidate('c-3', 1, { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/bank/candidates/c-3');
    expect(JSON.parse(init.body as string)).toEqual({ priority: 1 });
  });

  it('refuses a priority below one rather than letting the service 422', async () => {
    const fetch = stubFetch({});

    await expect(moveCandidate('c-3', 0, { fetch })).rejects.toThrow('priority');
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe('when the service cannot be reached at all', () => {
  it('says so rather than reporting a status it never received', async () => {
    const fetch = vi.fn(async (_path: string, _init: RequestInit): Promise<Response> => {
      throw new TypeError('Failed to fetch');
    });

    await expect(compileBank('eng-7', { fetch })).rejects.toThrow(
      'The service could not be reached.',
    );
  });
});

describe('uploading a document', () => {
  it('sends the file and its tag as a multipart form, not as JSON', async () => {
    const fetch = stubFetch({ document_id: 'doc-9' }, { status: 201 });
    const file = new File([new Uint8Array([1, 2, 3])], 'Scoping deck.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });

    const id = await uploadDocument('eng-7', file, 'ground truth', { fetch });

    expect(id).toBe('doc-9');
    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/engagements/eng-7/documents');
    expect(init.method).toBe('POST');
    const body = init.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get('status')).toBe('ground truth');
    expect((body.get('file') as File).name).toBe('Scoping deck.docx');
  });

  it('lets the browser set the multipart boundary rather than naming a type', async () => {
    // Setting Content-Type by hand omits the boundary, and the service then
    // rejects a body it cannot split.
    const fetch = stubFetch({ document_id: 'doc-9' }, { status: 201 });

    await uploadDocument('eng-7', new File(['x'], 'a.txt'), 'hypothesis', { fetch });

    const [, init] = fetch.mock.calls[0];
    const headers = (init.headers ?? {}) as Record<string, string>;
    expect(Object.keys(headers).map((k) => k.toLowerCase())).not.toContain('content-type');
  });

  it('surfaces the service’s reason when it refuses the file', async () => {
    const fetch = stubFetch(
      { detail: 'file must have a filename, or name must be provided' },
      { ok: false, status: 422 },
    );

    await expect(
      uploadDocument('eng-7', new File(['x'], ''), 'hypothesis', { fetch }),
    ).rejects.toThrow('must have a filename');
  });
});

describe('removing things', () => {
  it('removes a document', async () => {
    const fetch = stubFetch(null, { status: 204 });

    await deleteDocument('doc-1', { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/documents/doc-1');
    expect(init.method).toBe('DELETE');
  });

  it('removes a vocabulary term from its engagement', async () => {
    const fetch = stubFetch(null, { status: 204 });

    await deleteVocabularyTerm('eng-7', 'term-2', { fetch });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe('/api/engagements/eng-7/vocabulary/term-2');
    expect(init.method).toBe('DELETE');
  });

  it('says so when the service will not remove it', async () => {
    const fetch = stubFetch({ detail: 'no document: doc-9' }, { ok: false, status: 404 });

    await expect(deleteDocument('doc-9', { fetch })).rejects.toThrow('no document');
  });
});
