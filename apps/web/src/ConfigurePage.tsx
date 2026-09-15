import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Plus, RotateCcw, Trash2 } from "lucide-react";
import { api } from "./api";
import type { Job, Point, Region, Video } from "./types";
export function ConfigurePage() {
  const { id } = useParams(),
    nav = useNavigate();
  const video = useQuery({
    queryKey: ["video", id],
    queryFn: () => api<Video>(`/videos/${id}`),
  });
  const [camera, setCamera] = useState("road-camera-01"),
    [regions, setRegions] = useState<Region[]>([]),
    [points, setPoints] = useState<Point[]>([]),
    [name, setName] = useState("Lane 1"),
    [direction, setDirection] = useState("up"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [redact, setRedact] = useState(true);
  const saved = useQuery({
    queryKey: ["camera", camera],
    queryFn: () => api<{ regions: Region[] }>(`/cameras/${camera}/regions`),
    enabled: /^[a-zA-Z0-9_-]{1,64}$/.test(camera),
  });
  useEffect(() => {
    if (saved.data) setRegions(saved.data.regions);
  }, [saved.data]);
  function add() {
    if (points.length < 3) {
      setError("Add at least three polygon corners.");
      return;
    }
    const vectors: Record<string, [number, number]> = {
      up: [0, -1],
      down: [0, 1],
      left: [-1, 0],
      right: [1, 0],
    };
    setRegions([
      ...regions,
      {
        id: `lane_${Date.now()}`,
        name,
        polygon: points,
        direction: vectors[direction],
      },
    ]);
    setPoints([]);
    setName(`Lane ${regions.length + 2}`);
    setError("");
  }
  async function start() {
    if (points.length) {
      setError("Finish or reset the current polygon before starting.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(`/cameras/${camera}/regions`, {
        method: "PUT",
        body: JSON.stringify({ regions }),
      });
      const job = await api<Job>(`/videos/${id}/analyze`, {
        method: "POST",
        body: JSON.stringify({ camera_id: camera, redact }),
      });
      nav(`/jobs/${job.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (video.isLoading) return <p>Loading video…</p>;
  if (!video.data)
    return (
      <div className="error">{video.error?.message ?? "Video not found"}</div>
    );
  return (
    <div className="page">
      <Link className="back-link" to="/">
        <ArrowLeft size={15} /> Investigations
      </Link>
      <div className="eyebrow">STEP 02 / DEFINE THE SCENE</div>
      <h1>Give the road some context.</h1>
      <p className="lede">
        Draw convex road polygons and set the direction traffic moves. Regions
        are reused by camera ID.
      </p>
      <div className="configure-grid">
        <div className="card">
          <div className="card-heading">
            <h2>{video.data.filename}</h2>
            <span className="small-tag">CLICK TO ADD CORNERS</span>
          </div>
          <div className="scene-editor">
            <img
              src={video.data.thumbnail_url}
              alt="Representative traffic frame"
            />
            <svg
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              onClick={(e) => {
                const b = e.currentTarget.getBoundingClientRect();
                setPoints([
                  ...points,
                  {
                    x: (e.clientX - b.left) / b.width,
                    y: (e.clientY - b.top) / b.height,
                  },
                ]);
              }}
              role="img"
              aria-label="Road polygon editor"
            >
              <defs>
                <marker
                  id="arrow"
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#edb56b" />
                </marker>
              </defs>
              {regions.map((r) => {
                const x =
                    (r.polygon.reduce((s, p) => s + p.x, 0) /
                      r.polygon.length) *
                    1000,
                  y =
                    (r.polygon.reduce((s, p) => s + p.y, 0) /
                      r.polygon.length) *
                    1000;
                return (
                  <g key={r.id}>
                    <polygon
                      points={r.polygon
                        .map((p) => `${p.x * 1000},${p.y * 1000}`)
                        .join(" ")}
                      fill="#39c9ad30"
                      stroke="#53dbc0"
                      strokeWidth="3"
                    />
                    <text
                      x={x}
                      y={y - 45}
                      fill="white"
                      textAnchor="middle"
                      fontSize="25"
                    >
                      {r.name}
                    </text>
                    <line
                      x1={x}
                      y1={y}
                      x2={x + r.direction[0] * 65}
                      y2={y + r.direction[1] * 65}
                      stroke="#edb56b"
                      strokeWidth="7"
                      markerEnd="url(#arrow)"
                    />
                  </g>
                );
              })}
              <polyline
                points={points
                  .map((p) => `${p.x * 1000},${p.y * 1000}`)
                  .join(" ")}
                fill="#edb56b20"
                stroke="#edb56b"
                strokeWidth="3"
              />
              {points.map((p, i) => (
                <circle
                  key={i}
                  cx={p.x * 1000}
                  cy={p.y * 1000}
                  r="6"
                  fill="#edb56b"
                />
              ))}
            </svg>
          </div>
          <div className="editor-toolbar">
            <span>{points.length} corners in current polygon</span>
            <button
              className="secondary"
              onClick={() => setPoints(points.slice(0, -1))}
            >
              Undo corner
            </button>
            <button
              className="secondary"
              onClick={() => {
                setRegions([]);
                setPoints([]);
              }}
            >
              <RotateCcw size={14} /> Reset all
            </button>
          </div>
        </div>
        <aside className="card config-controls">
          <h2>Camera & road regions</h2>
          <label>
            Camera ID
            <input
              value={camera}
              onChange={(e) => setCamera(e.target.value)}
              maxLength={64}
            />
          </label>
          <label>
            Region name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Traffic travels
            <select
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
            >
              <option value="up">↑ Up the frame</option>
              <option value="down">↓ Down the frame</option>
              <option value="left">← Left</option>
              <option value="right">→ Right</option>
            </select>
          </label>
          <button className="secondary full" onClick={add}>
            <Plus size={16} /> Finish polygon
          </button>
          <div className="region-list">
            {regions.map((r) => (
              <div key={r.id}>
                <span>{r.name}</span>
                <button
                  aria-label={`Delete ${r.name}`}
                  className="icon-button"
                  onClick={() =>
                    setRegions(regions.filter((x) => x.id !== r.id))
                  }
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
          {!regions.length && (
            <div className="notice">
              Whole-road fallback is available. Its lower reliability means
              cause attribution may remain unknown.
            </div>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={redact}
              onChange={(e) => setRedact(e.target.checked)}
            />{" "}
            Blur detected non-relevant subjects in evidence
          </label>
          <p className="muted small">
            Original video stays unredacted. Review exported evidence for missed
            subjects.
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button
            className="primary full"
            disabled={busy}
            onClick={() => void start()}
          >
            {busy ? "Starting…" : "Save & investigate"}
            <ArrowRight size={16} />
          </button>
        </aside>
      </div>
    </div>
  );
}
