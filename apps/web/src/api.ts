export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      body?.error?.message || `Request failed (${response.status})`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export function validateFile(file: File, maxMB = 250): string | null {
  if (!/\.(mp4|mov|mkv|avi)$/i.test(file.name))
    return "Choose an MP4, MOV, MKV or AVI video.";
  if (file.size === 0) return "This file is empty.";
  if (file.size > maxMB * 1024 * 1024)
    return `The video must be smaller than ${maxMB} MB.`;
  return null;
}
export function uploadVideo<T>(
  file: File,
  onProgress: (value: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/videos");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress((e.loaded / e.total) * 100);
    };
    xhr.onerror = () =>
      reject(new Error("Connection interrupted. Please try again."));
    xhr.onload = () => {
      let body;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        reject(
          new Error("Upload failed. Check server health and the file size."),
        );
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(body.error?.message || "Upload failed."));
    };
    const data = new FormData();
    data.append("file", file);
    xhr.send(data);
  });
}
