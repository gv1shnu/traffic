import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  LoaderCircle,
  RotateCcw,
  Square,
} from "lucide-react";
import { api } from "./api";
import { human, type Job } from "./types";
export const stages = [
  "validate_video",
  "extract_metadata",
  "detect_and_track",
  "calculate_motion",
  "detect_congestion",
  "generate_candidates",
  "score_candidates",
  "extract_plate",
  "select_evidence",
  "generate_explanation",
  "quality_check",
  "persist_results",
];
export function JobStatus({ job }: { job: Job }) {
  const idx = stages.indexOf(job.stage);
  return (
    <>
      <div className="progress-title">
        <span>{human(job.stage)}</span>
        <strong>{Math.round(job.progress)}%</strong>
      </div>
      <progress max="100" value={job.progress} />
      <ol className="stages">
        {stages.map((stage, i) => (
          <li
            key={stage}
            className={
              stage === job.stage
                ? "current"
                : job.timings?.[stage] !== undefined
                  ? "done"
                  : ""
            }
          >
            <span>
              {job.timings?.[stage] !== undefined ? <Check size={13} /> : i + 1}
            </span>
            {human(stage)}
            {(i < idx || job.status === "completed") &&
              job.timings?.[stage] === undefined && <small>skipped</small>}
            {stage === job.stage && job.status === "processing" && (
              <LoaderCircle size={15} className="spin" />
            )}
          </li>
        ))}
      </ol>
    </>
  );
}
export function ProcessingPage() {
  const { id } = useParams(),
    nav = useNavigate();
  const [live, setLive] = useState<Job | null>(null),
    [error, setError] = useState(""),
    [tick, setTick] = useState(Date.now());
  const query = useQuery({
    queryKey: ["job", id],
    queryFn: () => api<Job>(`/jobs/${id}`),
    refetchInterval: 5000,
  });
  const job = live ?? query.data;
  useEffect(() => {
    setLive(null);
    const source = new EventSource(`/api/v1/jobs/${id}/events`);
    source.onmessage = (e) => {
      const data = JSON.parse(e.data) as Job;
      setLive(data);
      if (["completed", "failed", "cancelled"].includes(data.status))
        source.close();
    };
    return () => source.close();
  }, [id]);
  useEffect(() => {
    if (query.data) setLive(query.data);
  }, [query.data]);
  useEffect(() => {
    if (job?.incident_id)
      nav(`/incidents/${job.incident_id}`, { replace: true });
  }, [job?.incident_id, nav]);
  useEffect(() => {
    const timer = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  async function action(name: string) {
    setError("");
    try {
      const updated = await api<Job>(`/jobs/${id}/${name}`, { method: "POST" });
      setLive(updated);
      void query.refetch();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (!job)
    return (
      <div className="page">
        {query.error ? (
          <div className="error">{query.error.message}</div>
        ) : (
          "Loading job…"
        )}
      </div>
    );
  const elapsed = Math.max(
    0,
    Math.round(
      (tick - new Date(job.started_at ?? job.created_at).getTime()) / 1000,
    ),
  );
  return (
    <div className="page processing-page">
      <Link className="back-link" to="/">
        <ArrowLeft size={15} /> Investigations
      </Link>
      <div className="eyebrow">FOLLOWING THE EVIDENCE</div>
      <h1>
        {job.status === "failed"
          ? "The investigation paused."
          : job.status === "cancelled"
            ? "Investigation cancelled."
            : "Connecting the dots."}
      </h1>
      <p className="lede">
        Each stage reports actual work. You can leave this page and return
        later.
      </p>
      <div className="card processing-card">
        <div className="card-heading">
          <h2>Analysis progress</h2>
          <span className="badge">{job.mode.toUpperCase()} processing</span>
        </div>
        <JobStatus job={job} />
        <div className="processing-foot">
          <span>
            {elapsed}s elapsed{" "}
            {Object.keys(job.timings).length > 0 &&
              `· ${Object.keys(job.timings).length} stages recorded`}
          </span>
          {["failed", "cancelled"].includes(job.status) ? (
            <button className="primary" onClick={() => void action("retry")}>
              <RotateCcw size={15} /> Retry investigation
            </button>
          ) : (
            <button className="secondary" onClick={() => void action("cancel")}>
              <Square size={13} /> Cancel
            </button>
          )}
        </div>
        {(error || job.error_details) && (
          <div className="error" role="alert">
            {error || job.error_details}
          </div>
        )}
      </div>
      <p className="muted">
        ByteTrack runs on sampled frames. Dense traffic and CPU inference may
        take longer. Stages not applicable to the evidence are skipped.
      </p>
    </div>
  );
}
