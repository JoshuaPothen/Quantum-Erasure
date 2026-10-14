# SAM2 hair segmentation — results, 2026-09-30

Follows `CLAUDE_CODE_SAM2_WORKFLOW_BRIEF.md`. Shots 26 and 5 only, same frame ranges as Test 1.

## Setup that was actually there (skip the discovery step next time)

- **ComfyUI:** Comfy Desktop 0.37.4 at `127.0.0.1:8188`, RTX 3080 Laptop 16 GB.
  - Install: `%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI`
  - Output folder: `%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\output`
- **All nodes were already installed**, and nothing was substituted:
  - kijai `comfyui-segment-anything-2`: `DownloadAndLoadSAM2Model`, `Sam2VideoSegmentationAddPoints`, `Sam2VideoSegmentation`
  - VideoHelperSuite: `VHS_LoadImagesPath` (the current name of `VHS_LoadImagesFromDirectory`) and `VHS_VideoCombine`
  - Core and Impact-Pack: `GrowMask`, `ImpactGaussianBlurMask`, `InvertMask`, `ImageCompositeMasked`, `EmptyImage`
- **SAM2 checkpoint:** `sam2.1_hiera_large` auto-downloaded to `models/sam2/` on the first run.
- **The comfy-mcp MCP tools did not work.** `server_info` and `validate_workflow` both returned a bare error. The likely cause is that the `comfy` CLI they wrap isn't on PATH.
  - Instead, the workflow is built as API-format JSON and posted straight to ComfyUI's `/prompt`, then polled via `/history`. `sam2_workflow.py` does both.
  - Installing comfy-cli would probably bring the MCP tools back, but that's untested.
- **ffmpeg isn't on PATH.** Frames were extracted with `%LOCALAPPDATA%\autolumelive_colab\ffmpeg.exe`, using the same `-ss` commands as Test 1. VHS uses its own bundled copy.

## How to re-run

```
python sam2_workflow.py <shot> --submit            # full run: masks + white/black comps + mp4s
python sam2_workflow.py <shot> --cap 12 --fills white --tag ck --submit   # short checkpoint run
python checks/overlay.py <shot> <tag> checks/x.jpg 5 44 83                # red mask overlays
```

- Prompt points live in `PROMPTS` in `sam2_workflow.py`. Rejected attempts are left there as comments.
- The generated graphs are in `workflows/`. The final ones are `shot26_sam2.json` and `shot5_sam2c2.json`. `shot5_sam2.json` is the run before correction.
- Outputs follow Test 1's layout: `masks/<shot>_sam2/`, `out/<shot>_comp_{white,black}_sam2/`, `out/<shot>_sam2.mp4` (white fill) and `out/<shot>_sam2_black.mp4`.

## shot26 (control) — works, and is cleaner than v4 with one exception

- **Prompts:** frame 1 is mid-dissolve from John Smith, so there are two prompted frames:
  - a light prompt on f_0001: positives only on her visible hair, negatives on John and her face
  - a full prompt on f_0012, the first clean frame
- **Why two:** the kijai node propagates forward only from the earliest prompted frame, so frame 1 has to carry a prompt or it gets no mask.
- **Result:** the mask holds from about f_0005 to f_0083 with no drift. The hair mass is solid, with none of the compression-block holes the threshold had.
- **Compared with `pocahontas_hair_white_v4_clean.mp4`:**
  - v4 leaks onto the eyes and an eyebrow. SAM2 doesn't.
  - **SAM2 misses the thin loose strands crossing her face and chest.** v4 keeps them.
  - Neither extra positive points on the strands nor a separate SAM2 object for them fixed this. As extra points they were ignored; as their own object, the mask flooded her whole face and body. A few-pixel strand is below what SAM2's low-resolution mask decoder can hold.
  - If the strands matter, a hybrid could get them back: the SAM2 mask OR the v4 threshold pixels inside a dilated band around the SAM2 mask. That hasn't been built.
- f_0001–0004 (the dissolve) is still the known exception.

## shot5 (the real test) — SAM2 separates hair from rock; one corrective prompt needed

- **Prompts:**
  - f_0001: light prompt on the small diving figure, which is the incoming side of a dissolve. The large outgoing figure's hair is a negative.
  - f_0010: full prompt on the first clean sky frame.
- **Uncorrected:**
  - The sky portion is clean.
  - On the waterfall (about f_0060 on) it **never leaked onto the rock face**, which is exactly where the threshold failed.
  - But from about f_0075 it **shrank to the scalp cap** and dropped the long hair streaming up behind her head.
  - So the drift runs the opposite way from the threshold's failure: under-segmentation rather than leakage.
- **Corrective prompts:**
  - **One was kept:** f_0100, with 3 positives on the trailing hair and negatives on her face and the rock. The points were picked on a 2.6× contrast-boosted crop, where the hair reads near-black against navy rock.
  - After re-propagation the full hair stream holds from f_0062 to f_0108, with no rock leakage.
  - **One was tried and rejected:** f_0080. At that frame SAM2 read the points as the rock face and flooded the left cliff for f_0075–0090. It also blanked f_0062–0070, because prompted frames act as memory in both directions, not just forward. A bad correction can therefore damage frames *before* it.
- **Net cost:** 1 corrective prompt at about 72% through the shot, plus 1 wasted attempt. The waterfall section needed one careful point placement, checked on a contrast-boosted crop, not a click by eye.
- **Scope problem in the frame range:** f_0109–0139 dissolves into a different shot of a different character (it looks like Nakoma). SAM2 carries the track onto her hair. This is Test 1's missed-cut issue.
  - Either trim shot5 to f_0001–0108 or split it before use.
  - The masks and videos here still cover all 139 frames, so they stay comparable with Test 1.

## Defaults worth keeping

- **Model:** `sam2.1_hiera_large` at bf16. A full propagation on 139 frames at 1080p took about 2 minutes on the 3080.
- **Cleanup:** `GrowMask` expand 1, then `ImpactGaussianBlurMask` kernel 5 / sigma 2.0 (roughly Test 1's 2 px feather).
  - SAM2 output needs no closing or area filter.
  - The 1 px grow leaves a faint sky fringe on very small subjects (shot5's sky portion). Consider expand 0 there.
- **Prompting:**
  - Prompt the first clean frame fully.
  - If frame 1 is inside a dissolve, add a light prompt there too, or those frames get no mask.
  - Put corrective prompts where the target is most visually distinct, and always check the frames *before* the correction as well as after.
- **Compositing:** `ImageCompositeMasked`, with the frames as destination, a 1-frame `EmptyImage` fill as source, and the inverted alpha as mask. This avoids allocating a full-batch fill image, which matters for RAM on 139-frame shots.
