import { useEffect, useRef, useState } from 'react';
import { FileText, X } from 'lucide-react';
import { apiFile } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import { ErrorNotice, LoadingRows, humanError } from '../../components/ui';

/**
 * Opens one uploaded record in a dialog. The file is fetched with the viewer's identity (row-level
 * security decides, and the view is audited), shown from a local object URL, and released on close.
 */
export function RecordViewer({
  docId,
  title,
  onClose,
}: {
  docId: string;
  title: string;
  onClose: () => void;
}) {
  const { auth } = useAuth();
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState('');
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    apiFile(`/api/records/${docId}/file`, auth)
      .then(async (blob) => {
        if (cancelled) return;
        if (blob.type.startsWith('application/pdf')) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        } else {
          setText(await blob.text());
        }
      })
      .catch((cause) => !cancelled && setError(humanError(cause)));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docId, auth]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <button
        className="absolute inset-0 bg-ink/40"
        aria-label="Close document"
        onClick={onClose}
      />
      <div
        className="relative flex h-[min(88dvh,900px)] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white"
        style={{ boxShadow: 'var(--shadow-pop)' }}
      >
        <header className="flex items-center gap-3 border-b border-line px-5 py-3">
          <FileText size={16} className="text-brand-700" aria-hidden="true" />
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">
            {title}
          </h2>
          <span className="hidden text-[11px] text-muted sm:inline">
            This view is recorded in the audit log
          </span>
          <button
            ref={closeRef}
            onClick={onClose}
            aria-label="Close document"
            className="btn btn-ghost px-2"
          >
            <X size={18} />
          </button>
        </header>
        <div className="min-h-0 flex-1 bg-canvas">
          {error ? (
            <div className="p-5">
              <ErrorNotice message={error} />
            </div>
          ) : url ? (
            <iframe
              title={title}
              src={url}
              className="h-full w-full border-0"
            />
          ) : text !== null ? (
            <pre className="h-full overflow-auto whitespace-pre-wrap p-6 text-sm leading-relaxed">
              {text}
            </pre>
          ) : (
            <LoadingRows rows={4} />
          )}
        </div>
      </div>
    </div>
  );
}
