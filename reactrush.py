# REACTION SHORTS FACTORY - GOOGLE DRIVE + YOUTUBE + GITHUB ACTIONS
# Final logic:
# Google Drive clip 1 + watching + reaction 1
# Google Drive clip 2 + watching + reaction 2
# ...
# All segments are merged into ONE final 9:16 Short.

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


# ============================================================
# PROJECT SETTINGS
# ============================================================

CHANNEL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CHANNEL_DIR

DOWNLOADS_DIR = CHANNEL_DIR / "downloads"
OUTPUT_DIR = CHANNEL_DIR / "output"
DATA_DIR = CHANNEL_DIR / "data"
REACTIONS_DIR = CHANNEL_DIR / "reactions"
TEMP_DIR = DATA_DIR / "temp_segments"

# Number of FINAL Shorts per run.
VIDEOS_PER_RUN = 1

# Google Drive source clip duration.
# Long clips are allowed, but clips over this duration are skipped.
MIN_SOURCE_DURATION = 3
MAX_SOURCE_DURATION = 70

# Final Short target duration.
FINAL_MIN_DURATION = 50
FINAL_MAX_DURATION = 60

# The source clip is played 10% faster.
SPEED = 1.10

# 9:16 YouTube Shorts.
OUT_W = 1080
OUT_H = 1920

# Watching area at the top.
WATCH_HEIGHT = 480

# Google Drive OAuth files.
# Local: uses the API folder you prepared.
# GitHub Actions: set DRIVE_TOKEN_FILE to the runtime secret file path.
DRIVE_API_DIR = Path(
    os.getenv(
        "DRIVE_API_DIR",
        r"C:\Users\0boru\Desktop\YouTube_Automation\channels\reactrush\api جوجل درايف قناه الرياكتيد",
    )
)
DRIVE_TOKEN_FILE = Path(
    os.getenv("DRIVE_TOKEN_FILE", str(DRIVE_API_DIR / "token.json"))
)
DRIVE_CREDENTIALS_FILE = Path(
    os.getenv("DRIVE_CREDENTIALS_FILE", str(DRIVE_API_DIR / "credentials.json"))
)
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

# ============================================================
# GOOGLE DRIVE SOURCE CATEGORIES
# ============================================================

CONTENT_CATEGORIES = {
    "funny": {
        "reaction": "hysterical_laugh",
        "youtube_hashtags": "#shorts #funny #comedy #reaction",
    },
    "scary": {
        "reaction": "scared",
        "youtube_hashtags": "#shorts #scary #horror #reaction",
    },
    "weird": {
        "reaction": "confused",
        "youtube_hashtags": "#shorts #weird #unexpected #reaction",
    },
}

CATEGORY_NAMES_AR = {
    "funny": "الضحك والكوميديا",
    "scary": "الرعب والخضة",
    "weird": "الغريب وغير المتوقع",
}

# ============================================================
# YOUTUBE TITLES
# ============================================================

TITLE_BANKS = {
    "funny": [
        "You Had ONE Job 😂",
        "This Went Completely Wrong 😂",
        "I Was Not Ready For This 😂",
        "That Ending Got Me 😂",
        "You Cannot Make This Up 😂",
        "The Funniest Fail Ever? 😂",
        "Watch What Happens Next 😂",
        "This Is Actually Hilarious 😂",
    ],
    "scary": [
        "This Took a DARK Turn 😳",
        "I Would Have RUN 😳",
        "That Jump Scare Was Brutal 😱",
        "Do NOT Watch This Alone 😳",
        "Something Was Seriously Wrong 😨",
        "That Ending Was Terrifying 😱",
        "I Did Not See That Coming 😳",
        "This Got Creepy FAST 😨",
    ],
    "weird": [
        "What Did I Just Watch?! 😳",
        "This Makes Absolutely No Sense 😂",
        "Nobody Expected That 😳",
        "What Happened at the End?! 😳",
        "I Have So Many Questions 😂",
        "This Is the Weirdest Thing Ever 😳",
        "You Need to See This 😳",
        "That Was Unexpected 😳",
    ],
}

# ============================================================
# GOOGLE DRIVE
# ============================================================


