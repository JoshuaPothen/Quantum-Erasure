# Task brief: build the SAM2 hair-segmentation workflow in ComfyUI via MCP

**Audience:** a Claude Code session running on the user's Windows laptop (RTX 3080, 16GB VRAM), with a ComfyUI MCP server connected and ComfyUI + custom nodes already installed per `next-steps-comfyui-sam2.md` (project doc, read that first for install steps and the full pipeline rationale — this brief only covers building and running the SAM2 workflow itself).

**Don't start this brief unattended if either of those is unconfirmed — check first, ask if not:**
- ComfyUI is running and reachable (default `http://127.0.0.1:8188`)
- The SAM2 and VideoHelperSuite custom nodes are installed

---

## 0. Context in one paragraph

Test 1 (see project doc `test1-trailer-deterministic-masking.md`) built a pure color-threshold pipeline to isolate Pocahontas's hair frame-by-frame and proved, with real footage, that it works when the hair sits against a distinctly different-toned background (shot 26, a closeup) and **fails** when the background is dark and similar in luminance to the hair (shot 5, her cliff dive past a waterfall — the threshold grabs the whole dark rock face along with the hair). This task replaces the threshold step with SAM2 video segmentation for the shots where brightness alone can't disambiguate hair from background, using point-prompts rather than color.

---

## 1. First: discover what you actually have before building anything

MCP servers exposing ComfyUI vary in their tool surface — some expose granular tools (`add_node`, `connect_nodes`, `queue_prompt`), others are a thinner wrapper that takes a full workflow JSON and posts it to ComfyUI's `/prompt` endpoint. **Don't assume which one this is.**

1. List the MCP tools actually available in this session (`ToolSearch` or the equivalent for however tools are surfaced here) and read their schemas before calling anything.
2. If there's a tool to list installed ComfyUI nodes or query `/object_info`, use it to confirm these are present before building the graph:
   - A SAM2 node pack (image/video predictor with point-prompt input) — e.g. `ComfyUI-segment-anything-2`
   - `VHS_LoadImagesFromDirectory` / `VHS_VideoCombine` (VideoHelperSuite) or equivalent
   - Basic mask ops (grow/shrink/blur) — Impact-Pack or core ComfyUI mask nodes are both fine
3. If any required node is missing, **stop and report** which one rather than substituting something that changes the pipeline's behavior silently.
4. If the MCP tool only accepts a raw ComfyUI workflow JSON (the `/prompt`-style API format — a dict of node id → `{class_type, inputs}`), build that JSON directly; the graph described in section 3 below is written node-by-node so it translates either way.

---

## 2. Inputs

Source frames aren't on this machine yet unless Test 1's extraction was already redone locally. Re-derive them from the original trailer file using the exact commands in `test1-trailer-deterministic-masking.md` section 2 (same `ffmpeg -ss <start> -frames:v <n>` pattern), so folder names and frame numbering match the existing convention:

| Shot | Frame range (source trailer) | Start time | Frame count | Why this one |
|---|---|---|---|---|
| `shot26` | 2736–2823 | 54.70s | 88 | Bucket A control — threshold already works here (Test 1). Run SAM2 on it too, specifically to sanity-check SAM2's output quality against a known-good baseline before trusting it on shot5. |
| `shot5` | 861–999 | 17.20s | 139 | Bucket B target — threshold fails on the dark waterfall portion of this shot. This is what SAM2 needs to actually solve. |

Extract both into `frames/shot26/` and `frames/shot5/` (PNG sequence, matching `f_%04d.png` naming) before starting the ComfyUI graph.

---

## 3. The workflow graph to build

Conceptually, in order:

