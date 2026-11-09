# Trade Autopsy Video Studio — render backend

This repository is the free render backend for the online studio:

https://trade-autopsy-video.dgchh0718.workers.dev/studio/

A Cloudflare Worker dispatches the `Render` workflow. GitHub Actions runs the
Python/Skia/FFmpeg pipeline and publishes MP4/SRT/poster to a GitHub Release.
The site then shows the result and download links.

No secrets are stored in the repository. The Worker keeps its GitHub token as
an encrypted Cloudflare secret.
