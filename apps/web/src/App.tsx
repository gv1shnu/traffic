import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  CircleHelp,
  GitBranch,
  Layers3,
  Menu,
  Radar,
  ShieldCheck,
  X,
} from "lucide-react";
import { UploadPage } from "./UploadPage";
import { ConfigurePage } from "./ConfigurePage";
import { ProcessingPage } from "./ProcessingPage";
import { ResultsPage } from "./ResultsPage";

export function App() {
  const [nav, setNav] = useState(false);
  return (
    <div className="app-shell">
      <aside className={nav ? "sidebar open" : "sidebar"}>
        <NavLink to="/" className="brand" onClick={() => setNav(false)}>
          <span className="brand-icon">
            <GitBranch size={25} />
          </span>
          <span>
            TRAFFIC<span className="brand-sub">CAUSE INVESTIGATOR</span>
          </span>
        </NavLink>
        <div className="workspace-label">INVESTIGATION WORKSPACE</div>
        <nav>
          <NavLink to="/" end onClick={() => setNav(false)}>
            <Layers3 size={18} /> Investigations <span className="nav-dot" />
          </NavLink>
          <NavLink to="/method" onClick={() => setNav(false)}>
            <BookOpen size={18} /> Method & limitations
          </NavLink>
        </nav>
        <div className="sidebar-note">
          <Radar size={26} />
          <h3>Evidence before conclusions.</h3>
          <p>
            Understand what happened. Trace the queue. Keep a human in the loop.
          </p>
          <span className="small-tag">INDIAN TRAFFIC CONTEXT</span>
        </div>
        <div className="sidebar-bottom">
          <span className="status-dot" /> Local processing{" "}
          <ShieldCheck size={16} />
          <small>Video stays in your workspace</small>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Toggle navigation"
            onClick={() => setNav(!nav)}
          >
            {nav ? <X /> : <Menu />}
          </button>
          <span className="breadcrumb">
            Workspace <span>/</span> Traffic investigation
          </span>
          <div className="topbar-right">
            <span className="quiet-pill">
              <Activity size={13} /> Evidence-led analysis
            </span>
            <NavLink to="/method" aria-label="Help">
              <CircleHelp size={19} />
            </NavLink>
            <span className="avatar">TI</span>
          </div>
        </header>
        <main>
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/configure/:id" element={<ConfigurePage />} />
            <Route path="/jobs/:id" element={<ProcessingPage />} />
            <Route path="/incidents/:id" element={<ResultsPage />} />
            <Route path="/method" element={<Method />} />
            <Route
              path="*"
              element={
                <p>
                  Page not found.{" "}
                  <NavLink to="/">Return to investigations</NavLink>
                </p>
              }
            />
          </Routes>
        </main>
        <footer>
          <ShieldCheck size={15} />
          <p>
            This system produces probabilistic incident assessments for human
            review. It must not be used as the sole basis for enforcement,
            identification, or accusations.
          </p>
          <span>TCI / v0.1</span>
        </footer>
      </div>
    </div>
  );
}
function Method() {
  return (
    <div className="page">
      <div className="eyebrow">THE INVESTIGATION PROCESS</div>
      <h1>
        Measured evidence.
        <br />
        Considered conclusions.
      </h1>
      <p className="lede">A transparent workflow for complex, mixed traffic.</p>
      <div className="method-grid">
        {[
          [
            "01",
            "Detect & track",
            "A YOLO object detector and ByteTrack follow visible road users. Movement is normalized by subject size; it is not km/h without calibration.",
          ],
          [
            "02",
            "Find the queue",
            "Density, slow movement, occupancy and persistence must agree. Sparse stationary traffic is not congestion.",
          ],
          [
            "03",
            "Compare possible causes",
            "Temporal precedence, upstream follower response, queue propagation and tracking quality contribute to an explainable score. Ambiguous evidence returns unknown.",
          ],
          [
            "04",
            "Review the evidence",
            "Plate OCR needs sufficiently clear, agreeing frames. Review corrections are stored separately from the original computed report.",
          ],
        ].map(([n, t, b]) => (
          <article className="card" key={n}>
            <span className="step-number">{n}</span>
            <h2>{t}</h2>
            <p>{b}</p>
          </article>
        ))}
      </div>
      <div className="notice">
        <strong>Know the limits</strong>
        <p>
          Scores are heuristic, not calibrated probabilities. The general
          detector may miss autorickshaws, dense two-wheeler traffic, animals
          and small obstructions. Dedicated collision, road defect and
          signal-state models are not included. Whole-road fallback cannot
          reliably establish direction and therefore returns an unknown cause.
          Evidence redaction can miss undetected subjects; original media is
          retained until deletion or expiry.
        </p>
      </div>
      <a
        className="text-link"
        href="/api/v1/config"
        target="_blank"
        rel="noreferrer"
      >
        View runtime configuration <ArrowUpRight size={16} />
      </a>
    </div>
  );
}
