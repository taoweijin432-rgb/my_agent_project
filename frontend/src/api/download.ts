export interface DownloadBlobOptions {
  document?: Document;
  createObjectURL?: (blob: Blob) => string;
  revokeObjectURL?: (url: string) => void;
}

export function downloadBlob(
  blob: Blob,
  filename: string,
  options: DownloadBlobOptions = {}
): void {
  const targetDocument = options.document ?? document;
  const createObjectURL = options.createObjectURL ?? URL.createObjectURL.bind(URL);
  const revokeObjectURL = options.revokeObjectURL ?? URL.revokeObjectURL.bind(URL);
  const url = createObjectURL(blob);
  const anchor = targetDocument.createElement("a");

  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  targetDocument.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  revokeObjectURL(url);
}