def get_drive_service():
    """Authenticate to the permanent Google Drive account and return the API client."""
    if not DRIVE_TOKEN_FILE.exists():
        raise FileNotFoundError(
            f"Google Drive token not found: {DRIVE_TOKEN_FILE}"
        )

    credentials = Credentials.from_authorized_user_file(
        str(DRIVE_TOKEN_FILE),
        DRIVE_SCOPES,
    )

    if credentials.expired and credentials.refresh_token:
        print("🔄 Google Drive access token expired — refreshing...")
        credentials.refresh(Request())
        DRIVE_TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )
        print("✅ Google Drive token refreshed and saved.")

    if not credentials.valid:
        raise RuntimeError(
            "Google Drive OAuth token is invalid and cannot be refreshed. "
            f"Create a new token with {DRIVE_CREDENTIALS_FILE}."
        )

    granted_scopes = set(credentials.scopes or [])
    missing_scopes = set(DRIVE_SCOPES) - granted_scopes
    if missing_scopes:
        raise RuntimeError(
            "Google Drive token is missing required scopes: "
            + ", ".join(sorted(missing_scopes))
        )

    return build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def drive_folder_id(service, folder_name):
    """Find the first non-trashed folder with the exact name in My Drive."""
    response = service.files().list(
        q=(
            "trashed = false "
            "and mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{folder_name}'"
        ),
        spaces="drive",
        fields="files(id,name,parents)",
        pageSize=100,
    ).execute()

    folders = response.get("files", [])
    if not folders:
        raise FileNotFoundError(
            f"لم يتم العثور على فولدر Google Drive: {folder_name}"
        )

    return folders[0]["id"]


