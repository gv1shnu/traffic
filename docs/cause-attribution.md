# Congestion and attribution

Thresholds and weights live in `config/analysis.json`; every job snapshots them.

Movement is displacement per second normalized by mean bounding-box width/height. A ~1 second trajectory baseline reduces jitter. Long observation gaps reset stationary duration. Camera regions may include `meters_per_pixel` through the API; km/h is only populated with calibration. The browser currently edits polygons/direction, not calibration.

Congestion requires at least four vehicles, low median motion, a high stationary fraction, road occupancy and temporal persistence. Occupancy is the union of vehicle boxes inside a small road raster, so overlaps are not double counted. Queue growth corroborates onset. Clips that already begin congested need twice the persistence window; they usually lack evidence for causal attribution. The highest-severity interval is reported; multi-event reporting is a future extension.

The candidate score combines temporal precedence, downstream position, approximate blockage, stationary duration, follower response, upstream propagation, adjacent-region movement and tracking confidence. A candidate needs observed movement before its stop, and followers that were moving before stopping behind it. Earlier downstream stationary subjects reduce its temporal precedence; this prevents queued followers from becoming the selected origin.

Scores are weighted heuristic evidence strength, **not calibrated causal probabilities**. Missing precedence or follower response caps a candidate below 0.5. Without road regions, scores are capped at 0.59 and cannot pass the default 0.62 selection threshold. Similar top scores return `unknown`. Good object detection alone never establishes cause.

Automatically emitted categories currently cover a suspected stopped vehicle, persistent pedestrian obstruction, and supported animals. Custom debris/barricade labels can use the same stationary-object detector, but the default COCO model does not detect these labels. Collision, transverse blockage, illegal stopping, road defects, flood and signal failure are supported in the schema and review form but need dedicated event/model evidence before automatic attribution. A stationary vehicle does not prove a mechanical fault; explanations say so explicitly.

Test fixtures model flowing traffic, an upstream-growing queue, a pedestrian obstruction, a stationary vehicle with no queue, and a pre-existing queue of unknown origin. These fixtures test algorithm logic, not field accuracy. Evaluate representative fixed-camera Indian video with independently reviewed cause labels before relying on scores operationally.
