# ReactRush

Google Drive → FFmpeg montage → YouTube Shorts, designed to run locally and through GitHub Actions.

## Folder layout

- `reactrush.py` — main program
- `reactions/` — the 9 small reaction clips (`watching` + 8 reaction types)
- `requirements.txt` — Python dependencies
- `.github/workflows/reactrush.yml` — manual + 3-times-per-day GitHub Actions run

## Local run

The script keeps the local fallback path you already configured for the Google Drive OAuth token:

`C:\Users\0boru\Desktop\YouTube_Automation\channels\reactrush\api جوجل درايف قناه الرياكتيد`

The YouTube OAuth token defaults to `token.json` beside `reactrush.py`.

## GitHub Actions secrets

Create these two repository secrets:

- `DRIVE_TOKEN_JSON` — the complete Google Drive `token.json` for the permanent Drive account
- `YOUTUBE_TOKEN_JSON` — the complete ReactRush YouTube `token.json`

The workflow writes those secrets to temporary files during the run and deletes the temporary folder afterward. Never commit either token or `credentials.json` to the repository.

## Reaction clips

Put the 9 reaction videos in these folders (one or more files per folder is fine):

`reactions/watching/`
`reactions/disapproval/`
`reactions/disappointment/`
`reactions/amazed/`
`reactions/disgusted/`
`reactions/shocked/`
`reactions/scared/`
`reactions/hysterical_laugh/`
`reactions/confused/`

## Drive behavior

The program randomly chooses a video from `funny`, `scary`, or `weird`, builds the Short, and deletes only the source videos that were actually used **after** YouTube confirms a successful upload.

## YouTube titles

Drive filenames are not used as YouTube titles. The program chooses a clean English title from a category-specific title bank.