def drive_video_files(service, folder_id):
    """Return all video files in one Drive folder, across all pages."""
    files = []
    page_token = None

    while True:
        response = service.files().list(
            q=(
                f"'{folder_id}' in parents "
                "and trashed = false "
                "and mimeType contains 'video/'"
            ),
            spaces="drive",
            fields="nextPageToken,files(id,name,mimeType,size)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()

        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def download_drive_video(service, file_info, folder):
    """Download one Drive video into the local temporary downloads folder."""
    folder.mkdir(parents=True, exist_ok=True)

    safe_name = clean_filename(file_info.get("name") or "drive_video")
    output_path = folder / safe_name

    if output_path.exists():
        stem = output_path.stem
        suffix = output_path.suffix
        output_path = folder / f"{stem}_{file_info['id']}{suffix}"

    request = service.files().get_media(fileId=file_info["id"])

    with output_path.open("wb") as file_handle:
        downloader = MediaIoBaseDownload(
            file_handle,
            request,
            chunksize=8 * 1024 * 1024,
        )
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(
                    f"📥 Drive download: "
                    f"{status.progress() * 100:.1f}% - {file_info['name']}"
                )

    return output_path


def delete_drive_video(service, file_id, file_name=""):
    """Delete a source video from Drive after the YouTube upload succeeds."""
    service.files().delete(
        fileId=file_id,
    ).execute()
    print(f"🗑️ تم حذف الفيديو المستخدم من Google Drive: {file_name or file_id}")


# ============================================================
# REACTION KEYWORDS
# ============================================================

REACTIONS = {
    "disapproval": [
        "rude", "bad behavior", "annoying", "stupid",
        "wrong", "mean", "cringe"
    ],
    "disappointment": [
        "fail", "failure", "failed", "instant regret",
        "bad ending", "disappointing"
    ],
    "amazed": [
        "amazing", "amazed", "incredible", "impressive",
        "wow", "talent", "satisfying", "perfect"
    ],
    "disgusted": [
        "disgusting", "gross", "dirty", "nasty",
        "rotten", "eww"
    ],
    "shocked": [
        "shocking", "unexpected", "unbelievable",
        "surprise", "plot twist", "crazy"
    ],
    "scared": [
        "scary", "scared", "horror", "jump scare",
        "frightening", "creepy", "ghost"
    ],
    "hysterical_laugh": [
        "funny", "hilarious", "comedy", "laugh",
        "laughing", "joke", "funniest", "meme"
    ],
    "confused": [
        "confusing", "confused", "weird", "strange",
        "wtf", "random", "bizarre"
    ],
}

REACTION_AR = {
    "disapproval": "الاستنكار",
    "disappointment": "خيبة الأمل",
    "amazed": "الإعجاب والانبهار",
    "disgusted": "القرف والاشمئزاز",
    "shocked": "الصدمة والتفاجؤ",
    "scared": "الرعب أو الخضة",
    "hysterical_laugh": "الضحك الهيستيري",
    "confused": "الحيرة وعدم الفهم",
}

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


# ============================================================
# BASIC SETUP
# ============================================================

def setup():
    for folder in [
        DOWNLOADS_DIR,
        OUTPUT_DIR,
        DATA_DIR,
        REACTIONS_DIR,
        TEMP_DIR,
    ]:
        folder.mkdir(parents=True, exist_ok=True)

    for name in list(REACTIONS) + ["watching"]:
        (REACTIONS_DIR / name).mkdir(parents=True, exist_ok=True)



def ffmpeg_path():
    candidates = [
        PROJECT_DIR / "tools" / "ffmpeg" / "ffmpeg.exe",
        PROJECT_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        PROJECT_DIR / "tools" / "ffmpeg.exe",
    ]

    for path in candidates:
        if path.exists():
            return str(path)

    return shutil.which("ffmpeg")


def ffprobe_path(ffmpeg):
    ffmpeg_p = Path(ffmpeg)

    if ffmpeg_p.name.lower() == "ffmpeg.exe":
        candidate = ffmpeg_p.with_name("ffprobe.exe")
        if candidate.exists():
            return str(candidate)

    return shutil.which("ffprobe")


# ============================================================
# GOOGLE DRIVE
# ============================================================

# ============================================================
# MEDIA PROBE
# ============================================================

def probe_media(path, ffprobe):
    try:
        command = [
            ffprobe,
            "-v", "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of", "json",
            str(path),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=True,
        )

        data = json.loads(result.stdout)

        duration = float(
            data.get("format", {}).get("duration", 0)
        )

        streams = data.get("streams", [])

        has_audio = any(
            stream.get("codec_type") == "audio"
            for stream in streams
        )

        return duration, has_audio

    except Exception:
        return 0.0, False


# ============================================================
# REACTION FILES
# ============================================================

def reaction_file(name):
    files = []

    for pattern in (
        "*.mp4",
        "*.mov",
        "*.mkv",
        "*.webm",
    ):
        files.extend(
            (REACTIONS_DIR / name).glob(pattern)
        )

    if not files:
        raise FileNotFoundError(
            f"لا يوجد فيديو داخل: {REACTIONS_DIR / name}"
        )

    return random.choice(files)


# ============================================================
# FILE NAME
# ============================================================

def clean_filename(value):
    value = re.sub(
        r'[\\/:*?"<>|]+',
        "_",
        str(value),
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return value[:55] or "ReactRush_Reaction_Short"


# ============================================================
# CREATE ONE SEGMENT
# ============================================================

def create_segment(
    source_video,
    reaction_name,
    segment_output,
    ffmpeg,
    ffprobe,
    reaction_duration,
):
    watching = reaction_file("watching")
    ending = reaction_file(reaction_name)

    source_duration, has_audio = probe_media(source_video, ffprobe)

    if source_duration <= 0:
        raise RuntimeError("تعذر قراءة مدة الفيديو.")

    if not (MIN_SOURCE_DURATION <= source_duration <= MAX_SOURCE_DURATION):
        raise RuntimeError(
            f"مدة الفيديو غير مناسبة: {source_duration:.2f} ثانية"
        )

    main_duration = source_duration / SPEED
    total_audio_duration = main_duration + reaction_duration

    # Video:
    # [watching + source clip] then [full-screen reaction]
    # Audio:
    # Source audio (or silence) then silence for the reaction duration.
    # This is the important fix: the reaction is never cut by -shortest.
    video_filters = (
        f"[0:v]"
        f"crop=720:620:0:0,"
        f"scale={OUT_W}:{WATCH_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{WATCH_HEIGHT},"
        f"setsar=1,"
        f"fps=30,"
        f"trim=duration={main_duration:.3f},"
        f"setpts=PTS-STARTPTS"
        f"[watch];"

        f"[1:v]"
        f"setpts=PTS/{SPEED},"
        f"scale={OUT_W}:{OUT_H - WATCH_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H - WATCH_HEIGHT},"
        f"setsar=1,"
        f"fps=30,"
        f"setpts=PTS-STARTPTS"
        f"[main];"

        f"[watch][main]"
        f"vstack=inputs=2:shortest=1,"
        f"fps=30,"
        f"setpts=PTS-STARTPTS"
        f"[body];"

        f"[2:v]"
        f"trim=duration={reaction_duration:.3f},"
        f"scale={OUT_W}:{OUT_H}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},"
        f"setsar=1,"
        f"fps=30,"
        f"setpts=PTS-STARTPTS"
        f"[reaction];"

        f"[body][reaction]"
        f"concat=n=2:v=1:a=0,"
        f"fps=30,"
        f"format=yuv420p"
        f"[v]"
    )

    if has_audio:
        audio_filters = (
            f"[1:a]"
            f"atempo={SPEED},"
            f"atrim=duration={main_duration:.3f},"
            f"asetpts=PTS-STARTPTS"
            f"[main_audio];"
            f"anullsrc=r=44100:cl=stereo,"
            f"atrim=duration={reaction_duration:.3f},"
            f"asetpts=PTS-STARTPTS"
            f"[reaction_silence];"
            f"[main_audio][reaction_silence]"
            f"concat=n=2:v=0:a=1"
            f"[a]"
        )
    else:
        audio_filters = (
            f"anullsrc=r=44100:cl=stereo,"
            f"atrim=duration={total_audio_duration:.3f},"
            f"asetpts=PTS-STARTPTS"
            f"[a]"
        )

    filter_complex = video_filters + ";" + audio_filters

    command = [
        ffmpeg,
        "-y",
        "-stream_loop", "-1",
        "-i", str(watching),
        "-i", str(source_video),
        "-i", str(ending),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(segment_output),
    ]

    subprocess.run(command, check=True)


# ============================================================
# CONCAT SEGMENTS INTO ONE FINAL SHORT
# ============================================================

def concat_segments(
    segment_files,
    output_file,
    ffmpeg,
):
    if not segment_files:
        raise RuntimeError(
            "لا توجد أجزاء لدمجها."
        )

    concat_file = (
        TEMP_DIR
        / "concat_list.txt"
    )

    with concat_file.open(
        "w",
        encoding="utf-8"
    ) as file:
        for segment in segment_files:
            # ffmpeg concat format on Windows.
            path = segment.resolve().as_posix()
            file.write(
                f"file '{path}'\n"
            )

    command = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_file),
    ]

    subprocess.run(
        command,
        check=True,
    )

    # HARD FINAL GUARD:
    # Re-encode and trim the merged file to exactly <= 60 seconds.
    # This prevents timestamp/timebase problems from making concat output longer.
    trimmed = output_file.with_name(output_file.stem + "_trimmed.mp4")

    trim_command = [
        ffmpeg,
        "-y",
        "-i",
        str(output_file),
        "-t",
        str(FINAL_MAX_DURATION),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(trimmed),
    ]

    subprocess.run(trim_command, check=True)

    output_file.unlink(missing_ok=True)
    trimmed.replace(output_file)


