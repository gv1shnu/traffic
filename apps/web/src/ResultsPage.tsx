import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Eye,
  FileJson,
  ScanLine,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { api } from "./api";
import { causes, confidenceLabel, human, stamp, type Report } from "./types";

export function PlateResult({ report }: { report: Report }) {
  const plate = report.license_plate,
    crop = report.evidence.find((a) => a.id === plate.evidence_asset_id);
  return (
    <div className="plate-result">
      <span className="eyebrow">LICENSE PLATE</span>
      {plate.status === "recognized" ? (
        <>
          <div className="plate-number">
            <span>IND</span>
            {plate.text}
          </div>
          <span className="muted small">
            {Math.round(plate.confidence * 100)}% OCR consensus confidence
          </span>
          {crop && (
            <img
              className="plate-crop"
              src={crop.url}
              alt="Supporting plate crop"
            />
          )}
        </>
      ) : (
        <>
          <h3>No reliable plate detected</h3>
          <p>Use the evidentiary frame to review the suspected subject.</p>
        </>
      )}
      {plate.raw_readings.length > 0 && (
        <details>
          <summary>Uncertain / raw OCR readings</summary>
          {plate.raw_readings.map((r, i) => (
            <p key={i}>
              <code>{r.raw_text}</code> · {Math.round(r.confidence * 100)}% ·{" "}
              {stamp(r.timestamp)}
            </p>
          ))}
        </details>
      )}
    </div>
  );
}
export function ReviewForm({ report }: { report: Report }) {
  const client = useQueryClient(),
    [cause, setCause] = useState(report.cause.type),
    [plate, setPlate] = useState(""),
    [track, setTrack] = useState(""),
    [notes, setNotes] = useState(""),
    [feedback, setFeedback] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const reviews = useQuery({
    queryKey: ["reviews", report.incident_id],
    queryFn: () =>
      api<
        {
          id: string;
          action: string;
          corrected_cause: string | null;
          corrected_plate: string | null;
          corrected_track: number | null;
          notes: string;
        }[]
      >(`/incidents/${report.incident_id}/reviews`),
  });
  async function save(action: string) {
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      await api(`/incidents/${report.incident_id}/review`, {
        method: "PATCH",
        body: JSON.stringify({
          action,
          ...(action === "corrected"
            ? {
                corrected_cause: cause,
                corrected_plate: plate || null,
                corrected_track: track ? Number(track) : null,
              }
            : {}),
          notes,
        }),
      });
      setFeedback("Review saved. Original computed evidence is preserved.");
      void client.invalidateQueries({
        queryKey: ["report", report.incident_id],
      });
      void client.invalidateQueries({
        queryKey: ["reviews", report.incident_id],
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card review-card">
      <div className="card-heading">
        <h2>
          <ShieldCheck size={19} /> Human review
        </h2>
        <span className="badge">{report.review_status}</span>
      </div>
      <p>
        The evidence informs your judgment. Confirm the assessment or record a
        correction.
      </p>
      <div className="review-actions">
        <button
          className="primary"
          disabled={busy}
          onClick={() => void save("confirmed")}
        >
          <Check size={16} /> Confirm result
        </button>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void save("rejected")}
        >
          <X size={16} /> Mark incorrect
        </button>
      </div>
      <details>
        <summary>
          Correct the assessment <ChevronDown size={15} />
        </summary>
        <div className="review-fields">
          <label>
            Cause category
            <select value={cause} onChange={(e) => setCause(e.target.value)}>
              {causes.map((c) => (
                <option key={c} value={c}>
                  {human(c)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Selected subject
            <select value={track} onChange={(e) => setTrack(e.target.value)}>
              <option value="">Keep computed subject</option>
              {report.tracks.map((t) => (
                <option key={t.track_id} value={t.track_id}>
                  #{t.track_id} · {t.object_type}
                </option>
              ))}
            </select>
          </label>
          <label>
            Corrected plate
            <input
              value={plate}
              onChange={(e) => setPlate(e.target.value)}
              placeholder="Only if independently readable"
              maxLength={32}
            />
          </label>
        </div>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void save("corrected")}
        >
          Save correction
        </button>
      </details>
      <label>
        Reviewer notes
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What supports or changes this assessment?"
          maxLength={4000}
        />
      </label>
      {feedback && (
        <p role="status" className="success-message">
          <CheckCircle2 size={16} />
          {feedback}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {reviews.data && reviews.data.length > 0 && (
        <details>
          <summary>Review history ({reviews.data.length})</summary>
          {reviews.data.map((r) => (
            <div className="review-history" key={r.id}>
              <strong>{human(r.action)}</strong>
              <p>
                {[
                  r.corrected_cause && human(r.corrected_cause),
                  r.corrected_track != null && `Track #${r.corrected_track}`,
                  r.corrected_plate,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <p>{r.notes}</p>
            </div>
          ))}
        </details>
      )}
    </section>
  );
}
export function ResultsPage() {
  const { id } = useParams(),
    nav = useNavigate();
  const query = useQuery({
    queryKey: ["report", id],
    queryFn: () => api<Report>(`/incidents/${id}`),
  });
  const player = useRef<HTMLVideoElement>(null),
    [time, setTime] = useState(0),
    [boxes, setBoxes] = useState(true),
    [tab, setTab] = useState("evidence"),
    [deleting, setDeleting] = useState(false),
    [error, setError] = useState("");
  const r = query.data;
  if (!r)
    return (
      <div className="page">
        {query.error ? (
          <div className="error">{query.error.message}</div>
        ) : (
          "Loading evidence…"
        )}
      </div>
    );
  function seek(t: number) {
    if (player.current) {
      player.current.currentTime = t;
      setTime(t);
    }
  }
  const visible = r.tracks.flatMap((t) => {
    const row = t.observations.reduce<
      (typeof t.observations)[number] | undefined
    >(
      (best, o) =>
        Math.abs(o.timestamp - time) < 0.25 &&
        (!best ||
          Math.abs(o.timestamp - time) < Math.abs(best.timestamp - time))
          ? o
          : best,
      undefined,
    );
    return row ? [row] : [];
  });
  const best = r.evidence.find(
      (a) => a.id === r.fallback_subject_frame.asset_id,
    ),
    clip = r.evidence.find((a) => a.asset_type === "clip");
  async function remove() {
    if (!r) return;
    try {
      await api(`/videos/${r.video.id}`, { method: "DELETE" });
      nav("/");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <div className="page results-page">
      <Link className="back-link" to="/">
        <ArrowLeft size={15} /> Investigations
      </Link>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <span /> INVESTIGATION COMPLETE
          </div>
          <h1>
            {r.congestion.detected
              ? "The queue, in context."
              : "No sustained congestion detected."}
          </h1>
          <p className="lede">
            {r.video.filename} <span className="divider">/</span>{" "}
            {stamp(r.video.duration_seconds)} <span className="divider">/</span>{" "}
            {r.video.width} × {r.video.height}
          </p>
        </div>
        <a
          className="secondary"
          href={`/api/v1/incidents/${id}/report.json`}
          download
        >
          <FileJson size={16} /> Export report
        </a>
      </div>
      <div className="result-summary">
        <div>
          <span>CONGESTION START</span>
          <strong>{stamp(r.congestion.start_seconds)}</strong>
        </div>
        <div>
          <span>LIKELY CAUSE</span>
          <strong className="cause-label">{human(r.cause.type)}</strong>
        </div>
        <div>
          <span>CAUSE CONFIDENCE</span>
          <strong>
            {r.cause.type === "unknown"
              ? "Unresolved"
              : `${Math.round(r.cause.confidence * 100)}%`}{" "}
            <small>
              {r.cause.type !== "unknown" &&
                confidenceLabel(r.cause.confidence)}
            </small>
          </strong>
        </div>
        <div>
          <span>PEAK QUEUE</span>
          <strong>
            {r.congestion.peak_queue_size} <small>vehicles</small>
          </strong>
        </div>
      </div>
      <div className="result-grid">
        <section>
          <div className="card video-card">
            <div className="card-heading">
              <h2>
                <ScanLine size={18} /> Evidence player
              </h2>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={boxes}
                  onChange={(e) => setBoxes(e.target.checked)}
                />{" "}
                Track overlays
              </label>
            </div>
            <div className="video-stage">
              <video
                ref={player}
                src={r.video.url}
                controls
                onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                preload="metadata"
              />
              {boxes && (
                <svg
                  viewBox={`0 0 ${r.video.width} ${r.video.height}`}
                  className="video-overlay"
                  aria-label="Tracked object annotations"
                >
                  {visible.map((o) => (
                    <g key={o.track_id}>
                      <rect
                        x={o.bbox[0]}
                        y={o.bbox[1]}
                        width={o.bbox[2] - o.bbox[0]}
                        height={o.bbox[3] - o.bbox[1]}
                        stroke={
                          o.track_id === r.cause.suspected_track_id
                            ? "#f1bf7b"
                            : "#77d6c2"
                        }
                        fill="none"
                        strokeWidth="3"
                      />
                      <text
                        x={o.bbox[0] + 3}
                        y={Math.max(18, o.bbox[1] - 7)}
                        fill="#fff"
                        stroke="#142c2a"
                        paintOrder="stroke"
                        strokeWidth="3"
                        fontSize={Math.max(14, r.video.width / 65)}
                      >
                        #{o.track_id} {o.object_type}
                      </text>
                    </g>
                  ))}
                </svg>
              )}
            </div>
            <div className="timeline">
              <div className="timeline-heading">
                <span>
                  <Clock3 size={13} /> INCIDENT TIMELINE
                </span>
                <span>{stamp(time)}</span>
              </div>
              <div className="timeline-bar">
                <div
                  style={{
                    width: `${(time / r.video.duration_seconds) * 100}%`,
                  }}
                />
                {r.timeline.map((m, i) => (
                  <button
                    key={i}
                    style={{
                      left: `${(m.timestamp / r.video.duration_seconds) * 100}%`,
                    }}
                    title={`${m.label} · ${stamp(m.timestamp)}`}
                    aria-label={`Seek to ${m.label}`}
                    onClick={() => seek(m.timestamp)}
                  />
                ))}
              </div>
              <div className="timeline-markers">
                {r.timeline.length ? (
                  r.timeline.map((m, i) => (
                    <button key={i} onClick={() => seek(m.timestamp)}>
                      <span>{stamp(m.timestamp)}</span>
                      {m.label}
                    </button>
                  ))
                ) : (
                  <p>No congestion event markers were generated.</p>
                )}
              </div>
            </div>
          </div>
          <div className="tabs">
            <button
              className={tab === "evidence" ? "active" : ""}
              onClick={() => setTab("evidence")}
            >
              Evidence frames
            </button>
            <button
              className={tab === "metrics" ? "active" : ""}
              onClick={() => setTab("metrics")}
            >
              Movement & scores
            </button>
            <button
              className={tab === "alternatives" ? "active" : ""}
              onClick={() => setTab("alternatives")}
            >
              Alternative candidates{" "}
              <span>{r.alternative_candidates.length}</span>
            </button>
          </div>
          {tab === "evidence" && (
            <div>
              <div className="evidence-grid">
                {r.evidence
                  .filter((a) =>
                    ["before", "during", "after"].includes(a.asset_type),
                  )
                  .map((a) => (
                    <button
                      className="evidence-frame"
                      onClick={() => seek(a.timestamp)}
                      key={a.id}
                    >
                      <img
                        src={a.url}
                        alt={`${a.asset_type} the congestion event`}
                      />
                      <span>
                        {a.asset_type}
                        <small>{stamp(a.timestamp)}</small>
                      </span>
                    </button>
                  ))}
              </div>
              {clip && (
                <a
                  className="text-link"
                  href={clip.url}
                  download="evidence.mp4"
                >
                  <ArrowDownToLine size={15} /> Download evidence clip
                </a>
              )}
            </div>
          )}
          {tab === "metrics" && (
            <div className="card metrics-card">
              <h2>Measured queue size</h2>
              {r.metrics.length > 0 ? (
                <svg
                  viewBox="0 0 700 160"
                  role="img"
                  aria-label="Queue size over video time"
                >
                  <line x1="20" y1="140" x2="680" y2="140" stroke="#ccd5d0" />
                  <polyline
                    fill="none"
                    stroke="#277b6b"
                    strokeWidth="3"
                    points={r.metrics
                      .filter(
                        (m) =>
                          m.region ===
                          (r.congestion.region ?? r.metrics[0].region),
                      )
                      .map(
                        (m) =>
                          `${20 + (m.timestamp / r.video.duration_seconds) * 660},${140 - (m.queue_size / Math.max(1, ...r.metrics.map((x) => x.queue_size))) * 120}`,
                      )
                      .join(" ")}
                  />
                  <text x="20" y="157" fontSize="10">
                    0s
                  </text>
                  <text x="630" y="157" fontSize="10">
                    {stamp(r.video.duration_seconds)}
                  </text>
                </svg>
              ) : (
                <p>No vehicle movement metrics available.</p>
              )}
              <p className="muted small">
                Motion units: bounding-box lengths / second. Region:{" "}
                {r.congestion.region ?? "whole road"}.
              </p>
              <h3>Attribution factors</h3>
              {Object.entries(r.cause.evidence_scores).map(([k, v]) => (
                <div className="score-row" key={k}>
                  <span>{human(k)}</span>
                  <progress max="1" value={v} />
                  <strong>{Math.round(v * 100)}%</strong>
                </div>
              ))}
              {!Object.keys(r.cause.evidence_scores).length && (
                <p>No candidate met the evidence threshold.</p>
              )}
              <details>
                <summary>Processing timings</summary>
                {Object.entries(r.stage_timings).map(([k, v]) => (
                  <p key={k}>
                    {human(k)}: {v.toFixed(2)}s
                  </p>
                ))}
              </details>
            </div>
          )}
          {tab === "alternatives" && (
            <div className="card alternatives">
              {r.alternative_candidates.length ? (
                r.alternative_candidates.map((c) => (
                  <article key={c.candidate_track_id}>
                    <div>
                      <h3>
                        #{c.candidate_track_id} · {c.object_type}
                      </h3>
                      <span className="badge">
                        {Math.round(c.cause_confidence * 100)}% ·{" "}
                        {confidenceLabel(c.cause_confidence)}
                      </span>
                    </div>
                    <p>{c.explanation}</p>
                    <details>
                      <summary>Calculated evidence factors</summary>
                      {Object.entries(c.evidence_scores).map(([k, v]) => (
                        <p key={k}>
                          {human(k)}: {Math.round(v * 100)}%
                        </p>
                      ))}
                    </details>
                  </article>
                ))
              ) : (
                <p>No alternative candidates had sufficient observations.</p>
              )}
            </div>
          )}
          <ReviewForm report={r} />
        </section>
        <aside>
          <section className="card finding-card">
            <div className="card-heading">
              <h2>
                <Eye size={18} /> The assessment
              </h2>
            </div>
            <div className="finding-body">
              <span className="small-tag">
                SUSPECTED TRAFFIC-CAUSING SUBJECT
              </span>
              <h2>
                {r.cause.suspected_track_id != null
                  ? `${r.cause.object_type} #${r.cause.suspected_track_id}`
                  : "No reliable subject identified"}
              </h2>
              <p>{r.cause.explanation}</p>
              {best && (
                <a href={best.url} target="_blank" rel="noreferrer">
                  <img
                    className="best-frame"
                    src={best.url}
                    alt="Clearest evidentiary frame"
                  />
                  <span className="image-caption">
                    {best.asset_type === "during"
                      ? "Representative incident frame"
                      : "Clearest subject frame"}{" "}
                    <span>{stamp(best.timestamp)}</span>
                  </span>
                </a>
              )}
              <PlateResult report={r} />
            </div>
          </section>
          <details className="card limitations" open>
            <summary>Limitations & provenance</summary>
            <ul>
              {r.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
            <details>
              <summary>Model versions</summary>
              {Object.entries(r.model_versions).map(([k, v]) => (
                <p key={k}>
                  <strong>{k}</strong>: {v}
                </p>
              ))}
            </details>
          </details>
        </aside>
      </div>
      <div className="delete-section">
        {deleting ? (
          <>
            <p>
              Delete this video, every analysis and all associated evidence?
              This cannot be undone.
            </p>
            <button className="danger-button" onClick={() => void remove()}>
              Delete all video data
            </button>
            <button className="secondary" onClick={() => setDeleting(false)}>
              Keep investigation
            </button>
          </>
        ) : (
          <button className="text-link" onClick={() => setDeleting(true)}>
            <Trash2 size={14} /> Delete video & associated evidence
          </button>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
