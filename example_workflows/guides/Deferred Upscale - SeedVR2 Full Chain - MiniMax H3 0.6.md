# Deferred Upscale - SeedVR2 Full Chain - MiniMax H3 0.6

Built for the **0.6 branch**, not nightly.

Setup controls come first, followed by numbered generation columns.

WHOLE-CHAIN SEEDVR2 FINISH

1. In Checkpoint Manager select the final scene of a COMPLETE branch.
2. Use the original H3 VIDEO VAE. Do not select minimax_h3_audio_vae: it has 32 latent channels and cannot decode the 24-channel video latent.
3. Keep decode_buffer=disk-backed. MiniMax's temporal VAE writes the active scene to a temporary mmap; only boundary frames stay in ordinary RAM.
4. The adapter trims saved context, resolves the Plan's boundary blends, embeds the saved final audio policy, and caches one continuous lossless movie under output/h3_chains/<run>/upscaled/seedvr2/source/.
5. SeedVR2 Direct reads that movie in chunk_size batches. chunk_size=21 and overlap=2 are conservative defaults; its batching is independent of H3 scene boundaries.
6. The ethanfel SeedVR2 fork preserves input audio in its returned VIDEO, so it connects directly to core Save Video.

No Plan, Source Timeline, source media, per-scene upscale loop, IMAGE batch, or manual intermediate path is required. Legacy source-audio runs without a saved Source Timeline are the only case that may need source_audio on the adapter.

Required SeedVR2 fork: https://github.com/ethanfel/ComfyUI-SeedVR2_VideoUpscaler
