# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import ast
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

import av
from app_conf import FFMPEG_NUM_THREADS
from dataclasses_json import dataclass_json

TRANSCODE_VERSION = 1


@dataclass_json
@dataclass
class VideoMetadata:
    duration_sec: Optional[float]
    video_duration_sec: Optional[float]
    container_duration_sec: Optional[float]
    fps: Optional[float]
    width: Optional[int]
    height: Optional[int]
    num_video_frames: int
    num_video_streams: int
    video_start_time: float


def transcode(
    in_path: str,
    out_path: str,
    in_metadata: Optional[VideoMetadata],
    seek_t: float,
    duration_time_sec: float,
):
    codec = os.environ.get("VIDEO_ENCODE_CODEC", "libx264")
    crf = int(os.environ.get("VIDEO_ENCODE_CRF", "23"))
    # 移除fps环境变量，使用原视频帧率
    # fps = int(os.environ.get("VIDEO_ENCODE_FPS", "24"))
    # 移除分辨率限制环境变量，使用原视频分辨率
    # max_w = int(os.environ.get("VIDEO_ENCODE_MAX_WIDTH", "1280"))
    # max_h = int(os.environ.get("VIDEO_ENCODE_MAX_HEIGHT", "720"))
    verbose = ast.literal_eval(os.environ.get("VIDEO_ENCODE_VERBOSE", "False"))

    normalize_video(
        in_path=in_path,
        out_path=out_path,
        max_w=None,  # 不限制宽度
        max_h=None,  # 不限制高度
        seek_t=seek_t,
        max_time=duration_time_sec,
        in_metadata=in_metadata,
        codec=codec,
        crf=crf,
        fps=None,  # 使用原视频帧率
        verbose=verbose,
    )


def get_video_metadata(path: str) -> VideoMetadata:
    with av.open(path) as cont:
        num_video_streams = len(cont.streams.video)
        width, height, fps = None, None, None
        video_duration_sec = 0
        container_duration_sec = float((cont.duration or 0) / av.time_base)
        video_start_time = 0.0
        rotation_deg = 0
        num_video_frames = 0
        if num_video_streams > 0:
            video_stream = cont.streams.video[0]
            assert video_stream.time_base is not None

            # 修复 side_data 兼容性问题
            try:
                # 尝试新版本的访问方式
                if hasattr(video_stream, 'side_data'):
                    rotation_deg = video_stream.side_data.get("DISPLAYMATRIX", 0)
                else:
                    # 兼容旧版本或不同的访问方式
                    rotation_deg = 0
            except (AttributeError, TypeError):
                rotation_deg = 0
            
            num_video_frames = video_stream.frames
            video_start_time = float(video_stream.start_time * video_stream.time_base)
            width, height = video_stream.width, video_stream.height
            fps = float(video_stream.guessed_rate)
            fps_avg = video_stream.average_rate
            if video_stream.duration is not None:
                video_duration_sec = float(
                    video_stream.duration * video_stream.time_base
                )
            if fps is None:
                fps = float(fps_avg)

            if not math.isnan(rotation_deg) and int(rotation_deg) in (
                90,
                -90,
                270,
                -270,
            ):
                width, height = height, width

        duration_sec = max(container_duration_sec, video_duration_sec)

        return VideoMetadata(
            duration_sec=duration_sec,
            container_duration_sec=container_duration_sec,
            video_duration_sec=video_duration_sec,
            video_start_time=video_start_time,
            fps=fps,
            width=width,
            height=height,
            num_video_streams=num_video_streams,
            num_video_frames=num_video_frames,
        )


def normalize_video(
    in_path: str,
    out_path: str,
    max_w: Optional[int],  # 改为可选参数
    max_h: Optional[int],  # 改为可选参数
    seek_t: float,
    max_time: float,
    in_metadata: Optional[VideoMetadata],
    codec: str = "libx264",
    crf: int = 23,
    fps: Optional[float] = None,  # 改为可选的浮点数
    verbose: bool = False,
):
    if in_metadata is None:
        in_metadata = get_video_metadata(in_path)

    assert in_metadata.num_video_streams > 0, "no video stream present"

    w, h = in_metadata.width, in_metadata.height
    assert w is not None, "width not available"
    assert h is not None, "height not available"

    # 使用原视频分辨率，不进行缩放限制
    # 只确保尺寸为偶数（H.264编码要求）
    if w % 2 != 0:
        w += 1
    if h % 2 != 0:
        h += 1

    # 确保时长不会被错误截断
    actual_duration = min(max_time, in_metadata.duration_sec or max_time)
    
    # ffmpeg = shutil.which("ffmpeg")
    ffmpeg = "/usr/bin/ffmpeg"
    
    # 使用原视频帧率
    if fps is None and in_metadata and in_metadata.fps:
        fps = float(in_metadata.fps)  # 保持浮点精度
    elif fps is None:
        fps = 24.0  # 仅作为最后的备用值
    
    # 确保FFmpeg命令使用精确的帧率
    vf_filter = f"fps={fps:.3f},scale={w}:{h},setsar=1:1"
    
    cmd = [
        ffmpeg,
        "-threads", f"{FFMPEG_NUM_THREADS}",
        "-ss", f"{seek_t:.3f}",  # 使用更精确的时间戳
        "-t", f"{actual_duration:.3f}",  # 使用实际时长
        "-i", in_path,
        "-c:v", codec,
        "-profile:v", "baseline",
        "-level", "3.0",
        "-crf", f"{crf}",
        "-preset", "medium",
        "-g", "48",  # 关键帧间隔
        "-keyint_min", "24",
        "-vf", f"fps={fps},scale={w}:{h},setsar=1:1",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero",  # 避免负时间戳
        "-fflags", "+genpts",  # 生成时间戳
        "-threads", f"{FFMPEG_NUM_THREADS}",
        "-y",
        out_path,
    ]
    
    if verbose:
        print(f"FFmpeg command: {' '.join(cmd)}")
        print(f"Input duration: {in_metadata.duration_sec}, Output duration: {actual_duration}")
        print(f"Using original resolution: {w}x{h}, fps: {fps}")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if not verbose else None,
            stderr=subprocess.PIPE if not verbose else None,
            check=True,
            timeout=300
        )
        
        # 验证输出文件
        if os.path.exists(out_path):
            out_metadata = get_video_metadata(out_path)
            if verbose:
                print(f"Output file duration: {out_metadata.duration_sec}")
                print(f"Output file frames: {out_metadata.num_video_frames}")
                print(f"Output file resolution: {out_metadata.width}x{out_metadata.height}")
        
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg failed: {e}")
        if e.stderr:
            print(f"Error: {e.stderr.decode()}")
        raise
    except subprocess.TimeoutExpired:
        print("FFmpeg timed out")
        raise
