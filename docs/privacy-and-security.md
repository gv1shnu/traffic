# Privacy and security

This is a local decision-support workspace. The interface consistently calls subjects suspected or likely and includes the requested human-review disclaimer. It is not an enforcement or identity-verification system.

## Implemented controls

- UUID storage keys and strict path resolution; original filenames are display metadata only.
- Extension, MIME, container signature, resolution, FPS, duration and inference sample limits.
- Streaming file writes, HTTP-body byte limits before multipart parsing, and an Nginx body cap.
- FFmpeg/FFprobe use argument arrays and a `file,pipe` protocol allowlist; uploaded data is never executed as code.
- Decoder timeouts, worker task deadlines, constrained inference FPS and CPU thread count in Docker.
- Restricted CORS and cross-origin mutation rejection; CSP, no-sniff, no-store and referrer headers.
- Per-process request throttling and safe structured audit records. OCR text and image bytes are not emitted in application logs.
- A delete endpoint removes database relationships and video/evidence directories, after active processing is cancelled.
- Celery beat runs retention hourly; videos older than the configured number of days are removed when no job is active.
- Optional evidence redaction blurs detected non-selected subject boxes. Undetected faces and plates may remain; export review is necessary.
- No LLM, external analytics or external video upload. Model downloads are an explicit setup step and are disabled in inference by default.

## Boundaries

The local API has no login, RBAC or per-user ownership checks. Bind it and the frontend to localhost as documented. Random UUIDs are not access control. Before hosting publicly, add authentication, authorization, TLS, encrypted volumes/object storage, upload quotas, a sandboxed decoder service, network-level resource limits, a shared rate limiter, secret management and backups with deletion handling.

The storage boundary supports replacement but does not encrypt media itself. Use OS disk encryption or encrypted Docker storage when appropriate. Retention does not cover manually downloaded exports or dataset samples. The generated local `storage/datasets` directory is separate from the application media tree.

CSP blocks third-party scripts. A self-contained API reference is generated from the OpenAPI schema at `/docs`; the JSON contract is available at `/openapi.json`. It uses no CDN scripts.

Deleting data is irreversible. The UI asks explicitly, while the API assumes an authorized local caller. Database deletion precedes filesystem cleanup; a filesystem permission failure needs operator cleanup. Cancellation is cooperative between samples/stages; a normalization subprocess may need to reach its timeout before cancellation is observed.
