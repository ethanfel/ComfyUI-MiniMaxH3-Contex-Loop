#!/usr/bin/env python3
"""Issue #45: preserve filenames in Assemble's quoted FFmpeg concat list."""

import ast
import ctypes
import ctypes.util
import io
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


def production_writer():
    # Run the actual list-writing block, without importing ComfyUI or a model.
    tree = ast.parse((ROOT / "chain_nodes.py").read_text(encoding="utf-8"))
    assemble = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == "MiniMaxH3ChainAssemble")
    blocks = [node for node in ast.walk(assemble)
              if isinstance(node, ast.With)
              and any(isinstance(item.context_expr, ast.Call)
                      and isinstance(item.context_expr.func, ast.Name)
                      and item.context_expr.func.id == "open"
                      and item.context_expr.args
                      and isinstance(item.context_expr.args[0], ast.Name)
                      and item.context_expr.args[0].id == "concat_path"
                      for item in node.items)]
    assert len(blocks) == 1, "Expected exactly one assembly concat-list writer"
    code = compile(ast.Module(body=blocks, type_ignores=[]),
                   str(ROOT / "chain_nodes.py"), "exec")

    def write(paths, concat_path):
        exec(code, {"segment_paths": paths, "concat_path": str(concat_path)})

    return write


def path_checks(write):
    paths = [
        r"\\mightyjobs\Resources\comfyui_output\h3_chains\demo\segments\clip_0001.mp4",
        r"R:\comfyui_output\h3_chains\demo\segments\clip_0001.mp4",
        r"C:\ComfyUI output\scene one's clip.mp4",
        r"\\mightyjobs\Shared media\café\scene one's clip.mp4",
        r"\\?\UNC\mightyjobs\Resources\comfyui_output\clip_0001.mp4",
        "/tmp/render output/café/scene one's clip.mp4",
        r"/tmp/render output/a\literal\backslash.mp4",
        r"/tmp/render output/a\'quoted' clip.mp4",
        "/tmp/render output/ #clip [one]; &two.mp4 ",
    ]
    # The mock keeps the stream open after the production with-block exits.
    stream = io.StringIO()
    with patch("builtins.open") as opened:
        opened.return_value.__enter__.return_value = stream
        write(paths, "unused.concat.txt")
    lines = stream.getvalue().splitlines()
    assert len(lines) == len(paths)
    for path, line in zip(paths, lines):
        assert shlex.split(line) == ["file", path], (path, line)
        if "'" not in path:
            assert line == "file '%s'" % path
    print("H3 concat paths: UNC, mapped drives, extended UNC, POSIX, spaces, "
          "Unicode and apostrophes preserved")

    # Cross-check with FFmpeg's own tokenizer when its shared library exists.
    library = ctypes.util.find_library("avutil")
    if not library:
        print("SKIP native FFmpeg tokenizer: shared libavutil unavailable")
        return
    lib = ctypes.CDLL(library)
    lib.av_get_token.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.c_char_p]
    lib.av_get_token.restype = ctypes.c_void_p
    lib.av_free.argtypes = [ctypes.c_void_p]
    lib.av_free.restype = None
    for path, line in zip(paths, lines):
        cursor = ctypes.c_char_p(line.removeprefix("file ").encode("utf-8"))
        token = lib.av_get_token(ctypes.byref(cursor), b" \t\r\n")
        assert token, "FFmpeg could not allocate a parsed token"
        try:
            assert ctypes.string_at(token).decode("utf-8") == path
        finally:
            lib.av_free(token)
    print("H3 concat paths: FFmpeg's native av_get_token preserves all 9 paths")


def media_checks(write):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        print("SKIP media concat: ffmpeg/ffprobe unavailable")
        return

    def run(command):
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout

    # Only these throwaway CPU-generated clips are touched, never project data.
    with tempfile.TemporaryDirectory(prefix="h3-concat-paths-") as temporary:
        root = pathlib.Path(temporary)
        first = root / "scene one's café.mp4"
        second = root / (r"scene\two's clip.mp4" if os.name != "nt"
                         else "scene two's clip.mp4")
        run([ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i",
             "color=c=red:s=16x16:r=24", "-frames:v", "3", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", str(first)])
        shutil.copyfile(first, second)
        final_dir = root / "final output"
        final_dir.mkdir()
        concat = final_dir / ".concat.txt"
        output = final_dir / "joined.mp4"
        write([str(first), str(second)], concat)
        run([ffmpeg, "-v", "error", "-nostdin", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-map", "0:v:0", "-c", "copy", str(output)])
        info = json.loads(run([ffprobe, "-v", "error", "-select_streams", "v:0",
                               "-count_frames", "-show_entries",
                               "stream=nb_read_frames", "-of", "json", str(output)]))
        assert int(info["streams"][0]["nb_read_frames"]) == 6
        assert first.is_file() and second.is_file()
    print("H3 concat media: real H.264 stream-copy assembles all 6 frames "
          "with special-character filenames")


if __name__ == "__main__":
    writer = production_writer()
    path_checks(writer)
    media_checks(writer)
