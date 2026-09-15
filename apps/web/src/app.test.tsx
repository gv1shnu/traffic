import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, afterEach } from "vitest";
import { api, uploadVideo, validateFile } from "./api";
import { PlateResult, ReviewForm } from "./ResultsPage";
import { JobStatus } from "./ProcessingPage";
import { confidenceLabel, type Job, type Report } from "./types";

const report: Report = {
  analysis_id: "a",
  incident_id: "i",
  video: {
    id: "v",
    filename: "road.mp4",
    width: 720,
    height: 720,
    duration_seconds: 18,
    fps: 10,
    url: "/media",
  },
  congestion: {
    detected: true,
    start_seconds: 8,
    end_seconds: 17,
    severity: 0.8,
    peak_queue_size: 5,
    region: "lane_1",
  },
  cause: {
    type: "unknown",
    confidence: 0,
    suspected_track_id: null,
    object_type: null,
    first_relevant_timestamp: null,
    explanation: "No reliable cause could be identified.",
    evidence_scores: {},
  },
  license_plate: {
    status: "unreadable",
    text: null,
    confidence: 0,
    evidence_asset_id: null,
    raw_readings: [],
  },
  fallback_subject_frame: { asset_id: null, required: true },
  evidence: [],
  alternative_candidates: [],
  limitations: [],
  model_versions: {},
  review_status: "pending",
  timeline: [],
  metrics: [],
  tracks: [
    {
      track_id: 1,
      object_type: "car",
      observations: [],
      tracking_confidence: 0.9,
    },
  ],
  stage_timings: {},
};
afterEach(() => vi.restoreAllMocks());
describe("upload validation", () => {
  it("rejects unsupported extensions, empty and oversized files", () => {
    expect(validateFile(new File(["hello"], "file.exe"))).toContain(
      "Choose an MP4",
    );
    expect(validateFile(new File([], "file.mp4"))).toContain("empty");
    expect(validateFile(new File(["xx"], "file.mp4"), 0.000001)).toContain(
      "smaller",
    );
    expect(validateFile(new File(["hello"], "file.MOV"))).toBeNull();
  });
  it("reports measured upload progress", async () => {
    const callback = vi.fn();
    class MockXHR {
      status = 201;
      responseText = '{"id":"video"}';
      upload: {
        onprogress?: (e: {
          lengthComputable: boolean;
          loaded: number;
          total: number;
        }) => void;
      } = {};
      onload?: () => void;
      onerror?: () => void;
      open() {}
      send() {
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: 5,
          total: 10,
        });
        this.onload?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", MockXHR);
    expect(
      await uploadVideo(new File(["hello"], "road.mp4"), callback),
    ).toEqual({ id: "video" });
    expect(callback).toHaveBeenCalledWith(50);
    vi.unstubAllGlobals();
  });
});
it("renders actual job progress", () => {
  const job = {
    stage: "detect_and_track",
    status: "processing",
    progress: 21,
  } as Job;
  render(<JobStatus job={job} />);
  expect(screen.getByText("21%")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "21");
});
it("renders recognized plate with supporting confidence", () => {
  render(
    <PlateResult
      report={{
        ...report,
        license_plate: {
          ...report.license_plate,
          status: "recognized",
          text: "KA01AB1234",
          confidence: 0.92,
        },
      }}
    />,
  );
  expect(screen.getByText("KA01AB1234")).toBeInTheDocument();
  expect(screen.getByText("92% OCR consensus confidence")).toBeInTheDocument();
});
it("renders unreadable plate and evidence fallback", () => {
  render(<PlateResult report={report} />);
  expect(screen.getByText("No reliable plate detected")).toBeInTheDocument();
  expect(screen.queryByText("KA01AB1234")).not.toBeInTheDocument();
});
it("supports unknown and manual corrections without overwriting evidence", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(
      async (_url, options) =>
        new Response(
          JSON.stringify(
            options?.method === "PATCH" ? { review_status: "corrected" } : [],
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ReviewForm report={report} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("Correct the assessment"));
  expect(screen.getByLabelText("Cause category")).toHaveValue("unknown");
  fireEvent.change(screen.getByLabelText("Cause category"), {
    target: { value: "stalled_vehicle" },
  });
  fireEvent.change(screen.getByLabelText("Selected subject"), {
    target: { value: "1" },
  });
  fireEvent.change(screen.getByLabelText("Corrected plate"), {
    target: { value: "KA01AB1234" },
  });
  fireEvent.click(screen.getByText("Save correction"));
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("Review saved"),
  );
  const call = fetchMock.mock.calls.find(
    ([, init]) => init?.method === "PATCH",
  );
  expect(JSON.parse(call?.[1]?.body as string)).toMatchObject({
    action: "corrected",
    corrected_track: 1,
    corrected_cause: "stalled_vehicle",
    corrected_plate: "KA01AB1234",
  });
  expect(report.cause.type).toBe("unknown");
});
it("surfaces structured API errors", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: { message: "Video invalid" } }), {
      status: 422,
    }),
  );
  await expect(api("/videos")).rejects.toThrow("Video invalid");
});
it("uses specified confidence boundaries", () => {
  expect(confidenceLabel(0.8)).toBe("High");
  expect(confidenceLabel(0.6)).toBe("Medium");
  expect(confidenceLabel(0.599)).toBe("Low");
});
