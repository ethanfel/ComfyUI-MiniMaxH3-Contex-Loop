# Deferred Upscale - Pixel DLSS5 + USDU - EXPERIMENTAL - MiniMax H3

Validated against the **nightly node definitions**. A corresponding 0.6 example is maintained on the release branch.

Setup controls come first, followed by numbered generation columns.

EXPERIMENTAL • PER-SCENE PIXEL UPSCALE

Adapted from Illynir's H3_Pixel_Upscale_Loop.json and the Banodoco discussion:
https://discord.com/channels/1076117621407223829/1537598841199792148/1545925352377815130
Requirements and actual-image sizing:
https://discord.com/channels/1076117621407223829/1537598841199792148/1545926662288449637

Select a saved generated lineage in Checkpoint Manager (no Plan is needed). Choose a new child profile in Upscale Adapter, backend=pixel, save_latent=false. start_clip=1/end_clip=0 processes all selected generated scenes, one at a time; it does not upscale the full movie at once.

Pixel Current Scene decodes the original clean video checkpoint at its RAW frame count. DLSS5 upscales it. Pixel Upscale Conditioning measures those actual images, restores cached or overridden references at the target canvas, and synchronizes remaining eligible video/keyframe conditioning exactly once. Its positive output feeds Basic Guider; its unchanged images output feeds USDU H3. Do not insert another resize between conditioning and refinement. Both dimensions must be multiples of 32: if using a fractional upscaler, align its output before feeding this node.

Picture policy is preserved: match references are rebuilt from their cached RGB masters using the target canvas; max references deliberately retain their capped geometry. The source reference aspect ratio is preserved, so a match reference need not have the identical pixel rectangle as the movie. No fake latent or full-video VAE encode is used merely to determine size. The default motion policy drops reference video but keeps paired audio conditioning.

USDU performs its own tile encoding and low-denoise H3 refinement. The example retains the contributed 2x DLSS settings, Turbo v4 strength 0.75, beta schedule, 3 steps and denoise 0.2; these are experimental starting points, not a quality guarantee. The current upstream anchor_context field is BOOLEAN, not the stale 'H3 Visual Conditioning' string in the contributed file. H3 handling is selected by the H3 model in that fork. Extra memory-cleanup/attention patches from the original graph are not required for wiring; add your preferred memory controls only after a small test.

Save and Loop End both receive the final RAW images. They trim the repeated prefix once and retain each source checkpoint's delivered audio unchanged. Do not wire Pixel Current source_audio into recovered_audio (which expects RAW audio), or into Assemble source_audio (which expects the whole-run source track). The image reader's source_audio output is delivered-only and optional, intended for inspection/preview, not for a RAW-image mux. No audio VAE is required to preserve saved delivered sound.

No Pass-2 AV Prepare, latent Conditioning Sync, or upscaled_latent connection is needed. With backend=pixel, a parent Drift-Control boundary no longer demands an HQ latent; pixel refinement does not freeze/splice latent prefixes. This changes the refinement continuity strategy, not the original generation or its checkpoints. Inspect transitions before accepting a final.

Each completed scene is saved under output/h3_chains/<run>/upscaled/<profile>/. To resume, retain the same selection/profile/settings and set start_clip to the first unfinished scene. A changed source branch or recorded recipe refuses reuse of the prior HQ prefix. recipe_json documents the recipe but does not automatically track every external node edit: choose a new profile when changing upscaler/model/settings to avoid mixing passes. Final assembly is under that child profile's final/ directory. A selected generated branch can stop before ungenerated Plan scenes.

DEPENDENCIES

- DLSS5 image upscaler: https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer
  Its NVIDIA runtime is a separate platform-specific requirement; this file does not install it. Select/configure runtime_dir according to that pack. Any frame-preserving IMAGE upscaler can replace DLSS5 if its output drives both conditioning and refinement.
- H3-aware USDU fork: https://github.com/lisitskyaa/ComfyUI_UltimateSDUpscaleGuider_H3
  Use this H3-capable Guider fork, not just the unrelated standard Ultimate SD Upscale pack.
- MiniMax H3 Ref2VA model, Qwen3-VL encoder, video VAE, and Turbo v4 LoRA. Select the installed filenames. Removing the Turbo LoRA requires retuning the schedule, not merely bypassing it at three steps.

VALIDATION

The H3 adapter, scene reader, target-size reference rebuild, RAW trim, preserved audio, per-scene save, resume and final assembly have CPU integration coverage with synthetic checkpoints and fake VAE/CLIP. The external DLSS5 + USDU GPU refinement and visual quality still need testing on a machine with those packs and models. Start with one short scene before a long run.