1. **Load image sequence** — point at `frames/<shot>/`, load as a batch/sequence node (VHS loader or equivalent). Get frame count and confirm it matches the table above.
2. **Point-prompt the first frame.** SAM2 needs pixel coordinates on frame 1 as a positive prompt (on the hair), and ideally a negative prompt (on skin or background) to disambiguate — negative prompts matter more on shot5 where hair and background share tone.
   - **You can pick these coordinates yourself**: read frame 1 of the shot as an image (you can view images directly), identify a clear point inside the hair mass and a clear point on skin/background, and supply those pixel coordinates to the SAM2 node's point inputs. Don't guess coordinates blind — look at the actual frame first.
   - For shot5, frame 1 is the bright-sky portion; pick the prompt point there, since that's where the shot starts and propagation carries it forward.
3. **Propagate the mask** through the rest of the shot's frames (SAM2 video predictor node).
4. **Mask cleanup** — grow/shrink and a small blur pass, playing the same role as the morphological closing step in Test 1's `mask_hair_v4.py` (that script is in the project files if you want the exact parameters as a reference point, though SAM2's output shouldn't need nearly as aggressive cleanup as the threshold method did).
5. **Composite** — `hair * alpha + fill * (1 - alpha)`, fill color as a parameter. Build both a white-fill and a black-fill version, matching Test 1's two composite variants.
6. **Reassemble to video** — combine the composited frame sequence back to an mp4 at 50fps (VHS video-combine or equivalent).

Output conventions (match Test 1's folder structure so results are directly comparable):
```
masks/shot26_sam2/          masks/shot5_sam2/
out/shot26_comp_white_sam2/ out/shot5_comp_white_sam2/
out/shot26_comp_black_sam2/ out/shot5_comp_black_sam2/
out/shot26_sam2.mp4         out/shot5_sam2.mp4
```

---

## 4. Validation checkpoints — do not skip these

Test 1's biggest lesson: problems that are invisible at playback speed (a grainy mask, a dissolve artifact) are obvious in a still frame. Apply the same discipline here.

1. **Before propagating**: confirm the frame-1 point-prompt mask actually covers the hair and nothing else. Pull that single mask frame and look at it.
2. **After propagating shot26**: pull masks/composites from early, middle, and late frames (e.g. frame ~5, ~44, ~83) and visually compare against the threshold-based result already in the project files (`masks/shot26_v4/`, if available locally, or the composite videos already delivered to the user). SAM2 should be at least as clean, ideally cleaner (no compression-blockiness holes, since it's not thresholding on brightness).
3. **After propagating shot5**: this is the real test. Pull frames from the sky portion AND the waterfall portion specifically — early frames should look as good as shot26; the waterfall frames are where you find out whether SAM2 actually holds on to the hair separately from the rock face, which is the entire point of this task. If it drifts onto the rock/waterfall partway through, add a corrective point-prompt at the frame where it starts failing and re-propagate from there.
4. Report which frames needed corrective prompts and how many — that's a real data point on how much manual correction this shot needs per pass, useful for estimating effort before scaling past these two test shots.

---

## 5. What's explicitly out of scope for this task

- No generative fill / Wan VACE work yet — that's the next phase after this one, described in `next-steps-comfyui-sam2.md` section 5. Don't start on it even if it seems like a natural next step; get the segmentation solid and validated first.
- No processing of shots beyond `shot26` and `shot5`. Triage of the remaining 73 trailer shots into buckets A/B/C (per the next-steps doc's table) is a separate manual step the user does by eye — this task is just proving the SAM2 mechanics work on the two shots already scoped in Test 1.
- Don't touch the deterministic `mask_hair_v4*.py` scripts or their outputs — they're the baseline this task compares against, not something to modify.

---

## 6. When done

Write a short results note (a few paragraphs is enough) covering:
- Whether the required nodes were present or had to be installed, and which MCP tool surface was actually available (so the next task brief can skip the discovery step)
- How many corrective point-prompts shot5 needed, and roughly where in the shot
- A direct comparison: does the SAM2 mask on shot5's waterfall portion actually separate hair from rock, where the threshold method could not?
- Any node/parameter settings worth keeping as defaults for the next shots

That note is worth adding back to the project (`next-steps-comfyui-sam2.md` or a new dated results doc) so the next session — human or agent — doesn't have to re-derive any of it.
