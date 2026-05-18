# WorkAudit

WorkAudit is a transparent 3D Slicer extension for case-bound segmentation activity auditing.

It is designed for exception review, not minute-perfect payroll timing. The goal is to catch large discrepancies by comparing claimed time to active Slicer segmentation activity with an idle timeout.

## What it records

- Case ID entered in the module
- Worker/vendor ID if entered
- Timestamps of segmentation-related Slicer events
- Segment Editor context such as current segment and active effect
- Estimated active minutes using an idle timeout
- Source volume and segmentation node names

## What it does not record

- Screenshots
- Webcam or microphone data
- Keystrokes outside Slicer
- Browser or desktop activity
- Image voxel data
- Segmentation pixel data

## Local log location

`~/.config/slicer.org/WorkAudit/sessions.jsonl`

## Local development install

For a Slicer developer build, add this module directory to `Modules/AdditionalPaths`:

`<repo>/slicer_extensions/WorkAudit/WorkAudit`

Then restart Slicer and open the `WorkAudit` module.

## Planned distribution

- Public GitHub repository
- Submission to the Slicer Extensions Index so end users can install it from the Extensions Manager
