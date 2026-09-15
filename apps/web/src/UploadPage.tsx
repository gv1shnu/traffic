import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  Clock3,
  Film,
  FolderOpen,
  ScanLine,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { api, uploadVideo, validateFile } from "./api";
import { human, stamp, type Video } from "./types";

export function UploadPage() {
  const nav = useNavigate(),
    client = useQueryClient(),
    input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(0),
    [error, setError] = useState("");
  const config = useQuery({
    queryKey: ["config"],
    queryFn: () =>
      api<{
        max_upload_mb: number;
        max_duration_seconds: number;
        mode: string;
      }>("/config"),
  });
  const videos = useQuery({
    queryKey: ["videos"],
    queryFn: () => api<Video[]>("/videos"),
  });
  const max = config.data?.max_upload_mb ?? 250;
  async function choose(file?: File) {
    if (!file) return;
    const invalid = validateFile(file, max);
    if (invalid) {
      setError(invalid);
      return;
    }
    setError("");
    setBusy(true);
    setProgress(0);
    try {
      const v = await uploadVideo<Video>(file, setProgress);
      await client.invalidateQueries({ queryKey: ["videos"] });
      nav(`/configure/${v.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const completed =
    videos.data?.filter((v) => v.job?.status === "completed").length ?? 0;
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <span /> THE ROAD TELLS A STORY
          </div>
          <h1>Find where the slowdown started.</h1>
          <p className="lede">
            Turn traffic footage into a clear, reviewable chain of evidence.
          </p>
        </div>
        <span className="edition">
          INDIA EDITION <span>01</span>
        </span>
      </div>
      <div className="upload-layout">
        <section className="card upload-card">
          <div className="card-heading">
            <h2>Start an investigation</h2>
            <span className="small-tag">VIDEO ANALYSIS</span>
          </div>
          <div
            className={`dropzone ${drag ? "dragging" : ""} ${busy ? "is-busy" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              if (!busy) void choose(e.dataTransfer.files[0]);
            }}
          >
            <div className="upload-symbol">
              <Upload size={27} />
              <span className="corner top-left" />
              <span className="corner top-right" />
              <span className="corner bottom-left" />
              <span className="corner bottom-right" />
            </div>
            <h3>
              {busy
                ? progress < 100
                  ? "Uploading your footage…"
                  : "Validating video metadata…"
                : "Drop your traffic footage here"}
            </h3>
            <p>
              {busy
                ? "Keep this page open while the video is checked."
                : "A fixed camera. A stretch of road. A starting point."}
            </p>
            <input
              aria-label="Upload traffic video"
              ref={input}
              type="file"
              accept=".mp4,.mov,.mkv,.avi"
              disabled={busy}
              onChange={(e) => void choose(e.target.files?.[0])}
              hidden
            />
            {busy ? (
              <div className="upload-progress">
                <progress max="100" value={progress} />
                <span>{Math.round(progress)}% uploaded</span>
              </div>
            ) : (
              <button
                className="primary"
                onClick={() => input.current?.click()}
              >
                <FolderOpen size={16} /> Choose video <ArrowUpRight size={16} />
              </button>
            )}
            <div className="file-guidance">
              MP4, MOV, MKV, AVI <i /> Up to {max} MB <i />{" "}
              {Math.floor((config.data?.max_duration_seconds ?? 600) / 60)} min
              max
            </div>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={15} />
              </button>
            </div>
          )}
          <div className="upload-foot">
            <span>
              <ShieldCheck size={16} /> Processed locally. No external video
              upload.
            </span>
            <span>{config.data?.mode?.toUpperCase() ?? "LOCAL"} MODE</span>
          </div>
        </section>
        <aside className="road-card">
          <div className="road-top">
            <span className="small-tag">FROM FOOTAGE TO FINDINGS</span>
            <ScanLine size={21} />
          </div>
          <div className="road-illustration" aria-hidden="true">
            <div className="road-lane lane-one" />
            <div className="road-lane lane-two" />
            <div className="car car-one" />
            <div className="car car-two" />
            <div className="car car-three" />
            <div className="car car-four" />
            <div className="car car-five" />
            <span className="scan-bracket" />
            <span className="road-label">FOLLOW THE EVIDENCE</span>
          </div>
          <h2>Beyond the traffic jam.</h2>
          <p>
            Trace congestion back to its likely origin, with every conclusion
            linked to visible evidence.
          </p>
          <div className="road-caption">
            <span>DETECT</span>
            <ArrowRight size={12} />
            <span>TRACE</span>
            <ArrowRight size={12} />
            <span>REVIEW</span>
          </div>
        </aside>
      </div>
      <div className="workflow-strip">
        {[
          [
            <Film size={19} />,
            "01",
            "Upload footage",
            "Add a fixed-camera traffic video.",
          ],
          [
            <ScanLine size={19} />,
            "02",
            "Define the road",
            "Mark lanes and traffic direction.",
          ],
          [
            <ArrowDownToLine size={19} />,
            "03",
            "Follow the evidence",
            "Review subjects, timing and cause.",
          ],
        ].map(([icon, n, title, body], i) => (
          <div className="workflow-item" key={i}>
            <span className="workflow-icon">{icon}</span>
            <div>
              <span className="step-label">
                {n} / {title}
              </span>
              <p>{body}</p>
            </div>
            {i < 2 && <ArrowRight className="workflow-arrow" size={17} />}
          </div>
        ))}
      </div>
      <section className="recent-section">
        <div className="section-heading">
          <div>
            <h2>
              Recent investigations{" "}
              <span className="count">{videos.data?.length ?? 0}</span>
            </h2>
            <p>Your footage, findings and review history in one place.</p>
          </div>
          <span className="muted small">
            <Check size={14} /> {completed} completed
          </span>
        </div>
        {videos.isLoading ? (
          <div className="empty-state">Loading investigations…</div>
        ) : videos.error ? (
          <div className="error" role="alert">
            {videos.error.message}
            <button onClick={() => void videos.refetch()}>Retry</button>
          </div>
        ) : !videos.data?.length ? (
          <div className="empty-state">
            <span className="empty-icon">
              <Film size={25} />
            </span>
            <h3>A clearer picture starts with one video.</h3>
            <p>
              Your investigations will appear here after you upload footage.
            </p>
            <span className="muted small">
              <Clock3 size={13} /> Evidence is retained for the configured
              retention period.
            </span>
          </div>
        ) : (
          <div className="investigation-list">
            {videos.data.map((v) => (
              <Link
                className="investigation-row"
                key={v.id}
                to={
                  v.job?.incident_id
                    ? `/incidents/${v.job.incident_id}`
                    : v.job &&
                        [
                          "queued",
                          "processing",
                          "failed",
                          "cancelled",
                        ].includes(v.job.status)
                      ? `/jobs/${v.job.id}`
                      : `/configure/${v.id}`
                }
              >
                <img src={v.thumbnail_url} alt="Video preview" />
                <div>
                  <strong>{v.filename}</strong>
                  <p>
                    {new Date(v.created_at).toLocaleDateString()} <span>·</span>{" "}
                    {stamp(v.metadata.duration_seconds)} <span>·</span>{" "}
                    {v.metadata.width} × {v.metadata.height}
                  </p>
                </div>
                <span
                  className={`badge ${v.job?.status === "completed" ? "success" : ""}`}
                >
                  {human(v.job?.status ?? v.status)}
                </span>
                <ArrowUpRight size={18} />
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