# ============================================================
# BUILD ONE FINAL SHORT
# ============================================================

def build_final_short(drive, output_file, ffmpeg, ffprobe):
    category_name = random.choice(list(CONTENT_CATEGORIES))
    category = CONTENT_CATEGORIES[category_name]

    print(
        "\n🎯 الفئة المختارة: "
        f"{CATEGORY_NAMES_AR[category_name]}"
    )
    print(
        "🎯 كل فيديوهات الـShort ستكون من نفس الفئة "
        f"({category_name})"
    )

    folder_id = drive_folder_id(drive, category_name)
    available = drive_video_files(drive, folder_id)

    if not available:
        raise RuntimeError(
            f"لا توجد فيديوهات داخل فولدر Google Drive: {category_name}"
        )

    random.shuffle(available)

    segments = []
    accepted = []
    total_duration = 0.0

    for item in available:
        if total_duration >= FINAL_MIN_DURATION:
            break

        print("\n" + "-" * 65)
        print(f"📥 Google Drive: {item['name']}")
        print(
            f"🆔 {item['id']} | "
            f"🎭 {category['reaction']} | "
            f"📌 {category_name}"
        )

        clip_dir = DOWNLOADS_DIR / f"drive_{item['id']}"
        source = None

        try:
            source = download_drive_video(drive, item, clip_dir)
            source_duration, _ = probe_media(source, ffprobe)

            if not (
                MIN_SOURCE_DURATION
                <= source_duration
                <= MAX_SOURCE_DURATION
            ):
                print(
                    f"⏭️ مدة غير مناسبة: "
                    f"{source_duration:.2f} ثانية"
                )
                continue

            rp = reaction_file(category["reaction"])
            reaction_duration, _ = probe_media(rp, ffprobe)

            if reaction_duration <= 0:
                continue

            estimated = (
                source_duration / SPEED
                + reaction_duration
            )

            if total_duration + estimated > FINAL_MAX_DURATION:
                print(
                    "⏭️ تخطيه لأنه سيجعل الشورت أطول "
                    "من 60 ثانية"
                )
                continue

            seg = TEMP_DIR / (
                f"segment_{len(segments) + 1:02d}.mp4"
            )

            print("🎬 إنشاء الجزء...")

            create_segment(
                source,
                category["reaction"],
                seg,
                ffmpeg,
                ffprobe,
                reaction_duration,
            )

            actual, _ = probe_media(seg, ffprobe)

            if actual <= 0:
                seg.unlink(missing_ok=True)
                continue

            if total_duration + actual > FINAL_MAX_DURATION:
                print(
                    f"⏭️ تخطي الجزء: الإجمالي سيصبح "
                    f"{total_duration + actual:.2f} ثانية"
                )
                seg.unlink(missing_ok=True)
                continue

            segments.append(seg)
            accepted.append({
                "file_id": item["id"],
                "title": item.get("name") or "",
                "name": item.get("name") or "",
                "reaction": category["reaction"],
                "category": category_name,
            })
            total_duration += actual

            print(
                f"✅ المدة الحالية: "
                f"{total_duration:.2f} ثانية"
            )

        except Exception as error:
            print(
                f"❌ خطأ في فيديو Drive {item.get('name', '')}: "
                f"{type(error).__name__}: {error}"
            )

    if not segments:
        raise RuntimeError("لم يتم إنشاء أي جزء صالح من فيديوهات Google Drive")

    print(f"\n🔗 دمج {len(segments)} أجزاء...")

    concat_segments(
        segments,
        output_file,
        ffmpeg,
    )

    final_duration, _ = probe_media(
        output_file,
        ffprobe,
    )

    if final_duration > FINAL_MAX_DURATION + 0.05:
        raise RuntimeError(
            f"الملف النهائي تعدى الحد الأقصى: "
            f"{final_duration:.2f} ثانية"
        )

    return final_duration, accepted, category_name


