# Optical Audio to Digital WAV
Optical audio on film has been a critical part of the presentation of motion pictures since the 1920s when variable-area/variable-density was first introduced.
Converting scans of film can be difficult, and extracting audio moreso. There has been a very good tool for the past decade, [AEO-Light](https://github.com/usc-imi/aeo-light), that is popular 
to use to convert the audio. However, the codebase is in C++, and it is difficult to understand how it works, and to add new features to. As a result, this project is to create a modern 
Optical to Digital conversion tool, written in python, that can convert optical audio of all shapes and sizes (possibly other formats too like Dolby-Digital or SDDS) and Dolby A/SR easily and effectivly.
Also, another important goal is that anyone can understand how the audio conversions work and can extend the functionality into their own projects too.

![Cover Image](cover.png)

## Useful Links
* Sound-on-film https://en.wikipedia.org/wiki/Sound-on-film
* Dolby Stereo https://en.wikipedia.org/wiki/Dolby_Stereo
* Dolby SR https://en.wikipedia.org/wiki/Dolby_SR
* Dolby Digital https://en.wikipedia.org/wiki/Dolby_Digital

# Progress
A basic web-based application now exists that converts individual images that contain Optical Audio to a .wav that is subsequently downloaded. More features are being added. Also, the `KylesOpticalDecoder.py` can be used standalone in CLI, allowing for other programs/scripting to run it in a pipeline.

## Kyle's Optical Decoder
Python CLI tool that can extract film optical audio

### Prerequisites
- Python 3.10+
- Node.js 18+
- ffmpeg (must be on your `PATH`) — required for the Export Video feature (muxing/rendering); install via `brew install ffmpeg` (macOS), your Linux package manager, or from [ffmpeg.org](https://ffmpeg.org/) (Windows). Not required for WAV-only extraction.

## Download the app (macOS)

Grab the latest `Optical2Digital.dmg` from the [Releases page](../../releases), open it, and drag `Optical2Digital.app` to Applications.

**First launch only:** because this build isn't code-signed, macOS will refuse a plain double-click with an "unidentified developer" warning. Instead, right-click (or Control-click) `Optical2Digital.app` and choose **Open**, then confirm in the dialog that appears. After that first launch, it opens normally.

No Python, Node, or ffmpeg install needed — everything required is bundled inside the app.

### Setup (normal local)

First time: `start-dev-fresh.sh`
Afterwards: `start-dev.sh`

### Setup (development)

**Backend (Python):**
```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows

pip install opencv-python numpy natsort scipy fastapi uvicorn pydantic pywebview pyinstaller
```

**Frontend (React):**
```bash
cd frontend
npm install
```

### Running

Start the backend server:
```bash
python server.py
```

Start the frontend dev server (in a separate terminal):
```bash
cd frontend
npm run dev
```

Then open http://localhost:5173 in your browser.

### CLI Usage

`KylesOpticalDecoder.py` can also be used standalone from the command line:
```bash
python KylesOpticalDecoder.py --help
```

## Theory of Operation
TODO

## License
This project is licensed under the GNU General Public License v3.0.
See [LICENSE](LICENSE) for the full text.

### Contributors
* Kyle Mikolajczyk
* Will Dirkschka
* Ben Peters
* Thomas Piccicone (35mm Scan Examples)