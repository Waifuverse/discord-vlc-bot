Put show folders here, or set `MEDIA_ROOT` in your private `.env` to an existing folder.

```text
media/
  Example Show/
    Episode_01_Subbed.mp4
    Episode_02_Subbed.mp4
    Episode_02_Dubbed.mp4
```

Video files are not included in the repository. The first subfolder becomes the show name. Numeric sorting puts episode 2 before episode 10. Filenames containing Subbed or Dubbed create separate version groups; other videos appear as Unlabelled.

Supported video extensions: `.mp4`, `.mkv`, `.avi`, `.webm`, `.mov`, `.m4v`, `.ts` and `.m2ts`. Files directly inside the media root appear under **Videos**. Nested folders remain part of their first-level show. Subtitles and other non-video files are not playlist entries.
