# Quantum Erasure — process documentation

The project erases everything from *Pocahontas* (1995) except Pocahontas's hair. These documents record each phase as it happens:
- what was done, and the exact commands and scripts used
- what was checked, with images
- what failed and why
- which decisions were made

The aim is that the next session, human or agent, never has to re-derive anything.

Images live in `docs/img/`, named with the phase number as a prefix.

## Overview

**[PROCESS_OVERVIEW.md](PROCESS_OVERVIEW.md)**: a visual walkthrough from Test 1 to the X02 result (segment 224, hair only), with layered technical detail. Start here.

## Phases

| # | Doc | Status |
|---|---|---|
| — | Test 1: threshold masking on the trailer (`../../Test 1/Quantum Erasure/TEST1_README.md`) | done |
| — | SAM2 on trailer shots 26 + 5 (`../SAM2_RESULTS_2026-09-30.md`) | done |
| 00 | [Source selection](00_source_selection.md): BDrip `.mkv` chosen over YIFY | done |
| 01 | [Shot detection](01_shot_detection.md): full-film segment list `shots/shots_v1.csv` (1,276 shots, 31 flagged transitions); frame-identity rules | done |
| X01 | [SAM2 on the film's longest shot](X01_sam2_long_take.md): chunked propagation, drift fix, seam checks | done |
| X02 | [SAM3 main + SAM2 fallback](X02_sam3_main_sam2_fallback.md) on daylight seg 224 | done |
| 02 | Shot triage: superseded by 03's probe triage + identity classifier | superseded |
| 03 | [**Full-film run**](../film/README.md): SAM3 instances + CLIP identity classifier (Pocahontas only) + SAM2 fallback, one folder per segment in `film/segments/`, final film in `film/final/` | done 2026-10-26: full film + her cut assembled |

## Conventions

- **Master source:** `Pocahontas (1995) BDrip 1080p ENG-ITA MultiSub x264 blyuray -Shiv@.mkv`, 1920×1080, 23.976 fps.
- **Frame numbers** are 0-based **film frame indices**, `round(ffmpeg pts × 24000/1001)`, unless a doc says otherwise.
  - Read frames only through `tools/frameio.py`. **Don't** use OpenCV frame counters or positions, plain `ffmpeg -ss … -frames:v` without `-fps_mode passthrough`, or a continuous decode through `shots/damaged_spans.csv`.
  - [01, step 6](01_shot_detection.md) explains why. `f_%04d.png` files inside a shot folder are 1-based within that shot, matching Test 1's convention.
- **Folders** follow Test 1's layout: `shots/`, `frames/<shot>/`, `masks/<shot>_<method>/`, `out/<shot>_comp_<fill>_<method>/`.
- **Tools** live in `tools/`, and ad-hoc inspection scripts in `checks/`.
