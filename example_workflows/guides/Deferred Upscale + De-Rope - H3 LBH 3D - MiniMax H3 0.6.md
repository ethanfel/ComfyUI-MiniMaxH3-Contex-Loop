# Deferred Upscale + De-Rope - H3 LBH 3D - MiniMax H3 0.6

Built for the **0.6 branch**, not nightly.

Setup controls come first, followed by numbered generation columns.

CHAIN-AWARE H3 UPSCALE + DE-ROPE

1. Select the generated branch tip in Checkpoint Manager. Partial generated branches are valid.
2. Keep a unique profile name. Each recovered HQ scene is saved before the loop advances.
3. H3 Jerk Oracle finds overloaded motion on the saved clean source latent. Chain De-Rope Guard prevents it from retiming the disposable continuation prefix and the last 17 frames of every non-final selected scene. Its expand_to_end output must stay connected to H3 Time Smear.
4. Time Smear expands decoded source frames; VAE Encode returns them to clean H3 latent space; LBH 3D performs the spatial upscale. Chain De-Rope Continuity then splices the previous HQ Drift-Control tail at target resolution.
5. Chain De-Rope Freeze Mask must stay connected to H3 V2V Init with time_varying ON. The stretched source audio is seeded at strength 0.5 so dialogue timing does not drag the mouth back to natural speed.
6. Exact Recover and Audio Recover return to the original RAW clock. The bundled safe audio default keeps the original performance; change Audio Recover only for an intentional pass-2 foley test. Recovered AV is re-encoded for Drift-Control continuity and optional latent saving.

No Plan, Source Timeline, source media, or manual references are required. Automatic reference-cache restore remains active and excludes motion-video refs by default because the source latent already contains the motion. Functional nodes intentionally use their original registered names.

---

REQUIRES
https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler
https://github.com/matlowai/ComfyUI-MAINodes

This uses MAINodes' stable decoded pixel-smear path, not experimental latent temporal insertion. The longer smeared IMAGE batch lives on CPU, then VAE Encode and LBH operate scene by scene; effective time can still reach roughly 2-3x on high-motion clips. If RAM or generation time is excessive, process a smaller start/end scene range or use a less aggressive oracle preset before lowering target resolution.

Defaults: balanced oracle q=0.75 / d_max=4 / ramp ON / bridge=8; 1.5 MP LBH 3D; 20-step simple schedule injected from 0.50; res_multistep sampler; audio init follows the original performance at 0.5; Audio Recover delivers the original performance. Community testing consistently places d_max=4 at the useful H3 threshold and recommends doing spatial upscale and de-rope in this same regeneration pass.

H3 Conditioning Sync now permits the longer target clock while resizing only spatial reference/keyframe latents. Motion refs remain excluded by default. The pass-2 Comfy Kitchen override is bypassed because large H3 sequences can exceed Sage prequantized int32 strides. save_latent remains OFF; the compact HQ continuation tail is retained automatically when the next scene needs it.
