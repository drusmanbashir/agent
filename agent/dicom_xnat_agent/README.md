# DICOM XNAT Agent

CLI to prepare a root DICOM folder tree for XNAT upload using existing `dicom_utils` functions.

## What it does
- Deletes unwanted folders/files recursively (e.g. `SECTRA`, `README`, `Viewer`, `DICOMDIR`)
- For each direct case subfolder under the root, rewrites DICOM `PatientID` to the subfolder name
- Runs PatientID rewrite in multiprocessing mode
- Prints `ready to upload on xnat` when complete
- Converts DICOM scans in an XNAT project to NIFTI resources (multiprocess by default)
- Uses your existing `xnat` repo conversion methods (`dcm2nii_parallel` / `Proj.dcm2nii`)
- Uploads local resource files (e.g. `LABELMAP`) by matching filename to project/subject/scan

## CLI
```bash
dicom-xnat-agent prepare /s/insync/datasets/bones --workers 8
```

Single process mode:
```bash
dicom-xnat-agent prepare /s/insync/datasets/bones --no-multiprocess
```

Interactive dashboard (command line UI):
```bash
dicom-xnat-agent menu
```

Alias:
```bash
dicom-xnat-agent dashboard
```

## DICOM -> NIFTI in XNAT
This command uses your existing `/home/ub/code/xnat` repository code path and your `XNAT_CONFIG_PATH` config.

Interactive (asks for tags and naming options):
```bash
dicom-xnat-agent dcm2nifti BONES
```

Non-interactive:
```bash
dicom-xnat-agent dcm2nifti BONES \
  --workers 8 \
  --no-ask
```

Useful options:
- `--no-multiprocess` to disable multiprocessing
- `--no-date` to exclude study date from output filename
- `--no-desc` to exclude `SeriesDescription` from output filename
- `--subject <id>` repeatable; process only selected subject IDs
- `--overwrite` to replace existing target resource label

## Upload Resource By Filename
Uploads files from a local folder to matching XNAT scans using parsed filename tags:
- expected filename tags: `<project>_<subject>[_<date>][_<desc>].ext`
- parser source: `utilz.helpers.info_from_filename` (fallback to `utilz.stringz.info_from_filename`)
- checks project, subject, and scan existence before upload
- logs all failures to an errors TSV file

Example:
```bash
dicom-xnat-agent upload-resource BONES /s/path/to/resources LABELMAP --no-ask
```