def cleanup_used_drive_videos(drive, accepted):
    """Delete every Drive source that actually made it into the final Short."""
    deleted = 0
    for item in accepted:
        try:
            delete_drive_video(
                drive,
                item["file_id"],
                item.get("name", ""),
            )
            deleted += 1
        except Exception as error:
            print(
                f"⚠️ فشل حذف فيديو Drive {item.get('name', '')}: "
                f"{type(error).__name__}: {error}"
            )

    print(f"🗑️ تم حذف {deleted}/{len(accepted)} فيديو مصدر من Drive.")


# ============================================================
# YOUTUBE UPLOAD - REACTRUSH
# ============================================================

YOUTUBE_TOKEN_FILE = Path(
    os.getenv("YOUTUBE_TOKEN_FILE", str(CHANNEL_DIR / "token.json"))
)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]



def get_youtube_service():
    if not YOUTUBE_TOKEN_FILE.exists():
        raise FileNotFoundError(
            f"YouTube token not found: {YOUTUBE_TOKEN_FILE}"
        )

    credentials = Credentials.from_authorized_user_file(
        str(YOUTUBE_TOKEN_FILE),
        YOUTUBE_SCOPES,
    )

    # Access tokens expire. If the saved OAuth token contains a
    # refresh token, refresh it automatically instead of forcing
    # the user to log in again.
    if credentials.expired and credentials.refresh_token:
        print("🔄 YouTube access token expired — refreshing...")
        credentials.refresh(Request())
        YOUTUBE_TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )
        print("✅ YouTube token refreshed and saved.")

    if not credentials.valid:
        raise RuntimeError(
            "YouTube OAuth token is invalid and cannot be refreshed. "
            "Run login_channel.py for ReactRush again."
        )

    granted_scopes = set(credentials.scopes or [])
    missing_scopes = set(YOUTUBE_SCOPES) - granted_scopes
    if missing_scopes:
        raise RuntimeError(
            "YouTube token is missing required scopes: "
            + ", ".join(sorted(missing_scopes))
        )

    return build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def upload_to_youtube(video_file, accepted, category_name):
    print("\n📤 رفع الـShort إلى قناة ReactRush...")

    youtube = get_youtube_service()

    # Drive filenames are usually technical names/IDs, so never use them
    # as the public YouTube title. Pick a clean English title per category.
    youtube_title = random.choice(TITLE_BANKS[category_name])

    category_hashtags = CONTENT_CATEGORIES[category_name][
        "youtube_hashtags"
    ]

    description_parts = [
        "ReactRush reaction short.",
        f"Category: {category_name}",
        "",
        category_hashtags,
    ]

    youtube_description = "\n".join(description_parts)

    body = {
        "snippet": {
            "title": youtube_title,
            "description": youtube_description[:5000],
            "tags": [
                "shorts",
                category_name,
                "reaction",
                "ReactRush",
            ],
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    print(f"📝 YouTube title: {youtube_title}")
    print(f"📌 Category: {category_name}")

    media = MediaFileUpload(
        str(video_file),
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None

    while response is None:
        status, response = request.next_chunk()

        if status:
            print(
                f"📤 Upload: "
                f"{status.progress() * 100:.1f}%"
            )

    video_id = response.get("id")

    if not video_id:
        raise RuntimeError(
            "YouTube did not return a video ID."
        )

    url = f"https://www.youtube.com/shorts/{video_id}"

    print("✅ تم رفع الفيديو بنجاح.")
    print(f"🎬 Video ID: {video_id}")
    print(f"🔗 {url}")

    return video_id, url


# ============================================================
# MAIN
# ============================================================

async def main():
    setup()

    ffmpeg = ffmpeg_path()

    print(
        "\n"
        + "=" * 70
        + "\nREACTION SHORTS FACTORY - GOOGLE DRIVE MULTI CLIP\n"
        + "=" * 70
    )

    if not ffmpeg:
        print("❌ لم يتم العثور على FFmpeg")
        return 1

    ffprobe = ffprobe_path(ffmpeg)

    if not ffprobe:
        print("❌ لم يتم العثور على FFprobe")
        return 1

    print(f"FFmpeg: {ffmpeg}")
    print(f"FFprobe: {ffprobe}")

    # Check all reaction folders.
    try:
        reaction_file("watching")

        for reaction in REACTIONS:
            reaction_file(reaction)

    except Exception as error:
        print("❌", error)
        return 1

    # Clean old temporary segment files.
    for old_file in TEMP_DIR.glob("segment_*.mp4"):
        try:
            old_file.unlink()
        except Exception:
            pass

    print("\n☁️ بدء Google Drive...")
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("🤖 التشغيل عبر GitHub Actions")
    else:
        print("💻 التشغيل المحلي")
    success = 0

    try:
        drive = get_drive_service()
        print("✅ Google Drive session started")
    except Exception as error:
        print(
            f"❌ Google Drive failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    for number in range(1, VIDEOS_PER_RUN + 1):
        output_file = OUTPUT_DIR / f"reactrush_{number:02d}_reaction_short.mp4"

        try:
            final_duration, accepted, category_name = build_final_short(
                drive,
                output_file,
                ffmpeg,
                ffprobe,
            )

            print("\n" + "=" * 70)
            print(f"✅ تم إنشاء Short {number}/{VIDEOS_PER_RUN}")
            print(f"🎞️ عدد الفيديوهات المستخدمة: {len(accepted)}")
            print(f"⏱️ الطول النهائي: {final_duration:.2f} ثانية")
            print(f"📁 {output_file}")

            try:
                upload_to_youtube(
                    output_file,
                    accepted,
                    category_name,
                )

                # Delete source videos only AFTER YouTube confirms the upload.
                cleanup_used_drive_videos(drive, accepted)
                success += 1

            except Exception as upload_error:
                print(
                    f"❌ فشل رفع الفيديو إلى YouTube: "
                    f"{type(upload_error).__name__}: "
                    f"{upload_error}"
                )
                print("⚠️ لن يتم حذف فيديوهات المصدر من Drive لأن الرفع فشل.")

            print("=" * 70)

        except Exception as error:
            print(
                f"❌ فشل إنشاء الفيديو النهائي: "
                f"{type(error).__name__}: {error}"
            )

    print(
        f"\nتم الانتهاء: "
        f"{success}/{VIDEOS_PER_RUN}"
    )

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(main())
    )
