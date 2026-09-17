# Demo walkthrough

1. Start API, Redis, PostgreSQL, worker and web app. Download model weights once.
2. Open the workspace and upload a real fixed-camera MP4, MOV, MKV or AVI you are permitted to analyze. For an infrastructure smoke test only, generate synthetic clips with `python scripts/generate_fixtures.py`.
3. Name a camera and click three or more corners around each convex lane/road region. Set its traffic direction and finish the polygon. Save and investigate. Empty configuration clearly uses the lower-reliability whole-road fallback.
4. Watch measured upload and worker progress. No predicted completion time is fabricated. Stages that are not applicable are skipped. Leave and reopen the task from the recent-investigations list if desired.
5. Review the report, toggle track boxes, seek via timeline markers and frame cards, inspect alternative candidates and individual evidence factors, and download the evidence clip or JSON report.
6. For unreadable plates, show the null result and best frame. For unknown causes, show why no subject was selected. Never narrate a synthetic fixture as a real detection success.
7. Confirm, reject or correct the finding. Add notes and reopen review history to show persistence. The computed result stays intact and corrections appear separately in exports.
8. Delete the test investigation from the results page if no longer needed.

The synthetic shapes are deliberately not trained to resemble true vehicles: generic YOLO may detect nothing in them. They are useful for upload/worker/report and deterministic trajectory tests. Actual accuracy must be demonstrated on real labelled video separately. Public UVH-26 stills are suitable for detection evaluation, not incident-causality evaluation.
