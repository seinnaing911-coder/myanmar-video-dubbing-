# TODO

## Upload console accepts the required inputs

- The home page provides an MP4 video upload control with clear file selection, filename display, and format validation.
- The home page provides a Burmese SRT subtitle upload control with clear file selection, filename display, and format validation.
- The processing action remains unavailable until both valid files are selected.

## Provided Burmese dubbing pipeline is connected

- Starting processing sends the selected MP4 and SRT files to the server.
- The server invokes the provided Python pipeline as the core dubbing logic.
- The pipeline uses the fixed Edge TTS voice `my-MM-ThihaNeural` and writes the generated video as `final_output.mp4`.
- Processing errors return a useful message and do not claim that a file was created.

## Progress and completion states are visible

- The setup summary shows the selected inputs and the fixed Burmese voice before starting.
- The interface shows subtitle parsing, Burmese speech generation, clip cutting/timing adjustment, audio replacement, concatenation, and final export as visible processing stages.
- The completion view exposes a direct download action for the generated MP4.
- The mobile and desktop layouts remain usable at narrow viewport widths.

## Product presentation is polished and focused

- The landing page explains the three-step workflow, uses Burmese-first copy, and keeps the scope focused on video dubbing.
- The visual system uses the approved dark waveform editorial direction with a cyan signal accent and restrained motion.
- The route manifest is served at `/manus-routes.json` for the complete page route set.
