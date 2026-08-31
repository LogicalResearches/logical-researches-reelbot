from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .ai import GeminiClient
from .config import AppConfig
from .models import Article, ScriptPayload, VisualAsset
from .util import run


class RenderError(RuntimeError):
    pass


def _font(path: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidate = Path(path)
    if not candidate.exists() and bold:
        candidate = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if not candidate.exists():
        candidate = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    try:
        return ImageFont.truetype(str(candidate), size=size)
    except OSError:
        return ImageFont.load_default()


def _hex(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid color: {value}")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4)) + (alpha,)


def _wrapped_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        width = draw.textbbox((0, 0), trial, font=font)[2]
        if current and width > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _draw_multiline_center(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    center_y: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    width: int,
    spacing: int,
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
) -> None:
    heights = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)[3] for line in lines]
    total_height = sum(heights) + spacing * max(0, len(lines) - 1)
    y = center_y - total_height // 2
    for line, height in zip(lines, heights):
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        y += height + spacing


def _background(asset: VisualAsset, width: int, height: int) -> Image.Image:
    with Image.open(asset.path) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        background = ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS)
    background = ImageEnhance.Color(background).enhance(0.78)
    background = ImageEnhance.Contrast(background).enhance(1.05)
    # A softly blurred copy fills the whole frame; a sharper window retains useful detail.
    blurred = background.filter(ImageFilter.GaussianBlur(radius=5)).convert("RGBA")
    sharp = background.convert("RGBA")
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((44, 165, width - 44, height - 250), radius=42, fill=155)
    blurred.alpha_composite(Image.composite(sharp, Image.new("RGBA", sharp.size), mask))
    return blurred


