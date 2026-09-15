export type Job = {
  id: string;
  video_id: string;
  status: string;
  progress: number;
  stage: string;
  error_details: string | null;
  incident_id: string | null;
  created_at: string;
  started_at: string | null;
  mode: string;
  timings: Record<string, number>;
};
export type Video = {
  id: string;
  filename: string;
  status: string;
  created_at: string;
  metadata: {
    width: number;
    height: number;
    duration_seconds: number;
    fps: number;
  };
  thumbnail_url: string;
  job: Job | null;
};
export type Point = { x: number; y: number };
export type Region = {
  id: string;
  name: string;
  polygon: Point[];
  direction: [number, number];
  meters_per_pixel?: number | null;
};
export type Asset = {
  id: string;
  asset_type: string;
  url: string;
  timestamp: number;
  track_id: number | null;
  quality_score: number;
};
export type Observation = {
  track_id: number;
  object_type: string;
  bbox: [number, number, number, number];
  timestamp: number;
  speed: number;
  movement: string;
};
export type Track = {
  track_id: number;
  object_type: string;
  observations: Observation[];
  tracking_confidence: number;
};
export type Candidate = {
  candidate_track_id: number;
  cause_type: string;
  object_type: string;
  cause_confidence: number;
  evidence_scores: Record<string, number>;
  explanation: string;
};
export type Report = {
  analysis_id: string;
  incident_id: string;
  video: {
    id: string;
    filename: string;
    width: number;
    height: number;
    duration_seconds: number;
    fps: number;
    url: string;
  };
  congestion: {
    detected: boolean;
    start_seconds: number | null;
    end_seconds: number | null;
    severity: number;
    peak_queue_size: number;
    region: string | null;
  };
  cause: {
    type: string;
    confidence: number;
    suspected_track_id: number | null;
    object_type: string | null;
    first_relevant_timestamp: number | null;
    explanation: string;
    evidence_scores: Record<string, number>;
  };
  license_plate: {
    status: string;
    text: string | null;
    confidence: number;
    evidence_asset_id: string | null;
    raw_readings: { raw_text: string; confidence: number; timestamp: number }[];
  };
  fallback_subject_frame: { asset_id: string | null; required: boolean };
  evidence: Asset[];
  alternative_candidates: Candidate[];
  limitations: string[];
  model_versions: Record<string, string>;
  review_status: string;
  timeline: { label: string; timestamp: number }[];
  metrics: {
    timestamp: number;
    queue_size: number;
    median_motion: number;
    occupancy: number;
    region: string;
  }[];
  tracks: Track[];
  stage_timings: Record<string, number>;
};
export const causes = [
  "stalled_vehicle",
  "collision",
  "vehicle_blocking_lane",
  "illegal_parking_or_stopping",
  "pedestrian_obstruction",
  "animal_obstruction",
  "road_debris",
  "roadwork_or_barricade",
  "pothole_or_road_damage",
  "flooded_road",
  "traffic_signal_failure",
  "unknown",
];
export const human = (text: string) => text.replaceAll("_", " ");
export const stamp = (n: number | null | undefined) =>
  n == null
    ? "—"
    : `${Math.floor(n / 60)
        .toString()
        .padStart(2, "0")}:${(n % 60).toFixed(1).padStart(4, "0")}`;
export const confidenceLabel = (n: number) =>
  n >= 0.8 ? "High" : n >= 0.6 ? "Medium" : "Low";
