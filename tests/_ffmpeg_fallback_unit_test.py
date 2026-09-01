#!/usr/bin/env python3
"""Regress unusable ffmpeg detection and Windows loader diagnostics."""

import importlib.util
import pathlib
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_ffmpeg_fallback_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.output_directory = str(ROOT)
folder_paths.get_output_directory = lambda: folder_paths.output_directory
folder_paths.get_temp_directory = lambda: folder_paths.output_directory
folder_paths.get_input_directory = lambda: folder_paths.output_directory
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def main():
    executable = r"C:\ffmpeg\bin\ffmpeg.exe"
    calls = []
    original_which = chain.shutil.which
    original_run = chain.subprocess.run

    def failed_process(command, **_kwargs):
        calls.append(command)
        return types.SimpleNamespace(
            returncode=3221225785, stdout="", stderr="")

    try:
        chain.shutil.which = lambda name: (
            executable if name == "ffmpeg" else original_which(name))
        chain.subprocess.run = failed_process
        chain._FFMPEG_PROBE_CACHE.clear()

        assert chain._usable_ffmpeg() is None
        assert calls == [[executable, "-version"]]
        assert chain._usable_ffmpeg() is None
        assert len(calls) == 1, "an unusable executable should be probed once"

        with tempfile.TemporaryDirectory() as tempdir:
            folder_paths.output_directory = tempdir
            source = pathlib.Path(
                tempdir, "h3_chains", "fallback", "segments", "clip.mp4")
            source.parent.mkdir(parents=True)
            source.write_bytes(b"video")
            audio = {
                "waveform": chain.torch.zeros((1, 2, 1000)),
                "sample_rate": 24000,
            }
            mux_calls = []
            original_mux = chain._pyav_mux_audio

            def fake_mux(source_path, _audio, output_path, bitrate, frames):
                mux_calls.append((source_path, bitrate, frames))
                pathlib.Path(output_path).write_bytes(b"review with audio")

            chain._pyav_mux_audio = fake_mux
            try:
                review, has_audio, warning = chain._review_video(
                    {"run_name": "fallback"},
                    {
                        "index": 1,
                        "segment": chain._relative_output_path(str(source)),
                        "segment_sha256": "video-hash",
                        "delivered_frames": 1,
                    },
                    audio)
            finally:
                chain._pyav_mux_audio = original_mux
            review_path = pathlib.Path(
                tempdir, review["subfolder"], review["filename"])
            assert has_audio and not warning and review_path.is_file()
            assert mux_calls == [(str(source), 192, 1)]

        try:
            chain._run_ffmpeg([executable, "-version"])
        except RuntimeError as exc:
            message = str(exc)
            assert "3221225785 / 0xC0000139" in message
            assert "DLL entry point was not found" in message
        else:
            raise AssertionError("Windows loader failure was accepted")

        chain._FFMPEG_PROBE_CACHE.clear()
        chain.subprocess.run = lambda *_args, **_kwargs: types.SimpleNamespace(
            returncode=0, stdout="ffmpeg version test", stderr="")
        assert chain._usable_ffmpeg() == executable
        assert chain._usable_ffmpeg() == executable
    finally:
        chain.shutil.which = original_which
        chain.subprocess.run = original_run
        chain._FFMPEG_PROBE_CACHE.clear()

    print("H3 ffmpeg fallback: unusable Windows binary selects PyAV with "
          "clear diagnostics")


if __name__ == "__main__":
    main()