def render_slide(
    *,
    asset: VisualAsset,
    script: ScriptPayload,
    article: Article,
    segment_index: int,
    config: AppConfig,
    output: Path,
) -> None:
    style = config.style
    width, height = int(style["width"]), int(style["height"])
    image = _background(asset, width, height)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    # Legibility gradient and safe zones for Instagram UI.
    for y in range(height):
        top_strength = max(0.0, 1 - y / 660)
        bottom_strength = max(0.0, (y - 1050) / 870)
        alpha = int(72 + 120 * max(top_strength, bottom_strength))
        draw.line((0, y, width, y), fill=(4, 12, 24, min(225, alpha)))
    draw.rounded_rectangle((42, 155, width - 42, height - 250), radius=42, outline=(255, 255, 255, 38), width=2)

    regular = _font(style["font_regular"], 42)
    small = _font(style["font_regular"], 30)
    bold = _font(style["font_bold"], 80, bold=True)
    brand = _font(style["font_bold"], 35, bold=True)
    accent = _hex(style["accent"])
    primary = _hex(style["primary"])
    accent_secondary = _hex(style["accent_secondary"])

    draw.rounded_rectangle((60, 76, 530, 138), radius=28, fill=(5, 17, 32, 210), outline=accent, width=2)
    draw.text((88, 91), f"@{config.page['handle']}", font=brand, fill=primary)
    draw.text((width - 245, 93), "SOURCE-BASED", font=small, fill=accent)

    # Progress indicator.
    bar_y = 174
    gap = 14
    bar_width = (width - 120 - gap * (len(script.segments) - 1)) // len(script.segments)
    for index in range(len(script.segments)):
        x = 60 + index * (bar_width + gap)
        color = accent if index <= segment_index else (255, 255, 255, 45)
        draw.rounded_rectangle((x, bar_y, x + bar_width, bar_y + 9), radius=4, fill=color)

    segment = script.segments[segment_index]
    label = "THE DISCOVERY" if segment_index == 0 else f"PART {segment_index + 1} OF {len(script.segments)}"
    label_bbox = draw.textbbox((0, 0), label, font=small)
    label_width = label_bbox[2] - label_bbox[0]
    draw.rounded_rectangle(
        ((width - label_width) // 2 - 26, 420, (width + label_width) // 2 + 26, 478),
        radius=24,
        fill=accent_secondary[:-1] + (225,),
    )
    draw.text(((width - label_width) // 2, 431), label, font=small, fill=(9, 20, 33, 255))

    headline = script.cover_text if segment_index == 0 else segment.onscreen_text
    lines = _wrapped_lines(draw, headline, bold, width - 150)
    if len(lines) > 4:
        bold = _font(style["font_bold"], 68, bold=True)
        lines = _wrapped_lines(draw, headline, bold, width - 150)
    _draw_multiline_center(
        draw,
        lines,
        center_y=790,
        font=bold,
        fill=primary,
        width=width,
        spacing=18,
        stroke_width=3,
        stroke_fill=(2, 8, 16, 210),
    )

    # Burned-in subtitles preserve comprehension when audio is muted.
    subtitle_lines = _wrapped_lines(draw, segment.voiceover, regular, width - 180)
    subtitle_height = len(subtitle_lines) * 58 + 55
    subtitle_top = 1220 - subtitle_height // 2
    draw.rounded_rectangle(
        (62, subtitle_top - 24, width - 62, subtitle_top + subtitle_height),
        radius=32,
        fill=(4, 13, 26, 212),
        outline=(255, 255, 255, 32),
        width=2,
    )
    y = subtitle_top
    for line in subtitle_lines:
        bbox = draw.textbbox((0, 0), line, font=regular)
        draw.text(((width - (bbox[2] - bbox[0])) // 2, y), line, font=regular, fill=primary)
        y += 58

    source = f"SOURCE  •  {article.source_name.upper()}"
    source_lines = _wrapped_lines(draw, source, small, width - 180)
    _draw_multiline_center(draw, source_lines, 1570, small, accent, width, 10)
    draw.text((68, height - 165), "READ THE SOURCE IN THE CAPTION", font=small, fill=(235, 243, 250, 220))
    draw.text((width - 145, height - 170), f"{segment_index + 1:02d}", font=brand, fill=accent_secondary)

    image = Image.alpha_composite(image, overlay).convert("RGB")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, quality=94)


def _ffprobe(path: Path) -> dict:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def _audio_duration(path: Path) -> float:
    data = _ffprobe(path)
    return float(data["format"]["duration"])


def create_voiceover(script: ScriptPayload, ai: GeminiClient, output: Path) -> str:
    text_file = output.with_suffix(".txt")
    text_file.write_text(script.narration, encoding="utf-8")
    if ai.available:
        try:
            ai.text_to_speech(script.narration, output)
            return "gemini"
        except Exception:
            pass
    # Fully offline, zero-cost fallback. It is less natural but keeps the pipeline functional.
    if not shutil.which("ffmpeg"):
        raise RenderError("ffmpeg is required for the fallback voice")
    filter_value = f"flite=textfile={text_file.resolve()}:voice=slt"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", filter_value, "-ar", "24000", str(output)])
    return "ffmpeg-flite"


def _slide_durations(script: ScriptPayload, audio_duration: float) -> list[float]:
    word_counts = [max(1, len(segment.voiceover.split())) for segment in script.segments]
    usable = max(audio_duration + 1.2, 4.2 * len(word_counts))
    raw = [usable * count / sum(word_counts) for count in word_counts]
    durations = [max(3.7, value) for value in raw]
    scale = usable / sum(durations)
    if scale < 1:
        durations = [value * scale for value in durations]
    return [round(value, 3) for value in durations]


def render_reel(
    *,
    script: ScriptPayload,
    article: Article,
    assets: list[VisualAsset],
    ai: GeminiClient,
    config: AppConfig,
    work_dir: Path,
    output: Path,
    cover: Path,
) -> dict[str, object]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("ffmpeg and ffprobe are required")
    work_dir.mkdir(parents=True, exist_ok=True)
    slides_dir = work_dir / "slides"
    clips_dir = work_dir / "clips"
    slides_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    slide_paths: list[Path] = []
    for index, _segment in enumerate(script.segments):
        slide = slides_dir / f"slide-{index + 1:02d}.jpg"
        render_slide(
            asset=assets[index % len(assets)],
            script=script,
            article=article,
            segment_index=index,
            config=config,
            output=slide,
        )
        slide_paths.append(slide)
    cover.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(slide_paths[0], cover)

    voice = work_dir / "voice.wav"
    voice_provider = create_voiceover(script, ai, voice)
    durations = _slide_durations(script, _audio_duration(voice))
    fps = int(config.style["fps"])
    width, height = int(config.style["width"]), int(config.style["height"])
    clip_paths: list[Path] = []
    for index, (slide, duration) in enumerate(zip(slide_paths, durations)):
        clip = clips_dir / f"clip-{index + 1:02d}.mp4"
        frames = max(1, math.ceil(duration * fps))
        zoom_direction = 1 if index % 2 == 0 else -1
        if zoom_direction > 0:
            zoom = "min(max(pzoom,1.0)+0.00018,1.055)"
        else:
            zoom = "if(lte(on,1),1.055,max(1.0,pzoom-0.00018))"
        video_filter = (
            f"scale={width}:{height},"
            f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
        )
        run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-loop",
                "1",
                "-i",
                str(slide),
                "-vf",
                video_filter,
                "-t",
                str(duration),
                "-r",
                str(fps),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "24",
                str(clip),
            ]
        )
        clip_paths.append(clip)

    concat_file = work_dir / "clips.txt"
    concat_file.write_text("".join(f"file '{path.resolve()}'\n" for path in clip_paths), encoding="utf-8")
    silent_video = work_dir / "silent.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(silent_video),
        ]
    )

    total_duration = sum(durations)
    filter_complex = (
        f"[1:a]volume=1.0,apad=pad_dur=2[voice];"
        f"sine=frequency=98:sample_rate=48000:duration={total_duration},volume=0.012[m1];"
        f"sine=frequency=147:sample_rate=48000:duration={total_duration},volume=0.006[m2];"
        "[m1][m2]amix=inputs=2:normalize=0[music];"
        "[voice][music]amix=inputs=2:duration=longest:normalize=0[a]"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(silent_video),
            "-i",
            str(voice),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-t",
            f"{total_duration:.3f}",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    validation = validate_reel(output, width=width, height=height)
    validation["voice_provider"] = voice_provider
    validation["slide_durations"] = durations
    return validation


def validate_reel(path: Path, *, width: int = 1080, height: int = 1920) -> dict[str, object]:
    data = _ffprobe(path)
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise RenderError("Reel must contain both video and audio")
    actual_width, actual_height = int(video["width"]), int(video["height"])
    duration = float(data["format"]["duration"])
    if (actual_width, actual_height) != (width, height):
        raise RenderError(f"Unexpected resolution {actual_width}x{actual_height}")
    if not 3 <= duration <= 90:
        raise RenderError(f"Duration {duration:.2f}s is outside the configured Reel safety range")
    return {
        "status": "passed",
        "duration_seconds": round(duration, 3),
        "width": actual_width,
        "height": actual_height,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "size_bytes": path.stat().st_size,
    }
