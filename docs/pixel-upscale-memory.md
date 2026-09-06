# Pixel upscale memory

Upscale Loop End uses a lazy graph boundary. An internal Handoff node consumes
the saved scene's RAW HQ frames and optional latent, produces the existing
context/state outputs, and completes before Advance starts the next scene.
Waiting recursive nodes therefore do not pin earlier scenes' full RGB inputs
(or all the outputs of the Current Scene node through its state connection).
ComfyUI can evict those ordinary output-cache entries when needed. Existing
workflow wiring, trimming, audio, profiles, and final output sockets are unchanged.

The saver reads only delivered audio from the source checkpoint after verifying
its checksum; it no longer loads all source video/audio latents just to save audio.

This does not disable ComfyUI's output/model caches, discard intentional context
tails, or reduce the number of frames sampled by an external upscaler. A connected
optional HQ latent retains its existing carry behavior. USDU's H3 tiling is
spatial, so one tile still contains the full scene duration. Pair this with the
USDU fork's buffer cleanup and preallocated image assembly fix.

At 277 frames, 1920 x 1088, RGB float32, one full pixel buffer is about 6.47 GiB.
The improvements remove redundant storage and scheduler retention; they do not
promise a particular total RAM/VRAM figure for a model or workflow.

The CPU pixel integration test executes the actual ComfyUI recursive scheduler
with both disabled caching and RAM-pressure caching. Weak references verify
that earlier frame tensors can be freed before the next scene starts. It also
checks saved output, context, and unchanged source files. Run with:

```sh
COMFYUI_PATH=/path/to/ComfyUI python tests/_upscale_pixel_unit_test.py
COMFYUI_PATH=/path/to/ComfyUI python tests/_upscale_chain_unit_test.py
```
